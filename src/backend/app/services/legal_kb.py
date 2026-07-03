from __future__ import annotations

"""
Legal knowledge base (RAG) — retrieves relevant statute/regulation passages
to augment LLM prompts with citable legal context.

Architecture:
  Corpus   — data/legal_corpus/<jurisdiction>/<law>.txt (see .claude/skills/legal-kb)
  Chunking — reuses embedding.py::chunk_text, preserving "## Article/Section N —
             Title" boundaries where present so each chunk stays citable.
  Dense    — Apertus embeddings via LocalAIClient.embed(), L2-normalized and
             persisted as a plain numpy matrix. Similarity is exact cosine
             (normalized dot product) computed exhaustively over the
             jurisdiction-filtered pool — no approximate/ANN index (FAISS was
             considered and rejected: it is Meta-origin, which the project's
             own dependency no-go list excludes, and at this corpus size
             exhaustive search costs nothing).
  Sparse   — BM25 (rank_bm25, via embedding.py::bm25_scores) over the same
             pool, for exact citation/defined-term matches.
  Fusion   — Reciprocal Rank Fusion (embedding.py::rrf_fuse), same k as the
             document-chunk ensemble.

Falls back to an empty result set if the index hasn't been built yet, the
embedding endpoint is unreachable, or retrieval fails for any other reason
(e.g. a stale index built with a different embedding dimension) —
analyze_text() must never be blocked by legal-KB availability (same fallback
philosophy as embedding.py/localai.py).
"""

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from ..config import settings
from .embedding import bm25_scores, chunk_text, rrf_fuse
from .localai import LocalAIClient

logger = logging.getLogger("uvicorn.error")

_SECTION_HEADER = re.compile(r"^##\s+(.+)$", re.MULTILINE)
_META_LINE = re.compile(r"^#\s*([\w ]+):\s*(.+)$")

# Placeholder-status chunks must always carry this warning into the LLM
# prompt — see build_user_prompt() in prompts.py.
PLACEHOLDER_STATUS = "placeholder"


