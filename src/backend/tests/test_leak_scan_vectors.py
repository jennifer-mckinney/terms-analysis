"""Contract tests for the normalising evidence leak matcher (issue #91, grumpy r5).

Grumpy round 5 triggered the whack-a-mole rule: encoded spellings of a local
path kept being added to one ERE as untested alternatives. The matcher
(scripts/governance/leak_scan.py) now decodes every line before matching a
short canonical pattern set (.claude/governance/evidence-leak-regex.txt), and
the vectors in .claude/governance/leak-vectors.tsv pin each pattern:

* every pattern has >= 1 block and >= 1 allow vector;
* every pattern is load-bearing: removing it un-blocks at least one of its
  own block vectors (in-process mutation check);
* every vector runs through all three entry points: the CI tree scan, the CI
  --range history scan and the .githooks/pre-commit hook.
"""
from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path
from types import ModuleType
from typing import Dict, List, NamedTuple

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_GOV = _REPO_ROOT / ".claude" / "governance"
_PATTERNS = _GOV / "evidence-leak-regex.txt"
_VECTORS = _GOV / "leak-vectors.tsv"
_MATCHER = _REPO_ROOT / "scripts" / "governance" / "leak_scan.py"
_SCANNER = _REPO_ROOT / "scripts" / "governance" / "scan-evidence-leaks.sh"
_HOOK = _REPO_ROOT / ".githooks" / "pre-commit"

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or shutil.which("bash") is None or shutil.which("python3") is None,
    reason="git, bash and python3 are required to exercise the leak scanners",
)


def _load_matcher() -> ModuleType:
    spec = importlib.util.spec_from_file_location("leak_scan", _MATCHER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


leak_scan = _load_matcher()


class Vector(NamedTuple):
    kind: str
    pattern: str
    sample: str
    note: str


def _vectors() -> List[Vector]:
    rows: List[Vector] = []
    for number, line in enumerate(_VECTORS.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        cols = line.split("\t")
        assert len(cols) == 4, f"leak-vectors.tsv:{number}: expected 4 TAB columns"
        rows.append(Vector(*cols))
    return rows


VECTORS = _vectors()
BLOCK = [v for v in VECTORS if v.kind == "block"]
ALLOW = [v for v in VECTORS if v.kind == "allow"]
PATTERNS = leak_scan.load_patterns(_PATTERNS)
PATTERN_NAMES = [name for name, _, _ in PATTERNS]


def _line(sample: str) -> str:
    """The sample as the matcher sees it: UTF-8 file bytes decoded as latin-1.

    #91 r8 (security F8): every real caller (CLI, tree, range, hook) feeds
    bytes through scan_bytes, so in-process checks use the same form.
    """
    return sample.encode("utf-8").decode("latin-1")


def _vid(v: Vector) -> str:
    return f"{v.kind}-{v.pattern}-{v.note[:40]}"


# ---------------------------------------------------------------------------
# Table contract
# ---------------------------------------------------------------------------


def test_vector_table_is_well_formed() -> None:
    assert {v.kind for v in VECTORS} <= {"block", "allow"}
    unknown = {v.pattern for v in VECTORS} - set(PATTERN_NAMES)
    assert not unknown, f"vectors name unknown patterns: {unknown}"
    assert len({v.sample for v in VECTORS}) == len(VECTORS), "duplicate samples"


@pytest.mark.parametrize("name", PATTERN_NAMES)
def test_every_pattern_has_block_and_allow_vectors(name: str) -> None:
    assert any(v.pattern == name for v in BLOCK), f"{name}: no block vector"
    assert any(v.pattern == name for v in ALLOW), f"{name}: no allow vector"


def test_encoded_and_case_variants_are_covered() -> None:
    # The grumpy-r5 classes must stay pinned: lower- and upper-case %2F,
    # JSON \/ and \u002f escapes, and an upper-case-only sample.
    samples = [v.sample for v in BLOCK]
    assert any("%2F" in s for s in samples)
    assert any("%2f" in s for s in samples)
    assert any("\\/" in s for s in samples)
    assert any("\\u002f" in s for s in samples)
    assert any(s.isupper() or "/USERS/" in s for s in samples)


@pytest.mark.parametrize("vector", BLOCK, ids=_vid)
def test_block_vector_is_reported_by_its_pattern(vector: Vector) -> None:
    assert vector.pattern in leak_scan.match_line(_line(vector.sample), PATTERNS), vector.note


@pytest.mark.parametrize("vector", ALLOW, ids=_vid)
def test_allow_vector_is_not_reported(vector: Vector) -> None:
    assert leak_scan.match_line(_line(vector.sample), PATTERNS) == [], vector.note


@pytest.mark.parametrize("name", PATTERN_NAMES)
def test_each_pattern_is_load_bearing(name: str) -> None:
    # Mutation check: drop the pattern and at least one of its own block
    # vectors must stop being reported. A pattern another one fully shadows
    # (or one whose vectors are all caught elsewhere) fails here.
    reduced = [p for p in PATTERNS if p[0] != name]
    escaped = [v for v in BLOCK if v.pattern == name and not leak_scan.match_line(_line(v.sample), reduced)]
    assert escaped, f"removing {name!r} changes nothing: add a vector only it catches"


def test_pattern_file_quoting_itself_is_allowed() -> None:
    # A review that pastes the whole SSoT (comments and patterns) is not a leak.
    assert leak_scan.scan_bytes(_PATTERNS.read_bytes(), PATTERNS) == []


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("%2FUsers%2Fbob", "/users/bob"),
        ("%2fusers%2fbob", "/users/bob"),
        ("%25252Fx", "/x"),  # three passes: %25252F -> %252F -> %2F -> /
        ("\\/Users\\/bob", "/users/bob"),
        ("\\\\/home", "/home"),  # double-escaped: \\/ -> \/ -> /
        ("\\u002Fhome", "/home"),
        ("\\x2Fhome", "/home"),
        ("C:\\Users\\nancy", "c:/users/nancy"),  # \n is not unescaped, then folded
        ("a\x00b", "ab"),
    ],
)
def test_normalise(raw: str, expected: str) -> None:
    assert leak_scan.normalise(raw) == expected


def test_normalise_stops_after_max_passes() -> None:
    # Bounded work per line: a fourth encoding layer is left encoded.
    assert leak_scan.MAX_PASSES == 3
    assert leak_scan.normalise("%2525252F") == "%2f"


def test_scan_bytes_reports_line_numbers_and_first_pattern() -> None:
    data = b"ok\n/Users/bob/x\n\x00clean\n~/Documents/a/\n"
    assert leak_scan.scan_bytes(data, PATTERNS) == [(2, "home-root"), (4, "home-private")]


# ---------------------------------------------------------------------------
# Matcher CLI: exit codes mirror grep (0 hit / 1 none / 2 error)
# ---------------------------------------------------------------------------


def _cli(*args: str, stdin: bytes = b"") -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python3", "-I", str(_MATCHER), *args], input=stdin, capture_output=True
    )


def test_cli_hit_none_and_stdin() -> None:
    hit = _cli(str(_PATTERNS), stdin=b"x\n%2FUsers%2Fbob\n")
    assert hit.returncode == 0
    assert hit.stdout.decode() == "2:home-root\n"
    assert _cli(str(_PATTERNS), "-", stdin=b"<repo>/x\n").returncode == 1


@pytest.mark.parametrize(
    "content,message",
    [
        ("", "no patterns"),
        ("# only a comment\n", "no patterns"),
        ("no-tab-here\n", "expected"),
        ("a\t/x/\na\t/y/\n", "duplicate"),
        ("a\t/Users/\n", "lower case"),
        ("a\t(unclosed\n", "bad regex"),
    ],
)
def test_cli_rejects_malformed_pattern_file(tmp_path: Path, content: str, message: str) -> None:
    bad = tmp_path / "patterns.txt"
    bad.write_text(content, encoding="utf-8")
    result = _cli(str(bad), stdin=b"/Users/bob/x\n")
    assert result.returncode == 2
    assert message in result.stderr.decode()


