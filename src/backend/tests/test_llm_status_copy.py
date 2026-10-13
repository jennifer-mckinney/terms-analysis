"""Acceptance tests for #368: the one shared llm_status label mapping.

Contract (test author's proposal, lead ruling 2026-10-12 "one shared place"):

* Module ``app.llm_status_copy`` (``src/backend/app/llm_status_copy.py``) owns the
  reader-facing copy for every ``schemas.LLMStatus`` value. Scope is the backend
  only (owner ruling 2026-10-12: "Focus on the backend first and UI second"): the
  PDF export takes its text from it (the CSV export and /reviews carry the
  canonical token), and no other module in ``src/backend/app`` restates a label.
  There is no legacy UI consumer; the legacy UI is dropped. The v2 UI joins
  ``CONSUMER_DIRS`` as a consumer in the follow-up UI card, which also decides how
  the deployed webapp reaches this copy.
* ``llm_status_label(value: object) -> str`` is total. A member returns its label.
  Anything else (missing, ``None``, empty, a typo, a case or look-alike variant, a
  non-string, a huge value, markup) returns exactly ``llm_status_label("unknown")``:
  fail closed to a visible unknown state that never reads as success.
* ``RULES_ONLY_MARKER: str`` appears in the label of every rules-only status
  (each ``fallback_*`` value and ``disabled``, quick mode, where the LLM never
  runs), so each one reads as rules-only. It does not appear in the ``ok`` label,
  and not in the ``unknown`` label (an old row may have had an LLM answer, so
  claiming rules-only there would be dishonest too).
* The module is standard library only. That keeps the follow-up UI card's options
  open: the webapp (a separate deployable with only streamlit and requests
  installed) can load the same file without the backend package.

Copy is not pinned (lead ruling): the tests check properties, never sentences.
Copy follows LIB-VOICE V2 (no you/we/us/our/your in results) and V6 (no em-dash).
"""
from __future__ import annotations

import ast
import importlib
import re
import subprocess
import sys
import textwrap
import unicodedata
from pathlib import Path
from types import ModuleType
from typing import Any, get_args

import pytest

from app import schemas
from tests.test_auth_ratelimit import BACKEND_DIR, CHILD_TIMEOUT_S
from tests.test_regressions_pr34 import _forged_status_variants

MODULE_NAME = "app.llm_status_copy"
MODULE_PATH = BACKEND_DIR / "app" / "llm_status_copy.py"
SRC_DIR = BACKEND_DIR.parent
# The consumers that must take their copy from the module, never restate it.
# Backend only for #368; the follow-up UI card adds the v2 UI here.
CONSUMER_DIRS = (BACKEND_DIR / "app",)

# The API contract names (LIB-API API7), not config: the success value, the
# fail-closed default, quick mode, and the prefix every fallback carries.
OK = "ok"
UNKNOWN = "unknown"
DISABLED = "disabled"
FALLBACK_PREFIX = "fallback_"

# A token no label will ever contain: if it reaches a rendered page, an export or
# an API body, a raw stored value was echoed.
RAW_MARKER = "FORGED368"

# LIB-VOICE V2: results copy never uses these words.
_V2_FORBIDDEN = re.compile(r"\b(you|we|us|our|your)\b", re.IGNORECASE)
_EM_DASH = "—"  # LIB-VOICE V6


def copy_module() -> ModuleType:
    # Imported at call time so a missing module fails each test (red for the
    # right reason: missing symbol), not the collection of the whole suite.
    return importlib.import_module(MODULE_NAME)


def label(value: object) -> str:
    return copy_module().llm_status_label(value)


def members() -> tuple[str, ...]:
    return get_args(schemas.LLMStatus)


def fallback_members() -> tuple[str, ...]:
    return tuple(m for m in members() if m.startswith(FALLBACK_PREFIX))


def rules_only_members() -> tuple[str, ...]:
    return (*fallback_members(), DISABLED)


