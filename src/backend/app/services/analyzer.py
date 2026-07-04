from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional
from uuid import uuid4

from ..config import settings
from ..schemas import (
    CATEGORIES,
    AnalysisPayload,
    ContextChip,
    DocType,
    Evidence,
    Finding,
    IndustryProfile,
    Jurisdiction,
)
from .context import apply_category_weights, verdict_headline, verdict_label
from .legal_kb import get_legal_kb
from .localai import LocalAIClient
from .rules import _seed_irp, detect_findings
from .validation import validate_findings


@dataclass(frozen=True)
class AnalysisResult:
    payload: AnalysisPayload
    issues: List[str]


# Domain roll-up: category name → domain group. Used by ``_group_by_domain``
# to bucket top findings for the four reader-facing domains.
_DOMAIN_MAP = {
    # Data (what's collected)
    "Sensitive Data": "Data",
    "Biometric Data": "Data",
    "Health Data": "Data",
    "Financial Data": "Data",
    "Children's Privacy": "Data",
    "Collection Notice": "Data",
    "Minors": "Data",
    "Sensitive Data / Opt-Out": "Data",
    # Data use (how it's used)
    "AI Training": "Data use",
    "AI Training Opt-Out": "Data use",
    "Sale/Share": "Data use",
    "Data Sale / Sharing": "Data use",
    "Tracking / Profiling": "Data use",
    "Tracking & Consent": "Data use",
    "Marketing Communications": "Data use",
    "Purpose Limitation": "Data use",
    "ADM": "Data use",
    "Automated Decision-Making": "Data use",
    "Consequential AI Decisions": "Data use",
    "High-Risk AI": "Data use",
    "Prohibited AI": "Data use",
    "GPAI / Generative AI": "Data use",
    "AI-Generated Content": "Data use",
    "Algorithmic Accountability": "Data use",
    "Human Oversight": "Data use",
    "AI Non-Discrimination": "Data use",
    # Terms of use (the agreement)
    "Liability": "Terms of use",
    "Unilateral Changes": "Terms of use",
    "Dark Patterns": "Terms of use",
    "Deceptive Practices": "Terms of use",
    "Retention": "Terms of use",
    "Breach Notification": "Terms of use",
    "Data Security": "Terms of use",
    # Privacy rights (opt-outs, deletion, portability)
    "User Rights": "Privacy rights",
    "Data Rights": "Privacy rights",
    "Individual Rights": "Privacy rights",
    "Privacy Rights": "Privacy rights",
    "Cross-Border Transfer": "Privacy rights",
    "COPPA Compliance": "Privacy rights",
    "HIPAA Compliance": "Privacy rights",
    "FERPA Compliance": "Privacy rights",
    "PCI DSS Compliance": "Privacy rights",
    "PIPEDA Consent": "Privacy rights",
    "LGPD Rights": "Privacy rights",
    "APPI Disclosure": "Privacy rights",
    "DPDP Consent": "Privacy rights",
    "POPIA Processing": "Privacy rights",
    "PIPA Processing": "Privacy rights",
    "APP Privacy": "Privacy rights",
    "UK Data Rights": "Privacy rights",
    "Privacy as Human Right": "Privacy rights",
    "Serious Privacy Invasion": "Privacy rights",
}

_DOMAIN_ORDER = ["Data", "Data use", "Terms of use", "Privacy rights"]


# Validate _DOMAIN_MAP keys against the canonical category set at import time
# (Fix 5 — cross-file string-coupling guard). Drift here would silently
# mis-bucket findings, so fail loudly instead.
_unknown_domain_keys = {cat for cat in _DOMAIN_MAP.keys() if cat not in CATEGORIES}
if _unknown_domain_keys:
    raise RuntimeError(
        f"_DOMAIN_MAP references unknown categories: "
        f"{sorted(_unknown_domain_keys)}. Update schemas.CATEGORIES."
    )


