from __future__ import annotations

import ipaddress
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[3]

# URL schemes the fetcher implements. ``url_fetch_allowed_schemes`` may narrow
# this set but never widen it (CodeQL py/full-ssrf).
URL_FETCH_SUPPORTED_SCHEMES = frozenset({"http", "https"})

# Default SSRF blocklist for the user-URL fetcher (ingest.fetch_url_text).
# Every resolved address, and any IPv4 address embedded in an IPv6 one
# (IPv4-mapped, IPv4-compatible, 6to4, Teredo, NAT64 64:ff9b::/96), is
# checked against this list. Override with URL_FETCH_BLOCKED_NETWORKS.
_DEFAULT_URL_FETCH_BLOCKED_NETWORKS = ",".join(
    (
        "0.0.0.0/8",  # "this network"; 0.0.0.0 reaches localhost on Linux
        "10.0.0.0/8",  # RFC 1918
        "100.64.0.0/10",  # CGNAT, RFC 6598
        "127.0.0.0/8",  # loopback
        "169.254.0.0/16",  # link-local, cloud metadata (169.254.169.254)
        "172.16.0.0/12",  # RFC 1918
        "192.0.0.0/24",  # IETF protocol assignments
        "192.0.2.0/24",  # TEST-NET-1
        "192.88.99.0/24",  # 6to4 relay anycast
        "192.168.0.0/16",  # RFC 1918
        "198.18.0.0/15",  # benchmarking
        "198.51.100.0/24",  # TEST-NET-2
        "203.0.113.0/24",  # TEST-NET-3
        "224.0.0.0/4",  # multicast
        "240.0.0.0/4",  # reserved, includes 255.255.255.255
        "::/96",  # unspecified (::), IPv4-compatible (deprecated)
        "::1/128",  # loopback
        "64:ff9b:1::/48",  # local-use NAT64
        "100::/64",  # discard-only
        "2001:db8::/32",  # documentation
        "fc00::/7",  # unique local (ULA)
        "fe80::/10",  # link-local
        "fec0::/10",  # site-local (deprecated)
        "ff00::/8",  # multicast
    )
)


