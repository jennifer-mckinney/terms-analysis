"""Weekly wiring audit: the two workflows and the dependency rule (card #224, ADR 0002).

[C2] GitHub-hosted, schedule + workflow_dispatch only, `environment:` on both
jobs, and the default-branch ref guard. [C3] full-SHA pins with a tag
comment, least privilege (submit: contents read; collect: contents read,
actions read, issues write), no model output through a shell. [C4] the
dedicated WIRING_AUDIT_API_KEY, step-scoped, failing closed when missing.
[C6] no continue-on-error. [C9] stdlib only, nothing imported by the app.

Static YAML checks are used only where a GitHub runner is needed; the
missing-secret step is executed under bash.
"""
from __future__ import annotations

import ast
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.wiring_audit_support import (
    AUDIT_DIR,
    COLLECT_WORKFLOW,
    REPO_ROOT,
    SECRET_NAME,
    SUBMIT_WORKFLOW,
    TEST_REPO,
    git,
    make_repo,
    real_config,
)

SECRET_EXPR = "${{ secrets.%s }}" % SECRET_NAME
REF_GUARD = "github.ref == format('refs/heads/{0}', github.event.repository.default_branch)"
JOBS = {"submit": SUBMIT_WORKFLOW, "collect": COLLECT_WORKFLOW}
PERMISSIONS = {
    "submit": {"contents": "read"},
    "collect": {"contents": "read", "actions": "read", "issues": "write"},
}
SHA_USES = re.compile(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}")
TAG_COMMENT = re.compile(r"\s*#\s*v\d+(\.\d+)*\s*")


def _doc(job: str) -> dict[str, Any]:
    path = JOBS[job]
    assert path.is_file(), f"{path.name} does not exist (card #224 not implemented)"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(doc, dict)
    return doc


def _job(job: str) -> dict[str, Any]:
    jobs = _doc(job)["jobs"]
    assert list(jobs) == [job], f"expected exactly one job named {job}"
    return jobs[job]


def _triggers(doc: dict[str, Any]) -> Any:
    return doc.get("on", doc.get(True))  # PyYAML reads bare `on` as True


def _strip_expr(text: str) -> str:
    text = text.strip()
    m = re.fullmatch(r"\$\{\{\s*(.*?)\s*\}\}", text, re.S)
    return (m.group(1) if m else text).strip()


ALL = pytest.mark.parametrize("job", sorted(JOBS))


@ALL
def test_runs_on_github_hosted_ubuntu_only(job: str) -> None:
    assert _job(job)["runs-on"] == "ubuntu-latest"  # [C2] never a self-hosted label


@ALL
def test_triggers_are_schedule_and_dispatch_only(job: str) -> None:
    triggers = _triggers(_doc(job))
    assert isinstance(triggers, dict) and set(triggers) == {"schedule", "workflow_dispatch"}  # [C2]
    dispatch = triggers["workflow_dispatch"] or {}
    inputs = set((dispatch.get("inputs") or {}))
    assert inputs <= ({"batch_id"} if job == "collect" else set()), inputs
    assert not any("ref" in name for name in inputs)


@ALL
def test_schedule_matches_the_config(job: str) -> None:
    # [F10, F13] the cron lives in the workflow (GitHub needs it) and is pinned to config.
    crons = [entry["cron"] for entry in _triggers(_doc(job))["schedule"]]
    assert crons == [real_config()["schedule"][job]]


@ALL
def test_job_declares_the_environment_and_the_default_branch_guard(job: str) -> None:
    j = _job(job)
    env = j.get("environment")
    name = env.get("name") if isinstance(env, dict) else env
    assert isinstance(name, str) and name.strip()  # [C2] key held by an environment
    assert _strip_expr(str(j.get("if", ""))) == REF_GUARD


def test_both_jobs_use_the_same_environment() -> None:
    names = []
    for job in JOBS:
        env = _job(job)["environment"]
        names.append(env.get("name") if isinstance(env, dict) else env)
    assert len(set(names)) == 1


