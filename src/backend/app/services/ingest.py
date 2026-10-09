from __future__ import annotations

import asyncio
import encodings.idna
import ipaddress
import re
import socket
import unicodedata
from dataclasses import dataclass, replace
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Optional, Union
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup
from docx import Document
from PIL import Image
from pypdf import PdfReader

_ALLOWED_CONTENT_TYPES = {
    "text/plain",
    "text/html",
    "text/htm",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "application/rtf",
    "text/rtf",
    "text/markdown",
    "application/octet-stream",
}

try:
    import pytesseract
except ImportError:  # Optional OCR dependency
    pytesseract = None
from striprtf.striprtf import rtf_to_text

from ..config import Settings, settings


def _normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.strip()


def _decode_bytes(data: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _extract_html(text: str) -> str:
    soup = BeautifulSoup(text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    content = soup.get_text("\n")
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    return "\n".join(lines)


def _extract_pdf(data: bytes) -> str:
    reader = PdfReader(BytesIO(data))
    parts = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(parts)


def _extract_pdf_with_ocr(data: bytes) -> str:
    if pytesseract is None:
        return ""
    reader = PdfReader(BytesIO(data))
    parts = []
    page_limit = settings.max_pdf_pages
    for page in reader.pages[:page_limit]:
        text = page.extract_text()
        if text and text.strip():
            parts.append(text)
            continue
        images = []
        for image in page.images:
            images.append(Image.open(BytesIO(image.data)))
        if not images:
            parts.append("")
            continue
        ocr_text = []
        for image in images:
            try:
                ocr_text.append(pytesseract.image_to_string(image))
            except Exception:
                continue
        parts.append("\n".join(ocr_text))
    return "\n".join(parts)


def _extract_docx(data: bytes) -> str:
    doc = Document(BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs if p.text)


def _preserve_rtf_delimiter_spaces(text: str) -> str:
    # Fixed: RTF patterns use single backslash (\) not double (\\)
    # Raw string escapes one backslash to get the literal RTF code like \font0
    # (CRITICAL-2 from P9 security review: wrong escape levels in raw string)
    pattern = re.compile(r"(?<=\w)\\[a-zA-Z]+-?\d*\s(?=\w)")
    return pattern.sub(lambda match: match.group(0)[:-1] + r"\~", text)


def _extract_rtf(data: bytes) -> str:
    raw = _decode_bytes(data)
    raw = _preserve_rtf_delimiter_spaces(raw)
    return rtf_to_text(raw)


_ALLOWED_EXTENSIONS = {".txt", ".md", ".html", ".htm", ".pdf", ".docx", ".rtf"}


def extract_text_from_bytes(
    filename: str,
    content_type: Optional[str],
    data: bytes,
) -> str:
    ext = Path(filename).suffix.lower()
    if ext in {".txt", ".md"}:
        return _normalize_text(_decode_bytes(data))
    if ext in {".html", ".htm"}:
        return _normalize_text(_extract_html(_decode_bytes(data)))
    if ext == ".pdf":
        extracted = _extract_pdf(data)
        if extracted.strip():
            return _normalize_text(extracted)
        return _normalize_text(_extract_pdf_with_ocr(data))
    if ext == ".docx":
        return _normalize_text(_extract_docx(data))
    if ext == ".rtf":
        return _normalize_text(_extract_rtf(data))
    # For unknown extensions, only trust content_type for known HTML MIME types.
    # Do not fall through for arbitrary MIME types to avoid parser abuse.
    if content_type:
        ct_base = content_type.split(";")[0].strip().lower()
        if ct_base in {"text/html", "application/xhtml+xml"}:
            return _normalize_text(_extract_html(_decode_bytes(data)))
    return _normalize_text(_decode_bytes(data))


# ---------------------------------------------------------------------------
# SSRF-safe URL fetch (CodeQL alert #5, py/full-ssrf).
#
# Users submit arbitrary URLs, so there is no host allowlist. Instead every
# hop is parsed against an allowlist grammar, resolved once, checked against
# ``settings.url_fetch_blocked_networks``, and the request is sent to the
# checked IP literal (Host header and TLS SNI keep the hostname), so a second
# DNS answer can never swap the target (DNS rebinding). Redirects are followed
# by hand, re-running the same checks on every hop. One deadline covers DNS,
# connect, every hop and the body; the body cap is enforced while streaming.
# Every failure is a UrlFetchError with a fixed, clean message and a
# machine-readable ``.reason``; no untrusted bytes are echoed.
# ---------------------------------------------------------------------------


class UrlFetchError(ValueError):
    """A URL fetch failed. ``reason`` is one of redirects, size, timeout,
    dns, connect, status (or an UnsafeUrlError reason)."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class UnsafeUrlError(UrlFetchError):
    """The URL (or a redirect hop) was refused by policy. ``reason`` is one
    of malformed, scheme, userinfo, host, address."""


# Fixed user-facing messages, one per refusal cause (no untrusted text).
_MSG_MALFORMED = "This web address contains hidden or control characters or is not a valid URL, so it is not allowed."
_MSG_USERINFO = "Web addresses that include a username or password are not allowed."
_MSG_HOST = "This web address does not have a valid host name, so it is not allowed."
_MSG_ADDRESS = "This web address points to a private or internal network, so it is not allowed."
_MSG_DNS = "Could not find this website. Check the address for typos, or paste the policy text instead."
_MSG_CONNECT = (
    "Could not connect to this website. "
    "This may be a typo in the URL, a site that requires login, or a temporary outage. "
    "Try copying the policy text and using the Paste Text tab instead."
)
_MSG_TIMEOUT = "This website took too long to respond. Try again later, or paste the policy text instead."
_MSG_TOO_MANY_REDIRECTS = "This website redirected too many times (limit {limit}). Try pasting the policy text instead."
_MSG_NO_LOCATION = "This website sent a redirect without a destination. Try pasting the policy text instead."
_MSG_TOO_LARGE = "This page is larger than the {limit}-byte limit. Try pasting the policy text instead."
_MSG_BAD_LENGTH = "This website sent an invalid size header. Try pasting the policy text instead."
_MSG_BLOCKED_STATUS = (
    "This website blocks automated access. Copy the policy from your browser into "
    "the 'Paste text' tab, or save the page as PDF or HTML and use the 'Upload file' tab."
)
_MSG_STATUS = "Website returned an error ({status}). Try pasting the policy text instead."

_BLOCKED_STATUSES = frozenset({401, 403, 407, 429, 503})
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_DEFAULT_PORTS = {"http": 80, "https": 443}

# Protocol constants (RFC 6052 NAT64 well-known prefix; RFC 4291 IPv4-
# compatible block): an IPv6 address here carries an IPv4 address in its low
# 32 bits, which is checked against the blocklist as well.
_V4_IN_LOW_BITS = (
    ipaddress.ip_network("64:ff9b::/96"),
    ipaddress.ip_network("::/96"),
)

# Character classes (allowlists). Each pattern is a single anchored class or a
# class sequence with no nested quantifiers, so matching is linear.
_ASCII_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_BAD_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Zl", "Zp"})
_IDN_CHAR_CATEGORIES = ("L", "M", "Nd")
_LABEL = re.compile(r"[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?")
_NUMERIC_LABEL = re.compile(r"[0-9]+|0[xX][0-9a-fA-F]*")
_IPV6_CHARS = re.compile(r"[0-9A-Fa-f:.]+")
_PORT = re.compile(r"[0-9]{1,5}")
_DIGITS = re.compile(r"[0-9]+")


@dataclass(frozen=True)
class _Target:
    """One validated hop: where the request goes and what it claims to be."""

    url: str  # this hop's absolute URL (the base for a relative Location)
    scheme: str
    host: str  # lowercase ASCII (IDNA) name, or the IP literal
    port: int
    explicit_port: bool
    path_query: str
    ip: Union[ipaddress.IPv4Address, ipaddress.IPv6Address]
    is_literal: bool
    # The other resolved addresses, in answer order. Every one passed the
    # blocklist with ``ip``; tried in turn only when connecting to ``ip`` fails.
    fallbacks: tuple = ()

    @property
    def candidates(self) -> tuple:
        return (self.ip, *self.fallbacks)

    @property
    def host_header(self) -> str:
        host = f"[{self.ip}]" if self.is_literal and self.ip.version == 6 else self.host
        if self.explicit_port and self.port != _DEFAULT_PORTS[self.scheme]:
            host = f"{host}:{self.port}"
        return host

    @property
    def request_url(self) -> str:
        literal = f"[{self.ip}]" if self.ip.version == 6 else str(self.ip)
        return f"{self.scheme}://{literal}:{self.port}{self.path_query}"


def _check_raw(text: str) -> None:
    """Refuse control, format, surrogate and line/paragraph separator
    characters anywhere. Runs on the raw string because urlsplit silently
    drops TAB/CR/LF."""
    if _ASCII_CONTROL.search(text) or (
        not text.isascii() and any(unicodedata.category(c) in _BAD_CATEGORIES for c in text)
    ):
        raise UnsafeUrlError("malformed", _MSG_MALFORMED)


def _split_authority(netloc: str) -> tuple[str, Optional[str], bool]:
    """Return (host, port text or None, is_bracketed) for a userinfo-free netloc."""
    if netloc.startswith("["):
        # urlsplit has already refused an unclosed bracket or junk after it;
        # anything else after "]" is handed to the port check, which fails closed.
        host, _, rest = netloc[1:].partition("]")
        return host, rest[1:] if rest.startswith(":") else (rest or None), True
    host, sep, port = netloc.rpartition(":")
    return (host, port, False) if sep else (netloc, None, False)


def _ascii_hostname(raw: str) -> str:
    """Validate a DNS name against an allowlist and return its lowercase
    ASCII form. Non-ASCII labels must be real IDNs (encode to ``xn--``);
    a label that folds to plain ASCII (fullwidth or circled digits, other
    look-alikes) is refused, as is any non-ASCII dot."""
    if not raw or len(raw) > 253:
        raise UnsafeUrlError("host", _MSG_HOST)
    labels = raw.split(".")
    if labels[-1] == "":
        labels.pop()  # one trailing dot (absolute name) is allowed
    out = []
    for label in labels:
        if not label.isascii():
            if not all(unicodedata.category(c).startswith(_IDN_CHAR_CATEGORIES) for c in label):
                raise UnsafeUrlError("host", _MSG_HOST)
            try:
                label = encodings.idna.ToASCII(label).decode("ascii")
            except UnicodeError:
                raise UnsafeUrlError("host", _MSG_HOST) from None
            if not label.startswith("xn--"):
                raise UnsafeUrlError("host", _MSG_HOST)
        label = label.lower()
        if not _LABEL.fullmatch(label):
            raise UnsafeUrlError("host", _MSG_HOST)
        out.append(label)
    name = ".".join(out)
    if not out or len(name) > 253:
        raise UnsafeUrlError("host", _MSG_HOST)
    return name + ("." if raw.endswith(".") else "")


def _blocked_networks(cfg: Settings) -> tuple:
    return _parse_networks(tuple(cfg.url_fetch_blocked_networks))


@lru_cache(maxsize=8)
def _parse_networks(cidrs: tuple) -> tuple:
    return tuple(ipaddress.ip_network(c) for c in cidrs)


def _is_blocked(ip: Union[ipaddress.IPv4Address, ipaddress.IPv6Address], networks: tuple) -> bool:
    candidates = [ip]
    if ip.version == 6:
        candidates += [ip.ipv4_mapped, ip.sixtofour, *(ip.teredo or ())]
        if any(ip in net for net in _V4_IN_LOW_BITS):
            candidates.append(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    return any(c is not None and c in net for c in candidates for net in networks)


def _resolve(host: str, port: int) -> list:
    try:
        answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError, ValueError):
        raise UrlFetchError("dns", _MSG_DNS) from None
    addresses = []
    for answer in answers:
        try:
            addresses.append(ipaddress.ip_address(answer[4][0]))
        except (ValueError, TypeError, IndexError):
            continue  # not an IP (fail closed below if nothing usable is left)
    if not addresses:
        raise UrlFetchError("dns", _MSG_DNS)
    return addresses


def _validate_url(
    url: str,
    pins: Optional[dict] = None,
    cfg: Optional[Settings] = None,
    base: Optional[str] = None,
) -> _Target:
    """Validate one hop and pin it to a checked IP.

    ``url`` is the submitted URL, or a raw redirect Location resolved against
    ``base``. Order: raw characters (before any parsing, because urlsplit
    silently drops CR/LF/TAB), scheme, userinfo, host grammar, port, then the
    resolved (or literal) addresses against the configured blocklist. A host
    already in ``pins`` (same fetch, earlier hop) reuses the checked IP that
    connected and is never re-resolved. Every resolved address is checked;
    the rest of the answer set becomes ``fallbacks``. Raises UnsafeUrlError /
    UrlFetchError; never returns a target it did not check.
    """
    cfg = cfg or settings
    _check_raw(url)
    try:
        if base is not None:
            url = urljoin(base, url)
        parts = urlsplit(url)
    except ValueError:
        raise UnsafeUrlError("malformed", _MSG_MALFORMED) from None
    schemes = cfg.url_fetch_allowed_schemes
    if parts.scheme not in schemes:
        allowed = " and ".join(sorted(schemes))
        raise UnsafeUrlError("scheme", f"Only {allowed} URLs are allowed.")
    if "@" in parts.netloc:
        raise UnsafeUrlError("userinfo", _MSG_USERINFO)
    raw_host, port_text, bracketed = _split_authority(parts.netloc)
    if port_text:
        if not _PORT.fullmatch(port_text) or not 0 < int(port_text) < 65536:
            raise UnsafeUrlError("malformed", _MSG_MALFORMED)
        port, explicit = int(port_text), True
    else:
        port, explicit = _DEFAULT_PORTS[parts.scheme], False

    literal: Optional[Union[ipaddress.IPv4Address, ipaddress.IPv6Address]] = None
    if bracketed:
        # Only a plain IPv6 address: no IPvFuture, no zone id, no IPv4.
        try:
            literal = ipaddress.IPv6Address(raw_host if _IPV6_CHARS.fullmatch(raw_host) else "")
        except ValueError:
            raise UnsafeUrlError("host", _MSG_HOST) from None
        host = str(literal)
    else:
        host = _ascii_hostname(raw_host)
        if _NUMERIC_LABEL.fullmatch(host.rstrip(".").rsplit(".", 1)[-1]):
            # WHATWG parses a numeric last label as IPv4 (0x7f.1, 2130706433,
            # 0177.0.0.1, 127.0.0.1. ...). Only the canonical dotted quad is
            # accepted: IPv4Address refuses octal, hex, short forms, leading
            # zeros and a trailing dot.
            try:
                literal = ipaddress.IPv4Address(host)
            except ValueError:
                raise UnsafeUrlError("host", _MSG_HOST) from None

    networks = _blocked_networks(cfg)
    fallbacks: tuple = ()
    if literal is not None:
        ip = literal
        if _is_blocked(ip, networks):
            raise UnsafeUrlError("address", _MSG_ADDRESS)
    elif pins is not None and host in pins:
        ip = pins[host]
    else:
        addresses = _resolve(host, port)
        if any(_is_blocked(a, networks) for a in addresses):
            raise UnsafeUrlError("address", _MSG_ADDRESS)
        ip, *rest = addresses
        fallbacks = tuple(rest)

    return _Target(
        url=url,
        scheme=parts.scheme,
        host=host,
        port=port,
        explicit_port=explicit,
        path_query=(parts.path or "/") + (f"?{parts.query}" if parts.query else ""),
        ip=ip,
        is_literal=literal is not None,
        fallbacks=fallbacks,
    )


_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _check_status(status: int) -> None:
    if status in _BLOCKED_STATUSES:
        raise UrlFetchError("status", _MSG_BLOCKED_STATUS)
    if not 200 <= status < 300:
        raise UrlFetchError("status", _MSG_STATUS.format(status=int(status)))


async def _read_capped(response: httpx.Response, max_bytes: int) -> bytes:
    declared = response.headers.get("content-length")
    if declared is not None:
        declared = declared.strip()
        if not _DIGITS.fullmatch(declared):
            raise UrlFetchError("size", _MSG_BAD_LENGTH)
        # Compare by value: leading zeros do not change it (RFC 9110 1*DIGIT).
        # Strip them, then compare by length first so a huge digit string is
        # never int()-ed (int() is only ever given <= len(str(max_bytes)) digits).
        significant = declared.lstrip("0") or "0"
        if len(significant) > len(str(max_bytes)) or int(significant) > max_bytes:
            raise UrlFetchError("size", _MSG_TOO_LARGE.format(limit=max_bytes))
    chunks = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > max_bytes:
            raise UrlFetchError("size", _MSG_TOO_LARGE.format(limit=max_bytes))
        chunks.append(chunk)
    return b"".join(chunks)


async def _send_to(
    client: httpx.AsyncClient,
    target: _Target,
    ip: Union[ipaddress.IPv4Address, ipaddress.IPv6Address],
    extensions: dict,
) -> httpx.Response:
    pinned = replace(target, ip=ip, fallbacks=())
    try:
        request = client.build_request(
            "GET",
            pinned.request_url,
            headers={"Host": pinned.host_header},
            extensions=extensions,
        )
    except httpx.InvalidURL:
        # httpx refuses what it cannot encode (e.g. a URL over 65536
        # characters); refuse it cleanly instead of escaping as a 500.
        raise UnsafeUrlError("malformed", _MSG_MALFORMED) from None
    return await client.send(request, stream=True)


async def _connect(
    client: httpx.AsyncClient, target: _Target, extensions: dict
) -> tuple[httpx.Response, Union[ipaddress.IPv4Address, ipaddress.IPv6Address]]:
    """Send this hop to each checked address in answer order.

    Only a connect failure moves on to the next address; the last address's
    failure (or any other error) propagates, so the caller maps it once. The
    candidates all passed the blocklist in _validate_url and are never
    re-resolved; the total deadline in fetch_url_text bounds the loop.
    Returns the response and the address that connected.
    """
    *earlier, last = target.candidates
    for ip in earlier:
        try:
            return await _send_to(client, target, ip, extensions), ip
        except httpx.ConnectError:
            continue
    return await _send_to(client, target, last, extensions), last


async def _fetch_bytes(url: str, cfg: Settings) -> tuple[bytes, str]:
    pins: dict = {}
    current = url  # the next hop: the submitted URL, then each raw Location
    max_redirects = cfg.url_fetch_max_redirects
    async with httpx.AsyncClient(
        # The deadline is the single asyncio.wait_for in fetch_url_text, which
        # covers DNS, connect, every hop and the body together.
        timeout=None,
        follow_redirects=False,  # redirects are followed by hand below
        trust_env=False,  # no env proxies or netrc redirecting the request
        limits=httpx.Limits(max_keepalive_connections=0),  # no TLS reuse across hostnames
        headers=_FETCH_HEADERS,
    ) as client:
        hop = 0
        base: Optional[str] = None
        while True:
            target = await asyncio.to_thread(_validate_url, current, pins, cfg, base)
            extensions = (
                {"sni_hostname": target.host.rstrip(".")}
                if target.scheme == "https" and not target.is_literal
                else {}
            )
            response = None
            try:
                response, connected = await _connect(client, target, extensions)
                if not target.is_literal:
                    # Later hops to this host reuse the address that connected.
                    pins[target.host] = connected
                client.cookies.clear()  # never carry cookies to another hop
                if response.status_code in _REDIRECT_STATUSES:
                    location = response.headers.get("location")
                    if not location:
                        raise UrlFetchError("redirects", _MSG_NO_LOCATION)
                    if hop == max_redirects:
                        raise UrlFetchError(
                            "redirects", _MSG_TOO_MANY_REDIRECTS.format(limit=max_redirects)
                        )
                    # The next hop is the raw Location, resolved against this
                    # hop and fully re-validated by _validate_url.
                    base, current = target.url, location
                    hop += 1
                    continue
                _check_status(response.status_code)
                data = await _read_capped(response, cfg.url_fetch_max_bytes)
                return data, response.headers.get("content-type", "")
            except httpx.HTTPError:
                # Transport, protocol and decoding failures on send or body.
                raise UrlFetchError("connect", _MSG_CONNECT) from None
            finally:
                if response is not None:
                    await response.aclose()


async def fetch_url_text(url: str) -> str:
    """Fetch a user-submitted URL safely and return its extracted text.

    Limits are read from the module-level ``settings`` at call time:
    ``url_fetch_allowed_schemes``, ``url_fetch_blocked_networks``,
    ``url_fetch_max_redirects``, ``url_fetch_max_bytes`` and
    ``url_fetch_timeout_s`` (one total deadline, separate from the LLM
    inference budget ``request_timeout_s``). Raises UnsafeUrlError for policy
    refusals and UrlFetchError for fetch failures.
    """
    cfg = settings
    try:
        data, content_type = await asyncio.wait_for(
            _fetch_bytes(url, cfg), cfg.url_fetch_timeout_s
        )
    except asyncio.TimeoutError:
        raise UrlFetchError("timeout", _MSG_TIMEOUT) from None

    filename = Path(url).name or "document"
    return extract_text_from_bytes(filename, content_type, data)
