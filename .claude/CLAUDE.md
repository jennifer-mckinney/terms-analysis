format: agent-optimized (refreshed 2026-10-10; replaces the 2026-07-03 version)
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

## identity

| Key | Value |
|-----|-------|
| Purpose | Analyse ToS and privacy policies for compliance risk, using rule + LLM + RAG detection |
| Stack | FastAPI backend; Streamlit UI (v2 primary, v1 legacy rollback; Vue 3 planned under D2/G4); SQLite; LocalAI (Apertus-8B, EuroLLM-22B); numpy exhaustive search for the legal KB (no FAISS, no ANN) |
| Python | CI runs 3.11 (`ci.yml`); local dev is 3.14. Moving CI to 3.14 is #215, blocked by #265 |
| Jurisdictions | 30 codes (full list in `schemas.py`); empty `jurisdictions=[]` means no filter |
| Risk method | IRP composite per finding. Details: [[LIB-RULES#IRP]] |
| Sibling repo | `legal-corpus-ingester` (PUBLIC, like this one). Corpus bundles feed `legal_kb.py`; `load_from_bundle` is still unwired (D9 / two silent failures) |
| Hosting | Railway hosts the frontend (D10); railtail bridges to the local backend. Vercel is removed |
| Review | P9 runs as CI jobs on every PR: `security-review` + `grumpy-review` in `.github/workflows/p9-review.yml` (#214). CRITICAL/HIGH/MEDIUM block; LOW/NIT are carded P3 (#218) |

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
| `docs/adr/` | ADR 0001 (dependency rules scope) |
| `docs/evidence/` | review, design and status evidence. UNTRACKED. Never commit it; the evidence-scan job and pre-commit check 4 refuse local paths |
| `docs/plans/`, `docs/specs/`, `docs/reports/`, `docs/research/` | plans, specs, reports, research |

## commands

| Task | Command |
|------|---------|
| Backend | `cd src/backend && uvicorn app.main:app --reload` |
| Frontend | `cd src/webapp && streamlit run app_streamlit_v2.py --server.port 8501` |
| Both | `./run.sh` |
| Tests as CI runs them | copy the pytest line from `.github/workflows/ci.yml` verbatim and run it from `src/backend` on a Python 3.11 venv |
| Evaluation | `cd src/backend && python scripts/evaluate.py` |
| Governance hashes | `bash scripts/governance/verify-hashes.sh` |
| Evidence leak scan | `bash scripts/governance/scan-evidence-leaks.sh "$(git rev-parse --show-toplevel)"` |
| Install hooks | `bash scripts/install-hooks.sh` (sets `core.hooksPath=.githooks`) |

## git-and-review

- G1 prefixes: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `style:`, `chore:`. Subject under 72 characters. Reference the issue. Rules: `.claude/rules/code-style.md`.
- G2 agents never work on `main`. Each lane has its own worktree, `../ta-<card>` or `../lci-<card>`, and a branch cut on GitHub from main and pushed before work starts.
- G3 merge commits only. No rebase, no force-push, no `--no-verify`.
- G4 pipeline per card: design gate (new mechanisms only) → `test-author` (red commit) → `coder` → push + PR → CI reviews → fix rounds → ready → owner merges. After each merge the lead merges main into dependent branches.
- G5 `coder` and `test-author` always run on their defined model (opus), never Sonnet. Sonnet is for the PM and board work only.
- G6 fixes change existing files only (R1). New mechanisms become new cards. No hard-coded values (F13).
- G7 bot commits on our branches are owner-ruled; the default is to absorb them with `merge -s ours`.
- G8 push: agents push feature branches freely and open PRs (owner authorisations A1, A3). Never `main`. No local signoff exists any more.
- G9 "ready to merge #N" requires CI green on the exact `headRefOid`, `mergeStateStatus` CLEAN, and every review thread resolved after checking it against the code (reply with the fixing sha or the card number). Merging is owner-only.
- G10 blocking threshold (owner, 2026-10-09): CRITICAL, HIGH and MEDIUM block and are fixed; LOW and NIT are filed as P3 cards and their threads resolved. Copilot threads are judged the same way. Security findings that touch secrets or access are always fixed.
- G11 standard CI/CD over custom machinery: GitHub-hosted Actions, required checks, vendor-documented patterns. Check the docs and decide; don't build bespoke gates.
- G12 validate by disk: an agent report is not evidence. Read `git log`, `git show --stat`, test output and `gh pr view` before repeating a claim.

## p9-governance

- P9 (LIB-PRINCIPLES): independent security and code-quality review before code reaches main. Since 2026-10-09 it runs in CI (`p9-review.yml`, claude-code-action on Opus, read-only tool allowlist, deny rules for `/proc`, `.git` and credentials). Reviews cost API credit; a `billing_error` shows as `is_error:true`, $0, under 1 s.
- Retired on 2026-10-09 (#214): the local pre-push hard gate, `.git/reviews/*.signoff.json`, owner push scripts, evidence comments, `automations/p9-pre-push.md`.
- Required checks on `main` today: `Lint (ruff)`, `Test (pytest + coverage)`, `Dependency audit (pip-audit)`. `security-review`, `grumpy-review` and `Evidence leak scan (docs/evidence)` are NOT required yet (owner action; a red review does not block the merge button until then). `main` requires conversation resolution, so an unresolved thread blocks the merge.
- Round cap: a third review FAIL on a card goes to the owner (re-scope, or ship LOW/NIT with cards).

## governance-monitoring

- G1 injection: `~/.claude/scripts/verify-injection.sh`, which reads `~/.claude/session-start.log`.
- G2 content: `.claude/_governance-manifest.json` tracks this file, LIB-PRINCIPLES, `required-gitignore.txt` and (until #200 lands) the global CLAUDE.md and PEAS. Run `verify-hashes.sh`. Regenerate only with owner intent, as part of a reviewed PR.
- G3 periodic "is it wired" pass. Reviews catch diffs, not absences, so grep for callers of every public entry point and watch for success paths that can't tell "nothing to do" from "not wired". Automating this is #224.

## reference-library

| Key | File | Use when |
|-----|------|----------|
| LIB-ARCH | `@.claude/library/LIB-ARCH.md` | architecture, data flow, RAG pipeline |
| LIB-STACK | `@.claude/library/LIB-STACK.md` | dependencies, versions, approved tools |
| LIB-LEGAL | `@.claude/library/LIB-LEGAL.md` | legal models, corpora |
| LIB-TEST | `@.claude/library/LIB-TEST.md` | test coverage plan |
| LIB-API | `@.claude/library/LIB-API.md` | endpoint contracts |
| LIB-RULES | `@.claude/library/LIB-RULES.md` | rule engine, confidence, IRP |
| LIB-EVAL | `@.claude/library/LIB-EVAL.md` | rubric, F1/Kappa |
| LIB-CONTEXT | `@.claude/library/LIB-CONTEXT.md` | context chips, weights, sort |
| LIB-VOICE | `@.claude/library/LIB-VOICE.md` | copy rules |
| LIB-PRINCIPLES | `@.claude/library/LIB-PRINCIPLES.md` | P1-P9 governance (P7 attribution, P8 roles, P9 review) |

History of shipped work before 2026-10 (PR #34/#35, IRP, chips, `/infer`, the v2 UI): git log and `docs/reports/`. Don't restate it here.

## skills

`/test-suite`, `/write-tests`, `/evaluate`, `/review`, `/webapp-testing`, `/dependency-audit`, `/legal-kb`, `/ralph-loop`. Descriptions are in each skill's SKILL.md.
