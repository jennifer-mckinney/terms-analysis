import asyncio

import httpx
import pytest

from app.services.ingest import extract_text_from_bytes, fetch_url_text


def test_extracts_html_text():
    html = b"<html><body><h1>Title</h1><p>Policy text here.</p></body></html>"
    text = extract_text_from_bytes("policy.html", "text/html", html)
    assert "Title" in text
    assert "Policy text here." in text


def test_extracts_rtf_text():
    rtf = b"{\\rtf1\\ansi This is \\b bold\\b0 text.}"
    text = extract_text_from_bytes("policy.rtf", "application/rtf", rtf)
    assert "This is" in text
    assert "bold" in text
    assert "text." in text


def _patch_transport(monkeypatch, handler):
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


def test_fetch_url_text_rejects_redirect_to_blocked_address(monkeypatch):
    """A public URL that 302s to a link-local/metadata address must not be followed."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "93.184.216.34":
            return httpx.Response(
                302, headers={"location": "http://169.254.169.254/latest/meta-data/"}
            )
        raise AssertionError(f"blocked redirect target was followed: {request.url}")

    _patch_transport(monkeypatch, handler)

    with pytest.raises(ValueError):
        asyncio.run(fetch_url_text("http://93.184.216.34/policy"))


def test_fetch_url_text_follows_redirect_to_allowed_address(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "93.184.216.34" and request.url.path == "/policy":
            return httpx.Response(302, headers={"location": "http://93.184.216.35/final"})
        if request.url.host == "93.184.216.35" and request.url.path == "/final":
            return httpx.Response(
                200,
                headers={"content-type": "text/plain"},
                content=b"Final policy text.",
            )
        raise AssertionError(f"unexpected request: {request.url}")

    _patch_transport(monkeypatch, handler)

    text = asyncio.run(fetch_url_text("http://93.184.216.34/policy"))
    assert "Final policy text." in text


def test_fetch_url_text_caps_redirect_chain_length(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://93.184.216.34/loop"})

    _patch_transport(monkeypatch, handler)

    with pytest.raises(ValueError, match="Too many redirects"):
        asyncio.run(fetch_url_text("http://93.184.216.34/loop"))
