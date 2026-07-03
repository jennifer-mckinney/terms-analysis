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
  6. Language heuristic (French/German/Italian/Spanish/Dutch → GDPR default).

Deduplicates hits while preserving insertion order, so higher-precision signals
appear first in the result. Falls back to ["US-CA", "GDPR"] when nothing fires
and reports ``location_needed=True`` so the intake can prompt the user.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

from ..schemas import DocType, IndustryProfile, InferResponse, Jurisdiction


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
_STATUTE_PATTERNS: list[tuple[str, list[Jurisdiction], str]] = [
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

# CPA is Colorado only when Colorado is otherwise implicated; handled separately
# so a Canadian "CPA" (chartered accountant) doesn't false-trigger.
_CPA_PATTERN = re.compile(r"\bCPA\b", re.IGNORECASE)
_COLORADO_HINT = re.compile(r"\bColorado\b|\bC\.R\.S\.\b|\bSB\s*205\b", re.IGNORECASE)


# ── Regulatory body → jurisdiction ───────────────────────────────────────────
_REG_BODY_PATTERNS: list[tuple[str, list[Jurisdiction], str]] = [
    (r"\bCNIL\b", ["GDPR"], "CNIL (France)"),
    (r"\bICO\b", ["UK-GDPR"], "ICO (UK)"),
    (r"\bAEPD\b", ["GDPR"], "AEPD (Spain)"),
    (r"\bGarante\b", ["GDPR"], "Garante (Italy)"),
    (r"\bANPD\b", ["LGPD"], "ANPD (Brazil)"),
    (r"\bOAIC\b", ["APP"], "OAIC (Australia)"),
    (r"\bFTC\b", ["US-FED"], "FTC (US)"),
]


# ── Geographic scope phrases → jurisdiction ──────────────────────────────────
_GEO_PATTERNS: list[tuple[str, list[Jurisdiction], str]] = [
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

    # 2. Explicit statutes
    if text:
        for pattern, jurisdictions, label in _STATUTE_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                signals["statute"].append(label)
                ordered.extend(jurisdictions)
        # CPA is Colorado only in a Colorado context
        if _CPA_PATTERN.search(text) and _COLORADO_HINT.search(text):
            signals["statute"].append("CPA (Colorado context)")
            ordered.append("US-CO")

    # 3. Regulatory bodies
    if text:
        for pattern, jurisdictions, label in _REG_BODY_PATTERNS:
            if re.search(pattern, text):
                signals["regulator"].append(label)
                ordered.extend(jurisdictions)

    # 4. Geographic scope phrases
    if text:
        for pattern, jurisdictions, label in _GEO_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
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

    # Order matters: check more-specific patterns first.
    if re.search(r"\b(hipaa|patient|medical|health(?:care)?)\b", corpus):
        return "Healthcare"
    if re.search(r"\b(bank|credit|finance|financial|investment)\b", corpus):
        return "Finance"
    if re.search(r"\b(school|university|student|learning|educat\w*)\b", corpus) or ".edu" in hostname:
        return "Education"
    if re.search(r"\b(game|gaming|play(?:er)?s?)\b", corpus):
        return "Gaming"
    if re.search(
        r"\b(ai|ml|machine learning|chatbot|openai|anthropic|large language model|llm)\b",
        corpus,
    ):
        return "AI / Tech Platform"
    if re.search(r"\b(shop|store|commerce|retail|checkout|cart)\b", corpus):
        return "Retail"

    return "General"


def infer_all(url: Optional[str], text: Optional[str]) -> InferResponse:
    """Combined inference.

    Returns an ``InferResponse`` with jurisdictions, doc_type, industry,
    ``location_needed`` (True when nothing was detected), and
    ``detected_signals`` for downstream transparency in the UI.
    """
    jurisdictions, signals = infer_jurisdictions(url, text)
    doc_type = infer_doc_type(url, text)
    industry = infer_industry(url, text)

    # location_needed: True when we had to fall back to defaults.
    location_needed = len(jurisdictions) == 0
    if location_needed:
        jurisdictions = ["US-CA", "GDPR"]
        signals["fallback"] = ["default US-CA + GDPR (no location signals)"]

    # Drop empty signal buckets so the response stays compact.
    trimmed_signals = {k: v for k, v in signals.items() if v}

    return InferResponse(
        jurisdictions=jurisdictions,
        doc_type=doc_type,
        industry=industry,
        location_needed=location_needed,
        detected_signals=trimmed_signals,
    )
