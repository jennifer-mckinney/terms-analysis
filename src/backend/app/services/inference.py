"""Inference service for jurisdictions, document type, and industry.

Phase 1 backend for the Streamlit v2 redesign (issue #19). Given a URL and/or
raw policy text, produce a best-guess of:
  - the jurisdictions in play (California CCPA, EU GDPR, UK-GDPR, etc.),
  - the document type (Privacy Policy, Terms of Service, etc.),
  - the industry profile (Social Media, Healthcare, Finance, etc.).

Signals are ranked by precision (highest to lowest):
  1. URL TLD lookup (country-coded second-level domains).
  2. Explicit statute mentions in text (CCPA, GDPR, LGPD, ...).
  3. Regulatory body mentions (ICO, CNIL, ANPD, ...).
  4. Geographic scope phrases ("California residents", "EEA data subjects", ...).
  5. Currency + language pairing (£ + UK phrase, € + European phrase).
  6. Language heuristic (French/German/Italian/Spanish/Dutch → GDPR).

Deduplicates hits while preserving insertion order, so higher-precision signals
appear first in the result. When nothing fires, returns an empty
``jurisdictions`` list and reports ``location_needed=True``. This is a global
tool: unknown-user location means "no filter", not "assume US-CA + GDPR".
"""

from __future__ import annotations

import hashlib
import logging
import re
from functools import lru_cache
from typing import Optional
from urllib.parse import urlparse

from ..schemas import DocType, IndustryProfile, InferResponse, Jurisdiction

logger = logging.getLogger(__name__)

# Cap defensively against runaway payloads. Mirrors ``InferRequest.text``
# max_length so the cache and downstream regex work are bounded.
_MAX_TEXT_LENGTH = 200_000

# lru_cache size for the compiled InferResponse. 128 entries * ~a few KB
# per response keeps the memory footprint bounded while covering typical
# Streamlit rerun churn.
_INFER_CACHE_SIZE = 128


# ── URL TLD → jurisdiction map ───────────────────────────────────────────────
# Longest suffix first so ".co.uk" matches before ".uk".
_TLD_JURISDICTIONS: list[tuple[str, list[Jurisdiction]]] = [
    (".co.uk", ["UK-GDPR"]),
    (".org.uk", ["UK-GDPR"]),
    (".gov.uk", ["UK-GDPR"]),
    (".ac.uk", ["UK-GDPR"]),
    (".uk", ["UK-GDPR"]),
    (".eu", ["GDPR"]),
    (".de", ["GDPR"]),
    (".fr", ["GDPR"]),
    (".it", ["GDPR"]),
    (".es", ["GDPR"]),
    (".nl", ["GDPR"]),
    (".se", ["GDPR"]),
    (".dk", ["GDPR"]),
    (".fi", ["GDPR"]),
    (".pl", ["GDPR"]),
    (".pt", ["GDPR"]),
    (".gr", ["GDPR"]),
    (".ie", ["GDPR"]),
    (".ca", ["PIPEDA"]),
    (".au", ["APP"]),
    (".br", ["LGPD"]),
    (".in", ["DPDP"]),
    (".jp", ["APPI"]),
    (".kr", ["PIPA"]),
    (".za", ["POPIA"]),
    (".mx", ["LGPD"]),
    (".ng", ["NDPR"]),
    (".ke", ["PDPA-KE"]),
    (".th", ["PDPA-TH"]),
]


