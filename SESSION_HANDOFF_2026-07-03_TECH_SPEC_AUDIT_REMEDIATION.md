# Session Handoff — Tech Spec Audit Remediation

**RESOLVED 2026-07-03 later same day:** PR #35 merged. Phase 6 OE-003 completed. All "IN FLIGHT" warnings below are stale. See SESSION_HANDOFF_2026-07-03_SKILLS_WORKFLOWS_AGENTS_FOLLOWUP.md for next work.

**Date:** 2026-07-03
**Refresh:** end-of-day (09:24 local). Phases 5 + 6 landed since morning draft; OE-003 still IN FLIGHT at refresh time.
**Branch:** `claude/issue-19-arch-docs-followup`
**Base:** merged PR #34 (issue #19 plain-language redesign) — see `SESSION_HANDOFF_2026-07-03_ISSUE_19_REDESIGN.md` for the redesign session.
**Author:** Claude (Opus 4.7 [1M])
**Reason:** Session cleared with 3 background agents in flight (morning). Reconstructed state, then day continued through Phase 5 governance layer and Phase 6 OE-003 canonicalization. Refreshed so next instance can pick up cleanly after OE-003 returns.

---

## 1. Why this branch exists

After PR #34 merged, we drafted `docs/TECH_SPEC.md` and a companion audit `docs/reports/tech-spec-audit.md` that cross-checks the shipped code against BRD / PRD / `PRODUCT.md` / `.claude/CLAUDE.md` / `.claude/library/LIB-*.md`.

Audit headline (from `docs/reports/tech-spec-audit.md` §0):

- **BLOCKING:** 3
- **HIGH:** 12
- **MEDIUM:** 15
- **LOW:** 8
- **NIT:** 3
- **Open questions:** 6

Categories: GAPS (BRD/PRD requirement not implemented), OVER-ENGINEERING (code without an anchor), BLOAT (dead/superseded/redundant), LOGIC ERRORS (`LE-*`), GOVERNANCE (docs vs code drift).

The remediation was chunked into 4 phases and run as parallel background agents.

---

## 2. Phase status

| Phase | Scope | Status | Where the work landed |
|-------|-------|--------|-----------------------|
| **1** | Fix all 3 BLOCKING + 12 HIGH audit findings + write regression tests | **COMPLETE.** 24 new tests + 4 pre-existing tests corrected. **726 passing / 0 failing** (up from 702 baseline). 5 blockers surfaced and since resolved via Phases 5 + 6. | `src/backend/tests/test_audit_phase1_fixes.py` (new); fixes in `main.py:117,145,390-396,541,976`, `analyzer.py:332` + boost dicts, `app_streamlit_v2.py::_render_review_required_banner`, `src/webapp/requirements.txt`, `run.sh` |
| **2** | PRD refresh (bump version, remove personal path, reconcile IRP as shipped, document new endpoints/fields, retire "planned enhancement" labels) | **COMPLETE through v2.3.** v2.1 initial refresh, v2.2 resolved URL-timeout + text-cap + LE-013 taxonomy alignment, v2.3 rewrote Flow 2 Batch Analysis as API-only. v2.4 lands with OE-003. | `docs/PRD_Terms_Policies_Reviewer.md` (v2.0 → v2.3) |
| **3** | BRD update for global-tool contract — **Option A** (accept shipped `jurisdictions=[]` = no filter, rewrite US-CA+GDPR default clauses in BRD) | **COMPLETE.** BRD v1.0 → v1.1. BRD-CONSTRAINT-01 codified global-tool contract, BRD-CONSTRAINT-02 codified hardware permissions as scope caveats only. IRP scoring reconciled from "planned enhancement" to shipped. | `docs/BRD_Terms_Policies_Reviewer.md` (v1.0 → v1.1) |
| **4** | Retire JS SPA fallback (`app.js`, `index.html`, `style.css`) — Streamlit v2 is the only shipped UI now | **COMPLETE.** 4,321 lines deleted across 3 files. Doc sweep across 34 files. `.claude/rules/code-style.md` JS section removed. | `src/webapp/{app.js,index.html,style.css}` deleted; docs sweep |
| **5** | Drift 1 (6 dormant categories restored via `schemas.CATEGORIES` expansion), Drift 2 (Verify view split-pane in Streamlit v2), `.gitignore` governance layer (pre-commit hook + CI workflow + `docs/DEV_SETUP.md`) | **COMPLETE.** Test count 726 → **747 passing**. Closes GAP-007. See §7b for the governance layer details. | `.githooks/pre-commit` (new), `scripts/install-hooks.sh` (new), `.github/workflows/gitignore-enforcement.yml` (new), `docs/DEV_SETUP.md` (new), `schemas.py`, `app_streamlit_v2.py` |
| **6** | OE-003 watchlist canonicalization: merge `PolicyWatch` into `WatchlistItem`, honor per-item `check_frequency` (fixes silent no-op bug), migrate `enabled` string→bool (LE-010), migration script, PRD v2.4 codification | **IN FLIGHT at handoff refresh time.** File mtimes on `models.py` / `schemas.py` / `main.py` / migration script last touched 08:56-09:02; Doer still finalizing PRD v2.4. Test file `test_watchlist_merge.py` present at 09:02. Final test count TBD. | `src/backend/app/models.py`, `schemas.py`, `main.py`, `database.py`, `src/backend/scripts/migrate_policywatch_to_watchlist.py`, `src/backend/tests/test_watchlist_merge.py`, PRD v2.4 |

