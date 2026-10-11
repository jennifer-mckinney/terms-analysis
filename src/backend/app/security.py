"""API key auth and in-process rate limiting (#133).

One global FastAPI dependency (``enforce_access``) runs on every route, in
this order:

1. the settings in force are re-validated; invalid settings answer 503;
2. ``/health`` is limited in its own bucket by peer address, then served;
3. the pre-auth limit, by peer address, before the key is looked at;
4. the key check: the one ``X-API-Key`` header, compared as SHA-256 digests
   with ``hmac.compare_digest``. Only ``DEPLOY_ENV=local`` with an empty key
   (and a loopback bind, enforced by config) serves loopback peers without a
   key, and never a request that carries a forwarding header;
5. the client identity for the later limits: the trusted proxy's identity
   header when the peer is inside ``trusted_proxy_cidrs``, else the peer.

The analysis routes add ``analysis_admission`` / ``batch_admission``: the
per-client and per-key limits (one token per analysed item), then the
concurrency cap. Every rejection is a 429 with an integer ``Retry-After``.

Bucket ids are HMAC-SHA256 digests under a per-process random salt, so the
limiter holds neither addresses nor the key. Every store is size-capped.
Limits are per process: N uvicorn workers allow N times the configured rates.
"""

from __future__ import annotations

import functools
import hashlib
import hmac
import ipaddress
import logging
import math
import re
import secrets
import time
from collections import OrderedDict
from collections.abc import AsyncIterator
from typing import Optional, Protocol, Union

from fastapi import HTTPException, Request

from . import config
from .config import Settings, settings

logger = logging.getLogger("uvicorn.error")

# Read through the module attributes (tests drive the window and swap settings).
monotonic = time.monotonic

IPAddress = Union[ipaddress.IPv4Address, ipaddress.IPv6Address]

HEALTH_PATH = "/health"
API_KEY_HEADER = b"x-api-key"
# A request carrying any of these did not come straight from the loopback
# client, so the local keyless mode refuses it (railtail and other proxies).
_FORWARDING_HEADERS = frozenset({b"x-forwarded-for", b"forwarded", b"x-real-ip"})
# Allowlist for identity header values: hex digits, dots and colons, at most
# the length of the longest IPv6 text form. No "%" (scoped), no port, no list.
_IDENTITY_VALUE_RE = re.compile(rb"[0-9A-Fa-f.:]{2,45}")

UNAUTHORIZED_DETAIL = "Invalid or missing API key"
RATE_LIMITED_DETAIL = "Rate limit exceeded"
UNAVAILABLE_DETAIL = "Service unavailable"


class RateStore(Protocol):
    """Storage behind one rate limit. Implementations must cap their size."""

    def remaining(self, bucket: bytes, now: float) -> int: ...

    def consume(self, bucket: bytes, cost: int, now: float) -> None: ...

    def retry_after(self, bucket: bytes, now: float) -> int: ...

    def __len__(self) -> int: ...


class InMemoryFixedWindowStore:
    """Fixed-window counters, at most ``max_entries`` buckets (LRU eviction).

    Eviction means an attacker who cycles more than ``max_entries`` distinct
    identities within one window can push a bucket out and reset it; the cap
    bounds memory, the pre-auth and per-key limits bound the damage.
    """

    __slots__ = ("limit", "period", "max_entries", "_entries")

    def __init__(self, limit: int, period: int, max_entries: int) -> None:
        self.limit = limit
        self.period = period
        self.max_entries = max_entries
        # bucket -> [window start, tokens used]
        self._entries: OrderedDict[bytes, list[float]] = OrderedDict()

    def _live(self, bucket: bytes, now: float) -> Optional[list[float]]:
        entry = self._entries.get(bucket)
        if entry is None or now - entry[0] >= self.period:
            return None
        return entry

    def remaining(self, bucket: bytes, now: float) -> int:
        entry = self._live(bucket, now)
        return self.limit - int(entry[1]) if entry else self.limit

    def consume(self, bucket: bytes, cost: int, now: float) -> None:
        entry = self._live(bucket, now)
        if entry is not None:
            entry[1] += cost
        else:
            if bucket not in self._entries:
                while len(self._entries) >= self.max_entries:
                    self._entries.popitem(last=False)
            self._entries[bucket] = [now, float(cost)]
        self._entries.move_to_end(bucket)

    def retry_after(self, bucket: bytes, now: float) -> int:
        entry = self._live(bucket, now)
        wait = self.period if entry is None else math.ceil(entry[0] + self.period - now)
        return max(1, min(self.period, wait))

    def __len__(self) -> int:
        return len(self._entries)


