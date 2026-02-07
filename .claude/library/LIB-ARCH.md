# LIB-ARCH: Architecture Reference

## System Components

| Component | Tech | Location | Role |
|-----------|------|----------|------|
| Web UI | HTML/CSS/JS | `src/webapp/` | Static SPA, communicates via fetch to backend |
| API Server | FastAPI + Uvicorn | `src/backend/app/main.py` | 16 REST endpoints, async |
| Rule Engine | Python regex | `services/rules.py` | Baseline signal detection for 9 categories |
| LLM Client | httpx async | `services/lm_studio.py` | Chat completions to Ollama + SaulLM-7B (local legal LLM) |
| Embeddings | sentence-transformers | `services/embeddings.py` (planned) | Legal text embeddings via modernbert-legal |
| Legal KB | FAISS + chunked corpus | `services/legal_kb.py` (planned) | RAG retrieval of jurisdiction-specific legal requirements |
| Analyzer | Python async | `services/analyzer.py` | Orchestrates rules + RAG + LLM + validation + scoring |
| Validator | Python | `services/validation.py` | Hallucination guard, citation checker |
| Ingestion | Python | `services/ingest.py` | Multi-format text extraction (HTML/PDF/DOCX/RTF/TXT/OCR) |
| Diffing | Python | `services/diffing.py` | SHA-256 hash + unified diff for watchlist |
| Prompts | Python | `services/prompts.py` | System/user prompt construction for LLM |
| Database | SQLite + SQLAlchemy | `app/database.py` | Local persistence, 3 tables |
| Config | Python dataclass | `app/config.py` | Env-var driven settings |

## Data Flow (Current)

```
User Input → Ingestion (normalize text)
           → Rule Engine (9-category regex detection)
           → LLM (analysis with line-numbered context via Ollama)
           → Merge (deduplicate rule + LLM findings by category+excerpt)
           → Validation (citation check, hallucination guard, confidence scoring)
           → Scoring (risk_score 0-10, letter grade, review_required flag)
           → SQLite (persist analysis + findings)
           → UI (render results)
```

## Data Flow (Planned — RAG Pipeline)

```
Legal Corpus (GDPR, CCPA/CPRA, PIPEDA, state laws)
    → Chunk by article/section
        → Embed (modernbert-legal-8192)
            → FAISS vector index (local)

User Input → Ingestion (normalize text)
           → Rule Engine (9-category regex detection)
           → Embed policy text (same model)
               → Retrieve top-k matching legal requirements from FAISS
                   → Augment LLM prompt with retrieved legal context
                       → SaulLM-7B-Instruct (via Ollama) — legal reasoning
           → Merge (deduplicate rule + LLM findings)
           → Validation (citation check, hallucination guard)
           → Scoring (risk_score 0-10, grade, review_required)
           → SQLite (persist)
           → UI (render)
```

## Failure Modes

| Failure | Behavior |
|---------|----------|
| LLM unreachable (Ollama down) | Fall back to rule-only; confidence *= 0.8; may trigger review |
| LLM returns invalid JSON | Fall back to rule-only; confidence *= 0.8 |
| LLM returns empty findings | Keep rule findings; confidence *= 0.85 |
| LLM findings missing legal_basis | Drop those findings; apply additional penalty |
| FAISS index missing/empty | Skip RAG retrieval; LLM runs without legal context augmentation |
| Embedding model load failure | Skip RAG retrieval; fall back to rule + LLM without RAG |
| Parsing error / empty text | Return 400 with message |
| Confidence < 0.80 | Create review_item (human-in-the-loop) |

## Database Tables

| Table | Key Columns |
|-------|-------------|
| `analyses` | id, name, doc_type, source_url, document_text, line_offsets, status, confidence, risk_score, grade, findings_json, summary |
| `review_items` | id, analysis_id, status (pending/approved/rejected), notes |
| `watchlist_items` | id, vendor, source_url, status, last_checked, last_text, last_hash, change_count, risk_delta, change_summary |

## Background Processes

- Watchlist refresh: background thread in `main.py` runs every `WATCHLIST_REFRESH_SECONDS` (0 = disabled)
- Re-fetches URLs, computes content diff, updates risk_delta and change_summary
