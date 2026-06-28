# AI Terms & Policies Reviewer

## Identity

| Key | Value |
|-----|-------|
| Purpose | Analyze ToS/Privacy Policies for compliance risks using rule-based + LLM + RAG detection |
| Stack | FastAPI backend, Streamlit SPA, SQLite, EuroLLM-9B + Apertus (local LLMs via LocalAI), BM25 + dense + RRF embeddings |
| Jurisdictions | US-CA (CCPA/CPRA), EU (GDPR), Canada (PIPEDA), US-CO, US-CT, US-NY |
| Risk Method | IRP Score = 0.5*(I/5) + 0.4*(L/5) - 0.3*(S/5) |
| Status | Beta — backend on `claude/analyze-project-1Q21W`, tests on `claude/improve-test-coverage-DGT1c` |

## Hard Requirements

- **IMPORTANT:** All dependencies must be open source (Apache 2.0, MIT, BSD preferred).
- **IMPORTANT:** No tools/services from companies facing investor lawsuits.
- **IMPORTANT:** All dependencies must score IRP Grade A or higher.
- **IMPORTANT:** All data stays local. No external API calls.
- **IMPORTANT:** LLM failures must always fall back to rule-only findings with reduced confidence.
- **IMPORTANT:** No OpenAI dependency. LLM inference is local-only via LocalAI (EuroLLM-9B for EU/legal text, Apertus for multilingual/world coverage).
- Confidence < 0.80 triggers human-in-the-loop review.
- Rule confidence is clamped to [0.35, 0.95].
- Risk scores map to grades: A (0-3), B (3-5), C+ (5-7), C (7-8), D+ (8-9), D (9-10).

## Project Map

| Path | Purpose |
|------|---------|
| `src/webapp/` | Streamlit app: `app_streamlit.py` (canonical frontend, port 8503) |
| `src/backend/app/` | FastAPI app: `main.py` (16 endpoints), `services/`, `schemas.py`, `models.py` |
| `src/backend/app/services/` | Core logic: `rules.py`, `analyzer.py`, `validation.py`, `ingest.py`, `localai.py`, `embedding.py`, `diffing.py`, `prompts.py` |
| `src/backend/tests/` | pytest suite |
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
- Backend branch: `claude/analyze-project-1Q21W`
- Test coverage branch: `claude/improve-test-coverage-DGT1c`

## Reference Library

Access via `@.claude/library/<file>` when deeper context is needed.

| Key | File | Use When |
|-----|------|----------|
| **LIB-ARCH** | `@.claude/library/LIB-ARCH.md` | Architecture, data flow, failure modes, RAG pipeline |
| **LIB-STACK** | `@.claude/library/LIB-STACK.md` | Dependencies, versions, config, approved tools |
| **LIB-LEGAL** | `@.claude/library/LIB-LEGAL.md` | Legal LLM/embedding models, RAG architecture, legal corpora |
| **LIB-TEST** | `@.claude/library/LIB-TEST.md` | Test coverage gaps, implementation plan |
| **LIB-API** | `@.claude/library/LIB-API.md` | API endpoints, request/response contracts |
| **LIB-RULES** | `@.claude/library/LIB-RULES.md` | Rule engine patterns, 9 risk categories, IRP scoring |
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
