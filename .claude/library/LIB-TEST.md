# LIB-TEST: Test Coverage Status

> **Status (2026-07-03):** rewritten after PR #34. Baseline is now **702 tests, 98.06% line coverage** on `src/backend/`. Test policy formalized in `.claude/rules/testing.md` (3-rule policy: schema-to-handler parity, cross-endpoint parity, runtime enumeration over Literal values). Two audit reports at `docs/reports/test-suite-audit-pr34.md` (gap coverage) and `docs/reports/test-suite-quality-audit-pr34.md` (YELLOW quality verdict, pruning recommendations tracked as follow-up PR).

## Current baseline (702 tests, 98.06% coverage)

| File | Covers |
|------|--------|
| `test_all.py` | Broadest file: API endpoints (analyze/url/file/batch, analyses, rubric, exports incl. PDF-route-shadowing regression, reviews, watchlist CRUD), SSRF URL validation, schema/config boundary cases |
| `test_rules.py` | Rule pattern detection across categories, confidence formula, jurisdiction filtering |
| `test_enhancements.py` | Rubric scoring, completeness/action-readiness style computations |
| `test_ingest.py` | HTML/RTF extraction, SSRF-redirect regression tests (blocked-redirect rejected, allowed-redirect followed, redirect-loop capped) |
| `test_legal_kb.py` | Chunking, embedding/build/retrieve, jurisdiction filtering (incl. schema-code-mismatch regression), dimension-mismatch and corrupted-index graceful degradation, placeholder-status propagation, CLI indexing |
| `test_llm_failure.py` | LLM offline fallback, timeout returns `None`, rule-only fallback with reduced confidence |
| `test_prompts.py` | `legal_context` placeholder-warning propagation into the LLM prompt |
| `test_snapshots_and_diffs.py` | Snapshot create/list/detail, diff computation, policy-watch CRUD + manual snapshot trigger |
| `test_analyzer.py` | Analyzer orchestration, hybrid merge, IRP scoring path, action-readiness, domain grouping |
| `test_context.py` | Context chip weights, `resolve_context`, `apply_category_weights`, `verdict_headline`, `verdict_label` |
| `test_inference.py` | URL TLD detection, text signal detection, `@lru_cache` behavior, ReDoS canary |
| `test_irp.py` | IRP formula, seeded defaults, LLM parse, hybrid safeguard-max merge |
| `test_main_endpoints.py` | Per-endpoint validation, chip / jurisdiction allowlist enforcement, `/infer` endpoint |
| `test_database_and_main_coverage.py` | Coverage-fill for previously untested branches in `database.py` and `main.py` |
| `test_regressions_pr34.py` | **Categorical gap coverage backfilled after PR #34** (30 tests) — see next section |
| `test_services.py` | Cross-cutting service-layer wiring |
| `test_validation.py` | Hallucination guard, citation checker, boundary confidence values |

Run via `/test-suite` or `cd src/backend && python -m pytest -v` (must activate `.venv` first — `source .venv/bin/activate` — or dependencies like `httpx`/`playwright` resolve to the wrong Python and imports fail with unrelated-looking errors).

## Categorical regression coverage (`test_regressions_pr34.py`, 30 tests)

Backfilled after PR #34's four must-fix findings (all four had a shared root cause: cross-endpoint / schema-vs-handler drift). Tests are grouped by category letter, matching the audit brief in `docs/reports/test-suite-audit-pr34.md`.

