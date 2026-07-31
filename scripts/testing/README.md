# scripts/testing

Compact pytest wrappers for fast agent-driven verification. The goal is that
a Critic agent (or a human) can confirm a specific scope of the test suite is
green in a few hundred tokens rather than tens of thousands.

## Files

| File | Purpose |
|------|---------|
| `verify.sh` | Scoped pytest runner. Takes a scope name, runs the mapped subset, prints a compact PASS/FAIL summary. |
| `pytest-summary.py` | Reads raw pytest output (stdin or `--input`) and emits the compact summary format. `verify.sh` calls this internally, but it can also be piped directly. |
| `tests-for.py` | Maps a changed file or directory to the pytest node IDs it likely affects. Uses a static map with an import-grep fallback. |
| `tests/` | Structural unit tests for the three scripts above. Run with pytest. |

## Quick examples

Run the full suite and get a one-line result:

```
scripts/testing/verify.sh full
# PASS: 777 tests in 12.34s
```

Verify a narrow slice after touching the verify-view expander:

```
scripts/testing/verify.sh verify-view
# PASS: 12 tests in 1.42s
```

Discover which tests to run after editing a source file:

```
scripts/testing/tests-for.py src/backend/app/services/rules.py
# tests/test_rules.py
# tests/test_enhancements.py
# tests/test_all.py
# tests/test_irp.py
# tests/test_analyzer.py
# tests/test_audit_phase1_fixes.py
```

Compose the two:

```
scripts/testing/tests-for.py src/backend/app/services/rules.py \
    | xargs -I {} scripts/testing/verify.sh full
```

For most agent workflows the right pattern is:

1. `tests-for.py <changed_file>` to discover impacted tests.
2. Pick the closest named scope in `verify.sh --scopes` (or fall back to `full`).
3. Run `verify.sh <scope>` and read the compact result.

## Scope list

Run `verify.sh --scopes` for the authoritative list. Current scopes:

| Scope | Covers |
|-------|--------|
| `full` | Every test in `src/backend/tests/`. |
| `verify-view` | `test_audit_phase1_fixes.py::TestGap007VerifyView`, `TestDrift2VerifyViewSplitPane`. |
| `watchlist` | `test_watchlist_merge.py` plus watchlist classes across `test_main_endpoints.py` and `test_database_and_main_coverage.py`. |
| `audit-fixes` | Entire `test_audit_phase1_fixes.py`. |
| `regressions` | `test_regressions_pr34.py`. |
| `analyzer` | `test_analyzer.py`, `test_irp.py`. |
| `rules` | `test_rules.py`, `test_enhancements.py`. |
| `services` | `test_services.py`. |
| `endpoints` | `test_main_endpoints.py`, `test_database_and_main_coverage.py`. |
| `inference` | `test_inference.py`, `test_context.py`. |
| `legal-kb` | `test_legal_kb.py`. |
| `ingest` | `test_ingest.py`, `test_prompts.py`, `test_llm_failure.py`. |
| `snapshots` | `test_snapshots_and_diffs.py`. |
| `validation` | `test_validation.py`. |
| `smoke` | `test_all.py`. |
| `simplification` | Shell-native assertions for `simplify_finding_for_context()` — headless, no backend required. Mirrors `tests/test_child_context_simplification.py`. |
| `smoke-live` | Live HTTP smoke tests via curl+jq against running backend. Mirrors `tests/test_api_endpoints.py`. |

## Output format spec

Success:

```
PASS: <N> tests in <X>s
```

Failure:

```
FAIL: <F> failed / <P> passed
<node_id_1> :: <one-line reason>
<node_id_2> :: <one-line reason>
```

Collection error:

```
ERROR: <count> collection error(s)
<node_id> :: <reason>
```

Exit codes: `0` pass, `1` failures, `2` collection or parse error, `3` unknown
scope.

## Debug

Set `VERIFY_DEBUG=1` to have `verify.sh` dump the raw pytest log to stderr
after printing the compact summary. Useful when the summarizer classifies
something oddly.

## Self-tests

The scripts have their own tiny suite under `tests/`. Run:

```
python -m pytest scripts/testing/tests/ -q
```

These use synthetic pytest output and static-map assertions; they do not
touch the real backend test suite.

## Shell-native scripts

Two scripts bypass pytest entirely and produce the same `PASS/FAIL` output format:

| Script | Mirrors | Requires |
|--------|---------|---------|
| `simplification-check.sh` | `tests/test_child_context_simplification.py` | Python + webapp venv |
| `smoke-test.sh` | `tests/test_api_endpoints.py` | Running backend + jq |

The `.py` files are kept alongside as fallback. Differences:
- `.py` files use a copied function or TestClient mocks — faster to run offline.
- `.sh` files test the live source / live HTTP — catch integration regressions the mocks miss.

Run directly or via `verify.sh`:
```
scripts/testing/simplification-check.sh
scripts/testing/smoke-test.sh --base-url http://localhost:9000
scripts/testing/verify.sh simplification
scripts/testing/verify.sh smoke-live
```
