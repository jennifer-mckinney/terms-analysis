"""README.md does not contradict the code (#144, plan A1, HR9).

The public README contradicted itself and the code in four places:

- Features called the IRP methodology "planned, not-yet-implemented" while the
  Risk Scoring section publishes the live formula (``rules._seed_irp``).
- The Risk Scoring table used grades (``D or F``) that HR9 does not define.
- Features listed a handful of jurisdictions with no count, while
  ``schemas.Jurisdiction`` defines many more.
- The Risk Categories table read as exhaustive against the rule engine's
  categories, and the API Endpoints table read as complete.

Every expected value is derived at test time from its single source of truth
(F10, F13), never restated here:

- grades: the HR9 line in ``.claude/CLAUDE.md`` (cross-checked against the
  behaviour of ``analyzer._grade``);
- jurisdiction count: ``len(get_args(schemas.Jurisdiction))``;
- rule-category count: distinct ``category`` values in ``rules.PATTERNS``;
- endpoints: the live FastAPI OpenAPI schema (``app.openapi()``).

The README is prose, so these are static checks by necessity. Each checker is
pinned by a vectors table (positive and negative rows, with a contract test)
and by hostile Unicode generated per category, so a weakened checker goes red
here instead of letting a contradiction through. Sections are found by
heading, fence-aware, and a missing section fails the test: no test can pass
because the thing it checks is absent (F5).
"""
from __future__ import annotations

import math
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, get_args

import pytest

REPO_ROOT: Path = Path(__file__).resolve().parents[3]

# Repo-relative, so failure messages carry no absolute paths (F8).
README_REL = "README.md"
HR9_SOURCE_REL = ".claude/CLAUDE.md"
HR9_LINE_PREFIX = "- HR9 grades:"

FEATURES_HEADING = "Features"
RISK_CATEGORIES_HEADING = "Risk Categories"
API_ENDPOINTS_HEADING = "API Endpoints"
RISK_SCORING_HEADING = "Risk Scoring"

# Words a reader takes as "this table is not the full list". The card names
# "illustrative" for categories and "partial" for endpoints.
ILLUSTRATIVE_MARKERS: tuple[str, ...] = ("illustrative",)
PARTIAL_MARKERS: tuple[str, ...] = ("partial", "non-exhaustive", "not exhaustive")

# Display bound for untrusted text in assertion messages (output safety).
SHOW_LIMIT = 80

HTTP_METHODS: frozenset[str] = frozenset(
    {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
)

# Unicode categories a public markdown file must not carry: controls other
# than tab/LF/CR, format (zero-width, bidi, soft hyphen, BOM), surrogates,
# private use, unassigned, and the Unicode line/paragraph separators.
FORBIDDEN_CATEGORIES: frozenset[str] = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})
ALLOWED_CONTROLS: frozenset[str] = frozenset({"\t", "\n", "\r"})


# --------------------------------------------------------------------------
# Readers and display
# --------------------------------------------------------------------------


class DocCheckError(AssertionError):
    """A doc could not be read or parsed the way the check needs."""


def _show(text: str) -> str:
    """ASCII-escaped, truncated rendering of untrusted text for messages."""
    shown = ascii(text[:SHOW_LIMIT])
    extra = len(text) - SHOW_LIMIT
    return f"{shown}...(+{extra} chars)" if extra > 0 else shown


def _read_text(root: Path, rel: str) -> str:
    """Read ``root/rel`` as strict UTF-8; refuse symlinks and escapes (F7)."""
    path = root / rel
    if path.is_symlink():
        raise DocCheckError(f"{rel} is a symlink; the check must read the tracked file itself")
    if not path.is_file():
        raise DocCheckError(f"{rel} is missing")
    if not path.resolve().is_relative_to(root.resolve()):
        raise DocCheckError(f"{rel} resolves outside the repository")
    try:
        return path.read_bytes().decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise DocCheckError(f"{rel} is not valid UTF-8 at byte {exc.start}") from exc


def _forbidden_chars(text: str) -> list[tuple[int, str]]:
    """Every (index, U+XXXX) whose category a public doc must not carry."""
    found: list[tuple[int, str]] = []
    for index, char in enumerate(text):
        if char in ALLOWED_CONTROLS:
            continue
        if unicodedata.category(char) in FORBIDDEN_CATEGORIES:
            found.append((index, f"U+{ord(char):04X}"))
    return found


# --------------------------------------------------------------------------
# Markdown structure (CommonMark subset: ATX headings, fences, pipe tables)
# --------------------------------------------------------------------------

