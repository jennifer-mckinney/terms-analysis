from app.services.rules import detect_findings


def test_detects_sale_share_and_retention():
    text = (
        "We may sell personal information to third parties for advertising. "
        "We retain data as long as necessary for business purposes."
    )
    findings = detect_findings(text, ["US-CA", "GDPR"])
    categories = {finding.category for finding in findings}
    assert "Sale/Share" in categories
    assert "Retention" in categories