# ---------------------------------------------------------------------------
# Hostile stored values: every one must read as unknown, on every surface.
# Shared with the endpoint and UI tests (one table, QUALITY-BAR test rule 8).
# ``json_ok`` marks the values a JSON column can hold (endpoint tables).
# ---------------------------------------------------------------------------

HOSTILE_VALUES: list[tuple[str, Any]] = [
    ("none", None),
    ("empty", ""),
    ("space", " "),
    ("typo-okay", "okay"),
    ("success-word", "success"),
    ("true-word", "true"),
    ("bare-fallback", "fallback"),
    ("prefix-only", FALLBACK_PREFIX),
    ("int-0", 0),
    ("int-1", 1),
    ("bool-true", True),
    ("bool-false", False),
    ("float", 0.0),
    ("list", [OK]),
    ("dict", {"llm_status": OK}),
    ("script", f"<script>{RAW_MARKER}</script>"),
    ("html-ok", f"<b>{OK}</b>{RAW_MARKER}"),
    ("reportlab-markup", f"<font color='green'>{OK}</font>{RAW_MARKER}"),
    ("entity", f"&lt;{OK}&gt;{RAW_MARKER}"),
    ("csv-formula", f'=HYPERLINK("http://x","{RAW_MARKER}")'),
    ("csv-delimiter", f'{OK},{RAW_MARKER}"\r\n'),
    ("markdown", f"{OK}\n\n**{RAW_MARKER}**"),
    ("crlf-injection", f"{OK}\r\n{RAW_MARKER}"),
    ("bidi", f"‮{RAW_MARKER}"),
    ("nul", f"{OK}\x00{RAW_MARKER}"),
    ("lone-surrogate", f"\ud800{RAW_MARKER}"),
    ("huge", RAW_MARKER * 100_000),
]
_NOT_JSON = {"lone-surrogate"}  # json.dumps escapes it, but SQLite text round trips are not the point


def json_hostile_values() -> list[tuple[str, Any]]:
    return [(i, v) for i, v in HOSTILE_VALUES if i not in _NOT_JSON]


def forged_member_variants() -> list[str]:
    """Generated look-alikes of every member (case, space, NUL, line breaks, Cf)."""
    out: list[str] = []
    for m in members():
        out.extend(v for v in _forged_status_variants(m) if v not in members())
    return out


def visible_text_variants(text: str) -> tuple[str, ...]:
    # A sink may HTML-escape the label (reportlab markup in the PDF export).
    import html

    return (text, html.escape(text), html.escape(text, quote=False))


# ---------------------------------------------------------------------------
# The mapping itself
# ---------------------------------------------------------------------------


class TestLabelContract:
    @pytest.mark.parametrize("status", members())
    def test_every_member_has_a_non_empty_single_line_label(self, status: str) -> None:
        text = label(status)
        assert isinstance(text, str)
        assert text.strip() == text and text
        assert len(text.splitlines()) == 1
        # No control, format, line or paragraph separators (structure forgery
        # in CSV, PDF markup and HTML sinks).
        bad = [hex(ord(c)) for c in text if unicodedata.category(c) in {"Cc", "Cf", "Zl", "Zp"}]
        assert bad == []

    def test_labels_are_pairwise_distinct(self) -> None:
        labels = {m: label(m) for m in members()}
        assert len(set(labels.values())) == len(labels), labels

    def test_every_member_except_unknown_is_known(self) -> None:
        # Drift guard: a value added to schemas.LLMStatus without copy would
        # silently read as unknown.
        unknown = label(UNKNOWN)
        assert [m for m in members() if m != UNKNOWN and label(m) == unknown] == []

    @pytest.mark.parametrize("status", rules_only_members())
    def test_rules_only_labels_carry_the_marker(self, status: str) -> None:
        marker = copy_module().RULES_ONLY_MARKER
        assert isinstance(marker, str) and marker.strip()
        assert marker in label(status)

    def test_rules_only_labels_name_distinct_reasons(self) -> None:
        marker = copy_module().RULES_ONLY_MARKER
        reasons = {m: label(m).replace(marker, "").strip(" .,:;()-") for m in rules_only_members()}
        assert all(reasons.values()), reasons
        assert len(set(reasons.values())) == len(reasons), reasons

    def test_success_label_is_distinct_and_carries_no_rules_only_marker(self) -> None:
        marker = copy_module().RULES_ONLY_MARKER
        ok = label(OK)
        assert marker not in ok
        # Never a substring of another label: a page or export that shows a
        # fallback or unknown label can never also read as the success label.
        assert [m for m in members() if m != OK and ok in label(m)] == []

    def test_unknown_is_not_success_and_not_rules_only(self) -> None:
        marker = copy_module().RULES_ONLY_MARKER
        unknown = label(UNKNOWN)
        assert unknown != label(OK)
        assert label(OK) not in unknown
        assert marker not in unknown

    @pytest.mark.parametrize("status", members())
    def test_labels_follow_lib_voice(self, status: str) -> None:
        text = label(status)
        assert _EM_DASH not in text  # V6
        assert _V2_FORBIDDEN.findall(text) == []  # V2

    def test_marker_follows_lib_voice(self) -> None:
        marker = copy_module().RULES_ONLY_MARKER
        assert _EM_DASH not in marker
        assert _V2_FORBIDDEN.findall(marker) == []


