#!/usr/bin/env bash
# simplification-check.sh — Shell-native assertions for simplify_finding_for_context().
#
# Mirrors tests/test_child_context_simplification.py (kept alongside for comparison).
# Unlike the .py counterpart (tests a copied function), this tests the live source
# in src/webapp/app_streamlit_v2.py with streamlit stubbed for headless execution.
#
# Usage:
#     scripts/testing/simplification-check.sh
#
# Output (matches verify.sh / pytest-summary.py format):
#     PASS: N tests in Xs
#   or
#     FAIL: F failed / P passed
#     <test_name> :: <reason>
#
# Exit codes: 0=all pass  1=failures  2=runtime / import error

set -u

if command -v git >/dev/null 2>&1 && REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"; then
    :
else
    REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fi

PY="python3"
if [ -x "${REPO_ROOT}/venv/bin/python" ]; then
    PY="${REPO_ROOT}/venv/bin/python"
elif [ -x "${REPO_ROOT}/src/backend/.venv/bin/python" ]; then
    PY="${REPO_ROOT}/src/backend/.venv/bin/python"
fi

WEBAPP_DIR="${REPO_ROOT}/src/webapp"

WEBAPP_DIR="${WEBAPP_DIR}" "${PY}" - <<'PYEOF'
from __future__ import annotations
import os, sys, time, types
import unittest.mock as mock

# Stub streamlit before import so the module loads in headless mode.
_st = types.ModuleType("streamlit")
for _attr in [
    "set_page_config", "title", "sidebar", "columns", "write", "markdown",
    "error", "warning", "info", "success", "spinner", "button", "selectbox",
    "multiselect", "text_area", "file_uploader", "text_input", "expander",
    "container", "empty", "dataframe", "json", "subheader", "header",
    "caption", "divider", "tabs", "stop", "rerun", "cache_data",
    "cache_resource", "secrets", "query_params",
]:
    setattr(_st, _attr, mock.MagicMock())
_st.session_state = {}
sys.modules["streamlit"] = _st

sys.path.insert(0, os.environ["WEBAPP_DIR"])

try:
    from app_streamlit_v2 import simplify_finding_for_context
except Exception as e:
    print(f"ERROR: could not import simplify_finding_for_context — {e}")
    sys.exit(2)

tests_run = 0
tests_failed = 0
failures: list[tuple[str, str]] = []
t0 = time.time()


def run_test(name: str, finding: dict, context: list[str], checks: list) -> None:
    global tests_run, tests_failed
    tests_run += 1
    try:
        result = simplify_finding_for_context(finding, context)
        for desc, cond in checks:
            if not cond(result):
                tests_failed += 1
                failures.append((name, f"ASSERT FAILED: {desc}"))
                return
    except Exception as exc:
        tests_failed += 1
        failures.append((name, f"EXCEPTION: {exc}"))


# ── Mirror of tests/test_child_context_simplification.py ──────────────────────

run_test(
    "test_coppa_translation",
    {"explanation": "Special protections required for children's personal information under COPPA (under 13) and FERPA (education records).", "category": "Data Collection"},
    ["for_child"],
    [
        ("'law that says websites have to be extra careful' in explanation", lambda r: "law that says websites have to be extra careful" in r["explanation"]),
        ("'kids under 13' in explanation", lambda r: "kids under 13" in r["explanation"]),
        ("'COPPA' not in explanation", lambda r: "COPPA" not in r["explanation"]),
        ("'FERPA' not in explanation", lambda r: "FERPA" not in r["explanation"]),
    ],
)

run_test(
    "test_ai_ml_training_translation",
    {"explanation": "Using user data to train AI/ML models requires clear disclosure and in many jurisdictions an opt-out right.", "category": "AI/ML"},
    ["for_child"],
    [
        ("'teach its AI system' in explanation", lambda r: "teach its AI system" in r["explanation"]),
        ("'tell you if they do this' in explanation", lambda r: "tell you if they do this" in r["explanation"]),
        ("'AI/ML' not in explanation", lambda r: "AI/ML" not in r["explanation"]),
    ],
)

run_test(
    "test_no_simplification_without_context",
    {"explanation": "Special protections required for children's personal information under COPPA (under 13) and FERPA (education records).", "category": "Data Collection"},
    ["want_understand"],
    [
        ("explanation unchanged when for_child not in context", lambda r: r["explanation"] == "Special protections required for children's personal information under COPPA (under 13) and FERPA (education records)."),
    ],
)

