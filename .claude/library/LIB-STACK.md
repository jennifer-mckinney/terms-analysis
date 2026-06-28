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
| langdetect | Apache-2.0 | A | Language detection for LLM routing — unmaintained since 2021; graceful fallback exists |
| rank_bm25 | Apache-2.0 | A+ | BM25 sparse retrieval for embedding ensemble |

## Python Dependencies (Planned — RAG Pipeline)

| Package | License | IRP Grade | Purpose |
|---------|---------|-----------|---------|
| sentence-transformers[onnx] | Apache 2.0 | A+ | Embedding model loading (ONNX backend, no PyTorch needed) |
| onnxruntime | MIT | A+ | Model inference runtime (Microsoft; replaces torch/PyTorch) |
| sqlite-vec | MIT | A+ | Exact vector search via SQLite extension (use when corpus > 100K chunks) |

## Test Dependencies

| Package | License | Purpose |
|---------|---------|---------|
| pytest | MIT | Test runner |
| pytest-asyncio | Apache-2.0 | Async test support |
| pytest-cov | MIT | Coverage reporting |
| respx | BSD-3 | httpx mock (for LLM + URL fetch tests) |

## Configuration (env vars)

| Variable | Default | Purpose |
|----------|---------|---------|
| `LLM_BASE_URL` | `http://localhost:8080/v1` | LocalAI endpoint (EuroLLM-9B + Apertus) |
| `LLM_MODEL_EU` | `eurollm-9b-instruct` | EU/legal text model (EuroLLM-9B, Apache 2.0) |
| `LLM_MODEL_WORLD` | `apertus` | World/multilingual model (Apertus, Apache 2.0, 1,811 languages) |
| `EMBEDDING_MODEL` | `intfloat/multilingual-e5-large-instruct` | Primary multilingual embedding model (MIT, 100+ languages) |
| `VECTOR_INDEX_PATH` | `data/legal_kb.npy` | Numpy exhaustive vector index (exact search, no FAISS) |
| `DATABASE_URL` | `sqlite:///data/terms_analysis.db` | SQLite path |
| `REVIEW_THRESHOLD` | `0.80` | Confidence threshold for HITL review |
| `LLM_REQUEST_TIMEOUT_S` | `60` | LLM request timeout |
| `MAX_INPUT_CHARS` | `20000` | Max document text length |
| `ALLOWED_ORIGINS` | `http://localhost:8000,...` | CORS origins |
| `WATCHLIST_REFRESH_SECONDS` | `0` | Background refresh interval (0 = off) |

## Frontend Stack

| Tech | Purpose |
|------|---------|
| Vanilla HTML/CSS/JS | No build step, no bundler |
| Font Awesome | Icons (CSS-only) |
| CSS custom properties | Design tokens, light/dark theming |
| Fetch API | Backend communication |
| localStorage | Theme persistence, optional analytics rollup |

## Rejected Dependencies

| Package/Tool | Reason |
|-------------|--------|
| faiss-cpu | Facebook/Meta origin — see LIB-LEGAL.md |
| torch / PyTorch | Meta origin — use onnxruntime instead |
| LM Studio | Proprietary closed source |
| Stability AI models | Investor lawsuits |
| Ollama GUI/Turbo | Unclear license / proprietary |
| Voyage AI | API-only, proprietary |
| Pile of Law | CC-BY-NC-SA-4.0 (non-commercial) |
