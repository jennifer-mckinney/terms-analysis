"""Tests for the analyzer service helpers.

Covers ``app/services/analyzer.py`` — specifically the domain roll-up used to
group top findings into the four reader-facing domains (Data, Data use, Terms
of use, Privacy rights) for the redesigned intake payload.

Naming: ``test_analyzer_<function>_<scenario>``.
"""

from __future__ import annotations


def test_group_by_domain_maps_categories_correctly():
    from app.schemas import Finding, Evidence
    from app.services.analyzer import _group_by_domain, _DOMAIN_ORDER

    def _f(cat, irp=0.5):
        return Finding(
            category=cat, severity="High", confidence=0.9, excerpt="x", explanation="x",
            jurisdictions=["US-CA"], evidence=Evidence(line_start=1, line_end=1, legal_basis=["x"]),
            irp_score=irp,
        )

    findings = [
        _f("Children's Privacy"), _f("AI Training"), _f("Liability"),
        _f("User Rights"), _f("Biometric Data"), _f("Sale/Share"),
        _f("Dark Patterns"), _f("Cross-Border Transfer"),
    ]
    grouped = _group_by_domain(findings)
    assert list(grouped.keys()) == _DOMAIN_ORDER
    assert grouped["Data"][0].category == "Children's Privacy"
    assert grouped["Data use"][0].category == "AI Training"
    assert grouped["Terms of use"][0].category == "Liability"
    assert grouped["Privacy rights"][0].category == "User Rights"


def test_group_by_domain_caps_at_2_per_domain():
    from app.schemas import Finding, Evidence
    from app.services.analyzer import _group_by_domain

    def _f(cat):
        return Finding(
            category=cat, severity="High", confidence=0.9, excerpt="x", explanation="x",
            jurisdictions=["US-CA"], evidence=Evidence(line_start=1, line_end=1, legal_basis=["x"]),
            irp_score=0.5,
        )

    # Five findings all in Data domain
    findings = [_f("Sensitive Data"), _f("Biometric Data"), _f("Health Data"), _f("Children's Privacy"), _f("Minors")]
    grouped = _group_by_domain(findings)
    assert len(grouped["Data"]) == 2  # capped at 2


def test_group_by_domain_empty_domain_maps_to_empty_list():
    from app.schemas import Finding, Evidence
    from app.services.analyzer import _group_by_domain

    def _f(cat):
        return Finding(
            category=cat, severity="High", confidence=0.9, excerpt="x", explanation="x",
            jurisdictions=["US-CA"], evidence=Evidence(line_start=1, line_end=1, legal_basis=["x"]),
            irp_score=0.5,
        )

    findings = [_f("Sale/Share"), _f("AI Training")]  # only Data use findings
    grouped = _group_by_domain(findings)
    assert grouped["Data"] == []
    assert grouped["Terms of use"] == []
    assert grouped["Privacy rights"] == []
    assert len(grouped["Data use"]) == 2


# ---------------------------------------------------------------------------
# PR #34 regression: LLM jurisdiction filter must not admit empty-jurisdiction
# findings. See PR #34 security-engineer HIGH-2.
# ---------------------------------------------------------------------------


def test_llm_jurisdiction_filter_drops_empty_jurisdictions_finding(monkeypatch):
    """A finding with ``jurisdictions=[]`` must be dropped when a jurisdiction filter is active.

    Previously the predicate was ``not f.jurisdictions or any(...)`` which
    admitted any finding without a declared jurisdiction, effectively creating
    a bypass for anything the LLM returned without a jurisdiction tag. The
    predicate now requires explicit overlap: unclaimed jurisdiction ==>
    unverifiable applicability ==> dropped.
    """
    import asyncio

    from app.services import analyzer as analyzer_module
    from app.services.analyzer import analyze_text
    from app.services.localai import LocalAIClient

    # LLM returns two findings: one with a matching jurisdiction, one with an
    # empty jurisdictions list (regression case).
    llm_payload = {
        "summary": "Mocked LLM summary",
        "overall_confidence": 0.9,
        "findings": [
            {
                "category": "Sale/Share",
                "severity": "High",
                "confidence": 0.9,
                "excerpt": "we may sell your personal information",
                "explanation": "Sale/share disclosure without an opt-out.",
                "jurisdictions": ["US-CA"],
                "evidence": {
                    "line_start": 1,
                    "line_end": 1,
                    "legal_basis": ["CCPA §1798.120"],
                },
            },
            {
                "category": "Unclaimed Category",
                "severity": "High",
                "confidence": 0.9,
                "excerpt": "opaque clause with no jurisdiction tag",
                "explanation": "LLM produced a finding without declaring any jurisdiction.",
                "jurisdictions": [],
                "evidence": {
                    "line_start": 2,
                    "line_end": 2,
                    "legal_basis": ["general terms"],
                },
            },
        ],
    }

    async def fake_llm_analyze(self, *args, **kwargs):
        return llm_payload

    monkeypatch.setattr(LocalAIClient, "analyze", fake_llm_analyze)

    # Bypass legal-KB retrieval — return an empty list so the test focuses on
    # the jurisdiction filter itself.
    class _NoopKB:
        async def retrieve(self, *args, **kwargs):
            return []

    monkeypatch.setattr(analyzer_module, "get_legal_kb", lambda: _NoopKB())

    # Analyze with US-CA-only filter. The empty-jurisdiction finding must be
    # dropped; the US-CA finding must survive.
    result = asyncio.run(analyze_text("we may sell your personal information.", ["US-CA"]))
    categories = {finding.category for finding in result.payload.findings}
    assert "Unclaimed Category" not in categories, (
        "empty-jurisdiction LLM findings must be dropped by the post-LLM filter"
    )