def _group_by_domain(
    findings: list[Finding], max_per_domain: int = 2, max_total: int = 8
) -> dict[str, list[Finding]]:
    """Group findings by domain, respecting per-domain and total caps.

    Findings are assumed to already be sorted by context weight (via
    ``apply_category_weights``), so the first eligible per domain is the
    highest-weighted for that domain.

    Returns an ordered dict keyed by ``_DOMAIN_ORDER``. Empty domains map to
    empty lists so the frontend can render a consistent shape.
    """
    grouped: dict[str, list[Finding]] = {d: [] for d in _DOMAIN_ORDER}
    total = 0
    for f in findings:
        if total >= max_total:
            break
        domain = _DOMAIN_MAP.get(f.category)
        if domain is None:
            continue
        if len(grouped[domain]) < max_per_domain:
            grouped[domain].append(f)
            total += 1
    return grouped


def _compute_irp(impact: int, likelihood: int, safeguard_score: int) -> float:
    """IRP = 0.5*(impact/5) + 0.4*(likelihood/5) - 0.3*(safeguard_score/5), clamped [0, 1]."""
    raw = 0.5 * (impact / 5) + 0.4 * (likelihood / 5) - 0.3 * (safeguard_score / 5)
    return max(0.0, min(1.0, round(raw, 4)))


def _truncate_text(text: str) -> str:
    if len(text) <= settings.max_input_chars:
        return text
    return text[: settings.max_input_chars]


# Whitespace-only runs (spaces, tabs, newlines, unicode spaces) collapsed to a
# single space. Applied to user paste input only — URL-fetched documents are
# normalised upstream and stripping them here would corrupt structural
# whitespace (numbered clauses, tables) in legal text.
_WHITESPACE_RUN_RE = re.compile(r"\s+")


def _normalise_paste_whitespace(text: str) -> str:
    """Strip surrounding whitespace and collapse internal runs to single spaces.

    Only appropriate for user paste input. URL and file-extracted content is
    left alone so structural whitespace survives (see ``analyze_text``'s
    ``is_paste_input`` flag).
    """
    return _WHITESPACE_RUN_RE.sub(" ", text.strip())


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


# Expected policy sections for completeness scoring (pattern, label)
_COMPLETENESS_CHECKS: List[tuple[str, str]] = [
    (r"\bright\s+to\s+(access|delete|erasure|request)\b", "user_rights"),
    (r"\bretain(?:tion)?\b|as long as necessary\b", "retention"),
    (r"\bchildren?\b|\bminor\b|\bunder\s+13\b", "minors"),
    (r"\bcontact\b|\bemail\b|\b@[a-z]", "contact"),
    (r"\bopt.?out\b|\bdo not sell\b|\bGPC\b|\bglobal privacy control\b", "opt_out"),
    (r"\bautomated\s+decision\b|\bprofil", "adm"),
    (r"\bsecurit\b|\bencrypt\b|\bprotect\b", "security"),
    (r"\bthird.party\b|\bservice\s+provider\b|\bpartner\b", "third_party"),
]


def _compute_completeness(text: str) -> float:
    found = sum(
        1 for pattern, _ in _COMPLETENESS_CHECKS
        if re.search(pattern, text, re.IGNORECASE)
    )
    return round(found / len(_COMPLETENESS_CHECKS), 2)


def _compute_action_readiness(risk_score: float, confidence: float, completeness: float) -> str:
    """Return Go/Review/Stop based on risk, confidence, and section completeness.

    Mirrors the demo's CRS-based logic:
      CRS < 0.40 (risk_score < 4) and completeness >= 0.625 → Go
      CRS >= 0.70 (risk_score >= 7) or completeness < 0.375  → Stop
      everything else                                          → Review
    """
    if risk_score >= 7.0 or completeness < 0.375:
        return "Stop"
    if risk_score < 4.0 and confidence >= 0.65 and completeness >= 0.625:
        return "Go"
    return "Review"