@ALL
def test_every_action_is_pinned_to_a_full_sha_with_its_tag(job: str) -> None:
    text = JOBS[job].read_text(encoding="utf-8") if JOBS[job].is_file() else ""
    _doc(job)
    uses = re.findall(r"^\s*-?\s*uses:\s*(\S+)(.*)$", text, re.M)
    assert uses, "no actions found"
    for ref, comment in uses:
        assert SHA_USES.fullmatch(ref), ref  # [C3]
        assert TAG_COMMENT.fullmatch(comment), (ref, comment)


@ALL
def test_permissions_are_exactly_least_privilege(job: str) -> None:
    assert _doc(job)["permissions"] == {}
    assert _job(job)["permissions"] == PERMISSIONS[job]  # [C3]


@ALL
def test_job_is_bounded_longer_than_the_cancel_timeout(job: str) -> None:
    minutes = _job(job).get("timeout-minutes")
    assert isinstance(minutes, int) and not isinstance(minutes, bool) and minutes > 0
    assert minutes * 60 > real_config()["cancel_timeout_seconds"]


@ALL
def test_no_continue_on_error_anywhere(job: str) -> None:
    text = JOBS[job].read_text(encoding="utf-8") if JOBS[job].is_file() else ""
    _doc(job)
    assert "continue-on-error" not in text  # [C6]


@ALL
def test_runs_queue_instead_of_cancelling(job: str) -> None:
    conc = _doc(job).get("concurrency")
    assert isinstance(conc, dict) and conc.get("cancel-in-progress") is False  # attack sketch T8


@ALL
def test_checkout_persists_no_credentials_and_takes_no_ref(job: str) -> None:
    steps = _job(job)["steps"]
    checkout = [s for s in steps if str(s.get("uses", "")).startswith("actions/checkout@")]
    assert len(checkout) == 1
    w = checkout[0].get("with") or {}
    assert w.get("persist-credentials") is False
    # Round 3 (PR #282): collect may take full history so its ancestor check can
    # see older submit commits; nothing else (no `ref`, no other depth) is allowed.
    allowed = {"persist-credentials"} | ({"fetch-depth"} if job == "collect" else set())
    assert set(w) <= allowed, sorted(set(w) - allowed)
    assert w.get("fetch-depth", 0) == 0 and not isinstance(w.get("fetch-depth", 0), bool)


@ALL
def test_setup_python_reads_the_version_file(job: str) -> None:
    steps = _job(job)["steps"]
    setup = [i for i, s in enumerate(steps) if str(s.get("uses", "")).lower().startswith("actions/setup-python@")]
    assert len(setup) == 1
    w = steps[setup[0]].get("with") or {}
    assert w.get("python-version-file") == ".python-version" and "python-version" not in w
    first_python = min(i for i, s in enumerate(steps) if "python" in str(s.get("run", "")))
    assert setup[0] < first_python


def test_python_version_file_exists_for_setup_python() -> None:
    # Depends on #215 (PR #277) landing; the workflows reference this file.
    assert (REPO_ROOT / ".python-version").is_file()


@ALL
def test_secret_is_step_scoped_dedicated_and_checked_first(job: str) -> None:
    j = _job(job)
    assert "env" not in j or SECRET_NAME not in str(j["env"])
    text = JOBS[job].read_text(encoding="utf-8")
    assert "ANTHROPIC_API_KEY" not in text  # [C4] never the shared review key
    allowed = {SECRET_NAME} | ({"GITHUB_TOKEN"} if job == "collect" else set())
    assert set(re.findall(r"secrets\.([A-Za-z0-9_]+)", text)) <= allowed
    for step in j["steps"]:
        for key in ("with", "run"):
            assert "secrets." not in str(step.get(key, "")), (step.get("name"), key)
    first = j["steps"][0]
    assert first.get("env") == {SECRET_NAME: SECRET_EXPR}
    assert "python" not in first.get("run", "")


@ALL
def test_no_expression_is_interpolated_into_a_shell(job: str) -> None:
    # [C3] model output, inputs and step outputs reach scripts only through env.
    for step in _job(job)["steps"]:
        assert "${{" not in str(step.get("run", "")), step.get("name")


