from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, StrictFloat, field_validator

Jurisdiction = Literal[
    "US-CA",
    "US-FED",
    "US-NY",
    "US-TX",
    "US-VA",
    "US-CO",
    "US-CT",
    "US-IL",
    "US-NJ",
    "US-MN",
    "US-OR",
    "GDPR",
    "UK-GDPR",
    "LGPD",
    "PIPEDA",
    "CA-QC",
    "POPIA",
    "PDPA-KE",
    "DPDP",
    "APPI",
    "PIPA",
    "APP",
    "PDPA-TH",
    "NDPR",
    "ICCPR-17",
    "COE-108",
    "EU-AI-ACT",
    "COE-AI-225",
    "OECD-AI",
    "UNESCO-AI",
]
Severity = Literal["Low", "Medium", "High", "Critical"]

# ── Canonical finding categories ─────────────────────────────────────────────
# Single source of truth for category strings used across ``rules.py``,
# ``analyzer.py``, and ``context.py``. Modules that key dicts on category
# names must validate their keys against this set at import time so drift
# fails loudly instead of silently mis-mapping.
#
# NOTE: ``Sale/Share`` (canonical, emitted by rules) and ``Data Sale / Sharing``
# (defensive alias for LLM-generated variants) both live here on purpose.
CATEGORIES: frozenset[str] = frozenset({
    # Data-collection categories
    "Sensitive Data",
    "Sensitive Data / Opt-Out",
    "Biometric Data",
    "Health Data",
    "Financial Data",
    "Children's Privacy",
    "Collection Notice",
    "Minors",
    # Data-use categories
    "AI Training",
    "AI Training Opt-Out",
    "AI Training (Opt-Out)",  # alias used by ``_CATEGORY_IRP_DEFAULTS``
    "Sale/Share",
    "Data Sale / Sharing",  # LLM alias
    "Third-Party Sharing",  # dormant (Option Z drift-1) — reserved for future rules
    "Sub-processors",  # dormant (Option Z drift-1) — DPA-specific processor chain
    "Tracking / Profiling",
    "Tracking & Consent",
    "Marketing Communications",
    "Purpose Limitation",
    "ADM",
    "Automated Decision-Making",
    "Consequential AI Decisions",
    "High-Risk AI",
    "Prohibited AI",
    "GPAI / Generative AI",
    "AI-Generated Content",
    "Algorithmic Accountability",
    "Human Oversight",
    "AI Non-Discrimination",
    "Transparency",  # dormant (Option Z drift-1) — AI/tech platform disclosure duty
    # Terms-of-use categories
    "Liability",
    "Unilateral Changes",
    "Arbitration / Dispute",
    "Dark Patterns",
    "Deceptive Practices",
    "Retention",
    "Breach Notification",
    "Data Security",
    "Consent",
    "Intellectual Property",  # dormant (Option Z drift-1) — ToS IP/license clauses
    "In-App Purchases",  # dormant (Option Z drift-1) — gaming/microtransaction clauses
    # Privacy-rights categories
    "User Rights",
    "Data Rights",
    "Individual Rights",
    "Privacy Rights",
    "Cross-Border Transfer",
    "Data Transfer",  # dormant (Option Z drift-1) — DPA-specific transfer mechanism
    "COPPA Compliance",
    "HIPAA Compliance",
    "FERPA Compliance",
    "PCI DSS Compliance",
    "PIPEDA Consent",
    "LGPD Rights",
    "APPI Disclosure",
    "DPDP Consent",
    "POPIA Processing",
    "PIPA Processing",
    "APP Privacy",
    "UK Data Rights",
    "Privacy as Human Right",
    "Serious Privacy Invasion",
})

DocType = Literal[
    "Privacy Policy",
    "Terms of Service",
    "Cookie Policy",
    "Data Processing Agreement",
    "Combined",
]

IndustryProfile = Literal[
    "General",
    "Healthcare",
    "Finance",
    "Education",
    "Social Media",
    "AI / Tech Platform",
    "Gaming",
    "Retail",
]

# Context chips: capture the reader's stated intent for the intake (Streamlit v2).
# Used to bias which findings surface first and to swap verdict copy.
ContextChip = Literal[
    "want_understand",   # "I want to understand what I'm agreeing to"
    "for_child",         # "Something my child wants to use"
    "for_care",          # "Helping someone I care about with this"
    "for_work",          # "For work / business use"
    "just_curious",      # "Just curious"
]


# Re-export from canonical home for backwards-compatibility
from .exceptions import CorpusMismatchError as CorpusMismatchError  # noqa: F401


