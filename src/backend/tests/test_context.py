"""Tests for the context-chip tuning service.

Covers ``app/services/context.py`` — the reader-intent layer added in
Phase 1 (issue #19). Verifies the resolution priority when multiple chips
are selected, the category-weight ordering, and the verdict copy overrides.

Naming: ``test_context_<function>_<scenario>``.
"""

from __future__ import annotations

import pytest

from app.schemas import Evidence, Finding
from app.services.context import (
    apply_category_weights,
    resolve_context,
    verdict_headline,
    verdict_label,
)


def _make_finding(
    *,
    category: str,
    severity: str = "Medium",
    irp_score: float = 0.4,
    confidence: float = 0.9,
) -> Finding:
    return Finding(
        category=category,
        severity=severity,
        confidence=confidence,
        excerpt="excerpt",
        explanation="explanation",
        jurisdictions=["US-CA"],
        evidence=Evidence(line_start=1, line_end=1, legal_basis=["basis"]),
        impact=3,
        likelihood=3,
        safeguard_score=0,
        irp_score=irp_score,
    )


# ---------------------------------------------------------------------------
# resolve_context
# ---------------------------------------------------------------------------


class TestResolveContext:
    def test_context_resolve_context_empty_defaults_to_want_understand(self):
        assert resolve_context([]) == "want_understand"

    def test_context_resolve_context_single_returns_that_chip(self):
        assert resolve_context(["for_child"]) == "for_child"
        assert resolve_context(["for_care"]) == "for_care"
        assert resolve_context(["just_curious"]) == "just_curious"

    def test_context_resolve_context_child_beats_care(self):
        # for_child > for_care
        assert resolve_context(["for_care", "for_child"]) == "for_child"

    def test_context_resolve_context_child_beats_everything(self):
        assert (
            resolve_context(["just_curious", "want_understand", "for_care", "for_child"])
            == "for_child"
        )

    def test_context_resolve_context_care_beats_want_understand(self):
        assert resolve_context(["want_understand", "for_care"]) == "for_care"

    def test_context_resolve_context_want_understand_beats_curious(self):
        assert resolve_context(["just_curious", "want_understand"]) == "want_understand"


# ---------------------------------------------------------------------------
# apply_category_weights
# ---------------------------------------------------------------------------


class TestApplyCategoryWeights:
    def test_context_apply_weights_empty_findings_returns_empty(self):
        assert apply_category_weights([], ["for_child"]) == []

    def test_context_apply_weights_no_context_preserves_irp_order(self):
        findings = [
            _make_finding(category="Data Retention", irp_score=0.3),
            _make_finding(category="Children's Privacy", irp_score=0.6),
            _make_finding(category="Data Sale / Sharing", irp_score=0.5),
        ]
        result = apply_category_weights(findings, [])
        # No context -> highest irp_score comes first (Children's Privacy at 0.6).
        assert result[0].category == "Children's Privacy"
        assert result[-1].category == "Data Retention"

    def test_context_apply_weights_for_child_boosts_childrens_privacy(self):
        # Tier-first sort: Children's Privacy is a signature category (weight 3.0)
        # under for_child, so it outright beats Data Sale / Sharing (2.0) and
        # Retention (baseline 1.0) regardless of IRP.
        findings = [
            _make_finding(category="Retention", irp_score=0.5),
            _make_finding(category="Data Sale / Sharing", irp_score=0.6),
            _make_finding(category="Children's Privacy", irp_score=0.3),
        ]
        result = apply_category_weights(findings, ["for_child"])
        # Children's Privacy leads (weight 3.0) → Data Sale / Sharing
        # (weight 2.0) → Retention (baseline 1.0).
        assert result[0].category == "Children's Privacy"
        assert result[1].category == "Data Sale / Sharing"
        assert result[-1].category == "Retention"

    def test_context_apply_weights_for_care_boosts_dark_patterns(self):
        findings = [
            _make_finding(category="Retention", irp_score=0.5),
            _make_finding(category="Dark Patterns", irp_score=0.3),
        ]
        result = apply_category_weights(findings, ["for_care"])
        # Dark Patterns is a signature category (weight 3.0) → beats Retention
        # (baseline 1.0) even though its IRP is lower.
        assert result[0].category == "Dark Patterns"

    def test_context_apply_weights_does_not_mutate_irp_score(self):
        finding = _make_finding(category="Children's Privacy", irp_score=0.3)
        result = apply_category_weights([finding], ["for_child"])
        # Same object, irp_score unchanged — only ordering is affected.
        assert result[0].irp_score == 0.3

    def test_context_apply_weights_handles_missing_irp_score(self):
        # Legacy fallback path: severity-based baseline when irp_score is None.
        finding = Finding(
            category="Children's Privacy",
            severity="High",
            confidence=0.9,
            excerpt="excerpt",
            explanation="explanation",
            jurisdictions=["US-CA"],
            evidence=Evidence(line_start=1, line_end=1, legal_basis=["basis"]),
            impact=3,
            likelihood=3,
            safeguard_score=0,
            irp_score=None,
        )
        # Should not raise — just applies the weight to the fallback.
        result = apply_category_weights([finding], ["for_child"])
        assert result == [finding]


