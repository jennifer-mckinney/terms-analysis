from __future__ import annotations

from io import BytesIO
from pathlib import Path
import re
from typing import Optional

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


async def fetch_url_text(url: str) -> str:
    timeout = settings.request_timeout_s
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(url, follow_redirects=True)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        data = response.content
    filename = Path(url).name or "document"
    return extract_text_from_bytes(filename, content_type, data)
