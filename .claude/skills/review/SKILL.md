---
name: review
description: Review code changes for quality, conventions, and correctness. Use when asked to "review this", "check my changes", "review PR", or before committing to verify code quality. Also use proactively after writing significant code.
allowed-tools: Read, Bash, Grep, Glob
---

# Code Review

## Workflow

1. **Identify changes**
   ```bash
   git diff --stat
   git diff --name-only
   ```

2. **Read each changed file** and check against:

### Python Backend Checklist

| Check | Rule |
|-------|------|
| Type hints | All function signatures must have type hints |
| `from __future__ import annotations` | Required in every module |
| Import order | `__future__` → stdlib → third-party → local |
| Async I/O | Any HTTP/DB call must be async |
| Pydantic models | API request/response shapes use Pydantic |
| Error handling | LLM failures fall back to rule-only with reduced confidence |
| No external calls | All data stays local — only call local LM Studio |
| Confidence clamping | Rule confidence in [0.35, 0.95] |
| Security | No command injection, XSS, SQL injection risks |

### Test Code Checklist

| Check | Rule |
|-------|------|
| No real services | LM Studio, httpx, database are mocked |
| `@pytest.mark.asyncio` | Present on async test functions |
| Descriptive names | `test_<function>_<scenario>` pattern |
| Assertions | Clear, specific assertions — not just `assert result` |
| Edge cases | Empty input, boundary values, error paths covered |
| Fixtures | Shared fixtures in conftest.py, not duplicated |

### JavaScript Frontend Checklist

| Check | Rule |
|-------|------|
| Vanilla JS | No frameworks or transpilation |
| 4-space indent | Consistent indentation |
| `window.*` | Global functions exposed for inline handlers |
| XSS safety | No raw innerHTML with user input |

3. **Report findings** as:
   ```
   ## Review Summary
   | File | Issues | Severity |
   |------|--------|----------|

   ## Details
   ### file.py:line — Issue title
   Description and suggested fix
   ```

4. **Verdict**: APPROVE (no issues), APPROVE WITH COMMENTS (minor), or REQUEST CHANGES (blocking issues)

## Arguments
- `$ARGUMENTS`: optional file path or "staged" (review staged changes only)
- No arguments = review all uncommitted changes