_LINE_ENDING = re.compile(r"\r\n|\r|\n")  # CommonMark line endings only
_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_ATX_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
_CLOSING_HASHES = re.compile(r"(?:^|[ \t]+)#+[ \t]*$")
_TABLE_DELIMITER = re.compile(r"^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$")
_UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")
_MARKUP = re.compile(r"[*_`]")


@dataclass(frozen=True)
class Line:
    text: str
    in_code: bool


@dataclass(frozen=True)
class Heading:
    level: int
    title: str
    index: int  # line index


@dataclass(frozen=True)
class Section:
    heading: Heading
    lines: tuple[Line, ...]  # body, nested subsections included


@dataclass(frozen=True)
class Table:
    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    start: int  # line index of the header row within the section body


def _lines(text: str) -> list[Line]:
    """Split on CommonMark line endings and mark fenced-code lines."""
    out: list[Line] = []
    fence: str | None = None
    for raw in _LINE_ENDING.split(text):
        if fence is None:
            opened = _FENCE_OPEN.match(raw)
            if opened:
                fence = opened.group(1)
                out.append(Line(raw, True))
                continue
            out.append(Line(raw, False))
        else:
            out.append(Line(raw, True))
            stripped = raw.strip()
            if (
                stripped
                and set(stripped) == {fence[0]}
                and len(stripped) >= len(fence)
                and len(raw) - len(raw.lstrip(" ")) <= 3
            ):
                fence = None
    return out


def _headings(lines: list[Line]) -> list[Heading]:
    found: list[Heading] = []
    for index, line in enumerate(lines):
        if line.in_code:
            continue
        match = _ATX_HEADING.match(line.text)
        if not match:
            continue
        title = _CLOSING_HASHES.sub("", match.group(2) or "").strip()
        found.append(Heading(len(match.group(1)), _MARKUP.sub("", title).strip(), index))
    return found


def _title_matches(title: str, wanted: str) -> bool:
    """``wanted`` is the title, or its prefix followed by a non-word char."""
    if not title.casefold().startswith(wanted.casefold()):
        return False
    rest = title[len(wanted):]
    return rest == "" or not (rest[0].isalnum() or rest[0] == "_")


def _find_section(text: str, wanted: str) -> Section:
    """The one section whose heading starts with ``wanted``; else fail closed."""
    lines = _lines(text)
    heads = _headings(lines)
    hits = [h for h in heads if _title_matches(h.title, wanted)]
    if not hits:
        raise DocCheckError(f"README has no {wanted!r} section (looked for an ATX heading)")
    if len(hits) > 1:
        raise DocCheckError(
            f"README has {len(hits)} {wanted!r} sections; the check needs exactly one"
        )
    head = hits[0]
    end = len(lines)
    for other in heads:
        if other.index > head.index and other.level <= head.level:
            end = other.index
            break
    return Section(head, tuple(lines[head.index + 1:end]))


def _cells(row: str) -> tuple[str, ...]:
    body = row.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    return tuple(c.replace("\\|", "|").strip() for c in _UNESCAPED_PIPE.split(body))


def _tables(section: Section) -> list[Table]:
    """Pipe tables in the section body (header row + delimiter row + rows)."""
    lines = section.lines
    tables: list[Table] = []
    i = 0
    while i + 1 < len(lines):
        head, delim = lines[i], lines[i + 1]
        if (
            not head.in_code
            and not delim.in_code
            and "|" in head.text
            and _TABLE_DELIMITER.match(delim.text)
            and "-" in delim.text
        ):
            rows: list[tuple[str, ...]] = []
            j = i + 2
            while j < len(lines) and not lines[j].in_code and lines[j].text.strip().startswith("|"):
                rows.append(_cells(lines[j].text))
                j += 1
            tables.append(Table(_cells(head.text), tuple(rows), i))
            i = j
            continue
        i += 1
    return tables


def _prose(section: Section, until: int | None = None) -> str:
    """Heading title plus non-code, non-table body text (up to line ``until``)."""
    table_lines: set[int] = set()
    for table in _tables(section):
        table_lines.update(range(table.start, table.start + 2 + len(table.rows)))
    body = [
        line.text
        for index, line in enumerate(section.lines[:until])
        if not line.in_code and index not in table_lines
    ]
    return "\n".join([section.heading.title, *body])


def _column(table: Table, pattern: str) -> int | None:
    for index, name in enumerate(table.header):
        if re.search(pattern, _MARKUP.sub("", name), re.IGNORECASE | re.ASCII):
            return index
    return None


# --------------------------------------------------------------------------
# Prose checkers
# --------------------------------------------------------------------------

