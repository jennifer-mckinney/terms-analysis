"""Acceptance tests for terms-analysis #156 (G1-8, plan A5): one roadmap.

The BRD "Implementation Roadmap" section is the single roadmap. `docs/TODO.md`
is either deleted or demoted to a dated sprint list that links the roadmap.
Both outcomes are accepted here; which one ships is the coder's call.

Behaviour over text: every case runs the real
`scripts/governance/check-roadmap-ssot.sh` against a throwaway git repo in
tmp_path, then asserts the exit code, the exact set of `FAIL [<id>]` lines and
the message content. `test_real_repo_*` runs it against this checkout, which
is red until the BRD has a checked roadmap box and TODO.md is resolved.

No config value is restated (F13): paths, heading, keyword, caps and the
threshold are read from `.claude/governance/roadmap-ssot.conf`, the file the
script reads, and overridden explicitly through that file where a case needs
another value. Pinned here are only the script's output contract (exit codes,
condition ids, sentinel prefixes) and the config file's location.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "governance" / "check-roadmap-ssot.sh"
CONFIG_REL = ".claude/governance/roadmap-ssot.conf"

# Output contract of check-roadmap-ssot.sh (its header documents these).
EXIT_OK, EXIT_VIOLATION, EXIT_ERROR = 0, 1, 2
OK_PREFIX = "ROADMAP-SSOT OK:"
FAIL_SUMMARY = "ROADMAP-SSOT FAIL: {n} violation(s)"
ERROR_PREFIX = "ROADMAP-SSOT ERROR [{ident}]:"
VIOLATION_IDS = (
    "todo-file",
    "todo-sprint-heading",
    "todo-roadmap-link",
    "brd-file",
    "brd-roadmap-section",
    "brd-roadmap-checked",
    "stray-todo-reference",
)
FAIL_LINE_RE = re.compile(r"^FAIL \[([a-z-]+)\]: ", re.MULTILINE)
HARNESS_TIMEOUT_S = 60  # harness bound per script run, not product config
FAKE_GIT_SLEEP_FACTOR = 5  # fake git sleeps this many times the configured timeout

# Hostile characters: every line-break code point Python or Unicode knows of,
# beyond the three CommonMark line endings (CR LF, CR, LF).
UNICODE_LINE_BREAKS = ("\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029")


# --------------------------------------------------------------------------
# config: read the same file the script reads
# --------------------------------------------------------------------------
def read_config_text() -> str:
    return (REPO_ROOT / CONFIG_REL).read_text(encoding="ascii")


def parse_config(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.split("\n"):
        if line.strip() and not line.startswith("#"):
            key, _, value = line.partition("=")
            values[key] = value
    return values


CFG = parse_config(read_config_text())
TODO_REL: str = CFG["todo_path"]
BRD_REL: str = CFG["brd_path"]
HEADING: str = CFG["roadmap_heading"]
HEADING_LEVEL = len(HEADING) - len(HEADING.lstrip("#"))
KEYWORD: str = CFG["sprint_keyword"]
SCOPE: list[str] = CFG["reference_scope"].split(" ")
MIN_CHECKED = int(CFG["min_checked_boxes"])


def github_anchor(heading: str) -> str:
    """GitHub's heading slug (test oracle): lower-case, drop punctuation, '-'."""
    text = heading.lstrip("#").strip().lower()
    return re.sub(r"[^a-z0-9 _-]", "", text).replace(" ", "-")


ANCHOR = github_anchor(HEADING)
LINK_TARGET = os.path.relpath(BRD_REL, os.path.dirname(TODO_REL) or ".") + "#" + ANCHOR
SPRINT_HEADING = f"# {KEYWORD} 2026-10-12 to 2026-10-26"


def config_with(**overrides: str) -> str:
    """The real config text with some values replaced (keys must exist)."""
    lines = read_config_text().split("\n")
    seen: set[str] = set()
    for index, line in enumerate(lines):
        key = line.partition("=")[0]
        if key in overrides and not line.startswith("#"):
            lines[index] = f"{key}={overrides[key]}"
            seen.add(key)
    assert seen == set(overrides), f"unknown config keys: {set(overrides) - seen}"
    return "\n".join(lines)


# --------------------------------------------------------------------------
# document builders
# --------------------------------------------------------------------------
def brd(checked: int = MIN_CHECKED, unchecked: int = 2, *, before: str = "", inside: str = "",
        after: str = "", heading: str = HEADING) -> str:
    """A BRD whose roadmap section holds the given task boxes."""
    sub = "#" * (HEADING_LEVEL + 1)
    boxes = [f"- [x] shipped item {i}" for i in range(checked)]
    boxes += [f"- [ ] planned item {i}" for i in range(unchecked)]
    sibling = "#" * HEADING_LEVEL
    return "\n".join([
        "# Business Requirements",
        "",
        f"{sibling} Executive Summary",
        "",
        before,
        "",
        heading,
        "",
        f"{sub} Phase 1",
        "",
        *boxes,
        "",
        inside,
        "",
        f"{sibling} Financial Projections",
        "",
        after,
        "",
    ])


def sprint_todo(heading: str = SPRINT_HEADING, link: str | None = None, body: str = "") -> str:
    """A demoted TODO: dated sprint heading, link to the roadmap, a few items."""
    link_line = f"Roadmap: [BRD roadmap]({LINK_TARGET})" if link is None else link
    return f"{heading}\n\nScoped sprint list.\n\n{link_line}\n\n- [x] item one\n- [ ] item two\n{body}"


OLD_TODO = "# TODO\n\n## High Priority\n- [x] Persist raw document text.\n"


# --------------------------------------------------------------------------
# fixture repo + runner
# --------------------------------------------------------------------------
def clean_env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(extra)
    return env


def git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "init.defaultBranch=main", *args], cwd=root, env=clean_env(),
        check=True, capture_output=True, timeout=HARNESS_TIMEOUT_S,
    )


@dataclass
class Result:
    code: int
    stdout: str
    stderr: str
    ids: list[str] = field(default_factory=list)


def run_check(root: Path, *args: str, cwd: Path | None = None, env: dict[str, str] | None = None,
              redact: Path | None = None) -> Result:
    """Run the real script; assert no absolute path leaks into its output (F8)."""
    argv = ["bash", str(SCRIPT), *args] if args else ["bash", str(SCRIPT)]
    proc = subprocess.run(
        argv, cwd=cwd or root, env=env or clean_env(), capture_output=True,
        timeout=HARNESS_TIMEOUT_S,
    )
    out = proc.stdout.decode("utf-8", "replace")
    err = proc.stderr.decode("utf-8", "replace")
    for leak in {str(root), str(root.resolve()), str(redact or root), str(Path.home())}:
        assert leak not in out + err, "script output contains an absolute path"
    assert "\x1b" not in out + err, "script output contains a raw ESC byte"
    return Result(proc.returncode, out, err, FAIL_LINE_RE.findall(err))