- **A. Cross-endpoint field consistency** — same field validated the same way on `/analyze`, `/analyze/url`, `/analyze/file`, `/analyze/batch`. Iterates every value in the Literal via `typing.get_args()` and POSTs to every sibling endpoint.
- **B. Schema-`Literal` allowlist parity guards** — asserts `_VALID_CHIPS == frozenset(get_args(ContextChip))` and `_VALID_JURISDICTIONS == frozenset(get_args(Jurisdiction))` so drift fails at CI time.
- **C. URL-scheme XSS defense-in-depth** — rejects `javascript:`, `data:`, `vbscript:` scheme URLs on `/infer` and every URL-taking endpoint.
- **D. Malformed / oversized / unicode inputs** — empty bodies, oversize text, control characters, mixed-encoding payloads.
- **E. ReDoS canary on `inference.py`** — synthetic pathological input completes under a time budget; catches accidentally exponential regex changes.
- **F. Domain-grouping edge cases** — unknown category defaults to a known bucket rather than dropping the finding; empty `top_by_domain` renders without crash.
- **G. Sort stability** — `apply_category_weights` returns a stable order for equal-key findings; multi-select tie-breaking is deterministic.

Adopt the same category letters when adding future regression tests so audit traceability stays intact.

## Quality audit — YELLOW verdict, follow-up PR

`docs/reports/test-suite-quality-audit-pr34.md` flags the suite as YELLOW: coverage is high but has soft spots.

**Recommendations tracked for follow-up:**
- Parametrize ~55 rule-trigger tests that repeat the same shape with different regex payloads.
- Delete ~8 tautological assertions (e.g., asserting the mock returns what the mock was configured to return).
- Hoist common fixtures into `conftest.py` — the `_payload()` / `_result()` / `_finding()` builders currently duplicated across `test_regressions_pr34.py` and `test_main_endpoints.py` are the top candidates.
- Add explicit assertions for negative cases where the current test relies on "no exception raised" as the entire assertion surface.

None of these are blockers for PR #34 merge; they are quality-hygiene follow-ups.

## 3-rule testing policy (`.claude/rules/testing.md`)

Adopted from the PR #34 gap audit. All three rules exist to prevent the same class of bug: **schema-to-handler drift**.

- **Rule 1 — Schema-to-handler allowlist parity.** Any handler-level allowlist must be derived from `typing.get_args(TheLiteral)`, not hardcoded. Tests must assert equality between the handler allowlist and `get_args(Literal)`.
- **Rule 2 — Cross-endpoint field parity.** When a field is validated on `/analyze`, it must be validated the same way on every sibling endpoint. Parity tests iterate every Literal value and POST to every endpoint.
- **Rule 3 — Runtime enumeration over Literal values.** Tests must use `typing.get_args()` to iterate Literal values, not hardcode a list. Hardcoded lists drift; `get_args()` stays in sync automatically.

Reference implementations for each rule live in `test_regressions_pr34.py`.

## Known Remaining Gap: Frontend (tracked as issue #30)

No automated test coverage exists for:
- `src/webapp/app.js` — `setupJurisdictionBulkActions()`, `setupDocumentTextCounter()`, `escapeHtml()`-dependent rendering paths, theme toggling
- `src/webapp/app_streamlit_v2.py` — equivalent Streamlit-side logic (primary UI post-issue #19 redesign)

No JS unit-test runner (vitest/jest) or Playwright test suite currently exists in the repo; `/webapp-testing` provides manual/live Playwright verification but isn't part of the automated regression suite. This is an intentional backlog item, not an oversight — see issue #30 for the decision to scope it deliberately rather than bolt on a partial harness.

## Conventions (see also `.claude/rules/testing.md`)

- Async test functions use plain `asyncio.run(...)` inside a regular (non-`async def`) test function — **not** `@pytest.mark.asyncio`, since `pytest-asyncio` is not installed in this project's `.venv`. Follow the existing pattern in `test_legal_kb.py`/`test_ingest.py` rather than adding the marker.
- Mock `httpx` via `httpx.MockTransport` (patched into `httpx.AsyncClient.__init__` with `monkeypatch`) rather than `respx`, which also isn't installed — see `test_ingest.py`'s `_patch_transport()` helper for the pattern.
- Mock the LLM client with `unittest.mock`/hand-written fakes returning configurable payloads — never call a real LocalAI endpoint in tests.
- Use in-memory SQLite for database isolation; override `get_db` via `app.dependency_overrides` for endpoint tests.
- Iterate Literal values via `typing.get_args()`, not hardcoded lists — see Rule 3 above.
