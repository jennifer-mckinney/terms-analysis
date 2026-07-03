#!/usr/bin/env bash
# smoke-test.sh — Live HTTP smoke tests against the running backend.
#
# Mirrors tests/test_api_endpoints.py (kept alongside for comparison).
# Unlike the .py counterpart (uses TestClient + mocks), this fires real HTTP
# requests against a running backend instance via curl + jq.
#
# Usage:
#     scripts/testing/smoke-test.sh [--base-url URL]
#
# Environment:
#     TERMS_API_BASE   Override backend URL (default: http://localhost:9000)
#
# Output (matches verify.sh / pytest-summary.py format):
#     PASS: N tests in Xs
#   or
#     FAIL: F failed / P passed
#     <test_name> :: <reason>
#
# Exit codes: 0=all pass  1=failures  2=preflight failure (backend down / jq missing)

set -u

BASE_URL="${TERMS_API_BASE:-http://localhost:9000}"

while [ "$#" -gt 0 ]; do
    case "$1" in
        --base-url) BASE_URL="$2"; shift 2 ;;
        *) echo "ERROR: unknown argument '$1'" >&2; exit 2 ;;
    esac
done

# Preflight: jq required
if ! command -v jq >/dev/null 2>&1; then
    echo "ERROR: jq not found — install jq (brew install jq) to run smoke tests"
    exit 2
fi

# Preflight: backend reachable
if ! curl -sf --max-time 3 "${BASE_URL}/health" >/dev/null 2>&1; then
    echo "ERROR: backend not reachable at ${BASE_URL} — start with ./run.sh"
    exit 2
fi

tests_run=0
tests_failed=0
failures=()

t0=$(python3 -c "import time; print(time.time())" 2>/dev/null || echo "0")

_pass() { tests_run=$((tests_run + 1)); }
_fail() {
    local name="$1" reason="$2"
    tests_run=$((tests_run + 1))
    tests_failed=$((tests_failed + 1))
    failures+=("${name} :: ${reason}")
}

# Post JSON body to path; sets HTTP_CODE, prints response body.
_post() {
    local path="$1" body="$2"
    HTTP_CODE="000"
    local tmp
    tmp=$(mktemp)
    HTTP_CODE=$(curl -s -o "${tmp}" -w "%{http_code}" -X POST "${BASE_URL}${path}" \
        -H "Content-Type: application/json" -d "${body}" --max-time 30 2>/dev/null)
    cat "${tmp}"
    rm -f "${tmp}"
}

# ── Test 1: /analyze quick mode — mirrors test_analyze_endpoint_with_mode_parameter
name="test_analyze_quick_mode"
resp=$(_post "/analyze" '{"text":"We sell your personal information to third parties.","jurisdictions":["US-CA"],"mode":"quick"}')
if [ "$HTTP_CODE" != "200" ]; then
    _fail "$name" "expected 200, got ${HTTP_CODE}"
elif ! echo "$resp" | jq -e '.analysis_mode == "quick"' >/dev/null 2>&1; then
    _fail "$name" "analysis_mode != quick: $(echo "$resp" | jq -r '.analysis_mode // "missing"')"
elif ! echo "$resp" | jq -e '.estimated_time | type == "number"' >/dev/null 2>&1; then
    _fail "$name" "estimated_time missing or not a number"
else
    _pass
fi

# ── Test 2: /analyze full mode — mirrors test_analyze_endpoint_full_mode
name="test_analyze_full_mode"
resp=$(_post "/analyze" '{"text":"We collect your browsing data for analytics purposes.","jurisdictions":["GDPR"],"mode":"full"}')
if [ "$HTTP_CODE" != "200" ]; then
    _fail "$name" "expected 200, got ${HTTP_CODE}"
elif ! echo "$resp" | jq -e '.analysis_mode == "full"' >/dev/null 2>&1; then
    _fail "$name" "analysis_mode != full"
else
    _pass
fi

# ── Test 3: /analyze default mode — mirrors test_analyze_endpoint_mode_default
name="test_analyze_mode_default"
resp=$(_post "/analyze" '{"text":"We process personal data according to GDPR requirements.","jurisdictions":["GDPR"]}')
if [ "$HTTP_CODE" != "200" ]; then
    _fail "$name" "expected 200, got ${HTTP_CODE}"
