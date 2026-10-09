"""Board sync as a GitHub Action (agent-setup audit item 5, 2026-10-09).

Per-event project-manager agent dispatches are replaced by
``.github/workflows/board-sync.yml``. The workflow keeps the owner's
Projects v2 board in step with issues and pull requests:

- issue opened                         -> added to the board, Backlog
- issue closed as not planned          -> Done
- PR opened / reopened / ready for review (not draft) -> linked issues In review
- PR merged                            -> linked issues Done

Routing, config validation and the GitHub calls live in
``.github/board-sync/board_sync.py`` (stdlib only). The board, the field and
the option names come from ``.github/board-sync/config.json``; their IDs are
resolved by name at run time, never written down.

Covered here:
- the helper's config loader (exact schema, fail closed);
- the routing table, run as ``plan`` over real-shaped event payloads;
- ``apply`` against a fake ``gh`` on PATH: the exact GraphQL variables and
  ``gh project item-edit`` arguments, every error path, hostile API output;
- the workflow's shape: triggers (parity with the helper), SHA pins,
  permissions, fork guard, the loud missing-secret step (run under bash),
  no hard-coded board IDs, and the plan and apply steps run end to end;
- the doc's status table against the config.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "board-sync.yml"
HELPER_DIR = REPO_ROOT / ".github" / "board-sync"
HELPER = HELPER_DIR / "board_sync.py"
CONFIG = HELPER_DIR / "config.json"
DOC = REPO_ROOT / "automations" / "board-sync.md"

# Exit-code contract of board_sync.py.
EXIT_OK = 0
EXIT_FAILED = 1  # GitHub call failed, or the board does not match the config
EXIT_INVALID = 2  # bad config, environment, event payload or usage

EVENT_KEYS = {"issue_opened", "issue_closed_not_planned", "pr_ready", "pr_merged"}
CONFIG_KEYS = {
    "project_url",
    "status_field",
    "statuses",
    "gh_timeout_seconds",
    "gh_output_max_bytes",
    "max_linked_issues",
    "message_max_chars",
}
SECRET_EXPR = "${{ secrets.PROJECT_TOKEN }}"
FORK_GUARD = (
    "github.event_name == 'issues' || "
    "github.event.pull_request.head.repo.full_name == github.repository"
)
ACTION_REPOS = {"actions/checkout", "actions/add-to-project"}
TEST_REPO = "example-owner/example-repo"
RUN_TIMEOUT = 60

HOSTILE_TEXT = {
    "newline-forges-a-line": "x\nboard-sync: moved 9 issue(s)",
    "workflow-command": "x\n::add-mask::secret",
    "carriage-return": "x\rboard-sync: ok",
    "unicode-line-separator": "x board-sync: ok",
    "bidi-override": "x‮ko",
    "nul": "x\x00y",
}

# Fake gh: logs every call, answers by GraphQL operation name or subcommand.
# FAKE_GH_STATE maps a kind (operation name, or "item-edit") to a response:
# {"stdout": str, "stderr": str, "rc": int, "sleep": float, "big": int}.
# BoardSyncAddItem with no stdout echoes an item id built from the content id.
FAKE_GH = r'''
import json, os, re, sys, time
state = json.loads(open(os.environ["FAKE_GH_STATE"], encoding="utf-8").read())
args = sys.argv[1:]
body = sys.stdin.read() if args[:2] == ["api", "graphql"] else ""
with open(os.environ["FAKE_GH_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps({"args": args, "body": body}) + "\n")
kind = "unknown"
variables = {}
if args[:2] == ["api", "graphql"]:
    doc = json.loads(body)
    variables = doc.get("variables", {})
    match = re.search(r"\b(query|mutation)\s+(\w+)", doc["query"])
    kind = match.group(2) if match else "anonymous"
elif args[:2] == ["project", "item-edit"]:
    kind = "item-edit"
resp = state.get(kind, {"rc": 97, "stderr": "fake gh: unexpected call " + kind})
if resp.get("sleep"):
    time.sleep(resp["sleep"])
out = resp.get("stdout")
if out is None and kind == "BoardSyncAddItem":
    out = json.dumps({"data": {"addProjectV2ItemById": {"item": {"id": "ITEM_" + variables["content"]}}}})
if resp.get("big"):
    out = "x" * resp["big"]
sys.stdout.write(out or "")
sys.stderr.write(resp.get("stderr", ""))
sys.exit(resp.get("rc", 0))
'''


# --- helpers -----------------------------------------------------------------


def _real_config() -> dict[str, Any]:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def _write_config(tmp_path: Path, **overrides: Any) -> Path:
    """The real config with test overrides (tests never restate its values)."""
    doc = _real_config()
    doc.update(overrides)
    target = tmp_path / "config.json"
    target.write_text(json.dumps(doc), encoding="utf-8")
    return target


def _random_id(prefix: str) -> str:
    # Fresh per run, so a passing test proves IDs are resolved, not stored.
    return f"{prefix}_{secrets.token_hex(6)}"


class Board:
    """A fake board with random IDs and the configured option names."""

    def __init__(self, option_names: list[str] | None = None) -> None:
        cfg = _real_config()
        names = option_names if option_names is not None else sorted(set(cfg["statuses"].values()))
        self.project_id = _random_id("PVT")
        self.field_id = _random_id("PVTSSF")
        self.options = {name: secrets.token_hex(4) for name in names}
        self.field_name = cfg["status_field"]

    def response(self) -> dict[str, Any]:
        return {
            "data": {
                "user": {
                    "projectV2": {
                        "id": self.project_id,
                        "field": {
                            "__typename": "ProjectV2SingleSelectField",
                            "id": self.field_id,
                            "name": self.field_name,
                            "options": [{"id": oid, "name": name} for name, oid in self.options.items()],
                        },
                    }
                }
            }
        }

    def option_for(self, event_key: str) -> str:
        return self.options[_real_config()["statuses"][event_key]]


def _linked(ids: list[str], total: int | None = None) -> dict[str, Any]:
    return {
        "data": {
            "repository": {
                "pullRequest": {
                    "closingIssuesReferences": {
                        "totalCount": len(ids) if total is None else total,
                        "nodes": [{"id": i, "number": n + 1} for n, i in enumerate(ids)],
                    }
                }
            }
        }
    }


def _ok(doc: dict[str, Any]) -> dict[str, Any]:
    return {"stdout": json.dumps(doc)}


class Env:
    """A temp workspace: fake gh on PATH, event payload, GITHUB_OUTPUT."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        fake = self.bin / "gh"
        fake.write_text(f"#!{sys.executable}\n{FAKE_GH}", encoding="utf-8")
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        self.state_file = tmp_path / "gh-state.json"
        self.log_file = tmp_path / "gh-log.jsonl"
        self.output_file = tmp_path / "github-output"
        self.event_file = tmp_path / "event.json"
        self.state: dict[str, Any] = {}

    def env(self, event_name: str, payload: object, **extra: str) -> dict[str, str]:
        self.event_file.write_text(json.dumps(payload), encoding="utf-8")
        self.state_file.write_text(json.dumps(self.state), encoding="utf-8")
        base = {
            "PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}",
            "HOME": str(self.tmp),
            "FAKE_GH_STATE": str(self.state_file),
            "FAKE_GH_LOG": str(self.log_file),
            "GITHUB_EVENT_NAME": event_name,
            "GITHUB_EVENT_PATH": str(self.event_file),
            "GITHUB_OUTPUT": str(self.output_file),
            "GITHUB_REPOSITORY": TEST_REPO,
            "GH_TOKEN": "test-token",
            "ITEM_ID": "",
        }
        base.update(extra)
        return base

    def calls(self) -> list[dict[str, Any]]:
        if not self.log_file.exists():
            return []
        return [json.loads(line) for line in self.log_file.read_text(encoding="utf-8").splitlines()]

    def graphql_calls(self, operation: str) -> list[dict[str, Any]]:
        found = []
        for call in self.calls():
            if call["args"][:2] == ["api", "graphql"]:
                doc = json.loads(call["body"])
                if re.search(rf"\b(query|mutation)\s+{operation}\b", doc["query"]):
                    found.append(doc["variables"])
        return found

    def edits(self) -> list[list[str]]:
        return [c["args"] for c in self.calls() if c["args"][:2] == ["project", "item-edit"]]

    def outputs(self) -> dict[str, str]:
        if not self.output_file.exists():
            return {}
        pairs = [line.split("=", 1) for line in self.output_file.read_text(encoding="utf-8").splitlines()]
        return {k: v for k, v in pairs}


