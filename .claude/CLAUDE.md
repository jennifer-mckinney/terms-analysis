# AI Terms & Policies Reviewer

## Identity

| Key | Value |
|-----|-------|
| Purpose | Analyze ToS/Privacy Policies for compliance risks using rule-based + LLM + RAG detection |
| Stack | FastAPI backend, Streamlit UI (primary) + vanilla JS SPA (fallback), SQLite, LocalAI (Apertus-8B/EuroLLM-22B), numpy exhaustive search (legal-KB embeddings — not FAISS, see Hard Requirements) |
| Jurisdictions | 30 codes including US-CA (CCPA/CPRA), GDPR, PIPEDA, US-CO, US-CT, US-NY (full list in `schemas.py`) |
| Risk Method | Severity-weighted average (see `analyzer.py::calculate_risk_score`); an Impact/Likelihood/Safeguards "IRP" formula is a planned, not-yet-implemented enhancement |
| Status | Beta — active development on `claude/terms-analysis-setup-fpvabq` (open PR #5); prior branches `claude/analyze-project-1Q21W` and `claude/improve-test-coverage-DGT1c` are merged into it |

## Hard Requirements

- **IMPORTANT:** All dependencies must be open source (Apache 2.0, MIT, BSD preferred).
- **IMPORTANT:** No tools/services from companies facing investor lawsuits (this excludes Meta-origin packages, e.g. FAISS — the legal-KB vector index uses numpy exhaustive search instead).
- **IMPORTANT:** All dependencies must score IRP Grade A or higher.
- **IMPORTANT:** All data stays local. No external API calls.
- **IMPORTANT:** LLM failures must always fall back to rule-only findings with reduced confidence.
- **IMPORTANT:** No OpenAI dependency. LLM inference is local-only via LocalAI (Apertus-8B/EuroLLM-22B).
- Confidence < 0.80 triggers human-in-the-loop review.
- Rule confidence (active path, `_confidence_rules_based`) is clamped to [0.90, 0.95].
- Risk scores (0-10 scale, higher = worse) map to grades: A (<3.5), A- (3.5-4.5), B (4.5-5.5), B- (5.5-6.5), C+ (6.5-7.5), C (7.5-8.5), D+ (>=8.5).

## Project Map

| Path | Purpose |
|------|---------|
| `src/webapp/` | Streamlit UI (primary, `app_streamlit.py`) + static SPA fallback: `index.html`, `app.js`, `style.css` |
| `src/backend/app/` | FastAPI app: `main.py` (24 endpoints + `/health`), `services/`, `schemas.py`, `models.py` |
| `src/backend/app/services/` | Core logic: `rules.py`, `analyzer.py`, `validation.py`, `ingest.py`, `localai.py`, `embedding.py`, `legal_kb.py`, `diffing.py`, `prompts.py` |
| `src/backend/tests/` | pytest suite |
| `data/legal_corpus/` | Legal-KB source text (tracked; currently placeholder pending real statute ingestion, see `.claude/skills/legal-kb`) |
| `src/backend/evaluation/` | Gold dataset + F1/Kappa evaluation scripts |
| `docs/` | `DESIGN.md`, `TODO.md`, `reports/`, `specs/`, `wireframes/` |
| `docs/plans/` | Architecture analysis, agent/skills audit, roadmap documents |

## Commands

| Task | Command |
|------|---------|
| Run backend | `cd src/backend && uvicorn app.main:app --reload` |
| Run frontend | `cd src/webapp && python3 -m http.server 8000` |
| Run both | `./run.sh` |
| Run tests | `cd src/backend && python -m pytest -v` |
| Run tests + coverage | `cd src/backend && python -m pytest --cov=app --cov-report=term-missing -v` |
| Run evaluation | `cd src/backend && python scripts/evaluate.py` |

## Git Conventions

- Prefixes: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `style:`
- Active development branch: `claude/terms-analysis-setup-fpvabq` (open PR #5)
- Prior branches `claude/analyze-project-1Q21W` and `claude/improve-test-coverage-DGT1c` are already merged into the active branch — not separate lines of work

## Reference Library

Access via `@.claude/library/<file>` when deeper context is needed.

| Key | File | Use When |
|-----|------|----------|
| **LIB-ARCH** | `@.claude/library/LIB-ARCH.md` | Architecture, data flow, failure modes, RAG pipeline |
| **LIB-STACK** | `@.claude/library/LIB-STACK.md` | Dependencies, versions, config, approved tools |
| **LIB-LEGAL** | `@.claude/library/LIB-LEGAL.md` | Legal LLM/embedding models, RAG architecture, legal corpora |
| **LIB-TEST** | `@.claude/library/LIB-TEST.md` | Test coverage gaps, implementation plan |
| **LIB-API** | `@.claude/library/LIB-API.md` | API endpoints, request/response contracts |
| **LIB-RULES** | `@.claude/library/LIB-RULES.md` | Rule engine patterns (~50 categories/64 patterns), confidence/risk-score formulas |
| **LIB-EVAL** | `@.claude/library/LIB-EVAL.md` | Quality rubric, F1/Kappa metrics, grading thresholds |

## Plans & Analysis Documents

| Document | Path | Purpose |
|----------|------|---------|
| **Data Integrity & Architecture** | `docs/plans/data-integrity-architecture-analysis.md` | Pipeline integrity audit, current→future state, codebase gaps (P0-P3) |
| **Agent & Skills Audit** | `docs/plans/agent-skills-surface-area-audit.md` | Skills inventory, PEAS per skill, subagent patterns, gap analysis |

## Skills

| Skill | Trigger | Purpose |
|-------|---------|---------|
| `/test-suite` | "run tests", "check coverage" | Run pytest + coverage, analyze failures, report gaps |
| `/write-tests` | "write tests for X", "add coverage" | Guided workflow: read source → plan cases → write tests → verify |
| `/evaluate` | "run evaluation", "check F1" | Run gold dataset evaluation, report F1/Kappa vs targets |
| `/review` | "review this", "check changes" | Code quality review against project conventions |
| `/webapp-testing` | "test the webapp", "browser test" | Playwright-based frontend + API testing |
| `/dependency-audit` | "audit dependency", "check license" | IRP-score a dependency against hard requirements |
| `/legal-kb` | "update legal corpus", "add jurisdiction" | Manage legal knowledge base for RAG pipeline |
| `/ralph-loop` | "iterate on X", "loop until done" | Self-referential dev loop: same prompt repeated until completion promise met |
