# Test Coverage Matrix — End-to-End Journey Coverage
generated: 2026-07-03
branch: claude/issue-19-arch-docs-followup

## Legend

| Symbol | Meaning |
|--------|---------|
| COVERED | Explicit tests exist, happy path + key edges |
| PARTIAL | Tests exist but edge cases missing |
| THIN | Only 1-2 tests; boundary/param coverage absent |
| GAP | No tests found |
| N/A | Out of scope for backend test suite |

Severity: CRITICAL > HIGH > MEDIUM > LOW

---

## Section 1 — User Journey Matrix

| # | Journey | Layer | Test Files | Coverage | Gap Severity |
|---|---------|-------|-----------|----------|--------------|
| U1 | Text paste → jurisdiction(s) → findings grouped by domain | Integration | test_analyzer.py, test_all.py, test_main_endpoints.py | PARTIAL | MEDIUM |
| U2 | URL submission → fetch + analyze → findings | Integration | test_ingest.py, test_all.py, test_database_and_main_coverage.py | COVERED | LOW |
| U3 | File upload (PDF/DOCX/RTF/TXT) → extract + analyze | Unit/Int | test_ingest.py, test_enhancements.py | PARTIAL | HIGH |
| U4 | for_child chip → plain-English findings | Unit | test_context.py, test_child_context_simplification.py, simplification-check.sh | COVERED | LOW |
| U5 | for_work chip → work-weighted findings | Unit | test_context.py | COVERED | LOW |
| U6 | Multiple chips → compound weights + re-sort | Unit | test_context.py | COVERED | LOW |
| U7 | No jurisdiction → "no filter" mode (not US-CA/GDPR default) | Unit/Int | test_analyzer.py, test_audit_phase1_fixes.py | COVERED | LOW |
| U8 | Blocked URL (localhost / private IP) → SSRF error | Integration | test_ingest.py, test_all.py, test_database_and_main_coverage.py | COVERED | LOW |
| U9 | Batch URLs → cross-reference detection | Integration | tests/test_batch_analysis.py | PARTIAL | HIGH |
| U10 | IRP scoring — impact/likelihood/safeguard/irp_score on findings | Unit | test_irp.py, test_rules.py | COVERED | LOW |
| U11 | LLM failure → fallback to rule-only findings (HR5) | Unit | test_llm_failure.py | PARTIAL | MEDIUM |
| U12 | Confidence < 0.80 → finding flagged for HITL review (HR7) | Integration | (none found) | GAP | CRITICAL |
| U13 | Malformed/XSS input → sanitized, not rendered as HTML | Integration | test_regressions_pr34.py, test_critical_p9_fixes.py | COVERED | LOW |
| U14 | ReDoS pathological input → completes without hang | Unit | test_critical_p9_fixes.py | THIN | HIGH |
| U15 | Rule engine — 50+ categories detected correctly | Unit | test_rules.py (1 test) | THIN | CRITICAL |
| U16 | Risk grading — score → A/A-/B/B-/C+/C/D+ letter grade | Integration | test_all.py | PARTIAL | MEDIUM |
| U17 | /infer endpoint → TLD jurisdiction + doc_type signals | Unit/Int | test_inference.py, test_all.py | COVERED | LOW |
| U18 | Verify-view / snapshot comparison (GAP-007) | Unit/Int | test_snapshots_and_diffs.py, test_main_endpoints.py | PARTIAL | MEDIUM |
| U19 | Watchlist — add/remove/refresh entries | Integration | test_watchlist_merge.py, test_main_endpoints.py | COVERED | LOW |
| U20 | Legacy UI (STREAMLIT_UI=v1) vs v2 routing | E2E | (none) | GAP | N/A |

---

## Section 2 — Test File Inventory

