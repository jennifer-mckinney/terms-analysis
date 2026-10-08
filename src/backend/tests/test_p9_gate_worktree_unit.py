"""Coder-side unit tests for the P9 pre-push gate worktree fix (#175).

Complements the acceptance spec in ``test_p9_prepush_gate.py`` by pinning
the validations the fix must keep (bad JSON, failing verdicts, head_sha
mismatch, override) and the installer edge cases (idempotency, missing
``.githooks``, signoff in the per-worktree git dir is NOT accepted).

All git state lives in ``tmp_path`` with an isolated HOME and global config,
so the real repository's hooks and config are never touched.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PRE_PUSH = REPO_ROOT / ".githooks" / "pre-push"
INSTALLER = REPO_ROOT / "scripts" / "install-hooks.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or shutil.which("bash") is None,
    reason="git and bash are required for hook tests",
)


def _env(tmp_path: Path) -> dict[str, str]:
    """Isolated environment: no user/system git config leaks into the test."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    gitconfig = home / ".gitconfig"
    gitconfig.write_text(
        "[user]\n\tname = P9 Test\n\temail = p9@example.invalid\n"
        "[init]\n\tdefaultBranch = main\n"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        HOME=str(home),
        GIT_CONFIG_GLOBAL=str(gitconfig),
        GIT_CONFIG_NOSYSTEM="1",
    )
    return env


def _git(cwd: Path, env: dict[str, str], *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, env=env, text=True, capture_output=True, check=check
    )


@pytest.fixture
def repo(tmp_path: Path) -> dict[str, object]:
    """Throwaway repo with only the gate + installer, a bare remote and a worktree."""
    env = _env(tmp_path)
    main = tmp_path / "main"
    (main / ".githooks").mkdir(parents=True)
    (main / "scripts").mkdir()
    # Only pre-push is copied: pre-commit has project-specific guards that
    # are out of scope here and would interfere with throwaway commits.
    shutil.copy2(PRE_PUSH, main / ".githooks" / "pre-push")
    shutil.copy2(INSTALLER, main / "scripts" / "install-hooks.sh")
    _git(main, env, "init", "-q")
    (main / "README").write_text("p9\n")
    _git(main, env, "add", "-A")
    _git(main, env, "commit", "-qm", "init")
    remote = tmp_path / "remote.git"
    _git(tmp_path, env, "init", "-q", "--bare", str(remote))
    _git(main, env, "remote", "add", "origin", str(remote))
    wt = tmp_path / "wt"
    _git(main, env, "worktree", "add", "-q", "-b", "wt-branch", str(wt))
    proc = subprocess.run(
        ["bash", "scripts/install-hooks.sh"], cwd=wt, env=env, text=True, capture_output=True
    )
    assert proc.returncode == 0, proc.stderr
    common = Path(_git(main, env, "rev-parse", "--git-common-dir").stdout.strip())
    common = (main / common).resolve() if not common.is_absolute() else common.resolve()
    return {"env": env, "main": main, "wt": wt, "remote": remote, "common": common}


def _head(cwd: Path, env: dict[str, str]) -> str:
    return _git(cwd, env, "rev-parse", "HEAD").stdout.strip()


def _write_signoff(path: Path, payload: dict[str, object] | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload))


