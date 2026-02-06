---
paths:
  - "src/backend/tests/**/*.py"
  - "src/webapp/tests/**/*.js"
---

# Testing Conventions

## Python Backend (pytest)

- Use `pytest` + `pytest-asyncio` for all backend tests
- Place tests in `src/backend/tests/` mirroring source structure
- Shared fixtures go in `conftest.py` (db session, TestClient, Finding factory, mock LLM)
- Use `@pytest.mark.asyncio` for async test functions
- Use `@pytest.mark.parametrize` for multi-case coverage (rule categories, grade boundaries)
- Mock LM Studio with `unittest.mock.AsyncMock` — never call real LLM in tests
- Mock httpx with `respx` or `monkeypatch` for URL fetch tests
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
| All 9 rule categories tested | Yes |
| Validation penalty paths tested | Yes |
| LLM failure/fallback tested | Yes |
| API endpoint happy + error paths | Yes |
