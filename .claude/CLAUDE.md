format: agent-optimized (refreshed 2026-10-09; replaces the 2026-07-03 version)
# terms-analysis: project identity, hard requirements, index
loads: auto
scope: project
xref: [[LIB-ARCH]] [[LIB-STACK]] [[LIB-LEGAL]] [[LIB-TEST]] [[LIB-API]] [[LIB-RULES]] [[LIB-EVAL]] [[LIB-CONTEXT]] [[LIB-VOICE]] [[LIB-PRINCIPLES]] [[docs/BRD_Terms_Policies_Reviewer.md]] [[docs/PRD_Terms_Policies_Reviewer.md]] [[PRODUCT.md]]

## resume-here
- Current state and next actions: the newest `SESSION_HANDOFF_*.md` in the repo root. Read it first.
- Execution pipeline and owner limits: `~/.claude/library/EXECUTION-PLAYBOOK.md`.
- Settled plan (D1-D10, R1-R7, gate order G0 → GM → G1 → G1b → G2 → G2b → G3 → G4): `~/.claude/plans/as-my-principal-engineer-tidy-tulip.md`. Don't re-litigate it.
- Live log for the day: `docs/evidence/<date>-status.md` (untracked).
- Human-readable system overview: `docs/research/2026-10-09-system-playbook.md`.
- Claude Code optimisation plan (context diet, model routing, W1-W7): `~/.claude/plans/study-the-anthropic-developer-synchronous-beaver.md`.
- Process rules G1-G12, P9 CI review and M1-M3 monitoring: `.claude/library/LIB-PRINCIPLES.md#project-process`.
- Never work on or push to main; merge commits only, no rebase, no force-push, no --no-verify; merging is owner-only (G2, G3, G8, G9). Read the project-process section before any git or review work.