# Category groups boosted/suppressed per document type.
#
# Every key MUST be a member of ``schemas.CATEGORIES`` — the import-time guard
# below enforces this. Non-canonical labels (e.g. "Data Retention",
# "Liability Limitation") were removed rather than aliased so the boost dict
# stays a single source of truth. Audit finding LE-013.
_DOCTYPE_BOOSTS: dict[str, dict[str, float]] = {
    "Privacy Policy": {
        "Data Sale / Sharing": 0.3,
        "User Rights": 0.2,
        # Restored from Phase 1 removal: canonical "Retention" replaces the
        # non-canonical "Data Retention" the substring lookup used to fire on.
        "Retention": 0.2,
        # Option Z (drift-1) dormant boost: no rule currently emits
        # "Third-Party Sharing" so this is inert until a follow-up rule lands.
        # Kept here so the taxonomy is stable when it does.
        "Third-Party Sharing": 0.2,
    },
    "Terms of Service": {
        "Liability": 0.3,
        "Unilateral Changes": 0.3,
        # Restored from Phase 1 removal: "Arbitration / Dispute" is a canonical
        # category (Phase 2 taxonomy expansion added it to ``CATEGORIES``) and
        # already has a ``_CATEGORY_IRP_DEFAULTS`` entry in ``rules.py``.
        "Arbitration / Dispute": 0.2,
        # Option Z (drift-1) dormant boost: no rule currently emits
        # "Intellectual Property" so this is inert until a follow-up rule lands.
        "Intellectual Property": 0.2,
    },
    "Cookie Policy": {
        "Tracking / Profiling": 0.4,
        "Consent": 0.3,
        # Option Z (drift-1) dormant boost: no rule currently emits
        # "Third-Party Sharing" so this is inert until a follow-up rule lands.
        "Third-Party Sharing": 0.3,
    },
    "Data Processing Agreement": {
        "Data Security": 0.3,
        "Retention": 0.2,
        # Restored from Phase 1 removal: canonical "Cross-Border Transfer"
        # replaces the non-canonical "Data Transfer" the substring lookup
        # used to fire on.
        "Cross-Border Transfer": 0.3,
        # Option Z (drift-1) dormant boosts: no rule currently emits
        # "Data Transfer" or "Sub-processors" so these are inert until a
        # follow-up rule lands. Kept here so DPA taxonomy is stable.
        "Data Transfer": 0.3,
        "Sub-processors": 0.2,
    },
    "Combined": {},  # no adjustment — document contains everything
}

# Category groups boosted per industry. Same canonical-category rule applies
# as _DOCTYPE_BOOSTS. Audit finding LE-013.
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
        # Option Z (drift-1) dormant boost: no rule currently emits
        # "Transparency" so this is inert until a follow-up rule lands.
        # Kept here so AI/tech platform disclosure taxonomy is stable.
        "Transparency": 0.3,
    },
    "Gaming": {
        "Children's Privacy": 0.4,
        "Data Sale / Sharing": 0.2,
        # Option Z (drift-1) dormant boost: no rule currently emits
        # "In-App Purchases" so this is inert until a follow-up rule lands.
        "In-App Purchases": 0.3,
    },
    "Retail": {
        "Data Sale / Sharing": 0.3,
        "Tracking / Profiling": 0.2,
        "Financial Data": 0.2,
    },
    "General": {},
}


# Import-time guard: every boost key must be a canonical category in
# ``schemas.CATEGORIES``. Drift here would silently fail to boost (after LE-012
# switches _bump_severity to exact match), so fail loudly instead. Audit
# finding LE-013 — mirrors the existing _DOMAIN_MAP guard above.
_unknown_boost_keys = {
    key
    for boosts in list(_DOCTYPE_BOOSTS.values()) + list(_INDUSTRY_BOOSTS.values())
    for key in boosts.keys()
    if key not in CATEGORIES
}
if _unknown_boost_keys:
    raise RuntimeError(
        f"_DOCTYPE_BOOSTS / _INDUSTRY_BOOSTS reference unknown categories: "
        f"{sorted(_unknown_boost_keys)}. Update schemas.CATEGORIES or remove "
        f"the drifted keys."
    )