run_test(
    "test_no_simplification_with_empty_context",
    {"explanation": "Special protections required for children's personal information under COPPA (under 13) and FERPA (education records).", "category": "Data Collection"},
    [],
    [
        ("explanation unchanged when context is empty", lambda r: r["explanation"] == "Special protections required for children's personal information under COPPA (under 13) and FERPA (education records)."),
    ],
)

run_test(
    "test_multiple_replacements",
    {"explanation": "Children's data requires special protections and disclosures. Using user data to train AI/ML models requires clear disclosure.", "category": "Data Collection"},
    ["for_child"],
    [
        ("'lock' in explanation (children's data replacement)", lambda r: "lock" in r["explanation"]),
        ("'AI system' in explanation (ML replacement)", lambda r: "AI system" in r["explanation"]),
    ],
)

run_test(
    "test_case_insensitive_matching",
    {"explanation": "USING USER DATA TO TRAIN AI/ML MODELS REQUIRES CLEAR DISCLOSURE.", "category": "AI/ML"},
    ["for_child"],
    [
        ("'AI/ML' not in explanation.upper()", lambda r: "AI/ML" not in r["explanation"].upper()),
        ("'teach' in explanation.lower()", lambda r: "teach" in r["explanation"].lower()),
    ],
)

run_test(
    "test_deletion_right_translation",
    {"explanation": "Right to deletion may be limited or restricted.", "category": "Privacy Rights"},
    ["for_child"],
    [
        ("'might not be able to ask them to delete' in explanation", lambda r: "might not be able to ask them to delete" in r["explanation"]),
    ],
)

run_test(
    "test_marketing_tracking_translation",
    {"explanation": "Using user data for marketing purposes is permitted.", "category": "Data Use"},
    ["for_child"],
    [
        ("'watches what you do' in explanation", lambda r: "watches what you do" in r["explanation"]),
        ("'ads' in explanation", lambda r: "ads" in r["explanation"]),
    ],
)

run_test(
    "test_data_sharing_translation",
    {"explanation": "Personal data is shared to third parties for marketing purposes.", "category": "Data Sharing"},
    ["for_child"],
    [
        ("'shares your information' in explanation", lambda r: "shares your information" in r["explanation"]),
        ("'other companies' in explanation", lambda r: "other companies" in r["explanation"]),
        ("'ads too' in explanation", lambda r: "ads too" in r["explanation"]),
    ],
)

run_test(
    "test_biometric_translation",
    {"explanation": "Facial recognition data collection is permitted.", "category": "Biometric"},
    ["for_child"],
    [
        ("'recognize your face' in explanation", lambda r: "recognize your face" in r["explanation"]),
        ("'facial recognition' not in explanation.lower()", lambda r: "facial recognition" not in r["explanation"].lower()),
    ],
)

run_test(
    "test_location_tracking_translation",
    {"explanation": "Location data is collected and tracked.", "category": "Location"},
    ["for_child"],
    [
        ("'see where you are' in explanation", lambda r: "see where you are" in r["explanation"]),
    ],
)

# ── Shell-only additions (not in .py counterpart) ──────────────────────────────

run_test(
    "test_xss_html_escaped_before_simplification",
    {"explanation": "<script>alert('xss')</script> Using user data for marketing purposes.", "category": "Data Use"},
    ["for_child"],
    [
        ("raw <script> not in output (CRITICAL-3 defense-in-depth)", lambda r: "<script>" not in r["explanation"]),
    ],
)

run_test(
    "test_null_explanation_safe",
    {"explanation": None, "category": "Data Use"},
    ["for_child"],
    [
        ("None explanation does not raise — returns dict with explanation key", lambda r: "explanation" in r),
    ],
)

run_test(
    "test_unknown_jargon_passthrough",
    {"explanation": "This service complies with applicable law.", "category": "Other"},
    ["for_child"],
    [
        ("non-matching explanation passes through unchanged", lambda r: "complies with applicable law" in r["explanation"]),
    ],
)

# ── Output ─────────────────────────────────────────────────────────────────────

elapsed = time.time() - t0
passed = tests_run - tests_failed

if tests_failed == 0:
    print(f"PASS: {tests_run} tests in {elapsed:.2f}s")
    sys.exit(0)
else:
    print(f"FAIL: {tests_failed} failed / {passed} passed")
    for name, reason in failures:
        print(f"{name} :: {reason}")
    sys.exit(1)
PYEOF
