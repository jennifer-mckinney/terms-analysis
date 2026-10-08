"""Acceptance tests for terms-analysis #145 (folds #78).

Card: strip absolute user-home path leaks from the tracked tree, block them
in `.githooks/pre-commit` and in the gitignore-enforcement workflow, stop
graveyard directories (e.g. `.pip-cache/`) from being staged at any depth,
and close the Unicode homoglyph bypass of the `.env` guard.

Behaviour over text: every hook case runs the real `.githooks/pre-commit`
inside a throwaway git repo, and every CI case runs the real `run:` steps of
`.github/workflows/gitignore-enforcement.yml` against a throwaway tree.

F13: the home-path patterns come from
`.claude/governance/personal-path-patterns.txt` and the graveyard directories
from `.claude/governance/required-gitignore.txt`. Nothing here restates them.
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


def _home_patterns() -> list[re.Pattern[str]]:
    assert PATTERNS_FILE.is_file(), (
        f"home-path pattern SSoT missing: {PATTERNS_FILE.relative_to(REPO_ROOT)}"
    )
    lines = _load_ssot_lines(PATTERNS_FILE)
    assert lines, "home-path pattern SSoT has no patterns"
    return [re.compile(p) for p in lines]


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


LEAK = home()  # the canonical hostile value used across hook cases

BLOCK_VECTORS = [
    "cd " + home() + "\n",
    "cd " + home("home", "bob") + "\n",
    "file://" + home(),
    '"' + home("Users", "Alice") + '"',
    "[doc](" + home("Users", "j.doe") + ")",
    "`" + home("home", "a_b-1") + "`",
    "PATH=" + home("Users", "9z"),
    "/" + "Users" + "/​alice/x",  # Cf right after the slash
    "/" + "Us​ers" + "/alice/x",  # Cf inside the root
    "/" + "home" + "/‮bob/x",  # bidi override
]

ALLOW_VECTORS = [
    "/" + "Users" + "/<name>/x",
    "/" + "home" + "/<user>/x",
    "$HOME/.claude/CLAUDE.md",
    "~/.claude/CLAUDE.md",
    "https://api.github.com/users/alice",
    "the /" + "Users" + "/ directory",
    "Users/alice (relative, no root)",
]


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


def _assert_refused(proc: subprocess.CompletedProcess, *, names: list[str] = ()) -> None:
    out = _err(proc)
    assert proc.returncode == REFUSED, f"expected refusal rc={REFUSED}, got {proc.returncode}: {out[-600:]!r}"
    for n in names:
        assert n in out, f"refusal does not name {n!r}"
    # F8: the message must not re-leak the home path it is refusing.
    assert LEAK not in out and _strip_cf(LEAK) not in _strip_cf(out)


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
    patterns = _home_patterns()
    offenders = []
    for mode, rel in _tracked_entries():
        p = REPO_ROOT / rel
        if mode == "120000":
            text = os.readlink(p)
        elif p.is_file():
            text = p.read_bytes().decode("utf-8", "replace")
        else:
            continue
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


def test_pattern_config_vectors_contract():
    """R2/rule 9: every pattern has a block vector; no pattern hits an allow vector."""
    patterns = _home_patterns()
    for p in patterns:
        assert any(p.search(_strip_cf(v)) for v in BLOCK_VECTORS), f"pattern {p.pattern!r} has no block vector"
    for v in BLOCK_VECTORS:
        assert _leaks(v, patterns), f"block vector not detected: {v!r}"
    for v in ALLOW_VECTORS:
        assert not _leaks(v, patterns), f"allow vector falsely detected: {v!r}"


# ==========================================================================
# 2. Hook: home-path content check
# ==========================================================================
def test_rejects_staged_personal_path(sandbox):
    _write(sandbox, "doc.md", "cd " + LEAK + "\n")
    _stage(sandbox, "doc.md")
    _assert_refused(_run_hook(sandbox), names=["doc.md"])


def test_allows_policy_placeholder(sandbox):
    for i, v in enumerate(ALLOW_VECTORS):
        _write(sandbox, f"ok{i}.md", v + "\n")
    _stage(sandbox, *[f"ok{i}.md" for i in range(len(ALLOW_VECTORS))])
    proc = _run_hook(sandbox)
    assert proc.returncode == 0, _err(proc)


@pytest.mark.parametrize("idx", range(len(BLOCK_VECTORS)))
def test_rejects_block_vector(sandbox, idx):
    _write(sandbox, "v.md", BLOCK_VECTORS[idx])
    _stage(sandbox, "v.md")
    proc = _run_hook(sandbox)
    assert proc.returncode == REFUSED, f"vector {BLOCK_VECTORS[idx]!r} passed: {_err(proc)!r}"


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


@pytest.mark.parametrize("quotepath", ["true", "false"])
@pytest.mark.parametrize("name", HOSTILE_NAMES, ids=[repr(n) for n in HOSTILE_NAMES])
def test_hostile_filename_with_leak_refused(sandbox, name, quotepath):
    _write(sandbox, name, "cd " + LEAK + "\n")
    _stage(sandbox, name)
    proc = _run_hook(sandbox, {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.quotePath",
                               "GIT_CONFIG_VALUE_0": quotepath})
    _assert_refused(proc)
    out = _err(proc)
    assert "\x1b" not in out and "‮" not in out, "raw control bytes from filename echoed"


@pytest.mark.parametrize("name", HOSTILE_NAMES, ids=[repr(n) for n in HOSTILE_NAMES])
def test_hostile_filename_clean_allowed(sandbox, name):
    """Positive control: hostile names with clean content are not refused."""
    _write(sandbox, name, "nothing personal\n")
    _stage(sandbox, name)
    proc = _run_hook(sandbox)
    assert proc.returncode == 0, _err(proc)


def test_scans_index_not_worktree(sandbox):
    """F7: the staged blob is what gets committed; scan that, not the worktree."""
    _write(sandbox, "doc.md", "cd " + LEAK + "\n")
    _stage(sandbox, "doc.md")
    _write(sandbox, "doc.md", "clean now\n")
    _assert_refused(_run_hook(sandbox), names=["doc.md"])


def test_dirty_worktree_clean_index_allowed(sandbox):
    _write(sandbox, "doc.md", "clean\n")
    _stage(sandbox, "doc.md")
    _write(sandbox, "doc.md", "cd " + LEAK + "\n")
    proc = _run_hook(sandbox)
    assert proc.returncode == 0, _err(proc)


def test_symlink_to_home_path_refused(sandbox):
    os.symlink(home("Users", "alice", "/secret"), sandbox / "link")
    _stage(sandbox, "link")
    _assert_refused(_run_hook(sandbox), names=["link"])


def test_huge_single_line_leak_refused(sandbox):
    _write(sandbox, "big.txt", b"a" * (2 * 1024 * 1024) + LEAK.encode())
    _stage(sandbox, "big.txt")
    _assert_refused(_run_hook(sandbox), names=["big.txt"])


def test_many_files_one_leak_refused(sandbox):
    n = 3000
    for i in range(n):
        _write(sandbox, f"many/f{i:05d}.md", "clean\n")
    _write(sandbox, f"many/f{n - 1:05d}.md", LEAK)
    _stage(sandbox, "many")
    _assert_refused(_run_hook(sandbox), names=[f"f{n - 1:05d}.md"])


def test_clean_commit_reports_count(sandbox):
    """F12/R4: success carries an attestation (the number of files scanned)."""
    n = 7
    for i in range(n):
        _write(sandbox, f"c{i}.md", "clean\n")
    _stage(sandbox, *[f"c{i}.md" for i in range(n)])
    proc = _run_hook(sandbox)
    assert proc.returncode == 0, _err(proc)
    assert re.search(rf"(?<!\d){n}(?!\d)", _err(proc)), f"no scan count in output: {_err(proc)!r}"


# --- config fail-closed (F13) ---------------------------------------------
PATTERNS_REL = PATTERNS_FILE.relative_to(REPO_ROOT)


def _clean_stage(repo: Path) -> None:
    _write(repo, "c.md", "clean\n")
    _stage(repo, "c.md")


def test_missing_pattern_config_fails_closed(sandbox):
    (sandbox / PATTERNS_REL).unlink()
    _clean_stage(sandbox)
    proc = _run_hook(sandbox)
    assert proc.returncode == REFUSED
    out = _err(proc)
    assert PATTERNS_FILE.name in out
    assert str(sandbox) not in out and str(sandbox.resolve()) not in out, "absolute path in message (F8)"


@pytest.mark.parametrize("body", ["", "# only comments\n\n", "([\n"], ids=["empty", "comments", "bad-regex"])
def test_bad_pattern_config_fails_closed(sandbox, body):
    (sandbox / PATTERNS_REL).write_text(body, encoding="utf-8")
    _clean_stage(sandbox)
    proc = _run_hook(sandbox)
    assert proc.returncode == REFUSED, f"bad config {body!r} accepted: {_err(proc)!r}"


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
def test_rejects_pip_cache(sandbox):
    _write(sandbox, "src/backend/.pip-cache/selfcheck/x", "{}\n")
    _stage(sandbox, "src/backend/.pip-cache/selfcheck/x")
    _assert_refused(_run_hook(sandbox), names=[".pip-cache"])


@pytest.mark.parametrize("d", _graveyard_dirs())
def test_rejects_nested_graveyard_dir(sandbox, d):
    rel = f"src/backend/{d}x.txt"
    _write(sandbox, rel, "x\n")
    _stage(sandbox, rel)
    _assert_refused(_run_hook(sandbox))


@pytest.mark.parametrize("d", _graveyard_dirs())
def test_allows_graveyard_lookalike_name(sandbox, d):
    """Negative: a directory merely containing the name is not a graveyard dir."""
    rel = f"src/backend/{d.rstrip('/')}_notes/x.txt"
    _write(sandbox, rel, "x\n")
    _stage(sandbox, rel)
    proc = _run_hook(sandbox)
    assert proc.returncode == 0, _err(proc)


def test_root_pip_cache_still_refused(sandbox):
    """Control: green today."""
    _write(sandbox, ".pip-cache/x", "x\n")
    _stage(sandbox, ".pip-cache/x")
    _assert_refused(_run_hook(sandbox))


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
ENV_ALLOW = [".env.example", ".envrc_notes.md", "env.md", "dotenv.txt"]


@pytest.mark.parametrize("name", ENV_BLOCK, ids=[ascii(n) for n in ENV_BLOCK])
def test_rejects_env_homoglyph(sandbox, name):
    _write(sandbox, f"cfg/{name}", "SECRET=1\n")
    _stage(sandbox, f"cfg/{name}")
    proc = _run_hook(sandbox)
    assert proc.returncode == REFUSED, f"{ascii(name)} accepted: {_err(proc)!r}"


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


def test_ci_rejects_home_path(tmp_path):
    ok, log = _run_workflow(_ci_tree(tmp_path, {"docs/guide.md": "cd " + LEAK + "\n"}))
    assert not ok, "workflow passed a tree containing a user-home path"
    assert LEAK not in log, "workflow log re-leaks the home path (F8)"


def test_ci_rejects_nested_pip_cache(tmp_path):
    ok, log = _run_workflow(_ci_tree(tmp_path, {"src/backend/.pip-cache/selfcheck/x": "{}\n"}))
    assert not ok, "workflow passed a tree with a nested .pip-cache/"


@pytest.mark.parametrize("name", [".еnv", ".ｅnv", ".e​nv"], ids=["cyrillic", "fullwidth", "zwsp"])
def test_ci_rejects_env_homoglyph(tmp_path, name):
    ok, log = _run_workflow(_ci_tree(tmp_path, {f"cfg/{name}": "SECRET=1\n"}))
    assert not ok, f"workflow passed {ascii(name)}"


def test_ci_real_tree_passes(tmp_path):
    """Positive control: the workflow must not false-positive on the real tree."""
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