# U+2212 MINUS SIGN is Sm, not Pd, but reads as a hyphen.
_EXTRA_DASHES: frozenset[str] = frozenset({"−"})
_BLOCK_SPLIT = re.compile(r"\n[ \t]*\n|\n(?=[ \t]*(?:[-*+]|\d+[.)])[ \t])|\n(?=[ \t]*[|#])")
_SENTENCE_SPLIT = re.compile(r"(?<=[.;!?])\s+")
_UNIMPLEMENTED = re.compile(r"not[ -]*yet[ -]*implemented")
_IRP_MENTION = re.compile(r"\birp\b|impact\s*/\s*likelihood\s*/\s*safeguards?")
_IRP_NOT_LIVE = re.compile(
    r"\bplanned\b|\bnot[ -]*(?:yet[ -]*)?implemented\b|\bunimplemented\b|\bcoming soon\b"
)


def _fold_loose(text: str) -> str:
    """Normalise for FORBIDDEN phrases: catch every disguise of the phrase.

    Drops Cf (zero-width, bidi, soft hyphen), applies NFKC (full-width,
    long s), maps every dash to '-', collapses every Unicode space and line
    break to one space, and casefolds.
    """
    text = "".join(c for c in text if unicodedata.category(c) != "Cf")
    text = unicodedata.normalize("NFKC", text)
    text = "".join(
        "-" if unicodedata.category(c) == "Pd" or c in _EXTRA_DASHES else c for c in text
    )
    return re.sub(r"\s+", " ", text).casefold()


def _irp_claimed_unimplemented(text: str) -> bool:
    """True if the text calls IRP planned / not implemented.

    Two forms: the card's phrase "not yet implemented" anywhere, in any
    disguise; and any sentence that mentions IRP and calls it planned or not
    implemented. Sentences are split per markdown block first, so a soft line
    wrap cannot hide the claim and an unrelated bullet cannot trigger it.
    """
    commonmark = text.replace("\r\n", "\n").replace("\r", "\n")
    for block in _BLOCK_SPLIT.split(commonmark):
        folded = _fold_loose(block)
        if _UNIMPLEMENTED.search(folded):
            return True
        for sentence in _SENTENCE_SPLIT.split(folded):
            if _IRP_MENTION.search(sentence) and _IRP_NOT_LIVE.search(sentence):
                return True
    return False


def _has_marker(text: str, markers: tuple[str, ...]) -> bool:
    """A REQUIRED marker word, matched strictly: ASCII letters, whole word.

    No folding here: a look-alike (Cyrillic i, long s, full-width) must not
    count as the marker. Only runs of whitespace between words are relaxed.
    """
    for marker in markers:
        words = [re.escape(w) for w in marker.split()]
        pattern = r"(?<![A-Za-z0-9_-])" + r"\s+".join(words) + r"(?![A-Za-z0-9_-])"
        if re.search(pattern, text, re.IGNORECASE | re.ASCII):
            return True
    return False


def _stated_counts(text: str, noun: str) -> list[str]:
    """Every number written as the count of ``noun`` (e.g. "30 jurisdictions").

    Up to two letter-only words may sit between the number and the noun
    ("50 rule categories"). The number token is returned raw, with any "+"
    and in whatever digits it was written, so "30+", "1,000" and non-ASCII
    digits never equal the live count.
    """
    pattern = (
        r"(?<![\w.,+])(\d[\d,.]*\+?)"
        r"\s+(?:[^\W\d_]+\s+){0,2}?"
        + noun
        + r"\b"
    )
    # Deliberately unfolded: a count split by a zero-width character is not
    # the count (the hygiene test rejects such characters in the README).
    return re.findall(pattern, text, re.IGNORECASE)


_GRADE_SEPARATORS = re.compile(
    r"\s*(?:,|/|;|\bor\b|\band\b|\bto\b|\s[-–—]\s|[–—])\s*", re.IGNORECASE
)
_PARENTHETICAL = re.compile(r"\([^)]*\)")


def _bad_grade_tokens(cell: str, allowed: frozenset[str]) -> list[str]:
    """Pieces of a grade cell that are not exactly an allowed grade.

    An empty cell is itself bad: a grade column with no grade is not a
    subset of anything (F5).
    """
    stripped = _MARKUP.sub("", _PARENTHETICAL.sub("", cell))
    pieces = [p.strip() for p in _GRADE_SEPARATORS.split(stripped)]
    pieces = [p for p in pieces if p]
    if not pieces:
        return ["<empty>"]
    return [p for p in pieces if p not in allowed]


