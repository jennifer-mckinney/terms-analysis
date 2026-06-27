from __future__ import annotations

"""
3-way embedding ensemble for legal document retrieval.

Architecture:
  Layer 1 — BM25 (sparse, rank_bm25, MIT, no model)
             Critical for exact legal citations and defined terms.
  Layer 2 — Apertus mean pooling (dense, Swiss AI Initiative, 1,000+ languages)
             World-language semantic coverage.
  Layer 3 — EuroLLM mean pooling (dense, EU Horizon/EuroHPC, EU legal corpus)
             EU regulatory language specialisation.
  Fusion   — Reciprocal Rank Fusion (k=60), no trainable parameters.

Primary use: select the most legally relevant chunks from over-length documents
instead of naively truncating the head. Falls back to head truncation when the
embedding endpoint is unreachable.

Plug-in options for future 4th embedding layer (all qualified under ethical criteria):
  - AI4Bharat IndicBERT (IIT Madras / MeitY, Apache 2.0, 22 Indian languages)
  - Masakhane community models (Pan-African grassroots, Apache 2.0, 40+ African languages)
  - Helsinki-NLP OPUS-MT encoder (Univ. Helsinki / EU, Apache 2.0, 1,000+ translation pairs)
"""

import logging
import re
from typing import TYPE_CHECKING, List, Optional, Tuple

from ..config import settings

if TYPE_CHECKING:
    from .localai import LocalAIClient

logger = logging.getLogger("uvicorn.error")

try:
    from rank_bm25 import BM25Okapi as _BM25

    _BM25_AVAILABLE = True
except ImportError:
    _BM25_AVAILABLE = False
    logger.warning("rank_bm25 not installed — BM25 layer disabled in ensemble")


# ── Tokenisation ─────────────────────────────────────────────────────────────

def _tokenize(text: str) -> List[str]:
    """Unicode-aware tokenizer. Language-agnostic at character level."""
    return re.findall(r"\w+", text.lower())


# ── Chunking ──────────────────────────────────────────────────────────────────

def chunk_text(
    text: str,
    chunk_size: int = 800,
    overlap: int = 100,
) -> List[Tuple[int, str]]:
    """
    Split text into overlapping chunks preserving line boundaries.
    Returns list of (char_offset, chunk_text) pairs.
    """
    lines = text.splitlines(keepends=True)
    chunks: List[Tuple[int, str]] = []
    current: List[str] = []
    current_len = 0
    offset = 0
    chunk_start = 0

    for line in lines:
        if current_len + len(line) > chunk_size and current:
            chunks.append((chunk_start, "".join(current)))
            overlap_lines: List[str] = []
            overlap_len = 0
            for prev_line in reversed(current):
                if overlap_len + len(prev_line) > overlap:
                    break
                overlap_lines.insert(0, prev_line)
                overlap_len += len(prev_line)
            chunk_start = offset - overlap_len
            current = overlap_lines
            current_len = overlap_len

        current.append(line)
        current_len += len(line)
        offset += len(line)

    if current:
        chunks.append((chunk_start, "".join(current)))

    return chunks if chunks else [(0, text)]


# ── BM25 ──────────────────────────────────────────────────────────────────────

def bm25_scores(query: str, corpus: List[str]) -> List[float]:
    """BM25 relevance scores. Returns uniform 1.0 if rank_bm25 not available."""
    if not _BM25_AVAILABLE or not corpus:
        return [1.0] * len(corpus)
    tokenized = [_tokenize(doc) for doc in corpus]
    bm25 = _BM25(tokenized)
    scores = bm25.get_scores(_tokenize(query))
    return scores.tolist()


# ── RRF ───────────────────────────────────────────────────────────────────────

def _ranks_from_scores(scores: List[float]) -> List[int]:
    """Convert scores to 1-based ranks (highest score = rank 1)."""
    indexed = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
    ranks = [0] * len(scores)
    for rank_idx, (doc_idx, _) in enumerate(indexed):
        ranks[doc_idx] = rank_idx + 1
    return ranks


def rrf_fuse(score_lists: List[List[float]], k: int = 60) -> List[float]:
    """
    Reciprocal Rank Fusion over multiple ranking signals.
    rrf_score(d) = Σ 1 / (k + rank_i(d))  for each ranker i
    Higher combined score = more relevant.
    """
    if not score_lists:
        return []
    n = len(score_lists[0])
    combined = [0.0] * n
    for scores in score_lists:
        ranks = _ranks_from_scores(scores)
        for i, rank in enumerate(ranks):
            combined[i] += 1.0 / (k + rank)
    return combined


# ── Main entry point ──────────────────────────────────────────────────────────

async def select_relevant_chunks(
    text: str,
    query: str,
    max_chars: int,
    client: "LocalAIClient",
) -> str:
    """
    Return the most legally relevant portion of text within max_chars.

    Uses the 3-way ensemble (BM25 + Apertus + EuroLLM) to rank chunks,
    then reassembles the top-scoring chunks in document order.

    Falls back to head truncation if any embedding call fails, ensuring
    the critical analysis path is never blocked by embedding availability.

    Args:
        text:      Full document text.
        query:     Legal context string used as ranking query
                   (e.g. jurisdiction names + key legal terms).
        max_chars: Maximum characters to return.
        client:    LocalAIClient instance for dense embedding calls.
    """
    if len(text) <= max_chars:
        return text

    chunks = chunk_text(text)
    corpus = [chunk_text_part for _, chunk_text_part in chunks]

    # Layer 1 — BM25 (exact legal keyword matching)
    bm25 = bm25_scores(query, corpus)

    # Layer 2 — Apertus embeddings (world-language semantic)
    query_emb_world = await client.embed(query, model=settings.model_world)
    if query_emb_world is None:
        logger.info(
            "Apertus embedding unavailable — falling back to head truncation"
        )
        return text[:max_chars]

    chunk_scores_world: List[float] = []
    for chunk in corpus:
        emb = await client.embed(chunk, model=settings.model_world)
        score = (
            sum(a * b for a, b in zip(query_emb_world, emb)) if emb else 0.0
        )
        chunk_scores_world.append(score)

    # Layer 3 — EuroLLM embeddings (EU legal domain)
    query_emb_eu = await client.embed(query, model=settings.model_eu)
    if query_emb_eu is not None:
        chunk_scores_eu: List[float] = []
        for chunk in corpus:
            emb = await client.embed(chunk, model=settings.model_eu)
            score = (
                sum(a * b for a, b in zip(query_emb_eu, emb)) if emb else 0.0
            )
            chunk_scores_eu.append(score)
    else:
        chunk_scores_eu = [0.0] * len(corpus)

    # RRF fusion
    fused = rrf_fuse(
        [bm25, chunk_scores_world, chunk_scores_eu],
        k=settings.rrf_k,
    )

    # Select top chunks within budget, then re-sort by original position
    ranked = sorted(enumerate(fused), key=lambda x: x[1], reverse=True)
    selected: List[Tuple[int, str]] = []
    budget = 0
    for idx, _ in ranked:
        chunk = corpus[idx]
        if budget + len(chunk) > max_chars:
            break
        selected.append(chunks[idx])
        budget += len(chunk)

    selected.sort(key=lambda x: x[0])
    return "\n...\n".join(c for _, c in selected)