@ALL
def test_python_runs_isolated_on_tracked_audit_scripts(job: str) -> None:
    runs = [str(s.get("run", "")) for s in _job(job)["steps"]]
    calls = [line for r in runs for line in r.splitlines() if re.search(r"\bpython3?\b", line)]
    assert calls
    for line in calls:
        m = re.search(r"\bpython3 -I (scripts/audit/[\w/]+\.py)\b", line)
        assert m, line
        assert (REPO_ROOT / m.group(1)).is_file(), m.group(1)
    assert any(f"scripts/audit/{job}.py" in line for line in calls)


def _run_secret_step(job: str, value: str | None) -> subprocess.CompletedProcess[str]:
    env = {"PATH": os.environ.get("PATH", "")}
    if value is not None:
        env[SECRET_NAME] = value
    return subprocess.run(["bash", "-e", "-c", _job(job)["steps"][0]["run"]], env=env, text=True,
                          capture_output=True, timeout=60)


@ALL
@pytest.mark.parametrize("value", [None, "", "   "], ids=["unset", "empty", "blank"])
def test_missing_secret_fails_the_job_loudly(job: str, value: str | None) -> None:
    proc = _run_secret_step(job, value)
    assert proc.returncode == 1
    out = proc.stdout + proc.stderr
    assert "::error title=wiring-audit::" in out and SECRET_NAME in out


@ALL
def test_present_secret_passes_without_echoing_it(job: str) -> None:
    proc = _run_secret_step(job, "sk-" + "present-value-xyz")
    assert proc.returncode == 0, proc.stderr
    assert "present-value-xyz" not in proc.stdout + proc.stderr


def test_submit_has_a_failure_cleanup_step() -> None:
    # [C8] a failure after the batch exists cancels, polls and deletes it.
    steps = _job("submit")["steps"]
    cleanup = [s for s in steps if "failure()" in str(s.get("if", ""))]
    assert len(cleanup) == 1
    assert "python3 -I scripts/audit/submit.py" in cleanup[0]["run"]
    assert cleanup[0].get("env", {}).get(SECRET_NAME) == SECRET_EXPR


RUN_ID_EXPR = re.compile(r"\$\{\{\s*github\.run_id\s*\}\}")


def test_artifact_handoff_is_wired_between_the_workflows() -> None:
    # [F12] collect reads what submit uploads, from the submit workflow only.
    # Ruling 1 (PR #282): the hand-off name carries the run id, so two submit
    # runs never collide; collect finds them by the fixed prefix.
    upload = [s for s in _job("submit")["steps"] if str(s.get("uses", "")).startswith("actions/upload-artifact@")]
    assert len(upload) == 1
    name = str(upload[0]["with"]["name"])
    assert RUN_ID_EXPR.search(name), name
    prefix = name.split("${{", 1)[0]
    assert prefix.strip("-_ ") != ""
    text = COLLECT_WORKFLOW.read_text(encoding="utf-8")
    assert prefix in text
    assert "wiring-audit-submit.yml" in text


def test_collect_takes_every_uncollected_submit_run_not_only_the_newest() -> None:
    # Ruling 1 (PR #282): `gh run list --limit 1` orphaned every older batch.
    runs = "\n".join(str(s.get("run", "")) for s in _job("collect")["steps"]).replace("\\\n", " ")
    lookups = [line for line in runs.splitlines() if "gh run list" in line and "wiring-audit-submit.yml" in line]
    assert lookups, "collect no longer looks up the submit workflow's runs"
    for line in lookups:
        assert not re.search(r"--limit(\s+|=)1\b", line), "collect still reads only the newest submit run"
        assert not re.search(r"\.\[0\]", line), "collect still takes only the first submit run of the list"


# --- round 3 (PR #282): the collect download step, run under bash with a fake `gh` ---------------------
#
# Findings 1-3 of round 2. The step is executed as GitHub runs it (bash -eo pipefail) in a
# sandbox clone made the way actions/checkout makes it (depth 1 unless the collect checkout
# asks for fetch-depth 0), with a fake `gh` that filters and orders runs like the real CLI
# (newest first; an in-progress run has conclusion ""). Only the hand-off list the step
# writes for the collector, its exit code and its annotations are asserted.

