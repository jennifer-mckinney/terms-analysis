# AI Terms & Policies Reviewer

## Identity

| Key | Value |
|-----|-------|
| Purpose | Analyze ToS/Privacy Policies for compliance risks using rule-based + LLM detection |
| Stack | FastAPI (Python) backend, vanilla JS SPA frontend, SQLite, LM Studio (local LLM) |
| Jurisdictions | US-CA (CCPA/CPRA), EU (GDPR) |
| Risk Method | IRP Score = 0.5*(I/5) + 0.4*(L/5) - 0.3*(S/5) |
| Status | Beta — backend on branch `claude/analyze-project-1Q21W`, tests on `claude/improve-test-coverage-DGT1c` |

## Project Map

| Path | Purpose |
|------|---------|
| `src/webapp/` | Static SPA: `index.html`, `app.js` (1284 lines), `style.css` |
| `src/backend/app/` | FastAPI app: `main.py` (15+ endpoints), `services/`, `schemas.py`, `models.py` |
| `src/backend/app/services/` | Core logic: `rules.py`, `analyzer.py`, `validation.py`, `ingest.py`, `lm_studio.py`, `diffing.py`, `prompts.py` |
| `src/backend/tests/` | pytest suite: `test_rules.py`, `test_ingest.py`, `test_llm_failure.py` |
| `src/backend/evaluation/` | Gold dataset + F1/Kappa evaluation scripts |
| `src/demos/` | 6 standalone HTML demos (v1-v7) |
| `docs/` | `DESIGN.md`, `TODO.md`, `LOCAL_DATA.md`, `reports/`, `specs/`, `wireframes/` |

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

Access these via `@.claude/library/<file>` when deeper context is needed.

| Key | File | Use When |
|-----|------|----------|
| **LIB-ARCH** | `@.claude/library/LIB-ARCH.md` | Understanding architecture, data flow, failure modes |
| **LIB-STACK** | `@.claude/library/LIB-STACK.md` | Checking dependencies, versions, config settings |
| **LIB-TEST** | `@.claude/library/LIB-TEST.md` | Planning test implementation, checking coverage gaps |
| **LIB-API** | `@.claude/library/LIB-API.md` | API endpoints, request/response contracts |
| **LIB-RULES** | `@.claude/library/LIB-RULES.md` | Rule engine patterns, 9 risk categories, IRP scoring |
| **LIB-EVAL** | `@.claude/library/LIB-EVAL.md` | Quality rubric, F1/Kappa metrics, grading thresholds |

## Skills

Invoke via `/skill-name` or auto-triggered by matching descriptions.

| Skill | Trigger | Purpose |
|-------|---------|---------|
| `/test-suite` | "run tests", "check coverage" | Run pytest + coverage, analyze failures, report gaps |
| `/write-tests` | "write tests for X", "add coverage" | Guided workflow: read source → plan cases → write tests → verify |
| `/evaluate` | "run evaluation", "check F1" | Run gold dataset evaluation, report F1/Kappa vs targets |
| `/review` | "review this", "check changes" | Code quality review against project conventions |
| `/webapp-testing` | "test the webapp", "browser test" | Playwright-based frontend + API testing |

## Critical Constraints

- **IMPORTANT:** All data stays local. No external API calls except to local LM Studio.
- **IMPORTANT:** LLM failures must always fall back to rule-only findings with reduced confidence.
- Confidence < 0.80 triggers human-in-the-loop review.
- Rule confidence is clamped to [0.35, 0.95].
- Risk scores map to grades: A (0-3), B (3-5), C+ (5-7), C (7-8), D+ (8-9), D (9-10).
