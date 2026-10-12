"""The repository is licensed under Apache-2.0 (#333, HR1, BRD "Open source GitHub repository").

Owner ruling, 2026-10-12: "Apache sounds good". Acceptance, as tested here:

- ``LICENSE`` at the repository root is the verbatim Apache License 2.0 text
  published at ``CANONICAL_LICENSE_URL``, byte for byte. The SHA-256 below was
  taken from a fresh download of that URL on 2026-10-11 (11358 bytes, ASCII,
  LF line endings); it equals the digest SPDX tooling publishes for that file.
  The title line, the end-of-terms line and the nine numbered sections are also
  checked separately, so a failure says what is wrong, not only "hash differs".
- ``NOTICE`` at the root names the project (the README's single H1 title, the
  project-name source) and carries exactly one copyright line,
  ``NOTICE_COPYRIGHT_LINE``.
- Every tracked packaging file (``pyproject.toml``, ``setup.cfg``, ``setup.py``)
  declares ``Apache-2.0``. None is tracked on the base commit, so that test is
  green by construction today; its checker is pinned by vectors below.
- The README ``License`` section names ``Apache-2.0`` and links ``LICENSE``.
- No file that speaks for this project claims a conflicting licence, and the
  only licence-named files in the tree are the root ``LICENSE`` and ``NOTICE``.
  "Speaks for the project" excludes only the listed third-party and historical
  prefixes; the status docs at the top of ``docs/`` are scanned (PR #350 r2).
- No project markdown still shows the licence decision ("License selection",
  "Open source GitHub repository") as an unchecked task-list item.

The licence facts below are this card's acceptance values, defined once here
(F10). No product code reads them, so there is no config to load them from.
Files are prose or fixed legal text, so most checks are static by necessity;
each checker is pinned by a vectors table (positive and negative rows, with a
contract test) and by hostile characters generated per Unicode category, so a
weakened checker goes red here instead of letting a bad licence through.
"""
from __future__ import annotations

import ast
import configparser
import hashlib
import re
import subprocess
import sys
import tomllib
import unicodedata
from pathlib import Path, PurePosixPath

import pytest

from tests.test_docs_readme import (
    REPO_ROOT,
    DocCheckError,
    _find_section,
    _forbidden_chars,
    _headings,
    _lines,
    _read_text,
    _show,
)

# --------------------------------------------------------------------------
# Acceptance values (#333). Repo-relative paths only, so messages carry no
# absolute paths (F8).
# --------------------------------------------------------------------------

LICENSE_REL = "LICENSE"
NOTICE_REL = "NOTICE"
README_REL = "README.md"
LICENSE_SPDX_ID = "Apache-2.0"

CANONICAL_LICENSE_URL = "https://www.apache.org/licenses/LICENSE-2.0.txt"
CANONICAL_LICENSE_SHA256 = "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"
LICENSE_TITLE_LINES: tuple[str, ...] = ("Apache License", "Version 2.0, January 2004")
LICENSE_END_MARKER = "END OF TERMS AND CONDITIONS"
LICENSE_SECTION_COUNT = 9
# Canonical section headings are indented three spaces: "   1. Definitions."
_LICENSE_SECTION_LINE = re.compile(r"^ {3}(\d+)\. \S")

NOTICE_COPYRIGHT_LINE = "Copyright 2026 Jennifer McKinney"
README_LICENSE_HEADING = "License"

# Accepted link targets for the README's LICENSE link (repo-root relative).
LICENSE_LINK_TARGETS: frozenset[str] = frozenset({"LICENSE", "./LICENSE"})

PACKAGING_BASENAMES: frozenset[str] = frozenset({"pyproject.toml", "setup.cfg", "setup.py"})

# Basenames that declare a licence or notice. Only the root LICENSE and NOTICE
# may exist; any other one (a vendored tree, a stray LICENSE.md) needs a ruling.
_LICENCE_FILE_NAME = re.compile(r"^(?:licen[cs]e|copying|notice)(?:[.-].*)?$", re.IGNORECASE)

# Directory prefixes excluded from the conflicting-claim and checklist scans,
# each with its reason. Only third-party descriptions and historical records
# are excluded; everything else in the tracked tree speaks for the project,
# including the status docs at the top of docs/ (BRD, PRD, PROJECT_STRUCTURE).
# Round 2 (PR #350): the whole of docs/ used to be excluded, which hid stale
# licence checklist items in those status docs.
CLAIM_SCAN_EXCLUDED_PREFIXES: dict[str, str] = {
    "docs/research/": "research notes describe third-party tools and their licences",
    "docs/reports/": "technology reports quote dependency licences (e.g. a vendor's MIT pledge)",
    "docs/plans/": "dated plans cite dependency and corpus licences (MIT models, (c) ICJ)",
    "docs/evidence/": "historical review and run evidence; quotes findings and scanner output",
}
_EXCLUDED_PREFIX_PARTS: tuple[tuple[str, ...], ...] = tuple(
    PurePosixPath(prefix).parts for prefix in CLAIM_SCAN_EXCLUDED_PREFIXES
)

# This module holds conflicting phrases as test vectors, so the scan skips
# it by its own path (derived, not restated). Residual: a claim planted in
# this file is not scanned; review covers it.
THIS_MODULE_REL = Path(__file__).resolve().relative_to(REPO_ROOT.resolve()).as_posix()

GIT_TIMEOUT_S = 30


# --------------------------------------------------------------------------
# Readers (refuse symlinks, escapes and missing files: F7, F5)
# --------------------------------------------------------------------------


def _read_bytes(root: Path, rel: str) -> bytes:
    path = root / rel
    if path.is_symlink():
        raise DocCheckError(f"{rel} is a symlink; it must be the tracked file itself")
    if not path.is_file():
        raise DocCheckError(f"{rel} is missing at the repository root")
    if not path.resolve().is_relative_to(root.resolve()):
        raise DocCheckError(f"{rel} resolves outside the repository")
    return path.read_bytes()