def _parse_corpus_file(path: Path) -> List[Dict[str, Any]]:
    """Parse one data/legal_corpus/<jurisdiction>/<law>.txt file into chunks.

    Leading "# Key: Value" lines are file-level metadata applied to every
    chunk (including a "# Status: PLACEHOLDER" line, if present, which must
    survive into every chunk so retrieval callers can flag non-authoritative
    text — see prompts.py::build_user_prompt). Each "## Article/Section N —
    Title" block becomes one or more chunks (split via chunk_text if it
    exceeds the chunk window); files without section headers are chunked as
    a single block.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    meta: Dict[str, str] = {}
    body_start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            body_start = i + 1
            continue
        m = _META_LINE.match(line)
        if m:
            meta[m.group(1).strip().lower()] = m.group(2).strip()
            body_start = i + 1
        else:
            break
    body = "\n".join(lines[body_start:])

    sections = _SECTION_HEADER.split(body)
    chunks: List[Dict[str, Any]] = []

    if len(sections) <= 1:
        for _, chunk in chunk_text(body):
            cleaned = chunk.strip()
            if cleaned:
                chunks.append({"text": cleaned, "section": None, **meta})
        return chunks

    # re.split on a capturing "^## (.+)$" yields
    # [preamble, title_1, text_1, title_2, text_2, ...]
    for i in range(1, len(sections), 2):
        title = sections[i].strip()
        section_text = sections[i + 1].strip() if i + 1 < len(sections) else ""
        if not section_text:
            continue
        for _, chunk in chunk_text(section_text, chunk_size=1000, overlap=150):
            cleaned = chunk.strip()
            if cleaned:
                chunks.append({"text": f"{title}\n{cleaned}", "section": title, **meta})
    return chunks


def _iter_corpus_files(corpus_dir: Path) -> List[Path]:
    if not corpus_dir.is_dir():
        return []
    return sorted(corpus_dir.glob("*/*.txt"))


def _normalize(vector: List[float]) -> Optional[np.ndarray]:
    array = np.array(vector, dtype="float32")
    norm = np.linalg.norm(array)
    if norm == 0:
        return None
    return array / norm


class LegalKnowledgeBase:
    """Exact (exhaustive, non-approximate) search over an embedded legal corpus."""

    def __init__(self) -> None:
        self._matrix: Optional[np.ndarray] = None  # shape (n_chunks, dim), L2-normalized
        self._chunks: List[Dict[str, Any]] = []

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    async def build(
        self, client: LocalAIClient, corpus_dir: Optional[Path] = None
    ) -> int:
        """Chunk + embed the corpus, persist the vector matrix + metadata to disk.

        Returns the number of chunks indexed (0 if the corpus directory is
        empty or the embedding endpoint is unreachable).
        """
        directory = corpus_dir or settings.legal_corpus_dir
        chunks: List[Dict[str, Any]] = []
        for file_path in _iter_corpus_files(directory):
            chunks.extend(_parse_corpus_file(file_path))

        if not chunks:
            logger.warning("No legal corpus files found under %s", directory)
            return 0

        vectors: List[np.ndarray] = []
        kept_chunks: List[Dict[str, Any]] = []
        for chunk in chunks:
            embedding = await client.embed(chunk["text"], model=settings.model_world)
            if embedding is None:
                continue
            normalized = _normalize(embedding)
            if normalized is None:
                continue
            vectors.append(normalized)
            kept_chunks.append(chunk)

        if not vectors:
            logger.warning("Embedding endpoint unreachable — legal KB index not built")
            return 0

        matrix = np.stack(vectors).astype("float32")

        settings.legal_kb_index_path.parent.mkdir(parents=True, exist_ok=True)
        np.save(settings.legal_kb_index_path, matrix)
        settings.legal_kb_metadata_path.write_text(
            json.dumps(kept_chunks, indent=2), encoding="utf-8"
        )

        self._matrix = matrix
        self._chunks = kept_chunks
        logger.info("Legal KB built: %d chunks from %s", len(kept_chunks), directory)
        return len(kept_chunks)

    def _load(self) -> bool:
        if self._matrix is not None:
            return True
        index_path = settings.legal_kb_index_path
        metadata_path = settings.legal_kb_metadata_path
        if not index_path.exists() or not metadata_path.exists():
            return False
        try:
            self._matrix = np.load(index_path)
            self._chunks = json.loads(metadata_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to load legal KB index: %s", exc)
            self._matrix = None
            self._chunks = []
            return False
        if self._matrix.shape[0] != len(self._chunks):
            logger.warning(
                "Legal KB index/metadata mismatch (%d vectors, %d chunks) — ignoring",
                self._matrix.shape[0],
                len(self._chunks),
            )
            self._matrix = None
            self._chunks = []
            return False
        return True

    async def retrieve(
        self,
        query: str,
        client: LocalAIClient,
        jurisdictions: Optional[List[str]] = None,
        top_k: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Return top-k relevant legal chunks, optionally filtered by jurisdiction.

        Returns [] if the index hasn't been built, the embedding endpoint is
        unreachable, or retrieval fails for any reason (e.g. a stale index
        built with a different embedding dimension) — callers must treat
        legal-KB context as optional, never load-bearing for analyze_text().
        """
        try:
            return await self._retrieve(query, client, jurisdictions, top_k)
        except Exception as exc:
            logger.warning("Legal KB retrieval failed, returning no context: %s", exc)
            return []

    async def _retrieve(
        self,
        query: str,
        client: LocalAIClient,
        jurisdictions: Optional[List[str]],
        top_k: Optional[int],
    ) -> List[Dict[str, Any]]:
        if not self._load() or not self._chunks:
            return []

        if jurisdictions:
            wanted = {j.lower() for j in jurisdictions}
            pool = [
                i
                for i, c in enumerate(self._chunks)
                if c.get("jurisdiction", "").lower() in wanted
            ]
            if not pool:
                logger.warning(
                    "No legal KB chunks match jurisdictions=%s — searching full corpus",
                    jurisdictions,
                )
                pool = list(range(len(self._chunks)))
        else:
            pool = list(range(len(self._chunks)))

        query_embedding = await client.embed(query, model=settings.model_world)
        if query_embedding is None:
            return []
        query_vec = _normalize(query_embedding)
        if query_vec is None:
            return []

        if query_vec.shape[0] != self._matrix.shape[1]:
            logger.warning(
                "Legal KB embedding dimension mismatch (query=%d, index=%d) — "
                "index likely stale for the current embedding model",
                query_vec.shape[0],
                self._matrix.shape[1],
            )
            return []

        # Exact (exhaustive) cosine similarity over the full jurisdiction-filtered
        # pool — no top-K truncation before filtering/fusion, so relevant chunks
        # in a minority jurisdiction can't be silently dropped.
        pool_matrix = self._matrix[pool]
        dense_scores = (pool_matrix @ query_vec).tolist()
        pool_texts = [self._chunks[idx]["text"] for idx in pool]
        bm25 = bm25_scores(query, pool_texts)
        fused = rrf_fuse([dense_scores, bm25], k=settings.rrf_k)

        k = top_k or settings.legal_kb_top_k
        ranked = sorted(zip(pool, fused), key=lambda pair: pair[1], reverse=True)[:k]

        return [{**self._chunks[idx], "score": score} for idx, score in ranked]


_legal_kb = LegalKnowledgeBase()


def get_legal_kb() -> LegalKnowledgeBase:
    return _legal_kb


async def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Build the legal knowledge base index")
    parser.add_argument("action", choices=["index"], help="Action to perform")
    parser.add_argument(
        "--jurisdiction",
        default="all",
        help=(
            "Present for CLI compatibility with .claude/skills/legal-kb/SKILL.md; "
            "the index is always rebuilt from the full corpus directory since a "
            "full rebuild is simplest/correct at this corpus size."
        ),
    )
    args = parser.parse_args()

    kb = get_legal_kb()
    client = LocalAIClient()
    count = await kb.build(client)
    print(f"Indexed {count} legal KB chunks from {settings.legal_corpus_dir}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(_main())
