"""
Test suite for child context finding simplification.

Tests the simplify_finding_for_context function that translates legal jargon
to kindergarten-teacher-level language for parents reviewing policies for their children.
"""
import sys
from pathlib import Path

# Add webapp directory to path so we can import the streamlit app module
webapp_dir = Path(__file__).parent.parent / "src" / "webapp"
sys.path.insert(0, str(webapp_dir))

# Import the function (we'll need to extract it or mock streamlit)
import re


def simplify_finding_for_context(finding: dict, context_selections: list[str]) -> dict:
    """Copied from app_streamlit_v2.py for testing."""
    if not context_selections or "for_child" not in context_selections:
        return finding

    finding_copy = finding.copy()
    explanation = str(finding.get("explanation") or "")

    replacements = [
        (
            r"(?i)Special protections required for children's personal information under COPPA \(under 13\) and FERPA",
            "There's a law that says websites have to be extra careful with kids' information (kids under 13). They need special permission before collecting things like age or location.",
        ),
        (
            r"(?i)Special protections required for children's personal information under COPPA",
            "There's a law that says websites have to be extra careful with kids' information (kids under 13). They need special permission before collecting things like age or location.",
        ),
        (
            r"(?i)Using user data to train AI/ML models requires clear disclosure and (?:in many jurisdictions )?an? opt-out right",
            "This service might teach its AI system using your information. The law says they should tell you if they do this, and let you say 'no thanks'.",
        ),
        (
            r"(?i)Using user data to train AI/ML models requires clear disclosure",
            "This service might teach its AI system using your information. The law says they should tell you if they do this.",
        ),
        (
            r"(?i)Children's data requires special protections and disclosures",
            "Kids' information needs extra safety - it's like keeping their data in a special lock.",
        ),
        (
            r"(?i)(?:Using|Tracking|Collecting) (?:user|personal) data for (?:marketing|advertising|analytics) purposes",
            "This company watches what you do so they can show you better ads.",
        ),
        (
            r"(?i)(?:Personal|user) data (?:may be )?(?:retained|stored|kept) for [^.]*(?:marketing|business|commercial) purposes",
            "This company keeps your information to use it for ads and other business reasons.",
        ),
        (
            r"(?i)(?:Personal|user) data (?:may be |is )?(?:shared|disclosed|provided) to third.?parties for [^.]*(?:marketing|advertising|commercial) purposes",
            "This company shares your information with other companies so they can send you ads too.",
        ),
        (
            r"(?i)(?:Personal|user) data (?:may be |is )?(?:shared|disclosed|provided) to third.?parties",
            "This company shares your information with other companies.",
        ),
        (
            r"(?i)(?:behavioral|user|activity|usage) profiling (?:for )?(?:targeting|analytics|personalization)",
            "This service tracks what you do to figure out what you like.",
        ),
        (
            r"(?i)(?:location|geolocation) data (?:is )?(?:collected|tracked|monitored)",
            "This service can see where you are.",
        ),
        (
            r"(?i)(?:facial recognition|biometric|face scan|fingerprint) (?:data )?(?:collection|processing|use)",
            "This service can recognize your face or fingerprint.",
        ),
        (
            r"(?i)(?:right to deletion|right to be forgotten|erasure right) may (?:be limited|be restricted|not apply)",
            "You might not be able to ask them to delete your information.",
        ),
        (
            r"(?i)(?:right to deletion|right to be forgotten|erasure right)",
            "You can ask them to delete your information.",
        ),
        (
            r"(?i)automated decision.?making (?:based|relying) on (?:personal|user) data",
            "A computer decides things about you based on your information.",
        ),
        (
            r"(?i)(?:opt.?out|negative) consent",
            "They start doing something unless you say stop.",
        ),
        (
            r"(?i)(?:opt.?in|affirmative|explicit) consent",
            "They ask permission first before doing something.",
        ),
        (
            r"(?i)minors? (?:under |aged? )?(?:\d+)",
            "kids under that age",
        ),
    ]

    for pattern, replacement in replacements:
        explanation = re.sub(pattern, replacement, explanation)

    if explanation == str(finding.get("explanation") or ""):
        jargon_markers = ["GDPR", "CCPA", "regulation", "legislation", "statute", "compliance"]
        if any(marker in explanation for marker in jargon_markers):
            explanation = re.sub(
                r"(?i)(?:This|The) (?:service|company|website)",
                "This service",
                explanation,
            )

    finding_copy["explanation"] = explanation
    return finding_copy


