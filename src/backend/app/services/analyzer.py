from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import List, Optional
from uuid import uuid4
import time
import asyncio
import re

from ..config import settings
from ..schemas import AnalysisPayload, DocType, Finding, IndustryProfile, Jurisdiction, Evidence
from .localai import LocalAIClient
from .rules import detect_findings
from .validation import validate_findings


@dataclass(frozen=True)
class AnalysisResult:
    payload: AnalysisPayload
    issues: List[str]




def _truncate_text(text: str) -> str:
    if len(text) <= settings.max_input_chars:
        return text
    return text[: settings.max_input_chars]


def _with_line_numbers(text: str) -> str:
    lines = text.splitlines()
    return "\n".join(f"{idx + 1:04d}| {line}" for idx, line in enumerate(lines))


def _line_offsets(text: str) -> List[int]:
    offsets = []
    current = 0
    for line in text.splitlines(True):
        offsets.append(current)
        current += len(line)
    if not offsets:
        offsets.append(0)
    return offsets


# Category groups boosted/suppressed per document type
_DOCTYPE_BOOSTS: dict[str, dict[str, float]] = {
    "Privacy Policy": {
        "Data Sale / Sharing": 0.3,
        "Data Retention": 0.2,
        "User Rights": 0.2,
        "Third-Party Sharing": 0.2,
    },
    "Terms of Service": {
        "Liability Limitation": 0.3,
        "Unilateral Changes": 0.3,
        "Arbitration / Dispute": 0.2,
        "Intellectual Property": 0.1,
    },
    "Cookie Policy": {
        "Tracking / Profiling": 0.4,
        "Consent": 0.3,
        "Third-Party Sharing": 0.2,
    },
    "Data Processing Agreement": {
        "Data Security": 0.3,
        "Data Transfer": 0.3,
        "Sub-processors": 0.2,
        "Data Retention": 0.2,
    },
    "Combined": {},  # no adjustment — document contains everything
}

# Category groups boosted per industry
_INDUSTRY_BOOSTS: dict[str, dict[str, float]] = {
    "Healthcare": {
        "Health Data": 0.4,
        "Sensitive Data": 0.3,
        "Data Security": 0.2,
    },
    "Finance": {
        "Financial Data": 0.4,
        "Data Security": 0.3,
        "Consent": 0.2,
    },
    "Education": {
        "Children's Privacy": 0.4,
        "Sensitive Data": 0.3,
        "User Rights": 0.2,
    },
    "Social Media": {
        "Data Sale / Sharing": 0.3,
        "Tracking / Profiling": 0.3,
        "Children's Privacy": 0.2,
        "User Rights": 0.2,
    },
    "AI / Tech Platform": {
        "Automated Decision-Making": 0.4,
        "AI Training": 0.3,
        "Tracking / Profiling": 0.2,
        "Transparency": 0.2,
    },
    "Gaming": {
        "Children's Privacy": 0.4,
        "In-App Purchases": 0.3,
        "Data Sale / Sharing": 0.2,
    },
    "Retail": {
        "Data Sale / Sharing": 0.3,
        "Tracking / Profiling": 0.2,
        "Financial Data": 0.2,
    },
    "General": {},
}

_SEV_ORDER = {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}
_SEV_LIST = ["Low", "Medium", "High", "Critical"]


def _bump_severity(finding: Finding, boost: float) -> Finding:
    """Return a copy of finding with severity bumped by one level if boost >= 0.2."""
    if boost < 0.2:
        return finding
    current_idx = _SEV_ORDER.get(finding.severity, 0)
    new_idx = min(current_idx + 1, 3)
    if new_idx == current_idx:
        return finding
    new_sev = _SEV_LIST[new_idx]
    return finding.model_copy(update={"severity": new_sev})


