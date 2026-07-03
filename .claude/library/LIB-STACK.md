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
| python-dotenv | BSD-3 | A+ | .env config loading |
| python-multipart | Apache-2.0 | A | File upload parsing — **pin >= 0.0.18** (CVE-2024-24762, CVE-2024-53981 patched) |
| langdetect | BSD | A+ | Language routing (Apertus vs. EuroLLM) — unmaintained since 2021; graceful fallback exists |
| rank_bm25 | Apache 2.0 | A+ | Sparse retrieval (BM25) for document-chunk and legal-KB ensembles |
| numpy | BSD | A+ | Exact/exhaustive vector similarity (legal-KB retrieval — see Rejected Dependencies for why not FAISS) |

RAG pipeline is implemented (`services/legal_kb.py`, `services/embedding.py`) using the packages above plus the existing LocalAI client for dense embeddings — no sentence-transformers/torch/FAISS/onnxruntime/sqlite-vec were added; those were an evaluated candidate stack, not what shipped (see `@.claude/library/LIB-LEGAL.md` for that history).

## Test Dependencies

| Package | License | Purpose |
|---------|---------|---------|
| pytest | MIT | Test runner |
| pytest-cov | MIT | Coverage reporting |

**Not installed** (despite being conventional choices): `pytest-asyncio`, `respx`. Async tests use plain `asyncio.run(...)` inside a regular (non-`async def`) test function instead of `@pytest.mark.asyncio`; `httpx` mocking uses `httpx.MockTransport` patched into `httpx.AsyncClient.__init__` via `monkeypatch` instead of `respx`. See `.claude/library/LIB-TEST.md` and `test_ingest.py`'s `_patch_transport()` helper for the pattern — adding the `@pytest.mark.asyncio` marker without installing the plugin silently skips the test with a `PytestUnknownMarkWarning` rather than failing loudly.

## Configuration (env vars)

| Variable | Default | Purpose |
|----------|---------|---------|
| `LOCALAI_BASE_URL` | `http://localhost:8080/v1` | LocalAI endpoint (zero VC, Apache 2.0) |
| `MODEL_EU` | `eurollm-22b-instruct` | EU language model — EuroLLM 22B Instruct (EU Horizon/EuroHPC, Apache 2.0) |
| `MODEL_WORLD` | `apertus-8b-instruct` | World/multilingual model — Apertus 8B Instruct (Swiss AI Initiative, Apache 2.0) |
| `EU_LANGUAGE_CODES` | `bg,cs,da,de,el,en,…` | ISO 639-1 codes that route to EuroLLM; all others → Apertus |
| `LANGUAGE_DETECTION_ENABLED` | `true` | Enable language-based model routing |
| `RRF_K` | `60` | Reciprocal Rank Fusion constant for embedding ensemble |
| `LEGAL_CORPUS_DIR` | `data/legal_corpus` | Legal-KB source corpus directory |
| `LEGAL_KB_INDEX_PATH` | `data/legal_kb.npy` | Legal-KB vector index location (numpy, not FAISS) |
| `LEGAL_KB_METADATA_PATH` | `data/legal_kb_metadata.json` | Legal-KB chunk metadata |
| `DATABASE_URL` | `sqlite:///data/terms_analysis.db` | SQLite path |
| `REVIEW_THRESHOLD` | `0.80` | Confidence threshold for HITL review |
| `LM_REQUEST_TIMEOUT_S` | `60` | LocalAI request timeout (seconds) |
| `MAX_INPUT_CHARS` | `20000` | Max document text length before truncation |
| `MAX_UPLOAD_BYTES` | `10485760` | Max HTTP response / upload size (10 MB) |
| `MAX_PDF_PAGES` | `100` | Max pages processed per PDF (OCR path) |
| `ALLOWED_ORIGINS` | `http://localhost:8000,...` | CORS allowed origins |
| `WATCHLIST_REFRESH_SECONDS` | `0` | Background refresh interval (0 = off) |
| `API_KEY` | *(empty)* | Endpoint auth key — empty disables auth (local dev) |
| `TERMS_ANALYSIS_DATA_DIR` | `<repo>/data` | Override data directory for SQLite + exports |

## Frontend Stack

| Tech | Purpose |
|------|---------|
| Streamlit | Primary UI (`app_streamlit_v2.py`, served on :8501 by `run.sh`; `app_streamlit_legacy.py` retained for reference) |
| Vanilla HTML/CSS/JS | Fallback UI (`index.html`/`app.js`/`style.css`, :8000) — no build step, no bundler |
| Font Awesome | Icons (CSS-only) |
| CSS custom properties | Design tokens, light/dark theming |
| Fetch API | Backend communication |
| localStorage | Theme persistence, optional analytics rollup |

## Rejected Dependencies

| Package/Tool | Reason |
|-------------|--------|
| FAISS / faiss-cpu | Meta/Facebook origin — ANY Meta-origin dependency is rejected, no exceptions. Legal-KB uses numpy exhaustive search instead (`services/legal_kb.py`). See LIB-LEGAL.md. |
| torch / PyTorch | Meta origin — same rejection, no exceptions. |
| LM Studio | Proprietary closed source |
| Stability AI models | Investor lawsuits |
| Ollama GUI/Turbo | Unclear license / proprietary |
| Voyage AI | API-only, proprietary |
| Pile of Law | CC-BY-NC-SA-4.0 (non-commercial) |
