# LIB-STACK — tech stack, dependencies, config
loads: on-trigger
scope: project
xref: [[.claude/CLAUDE.md#hard-requirements]] [[LIB-LEGAL]] [[LIB-TEST]]

## dependency-policy

### S1: policy
rule: all deps MUST be open source (Apache 2.0/MIT/BSD), no investor lawsuits, IRP Grade A+
xref: [[LIB-LEGAL]] [[.claude/CLAUDE.md#HR1]]

## python-deps

| Package | License | IRP | Purpose |
|---------|---------|-----|---------|
| fastapi | MIT | A+ | Web framework |
| uvicorn | BSD-3 | A+ | ASGI server |
| pydantic | MIT | A+ | Data validation, schemas |
| sqlalchemy | MIT | A+ | ORM, database |
| httpx | BSD-3 | A+ | Async HTTP (LLM, URL fetch) |
| beautifulsoup4 | MIT | A+ | HTML text extraction |
| pypdf | BSD-3 | A+ | PDF text extraction |
| python-docx | MIT | A+ | DOCX text extraction |
| striprtf | BSD-3 | A+ | RTF text extraction |
| reportlab | BSD | A+ | PDF export generation |
| pytesseract | Apache-2.0 | A+ | OCR fallback for scanned PDFs |
| pillow | HPND | A+ | Image processing for OCR |
| python-dotenv | BSD-3 | A+ | .env config loading |
| python-multipart | Apache-2.0 | A | File upload parsing |
| langdetect | BSD | A+ | Language routing (Apertus vs. EuroLLM); unmaintained since 2021; graceful fallback exists |
| rank_bm25 | Apache 2.0 | A+ | Sparse retrieval (BM25) for doc-chunk + legal-KB ensembles |
| numpy | BSD | A+ | Exact/exhaustive vector similarity (legal-KB — see rejected below) |

### S2: python-multipart-pin
rule: pin `python-multipart >= 0.0.18`
because: CVE-2024-24762, CVE-2024-53981 patched at that version

### S3: RAG-uses-existing-LLM-client
rule: RAG pipeline (`services/legal_kb.py`, `services/embedding.py`) uses packages above + existing LocalAI client for dense embeddings
forbidden: sentence-transformers, torch, FAISS, onnxruntime, sqlite-vec
because: those were evaluated candidates, not shipped stack (see LIB-LEGAL)

## test-deps

| Package | License | Purpose |
|---------|---------|---------|
| pytest | MIT | Test runner |
| pytest-cov | MIT | Coverage reporting |

### S4: not-installed
rule: `pytest-asyncio` and `respx` are NOT installed
alternative_async: call from regular (non-`async def`) test via `asyncio.run(...)`
alternative_httpx: patch `httpx.AsyncClient.__init__` with `monkeypatch` to inject `httpx.MockTransport`
because: adding `@pytest.mark.asyncio` without the plugin silently skips as `PytestUnknownMarkWarning`
xref: [[LIB-TEST]] [[.claude/rules/testing.md#T1]] [[.claude/rules/testing.md#T6]]

## env-vars

| Variable | Default | Purpose |
|----------|---------|---------|
| `LOCALAI_BASE_URL` | `http://localhost:8080/v1` | LocalAI endpoint (Apache 2.0) |
| `MODEL_EU` | `eurollm-22b-instruct` | EuroLLM 22B Instruct (EU Horizon/EuroHPC, Apache 2.0) |
| `MODEL_WORLD` | `apertus-8b-instruct` | Apertus 8B Instruct (Swiss AI Initiative, Apache 2.0) |
| `EU_LANGUAGE_CODES` | `bg,cs,da,de,el,en,…` | ISO 639-1 codes routed to EuroLLM; all others → Apertus |
| `LANGUAGE_DETECTION_ENABLED` | `true` | Enable language-based model routing |
| `RRF_K` | `60` | Reciprocal Rank Fusion constant |
| `LEGAL_CORPUS_DIR` | `data/legal_corpus` | Legal-KB source corpus directory |
| `LEGAL_KB_INDEX_PATH` | `data/legal_kb.npy` | Legal-KB vector index (numpy, not FAISS) |
| `LEGAL_KB_METADATA_PATH` | `data/legal_kb_metadata.json` | Legal-KB chunk metadata |
| `DATABASE_URL` | `sqlite:///data/terms_analysis.db` | SQLite path |
| `REVIEW_THRESHOLD` | `0.80` | HITL confidence threshold |
| `LM_REQUEST_TIMEOUT_S` | `60` | LocalAI request timeout (seconds) |
| `MAX_INPUT_CHARS` | `20000` | Max document text length before truncation |
| `MAX_UPLOAD_BYTES` | `10485760` | Max HTTP response / upload size (10 MB) |
| `MAX_PDF_PAGES` | `100` | Max pages processed per PDF (OCR path) |
| `ALLOWED_ORIGINS` | `http://localhost:8501,...` | CORS allowed origins |
| `WATCHLIST_REFRESH_SECONDS` | `0` | Background refresh interval (0 = off) |
| `API_KEY` | *(empty)* | Endpoint auth key; empty disables auth (local dev) |
| `TERMS_ANALYSIS_DATA_DIR` | `<repo>/data` | Override data dir for SQLite + exports |

## frontend-stack

| Tech | Purpose |
|------|---------|
| Streamlit | Sole UI (`app_streamlit_v2.py` on :8501 via `run.sh`; `app_streamlit_legacy.py` v1 rollback via `STREAMLIT_UI=v1`) |
| Streamlit theming | `.streamlit/config.toml` — primary color, background, font, cache controls |

## rejected-deps

### S5: no-meta-origin
rule: reject FAISS/faiss-cpu, torch/PyTorch (Meta origin) — no exceptions
alternative: legal-KB uses numpy exhaustive search (`services/legal_kb.py`)
xref: [[LIB-LEGAL]]

### S6: no-proprietary-inference-runners
rule: reject LM Studio (proprietary closed source), Ollama GUI/Turbo (unclear license/proprietary)

### S7: no-lawsuit-model-orgs
rule: reject Stability AI models (investor lawsuits)

### S8: no-proprietary-api-embeddings
rule: reject Voyage AI (API-only, proprietary)

### S9: no-non-commercial-corpora
rule: reject Pile of Law (CC-BY-NC-SA-4.0, non-commercial)