def _git(*args: str) -> bytes:
    """Run git in the repository, bounded in time; fail closed on any error."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(REPO_ROOT), *args],
            capture_output=True,
            timeout=GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DocCheckError(f"git {args[0]} could not run ({type(exc).__name__})") from exc
    if proc.returncode != 0:
        raise DocCheckError(
            f"git {args[0]} exited {proc.returncode}: "
            f"{_show(proc.stderr.decode('utf-8', 'replace').strip())}"
        )
    return proc.stdout


def _tracked_paths() -> list[str]:
    raw = _git("ls-files", "-z")
    paths = [p.decode("utf-8", "surrogateescape") for p in raw.split(b"\0") if p]
    if not paths:
        raise DocCheckError("git ls-files listed no tracked files; the scan would check nothing")
    return paths


# --------------------------------------------------------------------------
# Checkers. Each returns a list of problems; [] means the input passes.
# --------------------------------------------------------------------------


def _byte_problems(raw: bytes, *, ascii_only: bool) -> list[str]:
    """Encoding and hidden-character hygiene for a root legal file."""
    problems: list[str] = []
    if raw.startswith(b"\xef\xbb\xbf"):
        problems.append("starts with a UTF-8 BOM")
    if b"\r" in raw:
        problems.append("contains CR; line endings must be LF")
    if not raw.endswith(b"\n"):
        problems.append("does not end with a newline")
    try:
        text = raw.decode("ascii" if ascii_only else "utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        kind = "non-ASCII" if ascii_only else "invalid UTF-8"
        problems.append(f"{kind} byte at offset {exc.start}")
        return problems
    hidden = _forbidden_chars(text)
    if hidden:
        problems.append(f"{len(hidden)} hidden/control characters, first {hidden[:3]}")
    return problems


def _license_structure_problems(text: str) -> list[str]:
    """Title lines, the single end marker and sections 1..N in order."""
    problems: list[str] = []
    lines = text.split("\n")
    nonblank = [line.strip() for line in lines if line.strip()]
    title = tuple(nonblank[: len(LICENSE_TITLE_LINES)])
    if title != LICENSE_TITLE_LINES:
        problems.append(f"title lines are {[_show(t) for t in title]}, not {list(LICENSE_TITLE_LINES)}")
    end_at = [i for i, line in enumerate(lines) if line.strip() == LICENSE_END_MARKER]
    if len(end_at) != 1:
        problems.append(f"{LICENSE_END_MARKER!r} appears {len(end_at)} times, not once")
    body = lines[: end_at[0]] if end_at else lines
    numbers = [int(m.group(1)) for line in body if (m := _LICENSE_SECTION_LINE.match(line))]
    expected = list(range(1, LICENSE_SECTION_COUNT + 1))
    if numbers != expected:
        problems.append(f"numbered sections before the end marker are {numbers}, not {expected}")
    return problems


def _notice_problems(text: str, project_name: str) -> list[str]:
    problems: list[str] = []
    nonblank = [line.strip() for line in text.split("\n") if line.strip()]
    if not nonblank or nonblank[0] != project_name:
        first = _show(nonblank[0]) if nonblank else "nothing"
        problems.append(f"first line is {first}, not the project name {project_name!r}")
    copyright_lines = [line for line in nonblank if _normalise(line).startswith("copyright")]
    if copyright_lines != [NOTICE_COPYRIGHT_LINE]:
        problems.append(
            f"copyright lines are {[_show(c) for c in copyright_lines]}, "
            f"not exactly [{NOTICE_COPYRIGHT_LINE!r}]"
        )
    if "\r" in text:
        problems.append("contains CR; line endings must be LF")
    hidden = _forbidden_chars(text)
    if hidden:
        problems.append(f"{len(hidden)} hidden/control characters, first {hidden[:3]}")
    return problems


def _normalise(text: str) -> str:
    """NFKC, drop format (Cf) characters, fold every space/control/line break
    to one space, casefold. Phrase matching runs on this form so zero-width
    joiners, Unicode line breaks and full-width look-alikes cannot hide a claim.
    """
    out: list[str] = []
    for char in unicodedata.normalize("NFKC", text):
        category = unicodedata.category(char)
        if category == "Cf":
            continue
        out.append(" " if category in {"Cc", "Zs", "Zl", "Zp"} or char.isspace() else char)
    return re.sub(r" +", " ", "".join(out)).casefold()


# One table of conflicting-licence phrases, matched on _normalise() output.
# Separators are optional (\s*) because _normalise drops Cf characters.
CONFLICT_PATTERNS: dict[str, re.Pattern[str]] = {
    "mit-license": re.compile(r"(?<![a-z0-9])mit\s*licen[cs]e"),
    "bsd-license": re.compile(r"(?<![a-z0-9])bsd\s*licen[cs]e"),
    "all-rights-reserved": re.compile(r"(?<![a-z0-9])all\s*rights\s*reserved"),
    "mit-body": re.compile(r"permission\s*is\s*hereby\s*granted,?\s*free\s*of\s*charge"),
    "bsd-body": re.compile(r"redistribution\s*and\s*use\s*in\s*source\s*and\s*binary\s*forms"),
    "gpl": re.compile(r"gnu\s*(?:lesser\s*|affero\s*)?general\s*public\s*licen[cs]e"),
}
_SPDX_TAG = "spdx-license-identifier:"


def _conflict_hits(text: str) -> list[str]:
    """Names of every conflicting-licence claim in ``text``."""
    normal = _normalise(text)
    hits = [name for name, pattern in CONFLICT_PATTERNS.items() if pattern.search(normal)]
    # SPDX tags are line-scoped: the whole expression after the tag must be
    # exactly Apache-2.0 ("Apache-2.0 OR MIT" is a conflict).
    for line in text.splitlines():
        flat = _normalise(line)
        at = flat.find(_SPDX_TAG)
        if at >= 0 and flat[at + len(_SPDX_TAG):].strip() != LICENSE_SPDX_ID.casefold():
            hits.append("spdx-not-apache")
    return hits


_INLINE_LINK = re.compile(r"\[[^\]\n]+\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_REF_DEFINITION = re.compile(r"^ {0,3}\[[^\]]+\]:\s*<?([^\s>]+)>?")
_SPDX_TOKEN = re.compile(r"(?<![\w.+-])" + re.escape(LICENSE_SPDX_ID) + r"(?![\w.+-])")
# Words that, in the README's License section, name some other licence or
# leave the licence undecided.
OTHER_LICENCE_WORDS: dict[str, re.Pattern[str]] = {
    "tbd": re.compile(r"(?<![a-z0-9])tbd(?![a-z0-9])"),
    "mit": re.compile(r"(?<![a-z0-9])mit(?![a-z0-9])"),
    "bsd": re.compile(r"(?<![a-z0-9])bsd(?![a-z0-9])"),
    "gpl": re.compile(r"(?<![a-z0-9])[al]?gpl(?![a-z0-9])"),
    "proprietary": re.compile(r"(?<![a-z0-9])proprietary(?![a-z0-9])"),
    "all-rights-reserved": CONFLICT_PATTERNS["all-rights-reserved"],
}


def _readme_license_problems(readme: str) -> list[str]:
    """The README License section names Apache-2.0, links LICENSE, and nothing else."""
    section = _find_section(readme, README_LICENSE_HEADING)
    prose = "\n".join(line.text for line in section.lines if not line.in_code)
    problems: list[str] = []
    hidden = _forbidden_chars(prose)
    if hidden:
        problems.append(f"{len(hidden)} hidden/control characters, first {hidden[:3]}")
    if not _SPDX_TOKEN.search(prose):
        problems.append(f"does not name {LICENSE_SPDX_ID!r}")
    targets = _INLINE_LINK.findall(prose) + [
        m.group(1) for line in prose.split("\n") if (m := _REF_DEFINITION.match(line))
    ]
    if not any(t in LICENSE_LINK_TARGETS for t in targets):
        problems.append(f"no link to {sorted(LICENSE_LINK_TARGETS)}; links found: {[_show(t) for t in targets]}")
    normal = _normalise(prose)
    others = [name for name, pattern in OTHER_LICENCE_WORDS.items() if pattern.search(normal)]
    if others:
        problems.append(f"also names {others}")
    return problems


def _packaging_problems(rel: str, text: str) -> list[str]:
    """A packaging file's declared licence must be exactly Apache-2.0."""
    name = PurePosixPath(rel).name
    declared: object = None
    try:
        if name == "pyproject.toml":
            data = tomllib.loads(text)
            declared = data.get("project", {}).get("license")
            if isinstance(declared, dict):
                declared = declared.get("text")
            if declared is None:
                declared = data.get("tool", {}).get("poetry", {}).get("license")
        elif name == "setup.cfg":
            parser = configparser.ConfigParser(interpolation=None)
            parser.read_string(text)
            declared = parser.get("metadata", "license", fallback=None)
        elif name == "setup.py":
            for node in ast.walk(ast.parse(text)):
                if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) == "setup":
                    for kw in node.keywords:
                        if kw.arg == "license":
                            declared = kw.value.value if isinstance(kw.value, ast.Constant) else "<non-literal>"
        else:
            return [f"{rel}: not a packaging file this check knows"]
    except (tomllib.TOMLDecodeError, configparser.Error, SyntaxError, ValueError) as exc:
        return [f"{rel}: could not be parsed ({type(exc).__name__})"]
    if declared != LICENSE_SPDX_ID:
        shown = _show(declared) if isinstance(declared, str) else repr(declared)
        return [f"{rel}: declares licence {shown}, not {LICENSE_SPDX_ID!r}"]
    return []


