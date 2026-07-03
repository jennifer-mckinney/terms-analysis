from __future__ import annotations

import asyncio

import pytest

from app.config import settings
from app.services.legal_kb import LegalKnowledgeBase, _parse_corpus_file
from app.services.localai import LocalAIClient


# Toy embedding space: 3 dims, one per "topic" keyword. Lets tests assert
# retrieval ranks the topically-relevant chunk first without a real LLM.
_TOPICS = ["erasure", "consent", "retention"]


def _toy_embed(text: str) -> list[float]:
    lowered = text.lower()
    return [1.0 if topic in lowered else 0.0 for topic in _TOPICS] or [1.0, 0.0, 0.0]


@pytest.fixture
def patched_paths(tmp_path, monkeypatch):
    corpus_dir = tmp_path / "legal_corpus"
    index_path = tmp_path / "legal_kb.faiss"
    metadata_path = tmp_path / "legal_kb_metadata.json"
    object.__setattr__(settings, "legal_corpus_dir", corpus_dir)
    object.__setattr__(settings, "legal_kb_index_path", index_path)
    object.__setattr__(settings, "legal_kb_metadata_path", metadata_path)
    yield corpus_dir, index_path, metadata_path


@pytest.fixture
def toy_client(monkeypatch):
    async def fake_embed(self, text, model=None):
        return _toy_embed(text)

    monkeypatch.setattr(LocalAIClient, "embed", fake_embed)
    return LocalAIClient()


def _write_corpus_file(corpus_dir, jurisdiction: str, law: str, body: str) -> None:
    directory = corpus_dir / jurisdiction
    directory.mkdir(parents=True, exist_ok=True)
    header = (
        f"# Jurisdiction: {jurisdiction.upper()}\n"
        f"# Law: {law}\n"
        "# Source: test-fixture\n"
        "# Effective Date: 2024-01-01\n\n"
    )
    (directory / f"{law}.txt").write_text(header + body, encoding="utf-8")


def test_parse_corpus_file_splits_sections(tmp_path):
    _write_corpus_file(
        tmp_path,
        "eu",
        "gdpr",
        "## Article 17 — Right to erasure\n"
        "The data subject has the right to erasure of personal data.\n\n"
        "## Article 7 — Conditions for consent\n"
        "Consent must be freely given and specific.\n",
    )
    chunks = _parse_corpus_file(tmp_path / "eu" / "gdpr.txt")
    assert len(chunks) == 2
    assert all(c["jurisdiction"] == "EU" for c in chunks)
    sections = {c["section"] for c in chunks}
    assert "Article 17 — Right to erasure" in sections
    assert "Article 7 — Conditions for consent" in sections


def test_parse_corpus_file_without_sections_is_single_chunk(tmp_path):
    _write_corpus_file(tmp_path, "eu", "gdpr", "Plain body with no section headers.")
    chunks = _parse_corpus_file(tmp_path / "eu" / "gdpr.txt")
    assert len(chunks) == 1
    assert chunks[0]["section"] is None


def test_retrieve_returns_empty_when_no_index_built(patched_paths, toy_client):
    kb = LegalKnowledgeBase()
    result = asyncio.run(kb.retrieve("erasure of personal data", toy_client))
    assert result == []


def test_build_and_retrieve_ranks_relevant_chunk_first(patched_paths, toy_client):
    corpus_dir, _, _ = patched_paths
    _write_corpus_file(
        corpus_dir,
        "eu",
        "gdpr",
        "## Article 17 — Right to erasure\n"
        "The data subject has the right to obtain erasure of personal data.\n\n"
        "## Article 7 — Conditions for consent\n"
        "Consent must be freely given, specific, and unambiguous.\n",
    )

    kb = LegalKnowledgeBase()
    count = asyncio.run(kb.build(toy_client))
    assert count == 2
    assert kb.chunk_count == 2

    results = asyncio.run(kb.retrieve("right to erasure", toy_client, top_k=2))
    assert len(results) >= 1
    assert "erasure" in results[0]["text"].lower()


def test_retrieve_filters_by_jurisdiction(patched_paths, toy_client):
    corpus_dir, _, _ = patched_paths
    _write_corpus_file(
        corpus_dir,
        "eu",
        "gdpr",
        "## Article 17 — Right to erasure\nThe data subject has erasure rights.\n",
    )
    _write_corpus_file(
        corpus_dir,
        "us-ca",
        "ccpa",
        "## Section 1798.105 — Right to delete\nConsumers have erasure rights too.\n",
    )

    kb = LegalKnowledgeBase()
    asyncio.run(kb.build(toy_client))

    results = asyncio.run(
        kb.retrieve("erasure rights", toy_client, jurisdictions=["US-CA"], top_k=5)
    )
    assert results
    assert all(r["jurisdiction"] == "US-CA" for r in results)


def test_build_persists_index_and_metadata_to_disk(patched_paths, toy_client):
    corpus_dir, index_path, metadata_path = patched_paths
    _write_corpus_file(
        corpus_dir,
        "eu",
        "gdpr",
        "## Article 17 — Right to erasure\nData subjects have erasure rights.\n",
    )

    kb = LegalKnowledgeBase()
    asyncio.run(kb.build(toy_client))

    assert index_path.exists()
    assert metadata_path.exists()

    # A fresh instance should be able to load the persisted index/metadata.
    reloaded = LegalKnowledgeBase()
    results = asyncio.run(reloaded.retrieve("erasure rights", toy_client))
    assert reloaded.chunk_count == 1
    assert results


def test_build_returns_zero_for_empty_corpus_dir(patched_paths, toy_client):
    kb = LegalKnowledgeBase()
    count = asyncio.run(kb.build(toy_client))
    assert count == 0
    assert kb.chunk_count == 0


def test_retrieve_returns_empty_when_embedding_endpoint_unreachable(
    patched_paths, monkeypatch
):
    corpus_dir, _, _ = patched_paths
    _write_corpus_file(
        corpus_dir, "eu", "gdpr", "## Article 17 — Erasure\nErasure rights text.\n"
    )

    async def working_embed(self, text, model=None):
        return _toy_embed(text)

    monkeypatch.setattr(LocalAIClient, "embed", working_embed)
    kb = LegalKnowledgeBase()
    built = asyncio.run(kb.build(LocalAIClient()))
    assert built == 1

    async def broken_embed(self, text, model=None):
        return None

    monkeypatch.setattr(LocalAIClient, "embed", broken_embed)
    result = asyncio.run(kb.retrieve("anything", LocalAIClient()))
    assert result == []