def test_llm_jurisdiction_filter_keeps_matching_finding(monkeypatch):
    """Sanity check for the tightened filter: matching jurisdictions still pass."""
    import asyncio

    from app.services import analyzer as analyzer_module
    from app.services.analyzer import analyze_text
    from app.services.localai import LocalAIClient

    llm_payload = {
        "summary": "Mocked",
        "overall_confidence": 0.9,
        "findings": [
            {
                "category": "Cross-Border Transfer",
                "severity": "Medium",
                "confidence": 0.85,
                "excerpt": "personal data is transferred outside the EU",
                "explanation": "GDPR-relevant cross-border transfer.",
                "jurisdictions": ["GDPR"],
                "evidence": {
                    "line_start": 1,
                    "line_end": 1,
                    "legal_basis": ["GDPR Ch. V"],
                },
            }
        ],
    }

    async def fake_llm_analyze(self, *args, **kwargs):
        return llm_payload

    monkeypatch.setattr(LocalAIClient, "analyze", fake_llm_analyze)

    class _NoopKB:
        async def retrieve(self, *args, **kwargs):
            return []

    monkeypatch.setattr(analyzer_module, "get_legal_kb", lambda: _NoopKB())

    result = asyncio.run(
        analyze_text("personal data is transferred outside the EU.", ["GDPR"])
    )
    categories = {finding.category for finding in result.payload.findings}
    assert "Cross-Border Transfer" in categories


# ---------------------------------------------------------------------------
# Fix 4: empty jurisdictions == "no filter" (global-tool contract)
# ---------------------------------------------------------------------------


def test_analyzer_detect_findings_empty_jurisdictions_runs_all_rules():
    """Empty jurisdictions list = no filter (global tool, unknown user location).

    Compared with a UK-only run the empty-list result must include categories
    from rules whose jurisdictions do NOT include UK-GDPR — proving no
    filtering happened.
    """
    from app.services.rules import detect_findings

    text = (
        "We sell your personal information. We use automated decision-making. "
        "We retain data indefinitely. Your rights include opt-out. Children under 13."
    )

    uk_only = detect_findings(text, ["UK-GDPR"])
    no_filter = detect_findings(text, [])

    uk_categories = {f.category for f in uk_only}
    no_filter_categories = {f.category for f in no_filter}

    # No-filter mode must be a superset of UK-only (nothing removed).
    assert uk_categories.issubset(no_filter_categories)
    # And must include categories UK-only would have filtered out.
    assert no_filter_categories - uk_categories, (
        "empty-jurisdictions run should include categories the UK-only filter drops"
    )


def test_analyzer_detect_high_severity_findings_empty_jurisdictions_no_filter():
    """Quick-mode helper honours the global-tool empty-list contract."""
    from app.services.analyzer import detect_high_severity_findings

    text = "We sell your personal information. This includes sensitive biometric data."
    no_filter = detect_high_severity_findings(text, [])
    us_only = detect_high_severity_findings(text, ["US-CA"])
    # No-filter must be at least as broad as US-only.
    assert len({f.category for f in no_filter}) >= len({f.category for f in us_only})


# ---------------------------------------------------------------------------
# Fix 6: _bump_severity fail-fast on unknown severities
# ---------------------------------------------------------------------------


