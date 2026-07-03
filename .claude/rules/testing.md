---
paths:
  - "src/backend/tests/**/*.py"
  - "src/webapp/tests/**/*.js"
---

# Testing Conventions

## Python Backend (pytest)

- Use `pytest` for all backend tests. **`pytest-asyncio` is NOT installed** in `src/backend/.venv` — do not add `@pytest.mark.asyncio`, it silently no-ops the test (`PytestUnknownMarkWarning`) rather than failing. For async functions under test, call them from a regular (non-`async def`) test via `asyncio.run(...)` — see `test_legal_kb.py`/`test_ingest.py` for the pattern.
- Place tests in `src/backend/tests/` mirroring source structure
- Shared fixtures go in `conftest.py` (db session, TestClient, Finding factory, mock LLM)
- Use `@pytest.mark.parametrize` for multi-case coverage (rule categories, grade boundaries)
- Mock LocalAI (`services/localai.py::LocalAIClient`) with `unittest.mock`/hand-written fakes — never call a real LocalAI endpoint in tests
- **`respx` is NOT installed** either — mock `httpx` by patching `httpx.AsyncClient.__init__` with `monkeypatch` to inject an `httpx.MockTransport`, per `test_ingest.py`'s `_patch_transport()` helper
- Use in-memory SQLite (`sqlite:///:memory:`) for database isolation
- Use `app.dependency_overrides[get_db]` for API endpoint tests
- Naming: `test_<module>_<function>_<scenario>` (e.g., `test_rules_detect_findings_sale_share`)

## JavaScript Frontend (vitest/jest)

- Use vitest or jest with jsdom environment
- Place tests in `src/webapp/tests/`
- Mock `fetch` for all API calls
- Mock `localStorage` for theme persistence

## Quality Gates

| Metric | Target |
|--------|--------|
| Line coverage | >= 85% |
| Branch coverage | >= 75% |
| Core rule categories tested (~50 categories/64 patterns exist; not all require individual tests) | Yes |
| Validation penalty paths tested | Yes |
| LLM failure/fallback tested | Yes |
| API endpoint happy + error paths | Yes |