def _project_name() -> str:
    """The README's one level-1 heading outside code is the project name."""
    lines = _lines(_read_text(REPO_ROOT, README_REL))
    titles = [h.title for h in _headings(lines) if h.level == 1]
    if len(titles) != 1:
        raise DocCheckError(f"README has {len(titles)} level-1 headings; the project name needs exactly one")
    return titles[0]


def _claim_scan_excluded(rel: str) -> bool:
    """True only for a file strictly under a listed prefix, compared by path
    component (so docs/researchers/ is not docs/research/). A path carrying
    '..' is never excluded: it could name a file outside the prefix (F7)."""
    parts = PurePosixPath(rel).parts
    if ".." in parts:
        return False
    return any(len(parts) > len(pre) and parts[: len(pre)] == pre for pre in _EXCLUDED_PREFIX_PARTS)


def _claim_scan_paths(tracked: list[str]) -> list[str]:
    return [p for p in tracked if not _claim_scan_excluded(p) and p != THIS_MODULE_REL]


def _top_level_docs_markdown(tracked: list[str]) -> list[str]:
    """Tracked docs/*.md directly under docs/: the project-status documents."""
    return [
        p
        for p in tracked
        if len(PurePosixPath(p).parts) == 2
        and PurePosixPath(p).parts[0] == "docs"
        and PurePosixPath(p).suffix.casefold() == ".md"
    ]


# Task-list items that #333 settles. A status doc that still shows one of
# these as open contradicts the licence decision. Matched on _normalise()
# output of the item text, so separators are optional (\s*).
#
# Every quantified part matches a given text exactly one way (CodeQL py/redos,
# alert #10). "open\s*-?\s*source" let two \s* share one space, so a repeated
# "open source" doubled the paths per repeat; "open\s*(?:-\s*)?source" accepts
# the same strings with one parse. In "licence-selection" the filler between
# the verb and "licence" is one loop of single tokens (one whitespace character
# or one word), entered with a token that starts with whitespace or, right
# after an "open" glued onto the verb ("pickopen-source"), with the rest of
# "open source". The verb's \w* run then owns every glued letter, so it never
# competes with the loop. Accepted strings are unchanged.
LICENCE_DECISION_ITEMS: dict[str, re.Pattern[str]] = {
    "licence-selection": re.compile(
        r"(?<![a-z0-9])licen[cs](?:e|ing)\s*(?:selection|choice|decision)"
        r"|(?<![a-z0-9])(?:select|choos|chose|pick|decid)\w*"
        r"(?:(?:\s|(?<=open)(?:\s+(?:-\s*)?|-\s*)source)"
        r"(?:\s|a|an|the|on|our|project|open\s*(?:-\s*)?source)*)?"
        r"licen[cs]e(?![a-z0-9])"
    ),
    "open-source-repository": re.compile(
        r"(?<![a-z0-9])open\s*(?:-\s*)?sourc(?:e|ed|ing)\s*(?:(?:the|this|our|a|project)\s*)*"
        r"(?:github\s*)?repo(?:sitory)?(?![a-z0-9])"
        r"|(?<![a-z0-9])(?:github\s*)?repo(?:sitory)?\s*(?:(?:is|as)\s*)?open\s*(?:-\s*)?sourc"
    ),
}

# Parsed on _normalise() output: indentation, tabs and NBSP fold to one space,
# Cf characters are gone and X is casefolded, so "[​]" reads as "[]".
_TASK_ITEM = re.compile(r"^[ >]*(?:[-*+]|\d{1,9}[.)]) ?\[([^\]]*)\] ?(.*)$")
_BLOCK_START = re.compile(r"^[ >]*(?:[-*+]|\d{1,9}[.)])(?: |$)")
_HEADING_START = re.compile(r"^ ?#{1,6}(?: |$)")


def _open_licence_items(text: str) -> list[tuple[int, str, str]]:
    """(line number, item name, item text) for each task-list item that is not
    ticked ``[x]`` and names a decision from LICENCE_DECISION_ITEMS.

    A list item runs on over following lines until a blank line, a heading, a
    code fence or the next list marker (CommonMark lazy continuation), so an
    item wrapped by a line break of any kind is read whole. Fenced code is an
    example, not a status, and is skipped.
    """
    blocks: list[tuple[int, list[str]]] = []
    current: tuple[int, list[str]] | None = None
    for number, line in enumerate(_lines(text), start=1):
        flat = _normalise(line.text)
        if line.in_code or not flat.strip():
            current = None
            continue
        if _HEADING_START.match(flat):
            current = None
            continue
        if current is None or _BLOCK_START.match(flat):
            current = (number, [line.text])
            blocks.append(current)
        else:
            current[1].append(line.text)
    found: list[tuple[int, str, str]] = []
    for number, raw_lines in blocks:
        item = _TASK_ITEM.match(_normalise("\n".join(raw_lines)))
        if not item or item.group(1).strip() == "x":
            continue
        found.extend(
            (number, name, item.group(2))
            for name, pattern in LICENCE_DECISION_ITEMS.items()
            if pattern.search(item.group(2))
        )
    return found


