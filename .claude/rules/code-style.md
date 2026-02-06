# Code Style

## Python (Backend)

- Follow existing indentation: 4 spaces
- Use type hints on all function signatures
- Pydantic models for all API request/response shapes
- Dataclasses for internal value objects (e.g., `RulePattern`, `ValidationResult`)
- Import order: `__future__`, stdlib, third-party, local
- Async functions for any I/O (HTTP, database)
- Use `from __future__ import annotations` in all modules

## JavaScript (Frontend)

- 4-space indentation
- Vanilla JS only — no frameworks or transpilation
- DOM manipulation via `document.getElementById` / `querySelector`
- Global functions exposed via `window.*` for inline event handlers

## Commit Messages

- Use conventional prefixes: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `style:`
- Keep subject line under 72 characters
- Reference issue numbers when applicable