def test_coppa_translation():
    """Test COPPA/FERPA legal jargon is translated to simple English."""
    finding = {
        "explanation": "Special protections required for children's personal information under COPPA (under 13) and FERPA (education records).",
        "category": "Data Collection",
    }
    result = simplify_finding_for_context(finding, ["for_child"])
    assert "law that says websites have to be extra careful" in result["explanation"]
    assert "kids under 13" in result["explanation"]
    assert "COPPA" not in result["explanation"]
    assert "FERPA" not in result["explanation"]


def test_ai_ml_training_translation():
    """Test AI/ML training disclosure is simplified."""
    finding = {
        "explanation": "Using user data to train AI/ML models requires clear disclosure and in many jurisdictions an opt-out right.",
        "category": "AI/ML",
    }
    result = simplify_finding_for_context(finding, ["for_child"])
    assert "teach its AI system" in result["explanation"]
    assert "tell you if they do this" in result["explanation"]
    assert "AI/ML" not in result["explanation"]


def test_no_simplification_without_context():
    """Test that findings are not simplified when for_child context is not selected."""
    finding = {
        "explanation": "Special protections required for children's personal information under COPPA (under 13) and FERPA (education records).",
        "category": "Data Collection",
    }
    result = simplify_finding_for_context(finding, ["want_understand"])
    assert result["explanation"] == finding["explanation"]


def test_no_simplification_with_empty_context():
    """Test that findings are not simplified when context list is empty."""
    finding = {
        "explanation": "Special protections required for children's personal information under COPPA (under 13) and FERPA (education records).",
        "category": "Data Collection",
    }
    result = simplify_finding_for_context(finding, [])
    assert result["explanation"] == finding["explanation"]


def test_multiple_replacements():
    """Test that multiple replacement patterns can apply to same finding."""
    finding = {
        "explanation": "Children's data requires special protections and disclosures. Using user data to train AI/ML models requires clear disclosure.",
        "category": "Data Collection",
    }
    result = simplify_finding_for_context(finding, ["for_child"])
    assert "lock" in result["explanation"]  # From children's data replacement
    assert "AI system" in result["explanation"]  # From ML replacement


def test_case_insensitive_matching():
    """Test that patterns match case-insensitively."""
    finding = {
        "explanation": "USING USER DATA TO TRAIN AI/ML MODELS REQUIRES CLEAR DISCLOSURE.",
        "category": "AI/ML",
    }
    result = simplify_finding_for_context(finding, ["for_child"])
    assert "AI/ML" not in result["explanation"].upper()
    assert "teach" in result["explanation"].lower()


def test_deletion_right_translation():
    """Test right to deletion/GDPR erasure is simplified."""
    finding = {
        "explanation": "Right to deletion may be limited or restricted.",
        "category": "Privacy Rights",
    }
    result = simplify_finding_for_context(finding, ["for_child"])
    assert "might not be able to ask them to delete" in result["explanation"]
    assert "deletion" not in result["explanation"].lower() or "delete" in result["explanation"]


def test_marketing_tracking_translation():
    """Test marketing and tracking language is simplified."""
    finding = {
        "explanation": "Using user data for marketing purposes is permitted.",
        "category": "Data Use",
    }
    result = simplify_finding_for_context(finding, ["for_child"])
    assert "watches what you do" in result["explanation"]
    assert "ads" in result["explanation"]


def test_data_sharing_translation():
    """Test third-party data sharing is simplified."""
    finding = {
        "explanation": "Personal data is shared to third parties for marketing purposes.",
        "category": "Data Sharing",
    }
    result = simplify_finding_for_context(finding, ["for_child"])
    assert "shares your information" in result["explanation"]
    assert "other companies" in result["explanation"]
    assert "ads too" in result["explanation"]


def test_biometric_translation():
    """Test biometric data language is simplified."""
    finding = {
        "explanation": "Facial recognition data collection is permitted.",
        "category": "Biometric",
    }
    result = simplify_finding_for_context(finding, ["for_child"])
    assert "recognize your face" in result["explanation"]
    assert "facial recognition" not in result["explanation"].lower()


def test_location_tracking_translation():
    """Test location tracking is simplified."""
    finding = {
        "explanation": "Location data is collected and tracked.",
        "category": "Location",
    }
    result = simplify_finding_for_context(finding, ["for_child"])
    assert "see where you are" in result["explanation"]
    assert "location" not in result["explanation"].lower() or "location" in finding["explanation"]


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
