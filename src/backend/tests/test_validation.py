from __future__ import annotations

import pytest

from app.schemas import Evidence, Finding
from app.services.validation import ValidationResult, _normalize_snippet, validate_findings


def _finding(
    *,
    excerpt: str = "We sell your personal data.",
    line_start: int = 1,
    line_end: int = 1,
    legal_basis: list[str] | None = None,
    jurisdictions: list[str] | None = None,
    confidence: float = 0.85,
) -> Finding:
    return Finding(
        category="data_sharing",
        severity="High",
        confidence=confidence,
        excerpt=excerpt,
        explanation="Sells personal data.",
        jurisdictions=jurisdictions or ["GDPR"],
        evidence=Evidence(
            line_start=line_start,
            line_end=line_end,
            legal_basis=legal_basis if legal_basis is not None else ["GDPR Art. 6"],
        ),
    )


# ── _normalize_snippet ────────────────────────────────────────────────────────

def test_validation_normalize_snippet_collapses_whitespace():
    assert _normalize_snippet("  hello   world  ") == "hello world"


def test_validation_normalize_snippet_lowercases():
    assert _normalize_snippet("Hello WORLD") == "hello world"


# ── Empty findings ────────────────────────────────────────────────────────────

def test_validation_empty_findings_returns_zero_confidence():
    result = validate_findings([], "Some document text")
    assert result.confidence == 0.0
    assert any("No findings" in issue for issue in result.issues)


def test_validation_empty_findings_no_document():
    result = validate_findings([], None)
    assert result.confidence == 0.0


# ── Missing excerpt ───────────────────────────────────────────────────────────

def test_validation_missing_excerpt_flagged():
    f = _finding(excerpt="")
    # excerpt="" still passes Finding validation but triggers hallucination flag
    result = validate_findings([f], "We sell your personal data.\n")
    assert any("missing excerpt" in issue for issue in result.issues)


# ── Invalid line numbers ──────────────────────────────────────────────────────

def test_validation_invalid_line_numbers_start_zero():
    # Evidence.line_start has ge=1, so we must build with start=1 and patch
    f = _finding(line_start=1, line_end=1)
    # Simulate bad evidence by calling validate_findings with a finding whose
    # line_start is valid schema-wise but logically wrong (start > end)
    bad_finding = Finding(
        category="data_sharing",
        severity="High",
        confidence=0.85,
        excerpt="We sell your personal data.",
        explanation="Bad lines.",
        jurisdictions=["GDPR"],
        evidence=Evidence(line_start=5, line_end=3, legal_basis=["GDPR Art. 6"]),
    )
    result = validate_findings([bad_finding], "line1\nline2\nline3\nline4\nline5\n")
    assert any("invalid line numbers" in issue for issue in result.issues)


# ── Line numbers out of range ─────────────────────────────────────────────────

def test_validation_line_numbers_out_of_range():
    doc = "only one line"
    f = Finding(
        category="data_sharing",
        severity="High",
        confidence=0.85,
        excerpt="only one line",
        explanation="Out of range.",
        jurisdictions=["GDPR"],
        evidence=Evidence(line_start=99, line_end=100, legal_basis=["GDPR Art. 6"]),
    )
    result = validate_findings([f], doc)
    assert any("out of range" in issue for issue in result.issues)


# ── Missing jurisdictions ─────────────────────────────────────────────────────

def test_validation_missing_jurisdictions_flagged():
    # Build directly — _finding() uses `jurisdictions or ["GDPR"]` so [] falls back to default
    f = Finding(
        category="data_sharing",
        severity="High",
        confidence=0.85,
        excerpt="We sell your personal data.",
        explanation="Sells personal data.",
        jurisdictions=[],
        evidence=Evidence(line_start=1, line_end=1, legal_basis=["GDPR Art. 6"]),
    )
    result = validate_findings([f], "We sell your personal data.\n")
    assert any("missing jurisdictions" in issue for issue in result.issues)


# ── Missing legal basis ───────────────────────────────────────────────────────

def test_validation_missing_legal_basis_flagged():
    f = _finding(legal_basis=[])
    result = validate_findings([f], "We sell your personal data.\n")
    assert any("missing legal basis" in issue for issue in result.issues)


# ── Excerpt not found in cited lines ─────────────────────────────────────────

def test_validation_excerpt_not_in_cited_lines():
    doc = "line1\nline2\nline3"
    f = Finding(
        category="data_sharing",
        severity="High",
        confidence=0.85,
        excerpt="completely different text",
        explanation="Excerpt mismatch.",
        jurisdictions=["GDPR"],
        evidence=Evidence(line_start=1, line_end=1, legal_basis=["GDPR Art. 6"]),
    )
    result = validate_findings([f], doc)
    assert any("excerpt not found in cited lines" in issue or "excerpt not found in document" in issue
               for issue in result.issues)


# ── Excerpt not in document at all ───────────────────────────────────────────

def test_validation_excerpt_not_in_document():
    doc = "This is the only content here."
    # line_start beyond total_lines so the cited-lines check doesn't run
    f = Finding(
        category="data_sharing",
        severity="High",
        confidence=0.85,
        excerpt="text that does not exist anywhere",
        explanation="Not in doc.",
        jurisdictions=["GDPR"],
        evidence=Evidence(line_start=99, line_end=99, legal_basis=["GDPR Art. 6"]),
    )
    result = validate_findings([f], doc)
    # Either out-of-range or not-in-document is flagged
    assert len(result.issues) > 0


# ── Low citation coverage ─────────────────────────────────────────────────────

def test_validation_low_citation_coverage_penalty():
    # Use a document that doesn't contain any excerpt text so coverage_hits = 0
    doc = "totally unrelated content here\nand another line"
    findings = [
        Finding(
            category="data_sharing",
            severity="High",
            confidence=0.90,
            excerpt="phantom excerpt one",
            explanation="Not in doc.",
            jurisdictions=["GDPR"],
            evidence=Evidence(line_start=99, line_end=99, legal_basis=["GDPR Art. 6"]),
        ),
        Finding(
            category="data_retention",
            severity="Medium",
            confidence=0.80,
            excerpt="phantom excerpt two",
            explanation="Not in doc.",
            jurisdictions=["GDPR"],
            evidence=Evidence(line_start=99, line_end=99, legal_basis=["GDPR Art. 6"]),
        ),
    ]
    result = validate_findings(findings, doc)
    assert any("Citation coverage low" in issue for issue in result.issues)
    # Penalty should reduce confidence below average
    avg = sum(f.confidence for f in findings) / len(findings)
    assert result.confidence < avg


# ── Happy path ────────────────────────────────────────────────────────────────

def test_validation_happy_path_returns_high_confidence():
    doc = "We sell your personal data to third parties."
    f = _finding(excerpt="We sell your personal data to third parties.", line_start=1, line_end=1)
    result = validate_findings([f], doc)
    assert isinstance(result, ValidationResult)
    assert result.confidence > 0.5
    assert result.issues == []


def test_validation_no_document_text():
    f = _finding()
    result = validate_findings([f], None)
    # Without document text, no line-anchor checks run
    assert isinstance(result, ValidationResult)
    assert result.confidence > 0.0