# --------------------------------------------------------------------------
# Live values from their single sources of truth
# --------------------------------------------------------------------------

_HR9_ENTRY = re.compile(r"^\s*(\S+)\s*(<|>=)\s*(\d+(?:\.\d+)?)\s*$")


def _parse_hr9(text: str) -> list[tuple[str, str, float]]:
    """(grade, op, threshold) entries from the one HR9 line."""
    lines = [line for line in _LINE_ENDING.split(text) if line.startswith(HR9_LINE_PREFIX)]
    if len(lines) != 1:
        raise DocCheckError(
            f"{HR9_SOURCE_REL} has {len(lines)} lines starting {HR9_LINE_PREFIX!r}; need one"
        )
    body = lines[0][len(HR9_LINE_PREFIX):].strip().rstrip(".")
    entries: list[tuple[str, str, float]] = []
    for part in body.split(","):
        match = _HR9_ENTRY.match(part)
        if not match:
            raise DocCheckError(f"HR9 entry {_show(part)} is not '<grade> <op> <number>'")
        entries.append((match.group(1), match.group(2), float(match.group(3))))
    if not entries:
        raise DocCheckError("HR9 defines no grades")
    return entries


@pytest.fixture(scope="module")
def readme() -> str:
    return _read_text(REPO_ROOT, README_REL)


@pytest.fixture(scope="module")
def hr9_entries() -> list[tuple[str, str, float]]:
    return _parse_hr9(_read_text(REPO_ROOT, HR9_SOURCE_REL))


@pytest.fixture(scope="module")
def hr9_grades(hr9_entries: list[tuple[str, str, float]]) -> frozenset[str]:
    grades = [grade for grade, _, _ in hr9_entries]
    assert len(grades) == len(set(grades)), f"HR9 repeats a grade: {grades}"
    return frozenset(grades)


@pytest.fixture(scope="module")
def jurisdiction_count() -> int:
    from app.schemas import Jurisdiction

    codes = get_args(Jurisdiction)
    assert codes and len(codes) == len(set(codes)), "schemas.Jurisdiction is empty or repeats"
    return len(codes)


@pytest.fixture(scope="module")
def rule_category_count() -> int:
    from app.services.rules import PATTERNS

    categories = {pattern.category for pattern in PATTERNS}
    assert categories and all(c.strip() for c in categories), "rules.PATTERNS has no categories"
    return len(categories)


def _normalise_path(path: str) -> str:
    return re.sub(r"\{[^}]*\}", "{}", path)


@pytest.fixture(scope="module")
def live_endpoints() -> frozenset[tuple[str, str]]:
    from app.main import app

    endpoints = frozenset(
        (method.upper(), _normalise_path(path))
        for path, operations in app.openapi()["paths"].items()
        for method in operations
        if method in HTTP_METHODS
    )
    assert endpoints, "the live OpenAPI schema lists no endpoints"
    return endpoints


def _readme_endpoints(section: Section) -> list[tuple[str, str]]:
    for table in _tables(section):
        method_col = _column(table, r"\bmethod\b")
        path_col = _column(table, r"\b(?:endpoint|path)\b")
        if method_col is None or path_col is None:
            continue
        rows: list[tuple[str, str]] = []
        for row in table.rows:
            method = _MARKUP.sub("", row[method_col] if method_col < len(row) else "").strip()
            path = _MARKUP.sub("", row[path_col] if path_col < len(row) else "").strip()
            rows.append((method.upper(), _normalise_path(path)))
        return rows
    raise DocCheckError("README API Endpoints section has no Method/Endpoint table")


# --------------------------------------------------------------------------
# Acceptance tests (card #144 test spec)
# --------------------------------------------------------------------------


def test_readme_does_not_call_irp_planned(readme: str) -> None:
    _find_section(readme, FEATURES_HEADING)  # the claim lived here; it must still exist
    _find_section(readme, RISK_SCORING_HEADING)  # the live formula lives here
    assert not _irp_claimed_unimplemented(readme), (
        "README calls the IRP methodology planned / not yet implemented, but "
        "rules._seed_irp computes it on every finding and Risk Scoring publishes "
        "the formula. Fix: describe IRP as live in Features."
    )