# --------------------------------------------------------------------------
# Acceptance tests (red until the licence lands)
# --------------------------------------------------------------------------


def test_license_is_byte_identical_to_canonical_apache_2_0() -> None:
    raw = _read_bytes(REPO_ROOT, LICENSE_REL)
    digest = hashlib.sha256(raw).hexdigest()
    assert digest == CANONICAL_LICENSE_SHA256, (
        f"{LICENSE_REL} SHA-256 is {digest} ({len(raw)} bytes); copy the text verbatim "
        f"from {CANONICAL_LICENSE_URL} (expected {CANONICAL_LICENSE_SHA256})"
    )


def test_license_has_title_end_marker_and_nine_sections() -> None:
    text = _read_bytes(REPO_ROOT, LICENSE_REL).decode("utf-8", errors="replace")
    problems = _license_structure_problems(text)
    assert problems == [], f"{LICENSE_REL}: {problems}"


def test_license_bytes_are_ascii_lf_without_hidden_characters() -> None:
    problems = _byte_problems(_read_bytes(REPO_ROOT, LICENSE_REL), ascii_only=True)
    assert problems == [], f"{LICENSE_REL}: {problems}"


def test_license_and_notice_are_tracked_and_index_blob_is_canonical() -> None:
    """The published object is the git blob, not the working-tree file (F7)."""
    tracked = set(_tracked_paths())
    missing = [rel for rel in (LICENSE_REL, NOTICE_REL) if rel not in tracked]
    assert missing == [], f"not tracked by git: {missing}"
    blob = _git("cat-file", "blob", f":{LICENSE_REL}")
    assert hashlib.sha256(blob).hexdigest() == CANONICAL_LICENSE_SHA256, (
        f"the {LICENSE_REL} blob in the git index differs from the canonical text "
        "(check .gitattributes filters and line-ending conversion)"
    )


def test_only_licence_files_are_root_license_and_notice() -> None:
    found = sorted(p for p in _tracked_paths() if _LICENCE_FILE_NAME.match(PurePosixPath(p).name))
    assert found == sorted({LICENSE_REL, NOTICE_REL}), (
        f"licence-named tracked files are {[_show(p) for p in found]}; "
        f"expected exactly {sorted({LICENSE_REL, NOTICE_REL})}"
    )


def test_notice_names_project_and_carries_the_copyright_line() -> None:
    raw = _read_bytes(REPO_ROOT, NOTICE_REL)
    problems = _byte_problems(raw, ascii_only=False)
    assert problems == [], f"{NOTICE_REL}: {problems}"
    problems = _notice_problems(raw.decode("utf-8"), _project_name())
    assert problems == [], f"{NOTICE_REL}: {problems}"


def test_readme_license_section_names_apache_2_0_and_links_license() -> None:
    problems = _readme_license_problems(_read_text(REPO_ROOT, README_REL))
    assert problems == [], f"{README_REL} {README_LICENSE_HEADING!r} section: {problems}"


def test_tracked_packaging_metadata_declares_apache_2_0() -> None:
    """Green on the base commit: no packaging file is tracked (count printed)."""
    files = [p for p in _tracked_paths() if PurePosixPath(p).name in PACKAGING_BASENAMES]
    problems = [
        problem
        for rel in files
        for problem in _packaging_problems(rel, _read_text(REPO_ROOT, rel))
    ]
    print(f"packaging files checked: {len(files)}")
    assert problems == [], f"packaging licence problems: {problems}"


def test_no_tracked_file_claims_a_conflicting_licence() -> None:
    tracked = _tracked_paths()
    scope = _claim_scan_paths(tracked)
    # Did-nothing guard (F5): the scan must cover the root files that speak
    # for the project, and the status docs at the top of docs/.
    assert README_REL in scope and scope, "claim scan scope lost the README"
    status_docs = _top_level_docs_markdown(tracked)
    unscanned = sorted(set(status_docs) - set(scope))
    assert status_docs and unscanned == [], (
        f"claim scan skips project-status docs {[_show(p) for p in unscanned]} "
        f"({len(status_docs)} top-level docs/*.md tracked)"
    )
    hits: list[str] = []
    binaries = 0
    for rel in scope:
        path = REPO_ROOT / rel
        if path.is_symlink() or not path.is_file():
            continue
        raw = path.read_bytes()
        if b"\0" in raw:
            binaries += 1
            continue
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            hits.append(f"{_show(rel)}: not UTF-8 and not binary; cannot be checked")
            continue
        hits.extend(f"{_show(rel)}: {name}" for name in _conflict_hits(text))
    print(f"claim scan: {len(scope)} files in scope, {binaries} binary skipped")
    assert hits == [], f"conflicting licence claims: {hits}"


def test_status_docs_leave_no_licence_decision_unchecked() -> None:
    """Copilot, PR #350 round 2: once the licence is decided, no project doc may
    still show "License selection" or "Open source GitHub repository" as an
    open task. Scope is every tracked markdown file the claim scan covers."""
    tracked = _tracked_paths()
    scope = [p for p in _claim_scan_paths(tracked) if PurePosixPath(p).suffix.casefold() == ".md"]
    status_docs = _top_level_docs_markdown(tracked)
    unscanned = sorted(set(status_docs) - set(scope))
    assert status_docs and unscanned == [], f"checklist scan skips status docs {[_show(p) for p in unscanned]}"
    open_items = [
        f"{_show(rel)}:{number}: {name} {_show(item)}"
        for rel in scope
        for number, name, item in _open_licence_items(_read_text(REPO_ROOT, rel))
    ]
    print(f"checklist scan: {len(scope)} markdown files, {len(status_docs)} top-level status docs")
    assert open_items == [], (
        f"#333 decided the licence ({LICENSE_SPDX_ID}); tick these items [x] or remove them: {open_items}"
    )


# --------------------------------------------------------------------------
# Checker vectors (green today; they pin the checkers so they cannot weaken)
# --------------------------------------------------------------------------


def _synthetic_license(
    titles: tuple[str, ...] = LICENSE_TITLE_LINES,
    sections: tuple[int, ...] = tuple(range(1, LICENSE_SECTION_COUNT + 1)),
    ends: int = 1,
) -> str:
    head = "\n" + "".join(f"   {t}\n" for t in titles) + "\n"
    body = "".join(f"   {n}. Heading {n}. Text.\n\n" for n in sections)
    return head + body + f"   {LICENSE_END_MARKER}\n" * ends + "\n   APPENDIX\n"