# ── Statute mention patterns → jurisdiction(s) ───────────────────────────────
# Order matters only for the human-readable signal log; jurisdictions are
# de-duplicated later. Patterns are case-insensitive.
# NOTE: source pattern strings are kept in ``_STATUTE_PATTERN_SOURCES`` so
# tests can introspect them; compiled versions are built once at import time
# below (Fix 7: regex pre-compilation).
_STATUTE_PATTERN_SOURCES: list[tuple[str, list[Jurisdiction], str]] = [
    # California
    (r"\bCCPA\b", ["US-CA"], "CCPA"),
    (r"\bCalifornia Consumer Privacy Act\b", ["US-CA"], "California Consumer Privacy Act"),
    (r"\bCPRA\b", ["US-CA"], "CPRA"),
    (r"\bCalifornia Privacy Rights Act\b", ["US-CA"], "California Privacy Rights Act"),
    # EU GDPR
    (r"\bGDPR\b", ["GDPR"], "GDPR"),
    (r"\bGeneral Data Protection Regulation\b", ["GDPR"], "General Data Protection Regulation"),
    (r"Regulation \(EU\) 2016/679", ["GDPR"], "Regulation (EU) 2016/679"),
    # UK
    (r"\bUK GDPR\b", ["UK-GDPR"], "UK GDPR"),
    (r"\bData Protection Act 2018\b", ["UK-GDPR"], "Data Protection Act 2018"),
    # Canada
    (r"\bPIPEDA\b", ["PIPEDA"], "PIPEDA"),
    (r"\bPersonal Information Protection and Electronic Documents Act\b", ["PIPEDA"], "PIPEDA (full name)"),
    (r"\bLaw 25\b", ["CA-QC"], "Quebec Law 25"),
    (r"\bLoi 25\b", ["CA-QC"], "Loi 25 (Quebec)"),
    # LATAM
    (r"\bLGPD\b", ["LGPD"], "LGPD"),
    (r"\bLei Geral de Prote[cç][aã]o de Dados\b", ["LGPD"], "Lei Geral de Proteção de Dados"),
    # India
    (r"\bDPDP\b", ["DPDP"], "DPDP"),
    (r"\bDigital Personal Data Protection Act\b", ["DPDP"], "Digital Personal Data Protection Act"),
    # Japan / Korea
    (r"\bAPPI\b", ["APPI"], "APPI"),
    (r"\bPIPA\b", ["PIPA"], "PIPA"),
    # South Africa
    (r"\bPOPIA\b", ["POPIA"], "POPIA"),
    # Australia
    (r"\bPrivacy Act 1988\b", ["APP"], "Privacy Act 1988"),
    (r"\bAustralian Privacy Principles\b", ["APP"], "Australian Privacy Principles"),
    (r"\bAPPs?\b(?!I)", ["APP"], "Australian Privacy Principles (APP)"),
    # EU AI Act
    (r"\bEU AI Act\b", ["EU-AI-ACT"], "EU AI Act"),
    (r"Regulation \(EU\) 2024/1689", ["EU-AI-ACT"], "Regulation (EU) 2024/1689"),
    # US state laws
    (r"\bColorado AI Act\b", ["US-CO"], "Colorado AI Act"),
    (r"\bSB\s*205\b", ["US-CO"], "SB 205"),
    (r"\bSHIELD Act\b", ["US-NY"], "SHIELD Act"),
    (r"\bTDPSA\b", ["US-TX"], "TDPSA"),
    (r"\bVCDPA\b", ["US-VA"], "VCDPA"),
    (r"\bCTDPA\b", ["US-CT"], "CTDPA"),
    (r"\bBIPA\b", ["US-IL"], "BIPA"),
    (r"\bBiometric Information Privacy Act\b", ["US-IL"], "Biometric Information Privacy Act"),
    # US federal
    (r"\bCOPPA\b", ["US-FED"], "COPPA"),
    (r"\bHIPAA\b", ["US-FED"], "HIPAA"),
]

# Pre-compile the statute patterns once at import time so the hot path avoids
# repeated ``re.compile`` calls (Fix 7).
_STATUTE_PATTERNS: list[tuple[re.Pattern[str], list[Jurisdiction], str]] = [
    (re.compile(source, re.IGNORECASE), juris, label)
    for source, juris, label in _STATUTE_PATTERN_SOURCES
]

# CPA is Colorado only when Colorado is otherwise implicated; handled separately
# so a Canadian "CPA" (chartered accountant) doesn't false-trigger.
_CPA_PATTERN = re.compile(r"\bCPA\b", re.IGNORECASE)
_COLORADO_HINT = re.compile(r"\bColorado\b|\bC\.R\.S\.\b|\bSB\s*205\b", re.IGNORECASE)


