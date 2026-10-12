"""The library docs agree with each other and with the code (#152, plan A5).

Two contradictions in ``.claude/library/``:

1. ``LIB-STACK.md`` lists dependencies under ``forbidden:`` that
   ``LIB-LEGAL.md`` lists in an approved table, and LIB-LEGAL's rejected
   table tells the reader to "use <forbidden package> instead". One side has
   to change. These tests do NOT say which side: plan R1 (the HR2a/HR2b split)
   and R3 (``multilingual-e5-large-instruct``) decide that, not the tests.
2. ``LIB-ARCH.md`` C5 calls ``services/embedding.py`` dead code, yet another
   app module imports it. C6 says the legal KB is wired, but not that a
   missing or empty index yields no legal context, reported through the
   ``legal_grounding`` response field (plan section 2b).

Docs are prose, so most checks here are static by necessity. Where a fact
can come from the code (which modules import the C5 module, the name of the
grounding field) it is read from the code, not restated. Every parser fails
closed on an empty result, a format it cannot read, or hidden characters, so
a format change turns these tests red instead of vacuously green.

Reading a doc, splitting a table row and parsing a table reuse the #159
helpers in ``test_docs_licences`` (one parser per format, F10).

"Approved" means: any pipe table in LIB-LEGAL that is not under a ``##``
section whose heading starts with ``## rejected``. A table anywhere else in
LIB-LEGAL reads as approved to a human, so it counts as approved here.
"""

from __future__ import annotations

import ast
import re
import unicodedata
from pathlib import Path, PurePosixPath

import pytest

from app.schemas import AnalysisPayload
from tests.test_docs_licences import (
    LIB_LEGAL,
    REPO_ROOT,
    DocError,
    _show,
    doc_lines,
    find_row,
    forbidden_chars,
    parse_table,
    read_doc,
)

# Repo-relative so failure messages carry no absolute paths (F8).
LIB_STACK = ".claude/library/LIB-STACK.md"
LIB_ARCH = ".claude/library/LIB-ARCH.md"
APP_DIR = "src/backend/app"

# Doc grammar the parsers read. These name the format, not its content.
FORBIDDEN_KEY = "forbidden:"
SECTION_PREFIX = "## "
REJECTED_SECTION_PREFIX = "## rejected"
ARCH_COMPONENTS_SECTION = "## system-components"
ARCH_ID_COLUMN = "id"
ARCH_LOCATION_COLUMN = "location"
C5_ID = "C5"
C6_ID = "C6"

# The response field that reports an empty or missing legal-KB index. Checked
# against the schema below, so a rename turns the test red instead of
# leaving the doc pinned to a field that no longer exists.
GROUNDING_FIELD = "legal_grounding"

# --------------------------------------------------------------------------
# Name normalisation: one normaliser for both docs (F10, QUALITY-BAR B).
# --------------------------------------------------------------------------

_NAME_SPLIT = re.compile(r"[\s/,;]+")
_PARENS = re.compile(r"\([^()]*\)")
_EXTRAS = re.compile(r"\[[^\[\]]*\]")
# "*" admits a family glob such as "Qwen3-*" (rejected table).
_NAME_TOKEN = re.compile(r"[\w.+*-]+")
_PEP503_SEPARATORS = re.compile(r"[-_.]+")
_EDGE_PUNCT = ".,;:!?\"'"
_DEAD_CODE = re.compile(r"dead[\s_-]*code")
_USE_INSTEAD = re.compile(r"\buse\s+(.+?)\s+instead\b", re.IGNORECASE)


def _reject_hidden(text: str, where: str) -> None:
    hidden = forbidden_chars(text)
    if hidden:
        raise DocError(f"{where}: hidden characters {hidden[:5]} in {_show(text)}")


def _letter_scripts(token: str) -> set[str]:
    """Script of each letter, from its Unicode name (LATIN, CYRILLIC, ...)."""
    return {unicodedata.name(ch, "UNKNOWN").split(" ")[0] for ch in token if ch.isalpha()}


