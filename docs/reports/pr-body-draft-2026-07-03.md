# Tech Spec Audit Remediation

## Summary

This branch closes out issue #19 architecture-docs follow-up by taking the tech-spec audit (`docs/reports/tech-spec-audit.md`, 41 findings + 6 open questions) from raw report to a shipped remediation. It fixes every BLOCKING and HIGH audit finding with regression tests, refreshes the BRD and PRD to match shipped behavior instead of aspirational text, retires the vanilla-JS SPA that was superseded by Streamlit v2, restores 6 dormant rule categories exposed by the LE-013 substring-to-exact-match fix, ships the Verify view that PRD v2.0 claimed but never delivered, canonicalizes the two overlapping watch abstractions (WatchlistItem + PolicyWatch) into a single model, and lands a `.gitignore` governance layer (pre-commit hook + CI workflow) so the invariants stay enforced structurally. Every MEDIUM and LOW audit finding was filed as a follow-up issue under label `audit-2026-07-03` (issues #36 through #76, plus a separate Alembic migration follow-up #77).

## Phases

### Phase 1: BLOCKING + HIGH audit fixes (COMPLETE)

Fixed the 3 BLOCKING findings and the 12 HIGH findings from `docs/reports/tech-spec-audit.md`. Regression tests defending each finding live in `src/backend/tests/test_audit_phase1_fixes.py`, one test class per audit ID.

- **LE-001**: `_refresh_all_watchlist_items` and `refresh_watchlist` endpoint no longer inject the `["US-CA", "GDPR"]` default jurisdiction pair. Both call `detect_findings(text, [])` per the global-tool contract.
- **LE-002**: `/analyze/file` no longer falls back to `["US-CA", "GDPR"]` when the caller omits jurisdictions or sends only invalid codes.
- **LE-003**: `_watchlist_loop_async` uses `logger.exception(...)` on refresh failure instead of `except Exception: pass`.
- **LE-012**: `_apply_industry_emphasis` and `_apply_doctype_weighting` use exact-category match, not substring lookup. The prior substring path was silently boosting "PIPEDA Consent" whenever Finance had a "Consent" boost.
- **LE-013**: Every key in `_DOCTYPE_BOOSTS` and `_INDUSTRY_BOOSTS` is validated against `schemas.CATEGORIES` at import time. Any drift raises immediately.
- **LE-017**: Streamlit v2 renders a visible banner via `_render_review_required_banner` when the backend flags `review_required`. Prior UI was silently swallowing the flag.
- **LE-018**: `_derive_action_items` output is stripped of em-dashes per LIB-VOICE.
- **GAP-001**: `/exports/analyses.csv` honors `?ids=` and `?detailed=true` query params. Streamlit v2 already sent them, backend was ignoring them.
- **GAP-014**: `src/webapp/requirements.txt` declares pinned `streamlit` and `requests`, and `run.sh` installs from it.