class TestFailClosed:
    @pytest.mark.parametrize("value", [v for _, v in HOSTILE_VALUES], ids=[i for i, _ in HOSTILE_VALUES])
    def test_non_member_reads_as_unknown(self, value: object) -> None:
        assert label(value) == label(UNKNOWN)

    def test_forged_look_alikes_of_every_member_read_as_unknown(self) -> None:
        unknown = label(UNKNOWN)
        variants = forged_member_variants()
        leaked = [v.encode("unicode_escape").decode("ascii") for v in variants if label(v) != unknown]
        print(f"llm_status forged variants fed to llm_status_label: {len(variants)}")
        assert leaked == []

    def test_hostile_table_has_both_polarities(self) -> None:
        # Contract test for the table: every hostile entry is a non-member
        # (negative), and every member maps away from unknown (positive) in
        # test_every_member_except_unknown_is_known.
        assert [i for i, v in HOSTILE_VALUES if isinstance(v, str) and v in members()] == []
        assert RAW_MARKER not in "".join(members())


# ---------------------------------------------------------------------------
# One shared place
# ---------------------------------------------------------------------------


def test_module_loads_with_the_standard_library_only() -> None:
    # Kept while the UI is out of scope: the webapp ships with streamlit and
    # requests only and imports nothing from the backend package, so a stdlib
    # module leaves the follow-up UI card free to load this same file.
    probe = textwrap.dedent(
        """
        import importlib.util, sys
        for name in ("app", "pydantic", "fastapi", "starlette", "sqlalchemy",
                     "httpx", "requests", "streamlit"):
            sys.modules[name] = None
        spec = importlib.util.spec_from_file_location("llm_status_copy_probe", sys.argv[1])
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert module.llm_status_label("ok") != module.llm_status_label("unknown")
        assert module.llm_status_label(object()) == module.llm_status_label("unknown")
        print("loaded")
        """
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", probe, str(MODULE_PATH)],
        capture_output=True,
        text=True,
        timeout=CHILD_TIMEOUT_S,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip() == "loaded"


def _string_constants(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.name)
    return {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def test_no_consumer_restates_a_label() -> None:
    # Static by necessity: duplication can't be observed by running the code
    # (a copy with identical text renders identically). Every UI and export
    # must call llm_status_label; a restated label is a second source of truth.
    labels = {label(m): m for m in members()}
    files = sorted(p for d in CONSUMER_DIRS for p in d.rglob("*.py") if p.resolve() != MODULE_PATH.resolve())
    assert files, "no consumer files found"
    restated = [
        (str(p.relative_to(SRC_DIR)), labels[c]) for p in files for c in _string_constants(p) if c in labels
    ]
    assert restated == [], "label text must live only in app/llm_status_copy.py"