def _run(cmd: str, env: dict[str, str], config: Path | None = None) -> subprocess.CompletedProcess[str]:
    args = [sys.executable, "-I", str(HELPER), cmd]
    if config is not None:
        args += ["--config", str(config)]
    return subprocess.run(args, env=env, text=True, capture_output=True, timeout=RUN_TIMEOUT)


def _edit_args(item: str, board: Board, event_key: str) -> list[str]:
    return [
        "project",
        "item-edit",
        "--id",
        item,
        "--project-id",
        board.project_id,
        "--field-id",
        board.field_id,
        "--single-select-option-id",
        board.option_for(event_key),
    ]


def _issue_event(action: str, state_reason: str | None = None, node_id: str = "I_kwTestIssue1") -> dict[str, Any]:
    return {"action": action, "issue": {"number": 5, "node_id": node_id, "state_reason": state_reason}}


def _pr_event(action: str, *, draft: bool = False, merged: bool = False, number: int = 12) -> dict[str, Any]:
    return {"action": action, "pull_request": {"number": number, "draft": draft, "merged": merged}}


def _workflow() -> dict[str, Any]:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _triggers(doc: dict[str, Any]) -> dict[str, Any]:
    # PyYAML (YAML 1.1) reads the bare key `on` as boolean True.
    return doc.get("on", doc.get(True))


def _job() -> dict[str, Any]:
    jobs = _workflow()["jobs"]
    assert list(jobs) == ["board-sync"]
    return jobs["board-sync"]


def _step(name: str) -> dict[str, Any]:
    found = [s for s in _job()["steps"] if s.get("name") == name]
    assert len(found) == 1, f"expected one step named {name!r}"
    return found[0]