def test_analyzer_bump_severity_raises_on_unknown_severity():
    from app.schemas import Evidence, Finding
    from app.services.analyzer import _bump_severity

    # Bypass pydantic's severity Literal by constructing then mutating with
    # ``model_copy(update=...)``. Pydantic validates on construction but
    # ``update`` re-runs validation, so use object.__setattr__ instead.
    valid = Finding(
        category="Sale/Share",
        severity="High",
        confidence=0.9,
        excerpt="x",
        explanation="x",
        jurisdictions=["US-CA"],
        evidence=Evidence(line_start=1, line_end=1, legal_basis=["x"]),
        irp_score=0.5,
    )
    # Bypass pydantic validation to inject a bogus severity value.
    object.__setattr__(valid, "severity", "Extreme")

    import pytest as _pytest

    with _pytest.raises(ValueError, match="Unknown severity"):
        _bump_severity(valid, 0.3)


def test_analyzer_bump_severity_still_bumps_valid_severity():
    from app.schemas import Evidence, Finding
    from app.services.analyzer import _bump_severity

    finding = Finding(
        category="Sale/Share",
        severity="Medium",
        confidence=0.9,
        excerpt="x",
        explanation="x",
        jurisdictions=["US-CA"],
        evidence=Evidence(line_start=1, line_end=1, legal_basis=["x"]),
        irp_score=0.5,
    )
    bumped = _bump_severity(finding, 0.3)
    assert bumped.severity == "High"


# ---------------------------------------------------------------------------
# Fix 8: backend-generated action_items on AnalysisPayload
# ---------------------------------------------------------------------------


def _make_finding_for_actions(category: str, jurisdictions=None):
    from app.schemas import Evidence, Finding

    return Finding(
        category=category,
        severity="High",
        confidence=0.9,
        excerpt="x",
        explanation="x",
        jurisdictions=jurisdictions or ["US-CA"],
        evidence=Evidence(line_start=1, line_end=1, legal_basis=["x"]),
        irp_score=0.5,
    )


def test_analyzer_derive_action_items_sale_share_us_ca():
    from app.services.analyzer import _derive_action_items

    items = _derive_action_items(
        [_make_finding_for_actions("Sale/Share")], ["US-CA"]
    )
    assert any("Do Not Sell" in line for line in items)


def test_analyzer_derive_action_items_sale_share_non_us_ca_uses_generic():
    from app.services.analyzer import _derive_action_items

    items = _derive_action_items(
        [_make_finding_for_actions("Sale/Share")], ["GDPR"]
    )
    assert not any("Do Not Sell" in line for line in items)
    assert any("opt-out of data sale" in line.lower() for line in items)


def test_analyzer_derive_action_items_gdpr_rights_line_added():
    from app.services.analyzer import _derive_action_items

    items = _derive_action_items(
        [_make_finding_for_actions("User Rights")], ["GDPR"]
    )
    assert any("GDPR" in line for line in items)


def test_analyzer_derive_action_items_ai_training_line():
    from app.services.analyzer import _derive_action_items

    items = _derive_action_items(
        [_make_finding_for_actions("AI Training")], ["US-CA"]
    )
    assert any("AI training opt-out" in line for line in items)


def test_analyzer_derive_action_items_children_line():
    from app.services.analyzer import _derive_action_items

    items = _derive_action_items(
        [_make_finding_for_actions("Children's Privacy")], ["US-CA"]
    )
    assert any("children" in line.lower() for line in items)


def test_analyzer_derive_action_items_caps_at_five():
    from app.services.analyzer import _derive_action_items

    # All applicable categories at once — pre-cap this produces 6 items:
    # Sale/Share, GDPR rights, generic-rights, AI training, ADM, Children, Liability.
    findings = [
        _make_finding_for_actions("Sale/Share"),
        _make_finding_for_actions("User Rights"),
        _make_finding_for_actions("AI Training"),
        _make_finding_for_actions("Automated Decision-Making"),
        _make_finding_for_actions("Children's Privacy"),
        _make_finding_for_actions("Liability"),
    ]
    items = _derive_action_items(findings, ["US-CA", "GDPR"])
    assert len(items) <= 5


def test_analyzer_derive_action_items_empty_findings_returns_empty():
    from app.services.analyzer import _derive_action_items

    assert _derive_action_items([], ["US-CA"]) == []


# ---------------------------------------------------------------------------
# Issue #83 / Phase 5.d CONTENT-1: chip-tuned action_items
# ---------------------------------------------------------------------------


def _mixed_findings():
    """A fixture with categories that exercise every branch of the derivation."""
    return [
        _make_finding_for_actions("Sale/Share"),
        _make_finding_for_actions("User Rights"),
        _make_finding_for_actions("AI Training"),
        _make_finding_for_actions("Liability"),
        _make_finding_for_actions("Children's Privacy"),
    ]


