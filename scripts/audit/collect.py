#!/usr/bin/env python3
"""Collect job of the weekly wiring audit (card #224, ADR 0002).

Reads the submit job's hand-off artifact, then checks the batch against the
result contract before filing anything (condition 6). Each check has its own
exit code and message, in this order:

    artifact schema ............................. ARTIFACT_INVALID (no request made)
    processing_status == "ended" ................ BATCH_NOT_ENDED (cancelled, polled, deleted)
    every custom_id exactly once, none unknown .. MISSING_OR_DUP
    every request succeeded ..................... PARTIAL
    every stop_reason == "end_turn" ............. TRUNCATED_OR_REFUSED
    every output matches the finding schema ..... SCHEMA
    the canary's known defect is reported ....... CANARY_MISSING
    any HTTP / transport problem ................ API_ERROR

Model output is data (condition 7): findings are schema-validated, then every
model-written field goes through ONE renderer (``clean_field`` + ``fenced``)
that strips control and format characters, redacts lines matching a secret or
local-path pattern, neutralises comment markers, truncates, and fences the
text so no markdown, mention or link in it is live. Titles carry no model text.
Issues are posted through the REST API from those fields, never via a shell.

The batch is deleted on every exit path once the artifact is valid (a
``finally``), except when a cancelled batch never reaches ``ended`` within the
configured timeout (CANCEL_TIMEOUT, id recorded). A failed delete is
DELETE_FAILED (condition 8). Actual cost from ``usage`` goes to the job summary.
"""
from __future__ import annotations

import collections
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import signal
import sys
import unicodedata
import urllib.parse
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
GITHUB_TOKEN_NAME = "GITHUB_TOKEN"
EXIT_CODES = {name: config.EXIT_CODES[name] for name in (
    "OK", "CONFIG", "MISSING_SECRET", "ARTIFACT_INVALID", "BATCH_NOT_ENDED", "PARTIAL", "MISSING_OR_DUP",
    "TRUNCATED_OR_REFUSED", "SCHEMA", "CANARY_MISSING", "API_ERROR", "DELETE_FAILED", "CANCEL_TIMEOUT",
    "HANDOFF_STALE", "NO_HANDOFF")}

ARTIFACT_KEYS = frozenset({"batch_id", "canary_custom_id", "created_at", "custom_ids", "model", "modules",
                           "worst_case_usd"})
_CREATED_AT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
FINDING_KEYS = frozenset({"kind", "severity", "symbol", "evidence", "recommendation"})
OUTPUT_KEYS = frozenset({"module", "findings"})
_REPO_SLUG = re.compile(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}")
_MARKER = re.compile(r"<!-- wiring-audit:([0-9a-f]{16}) -->")
_TITLE_UNSAFE = re.compile(r"[^A-Za-z0-9._/-]")
_FORBIDDEN = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})
_LINE_BREAKS = frozenset({"Zl", "Zp"})
_REDACTED = "[redacted by the wiring audit: the line matched a secret or local-path pattern]"


class Failure(Exception):
    def __init__(self, name: str, message: str) -> None:
        super().__init__(message)
        self.name = name


def _ids(values: list[str]) -> str:
    shown = ", ".join(client.safe_token(v) for v in values[:10])
    return shown + (f" and {len(values) - 10} more" if len(values) > 10 else "")


# --- artifact (attack sketch T10) --------------------------------------------------------


class Artifact:
    def __init__(self, doc: dict[str, Any]) -> None:
        self.batch_id: str = doc["batch_id"]
        self.custom_ids: list[str] = doc["custom_ids"]
        self.canary_id: str = doc["canary_custom_id"]
        self.modules: dict[str, str] = doc["modules"]
        self.created_at: dt.datetime = _parse_created_at(doc["created_at"])