def _single_line(text: str) -> None:
    for bad in ("\r", "\x00", " ", "‮"):
        assert bad not in text
    assert "::add-mask::" not in text or text.count("\n") <= 1


# --- config loader -----------------------------------------------------------


def test_real_config_has_exactly_the_schema_keys() -> None:
    doc = _real_config()
    assert set(doc) == CONFIG_KEYS
    assert set(doc["statuses"]) == EVENT_KEYS


def _drop(key: str) -> dict[str, Any]:
    doc = _real_config()
    del doc[key]
    return doc


def _with(**overrides: Any) -> dict[str, Any]:
    doc = _real_config()
    doc.update(overrides)
    return doc


def _statuses(**overrides: Any) -> dict[str, Any]:
    statuses = dict(_real_config()["statuses"])
    for key, value in overrides.items():
        if value is None:
            del statuses[key]
        else:
            statuses[key] = value
    return _with(statuses=statuses)


BAD_CONFIGS = {
    "missing-key": lambda: _drop("status_field"),
    "extra-key": lambda: _with(extra=1),
    "url-org-project": lambda: _with(project_url="https://github.com/orgs/acme/projects/7"),
    "url-http": lambda: _with(project_url="http://github.com/users/acme/projects/7"),
    "url-other-host": lambda: _with(project_url="https://github.com.evil/users/acme/projects/7"),
    "url-trailing-slash": lambda: _with(project_url="https://github.com/users/acme/projects/7/"),
    "url-newline": lambda: _with(project_url="https://github.com/users/acme/projects/7\nevent=pr_merged"),
    "url-project-zero": lambda: _with(project_url="https://github.com/users/acme/projects/0"),
    "url-not-string": lambda: _with(project_url=7),
    "field-blank": lambda: _with(status_field="  "),
    "field-control-char": lambda: _with(status_field="Sta\ntus"),
    "statuses-missing-key": lambda: _statuses(pr_merged=None),
    "statuses-extra-key": lambda: _statuses(pr_closed="Done"),
    "statuses-blank-value": lambda: _statuses(pr_ready=""),
    "statuses-non-string": lambda: _statuses(pr_ready=3),
    "statuses-not-object": lambda: _with(statuses=["Done"]),
    "timeout-zero": lambda: _with(gh_timeout_seconds=0),
    "timeout-bool": lambda: _with(gh_timeout_seconds=True),
    "timeout-string": lambda: _with(gh_timeout_seconds="30"),
    "timeout-too-big": lambda: _with(gh_timeout_seconds=601),
    "cap-zero": lambda: _with(gh_output_max_bytes=0),
    "linked-zero": lambda: _with(max_linked_issues=0),
    "linked-over-page-limit": lambda: _with(max_linked_issues=101),
    "message-cap-negative": lambda: _with(message_max_chars=-1),
    "not-an-object": lambda: [1, 2],
}


@pytest.mark.parametrize("case", sorted(BAD_CONFIGS))
def test_bad_config_fails_closed_before_any_github_call(tmp_path: Path, case: str) -> None:
    env = Env(tmp_path)
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(BAD_CONFIGS[case]()), encoding="utf-8")
    for cmd in ("plan", "apply"):
        proc = _run(cmd, env.env("issues", _issue_event("opened"), ITEM_ID="PVTI_x"), cfg)
        assert proc.returncode == EXIT_INVALID, (case, cmd, proc.stderr)
        assert "config" in proc.stderr
    assert env.calls() == []
    assert env.outputs() == {}


@pytest.mark.parametrize(
    "content",
    ["", "{", "not json", '{"project_url": 1, "project_url": 2}'],
    ids=["empty", "truncated", "not-json", "duplicate-key"],
)
def test_unparseable_config_fails_closed(tmp_path: Path, content: str) -> None:
    env = Env(tmp_path)
    cfg = tmp_path / "config.json"
    cfg.write_text(content, encoding="utf-8")
    proc = _run("plan", env.env("issues", _issue_event("opened")), cfg)
    assert proc.returncode == EXIT_INVALID
    assert "config" in proc.stderr


def test_missing_config_fails_closed(tmp_path: Path) -> None:
    env = Env(tmp_path)
    proc = _run("plan", env.env("issues", _issue_event("opened")), tmp_path / "absent.json")
    assert proc.returncode == EXIT_INVALID
    assert "config" in proc.stderr
    assert str(tmp_path) not in proc.stderr  # F8: no absolute paths


@pytest.mark.parametrize(
    ("key", "value"),
    [("gh_timeout_seconds", 1), ("gh_timeout_seconds", 600), ("max_linked_issues", 1), ("max_linked_issues", 100)],
)
def test_config_bounds_are_inclusive(tmp_path: Path, key: str, value: int) -> None:
    env = Env(tmp_path)
    proc = _run("plan", env.env("issues", _issue_event("opened")), _write_config(tmp_path, **{key: value}))
    assert proc.returncode == EXIT_OK, proc.stderr


# --- routing (plan) ----------------------------------------------------------