# ── Regulatory body → jurisdiction ───────────────────────────────────────────
_REG_BODY_PATTERN_SOURCES: list[tuple[str, list[Jurisdiction], str]] = [
    (r"\bCNIL\b", ["GDPR"], "CNIL (France)"),
    (r"\bICO\b", ["UK-GDPR"], "ICO (UK)"),
    (r"\bAEPD\b", ["GDPR"], "AEPD (Spain)"),
    (r"\bGarante\b", ["GDPR"], "Garante (Italy)"),
    (r"\bANPD\b", ["LGPD"], "ANPD (Brazil)"),
    (r"\bOAIC\b", ["APP"], "OAIC (Australia)"),
    (r"\bFTC\b", ["US-FED"], "FTC (US)"),
]


# Regulator patterns compiled at import time (Fix 7).
# NOTE: the original code searched regulator patterns case-sensitive; preserve
# that behaviour by not passing IGNORECASE here.
_REG_BODY_PATTERNS: list[tuple[re.Pattern[str], list[Jurisdiction], str]] = [
    (re.compile(source), juris, label)
    for source, juris, label in _REG_BODY_PATTERN_SOURCES
]


# ── Geographic scope phrases → jurisdiction ──────────────────────────────────
_GEO_PATTERN_SOURCES: list[tuple[str, list[Jurisdiction], str]] = [
    (r"\bCalifornia residents?\b", ["US-CA"], "California residents"),
    (r"\bEEA data subjects?\b", ["GDPR"], "EEA data subjects"),
    (r"\bEuropean Economic Area\b", ["GDPR"], "European Economic Area"),
    (r"\bEU residents?\b", ["GDPR"], "EU residents"),
    (r"\bUK residents?\b", ["UK-GDPR"], "UK residents"),
    (r"\bBritish residents?\b", ["UK-GDPR"], "British residents"),
    (r"\bCanadian residents?\b", ["PIPEDA"], "Canadian residents"),
    (r"\bQuebec residents?\b", ["CA-QC"], "Quebec residents"),
    (r"\bIllinois residents?\b", ["US-IL"], "Illinois residents"),
    (r"\bNew York residents?\b", ["US-NY"], "New York residents"),
    (r"\bTexas residents?\b", ["US-TX"], "Texas residents"),
    (r"\bVirginia residents?\b", ["US-VA"], "Virginia residents"),
    (r"\bColorado residents?\b", ["US-CO"], "Colorado residents"),
    (r"\bConnecticut residents?\b", ["US-CT"], "Connecticut residents"),
    (r"\bAustralian residents?\b", ["APP"], "Australian residents"),
    (r"\bBrazilian residents?\b", ["LGPD"], "Brazilian residents"),
    (r"\bJapanese residents?\b", ["APPI"], "Japanese residents"),
]


# Geo patterns compiled once at import time (Fix 7).
_GEO_PATTERNS: list[tuple[re.Pattern[str], list[Jurisdiction], str]] = [
    (re.compile(source, re.IGNORECASE), juris, label)
    for source, juris, label in _GEO_PATTERN_SOURCES
]


# ── Currency + language pairing ──────────────────────────────────────────────
_EURO_HINT = re.compile(r"€")
_POUND_HINT = re.compile(r"£")
_EU_LANG_HINT = re.compile(
    r"\b(?:datenschutz|traitement des donn[eé]es|trattamento dei dati|"
    r"tratamiento de datos|persoonsgegevens|dataskydd)\b",
    re.IGNORECASE,
)
_UK_LANG_HINT = re.compile(
    r"\b(?:United Kingdom|Britain|British|Her Majesty|HM Government|"
    r"pounds sterling)\b",
    re.IGNORECASE,
)