@dataclass
class Tree:
    root: Path

    def write(self, rel: str, content: str | bytes) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_bytes(content.encode("utf-8", "surrogatepass"))
        return path

    def track(self) -> None:
        git(self.root, "add", "-A")

    def run(self, **kwargs: object) -> Result:
        self.track()
        return run_check(self.root, str(self.root), **kwargs)  # type: ignore[arg-type]


def make_tree(base: Path, *, todo: str | bytes | None = None, brd_doc: str | bytes | None = None,
              refs: dict[str, str] | None = None, config: str | None = None) -> Tree:
    base.mkdir(parents=True, exist_ok=True)
    tree = Tree(base)
    git(base, "init", "-q")
    tree.write(CONFIG_REL, read_config_text() if config is None else config)
    tree.write(BRD_REL, brd() if brd_doc is None else brd_doc)
    if todo is not None:
        tree.write(TODO_REL, todo)
    for rel, text in (refs or {}).items():
        tree.write(rel, text)
    return tree


def assert_violations(result: Result, expected: set[str]) -> None:
    assert result.code == EXIT_VIOLATION, (result.code, result.stdout, result.stderr)
    assert set(result.ids) == expected, result.stderr
    assert len(result.ids) == len(expected), "a condition was reported twice"
    assert FAIL_SUMMARY.format(n=len(expected)) in result.stderr
    assert OK_PREFIX not in result.stdout


def assert_ok(result: Result, *, checked: int = MIN_CHECKED, todo_state: str = "absent") -> None:
    assert result.code == EXIT_OK, (result.code, result.stdout, result.stderr)
    assert result.ids == []
    assert result.stdout.startswith(OK_PREFIX)
    assert f"checked={checked} " in result.stdout
    assert f"todo={todo_state};" in result.stdout


def stray_ref_doc() -> str:
    return f"See {TODO_REL} for the roadmap.\n"


# --------------------------------------------------------------------------
# Spec cases from the card, plus the both-outcomes rule
# --------------------------------------------------------------------------
def test_check_roadmap_ssot_todo_absent_and_brd_checked_passes(tmp_path: Path) -> None:
    result = make_tree(tmp_path).run()
    assert_ok(result, todo_state="absent")
    # The tracked config names todo_path inside the reference scope; it must
    # not count as a stray reference to itself.
    assert any(CONFIG_REL.startswith(scope) for scope in SCOPE)
    assert "references=0" in result.stdout


def test_check_roadmap_ssot_demoted_sprint_list_passes(tmp_path: Path) -> None:
    # Demotion is allowed: the sprint list may be referenced from .claude.
    tree = make_tree(tmp_path, todo=sprint_todo(), refs={f"{SCOPE[0]}/CLAUDE.md": stray_ref_doc()})
    result = tree.run()
    assert_ok(result, todo_state="sprint-list")
    assert "references=1" in result.stdout


def test_check_roadmap_ssot_todo_heading_fails(tmp_path: Path) -> None:
    result = make_tree(tmp_path, todo=sprint_todo(heading="# TODO")).run()
    assert_violations(result, {"todo-sprint-heading"})
    assert TODO_REL in result.stderr and "line 1" in result.stderr
    assert f"'# {KEYWORD} YYYY-MM-DD to YYYY-MM-DD'" in result.stderr  # the fix is named


def test_check_roadmap_ssot_todo_link_missing_fails(tmp_path: Path) -> None:
    result = make_tree(tmp_path, todo=sprint_todo(link="No link here.")).run()
    assert_violations(result, {"todo-roadmap-link"})
    assert f"[roadmap]({LINK_TARGET})" in result.stderr


def test_check_roadmap_ssot_brd_zero_checked_fails(tmp_path: Path) -> None:
    result = make_tree(tmp_path, brd_doc=brd(checked=0, unchecked=4)).run()
    assert_violations(result, {"brd-roadmap-checked"})
    assert f"checked=0 unchecked=4; min_checked_boxes={MIN_CHECKED}" in result.stderr


def test_check_roadmap_ssot_brd_missing_section_fails_loudly(tmp_path: Path) -> None:
    doc = brd().replace(HEADING, "#" * HEADING_LEVEL + " Roadmap Ideas")
    result = make_tree(tmp_path, brd_doc=doc).run()
    assert_violations(result, {"brd-roadmap-section"})
    assert f"has 0 '{HEADING}' heading(s); exactly 1 is required" in result.stderr


def test_check_roadmap_ssot_brd_absent_fails_loudly(tmp_path: Path) -> None:
    tree = make_tree(tmp_path)
    (tree.root / BRD_REL).unlink()
    result = tree.run()
    assert_violations(result, {"brd-file"})
    assert f"{BRD_REL} is missing" in result.stderr


@pytest.mark.parametrize("scope_index", range(len(SCOPE)))
def test_check_roadmap_ssot_stray_reference_fails(tmp_path: Path, scope_index: int) -> None:
    scope = SCOPE[scope_index]
    rel = f"{scope}/notes.md" if "." not in Path(scope).name or scope.startswith(".") else scope
    result = make_tree(tmp_path, refs={rel: stray_ref_doc()}).run()
    assert_violations(result, {"stray-todo-reference"})
    assert f"1 reference(s) to {TODO_REL}" in result.stderr
    assert f"{rel} (1)" in result.stderr


def test_check_roadmap_ssot_reference_outside_scope_is_ignored(tmp_path: Path) -> None:
    # Positive control: docs/plans may still mention the old file.
    result = make_tree(tmp_path, refs={"docs/plans/history.md": stray_ref_doc()}).run()
    assert_ok(result)
    assert "references=0" in result.stdout


def test_check_roadmap_ssot_untracked_reference_is_ignored(tmp_path: Path) -> None:
    # The spec is `git grep`: only tracked files count.
    tree = make_tree(tmp_path)
    tree.track()
    tree.write(f"{SCOPE[0]}/scratch.md", stray_ref_doc())
    result = run_check(tree.root, str(tree.root))
    assert_ok(result)


def test_check_roadmap_ssot_invalid_todo_cannot_excuse_references(tmp_path: Path) -> None:
    refs = {f"{SCOPE[0]}/CLAUDE.md": stray_ref_doc()}
    result = make_tree(tmp_path, todo=sprint_todo(heading="# TODO"), refs=refs).run()
    assert_violations(result, {"todo-sprint-heading", "stray-todo-reference"})


def test_check_roadmap_ssot_reports_every_violation_at_once(tmp_path: Path) -> None:
    # Today's repo shape: old TODO with no link, BRD with nothing checked, refs.
    refs = {f"{SCOPE[0]}/CLAUDE.md": stray_ref_doc()}
    result = make_tree(tmp_path, todo=OLD_TODO, brd_doc=brd(checked=0), refs=refs).run()
    assert_violations(result, {"todo-sprint-heading", "todo-roadmap-link", "brd-roadmap-checked",
                               "stray-todo-reference"})