ROUTES = [
    ("issues", _issue_event("opened"), "issue_opened"),
    ("issues", _issue_event("closed", "not_planned"), "issue_closed_not_planned"),
    ("issues", _issue_event("closed", "completed"), ""),
    ("issues", _issue_event("closed", "duplicate"), ""),
    ("issues", _issue_event("closed", None), ""),
    ("pull_request_target", _pr_event("opened"), "pr_ready"),
    ("pull_request_target", _pr_event("reopened"), "pr_ready"),
    ("pull_request_target", _pr_event("ready_for_review"), "pr_ready"),
    ("pull_request_target", _pr_event("opened", draft=True), ""),
    ("pull_request_target", _pr_event("reopened", draft=True), ""),
    ("pull_request_target", _pr_event("closed", merged=True), "pr_merged"),
    ("pull_request_target", _pr_event("closed", merged=False), ""),
]


@pytest.mark.parametrize(("event_name", "payload", "expected"), ROUTES)
def test_plan_routes_each_event(tmp_path: Path, event_name: str, payload: dict[str, Any], expected: str) -> None:
    env = Env(tmp_path)
    proc = _run("plan", env.env(event_name, payload))
    assert proc.returncode == EXIT_OK, proc.stderr
    cfg = _real_config()
    assert env.outputs() == {"project_url": cfg["project_url"], "event": expected}
    if expected:
        assert f'-> "{cfg["statuses"][expected]}"' in proc.stdout
    else:
        assert "skip" in proc.stdout
    assert env.calls() == []  # plan never calls GitHub


def test_route_table_covers_every_event_key() -> None:
    assert {expected for _, _, expected in ROUTES if expected} == EVENT_KEYS


# case -> (event name, payload, text the error must contain)
BAD_EVENTS = {
    "unhandled-event": ("push", {"action": "opened"}, "event push"),
    "plain-pull-request-event": ("pull_request", _pr_event("opened"), "event pull_request"),
    "unhandled-issue-action": ("issues", _issue_event("edited"), "action"),
    "unhandled-pr-action": ("pull_request_target", _pr_event("synchronize"), "action"),
    "action-with-newline": ("issues", {"action": "opened\nevent=pr_merged", "issue": {"node_id": "I_x"}}, "action"),
    "payload-not-object": ("issues", ["opened"], "payload"),
    "issue-missing": ("issues", {"action": "opened"}, "issue"),
    "node-id-hostile": ("issues", _issue_event("closed", "not_planned", node_id="I_x\n--clear"), "node_id"),
    "node-id-empty": ("issues", _issue_event("opened", node_id=""), "node_id"),
    "state-reason-unknown": ("issues", _issue_event("closed", "wontfix"), "state_reason"),
    "pr-missing": ("pull_request_target", {"action": "opened"}, "pull_request"),
    "pr-number-zero": ("pull_request_target", _pr_event("opened", number=0), "number"),
    "pr-number-bool": ("pull_request_target", {"action": "opened", "pull_request": {"number": True, "draft": False, "merged": False}}, "number"),
    "pr-number-string": ("pull_request_target", {"action": "opened", "pull_request": {"number": "12", "draft": False, "merged": False}}, "number"),
    "pr-draft-not-bool": ("pull_request_target", {"action": "opened", "pull_request": {"number": 1, "draft": "no", "merged": False}}, "draft"),
    "pr-merged-missing": ("pull_request_target", {"action": "closed", "pull_request": {"number": 1, "draft": False}}, "merged"),
}


@pytest.mark.parametrize("case", sorted(BAD_EVENTS))
def test_plan_rejects_unhandled_or_malformed_events(tmp_path: Path, case: str) -> None:
    event_name, payload, reason = BAD_EVENTS[case]
    env = Env(tmp_path)
    proc = _run("plan", env.env(event_name, payload))
    assert proc.returncode == EXIT_INVALID, (case, proc.stdout, proc.stderr)
    assert proc.stderr.startswith("board-sync: error:"), proc.stderr
    assert reason in proc.stderr, (case, proc.stderr)
    assert env.outputs() == {}
    _single_line(proc.stderr.strip())


@pytest.mark.parametrize("missing", ["GITHUB_EVENT_NAME", "GITHUB_EVENT_PATH", "GITHUB_OUTPUT"])
def test_plan_fails_closed_without_its_environment(tmp_path: Path, missing: str) -> None:
    env = Env(tmp_path)
    run_env = env.env("issues", _issue_event("opened"))
    del run_env[missing]
    proc = _run("plan", run_env)
    assert proc.returncode == EXIT_INVALID
    assert missing in proc.stderr


@pytest.mark.parametrize("content", ["", "{", "\xff"], ids=["empty", "truncated", "not-utf8"])
def test_plan_fails_closed_on_unreadable_payload(tmp_path: Path, content: str) -> None:
    env = Env(tmp_path)
    run_env = env.env("issues", {})
    env.event_file.write_bytes(content.encode("latin-1"))
    proc = _run("plan", run_env)
    assert proc.returncode == EXIT_INVALID
    assert "payload" in proc.stderr