def test_readme_grades_subset_of_hr9(readme: str, hr9_grades: frozenset[str]) -> None:
    section = _find_section(readme, RISK_SCORING_HEADING)
    graded = [(t, _column(t, r"\bgrades?\b")) for t in _tables(section)]
    graded = [(t, col) for t, col in graded if col is not None]
    assert graded, "README Risk Scoring section has no table with a Grade column"
    bad: list[str] = []
    for table, col in graded:
        assert table.rows, "README Risk Scoring grade table has no rows"
        for row in table.rows:
            cell = row[col] if col < len(row) else ""
            bad.extend(_bad_grade_tokens(cell, hr9_grades))
    assert not bad, (
        f"README Risk Scoring grades {[_show(b) for b in bad]} are not HR9 grades "
        f"{sorted(hr9_grades)}. Fix: use only HR9 grades."
    )


def test_readme_jurisdiction_count(readme: str, jurisdiction_count: int) -> None:
    _find_section(readme, FEATURES_HEADING)
    stated = _stated_counts(readme, "jurisdictions")
    assert stated, (
        f"README never states a jurisdiction count; schemas.Jurisdiction has "
        f"{jurisdiction_count}. Fix: say '{jurisdiction_count} jurisdictions'."
    )
    wrong = [s for s in stated if s != str(jurisdiction_count)]
    assert not wrong, (
        f"README states jurisdiction counts {[_show(s) for s in wrong]}; "
        f"schemas.Jurisdiction has {jurisdiction_count}."
    )


def test_readme_category_table_marked_illustrative(readme: str, rule_category_count: int) -> None:
    section = _find_section(readme, RISK_CATEGORIES_HEADING)
    tables = _tables(section)
    intro = _prose(section, until=tables[0].start if tables else None)
    assert _has_marker(intro, ILLUSTRATIVE_MARKERS), (
        "README Risk Categories heading is not followed by the word 'illustrative' "
        "before its table, so the table reads as the full list."
    )
    stated = _stated_counts(intro, r"categor(?:y|ies)")
    assert str(rule_category_count) in stated, (
        f"README Risk Categories intro does not state the live count "
        f"({rule_category_count} distinct categories in rules.PATTERNS); "
        f"it states {[_show(s) for s in stated]}."
    )
    wrong = [s for s in stated if s != str(rule_category_count)]
    assert not wrong, f"README Risk Categories intro states stale counts {wrong}"


def test_readme_endpoint_table_marked_partial(
    readme: str, live_endpoints: frozenset[tuple[str, str]]
) -> None:
    section = _find_section(readme, API_ENDPOINTS_HEADING)
    listed = frozenset(_readme_endpoints(section))
    if listed == live_endpoints:
        return  # a complete table needs no marker
    assert _has_marker(_prose(section), PARTIAL_MARKERS), (
        f"README API Endpoints table lists {len(listed)} of {len(live_endpoints)} "
        f"live endpoints but is not marked partial. Fix: say it is partial."
    )


# --------------------------------------------------------------------------
# Positive controls (green today) and source integrity
# --------------------------------------------------------------------------


def test_readme_endpoint_rows_exist_in_live_api(
    readme: str, live_endpoints: frozenset[tuple[str, str]]
) -> None:
    rows = _readme_endpoints(_find_section(readme, API_ENDPOINTS_HEADING))
    assert rows, "README API Endpoints table has no rows"
    invented = [r for r in rows if r not in live_endpoints]
    assert not invented, f"README lists endpoints the app does not serve: {invented}"


def _hr9_grade(entries: list[tuple[str, str, float]], score: float) -> str:
    """Reference reading of HR9: the first '<' band the score is under, else '>='."""
    for grade, op, threshold in sorted(entries, key=lambda e: e[2]):
        if op == "<" and score < threshold:
            return grade
    tops = [grade for grade, op, threshold in entries if op == ">=" and score >= threshold]
    if len(tops) != 1:
        raise DocCheckError(f"HR9 does not grade score {score} exactly once")
    return tops[0]


def test_hr9_grades_match_analyzer_grade(hr9_entries: list[tuple[str, str, float]]) -> None:
    """HR9 (the grade source here) and analyzer._grade agree on every band.

    Probes: each threshold, just below it, midpoints between thresholds, and
    both open ends (so an invented grade above the top band goes red).
    """
    from app.services.analyzer import _grade

    thresholds = sorted({t for _, _, t in hr9_entries})
    probes = [-math.inf, math.inf, *thresholds]
    probes += [math.nextafter(t, -math.inf) for t in thresholds]
    probes += [(a + b) / 2 for a, b in zip(thresholds, thresholds[1:])]
    mismatched = [(p, _grade(p), _hr9_grade(hr9_entries, p)) for p in probes
                  if _grade(p) != _hr9_grade(hr9_entries, p)]
    assert not mismatched, f"analyzer._grade disagrees with HR9 at {mismatched}"
    assert {_grade(p) for p in probes} == {g for g, _, _ in hr9_entries}


