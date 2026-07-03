# LIB-STACK: Tech Stack & Configuration

## Dependency Policy

All dependencies must be: open source (Apache 2.0/MIT/BSD), no investor lawsuits, IRP Grade A+.
See @.claude/library/LIB-LEGAL.md for LLM/embedding/inference tool approvals.

## Python Dependencies (Current)

| Package | License | IRP Grade | Purpose |
|---------|---------|-----------|---------|
| fastapi | MIT | A+ | Web framework |
| uvicorn | BSD-3 | A+ | ASGI server |
| pydantic | MIT | A+ | Data validation, schemas |
| sqlalchemy | MIT | A+ | ORM, database |
| httpx | BSD-3 | A+ | Async HTTP client (LLM, URL fetch) |
| beautifulsoup4 | MIT | A+ | HTML text extraction |
| pypdf | BSD-3 | A+ | PDF text extraction |
| python-docx | MIT | A+ | DOCX text extraction |
| striprtf | BSD-3 | A+ | RTF text extraction |
| reportlab | BSD | A+ | PDF export generation |
| pytesseract | Apache-2.0 | A+ | OCR fallback for scanned PDFs |
| pillow | HPND | A+ | Image processing for OCR |
| langdetect | BSD | A+ | Language routing (Apertus vs. EuroLLM) |
| rank_bm25 | Apache 2.0 | A+ | Sparse retrieval (BM25) for document-chunk and legal-KB ensembles |
| numpy | BSD | A+ | Exact/exhaustive vector similarity (legal-KB retrieval — see Rejected Dependencies for why not FAISS) |

RAG pipeline is implemented (`services/legal_kb.py`, `services/embedding.py`) using the packages above plus the existing LocalAI client for dense embeddings — no sentence-transformers/torch/FAISS were added; see Rejected Dependencies.

## Test Dependencies

| Package | License | Purpose |
|---------|---------|---------|
| pytest | MIT | Test runner |
| pytest-cov | MIT | Coverage reporting |

**Not installed** (despite being conventional choices): `pytest-asyncio`, `respx`. Async tests use plain `asyncio.run(...)` inside a regular (non-`async def`) test function instead of `@pytest.mark.asyncio`; `httpx` mocking uses `httpx.MockTransport` patched into `httpx.AsyncClient.__init__` via `monkeypatch` instead of `respx`. See `.claude/library/LIB-TEST.md` and `test_ingest.py`'s `_patch_transport()` helper for the pattern — adding the `@pytest.mark.asyncio` marker without installing the plugin silently skips the test with a `PytestUnknownMarkWarning` rather than failing loudly.

## Configuration (env vars)

| Variable | Default | Purpose |
|----------|---------|---------|
| `LOCALAI_BASE_URL` | `http://localhost:8080/v1` | LocalAI endpoint |
| `MODEL_WORLD` / `MODEL_EU` | `apertus-8b-instruct` / `eurollm-22b-instruct` | LLM model names (language-routed) |
| `LEGAL_CORPUS_DIR` | `data/legal_corpus` | Legal-KB source corpus directory |
| `LEGAL_KB_INDEX_PATH` | `data/legal_kb.npy` | Legal-KB vector index location (numpy, not FAISS) |
| `LEGAL_KB_METADATA_PATH` | `data/legal_kb_metadata.json` | Legal-KB chunk metadata |
| `DATABASE_URL` | `sqlite:///data/terms_analysis.db` | SQLite path |
| `REVIEW_THRESHOLD` | `0.80` | Confidence threshold for HITL review |
| `LLM_REQUEST_TIMEOUT_S` | `60` | LLM request timeout |
| `MAX_INPUT_CHARS` | `20000` | Max document text length |
| `ALLOWED_ORIGINS` | `http://localhost:8000,...` | CORS origins |
| `WATCHLIST_REFRESH_SECONDS` | `0` | Background refresh interval (0 = off) |

## Frontend Stack

| Tech | Purpose |
|------|---------|
| Streamlit | Primary UI (`app_streamlit.py`, served on :8501 by `run.sh`) |
| Vanilla HTML/CSS/JS | Fallback UI (`index.html`/`app.js`/`style.css`, :8000) — no build step, no bundler |
| Font Awesome | Icons (CSS-only) |
| CSS custom properties | Design tokens, light/dark theming |
| Fetch API | Backend communication |
| localStorage | Theme persistence, optional analytics rollup |

## Rejected Dependencies

| Package/Tool | Reason |
|-------------|--------|
| LM Studio | Proprietary closed source |
| Stability AI models | Investor lawsuits |
| Ollama GUI/Turbo | Unclear license / proprietary |
| Voyage AI | API-only, proprietary |
| Pile of Law | CC-BY-NC-SA-4.0 (non-commercial) |
| FAISS / faiss-cpu | Meta/Facebook origin — ANY Meta-origin dependency is rejected, no exceptions. Legal-KB uses numpy exhaustive search instead (`services/legal_kb.py`). |
| torch / PyTorch | Meta origin — same rejection, no exceptions. |
