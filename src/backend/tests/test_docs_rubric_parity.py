"""Rubric docs parity: LIB-EVAL against the 8-category spec rubric (#153, folds #48).

What card #153 promises, and the test that holds each promise:

- ``docs/specs/terms_reviewer_rubric.md`` is the anchor. Its Scoring Sheet is
  the single source of truth (F10) for rubric category names and weights.
  ``test_spec_scoring_sheet_*`` pin its internal consistency.
- LIB-EVAL's spec table (``## spec-rubric``) restates the Scoring Sheet row for
  row, in order (``test_lib_eval_spec_table_matches_spec``).
- LIB-EVAL's computed table (``## computed-rubric``) documents every
  ``RubricScores`` field (``test_lib_eval_computed_table_covers_rubric_scores``)
  and names nothing else.
- #48: the computed table is labelled a heuristic proxy with the exact line
  ``label: heuristic-proxy`` in ``## computed-rubric``, and its derivations are
  honest: the documented signal block and formulas, worked through on the same
  records, reproduce what ``GET /rubric`` returns
  (``test_lib_eval_computed_formulas_reproduce_rubric_endpoint``).
- #48: the spec rubric anchors ``GET /rubric``. ``overall`` is the
  Scoring-Sheet-weighted sum of the category scores
  (``test_rubric_endpoint_overall_is_spec_weighted``).
- PR #335 r1: LIB-EVAL documents what ``GET /rubric`` returns on an empty
  database, as one ``empty-response: `<json>``` line in ``## computed-rubric``.
  The documented JSON must equal what the endpoint actually returns with no
  analysis records (``test_lib_eval_documents_rubric_empty_database_response``).
- PR #335 r1: the critical-blocker rule is criterion-level, as in the spec.
  The spec's ``**Critical blockers:**`` clause and every LIB-EVAL line that
  mentions a blocker are parsed by one grammar, ``any <unit> <= N in <names>``,
  and must agree on unit, threshold and the Scoring Sheet categories named
  (``test_lib_eval_blocker_rule_matches_spec``).

Name normalisation. The spec names categories in prose ("AI Law Signal
Quality"); ``RubricScores`` names fields in camelCase (``aiLawSignalQuality``).
The join is ``SPEC_CATEGORY_TO_FIELD`` below: one explicit table, compared by
exact lookup after Unicode NFC. There is no case folding, no whitespace or
punctuation stripping and no NFKC, so look-alikes (Cyrillic, Greek, fullwidth,
NBSP) never match. The table cannot drift: its keys must equal the Scoring
Sheet names and its values must equal the ``RubricScores`` category fields.

Nothing here is restated from the code under test. Weights come from the
Scoring Sheet, score bounds from the ``RubricScores`` field constraints, and
analysis statuses from the ``AnalysisPayload.status`` Literal (F13).

The docs are prose, so the parsers are static by necessity. Each parser fails
closed (``RubricDocError``) on missing, duplicate, empty or malformed input,
and each is pinned by a vectors table with accept and reject rows, plus
generated hostile characters (QUALITY-BAR R2). Documented formulas are never
executed as Python: a tree walker accepts numbers, allowlisted names,
``+ - * /``, unary minus and ``clamp(x)``, and rejects everything else.
"""
from __future__ import annotations

import ast
import json
import math
import operator
import re
import sys
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import get_args
from uuid import uuid4

import annotated_types
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Analysis
from app.schemas import AnalysisPayload, RubricScores

REPO_ROOT = Path(__file__).resolve().parents[3]

# The two artifacts card #153 names. Repo-relative so failure messages carry no
# absolute paths (F8).
SPEC_RUBRIC = "docs/specs/terms_reviewer_rubric.md"
LIB_EVAL = ".claude/library/LIB-EVAL.md"

SPEC_SHEET_HEADING = "### Scoring Sheet"
SPEC_TOTAL_LABEL = "**Total**"
LIB_EVAL_SPEC_HEADING = "## spec-rubric"
LIB_EVAL_COMPUTED_HEADING = "## computed-rubric"
LIB_EVAL_PROXY_LABEL = "label: heuristic-proxy"
# LIB-EVAL key for the documented empty-database body of GET /rubric.
LIB_EVAL_EMPTY_KEY = "empty-response:"
# The spec's blocker clause label, and the word that marks a LIB-EVAL line as
# stating a blocker rule (every such line must parse; none may be prose-only).
SPEC_BLOCKER_LABEL = "**Critical blockers:**"
BLOCKER_TRIGGER = "blocker"
SIGNAL_FENCE_OPEN = "```python"
FENCE = "```"

CATEGORY_COLUMN = "Category"
WEIGHT_COLUMN = "Weight"
FIELD_COLUMN = "Field"
FORMULA_COLUMN = "Formula"

RUBRIC_PATH = "/rubric"

# The aggregate field. Every other RubricScores field is one rubric category.
OVERALL_FIELD = "overall"

# The documented mapping between spec display names and RubricScores fields.
SPEC_CATEGORY_TO_FIELD: dict[str, str] = {
    "Product Integrity": "productIntegrity",
    "Legal Signal Quality": "legalSignalQuality",
    "AI Law Signal Quality": "aiLawSignalQuality",
    "Privacy & Security": "privacySecurity",
    "Accessibility & Usability": "accessibilityUsability",
    "Visual & Interaction Design": "visualIxd",
    "Performance & Reliability": "performanceReliability",
    "Governance Readiness": "governanceReadiness",
}

RUBRIC_FIELDS: tuple[str, ...] = tuple(RubricScores.model_fields)
CATEGORY_FIELDS: tuple[str, ...] = tuple(f for f in RUBRIC_FIELDS if f != OVERALL_FIELD)

# The analysis statuses /rubric aggregates over, from the schema Literal. The
# review status is the one the endpoint counts into review_rate.
ANALYSIS_STATUSES: tuple[str, ...] = get_args(AnalysisPayload.model_fields["status"].annotation)
REVIEW_STATUS = "needs_review"
COMPLETED_STATUS = "completed"

# Names the LIB-EVAL signal block may read: the per-record aggregates it
# documents (E3), named as the doc names them. The test computes these from
# the seeded records.
SIGNAL_INPUT_NAMES: tuple[str, ...] = ("avg_risk_score", "avg_confidence", "review_rate")
CLAMP_NAME = "clamp"

# Float comparison for documented formula vs endpoint value (JSON round trip).
FLOAT_TOLERANCE = 1e-9

# Unicode categories never allowed anywhere in a parsed doc. "\n" is the one
# line separator; every other control, format, surrogate, private-use,
# unassigned, line- or paragraph-separator code point is rejected (F1).
FORBIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})
LINE_SEPARATOR = "\n"

_SHOW_LIMIT = 60


class RubricDocError(ValueError):
    """A rubric doc is missing, malformed, ambiguous or hostile."""


def _show(value: str) -> str:
    """Render untrusted doc text for a message: ASCII-escaped and truncated (F2, F8)."""
    text = ascii(value)
    if len(text) <= _SHOW_LIMIT:
        return text
    return f"{text[:_SHOW_LIMIT]}...(+{len(text) - _SHOW_LIMIT} chars)"


# --------------------------------------------------------------------------
# Reading and splitting docs
# --------------------------------------------------------------------------


def _read_doc(rel: str, root: Path = REPO_ROOT) -> str:
    """Read a tracked doc as strict UTF-8. Refuse symlinks and escapes (F7)."""
    rel_path = Path(rel)
    if rel_path.is_absolute() or ".." in rel_path.parts:
        raise RubricDocError(f"{_show(rel)}: doc path must be repo-relative")
    path = root / rel_path
    current = path
    while current != root:
        if current.is_symlink():
            raise RubricDocError(f"{rel}: is or sits under a symlink; parity must read the tracked file itself")
        current = current.parent
    if not path.is_file():
        raise RubricDocError(f"{rel}: missing; restore the tracked doc")
    try:
        return path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RubricDocError(f"{rel}: not valid UTF-8 at byte {exc.start}") from exc


def _lines(text: str, doc: str) -> list[tuple[str, bool]]:
    """Split on "\\n" only and mark fenced lines. Reject forbidden characters.

    Only "\\n" separates lines, as in the rendered markdown, so U+2028, NEL, CR
    and friends can never forge a row; they are rejected outright.
    """
    out: list[tuple[str, bool]] = []
    in_fence = False
    for number, line in enumerate(text.split(LINE_SEPARATOR), start=1):
        for char in line:
            category = unicodedata.category(char)
            if category in FORBIDDEN_CATEGORIES:
                raise RubricDocError(
                    f"{doc}: line {number} has forbidden character U+{ord(char):04X} "
                    f"(category {category}); rubric docs must be plain text"
                )
        if line.strip(" ").startswith(FENCE):
            if in_fence and line.strip(" ") != FENCE:
                raise RubricDocError(f"{doc}: line {number} opens a fence inside a fence")
            out.append((line, True))
            in_fence = not in_fence
            continue
        out.append((line, in_fence))
    if in_fence:
        raise RubricDocError(f"{doc}: unclosed code fence")
    return out


_HEADING = re.compile(r"(#{1,6}) \S.*")