# ---------------------------------------------------------------------------
# verdict_headline
# ---------------------------------------------------------------------------


class TestVerdictHeadline:
    @pytest.mark.parametrize(
        "context,action,expected_substr",
        [
            ([], "Go", "clearer than most"),
            ([], "Review", "worth understanding"),
            ([], "Stop", "against the reader"),
            (["for_child"], "Go", "For a child"),
            (["for_child"], "Stop", "not be built with children"),
            (["for_care"], "Go", "someone being helped"),
            (["for_care"], "Review", "explaining"),
            (["for_care"], "Stop", "take advantage"),
            (["just_curious"], "Go", "relatively clear"),
            (["just_curious"], "Review", "worth noting"),
            (["just_curious"], "Stop", "notable"),
        ],
    )
    def test_context_verdict_headline_matches_context(self, context, action, expected_substr):
        headline = verdict_headline(context, action)
        assert expected_substr.lower() in headline.lower()

    def test_context_verdict_headline_returns_different_copy_per_context(self):
        # Same action_readiness should still produce distinct copy per context.
        go_child = verdict_headline(["for_child"], "Go")
        go_curious = verdict_headline(["just_curious"], "Go")
        go_care = verdict_headline(["for_care"], "Go")
        assert go_child != go_curious
        assert go_child != go_care
        assert go_care != go_curious

    def test_context_verdict_headline_unknown_action_falls_back_to_review(self):
        # Guard rail: unexpected action_readiness value should not raise.
        headline = verdict_headline(["for_child"], "Nonsense")
        assert isinstance(headline, str) and headline


# ---------------------------------------------------------------------------
# verdict_label
# ---------------------------------------------------------------------------


class TestVerdictLabel:
    @pytest.mark.parametrize(
        "context,action,expected",
        [
            ([], "Go", "Reasonable"),
            ([], "Review", "Worth a closer read"),
            ([], "Stop", "Serious concerns"),
            (["for_child"], "Go", "Reasonable for a child"),
            (["for_child"], "Stop", "Not built for children"),
            (["for_care"], "Review", "Worth reviewing together"),
            (["for_care"], "Stop", "Concerning to share"),
            (["just_curious"], "Go", "Clear"),
            (["just_curious"], "Review", "Worth noting"),
            (["just_curious"], "Stop", "Notable practices"),
        ],
    )
    def test_context_verdict_label_matches_context(self, context, action, expected):
        assert verdict_label(context, action) == expected

    def test_context_verdict_label_returns_different_copy_per_context(self):
        # Same action, different context → different label.
        stop_child = verdict_label(["for_child"], "Stop")
        stop_care = verdict_label(["for_care"], "Stop")
        stop_default = verdict_label([], "Stop")
        assert stop_child != stop_care
        assert stop_child != stop_default
        assert stop_care != stop_default

    def test_context_verdict_label_priority_child_wins(self):
        # for_child + for_care selected → for_child copy applies.
        label = verdict_label(["for_care", "for_child"], "Stop")
        assert label == "Not built for children"


# ---------------------------------------------------------------------------
# Tier-first sort semantics + for_work + sum-cap merger + baseline behaviour
# ---------------------------------------------------------------------------


