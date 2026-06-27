import asyncio

import httpx

from app.services.analyzer import analyze_text
from app.services.localai import LocalAIClient


def test_analyze_text_falls_back_to_rules(monkeypatch):
    async def fake_analyze(self, numbered_text, jurisdictions, rule_findings):
        return None

    monkeypatch.setattr(LocalAIClient, "analyze", fake_analyze)

    text = "We sell personal information and use automated decision-making."
    result = asyncio.run(analyze_text(text, ["US-CA", "GDPR"]))
    categories = {finding.category for finding in result.payload.findings}
    assert "Sale/Share" in categories
    assert "ADM" in categories


def test_localai_unreachable_returns_none(monkeypatch):
    class UnreachableClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "AsyncClient", UnreachableClient)

    result = asyncio.run(LocalAIClient().analyze("text", ["US-CA"], []))

    assert result is None
