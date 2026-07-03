# LIB-ARCH: Architecture Reference

## System Components

| Component | Tech | Location | Role |
|-----------|------|----------|------|
| Web UI (primary) | Streamlit | `src/webapp/app_streamlit.py` | Primary UI (:8501), communicates via `requests` to backend |
| Web UI (fallback) | HTML/CSS/JS | `src/webapp/` | Static SPA (:8000), communicates via fetch to backend |
| API Server | FastAPI + Uvicorn | `src/backend/app/main.py` | 24 REST endpoints + `/health`, async |
| Rule Engine | Python regex | `services/rules.py` | 64 patterns / ~50 categories across 30 jurisdictions |
| LLM Client | httpx async | `services/localai.py` | Chat completions + embeddings to LocalAI (Apertus-8B/EuroLLM-22B, routed by language) |
| Doc-chunk Embeddings | BM25 + LocalAI dense + RRF | `services/embedding.py` | Ensemble chunk-relevance ranking for over-length documents — **not yet wired into `analyzer.py`** (dead code, see Failure Modes) |
| Legal KB | numpy exhaustive + BM25/RRF | `services/legal_kb.py` | RAG retrieval of jurisdiction-specific legal requirements — wired into `analyzer.py`; corpus is currently placeholder text (see `data/legal_corpus/`) |
| Analyzer | Python async | `services/analyzer.py` | Orchestrates rules + legal-KB + LLM + validation + scoring |
| Validator | Python | `services/validation.py` | Hallucination guard, citation checker |
| Ingestion | Python | `services/ingest.py` | Multi-format text extraction (HTML/PDF/DOCX/RTF/TXT/OCR), SSRF-guarded URL fetch |
| Diffing | Python | `services/diffing.py` | SHA-256 hash + unified/token-level diff for watchlist and snapshots |
| Prompts | Python | `services/prompts.py` | System/user prompt construction, including legal-KB context injection |
| Database | SQLite + SQLAlchemy | `app/database.py` | Local persistence, 5 tables |
| Config | Python dataclass | `app/config.py` | Env-var driven settings |

## Data Flow (Current)

```
User Input → Ingestion (normalize text — HTML/PDF/DOCX/RTF/TXT/OCR)
           → Rule Engine (regex detection, 64 patterns / 30 jurisdictions)
           → Legal KB retrieval (numpy exhaustive cosine + BM25/RRF over data/legal_corpus/)
           → LLM (analysis with line-numbered context + legal-KB citations, via LocalAI)
               LLM failure → rule-only findings, confidence *= 0.8
           → Merge (match rule + LLM findings by category+excerpt; hybrid confidence 60% rule / 40% LLM on overlap — see LIB-RULES)
           → Validation (citation check, hallucination guard, confidence scoring)
           → Scoring (risk_score 0-10 severity-weighted average, letter grade, review_required flag)
           → SQLite (persist analysis, result_json blob)
           → UI (render results — Streamlit primary, JS SPA fallback)
```

An Impact/Likelihood/Safeguards ("IRP") scoring formula remains a planned, not-yet-implemented enhancement; current scoring is the severity-weighted average shown above. The RAG pipeline described here (BM25 + dense embed + RRF fusion, legal corpus chunking) is no longer "planned" — it shipped as `services/legal_kb.py` and is wired into `analyze_text()`; see the System Components table above.

## Failure Modes

| Failure | Behavior |
|---------|----------|
| LLM unreachable (LocalAI down) | Fall back to rule-only; confidence *= 0.8; may trigger review |
| LLM returns invalid JSON | Fall back to rule-only; confidence *= 0.8 |
| LLM returns empty findings | Keep rule findings; confidence *= 0.85 |
| LLM findings missing legal_basis | Drop those findings; apply additional penalty |
| Legal-KB index missing/empty or embedding endpoint unreachable | `retrieve()` returns `[]`; LLM runs without legal-KB context augmentation |
| Legal-KB embedding dimension mismatch (stale index) | Logged warning, `retrieve()` returns `[]` — never raises into `analyze_text()` |
| Legal-KB jurisdiction has no matching corpus chunks | Logged warning, falls back to searching the full corpus rather than returning nothing |
| Parsing error / empty text | Return 400 with message |
| Confidence < 0.80 | Create review_item (human-in-the-loop) |

## Database Tables

| Table | Model | Key Columns |
|-------|-------|-------------|
| `analyses` | `Analysis` | id, doc_name, doc_type, source_url, source_type, document_text, status, confidence, risk_score, grade, result_json (full findings payload) |
| `review_items` | `ReviewItem` | id, analysis_id, status (pending/approved/rejected), notes |
| `watchlist_items` | `WatchlistItem` | id, vendor, source_url, status, last_checked, last_document_text, last_document_hash, change_count, risk_delta, change_summary, last_analysis_id |
| `policy_snapshots` | `PolicySnapshot` | id, url, content_hash, captured_at, raw_text |
| `policy_watches` | `PolicyWatch` | id, url, user_id, check_frequency, last_check, enabled |

## Background Processes

- Watchlist refresh: background thread in `main.py` runs every `WATCHLIST_REFRESH_SECONDS` (0 = disabled)
- Re-fetches URLs, computes content diff, updates risk_delta and change_summary