_ALL = tuple(range(1, LICENSE_SECTION_COUNT + 1))
LICENSE_STRUCTURE_VECTORS: list[tuple[str, str, bool]] = [
    ("canonical-shape", _synthetic_license(), True),
    # Only three-space-indented lines are section headings; a nested numbered
    # line inside a section must not be counted as one.
    (
        "nested-numbered-line-ignored",
        _synthetic_license().replace("   4. Heading 4. Text.\n", "   4. Heading 4. Text.\n      1. Nested item.\n"),
        True,
    ),
    ("section-9-dropped", _synthetic_license(sections=_ALL[:-1]), False),
    ("section-10-added", _synthetic_license(sections=_ALL + (LICENSE_SECTION_COUNT + 1,)), False),
    ("sections-swapped", _synthetic_license(sections=(1, 3, 2) + _ALL[3:]), False),
    ("section-duplicated", _synthetic_license(sections=_ALL[:5] + (5,) + _ALL[5:]), False),
    ("end-marker-missing", _synthetic_license(ends=0), False),
    ("end-marker-twice", _synthetic_license(ends=2), False),
    ("title-cyrillic-a", _synthetic_license(titles=("Аpache License", LICENSE_TITLE_LINES[1])), False),
    ("title-zwsp", _synthetic_license(titles=("Apache​ License", LICENSE_TITLE_LINES[1])), False),
    ("version-2-1", _synthetic_license(titles=("Apache License", "Version 2.1, January 2004")), False),
    ("titles-missing", _synthetic_license(titles=()), False),
    ("empty", "", False),
]


@pytest.mark.parametrize("name,text,ok", LICENSE_STRUCTURE_VECTORS, ids=[v[0] for v in LICENSE_STRUCTURE_VECTORS])
def test_vectors_license_structure(name: str, text: str, ok: bool) -> None:
    assert (_license_structure_problems(text) == []) is ok, name


_GOOD_BYTES = _synthetic_license().encode("ascii")
BYTE_VECTORS: list[tuple[str, bytes, bool, bool]] = [
    ("ascii-lf", _GOOD_BYTES, True, True),
    ("bom", b"\xef\xbb\xbf" + _GOOD_BYTES, True, False),
    ("crlf", _GOOD_BYTES.replace(b"\n", b"\r\n"), True, False),
    ("no-final-newline", _GOOD_BYTES.rstrip(b"\n"), True, False),
    ("non-ascii-in-ascii-file", "é".encode() + _GOOD_BYTES, True, False),
    ("utf8-ok-in-notice", "Résumé\n".encode(), False, True),
    ("lone-surrogate-bytes", b"Name \xed\xa0\x80\n", False, False),
    ("invalid-utf8", b"Name \xff\n", False, False),
    ("nul", b"Name\x00\n", False, False),
]


@pytest.mark.parametrize("name,raw,ascii_only,ok", BYTE_VECTORS, ids=[v[0] for v in BYTE_VECTORS])
def test_vectors_byte_hygiene(name: str, raw: bytes, ascii_only: bool, ok: bool) -> None:
    assert (_byte_problems(raw, ascii_only=ascii_only) == []) is ok, name


_PROJECT = "Example Project"
NOTICE_VECTORS: list[tuple[str, str, bool]] = [
    ("canonical", f"{_PROJECT}\n{NOTICE_COPYRIGHT_LINE}\n", True),
    ("with-attribution-paragraph", f"{_PROJECT}\n{NOTICE_COPYRIGHT_LINE}\n\nThis product includes X.\n", True),
    ("no-project-name", f"{NOTICE_COPYRIGHT_LINE}\n", False),
    ("wrong-project-name", f"Other Project\n{NOTICE_COPYRIGHT_LINE}\n", False),
    ("no-copyright", f"{_PROJECT}\n", False),
    ("two-copyrights", f"{_PROJECT}\n{NOTICE_COPYRIGHT_LINE}\nCopyright 2026 Someone Else\n", False),
    ("wrong-year", f"{_PROJECT}\n{NOTICE_COPYRIGHT_LINE.replace('2026', '2025')}\n", False),
    ("c-symbol-variant", f"{_PROJECT}\n{NOTICE_COPYRIGHT_LINE.replace('Copyright', 'Copyright (c)')}\n", False),
    ("zwsp-in-copyright", f"{_PROJECT}\n{NOTICE_COPYRIGHT_LINE.replace(' ', chr(0x200B) + ' ', 1)}\n", False),
    ("bidi-in-name", f"‮{_PROJECT}\n{NOTICE_COPYRIGHT_LINE}\n", False),
    ("empty", "", False),
]


@pytest.mark.parametrize("name,text,ok", NOTICE_VECTORS, ids=[v[0] for v in NOTICE_VECTORS])
def test_vectors_notice(name: str, text: str, ok: bool) -> None:
    assert (_notice_problems(text, _PROJECT) == []) is ok, name


CONFLICT_VECTORS: list[tuple[str, str, str | None]] = [
    # (pattern name, text, expected hit or None)
    ("mit-license", "Released under the MIT License.", "mit-license"),
    ("mit-license", "mit licence", "mit-license"),
    ("mit-license", "MIT​License", "mit-license"),
    ("mit-license", "MIT License", "mit-license"),
    ("mit-license", "ＭＩＴ License", "mit-license"),  # full-width
    ("mit-license", "Please submit license renewals.", None),
    ("bsd-license", "BSD License (3-clause)", "bsd-license"),
    ("bsd-license", "the BSDs licensing story", None),
    ("all-rights-reserved", "Copyright 2026 X. All Rights Reserved.", "all-rights-reserved"),
    ("all-rights-reserved", "All rights\nreserved", "all-rights-reserved"),
    ("all-rights-reserved", "All rights reserved", "all-rights-reserved"),
    ("all-rights-reserved", "rights are reserved to the user", None),
    ("mit-body", "Permission is hereby granted, free of charge, to any person", "mit-body"),
    ("mit-body", "Permission is granted to use", None),
    ("bsd-body", "Redistribution and use in source and binary forms, with", "bsd-body"),
    ("bsd-body", "4. Redistribution. You may reproduce and distribute copies", None),  # Apache s.4
    ("gpl", "GNU GENERAL PUBLIC LICENSE Version 3", "gpl"),
    ("gpl", "GNU Lesser General Public License", "gpl"),
    ("gpl", "general public interest", None),
    ("spdx-not-apache", "# SPDX-License-Identifier: MIT\n", "spdx-not-apache"),
    ("spdx-not-apache", "# SPDX-License-Identifier: Apache-2.0 OR MIT\n", "spdx-not-apache"),
    ("spdx-not-apache", "# SPDX-License-Identifier: Apache-2.0​+\n", "spdx-not-apache"),
    ("spdx-not-apache", "# SPDX-License-Identifier: Apache-2.0\n", None),
]