| File | Location | Count | Primary Coverage |
|------|----------|-------|-----------------|
| test_all.py | src/backend/tests/ | 92 | Broad integration: rules, endpoints, SSRF, grade calc |
| test_main_endpoints.py | src/backend/tests/ | 108 | Rubric, exports, watchlist/reviews/snapshots/diff endpoints |
| test_services.py | src/backend/tests/ | 114 | Truncate, line offsets, encoding, mock patterns |
| test_audit_phase1_fixes.py | src/backend/tests/ | 60 | Empty jurisdiction, schema validation, endpoint parity |
| test_regressions_pr34.py | src/backend/tests/ | 38 | Jurisdiction filter, URL-scheme XSS, literal parity |
| test_inference.py | src/backend/tests/ | 41 | TLD mapping, statute extraction, doc_type/industry |
| test_context.py | src/backend/tests/ | 26 | Chip priority, category weights, verdict copy |
| test_database_and_main_coverage.py | src/backend/tests/ | 30 | DB connectivity, /analyze/url/file/batch error paths |
| test_analyzer.py | src/backend/tests/ | 16 | Domain roll-up, jurisdiction filtering, action items |
| test_enhancements.py | src/backend/tests/ | 22 | Evidence binding, industry patterns, confidence |
| test_snapshots_and_diffs.py | src/backend/tests/ | 29 | Content hashing, token-level diffing |
| test_irp.py | src/backend/tests/ | 12 | IRP formula, risk score calc, finding seeding |
| test_legal_kb.py | src/backend/tests/ | 15 | Corpus parsing, embedding indexing, retrieval ranking |
| test_watchlist_merge.py | src/backend/tests/ | 10 | WatchlistItem ORM, enabled bool, refresh cadence |
| test_validation.py | src/backend/tests/ | 14 | Finding validation, line number checks, excerpts |
| test_critical_p9_fixes.py | src/backend/tests/ | 18 | ReDoS, RTF regex, XSS escape, LLM paraphrase |
| test_ingest.py | src/backend/tests/ | 5 | HTML/RTF extraction, SSRF blocking, redirect limits |
| test_llm_failure.py | src/backend/tests/ | 2 | LLM failure fallback, LocalAI unreachable |
| test_rules.py | src/backend/tests/ | 1 | Basic rule detection (sale/share + retention only) |
| test_prompts.py | src/backend/tests/ | 5 | LLM prompt construction |
| test_api_endpoints.py | tests/ (root) | ~40 | Mode param (quick/full), endpoint integration (mocked) |
| test_batch_analysis.py | tests/ (root) | ~25 | Multi-doc batch, cross-reference API |
| test_child_context_simplification.py | tests/ (root) | ~15 | for_child simplification patterns (copied function) |
| test_quick_mode.py | tests/ (root) | ~18 | Quick mode speed, confidence, severity filtering |
| **simplification-check.sh** | scripts/testing/ | 14 | for_child simplification — live source, headless |
| **smoke-test.sh** | scripts/testing/ | 9 | Live HTTP endpoints via curl+jq |

**Total backend tests: ~873** | **Total shell assertions: 23**

---

## Section 3 — Gap Detail

### CRITICAL-GAP-1: Rule Engine Category Coverage

- **Journey**: U15
- **What exists**: 1 test in test_rules.py covering Sale/Share + Retention
- **What's missing**: ~48 of 50 categories have zero dedicated tests
- **Impact**: Silent breakage of any category rule goes undetected
- **Fix**: New `test_rules_comprehensive.py` with `@pytest.mark.parametrize("category, sample_text")` × 50 categories
- **Files**: `src/backend/app/services/rules.py`, `schemas.py:CATEGORIES`
- **Effort**: 1-2 days

### CRITICAL-GAP-2: Confidence Threshold HITL Flag

- **Journey**: U12
- **What exists**: Nothing — HR7 (confidence < 0.80 → HITL) has no test
- **What's missing**: Mock LLM to return low-confidence finding; assert `review_required=True` on payload
- **Impact**: HITL review may never trigger; critical findings ship without human review
- **Fix**: Add to `test_analyzer.py` — mock LLM returning `confidence=0.75`; assert flag set
- **Files**: `src/backend/app/main.py`, `src/backend/app/services/analyzer.py`
- **Effort**: 0.5 days

### HIGH-GAP-3: File Upload Format Coverage

- **Journey**: U3
- **What exists**: HTML + RTF extraction tested; DOCX/PDF handling not explicitly tested in endpoint path
- **What's missing**: `/analyze/file` endpoint tests with real PDF and DOCX sample fixtures
- **Fix**: Parametrize `test_ingest.py` with `tmp_path` fixtures for each MIME type
- **Files**: `src/backend/app/services/ingest.py`, `/analyze/file` endpoint
- **Effort**: 1 day

### HIGH-GAP-4: ReDoS Pathological Payload Specificity

- **Journey**: U14
- **What exists**: Timing test with 10KB "marketing" repetition, 1.0s threshold
- **What's missing**: Specific backtracking-prone patterns (nested quantifiers, alternation explosion)
- **Fix**: Add patterns like `(a+)+b`, `(x|x)*y` with 100-char inputs; assert < 50ms
- **Files**: `src/backend/tests/test_critical_p9_fixes.py`
- **Effort**: 0.5 days

### HIGH-GAP-5: Batch Cross-Reference Logic

