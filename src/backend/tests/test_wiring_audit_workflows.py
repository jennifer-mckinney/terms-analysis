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
    assert checkout[0].get("with") == {"persist-credentials": False}


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


def test_artifact_handoff_is_wired_between_the_workflows() -> None:
    # [F12] collect reads what submit uploads, from the submit workflow only.
    upload = [s for s in _job("submit")["steps"] if str(s.get("uses", "")).startswith("actions/upload-artifact@")]
    assert len(upload) == 1
    name = upload[0]["with"]["name"]
    text = COLLECT_WORKFLOW.read_text(encoding="utf-8")
    assert name in text
    assert "wiring-audit-submit.yml" in text


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
