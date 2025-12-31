from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, List, Optional

from ..schemas import Evidence, Finding, Jurisdiction, Severity


@dataclass(frozen=True)
class RulePattern:
    category: str
    severity: Severity
    jurisdictions: List[Jurisdiction]
    explanation: str
    legal_basis: List[str]
    patterns: List[str]


PATTERNS: List[RulePattern] = [
    RulePattern(
        category="Sale/Share",
        severity="High",
        jurisdictions=["US-CA"],
        explanation="Sharing/sale language may trigger CCPA/CPRA opt-out obligations.",
        legal_basis=["CCPA/CPRA opt-out (Sale/Share)"],
        patterns=[
            r"\bsell\b",
            r"\bsale of personal\b",
            r"\bshare\b.*\bpersonal\b",
            r"cross-context behavioral advertising",
        ],
    ),
    RulePattern(
        category="ADM",
        severity="High",
        jurisdictions=["GDPR"],
        explanation="Automated decision-making may require disclosures and safeguards.",
        legal_basis=["GDPR Art. 22"],
        patterns=[
            r"automated decision",
            r"profiling",
            r"algorithmic decision",
            r"solely automated",
        ],
    ),
    RulePattern(
        category="Dark Patterns",
        severity="Medium",
        jurisdictions=["US-CA", "GDPR"],
        explanation="Consent mechanisms that coerce or confuse may be invalid.",
        legal_basis=["GDPR consent validity", "CPRA consent requirements"],
        patterns=[
            r"consent by using",
            r"pre-checked",
            r"cannot opt out",
            r"by continuing to use",
            r"deemed to consent",
        ],
    ),
    RulePattern(
        category="Retention",
        severity="Medium",
        jurisdictions=["US-CA", "GDPR"],
        explanation="Retention periods must be disclosed and limited to necessity.",
        legal_basis=["GDPR Art. 5(1)(e)", "CPRA retention notice"],
        patterns=[
            r"retain",
            r"retention",
            r"as long as necessary",
            r"indefinite",
            r"for so long as",
        ],
    ),
    RulePattern(
        category="User Rights",
        severity="Medium",
        jurisdictions=["US-CA", "GDPR"],
        explanation="Policies must describe access, deletion, and correction rights.",
        legal_basis=["GDPR Art. 15-18", "CCPA/CPRA rights"],
        patterns=[
            r"access",
            r"delete",
            r"correct",
            r"opt[- ]?out",
            r"appeal",
            r"data portability",
        ],
    ),
    RulePattern(
        category="Minors",
        severity="High",
        jurisdictions=["US-CA", "GDPR"],
        explanation="Children's data requires special protections and disclosures.",
        legal_basis=["GDPR Art. 8", "CPRA minors consent"],
        patterns=[r"children", r"minor", r"under\s?(13|16|18)"],
    ),
    RulePattern(
        category="Sensitive Data",
        severity="High",
        jurisdictions=["US-CA", "GDPR"],
        explanation="Sensitive data handling requires explicit disclosures.",
        legal_basis=["GDPR Art. 9", "CPRA sensitive personal information"],
        patterns=[r"sensitive", r"biometric", r"health data", r"precise geolocation"],
    ),
    RulePattern(
        category="Unilateral Changes",
        severity="Medium",
        jurisdictions=["US-CA", "GDPR"],
        explanation="Unilateral change clauses without notice may be unfair.",
        legal_basis=["Unfair terms notice requirement"],
        patterns=[r"modify these terms", r"change these terms", r"without notice"],
    ),
    RulePattern(
        category="Liability",
        severity="Medium",
        jurisdictions=["US-CA", "GDPR"],
        explanation="Broad liability waivers may limit user remedies.",
        legal_basis=["Consumer protection fairness"],
        patterns=[r"limit(?:ation)? of liability", r"not liable", r"liability limitation"],
    ),
]


SEVERITY_BASE = {
    "Low": 0.45,
    "Medium": 0.6,
    "High": 0.75,
    "Critical": 0.9,
}


def _line_number(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _excerpt(text: str, match_start: int, match_end: int, window: int = 140) -> str:
    start = max(0, match_start - window)
    end = min(len(text), match_end + window)
    return text[start:end].strip()


def _match_stats(patterns: Iterable[str], text: str) -> tuple[Optional[re.Match], int, int]:
    first_match: Optional[re.Match] = None
    pattern_hits = 0
    match_count = 0
    for pattern in patterns:
        matches = list(re.finditer(pattern, text, flags=re.IGNORECASE))
        if matches:
            pattern_hits += 1
            match_count += len(matches)
            if first_match is None:
                first_match = matches[0]
    return first_match, pattern_hits, match_count


def _confidence(
    severity: Severity,
    pattern_hits: int,
    match_count: int,
    pattern_total: int,
) -> float:
    base = SEVERITY_BASE.get(severity, 0.6)
    hit_ratio = pattern_hits / pattern_total if pattern_total else 0.0
    density = min(1.0, match_count / 5)
    score = 0.25 + 0.5 * base + 0.15 * hit_ratio + 0.1 * density
    return max(0.35, min(0.95, score))


def detect_findings(text: str, jurisdictions: List[Jurisdiction]) -> List[Finding]:
    findings: List[Finding] = []
    for rule in PATTERNS:
        if not set(rule.jurisdictions).intersection(jurisdictions):
            continue
        match, pattern_hits, match_count = _match_stats(rule.patterns, text)
        if not match:
            continue
        line_start = _line_number(text, match.start())
        line_end = _line_number(text, match.end())
        excerpt = _excerpt(text, match.start(), match.end())
        findings.append(
            Finding(
                category=rule.category,
                severity=rule.severity,
                confidence=_confidence(
                    rule.severity,
                    pattern_hits=pattern_hits,
                    match_count=match_count,
                    pattern_total=len(rule.patterns),
                ),
                excerpt=excerpt,
                explanation=rule.explanation,
                jurisdictions=rule.jurisdictions,
                evidence=Evidence(
                    line_start=line_start,
                    line_end=line_end,
                    legal_basis=rule.legal_basis,
                ),
            )
        )
    return findings
