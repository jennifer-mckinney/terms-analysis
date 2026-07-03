# Open-Source Compliance & RAG Pipeline Implementation Plan

> **Status (2026-07-03): this plan was NOT executed as written.** The codebase never had `lm_studio.py` to rename — the actual LLM client (`services/localai.py`) targets LocalAI + Apertus-8B/EuroLLM-22B, not LM Studio/Ollama. A RAG pipeline was later built (issue #6) via a **different approach** than Tasks 3-6 below: `services/legal_kb.py` uses **FAISS** (`IndexFlatIP`, exact inner-product search) for the vector index rather than the sentence-transformers/onnx + numpy-exhaustive design specified here, and reuses the existing LocalAI-based embedding client (`localai.py::embed()`) rather than adding `intfloat/multilingual-e5-large-instruct` as a new local model. `legal_kb.py` does exist now (Task 5's goal), fusing FAISS dense scores with BM25 via Reciprocal Rank Fusion — same fusion strategy this plan specified, different vector backend. Task 7 (IRP scoring) and Task 8 (jurisdiction rule expansion beyond the current 30 codes) remain **not implemented**. Task 1 (LM Studio→Ollama) and Task 2 (rule pattern tightening) were separately not undertaken. Treat this document as historical context for the fusion-retrieval design rationale, not as an accurate task list for current work.

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the proprietary LM Studio dependency with Ollama (open source), fix false-positive rule patterns, and build the planned RAG pipeline using local open-source embeddings and exhaustive exact vector search.

**Architecture:** The LLM layer is an HTTP client hitting an OpenAI-compatible chat/completions endpoint — swapping LM Studio for Ollama requires only renaming files and changing defaults. The RAG pipeline is additive: a new embeddings service and legal knowledge base slot between the rule engine and LLM call in `analyzer.py`, augmenting the LLM prompt with retrieved legal text. Vector search uses exhaustive numpy dot-product (exact, no approximation) — required for a legal risk tool where false negatives have compliance consequences.

**Tech Stack:** FastAPI, SQLite/SQLAlchemy, Ollama CLI (MIT) + SaulLM-7B-Instruct (MIT, Equall.ai/France), sentence-transformers[onnx] (Apache 2.0, UKP Lab/Germany) + onnxruntime (MIT, Microsoft) + intfloat/multilingual-e5-large-instruct (MIT, Microsoft Research — 100+ languages for world jurisdiction coverage), numpy exhaustive exact search (BSD), rank-bm25 (Apache 2.0), pytest + pytest-asyncio

**No-go list enforced:** No Meta/Facebook (no faiss, no torch/PyTorch). No OpenAI. No Grok/xAI. No Chinese-origin models or tools (no Qwen, no BAAI/bge-m3). No approximate/HNSW vector search.

---

## Task 1: Migrate LM Studio → Ollama (rename service + config)

**Files:**
- Rename: `src/backend/app/services/lm_studio.py` → `src/backend/app/services/llm_client.py`
- Modify: `src/backend/app/config.py:26-31`
- Modify: `src/backend/app/services/analyzer.py:11`
- Modify: `src/backend/tests/test_llm_failure.py:6,13,37`
- Modify: `.env.example`
- Modify: `.claude/CLAUDE.md` (project map row)

**Step 1: Copy lm_studio.py to llm_client.py with class rename**

Create `src/backend/app/services/llm_client.py` with the exact content of `lm_studio.py` but with these changes:
- Class name: `LmStudioClient` → `OllamaClient`
- Log strings: replace `"LM Studio"` with `"Ollama"`

```python
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

import httpx

from ..config import settings
from .prompts import SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger("uvicorn.error")


class OllamaClient:
    def __init__(self) -> None:
        base_url = settings.llm_base_url.rstrip("/")
        if not base_url.endswith("/v1"):
            base_url = f"{base_url}/v1"
        self._base_url = base_url
        self._model = settings.llm_model
        self._timeout = settings.request_timeout_s

    async def analyze(
        self,
        numbered_text: str,
        jurisdictions: list[str],
        rule_findings: list[dict],
    ) -> Optional[Dict[str, Any]]:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_user_prompt(
                    numbered_text=numbered_text,
                    jurisdictions=jurisdictions,
                    rule_findings=rule_findings,
                ),
            },
        ]
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 1200,
        }
        endpoint = f"{self._base_url}/chat/completions"
        logger.info("Ollama request: endpoint=%s model=%s", endpoint, self._model)
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(endpoint, json=payload)
                logger.info(
                    "Ollama response: status=%s bytes=%s",
                    response.status_code,
                    len(response.content),
                )
                response.raise_for_status()
                try:
                    response_data = response.json()
                except ValueError as exc:
                    logger.warning("Ollama response JSON decode failed: %s", exc)
                    return None
                try:
                    content = response_data["choices"][0]["message"]["content"]
                except (KeyError, IndexError, TypeError) as exc:
                    logger.warning("Ollama response missing content: %s", exc)
                    return None
        except httpx.HTTPStatusError as exc:
            body = exc.response.text
            logger.warning(
                "Ollama HTTP %s: %s",
                exc.response.status_code,
                body[:300].replace("\n", "\\n"),
            )
            return None
        except httpx.HTTPError as exc:
            logger.warning("Ollama HTTP error: %s", exc)
            return None

        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            logger.warning(
                "Ollama content not JSON (len=%s): %s",
                len(content) if isinstance(content, str) else 0,
                exc,
            )
            return None
```

**Step 2: Update config.py to use generic llm_* names**

Replace lines 26-31 in `src/backend/app/config.py`:

```python
    llm_base_url: str = os.getenv(
        "LLM_BASE_URL", "http://localhost:11434/v1"
    )
    llm_model: str = os.getenv(
        "LLM_MODEL", "saullm-7b-instruct"
    )
```

**Step 3: Update analyzer.py import**

In `src/backend/app/services/analyzer.py`, replace line 11:
```python
# Old:
from .lm_studio import LmStudioClient
# New:
from .llm_client import OllamaClient
```

Also replace line 81:
```python
# Old:
    client = LmStudioClient()
# New:
    client = OllamaClient()
```

**Step 4: Update test_llm_failure.py**

Replace lines 6, 13, and 37 in `src/backend/tests/test_llm_failure.py`:
```python
# Line 6 — old:
from app.services.lm_studio import LmStudioClient
# Line 6 — new:
from app.services.llm_client import OllamaClient

# Line 13 — old:
    monkeypatch.setattr(LmStudioClient, "analyze", fake_analyze)
# Line 13 — new:
    monkeypatch.setattr(OllamaClient, "analyze", fake_analyze)

# Line 37 — old:
    result = asyncio.run(LmStudioClient().analyze("text", ["US-CA"], []))
# Line 37 — new:
    result = asyncio.run(OllamaClient().analyze("text", ["US-CA"], []))
```

**Step 5: Update .env.example**

Replace content:
```
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=saullm-7b-instruct
DATABASE_URL=sqlite:///./data/terms_analysis.db
REVIEW_THRESHOLD=0.80
ALLOWED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
WATCHLIST_REFRESH_SECONDS=0
```

**Step 6: Delete lm_studio.py**

```bash
rm src/backend/app/services/lm_studio.py
```

**Step 7: Run the full test suite to verify nothing broke**

```bash
cd src/backend && python -m pytest -v
```

Expected: All tests PASS. If `test_llm_failure.py` fails with ImportError, double-check step 4.

**Step 8: Commit**

```bash
git add src/backend/app/services/llm_client.py \
        src/backend/app/services/analyzer.py \
        src/backend/app/config.py \
        src/backend/tests/test_llm_failure.py \
        .env.example
git rm src/backend/app/services/lm_studio.py
git commit -m "feat: migrate LM Studio to Ollama (open-source compliance)"
```

---

## Task 2: Fix Over-Broad Rule Patterns

**Files:**
- Modify: `src/backend/app/services/rules.py:75-121`
- Modify: `src/backend/tests/test_rules.py`

**Context:** The `User Rights` category has patterns (`r"access"`, `r"delete"`, `r"correct"`) that match virtually any document. `r"retain"` in Retention is similarly noisy. These generate false positives that depress overall confidence scores.

**Step 1: Write failing tests that expose the false-positive problem**

Add to `src/backend/tests/test_rules.py`:

```python
def test_user_rights_does_not_fire_on_generic_access_language():
    # "access" in a non-rights context must NOT trigger User Rights
    text = "You may access our platform using a web browser. Third parties may access logs."
    findings = detect_findings(text, ["US-CA", "GDPR"])
    categories = {f.category for f in findings}
    assert "User Rights" not in categories


def test_user_rights_fires_on_explicit_right_language():
    text = "You have the right to access, delete, and correct your personal data."
    findings = detect_findings(text, ["US-CA", "GDPR"])
    categories = {f.category for f in findings}
    assert "User Rights" in categories


def test_retention_does_not_fire_on_generic_retain():
    # "retain" in a non-privacy context must NOT trigger Retention
    text = "We retain the right to refuse service."
    findings = detect_findings(text, ["US-CA", "GDPR"])
    categories = {f.category for f in findings}
    assert "Retention" not in categories


def test_retention_fires_on_data_retention_language():
    text = "We retain your personal data for as long as necessary to fulfill our services."
    findings = detect_findings(text, ["US-CA", "GDPR"])
    categories = {f.category for f in findings}
    assert "Retention" in categories
```

**Step 2: Run tests to verify they fail (exposing the bug)**

```bash
cd src/backend && python -m pytest tests/test_rules.py::test_user_rights_does_not_fire_on_generic_access_language tests/test_rules.py::test_retention_does_not_fire_on_generic_retain -v
```

Expected: FAIL — the current broad patterns trigger on both.

**Step 3: Replace the User Rights and Retention patterns in rules.py**

Replace the `User Rights` `RulePattern` (lines 75-89) with:

```python
    RulePattern(
        category="User Rights",
        severity="Medium",
        jurisdictions=["US-CA", "GDPR"],
        explanation="Policies must describe access, deletion, and correction rights.",
        legal_basis=["GDPR Art. 15-18", "CCPA/CPRA rights"],
        patterns=[
            r"\bright\s+to\s+(?:access|deletion|erasure|portability|correction|be\s+forgotten)\b",
            r"\brequest\s+(?:deletion|access\s+to|a\s+copy\s+of)\b",
            r"\bopt[- ]?out\b",
            r"\bappeal\s+(?:our|a)\s+decision\b",
            r"\bdata\s+portability\b",
        ],
    ),
```

Replace the `Retention` `RulePattern` (lines 63-74) with:

```python
    RulePattern(
        category="Retention",
        severity="Medium",
        jurisdictions=["US-CA", "GDPR"],
        explanation="Retention periods must be disclosed and limited to necessity.",
        legal_basis=["GDPR Art. 5(1)(e)", "CPRA retention notice"],
        patterns=[
            r"\bretain\s+(?:your|personal|user|this)\b",
            r"\bdata\s+retention\b",
            r"\bretention\s+period\b",
            r"\bstore\s+(?:your|personal)\s+(?:data|information)\b",
            r"\bas\s+long\s+as\s+(?:necessary|required|needed)\b",
            r"\bindefinitely\b",
            r"\bfor\s+so\s+long\s+as\b",
        ],
    ),
```

**Step 4: Run all four new tests to verify they pass**

```bash
cd src/backend && python -m pytest tests/test_rules.py -v
```

Expected: All tests PASS including the two new regression tests.

**Step 5: Run full suite to catch regressions**

```bash
cd src/backend && python -m pytest -v
```

Expected: All tests PASS.

**Step 6: Commit**

```bash
git add src/backend/app/services/rules.py src/backend/tests/test_rules.py
git commit -m "fix: tighten over-broad User Rights and Retention rule patterns"
```

---

## Task 3: Add RAG Dependencies

**Files:**
- Modify: `src/backend/requirements.txt`

**No-go:** Do NOT add `faiss-cpu` (Meta), `torch` (Meta/PyTorch), `usearch` (HNSW = approximate), or any BAAI/Qwen packages.

**Step 1: Add the three RAG packages to requirements.txt**

Append to `src/backend/requirements.txt`:

```
sentence-transformers[onnx]>=3.0.0
onnxruntime>=1.18.0
rank-bm25>=0.2.2
```

`sentence-transformers[onnx]` uses `onnxruntime` (MIT, Microsoft) as the inference backend — no PyTorch/Meta in the stack. Vector search is done with `numpy` which is already a transitive dependency.

**Step 2: Install the new dependencies**

```bash
cd src/backend && pip install -r requirements.txt
```

Expected: Packages install. `onnxruntime` downloads the model weights on first use (~1.2GB for multilingual-e5-large).

**Step 3: Verify imports work**

```bash
python -c "from sentence_transformers import SentenceTransformer; import numpy; from rank_bm25 import BM25Okapi; print('OK')"
```

Expected output: `OK`

**Step 4: Commit**

```bash
git add src/backend/requirements.txt
git commit -m "feat: add RAG dependencies (sentence-transformers[onnx], onnxruntime, rank-bm25) — no Meta/Chinese deps"
```

---

## Task 4: Build the Embeddings Service

**Files:**
- Create: `src/backend/app/services/embeddings.py`
- Create: `src/backend/tests/test_embeddings.py`

**Context:** Uses `intfloat/multilingual-e5-large-instruct` (MIT, Microsoft Research) — 100+ language coverage required for the tool's jurisdiction set (US, EU, UK, Canada, Brazil, Australia). Runs via ONNX Runtime (MIT, Microsoft) — no PyTorch/Meta in the inference path. Model lazy-loads on first use (~1.2GB). All vectors are L2-normalized; similarity is computed by exhaustive numpy dot-product in the KB layer (exact, no approximation).

**Step 1: Write the failing test first**

Create `src/backend/tests/test_embeddings.py`:

```python
from __future__ import annotations

import numpy as np
import pytest

from app.services.embeddings import embed, MODEL_NAME


def test_embed_returns_2d_array():
    vecs = embed(["This is a test sentence."])
    assert vecs.ndim == 2
    assert vecs.shape[0] == 1
    assert vecs.shape[1] == 1024  # multilingual-e5-large output dim


def test_embed_normalizes_to_unit_length():
    vecs = embed(["Privacy policy sentence about data retention."])
    norms = np.linalg.norm(vecs, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-5)


def test_embed_batch_shape():
    texts = ["First sentence.", "Second sentence.", "Third sentence."]
    vecs = embed(texts)
    assert vecs.shape == (3, 1024)


def test_embed_similar_sentences_close():
    vecs = embed([
        "We sell your personal data to third parties.",
        "We may share personal information with advertisers.",
        "The weather is sunny today.",
    ])
    # First two (both about data sharing) must be closer than either to the weather sentence
    sim_12 = float(np.dot(vecs[0], vecs[1]))
    sim_13 = float(np.dot(vecs[0], vecs[2]))
    assert sim_12 > sim_13


def test_embed_multilingual_legal_text():
    # Must handle non-English text — GDPR source texts are in EU languages
    vecs = embed([
        "Wir verkaufen Ihre personenbezogenen Daten an Dritte.",  # German
        "Nous vendons vos données personnelles à des tiers.",     # French
        "We sell your personal data to third parties.",           # English
    ])
    # All three express the same meaning — all similarities should be high (>0.7)
    sim_de_en = float(np.dot(vecs[0], vecs[2]))
    sim_fr_en = float(np.dot(vecs[1], vecs[2]))
    assert sim_de_en > 0.7, f"German-English similarity too low: {sim_de_en}"
    assert sim_fr_en > 0.7, f"French-English similarity too low: {sim_fr_en}"


def test_model_is_multilingual():
    assert "multilingual" in MODEL_NAME.lower() or "e5" in MODEL_NAME.lower()
```

**Step 2: Run tests to verify they fail (module doesn't exist yet)**

```bash
cd src/backend && python -m pytest tests/test_embeddings.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.embeddings'`

**Step 3: Create the embeddings service**

Create `src/backend/app/services/embeddings.py`:

```python
from __future__ import annotations

import logging
from typing import List

import numpy as np

logger = logging.getLogger("uvicorn.error")

# MIT license — Microsoft Research. 100+ language coverage for world jurisdiction support.
# Runs via onnxruntime (MIT, Microsoft) — no PyTorch/Meta in inference path.
MODEL_NAME = "intfloat/multilingual-e5-large-instruct"

_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        logger.info("Loading embedding model: %s", MODEL_NAME)
        _model = SentenceTransformer(MODEL_NAME, backend="onnx")
        logger.info("Embedding model loaded.")
    return _model


def embed(texts: List[str]) -> np.ndarray:
    """Embed texts. Returns float32 array shape (len(texts), 1024), L2-normalized.

    Uses exhaustive dot-product similarity in LegalKnowledgeBase — exact search,
    no approximation. Required for legal risk analysis.
    """
    model = _get_model()
    return model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=False,
        convert_to_numpy=True,
    ).astype(np.float32)
```

**Step 4: Run the embedding tests**

```bash
cd src/backend && python -m pytest tests/test_embeddings.py -v
```

Note: First run downloads the model (~1.2GB from HuggingFace). Allow 5–10 minutes on first run.

Expected: All 6 tests PASS. The multilingual similarity test (`test_embed_multilingual_legal_text`) is the key verification that world jurisdiction coverage works.

**Step 5: Commit**

```bash
git add src/backend/app/services/embeddings.py src/backend/tests/test_embeddings.py
git commit -m "feat: add embeddings service (multilingual-e5-large-instruct, onnxruntime — no Meta/Chinese deps)"
```

---

## Task 5: Build the Legal Knowledge Base Service

**Files:**
- Create: `src/backend/app/services/legal_kb.py`
- Create: `src/backend/tests/test_legal_kb.py`

**Context:** `LegalKnowledgeBase` stores embedded legal chunks in a numpy matrix and retrieves via exhaustive dot-product (exact cosine similarity on L2-normalized vectors). No FAISS, no HNSW, no approximation. For the expected corpus size (<50K chunks of legal text), numpy exhaustive search completes in <100ms on any modern CPU. When no corpus has been loaded, `retrieve()` returns `[]` — the analyzer falls back gracefully.

**Step 1: Write the failing tests**

Create `src/backend/tests/test_legal_kb.py`:

```python
from __future__ import annotations

import numpy as np
import pytest

from app.services.legal_kb import LegalKnowledgeBase


@pytest.fixture
def kb_with_data():
    kb = LegalKnowledgeBase()
    corpus = [
        {
            "text": "GDPR Article 17: The data subject shall have the right to obtain from the controller the erasure of personal data.",
            "source": "GDPR",
            "article": "Art. 17",
        },
        {
            "text": "CCPA Section 1798.105: A consumer shall have the right to request that a business delete any personal information.",
            "source": "CCPA",
            "article": "1798.105",
        },
        {
            "text": "GDPR Article 6: Processing shall be lawful only if and to the extent that at least one of the following applies.",
            "source": "GDPR",
            "article": "Art. 6",
        },
    ]
    kb.load_chunks(corpus)
    return kb


def test_retrieve_returns_empty_when_no_corpus_loaded():
    kb = LegalKnowledgeBase()
    results = kb.retrieve("right to delete personal data", top_k=3)
    assert results == []


def test_retrieve_returns_list_of_dicts(kb_with_data):
    results = kb_with_data.retrieve("right to delete personal data", top_k=2)
    assert isinstance(results, list)
    assert len(results) <= 2
    for r in results:
        assert "text" in r
        assert "score" in r
        assert "source" in r


def test_retrieve_top_result_relevant(kb_with_data):
    results = kb_with_data.retrieve("erasure of personal data right", top_k=1)
    assert len(results) == 1
    # The GDPR Art. 17 chunk (about erasure) must rank highest — exact search guarantees this
    assert "erasure" in results[0]["text"].lower() or "delete" in results[0]["text"].lower()


def test_retrieve_scores_are_exact_cosine(kb_with_data):
    # Scores must be cosine similarity: range [-1, 1], typically (0, 1] for semantic text
    results = kb_with_data.retrieve("processing lawful basis consent", top_k=3)
    for r in results:
        assert -1.0 <= r["score"] <= 1.0


def test_retrieve_results_ordered_descending(kb_with_data):
    results = kb_with_data.retrieve("right to delete personal data", top_k=3)
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True), "Results must be ordered by similarity descending"


def test_chunk_count_after_load(kb_with_data):
    assert kb_with_data.chunk_count == 3


def test_retrieve_top_k_capped_at_corpus_size(kb_with_data):
    # Corpus has 3 chunks — requesting top_k=10 must return at most 3
    results = kb_with_data.retrieve("data", top_k=10)
    assert len(results) <= 3
```

**Step 2: Run tests to confirm failure**

```bash
cd src/backend && python -m pytest tests/test_legal_kb.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.legal_kb'`

**Step 3: Create the legal KB service**

Create `src/backend/app/services/legal_kb.py`:

```python
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import numpy as np

from .embeddings import embed

logger = logging.getLogger("uvicorn.error")

# Exhaustive numpy dot-product search — exact cosine similarity on L2-normalized vectors.
# No approximation (FAISS/HNSW rejected: Meta origin + approximate results unacceptable
# for legal risk analysis where false negatives mean missed compliance issues).


class LegalKnowledgeBase:
    def __init__(self) -> None:
        self._corpus_matrix: Optional[np.ndarray] = None  # shape (n_chunks, dim)
        self._chunks: List[str] = []
        self._metadata: List[Dict[str, Any]] = []

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    def load_chunks(self, chunks: List[Dict[str, Any]]) -> None:
        """Load pre-chunked legal texts. Each dict must have 'text' key plus any metadata."""
        texts = [c["text"] for c in chunks]
        meta = [{k: v for k, v in c.items() if k != "text"} for c in chunks]
        vecs = embed(texts)  # shape (n, 1024), L2-normalized
        self._corpus_matrix = vecs
        self._chunks = texts
        self._metadata = meta
        logger.info("Legal KB loaded: %d chunks, dim=%d", len(texts), vecs.shape[1])

    def retrieve(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Return top-k most similar legal chunks. Exact exhaustive search — no approximation."""
        if self._corpus_matrix is None or not self._chunks:
            return []
        query_vec = embed([query])  # shape (1, dim), L2-normalized
        # Exhaustive cosine similarity: dot product of L2-normalized vectors
        similarities = np.dot(query_vec, self._corpus_matrix.T).squeeze(0)  # shape (n_chunks,)
        k = min(top_k, len(self._chunks))
        top_indices = np.argsort(similarities)[::-1][:k]
        return [
            {
                "text": self._chunks[idx],
                "score": float(similarities[idx]),
                **self._metadata[idx],
            }
            for idx in top_indices
        ]


_legal_kb = LegalKnowledgeBase()


def get_legal_kb() -> LegalKnowledgeBase:
    return _legal_kb
```

**Step 4: Run the legal KB tests**

```bash
cd src/backend && python -m pytest tests/test_legal_kb.py -v
```

Expected: All 7 tests PASS, including `test_retrieve_results_ordered_descending` which verifies exact ordering.

**Step 5: Run full suite**

```bash
cd src/backend && python -m pytest -v
```

Expected: All tests PASS.

**Step 6: Commit**

```bash
git add src/backend/app/services/legal_kb.py src/backend/tests/test_legal_kb.py
git commit -m "feat: add legal KB service (exact numpy exhaustive search — no FAISS/Meta, no approximation)"
```

---

## Task 6: Wire RAG into the Analysis Pipeline

**Files:**
- Modify: `src/backend/app/services/prompts.py:15-54`
- Modify: `src/backend/app/services/analyzer.py:70-93`
- Modify: `src/backend/tests/test_llm_failure.py`

**Context:** `analyze_text()` currently goes: rule engine → LLM. After this task it goes: rule engine → RAG retrieval → LLM (with legal context injected into the prompt). When the KB is empty (no corpus loaded), `retrieve()` returns `[]` and the prompt gets no augmentation — existing behavior is preserved.

**Step 1: Update prompts.py to accept optional legal context**

Replace the `build_user_prompt` function in `src/backend/app/services/prompts.py`:

```python
def build_user_prompt(
    numbered_text: str,
    jurisdictions: List[Jurisdiction],
    rule_findings: List[dict],
    legal_context: List[dict] | None = None,
) -> str:
    jurisdiction_text = ", ".join(jurisdictions)
    legal_section = ""
    if legal_context:
        passages = "\n".join(
            f"[{r.get('source', 'Law')} {r.get('article', '')}] {r['text']}"
            for r in legal_context
        )
        legal_section = (
            "\nRelevant legal requirements (use these to cite legal_basis):\n"
            f"{passages}\n"
        )
    return (
        "Analyze the document for privacy and terms risks for jurisdictions: "
        f"{jurisdiction_text}.\n\n"
        "Return JSON with this exact schema:\n"
        "{\n"
        '  "summary": "2-4 sentences",\n'
        '  "overall_confidence": 0.0,\n'
        '  "findings": [\n'
        "    {\n"
        '      "category": "string",\n'
        '      "severity": "Low|Medium|High|Critical",\n'
        '      "confidence": 0.0,\n'
        '      "excerpt": "string",\n'
        '      "explanation": "string",\n'
        '      "jurisdictions": ["US-CA","GDPR"],\n'
        '      "evidence": {\n'
        '        "line_start": 1,\n'
        '        "line_end": 1,\n'
        '        "legal_basis": ["string"]\n'
        "      }\n"
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        "- Every finding must cite line numbers from the document.\n"
        "- Every finding must include at least one legal_basis citation.\n"
        "- Only include issues supported by the text.\n"
        "- Keep categories short (e.g., Sale/Share, ADM, Retention, Rights).\n"
        "- If there are no issues, return an empty findings list.\n"
        f"{legal_section}\n"
        "Rule-based detections (for context, may be partial):\n"
        f"{rule_findings}\n\n"
        "Document (with line numbers):\n"
        f"{numbered_text}\n"
    )
```

Also add the import at the top of `prompts.py` (line 1, after `from __future__ import annotations`):

```python
from __future__ import annotations

from typing import List

from ..schemas import Jurisdiction
```

**Step 2: Update analyzer.py to call RAG retrieval**

In `src/backend/app/services/analyzer.py`, add the import after line 13 (after `from .rules import detect_findings`):

```python
from .legal_kb import get_legal_kb
```

Then update the `analyze_text` function. After line 78 (`rule_findings = detect_findings(cleaned, jurisdictions)`), add:

```python
    kb = get_legal_kb()
    query = " ".join(j for j in jurisdictions) + " " + cleaned[:500]
    legal_context = kb.retrieve(query, top_k=5)
```

Then update the `client.analyze()` call at line 89 to pass `legal_context`:

```python
    llm_payload = await client.analyze(
        numbered_text=numbered_text,
        jurisdictions=jurisdictions,
        rule_findings=formatted_rules,
        legal_context=legal_context,
    )
```

**Step 3: Update OllamaClient.analyze() to accept and pass legal_context**

In `src/backend/app/services/llm_client.py`, update the `analyze` method signature and the `build_user_prompt` call:

```python
    async def analyze(
        self,
        numbered_text: str,
        jurisdictions: list[str],
        rule_findings: list[dict],
        legal_context: list[dict] | None = None,
    ) -> Optional[Dict[str, Any]]:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_user_prompt(
                    numbered_text=numbered_text,
                    jurisdictions=jurisdictions,
                    rule_findings=rule_findings,
                    legal_context=legal_context,
                ),
            },
        ]
```

**Step 4: Write a test verifying RAG context passes through**

Add to `src/backend/tests/test_llm_failure.py`:

```python
from app.services.legal_kb import LegalKnowledgeBase, get_legal_kb
from app.services.prompts import build_user_prompt


def test_build_user_prompt_includes_legal_context():
    context = [{"text": "GDPR Art. 17: right to erasure.", "source": "GDPR", "article": "Art. 17"}]
    prompt = build_user_prompt(
        numbered_text="0001| We sell your data.",
        jurisdictions=["GDPR"],
        rule_findings=[],
        legal_context=context,
    )
    assert "GDPR Art. 17" in prompt
    assert "erasure" in prompt


def test_build_user_prompt_no_legal_context_still_works():
    prompt = build_user_prompt(
        numbered_text="0001| We sell your data.",
        jurisdictions=["US-CA"],
        rule_findings=[],
        legal_context=None,
    )
    assert "Analyze the document" in prompt
    assert "Relevant legal requirements" not in prompt
```

**Step 5: Run the full test suite**

```bash
cd src/backend && python -m pytest -v
```

Expected: All tests PASS.

**Step 6: Commit**

```bash
git add src/backend/app/services/prompts.py \
        src/backend/app/services/analyzer.py \
        src/backend/app/services/llm_client.py \
        src/backend/tests/test_llm_failure.py
git commit -m "feat: wire RAG retrieval into analysis pipeline (legal context augments LLM prompt)"
```

---

## Task 7: Implement IRP Scoring

**Files:**
- Modify: `src/backend/app/schemas.py:9,19-27`
- Modify: `src/backend/app/services/analyzer.py:46-67`
- Create: `src/backend/tests/test_irp_scoring.py`

**Context:** The documented IRP formula is `0.5*(Impact/5) + 0.4*(Likelihood/5) - 0.3*(Safeguards/5)`. Currently the code uses a simple severity-weight average on a 0–10 scale with a grade mapping that doesn't match the documentation. This task aligns the implementation with the spec. Impact/Likelihood/Safeguards default from severity level; the LLM can override them per finding.

**Step 1: Write failing tests**

Create `src/backend/tests/test_irp_scoring.py`:

```python
from __future__ import annotations

import pytest

from app.services.analyzer import calculate_irp_score, irp_grade
from app.schemas import Finding, Evidence


def _finding(severity: str, impact: float = None, likelihood: float = None, safeguards: float = None) -> Finding:
    return Finding(
        category="Test",
        severity=severity,
        confidence=0.8,
        excerpt="test excerpt",
        explanation="test",
        jurisdictions=["US-CA"],
        evidence=Evidence(line_start=1, line_end=1, legal_basis=["Test"]),
        impact=impact,
        likelihood=likelihood,
        safeguards=safeguards,
    )


def test_irp_score_formula_high_severity():
    # High severity defaults: impact=4, likelihood=4, safeguards=1
    # IRP = 0.5*(4/5) + 0.4*(4/5) - 0.3*(1/5) = 0.4 + 0.32 - 0.06 = 0.66
    f = _finding("High")
    score = calculate_irp_score([f])
    assert abs(score - 0.66) < 0.01


def test_irp_score_formula_with_safeguards():
    # Explicit safeguards=5 should reduce score
    f = _finding("High", impact=4, likelihood=4, safeguards=5)
    score = calculate_irp_score([f])
    # IRP = 0.5*(4/5) + 0.4*(4/5) - 0.3*(5/5) = 0.4 + 0.32 - 0.3 = 0.42
    assert abs(score - 0.42) < 0.01


def test_irp_score_empty_findings_is_zero():
    assert calculate_irp_score([]) == 0.0


def test_irp_grade_high_risk():
    assert irp_grade(0.80) in ("D", "F")


def test_irp_grade_medium_risk():
    assert irp_grade(0.60) == "C"


def test_irp_grade_low_risk():
    assert irp_grade(0.30) in ("A", "B")


def test_irp_grade_boundary_at_0_75():
    assert irp_grade(0.75) in ("D", "F")
    assert irp_grade(0.74) == "C"
```

**Step 2: Run tests to confirm failure**

```bash
cd src/backend && python -m pytest tests/test_irp_scoring.py -v
```

Expected: FAIL — `calculate_irp_score`, `irp_grade`, and IRP fields on `Finding` don't exist yet.

**Step 3: Add IRP fields to the Finding schema**

In `src/backend/app/schemas.py`, update the `Finding` class (starting at line 19):

```python
class Finding(BaseModel):
    category: str
    severity: Severity
    confidence: float = Field(..., ge=0.0, le=1.0)
    excerpt: str
    explanation: str
    jurisdictions: List[Jurisdiction]
    evidence: Evidence
    # IRP scoring axes (1-5 scale; default from severity if not set by LLM)
    impact: Optional[float] = Field(None, ge=1.0, le=5.0)
    likelihood: Optional[float] = Field(None, ge=1.0, le=5.0)
    safeguards: Optional[float] = Field(None, ge=1.0, le=5.0)
```

**Step 4: Add IRP functions to analyzer.py**

In `src/backend/app/services/analyzer.py`, replace the existing `calculate_risk_score` and `_grade` functions (lines 46-67) with:

```python
_SEVERITY_IRP_DEFAULTS: dict[str, tuple[float, float, float]] = {
    # (impact, likelihood, safeguards)
    "Low":      (2.0, 2.0, 3.0),
    "Medium":   (3.0, 3.0, 2.0),
    "High":     (4.0, 4.0, 1.0),
    "Critical": (5.0, 5.0, 1.0),
}


def _irp_per_finding(finding: Finding) -> float:
    defaults = _SEVERITY_IRP_DEFAULTS.get(finding.severity, (3.0, 3.0, 2.0))
    impact = finding.impact if finding.impact is not None else defaults[0]
    likelihood = finding.likelihood if finding.likelihood is not None else defaults[1]
    safeguards = finding.safeguards if finding.safeguards is not None else defaults[2]
    return 0.5 * (impact / 5) + 0.4 * (likelihood / 5) - 0.3 * (safeguards / 5)


def calculate_irp_score(findings: List[Finding]) -> float:
    if not findings:
        return 0.0
    return round(sum(_irp_per_finding(f) for f in findings) / len(findings), 4)


def irp_grade(score: float) -> str:
    if score >= 0.85:
        return "F"
    if score >= 0.75:
        return "D"
    if score >= 0.65:
        return "D+"
    if score >= 0.55:
        return "C"
    if score >= 0.45:
        return "C+"
    if score >= 0.35:
        return "B"
    if score >= 0.25:
        return "B+"
    return "A"
```

Update the `analyze_text` function to use the new scoring (replace `calculate_risk_score` and `_grade` calls):

```python
    risk_score = calculate_irp_score(merged)
    grade = irp_grade(risk_score)
```

Also update `AnalysisPayload` schema to change `risk_score` field bounds — IRP produces 0.0–0.9, not 0–10:

In `src/backend/app/schemas.py`, update `AnalysisPayload`:
```python
    risk_score: float = Field(..., ge=0.0, le=1.0)
```

And `AnalysisSummary`:
```python
    risk_score: float = Field(..., ge=0.0, le=1.0)
```

**Step 5: Run IRP tests**

```bash
cd src/backend && python -m pytest tests/test_irp_scoring.py -v
```

Expected: All 7 tests PASS.

**Step 6: Run full test suite**

```bash
cd src/backend && python -m pytest -v
```

Expected: All tests PASS. If any test checks `risk_score` against 0–10 range, update its assertion to 0.0–1.0.

**Step 7: Commit**

```bash
git add src/backend/app/schemas.py \
        src/backend/app/services/analyzer.py \
        src/backend/tests/test_irp_scoring.py
git commit -m "feat: implement IRP scoring (Impact/Likelihood/Safeguards formula per spec)"
```

---

## Task 8: Expand Jurisdiction Coverage

**Files:**
- Modify: `src/backend/app/schemas.py:9`
- Modify: `src/backend/app/services/rules.py:20-122`
- Modify: `src/backend/tests/test_rules.py`

**Context:** The `Jurisdiction` type only has `"US-CA"` and `"GDPR"`. The README lists US-CO (Colorado CPA), US-CT (CTDPA), US-NY (SHIELD Act), Canada (PIPEDA), UK. Each needs at least one rule pattern to produce rule-engine signal.

**Step 1: Expand the Jurisdiction type**

In `src/backend/app/schemas.py`, replace line 9:

```python
Jurisdiction = Literal["US-CA", "GDPR", "US-CO", "US-CT", "US-NY", "Canada", "UK"]
```

**Step 2: Write failing tests for new jurisdictions**

Add to `src/backend/tests/test_rules.py`:

```python
def test_colorado_cpa_opt_out_detection():
    text = "Colorado residents may opt out of the sale of personal data."
    findings = detect_findings(text, ["US-CO"])
    assert any(f.category == "Sale/Share" for f in findings)


def test_connecticut_ctdpa_profiling_detection():
    text = "We use automated profiling to make decisions about you."
    findings = detect_findings(text, ["US-CT"])
    assert any(f.category == "ADM" for f in findings)


def test_pipeda_consent_detection():
    text = "We collect personal information with your implied consent."
    findings = detect_findings(text, ["Canada"])
    assert any(f.category == "Dark Patterns" for f in findings)


def test_uk_gdpr_retention_detection():
    text = "We store your personal data indefinitely for business purposes."
    findings = detect_findings(text, ["UK"])
    assert any(f.category == "Retention" for f in findings)


def test_no_findings_when_jurisdiction_not_matched():
    # A US-CA rule should NOT fire when only UK jurisdiction is selected
    text = "We may sell personal information to third parties."
    findings = detect_findings(text, ["UK"])
    # Sale/Share rule is US-CA only — should not fire for UK-only query
    sale_findings = [f for f in findings if f.category == "Sale/Share" and "US-CA" in f.jurisdictions and "UK" not in f.jurisdictions]
    assert len(sale_findings) == 0
```

**Step 3: Run to confirm failures**

```bash
cd src/backend && python -m pytest tests/test_rules.py -v -k "colorado or connecticut or pipeda or uk"
```

Expected: FAIL — new jurisdictions have no rules.

**Step 4: Add new jurisdiction rules to rules.py**

Add these `RulePattern` entries to the `PATTERNS` list in `src/backend/app/services/rules.py` after the existing patterns (after line 121):

```python
    RulePattern(
        category="Sale/Share",
        severity="High",
        jurisdictions=["US-CO", "US-CT"],
        explanation="Colorado CPA and CTDPA require opt-out rights for sale/sharing of personal data.",
        legal_basis=["Colorado CPA § 6-1-1306", "CTDPA § 4(a)(5)"],
        patterns=[
            r"\bsell\b",
            r"\bsale\s+of\s+personal\b",
            r"\bshare\b.*\bpersonal\b",
            r"targeted\s+advertising",
        ],
    ),
    RulePattern(
        category="ADM",
        severity="High",
        jurisdictions=["US-CO", "US-CT"],
        explanation="Colorado CPA and CTDPA require opt-out from profiling for significant decisions.",
        legal_basis=["Colorado CPA § 6-1-1306(1)(c)", "CTDPA § 4(a)(4)"],
        patterns=[
            r"automated\s+decision",
            r"profiling",
            r"algorithmic\s+decision",
        ],
    ),
    RulePattern(
        category="Dark Patterns",
        severity="Medium",
        jurisdictions=["Canada"],
        explanation="PIPEDA requires meaningful, informed consent — implied consent for sensitive data is insufficient.",
        legal_basis=["PIPEDA Principle 3 (Consent)"],
        patterns=[
            r"implied\s+consent",
            r"deemed\s+to\s+(?:have\s+)?consent",
            r"by\s+(?:using|continuing\s+to\s+use)\b",
            r"pre-?checked",
        ],
    ),
    RulePattern(
        category="Retention",
        severity="Medium",
        jurisdictions=["Canada", "UK"],
        explanation="PIPEDA and UK GDPR require retention only as long as necessary for the identified purpose.",
        legal_basis=["PIPEDA Principle 5 (Limiting Use)", "UK GDPR Art. 5(1)(e)"],
        patterns=[
            r"\bstore\s+(?:your|personal)\s+(?:data|information)\b",
            r"\bdata\s+retention\b",
            r"\bindefinitely\b",
            r"\bas\s+long\s+as\s+(?:necessary|required)\b",
        ],
    ),
    RulePattern(
        category="User Rights",
        severity="Medium",
        jurisdictions=["US-CO", "US-CT", "US-NY", "Canada", "UK"],
        explanation="State/provincial laws and UK GDPR grant consumers rights to access, delete, and correct data.",
        legal_basis=[
            "Colorado CPA § 6-1-1306",
            "CTDPA § 4",
            "PIPEDA Principle 9 (Individual Access)",
            "UK GDPR Art. 15-18",
        ],
        patterns=[
            r"\bright\s+to\s+(?:access|deletion|erasure|portability|correction|be\s+forgotten)\b",
            r"\brequest\s+(?:deletion|access\s+to|a\s+copy\s+of)\b",
            r"\bopt[- ]?out\b",
            r"\bdata\s+portability\b",
        ],
    ),
    RulePattern(
        category="Sensitive Data",
        severity="High",
        jurisdictions=["US-CO", "US-CT", "US-NY"],
        explanation="Colorado CPA, CTDPA, and NY SHIELD Act impose heightened obligations on sensitive/biometric data.",
        legal_basis=["Colorado CPA § 6-1-1303(21)", "CTDPA § 1(25)", "NY SHIELD Act"],
        patterns=[
            r"\bbiometric\b",
            r"\bhealth\s+(?:data|information)\b",
            r"\bprecise\s+geolocation\b",
            r"\bfinancial\s+(?:data|account|information)\b",
        ],
    ),
```

**Step 5: Run new jurisdiction tests**

```bash
cd src/backend && python -m pytest tests/test_rules.py -v
```

Expected: All tests PASS including the 5 new ones.

**Step 6: Run full suite**

```bash
cd src/backend && python -m pytest -v
```

Expected: All tests PASS.

**Step 7: Commit**

```bash
git add src/backend/app/schemas.py src/backend/app/services/rules.py src/backend/tests/test_rules.py
git commit -m "feat: expand jurisdiction coverage (US-CO, US-CT, US-NY, Canada, UK)"
```

---

## Completion Checklist

After all 8 tasks, verify:

```bash
cd src/backend && python -m pytest --cov=app --cov-report=term-missing -v
```

Expected final state:
- [ ] No `lm_studio.py` file exists
- [ ] `llm_client.py` with `OllamaClient` class exists
- [ ] Config uses `LLM_BASE_URL` / `LLM_MODEL` env vars, defaults point to `saullm-7b-instruct`
- [ ] Rule patterns for User Rights and Retention are tightened (no bare `r"access"`, `r"delete"`, `r"retain"`)
- [ ] `requirements.txt` has `sentence-transformers[onnx]`, `onnxruntime`, `rank-bm25` — NO `faiss-cpu`, NO `torch`
- [ ] `embeddings.py` uses `intfloat/multilingual-e5-large-instruct` with `backend="onnx"`
- [ ] `legal_kb.py` uses numpy exhaustive dot-product — NO faiss imports anywhere
- [ ] `analyzer.py` calls `get_legal_kb().retrieve()` before the LLM call
- [ ] IRP scoring formula replaces the severity-average formula
- [ ] `Jurisdiction` type includes US-CO, US-CT, US-NY, Canada, UK
- [ ] New jurisdiction rules exist in `PATTERNS`
- [ ] Line coverage >= 85%

**Banned dependency check — run before final commit:**
```bash
cd src/backend && pip show faiss-cpu torch 2>&1 | grep -i "not found" | wc -l
```
Expected: `2` (both must be absent)