def _section(text: str, heading: str, doc: str) -> list[tuple[str, bool]]:
    """Return the lines under ``heading`` up to the next heading of the same or higher level."""
    level_match = _HEADING.fullmatch(heading)
    if level_match is None:
        raise RubricDocError(f"{_show(heading)} is not a markdown heading")
    level = len(level_match.group(1))
    lines = _lines(text, doc)
    starts = [i for i, (line, fenced) in enumerate(lines) if not fenced and line == heading]
    if len(starts) != 1:
        raise RubricDocError(f"{doc}: heading {_show(heading)} must appear exactly once; found {len(starts)}")
    body: list[tuple[str, bool]] = []
    for line, fenced in lines[starts[0] + 1 :]:
        if not fenced:
            match = _HEADING.fullmatch(line)
            if match is not None and len(match.group(1)) <= level:
                break
        body.append((line, fenced))
    return body


_SEPARATOR_CELL = re.compile(r":?-{3,}:?")


def _cells(line: str, where: str) -> list[str]:
    stripped = line.strip(" ")
    if not (stripped.startswith("|") and stripped.endswith("|") and len(stripped) >= 2):
        raise RubricDocError(f"{where}: table row {_show(line)} must start and end with '|'")
    inner = stripped[1:-1]
    if "\\|" in inner:
        raise RubricDocError(f"{where}: escaped '|' in a table row is not supported")
    return [unicodedata.normalize("NFC", cell.strip(" ")) for cell in inner.split("|")]


def _only_table(section: list[tuple[str, bool]], doc: str, where: str) -> list[dict[str, str]]:
    """Parse the one table in a section into header->cell rows. Fails closed."""
    tables: list[list[str]] = []
    current: list[str] = []
    for line, fenced in section:
        if not fenced and line.startswith("|"):
            current.append(line)
            continue
        if current:
            tables.append(current)
            current = []
    if current:
        tables.append(current)
    label = f"{doc} {where}"
    if len(tables) != 1:
        raise RubricDocError(f"{label}: expected exactly one table; found {len(tables)}")
    table = tables[0]
    if len(table) < 2:
        raise RubricDocError(f"{label}: table has no separator row")
    header = _cells(table[0], label)
    separator = _cells(table[1], label)
    if len(separator) != len(header) or not all(_SEPARATOR_CELL.fullmatch(c) for c in separator):
        raise RubricDocError(f"{label}: malformed separator row {_show(table[1])}")
    if len(set(header)) != len(header) or not all(header):
        raise RubricDocError(f"{label}: header cells must be non-empty and unique")
    rows: list[dict[str, str]] = []
    for raw in table[2:]:
        cells = _cells(raw, label)
        if len(cells) != len(header):
            raise RubricDocError(f"{label}: row {_show(raw)} has {len(cells)} cells; header has {len(header)}")
        rows.append(dict(zip(header, cells)))
    if not rows:
        raise RubricDocError(f"{label}: table has no rows")
    return rows


def _column(row: Mapping[str, str], column: str, where: str) -> str:
    if column not in row:
        raise RubricDocError(f"{where}: table has no {column!r} column")
    return row[column]


# --------------------------------------------------------------------------
# Category rows: (name, weight)
# --------------------------------------------------------------------------

_DECIMAL_WEIGHT = re.compile(r"[01]\.[0-9]{1,4}")
_PERCENT_WEIGHT = re.compile(r"(?:100|[1-9][0-9]?)%")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")


def _parse_weight(cell: str, where: str) -> Decimal:
    """Parse "0.20" or "20%" into a Decimal fraction in (0, 1]. ASCII digits only."""
    if _DECIMAL_WEIGHT.fullmatch(cell):
        value = Decimal(cell)
    elif _PERCENT_WEIGHT.fullmatch(cell):
        value = Decimal(cell[:-1]) / 100
    else:
        raise RubricDocError(f"{where}: weight {_show(cell)} is neither a decimal like 0.20 nor a percentage like 20%")
    if not Decimal(0) < value <= Decimal(1):
        raise RubricDocError(f"{where}: weight {_show(cell)} is outside (0, 1]")
    return value


def _category_rows(
    rows: Sequence[Mapping[str, str]], doc: str, where: str, *, total_required: bool
) -> list[tuple[str, Decimal]]:
    """(name, weight) rows. A **Total** row, when present, must be last and equal the sum."""
    label = f"{doc} {where}"
    names = [_column(row, CATEGORY_COLUMN, label) for row in rows]
    total_rows = [i for i, name in enumerate(names) if name == SPEC_TOTAL_LABEL]
    if len(total_rows) > 1 or (total_rows and total_rows[0] != len(rows) - 1):
        raise RubricDocError(f"{label}: the {SPEC_TOTAL_LABEL} row must appear at most once, as the last row")
    if total_required and not total_rows:
        raise RubricDocError(f"{label}: missing the {SPEC_TOTAL_LABEL} row")
    body = rows[:-1] if total_rows else rows
    if not body:
        raise RubricDocError(f"{label}: no category rows")
    parsed: list[tuple[str, Decimal]] = []
    for row in body:
        name = row[CATEGORY_COLUMN]
        if not name:
            raise RubricDocError(f"{label}: empty category name")
        parsed.append((name, _parse_weight(_column(row, WEIGHT_COLUMN, label), label)))
    seen = [name for name, _ in parsed]
    if len(set(seen)) != len(seen):
        raise RubricDocError(f"{label}: duplicate category names")
    if total_rows:
        bold = _BOLD.fullmatch(rows[-1][WEIGHT_COLUMN])
        if bold is None:
            raise RubricDocError(f"{label}: total weight {_show(rows[-1][WEIGHT_COLUMN])} must be bold")
        stated = _parse_weight(bold.group(1), label)
        if stated != sum(weight for _, weight in parsed):
            raise RubricDocError(f"{label}: stated total {stated} does not equal the row sum")
    return parsed


def _spec_sheet_rows(text: str) -> list[tuple[str, Decimal]]:
    rows = _only_table(_section(text, SPEC_SHEET_HEADING, SPEC_RUBRIC), SPEC_RUBRIC, SPEC_SHEET_HEADING)
    return _category_rows(rows, SPEC_RUBRIC, SPEC_SHEET_HEADING, total_required=True)


def _lib_eval_spec_rows(text: str) -> list[tuple[str, Decimal]]:
    rows = _only_table(_section(text, LIB_EVAL_SPEC_HEADING, LIB_EVAL), LIB_EVAL, LIB_EVAL_SPEC_HEADING)
    return _category_rows(rows, LIB_EVAL, LIB_EVAL_SPEC_HEADING, total_required=False)


_SPEC_CATEGORY_HEADING = re.compile(r"## ([1-9][0-9]*)\. (.+) \(Weight ([^)]*)\)")
_NUMBERED_H2 = re.compile(r"## [0-9]")


def _spec_heading_rows(text: str) -> list[tuple[str, Decimal]]:
    """(name, weight) from the spec's "## N. Name (Weight X%)" section headings."""
    parsed: list[tuple[str, Decimal]] = []
    for line, fenced in _lines(text, SPEC_RUBRIC):
        if fenced or not _NUMBERED_H2.match(line):
            continue
        match = _SPEC_CATEGORY_HEADING.fullmatch(line)
        if match is None:
            raise RubricDocError(f"{SPEC_RUBRIC}: malformed category heading {_show(line)}")
        if int(match.group(1)) != len(parsed) + 1:
            raise RubricDocError(f"{SPEC_RUBRIC}: category heading {_show(line)} is out of sequence")
        name = unicodedata.normalize("NFC", match.group(2))
        parsed.append((name, _parse_weight(match.group(3), SPEC_RUBRIC)))
    if not parsed:
        raise RubricDocError(f"{SPEC_RUBRIC}: no numbered category headings")
    return parsed


def _field_for(name: str) -> str:
    """Exact lookup in the documented mapping. No folding; look-alikes miss."""
    field = SPEC_CATEGORY_TO_FIELD.get(unicodedata.normalize("NFC", name))
    if field is None:
        raise RubricDocError(f"category {_show(name)} is not in SPEC_CATEGORY_TO_FIELD")
    return field


# --------------------------------------------------------------------------
# LIB-EVAL computed table, label and signal block
# --------------------------------------------------------------------------

