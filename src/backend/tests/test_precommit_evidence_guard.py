"""Integration tests for the .githooks/pre-commit evidence-path guard (issue #91).

P9 security F1: captured pytest output committed under docs/evidence/ leaked the
local account name and macOS temp-folder layout into a public repo. Check 4 of
the pre-commit hook now rejects staged evidence files containing local machine
paths. These tests run the real hook script inside a throwaway git repository
and also confirm the hook's pre-existing guards (checks 1-3) still fire.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Dict

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_HOOK = _REPO_ROOT / ".githooks" / "pre-commit"
_REQUIRED_LIST = _REPO_ROOT / ".claude" / "governance" / "required-gitignore.txt"
_LEAK_REGEX = _REPO_ROOT / ".claude" / "governance" / "evidence-leak-regex.txt"
_SCANNER = _REPO_ROOT / "scripts" / "governance" / "scan-evidence-leaks.sh"
_MATCHER = _REPO_ROOT / "scripts" / "governance" / "leak_scan.py"

# Home-path roots and private folder names are assembled at runtime so this
# tracked file is not itself a home-path leak (#145
# test_tracked_tree_has_no_home_paths, owner over-block policy 2026-10-08).
# The values are unchanged: _U == "/" "Users", _H == "/" "home".
_U = "/" + "Users"
_H = "/" + "home"
_DOCS = "Docu" + "ments"
_DESK = "Desk" + "top"
_DOWN = "Down" + "loads"
_U_B = _U.encode()
_H_B = _H.encode()
_DOCS_B = _DOCS.encode()

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or shutil.which("bash") is None,
    reason="git and bash are required to exercise the pre-commit hook",
)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A minimal git repo carrying the real hook, gitignore SSoT and .gitignore."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    (root / ".githooks").mkdir()
    shutil.copy2(_HOOK, root / ".githooks" / "pre-commit")
    (root / ".claude" / "governance").mkdir(parents=True)
    shutil.copy2(_REQUIRED_LIST, root / ".claude" / "governance" / "required-gitignore.txt")
    shutil.copy2(_LEAK_REGEX, root / ".claude" / "governance" / "evidence-leak-regex.txt")
    # Round 5: check 4 delegates matching to the shared normalising matcher.
    (root / "scripts" / "governance").mkdir(parents=True)
    shutil.copy2(_MATCHER, root / "scripts" / "governance" / "leak_scan.py")
    shutil.copy2(_REPO_ROOT / ".gitignore", root / ".gitignore")
    return root


def _stage(repo: Path, files: Dict[str, bytes]) -> None:
    for rel, content in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        _git(repo, "add", "-f", "--", rel)


def _run_hook(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(repo / ".githooks" / "pre-commit")],
        cwd=repo,
        capture_output=True,
        text=True,
    )


def test_precommit_clean_evidence_file_passes(repo: Path) -> None:
    _stage(repo, {"docs/evidence/run.txt": b"FAILED <tmp>/test_x.py::test_y\n<repo>/src\n"})
    result = _run_hook(repo)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "leak",
    [
        "/private/var/folders/n0/abc123/T/run/legal_kb.npy",
        "<tmp>/pytest-of-someuser/pytest-55/test_0/legal_kb.npy",
        _U + "/someuser/" + _DOCS + "/project/src/app.py",
    ],
)
def test_precommit_rejects_local_path_in_staged_evidence(repo: Path, leak: str) -> None:
    _stage(repo, {"docs/evidence/run.txt": f"line one\nE   {leak}\n".encode()})
    result = _run_hook(repo)
    assert result.returncode == 1
    assert "docs/evidence/run.txt" in result.stderr
    assert "line(s) 2" in result.stderr


def test_precommit_scans_nested_evidence_paths(repo: Path) -> None:
    _stage(repo, {"docs/evidence/sub/deep.md": _U_B + b"/x/thing\n"})
    assert _run_hook(repo).returncode == 1


def test_precommit_ignores_local_paths_outside_evidence(repo: Path) -> None:
    # The guard is scoped to docs/evidence/; other paths are out of scope.
    _stage(repo, {"docs/notes.md": _U_B + b"/x/thing\n", "src/a.py": b"# pytest-of-x\n"})
    assert _run_hook(repo).returncode == 0


def test_precommit_scans_staged_blob_not_working_tree(repo: Path) -> None:
    # A dirty staged blob must fail even if the working-tree copy was scrubbed
    # afterwards without re-staging.
    _stage(repo, {"docs/evidence/run.txt": b"/private/var/folders/aa/T/x\n"})
    (repo / "docs" / "evidence" / "run.txt").write_bytes(b"<tmp>/x\n")
    assert _run_hook(repo).returncode == 1


def test_precommit_scrubbed_and_restaged_file_passes(repo: Path) -> None:
    _stage(repo, {"docs/evidence/run.txt": b"/private/var/folders/aa/T/x\n"})
    _stage(repo, {"docs/evidence/run.txt": b"<tmp>/x\n"})
    assert _run_hook(repo).returncode == 0


def test_precommit_rejects_path_inside_binary_evidence_blob(repo: Path) -> None:
    # Round 2 (security R2-F3 vector 2): grep -I used to skip any blob with a
    # NUL byte, so one stray NUL hid a leak. NULs are now stripped first.
    _stage(repo, {"docs/evidence/report.bin": b"\x00\x01" + _U_B + b"/x\x00\xff"})
    assert _run_hook(repo).returncode == 1


def test_precommit_rejects_utf16_evidence_file(repo: Path) -> None:
    # Security R2-F3 vector 2: a UTF-16 export interleaves NULs with ASCII.
    content = ("ok\nE   " + _U + "/someuser/project/app.py\n").encode("utf-16")
    _stage(repo, {"docs/evidence/export.txt": content})
    result = _run_hook(repo)
    assert result.returncode == 1
    assert "line(s) 2" in result.stderr


def test_precommit_rejects_non_ascii_filename(repo: Path) -> None:
    # Security R2-F3 vector 1: core.quotePath C-quoted the name, the leading
    # '"' failed the docs/evidence/ prefix test and the file was skipped.
    _stage(repo, {"docs/evidence/r\u00e9sum\u00e9.txt": _U_B + b"/someuser/x\n"})
    result = _run_hook(repo)
    assert result.returncode == 1
    assert "docs/evidence/r\u00e9sum\u00e9.txt" in result.stderr


def test_precommit_rejects_filename_with_newline(repo: Path) -> None:
    # NUL-delimited listing: a newline in a name can't split it into two
    # paths that each miss the docs/evidence/ prefix.
    _stage(repo, {"docs/evidence/a\nb.txt": _H_B + b"/someuser/x\n"})
    assert _run_hook(repo).returncode == 1


@pytest.mark.parametrize(
    "leak",
    [
        "/var/folders/n0/abc123/T/run.npy",  # macOS temp root without /private
        _H + "/someuser/project/app.py",  # Linux home
        "pytest-of-someuser/pytest-1/x",  # bare pytest per-user dir
        # Round 3, security R3-F1: Claude Code scratchpad, dashed account name
        "/private/tmp/claude-503/-Users-alice-Documents-x/scratchpad",
        "see -Users-alice-Documents-proj for the slug",
        "/tmp/claude-503/session/scratchpad",
        # Round 3, security R3-F2 (lead decision: block, no waiver)
        "~/" + _DOCS + "/project/src",
        "~/Library/Mobile Documents/x",
        "~/" + _DESK + "/notes/x.md",
        "~/" + _DOWN + "/a.pdf",
        "$HOME/" + _DOCS + "/x",
        "${HOME}/" + _DESK + "/x",
        ".claude/worktrees/agent-af118a54/src",
    ],
)
def test_precommit_rejects_round2_regex_vectors(repo: Path, leak: str) -> None:
    _stage(repo, {"docs/evidence/run.txt": f"{leak}\n".encode()})
    assert _run_hook(repo).returncode == 1


@pytest.mark.parametrize(
    "scrubbed",
    [
        "/Users/<user>/project/app.py",
        "/home/<user>/project",
        "<tmp>/pytest-of-<user>/pytest-55/test_0",
        "/private/var/folders/<tmp>/T/x",
        "<repo>/src/backend",
        # Round 3: scrubbed forms of the new vectors
        "/private/tmp/claude-<uid>/-Users-<user>-Documents-x/scratchpad",
        ".claude/worktrees/agent-<hex>",
        # Round 3, R3-F2: a bare ~/ is allowed when the first segment is not a
        # private home folder (Documents, Desktop, Library, ...).
        "~/.claude/CLAUDE.md",
        "~/project/src",
        "~/",
        "the ~/" + _DOCS + " folder",  # private folder name with no trailing slash
    ],
)
def test_precommit_allows_scrubbed_placeholders(repo: Path, scrubbed: str) -> None:
    # Grumpy #6: already-scrubbed text must not be rejected.
    _stage(repo, {"docs/evidence/run.txt": f"{scrubbed}\n".encode()})
    result = _run_hook(repo)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "quoted",
    [
        # Round 3, grumpy #1: prose that QUOTES a pattern prefix (followed by
        # |, ..., `, ], ) or [) is not a path and must not be rejected.
        "/var/folders/|/(Users|home)/",
        "the /var/folders/... prefix",
        "`/var/folders/` and `/Users/`",
        "pytest-of-|/var/folders/",
        "pytest-of-... dirs",
        "match /Users/[^/<] and /home/)",
        "-Users-[A-Za-z0-9_] and /tmp/claude-[0-9]",
        "agent worktrees: .claude/worktrees/agent-[0-9a-f]",
        "(~|$HOME)/(Documents|Desktop)/",
    ],
)
def test_precommit_allows_prose_quoting_the_regex(repo: Path, quoted: str) -> None:
    _stage(repo, {"docs/evidence/review.md": f"{quoted}\n".encode()})
    result = _run_hook(repo)
    assert result.returncode == 0, result.stderr


def test_precommit_allows_the_regex_ssot_line_itself(repo: Path) -> None:
    # A review that pastes the exact SSoT pattern must not trip the guard.
    pattern = _ssot_pattern()
    _stage(repo, {"docs/evidence/review.md": f"Pattern: `{pattern}`\n".encode()})
    result = _run_hook(repo)
    assert result.returncode == 0, result.stderr


def _ssot_pattern() -> str:
    for line in _LEAK_REGEX.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            return line
    raise AssertionError("no pattern line in the SSoT")


def test_precommit_missing_regex_ssot_fails_closed(repo: Path) -> None:
    (repo / ".claude" / "governance" / "evidence-leak-regex.txt").unlink()
    _stage(repo, {"docs/evidence/run.txt": b"clean\n"})
    result = _run_hook(repo)
    assert result.returncode == 1
    assert "SSoT missing" in result.stderr


# ---------------------------------------------------------------------------
# CI scanner: scripts/governance/scan-evidence-leaks.sh (security R2-F2(b))
# ---------------------------------------------------------------------------


def _scan(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(_SCANNER), str(root)], capture_output=True, text=True
    )


def _scan_root(tmp_path: Path, files: Dict[str, bytes]) -> Path:
    root = tmp_path / "checkout"
    (root / ".claude" / "governance").mkdir(parents=True)
    shutil.copy2(_LEAK_REGEX, root / ".claude" / "governance" / "evidence-leak-regex.txt")
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return root


def test_scanner_clean_checkout_passes_and_reports_count(tmp_path: Path) -> None:
    root = _scan_root(tmp_path, {"docs/evidence/a.txt": b"<tmp>/x\n", "docs/evidence/b.png": b"\x89PNG"})
    result = _scan(root)
    assert result.returncode == 0, result.stderr
    assert "scanned 2 file(s)" in result.stdout


@pytest.mark.parametrize(
    "rel,content",
    [
        ("docs/evidence/a.txt", b"/var/folders/ab/T/x\n"),
        ("docs/evidence/deep/b.md", b"see " + _H_B + b"/someuser/x\n"),
        ("docs/evidence/r\u00e9sum\u00e9.txt", _U_B + b"/someuser/x\n"),
        ("docs/evidence/u16.txt", (_U + "/someuser/x\n").encode("utf-16")),
        ("docs/evidence/blob.bin", b"\x00\xffpytest-of-someuser\x00"),
        # Round 3, security R3-F1 / R3-F2
        ("docs/evidence/c.md", b"ran in /private/tmp/claude-503/-Users-alice-Docs/scratchpad\n"),
        ("docs/evidence/d.md", b"cwd ~/" + _DOCS_B + b"/05_Dev/legal-corpus-ingester/\n"),
        ("docs/evidence/e.md", b"worktree .claude/worktrees/agent-af118a54\n"),
    ],
)
def test_scanner_flags_leaks_in_checkout(tmp_path: Path, rel: str, content: bytes) -> None:
    root = _scan_root(tmp_path, {rel: content, "docs/evidence/clean.txt": b"ok\n"})
    result = _scan(root)
    assert result.returncode == 1
    assert "LEAK:" in result.stderr


def test_scanner_allows_scrubbed_and_quoted_forms(tmp_path: Path) -> None:
    root = _scan_root(
        tmp_path,
        {
            "docs/evidence/a.md": (
                b"/private/tmp/claude-<uid>/-Users-<user>-x/scratchpad\n"
                b".claude/worktrees/agent-<hex>\n~/.claude/CLAUDE.md\n"
                b"/var/folders/|pytest-of-|/(Users|home)/\n"
            ),
            "docs/evidence/b.md": f"`{_ssot_pattern()}`\n".encode(),
        },
    )
    result = _scan(root)
    assert result.returncode == 0, result.stderr


def test_scanner_ignores_paths_outside_evidence(tmp_path: Path) -> None:
    root = _scan_root(tmp_path, {"docs/notes.md": _U_B + b"/x/y\n", "docs/evidence/ok.txt": b"ok\n"})
    assert _scan(root).returncode == 0


def test_scanner_missing_regex_ssot_is_error(tmp_path: Path) -> None:
    root = _scan_root(tmp_path, {"docs/evidence/a.txt": b"ok\n"})
    (root / ".claude" / "governance" / "evidence-leak-regex.txt").unlink()
    assert _scan(root).returncode == 2


def test_scanner_without_evidence_dir_says_nothing_scanned(tmp_path: Path) -> None:
    root = _scan_root(tmp_path, {})
    result = _scan(root)
    assert result.returncode == 0
    assert "scanned 0 files" in result.stdout


def test_scanner_passes_on_this_repo_checkout() -> None:
    # The real docs/evidence/ in this checkout must be clean (same gate as CI).
    result = _scan(_REPO_ROOT)
    assert result.returncode == 0, result.stderr


def test_ci_workflow_runs_evidence_scanner() -> None:
    # Wiring check ("reviews catch diffs, not absences"): CI must call it.
    ci = (_REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "scripts/governance/scan-evidence-leaks.sh" in ci


def test_ci_workflow_least_privilege_and_range_scan_wired() -> None:
    # Round 3 (security CI notes): top-level read-only token, full history,
    # and a range scan over every commit in addition to the tip scan.
    import yaml  # PyYAML is a backend requirement; never skip this check
    ci = yaml.safe_load((_REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    assert ci["permissions"] == {"contents": "read"}
    steps = ci["jobs"]["evidence-scan"]["steps"]
    assert steps[0]["uses"].startswith("actions/checkout@")
    assert steps[0]["with"]["fetch-depth"] == 0
    runs = [step.get("run", "") for step in steps]
    assert any("scan-evidence-leaks.sh" in r and "--range" not in r for r in runs)
    range_step = next(step for step in steps if "--range" in step.get("run", ""))
    assert "github.event.pull_request.base.sha" in range_step["env"]["PR_BASE"]
    assert "github.event.pull_request.head.sha" in range_step["env"]["PR_HEAD"]
    assert "github.event.before" in range_step["env"]["PUSH_BEFORE"]


# ---------------------------------------------------------------------------
# Range mode: every line added under docs/evidence/ by each commit in a range
# (round 3, security CI note: a leak added then removed inside one PR).
# ---------------------------------------------------------------------------


def _history_repo(tmp_path: Path) -> Path:
    root = _scan_root(tmp_path, {})
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "README").write_text("base\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "tag", "base")
    return root


def _commit(root: Path, files: Dict[str, bytes], delete: tuple = ()) -> None:
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    for rel in delete:
        (root / rel).unlink()
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "change")


def _scan_range(root: Path, rev_range: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(_SCANNER), "--range", rev_range, str(root)],
        capture_output=True,
        text=True,
    )


def test_range_scan_catches_leak_added_then_removed(tmp_path: Path) -> None:
    root = _history_repo(tmp_path)
    _commit(root, {"docs/evidence/run.txt": b"ok\nE " + _U_B + b"/someuser/app.py\n"})
    leak_sha = _git(root, "rev-parse", "--short=7", "HEAD").stdout.strip()
    _commit(root, {"docs/evidence/run.txt": b"ok\nE <repo>/app.py\n"})
    # The tip is clean, so the tree scan passes ...
    assert _scan(root).returncode == 0
    # ... but the range scan finds the commit that added the leak.
    result = _scan_range(root, "base..HEAD")
    assert result.returncode == 1
    assert f"LEAK (history): {leak_sha} docs/evidence/run.txt" in result.stderr


def test_range_scan_clean_history_passes_and_reports_counts(tmp_path: Path) -> None:
    root = _history_repo(tmp_path)
    _commit(root, {"docs/evidence/a.txt": b"<tmp>/x\n~/.claude/x\n"})
    _commit(root, {"docs/notes.md": _U_B + b"/someuser/outside-evidence\n"})
    result = _scan_range(root, "base..HEAD")
    assert result.returncode == 0, result.stderr
    assert "1 commit(s) touching docs/evidence/, 2 added line(s)" in result.stdout


def test_range_scan_ignores_removed_lines(tmp_path: Path) -> None:
    # A commit that REMOVES a leak (scrub) must not be flagged itself.
    root = _history_repo(tmp_path)
    _commit(root, {"docs/evidence/a.txt": _U_B + b"/someuser/x\n"})
    _git(root, "tag", "dirty")
    _commit(root, {}, delete=("docs/evidence/a.txt",))
    assert _scan_range(root, "dirty..HEAD").returncode == 0


@pytest.mark.parametrize(
    "content",
    [
        ("x\n" + _U + "/someuser/x\n").encode("utf-16"),
        b"\x00\x01pytest-of-someuser\x00\xff",
    ],
)
def test_range_scan_reads_binary_and_utf16_additions(tmp_path: Path, content: bytes) -> None:
    root = _history_repo(tmp_path)
    _commit(root, {"docs/evidence/blob.bin": content})
    assert _scan_range(root, "base..HEAD").returncode == 1


def test_range_scan_does_not_treat_diff_header_as_content(tmp_path: Path) -> None:
    # The "+++ b/<path>" header must not be matched AS CONTENT: a file NAMED
    # like an agent worktree id is a name, not an added line.
    root = _history_repo(tmp_path)
    # Round 4: the NAME must match a regex alternative (rule 7) so a scanner
    # that wrongly emits "+++" headers as content would fail this test.
    _commit(root, {"docs/evidence/.claude/worktrees/agent-af11.txt": b"clean\n"})
    result = _scan_range(root, "base..HEAD")
    # #91 r8 (security F4): names are now scanned, so the name itself is a
    # leak, reported once as a NAME and never as an added content line.
    assert result.returncode == 1, result.stderr
    assert result.stderr.count("LEAK (history name): docs/evidence/.claude/worktrees/agent-af11.txt") == 1
    assert "LEAK (history):" not in result.stderr


def test_range_scan_bad_range_is_error_not_pass(tmp_path: Path) -> None:
    root = _history_repo(tmp_path)
    result = _scan_range(root, "no-such-rev..HEAD")
    assert result.returncode == 2
    assert "git log failed" in result.stderr


def test_range_scan_requires_a_range_argument(tmp_path: Path) -> None:
    root = _history_repo(tmp_path)
    result = subprocess.run(["bash", str(_SCANNER), "--range"], cwd=root, capture_output=True, text=True)
    assert result.returncode == 2


def test_range_scan_missing_regex_ssot_is_error(tmp_path: Path) -> None:
    root = _history_repo(tmp_path)
    (root / ".claude" / "governance" / "evidence-leak-regex.txt").unlink()
    assert _scan_range(root, "base..HEAD").returncode == 2


def test_range_scan_covers_merge_commit_resolution(tmp_path: Path) -> None:
    # -m: a line introduced only in a merge commit's resolution is scanned.
    root = _history_repo(tmp_path)
    _git(root, "checkout", "-q", "-b", "side")
    _commit(root, {"docs/evidence/s.txt": b"side\n"})
    _git(root, "checkout", "-q", "-")
    _commit(root, {"docs/evidence/m.txt": b"main\n"})
    _git(root, "merge", "-q", "--no-commit", "--no-ff", "side")
    (root / "docs" / "evidence" / "m.txt").write_bytes(b"main\n" + _H_B + b"/someuser/x\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "merge")
    assert _scan_range(root, "HEAD^1..HEAD").returncode == 1


def test_precommit_existing_env_guard_still_fires(repo: Path) -> None:
    _stage(repo, {"config/.ENV": b"SECRET=1\n"})
    result = _run_hook(repo)
    assert result.returncode == 1
    assert ".env-style file" in result.stderr


def test_precommit_existing_graveyard_guard_still_fires(repo: Path) -> None:
    _stage(repo, {".venv/lib.py": b"x = 1\n"})
    result = _run_hook(repo)
    assert result.returncode == 1
    assert "graveyard" in result.stderr


def test_precommit_existing_gitignore_guard_still_fires(repo: Path) -> None:
    (repo / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    result = _run_hook(repo)
    assert result.returncode == 1
    assert "missing required pattern" in result.stderr