def test_cli_usage_and_unreadable_input_are_errors(tmp_path: Path) -> None:
    assert _cli().returncode == 2
    assert _cli(str(tmp_path / "missing.txt")).returncode == 2
    assert _cli(str(_PATTERNS), str(tmp_path / "missing-input")).returncode == 2


# ---------------------------------------------------------------------------
# Every vector through the three real entry points
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)


def _vector_files() -> Dict[str, bytes]:
    return {f"docs/evidence/v{i:03d}.txt": f"{v.sample}\n".encode() for i, v in enumerate(VECTORS)}


def _checkout(tmp_path: Path, files: Dict[str, bytes]) -> Path:
    root = tmp_path / "checkout"
    (root / ".claude" / "governance").mkdir(parents=True)
    shutil.copy2(_PATTERNS, root / ".claude" / "governance" / "evidence-leak-regex.txt")
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return root


def _expected_leaks() -> set:
    return {f"docs/evidence/v{i:03d}.txt" for i, v in enumerate(VECTORS) if v.kind == "block"}


def test_tree_scan_runs_every_vector(tmp_path: Path) -> None:
    root = _checkout(tmp_path, _vector_files())
    result = subprocess.run(["bash", str(_SCANNER), str(root)], capture_output=True, text=True)
    assert result.returncode == 1
    leaked = set(re.findall(r"^LEAK: (\S+) line", result.stderr, flags=re.M))
    assert leaked == _expected_leaks()
    assert f"{len(BLOCK)} of {len(VECTORS)} evidence file(s)" in result.stderr


def test_range_scan_runs_every_vector(tmp_path: Path) -> None:
    root = _checkout(tmp_path, {})
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "README").write_text("base\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "tag", "base")
    for rel, content in _vector_files().items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "vectors")
    result = subprocess.run(
        ["bash", str(_SCANNER), "--range", "base..HEAD", str(root)], capture_output=True, text=True
    )
    assert result.returncode == 1
    assert f"{len(BLOCK)} added line(s) in base..HEAD" in result.stderr


def _hook_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    (root / ".githooks").mkdir()
    shutil.copy2(_HOOK, root / ".githooks" / "pre-commit")
    (root / ".claude" / "governance").mkdir(parents=True)
    shutil.copy2(_GOV / "required-gitignore.txt", root / ".claude" / "governance" / "required-gitignore.txt")
    shutil.copy2(_PATTERNS, root / ".claude" / "governance" / "evidence-leak-regex.txt")
    (root / "scripts" / "governance").mkdir(parents=True)
    shutil.copy2(_MATCHER, root / "scripts" / "governance" / "leak_scan.py")
    shutil.copy2(_REPO_ROOT / ".gitignore", root / ".gitignore")
    return root


def _stage_and_hook(root: Path, files: Dict[str, bytes], env: Dict[str, str] = None) -> subprocess.CompletedProcess:
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        _git(root, "add", "-f", "--", rel)
    return subprocess.run(
        ["bash", str(root / ".githooks" / "pre-commit")],
        cwd=root,
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
    )


@pytest.mark.parametrize("vector", BLOCK, ids=_vid)
def test_precommit_blocks_every_block_vector(tmp_path: Path, vector: Vector) -> None:
    result = _stage_and_hook(_hook_repo(tmp_path), {"docs/evidence/v.txt": f"ok\n{vector.sample}\n".encode()})
    assert result.returncode == 1, vector.note
    assert "line(s) 2" in result.stderr
    assert vector.pattern in result.stderr


def test_precommit_allows_every_allow_vector(tmp_path: Path) -> None:
    files = {f"docs/evidence/a{i:03d}.txt": f"{v.sample}\n".encode() for i, v in enumerate(ALLOW)}
    result = _stage_and_hook(_hook_repo(tmp_path), files)
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# Fail closed when the shared matcher or its interpreter is unavailable
# ---------------------------------------------------------------------------


def test_precommit_missing_matcher_fails_closed(tmp_path: Path) -> None:
    root = _hook_repo(tmp_path)
    (root / "scripts" / "governance" / "leak_scan.py").unlink()
    result = _stage_and_hook(root, {"docs/evidence/a.txt": b"clean\n"})
    assert result.returncode == 1
    assert "matcher missing" in result.stderr


def test_precommit_missing_python_fails_closed(tmp_path: Path) -> None:
    result = _stage_and_hook(
        _hook_repo(tmp_path), {"docs/evidence/a.txt": b"clean\n"}, {"LEAK_SCAN_PYTHON": "no-such-python-xyz"}
    )
    assert result.returncode == 1
    assert "not found" in result.stderr


def test_precommit_malformed_pattern_file_fails_closed(tmp_path: Path) -> None:
    root = _hook_repo(tmp_path)
    (root / ".claude" / "governance" / "evidence-leak-regex.txt").write_text("broken\n", encoding="utf-8")
    result = _stage_and_hook(root, {"docs/evidence/a.txt": b"clean\n"})
    assert result.returncode == 1
    assert "matcher exit 2" in result.stderr


def test_scanner_missing_python_is_error(tmp_path: Path) -> None:
    root = _checkout(tmp_path, {"docs/evidence/a.txt": b"ok\n"})
    result = subprocess.run(
        ["bash", str(_SCANNER), str(root)],
        capture_output=True,
        text=True,
        env={**os.environ, "LEAK_SCAN_PYTHON": "no-such-python-xyz"},
    )
    assert result.returncode == 2
    assert "not found" in result.stderr


def test_scanner_malformed_pattern_file_is_error_even_with_nothing_to_scan(tmp_path: Path) -> None:
    root = _checkout(tmp_path, {})
    (root / ".claude" / "governance" / "evidence-leak-regex.txt").write_text("broken\n", encoding="utf-8")
    result = subprocess.run(["bash", str(_SCANNER), str(root)], capture_output=True, text=True)
    assert result.returncode == 2
    assert "invalid pattern SSoT" in result.stderr


# ---------------------------------------------------------------------------
# Fail closed on ANY unexpected error (#91 security r6)
#
# Python exits 1 on an uncaught exception, and 1 means "no leak" to every
# caller. The matcher therefore maps every internal error to exit 2, and the
# callers accept exit 1 only together with the "CLEAN <n>" sentinel.
# ---------------------------------------------------------------------------

_DEEP_PATTERN = "deep\t" + "(" * 2000 + "a" + ")" * 2000 + "\n"
_LEAK = b"ok\n/Users/someuser/secret\n"


def _deep_pattern_file(root: Path) -> None:
    (root / ".claude" / "governance" / "evidence-leak-regex.txt").write_text(_DEEP_PATTERN, encoding="utf-8")


