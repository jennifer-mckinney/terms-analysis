# Test Suite Quality Audit (PR #34)

Read-only quality audit of the existing backend pytest suite at `src/backend/tests/`. Complementary to the separate gap-audit — this looks at what already exists, not what's missing.

## 5.1 Suite-level stats

| Metric | Value |
|---|---|
| Total test functions (`def test_`) | **514** declared |
| Total tests after `@pytest.mark.parametrize` expansion | **~626+** |
| Total test LoC (incl. helpers/fixtures) | **7,464** |
| Median LoC per test | ~10 |
| p90 LoC per test | ~35 (PDF-payload builders and full mocked-httpx harnesses are the tail) |
| Shared fixtures in `conftest.py` | 3 (`db_session`, `app_client`, `sample_privacy_policy_text`) |
| Parametrize decorators total | 13 (2 in `test_context`, 5 in `test_all`, 6 in `test_inference`) |

**Test count by file** (top 5 dominate ~85% of suite):

| File | LoC | test defs |
|---|---:|---:|
| `test_main_endpoints.py` | 1,537 | 106 |
| `test_services.py` | 1,429 | 114 |
| `test_all.py` | 1,005 | 92 |
| `test_database_and_main_coverage.py` | 851 | 32 |
| `test_snapshots_and_diffs.py` | 578 | 32 |
| `test_inference.py` | 362 | 33 |
| `test_legal_kb.py` | 314 | 15 |
| `test_enhancements.py` | 306 | 22 |
| `test_context.py` | 292 | 24 |
| `test_validation.py` | 212 | 14 |
| `test_analyzer.py` | 194 | 5 |
| `test_irp.py` | 130 | 12 |
| `test_ingest.py` | 79 | 5 |
| `test_prompts.py` | 72 | 5 |
| `test_llm_failure.py` | 40 | 2 |
| `test_rules.py` | 12 | 1 |

**Category mix (estimate):**
- Rule-detection assertions (single-line "does category X fire on text Y"): ~40%
- API endpoint tests (TestClient): ~25%
- Service-unit tests (analyzer/ingest/embedding/localai internals with mocks): ~25%
- Regression / security / PR #34 must-fix: ~7%
- Meta (schema/literal coverage): ~3%

---

## 5.2 Findings table (top 20 by impact)

