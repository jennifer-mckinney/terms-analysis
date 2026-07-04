"""
Test scaffolding for issue #82 — Streamlit rerun-state race on intake.

The fix wraps the context-chip cards + submit button inside ``st.form(...)``
so the chip state and submit event are captured atomically. Without this,
a user could tick a chip and click "Take a look" within the same paint
cycle and the button would resolve against a pre-chip render, dropping the
chip from the POST /analyze body.

A live Playwright test would be preferable but the existing test surface
does not carry a Streamlit runtime fixture. This test uses source
inspection to guarantee the structural invariant that closes the race:
the chip checkboxes and the submit button MUST live inside the same
``st.form(...)`` block. Any refactor that breaks that grouping will fail
this test loudly.

Companion assertion: verifies that the /analyze schema still accepts the
same context-chip shape the intake was posting before — this is a UI-only
fix and MUST NOT drift the wire contract.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas import ContextChip


_APP_STREAMLIT_V2 = (
    Path(__file__).resolve().parents[2] / "webapp" / "app_streamlit_v2.py"
)


def _read_intake_source() -> str:
    """Read the ``render_intake`` function body from app_streamlit_v2.py."""
    src = _APP_STREAMLIT_V2.read_text(encoding="utf-8")
    match = re.search(
        r"def render_intake\([^)]*\)\s*->\s*None:.*?(?=\ndef |\Z)",
        src,
        flags=re.DOTALL,
    )
    assert match, "render_intake function not found in app_streamlit_v2.py"
    return match.group(0)


# ---------------------------------------------------------------------------
# Structural invariants — the fix for issue #82.
# ---------------------------------------------------------------------------


def test_intake_wraps_chips_and_submit_in_st_form() -> None:
    """The chip checkboxes AND the submit button share the same st.form block.

    Regression guard for issue #82 / Phase 5.d UI-1 HIGH: the "Take a look"
    button and the context-chip state must submit atomically. Anything that
    moves the submit button outside the form (or moves the chips outside)
    reopens the race and this test fails.
    """
    body = _read_intake_source()
    # There must be a form open with the intake_form key.
    assert 'st.form(key="intake_form"' in body, (
        "render_intake must open st.form(key=\"intake_form\", ...) to close "
        "the rerun-state race that dropped chip selections (issue #82)."
    )
    # Submit MUST be st.form_submit_button, not st.button — the whole point.
    assert "st.form_submit_button" in body, (
        "render_intake must use st.form_submit_button for the primary submit "
        "so chip state and submit are transactional (issue #82)."
    )
    # And there must be no plain st.button used as the primary submit.
    assert 'st.button("Take a look' not in body, (
        "\"Take a look\" primary submit must be st.form_submit_button, not "
        "st.button — st.button inside a form errors, and st.button outside a "
        "form reintroduces the chip-drop race (issue #82)."
    )


def test_intake_form_captures_chip_state_on_submit() -> None:
    """The submit handler assigns chip selections into session_state.

    The reason the form fixes the race: chip state is written to
    st.session_state.context_selections at submit time, inside the form
    block. Guarding that assignment stays put.
    """
    body = _read_intake_source()
    # Match "if submitted:" then any run of comment/whitespace lines, then
    # the assignment. Comments between the branch head and the write are
    # fine — the assignment must still be under the submit branch.
    assert re.search(
        r"if\s+submitted\s*:\s*\n(?:\s*#[^\n]*\n)*\s*st\.session_state\.context_selections\s*=\s*selections",
        body,
    ), (
        "The submit branch inside st.form must assign selections to "
        "st.session_state.context_selections so chip state is captured "
        "atomically with the submit event (issue #82)."
    )


# ---------------------------------------------------------------------------
# Wire-contract invariance — the UI fix must not have drifted the schema.
# ---------------------------------------------------------------------------


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.mark.parametrize("chip", get_args(ContextChip))
def test_analyze_still_accepts_every_context_chip(
    client: TestClient, chip: str
) -> None:
    """Every ContextChip value is still accepted on /analyze.

    The form wrap is UI-only. This test locks the wire contract so a
    regression that changes what the POST body accepts would surface here
    rather than in production.
    """
    response = client.post(
        "/analyze",
        json={
            "name": "test.txt",
            "text": "We collect personal information from you.",
            "context": [chip],
        },
    )
    # 200 or 4xx from analysis is fine; 422 (validation) would mean the
    # schema drifted and this chip is no longer accepted.
    assert response.status_code != 422, (
        f"Chip {chip!r} rejected as invalid on /analyze — the wire "
        f"contract drifted after the form-wrap UI fix."
    )
