"""Acceptance tests for terms-analysis #384, owner rulings 3 and 4 (2026-10-15).

Ruling 4, runner-home allowlist: the GitHub-hosted runner account home is not a
personal path. The relocated ingester tree quotes it legitimately (ADR-016 and
one test literal), so the tree guard (hook check 5 and the
gitignore-enforcement workflow, one scanner, F10) must let the exact runner
home through while every near miss still refuses: the account name with a
prefix or suffix, another account, another OS home root (Windows), case
variants, a personal path on the same line, a Cf or ANSI split that glues
letters onto the account name, and `..` traversal out of the runner home.
Where the allowlist lives (the pattern file or the guard) is the coder's
choice under ruling 4, so these tests state the acceptance vectors and run
both real enforcers; they do not restate any config value (F13).

Ruling 3, absolute `core.hooksPath`: `scripts/install-hooks.sh` sets it to the
ABSOLUTE path of the main checkout's `.githooks`, also when it is run from a
linked worktree or a subdirectory, so every worktree runs the main checkout's
hook (the reloc worktree has no `.githooks` of its own).

Behaviour over text: real `git commit` through the hook, the real workflow
`run:` steps, the real installer. Home-path vectors are assembled at runtime so
this file is not a leak itself.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.test_precommit_guards import (
    CRASH_MARKERS,
    GITIGNORE_FILE,
    GOV_DIR,
    HOOK_TIMEOUT_S,
    HOOKS_DIR,
    REPO_ROOT,
    SCRIPTS_DIR,
    _ci_tree,
    _copy_tracked,
    _env,
    _git,
    _run_workflow,
)

INSTALLER = REPO_ROOT / "scripts" / "install-hooks.sh"
REASON_HOME = "home-path"

# The ruling's subject, not a config value: the GitHub-hosted runner account.
# Its homes are /home/<account> (Linux) and /Users/<account> (macOS); the
# Windows hosted account is a different one, so a Windows path stays a leak.
RUNNER = "runner"


def _h(root: str, user: str, rest: str = "") -> str:
    """A POSIX home path, assembled at runtime so this file holds no leak."""
    return "/" + root + "/" + user + rest


def _drive(sep: str, user: str, rest: str = "") -> str:
    """A Windows home path (drive, Users, account), assembled at runtime."""
    return "C:" + sep + "Users" + sep + user + rest


# (family, id, line). ALLOW: the exact runner home in the shapes the ingester
# tree really uses (ADR-016 quotes, a test literal) plus a list form.
ALLOW = [
    ("macos-home", "adr-backticks", "`" + _h("Users", RUNNER) + "`"),
    ("macos-home", "adr-mkdir-error", "mkdir: " + _h("Users", RUNNER) + ": Permission denied"),
    ("macos-home", "adr-env-assignment", "AGENT_TOOLSDIRECTORY=" + _h("Users", RUNNER, "/hostedtoolcache")),
    ("linux-home", "test-literal", 'TMP = "' + _h("home", RUNNER, "/work/_temp") + '"'),
    ("linux-home", "bare-at-eol", "cd " + _h("home", RUNNER)),
    ("linux-home", "path-list-runner-only",
     "PATH=" + _h("home", RUNNER, "/bin") + ":" + _h("Users", RUNNER, "/bin")),
]

REFUSE = [
    ("account-prefix", "x-prefix", _h("home", "x" + RUNNER, "/x")),
    ("account-prefix", "underscore-prefix", _h("Users", "_" + RUNNER, "/x")),
    ("account-suffix", "digit", _h("home", RUNNER + "2", "/x")),
    ("account-suffix", "plural", _h("home", RUNNER + "s", "/x")),
    ("account-suffix", "dot", _h("Users", RUNNER + ".bak", "/x")),
    ("account-suffix", "dash", _h("home", RUNNER + "-x", "/x")),
    ("account-suffix", "underscore", _h("home", RUNNER + "_x", "/x")),
    ("account-suffix", "admin", _h("Users", RUNNER + "admin", "/x")),
    ("other-account", "alice", _h("home", "alice", "/x")),
    ("other-os-root", "windows-backslash", _drive("\\", RUNNER, "\\x")),
    ("other-os-root", "windows-slash", _drive("/", RUNNER, "/x")),
    ("case", "account-capitalised", _h("home", RUNNER.capitalize(), "/x")),
    ("case", "account-upper", _h("Users", RUNNER.upper(), "/x")),
    ("case", "root-upper", _h("HOME", RUNNER, "/x")),
    ("case", "root-lower", _h("users", RUNNER, "/x")),
    ("same-line", "runner-then-personal", _h("home", RUNNER, "/x") + " " + _h("home", "alice", "/x")),
    ("same-line", "personal-then-runner", _h("Users", "alice", "/x") + " " + _h("Users", RUNNER, "/x")),
    ("same-line", "path-list", "PATH=" + _h("home", RUNNER, "/bin") + ":" + _h("home", "alice", "/bin")),
    ("cf-split", "zero-width-space", _h("home", RUNNER + "​john", "/x")),
    ("cf-split", "soft-hyphen", _h("Users", RUNNER + "­john", "/x")),
    ("ansi-split", "sgr-reset", _h("home", RUNNER + "\x1b[0mjohn", "/x")),
    ("traversal", "parent", _h("home", RUNNER, "/../alice/x")),
    ("traversal", "deep-parent", _h("Users", RUNNER, "/work/../../alice/x")),
    ("traversal", "dot-then-parent", _h("home", RUNNER, "/./../alice")),
]

REFUSE_FAMILIES = {
    "account-prefix", "account-suffix", "other-account", "other-os-root",
    "case", "same-line", "cf-split", "ansi-split", "traversal",
}
ENFORCERS = ("hook", "ci")


def test_vector_table_contract() -> None:
    """Both sides exist, both runner homes pass somewhere, every family refuses."""
    assert {f for f, _, _ in ALLOW} == {"macos-home", "linux-home"}
    assert {f for f, _, _ in REFUSE} == REFUSE_FAMILIES
    ids = [i for _, i, _ in ALLOW + REFUSE]
    assert len(ids) == len(set(ids)), "vector ids must be unique"
    # Every refuse vector names the runner account or a personal account, so a
    # refusal is never explained by an unrelated row.
    assert all(RUNNER in v.lower() or "alice" in v for _, _, v in REFUSE)


def _ta_repo(tmp_path: Path) -> Path:
    """A TA sandbox with the tracked hook, scripts and governance files."""
    ta = tmp_path / "ta"
    ta.mkdir()
    _git(ta, "init", "-q")
    shutil.copy2(GITIGNORE_FILE, ta / ".gitignore")
    for src in (GOV_DIR, HOOKS_DIR, SCRIPTS_DIR):
        _copy_tracked(src, ta)
    _git(ta, "add", "-A", "-f")
    _git(ta, "-c", "core.hooksPath=" + os.devnull, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "base")
    _git(ta, "config", "core.hooksPath", str(ta / ".githooks"))
    return ta


def _verdict(enforcer: str, tmp_path: Path, line: str) -> tuple[bool, str]:
    rel = "docs/runner-notes.md"
    if enforcer == "ci":
        return _run_workflow(_ci_tree(tmp_path, {rel: line + "\n"}))
    ta = _ta_repo(tmp_path)
    target = ta / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((line + "\n").encode("utf-8"))
    _git(ta, "add", "-f", "--", rel)
    proc = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "t"],
        cwd=ta, env=_env(), capture_output=True, timeout=HOOK_TIMEOUT_S,
    )
    out = (proc.stdout + proc.stderr).decode("utf-8", "replace")
    return proc.returncode == 0, out


@pytest.mark.parametrize("enforcer", ENFORCERS)
@pytest.mark.parametrize("family,vid,line", ALLOW, ids=[i for _, i, _ in ALLOW])
def test_runner_home_passes(enforcer: str, family: str, vid: str, line: str, tmp_path: Path) -> None:
    """Ruling 4: the exact runner home is not a leak, in hook and CI alike."""
    ok, out = _verdict(enforcer, tmp_path, line)
    assert ok, f"{enforcer} refused the runner home ({family}/{vid}): {out[-600:]!r}"


@pytest.mark.parametrize("enforcer", ENFORCERS)
@pytest.mark.parametrize("family,vid,line", REFUSE, ids=[i for _, i, _ in REFUSE])
def test_runner_near_miss_refuses(enforcer: str, family: str, vid: str, line: str, tmp_path: Path) -> None:
    """Ruling 4: full path segment, exact case, nothing else rides along."""
    ok, out = _verdict(enforcer, tmp_path, line)
    assert not ok, f"{enforcer} let a near miss through ({family}/{vid})"
    assert REASON_HOME in out, f"refused without the home-path reason: {out[-600:]!r}"
    assert [m for m in CRASH_MARKERS if m in out] == [], out[-600:]
    assert line not in out, "the refusal echoes the refused content"


# ---------------------------------------------------------------------------
# Ruling 3: install-hooks.sh wires the main checkout's hooks by absolute path.
# ---------------------------------------------------------------------------
def _inst_repo(tmp_path: Path) -> Path:
    # A space in the path: the value must survive quoting end to end.
    repo = tmp_path / "main checkout"
    repo.mkdir()
    _git(repo, "init", "-q")
    _copy_tracked(HOOKS_DIR, repo)
    (repo / "scripts").mkdir()
    shutil.copy2(INSTALLER, repo / "scripts" / "install-hooks.sh")
    _git(repo, "add", "-A", "-f")
    _git(repo, "-c", "core.hooksPath=" + os.devnull, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "base")
    return repo


def _linked(repo: Path, name: str = "wt") -> Path:
    wt = repo.parent / name
    _git(repo, "-c", "core.hooksPath=" + os.devnull, "worktree", "add", "-q", "-b", name, str(wt))
    return wt


def _install(checkout: Path, cwd: Path | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["bash", str(checkout / "scripts" / "install-hooks.sh")],
        cwd=cwd or checkout, env=_env(), capture_output=True, timeout=HOOK_TIMEOUT_S,
    )


def _assert_main_hooks_path(repo: Path) -> None:
    rows = _git(repo, "config", "--show-scope", "--get-all", "core.hooksPath").stdout.decode().splitlines()
    assert len(rows) == 1, f"expected one core.hooksPath value, got {rows!r}"
    scope, _, value = rows[0].partition("\t")
    assert scope == "local", f"core.hooksPath set in scope {scope!r}, not the repository config"
    assert os.path.isabs(value), f"core.hooksPath is relative ({value!r}); ruling 3 makes it absolute"
    assert os.path.realpath(value) == os.path.realpath(repo / ".githooks"), (
        "core.hooksPath does not point at the main checkout's .githooks"
    )


def test_installer_from_main_checkout_sets_absolute_path(tmp_path: Path) -> None:
    repo = _inst_repo(tmp_path)
    proc = _install(repo)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    _assert_main_hooks_path(repo)


def test_installer_from_linked_worktree_sets_main_checkout_path(tmp_path: Path) -> None:
    """Run from a linked worktree, the value is still the MAIN checkout's hooks."""
    repo = _inst_repo(tmp_path)
    wt = _linked(repo)
    proc = _install(wt)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    _assert_main_hooks_path(repo)