class RateLimiter:
    """The process's limit state. Built by the lifespan from the settings."""

    def __init__(self, s: Settings) -> None:
        cap = s.rate_limit_max_tracked_clients

        def store(rate: str) -> InMemoryFixedWindowStore:
            parsed = config.parse_rate(rate)
            if parsed is None:  # validated already; never build a silent no-op
                raise ValueError("invalid rate in settings")
            return InMemoryFixedWindowStore(parsed[0], parsed[1], cap)

        self._salt = secrets.token_bytes(32)
        self.pre_auth: RateStore = store(s.rate_limit_pre_auth)
        self.per_client: RateStore = store(s.rate_limit_per_client)
        self.per_key: RateStore = store(s.rate_limit_per_key)
        self.health: RateStore = store(s.rate_limit_health)
        self.max_in_flight = s.max_concurrent_analyses
        self.busy_retry_after = s.concurrency_retry_after_s
        self.in_flight = 0
        # There is one backend key, so the per-key limit has one bucket; it is
        # a label, never the key or a digest of it.
        self.key_bucket = self.bucket("api-key")

    def bucket(self, label: str) -> bytes:
        return hmac.new(self._salt, label.encode("ascii"), hashlib.sha256).digest()

    def store_sizes(self) -> dict[str, int]:
        return {
            "pre_auth": len(self.pre_auth),
            "per_client": len(self.per_client),
            "per_key": len(self.per_key),
            "health": len(self.health),
        }


def build_limiter() -> RateLimiter:
    """Validate the settings in force and build a fresh limiter from them."""
    config.validate_security_settings(settings)
    return RateLimiter(settings)


def _too_many(retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail=RATE_LIMITED_DETAIL,
        headers={"Retry-After": str(retry_after)},
    )


def _take(store: RateStore, bucket: bytes, now: float) -> None:
    if store.remaining(bucket, now) < 1:
        raise _too_many(store.retry_after(bucket, now))
    store.consume(bucket, 1, now)


def _parse_ip(text: str) -> Optional[IPAddress]:
    try:
        ip = ipaddress.ip_address(text.split("%", 1)[0])
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def _peer_ip(request: Request) -> Optional[IPAddress]:
    client = request.scope.get("client")
    if not client or not isinstance(client[0], str):
        return None
    return _parse_ip(client[0])


def _client_label(ip: Optional[IPAddress], ipv6_prefix: int) -> str:
    """One label per client: an IPv4 address, or the IPv6 network it sits in."""
    if ip is None:
        return "client:unknown"
    if isinstance(ip, ipaddress.IPv6Address):
        net = ipaddress.IPv6Network((ip, ipv6_prefix), strict=False)
        return f"client:{net}"
    return f"client:{ip}"


def _header_values(request: Request, name: bytes) -> list[bytes]:
    return [v for k, v in request.scope.get("headers", ()) if k.lower() == name]


def _has_forwarding_header(request: Request) -> bool:
    return any(k.lower() in _FORWARDING_HEADERS for k, _ in request.scope.get("headers", ()))


def _key_matches(request: Request, key: str) -> bool:
    """Exactly one X-API-Key header whose digest equals the key's digest.

    Digests make the compared length fixed (32 bytes) whatever is presented,
    and raw bytes mean hostile header encodings cannot raise. The compare runs
    even when the header is missing so every request takes the same path.
    """
    values = _header_values(request, API_KEY_HEADER)
    presented = values[0] if len(values) == 1 else b""
    match = hmac.compare_digest(
        hashlib.sha256(presented).digest(), hashlib.sha256(key.encode("ascii")).digest()
    )
    return match and len(values) == 1 and key != ""


@functools.lru_cache(maxsize=16)
def _networks(
    cidrs: tuple[str, ...],
) -> tuple[Union[ipaddress.IPv4Network, ipaddress.IPv6Network], ...]:
    return tuple(ipaddress.ip_network(c) for c in cidrs)


