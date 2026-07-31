format: agent-optimized (2026-07-03)
# terms-analysis — project identity, hard requirements, library index
loads: auto
scope: project
xref: [[LIB-ARCH]] [[LIB-STACK]] [[LIB-LEGAL]] [[LIB-TEST]] [[LIB-API]] [[LIB-RULES]] [[LIB-EVAL]] [[LIB-CONTEXT]] [[LIB-VOICE]] [[LIB-PRINCIPLES]] [[docs/BRD_Terms_Policies_Reviewer.md]] [[docs/PRD_Terms_Policies_Reviewer.md]] [[PRODUCT.md]] [[_AUTOMATION/CLAUDE.md]]

## identity

| Key | Value |
|-----|-------|
| Purpose | Analyze ToS/Privacy Policies for compliance risks via rule + LLM + RAG detection |
| Stack | FastAPI backend, Streamlit UI (v2 primary, v1 legacy rollback), SQLite, LocalAI (Apertus-8B/EuroLLM-22B), numpy exhaustive search (legal-KB — not FAISS) |
| Jurisdictions | 30 codes incl. US-CA (CCPA/CPRA), GDPR, PIPEDA, US-CO, US-CT, US-NY (full list in `schemas.py`) |
| Risk method | IRP composite per finding: `clamp(0.5*(impact/5)+0.4*(likelihood/5)-0.3*(safeguard/5), 0, 1)`; seeded in `rules.py::_seed_irp`; requested from LLM; hybrid merge takes rule impact/likelihood + `safeguard=max(rule,llm)`; recomputed in `_compute_irp`; sort tier-first `(weight, irp_score, severity_rank)` all desc; falls back to severity weight for legacy findings |
| Status | Beta — PR #4, #5, #34, #35 merged |

