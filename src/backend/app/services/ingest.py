from __future__ import annotations

import ipaddress
import re
import socket
from io import BytesIO
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

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

from ..config import settings

_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


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
    pattern = re.compile(r"(?<=\\w)\\\\[a-zA-Z]+-?\\d* (?=\\w)")
    return pattern.sub(lambda match: match.group(0)[:-1] + r"\\~", text)


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


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http and https URLs are allowed")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL is not allowed")

    addresses = []
    try:
        addresses.append(ipaddress.ip_address(hostname))
    except ValueError:
        try:
            for _, _, _, _, sockaddr in socket.getaddrinfo(hostname, None):
                address = sockaddr[0]
                try:
                    addresses.append(ipaddress.ip_address(address))
                except ValueError:
                    continue
        except socket.gaierror:
            raise ValueError("URL is not allowed") from None

    if not addresses:
        raise ValueError("URL is not allowed")

    for address in addresses:
        if any(address in network for network in _BLOCKED_NETWORKS):
            raise ValueError("URL is not allowed")


_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


async def fetch_url_text(url: str) -> str:
    _validate_url(url)

    # URL fetch uses its own budget — distinct from the LLM inference timeout
    # so a hung remote host cannot starve LocalAI callers. See ``config.py::
    # url_fetch_timeout_s``.
    timeout = settings.url_fetch_timeout_s
    max_bytes = settings.max_upload_bytes

    async def _on_request(request: httpx.Request) -> None:
        """Validate each URL before every request, including redirects — closes
        the SSRF bypass where an allowed URL 302s to a blocked address."""
        _validate_url(str(request.url))

    _BLOCKED_STATUSES = {401, 403, 407, 429, 503}
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers=_FETCH_HEADERS,
        event_hooks={"request": [_on_request]},
    ) as client:
        try:
            response = await client.get(url)
        except httpx.RequestError as exc:
            raise ValueError(
                "Could not connect to this website. "
                "This may be a typo in the URL, a site that requires login, or a temporary outage. "
                "Try copying the policy text and using the Paste Text tab instead."
            ) from exc
        if response.status_code in _BLOCKED_STATUSES:
            raise ValueError(
                "This website blocks automated access. Here's what you can do:\n"
                "• Use the 'Paste text' tab and copy the policy from your browser\n"
                "• Use the 'Upload file' tab if you can save the page as PDF/HTML"
            )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ValueError(
                f"Website returned an error ({exc.response.status_code}). "
                "Try pasting the policy text instead."
            ) from exc

        # Reject oversized responses before buffering the full body.
        raw_length = response.headers.get("content-length")
        if raw_length and int(raw_length) > max_bytes:
            raise ValueError(
                f"Response size {raw_length} bytes exceeds the "
                f"{max_bytes}-byte limit"
            )
        data = response.content
        if len(data) > max_bytes:
            raise ValueError(
                f"Response size {len(data)} bytes exceeds the "
                f"{max_bytes}-byte limit"
            )
        content_type = response.headers.get("content-type", "")

    filename = Path(url).name or "document"
    return extract_text_from_bytes(filename, content_type, data)