_SEV_ORDER = {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}
_SEV_LIST = ["Low", "Medium", "High", "Critical"]
_KNOWN_SEVERITIES: frozenset[str] = frozenset(_SEV_LIST)


# --------------------------------------------------------------------------
# Chip-tuned action items (issue #83 / Phase 5.d E2E CONTENT-1 MEDIUM).
#
# Previously ``_derive_action_items`` was chip-invariant: the same items
# fired for every reader. Phase 5.d found the "For work/vendor use,
# escalate liability" item surfacing for ``just_curious``, which is
# off-tone and undermines the appearance that the tool listens to context.
#
# The composition rule (see ``_derive_action_items`` below):
#   final = _ACTION_ITEMS_UNIVERSAL
#         + (chip items for every active chip in context)
#         + (category-derived items the previous implementation emitted)
#   deduped in insertion order, capped at 5 to match the prior cap.
#
# Voice constraint: chip items MUST honor LIB-VOICE V2 (no you/we/our/your
# at the load-bearing level; per-finding-observation exception does not
# apply to action_items). All items are em-dash free (LIB-VOICE V7).
# --------------------------------------------------------------------------

_ACTION_ITEMS_UNIVERSAL: List[str] = [
    "Review the specific opt-out and rights mechanisms named in the legal "
    "details above.",
]

_ACTION_ITEMS_BY_CHIP: dict[str, List[str]] = {
    "for_child": [
        "For accounts a child will use, look for parental supervision or "
        "family-account controls before signing up.",
        "Check whether facial recognition or biometric features can be "
        "disabled in the settings.",
        "Watch for policy-change notifications. These terms can update "
        "without a new consent step.",
    ],
    "for_work": [
        "For work or vendor use, escalate liability and unilateral-change "
        "clauses to legal review before signing.",
        "Compare this policy against the vendor's stated Data Processing "
        "Addendum if one exists.",
    ],
    "for_care": [
        "Consider walking through the settings together with the person "
        "being helped before agreeing.",
        "Note any language about who else can be granted account access.",
    ],
    "want_understand": [
        "Note any clauses that stood out and consider whether the "
        "tradeoffs are acceptable.",
    ],
    "just_curious": [
        "Note anything unusual for later reference.",
    ],
}