def dependency_names(cell: str) -> set[str]:
    """Normalised dependency names in one doc cell or list item.

    NFKC, markdown emphasis and code ticks off, parenthesised notes and
    ``[extras]`` dropped, split on whitespace, ``/``, ``,`` and ``;``, then
    casefolded with ``-``/``_``/``.`` runs folded to ``-`` (PEP 503). Fails
    closed on hidden characters, mixed-script look-alikes, characters that
    cannot be in a name, and a cell with no name at all.
    """
    _reject_hidden(cell, "name")
    text = unicodedata.normalize("NFKC", cell).replace("**", "").replace("`", "")
    text = _EXTRAS.sub(" ", _PARENS.sub(" ", text))
    names: set[str] = set()
    for raw in _NAME_SPLIT.split(text):
        token = raw.strip(_EDGE_PUNCT)
        if not token:
            continue
        if not _NAME_TOKEN.fullmatch(token):
            raise DocError(f"unparseable name {_show(raw)} in {_show(cell)}")
        if len(_letter_scripts(token)) > 1:
            raise DocError(f"mixed-script name {_show(raw)} in {_show(cell)}")
        names.add(_PEP503_SEPARATORS.sub("-", token.casefold()))
    if not names:
        raise DocError(f"no name in {_show(cell)}")
    return names


def _plain_text(text: str) -> str:
    _reject_hidden(text, "row")
    return unicodedata.normalize("NFKC", text).replace("**", "").replace("`", "").casefold()


def says_dead_code(text: str) -> bool:
    return bool(_DEAD_CODE.search(_plain_text(text)))


def mentions_identifier(text: str, identifier: str) -> bool:
    """``identifier`` appears as a whole Python identifier (not a prefix)."""
    pattern = r"(?<![A-Za-z0-9_])" + re.escape(identifier) + r"(?![A-Za-z0-9_])"
    return re.search(pattern, unicodedata.normalize("NFKC", text)) is not None


# --------------------------------------------------------------------------
# Doc structure.
# --------------------------------------------------------------------------


def blank_fences(text: str) -> str:
    """Blank every line inside a fenced code block (pipes there are not tables).

    Line numbers are kept. An unterminated fence fails closed: it would
    otherwise hide the rest of the doc.
    """
    out: list[str] = []
    fence: str | None = None
    for line in doc_lines(text):
        stripped = line.lstrip(" ")
        if fence is None and stripped.startswith(("```", "~~~")):
            fence = stripped[:3]
            out.append("")
        elif fence is not None:
            if stripped.startswith(fence):
                fence = None
            out.append("")
        else:
            out.append(line)
    if fence is not None:
        raise DocError("unterminated code fence")
    return "\n".join(out)


def doc_tables(text: str) -> list[tuple[str, str, list[dict[str, str]]]]:
    """``(## section, heading, rows)`` for every pipe table in the doc.

    Each table must sit under its own heading so ``parse_table`` (#159) reads
    exactly that table: a second table under one heading, or a table before
    the first heading, fails closed rather than being skipped.
    """
    clean = blank_fences(text)
    section = ""
    heading: str | None = None
    in_table = False
    found: dict[str, str] = {}
    for line in doc_lines(clean):
        if line.startswith("#"):
            heading = line.strip()
            in_table = False
            if line.startswith(SECTION_PREFIX):
                section = heading
            continue
        is_row = line.lstrip(" ").startswith("|")
        if is_row and not in_table:
            if heading is None:
                raise DocError("table before the first heading")
            if heading in found:
                raise DocError(f"heading {_show(heading)} has more than one table")
            found[heading] = section
        in_table = is_row
    if not found:
        raise DocError("no tables")
    return [(sec, head, parse_table(clean, head)) for head, sec in found.items()]


def forbidden_names(text: str) -> set[str]:
    """Union of every ``forbidden:`` line's comma list (LIB-STACK)."""
    lines = [line for line in doc_lines(blank_fences(text)) if line.startswith(FORBIDDEN_KEY)]
    if not lines:
        raise DocError(f"no {FORBIDDEN_KEY!r} line")
    names: set[str] = set()
    for line in lines:
        for item in line[len(FORBIDDEN_KEY) :].split(","):
            if not item.strip(" "):
                raise DocError(f"empty item in forbidden list: {_show(line)}")
            names |= dependency_names(item)
    return names


def is_rejected_section(section: str) -> bool:
    return section.startswith(REJECTED_SECTION_PREFIX)


def approved_names(text: str) -> dict[str, set[str]]:
    """First-column names of every approved table -> the headings naming them."""
    result: dict[str, set[str]] = {}
    for section, heading, rows in doc_tables(text):
        if is_rejected_section(section):
            continue
        first_column = next(iter(rows[0]))
        for row in rows:
            for name in dependency_names(row[first_column]):
                result.setdefault(name, set()).add(heading)
    if not result:
        raise DocError("no approved table")
    return result


