"""Acceptance tests for terms-analysis #161 (G1-13) and #327: ADRs 0003-0006.

Owner rulings, 2026-10-12:
- #161 "my approval is fine, renumber": owner sign-off (no counsel review) and
  this repo's 4-digit numbering. The card's reserved 015-017 are dropped; they
  would collide with the ingester's ADR-015/016 after the monorepo merge.
- #327 "b": torch is allowed by an ADR exception (ADR 0006).

Two layers:

1. Behaviour. `scripts/governance/check-adrs.py` runs as a subprocess against
   throwaway repos in tmp_path (positive controls, the brief's four negative
   vectors, generated hostile inputs, bad config) and then against this
   checkout, which is what wires it into CI (ci.yml runs this file).
2. Content. Docs can't be executed, so the settled decisions are checked
   statically, pinned to exact identifiers: ADRs 0003-0006, the index, and the
   citations in .claude/CLAUDE.md, LIB-STACK and LIB-LEGAL.

Checker contract (pinned here; the script header must document it):

  Usage: check-adrs.py [REPO_ROOT]  (default: the repo holding the script,
         never the cwd). Reads .claude/governance/adr-policy.conf under
         REPO_ROOT: one key=value per line, '#' comments and blank lines
         ignored, every key in CONFIG_KEYS required; a missing file, unknown,
         duplicate, empty or malformed key, a non-ASCII byte, a path that is
         absolute or contains '..', or a value outside its type fails closed.
  ADRs: every entry of adr_dir except index_file. Each must be named
         <number_digits ASCII digits>-<slug>.md, slug [a-z0-9-]+, else
         adr-filename (a misnamed entry is not numbered or indexed).
  Parsing: lines split on LF only (a trailing CR is ignored); text inside code
         fences and HTML comments is not structure. The header is everything
         before the first level-2 heading. Header fields are bullets
         "- **Key:** value". A line with any character outside printable
         ASCII is never a field or a heading.
  Exit 0: stdout "ADR-CHECK OK: <n> ADR(s)", n = ADR files checked.
  Exit 1: stderr one "FAIL [<id>]: <message>" line per violation, then
         "ADR-CHECK FAIL: <n> violation(s)". Ids:
           adr-file             not a regular file (symlink), invalid UTF-8,
                                NUL, or over max_doc_bytes (also index_file);
                                such a file is not parsed further
           adr-filename         see above
           adr-title            first line is not "# ADR <number>: <title>"
                                with the filename's number
           adr-number-duplicate two ADRs share a number
           adr-number-gap       the distinct numbers are not exactly 1..max
           adr-section          a required_sections level-2 heading missing
           adr-status           no Status field, or its first word is not in
                                statuses
           adr-approval         Status first word in approval_statuses and the
                                header mentions hard_requirement_prefix + an
                                ASCII digit, with no Approved-by field holding
                                a configured approver as a whole token
                                (tokens split on whitespace, ',' and ';')
           adr-index            index_file missing, an ADR not linked from it
                                (inline link "](<file>)"), or a link to an
                                ADR-named file that does not exist
           adr-none             adr_dir holds no ADR
  Exit 2: "ADR-CHECK ERROR [<id>]: <message>", ids usage, root, config,
         adr-dir (adr_dir missing, not a directory, or a symlink).
  All output is printable ASCII, names files relative to adr_dir, carries no
  absolute path, no raw bytes from the checked files and no traceback.

No config value is restated here (F13): everything is read from the config
file the checker reads, and overridden through that file where a case needs
another value. Pinned are only the output contract, the config location and
key names, and facts from the owner rulings (file names, ruling date).
"""
from __future__ import annotations

import functools
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "governance" / "check-adrs.py"
CONFIG_REL = ".claude/governance/adr-policy.conf"
CONFIG_KEYS = frozenset({
    "adr_dir",
    "index_file",
    "number_digits",
    "required_sections",
    "statuses",
    "approval_statuses",
    "hard_requirement_prefix",
    "approvers",
    "max_doc_bytes",
})

# Output contract of check-adrs.py.
EXIT_OK, EXIT_VIOLATION, EXIT_ERROR = 0, 1, 2
OK_LINE = "ADR-CHECK OK: {n} ADR(s)"
FAIL_SUMMARY = "ADR-CHECK FAIL: {n} violation(s)"
ERROR_PREFIX = "ADR-CHECK ERROR [{ident}]:"
FAIL_LINE_RE = re.compile(r"^FAIL \[([a-z-]+)\]: \S")
STATUS_FIELD, APPROVED_FIELD = "Status", "Approved-by"

# Facts from the owner rulings (not config).
RULING_DATE = "2026-10-12"
TARGET_ADRS = {
    1: "0001-dependency-rules-scope-ci-review-tooling.md",
    2: "0002-wiring-audit-batch-api-exemption.md",
    3: "0003-hr2-split.md",
    4: "0004-streamlit-to-vue.md",
    5: "0005-hr4-amendment.md",
    6: "0006-torch-exception.md",
}
OWNER_APPROVED = (5, 6)
# The ingester's ADRs are 3-digit (ADR-015, ADR-016); TA must never use that
# width or the numbers collide after the monorepo merge (#161 ruling).
INGESTER_WIDTH = 3

HARNESS_TIMEOUT_S = 60  # harness bound per checker run, not product config
LINEAR_BUDGET_S = 15  # one run over MANY_ADRS files or one very long line
MANY_ADRS = 2000

# Every line-break code point beyond LF/CR that str.splitlines() or Unicode
# honours. A checker that splits on these lets a hostile line forge a heading
# or a header field.
UNICODE_LINE_BREAKS = ("\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", " ", " ")
ZWSP, ZWJ, RLO, BOM = "​", "‍", "‮", "﻿"
CYRILLIC_A, CYRILLIC_E = "А", "е"


