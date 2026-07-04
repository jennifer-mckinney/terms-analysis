# Session Handoff — Issue #19 Plain-Language Redesign

**Date:** 2026-07-03
**Project:** terms-analysis
**Branch:** `claude/issue-19-plain-language-redesign`
**PR:** #34

---

## 1. Session context

This session executed the plain-language redesign called for in issue #19 — replacing the pre-existing verdict grades and dense results view with a two-view guided intake + verdict-first results experience. Scope covered end-to-end: interactive HTML mockup, design-decisions doc, BRD/PRD compliance audit, backend inference + context taxonomy + IRP scoring, full Streamlit port behind a feature flag, and a categorical regression test backfill. Landed as PR #34 on branch `claude/issue-19-plain-language-redesign` with CI green and 702 tests passing.

## 2. Current state

**PR #34** — merge-ready, CI green. 4 commits:

| SHA | Purpose |
|-----|---------|
| `e4fd706` | Feature — mockup + backend inference/context/IRP + Streamlit v2 + `POST /infer` endpoint + first-pass tests |
| `2626e2b` | Must-fix — 4 blocker findings from grumpy/principal/security reviews: `for_work` chip drop, `javascript:` XSS on `/infer`, jurisdiction filter empty-list boundary, `/analyze/file` unvalidated jurisdictions |
| `671d3e5` | P1/P2 + gap audit — schema-derived allowlists via `get_args()`, category frozenset import-time validation, backend-driven action items, `test_regressions_pr34.py` (30 tests) |
| `b5ea947` | CI green cleanup — final lint / formatting sweep, quality-audit report attached |

**Test suite:** 702 tests, 98.06% line coverage on `src/backend/`.

**Live services during the session** (may or may not still be running by the time the next agent picks this up — check `ps` before assuming):
- Backend: `uvicorn app.main:app --reload --port 9000` on port 9000
- Streamlit v2: `streamlit run src/webapp/app_streamlit_v2.py` on port 8501 (via `STREAMLIT_UI=v2 ./run.sh`)