def _apply_doctype_weighting(
    findings: List[Finding], doc_type: Optional[str]
) -> List[Finding]:
    """Boost severity of findings whose category is relevant to the document type."""
    if not doc_type:
        return findings
    boosts = _DOCTYPE_BOOSTS.get(doc_type, {})
    if not boosts:
        return findings
    result = []
    for f in findings:
        boost = next(
            (v for k, v in boosts.items() if k.lower() in f.category.lower()),
            0.0,
        )
        result.append(_bump_severity(f, boost))
    return result


def _apply_industry_emphasis(
    findings: List[Finding], industry: Optional[str]
) -> List[Finding]:
    """Boost severity of findings whose category is sensitive for the given industry."""
    if not industry or industry == "General":
        return findings
    boosts = _INDUSTRY_BOOSTS.get(industry, {})
    if not boosts:
        return findings
    result = []
    for f in findings:
        boost = next(
            (v for k, v in boosts.items() if k.lower() in f.category.lower()),
            0.0,
        )
        result.append(_bump_severity(f, boost))
    return result


def calculate_risk_score(findings: List[Finding]) -> float:
    if not findings:
        return 0.0
    weights = {"Low": 0.2, "Medium": 0.5, "High": 0.8, "Critical": 1.0}
    avg = sum(weights.get(f.severity, 0.5) for f in findings) / len(findings)
    return round(avg * 10, 2)


def _grade(score: float) -> str:
    if score >= 8.5:
        return "D+"
    if score >= 7.5:
        return "C"
    if score >= 6.5:
        return "C+"
    if score >= 5.5:
        return "B-"
    if score >= 4.5:
        return "B"
    if score >= 3.5:
        return "A-"
    return "A"


async def analyze_text(
    text: str,
    jurisdictions: List[Jurisdiction],
    name: Optional[str] = None,
    doc_type: Optional[DocType] = None,
    industry: Optional[IndustryProfile] = None,
    source_url: Optional[str] = None,
    mode: str = "full",
    source_document: Optional[str] = None,
) -> AnalysisResult:
    cleaned = _truncate_text(text.strip())
    start_time = time.time()
    
    # Quick mode: only detect high-severity findings, skip ML inference
    if mode == "quick":
        rule_findings = detect_high_severity_findings(cleaned, jurisdictions)
        llm_findings: List[Finding] = []
        summary: Optional[str] = None
        overall_confidence: Optional[float] = None
    else:
        rule_findings = detect_findings(cleaned, jurisdictions)

        numbered_text = _with_line_numbers(cleaned)
        client = LocalAIClient()
        formatted_rules = []
        for finding in rule_findings:
            if hasattr(finding, "model_dump"):
                formatted_rules.append(finding.model_dump())
            else:
                formatted_rules.append(json.loads(finding.json()))

        llm_payload = await client.analyze(
            numbered_text=numbered_text,
            jurisdictions=jurisdictions,
            rule_findings=formatted_rules,
        )

        llm_findings: List[Finding] = []
        summary: Optional[str] = None
        overall_confidence: Optional[float] = None
        dropped_for_legal = 0
        if llm_payload:
            summary = llm_payload.get("summary")
            overall_confidence = llm_payload.get("overall_confidence")
            for item in llm_payload.get("findings", []):
                try:
                    finding = Finding(**item)
                    if not finding.evidence.legal_basis:
                        dropped_for_legal += 1
                        continue
                    # Ensure needs_review is set for LLM findings
                    if finding.confidence < 0.6:
                        finding = finding.model_copy(update={"needs_review": True})
                    llm_findings.append(finding)
                except Exception:
                    continue

    # Add source_document to findings for batch processing
    if source_document:
        for finding in rule_findings + llm_findings:
            if not finding.source_document:
                finding.source_document = source_document

    merged = _merge_findings(rule_findings, llm_findings)
    merged = _apply_doctype_weighting(merged, doc_type)
    merged = _apply_industry_emphasis(merged, industry)
    validation = validate_findings(merged, cleaned)
    confidence_parts = [validation.confidence]
    if overall_confidence is not None:
        confidence_parts.append(max(0.0, min(1.0, float(overall_confidence))))
    confidence = sum(confidence_parts) / len(confidence_parts)
    if mode == "quick":
        confidence *= 0.85  # Lower confidence in quick mode
    else:
        if not summary:
            confidence *= 0.8
        elif not llm_findings:
            confidence *= 0.85
        if 'dropped_for_legal' in locals() and dropped_for_legal:
            confidence *= max(0.5, 1 - (0.1 * dropped_for_legal))
    confidence = max(0.0, min(1.0, confidence))

    risk_score = calculate_risk_score(merged)
    grade = _grade(risk_score)
    review_required = confidence < settings.review_threshold
    status = "needs_review" if review_required else "completed"
    
    elapsed_time = time.time() - start_time

    payload = AnalysisPayload(
        id=str(uuid4()),
        name=name,
        doc_type=doc_type,
        industry=industry,
        source_url=source_url,
        document_text=cleaned,
        line_offsets=_line_offsets(cleaned),
        status=status,
        review_required=review_required,
        confidence=confidence,
        risk_score=risk_score,
        grade=grade,
        created_at=datetime.now(timezone.utc),
        findings=merged,
        summary=summary,
        analysis_mode=mode,
        estimated_time=round(elapsed_time, 2),
    )
    return AnalysisResult(payload=payload, issues=validation.issues)