# --------------------------------------------------------------------------
# config: the same file the checker reads, loaded lazily so that a missing
# file fails the tests that need it instead of breaking collection for the
# whole CI suite.
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Cfg:
    text: str
    adr_dir: str
    index_file: str
    digits: int
    sections: tuple[str, ...]
    statuses: tuple[str, ...]
    approval_statuses: tuple[str, ...]
    hr_prefix: str
    approvers: tuple[str, ...]
    max_doc_bytes: int

    @property
    def accepted(self) -> str:
        return self.approval_statuses[0]

    @property
    def unapproved_status(self) -> str:
        """A configured status that needs no approval (positive controls)."""
        return next(s for s in self.statuses if s not in self.approval_statuses)

    @property
    def approver(self) -> str:
        return self.approvers[0]

    @property
    def index_name(self) -> str:
        return os.path.relpath(self.index_file, self.adr_dir)


def parse_config(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.split("\n"):
        if line.strip() and not line.startswith("#"):
            key, _, value = line.partition("=")
            values[key] = value
    return values


@functools.cache
def _config_text() -> str | None:
    path = REPO_ROOT / CONFIG_REL
    return path.read_text(encoding="ascii") if path.is_file() else None


def cfg() -> Cfg:
    text = _config_text()
    if text is None:
        pytest.fail(f"{CONFIG_REL} does not exist yet (#161)")
    raw = parse_config(text)
    missing = CONFIG_KEYS - raw.keys()
    if missing:
        pytest.fail(f"{CONFIG_REL} lacks keys {sorted(missing)}")
    return Cfg(
        text=text,
        adr_dir=raw["adr_dir"],
        index_file=raw["index_file"],
        digits=int(raw["number_digits"]),
        sections=tuple(raw["required_sections"].split()),
        statuses=tuple(raw["statuses"].split()),
        approval_statuses=tuple(raw["approval_statuses"].split()),
        hr_prefix=raw["hard_requirement_prefix"],
        approvers=tuple(raw["approvers"].split()),
        max_doc_bytes=int(raw["max_doc_bytes"]),
    )


def config_with(c: Cfg, **overrides: str) -> str:
    """The real config text with some values replaced (keys must exist)."""
    lines = c.text.split("\n")
    seen: set[str] = set()
    for index, line in enumerate(lines):
        key = line.partition("=")[0]
        if key in overrides and not line.startswith("#"):
            lines[index] = f"{key}={overrides[key]}"
            seen.add(key)
    assert seen == set(overrides), f"unknown config keys: {set(overrides) - seen}"
    return "\n".join(lines)


def config_without(c: Cfg, key: str) -> str:
    return "\n".join(line for line in c.text.split("\n") if line.partition("=")[0] != key)


# --------------------------------------------------------------------------
# fixture builders
# --------------------------------------------------------------------------
OMIT = object()


def num(c: Cfg, n: int) -> str:
    return f"{n:0{c.digits}d}"


def fname(c: Cfg, n: int, slug: str = "example") -> str:
    return f"{num(c, n)}-{slug}.md"


def field_line(key: str, value: str) -> str:
    return f"- **{key}:** {value}"


def approved_line(c: Cfg) -> str:
    return field_line(APPROVED_FIELD, f"{c.approver}, {RULING_DATE}")


def hr_line(c: Cfg) -> str:
    return field_line("Governs", f"{c.hr_prefix}4 (local-only data)")


def adr(c: Cfg, n: int, *, title: str = "Example decision", status: object = None,
        fields: tuple[str, ...] = (), sections: tuple[str, ...] | None = None,
        body: str = "", header_tail: str = "", first_line: str | None = None) -> str:
    """One well-formed ADR unless an argument says otherwise."""
    status_value = c.unapproved_status if status is None else status
    head = [first_line if first_line is not None else f"# ADR {num(c, n)}: {title}", ""]
    if status_value is not OMIT:
        head.append(field_line(STATUS_FIELD, str(status_value)))
    head.append(field_line("Date", RULING_DATE))
    head.extend(fields)
    if header_tail:
        head.append(header_tail)
    parts = ["\n".join(head), ""]
    for name in (c.sections if sections is None else sections):
        parts += [f"## {name}", "", f"Text for {name}.", ""]
    if body:
        parts += [body, ""]
    return "\n".join(parts)


def valid_name_re(c: Cfg) -> re.Pattern[str]:
    return re.compile(rf"[0-9]{{{c.digits}}}-[a-z0-9-]+\.md", re.ASCII)


def index_for(c: Cfg, names: list[str]) -> str:
    rows = ["# Architecture decision records", "", "| ADR | Title |", "|---|---|"]
    rows += [f"| [{n[:c.digits]}]({n}) | Example |" for n in names]
    return "\n".join(rows) + "\n"


DEFAULT_INDEX = object()


def make_repo(tmp_path: Path, c: Cfg, adrs: dict[str, str | bytes], *,
              index: object = DEFAULT_INDEX, config_text: str | None = None) -> Path:
    root = tmp_path / "repo"
    (root / CONFIG_REL).parent.mkdir(parents=True, exist_ok=True)
    (root / CONFIG_REL).write_text(c.text if config_text is None else config_text, encoding="utf-8")
    adr_dir = root / c.adr_dir
    adr_dir.mkdir(parents=True, exist_ok=True)
    for name, content in adrs.items():
        path = adr_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_bytes(content.encode("utf-8"))
    if index is DEFAULT_INDEX:
        linked = sorted(n for n in adrs if valid_name_re(c).fullmatch(n))
        index = index_for(c, linked)
    if index is not None:
        (root / c.index_file).write_text(str(index), encoding="utf-8")
    return root


def baseline(c: Cfg, count: int = 3) -> dict[str, str | bytes]:
    return {fname(c, n): adr(c, n) for n in range(1, count + 1)}


# --------------------------------------------------------------------------
# running the checker
# --------------------------------------------------------------------------
@dataclass
class Result:
    code: int
    stdout: str
    stderr: str


def run_checker(*args: str | Path, cwd: Path | None = None, forbid: tuple[Path, ...] = ()) -> Result:
    """Run the real checker; every run must be crash-free and leak-free."""
    assert SCRIPT.is_file(), "scripts/governance/check-adrs.py does not exist yet (#161)"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, args)],
        capture_output=True, timeout=HARNESS_TIMEOUT_S, cwd=cwd or SCRIPT.parent,
    )
    out = proc.stdout.decode("utf-8", "surrogateescape")
    err = proc.stderr.decode("utf-8", "surrogateescape")
    both = out + err
    assert "Traceback" not in err, f"checker crashed:\n{err[-2000:]}"
    bad = sorted({ch for ch in both if ch != "\n" and not " " <= ch <= "~"})
    assert not bad, f"non-printable or non-ASCII output: {bad!r}"
    for path in {*forbid, *(p.resolve() for p in forbid), Path.home()}:
        assert str(path) not in both, "absolute path in checker output"
    return Result(proc.returncode, out, err)


