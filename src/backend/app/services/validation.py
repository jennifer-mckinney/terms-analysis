from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from ..schemas import Finding


@dataclass(frozen=True)
class ValidationResult:
    confidence: float
    issues: List[str]


def _normalize_snippet(text: str) -> str:
    return " ".join(text.lower().split())


def validate_findings(findings: List[Finding], document_text: Optional[str]) -> ValidationResult:
    issues: List[str] = []
    if not findings:
        return ValidationResult(confidence=0.0, issues=["No findings returned."])

    lines = document_text.splitlines() if document_text else []
    total_lines = len(lines)
    missing_citations = 0
    hallucination_flags = 0
    coverage_hits = 0
    for idx, finding in enumerate(findings, start=1):
        if not finding.excerpt:
            issues.append(f"Finding {idx} missing excerpt.")
            hallucination_flags += 1
        line_start = finding.evidence.line_start
        line_end = finding.evidence.line_end
        if line_start < 1 or line_end < 1 or line_start > line_end:
            issues.append(f"Finding {idx} has invalid line numbers.")
            hallucination_flags += 1
        if total_lines and (line_start > total_lines or line_end > total_lines):
            issues.append(f"Finding {idx} line numbers out of range.")
            hallucination_flags += 1
        if not finding.jurisdictions:
            issues.append(f"Finding {idx} missing jurisdictions.")
        if not finding.evidence.legal_basis:
            issues.append(f"Finding {idx} missing legal basis.")
            missing_citations += 1
        if document_text and finding.excerpt and 1 <= line_start <= line_end <= total_lines:
            span_text = "\n".join(lines[line_start - 1:line_end])
            if _normalize_snippet(finding.excerpt) in _normalize_snippet(span_text):
                coverage_hits += 1
            else:
                issues.append(f"Finding {idx} excerpt not found in cited lines.")
                hallucination_flags += 1
        elif document_text and finding.excerpt and finding.excerpt not in document_text:
            issues.append(f"Finding {idx} excerpt not found in document.")
            hallucination_flags += 1

    avg_confidence = sum(f.confidence for f in findings) / len(findings)
    coverage_ratio = coverage_hits / len(findings)
    penalty = 0.03 * len(issues)
    penalty += 0.07 * missing_citations
    penalty += 0.08 * hallucination_flags
    if document_text and coverage_ratio < 0.7:
        issues.append(f"Citation coverage low ({coverage_ratio:.2f}).")
        penalty += 0.2 * (0.7 - coverage_ratio)
    confidence = max(0.0, min(1.0, avg_confidence - penalty))
    return ValidationResult(confidence=confidence, issues=issues)
