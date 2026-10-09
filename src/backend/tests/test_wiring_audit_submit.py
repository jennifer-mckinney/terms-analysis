"""Weekly wiring audit: the submit job (card #224, ADR 0002).

ADR 0002 condition numbers are in brackets on every test. Interface:
``tests/wiring_audit_support.py``. Every API call goes to an injected fake
transport; the real socket and urllib layers are banned in every test.

[C1] every payload, the canary included, passes leak_scan.py ("exit 1 AND
the CLEAN <n> sentinel") before ANY request, token counting included.
[C5] count_tokens runs only on those exact payloads; worst-case cost from the
config prices; over the ceiling or past price_review_by refuses, no batch.
[C6] zero modules and every API failure exit non-zero with their own code.
[C8] once a batch exists, its id is logged first; a later failure cancels,
polls until ended (bounded), deletes, and exits with its own code.
[C9] the default transport is stdlib urllib, bounded by a timeout.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.wiring_audit_support import (
    AUDIT_DIR,
    BATCH,
    BATCH_ID,
    BATCHES,
    CANARY_MARKER,
    CANCEL,
    COUNT_TOKENS,
    CUSTOM_ID_RE,
    FAKE_KEY,
    HOME_LINE_PATH,
    PYTEST_TMP_LEAK,
    SECRET_NAME,
    STD_MODULES,
    Call,
    FakeHTTP,
    audit_env,
    audit_repo,
    ban_network,
    batch_object,
    canary_source,
    created_requests,
    exit_code,
    install_clock,
    jbytes,
    longest_run,
    module_source,
    python_exe,
    request_text,
    require,
    route_submit,
    run_main,
    string_leaves,
    summary_text,
    write_config,
)


@pytest.fixture(autouse=True)
def net(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    return ban_network(monkeypatch)


@pytest.fixture(autouse=True)
def clock(monkeypatch: pytest.MonkeyPatch) -> Any:
    return install_clock(monkeypatch)


def _utc_today() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def _cfg(tmp: Path, **overrides: Any) -> tuple[Path, dict[str, Any]]:
    # Explicit overrides only: a narrow glob so the payloads are the fixture
    # modules, and a review date safely in the future.
    base: dict[str, Any] = {
        "module_globs": ["src/**/*.py"],
        "price_review_by": (_utc_today() + dt.timedelta(days=30)).isoformat(),
    }
    base.update(overrides)
    return write_config(tmp, **base)


def _submit(tmp: Path, repo: Path, cfg_path: Path, fake: FakeHTTP, *, env: dict[str, str] | None = None,
            artifact: Path | None = None) -> tuple[Any, int, str, Path]:
    submit = require("submit")
    artifact = artifact or tmp / "artifact" / "wiring-audit-batch.json"
    rc, out = run_main(
        submit,
        ["--repo", str(repo), "--config", str(cfg_path), "--artifact", str(artifact)],
        http=fake,
        env=audit_env(tmp) if env is None else env,
    )
    return submit, rc, out, artifact


def _ok_fake(tokens: int = 1000) -> FakeHTTP:
    fake = FakeHTTP()
    route_submit(fake, tokens=tokens)
    return fake


def _assert_no_secret(tmp: Path, *texts: str) -> None:
    b64 = base64.b64encode(FAKE_KEY.encode()).decode()
    for text in (*texts, summary_text(tmp)):
        assert FAKE_KEY not in text
        assert b64 not in text
        assert FAKE_KEY[:20] not in text


def _assert_error_line(out: str, name: str) -> None:
    assert name in out
    assert "::error title=wiring-audit::" in out


# --- happy path and config-driven requests ---------------------------------------------------------


def test_submit_creates_one_batch_with_every_module_and_the_canary(tmp_path: Path, net: list[str]) -> None:
    cfg_path, cfg = _cfg(tmp_path)
    repo = audit_repo(tmp_path, cfg)
    fake = _ok_fake()
    submit, rc, out, artifact = _submit(tmp_path, repo, cfg_path, fake)
    assert rc == exit_code(submit, "OK"), out
    assert fake.unexpected == [] and net == []
    reqs = created_requests(fake)
    ids = [r["custom_id"] for r in reqs]
    assert len(reqs) == len(STD_MODULES) + 1
    assert all(CUSTOM_ID_RE.fullmatch(i) for i in ids) and len(set(ids)) == len(ids)
    texts = [request_text(r) for r in reqs]
    assert sum(CANARY_MARKER in t for t in texts) == 1  # [C6] canary in every batch, once
    for marker, _ in STD_MODULES.values():
        assert sum(marker in t for t in texts) == 1
    for r in reqs:
        assert r["params"]["model"] == cfg["model"]
        assert r["params"]["max_tokens"] == cfg["max_tokens"]
    for call in fake.calls:
        assert call.is_anthropic
        assert call.headers.get("x-api-key") == FAKE_KEY
        assert call.headers.get("anthropic-version") == cfg["api_version"]
    # Hand-off artifact and positive attestation.
    doc = json.loads(artifact.read_text(encoding="utf-8"))
    assert doc["batch_id"] == BATCH_ID
    assert sorted(doc["custom_ids"]) == sorted(ids)
    assert BATCH_ID in out and BATCH_ID in summary_text(tmp_path)
    _assert_no_secret(tmp_path, out, artifact.read_text(encoding="utf-8"))
    assert "x-api-key" not in artifact.read_text(encoding="utf-8").lower()


def test_model_and_max_tokens_come_from_config(tmp_path: Path) -> None:
    # [F13] change the config, the request changes: nothing hard-coded.
    cfg_path, cfg = _cfg(tmp_path, model="claude-test-model-x", max_tokens=1234)
    repo = audit_repo(tmp_path, cfg)
    fake = _ok_fake()
    submit, rc, out, _ = _submit(tmp_path, repo, cfg_path, fake)
    assert rc == exit_code(submit, "OK"), out
    for r in created_requests(fake):
        assert r["params"]["model"] == "claude-test-model-x"
        assert r["params"]["max_tokens"] == 1234
    for c in fake.find("POST", COUNT_TOKENS):
        assert c.json()["model"] == "claude-test-model-x"


# --- [C1] leak scan before any request -----------------------------------------------------------


def _fake_scanner(log: Path, *, rc: int, stdout: str = "", stderr: str = "") -> str:
    return (
        "import sys\n"
        "args = sys.argv[1:]\n"
        "data = open(args[1], 'rb').read() if len(args) > 1 and args[1] != '-' else sys.stdin.buffer.read()\n"
        f"open({str(log)!r}, 'ab').write(data + b'\\n--SCAN--\\n')\n"
        f"sys.stdout.write({stdout!r})\n"
        f"sys.stderr.write({stderr!r})\n"
        f"sys.exit({rc})\n"
    )


def test_scanner_sees_every_payload_before_the_first_request(tmp_path: Path) -> None:
    cfg_path, cfg = _cfg(tmp_path)
    log = tmp_path / "scan.log"
    repo = audit_repo(tmp_path, cfg, extra={cfg["leak_scan_script"]: _fake_scanner(log, rc=1, stdout="CLEAN 3\n")})
    fake = _ok_fake()
    seen_at_first_call: list[bytes] = []
    fake.on_call.append(lambda c: seen_at_first_call.append(log.read_bytes() if log.exists() else b"") if not seen_at_first_call else None)
    submit, rc, out, _ = _submit(tmp_path, repo, cfg_path, fake)
    assert rc == exit_code(submit, "OK"), out
    assert seen_at_first_call, "no request was made"
    scanned = seen_at_first_call[0].decode("utf-8", "replace")
    for marker, _ in STD_MODULES.values():
        assert marker in scanned
    assert CANARY_MARKER in scanned


def test_leaking_module_refuses_submission_without_any_request(tmp_path: Path, net: list[str]) -> None:
    cfg_path, cfg = _cfg(tmp_path)
    leaky = module_source("ALPHA_MARKER_51c2", "alpha_fn") + f'TMP = "/tmp/{PYTEST_TMP_LEAK}/x"\n'
    repo = audit_repo(tmp_path, cfg, extra={"src/backend/app/alpha.py": leaky})
    fake = _ok_fake()
    submit, rc, out, artifact = _submit(tmp_path, repo, cfg_path, fake)
    assert rc == exit_code(submit, "LEAK")
    _assert_error_line(out, "LEAK")
    assert fake.calls == [] and net == []
    assert not artifact.exists()
    assert "src/backend/app/alpha.py" in out  # honest: names the file
    assert PYTEST_TMP_LEAK not in out  # [F8] never echoes the leaked bytes


def test_leaking_canary_refuses_submission_without_any_request(tmp_path: Path, net: list[str]) -> None:
    # [C1, C6] the canary passes the same scan as every module.
    cfg_path, cfg = _cfg(tmp_path)
    repo = audit_repo(tmp_path, cfg, canary=canary_source(f'TMP = "/tmp/{PYTEST_TMP_LEAK}/x"\n'))
    fake = _ok_fake()
    submit, rc, out, _ = _submit(tmp_path, repo, cfg_path, fake)
    assert rc == exit_code(submit, "LEAK")
    assert fake.calls == [] and net == []
    assert PYTEST_TMP_LEAK not in out


SCANNER_RESULTS = [
    ("clean", 1, "CLEAN 3\n", "", {"OK"}),
    ("exit-1-without-sentinel", 1, "", "", {"LEAK_SCAN_ERROR"}),
    ("exit-1-sentinel-on-stderr", 1, "", "CLEAN 3\n", {"LEAK_SCAN_ERROR"}),
    ("exit-1-malformed-sentinel", 1, "CLEAN\n", "", {"LEAK_SCAN_ERROR"}),
    ("exit-1-sentinel-not-a-number", 1, "CLEAN x\n", "", {"LEAK_SCAN_ERROR"}),
    ("usage-error-exit-2", 2, "", "leak_scan: bad pattern\n", {"LEAK_SCAN_ERROR"}),
    ("crash-exit-1-traceback", 1, "", "Traceback (most recent call last):\n", {"LEAK_SCAN_ERROR"}),
    ("leak-exit-0", 0, "1:home-root\n", "", {"LEAK"}),
    ("sentinel-with-exit-0", 0, "CLEAN 3\n", "", {"LEAK", "LEAK_SCAN_ERROR"}),
    ("leak-line-then-sentinel", 1, "1:home-root\nCLEAN 3\n", "", {"LEAK", "LEAK_SCAN_ERROR"}),
    ("killed-by-signal", -9, "", "", {"LEAK_SCAN_ERROR"}),
]


def test_scanner_result_table_has_both_outcomes() -> None:
    # Table contract: at least one accepting and one refusing row.
    outcomes = [o for *_, o in SCANNER_RESULTS]
    assert {"OK"} in outcomes and any("OK" not in o for o in outcomes)


@pytest.mark.parametrize(("case", "rc", "stdout", "stderr", "expected"), SCANNER_RESULTS, ids=[r[0] for r in SCANNER_RESULTS])
def test_scanner_passes_only_on_exit_1_with_the_clean_sentinel(
    tmp_path: Path, case: str, rc: int, stdout: str, stderr: str, expected: set[str]
) -> None:
    cfg_path, cfg = _cfg(tmp_path)
    log = tmp_path / "scan.log"
    script = _fake_scanner(log, rc=rc, stdout=stdout, stderr=stderr)
    if rc < 0:
        script = script.replace(f"sys.exit({rc})", "import os, signal; os.kill(os.getpid(), signal.SIGKILL)")
    repo = audit_repo(tmp_path, cfg, extra={cfg["leak_scan_script"]: script})
    fake = _ok_fake()
    submit, got, out, _ = _submit(tmp_path, repo, cfg_path, fake)
    assert got in {exit_code(submit, name) for name in expected}, (case, got, out[-500:])
    if "OK" not in expected:
        assert fake.calls == [], case
    else:
        assert len(fake.find("POST", BATCHES)) == 1


def test_personal_path_lines_are_dropped_before_scan_and_send(tmp_path: Path) -> None:
    # [C1] the line goes; the module (and the line after it) is still audited.
    cfg_path, cfg = _cfg(tmp_path)
    body = module_source("ALPHA_MARKER_51c2", "alpha_fn") + f'HINT = "{HOME_LINE_PATH}"\nAFTER = "KEPT_LINE_MARKER"\n'
    repo = audit_repo(tmp_path, cfg, extra={"src/backend/app/alpha.py": body})
    fake = _ok_fake()
    submit, rc, out, _ = _submit(tmp_path, repo, cfg_path, fake)
    assert rc == exit_code(submit, "OK"), out
    sent = fake.outbound_text()
    assert "someone-private" not in sent
    assert "KEPT_LINE_MARKER" in sent


def test_untracked_denied_and_linked_content_never_leaves_the_runner(tmp_path: Path) -> None:
    cfg_path, cfg = _cfg(tmp_path, module_globs=["**/*"])
    outside = tmp_path / "outside.py"
    outside.write_text("OUTSIDE_LINK_MARKER = 1\n", encoding="utf-8")
    extra = {
        "data/legal_corpus/importer.py": "from app import alpha  # DENIED_CALLER_MARKER\n",
        "docs/evidence/run.py": "import alpha  # EVIDENCE_MARKER\n",
        ".env": "API_KEY=SECRET_ENV_MARKER\n",
        "src/backend/tests/fixtures/cassettes/a.yaml": "CASSETTE_MARKER\n",
    }
    repo = audit_repo(
        tmp_path,
        cfg,
        extra=extra,
        untracked={"src/backend/app/untracked.py": "from app import alpha  # UNTRACKED_MARKER\n"},
        symlinks={"src/backend/app/link.py": str(outside)},
    )
    fake = _ok_fake()
    submit, rc, out, _ = _submit(tmp_path, repo, cfg_path, fake)
    assert rc == exit_code(submit, "OK"), out
    sent = fake.outbound_text()
    for m in ("DENIED_CALLER_MARKER", "EVIDENCE_MARKER", "SECRET_ENV_MARKER", "CASSETTE_MARKER",
              "UNTRACKED_MARKER", "OUTSIDE_LINK_MARKER"):
        assert m not in sent, m


def test_huge_module_is_capped_at_max_module_chars(tmp_path: Path) -> None:
    # [F6] a 2 MB single-line module is truncated, not shipped whole.
    cfg_path, cfg = _cfg(tmp_path)
    huge = module_source("ALPHA_MARKER_51c2", "alpha_fn") + "BLOB = '" + "Q" * 2_000_000 + "'\n"
    repo = audit_repo(tmp_path, cfg, extra={"src/backend/app/alpha.py": huge})
    fake = _ok_fake()
    submit, rc, out, _ = _submit(tmp_path, repo, cfg_path, fake)
    assert rc == exit_code(submit, "OK"), out[-500:]
    for r in created_requests(fake):
        assert longest_run(request_text(r), "Q") <= cfg["max_module_chars"]


def test_undecodable_bytes_never_reach_the_wire(tmp_path: Path) -> None:
    # Encoding attacks: invalid UTF-8, NUL, an encoded lone surrogate, bidi.
    cfg_path, cfg = _cfg(tmp_path)
    raw = module_source("ALPHA_MARKER_51c2", "alpha_fn").encode() + b"X = '\xff\xfe\x00\xed\xa0\x80'\nY = '\xe2\x80\xae'\n"
    repo = audit_repo(tmp_path, cfg, extra={"src/backend/app/alpha.py": raw})
    fake = _ok_fake()
    submit, rc, out, _ = _submit(tmp_path, repo, cfg_path, fake)
    assert rc == exit_code(submit, "OK"), out[-500:]
    for call in fake.calls:
        doc = json.loads(call.body.decode("utf-8"))  # strict UTF-8 JSON
        for leaf in string_leaves(doc):
            assert "\x00" not in leaf
            assert not any(0xD800 <= ord(ch) <= 0xDFFF for ch in leaf)


# --- [C5] budget -------------------------------------------------------------------------------------


def _worst_case(cfg: dict[str, Any], n: int, tokens: int) -> float:
    prices = cfg["prices_usd_per_mtok"]
    return (n * tokens * prices["input"] + n * cfg["max_tokens"] * prices["output"]) / 1_000_000


def test_count_tokens_runs_on_exactly_the_submitted_payloads_first(tmp_path: Path) -> None:
    cfg_path, cfg = _cfg(tmp_path)
    repo = audit_repo(tmp_path, cfg)
    fake = _ok_fake()
    submit, rc, out, _ = _submit(tmp_path, repo, cfg_path, fake)
    assert rc == exit_code(submit, "OK"), out
    reqs = created_requests(fake)
    counts = fake.find("POST", COUNT_TOKENS)
    keys = ("model", "system", "messages")
    sent = sorted(json.dumps({k: r["params"].get(k) for k in keys}, sort_keys=True) for r in reqs)
    counted = sorted(json.dumps({k: c.json().get(k) for k in keys}, sort_keys=True) for c in counts)
    assert counted == sent
    create_index = fake.calls.index(fake.find("POST", BATCHES)[0])
    assert all(fake.calls.index(c) < create_index for c in counts)


@pytest.mark.parametrize("side", ["just-over", "just-under"])
def test_budget_ceiling_is_enforced_before_the_batch_exists(tmp_path: Path, side: str) -> None:
    tokens = 200_000
    probe_path, probe = _cfg(tmp_path)
    n = len(STD_MODULES) + 1
    worst = _worst_case(probe, n, tokens)
    ceiling = worst * (1 - 1e-6) if side == "just-over" else worst * (1 + 1e-6)
    cfg_path, cfg = _cfg(tmp_path, budget_ceiling_usd=ceiling)
    repo = audit_repo(tmp_path, cfg)
    fake = _ok_fake(tokens=tokens)
    submit, rc, out, artifact = _submit(tmp_path, repo, cfg_path, fake)
    assert len(fake.find("POST", COUNT_TOKENS)) == n
    if side == "just-over":
        assert rc == exit_code(submit, "BUDGET_EXCEEDED")
        _assert_error_line(out, "BUDGET_EXCEEDED")
        assert fake.find("POST", BATCHES) == []
        assert not artifact.exists()
    else:
        assert rc == exit_code(submit, "OK"), out
        assert len(fake.find("POST", BATCHES)) == 1
        assert f"{worst:.2f}" in summary_text(tmp_path)  # worst case logged


def test_stale_price_table_refuses_without_creating_a_batch(tmp_path: Path) -> None:
    review_by = (_utc_today() - dt.timedelta(days=2)).isoformat()
    cfg_path, cfg = _cfg(tmp_path, price_review_by=review_by)
    repo = audit_repo(tmp_path, cfg)
    fake = _ok_fake()
    submit, rc, out, artifact = _submit(tmp_path, repo, cfg_path, fake)
    assert rc == exit_code(submit, "PRICES_STALE")
    _assert_error_line(out, "PRICES_STALE")
    assert review_by in out  # honest: says which date expired
    assert fake.find("POST", BATCHES) == []
    assert not artifact.exists()


# --- [C4, C6] fail closed before the network ----------------------------------------------------------


@pytest.mark.parametrize("value", [None, "", "   \n"], ids=["unset", "empty", "blank"])
def test_missing_secret_fails_before_any_request(tmp_path: Path, value: str | None, net: list[str]) -> None:
    cfg_path, cfg = _cfg(tmp_path)
    repo = audit_repo(tmp_path, cfg)
    env = audit_env(tmp_path)
    env.pop(SECRET_NAME)
    if value is not None:
        env[SECRET_NAME] = value
    fake = _ok_fake()
    submit, rc, out, _ = _submit(tmp_path, repo, cfg_path, fake, env=env)
    assert rc == exit_code(submit, "MISSING_SECRET")
    _assert_error_line(out, SECRET_NAME)
    assert fake.calls == [] and net == []


def test_bad_config_fails_before_any_request(tmp_path: Path, net: list[str]) -> None:
    cfg_path, cfg = _cfg(tmp_path)
    repo = audit_repo(tmp_path, cfg)
    cfg_path.write_text(json.dumps({**cfg, "max_tokens": "lots"}), encoding="utf-8")
    fake = _ok_fake()
    submit, rc, out, _ = _submit(tmp_path, repo, cfg_path, fake)
    assert rc == exit_code(submit, "CONFIG")
    assert "max_tokens" in out
    assert fake.calls == [] and net == []


def test_zero_modules_fails_before_any_request(tmp_path: Path, net: list[str]) -> None:
    cfg_path, cfg = _cfg(tmp_path, module_globs=["nomatch/**/*.py"])
    repo = audit_repo(tmp_path, cfg)
    fake = _ok_fake()
    submit, rc, out, artifact = _submit(tmp_path, repo, cfg_path, fake)
    assert rc == exit_code(submit, "NO_MODULES")
    _assert_error_line(out, "NO_MODULES")
    assert fake.calls == [] and net == []
    assert not artifact.exists()


def test_zero_modules_cli_runs_isolated_and_offline(tmp_path: Path) -> None:
    # [F12] the real entry point under `python3 -I` (as the workflow runs it).
    submit = require("submit")
    cfg_path, cfg = _cfg(tmp_path, module_globs=["nomatch/**/*.py"])
    repo = audit_repo(tmp_path, cfg)
    env = audit_env(tmp_path)
    env.update({"HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9", "NO_PROXY": ""})
    proc = subprocess.run(
        [python_exe(), "-I", str(AUDIT_DIR / "submit.py"), "--repo", str(repo), "--config", str(cfg_path),
         "--artifact", str(tmp_path / "a.json")],
        env=env, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == exit_code(submit, "NO_MODULES"), proc.stderr[-1000:]
    assert "NO_MODULES" in proc.stdout + proc.stderr


def _error_body(kind: str) -> bytes:
    return jbytes({"type": "error", "error": {"type": kind, "message": "nope"}})


def _raise(exc: Exception) -> Any:
    def handler(call: Call) -> Any:
        raise exc
    return handler


API_FAILURES = [
    ("count-500", "POST", COUNT_TOKENS, lambda c: (500, _error_body("api_error"))),
    ("count-401", "POST", COUNT_TOKENS, lambda c: (401, _error_body("authentication_error"))),
    ("count-timeout", "POST", COUNT_TOKENS, _raise(TimeoutError("timed out"))),
    ("count-not-json", "POST", COUNT_TOKENS, lambda c: (200, b"<html>gateway</html>")),
    ("count-missing-field", "POST", COUNT_TOKENS, lambda c: (200, jbytes({"tokens": 5}))),
    ("count-negative", "POST", COUNT_TOKENS, lambda c: (200, jbytes({"input_tokens": -5}))),
    ("count-string", "POST", COUNT_TOKENS, lambda c: (200, jbytes({"input_tokens": "lots"}))),
    ("create-500", "POST", BATCHES, lambda c: (500, _error_body("api_error"))),
    ("create-400-spend-limit", "POST", BATCHES, lambda c: (400, _error_body("invalid_request_error"))),
    ("create-oserror", "POST", BATCHES, _raise(OSError("connection reset"))),
    ("create-no-id", "POST", BATCHES, lambda c: (200, jbytes({"type": "message_batch"}))),
]


@pytest.mark.parametrize(("case", "method", "pattern", "handler"), API_FAILURES, ids=[a[0] for a in API_FAILURES])
def test_api_failures_fail_closed_without_leaking_the_key(
    tmp_path: Path, case: str, method: str, pattern: str, handler: Any
) -> None:
    cfg_path, cfg = _cfg(tmp_path)
    repo = audit_repo(tmp_path, cfg)
    fake = _ok_fake()
    fake.route(method, pattern, handler)
    submit, rc, out, artifact = _submit(tmp_path, repo, cfg_path, fake)
    assert rc == exit_code(submit, "API_ERROR"), (case, rc, out[-800:])
    _assert_error_line(out, "API_ERROR")
    assert "Traceback" not in out
    assert not artifact.exists()
    if pattern == COUNT_TOKENS:
        assert fake.find("POST", BATCHES) == []
    _assert_no_secret(tmp_path, out)


# --- [C8] retention when submit fails after the batch exists ----------------------------------------------


def _retrieve_sequence(fake: FakeHTTP, statuses: list[str]) -> None:
    state = {"i": 0}

    def handler(call: Call) -> tuple[int, bytes]:
        status = statuses[min(state["i"], len(statuses) - 1)]
        state["i"] += 1
        return 200, jbytes(batch_object(status, {"canceled": 3} if status == "ended" else {"processing": 3}))

    fake.route("GET", BATCH, handler)


def _unwritable_artifact(tmp: Path) -> Path:
    blocker = tmp / "blocker"
    blocker.write_text("a file, not a directory", encoding="utf-8")
    return blocker / "wiring-audit-batch.json"


def test_failure_after_create_logs_id_first_then_cancels_polls_and_deletes(tmp_path: Path) -> None:
    cfg_path, cfg = _cfg(tmp_path)
    repo = audit_repo(tmp_path, cfg)
    fake = _ok_fake()
    _retrieve_sequence(fake, ["canceling", "canceling", "ended"])
    snapshot: dict[str, str] = {}

    def watch(call: Call) -> None:
        if "created" in snapshot and "next" not in snapshot:
            snapshot["next"] = summary_text(tmp_path)
        if call.method == "POST" and call.path == "/v1/messages/batches":
            snapshot["created"] = "yes"

    fake.on_call.append(watch)
    submit, rc, out, _ = _submit(tmp_path, repo, cfg_path, fake, artifact=_unwritable_artifact(tmp_path))
    assert rc == exit_code(submit, "SUBMIT_FAILED_AFTER_CREATE"), out[-800:]
    _assert_error_line(out, "SUBMIT_FAILED_AFTER_CREATE")
    assert BATCH_ID in snapshot.get("next", ""), "batch id not in the job summary before the next API call"
    assert BATCH_ID in out
    cancel = fake.find("POST", CANCEL)
    deletes = fake.find("DELETE", BATCH)
    gets = fake.find("GET", BATCH)
    assert len(cancel) == 1 and len(deletes) == 1 and len(gets) >= 3
    order = fake.calls.index
    assert order(cancel[0]) < order(gets[-1]) < order(deletes[0])
    assert all(BATCH_ID in c.path for c in cancel + deletes + gets)


def test_cleanup_cancel_timeout_records_the_id_and_exits_loudly(tmp_path: Path, clock: Any) -> None:
    cfg_path, cfg = _cfg(tmp_path)
    repo = audit_repo(tmp_path, cfg)
    fake = _ok_fake()
    _retrieve_sequence(fake, ["canceling"])
    start = clock.now
    submit, rc, out, _ = _submit(tmp_path, repo, cfg_path, fake, artifact=_unwritable_artifact(tmp_path))
    assert rc == exit_code(submit, "CANCEL_TIMEOUT"), out[-800:]
    _assert_error_line(out, "CANCEL_TIMEOUT")
    assert BATCH_ID in out and BATCH_ID in summary_text(tmp_path)
    assert fake.unexpected == []  # bounded: no runaway polling
    assert clock.now - start >= cfg["cancel_timeout_seconds"]
    assert fake.find("DELETE", BATCH) == []


def test_cleanup_delete_failure_is_its_own_loud_error(tmp_path: Path) -> None:
    cfg_path, cfg = _cfg(tmp_path)
    repo = audit_repo(tmp_path, cfg)
    fake = _ok_fake()
    _retrieve_sequence(fake, ["ended"])
    fake.route("DELETE", BATCH, lambda c: (500, _error_body("api_error")))
    submit, rc, out, _ = _submit(tmp_path, repo, cfg_path, fake, artifact=_unwritable_artifact(tmp_path))
    assert rc in {exit_code(submit, "SUBMIT_FAILED_AFTER_CREATE"), exit_code(submit, "DELETE_FAILED")}
    assert "DELETE_FAILED" in out and BATCH_ID in out


# --- [C9, F6] the default transport ------------------------------------------------------------------


class _Resp:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body
        self.headers: dict[str, str] = {"content-type": "application/json"}

    def read(self, n: int = -1) -> bytes:
        data, self._body = (self._body, b"") if n is None or n < 0 else (self._body[:n], self._body[n:])
        return data

    def getcode(self) -> int:
        return self.status

    def __enter__(self) -> "_Resp":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def close(self) -> None:
        return None


def test_default_transport_is_urllib_with_a_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.request

    cfg_path, cfg = _cfg(tmp_path)
    repo = audit_repo(tmp_path, cfg)
    fake = _ok_fake()
    timeouts: list[Any] = []

    def opener_open(self: Any, fullurl: Any, data: Any = None, timeout: Any = None) -> _Resp:
        timeouts.append(timeout)
        if isinstance(fullurl, urllib.request.Request):
            method, url = fullurl.get_method(), fullurl.full_url
            headers, body = dict(fullurl.header_items()), data if data is not None else fullurl.data
        else:
            method, url, headers, body = ("POST" if data else "GET"), fullurl, {}, data
        status, payload = fake(method, url, headers, body)
        return _Resp(status, payload)

    def urlopen(url: Any, data: Any = None, timeout: Any = None, **kwargs: Any) -> _Resp:
        return opener_open(None, url, data, timeout)

    # Either entry point is accepted; both replace the autouse network ban.
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", opener_open)
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    submit = require("submit")
    rc, out = run_main(
        submit,
        ["--repo", str(repo), "--config", str(cfg_path), "--artifact", str(tmp_path / "a.json")],
        env=audit_env(tmp_path),
    )
    assert rc == exit_code(submit, "OK"), out[-800:]
    assert timeouts, "no request went through urllib"
    assert all(isinstance(t, (int, float)) and t > 0 for t in timeouts), timeouts
    assert len(fake.find("POST", BATCHES)) == 1


# Exit codes exercised above. Adding a code without a test fails here (T9 parity).
COVERED = {"OK", "CONFIG", "NO_MODULES", "MISSING_SECRET", "LEAK", "LEAK_SCAN_ERROR", "PRICES_STALE",
           "BUDGET_EXCEEDED", "API_ERROR", "SUBMIT_FAILED_AFTER_CREATE", "CANCEL_TIMEOUT", "DELETE_FAILED"}


def test_every_submit_exit_code_has_a_test() -> None:
    submit = require("submit")
    assert set(submit.EXIT_CODES) <= COVERED, sorted(set(submit.EXIT_CODES) - COVERED)