def fail_ids(res: Result) -> list[str]:
    ids = []
    for line in res.stderr.splitlines():
        match = FAIL_LINE_RE.match(line)
        if match:
            ids.append(match.group(1))
    return ids


def assert_violations(res: Result, expected: set[str]) -> None:
    assert res.code == EXIT_VIOLATION, f"exit {res.code}\nstdout={res.stdout}\nstderr={res.stderr}"
    ids = fail_ids(res)
    assert set(ids) == expected, f"FAIL ids {sorted(set(ids))} != {sorted(expected)}\n{res.stderr}"
    lines = [line for line in res.stderr.split("\n") if line]
    assert lines[-1] == FAIL_SUMMARY.format(n=len(ids)), res.stderr
    # One line per violation: no other line exists, so a hostile name or
    # title can't forge an extra FAIL, OK or summary line.
    assert len(lines) == len(ids) + 1, res.stderr
    assert "ADR-CHECK OK" not in res.stdout


def assert_ok(res: Result, count: int) -> None:
    assert res.code == EXIT_OK, f"exit {res.code}\nstdout={res.stdout}\nstderr={res.stderr}"
    assert res.stdout.strip() == OK_LINE.format(n=count), res.stdout
    assert not fail_ids(res)


def assert_error(res: Result, ident: str) -> None:
    assert res.code == EXIT_ERROR, f"exit {res.code}\nstdout={res.stdout}\nstderr={res.stderr}"
    assert ERROR_PREFIX.format(ident=ident) in res.stderr, res.stderr
    assert "ADR-CHECK OK" not in res.stdout


def check(tmp_path: Path, root: Path) -> Result:
    return run_checker(root, cwd=tmp_path, forbid=(tmp_path,))


def fail_lines(res: Result, ident: str) -> list[str]:
    return [line for line in res.stderr.splitlines() if line.startswith(f"FAIL [{ident}]:")]


# --------------------------------------------------------------------------
# the brief's four negative vectors, plus positive controls
# --------------------------------------------------------------------------
def test_checker_passes_well_formed_adrs_with_count(tmp_path: Path) -> None:
    c = cfg()
    adrs = baseline(c)
    adrs[fname(c, 4, "approved")] = adr(c, 4, status=c.accepted, fields=(hr_line(c), approved_line(c)))
    adrs[fname(c, 5, "accepted-no-hr")] = adr(c, 5, status=c.accepted)
    adrs[fname(c, 6, "proposed-hr")] = adr(c, 6, fields=(hr_line(c),))
    assert_ok(check(tmp_path, make_repo(tmp_path, c, adrs)), 6)


def test_checker_rejects_missing_section_each_required_one(tmp_path: Path) -> None:
    c = cfg()
    assert c.sections, "required_sections is empty"
    for i, missing in enumerate(c.sections):
        adrs = baseline(c)
        name = fname(c, 2)
        adrs[name] = adr(c, 2, sections=tuple(s for s in c.sections if s != missing))
        res = check(tmp_path / str(i), make_repo(tmp_path / str(i), c, adrs))
        assert_violations(res, {"adr-section"})
        (line,) = fail_lines(res, "adr-section")
        assert name in line and missing in line, line


def test_checker_rejects_accepted_hr_adr_without_approved_by(tmp_path: Path) -> None:
    c = cfg()
    adrs = baseline(c)
    name = fname(c, 3)
    adrs[name] = adr(c, 3, status=c.accepted, fields=(hr_line(c),))
    res = check(tmp_path, make_repo(tmp_path, c, adrs))
    assert_violations(res, {"adr-approval"})
    (line,) = fail_lines(res, "adr-approval")
    assert name in line and APPROVED_FIELD in line, line


def test_checker_rejects_duplicate_number(tmp_path: Path) -> None:
    c = cfg()
    adrs = baseline(c, 2)
    adrs[fname(c, 3, "a")] = adr(c, 3)
    adrs[fname(c, 3, "b")] = adr(c, 3)
    res = check(tmp_path, make_repo(tmp_path, c, adrs))
    assert_violations(res, {"adr-number-duplicate"})
    assert all(num(c, 3) in line for line in fail_lines(res, "adr-number-duplicate"))


def test_checker_rejects_ingester_width_filename(tmp_path: Path) -> None:
    """015-hr2-split.md is exactly the card's original, now-forbidden name."""
    c = cfg()
    adrs = baseline(c, 2)
    bad = f"{15:0{c.digits - 1}d}-hr2-split.md"
    adrs[bad] = adr(c, 3)
    res = check(tmp_path, make_repo(tmp_path, c, adrs))
    assert_violations(res, {"adr-filename"})
    (line,) = fail_lines(res, "adr-filename")
    assert bad in line, line


def test_checker_rejects_gap_and_names_missing_number(tmp_path: Path) -> None:
    c = cfg()
    adrs = baseline(c, 2)
    adrs[fname(c, 4)] = adr(c, 4)
    res = check(tmp_path, make_repo(tmp_path, c, adrs))
    assert_violations(res, {"adr-number-gap"})
    assert num(c, 3) in " ".join(fail_lines(res, "adr-number-gap"))


def test_checker_rejects_unindexed_adr_and_names_it(tmp_path: Path) -> None:
    c = cfg()
    adrs = baseline(c)
    res = check(tmp_path, make_repo(tmp_path, c, adrs, index=index_for(c, sorted(adrs)[:-1])))
    assert_violations(res, {"adr-index"})
    assert sorted(adrs)[-1] in " ".join(fail_lines(res, "adr-index"))


# --------------------------------------------------------------------------
# hostile vectors, table-driven. Each builds the ADR mapping (and maybe an
# index) from the config; expect is the exact FAIL id set (empty = must pass).
# --------------------------------------------------------------------------
Build = Callable[[Cfg], tuple[dict[str, str | bytes], object]]


@dataclass(frozen=True)
class Vector:
    family: str
    name: str
    build: Build
    expect: frozenset[str] = field(default_factory=frozenset)