def test_usage_errors_exit_invalid(tmp_path: Path) -> None:
    env = Env(tmp_path)
    for args in ([], ["frobnicate"]):
        proc = subprocess.run(
            [sys.executable, "-I", str(HELPER), *args],
            env=env.env("issues", {}),
            text=True,
            capture_output=True,
            timeout=RUN_TIMEOUT,
        )
        assert proc.returncode == EXIT_INVALID
        assert "usage: board_sync.py" in proc.stderr


# --- apply against a fake gh -------------------------------------------------


def _apply(env: Env, event_name: str, payload: object, board: Board | None = None, **extra: str):
    if board is not None:
        env.state.setdefault("BoardSyncProject", _ok(board.response()))
    return _run("apply", env.env(event_name, payload, **extra))


@pytest.mark.parametrize(("action", "merged", "key"), [("opened", False, "pr_ready"), ("closed", True, "pr_merged")])
def test_apply_moves_every_linked_issue(tmp_path: Path, action: str, merged: bool, key: str) -> None:
    env = Env(tmp_path)
    board = Board()
    issues = ["I_kwIssueA", "I_kwIssueB"]
    env.state["BoardSyncLinkedIssues"] = _ok(_linked(issues))
    proc = _apply(env, "pull_request_target", _pr_event(action, merged=merged, number=42), board)
    assert proc.returncode == EXIT_OK, proc.stderr

    cfg = _real_config()
    owner, number = re.fullmatch(r"https://github\.com/users/([^/]+)/projects/(\d+)", cfg["project_url"]).groups()
    assert env.graphql_calls("BoardSyncProject") == [
        {"login": owner, "number": int(number), "field": cfg["status_field"]}
    ]
    assert env.graphql_calls("BoardSyncLinkedIssues") == [
        {"owner": "example-owner", "repo": "example-repo", "number": 42, "first": cfg["max_linked_issues"]}
    ]
    assert env.graphql_calls("BoardSyncAddItem") == [
        {"project": board.project_id, "content": i} for i in issues
    ]
    assert env.edits() == [_edit_args(f"ITEM_{i}", board, key) for i in issues]
    assert f'moved 2 issue(s) to "{cfg["statuses"][key]}"' in proc.stdout


def test_apply_issue_closed_not_planned_adds_then_sets_done(tmp_path: Path) -> None:
    env = Env(tmp_path)
    board = Board()
    proc = _apply(env, "issues", _issue_event("closed", "not_planned", node_id="I_kwClosed"), board)
    assert proc.returncode == EXIT_OK, proc.stderr
    assert env.graphql_calls("BoardSyncAddItem") == [{"project": board.project_id, "content": "I_kwClosed"}]
    assert env.edits() == [_edit_args("ITEM_I_kwClosed", board, "issue_closed_not_planned")]
    assert "moved 1 issue(s)" in proc.stdout


def test_apply_issue_opened_sets_backlog_on_the_added_item(tmp_path: Path) -> None:
    env = Env(tmp_path)
    board = Board()
    proc = _apply(env, "issues", _issue_event("opened"), board, ITEM_ID="PVTI_lAddedByAction")
    assert proc.returncode == EXIT_OK, proc.stderr
    assert env.graphql_calls("BoardSyncAddItem") == []  # actions/add-to-project already added it
    assert env.edits() == [_edit_args("PVTI_lAddedByAction", board, "issue_opened")]


@pytest.mark.parametrize("item", ["", "  ", "PVTI_x\n--clear", "PVTI x", "a" * 129])
def test_apply_issue_opened_rejects_missing_or_hostile_item_id(tmp_path: Path, item: str) -> None:
    env = Env(tmp_path)
    proc = _apply(env, "issues", _issue_event("opened"), Board(), ITEM_ID=item)
    assert proc.returncode == EXIT_INVALID
    assert "ITEM_ID" in proc.stderr
    assert env.edits() == []


def test_apply_pr_with_no_linked_issues_reports_zero(tmp_path: Path) -> None:
    env = Env(tmp_path)
    env.state["BoardSyncLinkedIssues"] = _ok(_linked([]))
    proc = _apply(env, "pull_request_target", _pr_event("opened"), Board())
    assert proc.returncode == EXIT_OK, proc.stderr
    assert "links 0 issue(s)" in proc.stdout
    assert "moved 0 issue(s)" in proc.stdout
    assert env.edits() == []


@pytest.mark.parametrize("token", ["", "   "])
def test_apply_without_a_token_fails_loudly_before_any_call(tmp_path: Path, token: str) -> None:
    env = Env(tmp_path)
    proc = _apply(env, "pull_request_target", _pr_event("opened"), Board(), GH_TOKEN=token)
    assert proc.returncode == EXIT_INVALID
    assert "PROJECT_TOKEN" in proc.stderr
    assert env.calls() == []


def test_apply_refuses_an_event_plan_skipped(tmp_path: Path) -> None:
    env = Env(tmp_path)
    proc = _apply(env, "pull_request_target", _pr_event("opened", draft=True), Board())
    assert proc.returncode == EXIT_INVALID
    assert "nothing to apply" in proc.stderr
    assert env.calls() == []


def _project(project: object) -> dict[str, Any]:
    return _ok({"data": {"user": {"projectV2": project}}})