def test_installer_from_subdirectory_sets_same_path(tmp_path: Path) -> None:
    repo = _inst_repo(tmp_path)
    proc = _install(repo, cwd=repo / "scripts")
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    _assert_main_hooks_path(repo)


def test_installer_replaces_relative_value_and_is_idempotent(tmp_path: Path) -> None:
    """Today's relative value (the drift in design F2) is replaced; reruns agree."""
    repo = _inst_repo(tmp_path)
    _git(repo, "config", "core.hooksPath", ".githooks")
    for _ in range(2):
        proc = _install(repo)
        assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    _assert_main_hooks_path(repo)


def test_commit_in_linked_worktree_runs_main_checkout_hook(tmp_path: Path) -> None:
    """After installing from a worktree, a worktree commit runs the MAIN hook.

    The main checkout's on-disk hook is swapped for a marker (uncommitted), the
    worktree keeps its own tracked copy, so only the absolute wiring prints it.
    """
    repo = _inst_repo(tmp_path)
    wt = _linked(repo)
    assert _install(wt).returncode == 0
    hook = repo / ".githooks" / "pre-commit"
    hook.write_text("#!/usr/bin/env bash\necho MAIN-CHECKOUT-HOOK >&2\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    (wt / "note.txt").write_text("x\n", encoding="utf-8")
    _git(wt, "add", "--", "note.txt")
    proc = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "t"],
        cwd=wt, env=_env(), capture_output=True, timeout=HOOK_TIMEOUT_S,
    )
    out = (proc.stdout + proc.stderr).decode("utf-8", "replace")
    assert proc.returncode != 0 and "MAIN-CHECKOUT-HOOK" in out, (
        f"the linked worktree did not run the main checkout's hook: {out[-400:]!r}"
    )