FAKE_GH = r'''
import json, os, subprocess, sys
ALIASES = {"-R": "--repo", "-w": "--workflow", "-b": "--branch", "-s": "--status", "-e": "--event",
           "-L": "--limit", "-q": "--jq", "-n": "--name", "-D": "--dir", "-c": "--commit"}
STATUSES = {"queued", "in_progress", "completed", "waiting", "requested", "pending", "action_required"}
argv = sys.argv[1:]
with open(os.environ["FAKE_GH_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(argv) + "\n")
with open(os.environ["FAKE_GH_STATE"], encoding="utf-8") as fh:
    state = json.load(fh)
opts, pos, i = {}, [], 0
while i < len(argv):
    a = argv[i]
    if a.startswith("-"):
        name, _, val = a.partition("=")
        name = ALIASES.get(name, name)
        if not _:
            i += 1
            val = argv[i]
        opts.setdefault(name, []).append(val)
    else:
        pos.append(a)
    i += 1
def fail(msg, rc=1):
    sys.stderr.write("fake gh: " + msg + "\n")
    sys.exit(rc)
def created_ok(created, query):
    # GitHub search date qualifiers: >=, >, <=, <, a..b, with a date or a UTC timestamp.
    def cmp(op, value):
        key = created if "T" in value else created[:10]
        return {">=": key >= value, ">": key > value, "<=": key <= value, "<": key < value, "=": key == value}[op]
    if ".." in query:
        lo, hi = query.split("..", 1)
        return (lo == "*" or cmp(">=", lo)) and (hi == "*" or cmp("<=", hi))
    for op in (">=", "<=", ">", "<"):
        if query.startswith(op):
            return cmp(op, query[len(op):])
    return cmp("=", query)
if opts.get("--repo", [os.environ["GITHUB_REPOSITORY"]])[-1] != os.environ["GITHUB_REPOSITORY"]:
    fail("wrong --repo", 4)
if pos[:2] == ["run", "list"]:
    allowed = {"--repo", "--workflow", "--branch", "--status", "--event", "--limit", "--json", "--jq", "--commit",
               "--created"}
    if set(opts) - allowed:
        fail("unsupported option " + ",".join(sorted(set(opts) - allowed)), 3)
    runs = list(state["runs"].get(opts.get("--workflow", [""])[-1], []))
    for key, field in (("--branch", "headBranch"), ("--event", "event"), ("--commit", "headSha")):
        if key in opts:
            runs = [r for r in runs if r[field] == opts[key][-1]]
    if "--status" in opts:
        want = opts["--status"][-1]
        runs = [r for r in runs if (r["status"] if want in STATUSES else r["conclusion"]) == want]
    if "--created" in opts:
        runs = [r for r in runs if created_ok(r["createdAt"], opts["--created"][-1])]
    runs.sort(key=lambda r: r["createdAt"], reverse=True)
    runs = runs[: int(opts.get("--limit", ["20"])[-1])]
    if "--json" not in opts:
        fail("this fake answers --json only", 3)
    fields = opts["--json"][-1].split(",")
    unknown = [f for f in fields if f not in state["fields"]]
    if unknown:
        fail("Unknown JSON field: " + unknown[0])
    out = json.dumps([{f: r[f] for f in fields} for r in runs])
    if "--jq" in opts:
        proc = subprocess.run(["jq", "-r", opts["--jq"][-1]], input=out, text=True, capture_output=True)
        sys.stdout.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        sys.exit(proc.returncode)
    print(out)
    sys.exit(0)
if pos[:2] == ["run", "download"] and len(pos) == 3:
    run_id = pos[2]
    if run_id in state["fail_downloads"]:
        fail("error downloading artifact for run " + run_id)
    if opts.get("--name", [""])[-1] != "wiring-audit-batch-" + run_id:
        fail("no valid artifacts found to download")
    dest = opts.get("--dir", ["."])[-1]
    os.makedirs(dest, exist_ok=True)
    with open(os.path.join(dest, "wiring-audit-batch.json"), "w", encoding="utf-8") as fh:
        json.dump({"run_id": run_id}, fh)
    sys.exit(0)
fail("unsupported command " + " ".join(pos[:2]), 3)
'''

COLLECT_FILE = COLLECT_WORKFLOW.name
SUBMIT_FILE = SUBMIT_WORKFLOW.name
STEP_ENV = {
    "github.token": "ghs_fake-collect-token",
    "github.event.repository.default_branch": "main",
}
HANDOFF_PATH = re.compile(r"/(\d+)/wiring-audit-batch\.json$")


