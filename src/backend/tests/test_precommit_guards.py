"""Acceptance tests for terms-analysis #145 (folds #78).

Card: strip absolute user-home path leaks from the tracked tree, block them
in `.githooks/pre-commit` and in the gitignore-enforcement workflow, stop
graveyard directories (e.g. `.pip-cache/`) from being staged at any depth,
and close the Unicode homoglyph bypass of the `.env` guard.

Split per the #145 design gate (owner rulings on #199):

* Part A (active, required CI gate through pytest): the tracked tree has no
  home path and no gitignored file, judged by the INTERIM pattern file
  `.claude/governance/personal-path-patterns.txt` (O1; Part B deletes it in
  favour of the one `leak_scan.py` scanner from #192). Matching is
  case-insensitive, after Unicode Cf characters are removed. The tilde /
  $HOME standard-home-folder prefixes are leaks too (O3).
* Part B (after #192): staged-content guard, nested graveyard, `.env`
  look-alikes and CI wiring. Those cases are `xfail(strict=True)` with
  reason "Part B, #192" so they stay red for a stated reason and flip loudly
  (XPASS fails the run) when Part B lands. Controls that the CURRENT hook or
  workflow already satisfy stay active, so a Part A change cannot break them.

Behaviour over text: every hook case runs the real `.githooks/pre-commit`
inside a throwaway git repo, and every CI case runs the real `run:` steps of
`.github/workflows/gitignore-enforcement.yml` against a throwaway tree.

F13: home-path patterns come from the pattern file and graveyard directories
from `.claude/governance/required-gitignore.txt`; nothing here restates them.
Home-path vectors are assembled at runtime so this file is not a leak itself.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tarfile
import io
import json
import unicodedata
from pathlib import Path

import pytest
import yaml

# --- Paths resolved once, before any env is altered (AGENT-LANES probes). ---
REPO_ROOT = Path(__file__).resolve().parents[3]
HOOKS_DIR = REPO_ROOT / ".githooks"
HOOK_NAME = "pre-commit"
GOV_DIR = REPO_ROOT / ".claude" / "governance"
PATTERNS_FILE = GOV_DIR / "personal-path-patterns.txt"
REQUIRED_GITIGNORE_FILE = GOV_DIR / "required-gitignore.txt"
GITIGNORE_FILE = REPO_ROOT / ".gitignore"
WORKFLOW_FILE = REPO_ROOT / ".github" / "workflows" / "gitignore-enforcement.yml"
SCRIPTS_DIR = REPO_ROOT / "scripts"  # copied whole so a helper may live there

# Harness bounds (test parameters, not product config).
HOOK_TIMEOUT_S = 120
REFUSED = 1  # the hook's documented refusal exit code (`fail()` in the hook)


# --------------------------------------------------------------------------
# Config loading (same comment/blank format as required-gitignore.txt)
# --------------------------------------------------------------------------
def _load_ssot_lines(path: Path) -> list[str]:
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


class PatternConfigError(Exception):
    """The interim pattern file is unusable; the tree check fails closed."""


def _load_home_patterns(path: Path) -> list[re.Pattern[str]]:
    """Interim Part A matcher config loader (O1; deleted in Part B).

    Fails closed on anything a shell consumer could read differently from
    Python (attack sketch T3): missing file, BOM, CR, no patterns, a pattern
    that does not compile, or a pattern that matches the empty string.
    Patterns are compiled case-insensitively (design P1-2).
    """
    if not path.is_file():
        raise PatternConfigError(f"pattern config missing: {path.name}")
    data = path.read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):
        raise PatternConfigError(f"pattern config has a UTF-8 BOM: {path.name}")
    if b"\r" in data:
        raise PatternConfigError(f"pattern config has CR line endings: {path.name}")
    lines = []
    for raw in data.decode("utf-8").split("\n"):
        if not raw.strip():
            continue
        # Edge whitespace first: an indented "# ..." is not a comment to a shell
        # `grep -v '^#'`, so it must fail closed rather than be skipped here.
        if raw != raw.strip():
            raise PatternConfigError(f"pattern config line has edge whitespace: {path.name}")
        if raw.startswith("#"):
            continue
        lines.append(raw)
    if not lines:
        raise PatternConfigError(f"pattern config has no patterns: {path.name}")
    out = []
    for line in lines:
        try:
            pat = re.compile(line, re.IGNORECASE)
        except re.error as exc:
            raise PatternConfigError(f"pattern config regex does not compile: {path.name}") from exc
        if pat.search(""):
            raise PatternConfigError(f"pattern config regex matches the empty string: {path.name}")
        out.append(pat)
    return out


def _home_patterns() -> list[re.Pattern[str]]:
    return _load_home_patterns(PATTERNS_FILE)


def _graveyard_dirs() -> list[str]:
    """Directory patterns from the required-gitignore SSoT (end with '/')."""
    return [p for p in _load_ssot_lines(REQUIRED_GITIGNORE_FILE) if p.endswith("/") and "*" not in p]


def _strip_cf(text: str) -> str:
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf")


def _leaks(text: str, patterns: list[re.Pattern[str]]) -> bool:
    norm = _strip_cf(text)
    return any(p.search(norm) for p in patterns)


# --------------------------------------------------------------------------
# Vectors. Built at runtime: "/" + root + "/" + user.
# --------------------------------------------------------------------------
def home(root: str = "Users", user: str = "alice", rest: str = "/x") -> str:
    return "/" + root + "/" + user + rest


def win_home(sep: str = "\\", user: str = "alice") -> str:
    return "C:" + sep + "Users" + sep + user + sep + "x"


def tilde(folder: str, prefix: str = "~") -> str:
    """A standard macOS home folder under ~ or $HOME (O3: a leak)."""
    return prefix + "/" + folder + "/x"


LEAK = home()  # the canonical hostile value used across hook cases

# (family, vector). Every family has at least one block AND one allow row
# (QUALITY-BAR rule 9, enforced by test_vector_table_families_have_both_sides).
BLOCK_ROWS = [
    ("posix-home", "cd " + home() + "\n"),
    ("posix-home", "cd " + home("home", "bob") + "\n"),
    ("posix-home", "file://" + home()),
    ("posix-home", "file://" + home("home", "bob")),  # file: URL, home root
    ("posix-home", "file://localhost" + home()),  # file: URL with a host
    ("posix-home", "file:///Volumes/X" + home()),  # file: URL under a volume
    # Owner ruling 2026-10-08: `home`/`Users` at ANY depth in a file: URL blocks.
    ("posix-home", "file:///mnt/x" + home("home", "y", "")),
    ("posix-home", "file://wsl.localhost/Ubuntu" + home("home", "a", "")),
    ("posix-home", "file:///srv" + home("home", "alice")),
    ("posix-home", "file:///var" + home("home", "alice")),
    ("posix-home", "file:///System/Volumes/Data" + home("home", "a", "")),
    ("posix-home", "file:///tmp" + home("home", "x", "")),
    ("posix-home", "file:/tmp" + home("home", "x", "")),
    # grumpy/security F2: colon-separated lists (PATH, LD_LIBRARY_PATH style).
    ("posix-home", "PATH=/usr/bin:" + home("home", "bob", "/bin")),
    ("posix-home", "LD=/a:" + home("Users", "bob", "/lib")),
    ("posix-home", '"' + home("Users", "Alice") + '"'),
    ("posix-home", "[doc](" + home("Users", "j.doe") + ")"),
    ("posix-home", "`" + home("home", "a_b-1") + "`"),
    ("posix-home", "PATH=" + home("Users", "9z")),
    # final-r2 F5 (regression vs 22475ca): empty, dot or relative item before
    # the colon. Owner policy 2026-10-08: block home paths in ALL list forms.
    *[
        ("posix-home", prefix + home(root, user, ""))
        for root, user in (("home", "x"), ("Users", "x"))
        for prefix in ("PATH=:", "PATH=/a::", "PATH=.:", "PATH=bin:")
    ],
    ("posix-home", '"bin:' + home("Users", "bob", "") + '"'),  # quoted list item
    # owner: over-block accepted; word:/home/... is list-shaped (was an allow row).
    ("posix-home", "profile:/" + "Users" + "/x"),
    ("posix-home", "/" + "Users" + "/\u200balice/x"),  # Cf right after the slash
    ("posix-home", "/" + "Us\u200bers" + "/alice/x"),  # Cf inside the root
    ("posix-home", "/" + "home" + "/\u202ebob/x"),  # bidi override
    ("posix-lowercase", "cd " + home("users", "alice")),  # macOS FS is case-insensitive
    ("posix-lowercase", "cd " + home("HOME", "bob")),
    ("windows", "dir " + win_home("\\")),
    ("windows", "dir " + win_home("/")),
    ("windows", "dir " + win_home("\\").lower()),
    ("deep-macos", "/System/Volumes/Data" + home()),
    ("deep-macos", "/Volumes/Backup" + home()),
    ("home-private", "cd " + tilde("Docu" + "ments")),
    ("home-private", "see " + tilde("Desk" + "top")),
    ("home-private", "see " + tilde("Down" + "loads")),
    ("home-private", "cd " + tilde("Docu" + "ments", "$HOME")),  # $HOME prefix branch
    ("home-private", "cd " + tilde("Desk" + "top", "${HOME}")),  # ${HOME} prefix branch
    ("home-private", "~/Down" + "loads"),  # end-of-line branch: nothing after the folder
]

ALLOW_ROWS = [
    ("posix-home", "/" + "Users" + "/<name>/x"),
    ("posix-home", "/" + "home" + "/<user>/x"),
    ("posix-home", "the /" + "Users" + "/ directory"),
    ("posix-home", "Users/alice (relative, no root)"),
    ("posix-home", "https://api.github.com/" + "users/alice"),  # public URL, any case
    ("posix-lowercase", "src/" + "home/x"),  # relative: no anchor
    ("posix-lowercase", "api/" + "users/42"),  # relative REST route
    ("windows", "C:" + "\\" + "Users" + "\\<name>\\x"),
    ("windows", "C:" + "\\Program Files\\x"),
    ("deep-macos", "/System/Volumes/Data/Shared/x"),
    ("home-private", "$HOME/.claude/CLAUDE.md"),
    ("home-private", "~/.claude/CLAUDE.md"),
    ("home-private", "~/<projects>/x"),
    ("home-private", "~/Down" + "loads2/x"),  # name continues: not the standard folder
]

BLOCK_VECTORS = [v for _, v in BLOCK_ROWS]
ALLOW_VECTORS = [v for _, v in ALLOW_ROWS]

# Part B marker (owner ruling on #199, O1). strict: an unexpected pass fails.
PART_B = pytest.mark.xfail(strict=True, reason="Part B, #192")

# Refusal reason tags the Part B guard must print next to the file name, so a
# crash (set -e, rc 1) can never be mistaken for a refusal (attack sketch s3).
REASON_HOME = "home-path"
REASON_CONFIG = "config"
REASON_GRAVEYARD = "graveyard"
REASON_ENV = ".env"
CRASH_MARKERS = ("Traceback", "unbound variable", "command not found", "syntax error",
                 "illegal option", "invalid option", "usage:")


# --------------------------------------------------------------------------
# Sandbox helpers
# --------------------------------------------------------------------------
def _env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.invalid",
        }
    )
    if extra:
        env.update(extra)
    return env


def _git(repo: Path, *args: str, check: bool = True, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=repo, env=env or _env(), capture_output=True,
        check=check, timeout=HOOK_TIMEOUT_S,
    )


def _copy_tracked(src_dir: Path, dest_root: Path) -> None:
    """Copy only git-tracked files under src_dir (no stray __pycache__ etc.)."""
    rel_dir = src_dir.relative_to(REPO_ROOT)
    raw = subprocess.run(["git", "ls-files", "-z", "--", str(rel_dir)], cwd=REPO_ROOT,
                         capture_output=True, check=True).stdout
    for rec in raw.split(b"\0"):
        if rec:
            rel = os.fsdecode(rec)
            (dest_root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO_ROOT / rel, dest_root / rel)


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    shutil.copy2(GITIGNORE_FILE, repo / ".gitignore")
    _copy_tracked(GOV_DIR, repo)
    _copy_tracked(HOOKS_DIR, repo)
    _copy_tracked(SCRIPTS_DIR, repo)
    return repo


def _write(repo: Path, rel: str, content: bytes | str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    data = content.encode("utf-8", "surrogatepass") if isinstance(content, str) else content
    path.write_bytes(data)


def _stage(repo: Path, *rels: str) -> None:
    # Force-add so .gitignore cannot hide a vector from the hook.
    _git(repo, "add", "-f", "--", *rels)


def _run_hook(repo: Path, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(repo / ".githooks" / HOOK_NAME)], cwd=repo, env=_env(extra_env),
        capture_output=True, timeout=HOOK_TIMEOUT_S,
    )


def _err(proc: subprocess.CompletedProcess) -> str:
    return (proc.stdout + proc.stderr).decode("utf-8", "replace")


def _assert_refused(proc: subprocess.CompletedProcess, *, name: str, reason: str) -> None:
    """A refusal is rc == REFUSED AND names the file AND states the reason.

    Attack sketch s3: under `set -e` most crashes also exit 1, so the exit
    code alone cannot tell a refusal from a crash. Crash signatures fail it.
    """
    out = _err(proc)
    assert proc.returncode == REFUSED, f"expected refusal rc={REFUSED}, got {proc.returncode}: {out[-600:]!r}"
    crashes = [m for m in CRASH_MARKERS if m in out]
    assert crashes == [], f"rc={REFUSED} came from a crash, not a refusal: {crashes} in {out[-600:]!r}"
    assert name and name in out, f"refusal does not name {name!r}: {out[-600:]!r}"
    assert reason and reason in out, f"refusal does not state reason {reason!r}: {out[-600:]!r}"
    # F8: the message must not re-leak the home path it is refusing.
    assert LEAK not in out and _strip_cf(LEAK) not in _strip_cf(out)


def _safe_fragment(name: str) -> str:
    """The plain-ASCII lead of a hostile file name, which any escaping keeps."""
    m = re.match(r"[A-Za-z0-9 _-]+", name)
    assert m, name
    return m.group(0)


# ==========================================================================
# 1. Tracked tree (deterministic, config-driven)
# ==========================================================================
def _tracked_entries() -> list[tuple[str, str]]:
    raw = subprocess.run(
        ["git", "ls-files", "-s", "-z"], cwd=REPO_ROOT, capture_output=True, check=True
    ).stdout
    out = []
    for rec in raw.split(b"\0"):
        if not rec:
            continue
        meta, path = rec.split(b"\t", 1)
        out.append((meta.split(b" ")[0].decode(), os.fsdecode(path)))
    return out


def test_tracked_tree_has_no_home_paths():
    """Part A acceptance: no tracked blob (or symlink target) has a home path.

    Red today: 2 docs with absolute home paths, 3 governance docs with a
    tilde standard-home-folder prefix (O3), and the tracked .pip-cache/.
    """
    patterns = _home_patterns()
    offenders = []
    for mode, rel in _tracked_entries():
        p = REPO_ROOT / rel
        if mode == "120000":
            text = os.readlink(p)
        elif mode == "160000":
            continue  # gitlink: no blob in this repo
        elif p.is_file():
            text = p.read_bytes().decode("utf-8", "replace")
        else:
            raise AssertionError(f"tracked path missing from worktree: {rel!r}")
        if _leaks(text, patterns):
            offenders.append(rel)
    assert offenders == [], f"{len(offenders)} tracked file(s) contain a user-home path: {offenders[:10]}"


def test_no_tracked_file_is_gitignored():
    """Covers the committed src/backend/.pip-cache/ (231 files on main)."""
    out = subprocess.run(
        ["git", "ls-files", "-ci", "--exclude-standard", "-z"], cwd=REPO_ROOT,
        capture_output=True, check=True,
    ).stdout
    ignored = [os.fsdecode(x) for x in out.split(b"\0") if x]
    assert ignored == [], f"{len(ignored)} tracked file(s) match .gitignore, e.g. {ignored[:3]}"


@pytest.mark.parametrize("family,vector", BLOCK_ROWS, ids=[f"{f}:{ascii(v)}" for f, v in BLOCK_ROWS])
def test_matcher_blocks_vector(family, vector):
    assert _leaks(vector, _home_patterns()), f"[{family}] block vector not detected: {vector!r}"


@pytest.mark.parametrize("family,vector", ALLOW_ROWS, ids=[f"{f}:{ascii(v)}" for f, v in ALLOW_ROWS])
def test_matcher_allows_vector(family, vector):
    assert not _leaks(vector, _home_patterns()), f"[{family}] allow vector falsely detected: {vector!r}"


# grumpy r2 F1 (ReDoS): every pattern row must answer a hostile line inside the
# budget. A subprocess with a hard timeout keeps a catastrophic regex from
# hanging CI; the child measures its own match time.
REDOS_BUDGET_S = 0.5
REDOS_KILL_S = 20  # hard stop for the child: a hang fails instead of stalling CI
REDOS_SLASHES = 5000
REDOS_LINES = {
    "file-slash-run-then-x": "file:" + "/" * REDOS_SLASHES + "x",
    # security r2: 2 MB line, the size a committed blob can reach, ending in `!`.
    "file-slash-run-2mb-bang": "file:" + "/" * (2 * 1024 * 1024) + "!",
    "file-slash-run-only": "file:" + "/" * REDOS_SLASHES,
    "file-named-slash-runs": "file:" + "/a" * (REDOS_SLASHES // 2) + "//" * 50 + "x",
    "bare-slash-run": "/" * REDOS_SLASHES + "x",
    "bare-segments": "/a" * (REDOS_SLASHES // 2) + "x",
    "windows-sep-run": "C:" + "\\" * REDOS_SLASHES + "x",
}
_REDOS_CHILD = (
    "import json, re, sys, time\n"
    "pat, line = json.load(sys.stdin)\n"
    "rx = re.compile(pat, re.IGNORECASE)\n"
    "t = time.perf_counter()\n"
    "hit = bool(rx.search(line))\n"
    "print(json.dumps([hit, time.perf_counter() - t]))\n"
)


@pytest.mark.parametrize("line_id", sorted(REDOS_LINES))
@pytest.mark.parametrize("pattern", [p.pattern for p in _home_patterns()])
def test_pattern_rows_answer_hostile_line_within_budget(pattern, line_id):
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", _REDOS_CHILD],
            input=json.dumps([pattern, REDOS_LINES[line_id]]),
            capture_output=True, text=True, timeout=REDOS_KILL_S,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"ReDoS: {pattern!r} did not finish {line_id} in {REDOS_KILL_S}s")
    assert proc.returncode == 0, proc.stderr[-300:]
    _, elapsed = json.loads(proc.stdout)
    assert elapsed < REDOS_BUDGET_S, f"{pattern!r} took {elapsed:.2f}s on {line_id}"


def test_file_url_long_slash_run_without_home_root_is_allowed():
    """grumpy r2 F1 allow vector: 40 slashes after `file:`, no home root.

    Run in the budgeted child, not in-process: a backtracking row 4 regex
    would take hours on this line (r2), and an in-process search would hang
    the whole suite. Each row must finish inside the time budget.
    """
    line = "file:" + "/" * 40 + "x"
    for pattern in [p.pattern for p in _home_patterns()]:
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "-c", _REDOS_CHILD],
                input=json.dumps([pattern, line]),
                capture_output=True, text=True, timeout=REDOS_KILL_S,
            )
        except subprocess.TimeoutExpired:
            pytest.fail(f"ReDoS: {pattern!r} did not finish in {REDOS_KILL_S}s")
        hit, elapsed = json.loads(proc.stdout)
        assert elapsed < REDOS_BUDGET_S, f"{pattern!r} took {elapsed:.2f}s"
        assert not hit, f"{pattern!r} falsely blocks a home-less file: line"


def test_vector_table_families_have_both_sides():
    """Rule 9 contract: every family has a block row and an allow row."""
    block = {f for f, _ in BLOCK_ROWS}
    allow = {f for f, _ in ALLOW_ROWS}
    assert block == allow, f"families missing a side: block-only {block - allow}, allow-only {allow - block}"


def test_every_pattern_has_a_block_vector():
    """R2: a pattern no vector exercises is dead config, or an untested rule."""
    for p in _home_patterns():
        assert any(p.search(_strip_cf(v)) for v in BLOCK_VECTORS), f"pattern {p.pattern!r} has no block vector"


def test_matcher_generated_hostile_vectors():
    """R2: the leak survives every Cf/Cc/Zl/Zp/line-break/Cs/NUL/bad-UTF-8 wrap.

    Decoded the way the tree test decodes a blob (UTF-8, errors replaced).
    The ANSI-wrapped case is a Part B scanner concern (escape stripping) and
    is exercised only through the hook.
    """
    patterns = _home_patterns()
    cases = {k: v for k, v in _generated_cases().items() if k != "ansi_conceal.md"}
    print(f"generated hostile matcher cases: {len(cases)}")
    missed = [k for k, v in cases.items() if not _leaks(v.decode("utf-8", "replace"), patterns)]
    assert missed == [], f"{len(missed)}/{len(cases)} generated leaks missed, e.g. {missed[:5]}"


BAD_PATTERN_CONFIGS = {
    "empty": b"",
    "comments-only": b"# only comments\n\n",
    "bad-regex": b"([\n",
    "crlf": b"/Users/[a-z]\r\n",
    "bom": b"\xef\xbb\xbf/Users/[a-z]\n",
    "matches-empty": b".*\n",
    "optional-only": b"x?\n",
    "edge-whitespace": b"/Users/[a-z] \n",
    "indented-comment": b"  # c\n/Users/[a-z]\n",  # grep -v '^#' would compile it
}


@pytest.mark.parametrize("body", BAD_PATTERN_CONFIGS.values(), ids=BAD_PATTERN_CONFIGS.keys())
def test_bad_pattern_config_fails_closed_at_load(tmp_path, body):
    """F13 / attack sketch T3: a config a shell could read differently fails closed."""
    cfg = tmp_path / PATTERNS_FILE.name
    cfg.write_bytes(body)
    with pytest.raises(PatternConfigError) as exc:
        _load_home_patterns(cfg)
    assert str(tmp_path) not in str(exc.value), "absolute path in config error (F8)"


def test_missing_pattern_config_fails_closed_at_load(tmp_path):
    with pytest.raises(PatternConfigError):
        _load_home_patterns(tmp_path / PATTERNS_FILE.name)


# ==========================================================================
# 2. Hook: home-path content check
# ==========================================================================
@PART_B
def test_rejects_staged_personal_path(sandbox):
    _write(sandbox, "doc.md", "cd " + LEAK + "\n")
    _stage(sandbox, "doc.md")
    _assert_refused(_run_hook(sandbox), name="doc.md", reason=REASON_HOME)


def test_allows_policy_placeholder(sandbox):
    """Control, green today: the current hook has no content scan at all."""
    for i, v in enumerate(ALLOW_VECTORS):
        _write(sandbox, f"ok{i}.md", v + "\n")
    _stage(sandbox, *[f"ok{i}.md" for i in range(len(ALLOW_VECTORS))])
    proc = _run_hook(sandbox)
    assert proc.returncode == 0, _err(proc)


@PART_B
@pytest.mark.parametrize("idx", range(len(BLOCK_VECTORS)))
def test_rejects_block_vector(sandbox, idx):
    _write(sandbox, "v.md", BLOCK_VECTORS[idx])
    _stage(sandbox, "v.md")
    _assert_refused(_run_hook(sandbox), name="v.md", reason=REASON_HOME)


def _generated_cases() -> dict[str, bytes]:
    """R2: generated hostile cases over Cf, Cc, Zl, Zp, line breaks, Cs, NUL."""
    cases: dict[str, bytes] = {}
    leak_b = LEAK.encode()
    root, user = "Users", "alice"
    for cp in range(sys.maxunicode + 1):
        cat = unicodedata.category(chr(cp))
        c = chr(cp)
        if cat == "Cf":
            cases[f"cf_{cp:05x}_a.md"] = ("/" + root + "/" + c + user + "/x").encode("utf-8", "surrogatepass")
            cases[f"cf_{cp:05x}_b.md"] = ("/" + root[:2] + c + root[2:] + "/" + user + "/x").encode("utf-8", "surrogatepass")
        elif cat in ("Cc", "Zl", "Zp"):
            cases[f"{cat.lower()}_{cp:05x}.md"] = c.encode() + leak_b + c.encode()
    for name, sep in {"crlf": "\r\n", "nel": "\x85", "vt": "\x0b", "ff": "\x0c"}.items():
        cases[f"lb_{name}.md"] = ("x" + sep + LEAK + sep).encode()
    cases["cs_lone_surrogate.md"] = b"\xed\xa0\x80" + leak_b + b"\xed\xbf\xbf"
    cases["invalid_utf8.md"] = b"\xff\xfe\xc0\xaf" + leak_b + b"\x80"
    cases["nul_binary.bin"] = b"\x00\x01\x02" + leak_b + b"\x00"
    cases["ansi_conceal.md"] = b"\x1b[8m" + leak_b + b"\x1b[0m"
    return cases


@PART_B
def test_generated_hostile_content_all_refused(sandbox):
    cases = _generated_cases()
    print(f"generated hostile content cases: {len(cases)}")
    for name, data in cases.items():
        _write(sandbox, name, data)
    _stage(sandbox, *cases)
    proc = _run_hook(sandbox)
    out = _err(proc)
    assert proc.returncode == REFUSED, f"rc={proc.returncode}"
    missed = [n for n in cases if n not in out]
    assert missed == [], f"{len(missed)}/{len(cases)} generated leaks not reported, e.g. {missed[:5]}"
    assert "\x1b" not in out, "raw ESC echoed to terminal"


HOSTILE_NAMES = [
    "café.md", "a b.md", "tab\t.md", "nl\n.md", "esc\x1b[31m.md",
    'quote".md', "-n.md", "--help.md", "bidi‮md.txt",
]


@PART_B
@pytest.mark.parametrize("quotepath", ["true", "false"])
@pytest.mark.parametrize("name", HOSTILE_NAMES, ids=[repr(n) for n in HOSTILE_NAMES])
def test_hostile_filename_with_leak_refused(sandbox, name, quotepath):
    _write(sandbox, name, "cd " + LEAK + "\n")
    _stage(sandbox, name)
    proc = _run_hook(sandbox, {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.quotePath",
                               "GIT_CONFIG_VALUE_0": quotepath})
    _assert_refused(proc, name=_safe_fragment(name), reason=REASON_HOME)
    out = _err(proc)
    assert "\x1b" not in out and "‮" not in out, "raw control bytes from filename echoed"


HOSTILE_NAME_PARAMS = [
    pytest.param(n, id=repr(n), marks=PART_B if n.startswith("-") else ())
    for n in HOSTILE_NAMES
]


@pytest.mark.parametrize("name", HOSTILE_NAME_PARAMS)
def test_hostile_filename_clean_allowed(sandbox, name):
    """Positive control: hostile names with clean content are not refused.

    Leading-dash names are Part B: today's hook runs `basename` without `--`
    and crashes on them (attack sketch T7).
    """
    _write(sandbox, name, "nothing personal\n")
    _stage(sandbox, name)
    proc = _run_hook(sandbox)
    assert proc.returncode == 0, _err(proc)


@PART_B
def test_scans_index_not_worktree(sandbox):
    """F7: the staged blob is what gets committed; scan that, not the worktree."""
    _write(sandbox, "doc.md", "cd " + LEAK + "\n")
    _stage(sandbox, "doc.md")
    _write(sandbox, "doc.md", "clean now\n")
    _assert_refused(_run_hook(sandbox), name="doc.md", reason=REASON_HOME)


def test_dirty_worktree_clean_index_allowed(sandbox):
    """Control, green today (no content scan yet); Part B must keep it green."""
    _write(sandbox, "doc.md", "clean\n")
    _stage(sandbox, "doc.md")
    _write(sandbox, "doc.md", "cd " + LEAK + "\n")
    proc = _run_hook(sandbox)
    assert proc.returncode == 0, _err(proc)


@PART_B
def test_symlink_to_home_path_refused(sandbox):
    os.symlink(home("Users", "alice", "/secret"), sandbox / "link")
    _stage(sandbox, "link")
    _assert_refused(_run_hook(sandbox), name="link", reason=REASON_HOME)


@PART_B
def test_huge_single_line_leak_refused(sandbox):
    _write(sandbox, "big.txt", b"a" * (2 * 1024 * 1024) + LEAK.encode())
    _stage(sandbox, "big.txt")
    _assert_refused(_run_hook(sandbox), name="big.txt", reason=REASON_HOME)


@PART_B
def test_many_files_one_leak_refused(sandbox):
    n = 3000
    for i in range(n):
        _write(sandbox, f"many/f{i:05d}.md", "clean\n")
    _write(sandbox, f"many/f{n - 1:05d}.md", LEAK)
    _stage(sandbox, "many")
    _assert_refused(_run_hook(sandbox), name=f"f{n - 1:05d}.md", reason=REASON_HOME)


@PART_B
def test_clean_commit_reports_count(sandbox):
    """F12/R4: success carries an exact attestation line (design P1-5)."""
    n = 7
    for i in range(n):
        _write(sandbox, f"c{i}.md", "clean\n")
    _stage(sandbox, *[f"c{i}.md" for i in range(n)])
    proc = _run_hook(sandbox)
    assert proc.returncode == 0, _err(proc)
    lines = _err(proc).splitlines()
    assert f"CLEAN {n}" in lines, f"no exact 'CLEAN {n}' sentinel line: {lines!r}"


# --- config fail-closed (F13) ---------------------------------------------
PATTERNS_REL = PATTERNS_FILE.relative_to(REPO_ROOT)


def _clean_stage(repo: Path) -> None:
    _write(repo, "c.md", "clean\n")
    _stage(repo, "c.md")


@PART_B
def test_missing_pattern_config_fails_closed(sandbox):
    (sandbox / PATTERNS_REL).unlink()
    _clean_stage(sandbox)
    proc = _run_hook(sandbox)
    _assert_refused(proc, name=PATTERNS_FILE.name, reason=REASON_CONFIG)
    out = _err(proc)
    assert str(sandbox) not in out and str(sandbox.resolve()) not in out, "absolute path in message (F8)"


@PART_B
@pytest.mark.parametrize("body", BAD_PATTERN_CONFIGS.values(), ids=BAD_PATTERN_CONFIGS.keys())
def test_bad_pattern_config_fails_closed(sandbox, body):
    (sandbox / PATTERNS_REL).write_bytes(body)
    _clean_stage(sandbox)
    _assert_refused(_run_hook(sandbox), name=PATTERNS_FILE.name, reason=REASON_CONFIG)


@PART_B
def test_missing_required_gitignore_message_has_no_absolute_path(sandbox):
    (sandbox / REQUIRED_GITIGNORE_FILE.relative_to(REPO_ROOT)).unlink()
    _clean_stage(sandbox)
    proc = _run_hook(sandbox)
    assert proc.returncode == REFUSED
    out = _err(proc)
    assert str(sandbox) not in out and str(sandbox.resolve()) not in out, "absolute path in message (F8)"


# ==========================================================================
# 3. Hook: graveyard dirs at any depth (pip-cache)
# ==========================================================================
@PART_B
def test_rejects_pip_cache(sandbox):
    _write(sandbox, "src/backend/.pip-cache/selfcheck/x", "{}\n")
    _stage(sandbox, "src/backend/.pip-cache/selfcheck/x")
    _assert_refused(_run_hook(sandbox), name="src/backend/.pip-cache/selfcheck/x", reason=REASON_GRAVEYARD)


@PART_B
@pytest.mark.parametrize("d", _graveyard_dirs())
def test_rejects_nested_graveyard_dir(sandbox, d):
    rel = f"src/backend/{d}x.txt"
    _write(sandbox, rel, "x\n")
    _stage(sandbox, rel)
    _assert_refused(_run_hook(sandbox), name=rel, reason=REASON_GRAVEYARD)


@pytest.mark.parametrize("d", _graveyard_dirs())
def test_allows_graveyard_lookalike_name(sandbox, d):
    """Negative: a directory merely containing the name is not a graveyard dir."""
    rel = f"src/backend/{d.rstrip('/')}_notes/x.txt"
    _write(sandbox, rel, "x\n")
    _stage(sandbox, rel)
    proc = _run_hook(sandbox)
    assert proc.returncode == 0, _err(proc)


def test_root_pip_cache_still_refused(sandbox):
    """Control: green today (root-prefix graveyard check exists on main)."""
    _write(sandbox, ".pip-cache/x", "x\n")
    _stage(sandbox, ".pip-cache/x")
    _assert_refused(_run_hook(sandbox), name=".pip-cache/x", reason=REASON_GRAVEYARD)


# ==========================================================================
# 4. Hook: .env homoglyphs (#78)
# ==========================================================================
ENV_BLOCK = [
    ".env", ".ENV", ".Env.local",  # ASCII controls (green today)
    ".еnv",  # Cyrillic small ie
    ".ЕNV",  # Cyrillic capital IE
    ".ｅnv",  # fullwidth e
    ".\U0001d41env",  # mathematical bold e
    ".e​nv",  # ZWSP inside
    "​.env",  # leading Cf
    ".env‍",  # trailing Cf
    ".еnv.local",
]
ENV_ASCII_CONTROLS = {".env", ".ENV", ".Env.local"}  # enforced by today's hook
ENV_BLOCK_PARAMS = [
    pytest.param(n, id=ascii(n), marks=() if n in ENV_ASCII_CONTROLS else PART_B)
    for n in ENV_BLOCK
]
ENV_ALLOW = [".env.example", ".envrc_notes.md", "env.md", "dotenv.txt"]


@pytest.mark.parametrize("name", ENV_BLOCK_PARAMS)
def test_rejects_env_homoglyph(sandbox, name):
    _write(sandbox, f"cfg/{name}", "SECRET=1\n")
    _stage(sandbox, f"cfg/{name}")
    shown = f"cfg/{name}" if name.isascii() and name.isprintable() else "cfg/"
    _assert_refused(_run_hook(sandbox), name=shown, reason=REASON_ENV)


@pytest.mark.parametrize("name", ENV_ALLOW)
def test_allows_env_non_matches(sandbox, name):
    _write(sandbox, f"cfg/{name}", "x\n")
    _stage(sandbox, f"cfg/{name}")
    proc = _run_hook(sandbox)
    assert proc.returncode == 0, _err(proc)


# ==========================================================================
# 5. Wiring (F12): real `git commit` through the installed hooksPath
# ==========================================================================
def _install(repo: Path) -> None:
    subprocess.run(["bash", "scripts/install-hooks.sh"], cwd=repo, env=_env(), check=True,
                   capture_output=True, timeout=HOOK_TIMEOUT_S)


@PART_B
def test_installed_hook_blocks_real_commit(sandbox):
    _install(sandbox)
    _write(sandbox, "doc.md", "cd " + LEAK + "\n")
    _stage(sandbox, "doc.md")
    proc = _git(sandbox, "commit", "-q", "-m", "leak", check=False)
    assert proc.returncode != 0, "commit with a home path went through"
    assert _git(sandbox, "rev-parse", "--verify", "-q", "HEAD", check=False).returncode != 0, "a commit was created"


def test_installed_hook_allows_clean_commit(sandbox):
    """Positive control (green today)."""
    _install(sandbox)
    _write(sandbox, "doc.md", "clean\n")
    _stage(sandbox, ".gitignore", ".claude", ".githooks", "scripts", "doc.md")
    proc = _git(sandbox, "commit", "-q", "-m", "ok", check=False)
    assert proc.returncode == 0, _err(proc)


# ==========================================================================
# 6. CI: run the real gitignore-enforcement workflow steps
# ==========================================================================
_EXPR = re.compile(r"\$\{\{\s*(.*?)\s*\}\}")


def _resolve_expr(expr: str, ctx: dict) -> str:
    if expr == "github.event_name":
        return ctx["event"]
    if expr in ("github.base_ref", "github.head_ref"):
        return ""
    if expr == "github.workspace":
        return str(ctx["tree"])
    m = re.fullmatch(r"steps\.([\w-]+)\.outputs\.([\w-]+)", expr)
    if m:
        return ctx["outputs"].get(m.group(1), {}).get(m.group(2), "")
    raise AssertionError(f"workflow harness: unsupported expression {expr!r}")


def _eval_if(cond: str, ctx: dict) -> bool:
    cond = _EXPR.sub(lambda m: m.group(1), cond).strip()
    if cond in ("always()", "success()"):
        return True
    m = re.fullmatch(r"github\.event_name\s*(==|!=)\s*'([\w-]+)'", cond)
    if m:
        return (ctx["event"] == m.group(2)) == (m.group(1) == "==")
    raise AssertionError(f"workflow harness: unsupported if: {cond!r}")


def _parse_output_file(text: str) -> dict[str, str]:
    out, lines, i = {}, text.splitlines(), 0
    while i < len(lines):
        line = lines[i]
        if "<<" in line:
            key, delim = line.split("<<", 1)
            buf, i = [], i + 1
            while i < len(lines) and lines[i] != delim:
                buf.append(lines[i])
                i += 1
            out[key] = "\n".join(buf)
        elif "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
        i += 1
    return out


def _run_workflow(tree: Path, event: str = "push") -> tuple[bool, str]:
    wf = yaml.safe_load(WORKFLOW_FILE.read_text(encoding="utf-8"))
    ctx = {"event": event, "tree": tree, "outputs": {}}
    log = []
    ran = 0
    for job in wf["jobs"].values():
        for n, step in enumerate(job["steps"]):
            if "run" not in step:
                continue
            if "if" in step and not _eval_if(str(step["if"]), ctx):
                continue
            out_file = tree.parent / f"gh_output_{n}"
            out_file.write_text("")
            env = _env({"GITHUB_OUTPUT": str(out_file), "GITHUB_ACTIONS": "true", "CI": "true",
                        "GITHUB_EVENT_NAME": event, "GITHUB_WORKSPACE": str(tree)})
            for k, v in (step.get("env") or {}).items():
                env[k] = _EXPR.sub(lambda m: _resolve_expr(m.group(1), ctx), str(v))
            script = _EXPR.sub(lambda m: _resolve_expr(m.group(1), ctx), step["run"])
            proc = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", script],
                                  cwd=tree, env=env, capture_output=True, timeout=HOOK_TIMEOUT_S)
            ran += 1
            log.append(f"[{step.get('name')}] rc={proc.returncode}\n" + _err(proc))
            if "id" in step:
                ctx["outputs"][step["id"]] = _parse_output_file(out_file.read_text())
            if proc.returncode != 0:
                return False, "\n".join(log)
    assert ran > 0, "workflow harness ran no steps"
    return True, "\n".join(log)


def _ci_tree(tmp_path: Path, files: dict[str, bytes | str]) -> Path:
    tree = tmp_path / "tree"
    tree.mkdir()
    shutil.copy2(GITIGNORE_FILE, tree / ".gitignore")
    _copy_tracked(GOV_DIR, tree)
    _copy_tracked(SCRIPTS_DIR, tree)
    for rel, data in files.items():
        _write(tree, rel, data)
    _git(tree, "init", "-q")
    _git(tree, "add", "-f", "-A")
    _git(tree, "-c", "core.hooksPath=" + os.devnull, "commit", "-q", "-m", "t")
    return tree


def test_ci_clean_tree_passes(tmp_path):
    """Positive control (green today)."""
    ok, log = _run_workflow(_ci_tree(tmp_path, {"README.md": "hello\n"}))
    assert ok, log


@PART_B
def test_ci_rejects_home_path(tmp_path):
    ok, log = _run_workflow(_ci_tree(tmp_path, {"docs/guide.md": "cd " + LEAK + "\n"}))
    assert not ok, "workflow passed a tree containing a user-home path"
    assert LEAK not in log, "workflow log re-leaks the home path (F8)"


@PART_B
def test_ci_rejects_nested_pip_cache(tmp_path):
    ok, log = _run_workflow(_ci_tree(tmp_path, {"src/backend/.pip-cache/selfcheck/x": "{}\n"}))
    assert not ok, "workflow passed a tree with a nested .pip-cache/"


@PART_B
@pytest.mark.parametrize("name", [".\u0435nv", ".\uff45nv", ".e\u200bnv"], ids=["cyrillic", "fullwidth", "zwsp"])
def test_ci_rejects_env_homoglyph(tmp_path, name):
    ok, log = _run_workflow(_ci_tree(tmp_path, {f"cfg/{name}": "SECRET=1\n"}))
    assert not ok, f"workflow passed {ascii(name)}"


def test_ci_real_tree_passes(tmp_path):
    """Positive control (green today): no false positive on the real tree."""
    raw = subprocess.run(["git", "archive", "--format=tar", "HEAD"], cwd=REPO_ROOT,
                         capture_output=True, check=True).stdout
    tree = tmp_path / "tree"
    tree.mkdir()
    with tarfile.open(fileobj=io.BytesIO(raw)) as tf:
        tf.extractall(tree, filter="tar")
    _git(tree, "init", "-q")
    _git(tree, "add", "-f", "-A")
    _git(tree, "-c", "core.hooksPath=" + os.devnull, "commit", "-q", "-m", "t")
    ok, log = _run_workflow(tree)
    assert ok, log[-2000:]