def _derive_action_items(
    findings: List[Finding],
    jurisdictions: List[Jurisdiction],
    context: Optional[List[ContextChip]] = None,
) -> List[str]:
    """Return context-relevant, generic action items derived from findings.

    Ported from ``webapp/app_streamlit_v2.py::_derive_action_items`` so the
    frontend no longer has to duplicate the derivation rules. Not service-
    specific; no hardcoded URLs. Points readers to general levers (opt-out,
    deletion, supervisory authorities) tied to categories the analysis
    actually detected. Capped at 5 items.

    Chip-tuned per issue #83: the "For work/vendor use, escalate liability"
    item now fires ONLY when ``for_work`` is in ``context``. Chip-specific
    items from ``_ACTION_ITEMS_BY_CHIP`` are prepended so the output
    materially differs across readers.

    ``context`` defaults to ``None`` for backward compatibility with callers
    that predate the chip taxonomy; in that case only universal + category-
    derived items fire.
    """
    categories = {f.category for f in findings}
    jurisdiction_set = set(jurisdictions or [])
    context_set: set[str] = set(context or [])
    lines: List[str] = []

    # 1. Universal items always fire (unless zero findings, handled below).
    lines.extend(_ACTION_ITEMS_UNIVERSAL)

    # 2. Chip-specific items: one block per active chip, in taxonomy order
    # (defined by _ACTION_ITEMS_BY_CHIP dict insertion order).
    for chip, items in _ACTION_ITEMS_BY_CHIP.items():
        if chip in context_set:
            lines.extend(items)

    # 3. Category-derived items: the previous chip-invariant set, kept for
    # backward compatibility with callers that don't pass context and for
    # readers whose chip choice doesn't cover a detected category.

    if any(c in categories for c in ("Sale/Share", "Data Sale / Sharing")):
        if "US-CA" in jurisdiction_set:
            lines.append(
                "California residents can submit a \"Do Not Sell or Share My "
                "Personal Information\" request through the service's privacy "
                "settings or a designated privacy link."
            )
        else:
            lines.append(
                "Look for an opt-out of data sale/sharing in the service's "
                "privacy settings."
            )

    if any(
        c in categories
        for c in ("User Rights", "Data Rights", "Individual Rights", "Privacy Rights")
    ):
        if "GDPR" in jurisdiction_set or "UK-GDPR" in jurisdiction_set:
            lines.append(
                "EU/UK residents can request data access, correction, and "
                "deletion under GDPR / UK GDPR. Filed with the service "
                "directly; complaints filed with the national data protection "
                "authority."
            )
        lines.append(
            "A data download and account deletion path is usually available "
            "in the service's account settings."
        )

    if any(c in categories for c in ("AI Training", "AI Training Opt-Out")):
        lines.append(
            "Look for AI training opt-out settings in the service's privacy "
            "or account controls. Not every service offers a full opt-out."
        )

    if any(
        c in categories
        for c in (
            "Automated Decision-Making",
            "ADM",
            "Consequential AI Decisions",
        )
    ):
        lines.append(
            "Automated decisions with significant effect may be challengeable. "
            "Consider requesting human review through the service's support "
            "channels."
        )

    if any(
        c in categories
        for c in ("Children's Privacy", "COPPA Compliance", "Minors")
    ):
        lines.append(
            "For accounts involving children, look for parental supervision "
            "or family-account tools. Underage accounts can be reported to "
            "the service and, in the US, to the FTC."
        )

    # NOTE: the prior chip-invariant "For work/vendor use, escalate liability
    # and unilateral-change clauses to legal review before signing." fired
    # whenever Liability/Unilateral Changes were detected, regardless of who
    # was reading. That copy now lives in _ACTION_ITEMS_BY_CHIP["for_work"]
    # and only surfaces when the reader is actually in a work context. This
    # is exactly the swap Phase 5.d flagged for just_curious (CONTENT-1).

    # Zero findings means nothing to act on: return empty even if a chip is
    # set. Preserves the empty-findings contract prior consumers relied on.
    if not findings:
        return []

    # Dedupe in insertion order, then cap. Chip and category items can name
    # overlapping levers (e.g. for_work's liability item vs the category
    # liability item); dedupe prevents visible duplication.
    seen: set[str] = set()
    deduped: List[str] = []
    for line in lines:
        if line not in seen:
            seen.add(line)
            deduped.append(line)

    return deduped[:5]


def _bump_severity(finding: Finding, boost: float) -> Finding:
    """Return a copy of finding with severity bumped by one level if boost >= 0.2.

    Fails fast on unknown severity values rather than silently defaulting to
    "Low" — a bad severity signals a data-model drift the caller must fix.
    """
    if finding.severity not in _KNOWN_SEVERITIES:
        raise ValueError(
            f"Unknown severity: {finding.severity!r} "
            f"(expected one of {sorted(_KNOWN_SEVERITIES)})"
        )
    if boost < 0.2:
        return finding
    current_idx = _SEV_ORDER[finding.severity]
    new_idx = min(current_idx + 1, 3)
    if new_idx == current_idx:
        return finding
    new_sev = _SEV_LIST[new_idx]
    return finding.model_copy(update={"severity": new_sev})


