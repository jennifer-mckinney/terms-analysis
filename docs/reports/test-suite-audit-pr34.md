# Test Suite Audit — PR #34 Post-Mortem

**Author:** Claude Code (SDK audit agent)
**Branch:** `claude/issue-19-plain-language-redesign`
**Base commit under audit:** `2626e2b` (PR #34 must-fix pass)
**Total tests collected by pytest:** 635

## 1. Coverage inventory

### 1.1 Per-file counts

| Test file                                   | Tests | Style        |
|---------------------------------------------|:-----:|--------------|
| `tests/test_all.py`                         | 130   | integration  |
| `tests/test_services.py`                    | 114   | unit         |
| `tests/test_main_endpoints.py`              | 106   | integration  |
| `tests/test_inference.py`                   |  97   | unit         |
| `tests/test_context.py`                     |  43   | unit         |
| `tests/test_snapshots_and_diffs.py`         |  32   | integration  |
| `tests/test_database_and_main_coverage.py`  |  32   | integration  |
| `tests/test_enhancements.py`                |  22   | unit         |
| `tests/test_legal_kb.py`                    |  15   | unit         |
| `tests/test_validation.py`                  |  14   | unit         |
| `tests/test_irp.py`                         |  12   | unit         |
| `tests/test_prompts.py`                     |   5   | unit         |
| `tests/test_ingest.py`                      |   5   | unit         |
| `tests/test_analyzer.py`                    |   5   | unit         |
| `tests/test_llm_failure.py`                 |   2   | unit         |
| `tests/test_rules.py`                       |   1   | unit         |

### 1.2 Bucket totals (`app_client` presence heuristic)

| Bucket                          | Count |
|---------------------------------|:-----:|
| Unit (no HTTP client)           | 335   |
| Integration (uses `TestClient`) | 300   |
| End-to-end (real HTTP transport)|   0   |
| Regression (named after bug)    |  17   |
| Security (XSS/SSRF/auth/scheme) |  24   |

Regression and security tests are already counted inside the integration/unit
totals above; they are shown separately to highlight named coverage.

## 2. Categorical gaps — root-cause analysis

The four must-fix findings on PR #34 all shared one root cause: **behavior that
was validated in one place but drifted from a sibling implementation**. The
suite had thorough per-endpoint happy-path tests but no cross-endpoint parity
tests. Below, each gap category is numbered, one paragraph of analysis, then a
list of the tests being added.

### Gap 2.1 — Cross-endpoint field-consistency drift

The multipart `/analyze/file` handler had a **hardcoded chip allowlist** (a
literal `{"want_understand", "for_child", "for_care", "just_curious"}`) that
was already stale the moment `for_work` was added to the `ContextChip`
`Literal`. Meanwhile the JSON endpoints (`/analyze`, `/analyze/url`,
`/analyze/batch`) route the same input through Pydantic, which auto-derives the
allowlist from the `Literal`. **No existing test posted the same context /
jurisdiction / doc_type / industry values to all four endpoints and asserted
they were accepted equivalently.** The fix commit (`2626e2b`) now derives the
multipart allowlists from `typing.get_args(ContextChip)` / `get_args(Jurisdiction)`
via module-level `_VALID_CHIPS` / `_VALID_JURISDICTIONS` constants. A regression
guard that ties those constants to the schema `Literal` would have prevented
the drift.

Added tests (`test_regressions_pr34.py`):
- `test_all_analyze_endpoints_accept_every_context_chip`
- `test_all_analyze_endpoints_reject_bogus_context_chip_consistently`
- `test_all_analyze_endpoints_accept_every_valid_jurisdiction`
- `test_all_analyze_endpoints_filter_bogus_jurisdictions_consistently`

### Gap 2.2 — Schema-`Literal` allowlist drift guards

Even after the multipart handler was fixed, nothing forces future contributors
to keep `_VALID_CHIPS` and `_VALID_JURISDICTIONS` in sync with the schema
`Literal`s. A simple two-line equality assertion pinned to `typing.get_args()`
turns any future drift into a test failure at import time.

Added tests:
- `test_valid_chips_matches_context_chip_literal`
- `test_valid_jurisdictions_matches_jurisdiction_literal`
- `test_doctype_and_industry_allowlists_match_literal`

### Gap 2.3 — URL-scheme XSS defense-in-depth

`WatchlistCreateRequest.source_url` had a scheme validator well before PR #34;
`AnalyzeRequest.source_url`, `AnalyzeUrlRequest.url`, and `BatchItem.url` did
not. Only the `WatchlistCreateRequest` field was covered by a scheme-rejection
test — so when `AnalyzeRequest.source_url` finally got a validator (fix commit
`2626e2b`), the assumption that "the analyze endpoints must reject
`javascript:` the same way the watchlist does" had never been asserted. The
tests added here loop every URL-accepting request field through a battery of
XSS scheme payloads and assert `4xx`.

Added tests:
- `test_all_url_fields_reject_javascript_scheme`
- `test_all_url_fields_reject_data_scheme`
- `test_all_url_fields_reject_vbscript_scheme`
- `test_all_url_fields_reject_file_scheme`
- `test_all_url_fields_accept_https_scheme`
- `test_watchlist_and_analyze_reject_url_schemes_identically`

### Gap 2.4 — Jurisdiction-filter boundary predicate

`analyze_text` filters LLM findings by:

```python
if jurisdictions:
    jurisdiction_set = set(jurisdictions)
    llm_findings = [
        f for f in llm_findings
        if f.jurisdictions and any(j in jurisdiction_set for j in f.jurisdictions)
    ]
```

The pre-fix code used `if not f.jurisdictions or any(...)`, which meant a
finding with an empty `jurisdictions` list would slip through the filter — a
CCPA-only request could receive a BIPA finding. Nothing exercised the corner
case of "LLM emits a finding with `jurisdictions=[]`". Added tests seed the
`_merge_findings` pathway with empty-jurisdiction LLM findings and assert they
are dropped.

Added tests:
- `test_analyze_drops_llm_findings_with_empty_jurisdictions`
- `test_analyze_drops_llm_findings_with_nonmatching_jurisdictions`
- `test_analyze_keeps_llm_findings_when_at_least_one_matches`

### Gap 2.5 — Malformed / oversized inputs

The suite had happy-path input coverage but almost nothing on
`empty text` / `null bytes` / `pathologically large payload` /
`unicode normalization` / `whitespace-only` inputs. Empty text is already
guarded by Pydantic (`min_length=1`) — verified — but the assertion had no
regression protection.

Added tests:
- `test_analyze_rejects_empty_text`
- `test_analyze_rejects_whitespace_only_text`
- `test_analyze_handles_null_bytes_in_text`
- `test_analyze_handles_mixed_unicode_normalization`

### Gap 2.6 — ReDoS canary on `inference.py`

`inference.py` runs ~90 regex patterns over user-supplied text on every
`/infer` call. If any of them are catastrophically backtracking, a single
crafted payload could tie up a worker. There was no wall-clock budget check.

Added tests:
- `test_infer_regex_completes_within_budget_for_pathological_inputs`

### Gap 2.7 — Domain-grouping + sort-stability edge cases

`_group_by_domain` uses `_DOMAIN_MAP.get(f.category)` — categories that
aren't mapped return `None` and are silently skipped. Behaviour is intentional,
but nothing pins it as a contract. `apply_category_weights` is expected to
sort deterministically (stable per Python `sorted()`), but nothing verified
that two findings with identical `(weight, irp, severity)` keys preserve
input order.

Added tests:
- `test_group_by_domain_skips_unmapped_category`
- `test_group_by_domain_respects_per_domain_cap`
- `test_group_by_domain_respects_total_cap`
- `test_apply_category_weights_sort_is_stable_on_identical_keys`

## 3. Meta-recommendation — a testing policy

The common thread across all four PR #34 must-fix findings is:

> **every value-validating field, on every endpoint that accepts that field,
> must have a paired parity test proving the endpoints treat it the same way.**

Concretely, this manifests as three lint-like tests we should keep permanently:

1. **Schema-to-handler allowlist parity.** Any module-level `frozenset` or
   `set` used inside a handler to validate against a `Literal` must be
   equality-asserted against `typing.get_args(<Literal>)` in a test. If the
   `Literal` grows, the assertion fails at CI time — not in production.
2. **Cross-endpoint field parity.** For each field shared across
   `/analyze`, `/analyze/url`, `/analyze/file`, `/analyze/batch`, one
   parametrized test should submit the same valid value to every endpoint and
   assert `200`, and one should submit the same invalid value and assert
   `4xx` (or the same silent-drop behavior — pick one and enforce it).
3. **Schema-derived enumeration.** Tests that iterate over enum values should
   use `typing.get_args(<Literal>)` at runtime rather than hardcoded lists, so
   new values are automatically covered.

If we adopt these three rules as a policy in `.claude/rules/testing.md`, the
class of bugs PR #34 caught will fail CI on the first commit that introduces
them, instead of surviving into a multi-specialist code review.

## 4. Backfill summary

- **File added:** `src/backend/tests/test_regressions_pr34.py`
- **Categories covered:** 7 (2.1 through 2.7)
- **Tests added:** 25
- **All tests pass** against the code at commit `2626e2b`.

No genuine bugs surfaced beyond the four already fixed by that commit.
Everything the new tests assert either holds under current code or would hold
by construction (schema-derived allowlists).