@pytest.mark.parametrize("name,text,hit", CONFLICT_VECTORS, ids=[f"{v[0]}-{i}" for i, v in enumerate(CONFLICT_VECTORS)])
def test_vectors_conflict_patterns(name: str, text: str, hit: str | None) -> None:
    hits = _conflict_hits(text)
    if hit is None:
        assert name not in hits, f"{name} matched benign text {_show(text)}"
    else:
        assert hit in hits, f"{name} missed {_show(text)}"


def test_vectors_conflict_table_has_positive_and_negative_per_pattern() -> None:
    names = set(CONFLICT_PATTERNS) | {"spdx-not-apache"}
    for name in sorted(names):
        rows = [v for v in CONFLICT_VECTORS if v[0] == name]
        assert any(v[2] is not None for v in rows), f"{name} has no positive vector"
        assert any(v[2] is None for v in rows), f"{name} has no negative vector"


def test_control_apache_markers_are_not_conflicts() -> None:
    """Positive control: phrases from the canonical Apache text never trip the scan."""
    sample = (
        "\n".join(LICENSE_TITLE_LINES)
        + "\n2. Grant of Copyright License. Subject to the terms\n"
        + "4. Redistribution. You may reproduce and distribute copies\n"
        + f"{LICENSE_END_MARKER}\nCopyright [yyyy] [name of copyright owner]\n"
        + f"# SPDX-License-Identifier: {LICENSE_SPDX_ID}\n"
    )
    assert _conflict_hits(sample) == []


def _readme(section_body: str) -> str:
    return f"# {_PROJECT}\n\nIntro.\n\n## {README_LICENSE_HEADING}\n\n{section_body}\n\n## Contributing\n\nMIT is fine here.\n"


README_VECTORS: list[tuple[str, str, bool]] = [
    ("inline-link", f"Licensed under [{LICENSE_SPDX_ID}](LICENSE).", True),
    ("dot-slash-link", f"This project is {LICENSE_SPDX_ID}; see [LICENSE](./LICENSE).", True),
    ("reference-link", f"Licensed under {LICENSE_SPDX_ID}, see [the licence][lic].\n\n[lic]: LICENSE", True),
    ("tbd", "TBD", False),
    ("apache-without-link", f"Licensed under {LICENSE_SPDX_ID}.", False),
    ("link-without-apache", "See [LICENSE](LICENSE).", False),
    ("apache-2-not-spdx", "Licensed under Apache 2.0, see [LICENSE](LICENSE).", False),
    ("link-to-license-md", f"{LICENSE_SPDX_ID}: [LICENSE](LICENSE.md)", False),
    ("link-to-parent", f"{LICENSE_SPDX_ID}: [LICENSE](../LICENSE)", False),
    ("link-offsite", f"{LICENSE_SPDX_ID}: [LICENSE](https://example.invalid/LICENSE)", False),
    ("link-target-zwsp", f"{LICENSE_SPDX_ID}: [LICENSE](LICENSE​)", False),
    ("spdx-with-zwsp", "Apache​-2.0: [LICENSE](LICENSE)", False),
    ("dual-licence", f"{LICENSE_SPDX_ID} or MIT, see [LICENSE](LICENSE).", False),
    ("all-rights-reserved", f"{LICENSE_SPDX_ID} [LICENSE](LICENSE). All rights reserved.", False),
    ("link-only-in-code", f"{LICENSE_SPDX_ID}\n\n```\n[LICENSE](LICENSE)\n```", False),
    ("apache-plus", f"{LICENSE_SPDX_ID}+ [LICENSE](LICENSE)", False),
    ("bidi-override", f"‮{LICENSE_SPDX_ID} [LICENSE](LICENSE)", False),
]


@pytest.mark.parametrize("name,body,ok", README_VECTORS, ids=[v[0] for v in README_VECTORS])
def test_vectors_readme_license_section(name: str, body: str, ok: bool) -> None:
    assert (_readme_license_problems(_readme(body)) == []) is ok, name


def test_vectors_readme_missing_or_duplicate_section_fails_closed() -> None:
    with pytest.raises(DocCheckError):
        _readme_license_problems(f"# {_PROJECT}\n\n## Features\n\nText.\n")
    with pytest.raises(DocCheckError):
        _readme_license_problems(_readme("x") + f"\n## {README_LICENSE_HEADING}\n\nAgain.\n")


PACKAGING_VECTORS: list[tuple[str, str, str, bool]] = [
    ("pyproject.toml", "pep639-string", f'[project]\nname = "x"\nlicense = "{LICENSE_SPDX_ID}"\n', True),
    ("pyproject.toml", "table-text", f'[project]\nlicense = {{text = "{LICENSE_SPDX_ID}"}}\n', True),
    ("pyproject.toml", "poetry", f'[tool.poetry]\nlicense = "{LICENSE_SPDX_ID}"\n', True),
    ("pyproject.toml", "mit", '[project]\nlicense = "MIT"\n', False),
    ("pyproject.toml", "missing", '[project]\nname = "x"\n', False),
    ("pyproject.toml", "zwsp", f'[project]\nlicense = "{LICENSE_SPDX_ID}​"\n', False),
    ("pyproject.toml", "dual", f'[project]\nlicense = "{LICENSE_SPDX_ID} OR MIT"\n', False),
    ("pyproject.toml", "invalid-toml", "[project\nlicense = \n", False),
    ("setup.cfg", "cfg-ok", f"[metadata]\nlicense = {LICENSE_SPDX_ID}\n", True),
    ("setup.cfg", "cfg-mit", "[metadata]\nlicense = MIT\n", False),
    ("setup.cfg", "cfg-missing", "[metadata]\nname = x\n", False),
    ("setup.cfg", "cfg-invalid", "license = MIT\n", False),
    ("setup.py", "py-ok", f'from setuptools import setup\nsetup(name="x", license="{LICENSE_SPDX_ID}")\n', True),
    ("setup.py", "py-mit", 'import setuptools\nsetuptools.setup(license="MIT")\n', False),
    ("setup.py", "py-non-literal", "from setuptools import setup\nLIC = 'x'\nsetup(license=LIC)\n", False),
    ("setup.py", "py-missing", "from setuptools import setup\nsetup(name='x')\n", False),
    ("setup.py", "py-syntax-error", "setup(license=\n", False),
]


