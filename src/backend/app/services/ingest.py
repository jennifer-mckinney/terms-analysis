from __future__ import annotations

from io import BytesIO
import ipaddress
from pathlib import Path
import re
import socket
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from docx import Document
from PIL import Image
from pypdf import PdfReader
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
    for page in reader.pages:
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
    if content_type and "html" in content_type:
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


_MAX_REDIRECTS = 5


async def fetch_url_text(url: str) -> str:
    timeout = settings.request_timeout_s
    current_url = url
    async with httpx.AsyncClient(timeout=timeout) as client:
        for _ in range(_MAX_REDIRECTS + 1):
            _validate_url(current_url)
            response = await client.get(current_url, follow_redirects=False)
            if response.is_redirect:
                next_url = response.headers.get("location")
                if not next_url:
                    raise ValueError("URL is not allowed")
                current_url = urljoin(current_url, next_url)
                continue
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            data = response.content
            break
        else:
            raise ValueError("Too many redirects")
    filename = Path(current_url).name or "document"
    return extract_text_from_bytes(filename, content_type, data)
