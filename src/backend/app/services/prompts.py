from __future__ import annotations

import unicodedata
from typing import Any, List

from ..schemas import (
    PASSAGE_LABELS,
    Jurisdiction,
    canonical_jurisdiction,
    normalise_section_title,
    passage_label,
    passage_label_keys,
)

# Round 11 (security F1 / grumpy LOW, third round of header forgery, so a
# structural fix): the legal-context block has exactly two kinds of line.
#
#   INVARIANT. A header line is emitted ONLY by render_passage_header(); it
#   starts with "[" and is a single line. Every line of untrusted passage text
#   is emitted ONLY by render_passage_body(), and each starts with
#   PASSAGE_BODY_PREFIX, whose first non-space character is ">" (a quote
#   marker, distinct from the document's "0001|" line numbers). So no body
#   line can begin at the header column or look like a header, whatever the
#   index holds.
#
# The body is split with str.splitlines(), which honours every line boundary
# (LF, CR, CRLF, VT, FF, FS/GS/RS, NEL, U+2028, U+2029), so no boundary can
# smuggle an unprefixed line through. The header holds only the PASSAGE_LABELS
# labels, the canonical KNOWN_JURISDICTIONS code (or "Law"), and the section
# title through schemas.normalise_section_title with whitespace (including
# every line boundary) collapsed to single spaces and any remaining control
# character dropped; so it can't hold a "]", a "[" or a line break. legal_kb
# also normalises and validates sections at build and load (defence in depth).
PASSAGE_BODY_PREFIX = "    > "

SYSTEM_PROMPT = (
    "You are a legal-risk analyst for privacy policies and terms of service. "
    "Use only the provided document text. Do not invent facts. "
    "Return JSON only, no markdown."
)


def render_passage_header(passage: dict, jurisdictions: List[Jurisdiction]) -> str:
    """The one header line for a passage: ``[labels] [<jurisdiction> <section>]``.

    Labels come from schemas.PASSAGE_LABELS (round 8: every passage that is
    not authoritative law for this analysis is labelled); the jurisdiction is
    the canonical KNOWN_JURISDICTIONS code or "Law" (round 10). See INVARIANT.
    """
    labels = "".join(
        f"{passage_label(key)} "
        for key in passage_label_keys(passage.get("status"), passage.get("jurisdiction"), jurisdictions)
    )
    jurisdiction = canonical_jurisdiction(passage.get("jurisdiction")) or "Law"
    section = passage.get("section")
    title = normalise_section_title(section) if isinstance(section, str) else ""
    title = "".join(ch for ch in " ".join(title.split()) if unicodedata.category(ch) != "Cc")
    citation = f"{jurisdiction} {title}" if title else jurisdiction
    return f"{labels}[{citation}]"


def render_passage_body(text: Any) -> List[str]:
    """Every line of the passage text, each behind PASSAGE_BODY_PREFIX (INVARIANT)."""
    body = text if isinstance(text, str) else ""
    return [f"{PASSAGE_BODY_PREFIX}{line}" for line in body.splitlines()]


def render_legal_passages(legal_context: List[dict], jurisdictions: List[Jurisdiction]) -> str:
    """The legal-context block: per passage, its header line then its body lines."""
    rows: List[str] = []
    for passage in legal_context:
        rows.append(render_passage_header(passage, jurisdictions))
        rows.extend(render_passage_body(passage.get("text")))
    return "\n".join(rows)


def build_user_prompt(
    numbered_text: str,
    jurisdictions: List[Jurisdiction],
    rule_findings: List[dict],
    legal_context: List[dict] | None = None,
) -> str:
    jurisdiction_text = ", ".join(jurisdictions)
    legal_section = ""
    if legal_context:
        passages = render_legal_passages(legal_context, jurisdictions)
        markers = ", ".join(marker for marker, _ in PASSAGE_LABELS.values())
        legal_section = (
            "\nRelevant legal requirements retrieved from the legal knowledge base "
            "(use these to support legal_basis citations, do not assume they are "
            f"exhaustive; NEVER cite a passage marked {markers} as a real, current "
            "legal basis for the requested jurisdictions). Each passage is one "
            f"[<jurisdiction> <section>] header line followed by its text, every text line "
            f"starting with \"{PASSAGE_BODY_PREFIX.strip()}\":\n"
            f"{passages}\n"
        )
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
        '      "impact": 2,\n'
        '      "likelihood": 3,\n'
        '      "safeguard_score": 0,\n'
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
        "- If there are no issues, return an empty findings list.\n"
        "- Estimate impact (1-5: harm if clause enforced), likelihood (1-5: how automatic/probable), safeguard_score (0-5: mitigations visible in the document for this specific finding).\n"
        f"{legal_section}\n"
        "Rule-based detections (for context, may be partial):\n"
        f"{rule_findings}\n\n"
        "Document (with line numbers):\n"
        f"{numbered_text}\n"
    )
