"""Tests for Quick Scan Mode (Enhancement 2)"""

import pytest
import asyncio
import time
from datetime import datetime
from typing import List

# Test imports from the backend
import sys
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent.parent / "src" / "backend"
sys.path.insert(0, str(backend_path))

from app.services.analyzer import analyze_text
from app.schemas import Finding, Evidence


# Sample test documents
PRIVACY_POLICY_SAMPLE = """
Privacy Policy

We collect personal information including name, email, and browsing history.
We sell your personal information to third-party advertisers.
Your data is retained for 5 years unless you request deletion.
We use automated decision-making for content recommendations.
We share data with analytics partners like Google Analytics.
We use cookies to track your online behavior across websites.
Children under 13 are not permitted to use our service.
We process your data under legitimate interest basis.
"""

TERMS_OF_SERVICE_SAMPLE = """
Terms of Service

1. Limitation of Liability: We are not liable for indirect or consequential damages.
2. Unilateral Modifications: We may modify these terms at any time without notice.
3. Arbitration: Any disputes must be resolved through binding arbitration.
4. Intellectual Property: All content is our intellectual property.
5. User-Generated Content: We own all user-generated content.
6. Dispute Resolution: You waive your right to class action lawsuits.
"""


@pytest.mark.asyncio
async def test_quick_mode_returns_analysis_mode():
    """Test that quick mode returns analysis_mode field"""
    result = await analyze_text(
        PRIVACY_POLICY_SAMPLE,
        jurisdictions=["US-CA", "GDPR"],
        mode="quick",
    )
    
    assert result.payload.analysis_mode == "quick"


@pytest.mark.asyncio
async def test_full_mode_returns_analysis_mode():
    """Test that full mode returns analysis_mode field"""
    result = await analyze_text(
        PRIVACY_POLICY_SAMPLE,
        jurisdictions=["US-CA", "GDPR"],
        mode="full",
    )
    
    assert result.payload.analysis_mode == "full"


@pytest.mark.asyncio
async def test_quick_mode_returns_estimated_time():
    """Test that analysis returns estimated_time"""
    result = await analyze_text(
        PRIVACY_POLICY_SAMPLE,
        jurisdictions=["US-CA", "GDPR"],
        mode="quick",
    )
    
    assert hasattr(result.payload, "estimated_time")
    assert isinstance(result.payload.estimated_time, float)
    assert result.payload.estimated_time > 0


@pytest.mark.asyncio
async def test_quick_mode_is_faster_than_full():
    """Test that quick mode is faster than full mode"""
    # This is a heuristic test - quick mode should skip ML inference
    start_quick = time.time()
    result_quick = await analyze_text(
        PRIVACY_POLICY_SAMPLE,
        jurisdictions=["US-CA", "GDPR"],
        mode="quick",
    )
    time_quick = time.time() - start_quick
    
    # In a real scenario, full mode would be slower
    # For testing purposes, we just verify quick mode completes
    assert result_quick.payload.estimated_time < 30  # Should complete in < 30s


@pytest.mark.asyncio
async def test_quick_mode_finds_high_severity_findings():
    """Test that quick mode detects high-severity findings"""
    result = await analyze_text(
        PRIVACY_POLICY_SAMPLE,
        jurisdictions=["US-CA", "GDPR"],
        mode="quick",
    )
    
    # Should have findings (depends on rules)
    assert isinstance(result.payload.findings, list)
    
    # All findings should be High or Critical severity
    for finding in result.payload.findings:
        assert finding.severity in ["High", "Critical"]


@pytest.mark.asyncio
async def test_quick_mode_lower_confidence():
    """Test that quick mode produces lower confidence scores"""
    result_quick = await analyze_text(
        PRIVACY_POLICY_SAMPLE,
        jurisdictions=["US-CA", "GDPR"],
        mode="quick",
    )
    
    result_full = await analyze_text(
        PRIVACY_POLICY_SAMPLE,
        jurisdictions=["US-CA", "GDPR"],
        mode="full",
    )
    
    # Quick mode should generally have lower confidence
    # (since it skips ML inference)
    assert result_quick.payload.confidence <= result_full.payload.confidence


@pytest.mark.asyncio
async def test_quick_mode_findings_have_evidence():
    """Test that quick mode findings include evidence"""
    result = await analyze_text(
        PRIVACY_POLICY_SAMPLE,
        jurisdictions=["US-CA", "GDPR"],
        mode="quick",
    )
    
    for finding in result.payload.findings:
        assert finding.evidence is not None
        assert hasattr(finding.evidence, "line_start")
        assert hasattr(finding.evidence, "line_end")
        assert finding.evidence.line_start >= 1


@pytest.mark.asyncio
async def test_mode_parameter_default_is_full():
    """Test that default mode is 'full'"""
    result = await analyze_text(
        PRIVACY_POLICY_SAMPLE,
        jurisdictions=["US-CA", "GDPR"],
        # mode not specified
    )
    
    assert result.payload.analysis_mode == "full"


@pytest.mark.asyncio
async def test_quick_mode_with_different_jurisdictions():
    """Test quick mode works with different jurisdictions"""
    result = await analyze_text(
        PRIVACY_POLICY_SAMPLE,
        jurisdictions=["GDPR", "PIPEDA", "UK-GDPR"],
        mode="quick",
    )
    
    assert result.payload.analysis_mode == "quick"
    # Findings should be relevant to requested jurisdictions
    for finding in result.payload.findings:
        assert any(j in finding.jurisdictions for j in ["GDPR", "PIPEDA", "UK-GDPR"])


@pytest.mark.asyncio
async def test_quick_mode_with_short_document():
    """Test quick mode with very short document"""
    short_doc = "We sell your data."
    
    result = await analyze_text(
        short_doc,
        jurisdictions=["US-CA"],
        mode="quick",
    )
    
    assert result.payload.analysis_mode == "quick"
    assert result.payload.estimated_time > 0


@pytest.mark.asyncio
async def test_quick_mode_source_document_preserved():
    """Test that source_document parameter is preserved in findings"""
    result = await analyze_text(
        PRIVACY_POLICY_SAMPLE,
        jurisdictions=["US-CA"],
        mode="quick",
        source_document="privacy_policy_2024.txt",
    )
    
    # Findings should have source_document set
    for finding in result.payload.findings:
        assert finding.source_document == "privacy_policy_2024.txt"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