@pytest.mark.parametrize("basename,name,text,ok", PACKAGING_VECTORS, ids=[v[1] for v in PACKAGING_VECTORS])
def test_vectors_packaging(basename: str, name: str, text: str, ok: bool) -> None:
    assert (_packaging_problems(f"src/backend/{basename}", text) == []) is ok, name


def test_vectors_tables_have_both_outcomes() -> None:
    """Contract (QUALITY-BAR 9): every vectors table has a pass and a fail row,
    and every packaging format has both."""
    for label, outcomes in (
        ("structure", [v[2] for v in LICENSE_STRUCTURE_VECTORS]),
        ("bytes", [v[3] for v in BYTE_VECTORS]),
        ("notice", [v[2] for v in NOTICE_VECTORS]),
        ("readme", [v[2] for v in README_VECTORS]),
    ):
        assert set(outcomes) == {True, False}, f"{label} vectors lack a pass or a fail row"
    for basename in sorted(PACKAGING_BASENAMES):
        outcomes = {v[3] for v in PACKAGING_VECTORS if v[0] == basename}
        assert outcomes == {True, False}, f"{basename} vectors lack a pass or a fail row"


def _hostile_code_points() -> list[str]:
    """Every Cc, Cf, Zl and Zp code point except tab and LF (generated, R2)."""
    return [
        chr(cp)
        for cp in range(sys.maxunicode + 1)
        if unicodedata.category(chr(cp)) in {"Cc", "Cf", "Zl", "Zp"} and chr(cp) not in "\t\n"
    ]


def test_generated_hidden_characters_rejected_everywhere() -> None:
    """Each hidden character, put in each checked field, is rejected."""
    points = _hostile_code_points()
    escaped: list[str] = []
    for char in points:
        title = LICENSE_TITLE_LINES[0][:3] + char + LICENSE_TITLE_LINES[0][3:]
        licence = _synthetic_license(titles=(title, LICENSE_TITLE_LINES[1]))
        if _byte_problems(licence.encode("utf-8"), ascii_only=True) == []:
            escaped.append(f"bytes/U+{ord(char):04X}")
        if _license_structure_problems(licence) == []:
            escaped.append(f"structure/U+{ord(char):04X}")
        notice = f"{_PROJECT}\nCopy{char}right 2026 X\n{NOTICE_COPYRIGHT_LINE}\n"
        if _notice_problems(notice, _PROJECT) == []:
            escaped.append(f"notice/U+{ord(char):04X}")
        # CR is a CommonMark line ending, so in the README it splits the line
        # rather than hiding inside it; README line endings are out of scope.
        readme = _readme(f"{LICENSE_SPDX_ID}{char} [LICENSE](LICENSE)")
        if char != "\r" and _readme_license_problems(readme) == []:
            escaped.append(f"readme/U+{ord(char):04X}")
        if "mit-license" not in _conflict_hits(f"MIT{char}License"):
            escaped.append(f"conflict/U+{ord(char):04X}")
        # A hidden character in the item text or in the checkbox must not let
        # a stale licence item pass as ticked or as something else.
        for field, item_md in (
            ("checklist-text", f"- [ ] License{char}selection\n"),
            ("checklist-box", f"- [{char}] License selection\n"),
        ):
            if "licence-selection" not in [found[1] for found in _open_licence_items(item_md)]:
                escaped.append(f"{field}/U+{ord(char):04X}")
    print(f"generated hidden characters: {len(points)} x 7 fields")
    assert len(points) > 0
    assert escaped == [], f"{len(escaped)} hidden characters got through: {escaped[:10]}"


def test_claim_scan_scope_excludes_only_listed_prefixes() -> None:
    """Round 2 (PR #350): only files strictly under a listed prefix are
    excluded; status docs at the top of docs/ and look-alike paths are scanned."""
    scanned = [
        "README.md", "GITHUB_SETUP.md", "src/a.py", ".github/w.yml", "archive/y.py",
        "docs/BRD_Terms_Policies_Reviewer.md", "docs/PRD_Terms_Policies_Reviewer.md",
        "docs/PROJECT_STRUCTURE.md", "docs/adr/0001-x.md", "docs/specs/s.md", "docs/reviews/r.md",
        "docs/researchers/x.md",          # shares a prefix string, not a path component
        "docs/research",                  # the prefix itself as a file name
        "docs/research/../PRD.md",        # '..' never earns an exclusion
        "src/docs/research/z.md",         # same components, not at the root
        "DOCS/research/x.md",             # git paths are case-sensitive
    ]
    excluded = [
        f"{prefix}{leaf}" for prefix in CLAIM_SCAN_EXCLUDED_PREFIXES for leaf in ("x.md", "deep/y.log")
    ]
    assert _claim_scan_paths(scanned + excluded + [THIS_MODULE_REL]) == scanned
    assert THIS_MODULE_REL == "src/backend/tests/test_license.py"
    assert all(reason.strip() for reason in CLAIM_SCAN_EXCLUDED_PREFIXES.values())
    # No prefix may widen back to a top-level directory (the round-1 bug).
    assert all(len(parts) >= 2 for parts in _EXCLUDED_PREFIX_PARTS), CLAIM_SCAN_EXCLUDED_PREFIXES


def test_top_level_docs_markdown_selects_only_direct_children() -> None:
    sample = ["docs/BRD.md", "docs/TODO.MD", "docs/plans/p.md", "docs/a.png", "README.md", "src/docs/x.md"]
    assert _top_level_docs_markdown(sample) == ["docs/BRD.md", "docs/TODO.MD"]
    assert _top_level_docs_markdown([]) == []


