# Retro: Tech Spec Audit Remediation

**Date:** 2026-07-03
**Branch:** `claude/issue-19-arch-docs-followup`
**Scope:** Post-PR-#34 tech-spec audit remediation across 6 phases (BLOCKING+HIGH fixes, PRD v2.0→v2.3, BRD v1.0→v1.1, JS SPA retirement, drift + governance layer, OE-003 watchlist canonicalization). Ended day with OE-003 still in flight.

Sources cited from observable session artifacts: handoff, decision brief, audit report, PRD/BRD version history, `git log --oneline -30`, filed issues #36-#77.

## What went well

- **Three-agent Doer/Critic/Decision pattern with parallel dispatch.** Independent Doers on Phases 1, 2, 4 finished in parallel without collision (different file scopes: tests + analyzer vs PRD vs webapp deletes). Phase 5 governance + Phase 6 OE-003 ran with the same pattern.
- **`.gitignore` governance layer.** Novel invariant: pre-commit hook + CI workflow + `docs/DEV_SETUP.md` bootstrap. Structural enforcement means the `.venv/` / `terms_analysis.db` / `ignore/` / `__pycache__/` drift cannot recur even if a developer forgets to run `install-hooks.sh` (CI catches it).
- **`create_all()` self-init pattern makes public-repo readiness clean.** Fresh clones do not need a migration step. Only developers with pre-OE-003 SQLite state need the one-shot migration script. Alembic follow-up captured in issue #77 for future model changes.
- **LE-013 substring→exact-match fix.** Cleanly revealed 6 dormant boost keys. Rather than silently delete them, PRD v2.2 codified the seven canonical labels (`Arbitration / Dispute`, `Third-Party Sharing`, `Sub-processors`, `Data Transfer`, `Intellectual Property`, `Transparency`, `In-App Purchases`) as taxonomy-canonical, then Phase 5 Drift 1 added them to `schemas.CATEGORIES`. Taxonomy stays honest, boost behavior stays intact.
- **41 audit findings filed as tracked issues.** Under label `audit-2026-07-03` (issues #36-#76). No hidden backlog. Alembic follow-up filed as #77.
- **Test count grew each phase without regressions.** 702 (PR #34 baseline) → 726 (Phase 1) → 747 (Phase 5). Every phase added regression coverage, none deleted or skipped tests.

## What didn't go well

- **Parallel-Doer collision on shared files.** Phase 5 drift work and Phase 6 OE-003 both touched `schemas.py`, `main.py`, and test files. When both Doers had `main.py` open concurrently, the drift Doer's pytest suite could not collect until OE-003 finished rewiring endpoints. Signals we need domain-boundary guardrails, not just phase-boundary ones, when dispatching parallel Doers.
- **OPEN QUESTION markers in PRD v2.1 blocked downstream execution.** Phase 2 shipped v2.1 with three inline `OPEN QUESTION` markers, which meant no Phase 6 codification could land until Jennifer answered them. Batching those decisions into the pre-dispatch decision brief would have unblocked Phase 6 earlier in the day.
- **Morning handoff was stale by lunchtime.** Handoff was drafted while agents were still in flight and had to be refreshed twice as Phases 5 and 6 landed. Would be cleaner to write the handoff at end-of-day and use lighter status-only updates during the session.

## Start doing

- **Enumerate file-level ownership in every parallel-Doer prompt.** The Phase 6 dispatch pattern (explicit "do NOT touch these files" exclusion list at the top of the prompt) worked. Codify as the default for every parallel dispatch, not an exception.
- **Batch decisions ahead of dispatch.** Agent 3's decision brief at `docs/reports/user-decision-brief-2026-07-03.md` was load-bearing for the day. Every Doer that ran after the brief had a resolved decision to codify, not an open question to defer. Do this by default before dispatching Doers.
- **File audit backlog as GitHub issues immediately.** MEDIUM / LOW findings become invisible if left inside a markdown audit report. Filing them under a shared label (`audit-2026-07-03`) makes triage and re-prioritization trivial.

## Stop doing

- **Dispatching a Doer whose scope spans both a data model AND its consumers in parallel with another Doer that consumes the same model.** Split by consumer boundary or serialize. Phase 5 + Phase 6 both touched `schemas.py` and `main.py` and produced the collision above.
- **Leaving `OPEN QUESTION` markers in specs when the answer gates downstream work.** If a downstream Doer needs the answer, get it in the same session before dispatching the downstream Doer.
- **Writing the session handoff mid-flight.** It goes stale within an hour. End-of-day handoff refresh is cheaper than mid-flight drafting plus two refreshes.

## Do more of

- **Decision briefs with A/B/C options and a recommendation.** Agent 3's A1-A4 brief format let Jennifer answer 9 decisions cleanly in one pass. Frame every user question as concrete options with trade-offs, not open-ended prose.
- **GitHub Actions invariants that block regressions structurally.** `gitignore-enforcement.yml` blocks future drift without relying on developer discipline. Apply the same pattern to other invariants (personal-path scrub, em-dash scrub, endpoint-count-in-docs match).
- **Regression-test files organized by audit ID.** `test_audit_phase1_fixes.py` has one test class per audit ID (LE-001, LE-002, etc.). When a test fails, the class name names the finding it defends. Trivial to re-verify a specific fix later.

## Do less of

- **Ambiguous user questions.** Questions like "should we file GitHub issues?" without options slow Jennifer down. Always give her A vs B with a lean.
- **Phase-boundary-only planning.** Phases are useful narrative units but do not guarantee file-boundary isolation. Plan by files owned per Doer.

## What I learned

Structural enforcement beats discipline. Every invariant this session that landed as a hook (`.githooks/pre-commit`) or workflow (`gitignore-enforcement.yml`) will still hold six months from now. Every invariant that lives only in prose (BRD-CONSTRAINT-01, LIB-PRINCIPLES) needs a matching enforcement mechanism to survive the next codebase drift. The pattern generalizes.

## Technical learnings

- **SQLAlchemy `Base.metadata.create_all()` does not ALTER.** New models get created, but changes to existing tables need an explicit migration path. Fine for public-repo first-clone, not fine for existing developers with prior schema. Alembic (#77) captures the pattern for future.
- **`.githooks/` vs `.git/hooks/`.** Git hooks live in `.git/hooks/` which is not versioned. To version hooks, put them in `.githooks/` and use `git config core.hooksPath .githooks` (the `install-hooks.sh` bootstrap). This is a one-time setup per clone.
- **Substring lookup vs exact-match on category dicts is a real bug class, not a stylistic preference.** LE-012 showed "PIPEDA Consent" being boosted whenever Finance had "Consent" registered. Silent, category-mixing. Exact-match plus import-time validation against `schemas.CATEGORIES` catches drift at boot, not at CI review.
- **String `"true"` vs boolean `True` (LE-010) is a real deployment risk, not just a lint issue.** Any downstream `if row.enabled:` truthiness check would pass on the string, but SQLAlchemy filters like `.filter(Model.enabled == True)` may or may not, depending on dialect. Codifying as Boolean removes the ambiguity.

## Process learnings

- **The three-agent DCD (Doer/Critic/Decision) pattern maps two ways.** Interpretation 1: three sequential roles for one task (Doer proposes, Critic reviews, Decision arbitrates). Interpretation 2: three parallel Doers with the orchestrator acting as Critic and Decision for their outputs. This session used interpretation 2 for cost optimization. When the user's request is ambiguous, name the interpretation explicitly in the pre-dispatch summary so the pattern is visible.
- **Parallel-Doer prompts benefit from a "do NOT touch these files" exclusion list at the top.** Especially when the concurrent Doers might overlap. Phase 6 OE-003 was dispatched with an explicit exclusion list for the end-state prep Doer (this Doer) and it prevented collision.

## User psychology learnings

- **Jennifer decides fast when given concrete options plus a recommendation.** She answered all 9 decisions in one pass because the decision brief framed each as A vs B (or A vs B vs C) with a leaning. Ambiguity slows her down more than volume of decisions.
- **She values attribution and hates repeating herself.** The handoff / decision brief / retro triad is deliberately redundant so the next session does not need her to re-explain.
- **She notices unpatterned em-dashes.** LIB-VOICE forbids them in flowing prose. Bullet-lead `**LE-001**` followed by an em-dash separator reads as em-dash to a scanner even if the writer meant a list separator. Colon (`**LE-001**: foo`) is safer and equally readable.
