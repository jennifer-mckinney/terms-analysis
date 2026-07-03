from __future__ import annotations

"""Integration tests for IRP (Impact-Risk-Safeguards) scoring model."""


def test_compute_irp_max_risk():
    from app.services.analyzer import _compute_irp
    score = _compute_irp(5, 5, 0)
    assert score == 0.9  # 0.5*(5/5) + 0.4*(5/5) - 0.3*(0/5) = 0.9


def test_compute_irp_fully_mitigated():
    from app.services.analyzer import _compute_irp
    score = _compute_irp(1, 1, 5)
    assert score == 0.0  # -0.12 → clamped to 0


def test_compute_irp_typical():
    from app.services.analyzer import _compute_irp
    score = _compute_irp(3, 3, 1)
    # 0.5*(3/5) + 0.4*(3/5) - 0.3*(1/5) = 0.30 + 0.24 - 0.06 = 0.48
    assert abs(score - 0.48) < 0.001


def test_compute_irp_sale_share_defaults():
    from app.services.analyzer import _compute_irp
    # Sale/Share: impact=4, likelihood=5, safeguard=0
    score = _compute_irp(4, 5, 0)
    # 0.5*(4/5) + 0.4*(5/5) - 0.3*(0/5) = 0.40 + 0.40 = 0.80
    assert abs(score - 0.80) < 0.001


def test_calculate_risk_score_uses_irp():
    from app.schemas import Finding, Evidence
    from app.services.analyzer import calculate_risk_score
    f = Finding(
        category="Sale/Share", severity="High", confidence=0.9,
        excerpt="test", explanation="test", jurisdictions=["US-CA"],
        evidence=Evidence(line_start=1, line_end=1, legal_basis=["CCPA"]),
        impact=4, likelihood=5, safeguard_score=0, irp_score=0.80,
    )
    score = calculate_risk_score([f])
    assert abs(score - 8.0) < 0.01  # 0.80 * 10


def test_calculate_risk_score_fallback_severity():
    from app.schemas import Finding, Evidence
    from app.services.analyzer import calculate_risk_score
    # No irp_score set → fallback to severity weight
    f = Finding(
        category="Sale/Share", severity="High", confidence=0.9,
        excerpt="test", explanation="test", jurisdictions=["US-CA"],
        evidence=Evidence(line_start=1, line_end=1, legal_basis=["CCPA"]),
    )
    assert f.irp_score is None
    score = calculate_risk_score([f])
    assert abs(score - 8.0) < 0.01  # "High" severity weight 0.8 * 10


def test_calculate_risk_score_mixed_irp_and_severity():
    """Findings with and without irp_score can coexist — uses irp_score where available."""
    from app.schemas import Finding, Evidence
    from app.services.analyzer import calculate_risk_score
    f1 = Finding(
        category="Sale/Share", severity="High", confidence=0.9,
        excerpt="test1", explanation="test", jurisdictions=["US-CA"],
        evidence=Evidence(line_start=1, line_end=1, legal_basis=["CCPA"]),
        irp_score=0.80,
    )
    f2 = Finding(
        category="Retention", severity="Medium", confidence=0.9,
        excerpt="test2", explanation="test", jurisdictions=["GDPR"],
        evidence=Evidence(line_start=2, line_end=2, legal_basis=["GDPR Art. 5"]),
        # No irp_score → uses severity weight 0.5
    )
    score = calculate_risk_score([f1, f2])
    expected = round(((0.80 + 0.50) / 2) * 10, 2)  # 6.5
    assert abs(score - expected) < 0.01


def test_seed_irp_sale_share():
    from app.services.rules import _seed_irp
    impact, likelihood, safeguard, irp = _seed_irp("Sale/Share")
    assert impact == 4
    assert likelihood == 5
    assert safeguard == 0
    assert abs(irp - 0.80) < 0.001


def test_seed_irp_prohibited_ai_rare():
    from app.services.rules import _seed_irp
    impact, likelihood, safeguard, irp = _seed_irp("Prohibited AI")
    assert impact == 5  # catastrophic
    assert likelihood == 1  # extremely rare
    # 0.5*(5/5) + 0.4*(1/5) = 0.50 + 0.08 = 0.58
    assert abs(irp - 0.58) < 0.001


def test_seed_irp_unknown_category():
    from app.services.rules import _seed_irp
    impact, likelihood, safeguard, irp = _seed_irp("Unknown Category XYZ")
    assert impact == 2  # default
    assert likelihood == 3  # default


def test_finding_irp_fields_schema_defaults():
    from app.schemas import Finding, Evidence
    f = Finding(
        category="Test", severity="Low", confidence=0.9,
        excerpt="x", explanation="x", jurisdictions=["US-CA"],
        evidence=Evidence(line_start=1, line_end=1, legal_basis=["test"]),
    )
    assert f.impact == 2
    assert f.likelihood == 3
    assert f.safeguard_score == 0
    assert f.irp_score is None  # not auto-computed in schema


def test_rule_findings_have_irp_seeded():
    """Rule-based detect_findings() should populate IRP fields on all findings."""
    from app.services.rules import detect_findings
    text = "We sell your personal data to third-party advertising partners."
    findings = detect_findings(text, ["US-CA"])
    sale_findings = [f for f in findings if "Sale" in f.category or "Share" in f.category]
    assert len(sale_findings) > 0, "Expected at least one Sale/Share finding"
    for f in sale_findings:
        assert f.irp_score is not None, f"irp_score not set on {f.category} finding"
        assert 1 <= f.impact <= 5
        assert 1 <= f.likelihood <= 5
        assert 0 <= f.safeguard_score <= 5
