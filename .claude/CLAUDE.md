# AI Terms & Policies Reviewer

## Identity

| Key | Value |
|-----|-------|
| Purpose | Analyze ToS/Privacy Policies for compliance risks using rule-based + LLM + RAG detection |
| Stack | FastAPI backend, Streamlit UI (primary) + vanilla JS SPA (fallback), SQLite, LocalAI (Apertus-8B/EuroLLM-22B), numpy exhaustive search (legal-KB embeddings — not FAISS, see Hard Requirements) |
| Jurisdictions | 30 codes including US-CA (CCPA/CPRA), GDPR, PIPEDA, US-CO, US-CT, US-NY (full list in `schemas.py`) |
| Risk Method | IRP (Impact/Likelihood/Safeguards) composite per finding — `0.5*(impact/5)+0.4*(likelihood/5)-0.3*(safeguard/5)` — seeded by rule category in `rules.py::_seed_irp`, requested from LLM in prompts, merged in `_merge_findings` (rule impact/likelihood as baseline, `safeguard_score = max(rule, llm)`), recomputed via `_compute_irp`. Sort is **tier-first**: `(weight, irp_score, severity_rank)` all descending — context chip weight leads, IRP breaks ties within tier. Falls back to severity weight for legacy findings without `irp_score`. See LIB-RULES §IRP Scoring and LIB-CONTEXT. |
| Status | Beta — PR #4 (rubric expansion, API-key auth, PDF-export escaping, CI) and PR #5 (docs reconciliation, legal-KB RAG, XSS/SSRF fixes) merged into `main`; no open PRs/branches |

## Hard Requirements

- **IMPORTANT:** All dependencies must be open source (Apache 2.0, MIT, BSD preferred).
- **IMPORTANT:** No tools/services from companies facing investor lawsuits (this excludes Meta-origin packages, e.g. FAISS — the legal-KB vector index uses numpy exhaustive search instead).
- **IMPORTANT:** All dependencies must score IRP Grade A or higher.
- **IMPORTANT:** All data stays local. No external API calls.
- **IMPORTANT:** LLM failures must always fall back to rule-only findings with reduced confidence.
- **IMPORTANT:** No OpenAI dependency. LLM inference is local-only via LocalAI (EuroLLM-22B for EU/legal text, Apertus-8B for multilingual/world coverage).
- Confidence < 0.80 triggers human-in-the-loop review.
- Rule confidence (active path, `_confidence_rules_based`) is clamped to [0.90, 0.95].
- Risk scores (0-10 scale, higher = worse) map to grades: A (<3.5), A- (3.5-4.5), B (4.5-5.5), B- (5.5-6.5), C+ (6.5-7.5), C (7.5-8.5), D+ (>=8.5).

## Project Map