def _memoryerror_python(tmp_path: Path) -> str:
    # Stand-in for LEAK_SCAN_PYTHON: runs the REAL matcher's main() in a real
    # process, with scan_bytes patched to raise MemoryError mid-scan.
    wrapper = tmp_path / "python-memoryerror"
    wrapper.write_text(
        "#!/usr/bin/env bash\n"
        "# args: -I <matcher> <patterns> [input]\n"
        'shift; matcher="$1"; shift\n'
        'exec python3 -I -c \'import importlib.util, sys\n'
        'spec = importlib.util.spec_from_file_location("leak_scan", sys.argv[1])\n'
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "def boom(*a, **k): raise MemoryError()\n"
        "m.scan_bytes = boom\n"
        'sys.exit(m.main(sys.argv[2:]))\' "$matcher" "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    return str(wrapper)


def _silent_exit1_python(tmp_path: Path) -> str:
    # An interpreter that dies with exit 1 before main() (syntax error, failed
    # import): no hits, no sentinel. Must never read as "no leak".
    wrapper = tmp_path / "python-exit1"
    wrapper.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    wrapper.chmod(0o755)
    return str(wrapper)


def test_cli_clean_scan_prints_sentinel() -> None:
    result = _cli(str(_PATTERNS), stdin=b"a\nb\n")
    assert result.returncode == 1
    assert result.stdout.decode() == "CLEAN 3\n"


def test_cli_hit_prints_no_sentinel() -> None:
    assert "CLEAN" not in _cli(str(_PATTERNS), stdin=_LEAK).stdout.decode()


def test_load_patterns_maps_recursion_error_to_value_error(tmp_path: Path) -> None:
    deep = tmp_path / "deep.txt"
    deep.write_text(_DEEP_PATTERN, encoding="utf-8")
    with pytest.raises(ValueError, match="bad regex"):
        leak_scan.load_patterns(deep)


def test_cli_deeply_nested_pattern_file_is_error(tmp_path: Path) -> None:
    deep = tmp_path / "deep.txt"
    deep.write_text(_DEEP_PATTERN, encoding="utf-8")
    result = _cli(str(deep), stdin=_LEAK)
    assert result.returncode == 2, result.stderr
    assert "bad regex" in result.stderr.decode()


@pytest.mark.parametrize("error", [MemoryError, RecursionError, RuntimeError, KeyError])
def test_main_unexpected_error_is_exit_2(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, error: type) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise error("simulated")

    monkeypatch.setattr(leak_scan, "scan_bytes", boom)
    assert leak_scan.main([str(_PATTERNS), str(_PATTERNS)]) == 2
    captured = capsys.readouterr()
    assert "internal error" in captured.err
    assert "CLEAN" not in captured.out


def test_main_unexpected_error_in_pattern_loading_is_exit_2(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_path: Path) -> None:
        raise MemoryError()

    monkeypatch.setattr(leak_scan, "load_patterns", boom)
    assert leak_scan.main([str(_PATTERNS), str(_PATTERNS)]) == 2


def test_scanner_deeply_nested_pattern_file_is_error(tmp_path: Path) -> None:
    root = _checkout(tmp_path, {"docs/evidence/leak.md": _LEAK})
    _deep_pattern_file(root)
    result = subprocess.run(["bash", str(_SCANNER), str(root)], capture_output=True, text=True)
    assert result.returncode == 2, result.stdout
    assert "invalid pattern SSoT" in result.stderr
    assert "no local machine paths" not in result.stdout


def test_scanner_range_deeply_nested_pattern_file_is_error(tmp_path: Path) -> None:
    root = _checkout(tmp_path, {})
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "README").write_text("base\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    _deep_pattern_file(root)
    result = subprocess.run(["bash", str(_SCANNER), "--range", "HEAD", str(root)], capture_output=True, text=True)
    assert result.returncode == 2, result.stdout


def test_precommit_deeply_nested_pattern_file_fails_closed(tmp_path: Path) -> None:
    root = _hook_repo(tmp_path)
    _deep_pattern_file(root)
    result = _stage_and_hook(root, {"docs/evidence/leak.md": _LEAK})
    assert result.returncode == 1
    assert "matcher exit 2" in result.stderr


def test_scanner_memoryerror_during_scan_is_error(tmp_path: Path) -> None:
    root = _checkout(tmp_path, {"docs/evidence/leak.md": _LEAK})
    env = {**os.environ, "LEAK_SCAN_PYTHON": _memoryerror_python(tmp_path)}
    result = subprocess.run(["bash", str(_SCANNER), str(root)], capture_output=True, text=True, env=env)
    assert result.returncode == 2, result.stdout
    assert "matcher exit 2" in result.stderr
    assert "internal error: MemoryError" in result.stderr


def test_precommit_memoryerror_during_scan_fails_closed(tmp_path: Path) -> None:
    result = _stage_and_hook(
        _hook_repo(tmp_path),
        {"docs/evidence/leak.md": _LEAK},
        {"LEAK_SCAN_PYTHON": _memoryerror_python(tmp_path)},
    )
    assert result.returncode == 1
    assert "matcher exit 2" in result.stderr
    assert "internal error: MemoryError" in result.stderr


def test_scanner_exit1_without_sentinel_is_error(tmp_path: Path) -> None:
    root = _checkout(tmp_path, {"docs/evidence/leak.md": _LEAK})
    env = {**os.environ, "LEAK_SCAN_PYTHON": _silent_exit1_python(tmp_path)}
    result = subprocess.run(["bash", str(_SCANNER), str(root)], capture_output=True, text=True, env=env)
    assert result.returncode == 2
    assert "invalid pattern SSoT" in result.stderr


def test_precommit_exit1_without_sentinel_fails_closed(tmp_path: Path) -> None:
    result = _stage_and_hook(
        _hook_repo(tmp_path), {"docs/evidence/leak.md": _LEAK}, {"LEAK_SCAN_PYTHON": _silent_exit1_python(tmp_path)}
    )
    assert result.returncode == 1
    assert "no clean attestation" in result.stderr


# ---------------------------------------------------------------------------
# Per-file (tree) and per-range sentinel checks (#91 grumpy r7 finding 2)
#
# The interpreters above all fail at the empty-stdin SSoT self-test, so they
# never reach the per-file check in tree mode or the range check. This one
# passes the self-test with the real matcher, then dies silently (exit 1, no
# sentinel) on real input, exactly like a crash before main() would.
# ---------------------------------------------------------------------------


def _exit1_after_selftest_python(tmp_path: Path) -> str:
    wrapper = tmp_path / "python-exit1-late"
    wrapper.write_text(
        "#!/usr/bin/env bash\n"
        "# args: -I <matcher> <patterns> [input]; tree mode passes a file path.\n"
        "# #91 r8: the path-name scan runs first and must still pass, so only\n"
        "# an input holding the leaked content dies silently (exit 1).\n"
        'if [[ "$#" -eq 4 && "$4" != "-" ]]; then\n'
        '    grep -q secret "$4" && exit 1\n'
        '    exec python3 "$@"\n'
        "fi\n"
        'data="$(cat)"; [[ "$data" == *secret* ]] && exit 1\n'
        'printf "%s\\n" "$data" | exec python3 "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    return str(wrapper)


def test_tree_scan_exit1_without_sentinel_after_selftest_is_error(tmp_path: Path) -> None:
    root = _checkout(tmp_path, {"docs/evidence/leak.md": _LEAK})
    env = {**os.environ, "LEAK_SCAN_PYTHON": _exit1_after_selftest_python(tmp_path)}
    result = subprocess.run(["bash", str(_SCANNER), str(root)], capture_output=True, text=True, env=env)
    assert result.returncode == 2, result.stdout
    assert "scan failed for" in result.stderr
    assert "no clean attestation" in result.stderr
    assert "no local machine paths" not in result.stdout


def test_range_scan_exit1_without_sentinel_after_selftest_is_error(tmp_path: Path) -> None:
    root = _checkout(tmp_path, {})
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "docs" / "evidence").mkdir(parents=True)
    (root / "docs" / "evidence" / "leak.md").write_bytes(_LEAK)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "leak")
    env = {**os.environ, "LEAK_SCAN_PYTHON": _exit1_after_selftest_python(tmp_path)}
    result = subprocess.run(
        ["bash", str(_SCANNER), "--range", "HEAD", str(root)], capture_output=True, text=True, env=env
    )
    assert result.returncode == 2, result.stdout
    assert "history scan failed" in result.stderr
    assert "no clean attestation" in result.stderr
    assert "no local machine paths" not in result.stdout


# ---------------------------------------------------------------------------
# Path-name scan sentinel checks (#91 grumpy r9 finding 1)
#
# This interpreter passes the self-test and every content input with the
# real matcher, and dies silently (exit 1, no sentinel) only on the NAMES
# list (a file whose lines are docs/evidence/ paths). That reaches the
# "path name scan failed" branch in scan_names and in the hook.
# ---------------------------------------------------------------------------


