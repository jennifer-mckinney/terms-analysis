#!/usr/bin/env bash
# verify.sh - Scoped pytest runner with compact structured output.
#
# Usage:
#     scripts/testing/verify.sh <scope>
#
# Scopes:
#     full             Every test in src/backend/tests/ (777 tests).
#     verify-view      Verify-view (GAP-007) + verify-view split-pane drift tests.
#     watchlist        Watchlist merge, watchlist endpoints, watchlist loop, refresh.
#     audit-fixes      Every class in test_audit_phase1_fixes.py.
#     regressions      PR34 regression suite (test_regressions_pr34.py).
#     analyzer         test_analyzer.py + test_irp.py (analyzer + IRP scoring).
#     rules            test_rules.py + test_enhancements.py (rule engine surface).
#     services         test_services.py (analyzer, embedding, ingest, localai helpers).
#     endpoints        test_main_endpoints.py + test_database_and_main_coverage.py.
#     inference        test_inference.py + test_context.py (POST /infer + context chips).
#     legal-kb         test_legal_kb.py (legal knowledge base RAG surface).
#     ingest           test_ingest.py + test_prompts.py + test_llm_failure.py.
#     snapshots        test_snapshots_and_diffs.py.
#     validation       test_validation.py.
#     smoke            test_all.py only (broad smoke suite).
#     simplification   Shell assertions for simplify_finding_for_context() (headless, no backend).
#     smoke-live       Live HTTP smoke tests via curl+jq (requires backend running).
#
# Exit codes:
#     0    All tests pass.
#     1    One or more test failures.
#     2    Collection error or unparseable output.
#     3    Unknown scope.
#
# Output format:
#     PASS: N tests in Xs
#   or
#     FAIL: F failed / P passed
#     <node_id> :: <one-line reason>
#     ...
#
# The runner shells into src/backend so pytest picks up the local pytest.ini
# (pythonpath = .). Full pytest logs go to a temp file surfaced on failure via
# stderr if VERIFY_DEBUG=1.

set -u

# Resolve repo root without assuming a fixed absolute path.
if command -v git >/dev/null 2>&1 && REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"; then
    :
else
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
fi

BACKEND_DIR="${REPO_ROOT}/src/backend"
SUMMARIZER="${REPO_ROOT}/scripts/testing/pytest-summary.py"
TESTS_DIR="tests"

if [ ! -d "${BACKEND_DIR}" ]; then
    echo "ERROR: backend dir not found: ${BACKEND_DIR}" >&2
    exit 2
fi

if [ "$#" -lt 1 ]; then
    echo "usage: verify.sh <scope>" >&2
    echo "run 'verify.sh --scopes' for the scope list" >&2
    exit 3
fi

scope="$1"

if [ "${scope}" = "--scopes" ] || [ "${scope}" = "-l" ]; then
    grep -E "^#     [a-z-]+ " "${BASH_SOURCE[0]}" | sed 's/^#     /  /'
    exit 0
fi

