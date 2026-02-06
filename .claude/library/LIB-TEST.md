# LIB-TEST: Test Coverage Gaps & Implementation Plan

## Current State (5 tests total)

| File | Tests | Covers |
|------|-------|--------|
| `test_rules.py` | 1 | Sale/Share + Retention detection (2 of 9 categories) |
| `test_ingest.py` | 2 | HTML extraction, RTF extraction |
| `test_llm_failure.py` | 2 | LLM offline fallback, timeout returns None |

**Estimated coverage: ~5-8%**

## Coverage Gaps by Module

### rules.py (Priority 1 - Easy)

| Gap | What to Test |
|-----|-------------|
| 7 untested categories | ADM, Dark Patterns, Minors, Sensitive Data, Unilateral Changes, Liability, User Rights |
| `_confidence()` | Formula: `0.25 + 0.5*base + 0.15*hit_ratio + 0.1*density`, clamped [0.35, 0.95] |
| `_line_number()` | Character offset to line number conversion |
| `_excerpt()` | Context window extraction around match |
| `_match_stats()` | Pattern hit counting, first-match tracking |
| Jurisdiction filtering | Rules skipped when jurisdiction doesn't match |
| Edge cases | Empty text, no matches, all patterns match |

### validation.py (Priority 2 - Medium)

| Gap | What to Test |
|-----|-------------|
| Empty findings | Returns confidence 0.0 with "No findings returned" |
| Missing excerpt | Flags hallucination |
| Invalid line numbers | `line_start < 1`, `line_end < line_start` |
| Out-of-range lines | Lines beyond document length |
| Excerpt not in cited lines | Hallucination flag |
| Missing legal_basis | Citation penalty |
| Coverage ratio < 0.70 | Additional penalty |
| Confidence arithmetic | `avg_confidence - penalties`, clamped [0.0, 1.0] |

### diffing.py + prompts.py (Priority 3 - Easy)

| Gap | What to Test |
|-----|-------------|
| `content_hash()` | SHA-256 correctness, empty string |
| `diff_summary()` | Additions/removals count, max_lines truncation, identical texts |
| `build_user_prompt()` | Jurisdiction interpolation, rule findings included |

### analyzer.py (Priority 4 - Hard)

| Gap | What to Test |
|-----|-------------|
| `calculate_risk_score()` | Severity weight mapping: Critical=4, High=3, Medium=2, Low=1 |
| `_grade()` | Score-to-grade boundaries: A(0-3), B(3-5), C+(5-7), C(7-8), D+(8-9), D(9-10) |
| `_merge_findings()` | Deduplication by (category, excerpt[:80]) |
| Confidence modifiers | No LLM: *0.8, empty LLM findings: *0.85, dropped findings penalty |
| `review_required` | True when confidence < settings.review_threshold |
| `_truncate_text()` | Enforces max_input_chars |
| `_with_line_numbers()` | Format: `0001\| text` |

### lm_studio.py (Priority 5 - Medium)

| Gap | What to Test |
|-----|-------------|
| Successful response | Parse JSON from `choices[0].message.content` |
| HTTP error | Non-200 status handling |
| Invalid JSON in content | Fallback to None |
| Missing response structure | Missing choices/message/content path |
| URL normalization | Trailing `/v1` handling |

### ingest.py (Priority 6 - Medium)

| Gap | What to Test |
|-----|-------------|
| PDF extraction | `_extract_pdf()` with fixture file |
| DOCX extraction | `_extract_docx()` with fixture file |
| OCR fallback | `_extract_pdf_with_ocr()` — mock pytesseract |
| `_decode_bytes()` | utf-8, utf-16, latin-1 fallback chain |
| `_normalize_text()` | CR/LF normalization |
| `fetch_url_text()` | Async URL fetch — mock httpx |
| Content-type routing | Dispatch based on extension/MIME |

### main.py API endpoints (Priority 7 - Hard)

| Gap | What to Test |
|-----|-------------|
| `POST /analyze` | Happy path, empty text → 400, low confidence → review created |
| `POST /analyze/url` | URL fetch + analysis pipeline |
| `POST /analyze/file` | Multipart upload + extraction |
| `GET /analyses` | List with pagination |
| `GET /analyses/{id}` | Found, not found → 404 |
| `GET /rubric` | `_compute_rubric_scores()` aggregation |
| `GET /exports/*` | JSON, CSV, PDF export formats |
| `GET/POST /reviews` | HITL queue operations |
| `GET/POST/DELETE /watchlist` | CRUD operations |
| `POST /watchlist/{id}/refresh` | Re-fetch + diff + rescore |

### schemas.py + config.py (Priority 8 - Easy)

| Gap | What to Test |
|-----|-------------|
| Pydantic validation | Boundary values (confidence 0.0-1.0, risk_score 0.0-10.0) |
| Literal types | Invalid severity/jurisdiction/status rejected |
| Config env overrides | `monkeypatch.setenv` for each setting |
| Config defaults | Values when env vars unset |

### app.js Frontend (Priority 9 - Hard)

| Gap | What to Test |
|-----|-------------|
| `getRiskClass()` | Boundary values: 8, 7.99, 6, 5.99 |
| `getToastIcon()` | All 4 types + unknown fallback |
| Navigation | Page switching, active state |
| API communication | fetch mock for all endpoints |
| Theme cycling | auto → light → dark → auto |

## Recommended conftest.py Fixtures

| Fixture | Purpose |
|---------|---------|
| `db_session` | In-memory SQLite with tables created |
| `client` | FastAPI TestClient with db override |
| `sample_finding` | Factory: valid Finding with configurable fields |
| `sample_policy_text` | Realistic text triggering multiple rule categories |
| `mock_lm_client` | Patched LmStudioClient returning configurable payloads |
| `sample_pdf_bytes` | Minimal valid PDF binary |
| `sample_docx_bytes` | Minimal valid DOCX binary |

## Implementation Order

1. `conftest.py` (unblocks everything)
2. `test_rules.py` expansion (pure logic, highest ROI)
3. `test_validation.py` (pure logic, critical for quality)
4. `test_diffing.py` + `test_prompts.py` (quick wins)
5. `test_analyzer.py` (complex, core business logic)
6. `test_lm_studio.py` (network mocking)
7. `test_ingest.py` expansion (file format coverage)
8. `test_schemas.py` + `test_config.py` (validation boundaries)
9. `test_api_*.py` files (full integration)
10. `app.test.js` (frontend, separate toolchain)
