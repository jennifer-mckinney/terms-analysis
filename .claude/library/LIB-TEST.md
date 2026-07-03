# LIB-TEST: Test Coverage Status

> **Status (2026-07-03):** rewritten — the previous version of this file was a pre-implementation gap analysis describing a 5-test/~5-8% coverage state and a non-existent `lm_studio.py` module. The backend test suite has since grown to 211 tests across the modules that file identified as gaps. Kept here as the current, accurate picture; see git history for the original planning document if useful.

## Current State (211 tests, `src/backend/tests/`)

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

Run via `/test-suite` or `cd src/backend && python -m pytest -v` (must activate `.venv` first — `source .venv/bin/activate` — or dependencies like `httpx`/`playwright` resolve to the wrong Python and imports fail with unrelated-looking errors).

## Known Remaining Gap: Frontend (tracked as issue #30)

No automated test coverage exists for:
- `src/webapp/app.js` — `setupJurisdictionBulkActions()`, `setupDocumentTextCounter()`, `escapeHtml()`-dependent rendering paths, theme toggling
- `src/webapp/app_streamlit.py` — equivalent Streamlit-side logic

No JS unit-test runner (vitest/jest) or Playwright test suite currently exists in the repo; `/webapp-testing` provides manual/live Playwright verification but isn't part of the automated regression suite. This is an intentional backlog item, not an oversight — see issue #30 for the decision to scope it deliberately rather than bolt on a partial harness.

## Conventions (see also `.claude/rules/testing.md`)

- Async test functions use plain `asyncio.run(...)` inside a regular (non-`async def`) test function — **not** `@pytest.mark.asyncio`, since `pytest-asyncio` is not installed in this project's `.venv`. Follow the existing pattern in `test_legal_kb.py`/`test_ingest.py` rather than adding the marker.
- Mock `httpx` via `httpx.MockTransport` (patched into `httpx.AsyncClient.__init__` with `monkeypatch`) rather than `respx`, which also isn't installed — see `test_ingest.py`'s `_patch_transport()` helper for the pattern.
- Mock the LLM client with `unittest.mock`/hand-written fakes returning configurable payloads — never call a real LocalAI endpoint in tests.
- Use in-memory SQLite for database isolation; override `get_db` via `app.dependency_overrides` for endpoint tests.