# --------------------------------------------------------------------------
# Table: every condition id has at least one pass vector and one fail vector
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Vector:
    name: str
    condition: str
    passes: bool
    build: Callable[[Path], Tree]


def _symlinked_todo(base: Path) -> Tree:
    tree = make_tree(base)
    target = base / "elsewhere.md"
    target.write_text(sprint_todo(), encoding="utf-8")
    (base / TODO_REL).symlink_to(target)
    return tree


def _symlinked_brd(base: Path) -> Tree:
    tree = make_tree(base)
    target = base / "outside-brd.md"
    target.write_text(brd(), encoding="utf-8")
    (base / BRD_REL).unlink()
    (base / BRD_REL).symlink_to(target)
    return tree


def _todo_directory(base: Path) -> Tree:
    tree = make_tree(base)
    (base / TODO_REL).mkdir(parents=True)
    (base / TODO_REL / "keep.md").write_text("x\n", encoding="utf-8")
    return tree


def _oversize(rel_is_todo: bool) -> Callable[[Path], Tree]:
    def build(base: Path) -> Tree:
        cap = 4096
        doc = brd() if not rel_is_todo else sprint_todo()
        padded = doc + ("\n<!-- pad -->" * (cap // 8))
        tree = make_tree(base, config=config_with(max_doc_bytes=str(cap)))
        tree.write(TODO_REL if rel_is_todo else BRD_REL, padded)
        assert len(padded.encode()) > cap
        return tree
    return build


VECTORS: tuple[Vector, ...] = (
    # todo-file
    Vector("todo absent", "todo-file", True, lambda b: make_tree(b)),
    Vector("todo regular sprint list", "todo-file", True, lambda b: make_tree(b, todo=sprint_todo())),
    Vector("todo symlink to a valid sprint list", "todo-file", False, _symlinked_todo),
    Vector("todo is a directory", "todo-file", False, _todo_directory),
    Vector("todo has a NUL byte", "todo-file", False,
           lambda b: make_tree(b, todo=sprint_todo().encode() + b"\x00\n")),
    Vector("todo invalid UTF-8", "todo-file", False,
           lambda b: make_tree(b, todo=sprint_todo().encode() + b"\xff\xfe\n")),
    Vector("todo lone surrogate (CESU bytes)", "todo-file", False,
           lambda b: make_tree(b, todo=sprint_todo().encode() + b"\xed\xa0\x80\n")),
    Vector("todo over max_doc_bytes", "todo-file", False, _oversize(True)),
    # todo-sprint-heading
    Vector("heading 'to' range", "todo-sprint-heading", True, lambda b: make_tree(b, todo=sprint_todo())),
    Vector("heading '..' range, level 2", "todo-sprint-heading", True,
           lambda b: make_tree(b, todo=sprint_todo(f"## {KEYWORD} list 2026-10-12..2026-10-26"))),
    Vector("heading en dash range", "todo-sprint-heading", True,
           lambda b: make_tree(b, todo=sprint_todo(f"# {KEYWORD} 2026-10-12 \u2013 2026-10-26"))),
    Vector("heading one-day range (boundary)", "todo-sprint-heading", True,
           lambda b: make_tree(b, todo=sprint_todo(f"# {KEYWORD} 2026-10-12 to 2026-10-12"))),
    Vector("heading with closing hashes", "todo-sprint-heading", True,
           lambda b: make_tree(b, todo=sprint_todo(f"# {KEYWORD} 2026-10-12 to 2026-10-26 #"))),
    Vector("CRLF file", "todo-sprint-heading", True,
           lambda b: make_tree(b, todo=sprint_todo().replace("\n", "\r\n"))),
    Vector("leap day is a real date", "todo-sprint-heading", True,
           lambda b: make_tree(b, todo=sprint_todo(f"# {KEYWORD} 2028-02-29 to 2028-03-10"))),
    Vector("heading '# TODO'", "todo-sprint-heading", False,
           lambda b: make_tree(b, todo=sprint_todo("# TODO"))),
    Vector("keyword without dates", "todo-sprint-heading", False,
           lambda b: make_tree(b, todo=sprint_todo(f"# {KEYWORD} list"))),
    Vector("dates without keyword", "todo-sprint-heading", False,
           lambda b: make_tree(b, todo=sprint_todo("# Tasks 2026-10-12 to 2026-10-26"))),
    Vector("keyword glued to another word", "todo-sprint-heading", False,
           lambda b: make_tree(b, todo=sprint_todo(f"# Pre{KEYWORD.lower()} 2026-10-12 to 2026-10-26"))),
    Vector("one date only", "todo-sprint-heading", False,
           lambda b: make_tree(b, todo=sprint_todo(f"# {KEYWORD} 2026-10-12"))),
    Vector("reversed range", "todo-sprint-heading", False,
           lambda b: make_tree(b, todo=sprint_todo(f"# {KEYWORD} 2026-10-26 to 2026-10-12"))),
    Vector("month 13", "todo-sprint-heading", False,
           lambda b: make_tree(b, todo=sprint_todo(f"# {KEYWORD} 2026-13-01 to 2026-13-15"))),
    Vector("Feb 30", "todo-sprint-heading", False,
           lambda b: make_tree(b, todo=sprint_todo(f"# {KEYWORD} 2026-02-30 to 2026-03-01"))),
    Vector("Feb 29 in a non-leap year", "todo-sprint-heading", False,
           lambda b: make_tree(b, todo=sprint_todo(f"# {KEYWORD} 2026-02-29 to 2026-03-10"))),
    Vector("Arabic-Indic digits", "todo-sprint-heading", False,
           lambda b: make_tree(b, todo=sprint_todo(f"# {KEYWORD} \u0662\u0660\u0662\u0666-10-12 to 2026-10-26"))),
    Vector("fullwidth digits", "todo-sprint-heading", False,
           lambda b: make_tree(b, todo=sprint_todo(f"# {KEYWORD} \uff12\uff10\uff12\uff16-10-12 to 2026-10-26"))),
    Vector("Cyrillic look-alike keyword", "todo-sprint-heading", False,
           lambda b: make_tree(b, todo=sprint_todo("# " + KEYWORD.replace("p", "\u0440") + " 2026-10-12 to 2026-10-26"))),
    Vector("no space after # (not a heading)", "todo-sprint-heading", False,
           lambda b: make_tree(b, todo=sprint_todo(f"#{KEYWORD} 2026-10-12 to 2026-10-26"))),
    Vector("no heading at all", "todo-sprint-heading", False,
           lambda b: make_tree(b, todo=sprint_todo(f"{KEYWORD} 2026-10-12 to 2026-10-26"))),
    Vector("leading BOM", "todo-sprint-heading", False,
           lambda b: make_tree(b, todo="\ufeff" + sprint_todo())),
    Vector("sprint heading second, '# TODO' first", "todo-sprint-heading", False,
           lambda b: make_tree(b, todo="# TODO\n\n" + sprint_todo())),
    Vector("sprint heading only inside a code fence", "todo-sprint-heading", False,
           lambda b: make_tree(b, todo=f"```\n{SPRINT_HEADING}\n```\n\n" + sprint_todo("# TODO"))),
    Vector("sprint heading only inside an HTML comment", "todo-sprint-heading", False,
           lambda b: make_tree(b, todo=f"<!--\n{SPRINT_HEADING}\n-->\n" + sprint_todo("# TODO"))),
    Vector("lone CR splits '# TODO' from a forged sprint line", "todo-sprint-heading", False,
           lambda b: make_tree(b, todo=sprint_todo(f"# TODO\r{SPRINT_HEADING}"))),
    Vector("ANSI escape in the heading", "todo-sprint-heading", False,
           lambda b: make_tree(b, todo=sprint_todo(f"# {KEYWORD}\x1b[2J 2026-10-12 to 2026-10-26"))),
    # todo-roadmap-link
    Vector("plain link", "todo-roadmap-link", True, lambda b: make_tree(b, todo=sprint_todo())),
    Vector("./ prefix and title", "todo-roadmap-link", True,
           lambda b: make_tree(b, todo=sprint_todo(link=f'[r](./{LINK_TARGET} "roadmap")'))),
    Vector("link without anchor", "todo-roadmap-link", False,
           lambda b: make_tree(b, todo=sprint_todo(link=f"[r]({LINK_TARGET.split('#')[0]})"))),
    Vector("wrong anchor suffix", "todo-roadmap-link", False,
           lambda b: make_tree(b, todo=sprint_todo(link=f"[r]({LINK_TARGET}-old)"))),
    Vector("upper-case anchor", "todo-roadmap-link", False,
           lambda b: make_tree(b, todo=sprint_todo(link=f"[r]({LINK_TARGET.split('#')[0]}#{ANCHOR.upper()})"))),
    Vector("wrong directory", "todo-roadmap-link", False,
           lambda b: make_tree(b, todo=sprint_todo(link=f"[r](../{LINK_TARGET})"))),
    Vector("bare text, not a link", "todo-roadmap-link", False,
           lambda b: make_tree(b, todo=sprint_todo(link=f"See {LINK_TARGET}"))),
    Vector("link only inside a code fence", "todo-roadmap-link", False,
           lambda b: make_tree(b, todo=sprint_todo(link=f"```\n[r]({LINK_TARGET})\n```"))),
    Vector("link only inside an HTML comment", "todo-roadmap-link", False,
           lambda b: make_tree(b, todo=sprint_todo(link=f"<!-- [r]({LINK_TARGET}) -->"))),
    Vector("zero-width space inside the anchor", "todo-roadmap-link", False,
           lambda b: make_tree(b, todo=sprint_todo(link=f"[r]({LINK_TARGET[:-3]}\u200b{LINK_TARGET[-3:]})"))),
    # PR #331 round 1: only a real inline link counts, not link-shaped text.
    Vector("inline link with the text 'Roadmap'", "todo-roadmap-link", True,
           lambda b: make_tree(b, todo=sprint_todo(link=f"[Roadmap]({LINK_TARGET})"))),
    Vector("inline code before a real link on the same line", "todo-roadmap-link", True,
           lambda b: make_tree(b, todo=sprint_todo(link=f"Run `make` then read [Roadmap]({LINK_TARGET})."))),
    Vector("no opening '[' before '](target)'", "todo-roadmap-link", False,
           lambda b: make_tree(b, todo=sprint_todo(link=f"See roadmap]({LINK_TARGET}) here."))),
    Vector("link only inside inline code", "todo-roadmap-link", False,
           lambda b: make_tree(b, todo=sprint_todo(link=f"Example: `[Roadmap]({LINK_TARGET})`"))),
    Vector("link only inside double-backtick inline code", "todo-roadmap-link", False,
           lambda b: make_tree(b, todo=sprint_todo(link=f"Example: ``[Roadmap]({LINK_TARGET})``"))),
    Vector("image, not a link", "todo-roadmap-link", False,
           lambda b: make_tree(b, todo=sprint_todo(link=f"![x]({LINK_TARGET})"))),
    Vector("link only inside a tilde fence", "todo-roadmap-link", False,
           lambda b: make_tree(b, todo=sprint_todo(link=f"~~~\n[Roadmap]({LINK_TARGET})\n~~~"))),
    Vector("link only inside an indented code block", "todo-roadmap-link", False,
           lambda b: make_tree(b, todo=sprint_todo(link=f"Example:\n\n    [Roadmap]({LINK_TARGET})\n"))),
    # PR #331 round 2 (CommonMark oracle): a fence inside a list item may be
    # indented 0-3 columns past the item's content column, not past the margin.
    Vector("link only inside a fence nested in a list item", "todo-roadmap-link", False,
           lambda b: make_tree(b, todo=sprint_todo(link=f"- item\n\n    ```\n    [Roadmap]({LINK_TARGET})\n    ```"))),
    Vector("link only inside a tab-indented fence in an ordered item", "todo-roadmap-link", False,
           lambda b: make_tree(b, todo=sprint_todo(link=f"1. item\n\n\t```\n\t[Roadmap]({LINK_TARGET})\n\t```"))),
    Vector("link in the list item after its nested fence closes", "todo-roadmap-link", True,
           lambda b: make_tree(b, todo=sprint_todo(
               link=f"- item\n\n    ```\n    code\n    ```\n\n  [Roadmap]({LINK_TARGET})"))),
    Vector("link on an indented paragraph continuation line", "todo-roadmap-link", True,
           lambda b: make_tree(b, todo=sprint_todo(link=f"See the\n    [Roadmap]({LINK_TARGET})"))),
    Vector("unclosed '``' before a code span that holds the link", "todo-roadmap-link", False,
           lambda b: make_tree(b, todo=sprint_todo(link=f"``x `[Roadmap]({LINK_TARGET})`"))),
    Vector("unclosed backtick before a real link is literal text", "todo-roadmap-link", True,
           lambda b: make_tree(b, todo=sprint_todo(link=f"Run `make then read [Roadmap]({LINK_TARGET})."))),
    # brd-file
    Vector("brd regular file", "brd-file", True, lambda b: make_tree(b)),
    Vector("brd symlink", "brd-file", False, _symlinked_brd),
    Vector("brd NUL byte", "brd-file", False, lambda b: make_tree(b, brd_doc=brd().encode() + b"\x00")),
    Vector("brd invalid UTF-8", "brd-file", False, lambda b: make_tree(b, brd_doc=brd().encode() + b"\xc3\x28")),
    Vector("brd over max_doc_bytes", "brd-file", False, _oversize(False)),
    # brd-roadmap-section
    Vector("one section", "brd-roadmap-section", True, lambda b: make_tree(b)),
    Vector("closing hashes on the section heading", "brd-roadmap-section", True,
           lambda b: make_tree(b, brd_doc=brd(heading=HEADING + " " + "#" * HEADING_LEVEL))),
    Vector("section heading at the wrong level", "brd-roadmap-section", False,
           lambda b: make_tree(b, brd_doc=brd(heading="#" + HEADING))),
    Vector("zero-width space in the section heading", "brd-roadmap-section", False,
           lambda b: make_tree(b, brd_doc=brd(heading=HEADING.replace(" ", "\u200b", 2).replace("\u200b", " ", 1)))),
    Vector("Cyrillic look-alike in the section heading", "brd-roadmap-section", False,
           lambda b: make_tree(b, brd_doc=brd(heading=HEADING.replace("o", "\u043e")))),
    Vector("section heading only inside a code fence", "brd-roadmap-section", False,
           lambda b: make_tree(b, brd_doc=brd(heading=f"```\n{HEADING}\n```"))),
    Vector("duplicate section", "brd-roadmap-section", False,
           lambda b: make_tree(b, brd_doc=brd(after=f"{HEADING}\n\n- [x] again"))),
    # brd-roadmap-checked
    Vector("min checked (boundary)", "brd-roadmap-checked", True, lambda b: make_tree(b)),
    Vector("subsection, '*' / '+' / ordered / upper-case X / nested items", "brd-roadmap-checked", True,
           lambda b: make_tree(b, brd_doc=brd(checked=0, inside="* [X] a\n+ [x] b\n1. [x] c\n2) [x] d\n  - [x] e"),
                               config=config_with(min_checked_boxes="5"))),
    Vector("CRLF BRD", "brd-roadmap-checked", True,
           lambda b: make_tree(b, brd_doc=brd().replace("\n", "\r\n"))),
    Vector("min - 1 checked (boundary)", "brd-roadmap-checked", False,
           lambda b: make_tree(b, brd_doc=brd(checked=MIN_CHECKED - 1))),
    Vector("checked boxes only before the section", "brd-roadmap-checked", False,
           lambda b: make_tree(b, brd_doc=brd(checked=0, before="- [x] early\n" * MIN_CHECKED))),
    Vector("checked boxes only after the section", "brd-roadmap-checked", False,
           lambda b: make_tree(b, brd_doc=brd(checked=0, after="- [x] late\n" * MIN_CHECKED))),
    Vector("checked boxes after a setext heading that ends the section", "brd-roadmap-checked", False,
           lambda b: make_tree(b, brd_doc=brd(checked=0, inside="Appendix\n========\n\n" + "- [x] late\n" * MIN_CHECKED))),
    Vector("checked boxes inside a code fence", "brd-roadmap-checked", False,
           lambda b: make_tree(b, brd_doc=brd(checked=0, inside="```\n" + "- [x] fenced\n" * MIN_CHECKED + "```"))),
    Vector("checked boxes inside a tilde fence", "brd-roadmap-checked", False,
           lambda b: make_tree(b, brd_doc=brd(checked=0, inside="~~~~\n" + "- [x] fenced\n" * MIN_CHECKED + "~~~~"))),
    Vector("checked boxes inside an HTML comment", "brd-roadmap-checked", False,
           lambda b: make_tree(b, brd_doc=brd(checked=0, inside="<!--\n" + "- [x] hidden\n" * MIN_CHECKED + "-->"))),
    Vector("'[x]' in prose", "brd-roadmap-checked", False,
           lambda b: make_tree(b, brd_doc=brd(checked=0, inside="Mark items with [x] when done.\n" * MIN_CHECKED))),
    Vector("Cyrillic look-alike x", "brd-roadmap-checked", False,
           lambda b: make_tree(b, brd_doc=brd(checked=0, inside="- [\u0445] look-alike\n" * MIN_CHECKED))),
    Vector("fullwidth brackets", "brd-roadmap-checked", False,
           lambda b: make_tree(b, brd_doc=brd(checked=0, inside="- \uff3bx\uff3d fullwidth\n" * MIN_CHECKED))),
    Vector("NBSP after the list marker", "brd-roadmap-checked", False,
           lambda b: make_tree(b, brd_doc=brd(checked=0, inside="-\u00a0[x] nbsp\n" * MIN_CHECKED))),
    Vector("U+2028 forges a checked item onto an unchecked line", "brd-roadmap-checked", False,
           lambda b: make_tree(b, brd_doc=brd(checked=0, inside="- [ ] open\u2028- [x] forged\n" * MIN_CHECKED))),
    # PR #331 round 1: indented code is code, but a nested list task is a task.
    Vector("nested list task under a parent item", "brd-roadmap-checked", True,
           lambda b: make_tree(b, brd_doc=brd(checked=0, unchecked=0,
                                              inside="- parent\n" + "  - [x] child\n" * MIN_CHECKED))),
    Vector("task nested two levels (4-space indent inside a list)", "brd-roadmap-checked", True,
           lambda b: make_tree(b, brd_doc=brd(checked=0, unchecked=0,
                                              inside="- a\n  - b\n" + "    - [x] c\n" * MIN_CHECKED))),
    Vector("nested task after a blank line in a loose list", "brd-roadmap-checked", True,
           lambda b: make_tree(b, brd_doc=brd(checked=0, unchecked=0,
                                              inside="- parent\n\n" + "    - [x] child\n" * MIN_CHECKED))),
    Vector("checked boxes in a 4-space indented code block", "brd-roadmap-checked", False,
           lambda b: make_tree(b, brd_doc=brd(checked=0, unchecked=0,
                                              inside="Example:\n\n" + "    - [x] example\n" * MIN_CHECKED))),
    Vector("checked boxes in a tab-indented code block", "brd-roadmap-checked", False,
           lambda b: make_tree(b, brd_doc=brd(checked=0, unchecked=0,
                                              inside="Example:\n\n" + "\t- [x] example\n" * MIN_CHECKED))),
    Vector("checked boxes in an 8-space indented code block", "brd-roadmap-checked", False,
           lambda b: make_tree(b, brd_doc=brd(checked=0, unchecked=0,
                                              inside="Example:\n\n" + "        * [X] example\n" * MIN_CHECKED))),
    Vector("indented code block right under a subsection heading", "brd-roadmap-checked", False,
           lambda b: make_tree(b, brd_doc=brd(checked=0, unchecked=0,
                                              inside="#" * (HEADING_LEVEL + 1) + " Examples\n\n"
                                              + "    1. [x] example\n" * MIN_CHECKED))),
    # PR #331 round 2 (CommonMark oracle): fences nested in list items. A fence
    # opener or closer is indented 0-3 columns past the enclosing item's
    # content column; 4 or more is indented code. A line that leaves the item
    # (less indented, not blank) ends the item and the fence inside it.
    Vector("checked boxes in a fence nested in a bullet item", "brd-roadmap-checked", False,
           lambda b: make_tree(b, brd_doc=brd(checked=0, unchecked=0, inside=(
               "- item\n\n    ```\n" + "    - [x] fake\n" * MIN_CHECKED + "    ```")))),
    Vector("checked boxes in a fence nested in a '1.' item", "brd-roadmap-checked", False,
           lambda b: make_tree(b, brd_doc=brd(checked=0, unchecked=0, inside=(
               "1. item\n\n    ```\n" + "    - [x] fake\n" * MIN_CHECKED + "    ```")))),
    Vector("checked boxes in a fence at the content column of a '10.' item", "brd-roadmap-checked", False,
           lambda b: make_tree(b, brd_doc=brd(checked=0, unchecked=0, inside=(
               "10. item\n\n    ```\n" + "    - [x] fake\n" * MIN_CHECKED + "    ```")))),
    Vector("checked boxes in a fence 5 spaces into a '1.' item", "brd-roadmap-checked", False,
           lambda b: make_tree(b, brd_doc=brd(checked=0, unchecked=0, inside=(
               "1. item\n\n     ```\n" + "     - [x] fake\n" * MIN_CHECKED + "     ```")))),
    Vector("checked boxes in a tab-indented fence in a list item", "brd-roadmap-checked", False,
           lambda b: make_tree(b, brd_doc=brd(checked=0, unchecked=0, inside=(
               "- item\n\n\t```\n" + "\t- [x] fake\n" * MIN_CHECKED + "\t```")))),
    Vector("checked boxes in a tilde fence nested in a list item", "brd-roadmap-checked", False,
           lambda b: make_tree(b, brd_doc=brd(checked=0, unchecked=0, inside=(
               "- item\n\n    ~~~\n" + "    - [x] fake\n" * MIN_CHECKED + "    ~~~")))),
    Vector("checked boxes in a fence nested two list levels deep", "brd-roadmap-checked", False,
           lambda b: make_tree(b, brd_doc=brd(checked=0, unchecked=0, inside=(
               "- a\n  - b\n\n      ```\n" + "      - [x] fake\n" * MIN_CHECKED + "      ```")))),
    Vector("checked boxes in a nested fence that interrupts the item text", "brd-roadmap-checked", False,
           lambda b: make_tree(b, brd_doc=brd(checked=0, unchecked=0, inside=(
               "- item\n    ```\n" + "    - [x] fake\n" * MIN_CHECKED + "    ```")))),
    Vector("checked boxes in a list-nested fence, CRLF file", "brd-roadmap-checked", False,
           lambda b: make_tree(b, brd_doc=brd(checked=0, unchecked=0, inside=(
               "- item\n\n    ```\n" + "    - [x] fake\n" * MIN_CHECKED + "    ```")).replace("\n", "\r\n"))),
    Vector("closer 4 columns past the content column does not close the fence", "brd-roadmap-checked", False,
           lambda b: make_tree(b, brd_doc=brd(checked=0, unchecked=0, inside=(
               "- item\n\n    ```\n      ```\n" + "    - [x] fake\n" * MIN_CHECKED + "    ```")))),
    Vector("column-0 fence after a nested fence opens a new fence", "brd-roadmap-checked", False,
           lambda b: make_tree(b, brd_doc=brd(checked=0, unchecked=0, inside=(
               "- item\n\n    ```\n    x\n```\n" + "- [x] fake\n" * MIN_CHECKED + "```")))),
    Vector("fence 4 columns past the content column is indented code", "brd-roadmap-checked", False,
           lambda b: make_tree(b, brd_doc=brd(checked=0, unchecked=0, inside=(
               "- item\n\n      ```\n" + "      - [x] fake\n" * MIN_CHECKED + "      ```")))),
    Vector("real task after a list-nested fence closes", "brd-roadmap-checked", True,
           lambda b: make_tree(b, brd_doc=brd(checked=0, unchecked=0, inside=(
               "- item\n\n    ```\n    - [ ] fake\n    ```\n" + "- [x] real\n" * MIN_CHECKED)))),
    Vector("leaving the list item ends its unclosed fence", "brd-roadmap-checked", True,
           lambda b: make_tree(b, brd_doc=brd(checked=0, unchecked=0, inside=(
               "- item\n\n    ```\n    code\n\n" + "- [x] real\n" * MIN_CHECKED)))),
    Vector("nested task after a closed fence in the same item", "brd-roadmap-checked", True,
           lambda b: make_tree(b, brd_doc=brd(checked=0, unchecked=0, inside=(
               "- item\n\n    ```\n    code\n    ```\n\n" + "    - [x] real\n" * MIN_CHECKED)))),
    # PR #331 round 2: mutation killers from the coder's mutation run.
    Vector("nested task after a lazy continuation line", "brd-roadmap-checked", True,
           lambda b: make_tree(b, brd_doc=brd(checked=0, unchecked=0, inside=(
               "- parent\nlazy continuation\n\n" + "    - [x] child\n" * MIN_CHECKED)))),
    Vector("4-space task straight after a closing fence is code", "brd-roadmap-checked", False,
           lambda b: make_tree(b, brd_doc=brd(checked=0, unchecked=0, inside=(
               "```\ncode\n```\n" + "    - [x] x\n" * MIN_CHECKED)))),
    Vector("wide item (5 spaces after the marker): 6-space child is code", "brd-roadmap-checked", False,
           lambda b: make_tree(b, brd_doc=brd(checked=0, unchecked=0, inside=(
               "-     wide item\n\n" + "      - [x] x\n" * MIN_CHECKED)))),
    # stray-todo-reference
    Vector("no references", "stray-todo-reference", True, lambda b: make_tree(b)),
    Vector("references to a valid sprint list", "stray-todo-reference", True,
           lambda b: make_tree(b, todo=sprint_todo(), refs={"README.md": stray_ref_doc()})),
    Vector("reference with TODO absent", "stray-todo-reference", False,
           lambda b: make_tree(b, refs={f"{SCOPE[0]}/CLAUDE.md": stray_ref_doc()})),
    Vector("reference in a nested .claude file", "stray-todo-reference", False,
           lambda b: make_tree(b, refs={f"{SCOPE[0]}/library/LIB-X.md": stray_ref_doc()})),
)


@pytest.mark.parametrize("vector", VECTORS, ids=lambda v: f"{v.condition}:{v.name}")
def test_check_roadmap_ssot_vectors(tmp_path: Path, vector: Vector) -> None:
    result = vector.build(tmp_path).run()
    if vector.passes:
        assert vector.condition not in result.ids, result.stderr
        assert result.code == EXIT_OK, (result.code, result.stdout, result.stderr)
    else:
        assert result.code == EXIT_VIOLATION, (result.code, result.stdout, result.stderr)
        assert vector.condition in result.ids, result.stderr
        assert FAIL_SUMMARY.format(n=len(result.ids)) in result.stderr


def test_check_roadmap_ssot_vectors_cover_every_condition() -> None:
    """Contract: each condition id has a pass vector and a fail vector."""
    for ident in VIOLATION_IDS:
        kinds = {v.passes for v in VECTORS if v.condition == ident}
        assert kinds == {True, False}, f"{ident} needs both a pass and a fail vector"
    assert {v.condition for v in VECTORS} == set(VIOLATION_IDS)


def test_check_roadmap_ssot_boundary_follows_config(tmp_path: Path) -> None:
    """min_checked_boxes is read from config: N-1 fails, N and N+1 pass."""
    threshold = MIN_CHECKED + 2
    cfg = config_with(min_checked_boxes=str(threshold))
    for offset, ok in ((-1, False), (0, True), (1, True)):
        base = tmp_path / f"n{offset + 1}"
        result = make_tree(base, brd_doc=brd(checked=threshold + offset), config=cfg).run()
        if ok:
            assert_ok(result, checked=threshold + offset)
        else:
            assert_violations(result, {"brd-roadmap-checked"})
            assert f"min_checked_boxes={threshold}" in result.stderr


# --------------------------------------------------------------------------
# Generated hostile characters in the sprint heading (QUALITY-BAR R2)
# --------------------------------------------------------------------------
def _forbidden_heading_chars() -> list[str]:
    """Every Cc, Cf, Zl and Zp code point except tab and the CommonMark line endings."""
    chars = []
    for code in range(sys.maxunicode + 1):
        char = chr(code)
        if char in "\t\n\r":
            continue
        if unicodedata.category(char) in {"Cc", "Cf", "Zl", "Zp"}:
            chars.append(char)
    return chars


def test_check_roadmap_ssot_generated_invisible_chars_in_heading_fail(tmp_path: Path) -> None:
    chars = _forbidden_heading_chars()
    # The insert sits after the keyword, so keyword and dates still match:
    # the character alone must cause the failure.
    def one(index: int) -> tuple[str, Result]:
        heading = f"# {KEYWORD}{chars[index]} 2026-10-12 to 2026-10-26"
        tree = make_tree(tmp_path / f"c{index}", todo=sprint_todo(heading))
        return chars[index], tree.run()

    with ThreadPoolExecutor(max_workers=os.cpu_count() or 2) as pool:
        results = list(pool.map(one, range(len(chars))))
    print(f"generated hostile heading characters: {len(results)}")
    # NUL is refused for the whole file before any heading is parsed.
    missed = [f"U+{ord(c):04X}" for c, r in results
              if r.code != EXIT_VIOLATION
              or ("todo-file" if c == "\x00" else "todo-sprint-heading") not in r.ids]
    assert not missed, f"accepted as a sprint heading: {missed}"
    assert len(results) == len(chars) > 0


@pytest.mark.parametrize("brk", UNICODE_LINE_BREAKS + ("\r\n", "\r", "\n"),
                         ids=lambda c: f"U+{ord(c[0]):04X}{'+LF' if len(c) > 1 else ''}")
def test_check_roadmap_ssot_line_break_cannot_forge_sprint_heading(tmp_path: Path, brk: str) -> None:
    result = make_tree(tmp_path, todo=sprint_todo(f"# TODO{brk}{SPRINT_HEADING}")).run()
    assert result.code == EXIT_VIOLATION
    assert "todo-sprint-heading" in result.ids


# --------------------------------------------------------------------------
# Indirection, output safety, size and time
# --------------------------------------------------------------------------
def test_check_roadmap_ssot_git_dir_env_cannot_redirect_the_grep(tmp_path: Path) -> None:
    decoy = make_tree(tmp_path / "decoy")
    decoy.track()
    tree = make_tree(tmp_path / "real", refs={f"{SCOPE[0]}/CLAUDE.md": stray_ref_doc()})
    tree.track()
    env = clean_env(GIT_DIR=str(decoy.root / ".git"), GIT_WORK_TREE=str(decoy.root),
                    GIT_INDEX_FILE=str(decoy.root / ".git" / "index"))
    result = run_check(tree.root, str(tree.root), env=env, redact=tmp_path)
    assert_violations(result, {"stray-todo-reference"})


def test_check_roadmap_ssot_symlinked_docs_dir_is_refused(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / Path(BRD_REL).name).write_text(brd(), encoding="utf-8")
    tree = make_tree(tmp_path / "repo")
    shutil.rmtree(tree.root / Path(BRD_REL).parent)
    (tree.root / Path(BRD_REL).parent).symlink_to(outside, target_is_directory=True)
    tree.track()
    result = run_check(tree.root, str(tree.root), redact=tmp_path)
    # TODO.md is absent, but its parent is the symlink: both paths fail closed.
    assert_violations(result, {"brd-file", "todo-file"})
    assert "symlink" in result.stderr


def test_check_roadmap_ssot_hostile_file_names_are_not_echoed_raw(tmp_path: Path) -> None:
    name = f"{SCOPE[0]}/evil\x1b[31m\x07name.md"
    result = make_tree(tmp_path, refs={name: stray_ref_doc()}).run()
    assert_violations(result, {"stray-todo-reference"})
    assert "\x07" not in result.stderr  # run_check already refuses ESC


def test_check_roadmap_ssot_many_references_are_capped(tmp_path: Path) -> None:
    cap = int(CFG["max_listed_hits"])
    refs = {f"{SCOPE[0]}/ref{i:03d}.md": stray_ref_doc() for i in range(cap + 3)}
    result = make_tree(tmp_path, refs=refs).run()
    assert_violations(result, {"stray-todo-reference"})
    assert f"{cap + 3} reference(s)" in result.stderr
    assert result.stderr.count(" (1)") == cap
    assert ", and 3 more file(s)" in result.stderr


def _fake_git(tmp_path: Path, grep_body: str) -> dict[str, str]:
    """A git on PATH that runs real git, except `grep`, which runs grep_body."""
    real_git = shutil.which("git")
    assert real_git, "git is required"
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    fake = bin_dir / "git"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        'for a in "$@"; do if [ "$a" = grep ]; then\n'
        f"{grep_body}\n"
        "fi; done\n"
        f'exec "{real_git}" "$@"\n',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return clean_env(PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")


def test_check_roadmap_ssot_slow_git_fails_closed(tmp_path: Path) -> None:
    timeout = 1
    env = _fake_git(tmp_path, f"sleep {timeout * FAKE_GIT_SLEEP_FACTOR}; exit 1")
    tree = make_tree(tmp_path / "repo", config=config_with(git_timeout_seconds=str(timeout)))
    tree.track()
    started = time.monotonic()
    result = run_check(tree.root, str(tree.root), env=env, redact=tmp_path)
    elapsed = time.monotonic() - started
    assert result.code == EXIT_ERROR, result.stderr
    assert ERROR_PREFIX.format(ident="git-timeout") in result.stderr
    assert f"git_timeout_seconds={timeout}" in result.stderr
    assert elapsed < timeout * FAKE_GIT_SLEEP_FACTOR, "the deadline did not cut the hang"


def test_check_roadmap_ssot_huge_git_output_fails_closed(tmp_path: Path) -> None:
    cap = 1024
    env = _fake_git(tmp_path, f"head -c {cap * 4} /dev/zero | tr '\\0' a; exit 0")
    tree = make_tree(tmp_path / "repo", config=config_with(max_git_output_bytes=str(cap)))
    tree.track()
    result = run_check(tree.root, str(tree.root), env=env, redact=tmp_path)
    assert result.code == EXIT_ERROR, result.stderr
    assert ERROR_PREFIX.format(ident="git-output") in result.stderr


def test_check_roadmap_ssot_git_grep_error_fails_closed(tmp_path: Path) -> None:
    env = _fake_git(tmp_path, "exit 128")
    tree = make_tree(tmp_path / "repo")
    tree.track()
    result = run_check(tree.root, str(tree.root), env=env, redact=tmp_path)
    assert result.code == EXIT_ERROR, result.stderr
    assert ERROR_PREFIX.format(ident="git") in result.stderr


def test_check_roadmap_ssot_unparseable_git_output_fails_closed(tmp_path: Path) -> None:
    env = _fake_git(tmp_path, "echo 'no count here'; exit 0")
    tree = make_tree(tmp_path / "repo")
    tree.track()
    result = run_check(tree.root, str(tree.root), env=env, redact=tmp_path)
    assert result.code == EXIT_ERROR, result.stderr
    assert ERROR_PREFIX.format(ident="git") in result.stderr


# --------------------------------------------------------------------------
# Usage and root resolution
# --------------------------------------------------------------------------
def test_check_roadmap_ssot_default_root_is_git_toplevel(tmp_path: Path) -> None:
    tree = make_tree(tmp_path)
    tree.track()
    sub = tree.root / "docs"
    assert_ok(run_check(tree.root, cwd=sub))


def test_check_roadmap_ssot_default_root_outside_git_fails(tmp_path: Path) -> None:
    result = run_check(tmp_path, cwd=tmp_path, env=clean_env(GIT_CEILING_DIRECTORIES=str(tmp_path.parent)))
    assert result.code == EXIT_ERROR
    assert ERROR_PREFIX.format(ident="usage") in result.stderr


@pytest.mark.parametrize("case", ["two-args", "missing-dir", "empty-arg", "subdirectory", "not-a-repo"])
def test_check_roadmap_ssot_bad_root_fails_closed(tmp_path: Path, case: str) -> None:
    tree = make_tree(tmp_path / "repo")
    tree.track()
    plain = tmp_path / "plain"
    plain.mkdir()
    args = {
        "two-args": (str(tree.root), str(tree.root)),
        "missing-dir": (str(tmp_path / "nope"),),
        "empty-arg": ("",),
        "subdirectory": (str(tree.root / "docs"),),
        "not-a-repo": (str(plain),),
    }[case]
    env = clean_env(GIT_CEILING_DIRECTORIES=str(tmp_path))
    result = run_check(tree.root, *args, cwd=tmp_path, env=env, redact=tmp_path)
    assert result.code == EXIT_ERROR, (case, result.stderr)
    assert ERROR_PREFIX.format(ident="usage") in result.stderr
    assert OK_PREFIX not in result.stdout


# --------------------------------------------------------------------------
# Config fails closed at load (F13)
# --------------------------------------------------------------------------
def _bad_configs() -> dict[str, str]:
    real = read_config_text()
    first_key = next(line for line in real.split("\n") if line and not line.startswith("#"))
    return {
        "missing key": "\n".join(line for line in real.split("\n") if not line.startswith("min_checked_boxes=")),
        "unknown key": real + "\nmax_checked_boxes=3\n",
        "duplicate key": real + "\n" + first_key + "\n",
        "not key=value": real + "\njust words\n",
        "min_checked_boxes=0": config_with(min_checked_boxes="0"),
        "negative int": config_with(min_checked_boxes="-1"),
        "non-integer": config_with(max_doc_bytes="lots"),
        "leading zero": config_with(git_timeout_seconds="030"),
        "dotdot path": config_with(todo_path="docs/../TODO.md"),
        "absolute path": config_with(brd_path="/etc/passwd"),
        "same todo and brd": config_with(todo_path=CFG["brd_path"]),
        "heading without #": config_with(roadmap_heading=HEADING.lstrip("# ")),
        "heading level 7": config_with(roadmap_heading="#######" + HEADING.lstrip("#")),
        "keyword with digits": config_with(sprint_keyword=KEYWORD + "1"),
        "empty scope": config_with(reference_scope=""),
        "non-ASCII value": config_with(sprint_keyword="Spr\u0131nt"),
        "CR in file": real.replace("\n", "\r\n"),
        "NUL in file": real + "\x00",
        "empty file": "",
    }


@pytest.mark.parametrize("name", sorted(_bad_configs()))
def test_check_roadmap_ssot_bad_config_fails_closed(tmp_path: Path, name: str) -> None:
    result = make_tree(tmp_path, config=_bad_configs()[name]).run()
    assert result.code == EXIT_ERROR, (name, result.stdout, result.stderr)
    assert ERROR_PREFIX.format(ident="config") in result.stderr
    assert OK_PREFIX not in result.stdout


@pytest.mark.parametrize("case", ["missing", "symlink"])
def test_check_roadmap_ssot_config_file_must_exist_as_regular_file(tmp_path: Path, case: str) -> None:
    tree = make_tree(tmp_path / "repo")
    cfg = tree.root / CONFIG_REL
    if case == "missing":
        cfg.unlink()
    else:
        outside = tmp_path / "outside.conf"
        outside.write_text(read_config_text(), encoding="ascii")
        cfg.unlink()
        cfg.symlink_to(outside)
    tree.track()
    result = run_check(tree.root, str(tree.root), redact=tmp_path)
    assert result.code == EXIT_ERROR
    assert ERROR_PREFIX.format(ident="config") in result.stderr


# --------------------------------------------------------------------------
# The real repository (red until #156 is implemented)
# --------------------------------------------------------------------------
def test_real_repo_has_a_single_roadmap() -> None:
    """The check passes on this checkout: BRD roadmap ticked, TODO.md resolved."""
    result = run_check(REPO_ROOT, str(REPO_ROOT))
    assert result.code == EXIT_OK, result.stderr
    assert result.stdout.startswith(OK_PREFIX)
    assert re.search(r"\bchecked=[1-9][0-9]*\b", result.stdout)
    assert re.search(r"\btodo=(absent|sprint-list);", result.stdout)