def rejected_names(text: str) -> set[str]:
    names: set[str] = set()
    for section, _heading, rows in doc_tables(text):
        if is_rejected_section(section):
            first_column = next(iter(rows[0]))
            for row in rows:
                names |= dependency_names(row[first_column])
    if not names:
        raise DocError("no rejected table")
    return names


def recommended_names(text: str) -> set[str]:
    """Names the doc recommends with "use <name> instead"."""
    names: set[str] = set()
    for line in doc_lines(blank_fences(text)):
        for match in _USE_INSTEAD.finditer(line):
            names |= dependency_names(match.group(1))
    return names


def conflicts(root: Path = REPO_ROOT) -> list[str]:
    """Names forbidden in LIB-STACK and approved in LIB-LEGAL, with headings."""
    forbidden = forbidden_names(read_doc(LIB_STACK, root))
    approved = approved_names(read_doc(LIB_LEGAL, root))
    return [
        f"{name} (LIB-LEGAL {', '.join(_show(h) for h in sorted(approved[name]))})"
        for name in sorted(forbidden & approved.keys())
    ]


def arch_row(text: str, component: str) -> dict[str, str]:
    """The one LIB-ARCH component row whose id cell is ``component``."""
    rows = parse_table(blank_fences(text), ARCH_COMPONENTS_SECTION)
    row = find_row(rows, ARCH_ID_COLUMN, component)
    for cell in row.values():
        _reject_hidden(cell, component)
    return row


def row_text(row: dict[str, str]) -> str:
    return " | ".join(row.values())


# --------------------------------------------------------------------------
# Code facts (read from the code, not restated).
# --------------------------------------------------------------------------


def module_of(location: str, root: Path = REPO_ROOT) -> tuple[str, str]:
    """``(dotted module, app-relative path)`` for a LIB-ARCH location cell."""
    _reject_hidden(location, "location")
    rel = PurePosixPath(location.replace("`", "").replace("**", "").strip(" "))
    if rel.is_absolute() or ".." in rel.parts or rel.suffix != ".py":
        raise DocError(f"location is not an app-relative .py path: {_show(location)}")
    app = root / APP_DIR
    path = app / rel
    if path.is_symlink() or not path.is_file():
        raise DocError(f"location {_show(location)} is not a file under {APP_DIR}")
    package = PurePosixPath(APP_DIR).name
    return ".".join((package, *rel.with_suffix("").parts)), rel.as_posix()