def _split_env_list(name: str, default: str) -> List[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _data_dir() -> Path:
    default_dir = REPO_ROOT / "data"
    target = Path(os.getenv("TERMS_ANALYSIS_DATA_DIR", str(default_dir)))
    target.mkdir(parents=True, exist_ok=True)
    return target


def _parse_min_score(raw: Optional[str]) -> Optional[float]:
    """Parse LEGAL_KB_MIN_SCORE; unset/blank -> None (relevance floor disabled).

    Issue #91 round-2 (grumpy #5 / security R2-F5): ``float()`` alone accepted
    ``nan`` (``score >= nan`` is always False) and out-of-range values, which
    silently turned every retrieval into NO_MATCH. A set value must be a
    finite cosine in (-1, 1]; anything else raises at import, so a
    misconfigured floor fails startup instead of disabling the KB quietly.
    """
    if raw is None or not raw.strip():
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(
            f"LEGAL_KB_MIN_SCORE must be a number in (-1, 1], got {raw!r}"
        ) from exc
    # Round 8 (security F11): -1 is excluded. Cosine is never below -1, so a
    # floor of -1 keeps every candidate, exactly like the disabled floor, yet
    # it would open the legal_grounding_authoritative gate. Leave the
    # variable unset to disable the floor; a set floor must be in (-1, 1].
    if not math.isfinite(value) or not -1.0 < value <= 1.0:
        raise ValueError(
            f"LEGAL_KB_MIN_SCORE must be a finite number in (-1, 1] "
            f"(unset disables the floor), got {raw!r}"
        )
    return value


def _parse_top_k(raw: Optional[str]) -> int:
    """Parse LEGAL_KB_TOP_K; unset -> 5. Must be an integer >= 1.

    Round 8 (grumpy 6): ``int()`` alone accepted 0 and negatives, which made
    every retrieval return no chunks (NO_MATCH, "grounded, no relevant law")
    with the floor disabled. Anything else raises at import, so startup fails.
    """
    if raw is None:
        return 5
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise ValueError(f"LEGAL_KB_TOP_K must be an integer >= 1, got {raw!r}") from exc
    if value < 1:
        raise ValueError(f"LEGAL_KB_TOP_K must be an integer >= 1, got {raw!r}")
    return value


# Strict integer env format: ASCII digits only. ``int()`` alone would accept
# whitespace, ``_`` separators and non-ASCII digits (fullwidth, Arabic-Indic).
_ASCII_INT_RE = re.compile(r"[0-9]{1,9}")


def _env_int(name: str, default: str) -> int:
    """Parse an integer env var strictly; raise naming the variable.

    Range rules live in ``validate_security_settings`` so they also cover
    ``dataclasses.replace``.
    """
    raw = os.getenv(name, default)
    if not _ASCII_INT_RE.fullmatch(raw):
        raise ValueError(f"{name} must be a non-negative integer in ASCII digits")
    return int(raw)


@dataclass(frozen=True)
class Settings:
    # ── Inference backend ────────────────────────────────────────────────────
    # LocalAI (Apache 2.0, zero VC — https://localai.io)
    localai_base_url: str = os.getenv("LOCALAI_BASE_URL", "http://localhost:8080/v1")

    # Apertus 8B Instruct (Swiss AI Initiative — EPFL/ETH Zurich/CSCS, 1,000+ languages)
    # Download: https://huggingface.co/swiss-ai/Apertus-8B-Instruct-2509-GGUF
    model_world: str = os.getenv("MODEL_WORLD", "apertus-8b-instruct")

    # EuroLLM 22B Instruct (EU Horizon Europe / EuroHPC, 35 languages, EU legal corpus)
    # Download: https://huggingface.co/utter-project/EuroLLM-22B-Instruct-GGUF
    model_eu: str = os.getenv("MODEL_EU", "eurollm-22b-instruct")

    # Language routing: these ISO 639-1 codes route to EuroLLM; all others → Apertus
    eu_language_codes: List[str] = field(
        default_factory=lambda: _split_env_list(
            "EU_LANGUAGE_CODES",
            "bg,cs,da,de,el,en,es,et,fi,fr,ga,hr,hu,it,lt,lv,mt,nl,pl,pt,ro,sk,sl,sv",
        )
    )
    language_detection_enabled: bool = (
        os.getenv("LANGUAGE_DETECTION_ENABLED", "true").lower() == "true"
    )

    # ── Embedding ensemble ───────────────────────────────────────────────────
    # BM25 + Apertus mean-pool + EuroLLM mean-pool fused via Reciprocal Rank Fusion
    rrf_k: int = int(os.getenv("RRF_K", "60"))

    # ── Legal knowledge base (RAG) ──────────────────────────────────────────
    # Source corpus: data/legal_corpus/<jurisdiction>/<law>.txt (see .claude/skills/legal-kb)
    # Vector index: plain numpy matrix, exact exhaustive cosine search — no
    # FAISS (Meta-origin, excluded by the project's dependency no-go list;
    # unnecessary at this corpus size anyway).
    legal_corpus_dir: Path = field(
        default_factory=lambda: Path(
            os.getenv("LEGAL_CORPUS_DIR", str(_data_dir() / "legal_corpus"))
        )
    )
    legal_kb_index_path: Path = field(
        default_factory=lambda: Path(
            os.getenv("LEGAL_KB_INDEX_PATH", str(_data_dir() / "legal_kb.npy"))
        )
    )
    legal_kb_metadata_path: Path = field(
        default_factory=lambda: Path(
            os.getenv(
                "LEGAL_KB_METADATA_PATH", str(_data_dir() / "legal_kb_metadata.json")
            )
        )
    )
    legal_kb_top_k: int = field(
        default_factory=lambda: _parse_top_k(os.getenv("LEGAL_KB_TOP_K"))
    )
    # Relevance floor (issue #91, grumpy F1; round-2 OWNER RULING 2026-10-07,
    # "Disabled + loud"): minimum dense cosine similarity (range -1..1, on
    # L2-normalised vectors) a legal-KB passage must reach to be a retrieval
    # candidate. Applied before RRF fusion; passages scoring strictly below it
    # are dropped, and if none survive the retrieval reports NO_MATCH.
    # Default None = floor DISABLED. The value is uncalibrated (no gold set
    # yet for the Apertus mean-pooled embeddings, whose cosines sit in a
    # compressed positive band), and a 0.0 default looked like a filter while
    # keeping every candidate. With the floor disabled NO_MATCH cannot be
    # reported, the app logs a WARNING at startup, and
    # legal_grounding_authoritative is forced False (nobody checked the
    # passages for relevance). Set LEGAL_KB_MIN_SCORE once calibrated in
    # G2b/G3; a set value must be finite and in (-1, 1] or startup fails
    # (-1 keeps every candidate, so it is the disabled floor in disguise).
    legal_kb_min_score: Optional[float] = field(
        default_factory=lambda: _parse_min_score(os.getenv("LEGAL_KB_MIN_SCORE"))
    )

    # ── Core settings ────────────────────────────────────────────────────────
    database_url: str = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{_data_dir() / 'terms_analysis.db'}",
    )
    review_threshold: float = float(os.getenv("REVIEW_THRESHOLD", "0.80"))
    request_timeout_s: float = float(os.getenv("LM_REQUEST_TIMEOUT_S", "60"))
    # URL fetch timeout is deliberately separate from LLM inference timeout.
    # A remote website that hangs must not consume the full LLM budget; keeping
    # the two independent lets ops tune them per constraint. Audit finding
    # tracked via PRD §5 open question resolved in Phase 2 remediation.
    # INVARIANT: url_fetch_timeout_s <= request_timeout_s. URL fetch is the leading step of any URL-analyze flow;
    # the LLM budget consumes the remainder. Reviewer P9 grumpy-F4.
    # One total deadline for the whole fetch: DNS, connect, every redirect hop
    # and the body. Must be finite and > 0.
    url_fetch_timeout_s: float = float(os.getenv("LM_URL_FETCH_TIMEOUT_S", "30"))
    # ── User-URL fetch limits (CodeQL py/full-ssrf, ingest.fetch_url_text) ──
    # Schemes a submitted URL (and every redirect hop) may use: a non-empty
    # subset of URL_FETCH_SUPPORTED_SCHEMES, lowercase.
    url_fetch_allowed_schemes: Tuple[str, ...] = field(
        default_factory=lambda: tuple(_split_env_list("URL_FETCH_ALLOWED_SCHEMES", "http,https"))
    )
    # CIDRs no fetch may reach. Non-empty; every entry a valid network.
    url_fetch_blocked_networks: Tuple[str, ...] = field(
        default_factory=lambda: tuple(
            _split_env_list("URL_FETCH_BLOCKED_NETWORKS", _DEFAULT_URL_FETCH_BLOCKED_NETWORKS)
        )
    )
    # Redirect hops followed (each re-validated). 0 refuses every redirect.
    url_fetch_max_redirects: int = int(os.getenv("URL_FETCH_MAX_REDIRECTS", "5"))
    # Response body cap in bytes, enforced while streaming. >= 1.
    url_fetch_max_bytes: int = int(os.getenv("URL_FETCH_MAX_BYTES", str(10 * 1024 * 1024)))
    max_input_chars: int = int(os.getenv("MAX_INPUT_CHARS", "50000"))
    # 10 MB default upload limit (H5)
    max_upload_bytes: int = int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
    allowed_origins: List[str] = field(
        default_factory=lambda: _split_env_list(
            "ALLOWED_ORIGINS",
            "http://localhost:8000,http://127.0.0.1:8000",
        )
    )
    watchlist_refresh_seconds: int = int(os.getenv("WATCHLIST_REFRESH_SECONDS", "0"))
    # Maximum pages to process per PDF when OCR is involved.
    max_pdf_pages: int = int(os.getenv("MAX_PDF_PAGES", "100"))

    # ── API key auth and rate limiting (#133) ───────────────────────────────
    # Checked by validate_security_settings() in __post_init__ (import and
    # dataclasses.replace fail closed) and again on every request by
    # app.security, which answers 503 if the settings in force are invalid.
    #
    # Deployment mode. Unset (None) or "railway" means a key is required; only
    # the exact value "local" with a loopback BACKEND_HOST may run keyless,
    # and then only loopback peers are served.
    deploy_env: Optional[str] = os.getenv("DEPLOY_ENV")
    # The backend key, sent by clients in X-API-Key. repr=False keeps it out
    # of every repr/str of Settings; validation messages never echo it.
    api_key: str = field(default=os.getenv("API_KEY", ""), repr=False)
    # Minimum key length; may be raised, never below API_KEY_MIN_LENGTH_FLOOR.
    api_key_min_length: int = _env_int("API_KEY_MIN_LENGTH", "32")
    # Address the backend binds to (run.sh passes the same value to uvicorn).
    # Unset means unknown, which never counts as loopback.
    bind_host: str = os.getenv("BACKEND_HOST", "")
    # Rates are "<N>/<second|minute|hour|day>" fixed windows.
    # Every route except /health, keyed by TCP peer, checked before the key.
    # Behind railtail every remote request shares the proxy's peer address,
    # so this is an aggregate ceiling for all reviewers together.
    rate_limit_pre_auth: str = os.getenv("RATE_LIMIT_PRE_AUTH", "120/minute")
    # Analysis (LLM) routes, after auth, keyed by client identity; a batch
    # costs one token per item.
    rate_limit_per_client: str = os.getenv("RATE_LIMIT_PER_CLIENT", "5/minute")
    # Analysis routes, after auth, one ceiling for the key across clients.
    rate_limit_per_key: str = os.getenv("RATE_LIMIT_PER_KEY", "60/minute")
    # /health only, keyed by peer, separate from every other bucket.
    rate_limit_health: str = os.getenv("RATE_LIMIT_HEALTH", "60/minute")
    # Entry cap for every limiter store; the oldest entry is evicted at the cap.
    rate_limit_max_tracked_clients: int = _env_int("RATE_LIMIT_MAX_TRACKED_CLIENTS", "10000")
    # IPv6 clients are grouped by this prefix length (one /64 is one client).
    rate_limit_ipv6_prefix: int = _env_int("RATE_LIMIT_IPV6_PREFIX", "64")
    # Proxies whose client-identity header is trusted, and that header's name.
    # Both or neither. The header is read only from a peer inside these CIDRs
    # on a request with a valid key; unparseable values fall back to the peer.
    trusted_proxy_cidrs: Tuple[str, ...] = field(
        default_factory=lambda: tuple(_split_env_list("RATE_LIMIT_TRUSTED_PROXY_CIDRS", ""))
    )
    client_identity_header: str = os.getenv("RATE_LIMIT_CLIENT_IP_HEADER", "")
    # Read from the same variable uvicorn uses, so a catch-all ("*") set in
    # the environment stops startup. uvicorn's --forwarded-allow-ips CLI flag
    # is invisible here; run.sh passes --no-proxy-headers instead.
    forwarded_allow_ips: str = os.getenv("FORWARDED_ALLOW_IPS", "")
    # Analyses in flight at once; an extra request gets an immediate 429.
    max_concurrent_analyses: int = _env_int("MAX_CONCURRENT_ANALYSES", "2")
    # Retry-After (seconds) sent with the concurrency-cap 429. 1..3600.
    concurrency_retry_after_s: int = _env_int("CONCURRENCY_RETRY_AFTER_S", "5")
    # Items accepted by one /analyze/batch call (422 above it). Each item costs
    # one token from every rate in BATCH_CHARGED_RATES, so the cap may not
    # exceed any of their limits (5 matches the default RATE_LIMIT_PER_CLIENT).
    max_batch_items: int = _env_int("MAX_BATCH_ITEMS", "5")

    def __post_init__(self) -> None:
        # Fail closed at load (and on dataclasses.replace) on bad URL-fetch
        # limits: a broken SSRF config must stop startup, not weaken the guard.
        _validate_url_fetch_settings(self)
        # Same for auth and rate limits (#133 ruling 3).
        validate_security_settings(self)
        object.__setattr__(self, "trusted_proxy_cidrs", tuple(self.trusted_proxy_cidrs))


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_url_fetch_settings(s: Settings) -> None:
    schemes = s.url_fetch_allowed_schemes
    if (
        not isinstance(schemes, (list, tuple))
        or not schemes
        or not all(isinstance(x, str) and x in URL_FETCH_SUPPORTED_SCHEMES for x in schemes)
    ):
        raise ValueError(
            "url_fetch_allowed_schemes must be a non-empty list drawn from "
            f"{sorted(URL_FETCH_SUPPORTED_SCHEMES)}"
        )
    networks = s.url_fetch_blocked_networks
    if not isinstance(networks, (list, tuple)) or not networks:
        raise ValueError("url_fetch_blocked_networks must be a non-empty list of CIDRs")
    for net in networks:
        # Raises ValueError on a malformed CIDR or an out-of-range prefix.
        # Non-strings are parsed as "" so they fail too (ip_network accepts a
        # bare int, which would silently mean a /32).
        ipaddress.ip_network(net if isinstance(net, str) else "")
    if not _is_int(s.url_fetch_max_redirects) or s.url_fetch_max_redirects < 0:
        raise ValueError("url_fetch_max_redirects must be an integer >= 0")
    if not _is_int(s.url_fetch_max_bytes) or s.url_fetch_max_bytes < 1:
        raise ValueError("url_fetch_max_bytes must be an integer >= 1")
    timeout = s.url_fetch_timeout_s
    if (
        not isinstance(timeout, (int, float))
        or isinstance(timeout, bool)
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise ValueError("url_fetch_timeout_s must be a finite number > 0")
    # INVARIANT url_fetch_timeout_s <= request_timeout_s. Written as "not <="
    # so a NaN (or non-numeric) LLM budget fails closed instead of passing.
    llm_budget = s.request_timeout_s
    if (
        not isinstance(llm_budget, (int, float))
        or isinstance(llm_budget, bool)
        or not timeout <= llm_budget
    ):
        raise ValueError(
            "url_fetch_timeout_s must not exceed request_timeout_s "
            "(LM_URL_FETCH_TIMEOUT_S <= LM_REQUEST_TIMEOUT_S)"
        )
    # Store immutable copies so a caller's list cannot change the live config.
    object.__setattr__(s, "url_fetch_allowed_schemes", tuple(schemes))
    object.__setattr__(s, "url_fetch_blocked_networks", tuple(networks))


# ── #133 security settings ────────────────────────────────────────────────────

# Ruling 2: keys are at least 32 ASCII characters. API_KEY_MIN_LENGTH may raise
# the minimum, never lower it. A security floor, not a tunable.
API_KEY_MIN_LENGTH_FLOOR = 32
# Deployment modes. Unset means "not local" (auth required).
DEPLOY_ENVS = frozenset({"local", "railway"})
# Seconds per rate period (the rate format's own vocabulary).
RATE_PERIOD_SECONDS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}
# "<N>/<unit>", N a positive ASCII integer. [0-9] is ASCII-only in ``re``;
# ``\d`` would admit fullwidth and Arabic-Indic digits. fullmatch, so no
# trailing newline slips past a ``$``.
_RATE_RE = re.compile(r"([1-9][0-9]{0,8})/(second|minute|hour|day)")
# RFC 9110 header field-name token: ASCII only, no space, colon, CR, LF or NUL.
_HEADER_TOKEN_RE = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
# Rates /analyze/batch charges one token per item (security.batch_admission).
# A batch cap above any of these limits could never be admitted.
BATCH_CHARGED_RATES = ("rate_limit_per_client", "rate_limit_per_key")
# The concurrency 429's Retry-After must stay within an hour.
_CONCURRENCY_RETRY_AFTER_MAX_S = 3600
# Environment variable behind each field, so messages name both.
_ENV_NAMES = {
    "deploy_env": "DEPLOY_ENV",
    "api_key": "API_KEY",
    "api_key_min_length": "API_KEY_MIN_LENGTH",
    "bind_host": "BACKEND_HOST",
    "rate_limit_pre_auth": "RATE_LIMIT_PRE_AUTH",
    "rate_limit_per_client": "RATE_LIMIT_PER_CLIENT",
    "rate_limit_per_key": "RATE_LIMIT_PER_KEY",
    "rate_limit_health": "RATE_LIMIT_HEALTH",
    "rate_limit_max_tracked_clients": "RATE_LIMIT_MAX_TRACKED_CLIENTS",
    "rate_limit_ipv6_prefix": "RATE_LIMIT_IPV6_PREFIX",
    "trusted_proxy_cidrs": "RATE_LIMIT_TRUSTED_PROXY_CIDRS",
    "client_identity_header": "RATE_LIMIT_CLIENT_IP_HEADER",
    "forwarded_allow_ips": "FORWARDED_ALLOW_IPS",
    "max_concurrent_analyses": "MAX_CONCURRENT_ANALYSES",
    "concurrency_retry_after_s": "CONCURRENCY_RETRY_AFTER_S",
    "max_batch_items": "MAX_BATCH_ITEMS",
}


