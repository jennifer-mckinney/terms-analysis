"""Acceptance tests for #368 on the Streamlit side: every result shows llm_status.

Both UIs ``run.sh`` can start are covered: v2 (default) and the legacy v1 UI
(``STREAMLIT_UI=v1``), so a rollback never hides why a result is rules-only.

Contract (see ``test_llm_status_copy`` for the shared mapping):

* The results view renders ``llm_status_label(result.get("llm_status"))`` from
  ``app.llm_status_copy``, the one shared mapping. Each status shows its own label
  and no other.
* A missing, unknown or forged value shows the unknown label and never the
  success label. The raw value is never rendered (markup, markdown, line breaks,
  bidi controls, huge values).
* The legacy UI shows the status for every result, including a result with zero
  findings: a rules-only run that found nothing is exactly the result a reader
  must not mistake for a clean full review.

Runs the real script through Streamlit's AppTest, reusing the #133 fixtures.
"""
from __future__ import annotations

from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from tests.test_llm_status_copy import (
    HOSTILE_VALUES,
    OK,
    RAW_MARKER,
    UNKNOWN,
    forged_member_variants,
    label,
    members,
    visible_text_variants,
)
from tests.test_streamlit_backend_auth import (  # noqa: F401  (fixtures are used by name)
    APPTEST_TIMEOUT_S,
    LEGACY_PATH,
    V2_PATH,
    _Recorder,
    _results_state,
    _tree_text,
    fake_context,
    recorder,
    ui_env,
)

_ABSENT = object()
_FINDING = {"title": "Stub", "severity": "high", "category": "Data", "excerpt": "We share data.", "confidence": 0.9}
_RAW_CASES = [(i, v) for i, v in HOSTILE_VALUES if isinstance(v, str) and RAW_MARKER in v]


def _v2_apptest(value: Any) -> AppTest:
    at = AppTest.from_file(str(V2_PATH), default_timeout=APPTEST_TIMEOUT_S)
    at.session_state["view"] = "results"
    state = _results_state()
    if value is not _ABSENT:
        state["llm_status"] = value
    at.session_state["analysis_result"] = state
    return at


def _legacy_apptest(value: Any, *, with_findings: bool = True) -> AppTest:
    at = AppTest.from_file(str(LEGACY_PATH), default_timeout=APPTEST_TIMEOUT_S)
    findings = [dict(_FINDING)] if with_findings else []
    result: dict[str, Any] = {
        "id": "abc",
        "findings": findings,
        "grade": "A",
        "risk_score": 2.0,
        "confidence": 0.9,
        "review_required": False,
    }
    if value is not _ABSENT:
        result["llm_status"] = value
    at.session_state["findings"] = findings
    at.session_state["analysis_complete"] = True
    at.session_state["last_result"] = result
    return at


_UIS = {
    "v2": lambda value: _v2_apptest(value),
    "legacy": lambda value: _legacy_apptest(value),
    "legacy-zero-findings": lambda value: _legacy_apptest(value, with_findings=False),
}


def _render(at: AppTest) -> str:
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return "\n".join(_tree_text(at._tree))


def _shows(rendered: str, text: str) -> bool:
    return any(v in rendered for v in visible_text_variants(text))


@pytest.fixture
def ui(ui_env: str, recorder: _Recorder, fake_context: None) -> None:
    # No network: every export download the results view makes is recorded.
    return None


@pytest.mark.parametrize("surface", list(_UIS))
@pytest.mark.parametrize("status", members())
def test_result_shows_its_status_label(ui: None, surface: str, status: str) -> None:
    rendered = _render(_UIS[surface](status))
    shown = label(status)
    assert _shows(rendered, shown), (surface, status)
    others = [m for m in members() if m != status and label(m) not in shown and _shows(rendered, label(m))]
    assert others == [], (surface, status)


@pytest.mark.parametrize("surface", list(_UIS))
def test_result_without_status_shows_unknown(ui: None, surface: str) -> None:
    # A result from a backend before #195, or a payload that dropped the field.
    rendered = _render(_UIS[surface](_ABSENT))
    assert _shows(rendered, label(UNKNOWN))
    assert not _shows(rendered, label(OK))


@pytest.mark.parametrize("surface", list(_UIS))
@pytest.mark.parametrize("value", [v for _, v in HOSTILE_VALUES], ids=[i for i, _ in HOSTILE_VALUES])
def test_result_with_untrusted_status_shows_unknown(ui: None, surface: str, value: Any) -> None:
    rendered = _render(_UIS[surface](value))
    assert _shows(rendered, label(UNKNOWN))
    assert not _shows(rendered, label(OK))
    assert RAW_MARKER not in rendered


@pytest.mark.parametrize("surface", list(_UIS))
def test_result_with_forged_look_alike_shows_unknown(ui: None, surface: str) -> None:
    unknown, ok = label(UNKNOWN), label(OK)
    wrong = []
    variants = forged_member_variants()
    for variant in variants:
        rendered = _render(_UIS[surface](variant))
        if not _shows(rendered, unknown) or _shows(rendered, ok):
            wrong.append(variant.encode("unicode_escape").decode("ascii"))
    print(f"{surface}: forged llm_status variants rendered: {len(variants)}")
    assert wrong == []


# Positive control (green today, must stay green): a result carrying any
# status, or a hostile value, renders without an exception and never echoes the
# raw value onto the page.
@pytest.mark.parametrize("surface", list(_UIS))
@pytest.mark.parametrize(
    "value",
    [*members(), *(v for _, v in _RAW_CASES)],
    ids=[*members(), *(i for i, _ in _RAW_CASES)],
)
def test_result_renders_and_never_echoes_raw_status(ui: None, surface: str, value: Any) -> None:
    rendered = _render(_UIS[surface](value))
    assert RAW_MARKER not in rendered