def _parse_created_at(value: Any) -> dt.datetime:
    """RFC 3339 UTC with a Z suffix (the format submit writes), as an aware datetime."""
    if not isinstance(value, str) or not _CREATED_AT.fullmatch(value):
        raise ValueError("created_at is not RFC 3339 UTC (YYYY-MM-DDTHH:MM:SSZ)")
    return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def read_artifact(path: Path) -> Artifact:
    def bad(why: str) -> Failure:
        return Failure("ARTIFACT_INVALID", f"hand-off artifact {path.name}: {why}")

    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        raise bad("cannot be read") from None
    except (ValueError, RecursionError):
        raise bad("is not JSON") from None
    if not isinstance(doc, dict) or set(doc) != ARTIFACT_KEYS:
        raise bad("does not have exactly the expected keys")
    if not isinstance(doc["batch_id"], str) or not client.BATCH_ID_RE.fullmatch(doc["batch_id"]):
        raise bad("batch_id is malformed")
    ids = doc["custom_ids"]
    if (not isinstance(ids, list) or not ids or len(set(ids)) != len(ids)
            or not all(isinstance(i, str) and config.CUSTOM_ID_RE.fullmatch(i) for i in ids)):
        raise bad("custom_ids must be a non-empty list of unique valid ids")
    canary = doc["canary_custom_id"]
    if not isinstance(canary, str) or not config.CUSTOM_ID_RE.fullmatch(canary):
        raise bad("canary_custom_id is malformed")
    modules = doc["modules"]
    if not isinstance(modules, dict) or not all(
            isinstance(k, str) and config.CUSTOM_ID_RE.fullmatch(k) and isinstance(v, str)
            and _valid_module_path(v) for k, v in modules.items()):
        raise bad("modules must map custom ids to repository paths")
    if canary not in ids:
        raise bad("canary_custom_id is not one of custom_ids")
    if any(i != canary and i not in modules for i in ids):
        raise bad("a custom_id has no module path")
    try:
        art = Artifact(doc)
    except ValueError as exc:
        raise bad(str(exc)) from None
    if art.created_at > utc_now():
        raise bad("created_at is in the future")
    return art


def _valid_module_path(path: str) -> bool:
    return (0 < len(path) <= 1024 and not path.startswith("/") and ".." not in path.split("/")
            and all(ch == " " or unicodedata.category(ch)[0] in "LMNPS" for ch in path))


# --- results ------------------------------------------------------------------------------


def parse_results(data: bytes) -> list[dict[str, Any]]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise client.ApiFailure("anthropic results stream is not UTF-8") from None
    lines = []
    for number, line in enumerate(text.split("\n"), 1):
        if not line.strip():
            continue
        try:
            doc = json.loads(line)
        except (ValueError, RecursionError):
            raise client.ApiFailure(f"anthropic results line {number} is not JSON") from None
        if (not isinstance(doc, dict) or not isinstance(doc.get("custom_id"), str)
                or not isinstance(doc.get("result"), dict)):
            raise client.ApiFailure(f"anthropic results line {number} lacks custom_id or result")
        lines.append(doc)
    return lines


def request_counts(batch: dict[str, Any]) -> dict[str, int]:
    counts = batch.get("request_counts")
    if not isinstance(counts, dict) or not all(
            isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in counts.values()):
        raise client.ApiFailure("anthropic batch object has malformed request_counts")
    return counts


def _message(line: dict[str, Any]) -> dict[str, Any]:
    message = line["result"].get("message")
    return message if isinstance(message, dict) else {}


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [k for k, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate key")
    return dict(pairs)


def _reject_constant(name: str) -> Any:
    raise ValueError(f"non-standard JSON constant {name}")


def parse_output(message: dict[str, Any], cfg: dict[str, Any]) -> list[dict[str, str]]:
    """The findings of one model answer, or ValueError naming what broke the schema."""
    blocks = message.get("content")
    if not isinstance(blocks, list):
        raise ValueError("message has no content list")
    text = "".join(b.get("text", "") for b in blocks
                   if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str))
    body = text.strip()
    if body.startswith("```") and body.endswith("```") and "\n" in body:
        body = body[body.index("\n") + 1:-3].strip()  # tolerate one wrapping code fence
    try:
        doc = json.loads(body, object_pairs_hook=_no_duplicate_keys, parse_constant=_reject_constant)
    except RecursionError:
        raise ValueError("output nests too deeply") from None
    except ValueError:
        raise ValueError("output is not one JSON object") from None
    if not isinstance(doc, dict) or set(doc) != OUTPUT_KEYS or not isinstance(doc["module"], str):
        raise ValueError("output must have exactly the keys module and findings")
    findings = doc["findings"]
    if not isinstance(findings, list):
        raise ValueError("findings is not a list")
    if len(findings) > cfg["max_findings_per_module"]:
        raise ValueError("more findings than max_findings_per_module")
    for f in findings:
        if not isinstance(f, dict) or set(f) != FINDING_KEYS:
            raise ValueError("a finding does not have exactly the schema keys")
        if not all(isinstance(f[k], str) for k in FINDING_KEYS):
            raise ValueError("a finding field is not a string")
        if f["kind"] not in cfg["finding_kinds"] or f["severity"] not in cfg["severities"]:
            raise ValueError("a finding has a kind or severity outside the enumeration")
        if not f["symbol"].strip():
            raise ValueError("a finding has an empty symbol")
    return findings


