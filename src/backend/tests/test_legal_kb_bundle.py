from __future__ import annotations

import json

import numpy as np
import pytest
import yaml
from pathlib import Path

from app.services.legal_kb import LegalKnowledgeBase
from app.schemas import CorpusMismatchError


def _make_bundle(tmp_path: Path, chunker_version: str = "v1.0.0", n: int = 3) -> Path:
    """Write a minimal valid bundle to tmp_path and return bundle_dir."""
    bundle_dir = tmp_path / "bundle"
    (bundle_dir / "index").mkdir(parents=True)

    # Write MANIFEST.yaml
    manifest = {
        "corpus_version": "2026.07.0",
        "chunker_version": chunker_version,
        "embedder_model": "apertus-8b-instruct",
        "embedder_revision": "abc123",
        "sources": ["GDPR"],
        "chunk_count": n,
    }
    (bundle_dir / "MANIFEST.yaml").write_text(yaml.dump(manifest), encoding="utf-8")

    # Write legal_kb.npy (n × 1024, L2-normalized float32)
    raw = np.random.default_rng(42).random((n, 1024)).astype(np.float32)
    norms = np.linalg.norm(raw, axis=1, keepdims=True)
    matrix = raw / norms
    np.save(str(bundle_dir / "index" / "legal_kb.npy"), matrix)

    # Write legal_kb_metadata.json
    chunks = [
        {
            "source_name": "GDPR",
            "section": f"Art {i}",
            "text": f"text {i}",
            "offset_start": i * 10,
            "offset_end": i * 10 + 9,
            "license": "CC-BY-4.0",
        }
        for i in range(n)
    ]
    (bundle_dir / "index" / "legal_kb_metadata.json").write_text(
        json.dumps(chunks), encoding="utf-8"
    )
    return bundle_dir


def test_load_from_bundle_succeeds(tmp_path: Path) -> None:
    bundle_dir = _make_bundle(tmp_path)
    kb = LegalKnowledgeBase()
    kb.load_from_bundle(bundle_dir)
    assert kb.chunk_count == 3
    assert kb._matrix.shape == (3, 1024)
    assert kb._matrix.dtype == np.float32


def test_load_from_bundle_raises_on_chunker_version_mismatch(tmp_path: Path) -> None:
    bundle_dir = _make_bundle(tmp_path, chunker_version="v1.0.0")
    kb = LegalKnowledgeBase()
    with pytest.raises(CorpusMismatchError) as exc_info:
        kb.load_from_bundle(bundle_dir, expected_chunker_version="v2.0.0")
    assert exc_info.value.dimension == "chunker_version"


def test_load_from_bundle_raises_on_embedder_model_mismatch(tmp_path: Path) -> None:
    bundle_dir = _make_bundle(tmp_path)
    kb = LegalKnowledgeBase()
    with pytest.raises(CorpusMismatchError) as exc_info:
        kb.load_from_bundle(bundle_dir, expected_embedder_model="different-model")
    assert exc_info.value.dimension == "embedder_model"


def test_load_from_bundle_raises_on_embedder_revision_mismatch(tmp_path: Path) -> None:
    bundle_dir = _make_bundle(tmp_path)
    kb = LegalKnowledgeBase()
    with pytest.raises(CorpusMismatchError) as exc_info:
        kb.load_from_bundle(bundle_dir, expected_embedder_revision="wrong-revision")
    assert exc_info.value.dimension == "embedder_revision"


def test_load_from_bundle_raises_on_missing_manifest(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "empty_bundle"
    bundle_dir.mkdir()
    kb = LegalKnowledgeBase()
    with pytest.raises(FileNotFoundError):
        kb.load_from_bundle(bundle_dir)


def test_load_from_bundle_raises_on_missing_index(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    (bundle_dir / "index").mkdir(parents=True)
    manifest = {
        "corpus_version": "2026.07.0",
        "chunker_version": "v1.0.0",
        "embedder_model": "apertus-8b-instruct",
        "embedder_revision": "abc123",
        "sources": ["GDPR"],
        "chunk_count": 1,
    }
    (bundle_dir / "MANIFEST.yaml").write_text(yaml.dump(manifest), encoding="utf-8")
    # intentionally omit legal_kb.npy
    kb = LegalKnowledgeBase()
    with pytest.raises(FileNotFoundError):
        kb.load_from_bundle(bundle_dir)


def test_load_from_bundle_raises_on_missing_metadata(tmp_path: Path) -> None:
    bundle_dir = _make_bundle(tmp_path)
    # Remove the metadata file to trigger the FileNotFoundError
    (bundle_dir / "index" / "legal_kb_metadata.json").unlink()
    kb = LegalKnowledgeBase()
    with pytest.raises(FileNotFoundError):
        kb.load_from_bundle(bundle_dir)


def test_load_from_bundle_raises_on_chunk_count_mismatch(tmp_path: Path) -> None:
    """Matrix row count != metadata chunk count triggers CorpusMismatchError."""
    bundle_dir = _make_bundle(tmp_path, n=3)
    # Overwrite metadata with only 2 chunks while matrix has 3 rows
    two_chunks = [
        {"source_name": "GDPR", "section": f"Art {i}", "text": f"text {i}",
         "offset_start": i * 10, "offset_end": i * 10 + 9, "license": "CC-BY-4.0"}
        for i in range(2)
    ]
    (bundle_dir / "index" / "legal_kb_metadata.json").write_text(
        json.dumps(two_chunks), encoding="utf-8"
    )
    kb = LegalKnowledgeBase()
    with pytest.raises(CorpusMismatchError) as exc_info:
        kb.load_from_bundle(bundle_dir)
    assert exc_info.value.dimension == "chunk_count"
    assert exc_info.value.expected == "2"   # metadata chunk count
    assert exc_info.value.actual == "3"     # matrix row count


def test_load_from_bundle_no_version_check_passes(tmp_path: Path) -> None:
    """Without expected_* params, any version passes."""
    bundle_dir = _make_bundle(tmp_path, chunker_version="anything")
    kb = LegalKnowledgeBase()
    kb.load_from_bundle(bundle_dir)  # no exception
    assert kb.chunk_count == 3


def test_load_from_bundle_raises_on_empty_manifest(tmp_path: Path) -> None:
    """Empty MANIFEST.yaml must raise CorpusMismatchError, not AttributeError."""
    bundle_dir = tmp_path / "bundle"
    (bundle_dir / "index").mkdir(parents=True)
    (bundle_dir / "MANIFEST.yaml").write_text("", encoding="utf-8")
    kb = LegalKnowledgeBase()
    with pytest.raises(CorpusMismatchError) as exc_info:
        kb.load_from_bundle(bundle_dir)
    assert exc_info.value.dimension == "manifest_structure"


def test_load_from_bundle_error_message_contains_dimension(tmp_path: Path) -> None:
    """CorpusMismatchError structured attrs carry dimension, expected, actual."""
    bundle_dir = _make_bundle(tmp_path, chunker_version="v1.0.0")
    kb = LegalKnowledgeBase()
    with pytest.raises(CorpusMismatchError) as exc_info:
        kb.load_from_bundle(bundle_dir, expected_chunker_version="v9.0.0")
    assert exc_info.value.dimension == "chunker_version"
    assert exc_info.value.expected == "v9.0.0"
    assert exc_info.value.actual == "v1.0.0"