def v(family: str, name: str, expect: set[str], adr_n: Callable[[Cfg], tuple[int, str]] | None = None,
      build: Build | None = None) -> Vector:
    """adr_n(c) -> (number, text): replace baseline ADR <number> with text."""
    if build is None:
        assert adr_n is not None

        def build(c: Cfg, _f: Callable[[Cfg], tuple[int, str]] = adr_n) -> tuple[dict[str, str | bytes], object]:
            n, text = _f(c)
            adrs = baseline(c)
            adrs[fname(c, n)] = text
            return adrs, DEFAULT_INDEX
    return Vector(family, name, build, frozenset(expect))


def _fenced(lines: str) -> str:
    return "```text\n" + lines + "\n```"


def _commented(lines: str) -> str:
    return "<!--\n" + lines + "\n-->"


def _without_decision(c: Cfg) -> tuple[str, ...]:
    return tuple(s for s in c.sections if s != c.sections[1 % len(c.sections)])


def _target_section(c: Cfg) -> str:
    return c.sections[1 % len(c.sections)]


def _accepted_hr(c: Cfg, *extra: str, header_tail: str = "", body: str = "") -> str:
    return adr(c, 2, status=c.accepted, fields=(hr_line(c), *extra), header_tail=header_tail, body=body)


def _crlf(c: Cfg) -> tuple[int, str]:
    return 2, adr(c, 2).replace("\n", "\r\n")