class Evidence(BaseModel):
    line_start: int = Field(..., ge=1)
    line_end: int = Field(..., ge=1)
    legal_basis: List[str] = Field(default_factory=list)
    start_offset: Optional[int] = Field(None, ge=0, description="Character offset where finding starts in text")
    end_offset: Optional[int] = Field(None, ge=0, description="Character offset where finding ends in text")
    context_before: Optional[str] = Field(None, description="2-3 sentences before the finding")
    context_after: Optional[str] = Field(None, description="2-3 sentences after the finding")


class Finding(BaseModel):
    category: str
    severity: Severity
    confidence: float = Field(..., ge=0.0, le=1.0)
    excerpt: str
    explanation: str
    jurisdictions: List[Jurisdiction]
    evidence: Evidence
    needs_review: bool = Field(False, description="Flag when confidence < 0.6 or finding needs manual review")
    source_document: Optional[str] = Field(default=None, description="Document source for batch analysis")
    impact: int = Field(default=2, ge=1, le=5, description="Potential harm if clause enforced (1=trivial, 5=catastrophic)")
    likelihood: int = Field(default=3, ge=1, le=5, description="Probability clause activates (1=extremely rare, 5=automatic/routine)")
    safeguard_score: int = Field(default=0, ge=0, le=5, description="Existing mitigations offsetting risk (0=none, 5=full mitigation)")
    irp_score: Optional[float] = Field(None, ge=0.0, le=1.0, description="IRP composite: 0.5*(impact/5)+0.4*(likelihood/5)-0.3*(safeguard_score/5), clamped to [0,1]")


class AnalyzeRequest(BaseModel):
    text: str = Field(..., min_length=1)
    name: Optional[str] = None
    doc_type: Optional[DocType] = None
    industry: Optional[IndustryProfile] = None
    source_url: Optional[str] = None
    jurisdictions: List[Jurisdiction] = Field(default_factory=list)
    mode: Literal["full", "quick"] = Field(default="full", description="Analysis mode: 'full' for complete analysis, 'quick' for high-severity rules only")
    context: List[ContextChip] = Field(default_factory=list, description="Context chip selections from intake (biases top-things surfacing)")

    @field_validator("source_url")
    @classmethod
    def _validate_source_url_scheme(cls, v: Optional[str]) -> Optional[str]:
        # Defense-in-depth against ``javascript:`` (and other non-web) schemes
        # that survive ``html.escape()`` intact and would execute if rendered
        # in an ``<a href>``. Mirrors ``WatchlistCreateRequest`` — see PR #34
        # security review HIGH-1.
        if v is None or v == "":
            return v
        from urllib.parse import urlparse
        parsed = urlparse(v)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("source_url must use http or https scheme")
        if not parsed.hostname:
            raise ValueError("source_url must include a valid hostname")
        return v


class AnalyzeUrlRequest(BaseModel):
    url: str = Field(..., min_length=4)
    name: Optional[str] = None
    doc_type: Optional[DocType] = None
    industry: Optional[IndustryProfile] = None
    jurisdictions: List[Jurisdiction] = Field(default_factory=list)
    mode: Literal["full", "quick"] = Field(default="full", description="Analysis mode: 'full' for complete analysis, 'quick' for high-severity rules only")
    context: List[ContextChip] = Field(default_factory=list, description="Context chip selections from intake (biases top-things surfacing)")

    @field_validator("url")
    @classmethod
    def _validate_url_scheme(cls, v: str) -> str:
        # See ``AnalyzeRequest._validate_source_url_scheme`` — reject
        # ``javascript:`` and other non-http(s) schemes before they reach the
        # fetch layer or get echoed back into rendered payloads. SSRF-target
        # rejection still happens downstream in ``ingest._validate_url``.
        from urllib.parse import urlparse
        parsed = urlparse(v)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("url must use http or https scheme")
        if not parsed.hostname:
            raise ValueError("url must include a valid hostname")
        return v


class AnalysisPayload(BaseModel):
    id: str
    name: Optional[str] = None
    doc_type: Optional[DocType] = None
    industry: Optional[IndustryProfile] = None
    source_url: Optional[str] = None
    document_text: Optional[str] = None
    line_offsets: List[int] = Field(default_factory=list)
    status: Literal["completed", "needs_review"]
    review_required: bool
    confidence: float = Field(..., ge=0.0, le=1.0)
    risk_score: float = Field(..., ge=0.0, le=10.0)
    grade: str
    created_at: datetime
    findings: List[Finding]
    summary: Optional[str] = None
    analysis_mode: str = Field(default="full", description="Mode used for this analysis")
    estimated_time: float = Field(default=0.0, description="Estimated execution time in seconds")
    action_readiness: Literal["Go", "Review", "Stop"] = Field(
        default="Review",
        description="High-level recommendation: Go (low risk, high completeness), Stop (high risk), Review (all else)",
    )
    completeness: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Fraction of expected policy sections detected (rights, retention, contact, opt-out, ADM, security, third-party, minors)",
    )
    context: List[ContextChip] = Field(default_factory=list, description="Context chips supplied on the analyze request")
    jurisdictions: List[Jurisdiction] = Field(
        default_factory=list,
        description="Jurisdiction codes the analysis was filtered against (echoes the request so the UI can display 'Rules applied for: ...').",
    )
    verdict_headline: Optional[str] = Field(default=None, description="Context-appropriate verdict sentence for the reader")
    verdict_label: Optional[str] = Field(default=None, description="Short context-appropriate verdict chip label")
    top_by_domain: dict[str, list[Finding]] = Field(
        default_factory=dict,
        description="Top findings grouped by domain (Data, Data use, Terms of use, Privacy rights). Max 2 per domain, 8 total.",
    )
    action_items: List[str] = Field(
        default_factory=list,
        description="Suggested reader-actionable next steps derived from findings + jurisdictions. Backend-generated so the frontend does not have to know the derivation rules.",
    )