**Docs that were updated in this closeout** (not committed yet — orchestrator decides whether to attach to PR #34 or ship as separate follow-up):
- `.claude/CLAUDE.md` — Session outcomes block added, Risk Method row updated, LIB-CONTEXT + LIB-VOICE registered in Reference Library table
- `.claude/library/LIB-CONTEXT.md` — new
- `.claude/library/LIB-VOICE.md` — new
- `.claude/library/LIB-RULES.md` — tier-first sort + global-tool contract + category-taxonomy-pinning sections appended
- `.claude/library/LIB-TEST.md` — full rewrite reflecting 702 test baseline and 3-rule policy
- `.claude/library/LIB-ARCH.md` — IRP "planned" prose replaced with "shipped" prose
- `.claude/rules/testing.md` — 3-rule testing policy appended
- `SESSION_HANDOFF_2026-07-03_ISSUE_19_REDESIGN.md` — this file

## 3. What was built

### Design work
- **Interactive HTML mockup** at `docs/wireframes/issue-19-plain-language-design.html` — full two-view flow: intake with 5 chip cards + tabbed input + blank location defaults, results with verdict headline, 4 domain sections, always-visible scope box, dynamic action items.
- **Design decisions doc** at `docs/wireframes/issue-19-design-decisions.md` — 14 numbered decisions, each with reasoning / tradeoffs / anchors. Referenced from Streamlit v2 module docstring so future agents follow the anchor chain.
- **BRD/PRD compliance audit** at `docs/wireframes/issue-19-brd-prd-compliance.md` — traces every mockup element back to a BRD segment and PRD requirement.

### Backend work
- **`src/backend/app/services/inference.py`** — new. URL TLD detection + text signal detection for jurisdiction / doc_type / industry. `@lru_cache` on hot paths; pre-compiled regexes; observability logging with per-signal source tags.
- **`src/backend/app/services/context.py`** — new. 5-chip taxonomy (`want_understand` / `for_child` / `for_care` / `for_work` / `just_curious`), 1.0 / 2.0 / 2.5 / 3.0 weight tier scale, sum-cap-3.0 multi-context merger, tier-first sort key `(weight, irp_score, severity_rank)` descending, per-context verdict headlines and short chip labels. See LIB-CONTEXT for the full weight table.
- **IRP scoring model** — `impact`, `likelihood`, `safeguard_score`, `irp_score` fields on `Finding` (schemas.py). `analyzer.py::_compute_irp` computes the composite; `rules.py::_seed_irp` seeds rule findings from `_CATEGORY_IRP_DEFAULTS` (38 categories mapped); LLM prompts request the same three fields per finding; hybrid merge takes rule `impact/likelihood` as baseline and `safeguard_score = max(rule, llm)`. `calculate_risk_score()` uses `irp_score` when present, falls back to severity weight for legacy findings.
- **`_group_by_domain`** in `analyzer.py` — maps ~50 categories to 4 fixed domains (Data / Data use / Terms of use / Privacy rights). Populates `AnalysisPayload.top_by_domain`. Unknown category defaults to a known bucket rather than dropping the finding.
- **Global-tool contract** — empty `jurisdictions=[]` = "no filter" mode. Removed all US-CA + GDPR default fallbacks from `rules.py`, LLM post-filter, and Streamlit resolution.
- **Backend-generated `action_items`** on `AnalysisPayload`. Client-side derivation from `finding.explanation` is a fallback path.
- **`schemas.CATEGORIES`** — canonical `frozenset[str]` for all finding-category strings. `context.py::CATEGORY_WEIGHTS` and `analyzer.py::_CATEGORY_IRP_DEFAULTS` validate their keys against it at module load; drift raises `RuntimeError` before the server starts.
- **`POST /infer` endpoint** — accepts URL and/or text, returns TLD-based jurisdiction + doc_type + industry signals for intake pre-fill.
- **Test suite:** 702 tests, 98.06% coverage (baseline was 635 tests before session).

### Frontend work
- **`src/webapp/app_streamlit_v2.py`** (~972 lines) — full Streamlit port of the mockup. Two-view state machine via `st.session_state["view"]`. Teal palette (`--teal: #0d6e8a`). Tabbed input (link / text / file). 5 multi-select context option cards with hover-triggered contextual help. Blank location defaults (`index=None` on all dropdowns). 4 domain sections rendered from `top_by_domain`. Always-visible scope caveat box. Dynamic action items from backend `AnalysisPayload.action_items`.
- **Feature flag `STREAMLIT_UI=v2`** in `run.sh` — legacy path preserved by keeping `src/webapp/app_streamlit_legacy.py` intact. Rollback is a single env-var flip.

### Tests
- **`src/backend/tests/test_regressions_pr34.py`** (30 tests) — categorical regression backfill grouped by category letter (A–G). Covers cross-endpoint field consistency via `typing.get_args()` runtime iteration, schema-Literal allowlist parity, XSS defense-in-depth on URL-scheme fields, malformed / oversized / unicode inputs, ReDoS canary on `inference.py`, domain-grouping edges, sort stability.
- **`test_context.py`, `test_inference.py`, `test_irp.py`** — new per-module tests for the shipped services.
- **`test_main_endpoints.py`** — expanded with per-endpoint parity coverage for chip and jurisdiction allowlists, plus `/infer` endpoint tests.
- **`test_database_and_main_coverage.py`** — coverage-fill for previously untested branches.

### Docs
- **`docs/reports/test-suite-audit-pr34.md`** — gap audit report. Introduces categories A–G. Establishes the 3-rule testing policy that was adopted into `.claude/rules/testing.md`.
- **`docs/reports/test-suite-quality-audit-pr34.md`** — quality audit. **YELLOW verdict.** Pruning recommendations tracked as follow-up PR (parametrize ~55 rule-trigger tests, delete ~8 tautologies, hoist fixtures into `conftest.py`).

## 4. Design principles locked in

These are non-negotiables discovered during the session. Encode them in copy review going forward.

- **Two-voice architecture** — Intake is first-person warm ("What's on your mind?", "We're here to help"). Results is third-person observational (no `you`, `we`, `us`, `our`, `your` in results copy — ever). The reader may be checking a policy for someone else; possessives break when the reader isn't the subject. Full details in `.claude/library/LIB-VOICE.md`.
- **No em-dashes in tool voice** — Zero `—` characters in intake, results, error messages, verdict labels, scope box, action items. Em-dashes remain only inside verbatim quotes of the analyzed policy. AI-detection signal outweighs prosody. Replace with periods, commas, colons, or restructure.
- **Tentative framings** — "may," "perhaps," "possibly," "might," "some," "a possible…" throughout tool voice. Never "you should," "we recommend," "the tool determined." The tool suggests; the reader decides.
- **Global tool, no US default** — Empty `jurisdictions=[]` means "no filter," not "US-CA + GDPR fallback." Location dropdowns default blank (`index=None`) and never presume reader location.
- **Blank location defaults** — Do not pre-fill any location dropdown from browser IP, `Accept-Language`, or any other inference of reader location. The reader picks (or doesn't).
- **Hardware permissions are a scope caveat only** — Camera, mic, contacts, location permissions get surfaced verbatim in the always-visible scope box, never as a chip or a domain group with findings. Hard scope limit. Same rule applies to real-world practice divergence.
> **(SUPERSEDED 2026-07-03 by LIB-PRINCIPLES P4 amendment — real-world-practice-divergence clause dropped; see docs/plans/2026-07-03-results-view-revamp-report-card.md §7 D-Q9 and commit 4e8ccc9)**
- **Verdict labels are actionable, not grades** — "Worth a closer read," not "USE CAUTION." "Not vendor-safe as written," not "STOP." Letter grades still exist on `AnalysisPayload.grade` for machine consumption but are not the primary UI verdict.
- **Scope box always visible** — Never collapsible below the fold. Never optional. The tool must be honest about what wasn't checked before the reader trusts what was checked.

## 5. Workflow patterns established

- **Multi-agent code review** — Dispatched `grumpy-reviewer`, `principal-engineer-reviewer`, and `security-reviewer` in parallel background agents against the initial feature commit. Findings triaged into (a) convergent — flagged by 2+ agents, treated as real, and (b) unique — flagged by 1 agent, evaluated on merit. All four must-fix findings were convergent. Landed as commit `2626e2b`.
- **Gap-audit + quality-audit dual pass on the test suite** — Gap audit (`docs/reports/test-suite-audit-pr34.md`) categorizes what the suite doesn't cover; quality audit (`docs/reports/test-suite-quality-audit-pr34.md`) rates what it does cover. Both audits run at PR close, not at PR start.
- **Design mockup → decisions doc → Streamlit port with feature flag rollback** — HTML mockup first (fastest iteration surface for copy tone), decisions doc captures the "why" for every non-obvious choice, Streamlit port references the decisions doc in the module docstring so future agents can trace anchors. Feature flag keeps rollback trivial.
- **Cross-endpoint parity testing via `typing.get_args()`** — The meta-fix that turns schema-to-handler drift into an import-time failure. Handler allowlists are derived, not hardcoded; tests iterate Literals via `get_args()` instead of hardcoded lists. Codified in `.claude/rules/testing.md` §3-Rule Testing Policy.
- **CI green cleanup pattern before merge** — Final commit (`b5ea947`) does nothing but formatting / lint / quality-audit attachment. Keeps the feature commit and the must-fix commit narratively clean.
- **Session outcomes recorded in `.claude/CLAUDE.md`** — Dated block right above the Reference Library table. Future agents open the file and see what shipped without hunting through library files.

## 6. New skills / agents / workflows worth formalizing

Concrete follow-ups worth building as skills, agents, or hooks. These emerged from the session and would have saved time if they'd already existed.

- **`/persona-review` skill** — Dispatch persona-review agents (Patricia, Sam, Rachel, Alex, Morgan from PRD) against a design or copy sample and report BRD-segment coverage. Would have caught the `for_work` chip drop earlier than the multi-agent code review pass.
- **`/two-voice-audit` skill** — Scan Streamlit + HTML files for voice register violations: `you`, `we`, `us`, `our`, `your` inside results-view sections; first-person warm phrasing inside results copy. Report with file/line references.
- **`/em-dash-scan` skill** — Grep for `—` (U+2014) outside verbatim policy quotes. Fast, deterministic, would have caught the ~6 em-dashes in the initial mockup before mockup review.
- **`/allowlist-drift` skill / CI check** — Assert every handler allowlist is derived from a schema Literal via `get_args()`. Not a test file — a static check that greps for `frozenset({...literal-values...})` patterns and flags them.
- **`test-suite-auditor` agent** — Combines gap audit + quality audit into one pass. Outputs both reports and a merged action list. Would consolidate the two-report workflow into one dispatch.
- **`merge-review` agent** — Runs at end of PR work: green CI check, all-review-findings-addressed check, final lint sweep, verdict output (green / yellow / red). Would replace the manual "check everything one more time before I say merge-ready" ritual.
- **`session-handoff-writer` agent** — Automates the pattern this document follows: session-context paragraph, 4-commit table, principles-locked-in bullets, follow-ups. Reads git log, PR body, `.claude/CLAUDE.md` outcomes block, and generates the handoff.

## 7. Known follow-ups (not blocking)

From the audit reports and observations during the session. None block PR #34 merge.

- **Quality-audit pruning** — Parametrize ~55 rule-trigger tests currently written as separate functions with different regex payloads. Delete ~8 tautological tests where the mock's return value is asserted to equal the mock's configured return value. Hoist common fixtures (`_payload()`, `_result()`, `_finding()` builders duplicated across `test_regressions_pr34.py` and `test_main_endpoints.py`) into `conftest.py`.
- **Sweep remaining `app_streamlit.py` references** in `docs/PRD_*.md` and `docs/BRD_*.md` — the Streamlit primary is now `app_streamlit_v2.py`, but the PRD/BRD prose still references the pre-redesign filename in a few places.
- **`for_compliance_review` and `already_agreed` chips** — Considered and deferred; revisit with usage data on the shipped five. Do not add speculatively.
- **Backend LLM top-things generation** — Currently the "top three things about this policy" content is derived client-side from `finding.explanation` in `app_streamlit_v2.py`. Backend-driven generation via a dedicated LLM call would improve quality and let the tool avoid re-computing on every render.
- **JS SPA retired (Phase 4, 2026-07-03)** — the vanilla-JS SPA was retired rather than brought to Streamlit v2 parity. `src/webapp/index.html` / `app.js` / `style.css` deleted; `run.sh` reduced to backend + Streamlit only; Streamlit v2 is the sole UI, with `app_streamlit_legacy.py` retained as `STREAMLIT_UI=v1` rollback.
- **Adopt the 3-rule testing policy in `.claude/rules/testing.md`** — Codified in this session, needs team enforcement on future PRs. Consider a PR-template checkbox: "New allowlists derived from schema Literal via `get_args()`? Cross-endpoint parity test added? Literal values iterated via `get_args()`, not hardcoded?"

## 8. Files to read first when continuing this work

Reading order for the next agent picking up any follow-up on issue #19:

1. **This file** — `SESSION_HANDOFF_2026-07-03_ISSUE_19_REDESIGN.md`
2. **`.claude/CLAUDE.md`** — Session outcomes block + Reference Library table
3. **`docs/wireframes/issue-19-design-decisions.md`** — 14 numbered decisions with rationale
4. **`.claude/library/LIB-CONTEXT.md`** — Context chip taxonomy, weight tiers, sort semantics
5. **`.claude/library/LIB-VOICE.md`** — Two-voice architecture, no-em-dash rule, scope-honesty gap
6. **`docs/wireframes/issue-19-brd-prd-compliance.md`** — Traces mockup elements back to BRD segments and PRD requirements
7. **`docs/reports/test-suite-audit-pr34.md`** — Categorical gap audit; introduces categories A–G and the 3-rule policy
8. **`docs/reports/test-suite-quality-audit-pr34.md`** — YELLOW verdict, pruning recommendations for follow-up PR

## 9. Key user preferences captured this session

Avoid re-learning these. If a future agent proposes a change that violates one of these, push back before implementing.

- **Global tool, never presume US as default.** Empty jurisdictions = no filter, not US-CA + GDPR fallback. No exceptions.
- **Blank defaults, no inference-to-user-location prefill.** Location dropdowns start empty. Do not use IP, `Accept-Language`, browser geolocation, or any other signal to guess where the reader is.
- **Context choice LEADS priority.** Sort is tier-first (`weight, irp_score, severity_rank` all descending), not multiplicative. If the reader picks `for_child`, Children's Privacy always outranks a higher-IRP Liability finding.
- **No em-dashes in tool voice.** AI giveaway. Non-negotiable.
- **Non-negotiable: fix all review findings, not just must-fixes.** P1 and P2 findings from the multi-agent review pass landed in commit `671d3e5`, not deferred to a follow-up PR. If a reviewer flagged it, address it before merge.
- **Test suite must be honest, not coverage theater.** YELLOW verdict from the quality audit is documented in the PR, not hidden. Pruning follow-up is scheduled, not swept under the rug.
