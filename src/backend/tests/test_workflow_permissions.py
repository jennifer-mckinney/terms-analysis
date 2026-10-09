"""Least-privilege token contract for every GitHub Actions workflow.

CodeQL actions/missing-workflow-permissions (alerts #1-#4): a workflow or job
without a ``permissions:`` block runs with the repository's default token
scope, which can be read-write. Every workflow must declare a top-level
block that grants no write scope, and every job must declare its own block,
so a new job never silently inherits more than it needs. Write scopes are
allowed only for the (workflow, job, scope) triples pinned below; adding one
is a reviewed change to this table.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

# Jobs that genuinely need a write scope, and why.
# p9-review posts the review verdict as a PR comment.
_ALLOWED_WRITES = frozenset(
    {
        ("p9-review.yml", "security-review", "pull-requests"),
        ("p9-review.yml", "grumpy-review", "pull-requests"),
    }
)
_LEVELS = frozenset({"read", "write", "none"})


def _workflow_files() -> list[Path]:
    return sorted(
        p for p in WORKFLOW_DIR.iterdir() if p.suffix in {".yml", ".yaml"}
    )


def _permission_violations(name: str, doc: Any) -> list[str]:
    """Return every least-privilege violation in one parsed workflow."""
    if not isinstance(doc, dict):
        return [f"{name}: not a mapping"]
    problems: list[str] = []

    top = doc.get("permissions")
    if not isinstance(top, dict):
        problems.append(f"{name}: top-level permissions missing or not a mapping")
    else:
        for scope, level in top.items():
            if level not in {"read", "none"}:
                problems.append(f"{name}: top-level grants {scope}: {level!r}")

    jobs = doc.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        problems.append(f"{name}: no jobs")
        return problems
    for job_id, job in jobs.items():
        perms = job.get("permissions") if isinstance(job, dict) else None
        if not isinstance(perms, dict):
            problems.append(f"{name}/{job_id}: permissions missing or not a mapping")
            continue
        for scope, level in perms.items():
            if level not in _LEVELS:
                problems.append(f"{name}/{job_id}: {scope}: {level!r} is not a level")
            elif level == "write" and (name, job_id, scope) not in _ALLOWED_WRITES:
                problems.append(f"{name}/{job_id}: unpinned write grant {scope}")
    return problems


def test_workflow_dir_has_workflows() -> None:
    # "Did nothing" guard: an empty glob must not pass the contract below.
    names = [p.name for p in _workflow_files()]
    assert "ci.yml" in names
    assert "gitignore-enforcement.yml" in names


@pytest.mark.parametrize("path", _workflow_files(), ids=lambda p: p.name)
def test_workflow_declares_least_privilege_permissions(path: Path) -> None:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert _permission_violations(path.name, doc) == []


def test_allowed_writes_are_all_used() -> None:
    # A stale allowlist entry would silently pre-approve a future write grant.
    used = set()
    for path in _workflow_files():
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_id, job in (doc.get("jobs") or {}).items():
            for scope, level in ((job or {}).get("permissions") or {}).items():
                if level == "write":
                    used.add((path.name, job_id, scope))
    assert used == set(_ALLOWED_WRITES)


_JOB_OK = {"runs-on": "x", "permissions": {"contents": "read"}}


@pytest.mark.parametrize(
    "doc,expected",
    [
        ({"permissions": {"contents": "read"}, "jobs": {"a": _JOB_OK}}, []),
        ({"permissions": {}, "jobs": {"a": _JOB_OK}}, []),
        (
            {"jobs": {"a": _JOB_OK}},
            ["w.yml: top-level permissions missing or not a mapping"],
        ),
        (
            {"permissions": "write-all", "jobs": {"a": _JOB_OK}},
            ["w.yml: top-level permissions missing or not a mapping"],
        ),
        (
            {"permissions": {"contents": "write"}, "jobs": {"a": _JOB_OK}},
            ["w.yml: top-level grants contents: 'write'"],
        ),
        (
            {"permissions": {}, "jobs": {"a": {"runs-on": "x"}}},
            ["w.yml/a: permissions missing or not a mapping"],
        ),
        (
            {"permissions": {}, "jobs": {"a": {"permissions": "read-all"}}},
            ["w.yml/a: permissions missing or not a mapping"],
        ),
        (
            {"permissions": {}, "jobs": {"a": {"permissions": {"issues": "write"}}}},
            ["w.yml/a: unpinned write grant issues"],
        ),
        (
            {"permissions": {}, "jobs": {"a": {"permissions": {"issues": "admin"}}}},
            ["w.yml/a: issues: 'admin' is not a level"],
        ),
        ({"permissions": {}, "jobs": {}}, ["w.yml: no jobs"]),
        (None, ["w.yml: not a mapping"]),
    ],
)
def test_permission_checker_vectors(doc: Any, expected: list[str]) -> None:
    assert _permission_violations("w.yml", doc) == expected
