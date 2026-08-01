# code-style — Python + JS style + commit prefixes
loads: on-trigger
scope: project
xref: [[.claude/rules/testing.md]] [[.claude/CLAUDE.md]]

## python

### PY1: indentation
rule: 4 spaces; match existing file

### PY2: type hints
rule: type hints on all function signatures

### PY3: schema shapes
rule: Pydantic models for all API request/response shapes; dataclasses for internal value objects (e.g., `RulePattern`, `ValidationResult`)

### PY4: import order
rule: `__future__`, stdlib, third-party, local

### PY5: async I/O
rule: async functions for all I/O (HTTP, database)

### PY6: future annotations
rule: `from __future__ import annotations` in all modules

## javascript

### JS1: indentation
rule: 4 spaces

### JS2: no frameworks
rule: vanilla JS only; no frameworks or transpilation

### JS3: DOM access
rule: DOM via `document.getElementById` / `querySelector`

### JS4: global handlers
rule: global functions exposed via `window.*` for inline event handlers

## commit-messages

### CM1: prefixes
rule: use `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `style:`, `chore:`
because: `chore:` covers Conventional-Commits build/tooling/governance-artifact changes (e.g., manifest regen, dependency bumps, CI config) that do not fit the other prefixes; widened 2026-07-31 after P9 grumpy finding on commit b5f2034 (`chore(governance): regen manifest`) surfaced the gap

### CM2: subject length
rule: subject line under 72 characters

### CM3: issue refs
rule: reference issue numbers when applicable