def _lookback_seconds(days: int | None = None) -> int:
    # Round 4 ruling 1: the window is stale_handoff_days, read from the shipped config (F13).
    days = real_config()["stale_handoff_days"] if days is None else days
    assert isinstance(days, int) and not isinstance(days, bool) and days > 0, days
    return days * 86400


def _ago(seconds: float) -> str:
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _day(n: int, hour: int = 4) -> str:
    # Point n (0-9) inside the lookback window, oldest first; `hour` adds minutes for ordering.
    return _ago(_lookback_seconds() * (1 - (n + 1) / 12) - (hour - 4) * 60)


def _run(run_id: int, sha: str, created: str, *, updated: str | None = None, event: str = "schedule",
         branch: str = "main", status: str = "completed", conclusion: str = "success") -> dict[str, Any]:
    return {"databaseId": run_id, "headSha": sha, "createdAt": created, "updatedAt": updated or created,
            "event": event, "headBranch": branch, "status": status,
            "conclusion": conclusion if status == "completed" else ""}


def _download_step() -> dict[str, Any]:
    steps = [s for s in _job("collect")["steps"] if "gh run download" in str(s.get("run", ""))]
    assert len(steps) == 1, "collect has no single step that downloads the submit hand-offs"
    return steps[0]


def _collector_step() -> dict[str, Any]:
    steps = [s for s in _job("collect")["steps"] if "scripts/audit/collect.py" in str(s.get("run", ""))]
    assert len(steps) == 1
    return steps[0]


class _Checkout:
    """origin (A <- B on main, plus an unrelated fork commit C under refs/pull) and a checkout of it."""

    def __init__(self, tmp: Path) -> None:
        src = tmp / "src"
        files: dict[str, str | bytes] = {}
        for path in sorted(AUDIT_DIR.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                files[path.relative_to(REPO_ROOT).as_posix()] = path.read_bytes()
        make_repo(src, files)
        self.a = git(src, "rev-parse", "HEAD").stdout.decode().strip()
        (src / "later.txt").write_text("later\n", encoding="utf-8")
        git(src, "add", "later.txt")
        git(src, "commit", "-q", "-m", "later")
        self.b = git(src, "rev-parse", "HEAD").stdout.decode().strip()
        tree = git(src, "rev-parse", "HEAD^{tree}").stdout.decode().strip()
        self.c = git(src, "commit-tree", tree, "-m", "fork").stdout.decode().strip()
        git(src, "update-ref", "refs/pull/1/head", self.c)
        origin = tmp / "origin.git"
        git(tmp, "clone", "-q", "--mirror", str(src), str(origin))
        # actions/checkout: depth 1 by default; fetch-depth 0 takes every branch's history.
        checkout = [s for s in _job("collect")["steps"] if str(s.get("uses", "")).startswith("actions/checkout@")]
        depth = (checkout[0].get("with") or {}).get("fetch-depth", 1) if checkout else 1
        self.work = tmp / "work"
        args = ["clone", "-q", "--branch", "main"] + ([] if depth == 0 else ["--depth", "1"])
        git(tmp, *args, origin.as_uri(), str(self.work))
        self.unknown = "0123456789abcdef" * 2 + "01234567"  # well-formed, in no repository


def _run_download(tmp: Path, co: _Checkout, collect_runs: list[dict[str, Any]], submit_runs: list[dict[str, Any]],
                  fail_downloads: tuple[int, ...] = ()) -> tuple[subprocess.CompletedProcess[str], list[int]]:
    step = _download_step()
    tmp.mkdir(exist_ok=True)
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(f"#!{sys.executable}\n" + FAKE_GH, encoding="utf-8")
    gh.chmod(0o755)
    state = {"runs": {COLLECT_FILE: collect_runs, SUBMIT_FILE: submit_runs},
             "fields": sorted(_run(1, co.a, _day(0))),  # the JSON fields `gh run list` knows here
             "fail_downloads": [str(r) for r in fail_downloads]}
    (tmp / "gh-state.json").write_text(json.dumps(state), encoding="utf-8")
    runner = tmp / "runner"
    runner.mkdir()
    (tmp / "home").mkdir()
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "HOME": str(tmp / "home"), "LC_ALL": "C",
        "GITHUB_REPOSITORY": TEST_REPO, "RUNNER_TEMP": str(runner),
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0",
        "FAKE_GH_STATE": str(tmp / "gh-state.json"), "FAKE_GH_LOG": str(tmp / "gh-calls.jsonl"),
    }
    for name, value in (step.get("env") or {}).items():
        expr = _strip_expr(str(value))
        assert expr in STEP_ENV, f"download step env {name} = {value!r} has no stand-in in this test"
        env[name] = STEP_ENV[expr]
    proc = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", str(step["run"])],
                          cwd=co.work, env=env, text=True, capture_output=True, timeout=120)
    listed = runner / "wiring-audit" / "handoffs.txt"
    ids: list[int] = []
    for line in (listed.read_text(encoding="utf-8").splitlines() if listed.is_file() else []):
        m = HANDOFF_PATH.search(line)
        assert m and Path(line).is_file(), f"hand-off list names a file that was not downloaded: {line!r}"
        ids.append(int(m.group(1)))
    return proc, ids