def _merge_findings(
    rule_findings: List[Finding],
    llm_findings: List[Finding],
) -> List[Finding]:
    """Merge rule-based and LLM findings, applying hybrid confidence scoring.
    
    When a finding is matched by both rules and LLM, uses weighted average:
    - Rules-based confidence: ~90-95%
    - LLM confidence: use model's probability
    - Hybrid: 60% rules + 40% LLM confidence
    """
    merged: List[Finding] = []
    seen = set()
    
    # Create a dict of llm findings by category + excerpt for quick lookup
    llm_map = {}
    for llm_finding in llm_findings:
        key = (llm_finding.category.lower(), llm_finding.excerpt.strip()[:120].lower())
        llm_map[key] = llm_finding
    
    # Process rule findings first
    for finding in rule_findings:
        key = (finding.category.lower(), finding.excerpt.strip()[:120].lower())
        if key in seen:
            continue
        
        # Check if there's a corresponding LLM finding
        if key in llm_map:
            llm_finding = llm_map[key]
            # Apply hybrid confidence: 60% rules + 40% LLM
            hybrid_confidence = 0.6 * finding.confidence + 0.4 * llm_finding.confidence
            hybrid_confidence = max(0.0, min(1.0, hybrid_confidence))
            
            # Create a merged finding with hybrid confidence
            merged_finding = finding.model_copy(update={
                "confidence": hybrid_confidence,
                "needs_review": hybrid_confidence < 0.6,
            })
            merged.append(merged_finding)
            del llm_map[key]  # Mark as processed
        else:
            merged.append(finding)
        
        seen.add(key)
    
    # Add remaining LLM findings (those not matched by rules)
    for llm_finding in llm_map.values():
        key = (llm_finding.category.lower(), llm_finding.excerpt.strip()[:120].lower())
        if key not in seen:
            # LLM-only findings: mark for review if confidence < 0.6
            llm_finding_updated = llm_finding.model_copy(update={
                "needs_review": llm_finding.confidence < 0.6,
            })
            merged.append(llm_finding_updated)
            seen.add(key)
    
    return merged