def _identity(request: Request, s: Settings, peer: Optional[IPAddress]) -> Optional[IPAddress]:
    """The trusted proxy's identity header when it is usable, else the peer."""
    if not s.client_identity_header or peer is None:
        return peer
    if not any(peer in net for net in _networks(tuple(s.trusted_proxy_cidrs))):
        return peer
    values = _header_values(request, s.client_identity_header.lower().encode("ascii"))
    if len(values) != 1 or not _IDENTITY_VALUE_RE.fullmatch(values[0]):
        return peer
    claimed = _parse_ip(values[0].decode("ascii"))
    return claimed if claimed is not None else peer


async def enforce_access(request: Request) -> None:
    """Global dependency: settings check, health and pre-auth limits, auth.

    ``async def`` so each check-then-consume runs on the event loop with no
    await in between (no thread interleaving).
    """
    s = settings
    try:
        config.validate_security_settings(s)
    except Exception:  # any failure means the settings cannot be trusted
        # The message is fixed: a validation error could name a value.
        logger.error("Refusing request: security settings in force are invalid")
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None
    limiter = getattr(request.app.state, "rate_limiter", None)
    if not isinstance(limiter, RateLimiter):
        logger.error("Refusing request: rate limiter not initialised (lifespan not run)")
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL)

    now = monotonic()
    peer = _peer_ip(request)
    peer_bucket = limiter.bucket(_client_label(peer, s.rate_limit_ipv6_prefix))
    if request.scope.get("path") == HEALTH_PATH:
        _take(limiter.health, peer_bucket, now)
        return
    _take(limiter.pre_auth, peer_bucket, now)

    if s.api_key:
        authenticated = _key_matches(request, s.api_key)
    else:
        # Config allows an empty key only for DEPLOY_ENV=local on a loopback
        # bind; re-checked here because settings can change after startup.
        authenticated = (
            s.deploy_env == "local"
            and config.is_loopback_literal(s.bind_host)
            and peer is not None
            and peer.is_loopback
            and not _has_forwarding_header(request)
        )
    if not authenticated:
        logger.debug("Rejected request: invalid or missing API key")
        raise HTTPException(status_code=401, detail=UNAUTHORIZED_DETAIL)

    client = _identity(request, s, peer)
    request.state.client_bucket = limiter.bucket(_client_label(client, s.rate_limit_ipv6_prefix))


def _admit(request: Request, cost: int) -> RateLimiter:
    """Per-client and per-key tokens, then a concurrency slot; 429 otherwise.

    Nothing is consumed unless every check passes, so a rejected request
    costs no tokens.
    """
    limiter = getattr(request.app.state, "rate_limiter", None)
    client_bucket = getattr(request.state, "client_bucket", None)
    if not isinstance(limiter, RateLimiter) or not isinstance(client_bucket, bytes):
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL)
    now = monotonic()
    short = [
        store.retry_after(bucket, now)
        for store, bucket in (
            (limiter.per_client, client_bucket),
            (limiter.per_key, limiter.key_bucket),
        )
        if store.remaining(bucket, now) < cost
    ]
    if short:
        raise _too_many(max(short))
    if limiter.in_flight >= limiter.max_in_flight:
        raise _too_many(limiter.busy_retry_after)
    limiter.per_client.consume(client_bucket, cost, now)
    limiter.per_key.consume(limiter.key_bucket, cost, now)
    limiter.in_flight += 1
    return limiter


async def analysis_admission(request: Request) -> AsyncIterator[None]:
    """Admission for one analysis; the slot is released on every exit path."""
    limiter = _admit(request, 1)
    try:
        yield
    finally:
        limiter.in_flight -= 1


async def _batch_item_count(request: Request) -> int:
    """Items in the batch body; FastAPI has already parsed (and cached) it."""
    try:
        body = await request.json()
    except ValueError:
        return 1  # the body validation answers 422 for a malformed request
    items = body.get("items") if isinstance(body, dict) else None
    return len(items) if isinstance(items, list) else 1


async def batch_admission(request: Request) -> AsyncIterator[None]:
    """Item cap (422), then one token per item and one concurrency slot."""
    count = await _batch_item_count(request)
    cap = settings.max_batch_items
    if count > cap:
        raise HTTPException(status_code=422, detail=f"A batch may contain at most {cap} items")
    limiter = _admit(request, max(count, 1))
    try:
        yield
    finally:
        limiter.in_flight -= 1
