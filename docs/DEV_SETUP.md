# Developer Setup

## After clone: install governance hooks

Run once after cloning:

```bash
scripts/install-hooks.sh
```

This copies `.githooks/pre-commit` into `.git/hooks/pre-commit`. The hook
enforces `.gitignore` governance invariants before every commit. CI enforces
the same invariants via `.github/workflows/gitignore-enforcement.yml`, so the
pre-commit hook is a fast local convenience, not the only line of defense.

## What patterns are protected

The following `.gitignore` entries are protected and cannot be removed
without a governance-tier PR:

- `ignore/`: local graveyard directory for scratch work that must never leak
- `.env`, `.env.local`: secret protection
- `.venv/`, `venv/`, `env/`: virtualenv trees
- `__pycache__/`, `*.pyc`, `*.db-journal`, `*.db`: Python and SQLite runtime
- `.pip-cache/`, `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/`: toolchain caches
- `node_modules/`: npm dependency tree
- `.DS_Store`: macOS metadata

The pre-commit hook also refuses to stage any file under `ignore/`, `.venv/`,
`venv/`, or `.pip-cache/`.

## Adding a new protected pattern

Changes to the protected list are governance-tier and require PR review. To
add a pattern, update **both** files in the same PR:

1. `.githooks/pre-commit` (`REQUIRED_GITIGNORE_PATTERNS` array)
2. `.github/workflows/gitignore-enforcement.yml` (both `REQUIRED` and
   `PROTECTED` arrays)

The two lists must stay in sync: the CI workflow is the source of truth
because it runs unconditionally on every PR.

## Compact test verification

For agent-driven verification and quick local checks, use the wrappers in
`scripts/testing/`. `scripts/testing/verify.sh <scope>` runs a named subset
of the pytest suite and prints a one-line `PASS: N tests in Xs` on success or
a compact `FAIL:` block with node IDs and one-line reasons on failure. Run
`scripts/testing/verify.sh --scopes` for the current scope list, or read
`docs/testing-automation.md` for design notes and instructions on adding a
new scope. `scripts/testing/tests-for.py <path>` maps a changed source file
to the test files most likely to exercise it.