def detect_high_severity_findings(text: str, jurisdictions: List[Jurisdiction]) -> List[Finding]:
    """Quick mode: detect only high and critical severity findings."""
    from .rules import PATTERNS
    
    findings: List[Finding] = []
    for pattern in PATTERNS:
        # Only include High and Critical severity patterns
        if pattern.severity not in ["High", "Critical"]:
            continue
        
        # Check if pattern applies to any requested jurisdiction
        if not any(j in pattern.jurisdictions for j in jurisdictions):
            continue
        
        for regex_pattern in pattern.patterns:
            try:
                for match in re.finditer(regex_pattern, text, re.IGNORECASE | re.MULTILINE):
                    start = max(0, match.start() - 50)
                    end = min(len(text), match.end() + 50)
                    excerpt = text[start:end].strip()
                    
                    # Calculate line numbers
                    line_start = text[:match.start()].count('\n') + 1
                    line_end = text[:match.end()].count('\n') + 1
                    
                    finding = Finding(
                        category=pattern.category,
                        severity=pattern.severity,
                        confidence=0.8,  # High confidence for rule-based detection
                        excerpt=excerpt,
                        explanation=pattern.explanation,
                        jurisdictions=list(pattern.jurisdictions),
                        evidence=Evidence(
                            line_start=line_start,
                            line_end=line_end,
                            legal_basis=pattern.legal_basis,
                        ),
                    )
                    findings.append(finding)
            except Exception:
                continue
    
    return findings


async def analyze_batch_documents(
    documents: List[tuple[str, Optional[str], Optional[str], Optional[str]]],  # (text, name, url, doc_type)
    industry: Optional[IndustryProfile],
    jurisdictions: List[Jurisdiction],
    mode: str = "full",
    detect_cross_references: bool = True,
) -> tuple[List[AnalysisPayload], List[dict]]:
    """
    Analyze multiple documents in batch.
    Returns: (list of AnalysisPayload, list of cross-references)
    """
    results = []
    cross_refs = []
    
    # Process documents in parallel where possible
    tasks = []
    for idx, (text, name, url, doc_type) in enumerate(documents):
        doc_name = name or url or f"Document {idx + 1}"
        task = analyze_text(
            text,
            jurisdictions,
            name=doc_name,
            doc_type=doc_type,
            industry=industry,
            source_url=url,
            mode=mode,
            source_document=doc_name,
        )
        tasks.append((idx, task))
    
    # Execute tasks concurrently
    for idx, task in tasks:
        result = await task
        results.append(result.payload)
    
    # Detect cross-references between documents
    if detect_cross_references and len(results) > 1:
        cross_refs = _detect_cross_references(
            [(r.name or f"Doc {i}", r.document_text or "") for i, r in enumerate(results)]
        )
    
    return results, cross_refs


def _detect_cross_references(documents: List[tuple[str, str]]) -> List[dict]:
    """
    Detect cross-references between documents.
    Look for patterns like "See our Privacy Policy", "as stated in Terms of Service", etc.
    """
    cross_refs = []
    
    # Common reference patterns
    patterns = [
        r"see (?:our )?(privacy\s+policy|terms\s+of\s+service|cookie\s+policy|terms|privacy)",
        r"as\s+(?:described|stated|outlined)\s+in\s+(?:our\s+)?(privacy\s+policy|terms\s+of\s+service|cookie\s+policy|terms|privacy)",
        r"(?:refer|reference|see also)\s+(?:our\s+)?(privacy\s+policy|terms\s+of\s+service|cookie\s+policy|terms|privacy)",
        r"governed\s+by\s+(?:our\s+)?(privacy\s+policy|terms\s+of\s+service|cookie\s+policy|terms|privacy)",
    ]
    
    for i, (doc_name_i, text_i) in enumerate(documents):
        for j, (doc_name_j, text_j) in enumerate(documents):
            if i >= j:
                continue
            
            for pattern in patterns:
                matches = list(re.finditer(pattern, text_i, re.IGNORECASE))
                if matches:
                    for match in matches:
                        cross_refs.append({
                            "source_document": doc_name_i,
                            "target_document": doc_name_j,
                            "reference_text": match.group(0),
                            "type": "policy_reference",
                        })
    
    return cross_refs