def _label(name: str) -> str:
    return f"{name} ({_ENV_NAMES[name]})"


def parse_rate(value: object) -> Optional[Tuple[int, int]]:
    """Return ``(limit, period_seconds)`` for a valid rate string, else None."""
    if not isinstance(value, str):
        return None
    match = _RATE_RE.fullmatch(value)
    if match is None:
        return None
    return int(match.group(1)), RATE_PERIOD_SECONDS[match.group(2)]


def is_loopback_literal(host: object) -> bool:
    """True only for an IP literal in a loopback range (no names, no scopes)."""
    if not isinstance(host, str) or not host.isascii():
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _check_int(s: Settings, name: str, low: int, high: Optional[int] = None) -> None:
    value = getattr(s, name)
    if not _is_int(value) or value < low or (high is not None and value > high):
        bound = f"between {low} and {high}" if high is not None else f">= {low}"
        raise ValueError(f"{_label(name)} must be an integer {bound}")


def _check_network_list(name: str, entries: object, *, strict: bool) -> None:
    """Every entry an IP network other than a catch-all /0."""
    if not isinstance(entries, (list, tuple)):
        raise ValueError(f"{_label(name)} must be a list of IP networks")
    for entry in entries:
        try:
            if not isinstance(entry, str) or not entry.isascii():
                raise ValueError
            net = ipaddress.ip_network(entry, strict=strict)
        except ValueError:
            raise ValueError(
                f"{_label(name)} entries must be IP addresses or CIDRs"
            ) from None
        if net.prefixlen == 0:
            raise ValueError(f"{_label(name)} must not contain a catch-all /0 network")