def _with_field(board: Board, **changes: Any) -> dict[str, Any]:
    doc = board.response()
    doc["data"]["user"]["projectV2"]["field"].update(changes)
    return _ok(doc)


BOARD_MISMATCHES = {
    "project-not-found": lambda b: _project(None),
    "user-not-found": lambda b: _ok({"data": {"user": None}}),
    "field-not-found": lambda b: _project({"id": b.project_id, "field": None}),
    "field-not-single-select": lambda b: _with_field(b, __typename="ProjectV2Field"),
    "option-missing": lambda b: _with_field(b, options=[{"id": "aa11", "name": "Somewhere else"}]),
    "option-duplicated": lambda b: _with_field(
        b, options=[{"id": "aa11", "name": _real_config()["statuses"]["pr_ready"]}] * 2
    ),
    "options-not-list": lambda b: _with_field(b, options=None),
    "project-id-hostile": lambda b: _project({"id": "PVT x\n", "field": b.response()["data"]["user"]["projectV2"]["field"]}),
    "option-id-hostile": lambda b: _with_field(
        b, options=[{"id": "--clear", "name": _real_config()["statuses"]["pr_ready"]}]
    ),
}


@pytest.mark.parametrize("case", sorted(BOARD_MISMATCHES))
def test_apply_fails_when_the_board_does_not_match_the_config(tmp_path: Path, case: str) -> None:
    env = Env(tmp_path)
    board = Board()
    env.state["BoardSyncProject"] = BOARD_MISMATCHES[case](board)
    env.state["BoardSyncLinkedIssues"] = _ok(_linked(["I_kwA"]))
    proc = _apply(env, "pull_request_target", _pr_event("opened"))
    assert proc.returncode == EXIT_FAILED, (case, proc.stderr)
    assert env.edits() == []
    _single_line(proc.stderr.strip())


def test_missing_option_message_names_the_status_and_the_board_options(tmp_path: Path) -> None:
    env = Env(tmp_path)
    board = Board(option_names=["Todo", "Doing"])
    proc = _apply(env, "pull_request_target", _pr_event("opened"), board)
    assert proc.returncode == EXIT_FAILED
    wanted = _real_config()["statuses"]["pr_ready"]
    assert wanted in proc.stderr
    assert "Todo" in proc.stderr and "Doing" in proc.stderr


GH_FAILURES = {
    "nonzero-exit": {"rc": 1, "stderr": "HTTP 401: Bad credentials"},
    "not-json": {"stdout": "<html>"},
    "graphql-errors": {"stdout": json.dumps({"errors": [{"message": "Resource not accessible"}]})},
    "data-missing": {"stdout": json.dumps({})},
    "not-an-object": {"stdout": "[]"},
}


@pytest.mark.parametrize("case", sorted(GH_FAILURES))
def test_apply_fails_closed_on_github_errors(tmp_path: Path, case: str) -> None:
    env = Env(tmp_path)
    env.state["BoardSyncProject"] = GH_FAILURES[case]
    proc = _apply(env, "issues", _issue_event("closed", "not_planned"))
    assert proc.returncode == EXIT_FAILED, (case, proc.stderr)
    assert env.edits() == []


def test_apply_reports_the_github_error_text(tmp_path: Path) -> None:
    env = Env(tmp_path)
    env.state["BoardSyncProject"] = GH_FAILURES["nonzero-exit"]
    proc = _apply(env, "issues", _issue_event("closed", "not_planned"))
    assert "Bad credentials" in proc.stderr


def test_apply_times_out_a_hanging_gh(tmp_path: Path) -> None:
    env = Env(tmp_path)
    env.state["BoardSyncProject"] = {"sleep": 30}
    cfg = _write_config(tmp_path, gh_timeout_seconds=1)
    proc = _run("apply", env.env("issues", _issue_event("closed", "not_planned")), cfg)
    assert proc.returncode == EXIT_FAILED
    assert "timed out after 1s" in proc.stderr


def test_apply_caps_gh_output(tmp_path: Path) -> None:
    env = Env(tmp_path)
    env.state["BoardSyncProject"] = {"big": 5000}
    cfg = _write_config(tmp_path, gh_output_max_bytes=4096)
    proc = _run("apply", env.env("issues", _issue_event("closed", "not_planned")), cfg)
    assert proc.returncode == EXIT_FAILED
    assert "4096 bytes" in proc.stderr


def test_apply_fails_when_gh_is_not_installed(tmp_path: Path) -> None:
    env = Env(tmp_path)
    run_env = env.env("issues", _issue_event("closed", "not_planned"))
    run_env["PATH"] = str(tmp_path / "empty-bin")
    proc = _run("apply", run_env)
    assert proc.returncode == EXIT_FAILED
    assert "gh" in proc.stderr and "not found" in proc.stderr


def test_apply_refuses_more_linked_issues_than_the_cap(tmp_path: Path) -> None:
    env = Env(tmp_path)
    cap = _real_config()["max_linked_issues"]
    env.state["BoardSyncLinkedIssues"] = _ok(_linked(["I_kwA"], total=cap + 1))
    proc = _apply(env, "pull_request_target", _pr_event("opened"), Board())
    assert proc.returncode == EXIT_FAILED
    assert "max_linked_issues" in proc.stderr
    assert env.edits() == []


