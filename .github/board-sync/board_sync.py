#!/usr/bin/env python3
"""Board sync for the owner's GitHub Projects v2 board.

Run by .github/workflows/board-sync.yml. It replaces the per-event
project-manager agent dispatches (agent-setup audit item 5, 2026-10-09).

Subcommands:
    plan   Route the current event. Writes project_url and event to
           $GITHUB_OUTPUT; event is empty when the event is a deliberate skip
           (a draft PR, a PR closed without merge, an issue closed as anything
           but not planned). Makes no GitHub call.
    apply  Move the card(s) for the routed event to the configured status.
           Resolves the project, the status field and the option by name on
           every run, so no board ID is stored anywhere.

Config: config.json next to this file (or --config). It is the only place the
board URL, the field name, the status per event and the call bounds live; this
module validates it against an exact schema and fails closed on anything off.

Exit codes:
    0  done; the last line states what moved ("moved N issue(s) ...") or why
       the event was skipped
    1  a GitHub call failed, or the board does not match the config
    2  bad config, environment, event payload or usage

Standard library and the gh CLI only (both on GitHub-hosted runners).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_INVALID = 2

DEFAULT_CONFIG = Path(__file__).resolve().with_name("config.json")
SETUP_DOC = "automations/board-sync.md"

# Event keys: the config's "statuses" object maps each one to a board status.
EVENT_KEYS = ("issue_opened", "issue_closed_not_planned", "pr_ready", "pr_merged")
# The workflow triggers on exactly these event names and actions; the test
# suite checks the workflow's `on:` block against this table.
ROUTED_ACTIONS = {
    "issues": ("opened", "closed"),
    "pull_request_target": ("opened", "reopened", "ready_for_review", "closed"),
}
PR_READY_ACTIONS = ("opened", "reopened", "ready_for_review")
# Issue close reasons GitHub sends. Only not_planned moves a card; an unknown
# reason fails closed so a new GitHub value is noticed, not ignored.
SKIPPED_CLOSE_REASONS = ("completed", "duplicate", None)

CONFIG_FIELDS = (
    "project_url",
    "status_field",
    "statuses",
    "gh_timeout_seconds",
    "gh_output_max_bytes",
    "max_linked_issues",
    "message_max_chars",
)
# Schema bounds (validation, not tunables). GraphQL connections return at most
# 100 nodes per page, so max_linked_issues cannot usefully exceed it.
INT_BOUNDS = {
    "gh_timeout_seconds": (1, 600),
    "gh_output_max_bytes": (1, 16 * 1024 * 1024),
    "max_linked_issues": (1, 100),
    "message_max_chars": (80, 4000),
}
MAX_NAME_CHARS = 100
# A user-owned Projects v2 board. Org boards use another GraphQL root, so they
# are refused rather than half supported.
PROJECT_URL = re.compile(r"https://github\.com/users/([A-Za-z0-9][A-Za-z0-9-]{0,38})/projects/([1-9][0-9]{0,8})")
# GitHub node IDs and single-select option IDs. They go into gh argv, so a
# leading "-" (an option) and anything outside this set are refused.
NODE_ID = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_=-]{0,127}")
REPOSITORY = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}")

PROJECT_QUERY = """
query BoardSyncProject($login: String!, $number: Int!, $field: String!) {
  user(login: $login) {
    projectV2(number: $number) {
      id
      field(name: $field) {
        __typename
        ... on ProjectV2SingleSelectField { id name options { id name } }
      }
    }
  }
}
"""
LINKED_ISSUES_QUERY = """
query BoardSyncLinkedIssues($owner: String!, $repo: String!, $number: Int!, $first: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      closingIssuesReferences(first: $first) { totalCount nodes { id number } }
    }
  }
}
"""
# Idempotent: for an issue already on the board GitHub returns its item.
ADD_ITEM_MUTATION = """
mutation BoardSyncAddItem($project: ID!, $content: ID!) {
  addProjectV2ItemById(input: {projectId: $project, contentId: $content}) { item { id } }
}
"""


class InvalidInput(Exception):
    """Config, environment, payload or usage is off contract (exit 2)."""


class GitHubError(Exception):
    """A GitHub call failed or returned data the board sync cannot trust (exit 1)."""


@dataclass(frozen=True)
class Config:
    project_url: str
    owner: str
    project_number: int
    status_field: str
    statuses: dict[str, str]
    gh_timeout_seconds: int
    gh_output_max_bytes: int
    max_linked_issues: int
    message_max_chars: int


@dataclass(frozen=True)
class Route:
    event: str | None  # an EVENT_KEYS entry, or None for a deliberate skip
    reason: str
    issue_node_id: str | None = None
    pr_number: int | None = None


@dataclass(frozen=True)
class BoardTarget:
    project_id: str
    field_id: str
    option_id: str
    status: str


def clean(text: str, limit: int | None = None) -> str:
    """One printable line: control, format and separator characters become '?'."""
    line = "".join(ch if ch.isprintable() else "?" for ch in text)
    return line if limit is None else line[:limit]


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate key")
    return dict(pairs)


def _read_json(path: Path, what: str, error: type[Exception]) -> object:
    """Parse a JSON file; duplicate keys are refused. Messages carry no path."""
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except FileNotFoundError:
        raise error(f"{what} not found ({path.name})") from None
    except (OSError, UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise error(f"{what} is not valid JSON ({type(exc).__name__})") from None


def _is_name(value: object) -> bool:
    """A non-blank, printable, bounded name (field or status)."""
    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value) <= MAX_NAME_CHARS
        and value.isprintable()
    )


def _is_int(value: object) -> bool:
    # bool is a subclass of int, so it is refused explicitly.
    return isinstance(value, int) and not isinstance(value, bool)


def load_config(path: Path) -> Config:
    """Read and validate the config, or raise InvalidInput."""
    doc = _read_json(path, "board-sync config", InvalidInput)
    if not isinstance(doc, dict) or set(doc) != set(CONFIG_FIELDS):
        raise InvalidInput(f"board-sync config must have exactly the keys {', '.join(CONFIG_FIELDS)}")
    url = doc["project_url"]
    match = PROJECT_URL.fullmatch(url) if isinstance(url, str) else None
    if match is None:
        raise InvalidInput("board-sync config: project_url must be https://github.com/users/<login>/projects/<number>")
    if not _is_name(doc["status_field"]):
        raise InvalidInput("board-sync config: status_field must be a non-blank printable name")
    statuses = doc["statuses"]
    if (
        not isinstance(statuses, dict)
        or set(statuses) != set(EVENT_KEYS)
        or not all(_is_name(value) for value in statuses.values())
    ):
        raise InvalidInput(
            f"board-sync config: statuses must map exactly {', '.join(EVENT_KEYS)} to non-blank status names"
        )
    for key, (low, high) in INT_BOUNDS.items():
        value = doc[key]
        if not _is_int(value) or not low <= value <= high:
            raise InvalidInput(f"board-sync config: {key} must be an integer from {low} to {high}")
    return Config(
        project_url=url,
        owner=match.group(1),
        project_number=int(match.group(2)),
        status_field=doc["status_field"],
        statuses=dict(statuses),
        gh_timeout_seconds=doc["gh_timeout_seconds"],
        gh_output_max_bytes=doc["gh_output_max_bytes"],
        max_linked_issues=doc["max_linked_issues"],
        message_max_chars=doc["message_max_chars"],
    )


def _env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise InvalidInput(f"{name} is not set")
    return value


def _object(value: object, what: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise InvalidInput(f"event payload: {what} is missing or not an object")
    return value


def _payload_node_id(value: object) -> str:
    if not isinstance(value, str) or NODE_ID.fullmatch(value) is None:
        raise InvalidInput("event payload: issue.node_id is missing or malformed")
    return value


def _payload_bool(pr: dict[str, object], key: str) -> bool:
    value = pr.get(key)
    if not isinstance(value, bool):
        raise InvalidInput(f"event payload: pull_request.{key} is missing or not a boolean")
    return value


def route(event_name: str, payload: object) -> Route:
    """The single routing table: which board move, if any, this event means."""
    actions = ROUTED_ACTIONS.get(event_name)
    if actions is None:
        raise InvalidInput(f"event {event_name} is not handled (expected one of {', '.join(ROUTED_ACTIONS)})")
    doc = _object(payload, "the payload")
    action = doc.get("action")
    if not isinstance(action, str) or action not in actions:
        raise InvalidInput(f"event {event_name}: action {action!r} is not handled")

    if event_name == "issues":
        issue = _object(doc.get("issue"), "issue")
        node_id = _payload_node_id(issue.get("node_id"))
        if action == "opened":
            return Route("issue_opened", "issue opened", issue_node_id=node_id)
        reason = issue.get("state_reason")
        if reason == "not_planned":
            return Route("issue_closed_not_planned", "issue closed as not planned", issue_node_id=node_id)
        if reason in SKIPPED_CLOSE_REASONS:
            return Route(None, f"issue closed as {reason or 'unspecified'}")
        raise InvalidInput(f"event payload: issue.state_reason {reason!r} is not a known close reason")

    pr = _object(doc.get("pull_request"), "pull_request")
    number = pr.get("number")
    if not _is_int(number) or number < 1:
        raise InvalidInput("event payload: pull_request.number must be a positive integer")
    draft = _payload_bool(pr, "draft")
    merged = _payload_bool(pr, "merged")
    if action in PR_READY_ACTIONS:
        if draft:
            return Route(None, f"PR #{number} is a draft")
        return Route("pr_ready", f"PR #{number} {action}", pr_number=number)
    if merged:
        return Route("pr_merged", f"PR #{number} merged", pr_number=number)
    return Route(None, f"PR #{number} closed without merge")


def _event() -> tuple[str, object]:
    name = _env("GITHUB_EVENT_NAME")
    payload = _read_json(Path(_env("GITHUB_EVENT_PATH")), "event payload", InvalidInput)
    return name, payload


def plan(cfg: Config) -> int:
    name, payload = _event()
    output = Path(_env("GITHUB_OUTPUT"))
    decision = route(name, payload)
    # Both values are fixed keys or a schema-validated URL: no newline can
    # reach the output file and forge another key.
    with output.open("a", encoding="utf-8") as fh:
        fh.write(f"project_url={cfg.project_url}\n")
        fh.write(f"event={decision.event or ''}\n")
    if decision.event is None:
        print(f"board-sync: plan: skip ({decision.reason})")
    else:
        print(f'board-sync: plan: {decision.event} -> "{cfg.statuses[decision.event]}" ({decision.reason})')
    return EXIT_OK


def _gh(cfg: Config, args: list[str], stdin: str | None = None) -> str:
    """Run gh with a timeout and an output cap; any failure raises GitHubError."""
    try:
        proc = subprocess.run(
            ["gh", *args],
            input=None if stdin is None else stdin.encode("utf-8"),
            capture_output=True,
            timeout=cfg.gh_timeout_seconds,
            check=False,
        )
    except FileNotFoundError:
        raise GitHubError("the gh CLI was not found on PATH") from None
    except subprocess.TimeoutExpired:
        # subprocess.run kills the child before re-raising.
        raise GitHubError(f"gh {args[0]} {args[1]} timed out after {cfg.gh_timeout_seconds}s") from None
    if len(proc.stdout) > cfg.gh_output_max_bytes:
        raise GitHubError(f"gh {args[0]} {args[1]} returned more than {cfg.gh_output_max_bytes} bytes")
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace").strip()
        raise GitHubError(f"gh {args[0]} {args[1]} failed (exit {proc.returncode}): {detail}")
    try:
        return proc.stdout.decode("utf-8")
    except UnicodeDecodeError:
        raise GitHubError(f"gh {args[0]} {args[1]} returned non-UTF-8 output") from None


def _graphql(cfg: Config, query: str, variables: dict[str, object]) -> dict[str, object]:
    body = json.dumps({"query": query, "variables": variables})
    out = _gh(cfg, ["api", "graphql", "--input", "-"], body)
    try:
        doc = json.loads(out)
    except (ValueError, RecursionError):
        raise GitHubError("GitHub returned a response that is not JSON") from None
    if not isinstance(doc, dict):
        raise GitHubError("GitHub returned a response that is not a JSON object")
    errors = doc.get("errors")
    if errors:
        first = errors[0] if isinstance(errors, list) and errors else errors
        message = first.get("message") if isinstance(first, dict) else first
        raise GitHubError(f"GitHub GraphQL error: {message}")
    data = doc.get("data")
    if not isinstance(data, dict):
        raise GitHubError("GitHub returned no data")
    return data


def _dig(value: object, *keys: str) -> object:
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _api_id(value: object, what: str) -> str:
    if not isinstance(value, str) or NODE_ID.fullmatch(value) is None:
        raise GitHubError(f"GitHub returned a malformed {what}")
    return value


def resolve_board(cfg: Config, status: str) -> BoardTarget:
    """Look up the project, the status field and the option by name."""
    data = _graphql(
        cfg,
        PROJECT_QUERY,
        {"login": cfg.owner, "number": cfg.project_number, "field": cfg.status_field},
    )
    project = _dig(data, "user", "projectV2")
    if not isinstance(project, dict):
        raise GitHubError(
            f"project {cfg.project_url} was not found, or PROJECT_TOKEN cannot read it "
            "(it needs the project scope)"
        )
    project_id = _api_id(project.get("id"), "project id")
    field = project.get("field")
    if not isinstance(field, dict):
        raise GitHubError(f"the board has no field named {cfg.status_field}")
    if field.get("__typename") != "ProjectV2SingleSelectField":
        raise GitHubError(f"the board field {cfg.status_field} is not a single-select field")
    field_id = _api_id(field.get("id"), "field id")
    options = field.get("options")
    if not isinstance(options, list) or not all(isinstance(o, dict) for o in options):
        raise GitHubError(f"GitHub returned no option list for {cfg.status_field}")
    matches = [o for o in options if o.get("name") == status]
    if not matches:
        names = ", ".join(str(o.get("name")) for o in options)
        raise GitHubError(
            f'the {cfg.status_field} field has no option "{status}" (board options: {names}); '
            "fix the board or .github/board-sync/config.json"
        )
    if len(matches) > 1:
        raise GitHubError(f'the {cfg.status_field} field has {len(matches)} options named "{status}"')
    option_id = _api_id(matches[0].get("id"), "option id")
    return BoardTarget(project_id, field_id, option_id, status)


def linked_issues(cfg: Config, repository: str, number: int) -> list[str]:
    """Node IDs of the issues the PR closes (GitHub's closing-keyword links)."""
    owner, repo = repository.split("/", 1)
    data = _graphql(
        cfg,
        LINKED_ISSUES_QUERY,
        {"owner": owner, "repo": repo, "number": number, "first": cfg.max_linked_issues},
    )
    refs = _dig(data, "repository", "pullRequest", "closingIssuesReferences")
    if not isinstance(refs, dict):
        raise GitHubError(f"PR #{number} was not found in {repository}")
    total = refs.get("totalCount")
    nodes = refs.get("nodes")
    if not _is_int(total) or total < 0 or not isinstance(nodes, list):
        raise GitHubError(f"GitHub returned malformed linked issues for PR #{number}")
    if total > cfg.max_linked_issues:
        raise GitHubError(
            f"PR #{number} links {total} issues, above the max_linked_issues cap of {cfg.max_linked_issues}"
        )
    if len(nodes) != total:
        raise GitHubError(f"GitHub listed {len(nodes)} of {total} linked issues for PR #{number}")
    return [_api_id(_dig(node, "id"), "linked issue id") for node in nodes]


def add_item(cfg: Config, board: BoardTarget, content_id: str) -> str:
    data = _graphql(cfg, ADD_ITEM_MUTATION, {"project": board.project_id, "content": content_id})
    return _api_id(_dig(data, "addProjectV2ItemById", "item", "id"), "project item id")


def set_status(cfg: Config, board: BoardTarget, item_id: str) -> None:
    _gh(
        cfg,
        [
            "project",
            "item-edit",
            "--id",
            item_id,
            "--project-id",
            board.project_id,
            "--field-id",
            board.field_id,
            "--single-select-option-id",
            board.option_id,
        ],
    )


def apply(cfg: Config) -> int:
    token = os.environ.get("GH_TOKEN", "")
    if not token.strip():
        raise InvalidInput(f"GH_TOKEN is empty: set the PROJECT_TOKEN repository secret (see {SETUP_DOC})")
    name, payload = _event()
    decision = route(name, payload)
    if decision.event is None:
        raise InvalidInput(f"nothing to apply: {decision.reason}; the workflow should have skipped this step")

    # Validate every input before the first GitHub call.
    item_id = ""
    repository = ""
    if decision.event == "issue_opened":
        item_id = os.environ.get("ITEM_ID", "")
        if NODE_ID.fullmatch(item_id) is None:
            raise InvalidInput("ITEM_ID from actions/add-to-project is missing or malformed")
    elif decision.pr_number is not None:
        repository = os.environ.get("GITHUB_REPOSITORY", "")
        if REPOSITORY.fullmatch(repository) is None:
            raise InvalidInput("GITHUB_REPOSITORY is missing or malformed")

    board = resolve_board(cfg, cfg.statuses[decision.event])
    if decision.event == "issue_opened":
        set_status(cfg, board, item_id)
        print(f'board-sync: moved 1 issue(s) to "{board.status}" ({decision.reason})')
        return EXIT_OK

    if decision.pr_number is not None:
        content_ids = linked_issues(cfg, repository, decision.pr_number)
        print(f"board-sync: PR #{decision.pr_number} links {len(content_ids)} issue(s)")
    elif decision.issue_node_id is not None:
        content_ids = [decision.issue_node_id]
    else:
        raise InvalidInput(f"route {decision.event} carries no issue or PR")

    moved = 0
    for content_id in content_ids:
        try:
            set_status(cfg, board, add_item(cfg, board, content_id))
        except GitHubError as exc:
            raise GitHubError(f"{exc} (moved {moved} of {len(content_ids)} before the failure)") from None
        moved += 1
    print(f'board-sync: moved {moved} issue(s) to "{board.status}" ({decision.reason})')
    return EXIT_OK


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="board_sync.py", description="Sync the Projects v2 board.")
    parser.add_argument("command", choices=("plan", "apply"))
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(argv)  # usage errors exit 2 (EXIT_INVALID)

    limit: int | None = None
    try:
        cfg = load_config(args.config)
        limit = cfg.message_max_chars
        return plan(cfg) if args.command == "plan" else apply(cfg)
    except InvalidInput as exc:
        print(clean(f"board-sync: error: {exc}", limit), file=sys.stderr)
        return EXIT_INVALID
    except GitHubError as exc:
        print(clean(f"board-sync: error: {exc}", limit), file=sys.stderr)
        return EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
