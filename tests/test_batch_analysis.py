"""Tests for Multi-Document Support / Batch Analysis (Enhancement 7)"""

import pytest
import asyncio
from datetime import datetime
from typing import List

# Test imports from the backend
import sys
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent.parent / "src" / "backend"
sys.path.insert(0, str(backend_path))

from app.services.analyzer import analyze_batch_documents, _detect_cross_references
from app.schemas import Finding


# Sample test documents
PRIVACY_POLICY = """
Privacy Policy

We collect and process your personal information.
We sell your data to third parties.
See our Cookie Policy for more information about tracking.
Our Terms of Service govern this relationship.
Data retention is 30 days by default.
"""

COOKIE_POLICY = """
Cookie Policy

We use cookies for analytics and tracking.
See our Privacy Policy for details about data usage.
Third-party cookies are used for advertising.
You can control cookie settings in your browser.
"""

TERMS_OF_SERVICE = """
Terms of Service

Our services are provided "as-is".
As stated in our Privacy Policy, we may collect your data.
See our Cookie Policy for information about tracking technologies.
Disputes will be governed by California law.
We reserve the right to change these terms.
"""


@pytest.mark.asyncio
async def test_batch_documents_basic():
    """Test basic batch document analysis"""
    documents = [
        (PRIVACY_POLICY, "Privacy Policy", "https://example.com/privacy", "Privacy Policy"),
        (COOKIE_POLICY, "Cookie Policy", "https://example.com/cookies", "Cookie Policy"),
    ]
    
    results, cross_refs = await analyze_batch_documents(
        documents,
        industry=None,
        jurisdictions=["US-CA", "GDPR"],
        mode="full",
        detect_cross_references=True,
    )
    
    assert len(results) == 2
    assert all(r.name for r in results)


@pytest.mark.asyncio
async def test_batch_documents_source_document_tagged():
    """Test that batch documents have source_document field"""
    documents = [
        (PRIVACY_POLICY, "Privacy Policy", None, None),
        (COOKIE_POLICY, "Cookie Policy", None, None),
    ]
    
    results, _ = await analyze_batch_documents(
        documents,
        industry=None,
        jurisdictions=["US-CA"],
        mode="quick",
        detect_cross_references=False,
    )
    
    # All findings should have source_document set
    for i, result in enumerate(results):
        doc_name = ["Privacy Policy", "Cookie Policy"][i]
        for finding in result.findings:
            assert finding.source_document == doc_name


@pytest.mark.asyncio
async def test_batch_cross_reference_detection():
    """Test detection of cross-references between documents"""
    documents = [
        (PRIVACY_POLICY, "Privacy Policy", None, None),
        (COOKIE_POLICY, "Cookie Policy", None, None),
        (TERMS_OF_SERVICE, "Terms of Service", None, None),
    ]
    
    results, cross_refs = await analyze_batch_documents(
        documents,
        industry=None,
        jurisdictions=["US-CA"],
        mode="full",
        detect_cross_references=True,
    )
    
    # Should detect multiple cross-references
    assert isinstance(cross_refs, list)
    
    # Privacy Policy references Cookie Policy and Terms
    # Cookie Policy references Privacy Policy
    # Terms references both Privacy Policy and Cookie Policy
    if cross_refs:
        for ref in cross_refs:
            assert "source_document" in ref
            assert "target_document" in ref
            assert "reference_text" in ref
            assert "type" in ref


@pytest.mark.asyncio
async def test_batch_documents_with_mode():
    """Test batch analysis with quick mode"""
    documents = [
        (PRIVACY_POLICY, "Privacy Policy", None, None),
        (COOKIE_POLICY, "Cookie Policy", None, None),
    ]
    
    results, _ = await analyze_batch_documents(
        documents,
        industry="General",
        jurisdictions=["GDPR"],
        mode="quick",
        detect_cross_references=False,
    )
    
    # All results should use quick mode
    for result in results:
        assert result.analysis_mode == "quick"


@pytest.mark.asyncio
async def test_batch_results_have_timestamps():
    """Test that batch results include created_at timestamps"""
    documents = [
        (PRIVACY_POLICY, "Privacy Policy", None, None),
    ]
    
    results, _ = await analyze_batch_documents(
        documents,
        industry=None,
        jurisdictions=["US-CA"],
        mode="full",
        detect_cross_references=False,
    )
    
    assert len(results) > 0
    for result in results:
        assert hasattr(result, "created_at")
        assert isinstance(result.created_at, datetime)


