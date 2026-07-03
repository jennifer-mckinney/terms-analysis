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
| Line coverage | >= 85% (current baseline: 98.06%) |
| Branch coverage | >= 75% |
| Core rule categories tested (~50 categories/64 patterns exist; not all require individual tests) | Yes |
| Validation penalty paths tested | Yes |
| LLM failure/fallback tested | Yes |
| API endpoint happy + error paths | Yes |

## 3-Rule Testing Policy (adopted PR #34)

Adopted from the categorical gap audit in `docs/reports/test-suite-audit-pr34.md`. All three rules exist to prevent the same class of bug: **schema-to-handler drift** — a Pydantic Literal changes, a handler-level allowlist doesn't, and a valid value silently fails validation (or worse, an invalid value silently passes). PR #34's four must-fix findings all shared this root cause.

Reference implementations for each rule live in `src/backend/tests/test_regressions_pr34.py`.

### Rule 1 — Schema-to-handler allowlist parity

Any handler-level allowlist (frozenset, set, list) that validates against a Pydantic `Literal` must be **derived** from `typing.get_args(TheLiteral)`, not hardcoded. Tests must assert equality between the handler allowlist and `get_args(Literal)`. This turns drift into an import-time failure — the handler cannot be inconsistent with the schema because it is generated from the schema.

**Reference implementation in `main.py`:**

```python
from typing import get_args
from app.schemas import ContextChip, Jurisdiction

_VALID_CHIPS: frozenset[str] = frozenset(get_args(ContextChip))
_VALID_JURISDICTIONS: frozenset[str] = frozenset(get_args(Jurisdiction))
```

**Reference test in `test_regressions_pr34.py`** (Category B):

```python
def test_main_valid_chips_matches_schema_literal():
    from app.main import _VALID_CHIPS
    from app.schemas import ContextChip
    assert _VALID_CHIPS == frozenset(get_args(ContextChip))
```

### Rule 2 — Cross-endpoint field parity

When a field is validated on `/analyze`, it must be validated the same way on `/analyze/url`, `/analyze/file`, and `/analyze/batch`. A parity test must iterate every value in the field's Literal and POST to every sibling endpoint asserting consistent accept/reject behavior.

**Reference test pattern in `test_regressions_pr34.py`** (Category A):

```python
@pytest.mark.parametrize("chip", get_args(ContextChip))
@pytest.mark.parametrize("endpoint", [
    "/analyze", "/analyze/url", "/analyze/file", "/analyze/batch"
])
def test_endpoints_accept_all_valid_chips(client, chip, endpoint, ...):
    # POST with the chip; assert consistent accept behavior across endpoints
    ...
```

### Rule 3 — Runtime enumeration over Literal values

Tests must use `typing.get_args()` to iterate Literal values, not hardcode a list. Hardcoded test lists drift; `get_args()` stays in sync automatically. If a new value is added to the Literal, existing parametrized tests automatically pick it up.

**Rejected pattern** (hardcoded, drifts):

```python
@pytest.mark.parametrize("chip", [
    "want_understand", "for_child", "for_care", "for_work", "just_curious"
])
def test_something(chip): ...
```

**Required pattern** (runtime enumeration, stays in sync):

```python
@pytest.mark.parametrize("chip", get_args(ContextChip))
def test_something(chip): ...
```

Reference implementations across every category in `test_regressions_pr34.py`.
