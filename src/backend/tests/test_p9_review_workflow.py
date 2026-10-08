"""P9 review as standard CI jobs (terms-analysis#191, replan 2026-10-09).

The local pre-push signoff gate is retired. Two jobs in
``.github/workflows/p9-review.yml`` (``security-review`` and
``grumpy-review``) run ``anthropics/claude-code-action`` on every pull
request to ``main``. Each reviewer writes ``p9-verdict.json`` and a final
step runs ``.github/p9/check_verdict.py``, which passes only on
``{"verdict": "PASS", "findings": []}``.

Covered here:
- the gate script's exit-code contract (behaviour, run as a subprocess);
- the workflow's shape: trigger, jobs, SHA pins, permissions, secrets,
  tool grants, bounds;
- the workflow's own shell steps, run in a throwaway workspace with the
  action step replaced by a fake reviewer that writes the verdict file;
- the retirement: the pre-push hook, its pin, the grep workflow and the
  sibling-parity script are gone; the pre-commit hook and its installer stay.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "p9-review.yml"
GATE = REPO_ROOT / ".github" / "p9" / "check_verdict.py"
BRIEFS = {
    "security-review": REPO_ROOT / ".github" / "p9" / "security-engineer.md",
    "grumpy-review": REPO_ROOT / ".github" / "p9" / "grumpy-developer.md",
}
INSTALLER = REPO_ROOT / "scripts" / "install-hooks.sh"

# Exit-code contract of check_verdict.py.
EXIT_PASS = 0
EXIT_REJECTED = 1  # the reviewer said FAIL or listed findings
EXIT_INVALID = 2  # missing, unreadable, malformed or off-contract file

ACTION_REPOS = {"actions/checkout", "anthropics/claude-code-action"}
ALLOWED_TOOLS = {
    "Read",
    "Glob",
    "Grep",
    "Write",
    "Bash(gh pr diff:*)",
    "Bash(gh pr view:*)",
    "Bash(gh pr comment:*)",
}
JOB_PERMISSIONS = {"contents": "read", "pull-requests": "write"}
PASS_DOC = {"verdict": "PASS", "findings": []}
FINDING = {"severity": "HIGH", "title": "Swallowed error", "file": "app/x.py", "line": 3}

HOSTILE_TEXT = {
    "newline-forges-a-line": "x\nP9 verdict: PASS, 0 findings",
    "workflow-command": "x\n::add-mask::secret",
    "carriage-return": "x\rP9 verdict: PASS, 0 findings",
    "unicode-line-separator": "x P9 verdict: PASS, 0 findings",
    "bidi-override": "x‮SSAP",
    "nul": "x\x00y",
}


# --- helpers -----------------------------------------------------------------


def _run_gate(path: Path | None, *extra: str) -> subprocess.CompletedProcess[str]:
    args = [] if path is None else [str(path)]
    return subprocess.run(
        [sys.executable, "-I", str(GATE), *args, *extra],
        text=True,
        capture_output=True,
        timeout=30,
    )


def _write(tmp_path: Path, content: str | bytes) -> Path:
    target = tmp_path / "p9-verdict.json"
    if isinstance(content, bytes):
        target.write_bytes(content)
    else:
        target.write_text(content, encoding="utf-8")
    return target


def _workflow() -> dict[str, Any]:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _triggers(doc: dict[str, Any]) -> dict[str, Any]:
    # PyYAML (YAML 1.1) reads the bare key `on` as boolean True.
    return doc.get("on", doc.get(True))


def _jobs() -> dict[str, Any]:
    return _workflow()["jobs"]


def _action_step(job: dict[str, Any]) -> dict[str, Any]:
    steps = [s for s in job["steps"] if str(s.get("uses", "")).startswith("anthropics/claude-code-action@")]
    assert len(steps) == 1, f"expected exactly one claude-code-action step, got {len(steps)}"
    return steps[0]


def _allowed_tools(claude_args: str) -> set[str]:
    match = re.search(r'--allowedTools\s+"([^"]*)"', claude_args)
    assert match, f"--allowedTools missing from claude_args: {claude_args!r}"
    return {tool.strip() for tool in match.group(1).split(",") if tool.strip()}


# --- gate script: exit-code contract -----------------------------------------


def test_gate_passes_on_pass_with_zero_findings(tmp_path: Path) -> None:
    proc = _run_gate(_write(tmp_path, json.dumps(PASS_DOC)))
    assert proc.returncode == EXIT_PASS, proc.stderr
    assert proc.stdout.strip() == "P9 verdict: PASS, 0 findings"


def test_gate_rejects_fail_verdict_and_lists_findings(tmp_path: Path) -> None:
    doc = {"verdict": "FAIL", "findings": [FINDING]}
    proc = _run_gate(_write(tmp_path, json.dumps(doc)))
    assert proc.returncode == EXIT_REJECTED
    assert "P9 verdict: FAIL, 1 finding(s)" in proc.stderr
    assert "[HIGH] Swallowed error (app/x.py:3)" in proc.stderr


def test_gate_rejects_fail_verdict_with_no_findings(tmp_path: Path) -> None:
    proc = _run_gate(_write(tmp_path, json.dumps({"verdict": "FAIL", "findings": []})))
    assert proc.returncode == EXIT_REJECTED
    assert "P9 verdict: FAIL, 0 finding(s)" in proc.stderr


def test_gate_rejects_pass_that_still_lists_findings(tmp_path: Path) -> None:
    proc = _run_gate(_write(tmp_path, json.dumps({"verdict": "PASS", "findings": [FINDING]})))
    assert proc.returncode == EXIT_REJECTED
    assert "P9 verdict: PASS, 1 finding(s)" in proc.stderr


def test_gate_fails_closed_when_the_file_is_missing(tmp_path: Path) -> None:
    proc = _run_gate(tmp_path / "p9-verdict.json")
    assert proc.returncode == EXIT_INVALID
    assert "p9-verdict.json was not written" in proc.stderr
    assert str(tmp_path) not in proc.stderr  # F8: no absolute paths in messages


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("", id="empty-file"),
        pytest.param("{not json", id="malformed-json"),
        pytest.param('{"verdict": "PASS", "findings": []', id="truncated"),
        pytest.param(b"\xff\xfe\x00garbage", id="invalid-utf8"),
        pytest.param("[" * 100_000 + "]" * 100_000, id="deeply-nested"),
    ],
)
def test_gate_fails_closed_on_unparseable_file(tmp_path: Path, content: str | bytes) -> None:
    proc = _run_gate(_write(tmp_path, content))
    assert proc.returncode == EXIT_INVALID
    assert "is not valid JSON" in proc.stderr


@pytest.mark.parametrize(
    "doc",
    [
        pytest.param([], id="top-level-list"),
        pytest.param("PASS", id="top-level-string"),
        pytest.param({"findings": []}, id="verdict-missing"),
        pytest.param({"verdict": "pass", "findings": []}, id="verdict-lowercase"),
        pytest.param({"verdict": " PASS", "findings": []}, id="verdict-padded"),
        pytest.param({"verdict": "PASS​", "findings": []}, id="verdict-zero-width"),
        pytest.param({"verdict": True, "findings": []}, id="verdict-bool"),
        pytest.param({"verdict": None, "findings": []}, id="verdict-null"),
        pytest.param({"verdict": ["PASS"], "findings": []}, id="verdict-list-unhashable"),
        pytest.param({"verdict": "APPROVED", "findings": []}, id="verdict-unknown"),
        pytest.param({"verdict": "PASS"}, id="findings-missing"),
        pytest.param({"verdict": "PASS", "findings": None}, id="findings-null"),
        pytest.param({"verdict": "PASS", "findings": {}}, id="findings-object"),
        pytest.param({"verdict": "PASS", "findings": ""}, id="findings-empty-string"),
        pytest.param({"verdict": "FAIL", "findings": ["text"]}, id="finding-not-object"),
    ],
)
def test_gate_fails_closed_on_off_contract_shape(tmp_path: Path, doc: object) -> None:
    proc = _run_gate(_write(tmp_path, json.dumps(doc)))
    assert proc.returncode == EXIT_INVALID, proc.stdout
    assert "does not match the verdict contract" in proc.stderr


def test_gate_rejects_duplicate_keys_that_hide_a_fail(tmp_path: Path) -> None:
    raw = '{"verdict": "FAIL", "findings": [], "verdict": "PASS"}'
    proc = _run_gate(_write(tmp_path, raw))
    assert proc.returncode == EXIT_INVALID
    assert "duplicate key" in proc.stderr


# --- gate script: exact verdict contract (PR #214 review thread) ------------
# Lead ruling: the key sets are exact; severity is one of the tags the vendored
# briefs promise, `line` is a non-negative int (not bool), and `file`/`title`
# are non-empty strings. Off-contract -> EXIT_INVALID; valid FAIL -> EXIT_REJECTED.

_SEVERITY_RULE = re.compile(r"^\s*-\s*`severity` is one of (.+)\.\s*$", re.MULTILINE)


def _brief_severities() -> list[str]:
    """Severity tags the reviewer briefs allow, read from the briefs (F10/F13)."""
    tags: set[str] = set()
    for brief in BRIEFS.values():
        rules = _SEVERITY_RULE.findall(brief.read_text(encoding="utf-8"))
        assert len(rules) == 1, f"{brief.name}: expected one severity rule, got {rules}"
        tags.update(re.findall(r"`([A-Z]+)`", rules[0]))
    assert tags, "no severity tags found in the briefs"
    return sorted(tags)


SEVERITIES = _brief_severities()


def _finding_doc(**overrides: object) -> dict[str, object]:
    return {"verdict": "FAIL", "findings": [{**FINDING, **overrides}]}


@pytest.mark.parametrize(
    "doc",
    [
        pytest.param({**PASS_DOC, "approved": True}, id="extra-top-level-key"),
        pytest.param({"verdict": "FAIL", "findings": [{**FINDING, "fixed": True}]}, id="extra-finding-key"),
        pytest.param(
            {"verdict": "FAIL", "findings": [{k: v for k, v in FINDING.items() if k != "line"}]},
            id="missing-finding-key",
        ),
        pytest.param({"verdict": "FAIL", "findings": [{}]}, id="empty-finding"),
        pytest.param({"verdict": "PASS", "findings": [{**FINDING, "Severity": "HIGH"}]}, id="case-variant-key"),
    ],
)
def test_gate_rejects_inexact_key_sets(tmp_path: Path, doc: object) -> None:
    proc = _run_gate(_write(tmp_path, json.dumps(doc)))
    assert proc.returncode == EXIT_INVALID, proc.stderr
    assert "does not match the verdict contract" in proc.stderr
    assert proc.stdout == ""


@pytest.mark.parametrize(
    ("field", "value"),
    [
        # severity: only the briefs' tags, exact spelling.
        pytest.param("severity", "high", id="severity-lowercase"),
        pytest.param("severity", " HIGH", id="severity-padded"),
        pytest.param("severity", "HIGH\u200b", id="severity-zero-width"),
        pytest.param("severity", "INFO", id="severity-unknown"),
        pytest.param("severity", "", id="severity-empty"),
        pytest.param("severity", None, id="severity-null"),
        pytest.param("severity", 3, id="severity-int"),
        pytest.param("severity", ["HIGH"], id="severity-list"),
        *[pytest.param("severity", v, id=f"severity-hostile-{k}") for k, v in HOSTILE_TEXT.items()],
        # line: non-negative int; bool, float, string and null are off-contract.
        pytest.param("line", -1, id="line-negative"),
        pytest.param("line", "3", id="line-string"),
        pytest.param("line", True, id="line-bool-true"),
        pytest.param("line", False, id="line-bool-false"),
        pytest.param("line", 3.0, id="line-float"),
        pytest.param("line", None, id="line-null"),
        *[pytest.param("line", v, id=f"line-hostile-{k}") for k, v in HOSTILE_TEXT.items()],
        # title and file: non-empty strings.
        pytest.param("title", "", id="title-empty"),
        pytest.param("title", None, id="title-null"),
        pytest.param("title", 7, id="title-int"),
        pytest.param("title", ["x"], id="title-list"),
        pytest.param("file", "", id="file-empty"),
        pytest.param("file", None, id="file-null"),
        pytest.param("file", 7, id="file-int"),
        pytest.param("file", {"p": "x"}, id="file-object"),
    ],
)
@pytest.mark.parametrize("verdict", ["FAIL", "PASS"])
def test_gate_rejects_off_contract_finding_values(tmp_path: Path, field: str, value: object, verdict: str) -> None:
    doc = {"verdict": verdict, "findings": [{**FINDING, field: value}]}
    proc = _run_gate(_write(tmp_path, json.dumps(doc)))
    assert proc.returncode == EXIT_INVALID, proc.stderr
    assert "does not match the verdict contract" in proc.stderr
    assert proc.stdout == ""


def test_gate_rejects_one_bad_finding_among_valid_ones(tmp_path: Path) -> None:
    doc = {"verdict": "FAIL", "findings": [FINDING, {**FINDING, "line": -1}, FINDING]}
    proc = _run_gate(_write(tmp_path, json.dumps(doc)))
    assert proc.returncode == EXIT_INVALID, proc.stderr


@pytest.mark.parametrize("severity", SEVERITIES)
def test_gate_accepts_every_brief_severity_as_a_valid_fail(tmp_path: Path, severity: str) -> None:
    # Positive control: every tag a brief allows must reach EXIT_REJECTED, not
    # EXIT_INVALID (F3: what the writer is told to emit, the reader accepts).
    proc = _run_gate(_write(tmp_path, json.dumps(_finding_doc(severity=severity))))
    assert proc.returncode == EXIT_REJECTED, proc.stderr
    assert f"[{severity}] Swallowed error (app/x.py:3)" in proc.stderr


@pytest.mark.parametrize("line", [0, 1, 2**31], ids=["zero-no-line", "one", "large"])
def test_gate_accepts_non_negative_int_lines(tmp_path: Path, line: int) -> None:
    proc = _run_gate(_write(tmp_path, json.dumps(_finding_doc(line=line))))
    assert proc.returncode == EXIT_REJECTED, proc.stderr
    assert f"(app/x.py:{line})" in proc.stderr


def test_severity_table_has_positive_and_negative_cases() -> None:
    # Contract test (QUALITY-BAR 9): each allowed tag has a lower-case
    # variant that must be refused; the briefs' list is non-trivial.
    assert len(SEVERITIES) >= 2
    assert all(s.isupper() and s.lower() not in SEVERITIES for s in SEVERITIES)


@pytest.mark.parametrize("args", [(), ("a.json", "b.json")], ids=["no-args", "two-args"])
def test_gate_rejects_wrong_usage(tmp_path: Path, args: tuple[str, ...]) -> None:
    proc = subprocess.run(
        [sys.executable, "-I", str(GATE), *args],
        text=True,
        capture_output=True,
        cwd=tmp_path,
        timeout=30,
    )
    assert proc.returncode == EXIT_INVALID
    assert "usage: check_verdict.py <p9-verdict.json>" in proc.stderr




# Hostile text goes only in the free-text fields: severity and line are now
# validated (see test_gate_rejects_off_contract_finding_values), so a hostile
# value there is a contract mismatch, not a printed finding.
@pytest.mark.parametrize("field", ["title", "file"])
@pytest.mark.parametrize("payload", list(HOSTILE_TEXT.values()), ids=list(HOSTILE_TEXT))
def test_gate_prints_findings_on_one_sanitised_line(tmp_path: Path, field: str, payload: str) -> None:
    finding = {**FINDING, field: payload}
    proc = _run_gate(_write(tmp_path, json.dumps({"verdict": "FAIL", "findings": [finding]})))
    assert proc.returncode == EXIT_REJECTED
    lines = proc.stderr.splitlines()
    assert len(lines) == 2, lines  # header + exactly one line per finding
    assert all(line.isprintable() for line in lines), lines
    assert not any(line.startswith(("::", "P9 verdict: PASS")) for line in lines), lines
    assert proc.stdout == ""


def test_gate_truncates_long_finding_text(tmp_path: Path) -> None:
    finding = {**FINDING, "title": "A" * 2_000_000}
    proc = _run_gate(_write(tmp_path, json.dumps({"verdict": "FAIL", "findings": [finding]})))
    assert proc.returncode == EXIT_REJECTED
    assert max(len(line) for line in proc.stderr.splitlines()) < 1_000


# --- workflow shape ----------------------------------------------------------


def test_workflow_has_exactly_the_two_review_jobs() -> None:
    assert set(_jobs()) == set(BRIEFS)
    for name, job in _jobs().items():
        assert job.get("name", name) == name, "the job name is the required-check name"
        assert job["runs-on"] == "ubuntu-latest"


def test_trigger_is_pull_request_to_main_only() -> None:
    triggers = _triggers(_workflow())
    assert set(triggers) == {"pull_request"}, triggers
    pr = triggers["pull_request"]
    assert pr["branches"] == ["main"]
    assert set(pr["types"]) == {"opened", "synchronize", "reopened", "ready_for_review"}
    assert "pull_request_target" not in WORKFLOW.read_text(encoding="utf-8")


def test_every_action_is_pinned_to_a_full_sha_with_its_tag() -> None:
    uses_lines = [
        line.strip()
        for line in WORKFLOW.read_text(encoding="utf-8").splitlines()
        if re.match(r"\s*(-\s+)?uses:", line)
    ]
    assert len(uses_lines) == 2 * len(BRIEFS), uses_lines  # checkout + action per job
    seen = set()
    for line in uses_lines:
        match = re.fullmatch(r"(?:-\s+)?uses:\s+([\w.-]+/[\w.-]+)@([0-9a-f]{40})\s+#\s+v\d+(\.\d+)*", line)
        assert match, f"not SHA-pinned with a trailing tag comment: {line!r}"
        seen.add(match.group(1))
    assert seen == ACTION_REPOS


def test_permissions_are_least_privilege() -> None:
    doc = _workflow()
    assert doc["permissions"] == {}, "workflow default must grant nothing"
    for name, job in _jobs().items():
        assert job["permissions"] == JOB_PERMISSIONS, name


def test_secret_is_referenced_only_as_the_action_api_key() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert set(re.findall(r"secrets\.[A-Za-z0-9_]+", text)) == {"secrets.ANTHROPIC_API_KEY"}
    assert text.count("secrets.ANTHROPIC_API_KEY") == len(BRIEFS)
    for name, job in _jobs().items():
        assert _action_step(job)["with"]["anthropic_api_key"] == "${{ secrets.ANTHROPIC_API_KEY }}"
        for step in job["steps"]:
            assert "secrets." not in json.dumps(step.get("env", {})), name


def test_runs_are_bounded_and_superseded_runs_cancel() -> None:
    doc = _workflow()
    assert doc["concurrency"]["cancel-in-progress"] is True
    assert "github.event.pull_request.number" in doc["concurrency"]["group"]
    for name, job in _jobs().items():
        minutes = job["timeout-minutes"]
        assert isinstance(minutes, int) and 0 < minutes <= 30, name
        args = _action_step(job)["with"]["claude_args"]
        turns = re.search(r"--max-turns\s+(\d+)", args)
        assert turns and 0 < int(turns.group(1)) <= 50, args


def test_claude_gets_only_the_tools_it_needs() -> None:
    for name, job in _jobs().items():
        assert _allowed_tools(_action_step(job)["with"]["claude_args"]) == ALLOWED_TOOLS, name


def test_each_job_prompts_with_its_vendored_brief() -> None:
    for name, job in _jobs().items():
        brief = BRIEFS[name]
        prompt = _action_step(job)["with"]["prompt"]
        assert brief.relative_to(REPO_ROOT).as_posix() in prompt, name
        text = brief.read_text(encoding="utf-8")
        assert "p9-verdict.json" in text and "gh pr comment" in text, brief.name
        assert "/Users/" not in text and "/home/" not in text, brief.name


# --- workflow steps, run for real with a fake reviewer -----------------------


def _shell_steps(job: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Return the `run:` scripts before and after the action step."""
    before: list[str] = []
    after: list[str] = []
    seen_action = False
    for step in job["steps"]:
        if step is _action_step(job):
            seen_action = True
        elif "run" in step:
            (after if seen_action else before).append(step["run"])
    assert seen_action and before and after, "expected run steps around the action"
    return before, after