elif ! echo "$resp" | jq -e '.analysis_mode == "full"' >/dev/null 2>&1; then
    _fail "$name" "default analysis_mode should be full"
else
    _pass
fi

# ── Test 4: findings array present — mirrors test_findings_have_source_document_field
name="test_analyze_findings_array"
resp=$(_post "/analyze" '{"text":"We sell personal data to third parties.","jurisdictions":["US-CA"],"mode":"quick"}')
if [ "$HTTP_CODE" != "200" ]; then
    _fail "$name" "expected 200, got ${HTTP_CODE}"
elif ! echo "$resp" | jq -e '.findings | type == "array"' >/dev/null 2>&1; then
    _fail "$name" "findings field missing or not array"
else
    _pass
fi

# ── Test 5: /infer endpoint — mirrors SO8 in CLAUDE.md
name="test_infer_endpoint"
resp=$(_post "/infer" '{"url":"https://example.com/privacy-policy"}')
if [ "$HTTP_CODE" != "200" ]; then
    _fail "$name" "expected 200, got ${HTTP_CODE}"
elif ! echo "$resp" | jq -e 'has("doc_type") or has("jurisdiction") or has("tld")' >/dev/null 2>&1; then
    _fail "$name" "infer response missing doc_type/jurisdiction/tld"
else
    _pass
fi

# ── Test 6: invalid mode rejected 422 — mirrors test_batch_endpoint_exists error path
name="test_analyze_invalid_mode_422"
HTTP_CODE="000"
HTTP_CODE=$(curl -sf -o /dev/null -w "%{http_code}" -X POST "${BASE_URL}/analyze" \
    -H "Content-Type: application/json" -d '{"text":"test","mode":"banana"}' \
    --max-time 10 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "422" ]; then
    _pass
else
    _fail "$name" "expected 422 for invalid mode enum, got ${HTTP_CODE}"
fi

# ── Test 7: empty text rejected 400 or 422
name="test_analyze_empty_text_rejected"
HTTP_CODE="000"
HTTP_CODE=$(curl -sf -o /dev/null -w "%{http_code}" -X POST "${BASE_URL}/analyze" \
    -H "Content-Type: application/json" -d '{"text":"","jurisdictions":[]}' \
    --max-time 10 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "400" ] || [ "$HTTP_CODE" = "422" ]; then
    _pass
else
    _fail "$name" "expected 400/422 for empty text, got ${HTTP_CODE}"
fi

# ── Test 8: /analyze/batch endpoint exists — mirrors test_batch_endpoint_exists
name="test_batch_endpoint_exists"
HTTP_CODE="000"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE_URL}/analyze/batch" \
    -H "Content-Type: application/json" \
    -d '{"items":[{"url":"https://example.com/privacy","name":"P","doc_type":"Privacy Policy"}],"jurisdictions":["US-CA"],"mode":"full","detect_cross_references":true}' \
    --max-time 30 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "400" ] || [ "$HTTP_CODE" = "422" ] || [ "$HTTP_CODE" = "500" ]; then
    _pass
else
    _fail "$name" "unexpected status ${HTTP_CODE} from /analyze/batch"
fi

# ── Test 9: /health returns status field
name="test_health_status_field"
resp=$(curl -sf "${BASE_URL}/health" --max-time 5 2>/dev/null)
if [ -z "$resp" ]; then
    _fail "$name" "/health returned empty response"
elif ! echo "$resp" | jq -e '.status' >/dev/null 2>&1; then
    _fail "$name" "/health response missing .status field"
else
    _pass
fi

# ── Summary ────────────────────────────────────────────────────────────────────
t1=$(python3 -c "import time; print(time.time())" 2>/dev/null || echo "0")
elapsed=$(python3 -c "print(f'{float(\"${t1}\")-float(\"${t0}\"):.2f}s')" 2>/dev/null || echo "?s")
passed=$((tests_run - tests_failed))

if [ "$tests_failed" -eq 0 ]; then
    echo "PASS: ${tests_run} tests in ${elapsed}"
    exit 0
else
    echo "FAIL: ${tests_failed} failed / ${passed} passed"
    for line in "${failures[@]}"; do
        echo "${line}"
    done
    exit 1
fi
