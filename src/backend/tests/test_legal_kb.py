from __future__ import annotations

import asyncio
import json

import numpy as np
import pytest

import sys

from app.config import settings
from app.services.legal_kb import (
    LegalKBIndexCorruptError,
    LegalKnowledgeBase,
    RetrievalStatus,
    _main,
    _parse_corpus_file,
)
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


def test_retrieve_is_no_index_when_no_index_built(patched_paths, toy_client):
    kb = LegalKnowledgeBase()
    result = asyncio.run(kb.retrieve("erasure of personal data", toy_client))
    assert result.chunks == ()
    assert result.status is RetrievalStatus.NO_INDEX


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

    result = asyncio.run(kb.retrieve("right to erasure", toy_client, top_k=2))
    assert result.status is RetrievalStatus.OK
    assert len(result.chunks) >= 1
    assert "erasure" in result.chunks[0]["text"].lower()


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
    ).chunks
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
    result = asyncio.run(reloaded.retrieve("erasure rights", toy_client))
    assert reloaded.chunk_count == 1
    assert result.status is RetrievalStatus.OK
    assert result.chunks


def test_build_returns_zero_for_empty_corpus_dir(patched_paths, toy_client):
    kb = LegalKnowledgeBase()
    count = asyncio.run(kb.build(toy_client))
    assert count == 0
    assert kb.chunk_count == 0


def test_retrieve_is_error_when_embedding_endpoint_unreachable(
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
    assert result.chunks == ()
    assert result.status is RetrievalStatus.ERROR


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
    ).chunks
    assert results
    assert all(r["jurisdiction"] == "GDPR" for r in results)

    results = asyncio.run(
        kb.retrieve("retention", toy_client, jurisdictions=["PIPEDA"], top_k=5)
    ).chunks
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
        ).chunks
    assert results
    assert any("US-TX" in r.message for r in caplog.records)


def test_retrieve_embedding_dimension_mismatch_is_error(patched_paths, toy_client):
    # Grumpy F8: list equality ignored .status, so the old ``result == []``
    # would also have passed for a wrong NO_MATCH. Assert the status itself.
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
    assert result.chunks == ()
    assert result.status is RetrievalStatus.ERROR
    assert result.grounded is False


def test_load_raises_and_retrieve_reports_error_on_corrupted_index(
    patched_paths, toy_client
):
    # Issue #91: _load() now raises a typed error instead of returning False,
    # and retrieve() reports ERROR (not a silent, status-less []).
    _, index_path, metadata_path = patched_paths
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_bytes(b"not a valid numpy file")
    metadata_path.write_text("also not valid json", encoding="utf-8")

    kb = LegalKnowledgeBase()
    with pytest.raises(LegalKBIndexCorruptError):
        kb._load()
    result = asyncio.run(kb.retrieve("anything", toy_client))
    assert result.chunks == ()
    assert result.status is RetrievalStatus.ERROR


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


# --- G0-6 (#177): build() and _load() degraded paths -------------------------


def test_build_returns_zero_and_writes_nothing_when_every_embedding_fails(
    patched_paths, monkeypatch
):
    """An unreachable embedding endpoint must yield 0 chunks and no index files,
    so the caller can tell "not built" apart from a successful build."""
    corpus_dir, index_path, metadata_path = patched_paths
    _write_corpus_file(
        corpus_dir, "eu", "gdpr", "## Article 17 — Erasure\nErasure rights text.\n"
    )

    async def unreachable_embed(self, text, model=None):
        return None

    monkeypatch.setattr(LocalAIClient, "embed", unreachable_embed)
    kb = LegalKnowledgeBase()
    assert asyncio.run(kb.build(LocalAIClient())) == 0
    assert kb.chunk_count == 0
    assert not index_path.exists()
    assert not metadata_path.exists()


@pytest.mark.parametrize(
    "bad_vector",
    [
        pytest.param([0.0, 0.0, 0.0], id="zero"),
        # Round 3 (CI review MEDIUM, ref #91): a non-finite embedding used to
        # normalise to an all-NaN row and be written into the index.
        pytest.param([float("nan"), 0.0, 1.0], id="nan"),
        pytest.param([float("inf"), 1.0, 0.0], id="pos-inf"),
        pytest.param([1.0, float("-inf"), 0.0], id="neg-inf"),
        pytest.param([1e39, 0.0, 0.0], id="float32-overflow"),
    ],
)
def test_build_skips_chunks_whose_embedding_is_a_zero_vector(
    patched_paths, monkeypatch, bad_vector
):
    """A zero or non-finite vector cannot be L2-normalized; that chunk is
    dropped while the others are still indexed and persisted, and no NaN or
    inf row ever reaches the on-disk matrix."""
    corpus_dir, index_path, metadata_path = patched_paths
    _write_corpus_file(
        corpus_dir,
        "eu",
        "gdpr",
        "## Article 7 — Consent\nConsent text.\n\n## Article 99 — Misc\nOther text.\n",
    )

    async def partial_embed(self, text, model=None):
        # "Misc" chunk gets the degenerate embedding; the consent chunk is valid.
        return list(bad_vector) if "Misc" in text else _toy_embed(text)

    monkeypatch.setattr(LocalAIClient, "embed", partial_embed)
    kb = LegalKnowledgeBase()
    assert asyncio.run(kb.build(LocalAIClient())) == 1
    persisted = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert [c["section"] for c in persisted] == ["Article 7 — Consent"]
    matrix = np.load(index_path)
    assert matrix.shape[0] == 1
    assert np.isfinite(matrix).all()


def test_load_rejects_index_whose_row_count_disagrees_with_metadata(
    patched_paths, toy_client
):
    """A 2-row matrix next to 1 metadata entry is a stale/mixed bundle: _load()
    must refuse it and retrieve() must return no context.

    Issue #91: _load() raises a typed error instead of returning False, and
    retrieve() reports ERROR (not a silent, status-less [])."""
    _, index_path, metadata_path = patched_paths
    index_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(index_path, np.eye(2, 3, dtype="float32"))
    metadata_path.write_text(
        json.dumps([{"text": "only one", "section": None, "jurisdiction": "EU"}]),
        encoding="utf-8",
    )

    kb = LegalKnowledgeBase()
    with pytest.raises(LegalKBIndexCorruptError, match="index/metadata mismatch"):
        kb._load()
    assert kb.chunk_count == 0
    result = asyncio.run(kb.retrieve("erasure", toy_client))
    assert result.chunks == ()
    assert result.status is RetrievalStatus.ERROR