def _apply_doctype_weighting(
    findings: List[Finding], doc_type: Optional[str]
) -> List[Finding]:
    """Boost severity of findings whose category is relevant to the document type.

    Boost lookup is an exact-category match. Previously a case-insensitive
    substring match was used (``k.lower() in f.category.lower()``), which
    fired false positives whenever the boost key was a substring of an
    unrelated category (e.g. "Consent" matched "PIPEDA Consent",
    "Tracking & Consent", "DPDP Consent"). Audit finding LE-012.
    """
    if not doc_type:
        return findings
    boosts = _DOCTYPE_BOOSTS.get(doc_type, {})
    if not boosts:
        return findings
    result = []
    for f in findings:
        boost = boosts.get(f.category, 0.0)
        result.append(_bump_severity(f, boost))
    return result


def _apply_industry_emphasis(
    findings: List[Finding], industry: Optional[str]
) -> List[Finding]:
    """Boost severity of findings whose category is sensitive for the given industry.

    Boost lookup is an exact-category match — see ``_apply_doctype_weighting``
    for the rationale. Audit finding LE-012.
    """
    if not industry or industry == "General":
        return findings
    boosts = _INDUSTRY_BOOSTS.get(industry, {})
    if not boosts:
        return findings
    result = []
    for f in findings:
        boost = boosts.get(f.category, 0.0)
        result.append(_bump_severity(f, boost))
    return result


