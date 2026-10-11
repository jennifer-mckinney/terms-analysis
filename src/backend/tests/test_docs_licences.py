"""Corpus licences in the governance docs match upstream (#159, HR1).

HR1 (open-source-only, commercial use) is decided from the licence the docs
record for each corpus. Two docs got it wrong:

- ``.claude/library/LIB-LEGAL.md`` (``## legal-corpora`` table) records
  MultiEURLEX as ``CC-BY-4.0`` and LegalBench as the placeholder ``Open``.
- ``docs/plans/2026-07-04-corpus-AGG.md`` records MultiEURLEX as ``CC-BY-4.0``
  and LegalBench as a flat ``CC-BY-4.0`` "for the aggregate", and recommends
  the OPP-115 tasks as an asset without saying they are non-commercial.

Authoritative sources (fetched 2026-10-10; revisions pinned below):

- MultiEURLEX: https://huggingface.co/datasets/coastalcph/multi_eurlex
  dataset-card metadata ``license: cc-by-sa-4.0`` (HF API tag
  ``license:cc-by-sa-4.0``), revision ``2020d0350241461069a54177b639f0e6c7a7a712``.
  The card's prose section says the data keeps the EU's CC-BY-4.0; the
  machine-readable licence tag, which is the stricter one, is what card #159
  adopts.
- LegalBench: licensing is per task. Each task's README in
  https://github.com/HazyResearch/legalbench (``tasks/<task>/README.md``,
  commit ``b46bf4ffae90524b2b72aaa30e7745fe9db64481``) states its licence.
  The HF card https://huggingface.co/datasets/nguha/legalbench (revision
  ``daec8237410aa23e3faf4bc41ad8b3a7e1696826``) carries an aggregate
  ``cc-by-4.0`` tag that does NOT hold for every task. Of the 12 ToS/privacy
  tasks only ``unfair_tos`` (CC BY 4.0) and ``privacy_policy_qa`` (MIT) allow
  commercial use; the 9 ``opp115_*`` tasks ("Creative Commons
  Attribution-NonCommercial License", no version stated) and
  ``privacy_policy_entailment`` (CC BY-NC 3.0) do not.
- EUR-Lex (positive control): https://commission.europa.eu/legal-notice_en
  (CC BY 4.0 under Decision 2011/833/EU).

The expected licences below are this card's acceptance values, taken from
those sources. They are deliberately NOT read back from the docs under test
(a test that reads its answer from the file it checks cannot fail). This
module is the one table both docs are checked against (F10).

Docs are prose, so these are static checks by necessity. Every checker is
pinned by a vectors table (positive and negative rows, hostile Unicode
generated per category) so a weakened checker goes red here, not silently
green.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

# The two artifacts card #159 names. Repo-relative so failure messages carry
# no absolute paths (F8).
LIB_LEGAL = ".claude/library/LIB-LEGAL.md"
CORPUS_AGG = "docs/plans/2026-07-04-corpus-AGG.md"

LIB_LEGAL_SECTION = "## legal-corpora"
CORPUS_AGG_MULTIEURLEX_HEADING = "### HuggingFace: MultiEURLEX"
CORPUS_AGG_LEGALBENCH_HEADING = "### HuggingFace: LegalBench"

# --------------------------------------------------------------------------
# Acceptance values (card #159). One row per fact, each with its source.
# --------------------------------------------------------------------------

MULTIEURLEX_SPDX = "CC-BY-SA-4.0"
EURLEX_SPDX = "CC-BY-4.0"
# SPDX family prefix for the non-commercial CC licences. OPP-115 upstream
# states no version, so blocked tasks are matched on the family.
NON_COMMERCIAL_FAMILY = "CC-BY-NC"


@dataclass(frozen=True)
class TaskLicence:
    """Upstream licence of one LegalBench ToS/privacy task."""

    task: str
    mention: str  # key into MENTION_PATTERNS that names this task in prose
    spdx: str  # exact SPDX id, or the NC family prefix when upstream is unversioned
    commercial: bool


_OPP115_TASKS = (
    "opp115_data_retention",
    "opp115_data_security",
    "opp115_do_not_track",
    "opp115_first_party_collection_use",
    "opp115_international_and_specific_audiences",
    "opp115_policy_change",
    "opp115_third_party_sharing_collection",
    "opp115_user_access,_edit_and_deletion",
    "opp115_user_choice_control",
)

LEGALBENCH_TOS_PRIVACY_TASKS: tuple[TaskLicence, ...] = (
    TaskLicence("unfair_tos", "unfair_tos", "CC-BY-4.0", True),
    TaskLicence("privacy_policy_qa", "privacy_policy_qa", "MIT", True),
    TaskLicence(
        "privacy_policy_entailment", "privacy_policy_entailment", "CC-BY-NC-3.0", False
    ),
    *(TaskLicence(t, "opp115", NON_COMMERCIAL_FAMILY, False) for t in _OPP115_TASKS),
)
USABLE_TASKS = tuple(t for t in LEGALBENCH_TOS_PRIVACY_TASKS if t.commercial)
BLOCKED_MENTIONS = tuple(
    sorted({t.mention for t in LEGALBENCH_TOS_PRIVACY_TASKS if not t.commercial})
)

# --------------------------------------------------------------------------
# Checkers (each pinned by a vectors table further down).
# --------------------------------------------------------------------------

# SPDX ids the docs use, canonical case, plus the "Public domain" status the
# LIB-LEGAL table already records. Boundaries stop "CC-BY-4.0" matching
# inside "CC-BY-4.01" and "MIT" inside "SUBMIT".
_LICENCE_TOKEN = re.compile(
    r"(?<![A-Za-z0-9-])"
    r"(CC-BY(?:-NC)?(?:-SA|-ND)?(?:-[0-9]\.[0-9])?"
    r"|CC0-1\.0|MIT|Apache-2\.0|BSD-[23]-Clause|[Pp]ublic domain)"
    r"(?![A-Za-z0-9-]|\.[0-9])"
)

_B = r"(?<![A-Za-z0-9_])"
_E = r"(?![A-Za-z0-9_])"
MENTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "unfair_tos": re.compile(_B + r"unfair_tos" + _E),
    "privacy_policy_qa": re.compile(_B + r"privacy_policy_qa" + _E),
    "privacy_policy_entailment": re.compile(_B + r"privacy_policy_entailment" + _E),
    # The OPP-115 family: "OPP115", "OPP-115", "opp115_*", any opp115_<task>.
    "opp115": re.compile(
        _B + r"(?i:opp-?115)(?:_\*|_[A-Za-z0-9_,]*[A-Za-z0-9_])?" + _E
    ),
}

# Characters that forge structure or hide text in a rendered doc: controls,
# format/bidi (Cf), line/paragraph separators, surrogates.
_FORBIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp", "Cs"})


class DocError(AssertionError):
    """A doc could not be read or parsed as the card requires (a test failure)."""


def _show(text: str) -> str:
    """Render untrusted doc text for a message: ASCII-escaped and truncated."""
    return ascii(text[:160])


def read_doc(rel: str, root: Path = REPO_ROOT) -> str:
    """Read a repo doc fail-closed: no symlink indirection, strict UTF-8."""
    path = root / rel
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise DocError(f"{rel}: missing ({type(exc).__name__})") from None
    if resolved != root.resolve() / rel or not resolved.is_file():
        raise DocError(f"{rel}: not a regular file in the repo (symlink or directory)")
    try:
        return resolved.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DocError(f"{rel}: invalid UTF-8 at byte {exc.start}") from None


def doc_lines(text: str) -> list[str]:
    """Split on LF only, as GitHub markdown does.

    ``str.splitlines`` also splits on U+2028, U+0085, VT, FF and FS-RS; those
    must stay inside the line so the forbidden-character check sees them.
    """
    return [line.removesuffix("\r") for line in text.split("\n")]


def forbidden_chars(text: str) -> list[str]:
    return [
        f"U+{ord(ch):04X}"
        for ch in text
        if unicodedata.category(ch) in _FORBIDDEN_CATEGORIES
    ]


def _plain(cell: str) -> str:
    """Normalise a cell for comparison: NFKC, markdown emphasis off, casefold."""
    text = unicodedata.normalize("NFKC", cell)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")
    return text.replace("**", "").replace("`", "").strip().casefold()


def licence_tokens(text: str) -> list[str]:
    return _LICENCE_TOKEN.findall(text)


def is_open_placeholder(cell: str) -> bool:
    return _plain(cell) == "open"


def is_licence_cell(cell: str) -> bool:
    """A licence cell names at least one licence id and hides nothing."""
    return not forbidden_chars(cell) and bool(licence_tokens(cell))


def _split_row(line: str) -> list[str]:
    inner = line.strip()
    if not (inner.startswith("|") and inner.endswith("|")):
        raise DocError(f"table row not delimited by pipes: {_show(line)}")
    cells = re.split(r"(?<!\\)\|", inner[1:-1])
    # Trim ASCII spaces only: str.strip() would also eat U+2028, U+0085 and
    # other separators, hiding them from the forbidden-character check.
    return [c.strip(" ").replace("\\|", "|") for c in cells]


def parse_table(text: str, section: str) -> list[dict[str, str]]:
    """Parse the first pipe table after ``section`` into rows keyed by header.

    Fails closed: missing section, missing table, a row whose cell count
    differs from the header (a stray pipe or line break forged a column), or
    a table with no rows.
    """
    lines = doc_lines(text)
    starts = [i for i, line in enumerate(lines) if line.strip() == section]
    if len(starts) != 1:
        raise DocError(f"section {section!r} found {len(starts)} times, expected 1")
    i = starts[0] + 1
    while i < len(lines) and not lines[i].lstrip().startswith("|"):
        if lines[i].startswith("#"):
            raise DocError(f"section {section!r} has no table")
        i += 1
    if i + 1 >= len(lines):
        raise DocError(f"section {section!r} has no table")
    header = _split_row(lines[i])
    if not re.fullmatch(r"\|(\s*:?-{3,}:?\s*\|)+", lines[i + 1].strip()):
        raise DocError(f"section {section!r}: table has no separator row")
    rows: list[dict[str, str]] = []
    for line in lines[i + 2 :]:
        if not line.lstrip().startswith("|"):
            break
        cells = _split_row(line)
        if len(cells) != len(header):
            raise DocError(
                f"section {section!r}: row has {len(cells)} cells, header has "
                f"{len(header)}: {_show(line)}"
            )
        rows.append(dict(zip(header, cells, strict=True)))
    if not rows:
        raise DocError(f"section {section!r}: table has no rows")
    return rows


def find_row(rows: list[dict[str, str]], key: str, name: str) -> dict[str, str]:
    """Exactly one row whose ``key`` cell is ``name`` (after normalisation)."""
    hits = [r for r in rows if _plain(r.get(key, "")) == _plain(name)]
    if len(hits) != 1:
        raise DocError(f"{len(hits)} rows named {name!r} in column {key!r}, expected 1")
    return hits[0]


def section_lines(text: str, heading: str) -> list[str]:
    """Lines under ``heading`` up to the next heading. Exactly one heading."""
    lines = doc_lines(text)
    starts = [i for i, line in enumerate(lines) if line.strip() == heading]
    if len(starts) != 1:
        raise DocError(f"heading {heading!r} found {len(starts)} times, expected 1")
    out: list[str] = []
    for line in lines[starts[0] + 1 :]:
        if line.startswith("#"):
            break
        out.append(line)
    return out


def licence_line(lines: list[str], heading: str) -> str:
    hits = [ln for ln in lines if re.match(r"\s*\d+\.\s+\*\*License\*\*:", ln)]
    if len(hits) != 1:
        raise DocError(f"{heading!r}: {len(hits)} '**License**:' lines, expected 1")
    return hits[0]


def _mentions(text: str) -> list[tuple[int, int, str]]:
    found = [
        (m.start(), m.end(), key)
        for key, pat in MENTION_PATTERNS.items()
        for m in pat.finditer(text)
    ]
    return sorted(found)


def licences_after(text: str, key: str) -> list[str | None]:
    """For each mention of ``key``: the first licence id after it on the line."""
    out: list[str | None] = []
    for _start, end, k in _mentions(text):
        if k != key:
            continue
        m = _LICENCE_TOKEN.search(text, end)
        out.append(m.group(1) if m else None)
    return out


def mention_before(text: str, token_start: int) -> str | None:
    """The task mention nearest before a licence id on the same line."""
    prior = [k for start, _end, k in _mentions(text) if start < token_start]
    return prior[-1] if prior else None


def split_violations(text: str) -> list[str]:
    """What a LegalBench licence statement gets wrong about the per-task split.

    Contract: each usable task is named and the first licence id after it is
    its exact SPDX id; every non-commercial task named is followed by a
    CC-BY-NC id; at least one CC-BY-NC id states that the rest are blocked;
    no ``Open`` placeholder; nothing hidden.
    """
    problems: list[str] = []
    if bad := forbidden_chars(text):
        problems.append(f"hidden characters {bad[:5]}")
    if "open" in re.findall(r"[a-z]+", _plain(text)) and not licence_tokens(text):
        problems.append("'Open' placeholder instead of a licence id")
    for task in USABLE_TASKS:
        after = licences_after(text, task.mention)
        if not after:
            problems.append(f"{task.task} not named")
        elif any(lic != task.spdx for lic in after):
            problems.append(f"{task.task} paired with {after}, expected {task.spdx}")
    for key in BLOCKED_MENTIONS:
        for lic in licences_after(text, key):
            if lic is None or not lic.startswith(NON_COMMERCIAL_FAMILY):
                problems.append(f"{key} paired with {lic}, expected {NON_COMMERCIAL_FAMILY}*")
    if not any(t.startswith(NON_COMMERCIAL_FAMILY) for t in licence_tokens(text)):
        problems.append("no CC-BY-NC id for the non-commercial tasks")
    return problems


# --------------------------------------------------------------------------
# Acceptance tests: LIB-LEGAL (red today).
# --------------------------------------------------------------------------


def _lib_legal_rows() -> list[dict[str, str]]:
    return parse_table(read_doc(LIB_LEGAL), LIB_LEGAL_SECTION)


def test_lib_legal_multieurlex_licence_is_cc_by_sa_4_0() -> None:
    cell = find_row(_lib_legal_rows(), "Corpus", "MultiEURLEX")["License"]
    assert licence_tokens(cell) == [MULTIEURLEX_SPDX], (
        f"{LIB_LEGAL} MultiEURLEX licence cell is {_show(cell)}; upstream card "
        f"tag is {MULTIEURLEX_SPDX} (coastalcph/multi_eurlex)"
    )


def test_lib_legal_legalbench_licence_names_per_task_split() -> None:
    cell = find_row(_lib_legal_rows(), "Corpus", "LegalBench")["License"]
    problems = split_violations(cell)
    assert problems == [], (
        f"{LIB_LEGAL} LegalBench licence cell {_show(cell)} does not state the "
        f"per-task split: {problems}"
    )


def test_lib_legal_no_licence_cell_is_open_placeholder() -> None:
    rows = _lib_legal_rows()
    bad = [
        (r["Corpus"], r["License"])
        for r in rows
        if is_open_placeholder(r["License"]) or not is_licence_cell(r["License"])
    ]
    assert bad == [], (
        f"{LIB_LEGAL} licence cells must name a licence id, not a placeholder: "
        + ", ".join(f"{_show(c)}={_show(lic)}" for c, lic in bad)
    )


# --------------------------------------------------------------------------
# Acceptance tests: corpus-AGG plan (red today).
# --------------------------------------------------------------------------


def test_corpus_agg_multieurlex_licence_is_cc_by_sa_4_0() -> None:
    lines = section_lines(read_doc(CORPUS_AGG), CORPUS_AGG_MULTIEURLEX_HEADING)
    line = licence_line(lines, CORPUS_AGG_MULTIEURLEX_HEADING)
    tokens = licence_tokens(line)
    assert not forbidden_chars(line), f"hidden characters in {_show(line)}"
    assert tokens[:1] == [MULTIEURLEX_SPDX], (
        f"{CORPUS_AGG} MultiEURLEX licence line {_show(line)} states "
        f"{tokens[:1]}; upstream card tag is {MULTIEURLEX_SPDX}"
    )


def test_corpus_agg_legalbench_licence_names_per_task_split() -> None:
    lines = section_lines(read_doc(CORPUS_AGG), CORPUS_AGG_LEGALBENCH_HEADING)
    line = licence_line(lines, CORPUS_AGG_LEGALBENCH_HEADING)
    problems = split_violations(line)
    assert problems == [], (
        f"{CORPUS_AGG} LegalBench licence line {_show(line)} does not state the "
        f"per-task split: {problems}"
    )


def test_corpus_agg_legalbench_cc_by_4_0_only_for_unfair_tos() -> None:
    """Card spec's grep, made exact.

    The card's ``grep 'LegalBench' | grep -c CC-BY-4.0`` is 0 today because the
    wrong licence line does not repeat the word LegalBench, so it cannot fail.
    This checks every line in the LegalBench section and every line naming
    LegalBench: each CC-BY-4.0 there must belong to ``unfair_tos``.
    """
    text = read_doc(CORPUS_AGG)
    scoped = set(section_lines(text, CORPUS_AGG_LEGALBENCH_HEADING))
    scoped |= {ln for ln in doc_lines(text) if "legalbench" in ln.casefold()}
    cc_by = next(t for t in USABLE_TASKS if t.task == "unfair_tos")
    bad = [
        ln
        for ln in sorted(scoped)
        for m in _LICENCE_TOKEN.finditer(ln)
        if m.group(1) == cc_by.spdx and mention_before(ln, m.start()) != cc_by.mention
    ]
    assert bad == [], (
        f"{CORPUS_AGG} states CC-BY-4.0 for LegalBench beyond {cc_by.task}: "
        + "; ".join(_show(ln) for ln in bad)
    )


def test_corpus_agg_non_commercial_tasks_marked_wherever_named() -> None:
    text = read_doc(CORPUS_AGG)
    bad = [
        (key, lic, ln)
        for ln in doc_lines(text)
        for key in BLOCKED_MENTIONS
        for lic in licences_after(ln, key)
        if lic is None or not lic.startswith(NON_COMMERCIAL_FAMILY)
    ]
    assert bad == [], (
        f"{CORPUS_AGG} names non-commercial LegalBench tasks without a "
        f"{NON_COMMERCIAL_FAMILY} licence on the same line: "
        + "; ".join(f"{k}->{lic}: {_show(ln)}" for k, lic, ln in bad)
    )


# --------------------------------------------------------------------------
# Controls (green today): the docs parse, correct rows pass.
# --------------------------------------------------------------------------


def test_control_lib_legal_eurlex_row_is_cc_by_4_0() -> None:
    """Green today: a correct row passes, so the red rows are red on content."""
    cell = find_row(_lib_legal_rows(), "Corpus", "EUR-Lex")["License"]
    assert licence_tokens(cell) == [EURLEX_SPDX]
    assert is_licence_cell(cell)
    assert not is_open_placeholder(cell)


def test_control_lib_legal_table_has_both_corpora() -> None:
    """Green today: the parser finds the rows the red tests read."""
    rows = _lib_legal_rows()
    for name in ("MultiEURLEX", "LegalBench", "EUR-Lex"):
        assert find_row(rows, "Corpus", name)["Corpus"]


def test_control_corpus_agg_has_no_open_licence_placeholder() -> None:
    """Green today: no '**License**:' line in corpus-AGG says just 'Open'."""
    lines = doc_lines(read_doc(CORPUS_AGG))
    licence_lines = [ln for ln in lines if re.match(r"\s*\d+\.\s+\*\*License\*\*:", ln)]
    assert len(licence_lines) >= 2  # both corpus sections parsed
    bad = [
        ln
        for ln in licence_lines
        if re.findall(r"[a-z]+", _plain(ln.split("**License**:", 1)[1]))[:1] == ["open"]
    ]
    assert bad == [], [_show(ln) for ln in bad]


# --------------------------------------------------------------------------
# Checker vectors (green: they pin the checkers so weakening one goes red).
# --------------------------------------------------------------------------

GOOD_SPLIT = (
    "Per task: `unfair_tos` CC-BY-4.0, `privacy_policy_qa` MIT; the 9 "
    "`opp115_*` tasks and `privacy_policy_entailment` are CC-BY-NC "
    "(HR1-blocked)"
)

# (cell, is_licence_cell, is_open_placeholder)
CELL_VECTORS: list[tuple[str, bool, bool]] = [
    ("CC-BY-4.0", True, False),
    ("**CC-BY-SA-4.0**", True, False),
    ("Public domain", True, False),
    (GOOD_SPLIT, True, False),
    ("Open", False, True),
    ("**Open**", False, True),
    ("`open`", False, True),
    (" OPEN ", False, True),
    ("Open\u200b", False, True),  # ZWSP (Cf)
    ("Ope\u00adn", False, True),  # soft hyphen (Cf)
    ("\uff2f\uff50\uff45\uff4e", False, True),  # fullwidth, NFKC -> Open
    ("\u039fpen", False, False),  # Greek capital omicron look-alike
    ("Open source", False, False),
    ("TBD", False, False),
    ("", False, False),
    ("CC\u2011BY\u20114.0", False, False),  # non-breaking hyphens look-alike
    ("CC-BY-4.01", False, False),
    ("CC BY 4.0", False, False),
    ("SUBMIT", False, False),
    ("CC-BY-4.0\u202e", False, False),  # bidi override hidden in a cell
    ("CC-BY-4.0\u2028", False, False),  # Unicode line separator
]


@pytest.mark.parametrize(
    ("cell", "licence", "placeholder"),
    CELL_VECTORS,
    ids=[ascii(c)[:40] for c, _l, _p in CELL_VECTORS],
)
def test_vectors_cell_checkers(cell: str, licence: bool, placeholder: bool) -> None:
    assert is_licence_cell(cell) is licence
    assert is_open_placeholder(cell) is placeholder


def test_vectors_cell_table_has_both_outcomes() -> None:
    """Contract: each checker has a positive and a negative row."""
    assert {lic for _c, lic, _p in CELL_VECTORS} == {True, False}
    assert {p for _c, _l, p in CELL_VECTORS} == {True, False}


def test_generated_hidden_characters_rejected_in_licence_cell() -> None:
    """Every Cc/Cf/Zl/Zp/Cs code point, before or after a valid id, is rejected."""
    generated = [
        chr(cp)
        for cp in range(0x110000)
        if unicodedata.category(chr(cp)) in _FORBIDDEN_CATEGORIES
    ]
    accepted = [
        f"U+{ord(ch):04X}"
        for ch in generated
        for cell in (EURLEX_SPDX + ch, ch + EURLEX_SPDX)
        if is_licence_cell(cell)
    ]
    print(f"generated hidden-character cases: {len(generated) * 2}")
    assert len(generated) > 2048  # all surrogates plus Cc/Cf/Zl/Zp
    assert accepted == []


# (text, expected split_violations() == [])
SPLIT_VECTORS: list[tuple[str, bool]] = [
    (GOOD_SPLIT, True),
    (
        "unfair_tos: CC-BY-4.0. privacy_policy_qa: MIT. OPP-115 tasks: "
        "CC-BY-NC. privacy_policy_entailment: CC-BY-NC-3.0.",
        True,
    ),
    ("Open", False),
    ("CC-BY-4.0", False),
    ("CC-BY-4.0 for the aggregate; individual tasks may vary", False),
    ("unfair_tos CC-BY-4.0, privacy_policy_qa MIT", False),  # no NC statement
    ("unfair_tos MIT, privacy_policy_qa CC-BY-4.0; rest CC-BY-NC", False),
    ("unfair_tos and privacy_policy_qa: CC-BY-4.0; rest CC-BY-NC", False),
    ("unfair_tos CC-BY-4.0, privacy_policy_qa MIT, opp115_* CC-BY-4.0, CC-BY-NC", False),
    ("unfair_tos CC-BY-4.0, privacy_policy_qa MIT; OPP115 CC-BY-NC", True),
    ("unfair_tos CC-BY-4.0, privacy_policy_qa MIT; OPP115 (see notes)", False),
    (GOOD_SPLIT.replace("unfair_tos", "unfair\u200b_tos"), False),
    (GOOD_SPLIT + "\u202e", False),
    (GOOD_SPLIT.replace("privacy_policy_qa", "privacy_policy_qa_v2"), False),
]


@pytest.mark.parametrize(
    ("text", "ok"), SPLIT_VECTORS, ids=[f"split{i}" for i in range(len(SPLIT_VECTORS))]
)
def test_vectors_split_checker(text: str, ok: bool) -> None:
    assert (split_violations(text) == []) is ok, split_violations(text)


def test_vectors_split_table_has_both_outcomes() -> None:
    assert {ok for _t, ok in SPLIT_VECTORS} == {True, False}


@pytest.mark.parametrize("task", LEGALBENCH_TOS_PRIVACY_TASKS, ids=lambda t: t.task)
def test_vectors_every_task_is_named_by_its_own_mention_only(task: TaskLicence) -> None:
    """Contract: each upstream task matches its own mention pattern, no other."""
    hits = {k for _s, _e, k in _mentions(f"see {task.task} here")}
    assert hits == {task.mention}


def test_vectors_task_table_matches_upstream_counts() -> None:
    """12 ToS/privacy tasks upstream: 2 commercial, 10 non-commercial."""
    assert len(LEGALBENCH_TOS_PRIVACY_TASKS) == 12
    assert [t.task for t in USABLE_TASKS] == ["unfair_tos", "privacy_policy_qa"]


# (markdown, error substring or None)
TABLE_VECTORS: list[tuple[str, str | None]] = [
    ("## s\n\n| Corpus | License |\n|---|---|\n| A | MIT |\n", None),
    ("## s\n\n| Corpus | License |\n|---|---|\n| A | MIT \\| CC-BY-4.0 |\n", None),
    ("## s\n\n| Corpus | License |\n|---|---|\n| A | MIT | x |\n", "cells"),
    ("## s\n\n| Corpus | License |\n|---|---|\n| A |\n", "cells"),
    ("## s\n\n| Corpus | License |\n|---|---|\n", "no rows"),
    ("## s\n\n| Corpus | License |\n| A | MIT |\n", "separator"),
    ("## s\n\ntext only\n## t\n", "no table"),
    ("## other\n", "found 0 times"),
    ("## s\n## s\n", "found 2 times"),
]


@pytest.mark.parametrize(
    ("md", "error"), TABLE_VECTORS, ids=[f"table{i}-{e}" for i, (_m, e) in enumerate(TABLE_VECTORS)]
)
def test_vectors_table_parser_fails_closed(md: str, error: str | None) -> None:
    if error is None:
        rows = parse_table(md, "## s")
        assert [r["Corpus"] for r in rows] == ["A"]
    else:
        with pytest.raises(DocError, match=error):
            parse_table(md, "## s")


def test_vectors_table_has_both_outcomes() -> None:
    assert {e is None for _m, e in TABLE_VECTORS} == {True, False}


def test_line_breaks_other_than_lf_stay_in_the_cell_and_are_rejected() -> None:
    """Every non-LF line break inside a cell stays there and is rejected.

    Generated from ``str.splitlines`` itself (U+2028, U+0085, VT, FF, FS-RS,
    CR, ...), so the set tracks Python's. A trailing CR before LF is a CRLF
    line ending, not cell data, and is the one accepted case.
    """
    lf, cr = chr(10), chr(13)
    breaks = [
        chr(cp)
        for cp in range(0x110000)
        if chr(cp) != lf and len(("a" + chr(cp) + "b").splitlines()) == 2
    ]
    assert {chr(0x2028), chr(0x85), cr} <= set(breaks)
    head = lf.join(["## s", "", "| Corpus | License |", "|---|---|", ""])
    accepted = [
        f"U+{ord(br):04X}"
        for br in breaks
        if is_licence_cell(parse_table(head + f"| A | CC-BY-4.0{br} |" + lf, "## s")[0]["License"])
    ]
    print(f"generated line-break cases: {len(breaks)}")
    assert accepted == []
    crlf = head + "| A | CC-BY-4.0 |" + cr + lf
    assert is_licence_cell(parse_table(crlf, "## s")[0]["License"])


def test_duplicate_row_fails_closed() -> None:
    rows = [{"Corpus": "**MultiEURLEX**"}, {"Corpus": "MultiEURLEX"}]
    with pytest.raises(DocError, match="2 rows"):
        find_row(rows, "Corpus", "MultiEURLEX")


def test_read_doc_fails_closed(tmp_path: Path) -> None:
    """Missing, symlinked and invalid-UTF-8 docs fail; messages stay relative."""
    (tmp_path / "real.md").write_text("ok\n", encoding="utf-8")
    assert read_doc("real.md", tmp_path) == "ok\n"
    (tmp_path / "link.md").symlink_to(tmp_path / "real.md")
    (tmp_path / "bad.md").write_bytes(b"CC-BY-4.0 \xff\xfe\n")
    (tmp_path / "dir.md").mkdir()
    for rel, error in (
        ("missing.md", "missing"),
        ("link.md", "symlink"),
        ("bad.md", "invalid UTF-8"),
        ("dir.md", "not a regular file"),
    ):
        with pytest.raises(DocError, match=error) as info:
            read_doc(rel, tmp_path)
        assert str(tmp_path) not in str(info.value)