def _gh_calls(tmp: Path) -> list[list[str]]:
    log = tmp / "gh-calls.jsonl"
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.is_file() else []


def _collect_lookups(tmp: Path) -> list[list[str]]:
    # Any gh call that names the collect workflow, in any spelling of the option.
    return [call for call in _gh_calls(tmp) if any(COLLECT_FILE in arg for arg in call)]


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "timed_out", "success"])
def test_every_trusted_submit_in_the_lookback_is_listed_whatever_the_last_collect_did(
        tmp_path: Path, conclusion: str) -> None:
    # Round 4 ruling 1 (MEDIUM): a `since` taken from the last completed collect dropped every
    # hand-off that collect failed to reach (MISSING_SECRET, DOWNLOAD_FAILED, cancelled, ...).
    # No `since` at all: every trusted successful submit run in the lookback is listed, oldest
    # first, and the 404 -> ALREADY_COLLECTED path dedupes the ones already collected.
    co = _Checkout(tmp_path)
    collect_runs = [
        _run(900, co.b, _day(9), status="in_progress"),  # the running collect itself
        _run(800, co.b, _day(5), conclusion=conclusion),  # run N: ended before collecting 20
        _run(700, co.a, _day(1)),
    ]
    submit_runs = [
        _run(10, co.a, _day(0), updated=_day(0, 5)),
        _run(20, co.a, _day(3), updated=_day(3, 5)),   # never collected: run N failed first
        _run(30, co.a, _day(7), updated=_day(7, 5)),
    ]
    proc, ids = _run_download(tmp_path / "n1", co, collect_runs, submit_runs)
    assert proc.returncode == 0, proc.stdout[-800:] + proc.stderr[-800:]
    assert ids == [10, 20, 30], ids
    assert _collect_lookups(tmp_path / "n1") == []  # no collect-run lookup at all


def test_a_handoff_whose_download_failed_is_listed_again_by_the_next_run(tmp_path: Path) -> None:
    # Ruling 1: run N fails to download submit 20; run N+1 (after N completed as a failure)
    # lists 20 again, so the failure is retried instead of being skipped forever.
    co = _Checkout(tmp_path)
    submit_runs = [_run(20, co.a, _day(3)), _run(30, co.b, _day(4))]
    proc, ids = _run_download(tmp_path / "n", co, [_run(700, co.a, _day(1))], submit_runs, fail_downloads=(20,))
    assert proc.returncode == 1, proc.stdout[-800:] + proc.stderr[-800:]
    assert ids == [30], ids
    run_n = _run(800, co.b, _day(6), conclusion="failure")
    proc, ids = _run_download(tmp_path / "n1", co, [run_n, _run(700, co.a, _day(1))], submit_runs)
    assert proc.returncode == 0, proc.stdout[-800:] + proc.stderr[-800:]
    assert ids == [20, 30], ids
    assert _collect_lookups(tmp_path / "n") == [] and _collect_lookups(tmp_path / "n1") == []