class ReviewItemPayload(BaseModel):
    id: str
    analysis_id: str
    status: Literal["pending", "approved", "rejected"]
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ReviewUpdate(BaseModel):
    status: Literal["approved", "rejected"]
    notes: Optional[str] = None


class RubricScores(BaseModel):
    productIntegrity: float = Field(..., ge=0.0, le=10.0)
    legalSignalQuality: float = Field(..., ge=0.0, le=10.0)
    aiLawSignalQuality: float = Field(..., ge=0.0, le=10.0)
    privacySecurity: float = Field(..., ge=0.0, le=10.0)
    accessibilityUsability: float = Field(..., ge=0.0, le=10.0)
    visualIxd: float = Field(..., ge=0.0, le=10.0)
    performanceReliability: float = Field(..., ge=0.0, le=10.0)
    governanceReadiness: float = Field(..., ge=0.0, le=10.0)
    overall: float = Field(..., ge=0.0, le=10.0)


class AnalysisSummary(BaseModel):
    id: str
    name: Optional[str] = None
    doc_type: Optional[DocType] = None
    industry: Optional[IndustryProfile] = None
    source_url: Optional[str] = None
    status: Literal["completed", "needs_review"]
    confidence: float = Field(..., ge=0.0, le=1.0)
    risk_score: float = Field(..., ge=0.0, le=10.0)
    grade: str
    created_at: datetime


class WatchlistItemPayload(BaseModel):
    """Watchlist item response. ``user_id`` / ``check_frequency`` / ``enabled`` /
    ``notes`` / ``next_check_at`` are the OE-003 merged fields — see
    ``docs/reports/user-decision-brief-2026-07-03.md`` A3."""
    id: str
    vendor: str
    source_url: Optional[str] = None
    status: str
    last_checked: datetime
    changes_since: Optional[datetime] = None
    change_count: int
    risk_delta: Optional[StrictFloat] = None
    change_summary: Optional[str] = None
    # OE-003 merged fields (all optional on the response so old clients continue to parse):
    user_id: Optional[str] = None
    check_frequency: Optional[int] = Field(
        default=None,
        description="Per-item refresh cadence in seconds. Honored by ``_watchlist_loop_async``.",
    )
    enabled: Optional[bool] = Field(
        default=None,
        description="When False the background refresh loop skips this item. Boolean, not string (LE-010 fix).",
    )
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    next_check_at: Optional[datetime] = Field(
        default=None,
        description="Computed: last_checked + check_frequency. Null when the item is disabled.",
    )