Reviewer = Callable[[Path], object]  # stands in for the review action


def _run_job(tmp_path: Path, job: dict[str, Any], reviewer: Reviewer) -> subprocess.CompletedProcess[str]:
    """Run the job's shell steps in a copy of the repo files they touch."""
    workspace = tmp_path / "ws"
    runner_temp = tmp_path / "runner-temp"
    (workspace / ".github" / "p9").mkdir(parents=True)
    runner_temp.mkdir()
    shutil.copy2(GATE, workspace / ".github" / "p9" / "check_verdict.py")
    env = {"PATH": os.environ["PATH"], "RUNNER_TEMP": str(runner_temp), "HOME": str(tmp_path)}
    before, after = _shell_steps(job)
    for script in before:
        subprocess.run(["bash", "-e", "-c", script], cwd=workspace, env=env, check=True, timeout=30)
    reviewer(workspace)  # stands in for anthropics/claude-code-action
    result = None
    for script in after:
        result = subprocess.run(
            ["bash", "-e", "-c", script], cwd=workspace, env=env, text=True, capture_output=True, timeout=30
        )
        if result.returncode != 0:
            break
    assert result is not None
    return result


def _writes(doc: object) -> Reviewer:
    return lambda ws: (ws / "p9-verdict.json").write_text(json.dumps(doc), encoding="utf-8")