def test_readme_text_is_clean_utf8(readme: str) -> None:
    bad = _forbidden_chars(readme)
    assert not bad, f"README carries invisible/control characters at {bad[:10]}"


def test_doc_sources_are_regular_tracked_files() -> None:
    for rel in (README_REL, HR9_SOURCE_REL):
        path = REPO_ROOT / rel
        assert not path.is_symlink(), f"{rel} is a symlink"
        assert path.is_file(), f"{rel} is missing"


# --------------------------------------------------------------------------
# Checker vectors: each checker has positive and negative rows (contract)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Vector:
    checker: str
    text: str
    expected: bool
    note: str = field(default="")


_FENCED_HEADING = "intro\n```bash\n# Risk Scoring\n```\n"

CHECKERS: dict[str, Callable[[str], bool]] = {
    "irp_unimplemented": _irp_claimed_unimplemented,
    "illustrative": lambda t: _has_marker(t, ILLUSTRATIVE_MARKERS),
    "partial": lambda t: _has_marker(t, PARTIAL_MARKERS),
    "has_count_30": lambda t: _stated_counts(t, "jurisdictions") == ["30"],
    "finds_risk_scoring": lambda t: _section_found(t, RISK_SCORING_HEADING),
    "clean_text": lambda t: _forbidden_chars(t) == [],
}


def _section_found(text: str, wanted: str) -> bool:
    try:
        _find_section(text, wanted)
    except DocCheckError:
        return False
    return True


VECTORS: tuple[Vector, ...] = (
    # irp_unimplemented: the card's phrase and its disguises; and controls.
    Vector("irp_unimplemented", "IRP is a planned, not-yet-implemented enhancement", True),
    Vector("irp_unimplemented", "NOT YET IMPLEMENTED", True, "case"),
    Vector("irp_unimplemented", "not yet\nimplemented", True, "soft wrap"),
    Vector("irp_unimplemented", "- the IRP method is\n  planned", True, "wrapped bullet"),
    Vector("irp_unimplemented", "Impact/Likelihood/Safeguards scoring is planned", True),
    Vector("irp_unimplemented", "IRP is unimplemented", True),
    Vector("irp_unimplemented", "ＩＲＰ is planned", True, "full-width"),
    Vector("irp_unimplemented", "IRP scores every finding.", False),
    Vector("irp_unimplemented", "- IRP scores findings\n- Watchlist export is planned", False,
           "planned in another bullet"),
    Vector("irp_unimplemented", "IRP is live. Vue 3 is planned.", False, "another sentence"),
    Vector("irp_unimplemented", "not yet\n\nimplemented", False, "separate paragraphs"),
    Vector("irp_unimplemented", "", False, "empty"),
    # illustrative: strict ASCII whole word.
    Vector("illustrative", "This table is illustrative.", True),
    Vector("illustrative", "ILLUSTRATIVE list", True),
    Vector("illustrative", "(Illustrative; 50 categories)", True),
    Vector("illustrative", "illuſtrative", False, "long s look-alike"),
    Vector("illustrative", "іllustrative", False, "Cyrillic i look-alike"),
    Vector("illustrative", "illustratively", False, "longer word"),
    Vector("illustrative", "illus​trative", False, "zero-width split"),
    Vector("illustrative", "", False, "empty"),
    # partial
    Vector("partial", "Partial list of endpoints.", True),
    Vector("partial", "This list is not\nexhaustive.", True),
    Vector("partial", "A non-exhaustive table.", True),
    Vector("partial", "Full API documentation at /docs.", False),
    Vector("partial", "impartial", False, "substring"),
    Vector("partial", "pаrtial", False, "Cyrillic a look-alike"),
    # has_count_30: stated count is exactly the token "30".
    Vector("has_count_30", "covers 30 jurisdictions", True),
    Vector("has_count_30", "covers 30 jurisdictions", True, "no-break space"),
    Vector("has_count_30", "covers 30 supported jurisdictions", True),
    Vector("has_count_30", "10 of the 30 jurisdictions", True, "only the count before noun"),
    Vector("has_count_30", "covers 30+ jurisdictions", False, "plus"),
    Vector("has_count_30", "covers 3​0 jurisdictions", False, "zero-width split digit"),
    Vector("has_count_30", "covers ٣٠ jurisdictions", False, "Arabic-Indic digits"),
    Vector("has_count_30", "covers ３０ jurisdictions", False, "full-width digits"),
    Vector("has_count_30", "covers 10 jurisdictions", False),
    Vector("has_count_30", "covers 130 jurisdictions", False, "superstring number"),
    Vector("has_count_30", "covers thirty jurisdictions", False, "words"),
    Vector("has_count_30", "", False, "empty"),
    # finds_risk_scoring: fence-aware ATX headings only.
    Vector("finds_risk_scoring", "## Risk Scoring\nbody", True),
    Vector("finds_risk_scoring", "   ## Risk Scoring ##\nbody", True, "indent + closing"),
    Vector("finds_risk_scoring", "## Risk Scoring (HR9)\nbody", True, "suffix"),
    Vector("finds_risk_scoring", "## **Risk Scoring**", True, "emphasis"),
    Vector("finds_risk_scoring", _FENCED_HEADING, False, "heading inside fence"),
    Vector("finds_risk_scoring", "    ## Risk Scoring", False, "indented code"),
    Vector("finds_risk_scoring", "##Risk Scoring", False, "no space after #"),
    Vector("finds_risk_scoring", "text ## Risk Scoring", False, "U+2028 is not a line end"),
    Vector("finds_risk_scoring", "## Risk Scorings", False, "longer word"),
    Vector("finds_risk_scoring", "## Risk Scoring\n## Risk Scoring", False, "duplicate"),
    Vector("finds_risk_scoring", "", False, "missing"),
    # clean_text
    Vector("clean_text", "plain — text × ├── ok\n\ttab", True),
    Vector("clean_text", "nul\x00", False),
    Vector("clean_text", "bidi‮", False),
    Vector("clean_text", "bom﻿", False),
    Vector("clean_text", "lone\ud800", False, "lone surrogate"),
    # One literal per forbidden category, independent of FORBIDDEN_CATEGORIES,
    # so dropping a category from the constant goes red here.
    Vector("clean_text", "esc\x1b", False, "Cc"),
    Vector("clean_text", "zwsp​", False, "Cf"),
    Vector("clean_text", "pua", False, "Co"),
    Vector("clean_text", "unassigned͸", False, "Cn"),
    Vector("clean_text", "line sep", False, "Zl"),
    Vector("clean_text", "para sep", False, "Zp"),
)