VECTORS: list[Vector] = [
    # --- section: headings are level-2, outside fences/comments, real text
    v("section", "all-sections-present", set(), lambda c: (2, adr(c, 2))),
    v("section", "crlf-line-endings", set(), _crlf),
    v("section", "only-inside-code-fence", {"adr-section"}, lambda c: (
        2, adr(c, 2, sections=_without_decision(c), body=_fenced(f"## {_target_section(c)}")))),
    v("section", "only-inside-html-comment", {"adr-section"}, lambda c: (
        2, adr(c, 2, sections=_without_decision(c), body=_commented(f"## {_target_section(c)}")))),
    v("section", "level-3-heading", {"adr-section"}, lambda c: (
        2, adr(c, 2, sections=_without_decision(c), body=f"### {_target_section(c)}"))),
    v("section", "zero-width-space-in-heading", {"adr-section"}, lambda c: (
        2, adr(c, 2, sections=_without_decision(c),
               body=f"## {_target_section(c)[:2]}{ZWSP}{_target_section(c)[2:]}"))),
    v("section", "cyrillic-lookalike-heading", {"adr-section"}, lambda c: (
        2, adr(c, 2, sections=_without_decision(c),
               body=f"## {_target_section(c).replace('e', CYRILLIC_E, 1)}"))),
    *[
        v("section", f"forged-after-U+{ord(br):04X}", {"adr-section"}, lambda c, br=br: (
            2, adr(c, 2, sections=_without_decision(c), body=f"Prose.{br}## {_target_section(c)}")))
        for br in UNICODE_LINE_BREAKS
    ],
    # --- approval: Accepted + HR in header needs a configured approver token
    v("approval", "accepted-hr-approved", set(), lambda c: (2, _accepted_hr(c, approved_line(c)))),
    v("approval", "proposed-hr-unapproved", set(), lambda c: (2, adr(c, 2, fields=(hr_line(c),)))),
    v("approval", "accepted-no-hr-unapproved", set(), lambda c: (2, adr(c, 2, status=c.accepted))),
    v("approval", "accepted-with-note-hr-approved", set(), lambda c: (
        2, adr(c, 2, status=f"{c.accepted} (owner merge of the PR)", fields=(hr_line(c), approved_line(c))))),
    v("approval", "hr-in-title-only", {"adr-approval"}, lambda c: (
        2, adr(c, 2, status=c.accepted, title=f"{c.hr_prefix}4 amendment"))),
    v("approval", "hr-in-governs-unapproved", {"adr-approval"}, lambda c: (2, _accepted_hr(c))),
    v("approval", "approver-not-configured", {"adr-approval"}, lambda c: (
        2, _accepted_hr(c, field_line(APPROVED_FIELD, f"@mallory, {RULING_DATE}")))),
    v("approval", "approver-empty", {"adr-approval"}, lambda c: (
        2, _accepted_hr(c, f"- **{APPROVED_FIELD}:**"))),
    v("approval", "approver-prefix-of-longer-handle", {"adr-approval"}, lambda c: (
        2, _accepted_hr(c, field_line(APPROVED_FIELD, f"{c.approver}-evil, {RULING_DATE}")))),
    v("approval", "approver-with-zero-width-joiner", {"adr-approval"}, lambda c: (
        2, _accepted_hr(c, field_line(APPROVED_FIELD, f"{c.approver[:3]}{ZWJ}{c.approver[3:]}, {RULING_DATE}")))),
    v("approval", "approver-with-trailing-zwsp", {"adr-approval"}, lambda c: (
        2, _accepted_hr(c, field_line(APPROVED_FIELD, f"{c.approver}{ZWSP}, {RULING_DATE}")))),
    v("approval", "cyrillic-lookalike-key", {"adr-approval"}, lambda c: (
        2, _accepted_hr(c, field_line(CYRILLIC_A + APPROVED_FIELD[1:], f"{c.approver}, {RULING_DATE}")))),
    v("approval", "approved-by-in-body-only", {"adr-approval"}, lambda c: (
        2, _accepted_hr(c, body=approved_line(c)))),
    v("approval", "approved-by-in-header-comment", {"adr-approval"}, lambda c: (
        2, _accepted_hr(c, header_tail=_commented(approved_line(c))))),
    v("approval", "approved-by-in-header-fence", {"adr-approval"}, lambda c: (
        2, _accepted_hr(c, header_tail=_fenced(approved_line(c))))),
    *[
        v("approval", f"approved-by-forged-after-U+{ord(br):04X}", {"adr-approval"}, lambda c, br=br: (
            2, _accepted_hr(c, field_line("Note", "see below") + br + approved_line(c))))
        for br in UNICODE_LINE_BREAKS
    ],
    # --- status
    v("status", "status-with-trailing-note", set(), lambda c: (2, adr(c, 2, status=f"{c.accepted} (see PR)"))),
    v("status", "status-missing", {"adr-status"}, lambda c: (2, adr(c, 2, status=OMIT))),
    v("status", "status-unknown-word", {"adr-status"}, lambda c: (2, adr(c, 2, status=c.accepted + "x"))),
    v("status", "status-zero-width-split", {"adr-status"}, lambda c: (
        2, adr(c, 2, status=c.accepted[:3] + ZWSP + c.accepted[3:]))),
    # --- title: the H1 number must be the filename's number
    v("title", "title-matches", set(), lambda c: (2, adr(c, 2))),
    v("title", "title-claims-other-number", {"adr-title"}, lambda c: (
        2, adr(c, 2, first_line=f"# ADR {num(c, 3)}: Forged number"))),
    v("title", "title-missing", {"adr-title"}, lambda c: (2, adr(c, 2, first_line="Example decision"))),
    # A control character makes the H1 not a heading; the FAIL line must not
    # echo it (run_checker asserts printable-ASCII output).
    v("title", "title-escape-sequence", {"adr-title"}, lambda c: (
        2, adr(c, 2, title="\x1b[2J\x1b[31mred"))),
    # --- numbers
    v("number", "contiguous-from-one", set(), build=lambda c: (baseline(c, 4), DEFAULT_INDEX)),
    v("number", "starts-at-zero", {"adr-number-gap"}, build=lambda c: (
        {fname(c, 0): adr(c, 0), **baseline(c, 2)}, DEFAULT_INDEX)),
    v("number", "starts-at-two", {"adr-number-gap"}, build=lambda c: (
        {fname(c, 2): adr(c, 2), fname(c, 3): adr(c, 3)}, DEFAULT_INDEX)),
    # --- filename: width, digit script, slug, extension, layout, injection
    v("filename", "four-digit-ascii", set(), build=lambda c: (baseline(c), DEFAULT_INDEX)),
    *[
        v("filename", label, {"adr-filename"}, build=lambda c, mk=mk: (
            {**baseline(c, 2), mk(c): adr(c, 3)}, DEFAULT_INDEX))
        for label, mk in (
            ("one-digit-too-wide", lambda c: f"{3:0{c.digits + 1}d}-wide.md"),
            ("fullwidth-digits", lambda c: num(c, 3).translate({ord(d): 0xFF10 + int(d) for d in "0123456789"})
             + "-x.md"),
            ("arabic-indic-digits", lambda c: num(c, 3).translate({ord(d): 0x0660 + int(d) for d in "0123456789"})
             + "-x.md"),
            ("uppercase-slug", lambda c: f"{num(c, 3)}-HR2.md"),
            ("markdown-extension", lambda c: f"{num(c, 3)}-x.markdown"),
            ("no-extension", lambda c: f"{num(c, 3)}-x"),
            ("subdirectory", lambda c: f"drafts/{num(c, 3)}-x.md"),
            ("bidi-override-in-name", lambda c: f"{num(c, 3)}-x{RLO}dm.md"),
            ("newline-forges-ok-line", lambda c: f"{num(c, 3)}-x\nADR-CHECK OK: 99 ADR(s)\n.md"),
            ("escape-sequence-in-name", lambda c: f"{num(c, 3)}-x\x1b[2J.md"),
        )
    ],
    # --- index
    v("index", "every-adr-linked", set(), build=lambda c: (baseline(c), DEFAULT_INDEX)),
    v("index", "dot-slash-links", set(), build=lambda c: (
        baseline(c), index_for(c, sorted(baseline(c))).replace("](", "](./"))),
    v("index", "index-missing", {"adr-index"}, build=lambda c: (baseline(c), None)),
    v("index", "link-only-in-html-comment", {"adr-index"}, build=lambda c: (
        baseline(c), index_for(c, sorted(baseline(c))[:-1]) + _commented(f"[x]({sorted(baseline(c))[-1]})"))),
    v("index", "link-only-in-code-fence", {"adr-index"}, build=lambda c: (
        baseline(c), index_for(c, sorted(baseline(c))[:-1]) + _fenced(f"[x]({sorted(baseline(c))[-1]})"))),
    v("index", "link-to-missing-adr", {"adr-index"}, build=lambda c: (
        baseline(c), index_for(c, [*sorted(baseline(c)), fname(c, 9, "ghost")]))),
    # --- file: encoding and size
    v("file", "exactly-max-doc-bytes", set(), lambda c: (2, _sized(c, c.max_doc_bytes))),
    v("file", "one-over-max-doc-bytes", {"adr-file"}, lambda c: (2, _sized(c, c.max_doc_bytes + 1))),
    v("file", "invalid-utf8-byte", {"adr-file"}, lambda c: (2, adr(c, 2).encode() + b"\xff\n")),
    v("file", "encoded-lone-surrogate", {"adr-file"}, lambda c: (2, adr(c, 2).encode() + b"\xed\xa0\x80\n")),
    v("file", "nul-byte", {"adr-file"}, lambda c: (2, adr(c, 2).encode() + b"\x00\n")),
    v("file", "overlong-utf8", {"adr-file"}, lambda c: (2, adr(c, 2).encode() + b"\xc0\xaf\n")),
]


def _sized(c: Cfg, size: int) -> bytes:
    """A valid ADR padded inside its first section to exactly size bytes."""
    text = adr(c, 2).encode()
    marker = f"Text for {c.sections[0]}.".encode()
    pad = size - len(text)
    assert pad > 0, "max_doc_bytes is smaller than a minimal ADR"
    return text.replace(marker, marker + b"a" * pad, 1)


@pytest.mark.parametrize("vector", VECTORS, ids=[f"{x.family}:{x.name}" for x in VECTORS])
def test_hostile_vector(vector: Vector, tmp_path: Path) -> None:
    c = cfg()
    adrs, index = vector.build(c)
    root = make_repo(tmp_path, c, adrs, index=index)
    res = check(tmp_path, root)
    if vector.expect:
        assert_violations(res, set(vector.expect))
    else:
        assert_ok(res, sum(1 for n in adrs if valid_name_re(c).fullmatch(n)))