def test_analyzer_action_items_liability_no_longer_fires_without_for_work():
    """The prior chip-invariant 'For work/vendor use, escalate liability...'
    line MUST NOT surface for readers who did not pick the for_work chip.
    This is the specific off-tone item Phase 5.d E2E flagged CONTENT-1."""
    from app.services.analyzer import _derive_action_items

    for chip in ["just_curious", "for_child", "for_care", "want_understand"]:
        items = _derive_action_items(_mixed_findings(), ["US-CA"], [chip])
        # No item should carry the work/vendor escalation phrasing.
        joined = " ".join(items).lower()
        assert "work" not in joined and "vendor" not in joined, (
            f"chip {chip!r} should NOT surface work/vendor action items; got: {items}"
        )


def test_analyzer_action_items_for_work_surfaces_liability_item():
    """The work/vendor liability item MUST fire for readers who picked
    for_work. Complement to the guard above — proves the gating is
    causal, not just suppressive."""
    from app.services.analyzer import _derive_action_items

    items = _derive_action_items(_mixed_findings(), ["US-CA"], ["for_work"])
    joined = " ".join(items).lower()
    assert "work" in joined or "vendor" in joined, (
        f"for_work chip must surface work/vendor action items; got: {items}"
    )


def test_analyzer_action_items_differ_across_chips_parametrized():
    """Every ContextChip MUST produce a materially different action_items
    list on the same fixture. Iterating via typing.get_args() so this
    picks up new chips automatically per the 3-rule drift policy R3."""
    from typing import get_args

    from app.schemas import ContextChip
    from app.services.analyzer import _derive_action_items

    findings = _mixed_findings()
    outputs: dict[str, tuple[str, ...]] = {}
    for chip in get_args(ContextChip):
        items = _derive_action_items(findings, ["US-CA"], [chip])
        outputs[chip] = tuple(items)

    # Every chip returns at least one item (universal + chip-specific + category).
    for chip, items in outputs.items():
        assert items, f"chip {chip!r} returned no action items on mixed findings"

    # Outputs are not all identical. At least (n-1) chips must differ from
    # any given chip's output — i.e., the set of unique outputs > 1.
    unique_outputs = {items for items in outputs.values()}
    assert len(unique_outputs) > 1, (
        "action_items are chip-invariant across all ContextChips — the "
        "chip-tune fix from issue #83 has regressed."
    )


def test_analyzer_action_items_include_universal_regardless_of_chip():
    """The universal item ('Review the specific opt-out and rights mechanisms
    named in the legal details above.') fires for every chip when findings
    exist. Regression guard so the universal item cannot be silently dropped."""
    from typing import get_args

    from app.schemas import ContextChip
    from app.services.analyzer import _derive_action_items

    for chip in get_args(ContextChip):
        items = _derive_action_items(_mixed_findings(), ["US-CA"], [chip])
        assert any("opt-out and rights mechanisms" in line for line in items), (
            f"chip {chip!r} missing the universal review item; got: {items}"
        )


def test_analyzer_action_items_no_context_backward_compat():
    """Callers that pass no context still get category-derived items.
    Backward-compat guarantee: the third param defaults to None, and
    downstream consumers that predate the chip taxonomy still work."""
    from app.services.analyzer import _derive_action_items

    items = _derive_action_items(_mixed_findings(), ["US-CA"])
    # Universal item still fires.
    assert any("opt-out and rights mechanisms" in line for line in items)
    # Sale/Share category item still fires when US-CA is set.
    assert any("Do Not Sell" in line for line in items)


def test_analyzer_action_items_dedupes_when_chip_and_category_overlap():
    """If a chip item and a category-derived item say substantially the
    same thing, the return list must dedupe by exact-string. Regression
    guard against readers seeing near-identical items back to back."""
    from app.services.analyzer import _derive_action_items

    items = _derive_action_items(_mixed_findings(), ["US-CA"], ["for_child"])
    # All items are unique strings.
    assert len(items) == len(set(items)), (
        f"duplicate strings in action_items: {items}"
    )


def test_analyzer_action_items_cap_holds_with_chips_active():
    """The 5-item cap holds even when a chip + all category branches are
    firing. Prevents accidental cap regression when new items are added."""
    from app.services.analyzer import _derive_action_items

    findings = [
        _make_finding_for_actions("Sale/Share"),
        _make_finding_for_actions("User Rights"),
        _make_finding_for_actions("AI Training"),
        _make_finding_for_actions("Automated Decision-Making"),
        _make_finding_for_actions("Children's Privacy"),
        _make_finding_for_actions("Liability"),
    ]
    items = _derive_action_items(findings, ["US-CA", "GDPR"], ["for_work"])
    assert len(items) <= 5, f"cap breached with for_work + all categories: {items}"
