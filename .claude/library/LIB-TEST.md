# LIB-TEST — test coverage status, quality audit, conventions
loads: on-trigger
scope: project
xref: [[.claude/rules/testing.md]] [[LIB-STACK#S4]] [[docs/reports/test-suite-audit-pr34.md]] [[docs/reports/test-suite-quality-audit-pr34.md]]

status (2026-07-31): baseline is **828 tests, 98% line coverage** on `src/backend/` (2187 stmts, 53 missed, verified via `pytest --cov=app`). Prior anchor 2026-07-03: 702 tests / 98.06%. Policy in `.claude/rules/testing.md` (3-rule schema-drift policy). Two audit reports in `docs/reports/`.

## baseline

| File | Covers |
|------|--------|
| `test_all.py` | API endpoints (analyze/url/file/batch, analyses, rubric, exports incl. PDF-route-shadowing regression, reviews, watchlist CRUD), SSRF URL validation, schema/config boundary cases |
| `test_rules.py` | Rule pattern detection across categories, confidence formula, jurisdiction filtering |
| `test_enhancements.py` | Rubric scoring, completeness/action-readiness computations |
| `test_ingest.py` | HTML/RTF extraction, SSRF-redirect regressions (blocked rejected, allowed followed, loop capped) |
| `test_legal_kb.py` | Chunking, embedding/build/retrieve, jurisdiction filtering (incl. schema-code-mismatch), dimension-mismatch/corrupted-index graceful degradation, placeholder-status propagation, CLI indexing |
| `test_llm_failure.py` | LLM offline fallback, timeout returns `None`, rule-only fallback |
| `test_prompts.py` | `legal_context` placeholder-warning propagation into LLM prompt |
| `test_snapshots_and_diffs.py` | Snapshot create/list/detail, diff computation, policy-watch CRUD + manual snapshot trigger |
| `test_analyzer.py` | Analyzer orchestration, hybrid merge, IRP scoring path, action-readiness, domain grouping |
| `test_context.py` | Context chip weights, `resolve_context`, `apply_category_weights`, `verdict_headline`, `verdict_label` |
| `test_inference.py` | URL TLD detection, text signal detection, `@lru_cache` behavior, ReDoS canary |
| `test_irp.py` | IRP formula, seeded defaults, LLM parse, hybrid safeguard-max merge |
| `test_main_endpoints.py` | Per-endpoint validation, chip/jurisdiction allowlist enforcement, `/infer` endpoint |
| `test_database_and_main_coverage.py` | Coverage-fill for previously untested branches in `database.py` and `main.py` |
| `test_regressions_pr34.py` | **Categorical gap coverage backfilled after PR #34** (42 tests post-PR-#87; Categories A-I + JurisdictionFilterBoundary) — see next section |
| `test_services.py` | Cross-cutting service-layer wiring |
| `test_validation.py` | Hallucination guard, citation checker, boundary confidence values |
| `test_audit_phase1_fixes.py` | Phase 1 audit remediation regressions |
| `test_critical_p9_fixes.py` | P9 pre-push review critical-finding regressions |
| `test_intake_form_race.py` | Streamlit `st.form` intake race-condition regressions (revamp/results-report-card) |
| `test_legal_kb_bundle.py` | Consumer-side legal corpus bundle ingestion (sibling ingester contract) |
| `test_phantom_alias_removed.py` | Regression: `_vendor_from_url` alias deletion (closes #79) |
| `test_vendor_derivation_surface_spec.py` | Vendor derivation surface contract spec |
| `test_watchlist_merge.py` | Watchlist merge semantics regression coverage |

### TEST1: activate-venv-first
rule: MUST `source .venv/bin/activate` before `pytest`
because: else `httpx`/`playwright` resolve to wrong Python and imports fail with unrelated-looking errors

## categorical-regression-coverage

`test_regressions_pr34.py`, 42 tests (post-PR-#87), backfilled after PR #34's four must-fix findings (all four = cross-endpoint / schema-vs-handler drift). Grouped by category letter matching `docs/reports/test-suite-audit-pr34.md`. Categories H (schema-validator edges) and I (inference edges) added later beyond the original A-G taxonomy.

### TEST2: adopt-category-letters
rule: future regression tests MUST adopt same category letters
because: audit traceability

| Cat | Covers |
|-----|--------|
| A | Cross-endpoint field consistency — same field validated identically on `/analyze`, `/analyze/url`, `/analyze/file`, `/analyze/batch`; iterates every Literal value via `typing.get_args()` and POSTs to every sibling endpoint |
| B | Schema-Literal allowlist parity guards — `_VALID_CHIPS == frozenset(get_args(ContextChip))` and `_VALID_JURISDICTIONS == frozenset(get_args(Jurisdiction))` |
| C | URL-scheme XSS defense-in-depth — rejects `javascript:`, `data:`, `vbscript:` schemes on `/infer` and every URL-taking endpoint |
| D | Malformed / oversized / unicode inputs — empty bodies, oversize text, control characters, mixed-encoding payloads |
| E | ReDoS canary on `inference.py` — synthetic pathological input completes under time budget |
| F | Domain-grouping edge cases — unknown category defaults to known bucket rather than dropping; empty `top_by_domain` renders without crash |
| G | Sort stability — `apply_category_weights` returns stable order for equal-key findings; multi-select tie-breaking deterministic |

## quality-audit

`docs/reports/test-suite-quality-audit-pr34.md` flags suite as YELLOW: coverage high but soft spots.

### TEST3: follow-up-parametrize
rule: parametrize ~55 rule-trigger tests that repeat same shape with different regex payloads (follow-up PR, not PR #34 blocker)

### TEST4: follow-up-delete-tautologies
rule: delete ~8 tautological assertions (e.g., asserting mock returns what it was configured to return)

### TEST5: follow-up-hoist-fixtures
rule: hoist common `_payload()` / `_result()` / `_finding()` builders into `conftest.py`
current_duplication: `test_regressions_pr34.py` and `test_main_endpoints.py`

### TEST6: follow-up-explicit-negative-assertions
rule: add explicit assertions for negative cases; currently relying on "no exception raised" as entire assertion surface

## 3-rule-testing-policy

Adopted from PR #34 gap audit. All three prevent **schema-to-handler drift**. Reference implementations in `test_regressions_pr34.py`.
xref: [[.claude/rules/testing.md]]

### TEST7: rule-1-schema-handler-parity
rule: any handler-level allowlist MUST be derived from `typing.get_args(TheLiteral)`, not hardcoded; tests MUST assert equality between handler allowlist and `get_args(Literal)`
xref: [[.claude/rules/testing.md#R1]]

### TEST8: rule-2-cross-endpoint-parity
rule: field validated on `/analyze` MUST be validated same way on every sibling endpoint; parity tests iterate every Literal value + POST to every endpoint
xref: [[.claude/rules/testing.md#R2]]

### TEST9: rule-3-runtime-enum-over-literal
rule: tests MUST use `typing.get_args()` to iterate Literal values, NOT hardcode a list
because: hardcoded lists drift; `get_args()` stays in sync
xref: [[.claude/rules/testing.md#R3]]

## frontend-gap

### TEST10: frontend-gap-tracked-issue-30
rule: no automated test coverage for `src/webapp/app_streamlit_v2.py` or `app_streamlit_legacy.py`
scope_missing: jurisdiction multi-select, character counter, domain rendering, verdict framing, verify-view expander
status: intentional backlog (issue #30), not oversight — no Streamlit runner or Playwright suite in repo; `/webapp-testing` provides manual/live Playwright, not automated regression

## conventions

### TEST11: no-pytest-asyncio-marker
rule: async tests use `asyncio.run(...)` inside regular (non-`async def`) test function; do NOT use `@pytest.mark.asyncio`
because: `pytest-asyncio` not installed
xref: [[.claude/rules/testing.md#T1]] [[LIB-STACK#S4]]

### TEST12: mock-httpx-via-MockTransport
rule: mock `httpx` via `httpx.MockTransport` patched into `httpx.AsyncClient.__init__` with `monkeypatch`; do NOT use `respx`
because: `respx` not installed
xref: [[.claude/rules/testing.md#T6]]

### TEST13: mock-llm-never-call-real
rule: mock LLM client with `unittest.mock`/hand-written fakes returning configurable payloads
forbidden: calling a real LocalAI endpoint in tests

### TEST14: in-memory-sqlite-with-dep-override
rule: use in-memory SQLite for database isolation; override `get_db` via `app.dependency_overrides` for endpoint tests

### TEST15: iterate-literals-via-get_args
rule: iterate Literal values via `typing.get_args()`, NOT hardcoded lists
xref: [[.claude/rules/testing.md#R3]]
