# LIB-ARCH: Architecture Reference

## System Components

| Component | Tech | Location | Role |
|-----------|------|----------|------|
| Web UI | HTML/CSS/JS | `src/webapp/` | Static SPA, communicates via fetch to backend |
| API Server | FastAPI + Uvicorn | `src/backend/app/main.py` | 15+ REST endpoints, async |
| Rule Engine | Python regex | `src/backend/app/services/rules.py` | Baseline signal detection for 9 categories |
| LLM Client | httpx async | `src/backend/app/services/lm_studio.py` | OpenAI-compatible calls to local LM Studio |
| Analyzer | Python async | `src/backend/app/services/analyzer.py` | Orchestrates rules + LLM + validation + scoring |
| Validator | Python | `src/backend/app/services/validation.py` | Hallucination guard, citation checker |
| Ingestion | Python | `src/backend/app/services/ingest.py` | Multi-format text extraction (HTML/PDF/DOCX/RTF/TXT/OCR) |
| Diffing | Python | `src/backend/app/services/diffing.py` | SHA-256 hash + unified diff for watchlist |
| Prompts | Python | `src/backend/app/services/prompts.py` | System/user prompt construction for LLM |
| Database | SQLite + SQLAlchemy | `src/backend/app/database.py` | Local persistence, 3 tables |
| Config | Python dataclass | `src/backend/app/config.py` | Env-var driven settings |

## Data Flow

```
User Input → Ingestion (normalize text)
           → Rule Engine (9-category regex detection)
           → LM Studio (LLM analysis with line-numbered context)
           → Merge (deduplicate rule + LLM findings by category+excerpt)
           → Validation (citation check, hallucination guard, confidence scoring)
           → Scoring (risk_score 0-10, letter grade, review_required flag)
           → SQLite (persist analysis + findings)
           → UI (render results)
```

## Failure Modes

| Failure | Behavior |
|---------|----------|
| LM Studio unreachable | Fall back to rule-only; confidence *= 0.8; may trigger review |
| LM Studio returns invalid JSON | Fall back to rule-only; confidence *= 0.8 |
| LM Studio returns empty findings | Keep rule findings; confidence *= 0.85 |
| LLM findings missing legal_basis | Drop those findings; apply additional penalty |
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