# ── Language keyword heuristic (fallback → GDPR) ─────────────────────────────
_EU_LANGUAGE_KEYWORDS = [
    # French
    "confidentialité", "vie privée", "données personnelles",
    # German
    "datenschutz", "personenbezogene daten",
    # Italian
    "privacy", "dati personali", "informativa sulla privacy",
    # Spanish
    "política de privacidad", "datos personales", "protección de datos",
    # Dutch
    "privacyverklaring", "persoonsgegevens",
]


# ── Doc type inference paths ─────────────────────────────────────────────────
_DOC_TYPE_URL_MAP: list[tuple[str, DocType]] = [
    ("/privacy", "Privacy Policy"),
    ("/tos", "Terms of Service"),
    ("/terms-of-service", "Terms of Service"),
    ("/terms-of-use", "Terms of Service"),
    ("/terms_of_service", "Terms of Service"),
    ("/legal/terms", "Terms of Service"),
    ("/terms", "Terms of Service"),
    ("/cookie", "Cookie Policy"),
    ("/cookies", "Cookie Policy"),
    ("/dpa", "Data Processing Agreement"),
    ("/data-processing", "Data Processing Agreement"),
]


# ── Industry inference by domain ─────────────────────────────────────────────
_SOCIAL_MEDIA_DOMAINS = {
    "facebook.com", "instagram.com", "whatsapp.com", "meta.com",
    "x.com", "twitter.com", "tiktok.com", "snapchat.com",
    "linkedin.com", "reddit.com",
}

_AI_TECH_DOMAINS = {
    "openai.com", "anthropic.com", "perplexity.ai",
}


# ── Pre-compiled industry-classification regexes (Fix 7) ─────────────────────
_RE_INDUSTRY_HEALTHCARE = re.compile(r"\b(hipaa|patient|medical|health(?:care)?)\b")
_RE_INDUSTRY_FINANCE = re.compile(r"\b(bank|credit|finance|financial|investment)\b")
_RE_INDUSTRY_EDUCATION = re.compile(r"\b(school|university|student|learning|educat\w*)\b")
_RE_INDUSTRY_GAMING = re.compile(r"\b(game|gaming|play(?:er)?s?)\b")
_RE_INDUSTRY_AI = re.compile(
    r"\b(ai|ml|machine learning|chatbot|openai|anthropic|large language model|llm)\b"
)
_RE_INDUSTRY_RETAIL = re.compile(r"\b(shop|store|commerce|retail|checkout|cart)\b")


def _extract_hostname(url: Optional[str]) -> Optional[str]:
    """Return lowercased hostname (without leading ``www.``) or ``None``."""
    if not url:
        return None
    try:
        parsed = urlparse(url if "://" in url else f"http://{url}")
    except Exception:
        return None
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host or None


def _extract_path(url: Optional[str]) -> str:
    """Return the URL path portion (lowercased) or empty string."""
    if not url:
        return ""
    try:
        parsed = urlparse(url if "://" in url else f"http://{url}")
    except Exception:
        return ""
    return (parsed.path or "").lower()


def _dedup_preserve_order(items: list[Jurisdiction]) -> list[Jurisdiction]:
    """Return de-duplicated list while preserving first-seen order."""
    seen: set[Jurisdiction] = set()
    out: list[Jurisdiction] = []
    for j in items:
        if j not in seen:
            seen.add(j)
            out.append(j)
    return out