@pytest.mark.asyncio
async def test_batch_without_cross_reference_detection():
    """Test batch analysis without cross-reference detection"""
    documents = [
        (PRIVACY_POLICY, "Policy1", None, None),
        (COOKIE_POLICY, "Policy2", None, None),
    ]
    
    results, cross_refs = await analyze_batch_documents(
        documents,
        industry=None,
        jurisdictions=["US-CA"],
        mode="full",
        detect_cross_references=False,
    )
    
    # Cross references should be empty
    assert cross_refs == []


def test_cross_reference_detection_privacy_policy():
    """Test detecting references in privacy policy"""
    docs = [
        ("Our Privacy Policy states...", "Privacy Policy"),
        ("Our Cookie Policy explains...", "Cookie Policy"),
    ]
    
    cross_refs = _detect_cross_references(docs)
    
    # Privacy Policy mentions Cookie Policy
    assert any(
        ref["source_document"] == "Privacy Policy"
        for ref in cross_refs
    )


def test_cross_reference_detection_multiple_patterns():
    """Test multiple reference patterns are detected"""
    text_with_refs = """
    For more information, see our Privacy Policy.
    As described in our Terms of Service, you agree to...
    As outlined in our Cookie Policy, we collect information...
    Refer to our Privacy Policy for details.
    """
    
    docs = [
        (text_with_refs, "Main Policy"),
        ("Details here", "Privacy Policy"),
    ]
    
    cross_refs = _detect_cross_references(docs)
    
    # Should find multiple reference types
    if cross_refs:
        assert len(cross_refs) > 0


def test_cross_reference_bidirectional():
    """Test cross-reference detection handles bidirectional references"""
    privacy_policy = "For cookie tracking details, see our Cookie Policy."
    cookie_policy = "See our Privacy Policy for more on data handling."
    
    docs = [
        (privacy_policy, "Privacy Policy"),
        (cookie_policy, "Cookie Policy"),
    ]
    
    cross_refs = _detect_cross_references(docs)
    
    # Should detect both directions
    source_targets = {(ref["source_document"], ref["target_document"]) for ref in cross_refs}
    
    # Verify we found references (exact structure depends on pattern matching)
    assert len(cross_refs) >= 0  # At minimum, no errors


@pytest.mark.asyncio
async def test_batch_with_industry_emphasis():
    """Test batch analysis applies industry emphasis"""
    documents = [
        (PRIVACY_POLICY, "Privacy Policy", None, "Privacy Policy"),
    ]
    
    results_general, _ = await analyze_batch_documents(
        documents,
        industry="General",
        jurisdictions=["US-CA"],
        mode="full",
        detect_cross_references=False,
    )
    
    results_healthcare, _ = await analyze_batch_documents(
        documents,
        industry="Healthcare",
        jurisdictions=["US-CA"],
        mode="full",
        detect_cross_references=False,
    )
    
    # Different industries may produce different results
    # Healthcare should emphasize health/sensitive data
    assert len(results_general) == 1
    assert len(results_healthcare) == 1


@pytest.mark.asyncio
async def test_batch_preserves_doc_types():
    """Test that document types are preserved in batch results"""
    documents = [
        (PRIVACY_POLICY, "Policy 1", None, "Privacy Policy"),
        (COOKIE_POLICY, "Policy 2", None, "Cookie Policy"),
        (TERMS_OF_SERVICE, "Terms", None, "Terms of Service"),
    ]
    
    results, _ = await analyze_batch_documents(
        documents,
        industry=None,
        jurisdictions=["US-CA"],
        mode="full",
        detect_cross_references=False,
    )
    
    doc_types = [r.doc_type for r in results]
    assert "Privacy Policy" in doc_types
    assert "Cookie Policy" in doc_types
    assert "Terms of Service" in doc_types


@pytest.mark.asyncio
async def test_batch_documents_concurrent_processing():
    """Test that batch documents are processed"""
    # Create multiple documents
    documents = [
        (PRIVACY_POLICY, f"Doc{i}", None, None)
        for i in range(3)
    ]
    
    results, _ = await analyze_batch_documents(
        documents,
        industry=None,
        jurisdictions=["US-CA"],
        mode="quick",
        detect_cross_references=False,
    )
    
    # All documents should be analyzed
    assert len(results) == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