def test_vector_table_contract() -> None:
    """Every family has at least one passing and one failing vector (R2)."""
    families: dict[str, set[bool]] = {}
    for vector in VECTORS:
        families.setdefault(vector.family, set()).add(bool(vector.expect))
    incomplete = sorted(f for f, kinds in families.items() if kinds != {True, False})
    assert not incomplete, f"families without both a positive and a negative vector: {incomplete}"
    names = [f"{x.family}:{x.name}" for x in VECTORS]
    assert len(names) == len(set(names))
    generated = sum(1 for n in names if "forged-after-U+" in n)
    assert generated == 2 * len(UNICODE_LINE_BREAKS)
    print(f"{len(VECTORS)} vectors, {generated} generated line-break vectors")


# --------------------------------------------------------------------------
# indirection, size and time, "did nothing", usage
# --------------------------------------------------------------------------
def test_symlinked_adr_is_rejected(tmp_path: Path) -> None:
    c = cfg()
    adrs = baseline(c, 2)
    root = make_repo(tmp_path, c, {**adrs, fname(c, 3): adr(c, 3)})
    outside = tmp_path / "outside.md"
    outside.write_text(adr(c, 3), encoding="utf-8")
    target = root / c.adr_dir / fname(c, 3)
    target.unlink()
    target.symlink_to(outside)
    assert_violations(check(tmp_path, root), {"adr-file"})


def test_symlinked_index_is_rejected(tmp_path: Path) -> None:
    c = cfg()
    adrs = baseline(c)
    root = make_repo(tmp_path, c, adrs)
    outside = tmp_path / "outside-index.md"
    outside.write_text(index_for(c, sorted(adrs)), encoding="utf-8")
    (root / c.index_file).unlink()
    (root / c.index_file).symlink_to(outside)
    assert_violations(check(tmp_path, root), {"adr-file"})


def test_symlinked_adr_dir_is_an_error(tmp_path: Path) -> None:
    c = cfg()
    real = make_repo(tmp_path / "real", c, baseline(c))
    root = tmp_path / "repo"
    (root / CONFIG_REL).parent.mkdir(parents=True)
    (root / CONFIG_REL).write_text(c.text, encoding="utf-8")
    (root / c.adr_dir).parent.mkdir(parents=True, exist_ok=True)
    (root / c.adr_dir).symlink_to(real / c.adr_dir)
    assert_error(check(tmp_path, root), "adr-dir")


def test_missing_adr_dir_is_an_error(tmp_path: Path) -> None:
    c = cfg()
    root = tmp_path / "repo"
    (root / CONFIG_REL).parent.mkdir(parents=True)
    (root / CONFIG_REL).write_text(c.text, encoding="utf-8")
    assert_error(check(tmp_path, root), "adr-dir")


def test_no_adrs_is_not_success(tmp_path: Path) -> None:
    """F5: an empty ADR directory is "did nothing", never exit 0."""
    c = cfg()
    assert_violations(check(tmp_path, make_repo(tmp_path, c, {})), {"adr-none"})


def test_checks_repo_root_argument_not_cwd(tmp_path: Path) -> None:
    c = cfg()
    bad = make_repo(tmp_path / "bad", c, {fname(c, 2): adr(c, 2)})
    good = make_repo(tmp_path / "good", c, baseline(c))
    assert_ok(run_checker(good, cwd=bad, forbid=(tmp_path,)), 3)


def test_default_root_is_the_script_repo_not_cwd(tmp_path: Path) -> None:
    c = cfg()
    bad = make_repo(tmp_path, c, {fname(c, 2): adr(c, 2)})
    explicit = run_checker(REPO_ROOT, cwd=tmp_path)
    implicit = run_checker(cwd=bad, forbid=(tmp_path,))
    assert (implicit.code, implicit.stdout) == (explicit.code, explicit.stdout)


@pytest.mark.parametrize("args", [("a", "b"), ("a", "b", "c")], ids=["two-args", "three-args"])
def test_extra_arguments_are_a_usage_error(args: tuple[str, ...], tmp_path: Path) -> None:
    assert_error(run_checker(*args, cwd=tmp_path), "usage")


def test_missing_repo_root_is_an_error(tmp_path: Path) -> None:
    assert_error(check(tmp_path, tmp_path / "does-not-exist"), "root")


def test_many_adrs_finish_within_budget(tmp_path: Path) -> None:
    c = cfg()
    adrs = {fname(c, n): adr(c, n) for n in range(1, MANY_ADRS + 1)}
    root = make_repo(tmp_path, c, adrs)
    start = time.monotonic()
    res = check(tmp_path, root)
    elapsed = time.monotonic() - start
    assert_ok(res, MANY_ADRS)
    assert elapsed < LINEAR_BUDGET_S, f"{MANY_ADRS} ADRs took {elapsed:.1f}s"


