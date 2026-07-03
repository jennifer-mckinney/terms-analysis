---
name: write-tests
description: Guided workflow for writing comprehensive tests for a backend module. Use when asked to "write tests for X", "add test coverage for X", "test the X service", or when improving test coverage for a specific module. Accepts a module name as argument.
allowed-tools: Read, Write, Edit, Bash, Grep, Glob
---

# Write Tests Workflow

## Phase 1: Understand the Target

1. **Identify the module** from `$ARGUMENTS` (e.g., "rules", "validation", "analyzer", "ingest", "localai", "diffing", "prompts", "schemas", "config", "api")
2. **Read the source file**: `src/backend/app/services/$ARGUMENTS.py` (or `app/$ARGUMENTS.py` for schemas/config, `app/main.py` for api)
3. **Read existing tests**: check `src/backend/tests/test_$ARGUMENTS.py` if it exists
4. **Read the coverage gap analysis**: @.claude/library/LIB-TEST.md — find the module's section

## Phase 2: Plan Test Cases

For each public function in the module, plan:

| Function | Happy Path | Edge Cases | Error Cases |
|----------|-----------|------------|-------------|
| (fill in) | (fill in) | (fill in) | (fill in) |

Use `@pytest.mark.parametrize` when a function has 3+ test scenarios.

## Phase 3: Write Tests

### File Structure
```python
from __future__ import annotations

import pytest
# ... imports

# === Fixtures ===

# === Tests for function_name ===

class TestFunctionName:
    def test_happy_path(self):
        ...
    def test_edge_case(self):
        ...
    @pytest.mark.parametrize("input,expected", [...])
    def test_variations(self, input, expected):
        ...
```

### Rules
- **IMPORTANT**: Use `from __future__ import annotations` in every test file
- **IMPORTANT**: Mock external dependencies (LocalAI, httpx, database) — never call real services
- **IMPORTANT**: Use `asyncio.run(...)` inside a regular (non-`async def`) test function. Do NOT use `@pytest.mark.asyncio` — see @.claude/rules/testing.md T1 for why (marker silently no-ops as PytestUnknownMarkWarning).
- Use descriptive test names: `test_<function>_<scenario>`
- One assertion per test when possible
- Use factories/fixtures from conftest.py for Finding, Evidence, etc.
- Check `conftest.py` exists — if not, create it first with shared fixtures

### Fixture Patterns
```python
# conftest.py essentials:
@pytest.fixture
def sample_finding():
    return Finding(category="Sale/Share", severity="High", confidence=0.85,
                   excerpt="We may share...", explanation="...",
                   jurisdictions=["US-CA"],
                   evidence=Evidence(line_start=1, line_end=3, legal_basis=["CCPA"]))

@pytest.fixture
def sample_policy_text():
    return "We may sell or share your personal information with third parties..."
```

## Phase 4: Verify

1. Run the new tests: `cd src/backend && python -m pytest tests/test_$ARGUMENTS.py -v`
2. If failures, fix them immediately
3. Run full suite to check for regressions
4. Report coverage delta

## Arguments
- `$ARGUMENTS`: module name (e.g., "rules", "validation", "analyzer")
- If no argument given, read @.claude/library/LIB-TEST.md and pick the highest-priority untested module