def test_apply_category_weights_context_leads_over_irp():
    from app.schemas import Finding, Evidence
    from app.services.context import apply_category_weights

    high_irp_baseline = Finding(
        category="Sale/Share", severity="High", confidence=0.9,
        excerpt="x", explanation="x", jurisdictions=["US-CA"],
        evidence=Evidence(line_start=1, line_end=1, legal_basis=["x"]),
        irp_score=0.80,
    )
    low_irp_boosted = Finding(
        category="Children's Privacy", severity="Low", confidence=0.9,
        excerpt="x", explanation="x", jurisdictions=["US-CA"],
        evidence=Evidence(line_start=1, line_end=1, legal_basis=["x"]),
        irp_score=0.25,
    )
    result = apply_category_weights([high_irp_baseline, low_irp_boosted], ["for_child"])
    assert result[0].category == "Children's Privacy"


def test_apply_category_weights_sum_cap_merger():
    from app.services.context import _merge_weights
    # Sale/Share appears in both for_child (2.0) and for_work (2.2). Sum = 4.2, capped at 3.0.
    merged = _merge_weights(["for_child", "for_work"])
    assert merged["Sale/Share"] == 3.0
    # Liability is only in for_work — stays at 3.0.
    assert merged["Liability"] == 3.0


def test_apply_category_weights_no_financial_data_axis():
    from app.services.context import CATEGORY_WEIGHTS
    for chip, weights in CATEGORY_WEIGHTS.items():
        assert "Financial Data" not in weights, f"Financial Data should not be in {chip} weights"


def test_apply_category_weights_baseline_context_uses_irp_only():
    from app.schemas import Finding, Evidence
    from app.services.context import apply_category_weights
    a = Finding(category="Sale/Share", severity="High", confidence=0.9, excerpt="x", explanation="x",
                jurisdictions=["US-CA"], evidence=Evidence(line_start=1, line_end=1, legal_basis=["x"]),
                irp_score=0.8)
    b = Finding(category="Children's Privacy", severity="Low", confidence=0.9, excerpt="x", explanation="x",
                jurisdictions=["US-CA"], evidence=Evidence(line_start=1, line_end=1, legal_basis=["x"]),
                irp_score=0.3)
    for ctx in ["want_understand", "just_curious"]:
        result = apply_category_weights([a, b], [ctx])
        assert result[0].category == "Sale/Share"  # baseline: IRP wins


def test_resolve_context_for_work_priority():
    from app.services.context import resolve_context
    assert resolve_context(["for_work", "just_curious"]) == "for_work"
    assert resolve_context(["for_child", "for_work"]) == "for_child"  # child still wins
    assert resolve_context(["for_care", "for_work"]) == "for_care"    # care still wins


def test_verdict_for_work():
    from app.services.context import verdict_headline, verdict_label
    assert "work use" in verdict_headline(["for_work"], "Review").lower()
    assert verdict_label(["for_work"], "Stop") == "Not vendor-safe as written"


# ---------------------------------------------------------------------------
# Fix 5: canonical categories — every CATEGORY_WEIGHTS key must be recognised
# by schemas.CATEGORIES. Module-load validation already guards this at import,
# but pin it here so refactors surface the intent.
# ---------------------------------------------------------------------------


def test_context_category_weights_keys_are_all_known_categories():
    from app.schemas import CATEGORIES
    from app.services.context import CATEGORY_WEIGHTS

    unknown = {
        cat
        for chip_weights in CATEGORY_WEIGHTS.values()
        for cat in chip_weights.keys()
        if cat not in CATEGORIES
    }
    assert unknown == set(), (
        f"CATEGORY_WEIGHTS references unknown categories: {sorted(unknown)}"
    )


def test_context_domain_map_keys_are_all_known_categories():
    from app.schemas import CATEGORIES
    from app.services.analyzer import _DOMAIN_MAP

    unknown = {cat for cat in _DOMAIN_MAP.keys() if cat not in CATEGORIES}
    assert unknown == set(), (
        f"_DOMAIN_MAP references unknown categories: {sorted(unknown)}"
    )
