from __future__ import annotations

"""
Chunking, BM25, RRF and query-format primitives for legal retrieval.

Used by the legal KB (legal_kb.py):
  BM25   — sparse, rank_bm25 (MIT, no model). Exact legal citations and
           defined terms.
  Dense  — settings.embedding_model (multilingual-e5-large-instruct) via
           LocalAIClient.embed. Queries use format_e5_query; passages are
           embedded raw.
  Fusion — Reciprocal Rank Fusion (settings.rrf_k), no trainable parameters.

The former select_relevant_chunks (BM25 + Apertus + EuroLLM mean-pool over a
document's own chunks) was removed in #98-A: it had no caller, embedded with
generative models (F7), and the e5 query task is legal-KB specific.
"""

import logging
import re
from typing import List, Tuple

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


# ── e5-instruct query format ─────────────────────────────────────────────────

_WHITESPACE_RUN_RE = re.compile(r"\s+")


def format_e5_query(task: str, text: str) -> str:
    r"""Return the e5-instruct query input: ``Instruct: <task>\nQuery: <text>``.

    The task is validated in config (printable ASCII, single spaces). The
    user text has every whitespace run (including every Unicode line break)
    collapsed to one space, so the result holds exactly one line break and
    user text cannot forge an ``Instruct:`` line (F5). Not stripped: the
    collapse alone removes the structure, and leading/trailing spaces are
    harmless to the model.
    """
    return f"Instruct: {task}\nQuery: {_WHITESPACE_RUN_RE.sub(' ', text)}"