| Path | Purpose |
|------|---------|
| `src/webapp/` | Streamlit UI (primary, `app_streamlit_v2.py` — issue #19 redesign; `app_streamlit_legacy.py` retained) + static SPA fallback: `index.html`, `app.js`, `style.css` |
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

## Session outcomes (2026-07-03)

Landed via PR #34 (`claude/issue-19-plain-language-redesign`) across 4 commits — `e4fd706` (feature) -> `2626e2b` (must-fix) -> `671d3e5` (P1/P2 + audit) -> `b5ea947` (CI green cleanup). 702 tests passing, 98.06% coverage.

- **IRP scoring shipped** (was "planned enhancement" in prior LIB-ARCH text). `impact`, `likelihood`, `safeguard_score`, `irp_score` fields live on `Finding`. `analyzer.py::_compute_irp` computes the composite; `rules.py::_seed_irp` seeds rule findings from `_CATEGORY_IRP_DEFAULTS` (38 categories mapped); LLM prompts request the same three fields per finding; hybrid merge takes `impact/likelihood` from rules as baseline and `safeguard_score = max(rule, llm)`. Sort is **tier-first**: `(weight, irp_score, severity_rank)` all descending. Context weight leads.
- **Context chip taxonomy shipped** — 5 chips aligned to BRD segments: `want_understand`, `for_child`, `for_care`, `for_work`, `just_curious`. Weight tier scale 1.0 baseline / 2.0 boosted / 2.5 priority / 3.0 signature. Multi-select merger sums weights across chips, capped at 3.0. See LIB-CONTEXT for the full weight table and priority order.
- **Domain-grouped results** — findings group into 4 fixed domains: `Data` (collection), `Data use`, `Terms of use`, `Privacy rights`. `analyzer._group_by_domain` maps ~50 categories to these 4 buckets. Hardware permissions (camera / mic / contacts / location) are a **scope caveat only, never a chip or domain group with findings** — hard scope limit.
- **Global-tool contract** — empty `jurisdictions=[]` is treated as "no filter" mode across rules + LLM post-filter + Streamlit resolution. No US-CA + GDPR default fallback anywhere. Location dropdowns default to blank (`index=None`).
- **Schema-derived allowlists via `typing.get_args()`** — `_VALID_CHIPS` and `_VALID_JURISDICTIONS` in `main.py` are derived at module load: `frozenset(get_args(ContextChip))`. `schemas.CATEGORIES` is the canonical frozenset for finding category strings; `context.py` and `analyzer.py` validate their category-keyed dicts against it at import time. Any future drift fails at import, not at CI review.
- **Streamlit v2 shipped behind `STREAMLIT_UI=v2` feature flag** in `run.sh`. `app_streamlit_legacy.py` retained as rollback path. `app_streamlit_v2.py` is ~972 lines, teal palette, two-view state, tabbed input (link/text/file), 5 multi-select context option cards, hover-triggered contextual help, 4 domain sections rendered from `top_by_domain`, always-visible scope box, dynamic action items from backend `AnalysisPayload.action_items`.
- **New endpoint `POST /infer`** — accepts URL and/or text, returns TLD-based jurisdiction inference + doc_type + industry signals. `@lru_cache` on hot paths; pre-compiled regexes; observability logging.
- **Regression test file `test_regressions_pr34.py`** — 30 tests covering cross-endpoint consistency (via `typing.get_args()` runtime iteration), schema-`Literal` allowlist parity, XSS defense-in-depth (blocks `javascript:`, `data:`, `vbscript:` scheme URLs), malformed inputs, ReDoS canary on `inference.py`, domain-grouping edges, sort stability.

## Reference Library

Access via `@.claude/library/<file>` when deeper context is needed.

| Key | File | Use When |
|-----|------|----------|
| **LIB-ARCH** | `@.claude/library/LIB-ARCH.md` | Architecture, data flow, failure modes, RAG pipeline |
| **LIB-STACK** | `@.claude/library/LIB-STACK.md` | Dependencies, versions, config, approved tools |
| **LIB-LEGAL** | `@.claude/library/LIB-LEGAL.md` | Legal LLM/embedding models, RAG architecture, legal corpora |
| **LIB-TEST** | `@.claude/library/LIB-TEST.md` | Test coverage gaps, implementation plan |
| **LIB-API** | `@.claude/library/LIB-API.md` | API endpoints, request/response contracts |
| **LIB-RULES** | `@.claude/library/LIB-RULES.md` | Rule engine patterns (~50 categories/64 patterns), confidence/risk-score formulas, IRP scoring |
| **LIB-EVAL** | `@.claude/library/LIB-EVAL.md` | Quality rubric, F1/Kappa metrics, grading thresholds |
| **LIB-CONTEXT** | `@.claude/library/LIB-CONTEXT.md` | Context chip taxonomy, weight tiers, sort semantics, verdict copy (issue #19) |
| **LIB-VOICE** | `@.claude/library/LIB-VOICE.md` | Two-voice copy conventions, no-em-dash rule, scope-honesty gap (issue #19) |

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
