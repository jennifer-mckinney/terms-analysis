"""Weekly wiring audit: the collect job (card #224, ADR 0002).

ADR 0002 condition numbers are in brackets on every test. Interface:
``tests/wiring_audit_support.py``. Each test first runs the real submit with
a fake transport to produce the hand-off artifact, then runs collect against
a simulated batch, so the artifact format is never restated here.

[C6] every failure mode exits with its own code and message and files
nothing; a run without the canary finding fails. [C7] model output is data:
strict schema, truncated, escaped, REST-posted from validated fields, never
through a shell; dedupe key, cap, summary mode. [C8] the batch is deleted on
every exit path; a batch that never ends is cancelled, polled (bounded),
then deleted, or the run fails with the id recorded.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Callable

import pytest

from tests.wiring_audit_support import (
    BATCH,
    BATCH_ID,
    CANARY_MARKER,
    CANARY_SYMBOL,
    CANCEL,
    FAKE_GH_TOKEN,
    FAKE_KEY,
    HOME_LINE_PATH,
    ISSUES,
    RESULTS,
    SECRET_NAME,
    STD_MODULES,
    Call,
    FakeHTTP,
    audit_env,
    audit_repo,
    ban_network,
    batch_object,
    created_requests,
    exit_code,
    finding_key,
    forbidden_chars,
    install_clock,
    jbytes,
    lines_outside_fences,
    longest_run,
    marker,
    request_text,
    require,
    route_submit,
    run_main,
    summary_text,
    write_config,
)

ALPHA, BETA = sorted(STD_MODULES)


@pytest.fixture(autouse=True)
def net(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    return ban_network(monkeypatch)


@pytest.fixture(autouse=True)
def clock(monkeypatch: pytest.MonkeyPatch) -> Any:
    return install_clock(monkeypatch)


# --- set-up: a real submit, then a simulated batch ----------------------------------------------


class Prepared:
    def __init__(self, tmp: Path, cfg_path: Path, cfg: dict[str, Any], artifact: Path, ids: dict[str, str], canary_id: str):
        self.tmp, self.cfg_path, self.cfg, self.artifact = tmp, cfg_path, cfg, artifact
        self.ids = ids  # module path -> custom_id
        self.canary_id = canary_id

    @property
    def all_ids(self) -> list[str]:
        return [*self.ids.values(), self.canary_id]


def _prepare(tmp: Path, **overrides: Any) -> Prepared:
    base: dict[str, Any] = {
        "module_globs": ["src/**/*.py"],
        "price_review_by": (dt.datetime.now(dt.timezone.utc).date() + dt.timedelta(days=30)).isoformat(),
    }
    base.update(overrides)
    cfg_path, cfg = write_config(tmp, **base)
    repo = audit_repo(tmp, cfg)
    fake = FakeHTTP()
    route_submit(fake)
    submit = require("submit")
    artifact = tmp / "artifact" / "wiring-audit-batch.json"
    rc, out = run_main(submit, ["--repo", str(repo), "--config", str(cfg_path), "--artifact", str(artifact)],
                       http=fake, env=audit_env(tmp))
    assert rc == exit_code(submit, "OK"), out[-800:]
    ids: dict[str, str] = {}
    canary_id = ""
    for req in created_requests(fake):
        text = request_text(req)
        if CANARY_MARKER in text:
            canary_id = req["custom_id"]
        for path, (mark, _) in STD_MODULES.items():
            if mark in text:
                ids[path] = req["custom_id"]
    assert canary_id and len(ids) == len(STD_MODULES)
    (tmp / "step-summary.md").unlink(missing_ok=True)
    return Prepared(tmp, cfg_path, cfg, artifact, ids, canary_id)


def _finding(kind: str = "zero_caller_public", severity: str = "MEDIUM", symbol: str = "alpha_fn",
             evidence: str = "no caller found", recommendation: str = "wire it or delete it") -> dict[str, str]:
    return {"kind": kind, "severity": severity, "symbol": symbol, "evidence": evidence, "recommendation": recommendation}


USAGE = {"input_tokens": 2_000_000, "output_tokens": 300_000, "cache_read_input_tokens": 1_000_000,
         "cache_creation_input_tokens": 0}


def _succeeded(cid: str, text: str, *, stop: str = "end_turn") -> dict[str, Any]:
    return {
        "custom_id": cid,
        "result": {
            "type": "succeeded",
            "message": {
                "id": "msg_" + cid[:20], "type": "message", "role": "assistant", "model": "m",
                "content": [{"type": "text", "text": text}],
                "stop_reason": stop, "stop_sequence": None, "usage": dict(USAGE),
            },
        },
    }


class Sim:
    """A simulated ended batch plus the GitHub issues endpoint."""

    def __init__(self, prep: Prepared) -> None:
        self.prep = prep
        self.outputs: dict[str, Any] = {cid: None for cid in prep.all_ids}
        self.lines: list[dict[str, Any]] | None = None
        self.statuses = ["ended"]
        self.counts: dict[str, int] | None = None
        self.existing_issues: list[dict[str, Any]] = []
        self.fake = FakeHTTP()
        self._route()

    def module_output(self, path: str, findings: list[dict[str, str]]) -> None:
        self.outputs[self.prep.ids[path]] = {"module": path, "findings": findings}

    def default_text(self, cid: str) -> str:
        if self.outputs.get(cid) is not None:
            return json.dumps(self.outputs[cid])
        if cid == self.prep.canary_id:
            canary = _finding(kind=self.prep.cfg["canary_expected_kind"], severity="HIGH", symbol=CANARY_SYMBOL)
            return json.dumps({"module": self.prep.cfg["canary_fixture"], "findings": [canary]})
        path = next(p for p, c in self.prep.ids.items() if c == cid)
        return json.dumps({"module": path, "findings": []})

    def result_lines(self) -> list[dict[str, Any]]:
        if self.lines is not None:
            return self.lines
        return [_succeeded(cid, self.default_text(cid)) for cid in self.prep.all_ids]

    def _route(self) -> None:
        state = {"i": 0}

        def retrieve(call: Call) -> tuple[int, bytes]:
            status = self.statuses[min(state["i"], len(self.statuses) - 1)]
            state["i"] += 1
            counts = self.counts if self.counts is not None else {"succeeded": len(self.prep.all_ids)}
            if status != "ended":
                counts = {"processing": len(self.prep.all_ids)}
            return 200, jbytes(batch_object(status, counts))

        def results(call: Call) -> tuple[int, bytes]:
            return 200, ("\n".join(json.dumps(x) for x in self.result_lines()) + "\n").encode("utf-8")

        def create_issue(call: Call) -> tuple[int, bytes]:
            n = 100 + len(self.fake.find("POST", ISSUES))
            return 201, jbytes({"number": n, "html_url": f"https://github.com/example-owner/example-repo/issues/{n}"})

        self.fake.route("GET", BATCH, retrieve)
        self.fake.route("GET", RESULTS, results)
        self.fake.route("POST", CANCEL, lambda c: (200, jbytes(batch_object("canceling"))))
        self.fake.route("DELETE", BATCH, lambda c: (200, jbytes({"id": BATCH_ID, "type": "message_batch_deleted"})))
        self.fake.route("GET", ISSUES, lambda c: (200, jbytes(self.existing_issues)))
        self.fake.route("POST", ISSUES, create_issue)

    # -- views
    def issue_posts(self) -> list[dict[str, Any]]:
        return [c.json() for c in self.fake.find("POST", ISSUES)]

    def deletes(self) -> list[Call]:
        return self.fake.find("DELETE", BATCH)


def _collect(sim: Sim, *, env: dict[str, str] | None = None, artifact: Path | None = None,
             artifacts: list[Path] | None = None) -> tuple[Any, int, str]:
    collect = require("collect")
    prep = sim.prep
    paths = artifacts if artifacts is not None else [artifact or prep.artifact]
    argv = ["--config", str(prep.cfg_path)]
    for path in paths:  # ruling 1: one --artifact per uncollected submit run, newest last
        argv += ["--artifact", str(path)]
    rc, out = run_main(
        collect,
        argv,
        http=sim.fake,
        env=audit_env(prep.tmp, GITHUB_TOKEN=FAKE_GH_TOKEN) if env is None else env,
    )
    return collect, rc, out


def _key(path: str, kind: str, symbol: str) -> str:
    return finding_key(path, kind, symbol)


def _single_marker_posts(sim: Sim) -> list[dict[str, Any]]:
    return [p for p in sim.issue_posts() if len(re.findall(r"<!-- wiring-audit:[0-9a-f]{16} -->", p["body"])) == 1]


# --- [C6, C7] success path -----------------------------------------------------------------------------


def _three_findings(sim: Sim) -> None:
    sim.module_output(ALPHA, [_finding(severity="MEDIUM", symbol="alpha_fn"), _finding(kind="other", severity="LOW", symbol="alpha_low")])
    sim.module_output(BETA, [_finding(kind="unwired_entry_point", severity="HIGH", symbol="beta_main")])


def test_summary_mode_files_exactly_one_issue_with_every_medium_plus_finding(tmp_path: Path) -> None:
    prep = _prepare(tmp_path)  # shipped card_mode is "summary"
    sim = Sim(prep)
    _three_findings(sim)
    collect, rc, out = _collect(sim)
    assert rc == exit_code(collect, "OK"), out[-800:]
    posts = sim.issue_posts()
    assert len(posts) == 1
    body = posts[0]["body"]
    assert marker(_key(ALPHA, "zero_caller_public", "alpha_fn")) in body
    assert marker(_key(BETA, "unwired_entry_point", "beta_main")) in body
    assert marker(_key(ALPHA, "other", "alpha_low")) not in body  # below the threshold
    assert CANARY_SYMBOL not in body  # the canary is synthetic, never filed
    assert set(posts[0]) <= {"title", "body", "labels"}
    assert posts[0]["labels"] == prep.cfg["labels"]
    assert sim.fake.unexpected == []
    # [C8] deleted once, after filing.
    assert len(sim.deletes()) == 1
    assert sim.fake.calls.index(sim.deletes()[0]) > sim.fake.calls.index(sim.fake.find("POST", ISSUES)[0])


def test_credentials_go_only_to_their_own_api(tmp_path: Path) -> None:
    prep = _prepare(tmp_path)
    sim = Sim(prep)
    _three_findings(sim)
    collect, rc, out = _collect(sim)
    assert rc == exit_code(collect, "OK"), out[-800:]
    for call in sim.fake.calls:
        headers = " ".join(call.headers.values())
        if call.is_github:
            assert FAKE_GH_TOKEN in call.headers.get("authorization", "")
            assert FAKE_KEY not in headers
        else:
            assert call.headers.get("x-api-key") == FAKE_KEY
            assert FAKE_GH_TOKEN not in headers
    assert FAKE_KEY not in out and FAKE_GH_TOKEN not in out and FAKE_KEY not in summary_text(tmp_path)


def test_actual_cost_is_summed_from_usage_and_logged(tmp_path: Path) -> None:
    prep = _prepare(tmp_path)
    sim = Sim(prep)
    collect, rc, out = _collect(sim)
    assert rc == exit_code(collect, "OK"), out[-800:]
    prices = prep.cfg["prices_usd_per_mtok"]
    per = (USAGE["input_tokens"] * prices["input"] + USAGE["output_tokens"] * prices["output"]
           + USAGE["cache_read_input_tokens"] * prices["cache_read"]) / 1_000_000
    expected = per * len(prep.all_ids)
    assert f"{expected:.2f}" in summary_text(tmp_path)


@pytest.mark.parametrize("kind", ["errored", "expired", "canceled"])
def test_partial_batch_cost_counts_only_successful_requests(tmp_path: Path, kind: str) -> None:
    prep = _prepare(tmp_path)
    sim = Sim(prep)
    _errored(kind)(sim)
    collect, rc, out = _collect(sim)
    assert rc == exit_code(collect, "PARTIAL"), out[-800:]
    prices = prep.cfg["prices_usd_per_mtok"]
    per = (USAGE["input_tokens"] * prices["input"] + USAGE["output_tokens"] * prices["output"]
           + USAGE["cache_read_input_tokens"] * prices["cache_read"]) / 1_000_000
    expected = per * (len(prep.all_ids) - 1)
    assert f"${expected:.2f}" in summary_text(tmp_path)
    assert sim.issue_posts() == []
    assert len(sim.deletes()) == 1


@pytest.mark.parametrize("usage", [
    None, [], {}, {"input_tokens": 0}, {"output_tokens": 0},
    *[{**USAGE, key: value} for key in USAGE for value in (-1, True, 1.5, "1", None)],
])
def test_successful_request_with_invalid_usage_fails_closed(tmp_path: Path, usage: Any) -> None:
    prep = _prepare(tmp_path, card_mode="cards")
    sim = Sim(prep)
    line = _succeeded(prep.ids[ALPHA], sim.default_text(prep.ids[ALPHA]))
    line["result"]["message"]["usage"] = usage
    _set_line(sim, _alpha, lambda c: line)
    collect, rc, out = _collect(sim)
    assert rc == exit_code(collect, "API_ERROR"), out[-800:]
    assert sim.issue_posts() == []
    assert len(sim.deletes()) == 1


def test_cards_mode_files_one_issue_per_finding(tmp_path: Path) -> None:
    prep = _prepare(tmp_path, card_mode="cards")
    sim = Sim(prep)
    _three_findings(sim)
    collect, rc, out = _collect(sim)
    assert rc == exit_code(collect, "OK"), out[-800:]
    posts = sim.issue_posts()
    assert len(posts) == 2 == len(_single_marker_posts(sim))
    bodies = "\n".join(p["body"] for p in posts)
    assert marker(_key(ALPHA, "zero_caller_public", "alpha_fn")) in bodies
    assert marker(_key(BETA, "unwired_entry_point", "beta_main")) in bodies


def test_severity_threshold_comes_from_config(tmp_path: Path) -> None:
    prep = _prepare(tmp_path, card_mode="cards", card_threshold="HIGH")
    sim = Sim(prep)
    _three_findings(sim)
    collect, rc, out = _collect(sim)
    assert rc == exit_code(collect, "OK"), out[-800:]
    posts = sim.issue_posts()
    assert len(posts) == 1
    assert marker(_key(BETA, "unwired_entry_point", "beta_main")) in posts[0]["body"]


def test_dedupe_key_is_stable_and_skips_open_issues_and_repeats(tmp_path: Path) -> None:
    prep = _prepare(tmp_path, card_mode="cards")
    sim = Sim(prep)
    alpha = _finding(severity="MEDIUM", symbol="alpha_fn")
    sim.module_output(ALPHA, [alpha, dict(alpha, evidence="reworded by the model")])
    sim.module_output(BETA, [_finding(kind="unwired_entry_point", severity="HIGH", symbol="beta_main")])
    sim.existing_issues = [{"number": 7, "state": "open", "title": "old",
                            "body": "x\n" + marker(_key(ALPHA, "zero_caller_public", "alpha_fn")) + "\n"}]
    collect, rc, out = _collect(sim)
    assert rc == exit_code(collect, "OK"), out[-800:]
    posts = sim.issue_posts()
    assert len(posts) == 1
    assert marker(_key(BETA, "unwired_entry_point", "beta_main")) in posts[0]["body"]


def test_cards_per_run_are_capped_by_config(tmp_path: Path) -> None:
    prep = _prepare(tmp_path, card_mode="cards", max_cards_per_run=2)
    sim = Sim(prep)
    sim.module_output(ALPHA, [_finding(symbol=f"fn_{i}") for i in range(5)])
    collect, rc, out = _collect(sim)
    assert rc == exit_code(collect, "OK"), out[-800:]
    assert len(_single_marker_posts(sim)) == 2
    assert len(sim.issue_posts()) <= 3


# --- [C7] model output is data -----------------------------------------------------------------------------

HOSTILE_SYMBOL = "x`; rm -rf / #1 @owner\n# forged heading"
HOSTILE_EVIDENCE = ("```\n# injected heading\n<img src=x onerror=alert(1)>\n@owner #1 "
                    + "A" * 50_000 + "  ‮\x00\r\x1b[31m")
HOSTILE_RECOMMENDATION = "[click](javascript:alert(1)) https://evil.example/x ~~~\n<script>x</script>"


def test_hostile_finding_text_is_truncated_escaped_and_never_shelled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prep = _prepare(tmp_path, card_mode="cards")
    sim = Sim(prep)
    sim.module_output(ALPHA, [_finding(symbol=HOSTILE_SYMBOL, evidence=HOSTILE_EVIDENCE, recommendation=HOSTILE_RECOMMENDATION)])
    spawned: list[Any] = []
    real_popen = subprocess.Popen

    class GuardPopen(real_popen):  # type: ignore[misc, valid-type]
        def __init__(self, args: Any, *a: Any, **kw: Any) -> None:
            spawned.append((args, kw.get("shell")))
            super().__init__(args, *a, **kw)

    monkeypatch.setattr(subprocess, "Popen", GuardPopen)
    import os as _os

    monkeypatch.setattr(_os, "system", lambda *a: spawned.append((a, True)) or 1)
    collect, rc, out = _collect(sim)
    assert rc == exit_code(collect, "OK"), out[-800:]
    posts = sim.issue_posts()
    assert len(posts) == 1
    post = posts[0]
    assert set(post) <= {"title", "body", "labels"} and post["labels"] == prep.cfg["labels"]
    limit = prep.cfg["max_field_chars"]
    for field in ("title", "body"):
        assert forbidden_chars(post[field], allow="\n" if field == "body" else "") == [], field
    assert len(post["title"]) <= 256
    assert longest_run(post["body"], "A") <= limit
    outside = "\n".join(lines_outside_fences(post["body"]) + [post["title"]])
    for needle in ("<img", "onerror", "<script", "javascript:", "rm -rf", "@owner", "# injected", "# forged"):
        assert needle not in outside, needle
    assert not re.search(r"(?<![\w&])#1\b", outside)
    # [C3] no shell anywhere; no hostile text in any argv.
    for args, shell in spawned:
        assert not shell
        flat = " ".join(map(str, args if isinstance(args, (list, tuple)) else [args]))
        assert "rm -rf" not in flat and "onerror" not in flat


def test_secret_or_home_path_in_evidence_is_not_republished(tmp_path: Path) -> None:
    # Attack sketch T5: the repo is public; the issue must not quote them.
    secret = "sk-" + "ant-api03-" + "Z" * 24
    prep = _prepare(tmp_path, card_mode="cards")
    sim = Sim(prep)
    sim.module_output(ALPHA, [_finding(evidence=f"token = '{secret}' at {HOME_LINE_PATH}")])
    collect, rc, out = _collect(sim)
    assert rc == exit_code(collect, "OK"), out[-800:]
    text = json.dumps(sim.issue_posts())
    assert secret not in text and "someone-private" not in text
    assert secret not in out


def test_module_identity_comes_from_the_batch_not_the_model(tmp_path: Path) -> None:
    prep = _prepare(tmp_path, card_mode="cards")
    sim = Sim(prep)
    sim.outputs[prep.ids[ALPHA]] = {"module": "../../etc/passwd @evil", "findings": [_finding()]}
    collect, rc, out = _collect(sim)
    # Review finding 5 (PR #282): one contract. The model's `module` is ignored;
    # the card names the module the artifact maps this custom_id to.
    assert rc == exit_code(collect, "OK"), out[-800:]
    posts = sim.issue_posts()
    assert len(posts) == 1
    assert ALPHA in posts[0]["title"] and f"`{ALPHA}`" in posts[0]["body"]
    text = json.dumps(posts)
    assert "etc/passwd" not in text and "@evil" not in text


# --- [C6] failure modes: own code, nothing filed, batch deleted -----------------------------------------


def _set_line(sim: Sim, cid_of: Callable[[Prepared], str], line: Callable[[str], dict[str, Any]]) -> None:
    cid = cid_of(sim.prep)
    sim.lines = [line(c) if c == cid else _succeeded(c, sim.default_text(c)) for c in sim.prep.all_ids]


def _alpha(p: Prepared) -> str:
    return p.ids[ALPHA]


def _bad_text(text: str) -> Callable[[Sim], None]:
    return lambda sim: _set_line(sim, _alpha, lambda c: _succeeded(c, text))


def _errored(kind: str) -> Callable[[Sim], None]:
    def apply(sim: Sim) -> None:
        if kind == "errored":
            res = {"type": "errored", "error": {"type": "error", "error": {"type": "invalid_request_error", "message": "x"}}}
        else:
            res = {"type": kind}
        _set_line(sim, _alpha, lambda c: {"custom_id": c, "result": res})
        sim.counts = {"succeeded": len(sim.prep.all_ids) - 1, kind: 1}
    return apply


def _missing(sim: Sim) -> None:
    sim.lines = [_succeeded(c, sim.default_text(c)) for c in sim.prep.all_ids if c != sim.prep.ids[ALPHA]]


def _duplicate(sim: Sim) -> None:
    lines = [_succeeded(c, sim.default_text(c)) for c in sim.prep.all_ids]
    sim.lines = lines + [lines[0]]


def _unknown(sim: Sim) -> None:
    sim.lines = [_succeeded(c, sim.default_text(c)) for c in sim.prep.all_ids] + [_succeeded("not-submitted", "{}")]


def _stop(reason: str) -> Callable[[Sim], None]:
    return lambda sim: _set_line(sim, _alpha, lambda c: _succeeded(c, sim.default_text(c), stop=reason))


def _no_canary(sim: Sim) -> None:
    sim.outputs[sim.prep.canary_id] = {"module": sim.prep.cfg["canary_fixture"], "findings": []}


def _canary_wrong_kind(sim: Sim) -> None:
    other = next(k for k in ("zero_caller_public", "other") if k != sim.prep.cfg["canary_expected_kind"])
    sim.outputs[sim.prep.canary_id] = {"module": sim.prep.cfg["canary_fixture"],
                                       "findings": [_finding(kind=other, symbol=CANARY_SYMBOL)]}


def _good(**change: Any) -> str:
    f = _finding()
    f.update(change)
    return json.dumps({"module": ALPHA, "findings": [f]})


FAILURES: list[tuple[str, Callable[[Sim], None], str]] = [
    ("errored-request", _errored("errored"), "PARTIAL"),
    ("expired-request", _errored("expired"), "PARTIAL"),
    ("canceled-request", _errored("canceled"), "PARTIAL"),
    ("missing-custom-id", _missing, "MISSING_OR_DUP"),
    ("duplicate-custom-id", _duplicate, "MISSING_OR_DUP"),
    ("unknown-custom-id", _unknown, "MISSING_OR_DUP"),
    ("stop-max-tokens", _stop("max_tokens"), "TRUNCATED_OR_REFUSED"),
    ("stop-refusal", _stop("refusal"), "TRUNCATED_OR_REFUSED"),
    ("stop-context-window", _stop("model_context_window_exceeded"), "TRUNCATED_OR_REFUSED"),
    ("not-json", _bad_text("Sure! Here are the findings: none"), "SCHEMA"),
    ("bad-kind", _bad_text(_good(kind="bogus")), "SCHEMA"),
    ("bad-severity", _bad_text(_good(severity="SEVERE")), "SCHEMA"),
    ("lowercase-severity", _bad_text(_good(severity="medium")), "SCHEMA"),
    ("missing-symbol", _bad_text(json.dumps({"module": ALPHA, "findings": [{"kind": "other", "severity": "LOW"}]})), "SCHEMA"),
    ("extra-key", _bad_text(_good(assignees="owner")), "SCHEMA"),
    ("findings-not-list", _bad_text(json.dumps({"module": ALPHA, "findings": "none"})), "SCHEMA"),
    ("missing-findings", _bad_text(json.dumps({"module": ALPHA})), "SCHEMA"),
    ("severity-wrong-type", _bad_text(_good(severity=3)), "SCHEMA"),
    ("canary-missing", _no_canary, "CANARY_MISSING"),
    ("canary-wrong-kind", _canary_wrong_kind, "CANARY_MISSING"),
]


@pytest.mark.parametrize(("case", "apply", "name"), FAILURES, ids=[f[0] for f in FAILURES])
def test_each_failure_mode_has_its_own_exit_files_nothing_and_deletes(
    tmp_path: Path, case: str, apply: Callable[[Sim], None], name: str
) -> None:
    prep = _prepare(tmp_path, card_mode="cards")
    sim = Sim(prep)
    sim.module_output(BETA, [_finding(kind="unwired_entry_point", severity="HIGH", symbol="beta_main")])
    apply(sim)
    collect, rc, out = _collect(sim)
    assert rc == exit_code(collect, name), (case, rc, out[-800:])
    assert name in out and "::error title=wiring-audit::" in out
    assert sim.issue_posts() == []  # file nothing
    assert len(sim.deletes()) == 1  # [C8] deleted on the failure path too
    if name in {"PARTIAL", "MISSING_OR_DUP", "TRUNCATED_OR_REFUSED", "SCHEMA"}:
        assert prep.ids[ALPHA] in out or "not-submitted" in out  # names the request


def test_batch_not_ended_is_cancelled_polled_deleted_and_fails(tmp_path: Path) -> None:
    prep = _prepare(tmp_path)
    sim = Sim(prep)
    sim.statuses = ["in_progress", "canceling", "canceling", "ended"]
    collect, rc, out = _collect(sim)
    assert rc == exit_code(collect, "BATCH_NOT_ENDED"), out[-800:]
    assert "BATCH_NOT_ENDED" in out
    assert sim.fake.find("GET", RESULTS) == []  # never reads results of an unfinished batch
    cancel, deletes = sim.fake.find("POST", CANCEL), sim.deletes()
    assert len(cancel) == 1 and len(deletes) == 1
    assert sim.fake.calls.index(cancel[0]) < sim.fake.calls.index(deletes[0])
    assert sim.issue_posts() == []


def test_cancel_that_never_ends_times_out_with_the_id_recorded(tmp_path: Path, clock: Any) -> None:
    prep = _prepare(tmp_path)
    sim = Sim(prep)
    sim.statuses = ["in_progress", "canceling"]
    start = clock.now
    collect, rc, out = _collect(sim)
    assert rc == exit_code(collect, "CANCEL_TIMEOUT"), out[-800:]
    assert BATCH_ID in out and BATCH_ID in summary_text(tmp_path)
    assert clock.now - start >= prep.cfg["cancel_timeout_seconds"]
    assert sim.fake.unexpected == []
    assert sim.issue_posts() == []


def test_delete_failure_after_filing_is_loud_and_keeps_the_cards(tmp_path: Path) -> None:
    prep = _prepare(tmp_path)
    sim = Sim(prep)
    _three_findings(sim)
    sim.fake.route("DELETE", BATCH, lambda c: (500, jbytes({"type": "error", "error": {"type": "api_error", "message": "x"}})))
    collect, rc, out = _collect(sim)
    assert rc == exit_code(collect, "DELETE_FAILED"), out[-800:]
    assert "DELETE_FAILED" in out and BATCH_ID in out
    assert len(sim.issue_posts()) == 1


def test_delete_failure_on_a_failure_path_is_reported_too(tmp_path: Path) -> None:
    prep = _prepare(tmp_path)
    sim = Sim(prep)
    _bad_text("not json")(sim)
    sim.fake.route("DELETE", BATCH, lambda c: (500, b"{}"))
    collect, rc, out = _collect(sim)
    assert rc in {exit_code(collect, "SCHEMA"), exit_code(collect, "DELETE_FAILED")}
    assert "SCHEMA" in out and "DELETE_FAILED" in out and BATCH_ID in out


@pytest.mark.parametrize(
    ("case", "responses", "calls", "name"),
    [
        ("500-then-ok", [500, 200], 2, "OK"),
        ("500-twice", [500, 500], 2, "API_ERROR"),
        ("overloaded-then-ok", [529, 200], 2, "OK"),
        ("invalid-request-not-retried", [400, 200], 1, "API_ERROR"),
        ("auth-not-retried", [401, 200], 1, "API_ERROR"),
    ],
)
def test_retrieve_retries_once_only_for_transient_errors(tmp_path: Path, case: str, responses: list[int], calls: int, name: str) -> None:
    prep = _prepare(tmp_path)
    sim = Sim(prep)
    state = {"i": 0}
    kinds = {500: "api_error", 529: "overloaded_error", 400: "invalid_request_error", 401: "authentication_error"}

    def retrieve(call: Call) -> tuple[int, bytes]:
        status = responses[min(state["i"], len(responses) - 1)]
        state["i"] += 1
        if status != 200:
            return status, jbytes({"type": "error", "error": {"type": kinds[status], "message": "x"}})
        return 200, jbytes(batch_object("ended", {"succeeded": len(prep.all_ids)}))

    sim.fake.route("GET", BATCH, retrieve)
    collect, rc, out = _collect(sim)
    assert rc == exit_code(collect, name), (case, out[-800:])
    assert state["i"] == calls if name == "API_ERROR" else state["i"] >= calls
    if name == "API_ERROR":
        assert "API_ERROR" in out and sim.issue_posts() == []
    assert "Traceback" not in out and FAKE_KEY not in out


def test_results_transport_error_fails_closed(tmp_path: Path) -> None:
    prep = _prepare(tmp_path)
    sim = Sim(prep)

    def boom(call: Call) -> tuple[int, bytes]:
        raise TimeoutError("read timed out")

    sim.fake.route("GET", RESULTS, boom)
    collect, rc, out = _collect(sim)
    assert rc == exit_code(collect, "API_ERROR")
    assert sim.issue_posts() == [] and "Traceback" not in out


# --- [C6] hand-off artifact (attack sketch T10) ------------------------------------------------------------


INVALID_ARTIFACTS = [
    "missing-file", "not-json", "no-batch-id", "empty-custom-ids", "batch-id-forged",
    # Review finding 3 (PR #282): a canary id the batch never carried was a KeyError traceback.
    "canary-not-in-custom-ids",
    # Ruling 1: created_at is required, RFC 3339 UTC, and never in the future.
    "created-at-missing", "created-at-malformed", "created-at-naive", "created-at-number",
    "created-at-line-break", "created-at-future",
]


@pytest.mark.parametrize("case", INVALID_ARTIFACTS)
def test_invalid_artifact_is_refused_before_anything_is_filed(tmp_path: Path, case: str) -> None:
    prep = _prepare(tmp_path)
    sim = Sim(prep)
    doc = json.loads(prep.artifact.read_text(encoding="utf-8"))
    bad = tmp_path / "bad-artifact.json"
    if case == "not-json":
        bad.write_text("{not json", encoding="utf-8")
    elif case == "no-batch-id":
        doc.pop("batch_id")
        bad.write_text(json.dumps(doc), encoding="utf-8")
    elif case == "empty-custom-ids":
        doc["custom_ids"] = []
        bad.write_text(json.dumps(doc), encoding="utf-8")
    elif case == "batch-id-forged":
        doc["batch_id"] = "../../v1/organizations\nX"
        bad.write_text(json.dumps(doc), encoding="utf-8")
    elif case == "canary-not-in-custom-ids":
        # Every other check passes: the real canary id is listed as a module, the
        # results match custom_ids exactly, and only the canary pointer is wrong.
        doc["modules"][prep.canary_id] = prep.cfg["canary_fixture"]
        doc["canary_custom_id"] = "forged-canary-id"
        bad.write_text(json.dumps(doc), encoding="utf-8")
    elif case.startswith("created-at-"):
        future = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=2)
        values = {
            "malformed": "last tuesday",
            "naive": "2026-10-05T02:00:00",
            "number": 1_760_000_000,
            "line-break": "2026-10-05T02:00:00Z\n# forged",
            "future": future.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        kind = case.removeprefix("created-at-")
        if kind == "missing":
            doc.pop("created_at", None)
        else:
            doc["created_at"] = values[kind]
        bad.write_text(json.dumps(doc), encoding="utf-8")
    collect, rc, out = _collect(sim, artifact=bad)
    assert rc == exit_code(collect, "ARTIFACT_INVALID"), (case, out[-500:])
    assert "Traceback" not in out
    assert sim.fake.calls == []
    assert "\n# forged" not in out


def test_tampered_artifact_cannot_shrink_the_expected_set(tmp_path: Path) -> None:
    prep = _prepare(tmp_path)
    sim = Sim(prep)
    doc = json.loads(prep.artifact.read_text(encoding="utf-8"))
    doc["custom_ids"] = [c for c in doc["custom_ids"] if c != prep.ids[ALPHA]]
    shrunk = tmp_path / "shrunk.json"
    shrunk.write_text(json.dumps(doc), encoding="utf-8")
    collect, rc, out = _collect(sim, artifact=shrunk)
    assert rc == exit_code(collect, "MISSING_OR_DUP"), out[-500:]
    assert sim.issue_posts() == []


@pytest.mark.parametrize("value", [None, ""], ids=["unset", "empty"])
def test_collect_without_the_key_fails_before_any_request(tmp_path: Path, value: str | None) -> None:
    prep = _prepare(tmp_path)
    sim = Sim(prep)
    env = audit_env(tmp_path, GITHUB_TOKEN=FAKE_GH_TOKEN)
    env.pop(SECRET_NAME)
    if value is not None:
        env[SECRET_NAME] = value
    collect, rc, out = _collect(sim, env=env)
    assert rc == exit_code(collect, "MISSING_SECRET")
    assert SECRET_NAME in out and sim.fake.calls == []


def test_collect_bad_config_fails_closed(tmp_path: Path) -> None:
    prep = _prepare(tmp_path)
    sim = Sim(prep)
    prep.cfg_path.write_text(json.dumps({**prep.cfg, "card_mode": "flood"}), encoding="utf-8")
    collect, rc, out = _collect(sim)
    assert rc == exit_code(collect, "CONFIG") and "card_mode" in out
    assert sim.fake.calls == []


# --- ruling 1 (PR #282): every uncollected hand-off, stale refused, none is loud ---------------------------

SECOND_BATCH_ID = "msgbatch_01SECONDHANDOFF"


def _real_clock(clock: Any) -> float:
    """Pin the fake clock to real UTC time, so either clock source agrees on "now"."""
    clock.now = dt.datetime.now(dt.timezone.utc).timestamp()
    return clock.now


def _stamp(epoch: float) -> str:
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _handoff(prep: Prepared, name: str, **change: Any) -> Path:
    doc = json.loads(prep.artifact.read_text(encoding="utf-8"))
    doc.update(change)
    path = prep.tmp / "handoffs" / name / "wiring-audit-batch.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _route_per_batch(sim: Sim, results_for: dict[str, Callable[[], list[dict[str, Any]]]]) -> None:
    """Retrieve echoes the asked id; results differ per batch; issue list reflects posted issues."""
    n = len(sim.prep.all_ids)

    def retrieve(call: Call) -> tuple[int, bytes]:
        return 200, jbytes(batch_object("ended", {"succeeded": n}, batch_id=call.path.rsplit("/", 1)[1]))

    def results(call: Call) -> tuple[int, bytes]:
        lines = results_for[call.path.split("/")[-2]]()
        return 200, ("\n".join(json.dumps(x) for x in lines) + "\n").encode("utf-8")

    def issues(call: Call) -> tuple[int, bytes]:
        posted = [{"number": 100 + i, "state": "open", "title": p["title"], "body": p["body"]}
                  for i, p in enumerate(sim.issue_posts())]
        return 200, jbytes(sim.existing_issues + posted)

    sim.fake.route("GET", BATCH, retrieve)
    sim.fake.route("GET", RESULTS, results)
    sim.fake.route("GET", ISSUES, issues)


def test_every_uncollected_handoff_is_collected_and_each_batch_deleted(tmp_path: Path, clock: Any) -> None:
    _real_clock(clock)
    prep = _prepare(tmp_path)  # summary mode: one issue per hand-off with new findings
    sim = Sim(prep)
    older = _handoff(prep, "run-1001")
    newer = _handoff(prep, "run-1002", batch_id=SECOND_BATCH_ID)
    _three_findings(sim)
    first = sim.result_lines()
    sim.module_output(ALPHA, [_finding(severity="HIGH", symbol="alpha_second")])  # BETA's finding repeats
    second = sim.result_lines()
    _route_per_batch(sim, {BATCH_ID: lambda: first, SECOND_BATCH_ID: lambda: second})
    collect, rc, out = _collect(sim, artifacts=[older, newer])
    assert rc == exit_code(collect, "OK"), out[-800:]
    assert sim.fake.unexpected == []
    deleted = [c.path.rsplit("/", 1)[1] for c in sim.deletes()]
    assert sorted(deleted) == sorted([BATCH_ID, SECOND_BATCH_ID]), deleted  # two DELETE calls, one per batch
    for batch_id in (BATCH_ID, SECOND_BATCH_ID):
        assert len(sim.fake.find("GET", rf"/v1/messages/batches/{batch_id}/results")) == 1, batch_id
    posts = sim.issue_posts()
    assert len(posts) == 2, [p["title"] for p in posts]
    bodies = "\n".join(p["body"] for p in posts)
    assert marker(_key(BETA, "unwired_entry_point", "beta_main")) in bodies
    assert marker(_key(ALPHA, "zero_caller_public", "alpha_second")) in bodies
    assert bodies.count(marker(_key(BETA, "unwired_entry_point", "beta_main"))) == 1  # dedupe across hand-offs


def _stale_days(prep: Prepared) -> int:
    days = prep.cfg["stale_handoff_days"]
    assert isinstance(days, int) and days > 0
    return days


@pytest.mark.parametrize("override", [None, 2], ids=["shipped-days", "config-override-2"])
def test_stale_handoff_is_refused_without_any_request(tmp_path: Path, clock: Any, override: int | None) -> None:
    now = _real_clock(clock)
    prep = _prepare(tmp_path) if override is None else _prepare(tmp_path, stale_handoff_days=override)
    sim = Sim(prep)
    _three_findings(sim)
    stale = _handoff(prep, "run-0900", created_at=_stamp(now - _stale_days(prep) * 86400 - 3600))
    collect, rc, out = _collect(sim, artifacts=[stale])
    assert rc == exit_code(collect, "HANDOFF_STALE"), out[-800:]
    assert "::error title=wiring-audit::HANDOFF_STALE" in out and BATCH_ID in out
    assert sim.fake.calls == []  # not re-collected: no retrieve, no results, no delete, nothing filed
    assert "Traceback" not in out


@pytest.mark.parametrize("override", [None, 2], ids=["shipped-days", "config-override-2"])
def test_handoff_just_inside_the_stale_limit_is_collected(tmp_path: Path, clock: Any, override: int | None) -> None:
    # Boundary and positive control: one hour younger than the limit is collected.
    now = _real_clock(clock)
    prep = _prepare(tmp_path) if override is None else _prepare(tmp_path, stale_handoff_days=override)
    sim = Sim(prep)
    _three_findings(sim)
    fresh = _handoff(prep, "run-0950", created_at=_stamp(now - _stale_days(prep) * 86400 + 3600))
    collect, rc, out = _collect(sim, artifacts=[fresh])
    assert rc == exit_code(collect, "OK"), out[-800:]
    assert len(sim.issue_posts()) == 1 and len(sim.deletes()) == 1


def test_stale_handoff_does_not_stop_the_fresh_one(tmp_path: Path, clock: Any) -> None:
    now = _real_clock(clock)
    prep = _prepare(tmp_path)
    sim = Sim(prep)
    _three_findings(sim)
    stale = _handoff(prep, "run-0900", batch_id=SECOND_BATCH_ID,
                     created_at=_stamp(now - _stale_days(prep) * 86400 - 3600))
    fresh = _handoff(prep, "run-1000")
    collect, rc, out = _collect(sim, artifacts=[stale, fresh])
    assert rc == exit_code(collect, "HANDOFF_STALE"), out[-800:]
    assert not [c for c in sim.fake.calls if SECOND_BATCH_ID in c.url]  # no request for the stale batch
    assert [c.path for c in sim.deletes()] == [f"/v1/messages/batches/{BATCH_ID}"]
    assert len(sim.issue_posts()) == 1


def test_no_handoff_is_a_loud_failure_not_success(tmp_path: Path) -> None:
    # Ruling 1, F5: zero uncollected hand-offs is "did nothing", never exit 0.
    prep = _prepare(tmp_path)
    sim = Sim(prep)
    collect, rc, out = _collect(sim, artifacts=[])
    assert rc == exit_code(collect, "NO_HANDOFF"), out[-800:]
    assert rc != exit_code(collect, "OK")
    assert "::error title=wiring-audit::NO_HANDOFF" in out
    assert sim.fake.calls == [] and "Traceback" not in out


# --- review finding 4 (PR #282): HTTP error body that cannot be read ----------------------------------------


def test_http_error_whose_body_read_fails_is_api_error_not_a_traceback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import http.client
    import urllib.error
    import urllib.request

    prep = _prepare(tmp_path)
    opened: list[str] = []

    class BrokenBody:
        def read(self, *args: Any) -> bytes:
            raise http.client.IncompleteRead(b"partial", 512)

        def close(self) -> None:
            return None

    def opener_open(self: Any, fullurl: Any, data: Any = None, timeout: Any = None) -> Any:
        url = fullurl.full_url if isinstance(fullurl, urllib.request.Request) else str(fullurl)
        opened.append(url)
        raise urllib.error.HTTPError(url, 500, "Internal Server Error", None, BrokenBody())  # type: ignore[arg-type]

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", opener_open)
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, *a, **k: opener_open(None, url, *a, **k))
    collect = require("collect")
    rc, out = run_main(  # http=None: the real default transport, the fake is underneath it
        collect,
        ["--config", str(prep.cfg_path), "--artifact", str(prep.artifact)],
        env=audit_env(prep.tmp, GITHUB_TOKEN=FAKE_GH_TOKEN),
    )
    assert opened, "the default transport was not used"
    assert rc == exit_code(collect, "API_ERROR"), out[-800:]
    assert "::error title=wiring-audit::API_ERROR" in out
    assert "Traceback" not in out and "IncompleteRead(" not in out and FAKE_KEY not in out
    assert not [u for u in opened if "/issues" in u]  # nothing filed


# --- round 3 (PR #282) finding 1: a hand-off whose batch an earlier collect already deleted -----------------

NOT_FOUND = {"type": "error", "error": {"type": "not_found_error", "message": "batch not found"}}


def _gone(sim: Sim, gone_id: str) -> None:
    """Retrieve answers 404 for gone_id (deleted by an earlier, failed collect); other batches are ended."""
    n = len(sim.prep.all_ids)

    def retrieve(call: Call) -> tuple[int, bytes]:
        batch_id = call.path.rsplit("/", 1)[1]
        if batch_id == gone_id:
            return 404, jbytes(NOT_FOUND)
        return 200, jbytes(batch_object("ended", {"succeeded": n}, batch_id=batch_id))

    sim.fake.route("GET", BATCH, retrieve)


@pytest.mark.parametrize("order", ["gone-first", "gone-last"])
@pytest.mark.parametrize("other", ["OK", "CANARY_MISSING"])
def test_a_batch_already_deleted_is_skipped_and_the_run_is_governed_by_the_rest(
        tmp_path: Path, clock: Any, order: str, other: str) -> None:
    # A failed collect deleted its batch but (before round 3) never moved `since`, so the
    # next run met the same hand-off: retrieve 404. That hand-off is ALREADY_COLLECTED:
    # logged with its batch id, no further request for it, not a failure of the run.
    _real_clock(clock)
    prep = _prepare(tmp_path)
    sim = Sim(prep)
    _three_findings(sim)
    if other == "CANARY_MISSING":
        _no_canary(sim)
    gone = _handoff(prep, "run-0900", batch_id=SECOND_BATCH_ID)
    fresh = _handoff(prep, "run-1000")
    lines = sim.result_lines()
    _route_per_batch(sim, {BATCH_ID: lambda: lines})
    _gone(sim, SECOND_BATCH_ID)
    collect, rc, out = _collect(sim, artifacts=[gone, fresh] if order == "gone-first" else [fresh, gone])
    assert rc == exit_code(collect, other), out[-800:]
    assert exit_code(collect, "ALREADY_COLLECTED") != exit_code(collect, "OK")  # a named, distinct outcome
    notes = [line for line in out.splitlines() if "ALREADY_COLLECTED" in line]
    assert notes and all(SECOND_BATCH_ID in line for line in notes), notes
    assert not [line for line in notes if line.startswith("::error")], notes  # honest: not a failure
    gone_calls = [(c.method, c.path) for c in sim.fake.calls if SECOND_BATCH_ID in c.url]
    assert gone_calls == [("GET", f"/v1/messages/batches/{SECOND_BATCH_ID}")], gone_calls  # no results, cancel, delete
    assert [c.path for c in sim.deletes()] == [f"/v1/messages/batches/{BATCH_ID}"]  # the live batch is still deleted
    assert len(sim.issue_posts()) == (1 if other == "OK" else 0)
    assert sim.fake.unexpected == [] and "Traceback" not in out


@pytest.mark.parametrize(("case", "gone_ids", "expected"), [
    ("only-handoff-gone", [BATCH_ID], "ALREADY_COLLECTED"),
    ("every-handoff-gone", [SECOND_BATCH_ID, BATCH_ID], "ALREADY_COLLECTED"),
    ("one-collected-one-gone", [SECOND_BATCH_ID], "OK"),
])
def test_a_run_whose_handoffs_were_all_already_collected_is_not_success(
        tmp_path: Path, clock: Any, case: str, gone_ids: list[str], expected: str) -> None:
    # Lead's ruling (round 3, F5): every hand-off ALREADY_COLLECTED and none failed means the
    # run did nothing: it exits ALREADY_COLLECTED (non-zero) and files nothing. One hand-off
    # collected normally next to already-collected ones is a run that did work: exit 0.
    _real_clock(clock)
    prep = _prepare(tmp_path)
    sim = Sim(prep)
    _three_findings(sim)
    gone = _handoff(prep, "run-0900", batch_id=SECOND_BATCH_ID)
    paths = [prep.artifact] if case == "only-handoff-gone" else [gone, _handoff(prep, "run-1000")]
    lines = sim.result_lines()
    _route_per_batch(sim, {BATCH_ID: lambda: lines})
    n = len(prep.all_ids)

    def retrieve(call: Call) -> tuple[int, bytes]:
        batch_id = call.path.rsplit("/", 1)[1]
        if batch_id in gone_ids:
            return 404, jbytes(NOT_FOUND)
        return 200, jbytes(batch_object("ended", {"succeeded": n}, batch_id=batch_id))

    sim.fake.route("GET", BATCH, retrieve)
    collect, rc, out = _collect(sim, artifacts=paths)
    assert rc == exit_code(collect, expected), (case, out[-800:])
    if expected == "ALREADY_COLLECTED":
        assert rc != exit_code(collect, "OK")
        assert sim.issue_posts() == [] and sim.deletes() == []
        assert sim.fake.find("GET", RESULTS) == []
    else:
        assert len(sim.issue_posts()) == 1
        assert [c.path for c in sim.deletes()] == [f"/v1/messages/batches/{BATCH_ID}"]
    assert sim.fake.unexpected == [] and "Traceback" not in out


def _results_404(sim: Sim) -> None:
    sim.fake.route("GET", RESULTS, lambda c: (404, jbytes(NOT_FOUND)))


def _issue_list_404(sim: Sim) -> None:
    sim.fake.route("GET", ISSUES, lambda c: (404, jbytes({"message": "Not Found"})))


def _issue_post_404(sim: Sim) -> None:
    sim.fake.route("POST", ISSUES, lambda c: (404, jbytes({"message": "Not Found"})))


OTHER_404 = [("results", _results_404), ("issue-list", _issue_list_404), ("issue-post", _issue_post_404)]


@pytest.mark.parametrize(("case", "break_it"), OTHER_404, ids=[c for c, _ in OTHER_404])
def test_a_404_after_the_initial_retrieve_is_still_api_error(tmp_path: Path, case: str,
                                                             break_it: Callable[[Sim], None]) -> None:
    # Only the first retrieve of a hand-off's batch means "already collected". A 404 later
    # (results, the issues API) is a real failure: API_ERROR, never ALREADY_COLLECTED.
    prep = _prepare(tmp_path)
    sim = Sim(prep)
    _three_findings(sim)
    break_it(sim)
    collect, rc, out = _collect(sim)
    assert rc == exit_code(collect, "API_ERROR"), (case, out[-800:])
    assert "::error title=wiring-audit::API_ERROR" in out
    assert "ALREADY_COLLECTED" not in out
    assert [c.path for c in sim.deletes()] == [f"/v1/messages/batches/{BATCH_ID}"]  # still deleted (C8)
    assert "Traceback" not in out


# Exit codes exercised above. Adding a code without a test fails here (T9 parity).
COVERED = {"OK", "CONFIG", "MISSING_SECRET", "ARTIFACT_INVALID", "BATCH_NOT_ENDED", "API_ERROR",
           "DELETE_FAILED", "CANCEL_TIMEOUT", "HANDOFF_STALE", "NO_HANDOFF",
           "ALREADY_COLLECTED"} | {name for *_, name in FAILURES}


def test_every_collect_exit_code_has_a_test() -> None:
    collect = require("collect")
    assert set(collect.EXIT_CODES) <= COVERED, sorted(set(collect.EXIT_CODES) - COVERED)