@pytest.mark.parametrize("override", [None, 2], ids=["shipped-days", "config-override-2"])
def test_the_lookback_is_stale_handoff_days_from_the_config(tmp_path: Path, override: int | None) -> None:
    # Ruling 1, F13: the window is read from config.json in the step, never restated. One hour
    # outside it is not listed (the collector would refuse it as HANDOFF_STALE); one hour
    # inside is. The override proves the shipped value is not hard-coded in the step.
    co = _Checkout(tmp_path)
    if override is not None:
        assert override < real_config()["stale_handoff_days"]
        cfg_file = co.work / "scripts" / "audit" / "config.json"
        cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
        cfg["stale_handoff_days"] = override
        cfg_file.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    window = _lookback_seconds(override)
    submit_runs = [
        _run(10, co.a, _ago(window + 3600)),  # older than the lookback
        _run(20, co.a, _ago(window - 3600)),  # just inside
        _run(30, co.b, _ago(3600)),
    ]
    proc, ids = _run_download(tmp_path / "run", co, [_run(700, co.a, _ago(window - 600))], submit_runs)
    assert proc.returncode == 0, proc.stdout[-800:] + proc.stderr[-800:]
    assert ids == [20, 30], ids
    assert _collect_lookups(tmp_path / "run") == []


BAD_LOOKBACK = [
    ("zero", 0), ("negative", -1), ("fraction", 7.5), ("string", "8"), ("null", None), ("bool", True),
    ("missing", KeyError),
]


@pytest.mark.parametrize(("case", "value"), BAD_LOOKBACK, ids=[c[0] for c in BAD_LOOKBACK])
def test_a_bad_lookback_in_the_config_fails_the_step_closed(tmp_path: Path, case: str, value: Any) -> None:
    # F13/F3: what the config loader rejects (stale_handoff_days must be a positive int), the
    # step rejects too, before it downloads anything. A trusted collect run is present, so no
    # code path may skip reading the value.
    co = _Checkout(tmp_path)
    cfg_file = co.work / "scripts" / "audit" / "config.json"
    cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
    if value is KeyError:
        del cfg["stale_handoff_days"]
    else:
        cfg["stale_handoff_days"] = value
    cfg_file.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    proc, ids = _run_download(tmp_path / "run", co, [_run(700, co.a, _day(1))], [_run(20, co.a, _day(3))])
    out = proc.stdout + proc.stderr
    assert proc.returncode != 0, (case, out[-800:])
    assert "::error title=wiring-audit::CONFIG" in out, (case, out[-800:])
    assert ids == [], (case, ids)
    assert not [c for c in _gh_calls(tmp_path / "run") if c[:2] == ["run", "download"]], case


def _trusted_collect(co: _Checkout) -> list[dict[str, Any]]:
    return [_run(700, co.a, _day(1))]


SUBMIT_TRUST = [
    # (case, overrides of run 40, collected?)
    ("schedule", {}, True),
    ("workflow-dispatch-at-tip", {"event": "workflow_dispatch", "sha": "b"}, True),
    ("pull-request-from-a-fork-main", {"event": "pull_request"}, False),
    ("pull-request-target", {"event": "pull_request_target"}, False),
    ("push", {"event": "push"}, False),
    ("fork-commit-not-on-main", {"sha": "c"}, False),
    ("commit-in-no-repository", {"sha": "unknown"}, False),
    ("sha-is-a-ref-name", {"sha": "HEAD"}, False),
]


@pytest.mark.parametrize(("case", "change", "collected"), SUBMIT_TRUST, ids=[c[0] for c in SUBMIT_TRUST])
def test_only_trusted_submit_runs_are_collected(tmp_path: Path, case: str, change: dict[str, str], collected: bool) -> None:
    # Finding 3 (MEDIUM): `--branch main` also matches a fork PR whose head branch is the
    # fork's `main`. Only schedule/dispatch runs on a commit of the default branch count.
    co = _Checkout(tmp_path)
    sha = {"a": co.a, "b": co.b, "c": co.c, "unknown": co.unknown}.get(change.get("sha", "a"), change.get("sha", ""))
    candidate = _run(40, sha, _day(3), event=change.get("event", "schedule"))
    control = _run(30, co.a, _day(2))  # positive control: trusted, older than the candidate
    proc, ids = _run_download(tmp_path, co, _trusted_collect(co), [control, candidate])
    assert proc.returncode == 0, proc.stdout[-800:] + proc.stderr[-800:]
    assert ids == ([30, 40] if collected else [30]), (case, ids)