- **Journey**: U9
- **What exists**: API wrapper test; cross-ref detection exercised at API level
- **What's missing**: Unit tests for matching heuristics in isolation (how Privacy Policy + Cookie Policy get linked)
- **Fix**: New `test_batch_cross_references.py` targeting `analyzer._detect_cross_references`
- **Files**: `src/backend/app/services/analyzer.py`
- **Effort**: 1 day

### MEDIUM-GAP-6: Grade Boundary Parametrization

- **Journey**: U16
- **What exists**: Grade calc tested in test_all.py but not parameterized across all boundaries
- **What's missing**: `@pytest.mark.parametrize("score, expected")` covering all 7 grade cutoffs
- **Grade thresholds**: A (<3.5), A- (3.5-4.5), B (4.5-5.5), B- (5.5-6.5), C+ (6.5-7.5), C (7.5-8.5), D+ (>=8.5)
- **Fix**: 7 parametrized cases in `test_analyzer.py` or new `test_grading.py`
- **Effort**: 0.5 days

### MEDIUM-GAP-7: LLM Partial / Timeout Failure

- **Journey**: U11
- **What exists**: Complete LLM failure (unreachable) tested
- **What's missing**: Partial timeout (LLM hangs mid-stream); LLM returns partial findings
- **Fix**: Mock async timeout via `asyncio.TimeoutError`; assert graceful fallback with rule-only result
- **Effort**: 0.5 days

### MEDIUM-GAP-8: End-to-End UI Flow

- **Journey**: U1, U4-U6
- **What exists**: Backend unit/integration coverage for domain grouping and context chips
- **What's missing**: No Streamlit component test validating the full text→submit→domain display flow
- **Fix**: `tests/test_streamlit_flow.py` using `streamlit.testing.v1.AppTest`
- **Effort**: 2 days

---

## Section 4 — Test Layer Distribution

| Layer | Current % | Target % | Files |
|-------|-----------|----------|-------|
| Unit | 60% | 85% | analyzer, context, inference, irp, validation, critical_p9 |
| Integration | 50% | 80% | test_all, main_endpoints, ingest, batch_analysis |
| E2E (live HTTP) | 5% | 25% | smoke-test.sh (9 tests) |
| E2E (UI) | 0% | 15% | (none — Streamlit flow untested) |
| Regression lock | 40% | 60% | test_regressions_pr34, test_audit_phase1_fixes |

---

## Section 5 — Mock Strategy

| Service | Mock Type | Files | Gap |
|---------|-----------|-------|-----|
| LocalAI (LLM) | AsyncMock + fake_analyze | test_llm_failure, test_analyzer, test_all | Partial timeout path untested |
| HTTP (URL fetch) | httpx.MockTransport | test_ingest, test_all | Redirect loops; slow response |
| Database | In-memory SQLite | test_main_endpoints, test_watchlist | Concurrent writes; transaction rollback |
| File I/O | Real tmp_path fixtures | test_ingest, test_legal_kb | Large file stress; corrupt file |
| Streamlit | None (no UI tests) | — | Entire UI layer untested |

---

## Section 6 — Priority Backlog

| Priority | Gap | Journey | Effort | New File |
|----------|-----|---------|--------|---------|
| P0 | Rule category parametrization (48 untested) | U15 | 1-2 days | test_rules_comprehensive.py |
| P0 | Confidence < 0.80 HITL flag | U12 | 0.5 days | test_analyzer.py (append) |
| P1 | PDF/DOCX file upload endpoint | U3 | 1 day | test_ingest.py (extend) |
| P1 | ReDoS pathological payloads | U14 | 0.5 days | test_critical_p9_fixes.py (append) |
| P1 | Batch cross-reference logic unit tests | U9 | 1 day | test_batch_cross_references.py |
| P2 | Grade boundary parametrization | U16 | 0.5 days | test_grading.py |
| P2 | LLM partial/timeout failure | U11 | 0.5 days | test_llm_failure.py (append) |
| P3 | Streamlit E2E flow | U1, U4-U6 | 2 days | tests/test_streamlit_flow.py |

**Total estimated backlog: 7.5–8.5 days of test-writing work**

---

## Section 7 — Schema Drift Enforcement Status

The 3-rule drift policy from `.claude/rules/testing.md` is well-enforced for existing schemas:

| Rule | Status | Test |
|------|--------|------|
| R1: Handler allowlist derived from `get_args(Literal)` | ENFORCED | test_regressions_pr34.py |
| R2: Cross-endpoint field parity checked on all siblings | ENFORCED | test_regressions_pr34.py |
| R3: Tests enumerate Literals via `get_args()`, no hardcoding | ENFORCED | test_regressions_pr34.py |

**Gap**: No enforcement for schemas added post-PR34. Recommend an import-time test that auto-discovers all Literal fields and asserts R1-R3 compliance.