**Parallel GitHub issues filed:** 41 audit backlog issues under label `audit-2026-07-03` (issues #36 through #76). 1 Alembic follow-up filed as #77 for public-repo schema evolution readiness.

---

## 3. Phase 2 — PRD OPEN QUESTIONS (all resolved)

All three morning-draft `OPEN QUESTION` markers have been resolved and codified into the PRD Change History:

1. **URL fetch timeout — RESOLVED (v2.2).** Separated from LLM inference timeout via new `LM_URL_FETCH_TIMEOUT_S` env var (default 30 seconds). `LM_REQUEST_TIMEOUT_S` (60 seconds) governs LLM inference only.
2. **Text paste cap — RESOLVED (v2.2).** `MAX_INPUT_CHARS = 50000` with paste-time whitespace normalization (strip leading/trailing, collapse internal runs) applied before the length check.
3. **Flow 2 Batch Analysis — RESOLVED (v2.3).** Ships **API-only** for this release. UI treatment is a P2 follow-up. Rationale: the synchronous `POST /analyze/batch` endpoint cannot survive a real 50-URL run behind HTTP proxies without an async job model, which is a multi-day architecture change, not a UI wire-up.

PRD Change History table + Implementation Status Note are in place through v2.3. Personal path grep: 0 hits. v2.4 codification lands with OE-003 (merged WatchlistItem, per-item `check_frequency`, boolean `enabled`).

---

## 4. Current git state (uncommitted, refreshed 09:24)

```
Branch: claude/issue-19-arch-docs-followup
Commits ahead of origin/main: 1 (88fd411 docs: session outcomes — LIB-CONTEXT + LIB-VOICE + updated refs)

Modified:
  .claude/CLAUDE.md
  .claude/library/LIB-ARCH.md
  .claude/library/LIB-STACK.md
  .claude/library/LIB-TEST.md
  .claude/skills/webapp-testing/SKILL.md
  .env.example
  .gitignore                                    <-- Phase 5 governance layer
  AGENTS.md
  README.md
  docs/BRD_Terms_Policies_Reviewer.md          <-- Phase 3 complete (v1.1)
  docs/DESIGN.md
  docs/ENHANCEMENT_6.md
  docs/ENHANCEMENT_6_SUMMARY.md
  docs/PRD_Terms_Policies_Reviewer.md          <-- Phase 2 complete through v2.3; v2.4 with OE-003
  docs/PROJECT_STRUCTURE.md
  docs/architecture-diagrams.md
  docs/diagrams/architecture.mmd               <-- Phase 4 rewrote this
  docs/plans/agent-skills-surface-area-audit.md
  docs/plans/data-integrity-architecture-analysis.md
  docs/wireframes/issue-19-design-decisions.md
  run.sh
  src/backend/app/config.py                     <-- Phase 2 (LM_URL_FETCH_TIMEOUT_S)
  src/backend/app/main.py                       <-- Phase 1 + Phase 6 (OE-003 IN FLIGHT)
  src/backend/app/models.py                     <-- Phase 6 (OE-003 IN FLIGHT — do not touch)
  src/backend/app/schemas.py                    <-- Phase 5 (6 categories) + Phase 6 (OE-003 IN FLIGHT)
  src/backend/app/services/analyzer.py          <-- Phase 1 (LE-012/013/018)
  src/backend/app/services/ingest.py            <-- Phase 2 (URL timeout split)
  src/backend/tests/test_all.py
  src/backend/tests/test_main_endpoints.py      <-- Phase 6 (OE-003 IN FLIGHT — do not touch)
  src/backend/tests/test_services.py
  src/backend/tests/test_snapshots_and_diffs.py <-- Phase 6 (OE-003 IN FLIGHT — do not touch)
  src/webapp/app_streamlit_v2.py                <-- Phase 1 + Phase 5 (Verify view)

Deleted (Phase 4):
  src/webapp/app.js
  src/webapp/index.html
  src/webapp/style.css

Untracked (new files):
  .claude/library/LIB-PRINCIPLES.md            <-- constitutional doc, keep
  .githooks/                                    <-- Phase 5 governance layer
  .github/workflows/gitignore-enforcement.yml   <-- Phase 5 CI enforcement
  SESSION_HANDOFF_2026-07-03_ISSUE_19_REDESIGN.md
  SESSION_HANDOFF_2026-07-03_TECH_SPEC_AUDIT_REMEDIATION.md  <-- this file
  docs/DEV_SETUP.md                             <-- Phase 5 hook bootstrap docs
  docs/TECH_SPEC.md
  docs/reports/tech-spec-audit.md
  docs/reports/user-decision-brief-2026-07-03.md <-- Agent 3 decision brief
  docs/reports/pr-body-draft-2026-07-03.md      <-- End-state PR body draft
  scripts/                                      <-- Phase 5 install-hooks.sh
  src/backend/scripts/batch_analyze.py          <-- Flow 2 API-only helper
  src/backend/scripts/migrate_policywatch_to_watchlist.py <-- Phase 6 (OE-003)
  src/backend/tests/test_audit_phase1_fixes.py  <-- Phase 1 regression suite
  src/backend/tests/test_watchlist_merge.py     <-- Phase 6 (OE-003 IN FLIGHT — do not touch)
  src/webapp/requirements.txt                   <-- Phase 1 GAP-014

Diff shape: ~1,914 insertions, ~5,258 deletions across ~39 files (net negative due to JS SPA delete).
```

Stale `LIB-STACK 2.md` from morning session was deleted by dispatched agent (was untracked, no git diff).

---

## 5. Phase 1 findings covered by `test_audit_phase1_fixes.py`

The new test file (written by the Phase 1 agent, verify it exists and passes) defends against these audit IDs. Each has a test class named after it:

| Audit ID | Fix summary | Where |
|----------|-------------|-------|
| **LE-001** | `_refresh_all_watchlist_items` + `refresh_watchlist` endpoint must call `detect_findings(text, [])`, not `["US-CA", "GDPR"]` | `main.py` |
| **LE-002** | `/analyze/file` must not fall back to `["US-CA", "GDPR"]` when caller omits or sends only invalid jurisdictions | `main.py::analyze_file` |
| **LE-003** | `_watchlist_loop_async` must `logger.exception(...)` on refresh failure, not `except Exception: pass` | `main.py::_watchlist_loop_async` |
| **LE-012** | `_apply_industry_emphasis` / `_apply_doctype_weighting` must use exact-category match, not substring (was falsely boosting "PIPEDA Consent" when Finance had "Consent" boost) | `analyzer.py` |
| **LE-013** | Every key in `_DOCTYPE_BOOSTS` / `_INDUSTRY_BOOSTS` must be in `schemas.CATEGORIES`; import-time guard raises on drift | `analyzer.py` |
| **LE-017** | Streamlit v2 must render a visible banner for `review_required` (backend already sets it — UI was silently swallowing) | `app_streamlit_v2.py::_render_review_required_banner` |
| **LE-018** | `_derive_action_items` output must not contain em-dashes (LIB-VOICE) | `analyzer.py::_derive_action_items` |
| **GAP-001** | `/exports/analyses.csv` must honour `?ids=` and `?detailed=true` query params (Streamlit v2 already sends them; backend was ignoring) | `main.py` |
| **GAP-014** | `src/webapp/requirements.txt` must declare pinned `streamlit` + `requests`; `run.sh` installs them | `src/webapp/requirements.txt`, `run.sh` |
| **Drift 1** | 6 dormant categories restored to `schemas.CATEGORIES` after LE-013 substring→exact fix (Phase 5) | `schemas.py` |
| **Drift 2 / GAP-007** | Verify view split-pane expander added per PRD §5.4.3 acceptance criteria (Phase 5) | `app_streamlit_v2.py` |
| **OE-003** | Merged `PolicyWatch` into `WatchlistItem`; per-item `check_frequency`; `enabled` string→bool (LE-010); migration script (Phase 6 IN FLIGHT) | `models.py`, `schemas.py`, `main.py`, `migrate_policywatch_to_watchlist.py`, `test_watchlist_merge.py` |

**Verification step for next session:** run `cd src/backend && python -m pytest tests/test_audit_phase1_fixes.py -v` — every test that fails names the audit ID it defends. If any test fails, the corresponding code fix did not land or regressed. Also run `python -m pytest tests/test_watchlist_merge.py -v` for OE-003 coverage once Phase 6 completes.

---

## 6. Phase 3 — BRD update (COMPLETE)

`docs/BRD_Terms_Policies_Reviewer.md` bumped to v1.1 via Option A (accept shipped behavior, rewrite BRD, no code change).

- **BRD-CONSTRAINT-01** codifies the global-tool contract: `jurisdictions=[]` means "no filter" across rules, LLM post-filter, and Streamlit resolution. Cross-referenced from §Executive Summary, §Product Architecture, §Appendix A.
- **BRD-CONSTRAINT-02** codifies hardware permissions (camera / mic / contacts / location) as scope caveats only, never a chip or domain group with findings, per LIB-PRINCIPLES Principle 4.
- Every US-CA and GDPR default-jurisdiction clause rewritten to "user-selected".
- IRP scoring reconciled from "planned enhancement" to shipped, per PR #34 and PRD v2.1+ §F3.1.
- Personal path removed from header. Grep confirms 0 hits.

---

## 7. Phase 4 — JS SPA retirement (COMPLETE)

Files deleted: `src/webapp/{app.js,index.html,style.css}` (4,321 lines total).
`docs/diagrams/architecture.mmd` rewritten to remove the JS SPA node.
Doc sweep applied to: `README.md`, `run.sh`, `AGENTS.md`, `.env.example`, `.claude/library/LIB-STACK.md`, `.claude/library/LIB-ARCH.md`, `.claude/skills/webapp-testing/SKILL.md`, `docs/DESIGN.md`, `docs/architecture-diagrams.md`, `docs/PROJECT_STRUCTURE.md`. Anywhere `app.js`, `index.html`, `style.css`, "JS SPA", or "vanilla JS frontend" appeared, copy now points at Streamlit v2 as the sole UI (legacy Streamlit remains as rollback via `STREAMLIT_UI=v1`).
`.claude/rules/code-style.md` JavaScript section removed.

---

## 7b. Phase 5 — Drift + governance (COMPLETE)

Two code-drift fixes plus a new `.gitignore` governance layer.

**Drift 1 — 6 dormant categories restored to `schemas.CATEGORIES`.** The LE-013 substring→exact-match fix in Phase 1 exposed boost keys that had been firing on unrelated substrings and stopped firing entirely once the fix landed. Per PRD v2.2 taxonomy alignment, these canonical labels were added so their boost entries stayed live: `Arbitration / Dispute`, `Third-Party Sharing`, `Sub-processors`, `Data Transfer`, `Intellectual Property`, `Transparency`, `In-App Purchases`. `Data Retention` and `Liability Limitation` remain boost-dict aliases only (no new schema entry).

**Drift 2 — Verify view split-pane shipped.** PRD §5.4.3 acceptance criteria for Verify view codified in Streamlit v2 as an expander per finding: highlighted excerpts side-by-side with plain-language interpretation. Closes GAP-007.

**`.gitignore` governance layer:**

| File | Purpose |
|------|---------|
| `.githooks/pre-commit` | Blocks any commit that regresses canonical `.gitignore` invariants (no committed `.venv/`, `terms_analysis.db`, `ignore/`, `__pycache__/`). |
| `scripts/install-hooks.sh` | Bootstraps hooks path from `.git/hooks/` to `.githooks/`. Required because `.git/hooks/` is not versioned by default. |
| `.github/workflows/gitignore-enforcement.yml` | Runs the same invariants in CI, so the guard survives a developer who forgot to run `install-hooks.sh`. |
| `docs/DEV_SETUP.md` | Documents the bootstrap step for new clones. |

Test count moved 726 → **747 passing** after Phase 5.

---

## 7c. Phase 6 — OE-003 canonicalization (IN FLIGHT at handoff refresh)

Scope per `docs/reports/user-decision-brief-2026-07-03.md`:

- Merge `PolicyWatch` into `WatchlistItem` as single canonical watch abstraction (resolves OE-003).
- Honor per-item `check_frequency` in `_watchlist_loop_async` (fixes silent no-op bug — real bug, not just cleanup).
- Migrate `PolicyWatch.enabled` from string `"true"` to Boolean (closes LE-010).
- Migration script `src/backend/scripts/migrate_policywatch_to_watchlist.py` for pre-OE-003 SQLite files.
- PRD v2.4 codifies the merged model.
- Regression coverage in `src/backend/tests/test_watchlist_merge.py` (present at 09:02 mtime).

**File mtimes at refresh (09:24):** models.py 08:56, schemas.py 08:57, main.py 08:59, migration script 08:59, test file 09:02. All modified today, Doer still finalizing PRD v2.4 codification. Do NOT touch these files — parallel Doer owns them.

**Pickup after OE-003 returns:**

1. Run `python -m pytest src/backend/tests/test_watchlist_merge.py -v` to confirm the merged model tests pass.
2. Run the full suite to confirm test count landed at ~760 passing (baseline 747 + new OE-003 tests).
3. Confirm PRD v2.4 Change History entry was added.
4. Confirm final call on retired `/policy-watch/*` routes (HTTP 410 Gone vs redirect to `/watchlist/*`). User leaned toward 410 in the decision brief but Doer may have chosen redirect for backward-compat.
5. Refresh the PR body draft at `docs/reports/pr-body-draft-2026-07-03.md` — replace TBD placeholders in Phase 6 section, breaking-changes list, and final test count line.

---

## 8. User decisions this session (all resolved)

Jennifer answered every open question raised during the day:

| # | Question | Decision | Where codified |
|---|----------|----------|----------------|
| Q1 | URL fetch timeout — separate from LLM inference? | Yes, new `LM_URL_FETCH_TIMEOUT_S` env var, default 30 seconds | PRD v2.2, `config.py`, `ingest.py` |
| Q2 | Text paste cap — 20k or 50k? | 50k with paste-time whitespace normalization (strip + collapse runs) | PRD v2.2, `analyzer.py` |
| Q3 | Flow 2 Batch Analysis UI — ship this release? | No batch UI. API-only for this release, P2 follow-up for async job model | PRD v2.3 |
| Q4 | Phase 3 BRD approach — Option A (accept shipped) or Option B (change code)? | Option A. Codify shipped behavior in BRD | BRD v1.1, BRD-CONSTRAINT-01/02 |
| Q5 | GAP-007 Verify view — implement in v2 or update PRD? | Implement. PRD §5.4.3 acceptance criteria stand | `app_streamlit_v2.py` split-pane expander (Phase 5) |
| Q6 | OE-003 — canonicalize on WatchlistItem or PolicyWatch? | WatchlistItem canonical. Merge PolicyWatch fields into it, honor per-item `check_frequency`, migrate `enabled` to Boolean | Phase 6 IN FLIGHT |
| Q7 | `.gitignore` invariants — hook them structurally, or delete the offenders and rely on discipline? | Add governance hook (pre-commit + CI + docs), do not rely on discipline | Phase 5 governance layer |
| Q8 | LE-013 boost-only keys — delete or add to canonical categories? | Add to canonical `schemas.CATEGORIES` as Option Z. Preserves boost behavior, keeps taxonomy honest | PRD v2.2, `schemas.py` (Phase 5 Drift 1) |
| Q9 | File GitHub issues for deferred audit findings, or PRD status note? | File issues. All 41 landed under label `audit-2026-07-03` (#36-#76). Alembic follow-up filed as #77 | GitHub issues |

### 8a. Remaining open items

Everything else is either resolved or filed as a tracked follow-up issue. Only remaining item:

- **OE-003 outcomes** — final test count, final call on `/policy-watch/*` retirement mechanism (410 Gone vs redirect), PRD v2.4 codification content. Will settle when Doer returns.
- **BL-001 — `/ignore/` graveyard removal window.** Still deferred. Cleanup path unchanged: git tag → `git rm -r ignore/` → `.gitignore` update. Not blocking this PR — filed as backlog.

---

## 9. Do-not-do list (learned this session)

- **Do not** commit until all four phases are green AND the user has answered §3 open questions. Multiple commits per phase is fine; a "final" commit that mixes unresolved OPEN QUESTIONs with code fixes is not.
- **Do not** silently accept the `LIB-STACK 2.md` duplicate. Diff and delete.
- **Do not** re-inject the US-CA+GDPR default anywhere. Every entry point (endpoints, watchlist refresh, background loop) has to keep the `[]` == no-filter contract. This is BRD-CONSTRAINT territory now.
- **Do not** delete `app_streamlit_legacy.py` in Phase 4. It's the rollback path behind `STREAMLIT_UI=v1` and is explicitly named in `.claude/CLAUDE.md` §Project Map.
- **Do not** touch `ignore/` — it's the graveyard for superseded code; keep untracked (see `.gitignore`).
- **Do not** amend already-pushed commits. New commits per Ask → Confirm → Execute pattern.

---

## 10. Resume checklist for the next session

Run these, in order, once OE-003 Doer returns:

1. `git status` and `git diff --stat` — confirm the file list in §4 above still matches, plus any final OE-003 touches.
2. `cd src/backend && python -m pytest tests/test_audit_phase1_fixes.py -v` — Phase 1 regression suite. Every failure names its audit ID.
3. `cd src/backend && python -m pytest tests/test_watchlist_merge.py -v` — Phase 6 OE-003 regression suite.
4. `cd src/backend && python -m pytest -v` — full suite. Target ~760 passing (747 baseline + OE-003 tests).
5. Confirm PRD v2.4 Change History row exists and codifies the merged WatchlistItem model.
6. Refresh `docs/reports/pr-body-draft-2026-07-03.md`: replace TBD placeholders in Phase 6, breaking-changes list, final test count.
7. Personal-path scrub: grep for the developer's home-directory username across `docs/`, `.claude/`, `README.md`, `AGENTS.md` must return 0 across all committed files.
8. Em-dash scrub on any prose the OE-003 Doer wrote: LIB-VOICE forbids em-dashes.
9. Stage in logical chunks. Suggested commit order: (a) Phase 1 fixes + regression tests, (b) Phase 2 PRD v2.1-v2.3, (c) Phase 3 BRD v1.1, (d) Phase 4 JS SPA retirement + doc sweep, (e) Phase 5 drift fixes + governance layer, (f) Phase 6 OE-003 + PRD v2.4. Do not mix phases.
10. Push branch, open PR with body from `docs/reports/pr-body-draft-2026-07-03.md`. Link the audit backlog label `audit-2026-07-03`.

---

## 11. Key file map (fast reference)

```
Audit:      docs/reports/tech-spec-audit.md   (812 lines, 41 findings + 6 OQs)
Tech spec:  docs/TECH_SPEC.md                 (new, 1,627 lines)
BRD:        docs/BRD_Terms_Policies_Reviewer.md (1,370 lines, Phase 3 target)
PRD v2.1:   docs/PRD_Terms_Policies_Reviewer.md (2,211 lines, Phase 2 done)
Governance: .claude/library/LIB-PRINCIPLES.md (new, constitutional)
Redesign
handoff:    SESSION_HANDOFF_2026-07-03_ISSUE_19_REDESIGN.md (root)
This
handoff:    SESSION_HANDOFF_2026-07-03_TECH_SPEC_AUDIT_REMEDIATION.md (root)
```

Prior session's parallel-agent transcripts (informational, may be inaccessible after further /clear):
```
~/.claude/projects/<session-id>/subagents/
  agent-a006bd2c2a6208648.jsonl   Phase 2 PRD refresh   (completed)
  agent-a72c677b3f506fce8.jsonl   Phase 1 fixes+tests   (in flight at clear)
  agent-a9fe1e843f8972510.jsonl   Phase 4 JS SPA retire (in flight at clear)
```

---

## 12. One-line summary for the very impatient

Phase 1 (BLOCKING+HIGH fixes + regression tests) — **COMPLETE.** 702 → 726 passing.
Phase 2 (PRD v2.1 → v2.3) — **COMPLETE.** URL timeout split, text cap 50k, Flow 2 API-only.
Phase 3 (BRD v1.1 Option A) — **COMPLETE.** BRD-CONSTRAINT-01/02 codified.
Phase 4 (JS SPA retire) — **COMPLETE.** 4,321 lines removed, doc sweep across 34 files.
Phase 5 (Drift + governance) — **COMPLETE.** 726 → 747 passing. `.gitignore` guard live locally + in CI.
Phase 6 (OE-003 canonicalization) — **IN FLIGHT** at 09:24 refresh. Doer still finalizing PRD v2.4 codification.
41 audit-backlog issues (#36-#76) + 1 Alembic follow-up (#77) filed under label `audit-2026-07-03`.
PR body draft ready at `docs/reports/pr-body-draft-2026-07-03.md`.
Nothing committed yet. Branch is `claude/issue-19-arch-docs-followup`.