# Resolve scope -> pytest arg list. Args are relative to $BACKEND_DIR.
args=()
# NOTE: scopes are hardcoded here. Do NOT let a caller-supplied scope name reach pytest args as an unquoted or interpolated string.
# If dynamic scopes are ever needed, wrap in a strict whitelist before splatting into pytest.
# Reviewer P9 (grumpy F5) command injection guard rail.
case "${scope}" in
    full)
        args=("${TESTS_DIR}")
        ;;
    verify-view)
        args=(
            "${TESTS_DIR}/test_audit_phase1_fixes.py::TestGap007VerifyView"
            "${TESTS_DIR}/test_audit_phase1_fixes.py::TestDrift2VerifyViewSplitPane"
        )
        ;;
    watchlist)
        args=(
            "${TESTS_DIR}/test_watchlist_merge.py"
            "${TESTS_DIR}/test_main_endpoints.py::TestListWatchlist"
            "${TESTS_DIR}/test_main_endpoints.py::TestAddWatchlist"
            "${TESTS_DIR}/test_main_endpoints.py::TestRemoveWatchlist"
            "${TESTS_DIR}/test_main_endpoints.py::TestRefreshWatchlist"
            "${TESTS_DIR}/test_main_endpoints.py::TestCreateWatchlistWithMergedFields"
            "${TESTS_DIR}/test_database_and_main_coverage.py::TestWatchlistLoopAsync"
            "${TESTS_DIR}/test_database_and_main_coverage.py::TestRefreshWatchlistItemsWithData"
            "${TESTS_DIR}/test_database_and_main_coverage.py::TestLifespanWithWatchlist"
            "${TESTS_DIR}/test_audit_phase1_fixes.py::TestLE003WatchlistLoopLogsErrors"
        )
        ;;
    audit-fixes)
        args=("${TESTS_DIR}/test_audit_phase1_fixes.py")
        ;;
    regressions)
        args=("${TESTS_DIR}/test_regressions_pr34.py")
        ;;
    analyzer)
        args=(
            "${TESTS_DIR}/test_analyzer.py"
            "${TESTS_DIR}/test_irp.py"
        )
        ;;
    rules)
        args=(
            "${TESTS_DIR}/test_rules.py"
            "${TESTS_DIR}/test_enhancements.py"
        )
        ;;
    services)
        args=("${TESTS_DIR}/test_services.py")
        ;;
    endpoints)
        args=(
            "${TESTS_DIR}/test_main_endpoints.py"
            "${TESTS_DIR}/test_database_and_main_coverage.py"
        )
        ;;
    inference)
        args=(
            "${TESTS_DIR}/test_inference.py"
            "${TESTS_DIR}/test_context.py"
        )
        ;;
    legal-kb)
        args=("${TESTS_DIR}/test_legal_kb.py")
        ;;
    ingest)
        args=(
            "${TESTS_DIR}/test_ingest.py"
            "${TESTS_DIR}/test_prompts.py"
            "${TESTS_DIR}/test_llm_failure.py"
        )
        ;;
    snapshots)
        args=("${TESTS_DIR}/test_snapshots_and_diffs.py")
        ;;
    validation)
        args=("${TESTS_DIR}/test_validation.py")
        ;;
    smoke)
        args=("${TESTS_DIR}/test_all.py")
        ;;
    simplification)
        exec "${REPO_ROOT}/scripts/testing/simplification-check.sh" "${@:2}"
        ;;
    smoke-live)
        exec "${REPO_ROOT}/scripts/testing/smoke-test.sh" "${@:2}"
        ;;
    *)
        echo "ERROR: unknown scope '${scope}'" >&2
        echo "run 'verify.sh --scopes' for the scope list" >&2
        exit 3
        ;;
esac

# Prefer the project venv python if present. Fall back to whatever's on PATH.
PY="python3"
if [ -x "${REPO_ROOT}/venv/bin/python" ]; then
    PY="${REPO_ROOT}/venv/bin/python"
fi

LOG_FILE="$(mktemp -t verify-sh.XXXXXX)"
trap 'rm -f "${LOG_FILE}"' EXIT

# Run pytest quietly with line-tracebacks (compact) and short summary always on.
# stdout+stderr both go to LOG_FILE so the summarizer sees everything.
(
    cd "${BACKEND_DIR}" && \
    "${PY}" -m pytest -q --no-header --tb=line -rfE --disable-warnings "${args[@]}"
) >"${LOG_FILE}" 2>&1
pytest_exit=$?

# Summarize.
summary_output="$("${PY}" "${SUMMARIZER}" --input "${LOG_FILE}")"
summary_exit=$?

echo "${summary_output}"

# Debug hatch: dump raw log to stderr when requested.
if [ "${VERIFY_DEBUG:-0}" = "1" ]; then
    echo "--- verify.sh raw log (VERIFY_DEBUG=1) ---" >&2
    cat "${LOG_FILE}" >&2
fi

# If summarizer detected a real failure or parse error, honor its exit code.
# Otherwise fall back to pytest's own exit code so unusual pytest exits (like
# exit 5 = no tests collected) still surface as non-zero.
if [ "${summary_exit}" -ne 0 ]; then
    exit "${summary_exit}"
fi

if [ "${pytest_exit}" -ne 0 ]; then
    # Summarizer said PASS but pytest exited non-zero. Treat as parse error.
    echo "ERROR: pytest exited ${pytest_exit} but summary parsed as pass" >&2
    exit 2
fi

exit 0