def importers_of(module: str, root: Path = REPO_ROOT) -> list[str]:
    """App-relative paths of app modules that import ``module`` (AST, no exec)."""
    app = root / APP_DIR
    package = PurePosixPath(APP_DIR).name
    hits: list[str] = []
    for path in sorted(app.rglob("*.py")):
        rel = path.relative_to(app).as_posix()
        parts = (package, *PurePosixPath(rel).with_suffix("").parts)
        if ".".join(parts) == module:
            continue
        # A module and a package __init__ both resolve "." to their package.
        pkg = list(parts[:-1])
        imported: list[str] = []
        for node in ast.walk(ast.parse(path.read_bytes().decode("utf-8"), rel)):
            if isinstance(node, ast.Import):
                imported += [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = pkg[: len(pkg) - node.level + 1] if node.level else []
                target = ".".join(base + ([node.module] if node.module else []))
                imported += [target] + [f"{target}.{a.name}" for a in node.names]
        if any(n == module or n.startswith(module + ".") for n in imported):
            hits.append(rel)
    return hits


def _importer_identifier(rel: str) -> str:
    path = PurePosixPath(rel)
    return path.parent.name if path.stem == "__init__" else path.stem


# --------------------------------------------------------------------------
# Acceptance tests (card #152). Red today.
# --------------------------------------------------------------------------


def test_no_dependency_both_forbidden_and_approved() -> None:
    """No name is both ``forbidden:`` in LIB-STACK and approved in LIB-LEGAL."""
    found = conflicts()
    assert found == [], f"forbidden in {LIB_STACK} and approved in {LIB_LEGAL}: {found}"


def test_lib_legal_does_not_recommend_a_forbidden_dependency() -> None:
    """LIB-LEGAL never says "use <X> instead" for an X that LIB-STACK forbids."""
    forbidden = forbidden_names(read_doc(LIB_STACK))
    recommended = sorted(recommended_names(read_doc(LIB_LEGAL)) & forbidden)
    assert recommended == [], f"{LIB_LEGAL} recommends forbidden {recommended}"


def test_lib_arch_c5_not_dead_code() -> None:
    """C5's module is imported by app code, so its row must not say dead code."""
    row = arch_row(read_doc(LIB_ARCH), C5_ID)
    module, rel = module_of(row[ARCH_LOCATION_COLUMN])
    importers = importers_of(module)
    assert importers, f"premise changed: no app module imports {rel}; re-read card #152"
    assert not says_dead_code(row_text(row)), (
        f"{LIB_ARCH} {C5_ID} says dead code, but {rel} is imported by {importers}"
    )


def test_lib_arch_c5_names_every_module_that_imports_it() -> None:
    """C5 describes the real wiring: it names each app module importing it."""
    row = arch_row(read_doc(LIB_ARCH), C5_ID)
    module, rel = module_of(row[ARCH_LOCATION_COLUMN])
    importers = importers_of(module)
    assert importers, f"premise changed: no app module imports {rel}; re-read card #152"
    missing = [
        r for r in importers if not mentions_identifier(row_text(row), _importer_identifier(r))
    ]
    assert missing == [], f"{LIB_ARCH} {C5_ID} does not name importers of {rel}: {missing}"


def test_lib_arch_c6_describes_empty_index_legal_grounding() -> None:
    """C6 names the field that reports an empty or missing index."""
    assert GROUNDING_FIELD in AnalysisPayload.model_fields
    row = arch_row(read_doc(LIB_ARCH), C6_ID)
    assert mentions_identifier(row_text(row), GROUNDING_FIELD), (
        f"{LIB_ARCH} {C6_ID} does not describe the empty-index behaviour "
        f"({GROUNDING_FIELD}): {_show(row_text(row))}"
    )


# --------------------------------------------------------------------------
# Positive controls on the real docs and code. Green today.
# --------------------------------------------------------------------------


def test_control_lib_stack_forbidden_list_is_not_empty() -> None:
    assert forbidden_names(read_doc(LIB_STACK))


def test_control_lib_legal_has_approved_and_rejected_tables() -> None:
    """Both sides of the approved/rejected split parse, so neither is vacuous."""
    text = read_doc(LIB_LEGAL)
    assert approved_names(text)
    assert rejected_names(text)


def test_control_lib_arch_c5_and_c6_rows_point_at_app_modules() -> None:
    text = read_doc(LIB_ARCH)
    for component in (C5_ID, C6_ID):
        module_of(arch_row(text, component)[ARCH_LOCATION_COLUMN])


# --------------------------------------------------------------------------
# Vectors: each checker pinned with positive and negative rows.
# --------------------------------------------------------------------------

# (cell, expected names, or a DocError substring)
NAME_VECTORS: list[tuple[str, set[str] | str]] = [
    ("onnxruntime", {"onnxruntime"}),
    ("**onnxruntime**", {"onnxruntime"}),
    ("`ONNXRuntime`", {"onnxruntime"}),
    ("sentence-transformers[onnx]", {"sentence-transformers"}),
    ("Sentence_Transformers", {"sentence-transformers"}),
    ("sentence.transformers", {"sentence-transformers"}),
    ("sentence__transformers", {"sentence-transformers"}),
    ("onnxruntime (CPU build)", {"onnxruntime"}),
    ("FAISS / faiss-cpu", {"faiss", "faiss-cpu"}),
    ("Qwen / Qwen3-*", {"qwen", "qwen3-*"}),
    ("ｏｎｎｘｒｕｎｔｉｍｅ", {"onnxruntime"}),
    ("**intfloat/multilingual-e5-large-instruct**", {"intfloat", "multilingual-e5-large-instruct"}),
    ("onnxruntime-gpu", {"onnxruntime-gpu"}),  # a different distribution
    ("torchvision", {"torchvision"}),  # not torch
    ("Légifrance", {"légifrance"}),  # one script: allowed
    ("onnx​runtime", "hidden"),
    ("onnxruntime‮", "hidden"),
    ("оnnxruntime", "mixed-script"),  # Cyrillic o
    ("οnnxruntime", "mixed-script"),  # Greek omicron
    ("onnx|runtime", "unparseable"),
    ("sentence-transformers[onnx", "unparseable"),
    ("", "no name"),
    ("**  **", "no name"),
]


@pytest.mark.parametrize(
    ("cell", "expected"), NAME_VECTORS, ids=[f"name{i}" for i in range(len(NAME_VECTORS))]
)
def test_vectors_dependency_names(cell: str, expected: set[str] | str) -> None:
    if isinstance(expected, set):
        assert dependency_names(cell) == expected
    else:
        with pytest.raises(DocError, match=expected) as info:
            dependency_names(cell)
        assert str(info.value).isascii()


def test_vectors_name_table_has_both_outcomes() -> None:
    assert {isinstance(e, set) for _c, e in NAME_VECTORS} == {True, False}


STACK_OK = "## s\n\n### S3\nrule: x\nforbidden: Torch, onnxruntime\n"
LEGAL_OK = (
    "# t\n\n## approved-x\n\n| Model | Note |\n|---|---|\n| e5 | ok |\n\n"
    "## rejected-tools\n\n| Tool | Why |\n|---|---|\n| torch | Meta |\n"
)

# (LIB-STACK text, LIB-LEGAL text, expected conflicts or a DocError substring)
CONFLICT_VECTORS: list[tuple[str, str, list[str] | str]] = [
    (STACK_OK, LEGAL_OK, []),
    (
        STACK_OK,
        LEGAL_OK.replace("| e5 |", "| **ONNX_Runtime** |"),
        [],
    ),  # onnx-runtime != onnxruntime
    (
        STACK_OK,
        LEGAL_OK.replace("| e5 |", "| onnxruntime |"),
        ["onnxruntime (LIB-LEGAL '## approved-x')"],
    ),
    (
        STACK_OK.replace("onnxruntime", "sentence-transformers"),
        LEGAL_OK.replace("| e5 |", "| sentence_transformers[onnx] |"),
        ["sentence-transformers (LIB-LEGAL '## approved-x')"],
    ),
    (
        STACK_OK,
        LEGAL_OK.replace("## approved-x\n", "## inference-backend\n\n### L9: x\n"),
        [],
    ),
    (
        STACK_OK,
        LEGAL_OK.replace("## approved-x\n", "## inference-backend\n\n### L9: x\n").replace(
            "| e5 |", "| ONNXRUNTIME |"
        ),
        ["onnxruntime (LIB-LEGAL '### L9: x')"],
    ),
    (STACK_OK, LEGAL_OK.replace("| torch | Meta |", "| torch | Meta |"), []),  # rejected only
    (
        STACK_OK,
        LEGAL_OK + "\n## legal-corpora\n\n```\n| onnxruntime | fenced |\n```\n",
        [],
    ),
    (
        STACK_OK,
        LEGAL_OK + "\n## more\n\n| A |\n|---|\n| onnxruntime |\n",
        ["onnxruntime (LIB-LEGAL '## more')"],
    ),
    (
        "forbidden: torch\nforbidden: onnxruntime\n",
        LEGAL_OK.replace("| e5 |", "| onnxruntime |"),
        ["onnxruntime (LIB-LEGAL '## approved-x')"],
    ),
    ("## s\nno list here\n", LEGAL_OK, "no 'forbidden:' line"),
    ("  forbidden: onnxruntime\n", LEGAL_OK, "no 'forbidden:' line"),
    ("forbidden: torch,, onnxruntime\n", LEGAL_OK, "empty item"),
    ("forbidden:\n", LEGAL_OK, "empty item"),
    ("```\nforbidden: onnxruntime\n```\n", LEGAL_OK, "no 'forbidden:' line"),
    (
        STACK_OK,
        "## rejected-tools\n\n| Tool | Why |\n|---|---|\n| torch | Meta |\n",
        "no approved table",
    ),
    (STACK_OK, "## a\n\ntext only\n", "no tables"),
    (STACK_OK, "| A |\n|---|\n| x |\n## a\n", "before the first heading"),
    (STACK_OK, "## a\n\n| A |\n|---|\n| x |\n\n| B |\n|---|\n| y |\n", "more than one table"),
    (STACK_OK, "## a\n\n| A |\n|---|\n| x |\n```\nopen fence\n", "unterminated"),
    (STACK_OK, "## a\n\n| A | B |\n|---|---|\n| x | y | z |\n", "cells"),
    (STACK_OK, "## a\n\n| A |\n| x |\n", "separator"),
    (STACK_OK, "## a\n\n| A |\n|---|\n", "no rows"),
    (STACK_OK, "## a\n\n| A |\n|---|\n| оnnxruntime |\n", "mixed-script"),
]


def _write_docs(root: Path, stack: str, legal: str) -> None:
    for rel, text in ((LIB_STACK, stack), (LIB_LEGAL, legal)):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")


@pytest.mark.parametrize(
    ("stack", "legal", "expected"),
    CONFLICT_VECTORS,
    ids=[f"conflict{i}" for i in range(len(CONFLICT_VECTORS))],
)
def test_vectors_conflicts_checker(
    tmp_path: Path, stack: str, legal: str, expected: list[str] | str
) -> None:
    _write_docs(tmp_path, stack, legal)
    if isinstance(expected, list):
        assert conflicts(tmp_path) == expected
    else:
        with pytest.raises(DocError, match=expected) as info:
            conflicts(tmp_path)
        assert str(info.value).isascii()


def test_vectors_conflict_table_has_both_outcomes() -> None:
    kinds = {
        "clean" if e == [] else "conflict" if isinstance(e, list) else "error"
        for _s, _l, e in CONFLICT_VECTORS
    }
    assert kinds == {"clean", "conflict", "error"}


# (text, recommended names)
RECOMMEND_VECTORS: list[tuple[str, set[str]]] = [
    ("| torch | Meta origin; use onnxruntime instead |", {"onnxruntime"}),
    ("Use **ONNX_Runtime** instead.", {"onnx-runtime"}),
    ("use LocalAI embeddings instead", {"localai", "embeddings"}),
    ("Meta origin; fails no-Meta requirement", set()),
    ("wraps onnxruntime; rejected", set()),
    ("```\nuse onnxruntime instead\n```", set()),
]


@pytest.mark.parametrize(
    ("text", "expected"),
    RECOMMEND_VECTORS,
    ids=[f"recommend{i}" for i in range(len(RECOMMEND_VECTORS))],
)
def test_vectors_recommended_names(text: str, expected: set[str]) -> None:
    assert recommended_names(text) == expected


def test_vectors_recommend_table_has_both_outcomes() -> None:
    assert {bool(e) for _t, e in RECOMMEND_VECTORS} == {True, False}


# (row text, says dead code, or a DocError substring)
DEAD_CODE_VECTORS: list[tuple[str, bool | str]] = [
    ("not yet wired into `analyzer.py` — dead code", True),
    ("**Dead** Code", True),
    ("dead-code", True),
    ("dead_code", True),
    ("deadcode", True),
    ("dead code", True),  # NBSP folds to a space under NFKC
    ("dead\n code", "hidden"),  # a cell never holds a raw line break
    ("used by `legal_kb.py` for BM25 + RRF", False),
    ("deadline code review", False),
    ("not dead; code is live", False),
    ("dead​code", "hidden"),
    ("dead code", "hidden"),
]


@pytest.mark.parametrize(
    ("text", "expected"),
    DEAD_CODE_VECTORS,
    ids=[f"dead{i}" for i in range(len(DEAD_CODE_VECTORS))],
)
def test_vectors_dead_code_matcher(text: str, expected: bool | str) -> None:
    if isinstance(expected, bool):
        assert says_dead_code(text) is expected
    else:
        with pytest.raises(DocError, match=expected):
            says_dead_code(text)


def test_vectors_dead_code_table_has_both_outcomes() -> None:
    assert {e for _t, e in DEAD_CODE_VECTORS if isinstance(e, bool)} == {True, False}


# (text, identifier, mentioned)
IDENTIFIER_VECTORS: list[tuple[str, str, bool]] = [
    ("`legal_grounding` is False when the index is missing", GROUNDING_FIELD, True),
    ("legal_grounding: false", GROUNDING_FIELD, True),
    ("sets legal_grounding_authoritative", GROUNDING_FIELD, False),
    ("xlegal_grounding", GROUNDING_FIELD, False),
    ("legal grounding", GROUNDING_FIELD, False),
    ("legalgrounding", GROUNDING_FIELD, False),
    ("used by `legal_kb.py`", "legal_kb", True),
    ("used by legal_kb_bundle.py", "legal_kb", False),
]


@pytest.mark.parametrize(
    ("text", "identifier", "expected"),
    IDENTIFIER_VECTORS,
    ids=[f"ident{i}" for i in range(len(IDENTIFIER_VECTORS))],
)
def test_vectors_identifier_matcher(text: str, identifier: str, expected: bool) -> None:
    assert mentions_identifier(text, identifier) is expected


def test_vectors_identifier_table_has_both_outcomes() -> None:
    assert {e for _t, _i, e in IDENTIFIER_VECTORS} == {True, False}


def _write_app(root: Path, files: dict[str, str]) -> None:
    for rel, src in files.items():
        path = root / APP_DIR / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(src, encoding="utf-8")


def test_importers_of_resolves_every_import_form(tmp_path: Path) -> None:
    """Relative, absolute, aliased and package imports count; look-alikes don't."""
    _write_app(
        tmp_path,
        {
            "__init__.py": "",
            "services/__init__.py": "",
            "services/embedding.py": "def f() -> None: ...\n",
            "services/embedding_extra.py": "",
            "services/rel.py": "from .embedding import f\n",
            "services/pkg_rel.py": "from . import embedding\n",
            "services/abs.py": "import app.services.embedding as e\n",
            "services/abs_from.py": "from app.services.embedding import f\n",
            "api/up.py": "from ..services.embedding import f\n",
            "api/__init__.py": "from ..services import embedding\n",
            "services/lookalike.py": "from .embedding_extra import g\nimport app.services.embedding_extra\n",
            "services/comment.py": "# from .embedding import f\nx = 'app.services.embedding'\n",
            "services/other_pkg.py": "from .other.embedding import f\n",
        },
    )
    assert importers_of("app.services.embedding", tmp_path) == [
        "api/__init__.py",
        "api/up.py",
        "services/abs.py",
        "services/abs_from.py",
        "services/pkg_rel.py",
        "services/rel.py",
    ]
    assert importers_of("app.services.embedding_extra", tmp_path) == ["services/lookalike.py"]
    assert _importer_identifier("api/__init__.py") == "api"
    assert _importer_identifier("services/legal_kb.py") == "legal_kb"


# (location cell, ok, or a DocError substring)
LOCATION_VECTORS: list[tuple[str, tuple[str, str] | str]] = [
    ("`services/embedding.py`", ("app.services.embedding", "services/embedding.py")),
    ("**services/embedding.py**", ("app.services.embedding", "services/embedding.py")),
    ("services/missing.py", "not a file"),
    ("../app/services/embedding.py", "not an app-relative"),
    ("/services/embedding.py", "not an app-relative"),
    ("services/embedding.txt", "not an app-relative"),
    ("services/link.py", "not a file"),
    ("services", "not an app-relative"),
    ("services/embedding.py‮", "hidden"),
]


@pytest.mark.parametrize(
    ("cell", "expected"),
    LOCATION_VECTORS,
    ids=[f"location{i}" for i in range(len(LOCATION_VECTORS))],
)
def test_vectors_module_of_location(
    tmp_path: Path, cell: str, expected: tuple[str, str] | str
) -> None:
    _write_app(tmp_path, {"services/embedding.py": "", "services/embedding.txt": ""})
    (tmp_path / APP_DIR / "services/link.py").symlink_to(
        tmp_path / APP_DIR / "services/embedding.py"
    )
    if isinstance(expected, tuple):
        assert module_of(cell, tmp_path) == expected
    else:
        with pytest.raises(DocError, match=expected) as info:
            module_of(cell, tmp_path)
        assert str(tmp_path) not in str(info.value)
        assert str(info.value).isascii()


def test_vectors_location_table_has_both_outcomes() -> None:
    assert {isinstance(e, tuple) for _c, e in LOCATION_VECTORS} == {True, False}


ARCH_TABLE = (
    "## system-components\n\n| id | component | location | role |\n|---|---|---|---|\n"
    "| C5 | Emb | `services/embedding.py` | used by `legal_kb.py` |\n"
    "| C6 | KB | `services/legal_kb.py` | `legal_grounding` False on empty index |\n"
)


def test_arch_row_finds_rows_by_id_not_position() -> None:
    swapped = ARCH_TABLE.replace("| C5 |", "| CX |").replace("| C6 |", "| C5 |")
    assert arch_row(swapped, C5_ID)[ARCH_LOCATION_COLUMN] == "`services/legal_kb.py`"
    assert arch_row(ARCH_TABLE, C6_ID)[ARCH_LOCATION_COLUMN] == "`services/legal_kb.py`"


@pytest.mark.parametrize(
    ("md", "error"),
    [
        (ARCH_TABLE.replace("| C6 |", "| C5 |"), "2 rows"),
        (ARCH_TABLE.replace("| C5 |", "| C7 |"), "0 rows"),
        (ARCH_TABLE.replace("| id |", "| key |"), "0 rows"),
        (ARCH_TABLE.replace("## system-components", "## components"), "found 0 times"),
        (ARCH_TABLE.replace("used by", "used​by"), "hidden"),
        (ARCH_TABLE.replace("| Emb |", "| Emb | x |"), "cells"),
    ],
    ids=["dup-id", "missing-id", "no-id-column", "no-section", "hidden", "forged-cell"],
)
def test_arch_row_fails_closed(md: str, error: str) -> None:
    with pytest.raises(DocError, match=error):
        arch_row(md, C5_ID)


# --------------------------------------------------------------------------
# Generated hostile inputs (QUALITY-BAR R2): counts are printed.
# --------------------------------------------------------------------------

_HIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp", "Cs"})


def test_generated_hidden_characters_rejected_in_names() -> None:
    """Every Cc/Cf/Zl/Zp/Cs code point before, inside or after a name fails."""
    generated = [
        chr(cp) for cp in range(0x110000) if unicodedata.category(chr(cp)) in _HIDDEN_CATEGORIES
    ]
    accepted: list[str] = []
    for ch in generated:
        for cell in (ch + "onnxruntime", "onnx" + ch + "runtime", "onnxruntime" + ch):
            try:
                dependency_names(cell)
            except DocError:
                continue
            accepted.append(f"U+{ord(ch):04X}")
    print(f"generated hidden-character cases: {len(generated) * 3}")
    assert len(generated) > 2048  # every surrogate plus Cc/Cf/Zl/Zp
    assert accepted == []


def test_generated_line_breaks_in_forbidden_line_rejected() -> None:
    """Every non-LF line break stays in the ``forbidden:`` line and fails it.

    Generated from ``str.splitlines`` so the set tracks Python's. CRLF is a
    line ending, not data, and is the one accepted case.
    """
    lf, cr = chr(10), chr(13)
    breaks = [
        chr(cp)
        for cp in range(0x110000)
        if chr(cp) != lf and len(("a" + chr(cp) + "b").splitlines()) == 2
    ]
    assert {chr(0x2028), chr(0x2029), chr(0x85), cr} <= set(breaks)
    accepted: list[str] = []
    for br in breaks:
        try:
            forbidden_names(f"forbidden: torch,{br}onnxruntime{lf}")
        except DocError:
            continue
        accepted.append(f"U+{ord(br):04X}")
    print(f"generated line-break cases: {len(breaks)}")
    assert accepted == []
    assert forbidden_names(f"forbidden: torch, onnxruntime{cr}{lf}") == {"torch", "onnxruntime"}


def test_generated_mixed_script_lookalikes_rejected() -> None:
    """Every Greek or Cyrillic letter swapped into a Latin name fails closed."""
    generated = [
        chr(cp)
        for cp in range(0x0370, 0x0530)
        if chr(cp).isalpha()
        and unicodedata.name(chr(cp), "").split(" ")[0] in {"GREEK", "CYRILLIC"}
    ]
    accepted = []
    for ch in generated:
        try:
            dependency_names(ch + "nnxruntime")
        except DocError:
            continue
        accepted.append(f"U+{ord(ch):04X}")
    print(f"generated look-alike cases: {len(generated)}")
    assert len(generated) > 300
    assert accepted == []


# --------------------------------------------------------------------------
# Indirection and message safety for the doc readers.
# --------------------------------------------------------------------------


def test_conflicts_refuses_symlinked_missing_or_invalid_docs(tmp_path: Path) -> None:
    """A symlinked, missing or non-UTF-8 doc fails closed; messages stay relative."""
    _write_docs(tmp_path, STACK_OK, LEGAL_OK)
    stack = tmp_path / LIB_STACK
    real = tmp_path / "elsewhere.md"
    real.write_text("forbidden: nothing-here\n", encoding="utf-8")
    stack.unlink()
    stack.symlink_to(real)
    with pytest.raises(DocError, match="symlink") as info:
        conflicts(tmp_path)
    assert str(tmp_path) not in str(info.value)
    stack.unlink()
    stack.write_bytes(b"forbidden: onnx\xffruntime\n")
    with pytest.raises(DocError, match="invalid UTF-8"):
        conflicts(tmp_path)
    stack.unlink()
    with pytest.raises(DocError, match="missing") as info:
        conflicts(tmp_path)
    assert str(tmp_path) not in str(info.value)