def _push(cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return _git(cwd, env, "push", "-q", "origin", "HEAD:refs/heads/target", check=False)


def _passing(sha: str) -> dict[str, object]:
    return {
        "head_sha": sha,
        "security_engineer": {"verdict": "PASS"},
        "grumpy_developer": {"verdict": "PASS"},
    }


@pytest.mark.parametrize(
    "mutate, stderr_fragment",
    [
        (lambda d: d["security_engineer"].update(verdict="FAIL"), "security_engineer verdict: FAIL"),
        (lambda d: d["grumpy_developer"].update(verdict="FAIL"), "grumpy_developer verdict: FAIL"),
        (lambda d: d.update(head_sha="0" * 40), "head_sha mismatch"),
    ],
    ids=["security-fail", "grumpy-fail", "sha-mismatch"],
)
def test_worktree_push_rejects_invalid_signoff(repo, mutate, stderr_fragment):
    env, wt = repo["env"], repo["wt"]
    sha = _head(wt, env)
    payload = _passing(sha)
    mutate(payload)
    _write_signoff(repo["common"] / "reviews" / f"{sha}.signoff.json", payload)
    proc = _push(wt, env)
    assert proc.returncode != 0
    assert "signoff invalid" in proc.stderr
    assert stderr_fragment in proc.stderr
    assert _git(wt, env, "ls-remote", "origin", "target").stdout == ""


def test_worktree_push_rejects_non_json_signoff(repo):
    env, wt = repo["env"], repo["wt"]
    sha = _head(wt, env)
    _write_signoff(repo["common"] / "reviews" / f"{sha}.signoff.json", "{not json")
    proc = _push(wt, env)
    assert proc.returncode != 0
    assert "not valid JSON" in proc.stderr


def test_worktree_push_accepts_override_and_announces_it(repo):
    env, wt = repo["env"], repo["wt"]
    sha = _head(wt, env)
    payload = {
        "head_sha": sha,
        "override": {"used": True, "reason": "unit test", "authorized_by": "tester"},
    }
    _write_signoff(repo["common"] / "reviews" / f"{sha}.signoff.json", payload)
    proc = _push(wt, env)
    assert proc.returncode == 0, proc.stderr
    assert "P9 OVERRIDE ACTIVE: unit test (authorized by tester)" in proc.stderr
    assert sha in _git(wt, env, "ls-remote", "origin", "target").stdout


def test_signoff_in_per_worktree_git_dir_is_not_accepted(repo):
    """The gate must read the COMMON dir, not `--git-dir` (.git/worktrees/<name>)."""
    env, wt = repo["env"], repo["wt"]
    sha = _head(wt, env)
    per_wt = Path(_git(wt, env, "rev-parse", "--absolute-git-dir").stdout.strip())
    assert per_wt.resolve() != repo["common"]
    _write_signoff(per_wt / "reviews" / f"{sha}.signoff.json", _passing(sha))
    proc = _push(wt, env)
    assert proc.returncode != 0
    assert "signoff not found" in proc.stderr
    assert str(repo["common"] / "reviews") in proc.stderr


def test_install_hooks_is_idempotent_and_quiet_on_rerun(repo):
    env, wt = repo["env"], repo["wt"]
    proc = subprocess.run(
        ["bash", "scripts/install-hooks.sh"], cwd=wt, env=env, text=True, capture_output=True
    )
    assert proc.returncode == 0, proc.stderr
    # Already .githooks: no "replacing" notice on a second run.
    assert "replacing" not in proc.stderr
    assert _git(wt, env, "config", "--get", "core.hooksPath").stdout.strip() == ".githooks"
    assert (repo["common"] / "reviews").is_dir()
    assert os.access(repo["wt"] / ".githooks" / "pre-push", os.X_OK)


def test_install_hooks_names_replaced_absolute_value(repo):
    env, main = repo["env"], repo["main"]
    stale = str(repo["common"] / "hooks")
    _git(main, env, "config", "core.hooksPath", stale)
    proc = subprocess.run(
        ["bash", "scripts/install-hooks.sh"], cwd=repo["wt"], env=env, text=True, capture_output=True
    )
    assert proc.returncode == 0, proc.stderr
    assert f"replacing core.hooksPath={stale}" in proc.stderr
    assert _git(main, env, "config", "--get", "core.hooksPath").stdout.strip() == ".githooks"


def test_install_hooks_fails_when_shadowed_by_worktree_config(repo):
    """A per-worktree value that outranks local config must not be reported as installed."""
    env, wt = repo["env"], repo["wt"]
    _git(wt, env, "config", "extensions.worktreeConfig", "true")
    _git(wt, env, "config", "--worktree", "core.hooksPath", "/nonexistent/hooks")
    proc = subprocess.run(
        ["bash", "scripts/install-hooks.sh"], cwd=wt, env=env, text=True, capture_output=True
    )
    assert proc.returncode != 0
    assert "core.hooksPath is still '/nonexistent/hooks'" in proc.stderr


def test_install_hooks_refuses_without_githooks_dir(tmp_path):
    env = _env(tmp_path)
    bare = tmp_path / "plain"
    (bare / "scripts").mkdir(parents=True)
    shutil.copy2(INSTALLER, bare / "scripts" / "install-hooks.sh")
    _git(bare, env, "init", "-q")
    proc = subprocess.run(
        ["bash", "scripts/install-hooks.sh"], cwd=bare, env=env, text=True, capture_output=True
    )
    assert proc.returncode != 0
    assert ".githooks not found" in proc.stderr
    assert _git(bare, env, "config", "--get", "core.hooksPath", check=False).stdout == ""
