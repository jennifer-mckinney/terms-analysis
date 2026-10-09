#!/usr/bin/env python3
"""Submit job of the weekly wiring audit (card #224, ADR 0002).

Order of operations, each step failing closed with its own exit code:

1. config (CONFIG), the dedicated key (MISSING_SECRET), the price table's
   ``price_review_by`` date (PRICES_STALE), the inventory (NO_MODULES);
2. one request per module plus the canary, built from config; every payload,
   the canary included, goes through ``leak_scan.py`` BEFORE any request.
   Pass = exit 1 with exactly one ``CLEAN <n>`` line on stdout and nothing on
   stderr (LEAK, LEAK_SCAN_ERROR);
3. ``count_tokens`` on exactly those payloads, then the worst case
   ``(sum(input) * price_in + n * max_tokens * price_out) / 1e6`` against the
   ceiling (API_ERROR, BUDGET_EXCEEDED); no batch exists yet;
4. create the batch. From here the batch id is printed and written to the job
   summary and a ``.pending`` record first; any later failure cancels, polls
   (bounded) and deletes it (SUBMIT_FAILED_AFTER_CREATE, CANCEL_TIMEOUT,
   DELETE_FAILED). The hand-off artifact is written last, so it exists only
   when submission succeeded.

``--cleanup`` is the workflow's ``if: failure()`` step: it cancels, polls and
deletes the batch named by the artifact (or the pending record) when a later
workflow step failed.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import re
import signal
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


def _sibling(name: str) -> ModuleType:
    """Load scripts/audit/<name>.py by path (python3 -I drops the script dir from sys.path)."""
    key = f"wiring_audit_{name}"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, Path(__file__).with_name(f"{name}.py"))
    if spec is None or spec.loader is None:
        raise ImportError(name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[key] = module
    spec.loader.exec_module(module)
    return module


config = _sibling("config")
inventory = _sibling("inventory")
client = _sibling("client")

SECRET_NAME = "WIRING_AUDIT_API_KEY"
EXIT_CODES = {name: config.EXIT_CODES[name] for name in (
    "OK", "CONFIG", "NO_MODULES", "MISSING_SECRET", "LEAK", "LEAK_SCAN_ERROR", "PRICES_STALE",
    "BUDGET_EXCEEDED", "API_ERROR", "SUBMIT_FAILED_AFTER_CREATE", "CANCEL_TIMEOUT", "DELETE_FAILED")}

_CLEAN = re.compile(r"CLEAN [0-9]+")
_HIT = re.compile(r"([0-9]+):([A-Za-z0-9_-]{1,64})")


# --- requests ---------------------------------------------------------------------------


def _fence(text: str) -> str:
    longest = cur = 0
    for ch in text:
        cur = cur + 1 if ch == "`" else 0
        longest = max(longest, cur)
    return "`" * max(3, longest + 1)


def build_request(mod: Any, cfg: dict[str, Any]) -> dict[str, Any]:
    """One Batches request for one module; every word of the prompt comes from config."""
    system = config.render_template(cfg["system_prompt"], {
        "kinds": ", ".join(cfg["finding_kinds"]),
        "severities": ", ".join(cfg["severities"]),
        "max_findings": str(cfg["max_findings_per_module"]),
    })
    facts = {k: v for k, v in mod.facts().items() if k not in ("custom_id", "sha256")}
    fence = _fence(mod.truncated_text)
    user = config.render_template(cfg["user_prompt"], {
        "path": mod.path,
        "facts": json.dumps(facts, sort_keys=True, indent=1, ensure_ascii=False),
        "source": f"{fence}\n{mod.truncated_text}\n{fence}",
    })
    return {
        "custom_id": mod.custom_id,
        "params": {
            "model": cfg["model"],
            "max_tokens": cfg["max_tokens"],
            "system": system,
            "messages": [{"role": "user", "content": user}],
        },
    }


def scan_text(request: dict[str, Any]) -> str:
    """Every string the request carries, in a fixed order: this is what is scanned."""
    params = request["params"]
    parts = [request["custom_id"], params["model"], params["system"]]
    parts.extend(m["content"] for m in params["messages"])
    return "\n".join(parts)


# --- leak scan (condition 1) -------------------------------------------------------------


class Refusal(Exception):
    def __init__(self, name: str, message: str) -> None:
        super().__init__(message)
        self.name = name


def leak_scan(repo: Path, cfg: dict[str, Any], texts: list[tuple[str, str]]) -> int:
    """Scan (label, text) pairs in one scanner run; return the CLEAN count or raise Refusal."""
    script = config.repo_file(repo, cfg["leak_scan_script"], "leak_scan_script")
    patterns = config.repo_file(repo, cfg["leak_scan_patterns"], "leak_scan_patterns")
    owners: list[tuple[int, str]] = []  # (last line number, label)
    line = 0
    for label, text in texts:
        line += len(text.split("\n"))
        owners.append((line, label))
    data = "\n".join(text for _, text in texts).encode("utf-8")
    argv = [sys.executable, "-I", str(script), str(patterns), "-"]
    try:
        rc, out, err = inventory.run_bounded(argv, cwd=repo, env=inventory.git_env(), stdin=data,
                                             timeout=cfg["subprocess_timeout_seconds"],
                                             cap=cfg["max_subprocess_output_bytes"])
    except (OSError, inventory.InventoryError) as exc:
        raise Refusal("LEAK_SCAN_ERROR", f"leak_scan.py could not run: {exc}") from None
    lines = out.decode("utf-8", "replace").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if rc == 1:
        if len(lines) == 1 and _CLEAN.fullmatch(lines[0]) and not err:
            return int(lines[0].split(" ")[1])
        raise Refusal("LEAK_SCAN_ERROR", "leak_scan.py exited 1 without the single CLEAN sentinel "
                                         "(a crash also exits 1); refusing to submit")
    if rc == 0:
        hits = [_HIT.fullmatch(x) for x in lines]
        if not lines or not all(hits):
            raise Refusal("LEAK_SCAN_ERROR", "leak_scan.py reported a leak in an unreadable format")
        found: dict[str, set[str]] = {}
        for m in hits:
            assert m is not None
            number = int(m.group(1))
            label = next((lab for last, lab in owners if number <= last), "(beyond the input)")
            found.setdefault(label, set()).add(m.group(2))
        detail = "; ".join(f"{lab} ({', '.join(sorted(names))})" for lab, names in sorted(found.items()))
        raise Refusal("LEAK", f"leak pattern(s) matched, nothing was sent: {detail}. Remove the local "
                              "path from the file or exclude the file in the config")
    raise Refusal("LEAK_SCAN_ERROR", f"leak_scan.py exited {rc}; refusing to submit")


# --- budget (condition 5) -----------------------------------------------------------------


def count_tokens(api: Any, request: dict[str, Any]) -> int:
    params = request["params"]
    body = {"model": params["model"], "system": params["system"], "messages": params["messages"]}
    doc = api.json("POST", "/v1/messages/count_tokens", body, retry=True)
    tokens = doc.get("input_tokens") if isinstance(doc, dict) else None
    if not isinstance(tokens, int) or isinstance(tokens, bool) or tokens < 0:
        raise client.ApiFailure("anthropic count_tokens returned no valid input_tokens")
    return tokens


def worst_case_usd(cfg: dict[str, Any], n: int, total_input: int) -> float:
    prices = cfg["prices_usd_per_mtok"]
    return (total_input * prices["input"] + n * cfg["max_tokens"] * prices["output"]) / 1_000_000


# --- artifacts ----------------------------------------------------------------------------


def write_json_atomic(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _discard(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass  # e.g. the parent is not a directory: then the file never existed


def pending_path(artifact: Path) -> Path:
    return artifact.with_name(artifact.name + ".pending")


def cleanup_after_create(api: Any, batch_id: str, cfg: dict[str, Any], rep: Any, reason: str) -> int:
    """Condition 8: cancel, poll until ended (bounded), delete; every outcome is non-zero."""
    rep.log(f"submit failed after creating batch {batch_id} ({reason}); cancelling it")
    try:
        client.cancel_and_wait(api, batch_id, cfg, rep.log)
    except client.CancelTimeout:
        return rep.error("CANCEL_TIMEOUT", f"batch {batch_id} did not end within "
                         f"{cfg['cancel_timeout_seconds']}s of the cancel request ({reason}); delete it "
                         "later with DELETE /v1/messages/batches/{id}")
    try:
        client.delete_batch(api, batch_id)
    except client.ApiFailure as exc:
        return rep.error("DELETE_FAILED", f"batch {batch_id} was cancelled but not deleted ({exc}); "
                         f"submit had failed: {reason}")
    return rep.error("SUBMIT_FAILED_AFTER_CREATE", f"{reason}; batch {batch_id} was cancelled and deleted")


# --- main ----------------------------------------------------------------------------------


def _parse(argv: list[str] | None) -> Any:
    parser = inventory.make_parser("Submit the weekly wiring-audit batch.")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--config", required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--cleanup", action="store_true",
                        help="cancel and delete the batch recorded by a run whose later step failed")
    return parser.parse_args(argv)


def _secret(env: dict[str, str]) -> str:
    return (env.get(SECRET_NAME) or "").strip()


def run_cleanup(args: Any, cfg: dict[str, Any], env: dict[str, str], http: Any, rep: Any) -> int:
    artifact = Path(args.artifact)
    record = artifact if artifact.is_file() else pending_path(artifact)
    if not record.is_file():
        rep.log("no batch was recorded by the submit step, so there is nothing to cancel")
        return EXIT_CODES["OK"]
    try:
        doc = json.loads(record.read_text(encoding="utf-8"))
        batch_id = doc["batch_id"]
        if not isinstance(batch_id, str) or not client.BATCH_ID_RE.fullmatch(batch_id):
            raise ValueError
    except (OSError, ValueError, KeyError, TypeError):
        return rep.error("SUBMIT_FAILED_AFTER_CREATE", "the batch record is unreadable; find the batch "
                         "id in the submit step log and delete the batch by hand")
    key = _secret(env)
    if not key:
        return rep.error("MISSING_SECRET", f"{SECRET_NAME} is not set; batch {batch_id} could not be cancelled")
    api = client.anthropic_api(http or client.urllib_transport(cfg["http_timeout_seconds"],
                                                               cfg["max_response_bytes"]), cfg, key)
    return cleanup_after_create(api, batch_id, cfg, rep, "a later workflow step failed")


def main(argv: list[str] | None = None, *, http: Any = None, env: dict[str, str] | None = None) -> int:
    env = dict(os.environ) if env is None else env
    rep = client.Reporter(env, EXIT_CODES)
    try:
        args = _parse(argv)
        cfg = config.load_config(args.config)
    except config.ConfigError as exc:
        return rep.error("CONFIG", str(exc))
    if args.cleanup:
        return run_cleanup(args, cfg, env, http, rep)

    key = _secret(env)
    if not key:
        return rep.error("MISSING_SECRET", f"the {SECRET_NAME} environment secret is not set; add the "
                         "dedicated wiring-audit key to the wiring-audit environment")
    review_by = dt.date.fromisoformat(cfg["price_review_by"])
    if dt.datetime.now(dt.timezone.utc).date() > review_by:
        return rep.error("PRICES_STALE", f"price_review_by {cfg['price_review_by']} has passed; re-check "
                         "the batch prices and update prices_usd_per_mtok and price_review_by")
    repo = Path(args.repo).resolve()
    try:
        inv = inventory.build_inventory(repo, cfg)
    except config.ConfigError as exc:
        return rep.error("CONFIG", str(exc))
    except inventory.InventoryError as exc:
        return rep.error("CONFIG", f"inventory: {exc}")
    if not inv.modules:
        return rep.error("NO_MODULES", "the inventory is empty: no tracked file matched the module "
                         "globs after the denylist; nothing was sent")

    canary = build_request(inv.canary, cfg)
    requests = [build_request(m, cfg) for m in inv.modules] + [canary]
    labels = [m.path for m in inv.modules] + [f"canary fixture {inv.canary.path}"]
    try:
        clean = leak_scan(repo, cfg, [(lab, scan_text(r)) for lab, r in zip(labels, requests)])
    except config.ConfigError as exc:
        return rep.error("CONFIG", str(exc))
    except Refusal as exc:
        return rep.error(exc.name, str(exc))
    rep.log(f"leak scan CLEAN over {len(requests)} payloads ({clean} lines)")

    http = http or client.urllib_transport(cfg["http_timeout_seconds"], cfg["max_response_bytes"])
    api = client.anthropic_api(http, cfg, key)
    try:
        total_input = sum(count_tokens(api, r) for r in requests)
    except client.ApiFailure as exc:
        return rep.error("API_ERROR", f"{exc}; no batch was created")
    worst = worst_case_usd(cfg, len(requests), total_input)
    ceiling = cfg["budget_ceiling_usd"]
    try:
        rep.summary(f"Wiring audit: {len(requests)} requests ({len(inv.modules)} modules + canary), "
                    f"{total_input} input tokens, worst case ${worst:.2f} against a ceiling of ${ceiling:.2f}")
    except OSError:
        rep.log("could not write the job summary")
    if worst > ceiling:
        return rep.error("BUDGET_EXCEEDED", f"worst case ${worst:.4f} exceeds the ceiling ${ceiling:.4f}; "
                         "no batch was created")

    try:
        doc = api.json("POST", "/v1/messages/batches", {"requests": requests})
    except client.ApiFailure as exc:
        return rep.error("API_ERROR", f"{exc}; if the request reached the API, check the Console for "
                         "a batch this run does not know about")
    batch_id = doc.get("id") if isinstance(doc, dict) else None
    if not isinstance(batch_id, str) or not client.BATCH_ID_RE.fullmatch(batch_id):
        return rep.error("API_ERROR", "batch create returned no usable batch id; check the Console")

    # Condition 8: the id reaches the log and the summary before anything else.
    rep.log(f"BATCH_CREATED {batch_id}")
    artifact = Path(args.artifact)
    try:
        rep.summary(f"Batch created: `{batch_id}` ({len(requests)} requests)")
        write_json_atomic(pending_path(artifact), {"batch_id": batch_id})
        write_json_atomic(artifact, {
            "batch_id": batch_id,
            "canary_custom_id": canary["custom_id"],
            "custom_ids": sorted(r["custom_id"] for r in requests),
            "model": cfg["model"],
            "modules": {m.custom_id: m.path for m in inv.modules},
            "worst_case_usd": round(worst, 6),
        })
        pending_path(artifact).unlink()
    except BaseException as exc:  # noqa: BLE001 - any failure after create must clean up (C8)
        _discard(artifact)  # the artifact means "submitted"; it must not outlive a failure
        rc = cleanup_after_create(api, batch_id, cfg, rep, f"{type(exc).__name__} after create")
        if rc == EXIT_CODES["SUBMIT_FAILED_AFTER_CREATE"]:
            _discard(pending_path(artifact))  # deleted: nothing left for the cleanup step
        return rc
    rep.log(f"OK batch {batch_id} submitted with {len(requests)} requests, worst case ${worst:.2f}")
    return EXIT_CODES["OK"]


def _terminate(signum: int, frame: Any) -> None:
    raise KeyboardInterrupt(f"signal {signum}")  # lets the after-create cleanup run


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _terminate)
    sys.exit(main())
