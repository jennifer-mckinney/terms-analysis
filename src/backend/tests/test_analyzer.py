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