@pytest.mark.parametrize("vector", VECTORS, ids=lambda v: f"{v.checker}-{v.note or _show(v.text)}")
def test_checker_vectors(vector: Vector) -> None:
    assert CHECKERS[vector.checker](vector.text) is vector.expected, _show(vector.text)


def test_vectors_contract_every_checker_has_positive_and_negative() -> None:
    for name in CHECKERS:
        outcomes = {v.expected for v in VECTORS if v.checker == name}
        assert outcomes == {True, False}, f"checker {name!r} lacks a positive or negative vector"
    assert {v.checker for v in VECTORS} == set(CHECKERS)


def test_grade_cell_vectors(hr9_grades: frozenset[str]) -> None:
    """Grade cells: HR9 grades in any list form pass; anything else is reported."""
    allowed = sorted(hr9_grades)
    positives = [
        *allowed,
        " or ".join(allowed),
        ", ".join(allowed),
        " / ".join(allowed),
        f"**{allowed[0]}**",
        f"`{allowed[-1]}`",
        f"{allowed[0]} (best)",
        f"{allowed[0]} – {allowed[-1]}",
    ]
    for cell in positives:
        assert _bad_grade_tokens(cell, hr9_grades) == [], _show(cell)
    # Grades HR9 lacks, look-alikes of HR9 grades, and empty cells.
    lookalikes = [g.replace("-", "−") for g in allowed if "-" in g]
    full_width = {cp: cp + 0xFEE0 for cp in range(ord("A"), ord("Z") + 1)}
    lookalikes += [g.translate(full_width) for g in allowed]
    lookalikes += [g[0] + "​" + g[1:] for g in allowed if len(g) > 1]
    negatives = ["D or F", "F", "D", "E", "D+ or F", "n/a", "", "  ", "()", *lookalikes]
    for cell in negatives:
        assert _bad_grade_tokens(cell, hr9_grades) != [], _show(cell)
    assert set(_bad_grade_tokens("D or F", hr9_grades)) == {"D", "F"}


# --------------------------------------------------------------------------
# Generated hostile inputs (R2): every line break, dash and Cf code point
# --------------------------------------------------------------------------


def _all_chars(predicate: Callable[[str], bool]) -> list[str]:
    return [chr(cp) for cp in range(sys.maxunicode + 1) if predicate(chr(cp))]