Test count moved from 702 (PR #34 baseline) to 726 passing after Phase 1.

### Phase 2: PRD v2.0 to v2.3 refresh (COMPLETE)

Refreshed the PRD across three version bumps as user decisions landed. `docs/PRD_Terms_Policies_Reviewer.md` Change History captures each step.

- **v2.1**: initial refresh. Removed personal path, reconciled IRP scoring language from "planned enhancement" to shipped, retired "planned enhancement" labels on features PR #34 already delivered, documented `POST /infer` and the 5 shipped context chips, added implementation-status note.
- **v2.2**: resolved two of the three v2.1 OPEN QUESTIONs: URL fetch timeout separated from LLM inference timeout via new `LM_URL_FETCH_TIMEOUT_S` env var (default 30 seconds), text paste cap set to `MAX_INPUT_CHARS = 50000` with paste-time whitespace normalization. LE-013 taxonomy alignment codified: seven boost-only labels (`Arbitration / Dispute`, `Third-Party Sharing`, `Sub-processors`, `Data Transfer`, `Intellectual Property`, `Transparency`, `In-App Purchases`) formally listed as canonical categories that must appear in both `schemas.CATEGORIES` and the boost dicts.
- **v2.3**: Flow 2 Batch Analysis rewritten as API-only for this release. Rationale documented in the PRD: the synchronous `POST /analyze/batch` endpoint cannot survive a real 50-URL run behind HTTP proxies without an async job model, which is a multi-day architecture change, not a UI wire-up. UI treatment moved to a P2 follow-up.
- **v2.4**: TBD (refresh after OE-003 returns). Will codify the merged WatchlistItem model, per-item `check_frequency` semantics, and boolean `enabled`.

### Phase 3: BRD v1.0 to v1.1 rewrite (COMPLETE)

`docs/BRD_Terms_Policies_Reviewer.md` bumped to v1.1 via Option A per user decision (accept the shipped behavior, rewrite the doc, no code change).

- **BRD-CONSTRAINT-01** codifies the global-tool contract: `jurisdictions=[]` means "no filter" across rules, LLM post-filter, and Streamlit resolution. No silent US-CA + GDPR default anywhere. Cross-referenced from §Executive Summary, §Product Architecture, and §Appendix A.
- **BRD-CONSTRAINT-02** codifies that hardware permissions (camera / mic / contacts / location) are scope caveats only, never a chip or domain group with findings, per LIB-PRINCIPLES Principle 4.
- Every US-CA and GDPR default-jurisdiction clause was rewritten to "user-selected".
- IRP scoring reconciled from "planned enhancement" to shipped, per PR #34 and PRD v2.1+ §F3.1.
- Personal path removed from header.

### Phase 4: JS SPA retirement (COMPLETE)

The vanilla-JS SPA was superseded by Streamlit v2 in PR #34. This branch removes it and sweeps the documentation.

- Deleted `src/webapp/app.js` (1,725 lines), `src/webapp/index.html` (504 lines), `src/webapp/style.css` (2,092 lines), 4,321 lines total.
- Doc sweep across 34 files removed `app.js` / `index.html` / `style.css` / "JS SPA" / "vanilla JS frontend" references and pointed remaining copy at Streamlit v2 as the sole UI. `app_streamlit_legacy.py` retained as the `STREAMLIT_UI=v1` rollback path per `.claude/CLAUDE.md`.
- `.claude/rules/code-style.md` JavaScript section removed.
- `docs/diagrams/architecture.mmd` rewritten to remove the JS SPA node.

### Phase 5: Drift + governance fixes (COMPLETE)

Two code-drift fixes plus a new governance layer to prevent future `.gitignore` regressions.

- **Drift 1, 6 dormant categories restored.** The LE-013 substring-to-exact-match fix in Phase 1 exposed 6 boost keys that had been firing on unrelated substrings and stopped firing entirely once the fix landed. Per PRD v2.2 taxonomy alignment, the following canonical labels were added to `schemas.CATEGORIES` so their boost entries could stay live: `Arbitration / Dispute`, `Third-Party Sharing`, `Sub-processors`, `Data Transfer`, `Intellectual Property`, `Transparency`, `In-App Purchases`. `Data Retention` and `Liability Limitation` remain as boost-dict aliases only (no new schema entry).
- **Drift 2, Verify view split-pane shipped.** PRD §5.4.3 acceptance criteria for Verify view were codified in Streamlit v2 as an expander per finding, with highlighted excerpts side-by-side with the plain-language interpretation. Closes GAP-007.
- **.gitignore governance layer.**
  - `.githooks/pre-commit` blocks any commit that regresses the canonical `.gitignore` invariants (no committed `.venv/`, no committed `terms_analysis.db`, no committed `ignore/`, no committed `__pycache__/`).
  - `scripts/install-hooks.sh` bootstraps the hooks path from `.git/hooks/` to `.githooks/` because `.git/hooks/` is not versioned by default.
  - `.github/workflows/gitignore-enforcement.yml` runs the same invariants in CI so the guard survives a developer who forgot to run the install script.
  - `docs/DEV_SETUP.md` documents the `scripts/install-hooks.sh` bootstrap step for new clones.

Test count moved from 726 (post-Phase 1) to 747 passing after Phase 5.

### Phase 6: OE-003 watchlist canonicalization (IN FLIGHT at PR-body drafting time)

Scope planned per `docs/reports/user-decision-brief-2026-07-03.md`:

- `PolicyWatch` merged into `WatchlistItem` as the single canonical watch abstraction. Removes the two-model overlap that gated GAP-004 and LE-010.
- Per-item `check_frequency` honored by `_watchlist_loop_async`. Prior code silently no-op'd for items whose frequency did not match the global default, real bug.
- `PolicyWatch.enabled` migrated from string `"true"` to Boolean, closing LE-010.
- Migration script at `src/backend/scripts/migrate_policywatch_to_watchlist.py` handles existing rows for developers with a pre-OE-003 SQLite file.
- PRD v2.4 codification documenting the merged model.
- Regression coverage in `src/backend/tests/test_watchlist_merge.py`.

TBD (refresh after OE-003 returns): final test count, any breaking-endpoint choices between HTTP 410 Gone and redirect for retired `/policy-watch/*` routes, whether the migration script auto-runs or is left as a one-shot for the developer.

## Follow-up issues filed

- 41 audit backlog issues filed under label `audit-2026-07-03` (issues #36 through #76). Covers every MEDIUM, LOW, and NIT finding plus the LE-* items whose fix was deferred behind spec decisions (LE-004, LE-005, LE-006, LE-007, LE-008, LE-009, LE-011, LE-019, LE-020).
- 1 Alembic follow-up filed for public-repo schema evolution readiness (issue #77). Current schema init uses `Base.metadata.create_all()`, which does not ALTER; developers with a pre-OE-003 SQLite file must run `scripts/migrate_policywatch_to_watchlist.py`. Alembic makes this transparent on future model changes.

## Testing

- Baseline: 702 tests / 98.06% coverage at PR #34 merge.
- After Phase 1: 726 passing.
- After Phase 5: 747 passing.
- Final after OE-003: TBD (refresh after OE-003 returns).

## Files touched

Rollup of `git diff --stat` at PR-body drafting time (Phase 6 in flight, will refresh at commit time):

- `.claude/`, CLAUDE.md, LIB-ARCH.md, LIB-STACK.md, LIB-TEST.md, LIB-CONTEXT.md (new), LIB-RULES.md, LIB-VOICE.md (new), LIB-PRINCIPLES.md (new), rules/testing.md, skills/webapp-testing/SKILL.md.
- `.env.example`, `.gitignore`, governance invariants.
- `.githooks/pre-commit` (new), `scripts/install-hooks.sh` (new), `.github/workflows/gitignore-enforcement.yml` (new), `docs/DEV_SETUP.md` (new).
- `AGENTS.md`, `README.md`, `run.sh`, JS SPA sweep + STREAMLIT_UI flag documentation.
- `docs/BRD_Terms_Policies_Reviewer.md` (v1.1), `docs/PRD_Terms_Policies_Reviewer.md` (v2.3, v2.4 TBD), `docs/TECH_SPEC.md` (new, 1,627 lines), `docs/reports/tech-spec-audit.md` (new, 812 lines), `docs/reports/user-decision-brief-2026-07-03.md` (new).
- `docs/DESIGN.md`, `docs/ENHANCEMENT_6.md`, `docs/ENHANCEMENT_6_SUMMARY.md`, `docs/PROJECT_STRUCTURE.md`, `docs/architecture-diagrams.md`, `docs/diagrams/architecture.mmd`, `docs/plans/agent-skills-surface-area-audit.md`, `docs/plans/data-integrity-architecture-analysis.md`, `docs/wireframes/issue-19-design-decisions.md`.
- `src/backend/app/config.py`, `main.py`, `models.py`, `schemas.py`, `services/analyzer.py`, `services/ingest.py`.
- `src/backend/scripts/batch_analyze.py` (new), `src/backend/scripts/migrate_policywatch_to_watchlist.py` (new).
- `src/backend/tests/test_all.py`, `test_main_endpoints.py`, `test_services.py`, `test_snapshots_and_diffs.py`, `test_audit_phase1_fixes.py` (new), `test_watchlist_merge.py` (new).
- `src/webapp/app.js`, `index.html`, `style.css`, deleted.
- `src/webapp/app_streamlit_v2.py`, `src/webapp/requirements.txt` (new).

Rough shape: ~1,914 insertions, ~5,258 deletions across ~39 files (pre-Phase-6 snapshot), net negative because of the 4,321-line JS SPA delete.

## Breaking changes

- Retired JS SPA (`src/webapp/app.js`, `index.html`, `style.css`). Streamlit v2 is the sole UI. `app_streamlit_legacy.py` remains reachable via `STREAMLIT_UI=v1` in `run.sh` as a rollback path.
- Retired `/policy-watch/*` endpoints (final choice between HTTP 410 Gone and redirect to `/watchlist/*` is TBD, decided by OE-003).
- New required env var: `LM_URL_FETCH_TIMEOUT_S` (default 30 seconds). Distinct from `LM_REQUEST_TIMEOUT_S` (default 60 seconds, LLM inference only). Existing `.env` files inherit the default and do not need to be updated.
- `.gitignore` invariants now enforced structurally by `.githooks/pre-commit` and `.github/workflows/gitignore-enforcement.yml`. Fresh clones must run `scripts/install-hooks.sh` once to activate the local hook (CI enforces regardless).
- `PolicyWatch.enabled` schema migrated from string `"true"` to Boolean per LE-010. Existing rows in pre-OE-003 SQLite files must be migrated via `scripts/migrate_policywatch_to_watchlist.py`.

## Deployment notes

- **Fresh clone:** `./run.sh` handles DB init via `Base.metadata.create_all()`. No migration step needed.
- **Existing developer with a pre-OE-003 DB:** run `python src/backend/scripts/migrate_policywatch_to_watchlist.py` once against the local SQLite file before starting the backend. Script is idempotent.
- **Alembic follow-up (#77):** future schema changes will land through Alembic revisions instead of ad-hoc migration scripts. Not required for this PR to merge.
- **Governance hooks:** run `scripts/install-hooks.sh` after clone to activate the pre-commit `.gitignore` guard locally. CI enforces the same invariants regardless.

## Related

- Closes #19 (architecture-docs follow-up).
- Follows PR #34 (issue-19 plain-language redesign).
- Filed as follow-up: audit-2026-07-03 backlog (#36 through #76), Alembic setup (#77).
