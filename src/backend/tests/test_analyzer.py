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