| # | File | Test | Verdict | Reason | Action |
|---|---|---|---|---|---|
| 1 | `test_all.py` | `test_coppa_triggers_on_children_under_13_text`, `_on_coppa_keyword`, `_hipaa_triggers_on_phi_text`, `_on_hipaa_keyword`, `_glba_triggers_on_financial_information`, ... (all ~40 "category X fires on text Y" tests, lines 407-810) | **Consolidate** | 40+ near-identical single-assert tests: `assert "<Category>" in {f.category for f in detect_findings(...)}` | Collapse into 1 parametrized test `(text, jurisdictions, expected_category)`. Reduces ~40 tests to 1 |
| 2 | `test_services.py` | `TestLocalAIClientAnalyze::test_localai_analyze_*` (6 tests, 993-1090) | **Refactor** | Each rebuilds a 12-line `mock_response`+`AsyncClient` scaffold. Only differs in the injected error mode | Extract `_mock_httpx_post(response_or_exc)` fixture in `conftest.py`; each test drops to ~4 lines |
| 3 | `test_main_endpoints.py` | `TestSecurityApiKeyAuth::test_security_api_key_*_key_*` (4 tests, 1222-1248) | **Consolidate** | Same `with patch("app.main.settings")` + `mock_settings.api_key = "correct-key"` block, varying only header | Parametrize `(header_value, expected_status)` |
| 4 | `test_main_endpoints.py` | `TestSecurityAnalysesLimit` (4 tests, 1046-1060) | **Consolidate** | Four one-liner limit boundary tests | `@pytest.mark.parametrize("limit,expected", [(1000000, 422), (0, 422), (200, 200), (201, 422)])` |
| 5 | `test_all.py` | `test_jurisdiction_literal_includes_all_27_codes` (596-630) | **Keep** | Already parametrized — good baseline example. Note: file title says 27 but reality is 30 per CLAUDE.md; verify | Keep, rename to reflect actual count |
| 6 | `test_services.py` | `TestAnalyzeTextQuickMode::test_analyzer_analyze_text_quick_mode_returns_result` and `test_analyzer_analyze_text_quick_mode_lower_confidence` (235-245) | **Delete** | Two tests. Second one imports `analyze_text as _at` and repeats the first with a comment claim ("0.85 multiplier") that is not actually asserted — only `confidence <= 1.0`, which is trivially true | Delete `_lower_confidence`; either assert the multiplier or drop the coverage-theater test |
| 7 | `test_services.py` | `TestDetectHighSeverityRegexException::test_analyzer_detect_high_severity_regex_exception_is_continued` (1327-1344) | **Delete candidate** | Patches `re.finditer` to raise on call 1, then asserts `call_count[0] >= 1` and `isinstance(findings, list)`. This tests the mock, not behavior. Coverage-only. | Delete OR rewrite to assert that the surviving pattern still produced its expected finding |
| 8 | `test_database_and_main_coverage.py` | `TestExportPdfWithFindings::test_main_export_pdf_with_findings_covers_finding_loop` (451-554) | **Refactor** | 100+ lines of fixture setup for 2 assertions (`media_type` + PDF magic bytes). Fixture cost is disproportionate to what's verified. | Extract `_analysis_with_findings(db_session, findings_data)` fixture; keep the test as regression guard but shrink to ~15 lines |
| 9 | `test_database_and_main_coverage.py` | `TestExportPdfLongExcerpt::test_main_export_pdf_long_excerpt_appends_ellipsis` (562-617) | **Delete candidate** | Name promises "appends ellipsis" — body only asserts `media_type == "application/pdf"` and PDF header bytes. Never checks for ellipsis or truncation. Misnamed / coverage theater. | Either open PDF content and assert the ellipsis is present, or delete |
| 10 | `test_main_endpoints.py` | `TestSecurityWatchlistPrivateUrl::test_security_watchlist_private_ip_url_rejected` (1066-1073) | **Delete** | Assertion is `assert response.status_code in {200, 201, 400, 422}` — any 2xx or 4xx passes. Assertion is a no-op | Either tighten to a single expected code or delete |
| 11 | `test_database_and_main_coverage.py` | `TestRefreshAllWatchlistItems::test_main_refresh_all_watchlist_items_no_items` and `_skips_when_disabled` (303-325) | **Consolidate** | Both patch `db_session` context manager, both count 0 rows or exit early. Overlap heavily | Merge into one test that parametrizes the disabled/enabled path |
| 12 | `test_services.py` | `TestAnalyzeTextFullMode::test_analyzer_analyze_text_full_mode_llm_success` etc. (250-397) | **Refactor** | 5 tests, each inlines the 15-line `with patch("app.services.analyzer.LocalAIClient")` boilerplate | Extract `mock_localai_client` fixture that takes a `payload` param |
| 13 | `test_all.py` | `test_watchlist_item_payload_accepts_none_risk_delta` / `_accepts_float_risk_delta` / `_rejects_string_risk_delta` (364-397) | **Consolidate** | Three tests differ only in `risk_delta` value + expected outcome | Parametrize |
| 14 | `test_context.py` | `TestVerdictHeadline` + `TestVerdictLabel` (already parametrized) | **Keep** | Exemplary — heavy parametrize table + assertion of substring. This is the pattern the rest of the suite should copy | No action |
| 15 | `test_services.py` | `TestLocalAIClientEmbed` (1093-1145) | **Refactor** | Same httpx-mock scaffold as `TestLocalAIClientAnalyze`. Extract shared fixture (see #2) | Reuse #2's fixture |
| 16 | `test_main_endpoints.py` | `TestGetSnapshots`, `TestGetSnapshotDetail`, `TestListWatchlist`, `TestListReviews` (many "empty" + "returns inserted" pairs) | **Consolidate** | Repeated pattern across ~8 endpoints: `empty → []`, `insert → list length N`. Currently 16 tests | Extract a helper `_assert_list_endpoint(app_client, db_session, url, model_factory)` and parametrize |
| 17 | `test_main_endpoints.py` | `TestCaptureWatchSnapshot::_insert_watch` (807-818) | **Refactor** | Class-local helper duplicates the module-level `_insert_watchlist_item` / `PolicyWatch` insert idiom found elsewhere | Move `_insert_watch` next to `_insert_watchlist_item` at module level; share |
| 18 | `test_services.py` | `TestExtractPdf`, `TestExtractDocx`, `TestExtractRtf`, `TestExtractPdfViaExtractBytes` (496-538, 1172-1184) | **Consolidate** | PDF extraction covered twice (`TestExtractPdf` and `TestExtractPdfViaExtractBytes`) with nearly identical body | Merge; keep only the `extract_text_from_bytes` version (higher-level API) |
| 19 | `test_database_and_main_coverage.py` | `TestDatabaseGetDb::test_database_get_db_yields_session` and `_closes_on_completion` (108-131) | **Consolidate** | Second test asserts `len(sessions) == 1` after appending a single session — tautology. Duplicate of first with a trivial extra assert | Merge or delete `_closes_on_completion` |
| 20 | `test_main_endpoints.py` | `TestPr34MustFixRegressions` (1389-1537) | **Keep** | High-value regression bar for the CRITICAL/HIGH PR #34 findings. Well-named, explains rationale in docstrings. Model example | No action |

---

## 5.3 Meta findings

1. **Massive parametrize deficit in `test_all.py`.** ~40 rule-triggering tests all follow `findings = get_findings_for_text(text, [jur]); assert "<Category>" in {f.category for f in findings}`. Collapsing to 1 parametrized test with a table would drop ~40 tests to 1 with 40 params — no coverage loss.

2. **Fixture opportunity: `mock_localai_client`.** `test_services.py` inlines the `with patch("app.services.analyzer.LocalAIClient") as mock_cls: mock_client = AsyncMock(); mock_client.analyze.return_value = ...` incantation ~10 times. Extract to `conftest.py` as a factory fixture.

3. **Fixture opportunity: `_mock_httpx_post`.** ~15 tests build the same `httpx.AsyncClient` mock scaffold (`__aenter__` + `post` + `raise_for_status`). Extract.

4. **Fixture opportunity: `_insert_analysis` helper is duplicated.** `test_main_endpoints.py` and `test_database_and_main_coverage.py` both define nearly identical `_insert_analysis` helpers. Move to `conftest.py`.

5. **Over-mocking (2 counts):**
   - `TestAnalyzeBatch::_make_batch_ns` uses `SimpleNamespace` to sidestep Pydantic and reach a legacy code branch (line 388: `hasattr(request, 'json')`). This tests a dead branch — if the current code uses proper Pydantic, that branch cannot be reached in production. Verify the branch is still live; if not, delete both the branch and the test.
   - `TestAnalyzeBatchLegacyResult::test_main_analyze_batch_legacy_batch_result_uses_json` (804-851) manufactures a fake `BatchAnalysisResult` class to hit an `else` for a legacy `json()` method. Same concern.

6. **Under-mocking / risk:** `test_all.py::test_validate_url_allows_public_https` monkeypatches DNS but if the test runner has offline network policy inconsistencies, this could flake. Not currently a problem based on code but worth marking `@pytest.mark.network`.

7. **Coverage theater:** counted ~6 tests whose only assertions are `assert isinstance(x, list)` or `assert x is not None` or `assert response.status_code in {A, B, C, D}`. These pass regardless of behavior. Enumerated: `TestExtractPdfEmptyReturnsOcrAttempt`, `TestDetectHighSeverityRegexException`, `TestSecurityWatchlistPrivateUrl::test_security_watchlist_private_ip_url_rejected`, `TestSelectChunksBudgetFits::test_embedding_select_chunks_large_budget_exercises_selection`, `TestDatabaseDbSession::test_database_db_session_closes_after_exit`, `TestDetectLanguage::test_localai_detect_language_short_text` (asserts `result is None or isinstance(result, str)` — a tautology).

8. **Test-title vs body drift:** Test names like `..._covers_line_123`, `..._hits_line_123`, `..._covers_lines_257_258` and TestClass docstrings citing line numbers are a code smell — they tie the test to source line numbers rather than behavior. Once source shifts, the doc lies. Rename to behavior descriptors.

9. **Async pattern is consistent.** Following the project convention (per `.claude/rules/testing.md`), all async work goes through `asyncio.run(...)` inside regular `def` tests. No `@pytest.mark.asyncio` no-ops. Good.

10. **No slow-test marker or timing signal.** Nothing under `@pytest.mark.slow`. The PDF-generation and reportlab tests likely dominate suite runtime — they should be marked and skipped on CI-quick runs.

11. **Flaky patterns:** None spotted (no `time.sleep`, no wall-clock comparisons). The `_watchlist_loop_async` tests use `CancelledError` short-circuits deliberately — clean.

12. **Regression tests are high value.** The `TestPr34MustFixRegressions` class and `test_export_pdf_route_is_not_shadowed_by_json_export_route` (test_all.py line 217) are exactly the kind of tests that justify the suite existing — they cite the finding, explain the regression, assert the fix. Model examples.

---

## 5.4 Recommended pruning

Applying the recommendations above:

| Action | Count |
|---|---:|
| **Consolidate** into parametrize tables (net removed) | ~55 tests → ~5 parametrized tests |
| **Delete** (coverage theater / tautology / misnamed) | ~8 tests |
| **Refactor** (extract fixtures, no change to test count) | ~25 tests |

**Estimated suite size after prune:** 514 → **~450 declared test defs** (params still expand to ~570+ runs). LoC drops from 7,464 to ~5,500 (–25%).

**Coverage impact:** Near-zero. Nothing recommended for deletion covers a code path that isn't already covered by another test or by a stronger parametrized replacement. The two `SimpleNamespace`/`LegacyBatchResult` tests may legitimately drop 1-2% if the underlying legacy branch is still live — verify before deleting.

---

## 5.5 Suite health verdict

**YELLOW.**

The suite is not broken. It has real value — the PR #34 regression class, the security tests, the rule-firing catalog, and the diffing/hashing tests are the kind of coverage a project this size should have. The `test_context.py` and `test_inference.py` files are near-exemplary in their parametrize discipline and behavior-focused assertions.

But there is real bloat:
- ~55 near-identical rule-trigger tests that beg to be one parametrize table
- ~8 coverage-theater tests whose only job is to hit a line, not verify behavior
- Systematic under-use of shared fixtures — 3 fixtures in `conftest.py` supporting 626+ tests is under-invested; the `_insert_analysis` / `_mock_localai_client` / `_mock_httpx_post` boilerplate should have been fixtures from day one
- Line-number-citing test names create maintenance debt

None of this is dangerous, but it slows edit velocity and inflates the "626 tests!" number in a way that reads worse than the underlying quality actually is. A single cleanup pass (est. 1 focused day) would drop LoC ~25%, retain coverage, and make the suite easier to extend.

The top-3 highest-impact wins are: (1) parametrize the rule-trigger catalog, (2) extract `mock_localai_client` and `_insert_analysis` to `conftest.py`, (3) delete or repair the ~8 coverage-theater tests. Everything else is nice-to-have.