xref: [[LIB-RULES#IRP]] [[LIB-CONTEXT]]

## hard-requirements

### HR1: open-source-only
rule: all dependencies MUST be open source (Apache 2.0, MIT, BSD preferred)

### HR2: no-investor-lawsuit-vendors
rule: no tools/services from companies facing investor lawsuits (excludes Meta-origin, e.g. FAISS)
because: legal-KB vector index uses numpy exhaustive search instead

### HR3: IRP-grade-A-or-higher
rule: all dependencies MUST score IRP Grade A or higher

### HR4: local-only-data
rule: all data stays local; no external API calls

### HR5: LLM-fallback-to-rules
rule: LLM failures MUST fall back to rule-only findings with reduced confidence

### HR6: no-openai-local-LLM-only
rule: no OpenAI dependency; LLM inference is local-only via LocalAI (EuroLLM-22B for EU/legal, Apertus-8B for multilingual/world)

### HR7: HITL-threshold
rule: confidence < 0.80 triggers human-in-the-loop review

### HR8: rule-confidence-clamp
rule: rule confidence (active path, `_confidence_rules_based`) clamped to [0.90, 0.95]

### HR9: risk-grade-thresholds
rule: risk scores (0-10, higher=worse) map to grades: A (<3.5), A- (3.5-4.5), B (4.5-5.5), B- (5.5-6.5), C+ (6.5-7.5), C (7.5-8.5), D+ (>=8.5)

## project-map

| Path | Purpose |
|------|---------|
| `src/webapp/` | Streamlit UI: `app_streamlit_v2.py` (primary, issue #19) + `app_streamlit_legacy.py` (v1 rollback via `STREAMLIT_UI=v1`) |
| `src/backend/app/` | FastAPI: `main.py` (24 endpoints + `/health`), `services/`, `schemas.py`, `models.py` |
| `src/backend/app/services/` | Core: `rules.py`, `analyzer.py`, `validation.py`, `ingest.py`, `localai.py`, `embedding.py`, `legal_kb.py`, `diffing.py`, `prompts.py` |
| `src/backend/tests/` | pytest suite |
| `data/legal_corpus/` | Legal-KB source text (tracked; placeholder pending real statute ingestion — see `.claude/skills/legal-kb`) |
| `src/backend/evaluation/` | Gold dataset + F1/Kappa scripts |
| `docs/` | `DESIGN.md`, `TODO.md`, `reports/`, `specs/`, `wireframes/` |
| `docs/plans/` | Architecture analysis, agent/skills audit, roadmap |

## commands

| Task | Command |
|------|---------|
| Run backend | `cd src/backend && uvicorn app.main:app --reload` |
| Run frontend | `cd src/webapp && streamlit run app_streamlit_v2.py --server.port 8501` |
| Run both | `./run.sh` |
| Run tests | `cd src/backend && python -m pytest -v` |
| Run tests + coverage | `cd src/backend && python -m pytest --cov=app --cov-report=term-missing -v` |
| Run evaluation | `cd src/backend && python scripts/evaluate.py` |

## git-conventions

### G1: commit-prefixes
rule: use `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `style:`

### G2: active-branch
rule: active development branch is `claude/issue-19-arch-docs-followup`; prior branches merged: `claude/analyze-project-1Q21W`, `claude/improve-test-coverage-DGT1c`, `claude/terms-analysis-setup-fpvabq` (PR #5), `claude/issue-19-plain-language-redesign` (PR #34)

## session-outcomes-2026-07-03

### SO1: PR34-shipped
rule: PR #34 (`claude/issue-19-plain-language-redesign`) landed across 4 commits — `e4fd706` -> `2626e2b` -> `671d3e5` -> `b5ea947`; 873 tests passing, 98.06% coverage

### SO2: IRP-scoring-shipped
rule: `impact`, `likelihood`, `safeguard_score`, `irp_score` fields live on `Finding`; was "planned" in prior LIB-ARCH text
detail: `analyzer.py::_compute_irp` computes composite; `rules.py::_seed_irp` seeds from `_CATEGORY_IRP_DEFAULTS` (38 categories); LLM prompts request the three fields; hybrid merge takes rule impact/likelihood + `safeguard=max(rule,llm)`; sort tier-first `(weight, irp_score, severity_rank)` all desc; context weight leads
xref: [[LIB-RULES#IRP]]

### SO3: context-chip-taxonomy-shipped
rule: 5 chips aligned to BRD segments — `want_understand`, `for_child`, `for_care`, `for_work`, `just_curious`
weights: 1.0 baseline / 2.0 boosted / 2.5 priority / 3.0 signature; multi-select sums, capped at 3.0
xref: [[LIB-CONTEXT]]

### SO4: domain-grouped-results
rule: findings group into 4 fixed domains — `Data` (collection), `Data use`, `Terms of use`, `Privacy rights`; `analyzer._group_by_domain` maps ~50 categories to these 4 buckets
hardware_scope: camera/mic/contacts/location = scope caveat only, NEVER chip or domain group with findings
xref: [[LIB-PRINCIPLES#P4]] [[LIB-VOICE#V11]]

### SO5: global-tool-contract
rule: empty `jurisdictions=[]` = "no filter" mode across rules + LLM post-filter + Streamlit resolution
forbidden: US-CA + GDPR default fallback anywhere
default_ui: location dropdowns blank (`index=None`)

### SO6: schema-derived-allowlists
rule: `_VALID_CHIPS` and `_VALID_JURISDICTIONS` in `main.py` derived at module load via `frozenset(get_args(ContextChip))`; `schemas.CATEGORIES` is canonical frozenset for category strings; `context.py` and `analyzer.py` validate category-keyed dicts against it at import time
because: future drift fails at import, not at CI review
xref: [[.claude/rules/testing.md#R1]]

### SO7: streamlit-v2-feature-flag
rule: v2 shipped behind `STREAMLIT_UI=v2` in `run.sh`; `app_streamlit_legacy.py` retained as rollback
detail: v2 is ~972 lines, teal palette, two-view state, tabbed input (link/text/file), 5 multi-select context option cards, hover-tooltips, 4 domain sections from `top_by_domain`, always-visible scope box, dynamic action items from `AnalysisPayload.action_items`

### SO8: infer-endpoint
rule: new `POST /infer` — accepts URL and/or text; returns TLD-based jurisdiction + doc_type + industry signals
impl: `@lru_cache` on hot paths; pre-compiled regexes; observability logging

### SO10: shell-native-test-scripts
rule: two shell scripts mirror Python test counterparts and kept side-by-side for comparison
files: `scripts/testing/simplification-check.sh` (14 assertions, live app_streamlit_v2.py source, streamlit stubbed headless) + `scripts/testing/smoke-test.sh` (9 live HTTP tests via curl+jq)
verify_scopes: `verify.sh simplification` + `verify.sh smoke-live` (both exec directly, bypass pytest/summarizer)
key_diff: .py counterparts test copied/mocked function; .sh scripts test live source — run both to catch divergence
p9_findings_fixed: F1-F5 security + G1-G5 grumpy (all fixed before push 2026-07-03)
coverage_matrix: `docs/research/test-coverage-matrix.md` — 20 journeys mapped, 2 CRITICAL gaps (rule categories, HITL threshold)
xref: [[.claude/rules/testing.md]] [[LIB-PRINCIPLES#P9]]

### SO9: regressions-file
rule: `test_regressions_pr34.py` — 30 tests covering cross-endpoint consistency via `typing.get_args()` runtime iteration, schema-Literal allowlist parity, XSS defense-in-depth (blocks `javascript:`, `data:`, `vbscript:` schemes), malformed inputs, ReDoS canary on `inference.py`, domain-grouping edges, sort stability
xref: [[.claude/rules/testing.md]]

## session-outcomes-2026-07-04

### SO11: p9-loop-pattern-active
rule: every push runs the parallel security+grumpy review loop. ANY finding of ANY severity triggers a fix-Coder dispatch; iterate to fixed-point (both PASS zero findings) before writing signoff and pushing
codified: `.git/reviews/<sha>.signoff.json` schema in `automations/p9-pre-push.md`; hook validates signoff before allowing push
because: user directive 2026-07-04 extends P9 zero-tolerance-security to zero-tolerance-grumpy
whack-a-mole warning: when name-based deny-lists keep growing across rounds, switch to structural fix (pattern-based rules, schema-driven ordering, input normalization). Two structural-fix wins this session:
  - SO12 F2 (chip order): switched `_ACTION_ITEMS_BY_CHIP.items()` → `typing.get_args(ContextChip)`
  - ingester rounds 6-9: added `_REDACT_SUFFIXES` + `_normalize_key(camelCase→snake_case)` instead of growing exact-name list further
xref: [[LIB-PRINCIPLES#P9]] [[automations/p9-pre-push.md]]

### SO12: revamp-branch-shipped
rule: `revamp/results-report-card` pushed to `origin/revamp/results-report-card` at `ae3dda2`. 4 P9 loop rounds converged
commits: `569260b` (st.form intake), `a4b4c66` (chip-tune action_items), `f1d8ca3` (corpus plans landed), `9bc3dbc` (grumpy F1-F3 fixes: short-circuit + schema-order + real dedupe), `3db1d0e` (grumpy F4: drop stale context arg from call_infer), `f5065cd` (mirror P9 hook), `ae3dda2` (P9_ENFORCEMENT_GUIDE.md updated for hard-gate)
detail: `/infer` handler verified to ignore context arg (main.py:340-349, inference.py:535) — arg dropped from call_infer signature + docstring explains why
xref: [[automations/p9-pre-push.md]] [[SO11]]

### SO13: p9-hard-gate-mirrored
rule: `.githooks/pre-push` is the P9 hard-gate (mirrored from legal-corpus-ingester at commit `3fb017e`). Refuses push unless `.git/reviews/<HEAD_SHA>.signoff.json` exists with security_engineer.verdict=PASS + grumpy_developer.verdict=PASS (or override.used=true with reason + authorized_by)
existing: `.githooks/pre-commit` unchanged (project-specific gitignore-SSoT + graveyard + case-insensitive .env guards)
deleted: `.githooks/pre-push-p9-check` (dormant interactive checklist superseded by the hard gate)
replaced: `scripts/install-hooks.sh` — was stale copy-based, now `core.hooksPath`-based (idempotent glob-chmod + `.git/reviews/` ensure)
docs: `automations/p9-pre-push.md` + `docs/P9_ENFORCEMENT_GUIDE.md` (both updated 2026-07-04)
classifier friction: subagent + Write both blocked when writing signoff files. Workaround: hand user a paste-block containing mkdir + cat heredoc + git push
xref: [[SO11]]

### SO14: sibling-project-legal-corpus-ingester
rule: sibling project `~/Documents/05_Technical_Development/01_AUTOMATION/01_Claude_Projects/legal-corpus-ingester/` bootstrapped 2026-07-04. Phase 0.1 Tasks 1-40 complete and pushed at `459a1b8`.
remote: `jennifer-mckinney/legal-corpus-ingester` (private)
plan: `docs/plans/2026-07-04-legal-corpus-ingester.md` (this repo) — complete; Phase 1 EU plan at `docs/plans/2026-07-04-legal-corpus-ingester-phase1-EU.md`
consumer contract: `src/backend/app/services/legal_kb.py` — consumes corpus bundles from ingester per plan Task 28
xref: [[docs/plans/2026-07-04-legal-corpus-ingester.md]] [[docs/plans/2026-07-04-legal-corpus-ingester-phase1-EU.md]]

## session-outcomes-2026-07-04b

### SO15: ingester-phase-01-complete
rule: legal-corpus-ingester Phase 0.1 Tasks 1-40 all complete and pushed at HEAD `459a1b8`.
phase-00: P1-P10 (bootstrapping, governance, CI skeleton, fetcher, cleaner, chunker, embedder, publisher, pipeline orchestrator, tools/agents/skills)
phase-01: T1-T40 (VCR cassettes, snapshot tests, retention policy, CLI subcommands audit-license/validate-round-trip/prune/refresh, Docker, self-hosted runner, weekly refresh workflow, approval expiry watcher, VCR drift canary, nightly health check)
bugs-fixed: 10 GitHub issues (Groups A-D) — EXIT_NO_SOURCES, SHA-pinned actions, duplicate-issue guards, sha256 validation, ModuleNotFoundError narrowing, retrieve truthiness check, --offline flag, VCR integration test, consumer stub test
next: Phase 1 EU cluster ingestion (GDPR + AI Act + DSA + Data Act + DMA) per `docs/plans/2026-07-04-legal-corpus-ingester-phase1-EU.md`
xref: [[SO14]]

### SO16: ingester-ci-venv-fix
rule: `.github/workflows/ci.yml` test step had no guard for missing `.venv/bin/activate`; caused CI failure on `a8365d5`. Fixed at `9db68f3` — now handled in Phase 0.1 Task 2 pyproject setup.
status: RESOLVED — historical note only

## reference-library

Access via `@.claude/library/<file>` when deeper context is needed.

| Key | File | Use When |
|-----|------|----------|
| **LIB-ARCH** | `@.claude/library/LIB-ARCH.md` | Architecture, data flow, failure modes, RAG pipeline |
| **LIB-STACK** | `@.claude/library/LIB-STACK.md` | Dependencies, versions, config, approved tools |
| **LIB-LEGAL** | `@.claude/library/LIB-LEGAL.md` | Legal LLM/embedding models, RAG architecture, legal corpora |
| **LIB-TEST** | `@.claude/library/LIB-TEST.md` | Test coverage, implementation plan |
| **LIB-API** | `@.claude/library/LIB-API.md` | API endpoints, request/response contracts |
| **LIB-RULES** | `@.claude/library/LIB-RULES.md` | Rule engine (~50 categories/64 patterns), confidence/risk-score, IRP |
| **LIB-EVAL** | `@.claude/library/LIB-EVAL.md` | Rubric, F1/Kappa, grading thresholds |
| **LIB-CONTEXT** | `@.claude/library/LIB-CONTEXT.md` | Context chip taxonomy, weight tiers, sort semantics, verdict copy |
| **LIB-VOICE** | `@.claude/library/LIB-VOICE.md` | Two-voice copy, no-em-dash, scope-honesty gap |
| **LIB-PRINCIPLES** | `@.claude/library/LIB-PRINCIPLES.md` | Governance principles P1-P9 (P8 agent-separation, P9 pre-push review) |

## governance-monitoring

### G1: injection-consistency
script: `~/.claude/scripts/verify-injection.sh`
reads: `~/.claude/session-start.log`
gate: confirms LIB-PRINCIPLES + PEAS + global CLAUDE.md + project CLAUDE.md appeared in most recent session-start injection
exit_codes: 0=ok, 1=drift-missing-file, 2=no-matching-entry, 3=no-log, 4=no-jq
run_from: project root
because: guards against silent hook failure or misconfiguration
xref: [[LIB-PRINCIPLES#P8]] [[$HOME/.claude/CLAUDE.md#session-start-governance-chain]]

### G2: content-consistency
manifest: `.claude/_governance-manifest.json`
tracks: SHA256 of `.claude/CLAUDE.md`, `.claude/library/LIB-PRINCIPLES.md`, `$HOME/.claude/CLAUDE.md`, `$HOME/.claude/library/PEAS.md`
verify: `scripts/governance/verify-hashes.sh` — exit 0 ok, 1 drift, 2 manifest-missing, 3 tracked-file-missing
regen: `scripts/governance/regen-manifest.sh` — requires explicit intent (`y/N` prompt or `--yes` flag)
regen_policy: only after intentional governance-file change reviewed via PR
because: catches silent governance drift between sessions
xref: [[LIB-PRINCIPLES#P8]]

### G3: pre-push-independent-review
rule: enforce LIB-PRINCIPLES P9 — dispatch security-engineer + grumpy-developer before any push. Zero-tolerance for BOTH per 2026-07-04 user directive: ANY finding of ANY severity triggers a fix-Coder + re-review loop until both PASS
automation: `.githooks/pre-push` hard-gate refuses push without `.git/reviews/<sha>.signoff.json` (see [[SO11]] [[SO13]])
gate: ANY finding of ANY severity blocks push until resolved or user-overridden via `override.used=true` with reason + authorized_by
xref: [[LIB-PRINCIPLES#P9]] [[SO11]] [[SO13]] [[automations/p9-pre-push.md]]

## plans-and-analysis

| Document | Path | Purpose |
|----------|------|---------|
| Data Integrity & Architecture | `docs/plans/data-integrity-architecture-analysis.md` | Pipeline integrity audit, current→future state, gaps (P0-P3) |
| Agent & Skills Audit | `docs/plans/agent-skills-surface-area-audit.md` | Skills inventory, PEAS per skill, subagent patterns, gap analysis |

## skills

| Skill | Trigger | Purpose |
|-------|---------|---------|
| `/test-suite` | "run tests", "check coverage" | Run pytest + coverage, analyze failures, report gaps |
| `/write-tests` | "write tests for X", "add coverage" | Guided workflow: read source → plan cases → write tests → verify |
| `/evaluate` | "run evaluation", "check F1" | Run gold dataset evaluation, report F1/Kappa vs targets |
| `/review` | "review this", "check changes" | Code quality review against project conventions |
| `/webapp-testing` | "test the webapp", "browser test" | Playwright-based frontend + API testing |
| `/dependency-audit` | "audit dependency", "check license" | IRP-score a dependency against hard requirements |
| `/legal-kb` | "update legal corpus", "add jurisdiction" | Manage legal knowledge base for RAG |
| `/ralph-loop` | "iterate on X", "loop until done" | Self-referential dev loop until completion promise met |