def test_generated_disguises_of_unimplemented_are_caught() -> None:
    line_breaks = _all_chars(lambda c: len(f"a{c}b".splitlines()) == 2) + ["\r\n"]
    dashes = _all_chars(lambda c: unicodedata.category(c) == "Pd") + sorted(_EXTRA_DASHES)
    format_chars = _all_chars(lambda c: unicodedata.category(c) == "Cf")
    cases = [f"IRP: not{sep}yet{sep}implemented" for sep in line_breaks + dashes]
    cases += [f"IRP: not-ye{cf}t-implemented" for cf in format_chars]
    cases += [f"The IRP method is{sep}planned" for sep in line_breaks]
    missed = [_show(c) for c in cases if not _irp_claimed_unimplemented(c)]
    print(f"generated {len(cases)} disguised 'not yet implemented' cases")
    assert len(line_breaks) > 1 and len(dashes) > 1 and len(format_chars) > 1
    assert not missed, missed


def test_generated_forbidden_chars_are_all_flagged() -> None:
    hostile = _all_chars(
        lambda c: c not in ALLOWED_CONTROLS and unicodedata.category(c) in FORBIDDEN_CATEGORIES
    )
    flagged = {code for _, code in _forbidden_chars("".join(hostile))}
    expected = {f"U+{ord(c):04X}" for c in hostile}
    print(f"generated {len(hostile)} forbidden code points")
    assert {unicodedata.category(c) for c in hostile} == FORBIDDEN_CATEGORIES
    assert flagged == expected


def test_generated_line_breaks_do_not_forge_headings() -> None:
    """Only CommonMark line endings start a heading; other breaks do not."""
    commonmark = {"\n", "\r", "\r\n"}
    breaks = _all_chars(lambda c: len(f"a{c}b".splitlines()) == 2) + ["\r\n"]
    for brk in breaks:
        found = _section_found(f"text{brk}## {RISK_SCORING_HEADING}", RISK_SCORING_HEADING)
        assert found is (brk in commonmark), ascii(brk)


def test_huge_line_is_parsed() -> None:
    """A 2 MB line with a count buried at the end is still found."""
    filler = "word " * (2 * 1024 * 1024 // 5)
    assert _stated_counts(filler + "30 jurisdictions", "jurisdictions") == ["30"]
    assert not _irp_claimed_unimplemented(filler)


# --------------------------------------------------------------------------
# Readers and message safety
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (b"\xff\xfe bad", "not valid UTF-8"),
        (b"lone \xed\xa0\x80 surrogate", "not valid UTF-8"),
        (b"overlong \xc0\xaf", "not valid UTF-8"),
    ],
)
def test_read_text_rejects_invalid_utf8(tmp_path: Path, payload: bytes, reason: str) -> None:
    (tmp_path / "README.md").write_bytes(payload)
    with pytest.raises(DocCheckError, match=reason) as info:
        _read_text(tmp_path, "README.md")
    assert str(tmp_path) not in str(info.value)  # no absolute path in the message (F8)


def test_read_text_refuses_symlink_and_missing(tmp_path: Path) -> None:
    (tmp_path / "clean.md").write_text("## Risk Scoring\n", encoding="utf-8")
    (tmp_path / "README.md").symlink_to(tmp_path / "clean.md")
    with pytest.raises(DocCheckError, match="symlink") as info:
        _read_text(tmp_path, "README.md")
    assert str(tmp_path) not in str(info.value)
    with pytest.raises(DocCheckError, match="missing"):
        _read_text(tmp_path, "absent.md")


def test_read_text_keeps_nul_for_the_hygiene_check(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_bytes(b"ok\x00")
    assert _forbidden_chars(_read_text(tmp_path, "README.md")) == [(2, "U+0000")]


def test_show_escapes_and_truncates() -> None:
    hostile = "\x1b[31m‮" + "x" * (SHOW_LIMIT * 2)
    shown = _show(hostile)
    assert shown.isascii() and "\x1b" not in shown and "‮" not in shown
    assert shown.endswith(f"(+{len(hostile) - SHOW_LIMIT} chars)")
    assert _show("ok") == "'ok'"


def test_hr9_parser_fails_closed() -> None:
    with pytest.raises(DocCheckError, match="need one"):
        _parse_hr9("no grades here")
    with pytest.raises(DocCheckError, match="need one"):
        _parse_hr9(f"{HR9_LINE_PREFIX} A <1\n{HR9_LINE_PREFIX} B <2")
    with pytest.raises(DocCheckError, match="not '<grade> <op> <number>'"):
        _parse_hr9(f"{HR9_LINE_PREFIX} A about 3")
    assert _parse_hr9(f"{HR9_LINE_PREFIX} A <1, B >=1.") == [("A", "<", 1.0), ("B", ">=", 1.0)]
