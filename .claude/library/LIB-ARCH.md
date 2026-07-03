# LIB-ARCH — architecture reference
loads: on-trigger
scope: project
xref: [[LIB-STACK]] [[LIB-RULES]] [[LIB-LEGAL]] [[LIB-CONTEXT]] [[LIB-API]]

## system-components

| id | component | tech | location | role |
|----|-----------|------|----------|------|
| C1 | Web UI | Streamlit | `src/webapp/app_streamlit_v2.py` | Sole UI (:8501); communicates via `requests`; issue #19 redesign; `app_streamlit_legacy.py` is v1 rollback via `STREAMLIT_UI=v1` |
| C2 | API server | FastAPI + Uvicorn | `src/backend/app/main.py` | 24 REST endpoints + `/health`, async |
| C3 | Rule engine | Python regex | `services/rules.py` | 64 patterns / ~50 categories across 30 jurisdictions |
| C4 | LLM client | httpx async | `services/localai.py` | Chat completions + embeddings to LocalAI (Apertus-8B/EuroLLM-22B, routed by language) |
| C5 | Doc-chunk embeddings | BM25 + LocalAI dense + RRF | `services/embedding.py` | Ensemble chunk-relevance ranking for over-length docs; **not yet wired into `analyzer.py`** — dead code |
| C6 | Legal KB | numpy exhaustive + BM25/RRF | `services/legal_kb.py` | RAG retrieval of jurisdiction-specific legal requirements; wired into `analyzer.py`; corpus currently placeholder |
| C7 | Analyzer | Python async | `services/analyzer.py` | Orchestrates rules + legal-KB + LLM + validation + scoring |
| C8 | Validator | Python | `services/validation.py` | Hallucination guard, citation checker |
| C9 | Ingestion | Python | `services/ingest.py` | Multi-format extraction (HTML/PDF/DOCX/RTF/TXT/OCR), SSRF-guarded URL fetch |
| C10 | Diffing | Python | `services/diffing.py` | SHA-256 hash + unified/token-level diff for watchlist and snapshots |
| C11 | Prompts | Python | `services/prompts.py` | System/user prompt construction incl. legal-KB context injection |
| C12 | Database | SQLite + SQLAlchemy | `app/database.py` | Local persistence, 5 tables |
| C13 | Config | Python dataclass | `app/config.py` | Env-var driven settings |

## data-flow

### ARCH-1: pipeline stages (current)
```
User Input → Ingestion (normalize text — HTML/PDF/DOCX/RTF/TXT/OCR)
           → Rule Engine (regex detection, 64 patterns / 30 jurisdictions)
           → Legal KB retrieval (numpy exhaustive cosine + BM25/RRF over data/legal_corpus/)
           → LLM (analysis with line-numbered context + legal-KB citations, via LocalAI)
               LLM failure → rule-only findings, confidence *= 0.8
           → Merge (match rule + LLM findings by category+excerpt; hybrid confidence 60% rule / 40% LLM on overlap)
           → Validation (citation check, hallucination guard, confidence scoring)
           → Scoring (risk_score 0-10 severity-weighted, letter grade, review_required flag)
           → SQLite (persist analysis, result_json blob)
           → UI (Streamlit v2, sole UI)
```
xref: [[LIB-RULES]]

### ARCH-2: IRP scoring shipped in pipeline
rule: `impact` / `likelihood` / `safeguard_score` / `irp_score` fields live on `Finding`; seeded by rule category via `rules.py::_seed_irp`; requested from LLM in prompt template; merged with `safeguard_score = max(rule, llm)` in `_merge_findings`; `calculate_risk_score()` uses `irp_score` when present; falls back to severity weight for legacy findings without it
sort: tier-first — context weight leads (see LIB-RULES §Sort and LIB-CONTEXT)
shipped_in: PR #34 (2026-07-03)
xref: [[LIB-RULES#IRP]] [[LIB-CONTEXT]]

### ARCH-3: RAG pipeline live
rule: BM25 + dense embed + RRF fusion + legal corpus chunking is live in `services/legal_kb.py`, wired into `analyze_text()`
xref: [[LIB-LEGAL]]

## failure-modes

| id | failure | behavior |
|----|---------|----------|
| F1 | LLM unreachable (LocalAI down) | Fall back to rule-only; confidence *= 0.8; may trigger review |
| F2 | LLM returns invalid JSON | Fall back to rule-only; confidence *= 0.8 |
| F3 | LLM returns empty findings | Keep rule findings; confidence *= 0.85 |
| F4 | LLM findings missing legal_basis | Drop those findings; apply additional penalty |
| F5 | Legal-KB index missing/empty or embed endpoint unreachable | `retrieve()` returns `[]`; LLM runs without legal-KB context |
| F6 | Legal-KB embedding dimension mismatch (stale index) | Logged warning, `retrieve()` returns `[]`; never raises into `analyze_text()` |
| F7 | Legal-KB jurisdiction has no matching corpus chunks | Logged warning, falls back to searching full corpus rather than returning nothing |
| F8 | Parsing error / empty text | Return 400 with message |
| F9 | Confidence < 0.80 | Create review_item (human-in-the-loop) |

## database-tables

| table | model | key columns |
|-------|-------|-------------|
| `analyses` | `Analysis` | id, doc_name, doc_type, source_url, source_type, document_text, status, confidence, risk_score, grade, result_json |
| `review_items` | `ReviewItem` | id, analysis_id, status (pending/approved/rejected), notes |
| `watchlist_items` | `WatchlistItem` | id, vendor, source_url, status, last_checked, last_document_text, last_document_hash, change_count, risk_delta, change_summary, last_analysis_id |
| `policy_snapshots` | `PolicySnapshot` | id, url, content_hash, captured_at, raw_text |
| `policy_watches` | `PolicyWatch` | id, url, user_id, check_frequency, last_check, enabled |

## background-processes

### ARCH-4: watchlist refresh
rule: background thread in `main.py` runs every `WATCHLIST_REFRESH_SECONDS` (0 = disabled); re-fetches URLs, computes content diff, updates `risk_delta` + `change_summary`