class WatchlistCreateRequest(BaseModel):
    """Create a watchlist entry. Subject is ``vendor`` + ``source_url`` (not
    ``analysis_id``). Optional fields land from the OE-003 merge — see
    ``docs/reports/user-decision-brief-2026-07-03.md`` A3.
    """
    vendor: str = Field(..., min_length=1)
    source_url: Optional[str] = None
    # OE-003 merged optional fields (all default-backward-compatible so old callers keep working):
    user_id: Optional[str] = Field(
        default=None,
        max_length=255,
        pattern=r"^[a-zA-Z0-9@._\-]+$",
        description="Opaque user identifier; alphanumeric, @, ., _, - only. Nullable.",
    )
    check_frequency: Optional[int] = Field(
        default=None,
        ge=300,
        le=604800,
        description="Per-item refresh cadence in seconds (5 minutes to 7 days). When omitted, ``_watchlist_loop_async`` falls back to ``settings.watchlist_refresh_seconds``.",
    )
    enabled: Optional[bool] = Field(
        default=True,
        description="When False the background refresh loop skips this item.",
    )
    notes: Optional[str] = Field(
        default=None,
        max_length=1024,
        description="Free-text notes / tags (e.g. reference to a prior analysis id). Optional.",
    )

    @field_validator("source_url")
    @classmethod
    def validate_source_url_scheme(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        from urllib.parse import urlparse
        parsed = urlparse(v)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("source_url must use http or https scheme")
        if not parsed.hostname:
            raise ValueError("source_url must include a valid hostname")
        return v


class InferRequest(BaseModel):
    """Request to infer jurisdiction, doc_type, and industry from URL and/or text."""
    url: Optional[str] = Field(default=None, description="Source URL (used for TLD signals)")
    text: Optional[str] = Field(
        default=None,
        max_length=200_000,
        description="Policy text (used for statute / geographic / regulatory-body signals). Capped at 200k chars to bound cache and regex work.",
    )
    context: List[ContextChip] = Field(default_factory=list, description="Context chip selections from the intake")

    @field_validator("text")
    @classmethod
    def _validate_text_not_all_whitespace(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            return None
        return v


class InferResponse(BaseModel):
    """Response with inferred jurisdictions, doc_type, industry, and transparency signals."""
    jurisdictions: List[Jurisdiction] = Field(default_factory=list)
    doc_type: Optional[DocType] = None
    industry: Optional[IndustryProfile] = None
    location_needed: bool = Field(default=False, description="True if jurisdiction inference confidence is low and the intake should show the location Q")
    detected_signals: dict = Field(default_factory=dict, description="Human-readable list of which signals fired, for transparency")


class BatchItem(BaseModel):
    """Individual item for batch analysis (URL or file reference)"""
    url: Optional[str] = Field(default=None, description="URL to analyze")
    name: Optional[str] = Field(default=None, description="Display name for document")
    doc_type: Optional[DocType] = None

    @field_validator("url")
    @classmethod
    def _validate_url_scheme(cls, v: Optional[str]) -> Optional[str]:
        # Same defense as ``AnalyzeRequest`` / ``AnalyzeUrlRequest`` — reject
        # non-http(s) schemes at the schema layer.
        if v is None or v == "":
            return v
        from urllib.parse import urlparse
        parsed = urlparse(v)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("url must use http or https scheme")
        if not parsed.hostname:
            raise ValueError("url must include a valid hostname")
        return v


class AnalyzeBatchRequest(BaseModel):
    """Request for batch analysis of multiple documents"""
    items: List[BatchItem] = Field(..., min_items=1, description="Documents to analyze")
    industry: Optional[IndustryProfile] = None
    jurisdictions: List[Jurisdiction] = Field(default_factory=list)
    mode: Literal["full", "quick"] = Field(default="full", description="Analysis mode: 'full' for complete analysis, 'quick' for high-severity rules only")
    detect_cross_references: bool = Field(default=True, description="Detect references between documents")
    context: List[ContextChip] = Field(default_factory=list, description="Context chip selections from intake (biases top-things surfacing)")


class BatchAnalysisResult(BaseModel):
    """Combined result for batch analysis"""
    batch_id: str = Field(..., description="Unique batch analysis ID")
    analysis_mode: str
    items: List[AnalysisPayload] = Field(..., description="Results for each document")
    cross_references: List[dict] = Field(default_factory=list, description="Cross-references detected between documents")
    created_at: datetime


class PolicySnapshotPayload(BaseModel):
    """Policy snapshot with historical version information."""
    id: str
    url: str
    content_hash: str
    captured_at: datetime
    raw_text: Optional[str] = None  # Optional on list endpoints to save bandwidth


class PolicySnapshotListItem(BaseModel):
    """Lightweight version for listing snapshots."""
    id: str
    url: str
    content_hash: str
    captured_at: datetime


class DiffToken(BaseModel):
    """A token in a diff with position and type information."""
    token: str
    type: Literal["added", "removed", "unchanged"]
    line_number: Optional[int] = None
    severity: Literal["low", "medium", "high"] = "low"


class DiffResult(BaseModel):
    """Result of comparing two snapshots."""
    snapshot_1_id: str
    snapshot_2_id: str
    url: str
    created_at_1: datetime
    created_at_2: datetime
    added: List[DiffToken] = Field(default_factory=list)
    removed: List[DiffToken] = Field(default_factory=list)
    unchanged: List[DiffToken] = Field(default_factory=list)
    change_count: int
    severity_summary: dict = Field(default_factory=lambda: {"high": 0, "medium": 0, "low": 0})


# OE-003 (2026-07-03): ``PolicyWatchPayload`` and ``PolicyWatchCreateRequest``
# were deleted when ``PolicyWatch`` was merged into ``WatchlistItem``. Callers
# should use ``WatchlistItemPayload`` / ``WatchlistCreateRequest`` instead. The
# legacy ``/policy-watch/*`` HTTP paths return 308 redirects to ``/watchlist/*``
# for one deprecation cycle (Sunset: 2026-10-01) — see main.py.
