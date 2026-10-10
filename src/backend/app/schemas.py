from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, get_args

from pydantic import BaseModel, Field, StrictFloat, field_validator, model_validator

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

# Issue #195: why an analysis does or does not carry an LLM answer. One value
# per outcome of the LLM step, so a LocalAI outage, a misbehaving model and
# our own code falling back on every call are told apart:
#   ok                        an answer arrived and passed ``LLMAnswer``
#   fallback_llm_unreachable  no HTTP response (httpx TransportError, incl.
#                             every timeout): LocalAI is down or unreachable
#   fallback_llm_invalid      a 2xx response whose answer failed parsing or
#                             ``LLMAnswer`` validation
#   fallback_llm_error        anything else inside the HR5 boundary: a non-2xx
#                             reply, model selection, prompt build, request
#                             encoding, an unforeseen exception
#   disabled                  the LLM step was not run (quick mode)
#   unknown                   rows stored before this field existed; a fresh
#                             analysis never reports it
LLMStatus = Literal[
    "ok",
    "fallback_llm_unreachable",
    "fallback_llm_invalid",
    "fallback_llm_error",
    "disabled",
    "unknown",
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


# Plain decimal float: optional sign, digits, optional fraction; no "_", "e", nan.
_PLAIN_DECIMAL = re.compile(r"[+-]?(\d+(\.\d*)?|\.\d+)")


class LLMAnswer(BaseModel):
    """The shape of the LLM's JSON answer, checked before anything uses it.

    Issue #91 F2 round (security M1, HR5): ``LocalAIClient.analyze()``
    validates the parsed answer against this model inside its one fallback
    boundary, so it returns either ``None`` (rules-only) or an answer that
    ``analyze_text`` can use unchecked: ``findings`` must be a list,
    ``summary`` a string or null, ``overall_confidence`` a finite number or
    null (no NaN/Infinity). The caller uses the validated ``model_dump()``,
    never the raw parse. Each finding item is still parsed
    into ``Finding`` one by one in ``analyze_text``, which skips bad items.
    Every string in the answer, keys included, must be valid UTF-8, or the
    response could not be serialised (a lone surrogate from a JSON escape).
    """

    findings: List[Any] = Field(default_factory=list)
    summary: Optional[str] = None
    overall_confidence: Optional[float] = Field(default=None, allow_inf_nan=False)

    @field_validator("overall_confidence", mode="before")
    @classmethod
    def _confidence_is_plain_number(cls, value: Any) -> Any:
        # Pydantic's lax float accepts True (as 1.0) and "1_0" (as 10.0);
        # neither is a confidence the model meant. Strings must be plain
        # decimals, so "0.9" still parses as 0.9 (round-trip M8 row).
        if isinstance(value, bool):
            raise ValueError("overall_confidence must not be a boolean")
        if isinstance(value, str) and not _PLAIN_DECIMAL.fullmatch(value.strip()):
            raise ValueError("overall_confidence string must be a plain decimal")
        return value

    @model_validator(mode="after")
    def _strings_are_utf8(self) -> "LLMAnswer":
        # ensure_ascii=False keeps a lone surrogate as a character, so the
        # one UTF-8 rule sees it (with escaping on, it would pass as "\\ud800").
        if not is_valid_utf8(json.dumps(self.model_dump(), ensure_ascii=False)):
            raise ValueError("LLM answer holds a string that is not valid UTF-8")
        return self


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


# Corpus status marking synthetic, non-authoritative passages. Lives here (not
# in services.legal_kb) so prompts.py can share it without an import cycle
# (localai -> prompts -> legal_kb -> localai); legal_kb re-exports it.
PLACEHOLDER_STATUS = "placeholder"
NOT_YET_IN_FORCE_STATUS = "not_yet_in_force"

# Issue #91 round-2 (grumpy #2 / security R2-F4): the ONLY corpus statuses
# that count as authoritative law. An allowlist, so it fails closed: a null,
# unknown or misspelled status (or "placeholder") is never authoritative.
# Vocabulary source: the sibling legal-corpus-ingester resolves a legal
# instrument's status in src/legal_corpus_ingester/pipeline/status_rules.py
# (resolve_status), whose values are "not_yet_in_force" and "in_force". Only
# "in_force" means verified text of law currently in force. Compare against
# normalise_corpus_status(...) output (stripped, lower-case). Round 8
# (security F3): moved here from services.legal_kb (which re-exports it) so
# the analyzer flag and the prompt labels read ONE allowlist.
AUTHORITATIVE_STATUSES = frozenset({"in_force"})

# Round 8 (security F2 / F3, grumpy 2): every reason a retrieved passage is
# NOT authoritative law, with the label the LLM prompt puts in front of it.
# One table, two readers: prompts.build_user_prompt prints the labels (and
# names every marker in its NEVER-cite sentence), and
# analyzer._grounding_is_authoritative counts a citation only when it has no
# label at all. (marker, advice) pairs; the label is "[<marker> — <advice>]".
PASSAGE_LABELS = {
    "placeholder": ("UNVERIFIED PLACEHOLDER", "not real statute text, do not cite as authoritative"),
    "not_yet_in_force": ("NOT YET IN FORCE", "not current law, do not cite as current law"),
    "unverified_provenance": ("UNVERIFIED PROVENANCE", "status unknown, do not cite as authoritative"),
    # Round 10 (security F1, grumpy 1): a jurisdiction that is not in
    # KNOWN_JURISDICTIONS (null, blank, junk, a typo) is unknown provenance,
    # in every mode, SO5 global mode (no jurisdictions requested) included.
    "unknown_jurisdiction": (
        "UNKNOWN JURISDICTION",
        "jurisdiction not recorded or not recognised, do not cite as authoritative",
    ),
    "out_of_jurisdiction": (
        "OUT OF JURISDICTION",
        "not law of the requested jurisdictions, do not cite as their legal basis",
    ),
}


def normalise_corpus_status(raw: Any) -> Optional[str]:
    """Strip + lower-case a legal-corpus status; non-string / blank -> None.

    Issue #91 (grumpy F2): corpus files declare ``# Status: PLACEHOLDER`` in
    upper case and the parser keeps meta values verbatim. Single source of
    truth for both the analyzer (authoritative-flag computation) and the
    ``LegalCitation`` validator (stored rows, any other producer).
    """
    if not isinstance(raw, str):
        return None
    normalised = raw.strip().lower()
    return normalised or None


def has_format_character(text: str) -> bool:
    """True when ``text`` holds a Unicode format character (category Cf).

    Cf covers invisible characters such as bidi overrides (U+202E), zero-width
    characters (U+200B, U+200D, U+FEFF) and the tag block (U+E0000-U+E007F,
    the "ASCII smuggling" channel for hidden LLM instructions).
    """
    return any(unicodedata.category(ch) == "Cf" for ch in text)


def is_valid_utf8(value: str) -> bool:
    """True when ``value`` encodes as UTF-8, i.e. it holds no lone surrogate.

    Round 12 (security F2): ``json.loads`` turns the escape ``"\\ud800"`` into
    a lone surrogate, which is a legal Python ``str`` but can't be encoded.
    It used to pass validation and then raise ``UnicodeEncodeError`` when
    httpx encoded the LLM request body. The one UTF-8 rule: the legal-KB
    chunk validator and ``LLMAnswer`` both use it.
    """
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def normalise_jurisdiction(raw: Any) -> Optional[str]:
    """Strip + lower-case a jurisdiction code; non-string / blank -> None.

    Round 8 (grumpy 2): the single comparison form for "is this citation for
    a requested jurisdiction", shared by legal_kb's jurisdiction filter and
    passage_label_keys.

    Round 11 (security N1): a code holding a format (Cf) character is
    REJECTED (None, so UNKNOWN JURISDICTION), never stripped. Stripping would
    widen the allowlist: an invisibly padded "GDPR<U+200B>" from crafted
    metadata would count as known. Rejecting fails closed whatever the
    allowlist holds, and the UNKNOWN label tells the LLM not to rely on it.
    """
    code = normalise_corpus_status(raw)
    if code is not None and has_format_character(code):
        return None
    return code


# Round 11 (grumpy LOW / security F2): the ONE section-title normaliser, run by
# legal_kb._validate_chunks on every chunk at build and at load, and by the
# prompt header renderer. "[" / "]" become "(" / ")" so a legitimate title such
# as "Article 6 [Lawfulness]" or "Section 4 [Repealed]" builds and loads
# instead of bricking grounding; format (Cf) characters are STRIPPED (security
# N1) because they are invisible: removing them keeps the visible title intact,
# drops any hidden tag-character payload, and doesn't reject a whole corpus
# over one stray zero-width joiner.
_SECTION_BRACKETS = str.maketrans({"[": "(", "]": ")"})


def normalise_section_title(raw: str) -> str:
    """``raw`` with ``[``/``]`` mapped to ``(``/``)`` and Cf characters removed."""
    visible = "".join(ch for ch in raw if unicodedata.category(ch) != "Cf")
    return visible.translate(_SECTION_BRACKETS)


# Round 10 (security F1 / F2, grumpy 1): the ONLY definition of a "known"
# jurisdiction, derived from the Jurisdiction Literal through the shared
# normaliser (SO6 schema-derived allowlist). Anything else, whether null,
# blank, zero-width, "None", "unknown", "N/A", "xx-fake" or a typo like
# "GPDR", is UNKNOWN JURISDICTION and never authoritative. A corpus code the
# Literal lacks stays unknown until the Literal gains it (fails closed).
def _build_canonical_jurisdictions(codes: Any) -> Dict[str, str]:
    """Map each code's normalised form to the code itself; raise on drift.

    Import-time drift guard: every code must normalise to a distinct,
    non-empty key, or "known" would no longer mean "one of the Literal's codes".
    """
    canonical: Dict[str, str] = {}
    for code in codes:
        key = normalise_jurisdiction(code)
        if key is None or key in canonical:
            raise RuntimeError(
                f"KNOWN_JURISDICTIONS drifted from the Jurisdiction Literal: {code!r} "
                "is blank or normalises to the same key as another code"
            )
        canonical[key] = code
    return canonical


_CANONICAL_JURISDICTIONS = _build_canonical_jurisdictions(get_args(Jurisdiction))
KNOWN_JURISDICTIONS = frozenset(_CANONICAL_JURISDICTIONS)

# Round 10 (grumpy NIT): the ONE phrase every doc uses for a jurisdiction that
# blocks authority. AnalysisPayload's description is built from it, and the
# doc-contract test checks LIB-API API6, TECH_SPEC 5.1.5 and the analyzer
# docstring against it.
UNKNOWN_JURISDICTION_PHRASE = "a null, blank or unrecognised jurisdiction"
KNOWN_JURISDICTION_PHRASE = "a known, requested jurisdiction (any known one when none was requested)"


def canonical_jurisdiction(raw: Any) -> Optional[str]:
    """The Jurisdiction Literal code for ``raw`` if it is known, else None.

    Known means ``normalise_jurisdiction(raw) in KNOWN_JURISDICTIONS``. The
    prompt header prints only this canonical code (or "Law"), never the raw
    value (round 10, security F2; see prompts.render_passage_header).
    """
    code = normalise_jurisdiction(raw)
    if code not in KNOWN_JURISDICTIONS:
        return None
    return _CANONICAL_JURISDICTIONS[code]


def passage_label_keys(status: Any, jurisdiction: Any, requested: Any) -> List[str]:
    """PASSAGE_LABELS keys that apply to one retrieved passage, in table order.

    ``requested`` is the analysis' jurisdiction list; empty means "no filter"
    (SO5 global mode), so any jurisdiction is in scope. A passage is
    authoritative law for this analysis only when the result is empty: its
    normalised status is in AUTHORITATIVE_STATUSES, its jurisdiction is in
    KNOWN_JURISDICTIONS and, when jurisdictions were requested, it is one of them. Round 8 (security F2,
    grumpy 2): the legal-KB fallback searches the full corpus when nothing
    matches the requested jurisdictions, so a GDPR passage can come back for
    a US-CA analysis; it is labelled out of jurisdiction, never authoritative.
    """
    keys: List[str] = []
    normalised = normalise_corpus_status(status)
    if normalised == PLACEHOLDER_STATUS:
        keys.append("placeholder")
    elif normalised == NOT_YET_IN_FORCE_STATUS:
        keys.append("not_yet_in_force")
    elif normalised not in AUTHORITATIVE_STATUSES:
        keys.append("unverified_provenance")
    # Round 10 (security F1, grumpy 1): "known" is membership of the
    # KNOWN_JURISDICTIONS allowlist, not "non-blank". An unknown jurisdiction
    # is labelled whatever was requested, so it can't make a global-mode
    # analysis authoritative; a known one is out of jurisdiction when it is
    # not among those requested.
    code = normalise_jurisdiction(jurisdiction)
    wanted = {normalise_jurisdiction(j) for j in (requested or [])} - {None}
    if code not in KNOWN_JURISDICTIONS:
        keys.append("unknown_jurisdiction")
    elif wanted and code not in wanted:
        keys.append("out_of_jurisdiction")
    return keys


def passage_label(key: str) -> str:
    """The prompt label for one PASSAGE_LABELS key."""
    marker, advice = PASSAGE_LABELS[key]
    return f"[{marker} — {advice}]"


class LegalCitation(BaseModel):
    """One legal-KB passage supplied to the LLM prompt (issue #91)."""

    jurisdiction: Optional[str] = None
    law: Optional[str] = None
    section: Optional[str] = None
    # Kept as a normalised free-form string rather than a Literal: the status
    # vocabulary is owned by the corpus / legal-corpus-ingester and is open
    # ("placeholder" here; "in_force" / "not_yet_in_force" from the ingester;
    # authority is decided by AUTHORITATIVE_STATUSES above), so a Literal would turn a new
    # corpus status into a response-validation 500. Normalisation (strip +
    # lower-case) happens here as well as in the analyzer so stored rows and
    # any other producer can never expose "PLACEHOLDER" (grumpy F2).
    status: Optional[str] = Field(
        default=None,
        description=(
            "Corpus status of the passage, always lower-case. 'placeholder' marks "
            "synthetic, non-authoritative text that is NOT real statute text; "
            "only 'in_force' counts towards legal_grounding_authoritative. "
            "Null when the corpus file declared no status (never authoritative)."
        ),
    )
    score: Optional[float] = Field(
        default=None,
        description="Reciprocal Rank Fusion score (rank-based relevance, not a probability).",
    )

    @field_validator("status", mode="before")
    @classmethod
    def _normalise_status(cls, v: Any) -> Optional[str]:
        return normalise_corpus_status(v)


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
    # Issue #91: distinguishes "grounded in the legal KB" from "ran without
    # it". Defaults to False so rows stored before this field existed still
    # load (and are honestly reported as ungrounded).
    legal_grounding: bool = Field(
        default=False,
        description=(
            "True only when the legal knowledge-base index loaded and retrieval ran "
            "against it (a search whose candidates all fall below the relevance "
            "floor is still grounded, with an empty legal_context). It reflects "
            "retrieval only, NOT legal authority: it is also True when every "
            "retrieved passage is placeholder text; see "
            "legal_grounding_authoritative. False when the index is missing or "
            "empty, retrieval errored (including a broken embedder), or the "
            "analysis ran in quick mode; legal_context is then always empty and "
            "no legal-KB passages reached the LLM prompt."
        ),
    )
    # Issue #91 round-1 (grumpy F3 / security F2): the shipped corpus is all
    # placeholder text, so legal_grounding alone overstates authority.
    legal_grounding_authoritative: bool = Field(
        default=False,
        description=(
            "True only when legal_grounding is True, the relevance floor "
            "LEGAL_KB_MIN_SCORE is configured, AND at least one legal_context "
            "citation has an allow-listed status ('in_force') AND "
            f"{KNOWN_JURISDICTION_PHRASE}. Fails closed: a null, unknown, "
            "'not_yet_in_force' or 'placeholder' status is never authoritative, "
            f"and neither is a passage with {UNKNOWN_JURISDICTION_PHRASE} or one "
            "from another jurisdiction (the legal KB falls back to the full corpus when no "
            "passage matches the requested ones). Always False while no relevance "
            "floor is set, when nothing was retrieved, or when the analysis is "
            "ungrounded. Clients must use this field, not legal_grounding, "
            "before presenting an analysis as grounded in law."
        ),
    )
    # Issue #195: additive, with a default so rows stored before the field
    # existed still load (as "unknown", never as "ok").
    llm_status: LLMStatus = Field(
        default="unknown",
        description=(
            "Outcome of the LLM step: 'ok' (a validated answer was used), "
            "'fallback_llm_unreachable' (LocalAI gave no HTTP response), "
            "'fallback_llm_invalid' (a 2xx answer failed parsing or validation), "
            "'fallback_llm_error' (any other failure, e.g. a non-2xx reply or an "
            "internal error), 'disabled' (quick mode, no LLM call). Every "
            "fallback value means rules-only findings with reduced confidence "
            "(HR5). 'unknown' only appears on analyses stored before this field "
            "existed."
        ),
    )
    legal_context: List[LegalCitation] = Field(
        default_factory=list,
        description=(
            "Legal-KB passages retrieved for this analysis and supplied to the LLM "
            "prompt (metadata only, no passage text). Always empty when "
            "legal_grounding is False. Check each citation's status and "
            "jurisdiction: only an 'in_force' passage for a requested "
            "jurisdiction is authoritative law."
        ),
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