@pytest.mark.parametrize(("failing", "kept"), [((25,), [30]), ((30,), [25]), ((25, 30), [])],
                         ids=["older-fails", "newer-fails", "all-fail"])
def test_one_failed_download_is_reported_and_the_rest_still_collected(
        tmp_path: Path, failing: tuple[int, ...], kept: list[int]) -> None:
    # Finding 2 (MEDIUM): under `set -euo pipefail` one failed `gh run download` ended the
    # step before the other hand-offs were listed. Each failure names its run, the others
    # are still listed, and the step fails at the end.
    co = _Checkout(tmp_path)
    proc, ids = _run_download(tmp_path, co, _trusted_collect(co),
                              [_run(25, co.a, _day(2)), _run(30, co.b, _day(3))], fail_downloads=failing)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1, out[-800:]
    assert ids == kept, ids
    errors = [line for line in out.splitlines() if line.startswith("::error title=wiring-audit::")]
    for run_id in failing:
        mine = [e for e in errors if re.search(rf"\b{run_id}\b", e)]
        assert mine, (run_id, errors)
        # Round 4 ruling 4: with the fixed window the hand-off is retried; the message says so.
        assert all("will be retried by the next collect run" in e for e in mine), mine
    attempted = [json.loads(line) for line in (tmp_path / "gh-calls.jsonl").read_text(encoding="utf-8").splitlines()]
    assert sorted(int(a[2]) for a in attempted if a[:2] == ["run", "download"]) == [25, 30]


def test_collector_still_runs_after_a_failed_download() -> None:
    # Finding 2: what did download is still checked and its batch deleted. The collector
    # step must run when the download step failed, but not when the job was cancelled.
    cond = _strip_expr(str(_collector_step().get("if", "")))
    assert re.fullmatch(r"!\s*cancelled\(\)|always\(\)", cond), cond


def test_only_the_submit_lookup_remains_and_it_restricts_the_event_and_checks_ancestry() -> None:
    # Round 4 ruling 1, static companion of the behavioural tests above: the step looks up
    # submit runs only (no collect-run lookup, no `since`), restricts the event and proves
    # each head commit is on the default branch.
    script = str(_download_step()["run"]).replace("\\\n", " ")
    lookups = [line for line in script.splitlines() if "gh run list" in line]
    assert lookups and all(SUBMIT_FILE in line for line in lookups), lookups
    assert COLLECT_FILE not in script
    for line in lookups:
        assert re.search(r"--event[ =]|\bevent\b", line), line
    assert "merge-base --is-ancestor" in script


# --- [C9] not in the application -------------------------------------------------------------------


def test_audit_scripts_import_only_the_standard_library() -> None:
    files = sorted(AUDIT_DIR.glob("*.py")) if AUDIT_DIR.is_dir() else []
    names = {p.stem for p in files}
    assert {"config", "inventory", "submit", "collect"} <= names
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            mods: list[str] = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mods = [node.module]
            for mod in mods:
                top = mod.split(".")[0]
                assert top in sys.stdlib_module_names or top in names, (path.name, mod)


def test_no_sdk_is_added_to_any_requirements_file() -> None:
    hits = []
    for path in REPO_ROOT.rglob("*requirements*.txt"):
        if ".venv" in path.parts or "venv" in path.parts or "node_modules" in path.parts:
            continue
        if re.search(r"^\s*anthropic\b", path.read_text(encoding="utf-8", errors="replace"), re.M | re.I):
            hits.append(path.relative_to(REPO_ROOT).as_posix())
    assert hits == []


def test_application_never_imports_the_audit() -> None:
    offenders = []
    for root in (REPO_ROOT / "src" / "backend" / "app", REPO_ROOT / "src" / "webapp"):
        for path in root.rglob("*.py"):
            if re.search(r"^\s*(from|import)\s+scripts(\.audit)?\b", path.read_text(encoding="utf-8", errors="replace"), re.M):
                offenders.append(path.relative_to(REPO_ROOT).as_posix())
    assert offenders == []
