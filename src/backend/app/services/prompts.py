from __future__ import annotations

from typing import List

from ..schemas import Jurisdiction

SYSTEM_PROMPT = (
    "You are a legal-risk analyst for privacy policies and terms of service. "
    "Use only the provided document text. Do not invent facts. "
    "Return JSON only, no markdown."
)


def build_user_prompt(
    numbered_text: str,
    jurisdictions: List[Jurisdiction],
    rule_findings: List[dict],
) -> str:
    jurisdiction_text = ", ".join(jurisdictions)
    return (
        "Analyze the document for privacy and terms risks for jurisdictions: "
        f"{jurisdiction_text}.\n\n"
        "Return JSON with this exact schema:\n"
        "{\n"
        '  "summary": "2-4 sentences",\n'
        '  "overall_confidence": 0.0,\n'
        '  "findings": [\n'
        "    {\n"
        '      "category": "string",\n'
        '      "severity": "Low|Medium|High|Critical",\n'
        '      "confidence": 0.0,\n'
        '      "excerpt": "string",\n'
        '      "explanation": "string",\n'
        '      "jurisdictions": ["US-CA","GDPR"],\n'
        '      "evidence": {\n'
        '        "line_start": 1,\n'
        '        "line_end": 1,\n'
        '        "legal_basis": ["string"]\n'
        "      }\n"
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        "- Every finding must cite line numbers from the document.\n"
        "- Every finding must include at least one legal_basis citation.\n"
        "- Only include issues supported by the text.\n"
        "- Keep categories short (e.g., Sale/Share, ADM, Retention, Rights).\n"
        "- If there are no issues, return an empty findings list.\n\n"
        "Rule-based detections (for context, may be partial):\n"
        f"{rule_findings}\n\n"
        "Document (with line numbers):\n"
        f"{numbered_text}\n"
    )