# (item name, markdown, expected open) for the checklist scan. The item text
# comes from the real stale lines (PROJECT_STRUCTURE "License selection", BRD
# "Open source GitHub repository") plus structure-forging variants of them.
_LICENCE_ITEM = "License selection"
_REPO_ITEM = "Open source GitHub repository"
CHECKLIST_VECTORS: list[tuple[str, str, bool]] = [
    ("licence-selection", f"- [ ] {_LICENCE_ITEM}\n", True),
    ("licence-selection", "* [ ] Licence choice\n", True),
    ("licence-selection", "1. [ ] Choose a license\n", True),
    ("licence-selection", "- [ ] Select the project licence\n", True),
    ("licence-selection", f"  - [ ] {_LICENCE_ITEM}\n", True),                  # nested
    ("licence-selection", f"> - [ ] {_LICENCE_ITEM}\n", True),                  # blockquote
    ("licence-selection", "- [ ] License\nselection\n", True),                  # wrapped (lazy continuation)
    ("licence-selection", "- [ ] License\rselection\n", True),                  # CR line ending
    ("licence-selection", "- [ ] License selection\n", True),              # Unicode line separator
    ("licence-selection", f"- [\r] {_LICENCE_ITEM}\n", True),                   # box split across lines
    ("licence-selection", f"- [] {_LICENCE_ITEM}\n", True),                     # empty box
    ("licence-selection", f"- [​] {_LICENCE_ITEM}\n", True),               # zero-width box
    ("licence-selection", f"- [ ] {_LICENCE_ITEM}\n", True),               # NBSP box
    ("licence-selection", f"- [-] {_LICENCE_ITEM}\n", True),                    # "in progress" is not ticked
    ("licence-selection", f"- [?] {_LICENCE_ITEM}\n", True),
    ("licence-selection", f"-\t[ ]\t{_LICENCE_ITEM}\n", True),                  # tabs
    ("licence-selection", "- [ ] ＬＩＣＥＮＳＥ selection\n", True),  # full-width
    ("licence-selection", "- [ ] " + "a " * 1_000_000 + _LICENCE_ITEM + "\n", True),  # 2 MB item
    ("licence-selection", f"- [x] {_LICENCE_ITEM}\n", False),                   # ticked
    ("licence-selection", f"- [X] {_LICENCE_ITEM}\n", False),
    ("licence-selection", "- [ ] White-label licensing option\n", False),       # BRD product feature
    ("licence-selection", "- [ ] License compliance audit for dependencies\n", False),
    ("licence-selection", "- [ ] Select licensed corpora\n", False),
    ("licence-selection", f"{_LICENCE_ITEM} is done.\n", False),                # not a task item
    ("licence-selection", f"```\n- [ ] {_LICENCE_ITEM}\n```\n", False),         # fenced example
    ("licence-selection", f"- [ ] Code of conduct\n\n{_LICENCE_ITEM}\n", False),  # blank line ends the item
    ("licence-selection", "", False),
    ("open-source-repository", f"- [ ] {_REPO_ITEM}\n", True),
    ("open-source-repository", "- [ ] Open-source the repository\n", True),
    ("open-source-repository", "- [ ] Open​source repo\n", True),
    ("open-source-repository", "- [ ] Make the GitHub repository open source\n", True),
    ("open-source-repository", "- [ ] Open source GitHub\nrepository\n", True),
    ("open-source-repository", f"- [x] {_REPO_ITEM}\n", False),
    ("open-source-repository", "- [ ] Reddit posts in r/privacy, r/opensource\n", False),  # PRD
    ("open-source-repository", "- [ ] Open source RAG pipeline\n", False),
    ("open-source-repository", "- [ ] Repository pattern for storage adapters\n", False),
    ("open-source-repository", "- [ ] Open-source dependencies only (HR1)\n", False),
]


@pytest.mark.parametrize(
    "name,text,is_open", CHECKLIST_VECTORS, ids=[f"{v[0]}-{i}" for i, v in enumerate(CHECKLIST_VECTORS)]
)
def test_vectors_licence_checklist(name: str, text: str, is_open: bool) -> None:
    names = [found[1] for found in _open_licence_items(text)]
    assert (name in names) is is_open, f"{name} open={is_open} expected for {_show(text)}; got {names}"


def test_vectors_checklist_table_has_positive_and_negative_per_item() -> None:
    for name in sorted(LICENCE_DECISION_ITEMS):
        rows = [v for v in CHECKLIST_VECTORS if v[0] == name]
        assert any(v[2] for v in rows), f"{name} has no open-item vector"
        assert any(not v[2] for v in rows), f"{name} has no closed or benign vector"
    assert {v[0] for v in CHECKLIST_VECTORS} == set(LICENCE_DECISION_ITEMS)


# CodeQL py/redos (alert #10): the old "licence-selection" pattern took about
# 1 s at 22 repeats of " sourceopen" and doubled with each repeat. The search
# runs in a child process so a regression fails at the kill bound instead of
# hanging the suite.
_REDOS_REPEATS = 5000
_REDOS_BUDGET_SECONDS = 1.0
_REDOS_KILL_SECONDS = 10 * _REDOS_BUDGET_SECONDS
_TIMED_SEARCH = (
    "import re, sys, time\n"
    "pattern = re.compile(sys.argv[1], int(sys.argv[2]))\n"
    "text = sys.stdin.read()\n"
    "start = time.perf_counter()\n"
    "found = pattern.search(text) is not None\n"
    "print(found, time.perf_counter() - start)\n"
)


def test_licence_decision_patterns_resist_backtracking_blowup() -> None:
    hostile = "pickopen" + " sourceopen" * _REDOS_REPEATS
    # (text, items expected to match): a non-matching tail forces a full
    # backtrack; a licence tail is the positive control.
    cases = [(hostile + " x", set()), (hostile + " source licence", {"licence-selection"})]
    for text, expected in cases:
        matched = set()
        for name, pattern in LICENCE_DECISION_ITEMS.items():
            try:
                run = subprocess.run(
                    [sys.executable, "-I", "-c", _TIMED_SEARCH, pattern.pattern, str(pattern.flags)],
                    input=text,
                    capture_output=True,
                    text=True,
                    timeout=_REDOS_KILL_SECONDS,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                pytest.fail(f"{name} still searching after {_REDOS_KILL_SECONDS}s on {_show(text[-20:])}")
            assert run.returncode == 0, f"{name}: child exited {run.returncode}: {run.stderr[-500:]}"
            found, elapsed = run.stdout.split()
            assert float(elapsed) < _REDOS_BUDGET_SECONDS, f"{name} took {elapsed}s on {_show(text[-20:])}"
            if found == "True":
                matched.add(name)
        assert matched == expected, f"tail {_show(text[-20:])}: matched {matched}, expected {expected}"


def test_checklist_reports_the_item_line_number() -> None:
    """The message points at the item's own line, derived from the text."""
    text = f"# Status\n\n- [x] Done thing\n- [ ] Code of conduct\n- [ ] {_LICENCE_ITEM}\n"
    expected = text.split("\n").index(f"- [ ] {_LICENCE_ITEM}") + 1
    assert _open_licence_items(text) == [(expected, "licence-selection", _LICENCE_ITEM.casefold())]


LICENCE_NAME_VECTORS: list[tuple[str, bool]] = [
    ("LICENSE", True), ("LICENCE", True), ("license.md", True), ("LICENSE-MIT", True),
    ("COPYING", True), ("NOTICE", True), ("NOTICE.txt", True),
    ("licensed.py", False), ("test_license.py", False), ("notices.md", False), ("README.md", False),
]


@pytest.mark.parametrize("name,match", LICENCE_NAME_VECTORS, ids=[v[0] for v in LICENCE_NAME_VECTORS])
def test_vectors_licence_file_names(name: str, match: bool) -> None:
    assert bool(_LICENCE_FILE_NAME.match(name)) is match
