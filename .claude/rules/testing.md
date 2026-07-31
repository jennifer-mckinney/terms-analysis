---
paths:
  - "src/backend/tests/**/*.py"
  - "src/webapp/tests/**/*.js"
---

# testing — pytest conventions + 3-rule schema-drift policy
loads: on-trigger
scope: project
xref: [[LIB-TEST]] [[LIB-STACK]] [[docs/reports/test-suite-audit-pr34.md]]

## pytest-conventions

### T1: no pytest-asyncio
rule: do not use `@pytest.mark.asyncio`
apply_when: any async function under test
alternative: call from a regular (non-`async def`) test via `asyncio.run(...)`
because: `pytest-asyncio` not installed in `src/backend/.venv`; marker silently no-ops as `PytestUnknownMarkWarning`
xref: [[test_legal_kb.py]] [[test_ingest.py]]

### T2: test location
rule: place tests in `src/backend/tests/` mirroring source structure

### T3: shared fixtures
rule: shared fixtures in `conftest.py` (db session, TestClient, Finding factory, mock LLM)

### T4: parametrize multi-case
rule: use `@pytest.mark.parametrize` for multi-case coverage (rule categories, grade boundaries)

### T5: mock LocalAI
rule: mock `services/localai.py::LocalAIClient` with `unittest.mock` / hand-written fakes; never call real LocalAI in tests

### T6: no respx
rule: do not use `respx`
alternative: patch `httpx.AsyncClient.__init__` with `monkeypatch` to inject `httpx.MockTransport`
because: `respx` not installed
xref: [[test_ingest.py#_patch_transport]]

### T7: in-memory sqlite
rule: use `sqlite:///:memory:` for database isolation

### T8: dependency override for endpoints
rule: use `app.dependency_overrides[get_db]` for API endpoint tests

### T9: test naming
rule: `test_<module>_<function>_<scenario>` (e.g., `test_rules_detect_findings_sale_share`)

## javascript-frontend

### JT1: runner + env
rule: vitest or jest with jsdom environment

### JT2: test location
rule: place tests in `src/webapp/tests/`

### JT3: mock fetch
rule: mock `fetch` for all API calls

### JT4: mock localStorage
rule: mock `localStorage` for theme persistence

## quality-gates

| metric | target |
|--------|--------|
| line coverage | >= 85% (baseline: 98.06%) |
| branch coverage | >= 75% |
| core rule categories tested | No — CRITICAL gap: only 2/50 categories individually tested; see docs/research/test-coverage-matrix.md |
| validation penalty paths | Yes |
| LLM failure/fallback | Yes |
| API endpoint happy + error | Yes |

## 3-rule-drift-policy
adopted: PR #34 gap audit
prevents: schema-to-handler drift (Pydantic Literal changes, handler-level allowlist doesn't, valid value silently fails or invalid value silently passes)
reference_impl: `src/backend/tests/test_regressions_pr34.py`

### R1: schema-to-handler allowlist parity
rule: any handler-level allowlist (frozenset/set/list) validating against a Pydantic Literal MUST be derived from `typing.get_args(TheLiteral)`, not hardcoded
test_must_assert: equality between handler allowlist and `get_args(Literal)`
because: makes drift an import-time failure; handler cannot diverge from schema because it is generated from it
reference_impl_prod:
```python
from typing import get_args
from app.schemas import ContextChip, Jurisdiction
_VALID_CHIPS: frozenset[str] = frozenset(get_args(ContextChip))
_VALID_JURISDICTIONS: frozenset[str] = frozenset(get_args(Jurisdiction))
```
reference_impl_test:
```python
def test_main_valid_chips_matches_schema_literal():
    from app.main import _VALID_CHIPS
    from typing import get_args; from app.schemas import ContextChip
    assert _VALID_CHIPS == frozenset(get_args(ContextChip))
```

### R2: cross-endpoint field parity
rule: a field validated on `/analyze` MUST be validated the same way on `/analyze/url`, `/analyze/file`, `/analyze/batch`
test_must_iterate: every Literal value AND every sibling endpoint
reference_impl:
```python
@pytest.mark.parametrize("chip", get_args(ContextChip))
@pytest.mark.parametrize("endpoint", ["/analyze", "/analyze/url", "/analyze/file", "/analyze/batch"])
def test_endpoints_accept_all_valid_chips(client, chip, endpoint, ...): ...
```

### R3: runtime enumeration over Literal
rule: tests MUST use `typing.get_args()` to iterate Literal values; MUST NOT hardcode the list
because: hardcoded lists drift; `get_args()` stays in sync automatically and picks up new values
rejected:
```python
@pytest.mark.parametrize("chip", ["want_understand", "for_child", "for_care", "for_work", "just_curious"])
```
required:
```python
@pytest.mark.parametrize("chip", get_args(ContextChip))
```