def _check_api_key(s: Settings) -> None:
    key = s.api_key
    if key == "":
        if s.deploy_env == "local" and is_loopback_literal(s.bind_host):
            return
        if s.deploy_env == "local":
            raise ValueError(
                "API_KEY is required: DEPLOY_ENV=local runs without a key only when "
                "bind_host (BACKEND_HOST) is a loopback address such as 127.0.0.1"
            )
        raise ValueError(
            "API_KEY is required unless DEPLOY_ENV=local with a loopback BACKEND_HOST"
        )
    # Allowlist: printable ASCII without space (0x21-0x7E). Rejects edge
    # whitespace, control characters, DEL, non-ASCII and lone surrogates.
    # The messages never include the value.
    if not all("\x21" <= ch <= "\x7e" for ch in key):
        raise ValueError(
            f"{_label('api_key')} must be printable ASCII with no whitespace or "
            "control characters"
        )
    if len(key) < s.api_key_min_length:
        raise ValueError(
            f"{_label('api_key')} is shorter than api_key_min_length "
            f"({s.api_key_min_length} characters)"
        )


def validate_security_settings(s: Settings) -> None:
    """Raise ValueError (naming the field and env var) on any invalid #133 setting.

    Pure check: called from ``Settings.__post_init__`` and, per request, by
    ``app.security`` so settings altered after construction still fail closed.
    """
    if s.deploy_env is not None and (
        not isinstance(s.deploy_env, str) or s.deploy_env not in DEPLOY_ENVS
    ):
        raise ValueError(
            f"{_label('deploy_env')} must be unset, 'local' or 'railway' (exact, lower case)"
        )
    _check_int(s, "api_key_min_length", API_KEY_MIN_LENGTH_FLOOR)
    _check_int(s, "rate_limit_max_tracked_clients", 1)
    _check_int(s, "rate_limit_ipv6_prefix", 1, 128)
    _check_int(s, "max_concurrent_analyses", 1)
    _check_int(s, "concurrency_retry_after_s", 1, _CONCURRENCY_RETRY_AFTER_MAX_S)
    _check_int(s, "max_batch_items", 1)
    for name in (
        "rate_limit_pre_auth",
        "rate_limit_per_client",
        "rate_limit_per_key",
        "rate_limit_health",
    ):
        if parse_rate(getattr(s, name)) is None:
            raise ValueError(
                f"{_label(name)} must look like '<N>/<second|minute|hour|day>' "
                "with N a positive integer"
            )
    for name in BATCH_CHARGED_RATES:
        limit, _period = parse_rate(getattr(s, name)) or (0, 0)
        if s.max_batch_items > limit:
            raise ValueError(
                f"{_label('max_batch_items')} ({s.max_batch_items}) exceeds the "
                f"{limit} tokens per window of {_label(name)}; each batch item "
                "costs one token, so a full batch could never be admitted. "
                "Lower MAX_BATCH_ITEMS or raise the rate"
            )
    for name in ("bind_host", "forwarded_allow_ips", "client_identity_header", "api_key"):
        if not isinstance(getattr(s, name), str):
            raise ValueError(f"{_label(name)} must be a string")
    forwarded = s.forwarded_allow_ips
    if forwarded != "":
        # Allowlist, not a "*" deny-list: every comma entry must be an IP or
        # CIDR, so "*", " * ", "*\n" and unix-socket globs are all refused.
        _check_network_list(
            "forwarded_allow_ips",
            [part.strip() for part in forwarded.split(",")],
            strict=False,
        )
    _check_network_list("trusted_proxy_cidrs", s.trusted_proxy_cidrs, strict=True)
    header = s.client_identity_header
    if header and (
        not _HEADER_TOKEN_RE.fullmatch(header) or header.lower() == "x-api-key"
    ):
        raise ValueError(
            f"{_label('client_identity_header')} must be an ASCII header name "
            "(no spaces, colons or control characters) other than X-API-Key"
        )
    if bool(header) != bool(s.trusted_proxy_cidrs):
        raise ValueError(
            f"{_label('client_identity_header')} and {_label('trusted_proxy_cidrs')} "
            "must be set together or not at all"
        )
    _check_api_key(s)


settings = Settings()
