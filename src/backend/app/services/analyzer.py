from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import List, Optional
from uuid import uuid4

from ..config import settings
from ..schemas import AnalysisPayload, Finding, Jurisdiction
from .lm_studio import LmStudioClient
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
    doc_type: Optional[str] = None,
    source_url: Optional[str] = None,
) -> AnalysisResult:
    cleaned = _truncate_text(text.strip())
    rule_findings = detect_findings(cleaned, jurisdictions)

    numbered_text = _with_line_numbers(cleaned)
    client = LmStudioClient()
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
                llm_findings.append(finding)
            except Exception:
                continue

    merged = _merge_findings(rule_findings, llm_findings)
    validation = validate_findings(merged, cleaned)
    confidence_parts = [validation.confidence]
    if overall_confidence is not None:
        confidence_parts.append(max(0.0, min(1.0, float(overall_confidence))))
    confidence = sum(confidence_parts) / len(confidence_parts)
    if not llm_payload:
        confidence *= 0.8
    elif not llm_findings:
        confidence *= 0.85
    if dropped_for_legal:
        confidence *= max(0.5, 1 - (0.1 * dropped_for_legal))
    confidence = max(0.0, min(1.0, confidence))

    risk_score = calculate_risk_score(merged)
    grade = _grade(risk_score)
    review_required = confidence < settings.review_threshold
    status = "needs_review" if review_required else "completed"

    payload = AnalysisPayload(
        id=str(uuid4()),
        name=name,
        doc_type=doc_type,
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
    )
    return AnalysisResult(payload=payload, issues=validation.issues)


def _merge_findings(
    rule_findings: List[Finding],
    llm_findings: List[Finding],
) -> List[Finding]:
    merged: List[Finding] = []
    seen = set()
    for finding in rule_findings + llm_findings:
        key = (finding.category.lower(), finding.excerpt.strip()[:120].lower())
        if key in seen:
            continue
        merged.append(finding)
        seen.add(key)
    return merged