@pytest.mark.parametrize("name", sorted(BRIEFS))
@pytest.mark.parametrize(
    ("reviewer", "expected"),
    [
        pytest.param(_writes(PASS_DOC), EXIT_PASS, id="pass"),
        pytest.param(_writes({"verdict": "FAIL", "findings": [FINDING]}), EXIT_REJECTED, id="fail"),
        pytest.param(lambda ws: None, EXIT_INVALID, id="reviewer-wrote-nothing"),
    ],
)
def test_job_steps_gate_on_the_reviewer_verdict(tmp_path: Path, name: str, reviewer: Reviewer, expected: int) -> None:
    proc = _run_job(tmp_path, _jobs()[name], reviewer)
    assert proc.returncode == expected, proc.stderr


@pytest.mark.parametrize("name", sorted(BRIEFS))
def test_a_verdict_committed_in_the_pr_cannot_pass_the_job(tmp_path: Path, name: str) -> None:
    def committed_then_silent(ws: Path) -> None:
        return None

    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "p9-verdict.json").write_text(json.dumps(PASS_DOC), encoding="utf-8")
    proc = _run_job(tmp_path, _jobs()[name], committed_then_silent)
    assert proc.returncode == EXIT_INVALID, proc.stderr


@pytest.mark.parametrize("name", sorted(BRIEFS))
def test_reviewer_cannot_swap_the_gate_script(tmp_path: Path, name: str) -> None:
    def tamper(ws: Path) -> None:
        (ws / ".github" / "p9" / "check_verdict.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
        _writes({"verdict": "FAIL", "findings": [FINDING]})(ws)

    proc = _run_job(tmp_path, _jobs()[name], tamper)
    assert proc.returncode == EXIT_REJECTED, proc.stderr


# --- retirement of the local pre-push gate ------------------------------------


@pytest.mark.parametrize(
    "rel",
    [
        ".githooks/pre-push",
        ".githooks/pre-push.sha256",
        ".github/workflows/enforce-p9-review.yml",
        "scripts/ci/p9-sibling-parity.sh",
        "src/backend/tests/p9_gate_harness.sh",
    ],
)
def test_retired_p9_gate_files_are_gone(rel: str) -> None:
    assert not (REPO_ROOT / rel).exists(), f"{rel} belongs to the retired local P9 gate"


def test_pre_commit_hook_and_installer_are_tracked_executable() -> None:
    out = subprocess.run(
        ["git", "ls-files", "-s", ".githooks/pre-commit", "scripts/install-hooks.sh"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.splitlines()
    assert len(out) == 2 and all(line.startswith("100755 ") for line in out), out


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required to run the installer")
def test_installer_wires_pre_commit_and_no_longer_creates_reviews(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(HOME=str(home), GIT_CONFIG_GLOBAL=str(home / ".gitconfig"), GIT_CONFIG_NOSYSTEM="1")
    repo = tmp_path / "repo"
    (repo / ".githooks").mkdir(parents=True)
    (repo / "scripts").mkdir()
    shutil.copy2(REPO_ROOT / ".githooks" / "pre-commit", repo / ".githooks" / "pre-commit")
    shutil.copy2(INSTALLER, repo / "scripts" / "install-hooks.sh")
    (repo / ".githooks" / "pre-commit").chmod(0o644)
    subprocess.run(["git", "init", "-q"], cwd=repo, env=env, check=True)

    proc = subprocess.run(
        ["bash", "scripts/install-hooks.sh"], cwd=repo, env=env, text=True, capture_output=True
    )

    assert proc.returncode == 0, proc.stderr
    hooks_path = subprocess.run(
        ["git", "config", "--get", "core.hooksPath"], cwd=repo, env=env, text=True, capture_output=True
    ).stdout.strip()
    assert hooks_path == ".githooks"
    assert os.access(repo / ".githooks" / "pre-commit", os.X_OK)
    assert not (repo / ".git" / "reviews").exists()