def _exit1_on_names_python(tmp_path: Path) -> str:
    wrapper = tmp_path / "python-exit1-names"
    wrapper.write_text(
        "#!/usr/bin/env bash\n"
        "# args: -I <matcher> <patterns> [input]; the names list is a file path.\n"
        'if [[ "$#" -eq 4 && "$4" != "-" ]] && grep -q \'^docs/evidence/\' "$4"; then exit 1; fi\n'
        'exec python3 "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    return str(wrapper)


def test_tree_scan_name_scan_without_sentinel_is_error(tmp_path: Path) -> None:
    root = _checkout(tmp_path, {"docs/evidence/a.md": b"<repo>/clean\n"})
    env = {**os.environ, "LEAK_SCAN_PYTHON": _exit1_on_names_python(tmp_path)}
    result = subprocess.run(["bash", str(_SCANNER), str(root)], capture_output=True, text=True, env=env)
    assert result.returncode == 2, result.stdout
    assert "path name scan failed (matcher exit 1, no clean attestation)" in result.stderr
    assert "no local machine paths" not in result.stdout


def test_range_scan_name_scan_without_sentinel_is_error(tmp_path: Path) -> None:
    root = _range_repo(tmp_path)
    (root / "docs" / "evidence").mkdir(parents=True)
    (root / "docs" / "evidence" / "a.md").write_bytes(b"<repo>/clean\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "clean")
    env = {**os.environ, "LEAK_SCAN_PYTHON": _exit1_on_names_python(tmp_path)}
    result = subprocess.run(
        ["bash", str(_SCANNER), "--range", "base..HEAD", str(root)], capture_output=True, text=True, env=env
    )
    assert result.returncode == 2, result.stdout
    assert "path name scan failed (matcher exit 1, no clean attestation)" in result.stderr
    assert "history scan failed" not in result.stderr  # the content stream passed
    assert "no local machine paths" not in result.stdout


def test_precommit_name_scan_without_sentinel_fails_closed(tmp_path: Path) -> None:
    result = _stage_and_hook(
        _hook_repo(tmp_path),
        {"docs/evidence/a.md": b"<repo>/clean\n"},
        {"LEAK_SCAN_PYTHON": _exit1_on_names_python(tmp_path)},
    )
    assert result.returncode == 1, result.stderr
    assert "evidence path name scan failed (matcher exit 1, no clean attestation)" in result.stderr
    assert "evidence path scan failed for" not in result.stderr  # the content scan passed


# ---------------------------------------------------------------------------
# Scanner I/O fault injection (#91 grumpy r9 finding 2): find, the range
# name listing (git --name-only, tr) and readlink. Each fault must be exit 2,
# never a clean pass. PATH shims wrap the real tool and fail only the one
# call under test; the tests' own git calls use the real PATH.
# ---------------------------------------------------------------------------


def _shim_env(tmp_path: Path, tool: str, body: str) -> Dict[str, str]:
    real = shutil.which(tool)
    assert real is not None, tool
    shims = tmp_path / "shims"
    shims.mkdir(exist_ok=True)
    shim = shims / tool
    shim.write_text(f"#!/usr/bin/env bash\nREAL={real!r}\n{body}\nexec \"$REAL\" \"$@\"\n", encoding="utf-8")
    shim.chmod(0o755)
    return {**os.environ, "PATH": f"{shims}{os.pathsep}{os.environ['PATH']}"}


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores directory modes")
def test_tree_scan_unlistable_directory_is_error(tmp_path: Path) -> None:
    root = _checkout(tmp_path, {"docs/evidence/ok.md": b"ok\n", "docs/evidence/sub/hidden.md": b"ok\n"})
    sub = root / "docs" / "evidence" / "sub"
    sub.chmod(0o000)
    try:
        result = subprocess.run(["bash", str(_SCANNER), str(root)], capture_output=True, text=True)
    finally:
        sub.chmod(0o755)
    assert result.returncode == 2, result.stdout
    assert "could not list" in result.stderr
    assert "no local machine paths" not in result.stdout


def _clean_range_repo(tmp_path: Path) -> Path:
    root = _range_repo(tmp_path)
    (root / "docs" / "evidence").mkdir(parents=True)
    (root / "docs" / "evidence" / "a.md").write_bytes(b"ok\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "clean")
    return root


def test_range_scan_name_listing_git_failure_is_error(tmp_path: Path) -> None:
    root = _clean_range_repo(tmp_path)
    # Only the --name-only listing fails; the content git log runs for real.
    env = _shim_env(tmp_path, "git", 'for a in "$@"; do [[ "$a" == --name-only ]] && exit 128; done')
    result = subprocess.run(
        ["bash", str(_SCANNER), "--range", "base..HEAD", str(root)], capture_output=True, text=True, env=env
    )
    assert result.returncode == 2, result.stdout
    assert "git log --name-only failed for range base..HEAD" in result.stderr
    assert "no local machine paths" not in result.stdout


def test_range_scan_name_listing_tr_failure_is_error(tmp_path: Path) -> None:
    root = _clean_range_repo(tmp_path)
    # Only the NUL-to-newline translation of the listing fails ("tr -d" passes).
    env = _shim_env(tmp_path, "tr", "[[ \"$#\" -eq 2 && \"$1\" == '\\000' && \"$2\" == '\\n' ]] && exit 1")
    result = subprocess.run(
        ["bash", str(_SCANNER), "--range", "base..HEAD", str(root)], capture_output=True, text=True, env=env
    )
    assert result.returncode == 2, result.stdout
    assert "could not read the name listing for base..HEAD" in result.stderr
    assert "no local machine paths" not in result.stdout


def test_tree_scan_readlink_failure_is_error(tmp_path: Path) -> None:
    root = _checkout(tmp_path, {"docs/evidence/ok.txt": b"ok\n"})
    (root / "docs" / "evidence" / "link.txt").symlink_to("ok.txt")
    env = _shim_env(tmp_path, "readlink", "exit 1")
    result = subprocess.run(["bash", str(_SCANNER), str(root)], capture_output=True, text=True, env=env)
    assert result.returncode == 2, result.stdout
    assert "could not read link" in result.stderr
    assert "no local machine paths" not in result.stdout


# ---------------------------------------------------------------------------
# "absolute-path" context (#91 r7)
# ---------------------------------------------------------------------------


def test_unknown_context_in_pattern_file_is_error(tmp_path: Path) -> None:
    bad = tmp_path / "patterns.txt"
    bad.write_text("a\t/x/\tno-such-context\n", encoding="utf-8")
    result = _cli(str(bad), stdin=b"/x/\n")
    assert result.returncode == 2
    assert "unknown context" in result.stderr.decode()


def test_absolute_path_context_offset_outside_any_run_fails_closed() -> None:
    # Defensive branch: an offset on a hard delimiter is not in any run and
    # must count as a leak, never as "relative path".
    # ";" is always hard (#91 r8: "=" between path characters no longer is).
    runs = leak_scan.CONTEXTS["absolute-path"]("a;b")
    assert runs.is_leak(1) is True
    assert runs.is_leak(0) is False


def test_context_reports_a_leak_after_an_exempt_hit_on_the_same_line() -> None:
    line = "https://github.com/users/someuser/projects/7 and /Users/someuser/x"
    assert leak_scan.match_line(line, PATTERNS) == ["home-root"]
    assert leak_scan.match_line("api/users/7 then api/home/8", PATTERNS) == []


@pytest.mark.parametrize(
    "line",
    [
        "/a" * 50000,
        "a/home/b" * 10000,
        " /home/" * 10000,
        "https://example.com" + "/home/x" * 10000,
        "-a" * 50000 + "-users",
        "--users" * 10000,
    ],
)
def test_matcher_is_linear_on_long_lines(line: str) -> None:
    import time

    start = time.perf_counter()
    leak_scan.match_line(line, PATTERNS)
    assert time.perf_counter() - start < 2.0


# ---------------------------------------------------------------------------
# #91 r8: private TLD contract, opaque containers, path names, symlinks and
# type changes, CI trigger for card branches.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tld", sorted(leak_scan._PRIVATE_TLDS))
def test_every_private_tld_has_a_block_vector(tld: str) -> None:
    # Contract: each special-use / private TLD that loses the public-URL
    # exemption is pinned by a block vector, so removing it from the set
    # turns that vector green-to-red in test_block_vector_is_reported...
    hosts = [re.match(r"https?://([^/:]+)", v.sample) for v in BLOCK]
    assert any(h and h.group(1).endswith(f".{tld}") for h in hosts), tld


def test_private_tld_set_is_load_bearing(monkeypatch: pytest.MonkeyPatch) -> None:
    # In-process mutation: with an empty set every private-TLD block vector
    # would be exempt again (proves the set, not something else, blocks them).
    monkeypatch.setattr(leak_scan, "_PRIVATE_TLDS", frozenset())
    sample = _line("http://devbox.local/Users/someuser/x")
    assert leak_scan.match_line(sample, PATTERNS) == []


def _zip(members: Dict[str, bytes], method: int) -> bytes:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=method) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _container_samples() -> Dict[str, bytes]:
    """One real payload per CONTAINER_SIGNATURES entry, each hiding a leak."""
    import bz2
    import gzip
    import lzma
    import zipfile

    leak = b"see /Users/someuser/Documents/proj/app.py\n" * 4
    docx = _zip({"[Content_Types].xml": b"<Types/>", "word/document.xml": b"<w:t>" + leak + b"</w:t>"}, zipfile.ZIP_DEFLATED)
    return {
        "zip": docx,  # a deflated .docx (security F1 probe)
        "zip-empty": _zip({}, zipfile.ZIP_STORED),
        "zip-spanned": b"PK\x07\x08" + docx,
        "gzip": gzip.compress(leak),
        "bzip2": bz2.compress(leak),
        "xz": lzma.compress(leak),
        "zstd": b"\x28\xb5\x2f\xfd\x04\x00" + bytes(range(1, 64)),
        "7z": b"7z\xbc\xaf\x27\x1c\x00\x04" + bytes(range(1, 64)),
        "pdf": b"%PDF-1.7\n1 0 obj << /Filter /FlateDecode /Length 9 >> stream\nx\x9c\x03\x00\nendstream\n",
    }


CONTAINERS = _container_samples()

# Near misses: text that mentions a signature but is not a container.
CONTAINER_NEAR_MISSES = [
    b"the zip header is PK\\x03\\x04 (escaped, prose)\n",
    b"BZh9 starts a bzip2 stream\n",
    b"BZh91AY&S is one byte short\n",
    b"%PDF is the PDF magic\n",
    b"%PDF-x.y is a template\n",
    b"  %PDF-1.7 indented, not at a line start\n",
    b"7z archives are opaque\n",
]


def test_every_container_signature_has_a_sample() -> None:
    assert set(CONTAINERS) == set(leak_scan.CONTAINER_SIGNATURES)
    for name, data in CONTAINERS.items():
        assert data.replace(b"\x00", b"").startswith(leak_scan.CONTAINER_SIGNATURES[name]), name


@pytest.mark.parametrize("name", sorted(CONTAINERS))
def test_container_is_refused_as_opaque_by_the_cli(name: str) -> None:
    result = _cli(str(_PATTERNS), "-", stdin=CONTAINERS[name])
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[0] == f"1:{leak_scan.OPAQUE_CONTAINER}".encode()
    assert b"CLEAN" not in result.stdout


def test_stored_zip_is_refused_too() -> None:
    # Before r8 a STORED zip was caught by its plain-text member, a deflated
    # one was not; now both are refused before decoding is even attempted.
    import zipfile

    data = _zip({"a.txt": b"<repo>/clean\n"}, zipfile.ZIP_STORED)
    assert leak_scan.scan_bytes(data, PATTERNS)[0] == (1, leak_scan.OPAQUE_CONTAINER)


@pytest.mark.parametrize("line", CONTAINER_NEAR_MISSES)
def test_container_near_miss_is_text(line: bytes) -> None:
    assert leak_scan.scan_bytes(line, PATTERNS) == []


def test_tree_scan_refuses_every_container(tmp_path: Path) -> None:
    files = {f"docs/evidence/c-{name}.bin": data for name, data in CONTAINERS.items()}
    files["docs/evidence/near-miss.txt"] = b"".join(CONTAINER_NEAR_MISSES)
    root = _checkout(tmp_path, files)
    result = subprocess.run(["bash", str(_SCANNER), str(root)], capture_output=True, text=True)
    assert result.returncode == 1
    leaked = set(re.findall(r"^LEAK: (\S+) line", result.stderr, flags=re.M))
    assert leaked == {f"docs/evidence/c-{name}.bin" for name in CONTAINERS}


def test_range_scan_refuses_every_container(tmp_path: Path) -> None:
    root = _checkout(tmp_path, {})
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "README").write_text("base\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "tag", "base")
    (root / "docs" / "evidence").mkdir(parents=True)
    for name, data in CONTAINERS.items():
        (root / "docs" / "evidence" / f"c-{name}.bin").write_bytes(data)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "containers")
    result = subprocess.run(
        ["bash", str(_SCANNER), "--range", "base..HEAD", str(root)], capture_output=True, text=True
    )
    assert result.returncode == 1, result.stdout
    labelled = set(re.findall(r"^LEAK \(history\): \S+ (\S+)$", result.stderr, flags=re.M))
    assert labelled == {f"docs/evidence/c-{name}.bin" for name in CONTAINERS}


@pytest.mark.parametrize("name", ["zip", "gzip", "pdf"])
def test_precommit_refuses_container(tmp_path: Path, name: str) -> None:
    result = _stage_and_hook(_hook_repo(tmp_path), {f"docs/evidence/report.{name}": CONTAINERS[name]})
    assert result.returncode == 1, result.stderr
    assert leak_scan.OPAQUE_CONTAINER in result.stderr


def test_precommit_allows_container_near_misses(tmp_path: Path) -> None:
    result = _stage_and_hook(_hook_repo(tmp_path), {"docs/evidence/n.txt": b"".join(CONTAINER_NEAR_MISSES)})
    assert result.returncode == 0, result.stderr


# Path names (security F4): clean content, leaky NAME.
_LEAKY_NAMES = [
    "docs/evidence/-Users-someuser-Documents-proj/s.md",  # dashed project slug dir
    "docs/evidence/pytest-of-émile/run.txt",  # non-ASCII name, -z listing
    "docs/evidence/.claude/worktrees/agent-af11/x.md",
]


@pytest.mark.parametrize("rel", _LEAKY_NAMES)
def test_tree_scan_reports_leaky_path_name(tmp_path: Path, rel: str) -> None:
    root = _checkout(tmp_path, {rel: b"<repo>/clean\n"})
    result = subprocess.run(["bash", str(_SCANNER), str(root)], capture_output=True, text=True)
    assert result.returncode == 1, result.stdout
    assert f"LEAK (name): {rel}" in result.stderr
    assert "path name(s) under docs/evidence/ contain a local machine path" in result.stderr
    assert not re.search(r"^LEAK: ", result.stderr, flags=re.M)  # content is clean


def test_tree_scan_names_are_relative_to_the_checkout(tmp_path: Path) -> None:
    # The checkout itself lives under a leaky-looking parent; only names
    # BELOW the repo root are matched, so this clean tree passes.
    parent = tmp_path / "pytest-of-someuser" / "-Users-someuser-x"
    parent.mkdir(parents=True)
    root = _checkout(parent, {"docs/evidence/a/b.txt": b"<repo>/clean\n"})
    result = subprocess.run(["bash", str(_SCANNER), str(root)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "scanned 1 file(s) and 2 path name(s), no local machine paths" in result.stdout


@pytest.mark.parametrize("rel", _LEAKY_NAMES)
def test_precommit_refuses_leaky_path_name(tmp_path: Path, rel: str) -> None:
    result = _stage_and_hook(_hook_repo(tmp_path), {rel: b"<repo>/clean\n"})
    assert result.returncode == 1, result.stderr
    assert "Refusing to stage path name(s)" in result.stderr
    assert rel in result.stderr


def _range_repo(tmp_path: Path) -> Path:
    root = _checkout(tmp_path, {})
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "README").write_text("base\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "tag", "base")
    return root


def _range(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(_SCANNER), "--range", "base..HEAD", str(root)], capture_output=True, text=True)


@pytest.mark.parametrize("rel", _LEAKY_NAMES)
def test_range_scan_reports_leaky_path_name(tmp_path: Path, rel: str) -> None:
    root = _range_repo(tmp_path)
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"<repo>/clean\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "name")
    result = _range(root)
    assert result.returncode == 1, result.stdout
    assert f"LEAK (history name): {rel}" in result.stderr


def test_range_scan_clean_names_reports_name_count(tmp_path: Path) -> None:
    root = _range_repo(tmp_path)
    (root / "docs" / "evidence").mkdir(parents=True)
    (root / "docs" / "evidence" / "a.txt").write_bytes(b"ok\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "a")
    (root / "docs" / "evidence" / "a.txt").unlink()
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "delete")
    result = _range(root)
    assert result.returncode == 0, result.stderr
    # The deletion is not listed again (--diff-filter=d): one name, once.
    assert "1 added line(s), 1 path name(s), no local machine paths" in result.stdout


_LINK_TARGET = "/Users/someuser/Documents/secret.txt"


def test_tree_scan_scans_symlink_target(tmp_path: Path) -> None:
    root = _checkout(tmp_path, {"docs/evidence/ok.txt": b"ok\n"})
    (root / "docs" / "evidence" / "link.txt").symlink_to(_LINK_TARGET)  # dangling on purpose
    result = subprocess.run(["bash", str(_SCANNER), str(root)], capture_output=True, text=True)
    assert result.returncode == 1, result.stdout
    assert "LEAK: docs/evidence/link.txt line(s) 1" in result.stderr
    assert "1 of 2 evidence file(s)" in result.stderr


def test_tree_scan_clean_symlink_is_counted_and_passes(tmp_path: Path) -> None:
    root = _checkout(tmp_path, {"docs/evidence/ok.txt": b"ok\n"})
    (root / "docs" / "evidence" / "link.txt").symlink_to("ok.txt")
    result = subprocess.run(["bash", str(_SCANNER), str(root)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "scanned 2 file(s)" in result.stdout


def test_precommit_refuses_file_replaced_by_symlink_type_change(tmp_path: Path) -> None:
    # Grumpy 5 / security F5: a tracked file turned into a symlink is staged
    # as "T", which the old ACMR filter dropped.
    root = _hook_repo(tmp_path)
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "commit.gpgsign", "false")
    target = root / "docs" / "evidence" / "a.md"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"ok\n")
    _git(root, "add", "-f", "--", "docs/evidence/a.md")
    _git(root, "commit", "-q", "--no-verify", "-m", "base")
    target.unlink()
    target.symlink_to(_LINK_TARGET)
    _git(root, "add", "-f", "--", "docs/evidence/a.md")
    status = _git(root, "diff", "--cached", "--name-status").stdout
    assert status.startswith("T\t"), status
    result = subprocess.run(["bash", str(root / ".githooks" / "pre-commit")], cwd=root, capture_output=True, text=True)
    assert result.returncode == 1, result.stderr
    assert "Refusing to stage docs/evidence/a.md" in result.stderr


def test_precommit_refuses_new_symlink(tmp_path: Path) -> None:
    root = _hook_repo(tmp_path)
    link = root / "docs" / "evidence" / "l.md"
    link.parent.mkdir(parents=True)
    link.symlink_to(_LINK_TARGET)
    _git(root, "add", "-f", "--", "docs/evidence/l.md")
    result = subprocess.run(["bash", str(root / ".githooks" / "pre-commit")], cwd=root, capture_output=True, text=True)
    assert result.returncode == 1, result.stderr
    assert "home-root" in result.stderr


def test_range_scan_catches_symlink_type_change(tmp_path: Path) -> None:
    root = _range_repo(tmp_path)
    target = root / "docs" / "evidence" / "a.md"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"ok\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "file")
    target.unlink()
    target.symlink_to(_LINK_TARGET)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "symlink")
    result = _range(root)
    assert result.returncode == 1, result.stdout
    assert "docs/evidence/a.md" in result.stderr


def test_ci_push_trigger_covers_card_branches() -> None:
    # Security F12: the trigger cannot be exercised locally, so pin the exact
    # branch filters (PyYAML 1.1 reads the "on" key as True).
    import yaml

    ci = yaml.safe_load((_REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    on = ci.get("on", ci.get(True))
    assert on["push"]["branches"] == ["main", "claude/**", "feat/**"]
    assert "evidence-scan" in ci["jobs"]


# ---------------------------------------------------------------------------
# #192 lift, design gate section 4 (N1-N5): the hook is wired through
# core.hooksPath on a REAL git commit (QUALITY-BAR R4 / DEV-FUNDAMENTALS F12),
# in a linked worktree too (#175 failure class), option-like file names are
# not misparsed (attack sketch T7), the pattern loader is pinned for CRLF and
# BOM files (attack sketch T3), and the tracked evidence corpus is clean (R2).
# ---------------------------------------------------------------------------

# A block vector without encoded bytes, so its file content is plain ASCII.
_WIRING_VECTOR = next(v for v in BLOCK if v.sample.isascii())


def _wired_repo(tmp_path: Path) -> Path:
    """_hook_repo with core.hooksPath set and its guard files committed.

    The base commit goes through the real hook, so the hook's mode bit and the
    hooksPath wiring are exercised before any evidence is staged.
    """
    root = _hook_repo(tmp_path)
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "commit.gpgsign", "false")
    _git(root, "config", "core.hooksPath", ".githooks")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    return root


def _git_commit(checkout: Path, files: Dict[str, bytes]) -> subprocess.CompletedProcess:
    """Stage files and run a real `git commit` (no direct hook invocation)."""
    for rel, content in files.items():
        target = checkout / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        _git(checkout, "add", "-f", "--", rel)
    return subprocess.run(
        ["git", "commit", "-q", "-m", "evidence"], cwd=checkout, capture_output=True, text=True
    )


def _head(checkout: Path) -> str:
    return _git(checkout, "rev-parse", "HEAD").stdout.strip()


def _linked_worktree(root: Path) -> Path:
    worktree = root.parent / "linked"
    _git(root, "worktree", "add", "-q", "-b", "probe-worktree", str(worktree))
    return worktree


@pytest.mark.parametrize("where", ["main-checkout", "linked-worktree"])
def test_hookspath_commit_refuses_leaking_evidence(tmp_path: Path, where: str) -> None:
    # N1 / N2: git itself must invoke check 4; a hook that is present but not
    # wired (mode bit, hooksPath, worktree toplevel) would let this commit in.
    root = _wired_repo(tmp_path)
    checkout = root if where == "main-checkout" else _linked_worktree(root)
    before = _head(checkout)
    result = _git_commit(checkout, {"docs/evidence/run.txt": f"ok\n{_WIRING_VECTOR.sample}\n".encode()})
    assert result.returncode == 1, result.stderr
    assert "Refusing to stage docs/evidence/run.txt" in result.stderr
    assert _WIRING_VECTOR.pattern in result.stderr
    assert "line(s) 2" in result.stderr
    assert _head(checkout) == before, "a refused commit must not move HEAD"


@pytest.mark.parametrize("where", ["main-checkout", "linked-worktree"])
def test_hookspath_commit_accepts_clean_evidence(tmp_path: Path, where: str) -> None:
    # N1 / N2 positive control: clean evidence commits through the same wiring.
    root = _wired_repo(tmp_path)
    checkout = root if where == "main-checkout" else _linked_worktree(root)
    before = _head(checkout)
    files = {f"docs/evidence/a{i:03d}.txt": f"{v.sample}\n".encode() for i, v in enumerate(ALLOW)}
    result = _git_commit(checkout, files)
    assert result.returncode == 0, result.stderr
    assert _head(checkout) != before
    committed = _git(checkout, "ls-tree", "-r", "--name-only", "HEAD", "--", "docs/evidence").stdout.split()
    assert sorted(committed) == sorted(files)


_OPTION_LIKE_NAMES = ["docs/evidence/-n.md", "docs/evidence/--help.md"]


def test_hookspath_commit_accepts_option_like_names(tmp_path: Path) -> None:
    # N3 (attack sketch T7): names that look like options to echo, printf or
    # a CLI must be read as names, scanned, and committed when clean.
    root = _wired_repo(tmp_path)
    result = _git_commit(root, {rel: b"<repo>/clean\n" for rel in _OPTION_LIKE_NAMES})
    assert result.returncode == 0, result.stderr
    committed = _git(root, "ls-tree", "-r", "--name-only", "HEAD", "--", "docs/evidence").stdout.split()
    assert sorted(committed) == sorted(_OPTION_LIKE_NAMES)


@pytest.mark.parametrize("rel", _OPTION_LIKE_NAMES)
def test_hookspath_commit_scans_option_like_names(tmp_path: Path, rel: str) -> None:
    # N3 negative: the same names with leaking content are refused and named
    # verbatim, so the file was scanned rather than skipped or misparsed.
    root = _wired_repo(tmp_path)
    before = _head(root)
    result = _git_commit(root, {rel: f"{_WIRING_VECTOR.sample}\n".encode()})
    assert result.returncode == 1, result.stderr
    assert f"Refusing to stage {rel}:" in result.stderr
    assert _WIRING_VECTOR.pattern in result.stderr
    assert _head(root) == before


def _pattern_bytes(encoding: str) -> bytes:
    raw = _PATTERNS.read_bytes()
    if encoding == "crlf":
        return raw.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    if encoding == "bom":
        return b"\xef\xbb\xbf" + raw
    raise AssertionError(encoding)


def _vector_stdin() -> bytes:
    return "".join(f"{v.sample}\n" for v in VECTORS).encode()


def test_cli_crlf_pattern_file_reports_every_vector_like_lf(tmp_path: Path) -> None:
    # N4 (attack sketch T3): the grep-based predecessor went blind on a CRLF
    # pattern file. Every block vector must be reported by its own pattern
    # and every allow vector must stay silent, exactly as with the LF file.
    crlf = tmp_path / "patterns-crlf.txt"
    crlf.write_bytes(_pattern_bytes("crlf"))
    assert b"\r\n" in crlf.read_bytes()
    lf_out = _cli(str(_PATTERNS), stdin=_vector_stdin())
    crlf_out = _cli(str(crlf), stdin=_vector_stdin())
    assert crlf_out.returncode == lf_out.returncode == 0, crlf_out.stderr
    assert crlf_out.stdout == lf_out.stdout
    reported = {int(n) for n, _ in (row.split(":", 1) for row in crlf_out.stdout.decode().splitlines())}
    expected = {i for i, v in enumerate(VECTORS, 1) if v.kind == "block"}
    assert reported == expected


def test_precommit_crlf_pattern_file_still_refuses(tmp_path: Path) -> None:
    root = _hook_repo(tmp_path)
    (root / ".claude" / "governance" / "evidence-leak-regex.txt").write_bytes(_pattern_bytes("crlf"))
    result = _stage_and_hook(root, {"docs/evidence/v.txt": f"ok\n{_WIRING_VECTOR.sample}\n".encode()})
    assert result.returncode == 1, result.stderr
    assert _WIRING_VECTOR.pattern in result.stderr
    assert "line(s) 2" in result.stderr


def test_scanner_crlf_pattern_file_still_reports_every_vector(tmp_path: Path) -> None:
    root = _checkout(tmp_path, _vector_files())
    (root / ".claude" / "governance" / "evidence-leak-regex.txt").write_bytes(_pattern_bytes("crlf"))
    result = subprocess.run(["bash", str(_SCANNER), str(root)], capture_output=True, text=True)
    assert result.returncode == 1, result.stderr
    leaked = set(re.findall(r"^LEAK: (\S+) line", result.stderr, flags=re.M))
    assert leaked == _expected_leaks()


def test_cli_bom_pattern_file_is_a_config_error(tmp_path: Path) -> None:
    # N4: a UTF-8 BOM glues itself to the first line; the loader must refuse
    # the file (exit 2, honest message), never load a partial set.
    bom = tmp_path / "patterns-bom.txt"
    bom.write_bytes(_pattern_bytes("bom"))
    result = _cli(str(bom), stdin=f"{_WIRING_VECTOR.sample}\n".encode())
    assert result.returncode == 2
    assert result.stdout == b""
    # fix r1: the generic Cf check now owns this case; it names line 1 and U+FEFF.
    err = result.stderr.decode()
    assert ":1:" in err
    assert "U+FEFF" in err


def test_precommit_bom_pattern_file_fails_closed(tmp_path: Path) -> None:
    root = _hook_repo(tmp_path)
    (root / ".claude" / "governance" / "evidence-leak-regex.txt").write_bytes(_pattern_bytes("bom"))
    result = _stage_and_hook(root, {"docs/evidence/a.txt": b"clean\n"})
    assert result.returncode == 1
    assert "evidence path scan failed for docs/evidence/a.txt (matcher exit 2" in result.stderr


def test_scanner_bom_pattern_file_fails_self_test(tmp_path: Path) -> None:
    root = _checkout(tmp_path, {"docs/evidence/a.txt": b"clean\n"})
    (root / ".claude" / "governance" / "evidence-leak-regex.txt").write_bytes(_pattern_bytes("bom"))
    result = subprocess.run(["bash", str(_SCANNER), str(root)], capture_output=True, text=True)
    assert result.returncode == 2
    assert "invalid pattern SSoT" in result.stderr
    assert "(matcher exit 2)" in result.stderr


# #192 fix r2 (lead ruling, grumpy r2 LOW 1/2 + security N1): the loader accepts
# ONLY printable ASCII (0x20-0x7E) plus TAB on every line (patterns, names and
# comments alike). Any other code point fails closed (exit 2); the message names
# the line and the literal "U+XXXX" and never echoes the character. The old
# Cf-only deny-list missed NBSP, U+3000, U+3164, combining marks, private-use
# and unassigned code points, DEL, NUL and the C0 controls (probe: a regex
# column starting with U+00A0 loads and silently disables the pattern).
# label -> (character, literal token expected in the message). The token is a
# literal on purpose: it must not be derived from ord() by the test.
_BAD_CHARS = {
    # Cf (the r1 set; already red-then-green, kept as regression)
    "bom": ("\ufeff", "U+FEFF"),
    "zwsp": ("\u200b", "U+200B"),
    "lrm": ("\u200e", "U+200E"),
    "word-joiner": ("\u2060", "U+2060"),
    "soft-hyphen": ("\u00ad", "U+00AD"),
    "rlo": ("\u202e", "U+202E"),
    "tag-a": ("\U000e0041", "U+E0041"),
    # not Cf: red today
    "del": ("\x7f", "U+007F"),
    "nul": ("\x00", "U+0000"),
    "c0-soh": ("\x01", "U+0001"),
    "c0-esc": ("\x1b", "U+001B"),
    "c0-vt": ("\x0b", "U+000B"),
    "c0-ff": ("\x0c", "U+000C"),
    "c0-fs": ("\x1c", "U+001C"),
    "c1-nel": ("\x85", "U+0085"),
    "line-sep": ("\u2028", "U+2028"),
    "nbsp": ("\u00a0", "U+00A0"),
    "ideographic-space": ("\u3000", "U+3000"),
    "combining-acute": ("\u0301", "U+0301"),
    "private-use": ("\ue000", "U+E000"),
    "unassigned": ("\u0378", "U+0378"),
    "hangul-filler": ("\u3164", "U+3164"),
    "e-acute": ("\u00e9", "U+00E9"),
}
# Positions inside the first real pattern line (name TAB regex TAB context),
# plus a comment line inserted above it.
_BAD_POSITIONS = ("name", "regex-start", "regex-middle", "regex-end", "comment")


def _bad_pattern_bytes(position: str, char: str) -> "tuple[bytes, int]":
    text = _PATTERNS.read_text(encoding="utf-8").split("\n")
    index = next(i for i, ln in enumerate(text) if ln.strip() and not ln.lstrip().startswith("#"))
    if position == "comment":
        text.insert(index, "# plain note " + char + " tail")
        return "\n".join(text).encode("utf-8"), index + 1
    cols = text[index].split("\t")
    name, regex = cols[0], cols[1]
    if position == "name":
        cols[0] = name[:1] + char + name[1:]
    elif position == "regex-start":
        cols[1] = char + regex
    elif position == "regex-middle":
        cols[1] = regex[: len(regex) // 2] + char + regex[len(regex) // 2 :]
    else:
        cols[1] = regex + char
    text[index] = "\t".join(cols)
    return "\n".join(text).encode("utf-8"), index + 1


def test_bad_char_table_has_the_required_classes() -> None:
    cats = {unicodedata.category(c) for c, _ in _BAD_CHARS.values()}
    assert {"Cf", "Cc", "Zs", "Zl", "Mn", "Co", "Cn", "Lo", "Ll"} <= cats
    for char, token in _BAD_CHARS.values():
        assert token == f"U+{ord(char):04X}"  # table self-check only


@pytest.mark.parametrize("position", _BAD_POSITIONS)
@pytest.mark.parametrize("label", sorted(_BAD_CHARS))
def test_cli_non_ascii_or_control_char_in_pattern_file_is_a_config_error(
    tmp_path: Path, label: str, position: str
) -> None:
    char, token = _BAD_CHARS[label]
    data, line_no = _bad_pattern_bytes(position, char)
    cfg = tmp_path / "patterns-bad.txt"
    cfg.write_bytes(data)
    # Input the unmutated home-root pattern flags; a silent accept scans CLEAN.
    result = _cli(str(cfg), stdin=b"/Users/someone/x\n")
    assert result.returncode == 2, (result.returncode, result.stdout)
    assert result.stdout == b""
    err = result.stderr.decode("utf-8", "replace")
    assert f":{line_no}:" in err
    # Message honesty and output safety: the literal code point, never the raw char.
    assert token in err
    assert char.encode("utf-8") not in result.stderr


@pytest.mark.parametrize("position", ("regex-start", "comment"))
@pytest.mark.parametrize("label", ("bom", "nbsp", "del", "private-use"))
def test_precommit_bad_char_in_pattern_file_fails_closed(tmp_path: Path, label: str, position: str) -> None:
    root = _hook_repo(tmp_path)
    data, _ = _bad_pattern_bytes(position, _BAD_CHARS[label][0])
    (root / ".claude" / "governance" / "evidence-leak-regex.txt").write_bytes(data)
    result = _stage_and_hook(root, {"docs/evidence/a.txt": b"clean\n"})
    assert result.returncode == 1
    assert "evidence path scan failed for docs/evidence/a.txt (matcher exit 2" in result.stderr


@pytest.mark.parametrize("position", ("regex-start", "comment"))
@pytest.mark.parametrize("label", ("bom", "nbsp", "del", "private-use"))
def test_scanner_bad_char_in_pattern_file_fails_self_test(tmp_path: Path, label: str, position: str) -> None:
    root = _checkout(tmp_path, {"docs/evidence/a.txt": b"clean\n"})
    data, _ = _bad_pattern_bytes(position, _BAD_CHARS[label][0])
    (root / ".claude" / "governance" / "evidence-leak-regex.txt").write_bytes(data)
    result = subprocess.run(["bash", str(_SCANNER), str(root)], capture_output=True, text=True)
    assert result.returncode == 2
    assert "invalid pattern SSoT" in result.stderr
    assert "(matcher exit 2)" in result.stderr


def test_cli_tag_a_and_nbsp_messages_carry_the_literal_code_point(tmp_path: Path) -> None:
    # Grumpy r2 LOW 2: literal strings, not a formatted ord().
    for char, literal in (("\U000e0041", "U+E0041"), ("\u00a0", "U+00A0")):
        data, _ = _bad_pattern_bytes("regex-start", char)
        cfg = tmp_path / "p.txt"
        cfg.write_bytes(data)
        err = _cli(str(cfg), stdin=b"x\n").stderr.decode("utf-8", "replace")
        assert literal in err


def test_cli_printable_ascii_comment_and_tab_columns_still_load(tmp_path: Path) -> None:
    # Positive control: the full printable range 0x20-0x7E in a comment, and the
    # TAB-separated shipped lines, stay accepted and behave like the original.
    printable = "".join(chr(c) for c in range(0x20, 0x7F))
    text = _PATTERNS.read_text(encoding="utf-8").split("\n")
    index = next(i for i, ln in enumerate(text) if ln.strip() and not ln.lstrip().startswith("#"))
    text.insert(index, "# " + printable)
    cfg = tmp_path / "patterns-ok.txt"
    cfg.write_bytes("\n".join(text).encode("utf-8"))
    stdin = b"/Users/someone/x\n"
    mutated = _cli(str(cfg), stdin=stdin)
    original = _cli(str(_PATTERNS), stdin=stdin)
    assert mutated.returncode == original.returncode == 0, (mutated.stderr, original.stderr)
    assert mutated.stdout == original.stdout != b""


# #192 fix r1 (security F1, scoped to the evidence-scan job; repo-wide pinning
# stays on #197): every `uses:` there is pinned to a full 40-hex commit SHA.
_SHA_PINNED = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@[0-9a-f]{40}")


@pytest.mark.parametrize(
    "ref,ok",
    [
        ("actions/checkout@" + "a" * 40, True),
        ("actions/checkout@v4", False),
        ("actions/checkout@main", False),
        ("actions/checkout@" + "a" * 39, False),
        ("actions/checkout@" + "A" * 40, False),
        ("actions/checkout@" + "a" * 41, False),
        ("actions/checkout", False),
    ],
)
def test_sha_pin_matcher_has_positive_and_negative_cases(ref: str, ok: bool) -> None:
    assert bool(_SHA_PINNED.fullmatch(ref)) is ok


def test_evidence_scan_job_actions_are_pinned_to_full_shas() -> None:
    import yaml

    ci = yaml.safe_load((_REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    uses = [step["uses"] for step in ci["jobs"]["evidence-scan"]["steps"] if "uses" in step]
    assert uses, "evidence-scan has no `uses:` steps: the pin check would attest nothing"
    unpinned = [u for u in uses if not _SHA_PINNED.fullmatch(u)]
    assert unpinned == []


def test_tracked_evidence_corpus_is_clean() -> None:
    # N5 (QUALITY-BAR R2 benign corpus): every TRACKED evidence blob and every
    # tracked evidence path name scans CLEAN through the CLI. Unlike the tree
    # scan (find), untracked local files cannot make this red or green.
    listing = subprocess.run(
        ["git", "ls-files", "-z", "--", "docs/evidence/"], cwd=_REPO_ROOT, capture_output=True, check=True
    ).stdout
    paths = [p.decode() for p in listing.split(b"\0") if p]
    assert paths, "no tracked evidence files: the corpus check would attest nothing"
    leaking = []
    for rel in paths:
        blob = subprocess.run(["git", "show", f":{rel}"], cwd=_REPO_ROOT, capture_output=True, check=True).stdout
        result = _cli(str(_PATTERNS), stdin=blob.replace(b"\0", b""))
        if result.returncode != 1 or not re.fullmatch(rb"CLEAN \d+\n", result.stdout):
            leaking.append((rel, result.returncode))
    assert leaking == []
    # No trailing newline: the matcher counts split(b"\n") segments.
    names = _cli(str(_PATTERNS), stdin="\n".join(paths).encode())
    assert names.returncode == 1, names.stdout
    assert names.stdout == f"CLEAN {len(paths)}\n".encode()
