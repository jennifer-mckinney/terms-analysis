# Testing automation

Design notes for the `scripts/testing/` wrappers. Read this before adding a
new scope or changing the summary format.

## Why this exists

The backend pytest suite runs 777 tests. Verbose output is ~30k tokens when
piped to an agent for verification. That is expensive for a Critic agent
whose only job is to answer "did the change break anything." The wrappers
here strip pytest output to a few hundred tokens while preserving enough
detail (failed node ID plus one-line reason) to act on a real failure.

## Design principles

1. **Compact by default.** The primary output is one line on success, and one
   line per failure otherwise. No headers, no tracebacks, no timings per
   test.
2. **Static scope map, curated by hand.** Test-to-source mapping in Python
   is fragile if inferred at runtime. The scope table in `verify.sh` and the
   static map in `tests-for.py` are both explicit; adding a scope is a
   two-file edit and a docs update.
3. **Dogfood the summary.** `verify.sh` calls `pytest-summary.py`. Anyone can
   invoke `pytest-summary.py` directly on saved pytest output for retros.
4. **No test-logic changes.** The wrappers never edit tests. If a test needs
   fixing, that is a separate ask.
5. **No hardcoded personal paths.** `verify.sh` resolves the repo root via
   `git rev-parse --show-toplevel` with a script-directory fallback, so the
   scripts run identically in CI, worktrees, or fresh clones.

## Output format

Success:

```
PASS: <N> tests in <X>s
```

Failure:

```
FAIL: <F> failed / <P> passed
<node_id> :: <one-line reason>
```

Collection error:

```
ERROR: <count> collection error(s)
<node_id> :: <reason>
```

Exit codes: `0` all pass, `1` test failures, `2` collection or parse error,
`3` unknown scope name.

## Scope naming

Scope names are lowercase, hyphen-separated, and describe what the caller
cares about, not which files pytest visits. Preferred phrasing:

- Feature-facing: `verify-view`, `watchlist`, `inference`, `legal-kb`.
- Layer-facing when a feature scope does not exist: `analyzer`, `rules`,
  `services`, `endpoints`.
- Suite-facing: `regressions`, `audit-fixes`, `smoke`, `full`.

## Adding a new scope

1. Add a `case` branch in `scripts/testing/verify.sh`. Prefer class-level
   node IDs (`file.py::TestClass`) over freeform `-k` expressions; they are
   easier to audit and skip re-collection heuristics.
2. Update the scope table in `scripts/testing/README.md`.
3. Add a row to the scope table below.
4. Run `scripts/testing/verify.sh <new_scope>` and confirm the count matches
   what you expect. If it does not, the case entry is wrong.
5. If the new scope references a new source module, extend `STATIC_MAP` in
   `scripts/testing/tests-for.py` so `tests-for.py` can point future agents
   at it.

## Scope reference

| Scope | Pytest args (relative to `src/backend`) |
|-------|-----------------------------------------|
| `full` | `tests` |
| `verify-view` | `tests/test_audit_phase1_fixes.py::TestGap007VerifyView`, `tests/test_audit_phase1_fixes.py::TestDrift2VerifyViewSplitPane` |
| `watchlist` | `tests/test_watchlist_merge.py`, `tests/test_main_endpoints.py::TestListWatchlist`, `TestAddWatchlist`, `TestRemoveWatchlist`, `TestRefreshWatchlist`, `TestCreateWatchlistWithMergedFields`, `tests/test_database_and_main_coverage.py::TestWatchlistLoopAsync`, `TestRefreshWatchlistItemsWithData`, `TestLifespanWithWatchlist`, `tests/test_audit_phase1_fixes.py::TestLE003WatchlistLoopLogsErrors` |
| `audit-fixes` | `tests/test_audit_phase1_fixes.py` |
| `regressions` | `tests/test_regressions_pr34.py` |
| `analyzer` | `tests/test_analyzer.py`, `tests/test_irp.py` |
| `rules` | `tests/test_rules.py`, `tests/test_enhancements.py` |
| `services` | `tests/test_services.py` |
| `endpoints` | `tests/test_main_endpoints.py`, `tests/test_database_and_main_coverage.py` |
| `inference` | `tests/test_inference.py`, `tests/test_context.py` |
| `legal-kb` | `tests/test_legal_kb.py` |
| `ingest` | `tests/test_ingest.py`, `tests/test_prompts.py`, `tests/test_llm_failure.py` |
| `snapshots` | `tests/test_snapshots_and_diffs.py` |
| `validation` | `tests/test_validation.py` |
| `smoke` | `tests/test_all.py` |

## How `tests-for.py` chooses tests

The static map covers the app modules touched most often. It records, for
each source file, every test file that imports it directly (from a recursive
scan of `from app.X import Y` statements across `src/backend/tests/`). When
a caller passes a source path outside the static map, the script falls back
to grepping test files for import statements referencing that module and
returns the matches.

Directory inputs recurse and aggregate. Test files and directories under
`tests/` echo back unchanged.

## Self-tests

`scripts/testing/tests/` contains structural tests for the wrapper scripts.
They use synthetic pytest output for `pytest-summary.py` and assert the
static map for `tests-for.py`. Run them with:

```
python -m pytest scripts/testing/tests/ -q
```

The wrappers deliberately do not import project code, so their tests do not
need the backend virtualenv.

## Not in scope

- Coverage reporting. Use `pytest --cov` for that.
- Watch mode or auto-rerun. Out of charter.
- Live test discovery beyond the static map. If a scope needs to be dynamic,
  add a first-class scope entry.