@pytest.mark.parametrize(
    "refs",
    [
        None,
        {"totalCount": 2, "nodes": [{"id": "I_kwA"}]},
        {"totalCount": 1, "nodes": [None]},
        {"totalCount": 1, "nodes": [{"id": "I_kw A\n"}]},
        {"totalCount": True, "nodes": []},
    ],
    ids=["pr-not-found", "count-mismatch", "null-node", "hostile-id", "bool-count"],
)
def test_apply_rejects_malformed_linked_issue_data(tmp_path: Path, refs: object) -> None:
    env = Env(tmp_path)
    env.state["BoardSyncLinkedIssues"] = _ok({"data": {"repository": {"pullRequest": None if refs is None else {"closingIssuesReferences": refs}}}})
    proc = _apply(env, "pull_request_target", _pr_event("opened"), Board())
    assert proc.returncode == EXIT_FAILED
    assert env.edits() == []


def test_apply_rejects_a_hostile_added_item_id(tmp_path: Path) -> None:
    env = Env(tmp_path)
    env.state["BoardSyncAddItem"] = _ok({"data": {"addProjectV2ItemById": {"item": {"id": "--clear"}}}})
    proc = _apply(env, "issues", _issue_event("closed", "not_planned"), Board())
    assert proc.returncode == EXIT_FAILED
    assert env.edits() == []


def test_apply_reports_progress_when_an_edit_fails_midway(tmp_path: Path) -> None:
    env = Env(tmp_path)
    env.state["BoardSyncLinkedIssues"] = _ok(_linked(["I_kwA", "I_kwB"]))
    env.state["item-edit"] = {"rc": 1, "stderr": "boom"}
    proc = _apply(env, "pull_request_target", _pr_event("opened"), Board())
    assert proc.returncode == EXIT_FAILED
    assert "moved 0 of 2" in proc.stderr
    assert len(env.edits()) == 1  # stops at the first failure


def test_apply_rejects_a_bad_repository_name(tmp_path: Path) -> None:
    env = Env(tmp_path)
    proc = _apply(env, "pull_request_target", _pr_event("opened"), Board(), GITHUB_REPOSITORY="owner/repo\nx")
    assert proc.returncode == EXIT_INVALID
    assert "GITHUB_REPOSITORY" in proc.stderr


@pytest.mark.parametrize("name", sorted(HOSTILE_TEXT))
def test_github_error_text_is_printed_on_one_sanitised_line(tmp_path: Path, name: str) -> None:
    env = Env(tmp_path)
    env.state["BoardSyncProject"] = {"rc": 1, "stderr": HOSTILE_TEXT[name]}
    proc = _apply(env, "issues", _issue_event("closed", "not_planned"))
    assert proc.returncode == EXIT_FAILED
    assert proc.stderr.count("\n") == 1, proc.stderr
    _single_line(proc.stderr.rstrip("\n"))


def test_github_error_text_is_truncated(tmp_path: Path) -> None:
    env = Env(tmp_path)
    env.state["BoardSyncProject"] = {"rc": 1, "stderr": "E" * 5000}
    cfg = _write_config(tmp_path, message_max_chars=300)
    proc = _run("apply", env.env("issues", _issue_event("closed", "not_planned")), cfg)
    assert proc.returncode == EXIT_FAILED
    assert len(proc.stderr.rstrip("\n")) <= 300


# --- workflow shape ----------------------------------------------------------


def test_triggers_match_the_helper_routes() -> None:
    triggers = _triggers(_workflow())
    assert set(triggers) == {"issues", "pull_request_target"}
    routed: dict[str, set[str]] = {}
    for event_name, payload, _ in ROUTES:
        routed.setdefault(event_name, set()).add(payload["action"])
    for event_name, spec in triggers.items():
        assert set(spec) == {"types"}
        assert set(spec["types"]) == routed[event_name]


def test_every_action_is_pinned_to_a_full_sha_with_its_tag() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    uses = re.findall(r"uses:\s*(\S+)(.*)", text)
    assert {u.split("@")[0] for u, _ in uses} == ACTION_REPOS
    for ref, comment in uses:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", ref), ref
        assert re.fullmatch(r"\s*#\s*v\d+(\.\d+)*", comment), (ref, comment)


def test_permissions_are_least_privilege() -> None:
    doc = _workflow()
    assert doc["permissions"] == {}
    assert _job()["permissions"] == {"contents": "read"}


def test_fork_prs_never_reach_the_token() -> None:
    assert _job()["if"] == FORK_GUARD


def test_pull_request_target_never_runs_pr_code() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    checkout = [s for s in _job()["steps"] if str(s.get("uses", "")).startswith("actions/checkout@")]
    assert len(checkout) == 1
    assert checkout[0]["with"] == {"persist-credentials": False}  # no ref: the base branch
    assert "pull_request.head.sha" not in text
    assert "pull_request.head.ref" not in text
    assert "github.head_ref" not in text


def test_job_is_bounded_and_runs_do_not_cancel_each_other() -> None:
    doc = _workflow()
    assert 0 < _job()["timeout-minutes"] <= 10
    assert doc["concurrency"]["cancel-in-progress"] is False


