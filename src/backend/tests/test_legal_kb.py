from __future__ import annotations

import asyncio

import pytest

import sys

from app.config import settings
from app.services.legal_kb import LegalKnowledgeBase, _main, _parse_corpus_file
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
    index_path = tmp_path / "legal_kb.npy"
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


def test_retrieve_filters_by_jurisdiction_using_schema_codes(patched_paths, toy_client):
    # Regression test for issue #14: corpus files must use the canonical
    # Jurisdiction codes (GDPR, PIPEDA), not directory-style names (EU, Canada) —
    # otherwise the jurisdiction filter silently falls back to the full corpus.
    corpus_dir, _, _ = patched_paths
    directory = corpus_dir / "eu"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "gdpr.txt").write_text(
        "# Jurisdiction: GDPR\n# Law: GDPR\n# Source: test\n# Effective Date: 2024-01-01\n\n"
        "## Article 17 — Right to erasure\nData subjects have erasure rights.\n",
        encoding="utf-8",
    )
    canada_dir = corpus_dir / "canada"
    canada_dir.mkdir(parents=True, exist_ok=True)
    (canada_dir / "pipeda.txt").write_text(
        "# Jurisdiction: PIPEDA\n# Law: PIPEDA\n# Source: test\n# Effective Date: 2024-01-01\n\n"
        "## Principle 5 — Retention\nOrganizations must retain data appropriately.\n",
        encoding="utf-8",
    )

    kb = LegalKnowledgeBase()
    asyncio.run(kb.build(toy_client))

    results = asyncio.run(
        kb.retrieve("erasure rights", toy_client, jurisdictions=["GDPR"], top_k=5)
    )
    assert results
    assert all(r["jurisdiction"] == "GDPR" for r in results)

    results = asyncio.run(
        kb.retrieve("retention", toy_client, jurisdictions=["PIPEDA"], top_k=5)
    )
    assert results
    assert all(r["jurisdiction"] == "PIPEDA" for r in results)


def test_retrieve_falls_back_to_full_corpus_when_jurisdiction_pool_empty(
    patched_paths, toy_client, caplog
):
    corpus_dir, _, _ = patched_paths
    _write_corpus_file(
        corpus_dir, "eu", "gdpr", "## Article 17 — Erasure\nErasure rights text.\n"
    )
    kb = LegalKnowledgeBase()
    asyncio.run(kb.build(toy_client))

    # No chunk has jurisdiction "US-TX" — pool is empty, should fall back to
    # searching everything rather than silently returning nothing, but must
    # log a warning so this isn't a silent behavior.
    with caplog.at_level("WARNING"):
        results = asyncio.run(
            kb.retrieve("erasure", toy_client, jurisdictions=["US-TX"], top_k=5)
        )
    assert results
    assert any("US-TX" in r.message for r in caplog.records)


def test_retrieve_returns_empty_on_embedding_dimension_mismatch(patched_paths, toy_client):
    corpus_dir, _, _ = patched_paths
    _write_corpus_file(
        corpus_dir, "eu", "gdpr", "## Article 17 — Erasure\nErasure rights text.\n"
    )
    kb = LegalKnowledgeBase()
    asyncio.run(kb.build(toy_client))

    class WrongDimClient:
        async def embed(self, text, model=None):
            return [1.0, 0.0, 0.0, 0.0, 0.0]  # 5 dims vs. the 3-dim index built above

    result = asyncio.run(kb.retrieve("erasure", WrongDimClient()))
    assert result == []


def test_load_returns_false_and_retrieve_returns_empty_on_corrupted_index(
    patched_paths, toy_client
):
    _, index_path, metadata_path = patched_paths
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_bytes(b"not a valid numpy file")
    metadata_path.write_text("also not valid json", encoding="utf-8")

    kb = LegalKnowledgeBase()
    assert kb._load() is False
    result = asyncio.run(kb.retrieve("anything", toy_client))
    assert result == []


def test_parse_corpus_file_propagates_placeholder_status(tmp_path):
    directory = tmp_path / "eu"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "gdpr.txt").write_text(
        "# Jurisdiction: GDPR\n"
        "# Law: GDPR\n"
        "# Status: PLACEHOLDER\n"
        "# Source: test\n\n"
        "## Article 17 — Erasure\nSample text.\n",
        encoding="utf-8",
    )
    chunks = _parse_corpus_file(directory / "gdpr.txt")
    assert len(chunks) == 1
    assert chunks[0]["status"] == "PLACEHOLDER"


def test_cli_main_indexes_corpus_and_prints_count(patched_paths, monkeypatch, capsys):
    corpus_dir, _, _ = patched_paths
    _write_corpus_file(
        corpus_dir, "eu", "gdpr", "## Article 17 — Erasure\nErasure rights text.\n"
    )

    async def fake_embed(self, text, model=None):
        return _toy_embed(text)

    monkeypatch.setattr(LocalAIClient, "embed", fake_embed)
    monkeypatch.setattr(sys, "argv", ["legal_kb.py", "index", "--jurisdiction", "all"])

    asyncio.run(_main())

    captured = capsys.readouterr()
    assert "Indexed 1 legal KB chunks" in captured.out


def test_cli_main_rejects_invalid_action(monkeypatch):
    """argparse validation still runs even though the parsed args aren't
    bound to a variable (only "index" is a valid CLI action)."""
    monkeypatch.setattr(sys, "argv", ["legal_kb.py", "not-a-real-action"])

    with pytest.raises(SystemExit):
        asyncio.run(_main())