def usage_cost(results: list[dict[str, Any]], cfg: dict[str, Any]) -> tuple[float, dict[str, int]]:
    totals = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
              "cache_creation_input_tokens": 0}
    for line in results:
        usage = _message(line).get("usage")
        if not isinstance(usage, dict):
            continue
        for key in totals:
            value = usage.get(key, 0)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                totals[key] += value
    prices = cfg["prices_usd_per_mtok"]
    cost = (totals["input_tokens"] * prices["input"] + totals["output_tokens"] * prices["output"]
            + totals["cache_read_input_tokens"] * prices["cache_read"]
            + totals["cache_creation_input_tokens"] * prices["cache_write"]) / 1_000_000
    return cost, totals


def check_results(art: Artifact, batch: dict[str, Any], results: list[dict[str, Any]],
                  cfg: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    """The result contract; returns findings per custom_id or raises Failure."""
    counts = request_counts(batch)
    expected = set(art.custom_ids)
    seen = collections.Counter(line["custom_id"] for line in results)
    missing = sorted(c for c in expected if seen[c] == 0)
    dups = sorted(c for c, n in seen.items() if n > 1)
    unknown = sorted(c for c in seen if c not in expected)
    if missing or dups or unknown or sum(counts.values()) != len(expected):
        parts = []
        if missing:
            parts.append(f"missing {_ids(missing)}")
        if dups:
            parts.append(f"duplicated {_ids(dups)}")
        if unknown:
            parts.append(f"not submitted {_ids(unknown)}")
        if sum(counts.values()) != len(expected):
            parts.append(f"the batch reports {sum(counts.values())} requests, the artifact {len(expected)}")
        raise Failure("MISSING_OR_DUP", "result set does not match the submitted set: " + "; ".join(parts))
    failed = sorted((line["custom_id"], client.safe_token(line["result"].get("type")))
                    for line in results if line["result"].get("type") != "succeeded")
    if failed or counts.get("succeeded") != len(expected):
        detail = ", ".join(f"{client.safe_token(c)} ({t})" for c, t in failed[:10]) or "per request_counts"
        raise Failure("PARTIAL", f"not every request succeeded: {detail}")
    stopped = sorted((line["custom_id"], client.safe_token(_message(line).get("stop_reason")))
                     for line in results if _message(line).get("stop_reason") != "end_turn")
    if stopped:
        detail = ", ".join(f"{client.safe_token(c)} ({r})" for c, r in stopped[:10])
        raise Failure("TRUNCATED_OR_REFUSED", f"stop_reason other than end_turn: {detail}")
    findings: dict[str, list[dict[str, str]]] = {}
    for line in sorted(results, key=lambda x: x["custom_id"]):
        try:
            findings[line["custom_id"]] = parse_output(_message(line), cfg)
        except ValueError as exc:
            raise Failure("SCHEMA", f"{client.safe_token(line['custom_id'])}: {exc}") from None
    if not any(f["kind"] == cfg["canary_expected_kind"] for f in findings[art.canary_id]):
        raise Failure("CANARY_MISSING", f"the canary request did not report its known "
                      f"{cfg['canary_expected_kind']} defect; the run is not trusted and files nothing")
    return findings


# --- the one issue renderer (condition 7) -------------------------------------------------


class Redactor:
    def __init__(self, personal: list[re.Pattern[str]], leak: list[re.Pattern[str]],
                 secrets: list[str]) -> None:
        self.personal = personal
        self.leak = leak
        self.secrets = [re.compile(p) for p in secrets]

    def hit(self, line: str) -> bool:
        folded = line.casefold()
        return (config.matches_personal_path(line, self.personal)
                or any(rx.search(folded) for rx in self.leak)
                or any(rx.search(line) for rx in self.secrets))


def clean_field(text: str, limit: int, redactor: Redactor) -> str:
    """Model text made inert: no control/format chars, redacted, no comment markers, truncated."""
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    chars = []
    for ch in text:
        category = unicodedata.category(ch)
        if ch == "\n" or category in _LINE_BREAKS:
            chars.append("\n")
        elif ch == "\t":
            chars.append(" ")
        elif category not in _FORBIDDEN:
            chars.append(ch)
    lines = [_REDACTED if redactor.hit(line) else line for line in "".join(chars).split("\n")]
    text = "\n".join(lines).replace("<!--", "<!- -").replace("-->", "- ->")
    if len(text) > limit:
        text = text[:limit] + f"\n[truncated by the wiring audit: {len(text) - limit} characters omitted]"
    return text


def fenced(text: str) -> str:
    """A code fence longer than any backtick run inside, so the text cannot close it."""
    longest = cur = 0
    for ch in text:
        cur = cur + 1 if ch == "`" else 0
        longest = max(longest, cur)
    fence = "`" * max(3, longest + 1)
    return f"{fence}text\n{text}\n{fence}"


def safe_path(path: str) -> str:
    return _TITLE_UNSAFE.sub("_", path)


class Finding:
    def __init__(self, repo: str, path: str, raw: dict[str, str]) -> None:
        self.path = path
        self.kind = raw["kind"]
        self.severity = raw["severity"]
        self.raw = raw
        self.key = hashlib.sha256(f"{repo}|{path}|{raw['kind']}|{raw['symbol']}".encode("utf-8")).hexdigest()[:16]


def finding_block(f: Finding, cfg: dict[str, Any], redactor: Redactor) -> str:
    limit = cfg["max_field_chars"]
    parts = [
        f"<!-- wiring-audit:{f.key} -->",
        f"**{f.kind}** ({f.severity}) in `{safe_path(f.path)}`",
        "",
    ]
    for label, field in (("Symbol", "symbol"), ("Evidence", "evidence"), ("Recommendation", "recommendation")):
        parts.extend([f"{label}:", "", fenced(clean_field(f.raw[field], limit, redactor)), ""])
    return "\n".join(parts)


_PREAMBLE = ("Filed by the weekly wiring audit (ADR 0002). The text in code blocks is model output: "
             "it was validated against the audit schema and is shown verbatim, so treat it as a lead "
             "to check, not as a fact.")


def card(f: Finding, cfg: dict[str, Any], redactor: Redactor, batch_id: str) -> dict[str, Any]:
    title = f"Wiring audit: {f.kind} in {safe_path(f.path)}"[: cfg["max_title_chars"]]
    body = "\n".join([_PREAMBLE, "", f"Batch: `{batch_id}`", "", finding_block(f, cfg, redactor)])
    return {"title": title, "body": body, "labels": list(cfg["labels"])}


def summary_issue(items: list[Finding], cfg: dict[str, Any], redactor: Redactor,
                  batch_id: str) -> tuple[dict[str, Any], int]:
    """One issue for the run (card_mode summary); returns (issue, findings listed)."""
    head = [_PREAMBLE, "",
            f"Batch: `{batch_id}`. New findings at or above {cfg['card_threshold']}: {len(items)}. "
            "card_mode is summary: the owner reviews this format before switching to one card per finding.",
            ""]
    body = "\n".join(head)
    listed = 0
    for f in items:
        block = finding_block(f, cfg, redactor)
        if len(body) + len(block) + 200 > cfg["max_issue_body_chars"]:
            break
        body += "\n" + block
        listed += 1
    if listed < len(items):
        body += (f"\n{len(items) - listed} more finding(s) did not fit in this issue; "
                 "they are reported again by the next run.\n")
    title = f"Wiring audit: {len(items)} new finding(s), batch {batch_id}"[: cfg["max_title_chars"]]
    return {"title": title, "body": body, "labels": list(cfg["labels"])}, listed


# --- GitHub --------------------------------------------------------------------------------


def github_api(http: Any, cfg: dict[str, Any], token: str) -> Any:
    headers = {"authorization": f"Bearer {token}", "accept": "application/vnd.github+json",
               "x-github-api-version": cfg["github_api_version"], "user-agent": cfg["user_agent"]}
    return client.Api(http, cfg["github_api_url"], headers, cfg, "github")


def open_issue_keys(gh: Any, slug: str, cfg: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    labels = urllib.parse.quote(",".join(cfg["labels"]), safe="")
    size = cfg["issue_page_size"]
    for page in range(1, cfg["max_issue_pages"] + 1):
        items = gh.json("GET", f"/repos/{slug}/issues?state=open&labels={labels}&per_page={size}&page={page}",
                        retry=True)
        if not isinstance(items, list):
            raise client.ApiFailure("github issue list is not a list")
        for item in items:
            if isinstance(item, dict) and "pull_request" not in item and isinstance(item.get("body"), str):
                keys.update(_MARKER.findall(item["body"]))
        if len(items) < size:
            return keys
    raise client.ApiFailure(f"more than {cfg['max_issue_pages']} pages of open wiring-audit issues; "
                            "raise max_issue_pages or close old issues")


def post_issue(gh: Any, slug: str, issue: dict[str, Any]) -> int:
    doc = gh.json("POST", f"/repos/{slug}/issues", issue, ok=(201,))
    number = doc.get("number") if isinstance(doc, dict) else None
    if not isinstance(number, int) or isinstance(number, bool):
        raise client.ApiFailure("github issue create returned no issue number")
    return number


# --- the run --------------------------------------------------------------------------------


class Collector:
    def __init__(self, cfg: dict[str, Any], art: Artifact, api: Any, gh: Any, slug: str,
                 redactor: Redactor, rep: Any) -> None:
        self.cfg, self.art, self.api, self.gh, self.slug = cfg, art, api, gh, slug
        self.redactor, self.rep = redactor, rep
        self.filed: list[int] = []

    def _summary(self, line: str) -> None:
        try:
            self.rep.summary(line)
        except OSError:
            self.rep.log("could not write the job summary")

    def run(self) -> int:
        outcome: Failure | None = None
        delete = True
        delete_error = ""
        try:
            try:
                self._work()
            except Failure as exc:
                outcome = exc
            except client.ApiFailure as exc:
                outcome = Failure("API_ERROR", str(exc))
            except client.CancelTimeout:
                delete = False  # a batch that has not ended cannot be deleted
                outcome = Failure("CANCEL_TIMEOUT", f"batch {self.art.batch_id} did not end within "
                                  f"{self.cfg['cancel_timeout_seconds']}s of the cancel request; delete it "
                                  "later with DELETE /v1/messages/batches/{id}")
        finally:  # condition 8: every exit path, including an unexpected exception
            if delete:
                try:
                    client.delete_batch(self.api, self.art.batch_id)
                except client.ApiFailure as exc:
                    delete_error = str(exc)
        rc = EXIT_CODES["OK"]
        if outcome is not None:
            rc = self.rep.error(outcome.name, str(outcome))
        if delete_error:
            code = self.rep.error("DELETE_FAILED", f"batch {self.art.batch_id} was not deleted ({delete_error}); "
                                  "delete it by hand so its prompts do not stay in retention")
            rc = code if outcome is None else rc
        if outcome is None and not delete_error:
            self.rep.log(f"OK batch {self.art.batch_id} collected and deleted; issues filed: "
                         f"{len(self.filed)}")
        return rc

    def _work(self) -> None:
        batch_id = self.art.batch_id
        batch = client.retrieve(self.api, batch_id)
        status = client.processing_status(batch)
        if status != "ended":
            self.rep.log(f"batch {batch_id} is {client.safe_token(status)}; cancelling it")
            client.cancel_and_wait(self.api, batch_id, self.cfg, self.rep.log)
            raise Failure("BATCH_NOT_ENDED", f"batch {batch_id} had not ended at collect time "
                          f"({client.safe_token(status)}); it was cancelled and nothing was filed")
        data = self.api.call("GET", client.batch_path(batch_id, "/results"), retry=True)
        results = parse_results(data)
        cost, totals = usage_cost(results, self.cfg)
        self._summary(f"Wiring audit batch `{batch_id}`: {len(results)} results, actual cost "
                         f"${cost:.2f} ({totals['input_tokens']} input, {totals['output_tokens']} output, "
                         f"{totals['cache_read_input_tokens']} cache-read tokens)")
        per_id = check_results(self.art, batch, results, self.cfg)
        self._file(per_id)

    def _file(self, per_id: dict[str, list[dict[str, str]]]) -> None:
        cfg = self.cfg
        threshold = config.severity_rank(cfg, cfg["card_threshold"])
        found: dict[str, Finding] = {}
        below = 0
        for cid, raws in per_id.items():
            if cid == self.art.canary_id:
                continue  # the canary is synthetic and never filed
            for raw in raws:
                if config.severity_rank(cfg, raw["severity"]) < threshold:
                    below += 1
                    continue
                f = Finding(self.slug, self.art.modules[cid], raw)
                found.setdefault(f.key, f)
        existing = open_issue_keys(self.gh, self.slug, cfg) if found else set()
        new = sorted((f for f in found.values() if f.key not in existing),
                     key=lambda f: (-config.severity_rank(cfg, f.severity), f.path, f.kind, f.key))
        self._summary(f"Findings at or above {cfg['card_threshold']}: {len(found)} "
                         f"({len(found) - len(new)} already open), below the threshold: {below}")
        if not new:
            self.rep.log("no new findings to file")
            return
        if cfg["card_mode"] == "summary":
            issue, listed = summary_issue(new, cfg, self.redactor, self.art.batch_id)
            self.filed.append(post_issue(self.gh, self.slug, issue))
            self._summary(f"Filed summary issue {self.filed[-1]} listing {listed} finding(s)")
            return
        for f in new[: cfg["max_cards_per_run"]]:
            self.filed.append(post_issue(self.gh, self.slug, card(f, cfg, self.redactor, self.art.batch_id)))
        skipped = len(new) - min(len(new), cfg["max_cards_per_run"])
        self._summary(f"Filed {len(self.filed)} card(s); {skipped} more held back by max_cards_per_run")


def _parse(argv: list[str] | None) -> Any:
    parser = inventory.make_parser("Collect the weekly wiring-audit batch and file its findings.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--artifact", action="append", default=[],
                        help="one per uncollected submit run, oldest first (repeatable)")
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]),
                        help="checkout holding the pattern files (default: this script's checkout)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, *, http: Any = None, env: dict[str, str] | None = None) -> int:
    env = dict(os.environ) if env is None else env
    rep = client.Reporter(env, EXIT_CODES)
    try:
        args = _parse(argv)
        cfg = config.load_config(args.config)
        repo = Path(args.repo)
        redactor = Redactor(config.load_personal_patterns(repo, cfg), config.load_leak_patterns(repo, cfg),
                            cfg["secret_patterns"])
    except config.ConfigError as exc:
        return rep.error("CONFIG", str(exc))
    key = (env.get(SECRET_NAME) or "").strip()
    if not key:
        return rep.error("MISSING_SECRET", f"the {SECRET_NAME} environment secret is not set; add the "
                         "dedicated wiring-audit key to the wiring-audit environment")
    token = (env.get(GITHUB_TOKEN_NAME) or "").strip()
    if not token:
        return rep.error("MISSING_SECRET", f"{GITHUB_TOKEN_NAME} is not set; the workflow passes the job token")
    slug = env.get("GITHUB_REPOSITORY", "")
    if not _REPO_SLUG.fullmatch(slug):
        return rep.error("CONFIG", "GITHUB_REPOSITORY is not set to owner/name")
    if not args.artifact:
        return rep.error("NO_HANDOFF", "no submit hand-off to collect: no successful submit run since the "
                         "last successful collect; nothing was checked or filed")
    http = http or client.urllib_transport(cfg["http_timeout_seconds"], cfg["max_response_bytes"])
    api, gh = client.anthropic_api(http, cfg, key), github_api(http, cfg, token)
    limit = dt.timedelta(days=cfg["stale_handoff_days"])
    rc = EXIT_CODES["OK"]
    # Every hand-off is processed, oldest first; one failing never stops the next.
    # The run's exit code is the first failure, so any failure turns it red.
    for path in args.artifact:
        try:
            art = read_artifact(Path(path))
        except Failure as exc:
            code = rep.error(exc.name, str(exc))
        else:
            if utc_now() - art.created_at > limit:
                code = rep.error("HANDOFF_STALE", f"hand-off for batch {art.batch_id} was written at "
                                 f"{art.created_at:%Y-%m-%dT%H:%M:%SZ}, more than {cfg['stale_handoff_days']} "
                                 "days ago; it was not collected and no request was made for it. If the "
                                 "batch still exists, delete it by hand so its prompts leave retention")
            else:
                code = Collector(cfg, art, api, gh, slug, redactor, rep).run()
        if rc == EXIT_CODES["OK"]:
            rc = code
    return rc


def _terminate(signum: int, frame: Any) -> None:
    raise KeyboardInterrupt(f"signal {signum}")  # runs the delete in Collector.run's finally


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _terminate)
    sys.exit(main())