def test_token_check_is_the_first_step() -> None:
    steps = _job()["steps"]
    assert steps[0]["name"] == "Require the board token"
    assert steps[0]["env"] == {"PROJECT_TOKEN": SECRET_EXPR}
    for step in steps:
        assert "continue-on-error" not in step


def _run_token_step(value: str | None) -> subprocess.CompletedProcess[str]:
    env = {"PATH": os.environ.get("PATH", "")}
    if value is not None:
        env["PROJECT_TOKEN"] = value
    return subprocess.run(
        ["bash", "-e", "-c", _step("Require the board token")["run"]],
        env=env,
        text=True,
        capture_output=True,
        timeout=RUN_TIMEOUT,
    )


@pytest.mark.parametrize("value", [None, "", "   "], ids=["unset", "empty", "blank"])
def test_missing_secret_fails_the_job_loudly(value: str | None) -> None:
    proc = _run_token_step(value)
    assert proc.returncode == 1
    out = proc.stdout + proc.stderr
    assert "::error" in out
    assert "PROJECT_TOKEN" in out
    assert "automations/board-sync.md" in out


def test_present_secret_passes_the_token_step_without_echoing_it() -> None:
    proc = _run_token_step("ghp_supersecretvalue")
    assert proc.returncode == 0, proc.stderr
    assert "ghp_supersecretvalue" not in proc.stdout + proc.stderr


def test_secret_is_used_only_where_needed() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.count("secrets.") == 3
    assert text.count(SECRET_EXPR) == 3
    assert _step("Add the new issue to the board")["with"]["github-token"] == SECRET_EXPR
    assert _step("Set the card status")["env"]["GH_TOKEN"] == SECRET_EXPR


def test_add_to_project_is_driven_by_the_plan() -> None:
    plan = _step("Plan")
    add = _step("Add the new issue to the board")
    apply = _step("Set the card status")
    assert plan["id"] == "plan"
    assert add["id"] == "add"
    assert str(add["uses"]).startswith("actions/add-to-project@")
    assert add["if"] == "steps.plan.outputs.event == 'issue_opened'"
    assert add["with"]["project-url"] == "${{ steps.plan.outputs.project_url }}"
    assert apply["if"] == "steps.plan.outputs.event != ''"
    assert apply["env"]["ITEM_ID"] == "${{ steps.add.outputs.itemId }}"
    names = [s.get("name") for s in _job()["steps"]]
    assert names.index("Plan") < names.index("Add the new issue to the board") < names.index("Set the card status")


def test_no_board_ids_or_urls_are_hard_coded() -> None:
    node_id = re.compile(r"\b(PVT|PVTSSF|PVTF|PVTI|PVTIF|I_kw|PR_kw)[A-Za-z0-9_-]{4,}")
    option_id = re.compile(r"(?<![0-9a-f])[0-9a-f]{8}(?![0-9a-f])")
    for path in (WORKFLOW, HELPER, CONFIG):
        text = path.read_text(encoding="utf-8")
        assert not node_id.search(text), path.name
        assert not option_id.search(text), path.name
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "github.com/users" not in workflow
    assert "projects/" not in workflow
    helper = HELPER.read_text(encoding="utf-8")
    for value in _real_config()["statuses"].values():
        assert f'"{value}"' not in helper, value


def _run_step(name: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-e", "-c", _step(name)["run"]],
        env=env,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        timeout=RUN_TIMEOUT,
    )


def test_workflow_steps_run_end_to_end_for_a_merged_pr(tmp_path: Path) -> None:
    env = Env(tmp_path)
    board = Board()
    env.state["BoardSyncProject"] = _ok(board.response())
    env.state["BoardSyncLinkedIssues"] = _ok(_linked(["I_kwMerged"]))
    run_env = env.env("pull_request_target", _pr_event("closed", merged=True))
    plan = _run_step("Plan", run_env)
    assert plan.returncode == 0, plan.stderr
    assert env.outputs()["event"] == "pr_merged"
    apply = _run_step("Set the card status", run_env)
    assert apply.returncode == 0, apply.stderr
    assert env.edits() == [_edit_args("ITEM_I_kwMerged", board, "pr_merged")]


def test_workflow_plan_step_skips_a_draft_pr(tmp_path: Path) -> None:
    env = Env(tmp_path)
    plan = _run_step("Plan", env.env("pull_request_target", _pr_event("opened", draft=True)))
    assert plan.returncode == 0, plan.stderr
    assert env.outputs()["event"] == ""


# --- doc ---------------------------------------------------------------------


def test_doc_status_table_matches_the_config() -> None:
    text = DOC.read_text(encoding="utf-8")
    rows = dict(re.findall(r"^\|\s*`(\w+)`\s*\|[^|]*\|\s*([^|]+?)\s*\|\s*$", text, re.M))
    assert rows == _real_config()["statuses"]


def test_doc_explains_the_owner_setup_step() -> None:
    text = DOC.read_text(encoding="utf-8")
    assert "PROJECT_TOKEN" in text
    assert ".github/board-sync/config.json" in text
    assert "/Users/" not in text