def infer_jurisdictions(
    url: Optional[str], text: Optional[str]
) -> tuple[list[Jurisdiction], dict]:
    """Return (list of inferred jurisdictions, dict of detected_signals for transparency).

    Signals are ordered by precision. When nothing fires the returned list is
    empty; callers use that to decide whether to prompt for a location.
    """
    ordered: list[Jurisdiction] = []
    signals: dict[str, list[str]] = {
        "tld": [],
        "statute": [],
        "regulator": [],
        "geography": [],
        "currency_language": [],
        "language_heuristic": [],
    }

    hostname = _extract_hostname(url)

    # 1. URL TLD
    if hostname:
        for suffix, jurisdictions in _TLD_JURISDICTIONS:
            if hostname.endswith(suffix):
                signals["tld"].append(f"{suffix} → {', '.join(jurisdictions)}")
                ordered.extend(jurisdictions)
                break  # only the longest-matching suffix

    # 2. Explicit statutes (patterns pre-compiled at module load — Fix 7)
    if text:
        for pattern, jurisdictions, label in _STATUTE_PATTERNS:
            if pattern.search(text):
                signals["statute"].append(label)
                ordered.extend(jurisdictions)
        # CPA is Colorado only in a Colorado context
        if _CPA_PATTERN.search(text) and _COLORADO_HINT.search(text):
            signals["statute"].append("CPA (Colorado context)")
            ordered.append("US-CO")

    # 3. Regulatory bodies (patterns pre-compiled — Fix 7)
    if text:
        for pattern, jurisdictions, label in _REG_BODY_PATTERNS:
            if pattern.search(text):
                signals["regulator"].append(label)
                ordered.extend(jurisdictions)

    # 4. Geographic scope phrases (patterns pre-compiled — Fix 7)
    if text:
        for pattern, jurisdictions, label in _GEO_PATTERNS:
            if pattern.search(text):
                signals["geography"].append(label)
                ordered.extend(jurisdictions)

    # 5. Currency + language pairing
    if text:
        if _EURO_HINT.search(text) and _EU_LANG_HINT.search(text):
            signals["currency_language"].append("€ + European language")
            ordered.append("GDPR")
        if _POUND_HINT.search(text) and _UK_LANG_HINT.search(text):
            signals["currency_language"].append("£ + UK phrase")
            ordered.append("UK-GDPR")

    # 6. Language keyword heuristic (only if we still have nothing)
    if text and not ordered:
        lowered = text.lower()
        hit_count = sum(1 for kw in _EU_LANGUAGE_KEYWORDS if kw in lowered)
        if hit_count >= 2:
            signals["language_heuristic"].append(
                f"{hit_count} EU-language keyword hits"
            )
            ordered.append("GDPR")

    return _dedup_preserve_order(ordered), signals


def infer_doc_type(
    url: Optional[str], text: Optional[str]
) -> Optional[DocType]:
    """Return the best-guess DocType or None.

    URL path is the strongest signal. If none matches, the text is scanned for
    obvious markers ("privacy policy" + "terms of service" → Combined, etc.).
    Defaults to "Privacy Policy" when at least one signal exists but is
    ambiguous; returns None only when neither URL nor text is supplied.
    """
    if not url and not text:
        return None

    path = _extract_path(url)
    for token, doc_type in _DOC_TYPE_URL_MAP:
        if token in path:
            return doc_type

    if text:
        lowered = text.lower()
        has_privacy = "privacy policy" in lowered or "personal information collected" in lowered
        has_tos = (
            "terms of service" in lowered
            or "you agree to" in lowered
            or "arbitration" in lowered
        )
        if has_privacy and has_tos:
            return "Combined"
        if has_tos and not has_privacy:
            return "Terms of Service"
        if has_privacy:
            return "Privacy Policy"

    # Default fallback when a URL was given but nothing matched.
    return "Privacy Policy"


def infer_industry(
    url: Optional[str], text: Optional[str]
) -> Optional[IndustryProfile]:
    """Return the best-guess IndustryProfile or None.

    Domain-based rules run first (Social Media, AI/Tech), then keyword rules on
    URL + text. Falls back to "General" when at least one signal is provided.
    """
    if not url and not text:
        return None

    hostname = _extract_hostname(url) or ""

    # 1. Domain-based lookups (most specific).
    if hostname in _SOCIAL_MEDIA_DOMAINS or any(
        hostname.endswith(f".{d}") for d in _SOCIAL_MEDIA_DOMAINS
    ):
        return "Social Media"
    if hostname in _AI_TECH_DOMAINS or any(
        hostname.endswith(f".{d}") for d in _AI_TECH_DOMAINS
    ):
        return "AI / Tech Platform"

    # 2. Government defaults to General
    if hostname.endswith(".gov") or ".gov." in hostname:
        return "General"

    # 3. Keyword rules across combined URL + text corpus.
    corpus_parts: list[str] = []
    if url:
        corpus_parts.append(url.lower())
    if text:
        # Cap text to keep the keyword scan cheap on very large policies.
        corpus_parts.append(text[:20000].lower())
    corpus = " ".join(corpus_parts)

    if not corpus:
        return "General"

    # Order matters: check more-specific patterns first. Patterns are
    # pre-compiled at module scope (Fix 7).
    if _RE_INDUSTRY_HEALTHCARE.search(corpus):
        return "Healthcare"
    if _RE_INDUSTRY_FINANCE.search(corpus):
        return "Finance"
    if _RE_INDUSTRY_EDUCATION.search(corpus) or ".edu" in hostname:
        return "Education"
    if _RE_INDUSTRY_GAMING.search(corpus):
        return "Gaming"
    if _RE_INDUSTRY_AI.search(corpus):
        return "AI / Tech Platform"
    if _RE_INDUSTRY_RETAIL.search(corpus):
        return "Retail"

    return "General"