def calculate_risk_score(findings: List[Finding]) -> float:
    if not findings:
        return 0.0
    severity_weights = {"Low": 0.2, "Medium": 0.5, "High": 0.8, "Critical": 1.0}
    scores = [
        f.irp_score if f.irp_score is not None
        else severity_weights.get(f.severity, 0.5)
        for f in findings
    ]
    return round((sum(scores) / len(scores)) * 10, 2)


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
    context: Optional[List[ContextChip]] = None,
    is_paste_input: bool = False,
) -> AnalysisResult:
    # User paste input: strip surrounding whitespace and collapse internal runs
    # to single spaces before the length gate. URL and file-extracted content
    # is left as-is so structural whitespace in legal text (numbered clauses,
    # tables) survives — per PRD §5 open-question resolution.
    if is_paste_input:
        cleaned = _truncate_text(_normalise_paste_whitespace(text))
    else:
        cleaned = _truncate_text(text.strip())
    start_time = time.time()
    # Normalise context to a list so downstream helpers can trust the type.
    context_list: List[ContextChip] = list(context) if context else []
    
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

        legal_query = " ".join(jurisdictions) + " " + cleaned[:500]
        legal_context = await get_legal_kb().retrieve(
            legal_query, client, jurisdictions=jurisdictions
        )

        llm_payload = await client.analyze(
            numbered_text=numbered_text,
            jurisdictions=jurisdictions,
            rule_findings=formatted_rules,
            legal_context=legal_context,
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
                    # Compute irp_score from LLM-provided IRP fields if not already set
                    if finding.irp_score is None:
                        finding = finding.model_copy(update={
                            "irp_score": _compute_irp(finding.impact, finding.likelihood, finding.safeguard_score)
                        })
                    llm_findings.append(finding)
                except Exception:
                    continue

        # Filter LLM findings by requested jurisdictions. Rule-based detection
        # is already jurisdiction-scoped in ``detect_findings``, but the LLM
        # can return findings tagged for jurisdictions the user did not
        # request (e.g., BIPA for a California-only request) or for no
        # jurisdiction at all. A finding is kept only if it declares at least
        # one jurisdiction and at least one of those declared jurisdictions
        # matches the caller's list. Findings with an empty jurisdictions list
        # are dropped: an unclaimed jurisdiction can't be verified as
        # applicable, so we don't surface it. (PR #34 security review HIGH-2.)
        #
        # Fix 4 (global-tool contract): an empty requested ``jurisdictions``
        # list means "no jurisdiction filter". Unclaimed LLM findings
        # (``jurisdictions=[]``) are STILL dropped in that mode — an LLM
        # finding without a declared jurisdiction remains unverifiable
        # regardless of the caller's filter posture.
        if jurisdictions:
            jurisdiction_set = set(jurisdictions)
            llm_findings = [
                f for f in llm_findings
                if f.jurisdictions and any(j in jurisdiction_set for j in f.jurisdictions)
            ]
        else:
            # No jurisdiction filter, but still drop unclaimed findings.
            llm_findings = [f for f in llm_findings if f.jurisdictions]

    # Add source_document to findings for batch processing
    if source_document:
        for finding in rule_findings + llm_findings:
            if not finding.source_document:
                finding.source_document = source_document

    merged = _merge_findings(rule_findings, llm_findings)
    merged = _apply_doctype_weighting(merged, doc_type)
    merged = _apply_industry_emphasis(merged, industry)
    # Context chips re-order findings so the most reader-relevant surface first.
    merged = apply_category_weights(merged, context_list)
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
        if dropped_for_legal:
            confidence *= max(0.5, 1 - (0.1 * dropped_for_legal))
    confidence = max(0.0, min(1.0, confidence))

    risk_score = calculate_risk_score(merged)
    grade = _grade(risk_score)
    review_required = confidence < settings.review_threshold
    status = "needs_review" if review_required else "completed"
    completeness = _compute_completeness(cleaned)
    action_readiness = _compute_action_readiness(risk_score, confidence, completeness)

    # Group top findings by domain — merged is already sorted by
    # ``apply_category_weights`` so first eligible per domain is the highest.
    top_by_domain = _group_by_domain(merged)

    # Backend-generated action items (Fix 8). Frontend no longer has to
    # duplicate the derivation logic. ``context_list`` threads the reader's
    # chip choice through so items are chip-tuned per issue #83
    # (Phase 5.d E2E CONTENT-1).
    action_items = _derive_action_items(
        merged,
        list(jurisdictions) if jurisdictions else [],
        context_list,
    )

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
        action_readiness=action_readiness,
        completeness=completeness,
        context=context_list,
        jurisdictions=list(jurisdictions) if jurisdictions else [],
        verdict_headline=verdict_headline(context_list, action_readiness),
        verdict_label=verdict_label(context_list, action_readiness),
        top_by_domain=top_by_domain,
        action_items=action_items,
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
            
            # Merge IRP: use rule's impact/likelihood as reliable baseline, take max safeguard_score
            merged_safeguard = max(finding.safeguard_score, llm_finding.safeguard_score)
            merged_irp = _compute_irp(finding.impact, finding.likelihood, merged_safeguard)

            # Create a merged finding with hybrid confidence
            merged_finding = finding.model_copy(update={
                "confidence": hybrid_confidence,
                "needs_review": hybrid_confidence < 0.6,
                "safeguard_score": merged_safeguard,
                "irp_score": merged_irp,
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
    """Quick mode: detect only high and critical severity findings.

    Empty ``jurisdictions`` == "no filter" — global-tool contract per Fix 4.
    """
    from .rules import PATTERNS

    jurisdiction_filter = set(jurisdictions) if jurisdictions else None
    findings: List[Finding] = []
    for pattern in PATTERNS:
        # Only include High and Critical severity patterns
        if pattern.severity not in ["High", "Critical"]:
            continue

        # Check if pattern applies to any requested jurisdiction. Empty
        # requested list means "no filter" (global tool, unknown user location).
        if jurisdiction_filter is not None and not any(
            j in pattern.jurisdictions for j in jurisdiction_filter
        ):
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

                    # Seed IRP fields from category defaults
                    irp_impact, irp_likelihood, irp_safeguard, irp_score = _seed_irp(pattern.category)

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
                        impact=irp_impact,
                        likelihood=irp_likelihood,
                        safeguard_score=irp_safeguard,
                        irp_score=irp_score,
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
    context: Optional[List[ContextChip]] = None,
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
            context=context,
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