def test_one_long_hostile_line_finishes_within_budget(tmp_path: Path) -> None:
    c = cfg()
    unit = "<!-- -->`*_[]("
    line = unit * ((c.max_doc_bytes // 2) // len(unit))
    adrs = baseline(c)
    adrs[fname(c, 2)] = adr(c, 2, header_tail=field_line("Note", line[: c.max_doc_bytes // 4]), body=line)
    assert len(adrs[fname(c, 2)].encode()) <= c.max_doc_bytes
    root = make_repo(tmp_path, c, adrs)
    start = time.monotonic()
    res = check(tmp_path, root)
    elapsed = time.monotonic() - start
    assert_ok(res, 3)
    assert elapsed < LINEAR_BUDGET_S, f"long line took {elapsed:.1f}s"


def test_violations_in_many_files_are_all_reported(tmp_path: Path) -> None:
    """Each broken ADR gets its own line; the summary count is exact."""
    c = cfg()
    adrs = {fname(c, n): adr(c, n, sections=_without_decision(c)) for n in range(1, 6)}
    res = check(tmp_path, make_repo(tmp_path, c, adrs))
    assert_violations(res, {"adr-section"})
    assert len(fail_lines(res, "adr-section")) == 5


# --------------------------------------------------------------------------
# config fails closed at load (F13)
# --------------------------------------------------------------------------
BAD_CONFIGS: list[tuple[str, Callable[[Cfg], str]]] = [
    ("unknown-key", lambda c: c.text + "\nsurprise=1\n"),
    ("duplicate-key", lambda c: c.text + f"\nnumber_digits={c.digits}\n"),
    ("line-without-equals", lambda c: c.text + "\nnumber_digits\n"),
    ("non-ascii-byte", lambda c: c.text + "\n# café\n"),
    ("nul-byte", lambda c: c.text + "\n#\x00\n"),
    *[(f"missing-{key}", lambda c, key=key: config_without(c, key)) for key in sorted(CONFIG_KEYS)],
    *[
        (f"number_digits={bad!r}", lambda c, bad=bad: config_with(c, number_digits=bad))
        for bad in ("", "0", "-1", "four", "4.0", " 4", "٤", "４")
    ],
    *[
        (f"max_doc_bytes={bad!r}", lambda c, bad=bad: config_with(c, max_doc_bytes=bad))
        for bad in ("", "0", "-5", "1e6", "١٠٠")
    ],
    ("approvers-empty", lambda c: config_with(c, approvers="")),
    ("approvers-without-at", lambda c: config_with(c, approvers=c.approver.lstrip("@"))),
    ("approvers-bare-at", lambda c: config_with(c, approvers="@")),
    ("required_sections-empty", lambda c: config_with(c, required_sections="")),
    ("statuses-empty", lambda c: config_with(c, statuses="")),
    ("approval_statuses-not-a-status", lambda c: config_with(c, approval_statuses=c.accepted + "x")),
    ("approval_statuses-empty", lambda c: config_with(c, approval_statuses="")),
    ("hard_requirement_prefix-empty", lambda c: config_with(c, hard_requirement_prefix="")),
    ("adr_dir-traversal", lambda c: config_with(c, adr_dir="../outside")),
    ("adr_dir-absolute", lambda c: config_with(c, adr_dir="/tmp/adr")),
    ("index_file-absolute", lambda c: config_with(c, index_file="/etc/passwd")),
    ("index_file-traversal", lambda c: config_with(c, index_file=f"{c.adr_dir}/../../x.md")),
]


@pytest.mark.parametrize("label,make", BAD_CONFIGS, ids=[b[0] for b in BAD_CONFIGS])
def test_bad_config_fails_closed(label: str, make: Callable[[Cfg], str], tmp_path: Path) -> None:
    c = cfg()
    assert_error(check(tmp_path, make_repo(tmp_path, c, baseline(c), config_text=make(c))), "config")


def test_missing_config_fails_closed(tmp_path: Path) -> None:
    c = cfg()
    root = make_repo(tmp_path, c, baseline(c))
    (root / CONFIG_REL).unlink()
    assert_error(check(tmp_path, root), "config")


def test_config_overrides_are_honoured(tmp_path: Path) -> None:
    """The width comes from config, not a literal: one wider works end to end."""
    c = cfg()
    wide = Cfg(**{**c.__dict__, "digits": c.digits + 1,
                  "text": config_with(c, number_digits=str(c.digits + 1))})
    assert_ok(check(tmp_path / "w", make_repo(tmp_path / "w", wide, baseline(wide), config_text=wide.text)), 3)
    res = check(tmp_path / "n", make_repo(tmp_path / "n", c, baseline(c), config_text=wide.text))
    assert "adr-filename" in fail_ids(res)


def test_config_has_exactly_the_contract_keys() -> None:
    c = cfg()
    raw = parse_config(c.text)
    assert set(raw) == CONFIG_KEYS
    assert c.index_file.startswith(c.adr_dir + "/"), "index_file must live in adr_dir"
    assert all(a.startswith("@") and len(a) > 1 for a in c.approvers)
    assert set(c.approval_statuses) <= set(c.statuses)


# --------------------------------------------------------------------------
# this checkout: wiring (CI runs this file) and the settled decisions
# --------------------------------------------------------------------------
def test_real_repo_passes_the_checker() -> None:
    c = cfg()
    count = sum(1 for p in (REPO_ROOT / c.adr_dir).iterdir() if p.name != c.index_name)
    assert count >= len(TARGET_ADRS)
    assert_ok(run_checker(REPO_ROOT), count)


def test_real_repo_has_the_target_adr_files() -> None:
    c = cfg()
    missing = [name for name in TARGET_ADRS.values() if not (REPO_ROOT / c.adr_dir / name).is_file()]
    assert not missing, f"missing ADR files: {missing}"


def test_real_repo_has_no_ingester_width_adr_numbers() -> None:
    """Green today and must stay green: 015-017 were renumbered (#161 ruling)."""
    adr_dir = REPO_ROOT / "docs" / "adr"
    clashing = sorted(p.name for p in adr_dir.iterdir() if re.match(rf"[0-9]{{{INGESTER_WIDTH}}}-", p.name))
    assert not clashing, f"3-digit ADR files collide with the ingester's ADR-015/016: {clashing}"


def test_real_index_links_each_target_adr() -> None:
    c = cfg()
    text = strip_non_structure((REPO_ROOT / c.index_file).read_text(encoding="utf-8"))
    unlinked = [name for name in TARGET_ADRS.values() if not re.search(rf"\]\((\./)?{re.escape(name)}\)", text)]
    assert not unlinked, f"index does not link: {unlinked}"


def strip_non_structure(text: str) -> str:
    """Drop code fences and HTML comments (test oracle, LF lines only)."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    out, fenced = [], False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if not fenced:
            out.append(line)
    return "\n".join(out)


def sections_of(text: str) -> dict[str, str]:
    """Level-2 heading -> body; key "" is the header."""
    parts: dict[str, str] = {"": ""}
    current = ""
    for line in strip_non_structure(text).split("\n"):
        if line.startswith("## "):
            current = line[3:].strip()
            parts.setdefault(current, "")
        else:
            parts[current] += line + "\n"
    return parts


def header_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in sections_of(text)[""].split("\n"):
        match = re.fullmatch(r"- \*\*([A-Za-z-]+):\*\*\s*(.*)", line.rstrip("\r"))
        if match:
            fields[match.group(1)] = match.group(2)
    return fields


def read_adr(n: int) -> str:
    path = REPO_ROOT / "docs" / "adr" / TARGET_ADRS[n]
    if not path.is_file():
        pytest.fail(f"{TARGET_ADRS[n]} does not exist yet")
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("n", OWNER_APPROVED, ids=[TARGET_ADRS[n] for n in OWNER_APPROVED])
def test_owner_approved_adrs_are_accepted_with_dated_approval(n: int) -> None:
    c = cfg()
    fields = header_fields(read_adr(n))
    assert fields.get(STATUS_FIELD, "").split()[:1] == [c.accepted], fields
    tokens = re.split(r"[\s,;]+", fields.get(APPROVED_FIELD, ""))
    assert set(tokens) & set(c.approvers), f"{APPROVED_FIELD} names no configured approver: {fields}"
    assert RULING_DATE in tokens, f"{APPROVED_FIELD} lacks the ruling date {RULING_DATE}: {fields}"


# Static, pinned identifiers per ADR: (where, identifiers). "decision" is the
# Decision section plus an optional Conditions section; "body" is every
# section after the header.
ADR_POINTS: dict[int, list[tuple[str, tuple[str, ...]]]] = {
    3: [
        ("decision", ("HR2a", "HR2b", "CycloneDX", "SPDX")),
        ("body", ("R1",)),
    ],
    4: [
        ("decision", ("Vue 3", "Vite", "Capacitor", "Streamlit")),
        ("body", ("D2",)),
    ],
    5: [
        ("decision", ("HR4", "Railway", "railtail")),
        ("body", ("D10",)),
    ],
    6: [
        # scope: only as the runtime dependency of the approved package
        ("decision", ("sentence-transformers[onnx]", "torch>=2.2", "#152", "#330")),
        # grounds
        ("decision", ("HR2b", "BSD-3", "PyTorch Foundation", "Linux Foundation")),
        # conditions
        ("decision", ("pinned", "CPU", "pip-audit", "HR3", "model weights", "import torch")),
        # supersedes the S5 "no exceptions" wording for this case
        ("body", ("LIB-STACK", "S5")),
    ],
}


@pytest.mark.parametrize("n", sorted(ADR_POINTS), ids=[TARGET_ADRS[n] for n in sorted(ADR_POINTS)])
def test_adr_records_the_settled_decision(n: int) -> None:
    c = cfg()
    parts = sections_of(read_adr(n))
    missing_sections = [s for s in c.sections if s not in parts]
    assert not missing_sections, f"{TARGET_ADRS[n]} lacks sections {missing_sections}"
    decision = parts.get("Decision", "") + parts.get("Conditions", "")
    body = "".join(text for name, text in parts.items() if name)
    where = {"decision": decision, "body": body}
    missing = [
        ident for scope, idents in ADR_POINTS[n] for ident in idents
        if not re.search(rf"(?<![\w-]){re.escape(ident)}(?![\w])", where[scope])
    ]
    assert not missing, f"{TARGET_ADRS[n]} does not record: {missing}"


def test_adr_points_table_covers_every_new_adr() -> None:
    assert sorted(ADR_POINTS) == [n for n in TARGET_ADRS if n > 2]


CITE_RE = {n: re.compile(rf"ADR[ -]{n:04d}(?!\d)|adr/{re.escape(TARGET_ADRS[n])}") for n in TARGET_ADRS}


def hr_entries(prefix: str) -> str:
    text = (REPO_ROOT / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
    lines = [line for line in text.split("\n") if re.match(rf"- {prefix}[a-z]?(?![0-9])", line)]
    assert lines, f"no {prefix} entry in .claude/CLAUDE.md"
    return "\n".join(lines)


@pytest.mark.parametrize("prefix,adrs", [("HR2", (3, 6)), ("HR4", (5,))], ids=["HR2", "HR4"])
def test_claude_md_hard_requirement_cites_its_adrs(prefix: str, adrs: tuple[int, ...]) -> None:
    text = hr_entries(prefix)
    uncited = [TARGET_ADRS[n] for n in adrs if not CITE_RE[n].search(text)]
    assert not uncited, f"{prefix} entries in .claude/CLAUDE.md do not cite {uncited}"


TORCH_RE = re.compile(r"\btorch\b|sentence-transformers")


def uncited_torch_mentions(text: str, *, prose: bool) -> list[str]:
    """Table rows (and, if prose, heading blocks) mentioning torch or
    sentence-transformers that don't cite ADR 0006."""
    bad: list[str] = []
    blocks: list[tuple[str, list[str]]] = [("(top)", [])]
    for line in text.split("\n"):
        if line.startswith("#"):
            blocks.append((line, []))
        else:
            blocks[-1][1].append(line)
    for heading, lines in blocks:
        rows = [line for line in lines if line.lstrip().startswith("|")]
        bad += [row[:120] for row in rows if TORCH_RE.search(row) and not CITE_RE[6].search(row)]
        if prose:
            rest = "\n".join(line for line in lines if not line.lstrip().startswith("|"))
            if TORCH_RE.search(heading + rest) and not CITE_RE[6].search(heading + rest):
                bad.append(heading[:120])
    return bad


def test_lib_stack_s5_cites_the_torch_exception() -> None:
    text = (REPO_ROOT / ".claude" / "library" / "LIB-STACK.md").read_text(encoding="utf-8")
    match = re.search(r"^### S5:.*?(?=^#|\Z)", text, flags=re.MULTILINE | re.DOTALL)
    assert match, "LIB-STACK has no S5 section"
    assert CITE_RE[6].search(match.group(0)), "S5 does not cite ADR 0006"
    assert "no exceptions" not in match.group(0), "S5 still says 'no exceptions' (superseded by ADR 0006)"


def test_lib_stack_torch_and_sentence_transformers_cite_adr_0006() -> None:
    text = (REPO_ROOT / ".claude" / "library" / "LIB-STACK.md").read_text(encoding="utf-8")
    assert TORCH_RE.search(text), "positive control: LIB-STACK mentions torch"
    bad = uncited_torch_mentions(text, prose=True)
    assert not bad, f"LIB-STACK torch/sentence-transformers entries without ADR 0006: {bad}"


def test_lib_legal_torch_rows_cite_adr_0006() -> None:
    text = (REPO_ROOT / ".claude" / "library" / "LIB-LEGAL.md").read_text(encoding="utf-8")
    bad = uncited_torch_mentions(text, prose=False)
    assert not bad, f"LIB-LEGAL torch/sentence-transformers rows without ADR 0006: {bad}"