def _infer_all_impl(url: Optional[str], text: Optional[str]) -> InferResponse:
    """Combined inference (uncached implementation).

    Returns an ``InferResponse`` with jurisdictions, doc_type, industry,
    ``location_needed`` (True when no jurisdiction signals were detected),
    and ``detected_signals`` for downstream transparency in the UI.

    **Global-tool contract:** when no jurisdiction signals fire, the returned
    ``jurisdictions`` list is empty (no US-CA + GDPR fallback). Downstream
    callers must interpret an empty list as "no filter" — the tool is used
    worldwide and cannot assume a default reader location.
    """
    jurisdictions, signals = infer_jurisdictions(url, text)
    doc_type = infer_doc_type(url, text)
    industry = infer_industry(url, text)

    # location_needed: True when nothing fired. We do NOT populate a default
    # jurisdiction list — see module docstring (global-tool rule).
    location_needed = len(jurisdictions) == 0
    if location_needed:
        signals["fallback"] = [
            "no signals detected — jurisdictions returned empty"
        ]
        logger.info(
            "inference_fallback",
            extra={
                "event": "infer_fallback",
                "url": url,
                "text_present": bool(text),
                "reason": "no_signals_detected",
            },
        )

    # Drop empty signal buckets so the response stays compact.
    trimmed_signals = {k: v for k, v in signals.items() if v}

    return InferResponse(
        jurisdictions=jurisdictions,
        doc_type=doc_type,
        industry=industry,
        location_needed=location_needed,
        detected_signals=trimmed_signals,
    )


@lru_cache(maxsize=_INFER_CACHE_SIZE)
def _infer_all_cached(
    url: Optional[str], text_hash: Optional[str], text: Optional[str]
) -> InferResponse:
    """Cache wrapper keyed on ``(url, sha256(text))``.

    ``text_hash`` is the actual cache key discriminator — ``text`` is passed
    through so the underlying implementation can reconstitute the response
    (patterns are matched against the full body, not the hash).
    """
    # ``text_hash`` unused inside — it exists purely to make the lru_cache
    # key stable and bounded even when the underlying text is very large.
    del text_hash
    return _infer_all_impl(url, text)


def infer_all(url: Optional[str], text: Optional[str]) -> InferResponse:
    """Cached combined inference.

    Streamlit reruns every widget interaction. Without a cache the backend
    would re-run every regex against the same policy body on every keypress;
    the ``lru_cache`` keyed on ``(url, sha256(text))`` collapses that back to
    one real call per unique input (Fix 1).

    Also defensively truncates oversized inputs (Fix 3) — the schema already
    enforces a ``max_length`` on ``InferRequest.text`` but this guards direct
    ``infer_all`` callers (evaluation scripts, tests) too.
    """
    # Fix 3: defensive text-length ceiling for direct callers.
    if text is not None and len(text) > _MAX_TEXT_LENGTH:
        text = text[:_MAX_TEXT_LENGTH]
    text_hash = (
        hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None
    )
    return _infer_all_cached(url, text_hash, text)