_FIELD_CELL = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)`")
_CODE_SPAN = re.compile(r"`([^`]+)`")


def _field_cell(cell: str, where: str) -> str:
    match = _FIELD_CELL.fullmatch(cell)
    if match is None:
        raise RubricDocError(f"{where}: field cell {_show(cell)} must be one backticked identifier")
    return match.group(1)


def _lib_eval_computed_formulas(text: str) -> dict[str, str]:
    """Field -> first code span of its Formula cell, from the computed table."""
    label = f"{LIB_EVAL} {LIB_EVAL_COMPUTED_HEADING}"
    rows = _only_table(_section(text, LIB_EVAL_COMPUTED_HEADING, LIB_EVAL), LIB_EVAL, LIB_EVAL_COMPUTED_HEADING)
    formulas: dict[str, str] = {}
    for row in rows:
        field = _field_cell(_column(row, FIELD_COLUMN, label), label)
        if field in formulas:
            raise RubricDocError(f"{label}: field {field!r} is documented twice")
        span = _CODE_SPAN.search(_column(row, FORMULA_COLUMN, label))
        if span is None:
            raise RubricDocError(f"{label}: field {field!r} has no backticked formula")
        formulas[field] = span.group(1)
    return formulas


def _lib_eval_signal_block(text: str) -> str:
    """The one ```python block in the computed section (E3 signal definitions)."""
    section = _section(text, LIB_EVAL_COMPUTED_HEADING, LIB_EVAL)
    blocks: list[list[str]] = []
    collecting = False
    for line, fenced in section:
        if fenced and line.strip(" ") == SIGNAL_FENCE_OPEN:
            collecting = True
            blocks.append([])
            continue
        if fenced and line.strip(" ") == FENCE:
            collecting = False
            continue
        if collecting:
            blocks[-1].append(line)
    if len(blocks) != 1:
        raise RubricDocError(
            f"{LIB_EVAL} {LIB_EVAL_COMPUTED_HEADING}: expected one {SIGNAL_FENCE_OPEN} block; found {len(blocks)}"
        )
    return LINE_SEPARATOR.join(blocks[0])


def _require_label(section: list[tuple[str, bool]], label: str, where: str) -> None:
    hits = [line for line, fenced in section if not fenced and line == label]
    if len(hits) != 1:
        raise RubricDocError(f"{where}: needs the line {label!r} exactly once outside code; found {len(hits)}")


# --------------------------------------------------------------------------
# LIB-EVAL empty-database response (PR #335 r1, finding 1)
# --------------------------------------------------------------------------

_EMPTY_RESPONSE = re.compile(re.escape(LIB_EVAL_EMPTY_KEY) + r" `([^`]+)`(?: \S.*)?")


def _reject_json_constant(name: str) -> object:
    raise RubricDocError(f"JSON constant {_show(name)} is not a JSON value")


def _lib_eval_empty_response(text: str) -> object:
    """The JSON body LIB-EVAL documents for GET /rubric with no analysis records.

    Exactly one ``empty-response: `<json>``` line, outside code, in
    ``## computed-rubric``. The first code span is parsed as strict JSON (no
    NaN/Infinity); prose may follow it.
    """
    where = f"{LIB_EVAL} {LIB_EVAL_COMPUTED_HEADING}"
    section = _section(text, LIB_EVAL_COMPUTED_HEADING, LIB_EVAL)
    hits = [line for line, fenced in section if not fenced and line.startswith(LIB_EVAL_EMPTY_KEY)]
    if len(hits) != 1:
        raise RubricDocError(
            f"{where}: needs one '{LIB_EVAL_EMPTY_KEY} `<json>`' line outside code documenting what "
            f"GET {RUBRIC_PATH} returns with no analysis records; found {len(hits)}"
        )
    match = _EMPTY_RESPONSE.fullmatch(hits[0])
    if match is None:
        raise RubricDocError(f"{where}: {_show(hits[0])} must be '{LIB_EVAL_EMPTY_KEY} `<json>`' then optional prose")
    try:
        return json.loads(match.group(1), parse_constant=_reject_json_constant)
    except (ValueError, RecursionError) as exc:
        raise RubricDocError(f"{where}: {_show(match.group(1))} is not strict JSON") from exc


# --------------------------------------------------------------------------
# Critical-blocker rule (PR #335 r1, finding 2): one grammar for both docs
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Blocker:
    unit: str  # what is scored: "criterion" in the spec today
    threshold: int  # a score <= threshold blocks
    categories: frozenset[str]  # Scoring Sheet names the rule covers


# "any <unit> <= N in A, B, or C". ASCII digits only, at most 3 (no int bomb).
_BLOCKER_CLAUSE = re.compile(r"any (?P<unit>[a-z]+) (?:≤|<=) ?(?P<threshold>[0-9]{1,3}) in (?P<names>[^.;]+)")
_BLOCKER_LIST_SPLIT = re.compile(r",(?: or)? | or ")


def _blocker_category(name: str, sheet_names: Sequence[str], where: str) -> str:
    """A name in the clause is a Scoring Sheet name or a unique whole-word prefix of one."""
    name = unicodedata.normalize("NFC", name)
    hits = [s for s in sheet_names if s == name or s.startswith(name + " ")]
    if not name or len(hits) != 1:
        raise RubricDocError(f"{where}: blocker category {_show(name)} names {len(hits)} Scoring Sheet categories")
    return hits[0]


def _blocker_match(text: str, sheet_names: Sequence[str], where: str) -> tuple[Blocker, int]:
    """Parse the one blocker clause in ``text``; return it and where it ends. Zero or several fail closed."""
    matches = list(_BLOCKER_CLAUSE.finditer(text))
    if len(matches) != 1:
        raise RubricDocError(
            f"{where}: {_show(text)} must state the blocker as 'any <unit> <= N in <categories>' "
            f"exactly once; found {len(matches)}"
        )
    match = matches[0]
    parts = _BLOCKER_LIST_SPLIT.split(match.group("names").rstrip(" "))
    categories = [_blocker_category(part, sheet_names, where) for part in parts]
    if len(set(categories)) != len(categories):
        raise RubricDocError(f"{where}: blocker names a category twice")
    return Blocker(match.group("unit"), int(match.group("threshold")), frozenset(categories)), match.end()


def _blocker_in(text: str, sheet_names: Sequence[str], where: str) -> Blocker:
    return _blocker_match(text, sheet_names, where)[0]


def _spec_blocker(text: str, sheet_names: Sequence[str]) -> Blocker:
    """The spec's ``**Critical blockers:**`` clause: one label, outside code, ending the line."""
    hits = [line for line, fenced in _lines(text, SPEC_RUBRIC) if not fenced and SPEC_BLOCKER_LABEL in line]
    if len(hits) != 1 or hits[0].count(SPEC_BLOCKER_LABEL) != 1:
        raise RubricDocError(f"{SPEC_RUBRIC}: needs {SPEC_BLOCKER_LABEL!r} exactly once outside code")
    clause = hits[0].split(SPEC_BLOCKER_LABEL, 1)[1]
    blocker, end = _blocker_match(clause, sheet_names, SPEC_RUBRIC)
    tail = clause[end:].strip(" ")
    if tail not in ("", "."):
        raise RubricDocError(f"{SPEC_RUBRIC}: unexpected text {_show(tail)} after the blocker clause")
    return blocker


def _lib_eval_blockers(text: str, sheet_names: Sequence[str]) -> list[Blocker]:
    """Every LIB-EVAL line outside code that mentions a blocker, parsed. None is a failure."""
    lines = [line for line, fenced in _lines(text, LIB_EVAL) if not fenced and BLOCKER_TRIGGER in line.casefold()]
    if not lines:
        raise RubricDocError(f"{LIB_EVAL}: states no {BLOCKER_TRIGGER} rule; restate the spec's {SPEC_BLOCKER_LABEL}")
    return [_blocker_in(line, sheet_names, LIB_EVAL) for line in lines]


# --------------------------------------------------------------------------
# Formula arithmetic: an allowlisted tree walker; doc text is never executed
# --------------------------------------------------------------------------

_BINARY_OPERATORS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
_UNARY_OPERATORS: dict[type[ast.unaryop], Callable[[float], float]] = {
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _walk(node: ast.expr, names: Mapping[str, float], clamp: Callable[[float], float]) -> float:
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id not in names:
            raise RubricDocError(f"formula uses unknown name {_show(node.id)}")
        return names[node.id]
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        left = _walk(node.left, names, clamp)
        right = _walk(node.right, names, clamp)
        try:
            return _BINARY_OPERATORS[type(node.op)](left, right)
        except ZeroDivisionError as exc:
            raise RubricDocError("formula divides by zero") from exc
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        return _UNARY_OPERATORS[type(node.op)](_walk(node.operand, names, clamp))
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == CLAMP_NAME
        and len(node.args) == 1
        and not node.keywords
    ):
        return clamp(_walk(node.args[0], names, clamp))
    raise RubricDocError(f"formula uses unsupported syntax {type(node).__name__}")


def _compute(source: str, names: Mapping[str, float], clamp: Callable[[float], float]) -> float:
    try:
        tree = ast.parse(source, mode="eval")
        return _walk(tree.body, names, clamp)
    except RubricDocError:
        raise
    except (SyntaxError, RecursionError, ValueError) as exc:
        raise RubricDocError(f"formula {_show(source)} does not parse ({type(exc).__name__})") from exc


def _run_signal_block(source: str, inputs: Mapping[str, float], clamp: Callable[[float], float]) -> dict[str, float]:
    """Work through ``name = expr`` lines in order. No rebinding, nothing but assignments."""
    try:
        tree = ast.parse(source, mode="exec")
    except (SyntaxError, RecursionError, ValueError) as exc:
        raise RubricDocError(f"signal block does not parse ({type(exc).__name__})") from exc
    if not tree.body:
        raise RubricDocError("signal block assigns nothing")
    names = dict(inputs)
    for statement in tree.body:
        if not (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        ):
            raise RubricDocError(f"signal block allows only 'name = expr'; got {type(statement).__name__}")
        target = statement.targets[0].id
        if target in names or target == CLAMP_NAME:
            raise RubricDocError(f"signal block rebinds {_show(target)}")
        try:
            names[target] = _walk(statement.value, names, clamp)
        except RecursionError as exc:
            raise RubricDocError("signal block expression is too deep") from exc
    return names


def _score_bounds() -> tuple[float, float]:
    """The one [lower, upper] every RubricScores field is constrained to (schema-derived)."""
    bounds: set[tuple[float, float]] = set()
    for name, info in RubricScores.model_fields.items():
        lower = [m.ge for m in info.metadata if isinstance(m, annotated_types.Ge)]
        upper = [m.le for m in info.metadata if isinstance(m, annotated_types.Le)]
        if len(lower) != 1 or len(upper) != 1:
            raise RubricDocError(f"RubricScores.{name} needs exactly one ge and one le bound")
        bounds.add((float(lower[0]), float(upper[0])))
    if len(bounds) != 1:
        raise RubricDocError("RubricScores fields disagree on score bounds")
    return bounds.pop()


def _make_clamp() -> Callable[[float], float]:
    lower, upper = _score_bounds()

    def clamp(value: float) -> float:
        return max(lower, min(upper, value))

    return clamp


# --------------------------------------------------------------------------
# /rubric record vectors
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RecordSpec:
    risk_score: float
    confidence: float
    status: str


# Mixed sets give every category a distinct value; the corner sets pin the
# all-best and all-worst records.
RUBRIC_VECTORS: dict[str, tuple[RecordSpec, ...]] = {
    "two-completed": (
        RecordSpec(3.0, 0.85, COMPLETED_STATUS),
        RecordSpec(1.0, 0.95, COMPLETED_STATUS),
    ),
    "half-review": (
        RecordSpec(5.0, 0.70, REVIEW_STATUS),
        RecordSpec(2.0, 0.90, COMPLETED_STATUS),
    ),
    "mostly-review": (
        RecordSpec(7.5, 0.40, REVIEW_STATUS),
        RecordSpec(6.0, 0.55, REVIEW_STATUS),
        RecordSpec(2.5, 0.92, COMPLETED_STATUS),
    ),
    "best-corner": (RecordSpec(0.0, 1.0, COMPLETED_STATUS),),
    "worst-corner": (RecordSpec(10.0, 0.0, REVIEW_STATUS),),
}


def _seed(db_session: Session, records: Sequence[RecordSpec]) -> None:
    for record in records:
        db_session.add(
            Analysis(
                id=str(uuid4()),
                source_type="text",
                status=record.status,
                confidence=record.confidence,
                risk_score=record.risk_score,
                grade="A",
                result_json="{}",
            )
        )
    db_session.commit()


def _signal_inputs(records: Sequence[RecordSpec]) -> dict[str, float]:
    """The aggregates LIB-EVAL's E3 block documents as its inputs."""
    count = len(records)
    values = (
        sum(r.risk_score for r in records) / count,
        sum(r.confidence for r in records) / count,
        sum(1 for r in records if r.status == REVIEW_STATUS) / count,
    )
    return dict(zip(SIGNAL_INPUT_NAMES, values))


def _get_rubric(client: TestClient) -> dict[str, float]:
    response = client.get(RUBRIC_PATH)
    assert response.status_code == 200, f"GET {RUBRIC_PATH} returned {response.status_code}"
    body = response.json()
    assert isinstance(body, dict), f"GET {RUBRIC_PATH} returned no scores for seeded records"
    return body


# --------------------------------------------------------------------------
# Acceptance tests (card #153 test spec, plus #48)
# --------------------------------------------------------------------------


def test_rubric_schema_constants_are_wired() -> None:
    """The names the tests key on exist in the schema, so no exclusion is a silent no-op."""
    assert OVERALL_FIELD in RUBRIC_FIELDS
    assert REVIEW_STATUS in ANALYSIS_STATUSES and COMPLETED_STATUS in ANALYSIS_STATUSES
    assert all(r.status in ANALYSIS_STATUSES for v in RUBRIC_VECTORS.values() for r in v)
    assert RUBRIC_VECTORS and all(RUBRIC_VECTORS.values())


def test_spec_scoring_sheet_has_one_row_per_rubric_category_and_weights_sum_to_one() -> None:
    rows = _spec_sheet_rows(_read_doc(SPEC_RUBRIC))
    assert len(rows) == len(CATEGORY_FIELDS), (
        f"{SPEC_RUBRIC} Scoring Sheet has {len(rows)} categories; RubricScores has {len(CATEGORY_FIELDS)}"
    )
    assert math.isclose(float(sum(w for _, w in rows)), 1.0, abs_tol=FLOAT_TOLERANCE)


def test_spec_scoring_sheet_matches_spec_section_headings() -> None:
    text = _read_doc(SPEC_RUBRIC)
    assert _spec_heading_rows(text) == _spec_sheet_rows(text), (
        f"{SPEC_RUBRIC}: the '## N. Name (Weight X%)' headings disagree with the Scoring Sheet"
    )


def test_spec_category_mapping_matches_rubric_scores_fields() -> None:
    names = [name for name, _ in _spec_sheet_rows(_read_doc(SPEC_RUBRIC))]
    assert list(SPEC_CATEGORY_TO_FIELD) == names, "SPEC_CATEGORY_TO_FIELD keys drifted from the Scoring Sheet"
    assert sorted(SPEC_CATEGORY_TO_FIELD.values()) == sorted(CATEGORY_FIELDS), (
        "SPEC_CATEGORY_TO_FIELD values drifted from the RubricScores category fields"
    )


def test_lib_eval_spec_table_matches_spec() -> None:
    spec = _spec_sheet_rows(_read_doc(SPEC_RUBRIC))
    lib_eval = _lib_eval_spec_rows(_read_doc(LIB_EVAL))
    missing = sorted({n for n, _ in spec} - {n for n, _ in lib_eval})
    assert len(lib_eval) == len(spec), (
        f"{LIB_EVAL} {LIB_EVAL_SPEC_HEADING} has {len(lib_eval)} categories; "
        f"{SPEC_RUBRIC} Scoring Sheet has {len(spec)}. Missing: {missing}"
    )
    assert math.isclose(float(sum(w for _, w in lib_eval)), 1.0, abs_tol=FLOAT_TOLERANCE)
    differing = [(str(s), str(lib)) for s, lib in zip(spec, lib_eval) if s != lib]
    assert lib_eval == spec, f"{LIB_EVAL} spec table differs from the Scoring Sheet (spec, lib-eval): {differing}"


# Card #153 says "every RubricScores field". The brief excludes the aggregate;
# covering it too is strictly stronger, and its row is what the honesty test
# checks against the endpoint.
@pytest.mark.parametrize("field", RUBRIC_FIELDS)
def test_lib_eval_computed_table_covers_rubric_scores(field: str) -> None:
    documented = _lib_eval_computed_formulas(_read_doc(LIB_EVAL))
    assert field in documented, (
        f"RubricScores.{field} has no row in {LIB_EVAL} {LIB_EVAL_COMPUTED_HEADING}; document its derivation"
    )


def test_lib_eval_computed_table_names_only_rubric_scores_fields() -> None:
    documented = _lib_eval_computed_formulas(_read_doc(LIB_EVAL))
    unknown = sorted(set(documented) - set(RUBRIC_FIELDS))
    assert not unknown, f"{LIB_EVAL} computed table documents fields RubricScores lacks: {unknown}"


def test_lib_eval_computed_table_is_labelled_heuristic_proxy() -> None:
    section = _section(_read_doc(LIB_EVAL), LIB_EVAL_COMPUTED_HEADING, LIB_EVAL)
    _require_label(section, LIB_EVAL_PROXY_LABEL, f"{LIB_EVAL} {LIB_EVAL_COMPUTED_HEADING}")


@pytest.mark.parametrize("vector", sorted(RUBRIC_VECTORS))
def test_lib_eval_computed_formulas_reproduce_rubric_endpoint(
    vector: str, app_client: TestClient, db_session: Session
) -> None:
    records = RUBRIC_VECTORS[vector]
    _seed(db_session, records)
    body = _get_rubric(app_client)
    text = _read_doc(LIB_EVAL)
    clamp = _make_clamp()
    signals = _run_signal_block(_lib_eval_signal_block(text), _signal_inputs(records), clamp)
    categories = {field: float(body[field]) for field in CATEGORY_FIELDS}
    mismatches: list[str] = []
    for field, source in _lib_eval_computed_formulas(text).items():
        if field not in body:
            mismatches.append(f"{field}: not a RubricScores field")
            continue
        # Only overall may combine category scores; a category row that named
        # its own field would be a tautology.
        names = {**signals, **categories} if field == OVERALL_FIELD else signals
        documented = _compute(source, names, clamp)
        if not math.isclose(documented, body[field], rel_tol=FLOAT_TOLERANCE, abs_tol=FLOAT_TOLERANCE):
            mismatches.append(
                f"{field}: documented {_show(source)} gives {documented:.6f}; "
                f"GET {RUBRIC_PATH} returns {body[field]:.6f}"
            )
    assert not mismatches, f"{LIB_EVAL} computed table is not what /rubric computes: {mismatches}"


@pytest.mark.parametrize("vector", sorted(RUBRIC_VECTORS))
def test_rubric_endpoint_overall_is_spec_weighted(vector: str, app_client: TestClient, db_session: Session) -> None:
    _seed(db_session, RUBRIC_VECTORS[vector])
    body = _get_rubric(app_client)
    weights = _spec_sheet_rows(_read_doc(SPEC_RUBRIC))
    expected = _make_clamp()(sum(float(w) * float(body[_field_for(name)]) for name, w in weights))
    assert math.isclose(body[OVERALL_FIELD], expected, rel_tol=FLOAT_TOLERANCE, abs_tol=FLOAT_TOLERANCE), (
        f"GET {RUBRIC_PATH} overall {body[OVERALL_FIELD]:.6f} is not the Scoring-Sheet-weighted sum {expected:.6f}"
    )


def test_lib_eval_documents_rubric_empty_database_response(app_client: TestClient, db_session: Session) -> None:
    """PR #335 r1 finding 1: LIB-EVAL says what /rubric returns with no records, and it is true.

    The expected body is not restated here: it is whatever the endpoint returns
    on an empty database, so the doc follows the code if the contract changes.
    """
    assert db_session.query(Analysis).count() == 0, "precondition: the database must be empty"
    response = app_client.get(RUBRIC_PATH)
    assert response.status_code == 200, f"GET {RUBRIC_PATH} on an empty database returned {response.status_code}"
    actual = response.json()
    documented = _lib_eval_empty_response(_read_doc(LIB_EVAL))
    # Type check too: 0 == False and 1.0 == 1 would otherwise pass.
    assert type(documented) is type(actual) and documented == actual, (
        f"{LIB_EVAL} documents {_show(json.dumps(documented))} for an empty database; "
        f"GET {RUBRIC_PATH} returns {_show(json.dumps(actual))}"
    )


def test_lib_eval_blocker_rule_matches_spec() -> None:
    """PR #335 r1 finding 2: every LIB-EVAL blocker statement equals the spec's clause.

    Unit (criterion vs category), threshold and covered categories all come
    from the spec's ``**Critical blockers:**`` line, resolved against the
    Scoring Sheet; nothing is restated here.
    """
    spec_text = _read_doc(SPEC_RUBRIC)
    sheet_names = [name for name, _ in _spec_sheet_rows(spec_text)]
    spec = _spec_blocker(spec_text, sheet_names)
    lib_eval = _lib_eval_blockers(_read_doc(LIB_EVAL), sheet_names)
    differing = [blocker for blocker in lib_eval if blocker != spec]
    assert not differing, f"{LIB_EVAL} blocker rule differs from {SPEC_RUBRIC} {spec}: {differing}"


# --------------------------------------------------------------------------
# Parser vectors (QUALITY-BAR R2): accept and reject rows per parser
# --------------------------------------------------------------------------

REJECT = object()

_MINI_SPEC_LINES: tuple[str, ...] = (
    "# Rubric",
    "",
    SPEC_SHEET_HEADING,
    "| Category | Weight | Score (1-5) | Weighted |",
    "|---|---:|---:|---:|",
    "| Alpha | 0.60 |  |  |",
    "| Beta | 0.40 |  |  |",
    "| **Total** | **1.00** |  |  |",
    "",
)
_MINI_SPEC = LINE_SEPARATOR.join(_MINI_SPEC_LINES)
_MINI_ROWS = [("Alpha", Decimal("0.60")), ("Beta", Decimal("0.40"))]


def _mini_spec(*replace: tuple[str, str]) -> str:
    text = _MINI_SPEC
    for old, new in replace:
        assert old in text, f"vector setup: {old!r} not in the mini spec"
        text = text.replace(old, new)
    return text


def _mini_lib_eval(spec_rows: Sequence[str], computed_rows: Sequence[str], extra: Sequence[str] = ()) -> str:
    return LINE_SEPARATOR.join(
        [
            "# LIB-EVAL",
            LIB_EVAL_SPEC_HEADING,
            "### E1: spec",
            "| Category | Weight | Target |",
            "|---|---|---|",
            *spec_rows,
            LIB_EVAL_COMPUTED_HEADING,
            *extra,
            SIGNAL_FENCE_OPEN,
            "# a comment line is code, not a heading",
            "base = clamp(10 - avg_risk_score)",
            FENCE,
            "| Field | Formula |",
            "|---|---|",
            *computed_rows,
            "## evaluation-scripts",
            "| Field | Formula |",
            "|---|---|",
            "| `ignored` | `1` |",
        ]
    )


_GOOD_LIB = _mini_lib_eval(["| Alpha | 60% | x |", "| Beta | 40% | x |"], ["| `productIntegrity` | `base` |"])
_ONE_ROW = ["| `a` | `1` |"]
_SIGNAL_NAMES: dict[str, float] = {"base": 6.0, "confidence_score": 8.0, "review_score": 5.0}


def _ident(value: float) -> float:
    return value


def _clamp10(value: float) -> float:
    return max(0.0, min(10.0, value))


def _label_in(extra: Sequence[str], spec_rows: Sequence[str] = ()) -> None:
    text = _mini_lib_eval(spec_rows, _ONE_ROW, extra=extra)
    _require_label(_section(text, LIB_EVAL_COMPUTED_HEADING, "v"), LIB_EVAL_PROXY_LABEL, "v")


def _empty_in(extra: Sequence[str], spec_rows: Sequence[str] = ()) -> object:
    return _lib_eval_empty_response(_mini_lib_eval(spec_rows, _ONE_ROW, extra=extra))


_EMPTY_NULL = f"{LIB_EVAL_EMPTY_KEY} `null`"

# Blocker vectors resolve against this mini Scoring Sheet. "Alpha" is an
# ambiguous prefix; "Beta" a unique whole-word prefix of "Beta Gamma".
_BLOCKER_SHEET: tuple[str, ...] = ("Alpha One", "Alpha Two", "Beta Gamma", "Delta")
_BLOCKER_EXPECTED = Blocker("criterion", 2, frozenset({"Alpha One", "Beta Gamma", "Delta"}))
_SPEC_BLOCKER_LINE = (
    f"**Pass threshold:** ≥4.2 average. {SPEC_BLOCKER_LABEL} any criterion ≤2 in Alpha One, Beta, or Delta."
)


def _spec_blk(*lines: str) -> Blocker:
    return _spec_blocker(LINE_SEPARATOR.join((_MINI_SPEC, *lines)), _BLOCKER_SHEET)


def _line_blk(line: str) -> Blocker:
    return _blocker_in(line, _BLOCKER_SHEET, "v")


def _lib_blk(*lines: str) -> list[Blocker]:
    return _lib_eval_blockers(LINE_SEPARATOR.join(("# LIB-EVAL", LIB_EVAL_SPEC_HEADING, *lines)), _BLOCKER_SHEET)


@dataclass(frozen=True)
class Vector:
    parser: str
    case: str
    run: Callable[[], object]
    expect: object  # REJECT, or the exact expected return value


VECTORS: tuple[Vector, ...] = (
    # _parse_weight
    Vector("weight", "decimal", lambda: _parse_weight("0.20", "v"), Decimal("0.20")),
    Vector("weight", "percent", lambda: _parse_weight("20%", "v"), Decimal("0.20")),
    Vector("weight", "percent-100", lambda: _parse_weight("100%", "v"), Decimal(1)),
    Vector("weight", "decimal-one", lambda: _parse_weight("1.00", "v"), Decimal(1)),
    Vector("weight", "bare-integer", lambda: _parse_weight("20", "v"), REJECT),
    Vector("weight", "space-before-percent", lambda: _parse_weight("20 %", "v"), REJECT),
    Vector("weight", "fullwidth-digits", lambda: _parse_weight("２０%", "v"), REJECT),
    Vector("weight", "arabic-indic-digits", lambda: _parse_weight("0.٢٠", "v"), REJECT),
    Vector("weight", "letter-O-for-zero", lambda: _parse_weight("0.2O", "v"), REJECT),
    Vector("weight", "negative", lambda: _parse_weight("-0.20", "v"), REJECT),
    Vector("weight", "zero-decimal", lambda: _parse_weight("0.00", "v"), REJECT),
    Vector("weight", "zero-percent", lambda: _parse_weight("0%", "v"), REJECT),
    Vector("weight", "above-one", lambda: _parse_weight("1.50", "v"), REJECT),
    Vector("weight", "above-100-percent", lambda: _parse_weight("101%", "v"), REJECT),
    Vector("weight", "exponent", lambda: _parse_weight("1e-1", "v"), REJECT),
    Vector("weight", "nan", lambda: _parse_weight("NaN", "v"), REJECT),
    Vector("weight", "infinity", lambda: _parse_weight("Infinity", "v"), REJECT),
    Vector("weight", "hex", lambda: _parse_weight("0x14", "v"), REJECT),
    Vector("weight", "empty", lambda: _parse_weight("", "v"), REJECT),
    Vector("weight", "huge", lambda: _parse_weight("0." + "1" * 2_000_000, "v"), REJECT),
    # _field_for: the documented mapping, exact lookup only
    Vector("mapping", "exact", lambda: _field_for("AI Law Signal Quality"), "aiLawSignalQuality"),
    Vector("mapping", "ampersand-name", lambda: _field_for("Privacy & Security"), "privacySecurity"),
    Vector("mapping", "lower-case", lambda: _field_for("ai law signal quality"), REJECT),
    Vector("mapping", "camel-case-field", lambda: _field_for("aiLawSignalQuality"), REJECT),
    Vector("mapping", "greek-alpha", lambda: _field_for("ΑI Law Signal Quality"), REJECT),
    Vector("mapping", "cyrillic-o", lambda: _field_for("Prоduct Integrity"), REJECT),
    Vector("mapping", "fullwidth-A", lambda: _field_for("ＡI Law Signal Quality"), REJECT),
    Vector("mapping", "nbsp", lambda: _field_for("Product Integrity"), REJECT),
    Vector("mapping", "and-for-ampersand", lambda: _field_for("Privacy and Security"), REJECT),
    Vector("mapping", "trailing-space", lambda: _field_for("Product Integrity "), REJECT),
    Vector("mapping", "huge", lambda: _field_for("A" * 2_000_000), REJECT),
    # _spec_sheet_rows: section + table + category rows + total
    Vector("sheet", "minimal", lambda: _spec_sheet_rows(_MINI_SPEC), _MINI_ROWS),
    Vector("sheet", "no-heading", lambda: _spec_sheet_rows(_mini_spec((SPEC_SHEET_HEADING, "### Sheet"))), REJECT),
    Vector(
        "sheet",
        "heading-trailing-space",
        lambda: _spec_sheet_rows(_mini_spec((SPEC_SHEET_HEADING, SPEC_SHEET_HEADING + " "))),
        REJECT,
    ),
    Vector("sheet", "duplicate-heading", lambda: _spec_sheet_rows(_MINI_SPEC + LINE_SEPARATOR + _MINI_SPEC), REJECT),
    Vector(
        "sheet",
        "heading-only-in-fence",
        lambda: _spec_sheet_rows(f"{FENCE}{LINE_SEPARATOR}{_MINI_SPEC}{LINE_SEPARATOR}{FENCE}"),
        REJECT,
    ),
    Vector("sheet", "no-table", lambda: _spec_sheet_rows(f"{SPEC_SHEET_HEADING}{LINE_SEPARATOR}prose"), REJECT),
    Vector("sheet", "header-only", lambda: _spec_sheet_rows(LINE_SEPARATOR.join(_MINI_SPEC_LINES[:5])), REJECT),
    Vector(
        "sheet",
        # The first table is complete and valid on its own; only "exactly one
        # table" rejects this, so a parser that takes the first table fails.
        "second-table-after-total",
        lambda: _spec_sheet_rows(
            _mini_spec(("| **Total** | **1.00** |  |  |", "| **Total** | **1.00** |  |  |\n\n| A | B |\n|---|---|\n| x | y |"))
        ),
        REJECT,
    ),
    Vector(
        "sheet",
        "ragged-row",
        lambda: _spec_sheet_rows(_mini_spec(("| Beta | 0.40 |  |  |", "| Beta | 0.40 |  |"))),
        REJECT,
    ),
    Vector(
        "sheet",
        "bad-separator",
        lambda: _spec_sheet_rows(_mini_spec(("|---|---:|---:|---:|", "|--|---:|---:|---:|"))),
        REJECT,
    ),
    Vector("sheet", "escaped-pipe", lambda: _spec_sheet_rows(_mini_spec(("| Beta |", "| Be\\|ta |"))), REJECT),
    Vector("sheet", "duplicate-category", lambda: _spec_sheet_rows(_mini_spec(("| Beta |", "| Alpha |"))), REJECT),
    Vector("sheet", "empty-category", lambda: _spec_sheet_rows(_mini_spec(("| Beta |", "|  |"))), REJECT),
    Vector(
        "sheet",
        "total-missing",
        lambda: _spec_sheet_rows(_mini_spec(("| **Total** | **1.00** |  |  |\n", ""))),
        REJECT,
    ),
    Vector("sheet", "total-wrong", lambda: _spec_sheet_rows(_mini_spec(("**1.00**", "**0.90**"))), REJECT),
    Vector("sheet", "total-not-bold", lambda: _spec_sheet_rows(_mini_spec(("**1.00**", "1.00"))), REJECT),
    Vector(
        "sheet",
        "total-not-last",
        lambda: _spec_sheet_rows(
            _mini_spec(("| **Total** | **1.00** |  |  |", "| **Total** | **1.00** |  |  |\n| Gamma | 0.10 |  |  |"))
        ),
        REJECT,
    ),
    Vector(
        "sheet",
        "no-category-rows",
        lambda: _spec_sheet_rows(_mini_spec(("| Alpha | 0.60 |  |  |\n| Beta | 0.40 |  |  |\n", ""))),
        REJECT,
    ),
    Vector(
        "sheet",
        "u2028-forged-row",
        lambda: _spec_sheet_rows(
            _mini_spec(("| Beta | 0.40 |  |  |", "| Beta | 0.40 |  |  | | Gamma | 0.10 |  |  |"))
        ),
        REJECT,
    ),
    Vector("sheet", "crlf", lambda: _spec_sheet_rows(_MINI_SPEC.replace(LINE_SEPARATOR, "\r\n")), REJECT),
    Vector("sheet", "nul", lambda: _spec_sheet_rows(_mini_spec(("Alpha", "Al\x00pha"))), REJECT),
    Vector("sheet", "lone-surrogate", lambda: _spec_sheet_rows(_mini_spec(("Alpha", "Al\ud800pha"))), REJECT),
    Vector("sheet", "bidi-override", lambda: _spec_sheet_rows(_mini_spec(("Alpha", "‮Alpha"))), REJECT),
    Vector("sheet", "unclosed-fence", lambda: _spec_sheet_rows(_MINI_SPEC + FENCE), REJECT),
    # _spec_heading_rows
    Vector(
        "headings",
        "two-in-order",
        lambda: _spec_heading_rows("## 1. Alpha (Weight 60%)\ntext\n## 2. Beta (Weight 40%)\n---\n### Scoring Sheet"),
        _MINI_ROWS,
    ),
    Vector("headings", "none", lambda: _spec_heading_rows("## Intro\ntext"), REJECT),
    Vector(
        "headings",
        "out-of-sequence",
        lambda: _spec_heading_rows("## 1. Alpha (Weight 60%)\n## 3. Beta (Weight 40%)"),
        REJECT,
    ),
    Vector("headings", "malformed-weight", lambda: _spec_heading_rows("## 1. Alpha (Weight sixty)"), REJECT),
    Vector("headings", "missing-weight", lambda: _spec_heading_rows("## 1. Alpha"), REJECT),
    Vector(
        "headings",
        "u2029-forged",
        lambda: _spec_heading_rows("## 1. Alpha (Weight 60%) ## 2. Beta (Weight 40%)"),
        REJECT,
    ),
    # _lib_eval_spec_rows: optional total, percent weights
    Vector("lib-spec", "minimal", lambda: _lib_eval_spec_rows(_GOOD_LIB), _MINI_ROWS),
    Vector(
        "lib-spec",
        "with-total",
        lambda: _lib_eval_spec_rows(
            _mini_lib_eval(["| Alpha | 60% | x |", "| Beta | 40% | x |", "| **Total** | **100%** | |"], _ONE_ROW)
        ),
        _MINI_ROWS,
    ),
    Vector("lib-spec", "no-rows", lambda: _lib_eval_spec_rows(_mini_lib_eval([], _ONE_ROW)), REJECT),
    Vector(
        "lib-spec",
        "missing-section",
        lambda: _lib_eval_spec_rows(_GOOD_LIB.replace(LIB_EVAL_SPEC_HEADING, "## spec")),
        REJECT,
    ),
    # _lib_eval_computed_formulas / _field_cell
    Vector("computed", "minimal", lambda: _lib_eval_computed_formulas(_GOOD_LIB), {"productIntegrity": "base"}),
    Vector(
        "computed",
        "first-code-span-wins",
        lambda: _lib_eval_computed_formulas(_mini_lib_eval([], ["| `overall` | `a + b` - prose `c` |"])),
        {"overall": "a + b"},
    ),
    Vector(
        "computed",
        "no-backticks",
        lambda: _lib_eval_computed_formulas(_mini_lib_eval([], ["| productIntegrity | `base` |"])),
        REJECT,
    ),
    Vector(
        "computed",
        "two-identifiers",
        lambda: _lib_eval_computed_formulas(_mini_lib_eval([], ["| `a` `b` | `base` |"])),
        REJECT,
    ),
    Vector(
        "computed",
        "cyrillic-identifier",
        lambda: _lib_eval_computed_formulas(_mini_lib_eval([], ["| `prоduct` | `base` |"])),
        REJECT,
    ),
    Vector("computed", "no-formula-span", lambda: _lib_eval_computed_formulas(_mini_lib_eval([], ["| `a` | base |"])), REJECT),
    Vector(
        "computed",
        "duplicate-field",
        lambda: _lib_eval_computed_formulas(_mini_lib_eval([], ["| `a` | `1` |", "| `a` | `2` |"])),
        REJECT,
    ),
    Vector("computed", "no-rows", lambda: _lib_eval_computed_formulas(_mini_lib_eval([], [])), REJECT),
    # _lib_eval_signal_block
    Vector(
        "signal-block",
        "one-block",
        lambda: _lib_eval_signal_block(_GOOD_LIB),
        "# a comment line is code, not a heading\nbase = clamp(10 - avg_risk_score)",
    ),
    Vector(
        "signal-block",
        "two-blocks",
        lambda: _lib_eval_signal_block(_mini_lib_eval([], _ONE_ROW, extra=[SIGNAL_FENCE_OPEN, "x = 1", FENCE])),
        REJECT,
    ),
    Vector("signal-block", "none", lambda: _lib_eval_signal_block(_GOOD_LIB.replace(SIGNAL_FENCE_OPEN, "```text")), REJECT),
    # _require_label
    Vector("label", "present-once", lambda: _label_in([LIB_EVAL_PROXY_LABEL]), None),
    Vector("label", "absent", lambda: _label_in([]), REJECT),
    Vector("label", "twice", lambda: _label_in([LIB_EVAL_PROXY_LABEL, LIB_EVAL_PROXY_LABEL]), REJECT),
    Vector("label", "only-inside-code", lambda: _label_in([FENCE, LIB_EVAL_PROXY_LABEL, FENCE]), REJECT),
    Vector("label", "other-section", lambda: _label_in([], spec_rows=[LIB_EVAL_PROXY_LABEL]), REJECT),
    Vector("label", "case-variant", lambda: _label_in(["label: Heuristic-Proxy"]), REJECT),
    Vector("label", "trailing-text", lambda: _label_in([LIB_EVAL_PROXY_LABEL + " (not really)"]), REJECT),
    Vector("label", "zero-width-space", lambda: _label_in(["label: heuristic​-proxy"]), REJECT),
    # _compute: allowlisted tree walker
    Vector(
        "formula",
        "linear",
        lambda: _compute("0.6 * review_score + 0.4 * confidence_score", _SIGNAL_NAMES, _ident),
        0.6 * 5.0 + 0.4 * 8.0,
    ),
    Vector("formula", "parens-unary", lambda: _compute("-(base - 10)", _SIGNAL_NAMES, _ident), 4.0),
    Vector("formula", "clamp", lambda: _compute("clamp(base * 3)", _SIGNAL_NAMES, _clamp10), 10.0),
    Vector("formula", "unknown-name", lambda: _compute("bogus + 1", _SIGNAL_NAMES, _ident), REJECT),
    Vector("formula", "dunder-import", lambda: _compute("__import__('os')", _SIGNAL_NAMES, _ident), REJECT),
    Vector("formula", "attribute", lambda: _compute("base.real", _SIGNAL_NAMES, _ident), REJECT),
    Vector("formula", "power-bomb", lambda: _compute("2 ** 10 ** 10", _SIGNAL_NAMES, _ident), REJECT),
    Vector("formula", "lambda", lambda: _compute("(lambda: 1)()", _SIGNAL_NAMES, _ident), REJECT),
    Vector("formula", "conditional", lambda: _compute("base if 1 else 2", _SIGNAL_NAMES, _ident), REJECT),
    Vector("formula", "string", lambda: _compute("'1'", _SIGNAL_NAMES, _ident), REJECT),
    Vector("formula", "bool", lambda: _compute("True", _SIGNAL_NAMES, _ident), REJECT),
    Vector("formula", "complex", lambda: _compute("1j", _SIGNAL_NAMES, _ident), REJECT),
    Vector("formula", "other-call", lambda: _compute("max(base, 1)", _SIGNAL_NAMES, _ident), REJECT),
    Vector("formula", "clamp-two-args", lambda: _compute("clamp(base, 1)", _SIGNAL_NAMES, _ident), REJECT),
    Vector("formula", "clamp-keyword", lambda: _compute("clamp(x=base)", _SIGNAL_NAMES, _ident), REJECT),
    Vector("formula", "bare-clamp-name", lambda: _compute("clamp", _SIGNAL_NAMES, _ident), REJECT),
    Vector("formula", "divide-by-zero", lambda: _compute("base / 0", _SIGNAL_NAMES, _ident), REJECT),
    Vector("formula", "syntax-error", lambda: _compute("base +", _SIGNAL_NAMES, _ident), REJECT),
    Vector("formula", "statement", lambda: _compute("base; import os", _SIGNAL_NAMES, _ident), REJECT),
    Vector("formula", "empty", lambda: _compute("", _SIGNAL_NAMES, _ident), REJECT),
    Vector("formula", "deep-chain", lambda: _compute("1+" * 200_000 + "1", _SIGNAL_NAMES, _ident), REJECT),
    Vector("formula", "deep-parens", lambda: _compute("(" * 5_000 + "1" + ")" * 5_000, _SIGNAL_NAMES, _ident), REJECT),
    # _run_signal_block
    Vector(
        "signal-run",
        "assignments-in-order",
        lambda: _run_signal_block("a = clamp(10 - x)  # note\nb = a * 2", {"x": 4.0}, _clamp10),
        {"x": 4.0, "a": 6.0, "b": 12.0},
    ),
    Vector("signal-run", "empty", lambda: _run_signal_block("# only a comment", {"x": 1.0}, _ident), REJECT),
    Vector("signal-run", "import", lambda: _run_signal_block("import os", {"x": 1.0}, _ident), REJECT),
    Vector("signal-run", "rebind-input", lambda: _run_signal_block("x = 2", {"x": 1.0}, _ident), REJECT),
    Vector("signal-run", "rebind-signal", lambda: _run_signal_block("a = 1\na = 2", {"x": 1.0}, _ident), REJECT),
    Vector("signal-run", "bind-clamp", lambda: _run_signal_block("clamp = 1", {"x": 1.0}, _ident), REJECT),
    Vector("signal-run", "tuple-target", lambda: _run_signal_block("a, b = 1, 2", {"x": 1.0}, _ident), REJECT),
    Vector("signal-run", "aug-assign", lambda: _run_signal_block("x += 1", {"x": 1.0}, _ident), REJECT),
    Vector("signal-run", "def", lambda: _run_signal_block("def f():\n    pass", {"x": 1.0}, _ident), REJECT),
    Vector("signal-run", "unknown-name", lambda: _run_signal_block("a = y", {"x": 1.0}, _ident), REJECT),
    Vector("signal-run", "deep", lambda: _run_signal_block("a = " + "1+" * 200_000 + "1", {"x": 1.0}, _ident), REJECT),
    # _lib_eval_empty_response (PR #335 r1 finding 1)
    Vector("empty-response", "null", lambda: _empty_in([_EMPTY_NULL]), None),
    Vector(
        "empty-response",
        "null-then-prose",
        lambda: _empty_in([f"{_EMPTY_NULL} (HTTP 200) when there are no analysis records"]),
        None,
    ),
    Vector("empty-response", "object", lambda: _empty_in([f"{LIB_EVAL_EMPTY_KEY} `{{}}`"]), {}),
    Vector("empty-response", "absent", lambda: _empty_in([]), REJECT),
    Vector("empty-response", "twice", lambda: _empty_in([_EMPTY_NULL, _EMPTY_NULL]), REJECT),
    Vector("empty-response", "only-inside-code", lambda: _empty_in([FENCE, _EMPTY_NULL, FENCE]), REJECT),
    Vector("empty-response", "other-section", lambda: _empty_in([], spec_rows=[_EMPTY_NULL]), REJECT),
    Vector("empty-response", "key-case-variant", lambda: _empty_in(["Empty-response: `null`"]), REJECT),
    Vector("empty-response", "no-code-span", lambda: _empty_in([f"{LIB_EVAL_EMPTY_KEY} null"]), REJECT),
    Vector("empty-response", "prose-glued-to-span", lambda: _empty_in([f"{_EMPTY_NULL}x"]), REJECT),
    Vector("empty-response", "python-none", lambda: _empty_in([f"{LIB_EVAL_EMPTY_KEY} `None`"]), REJECT),
    Vector("empty-response", "lookalike-null", lambda: _empty_in([f"{LIB_EVAL_EMPTY_KEY} `nuII`"]), REJECT),
    Vector("empty-response", "nan-constant", lambda: _empty_in([f"{LIB_EVAL_EMPTY_KEY} `NaN`"]), REJECT),
    Vector("empty-response", "two-values", lambda: _empty_in([f"{LIB_EVAL_EMPTY_KEY} `null null`"]), REJECT),
    Vector(
        "empty-response",
        "u2028-forged",
        lambda: _empty_in([f"see below {_EMPTY_NULL}"]),
        REJECT,
    ),
    Vector(
        "empty-response",
        "deep-nesting",
        lambda: _empty_in([f"{LIB_EVAL_EMPTY_KEY} `{'[' * 200_000}{']' * 200_000}`"]),
        REJECT,
    ),
    Vector("empty-response", "huge-int", lambda: _empty_in([f"{LIB_EVAL_EMPTY_KEY} `{'1' * 2_000_000}`"]), REJECT),
    # _spec_blocker (PR #335 r1 finding 2): the spec's labelled clause
    Vector("blocker-spec", "spec-form", lambda: _spec_blk(_SPEC_BLOCKER_LINE), _BLOCKER_EXPECTED),
    Vector(
        "blocker-spec",
        "ascii-le-no-oxford-comma",
        lambda: _spec_blk(f"{SPEC_BLOCKER_LABEL} any criterion <= 2 in Alpha One, Beta or Delta"),
        _BLOCKER_EXPECTED,
    ),
    Vector("blocker-spec", "label-missing", lambda: _spec_blk("any criterion ≤2 in Delta."), REJECT),
    Vector("blocker-spec", "label-twice", lambda: _spec_blk(_SPEC_BLOCKER_LINE, _SPEC_BLOCKER_LINE), REJECT),
    Vector(
        "blocker-spec",
        "label-twice-in-line",
        lambda: _spec_blk(f"{_SPEC_BLOCKER_LINE} {SPEC_BLOCKER_LABEL}"),
        REJECT,
    ),
    Vector("blocker-spec", "label-only-inside-code", lambda: _spec_blk(FENCE, _SPEC_BLOCKER_LINE, FENCE), REJECT),
    Vector("blocker-spec", "text-after-clause", lambda: _spec_blk(f"{_SPEC_BLOCKER_LINE} Also more."), REJECT),
    Vector(
        "blocker-spec",
        "u2028-forged",
        lambda: _spec_blk(f"{SPEC_BLOCKER_LABEL} any criterion ≤2 in Delta."),
        REJECT,
    ),
    # _blocker_in: the one grammar both docs are parsed with
    Vector(
        "blocker-line",
        "unit-is-captured-not-assumed",
        lambda: _line_blk("critical blocker if any category <= 2 in Alpha One"),
        Blocker("category", 2, frozenset({"Alpha One"})),
    ),
    Vector(
        "blocker-line",
        "whole-word-prefix",
        lambda: _line_blk("any criterion <= 3 in Beta"),
        Blocker("criterion", 3, frozenset({"Beta Gamma"})),
    ),
    Vector(
        "blocker-line",
        "category-level-phrasing",
        lambda: _line_blk("critical blocker if any of Alpha One, Beta or Delta scores <= 2"),
        REJECT,
    ),
    Vector("blocker-line", "ambiguous-prefix", lambda: _line_blk("any criterion <= 2 in Alpha"), REJECT),
    Vector("blocker-line", "part-word-prefix", lambda: _line_blk("any criterion <= 2 in Bet"), REJECT),
    Vector("blocker-line", "unknown-name", lambda: _line_blk("any criterion <= 2 in Epsilon"), REJECT),
    Vector("blocker-line", "cyrillic-e", lambda: _line_blk("any criterion <= 2 in B\u0435ta"), REJECT),
    Vector("blocker-line", "nbsp-in-name", lambda: _line_blk("any criterion <= 2 in Alpha\u00a0One"), REJECT),
    Vector("blocker-line", "fullwidth-threshold", lambda: _line_blk("any criterion <= ２ in Delta"), REJECT),
    Vector("blocker-line", "lookalike-le", lambda: _line_blk("any criterion ≦2 in Delta"), REJECT),
    Vector("blocker-line", "two-clauses", lambda: _line_blk("any criterion <= 2 in Delta; any category <= 1 in Beta"), REJECT),
    Vector("blocker-line", "duplicate-category", lambda: _line_blk("any criterion <= 2 in Beta, Beta Gamma"), REJECT),
    Vector("blocker-line", "empty-item", lambda: _line_blk("any criterion <= 2 in Beta, , Delta"), REJECT),
    Vector("blocker-line", "and-conjunction", lambda: _line_blk("any criterion <= 2 in Beta and Delta"), REJECT),
    Vector("blocker-line", "threshold-int-bomb", lambda: _line_blk(f"any criterion <= {'9' * 2_000_000} in Delta"), REJECT),
    Vector("blocker-line", "huge-name", lambda: _line_blk(f"any criterion <= 2 in {'A' * 2_000_000}"), REJECT),
    # _lib_eval_blockers: every mention outside code must parse; none is a failure
    Vector(
        "blocker-lib",
        "every-mention-parsed",
        lambda: _lib_blk("rule: blocker if any criterion <= 2 in Delta", "Critical Blocker: any category <= 1 in Beta"),
        [Blocker("criterion", 2, frozenset({"Delta"})), Blocker("category", 1, frozenset({"Beta Gamma"}))],
    ),
    Vector("blocker-lib", "none", lambda: _lib_blk("rule: any criterion <= 2 in Delta"), REJECT),
    Vector("blocker-lib", "only-inside-code", lambda: _lib_blk(FENCE, "blocker: any criterion <= 2 in Delta", FENCE), REJECT),
    Vector(
        "blocker-lib",
        "second-prose-mention",
        lambda: _lib_blk("blocker: any criterion <= 2 in Delta", "Blockers are described above."),
        REJECT,
    ),
)

PARSERS = frozenset(
    {
        "weight",
        "mapping",
        "sheet",
        "headings",
        "lib-spec",
        "computed",
        "signal-block",
        "label",
        "formula",
        "signal-run",
        "empty-response",
        "blocker-spec",
        "blocker-line",
        "blocker-lib",
    }
)


@pytest.mark.parametrize("vector", VECTORS, ids=[f"{v.parser}:{v.case}" for v in VECTORS])
def test_rubric_doc_parser_vectors(vector: Vector) -> None:
    if vector.expect is REJECT:
        with pytest.raises(RubricDocError):
            vector.run()
    else:
        assert vector.run() == vector.expect


def test_rubric_doc_parser_vectors_contract() -> None:
    """Every parser has at least one accept and one reject vector; no stray parser names."""
    assert {v.parser for v in VECTORS} == PARSERS
    for parser in sorted(PARSERS):
        rows = [v for v in VECTORS if v.parser == parser]
        assert any(v.expect is REJECT for v in rows), f"{parser}: no reject vector"
        assert any(v.expect is not REJECT for v in rows), f"{parser}: no accept vector"
    ids = [(v.parser, v.case) for v in VECTORS]
    assert len(ids) == len(set(ids)), "duplicate vector ids"


def test_rubric_doc_parser_handles_many_rows_and_huge_cells() -> None:
    """Many rows are all returned (no truncation hides an extra row); a 2 MB cell is not cut."""
    many = 30_000
    huge = "A" * 2_000_000
    lines = [SPEC_SHEET_HEADING, "| Category | Weight |", "|---|---|"]
    lines += [f"| C{i} | 0.0001 |" for i in range(many)]
    lines.append(f"| {huge} | 0.0001 |")
    rows = _only_table(_section(LINE_SEPARATOR.join(lines), SPEC_SHEET_HEADING, "v"), "v", "v")
    assert len(rows) == many + 1
    assert rows[-1][CATEGORY_COLUMN] == huge


def _forbidden_code_points() -> list[str]:
    """Every Cc, Cf, Cs, Zl, Zp code point, plus Co and Cn samples (both ranges are huge)."""
    full = {"Cc", "Cf", "Cs", "Zl", "Zp"}
    points = [
        chr(cp)
        for cp in range(sys.maxunicode + 1)
        if unicodedata.category(chr(cp)) in full and chr(cp) != LINE_SEPARATOR
    ]
    samples = ["", "", "\U000f0000", "\U0010fffd", "͸", "￿", "\U0010ffff"]
    assert {unicodedata.category(s) for s in samples} == {"Co", "Cn"}
    assert {unicodedata.category(p) for p in points} | {"Co", "Cn"} == FORBIDDEN_CATEGORIES
    return points + samples


def test_rubric_doc_parsers_reject_generated_hostile_characters() -> None:
    """Generated, not listed (R2): each forbidden code point in a name, a weight and after a row."""
    targets = (
        ("| Alpha | 0.60 |", "| Al{c}pha | 0.60 |"),
        ("| Beta | 0.40 |", "| Beta | 0.4{c}0 |"),
        ("| Beta | 0.40 |  |  |", "| Beta | 0.40 |  |  |{c}"),
    )
    accepted: list[str] = []
    generated = 0
    for char in _forbidden_code_points():
        for old, template in targets:
            generated += 1
            try:
                _spec_sheet_rows(_mini_spec((old, template.format(c=char))))
            except RubricDocError:
                continue
            accepted.append(f"U+{ord(char):04X} in {template!r}")
    print(f"generated hostile cases: {generated}")
    assert generated >= 3 * 2000, f"only {generated} hostile cases generated"
    assert not accepted, f"forbidden characters accepted: {accepted[:10]}"


def test_rubric_doc_errors_are_ascii_and_path_free(tmp_path: Path) -> None:
    """Messages show untrusted text escaped and truncated, and never an absolute path (F2, F8)."""
    hostile = "\x1b[31m‮EVIL" + "X" * 500
    runs: tuple[Callable[[], object], ...] = (
        lambda: _field_for(hostile),
        lambda: _parse_weight(hostile, "v"),
        lambda: _compute(hostile, _SIGNAL_NAMES, _ident),
        lambda: _read_doc("missing.md", tmp_path),
        lambda: _line_blk(hostile),
        lambda: _line_blk(f"any criterion <= 2 in {hostile}"),
        # Doc-level parsers reject control and bidi characters before echoing,
        # so feed them printable oversized text to exercise truncation.
        lambda: _spec_blk(f"{SPEC_BLOCKER_LABEL} any criterion <= 2 in Delta. {'EVIL' + 'X' * 500}"),
        lambda: _empty_in([f"{LIB_EVAL_EMPTY_KEY} `{'EVIL' + 'X' * 500}`"]),
    )
    for run in runs:
        with pytest.raises(RubricDocError) as caught:
            run()
        message = str(caught.value)
        assert message.isascii() and message.isprintable(), f"raw bytes in message: {message[:80]!r}"
        assert "\x1b" not in message and "EVIL" + "X" * 100 not in message
        assert str(tmp_path) not in message and str(REPO_ROOT) not in message


def test_read_doc_refuses_symlinks_escapes_bad_utf8_and_missing_files(tmp_path: Path) -> None:
    good = tmp_path / "docs" / "good.md"
    good.parent.mkdir()
    good.write_text(_MINI_SPEC, encoding="utf-8")
    assert _read_doc("docs/good.md", tmp_path) == _MINI_SPEC

    (tmp_path / "docs" / "link.md").symlink_to(good)
    (tmp_path / "linked-dir").symlink_to(good.parent, target_is_directory=True)
    (tmp_path / "docs" / "bad.md").write_bytes(b"### Scoring Sheet\n\xff\xfe\xc0\x80")
    for rel in ("docs/link.md", "linked-dir/good.md", "docs/bad.md", "docs/absent.md", "../good.md", str(good)):
        with pytest.raises(RubricDocError):
            _read_doc(rel, tmp_path)