## identity
| Key | Value |
|-----|-------|
| Purpose | Analyse ToS and privacy policies for compliance risk, using rule + LLM + RAG detection |
| Stack | FastAPI backend; Streamlit UI (v2 primary, v1 legacy rollback; Vue 3 planned under D2/G4); SQLite; LocalAI (Apertus-8B, EuroLLM-22B); numpy exhaustive search for the legal KB (no FAISS, no ANN) |
| Python | 3.14, pinned once in `.python-version`; `ci.yml` reads it (#277). Both repos run every workflow on GitHub-hosted `ubuntu-latest` (ingester ADR-016, PR #69; the laptop runner is decommissioned by the owner) |
| Jurisdictions | 30 codes (full list in `schemas.py`); empty `jurisdictions=[]` means no filter |
| Risk method | IRP composite per finding. Details: [[LIB-RULES#IRP]] |
| Sibling repo | `legal-corpus-ingester` (PUBLIC, like this one). Corpus bundles feed `legal_kb.py`; `load_from_bundle` is still unwired (D9 / two silent failures). Refresh/health state on ephemeral runners: ingester #71 decided (owner, 2026-10-10) as option 1, `actions/cache`; the mechanism, including the first-record seed step, is still to be implemented before refresh is wired (G2) |
| Wiring audit | #224 shipped (#282): `wiring-audit-submit.yml` Mon 02:00 UTC, `wiring-audit-collect.yml` Tue 04:00 UTC, environment `wiring-audit` with secret `WIRING_AUDIT_API_KEY`, label `wiring-audit`. Fails loudly until the owner creates those. `AnalysisPayload.llm_status` (#287, LIB-API API7) tells an LLM outage from an always-fallback bug |
| Hosting | Railway hosts the frontend (D10); railtail bridges to the local backend. Vercel is removed. Since #133 (#296) the backend requires `API_KEY` (>= 32 chars, ASCII 0x21-0x7E, no whitespace) unless `DEPLOY_ENV=local` on a loopback `BACKEND_HOST`; Railway sets `DEPLOY_ENV=railway` + `API_KEY`. Streamlit and `src/backend/scripts/batch_analyze.py` send `BACKEND_API_KEY` as `X-API-Key`. `MAX_BATCH_ITEMS` defaults to 5 (`config.py`) |
| Review | P9 runs as CI jobs on every PR: `security-review` + `grumpy-review` in `.github/workflows/p9-review.yml` (#214). CRITICAL/HIGH/MEDIUM block; LOW/NIT are carded P3 (#218). Both jobs authenticate with the `CLAUDE_CODE_OAUTH_TOKEN` repo Actions secret (subscription token from `claude setup-token`; #297, owner 2026-10-11; `ANTHROPIC_API_KEY` removed). Only the wiring audit draws API credit (`WIRING_AUDIT_API_KEY`, ADR 0002) |

## hard-requirements
These identifiers mean different things in the ingester repo. Never cite a bare "HR7" across repos.

- HR1 open-source-only: Apache-2.0, MIT or BSD preferred.
- HR2 no vendors facing investor lawsuits, so no Meta-origin dependencies (FAISS excluded). Split HR2a (vendor, zero hops) / HR2b (licence, not origin) is approved (plan R1).
- HR3 every dependency at IRP grade A or higher (`/dependency-audit`).
- HR4 local-only data. Amended by D10 for Railway; see the plan.
- HR5 an LLM failure falls back to rule-only findings with reduced confidence. The LLM answer is validated by `schemas.LLMAnswer` inside `analyze()`.
- HR6 no OpenAI; LocalAI only. EuroLLM-22B for EU/legal, Apertus-8B for multilingual.
- HR7 confidence below 0.80 triggers human-in-the-loop review.
- HR8 rule confidence clamped to [0.90, 0.95]. Scheduled for replacement by per-rule calibrated precision (plan Workstream I, G2b).
- HR9 grades: A <3.5, A- <4.5, B <5.5, B- <6.5, C+ <7.5, C <8.5, D+ >=8.5.
- Model bars (screen before any research): no Meta, no Chinese-origin, no VC-funded LLM house, no ANN index. Memory: `model_constraint_stack`.
- ADR 0001 (`docs/adr/0001-dependency-rules-scope-ci-review-tooling.md`): HR1-HR4 and HR6 cover the PRODUCT. CI review tooling (claude-code-action, CodeQL, Copilot) is exempt.
- ADR 0002 (`docs/adr/0002-wiring-audit-batch-api-exemption.md`): the weekly wiring audit (#224, `scripts/audit/`, two scheduled workflows) may send allowlisted, leak-scanned repository source to the Message Batches API under nine conditions (source only, GitHub-hosted trusted triggers, dedicated environment-scoped key with its own cap, budget before submission, no silent success, model output as data, batch deleted on every exit path, no SDK in the app).

## project-map
| Path | Purpose |
|------|---------|
| `src/webapp/` | Streamlit `app_streamlit_v2.py` (primary) and `app_streamlit_legacy.py` (`STREAMLIT_UI=v1`) |
| `src/backend/app/` | FastAPI `main.py`, `schemas.py`, `models.py`, `config.py` (fail-closed validators), `services/` (rules, analyzer, validation, ingest, localai, embedding, legal_kb, diffing, prompts) |
| `src/backend/app/services/ingest.py` | SSRF-safe URL fetcher (#258): resolve once, blocklist every address, pin the connected one, identity-only encoding, byte cap, one total deadline. Typed `UrlFetchError.reason` |
| `src/backend/tests/` | pytest suite. CI enforces a 98% coverage floor at precision 2 (#208) |
| `tests/` | root integration and E2E tests |
| `.githooks/pre-commit` | gitignore SSoT, graveyard, case-insensitive `.env` guard, evidence leak guard (check 4). Install with `scripts/install-hooks.sh`. There is no pre-push hook any more |
| `.github/workflows/` | `ci.yml` (lint, test, evidence-scan, audit; job timeouts; least-privilege permissions), `p9-review.yml` (CI reviews), `gitignore-enforcement.yml`, `board-sync.yml` (#219; needs the `PROJECT_TOKEN` secret) |
| `.claude/governance/` | `required-gitignore.txt`, `personal-path-patterns.txt` (#145), `evidence-leak-regex.txt` + `leak-vectors.tsv` (#192) |
| `scripts/governance/` | `leak_scan.py` + `scan-evidence-leaks.sh` (#192), `verify-hashes.sh`, `regen-manifest.sh` (regen needs owner intent) |
| `docs/adr/` | ADR 0001 (dependency rules scope), ADR 0002 (wiring audit exemption) |
| `scripts/audit/` | Weekly wiring audit (#224): `inventory.py`, `submit.py`, `collect.py`, `client.py`, `config.py`, `config.json`, `fixtures/canary_unwired.py`. Runs from `wiring-audit-submit.yml` / `-collect.yml` under ADR 0002 |
| `docs/evidence/` | review, design and status evidence. UNTRACKED. Never commit it; the evidence-scan job and pre-commit check 4 refuse local paths |
| `docs/plans/`, `docs/specs/`, `docs/reports/`, `docs/research/` | plans, specs, reports, research |

## commands
| Task | Command |
|------|---------|
| Backend | `cd src/backend && uvicorn app.main:app --reload` |
| Frontend | `cd src/webapp && streamlit run app_streamlit_v2.py --server.port 8501` |
| Both | `./run.sh` |
| Tests as CI runs them | copy the pytest line from `.github/workflows/ci.yml` verbatim and run it from `src/backend` on a Python 3.14 venv (`.python-version`) |
| Evaluation | `cd src/backend && python scripts/evaluate.py` |
| Governance hashes | `bash scripts/governance/verify-hashes.sh` |
| Evidence leak scan | `bash scripts/governance/scan-evidence-leaks.sh "$(git rev-parse --show-toplevel)"` |
| Install hooks | `bash scripts/install-hooks.sh` (sets `core.hooksPath=.githooks`) |

## reference-library
On demand in `.claude/library/<KEY>.md`: LIB-ARCH (architecture, data flow, RAG pipeline); LIB-STACK (dependencies, versions, approved tools); LIB-LEGAL (legal models, corpora); LIB-TEST (test coverage plan); LIB-API (endpoint contracts); LIB-RULES (rule engine, confidence, IRP); LIB-EVAL (rubric, F1/Kappa); LIB-CONTEXT (context chips, weights, sort); LIB-VOICE (copy rules); LIB-PRINCIPLES (P1-P9 governance: P7 attribution, P8 roles, P9 review).
History of shipped work before 2026-10 (PR #34/#35, IRP, chips, `/infer`, the v2 UI): git log and `docs/reports/`. Don't restate it here.

## skills
`/test-suite`, `/write-tests`, `/evaluate`, `/review`, `/webapp-testing`, `/dependency-audit`, `/legal-kb`, `/ralph-loop`. Descriptions are in each skill's SKILL.md.
