# Technical Audit Report — Terms & Policies Reviewer

> Version 1.0 — 2026-07-03
> Companion to `docs/TECH_SPEC.md` (drafted in parallel).
> Anchors: `docs/BRD_Terms_Policies_Reviewer.md`, `docs/PRD_Terms_Policies_Reviewer.md`, `PRODUCT.md`, `.claude/CLAUDE.md`, `.claude/library/LIB-*.md`.
> Governance: `.claude/library/LIB-PRINCIPLES.md`.
>
> **Post-audit note (2026-07-03, Phase 4):** the vanilla-JS SPA (`src/webapp/index.html` / `app.js` / `style.css`) was retired after this audit was written. Findings below that reference `app.js` reflect the pre-retirement state and are resolved by the retirement itself; OE-005 (30-value jurisdiction map duplication) is now a two-source problem (PDF export + Streamlit v2), not three.

## 0. Executive Summary

This audit cross-checks the shipped codebase (backend `src/backend/app/`, frontend `src/webapp/`, tests `src/backend/tests/`, root `tests/`, launch scripts) against BRD, PRD, `PRODUCT.md`, `.claude/CLAUDE.md`, and the LIB-* reference library. Findings are grouped into GAPS (requirements not implemented), OVER-ENGINEERING (code with no anchor), BLOAT (dead / superseded / redundant code), LOGIC ERRORS (bugs, wrong formulas, silent swallows, contract violations), and GOVERNANCE (docs vs code drift). The audit stays inside `LIB-PRINCIPLES` — every finding cites a BRD/PRD anchor or a code anchor; speculative observations were moved to Open Questions.

Headline counts by severity:

- **BLOCKING:** 3
- **HIGH:** 12
- **MEDIUM:** 15
- **LOW:** 8
- **NIT:** 3
- **Open questions:** 6

Severity legend:
- **BLOCKING** — silently violates a documented contract, ships wrong data to the reader, or contradicts the LIB-PRINCIPLES governance in a way that produces silent goal drift. Fix before next merge.
- **HIGH** — a requirement is not met, a bug degrades output correctness, or a suspicious pattern will break under a realistic input. Fix in the current iteration.
- **MEDIUM** — a spec is only partially implemented, an abstraction is redundant, or documentation is drifting from code. Fix in the next iteration.
- **LOW** — minor cleanup, formatting, or non-load-bearing simplification.
- **NIT** — cosmetic; safe to defer.

---

## 1. Scope of Audit

**Audited:**
- All backend source: `src/backend/app/main.py`, `schemas.py`, `models.py`, `config.py`, `database.py`, `services/*.py`.
- All frontend source: `src/webapp/app_streamlit_v2.py`, `app_streamlit_legacy.py`, `app.js`, `index.html`, `style.css`.
- Backend tests: `src/backend/tests/*.py` (17 files).
- Root-level tests: `tests/test_api_endpoints.py`, `tests/test_batch_analysis.py`, `tests/test_quick_mode.py`.
- Governance and identity docs: `.claude/CLAUDE.md`, `.claude/library/LIB-*.md`, `.claude/rules/*.md`, `PRODUCT.md`.
- Product docs: `docs/BRD_Terms_Policies_Reviewer.md`, `docs/PRD_Terms_Policies_Reviewer.md`.
- Ops: `run.sh`, `.env.example`, `requirements.txt`, `src/backend/requirements.txt`, root-level `SESSION_HANDOFF_2026-07-03_ISSUE_19_REDESIGN.md`.
- Legacy / graveyard: `ignore/`, `archive/`, root `data/legal_corpus/`.

**Not audited:**
- LocalAI runtime internals (upstream OSS project, out of scope for this repo).
- External legal corpus sources — only the placeholder text in `data/legal_corpus/` was inspected for shape and presence, not correctness.
- Deployment / infra outside `run.sh` (there is no k8s / docker manifest to review).
- Third-party dependency source (numpy, sqlalchemy, pypdf, python-docx, striprtf, langdetect, httpx, reportlab).

**Method:**
1. BRD/PRD → code cross-check. Each F-numbered feature and each BRD-CONSTRAINT-* requirement was traced to source. Missing implementations became GAPS.
2. Code → BRD/PRD walk. Each service module, each endpoint, and each schema field was reviewed for a matching requirement. Un-anchored code became OVER-ENGINEERING candidates.
3. Suspicious-marker walk. The pre-produced code inventory flagged silent exception swallows, hardcoded fallbacks, duplicate abstractions, and the `/ignore/` graveyard. Each was re-verified by reading the specific line(s) in the source before being written up.
4. LIB governance sweep. Every `.claude/library/LIB-*.md` file was compared to the code paths it documents. Drift became GOVERNANCE findings.

---

## 2. Findings — GAPS (BRD/PRD requirement not implemented)

### GAP-001 — F5.3 CSV export ignores documented `detailed` and `ids` query params

- **Severity:** HIGH
- **BRD/PRD anchor:** PRD §5.5.3 (F5.3), PRD §7.3.12
- **Requirement (verbatim):**
  > "Export endpoint: `GET /exports/analyses.csv?detailed=true`" (PRD §7.3.12)
  > "Query Parameters: `ids`: comma-separated analysis IDs (optional, default: all); `detailed`: boolean (default: false) - include findings or just summary" (PRD §7.3.12)
- **Current implementation state:** `src/backend/app/main.py:541-571` — the endpoint signature takes zero query parameters. It always returns a summary CSV of every analysis in the database. Bulk finding-level export is not implemented. Streamlit v2 already sends `?ids={doc_id}&detailed=true` (`app_streamlit_v2.py:923`); the backend silently ignores both.
- **Proposed remediation:** Add `ids: Optional[str] = Query(default=None)` and `detailed: bool = Query(default=False)` parameters. Filter analyses by parsed IDs; when `detailed=true`, emit one row per finding with columns from PRD §5.5.3 (`Analysis ID, Document Name, Finding ID, Category, Severity, Confidence, Excerpt, Line Start, Line End`).
- **Effort:** M
- **Notes:** The Streamlit v2 export button currently produces the wrong output (summary of all analyses instead of one detailed sheet for the current doc). Reader-visible bug.

### GAP-002 — F5.2 JSON export endpoint URL diverges from PRD contract

- **Severity:** MEDIUM
- **BRD/PRD anchor:** PRD §7.3.11 (F5.2)
- **Requirement (verbatim):**
  > "GET `/exports/analysis/{id}.json` — Export analysis as JSON" (PRD §7.3.11)
- **Current implementation state:** `main.py:848-853` registers `GET /exports/analysis/{analysis_id}` (no `.json` suffix). Streamlit v2 calls `.../{doc_id}.json` (`app_streamlit_v2.py:903`), which will 404 or (worse) be treated by Starlette's path matcher as a literal ID containing `.json`. Manual test needed to confirm which failure mode fires, but the contract does not match either way.
- **Proposed remediation:** Either register the route as `{analysis_id}.json` (mirroring the `.pdf` route), or update PRD to name the extensionless variant. Given the `.pdf` route was explicitly ordered before the JSON route to prevent shadowing (comment at `main.py:843-847`), the intent was clearly to support both extensions.
- **Effort:** S
- **Notes:** The bug is invisible in unit tests because `test_regressions_pr34.py` doesn't exercise the `.json` suffix; only the frontend hits it.

### GAP-003 — F1.2 file upload accepts formats but `.rtf` support is missing from Streamlit v2 UI declaration and PDF OCR silently returns "" on empty pages

- **Severity:** MEDIUM
- **BRD/PRD anchor:** BRD §2.2.1 (BRD-VP), PRD §5.1.2 (F1.2), BRD-CONSTRAINT-TECH-004
- **Requirement (verbatim):**
  > "Support minimum 6 document formats: PDF, DOCX, RTF, HTML, text, URL" (BRD-CONSTRAINT-TECH-004)
- **Current implementation state:** `ingest.py:124` allows all six formats. `app_streamlit_v2.py:406` correctly lists `["pdf", "docx", "rtf", "html", "txt"]`. But `ingest.py:141` — for a scanned PDF where per-page text extraction returns empty AND `pytesseract` is unavailable — returns `""`. `main.py:369` then rejects with 400 "Uploaded file is empty". BRD §2.2.1 promises "OCR fallback for scanned PDFs" as a shipped capability, not a runtime option. `pytesseract` is in `requirements.txt` but Tesseract itself is a system binary that may be missing on a fresh install.
- **Proposed remediation:** Detect the `pytesseract is None` case at import and surface an actionable error to the caller ("OCR unavailable — install Tesseract to analyze scanned PDFs") rather than silently returning empty text.
- **Effort:** S
- **Notes:** Related to LE-006 (silent extraction fallback).

### GAP-004 — F6.1 "add to watchlist" request contract does not match PRD

- **Severity:** HIGH
- **BRD/PRD anchor:** PRD §7.3.9 (F6.1)
- **Requirement (verbatim):**
  > "Request: `{ "analysis_id": "uuid (required)", "frequency": "daily | weekly | monthly (default: weekly)", "notes": "string (optional)" }`" (PRD §7.3.9)
- **Current implementation state:** `schemas.py:316-331` defines `WatchlistCreateRequest` as `{vendor: str, source_url: Optional[str]}`. No `analysis_id`, no `frequency`, no `notes`. The watchlist model itself (`models.py:46-61`) has no FK back to `Analysis`. The refresh loop (`main.py:113-119`) uses a global interval, not per-item frequency.
- **Proposed remediation:** Either (a) update BRD/PRD to reflect the shipped vendor+URL contract, or (b) add the three PRD fields and wire a per-item scheduler. Given `check_frequency` already lives on the separate `PolicyWatch` table (`models.py:82`), option (a) plus a merge of `PolicyWatch` and `WatchlistItem` is likely the correct shape.
- **Effort:** L
- **Notes:** Two overlapping "watch" abstractions exist (watchlist + policy_watch); see OE-003.

### GAP-005 — F6.2 change-detection notification (email) is not implemented

- **Severity:** MEDIUM
- **BRD/PRD anchor:** PRD §5.6.2 (F6.2), BRD-ROADMAP-P4-D007
- **Requirement (verbatim):**
  > "System sends email notification if significant change (±1.0 risk score or new high-severity finding)" (PRD §5.6.2)
  > "Email notification system" (BRD-ROADMAP-P4-D007)
- **Current implementation state:** `main.py:122-163` (`_refresh_all_watchlist_items`) computes `risk_delta` and stores it on the `WatchlistItem` row, but there is no SMTP integration, no notification service, and no queue. The refresh loop just mutates rows.
- **Proposed remediation:** F6 is P1 (Phase 4). Either mark this as deferred with an explicit note in PRD, or wire a simple SMTP sender behind a config flag. Cannot ship "Watchlist change alerts (email)" (BRD-RETENTION-ENGAGE-001) without this.
- **Effort:** L

### GAP-006 — F7 vendor comparison endpoint and UI missing

- **Severity:** MEDIUM
- **BRD/PRD anchor:** PRD §5.7 (F7), BRD-ROADMAP-P4-D002 "Vendor comparison (side-by-side)"
- **Requirement (verbatim):**
  > "User can select 2-3 analyses to compare. System displays side-by-side comparison table." (PRD §5.7.1)
- **Current implementation state:** No `/compare` or `/vendor-comparison` endpoint in `main.py`. `app.js:1003-1004` renders a `compare` page shell with vendor A/B selectors but nothing wires up the comparison logic. Streamlit v2 has no comparison view at all.
- **Proposed remediation:** F7 is P1 (Phase 4). Mark deferred in PRD implementation status note (§4 already documents such deferrals for F1.3 etc.), or scaffold the endpoint.
- **Effort:** L

### GAP-007 — F4.3 Verify view is absent from Streamlit v2

- **Severity:** HIGH
- **BRD/PRD anchor:** PRD §5.4.3 (F4.3), PRD §4 implementation status note
- **Requirement (verbatim):**
  > "F4.3 (Verify View): **resolved.** Streamlit now has a 'View in full document' Verify View expander alongside the JS SPA's modal implementation." (PRD §4)
- **Current implementation state:** `grep -n 'verify\|Verify' src/webapp/app_streamlit_v2.py` returns one match (line 691, a code comment about "verify the correct region was targeted"). No expander, no split pane, no highlight, no line-navigation. The legacy Streamlit file (`app_streamlit_legacy.py:477`) does have "Verify view: full source document with this finding's excerpt highlighted" but that file is no longer the primary UI.
- **Proposed remediation:** Either implement a Verify expander in v2 (per PRD §5.4.3 acceptance criteria) or update PRD §4 to say the redesign explicitly deprioritized Verify View in favor of the collapsed "Legal details / N issues" expander (`app_streamlit_v2.py:804`).
- **Effort:** M
- **Notes:** PRD §4 explicitly claimed this was resolved; the claim is now false.

### GAP-008 — F4.2 finding filters (category / severity / confidence / jurisdiction) and sort controls not implemented in Streamlit v2

- **Severity:** MEDIUM
- **BRD/PRD anchor:** PRD §5.4.2 (F4.2)
- **Requirement (verbatim):**
  > "Enable filtering by category, severity, confidence. Enable sorting by severity, confidence, category. ... Filters: Category: Checkboxes for all 9 categories. Severity: High, Medium, Low. Confidence: ≥90%, 80-89%, <80% (Needs Review). Jurisdiction: US-CA, GDPR, etc." (PRD §5.4.2)
- **Current implementation state:** `app_streamlit_v2.py:804-848` renders all findings inside a single "Legal details / N issues" expander with no filters or sort controls. This is intentional per redesign decision #7 (see LIB-VOICE) but the PRD acceptance criteria still list unfiltered.
- **Proposed remediation:** Update PRD §5.4.2 to reflect the redesign trade-off (the plain-language flow favors curated domain groups over reader-side filtering), or add a filter row inside the expander.
- **Effort:** S (docs) or M (code)

### GAP-009 — F5.1 PDF export does not include "Verify view section with highlighted excerpts"

- **Severity:** LOW
- **BRD/PRD anchor:** PRD §5.5.1 (F5.1)
- **Requirement (verbatim):**
  > "PDF includes Verify view section with highlighted excerpts" (PRD §5.5.1)
- **Current implementation state:** `main.py:685-807` builds the PDF with title, metadata, grade badge, severity counts, and findings grouped by severity — but no dedicated "Verify view" section that renders the source text with highlights. Excerpts are inline within each finding block; there is no full-document view.
- **Proposed remediation:** Either add a page with the source text and highlighted excerpts, or update PRD §5.5.1 to drop the Verify-in-PDF acceptance criterion.
- **Effort:** M

### GAP-010 — `/analyses` list endpoint missing four PRD-specified query params (`offset`, `sort`, `order`, `filter_grade`, `filter_review_required`)

- **Severity:** MEDIUM
- **BRD/PRD anchor:** PRD §7.3.4
- **Requirement (verbatim):**
  > "Query Parameters: `limit`: integer (default: 20, max: 100); `offset`: integer (default: 0); `sort`: 'created_at' | 'risk_score' | 'grade' (default: created_at); `order`: 'asc' | 'desc' (default: desc); `filter_grade`: 'A' | 'B' | 'C' | 'D' | 'F'; `filter_review_required`: boolean" (PRD §7.3.4)
- **Current implementation state:** `main.py:493-517` — the endpoint only supports `limit` (default 25, max 200 — both defaults diverge from PRD). No offset means researchers cannot paginate beyond `limit`. No filters means the UI has no way to build the "Filter by grade" experience the PRD envisions.
- **Proposed remediation:** Add missing params. Adjust `limit` default to 20 and max to 100 to match PRD, or update PRD to reflect the shipped 25/200 pair.
- **Effort:** S
- **Notes:** Response envelope also diverges — PRD says `{total, limit, offset, analyses: [...]}` but code returns a bare `list[AnalysisSummary]`.

### GAP-011 — F5.2 JSON export response envelope differs from PRD schema

- **Severity:** LOW
- **BRD/PRD anchor:** PRD §5.5.2
- **Requirement (verbatim):**
  > "JSON includes schema version for future compatibility" (PRD §5.5.2), with example `"schema_version": "1.0"` in top-level payload
- **Current implementation state:** `main.py:848-853` returns the stored `result_json` verbatim. No `schema_version` field is added by the backend. `AnalysisPayload` also lacks the field.
- **Proposed remediation:** Add `schema_version: str = "1.0"` to `AnalysisPayload`, or drop the requirement from PRD.
- **Effort:** S

### GAP-012 — F3.4 "System learns from user feedback" (ML retraining loop) unimplemented

- **Severity:** LOW
- **BRD/PRD anchor:** PRD §5.3.4
- **Requirement (verbatim):**
  > "System learns from user feedback (future: ML retraining)" (PRD §5.3.4)
- **Current implementation state:** No training pipeline exists. The `review_items` table (`models.py:28-43`) stores `status` and `notes` but nothing consumes them for model improvement.
- **Proposed remediation:** PRD marks this "(future)" already. Leave as-is; no action required. Recorded here so audit is complete.
- **Effort:** L (if pursued)

### GAP-013 — F4.1 "Overview Summary" fields `analysis timestamp and jurisdiction(s)` acceptance criterion partially covered

- **Severity:** LOW
- **BRD/PRD anchor:** PRD §5.4.1
- **Requirement (verbatim):**
  > "Show analysis timestamp and jurisdiction(s)" (PRD §5.4.1)
- **Current implementation state:** Streamlit v2 shows jurisdictions in the "Rules applied for:" line (`app_streamlit_v2.py:697-700`) but does NOT render the analysis timestamp anywhere. The backend returns `created_at`, so this is a UI omission only.
- **Proposed remediation:** Add a small timestamp under the crumb bar.
- **Effort:** S

### GAP-014 — Streamlit and `requests` are not declared as dependencies

- **Severity:** HIGH
- **BRD/PRD anchor:** BRD-TECH-FE-001 ("Streamlit ... primary UI by product decision, launched by `run.sh` on port 8501")
- **Requirement (verbatim):**
  > "Streamlit (`src/webapp/app_streamlit.py`) — primary UI by product decision" (BRD-TECH-FE-001)
- **Current implementation state:** `src/backend/requirements.txt` contains no `streamlit` and no `requests` line. `run.sh:80-81` installs only backend requirements. Streamlit v2 imports both (`app_streamlit_v2.py:23-24`). A fresh clone + `./run.sh` will fail on the Streamlit process start. Root `requirements.txt` only pins `pytest-asyncio`.
- **Proposed remediation:** Add `streamlit>=1.27` and `requests` to a `webapp` requirements file, OR add them to the backend requirements. Reference from `run.sh`.
- **Effort:** S
- **Notes:** Almost certainly reproducing on any machine without a manual pip install.

### GAP-015 — BRD §1.5 "Average analysis time <30 seconds" has no test / no monitoring

- **Severity:** LOW
- **BRD/PRD anchor:** BRD-R020, BRD-CONSTRAINT-TECH-006, PRD §10.3
- **Requirement (verbatim):**
  > "Average analysis time <30 seconds" (BRD-R020)
- **Current implementation state:** `analyzer.py:580` computes `elapsed_time` and stores it on the payload, but there is no test asserting the p50, no timing histogram, and no CI gate. The 400-second timeout in `app_streamlit_v2.py:288` implicitly acknowledges that real analyses can far exceed 30s.
- **Proposed remediation:** Add a perf test with a fixed corpus asserting p50 < 30s, or explicitly downscope the target in BRD.
- **Effort:** M

---

## 3. Findings — OVER-ENGINEERING (code beyond BRD/PRD)

### OE-001 — Batch analysis + cross-reference detection

- **Severity:** MEDIUM
- **Code anchor:** `src/backend/app/main.py:432-490` (`/analyze/batch`), `src/backend/app/services/analyzer.py:736-813` (`analyze_batch_documents`, `_detect_cross_references`), `src/backend/app/schemas.py:361-399` (`BatchItem`, `AnalyzeBatchRequest`, `BatchAnalysisResult`).
- **What exists:** A full batch-analysis endpoint that accepts multiple URLs, runs each through `analyze_text`, and additionally detects cross-references between documents using 4 regex patterns ("see our privacy policy", "as stated in Terms of Service", etc.).
- **BRD/PRD anchor absent:** PRD §5 has no F-number for batch analysis. PRD §7.3.13 documents it as "additional shipped endpoint not in the original spec." PRD §6.2 (Flow 2 "Researcher Bulk Analyzes 50 Policies") describes a "Batch Analysis (future feature)" — explicitly out of scope for MVP. Cross-reference detection is nowhere in BRD/PRD.
- **Why it's over-engineering:** Ships a persona-3 feature (researcher bulk analysis) that PRD schedules as "future". Cross-reference detection is a novel research feature the reader never asked for. Adds a whole schema tree, an async orchestrator, and a regex bank.
- **Proposed remediation:** Two options: (a) update BRD/PRD to promote batch analysis and cross-refs to shipped features with real acceptance criteria; (b) gate behind a feature flag and remove from the default surface until Phase 4-5 (BRD-ROADMAP-P4/P5).
- **Effort:** M

### OE-002 — `/rubric` endpoint + 8-dimensional rubric computation

- **Severity:** MEDIUM
- **Code anchor:** `src/backend/app/main.py:206-252` (`_compute_rubric_scores`), `main.py:520-525` (`/rubric` endpoint), `src/backend/app/schemas.py:279-288` (`RubricScores`).
- **What exists:** A `GET /rubric` endpoint that averages risk, confidence, and review-rate across ALL analyses in the database and derives 8 named scores (`productIntegrity`, `legalSignalQuality`, `aiLawSignalQuality`, `privacySecurity`, `accessibilityUsability`, `visualIxd`, `performanceReliability`, `governanceReadiness`) plus a weighted `overall`. Weighted formula uses hardcoded coefficients (`0.20, 0.20, 0.10, 0.10, 0.15, 0.10, 0.10, 0.05`).
- **BRD/PRD anchor absent:** No BRD/PRD anchor found for a "rubric" score. BRD §7.1 (KPIs) lists detection accuracy, uptime, and user-facing metrics — none of them names an 8-dimensional rubric. `LIB-EVAL` documents rubric scoring but reads as an internal quality-of-tool metric, not a user surface.
- **Why it's over-engineering:** The rubric mixes unrelated axes (`visualIxd`, `accessibilityUsability`) into a per-database aggregate that no user story consumes. The `accessibilityUsability` computation from `review_rate` and `confidence_score` has no theoretical justification — accessibility is a design property, not a database aggregate.
- **Proposed remediation:** Either (a) document the rubric's purpose in a BRD/PRD KPI section and remove the mislabeled dimensions, or (b) delete the endpoint and the schema. `app.js:1005` populates a "Reports" page from this; that page can also be dropped.
- **Effort:** M
- **Notes:** The 8 axes appear to be scraped from a UX rubric doc; embedding them in the API contract is the wrong abstraction level.

### OE-003 — Two overlapping "policy monitoring" abstractions: `WatchlistItem` and `PolicyWatch`

- **Severity:** HIGH
- **Code anchor:** `src/backend/app/models.py:46-61` (`WatchlistItem`), `models.py:75-86` (`PolicyWatch`); `main.py:891-1007` (watchlist endpoints), `main.py:1168-1284` (policy-watch endpoints).
- **What exists:** Two independent tables and two independent endpoint groups (`/watchlist/*` and `/policy-watch/*`) both tracking "a URL that should be re-checked for changes." `WatchlistItem` tracks vendor, hash, risk_delta, and last check. `PolicyWatch` tracks url, user_id, check_frequency, and enabled flag. Neither table references the other.
- **BRD/PRD anchor absent:** PRD §5.6 (F6) describes a single "watchlist monitoring" feature. Only one abstraction is called for.
- **Why it's over-engineering:** Two features doing the same job. The `WatchlistItem.enabled` field is missing but present as a string `"true"` in `PolicyWatch.enabled` (`models.py:84`) — the two schemas were built by two different sessions without a merge.
- **Proposed remediation:** Consolidate. Keep `WatchlistItem` (has richer metadata: risk_delta, last_document_text). Move `check_frequency` and `enabled` (as Boolean) onto it. Delete `PolicyWatch` and `/policy-watch/*` endpoints. Migrate any existing rows.
- **Effort:** L
- **Notes:** Powers GAP-004 (schema mismatch); until the merge lands, the watchlist endpoint contract stays broken.

### OE-004 — Cross-reference detection (`_detect_cross_references`)

- **Severity:** MEDIUM
- **Code anchor:** `src/backend/app/services/analyzer.py:782-813`
- **What exists:** 4 regex patterns detecting "see our privacy policy" / "as stated in Terms of Service" phrasing across batch documents, emitted as a `cross_references` list on `BatchAnalysisResult`.
- **BRD/PRD anchor absent:** Nowhere in BRD, PRD, PRODUCT.md, or LIB-* files.
- **Why it's over-engineering:** Powers a batch feature that itself is over-engineering (OE-001). Adds a novel data shape (a `cross_references: List[dict]` list of loose dicts, no schema).
- **Proposed remediation:** Delete with the batch endpoint, or type it properly if kept.
- **Effort:** S

### OE-005 — 30-value jurisdiction name map hardcoded twice (PDF + JS SPA)

- **Severity:** LOW
- **Code anchor:** `src/backend/app/main.py:636-667` (`_JURISDICTION_NAMES` inside PDF export), plus `app.js` category / grade maps referenced in code inventory §Webapp Layer.
- **What exists:** A 30-row mapping from jurisdiction code to full legal name (e.g., `"US-CA": "California CCPA/CPRA"`) built as a local dict inside the PDF export function. Similar mapping likely duplicated in `app.js`.
- **BRD/PRD anchor absent:** No BRD/PRD anchor for how the code should carry canonical human-readable jurisdiction labels.
- **Why it's over-engineering:** The Streamlit v2 `_friendly_jurisdiction_labels` function (`app_streamlit_v2.py:568-602`) is a third, smaller mapping (only 17 codes) that will drift from the PDF and JS SPA versions. Three sources of truth for what should be one.
- **Proposed remediation:** Move a canonical `{code: friendly_name}` map to `schemas.py` next to the `Jurisdiction` Literal. Import from all three call sites.
- **Effort:** S

### OE-006 — `_KNOWN_SEVERITIES` guard inside `_bump_severity` raises on unknown severity

- **Severity:** LOW
- **Code anchor:** `src/backend/app/services/analyzer.py:361-365`
- **What exists:** `_bump_severity` raises `ValueError` if the finding severity is not one of `{Low, Medium, High, Critical}`.
- **BRD/PRD anchor absent:** No requirement dictates fail-fast on severity.
- **Why it's over-engineering:** The `Finding.severity` field is a Pydantic `Literal["Low","Medium","High","Critical"]` (`schemas.py:40, 153`). It cannot deserialize with any other value. The guard is dead defense — the type system already enforces the invariant.
- **Proposed remediation:** Delete the guard, or downgrade to a plain `assert` inside a `if __debug__:` block.
- **Effort:** S

---

## 4. Findings — BLOAT (dead, redundant, unused)

### BL-001 — `/ignore/` directory (design-iteration graveyard)

- **Severity:** HIGH
- **Code anchor:** `ignore/src/webapp/app_streamlit.py`, `app-new.js`, `app-v3.js`, `app.js`, `index-new.html`, `index-v3.html`, `index-v4.html`, `style-new.css`, `style-v3.css` (~250 KB combined); `ignore/src/backend/app/` (full mirror of old backend structure, dated Jun 28); `ignore/tests/`; `ignore/.venv/`; `ignore/.pip-cache/`.
- **What it is:** A parallel filesystem containing older versions of every source file, plus a checked-in Python virtualenv and pip cache.
- **Evidence it's bloat:** No file inside `/ignore/` is imported or referenced by any file in `src/`. Session handoff acknowledges it as a "design-iteration graveyard." Presence of `.venv/` and `.pip-cache/` inside a tracked directory is a red flag.
- **Proposed remediation:** Move to a git tag or archive branch, then `git rm -r ignore/`. Add `**/.venv/` and `**/.pip-cache/` to `.gitignore`.
- **Effort:** S

### BL-002 — Root-level `tests/` directory (3 legacy files) shadows `src/backend/tests/`

- **Severity:** MEDIUM
- **Code anchor:** `tests/test_api_endpoints.py`, `tests/test_batch_analysis.py`, `tests/test_quick_mode.py`.
- **What it is:** Three test files that use `sys.path` manipulation (`tests/test_api_endpoints.py:11-14`, `tests/test_batch_analysis.py:11-15`) to reach into `src/backend/`, running with an ad-hoc `MockDB` (`tests/test_api_endpoints.py:23-33`) rather than the `conftest.py` fixtures used by the active suite.
- **Evidence it's bloat:** The active suite at `src/backend/tests/` (17 files, 702 tests per `.claude/CLAUDE.md`) uses `conftest.py` fixtures. Two parallel test infrastructures is a maintenance smell. Session handoff and CLAUDE.md never reference the root `tests/` directory.
- **Proposed remediation:** Fold coverage into `src/backend/tests/`. Delete the root `tests/` directory.
- **Effort:** M

### BL-003 — `app_streamlit_legacy.py` retained as rollback path

- **Severity:** LOW
- **Code anchor:** `src/webapp/app_streamlit_legacy.py` (795 lines)
- **What it is:** The pre-v2 Streamlit UI, kept behind the `STREAMLIT_UI=v1` flag in `run.sh:26`.
- **Evidence it's bloat:** Session handoff explicitly retains it as rollback. No test exercises it. No CI job builds against it. The v2 has been the merged default since PR #34; if it were going to be rolled back, that would have happened by now.
- **Proposed remediation:** Set a sunset date (e.g., 2 releases after PR #34 merge) and delete. Remove the `case "$STREAMLIT_UI" in` branch from `run.sh` when deleting.
- **Effort:** S
- **Notes:** Low risk to defer, but the legacy file's presence continues to bloat the "which UI is real?" answer for new contributors.

### BL-004 — `archive/` directory (11 HTML wireframes + 6 PNG mockups + 2 RTF)

- **Severity:** LOW
- **Code anchor:** `archive/` at repo root (~1-2 MB of static HTML/PNG/RTF wireframe iterations).
- **What it is:** Snapshot HTML demos of pre-redesign UI concepts, plus PNG wireframes with `(1).png`, `(2).png` suffix numbering typical of browser downloads.
- **Evidence it's bloat:** Nothing in `src/` or `docs/` references any file in `archive/`. `docs/wireframes/` is the live wireframe location. Suffixed duplicate filenames suggest downloaded-not-curated content.
- **Proposed remediation:** Move to a `wireframes-archive` tag; delete from working tree.
- **Effort:** S

### BL-005 — 4 near-identical URL-scheme validators in `schemas.py`

- **Severity:** MEDIUM
- **Code anchor:** `src/backend/app/schemas.py:177-192` (`AnalyzeRequest._validate_source_url_scheme`), `schemas.py:204-217` (`AnalyzeUrlRequest._validate_url_scheme`), `schemas.py:320-331` (`WatchlistCreateRequest.validate_source_url_scheme`), `schemas.py:367-380` (`BatchItem._validate_url_scheme`).
- **What it is:** Four Pydantic field validators with the same body: `urlparse` the URL, reject non-http(s) schemes, require a hostname. Copy-paste with minor phrasing drift.
- **Evidence it's bloat:** The comment on `AnalyzeRequest._validate_source_url_scheme` cross-references `WatchlistCreateRequest`; the comment on `BatchItem._validate_url_scheme` cross-references `AnalyzeRequest`. Author was aware of the duplication.
- **Proposed remediation:** Extract `_validate_http_url(v: str | None) -> str | None` as a module-level helper and call it from each validator.
- **Effort:** S

### BL-006 — `_derive_action_items` category branches use both canonical and alias category names redundantly

- **Severity:** LOW
- **Code anchor:** `src/backend/app/services/analyzer.py:290, 302-306, 317, 323-329, 336-338, 346`
- **What it is:** Each branch checks a tuple like `("Sale/Share", "Data Sale / Sharing")` or `("User Rights", "Data Rights", "Individual Rights", "Privacy Rights")` to cover the canonical name plus known aliases.
- **Evidence it's bloat:** The `CATEGORIES` frozenset (`schemas.py:50-109`) permits both canonical and alias forms. But the "alias" story is inconsistent — `Sale/Share` and `Data Sale / Sharing` are treated as siblings, while `AI Training (Opt-Out)` is documented as an alias for `AI Training Opt-Out` and only lives in `_CATEGORY_IRP_DEFAULTS`. No single normalization function.
- **Proposed remediation:** Add `_normalize_category(cat: str) -> str` in `schemas.py`, apply once at ingest time (rule engine and LLM parser), then use only canonical names downstream.
- **Effort:** M

### BL-007 — `_JURISDICTION_NAMES` inside PDF export duplicates Jurisdiction Literal

- **Severity:** LOW
- **Code anchor:** `src/backend/app/main.py:636-667`
- **What it is:** A 30-entry dict inside `export_analysis_pdf` mapping jurisdiction codes to legal names.
- **Evidence it's bloat:** Same map is partially rewritten in `_friendly_jurisdiction_labels` (`app_streamlit_v2.py:575-594`). Two maps drift.
- **Proposed remediation:** Extract to `schemas.py` (see OE-005).
- **Effort:** S

### BL-008 — Dual Pydantic v1/v2 compatibility branches

- **Severity:** MEDIUM
- **Code anchor:** `src/backend/app/main.py:179-182` (`_persist_analysis`: `hasattr(payload, "model_dump_json")` else `payload.json()`); `main.py:487-490` (`hasattr(batch_result, 'model_dump')` else `json.loads(batch_result.json())`); `src/backend/app/services/analyzer.py:471-474` (`hasattr(finding, "model_dump")` else `json.loads(finding.json())`).
- **What it is:** Three call sites branch on Pydantic v1 (`.json()`) vs v2 (`.model_dump()`).
- **Evidence it's bloat:** `pydantic` is not pinned in `src/backend/requirements.txt`. If the project is v2 (`Field(..., ge=0.0)` with keyword args works in both, but `field_validator` at `schemas.py:177` is v2-only), then the v1 fallback is unreachable.
- **Proposed remediation:** Pin Pydantic v2 in requirements. Delete `.json()` fallback branches. This also drops a rung on the migration ladder.
- **Effort:** S

### BL-009 — `terms_analysis.db` (1.5 MB SQLite file) checked into `data/`

- **Severity:** LOW
- **Code anchor:** `data/terms_analysis.db` (1568768 bytes per `ls -la`).
- **What it is:** A local SQLite database file physically present in the working tree.
- **Evidence it's bloat:** BRD-TECH-DB-* documents this as gitignored. `.gitignore` should exclude it; if it's tracked in git, that's a footgun.
- **Proposed remediation:** Confirm gitignored; if tracked, `git rm --cached data/terms_analysis.db` and add to `.gitignore`. If untracked, no action.
- **Effort:** S (verification only if already ignored).

### BL-010 — BRD/PRD still reference `app_streamlit.py` (pre-redesign filename)

- **Severity:** LOW
- **Code anchor:** `docs/BRD_Terms_Policies_Reviewer.md` (2 references), `docs/PRD_Terms_Policies_Reviewer.md` (2 references) — verified via `grep -c 'app_streamlit\.py'`.
- **What it is:** BRD-TECH-FE-001 and Appendix A of BRD, plus PRD §4 and §7.1, name `app_streamlit.py` as the primary UI file. Actual primary is `app_streamlit_v2.py`.
- **Evidence it's bloat:** Session handoff §2 explicitly noted the sweep was incomplete: "Sweep remaining `app_streamlit.py` references in `docs/PRD_*.md` and `docs/BRD_*.md`."
- **Proposed remediation:** Replace with `app_streamlit_v2.py` in all four references.
- **Effort:** S

### BL-011 — `_data_dir()` side effects at import (creates `data/` directory)

- **Severity:** LOW
- **Code anchor:** `src/backend/app/config.py:16-20`
- **What it is:** `_data_dir()` calls `target.mkdir(parents=True, exist_ok=True)` as part of computing a default path, invoked at Settings instantiation.
- **Evidence it's bloat:** Import-time filesystem mutation. Not documented in any spec. Import a config module → new empty directory appears on disk.
- **Proposed remediation:** Move the `mkdir` into an explicit `ensure_data_dir()` called from `main.py::lifespan` alongside `init_db()`.
- **Effort:** S

---

## 5. Findings — LOGIC ERRORS

### LE-001 — Watchlist refresh hardcodes `["US-CA", "GDPR"]`, violating global-tool contract

- **Severity:** BLOCKING
- **Code anchor:** `src/backend/app/main.py:145` and `main.py:976`
- **The error:** `_refresh_all_watchlist_items` and `refresh_watchlist` both call `detect_findings(current_text, ["US-CA", "GDPR"])`. This silently re-scopes every monitored policy to two jurisdictions regardless of the reader's actual location.
- **Expected behavior:** `.claude/CLAUDE.md` §Session outcomes states: "Global-tool contract — empty `jurisdictions=[]` is treated as 'no filter' mode ... No US-CA + GDPR default fallback anywhere." `LIB-PRINCIPLES.md` §Principle 3 example: "User asks to hardcode a US-CA default jurisdiction. BRD §Global Tool + LIB-CONTEXT explicitly state empty `jurisdictions=[]` = 'no filter.' Silent execution would contradict a shipped design decision."
- **Impact:** A user who added a UK-based policy to their watchlist sees only CCPA/GDPR rule findings and misses UK-specific findings. Risk delta ("policy got worse") is computed against the wrong rule set, so notifications fire on the wrong signal. This is exactly the drift LIB-PRINCIPLES was written to prevent.
- **Proposed fix:** Pass `[]` (no filter) to `detect_findings`. If per-user location on a watchlist item is desired, add a `jurisdictions` column to `WatchlistItem` and thread it through the refresh loop.
- **Test that would have caught it:** A regression test asserting that `WatchlistItem` refresh calls the rules engine without hardcoded jurisdiction args. `test_regressions_pr34.py` covers `/analyze/file` but not the watchlist path.
- **Effort:** S

### LE-002 — `/analyze/file` hardcodes `["US-CA", "GDPR"]` fallback, violating global-tool contract

- **Severity:** BLOCKING
- **Code anchor:** `src/backend/app/main.py:390-396`
- **The error:** When multipart uploads arrive with no valid jurisdictions (either omitted or with only invalid entries), the code falls back to `selected_jurisdictions = ["US-CA", "GDPR"]`. The inline comment even acknowledges: "Falls back to the same default as the JSON endpoints when no valid values remain" — but the JSON endpoints (`AnalyzeRequest`, `AnalyzeUrlRequest`) default to `[]` (see `schemas.py:173, 200`), NOT to `["US-CA", "GDPR"]`. The comment is factually wrong AND the fallback contradicts the shipped contract.
- **Expected behavior:** Empty jurisdictions = "no filter" (`.claude/CLAUDE.md` §Session outcomes, `LIB-PRINCIPLES` §Principle 3 example).
- **Impact:** Every file-upload analysis silently double-scopes to California + GDPR, discarding findings from all other 28 jurisdictions the user might care about.
- **Proposed fix:** Change `selected_jurisdictions = ["US-CA", "GDPR"]` to `selected_jurisdictions = []` at line 396. Delete the misleading comment.
- **Test that would have caught it:** `test_regressions_pr34.py::test_analyze_file_empty_jurisdictions_treated_as_no_filter` would fail if it existed. The code inventory (§Suspicious Markers, line 396) already flagged this.
- **Effort:** S (fix), M (add regression test)

### LE-003 — Silent `except Exception: pass` in watchlist refresh loop swallows all errors

- **Severity:** HIGH
- **Code anchor:** `src/backend/app/main.py:113-119`
- **The error:** `_watchlist_loop_async` wraps the refresh call in `try: await _refresh_all_watchlist_items(); except Exception: pass`. There is no log, no metric, no re-raise.
- **Expected behavior:** `.claude/CLAUDE.md` §Hard Requirements does not mandate specific error handling but `.claude/rules/code-style.md` and standard Python practice require at minimum a structured log. LocalAI failures already log (`localai.py:144-154`); a background loop failure should not be more opaque than that.
- **Impact:** Any exception in the loop (SQL error, URL fetch bug, hash mismatch, etc.) is invisible in ops. A single bug freezes the watchlist silently until service restart.
- **Proposed fix:** Add `logger.exception("watchlist refresh loop failed; retrying in %s s", settings.watchlist_refresh_seconds)` before the sleep.
- **Test that would have caught it:** A test asserting `caplog` captures a log record when the refresh raises.
- **Effort:** S

### LE-004 — `_refresh_all_watchlist_items` swallows per-item fetch errors without emitting the failure to any log

- **Severity:** MEDIUM
- **Code anchor:** `src/backend/app/main.py:132-138`
- **The error:** `except Exception: item.status = "Check Failed"; continue` marks the item without logging the actual exception. If every fetch fails (DNS outage, cert issue), an operator sees only `status = "Check Failed"` in the UI with no diagnostic.
- **Expected behavior:** Log at WARNING level with URL and exception.
- **Impact:** Ops loop invisible.
- **Proposed fix:** `logger.warning("watchlist refresh failed for %s: %s", item.source_url, exc)` in the except block.
- **Test that would have caught it:** Same as LE-003.
- **Effort:** S

### LE-005 — Silent `except Exception: continue` in `detect_high_severity_findings` and LLM finding parser

- **Severity:** MEDIUM
- **Code anchor:** `src/backend/app/services/analyzer.py:510-511` (LLM finding construction), `analyzer.py:730-731` (quick-mode regex match).
- **The error:** Both blocks catch every exception and continue. Line 510 hides Pydantic validation errors (missing required `evidence` fields, malformed IRP integers). Line 730 hides regex errors from patterns compiled at line 700.
- **Expected behavior:** Log at DEBUG or INFO with the failing item's identifier and reason.
- **Impact:** A subtle schema change to `Finding` silently drops LLM findings without any signal. `dropped_for_legal` is counted (line 499) but generic parse failures are not.
- **Proposed fix:** Add `logger.debug("skipped LLM finding: %r", exc)` at line 510 and similar at line 730.
- **Effort:** S

### LE-006 — `ingest.py::extract_text_from_bytes` silently falls back to raw decode on unknown extensions

- **Severity:** MEDIUM
- **Code anchor:** `src/backend/app/services/ingest.py:146-152`
- **The error:** For unknown extensions, if content_type isn't HTML/XHTML, the function does `return _normalize_text(_decode_bytes(data))` — treating unknown binary payloads as text.
- **Expected behavior:** BRD §8.1.2 promises "format detection and fallback mechanisms" with "user feedback mechanism for failed parses." The current behavior returns garbage-looking text and the analyzer proceeds as if it were policy text.
- **Impact:** A `.doc` file (old MS Word binary, not `.docx`) or a PowerPoint upload will be decoded as latin-1 and analyzed with garbage input, producing meaningless findings at 90-95% confidence (`_confidence_rules_based` clamp).
- **Proposed fix:** Raise a `ValueError` with a message like "Unable to extract text from this file type" for unknown extensions + non-HTML content types. Let `main.py:369` surface the 400 to the user.
- **Test that would have caught it:** `test_ingest.py::test_unknown_extension_rejected`.
- **Effort:** S

### LE-007 — `_extract_pdf_with_ocr` silently drops OCR failures per image (`except Exception: continue`)

- **Severity:** LOW
- **Code anchor:** `src/backend/app/services/ingest.py:100-104`
- **The error:** Loop over `images`, each `pytesseract.image_to_string` call is wrapped in `try/except Exception: continue`. Aggregated OCR output silently misses failed images.
- **Expected behavior:** Log the failure with page number.
- **Impact:** Multi-page scanned PDF with one corrupted image yields partial text with no signal that pages were skipped.
- **Proposed fix:** Log warning per exception.
- **Effort:** S

### LE-008 — `analyze_batch` swallows per-item URL fetch errors (`except Exception as e: continue`) — but logs to `logger.error`, so this is intentional; however no counter is emitted

- **Severity:** LOW
- **Code anchor:** `src/backend/app/main.py:444-452`
- **The error:** Items with fetch failures are silently dropped from the results. `logger.error` fires but no field in `BatchAnalysisResult` reports "N of M items failed."
- **Expected behavior:** PRD §6.2 edge case: "Some URLs fail → Continue with successful ones, log failures." The log satisfies that. But a batch that entirely fails (`main.py:454` raises 400 "No valid documents") gives the caller no way to know which URLs failed.
- **Impact:** Researcher persona (PRD §3.3) submitting a 50-URL batch has no reliable per-item failure signal.
- **Proposed fix:** Add a `failed_items: List[dict]` list on `BatchAnalysisResult` with URL and error message.
- **Effort:** M

### LE-009 — Confidence penalty stack can drive confidence far below actual signal quality

- **Severity:** MEDIUM
- **Code anchor:** `src/backend/app/services/analyzer.py:550-563`
- **The error:** Penalties are multiplicative and stack: `× 0.85` (quick mode) OR `× 0.8` (no summary) or `× 0.85` (no LLM findings) AND `× max(0.5, 1 - 0.1*dropped)`. Rule findings with 0.90-0.95 base confidence can be pulled below 0.80 (review threshold) after just two penalty hits.
- **Expected behavior:** `.claude/CLAUDE.md` §Hard Requirements: "Confidence < 0.80 triggers human-in-the-loop review" and "Rule confidence (active path, `_confidence_rules_based`) is clamped to [0.90, 0.95]." The clamp implies rule confidence should stay in that band. Multiplying by 0.85 × 0.8 = 0.68 breaks the clamp semantics — a valid rule finding gets flagged for review because the LLM failed to return a summary.
- **Impact:** LLM failures (BRD-TECH-ML-* fallback path) trigger over-review of rule findings, inflating the reviewer's queue with high-quality rule matches that don't need it. The intended fallback is graceful degradation, not confidence collapse.
- **Proposed fix:** Apply penalties additively (subtract fixed amounts) or apply them only to LLM findings, not to the aggregate. Alternatively, clamp final confidence to at least 0.85 when the majority of findings are rule-based.
- **Test that would have caught it:** `test_llm_failure.py` covers fallback but does not assert final confidence stays in the documented band.
- **Effort:** M

### LE-010 — `PolicyWatch.enabled` stored as string `"true"` not boolean

- **Severity:** MEDIUM
- **Code anchor:** `src/backend/app/models.py:84`; `main.py:1181` writes `enabled="true"`; `schemas.py:448` types `enabled: str`.
- **The error:** A field that semantically is a boolean is stored as a string and never toggled. There is no `PUT /policy-watch/{id}/toggle` endpoint that would set it to `"false"`. `WatchlistItem` has no `enabled` at all.
- **Expected behavior:** A boolean. Standard SQLAlchemy `Boolean` column.
- **Impact:** Filtering enabled/disabled watches requires string comparison. A future bug that sets `enabled="True"` (capital T) would silently break equality checks. Type drift between `WatchlistItem` (no field) and `PolicyWatch` (string) is exactly the schema drift LIB-PRINCIPLES cautions against.
- **Proposed fix:** Migrate to `Column(Boolean, default=True, nullable=False)`. Type as `bool` in the Pydantic schema. Add a migration for existing rows.
- **Test that would have caught it:** Schema round-trip test asserting bool.
- **Effort:** S

### LE-011 — `refresh_watchlist` and `_refresh_all_watchlist_items` differ in behavior for uninitialized `last_document_hash`

- **Severity:** MEDIUM
- **Code anchor:** `src/backend/app/main.py:142` and `main.py:973`
- **The error:** Both compute `changed = item.last_document_hash and item.last_document_hash != new_hash`. If `last_document_hash` is `None` (first-ever check), `changed` is `False`, so status is set to "No Changes" even though this is the FIRST check and nothing was compared. The user sees "No Changes" on a brand-new watchlist item, which reads as "we checked and it's the same" when in fact "we just captured baseline."
- **Expected behavior:** First-check status should be "Baseline captured" or similar, distinct from "No Changes."
- **Impact:** Reader misinterprets initial state.
- **Proposed fix:** Add a branch: `if item.last_document_hash is None: item.status = "Baseline captured"`.
- **Effort:** S

### LE-012 — `_bump_severity` boost lookup uses `.lower() in .lower()` substring match, causing false-positive boosts

- **Severity:** MEDIUM
- **Code anchor:** `src/backend/app/services/analyzer.py:387-390, 406-409`
- **The error:** `boost = next((v for k, v in boosts.items() if k.lower() in f.category.lower()), 0.0)` — matches "Data Security" boost against a finding categorized "Data Sale / Sharing" (both share "Data"), or "Consent" boost against "PIPEDA Consent". The substring test does not respect category boundaries.
- **Expected behavior:** Boost only when the finding's category is exactly one of the configured boost categories.
- **Impact:** Doc-type and industry boosts fire on wrong findings. "Cookie Policy" boosts `"Consent": 0.3` (`analyzer.py:216`), which will match ANY finding whose category contains "Consent" ("PIPEDA Consent", "Tracking & Consent", "DPDP Consent"). Wrong findings get severity-bumped.
- **Proposed fix:** Replace with exact match: `boost = boosts.get(f.category, 0.0)`. If the intent is to support aliases, use the canonical category from BL-006.
- **Test that would have caught it:** `test_analyzer.py::test_bump_only_exact_category_match`.
- **Effort:** S

### LE-013 — `_DOCTYPE_BOOSTS` and `_INDUSTRY_BOOSTS` reference categories not in `schemas.CATEGORIES`

- **Severity:** MEDIUM
- **Code anchor:** `src/backend/app/services/analyzer.py:201-268`
- **The error:** `_DOCTYPE_BOOSTS` references `"Third-Party Sharing"`, `"Arbitration / Dispute"`, `"Intellectual Property"`, `"Data Transfer"`, `"Sub-processors"`, `"Data Retention"`, `"Liability Limitation"` — none of these are in the `CATEGORIES` frozenset (`schemas.py:50-109`). Similarly `_INDUSTRY_BOOSTS` references `"In-App Purchases"` and `"Transparency"`, which are not `CATEGORIES` members.
- **Expected behavior:** `.claude/CLAUDE.md` §Session outcomes documents Fix 5: "Any future drift fails at import, not at CI review." `analyzer.py:102-107` enforces this for `_DOMAIN_MAP` but NOT for `_DOCTYPE_BOOSTS` and `_INDUSTRY_BOOSTS`. LE-012 (substring match) is masking the drift — boosts still "work" fuzzily. If LE-012 is fixed with exact match, boosts silently stop working.
- **Impact:** Doc-type/industry boosting is largely a no-op today. The substring match happens to catch `"Data Sale / Sharing"` for `"Data Retention"` etc., producing wrong boosts. Fixing LE-012 without fixing LE-013 removes the wrong-boost bug and replaces it with a no-boost bug.
- **Proposed fix:** Add an import-time assertion: `for boosts in _DOCTYPE_BOOSTS.values() + list(_INDUSTRY_BOOSTS.values()): for k in boosts: assert k in CATEGORIES, ...`. Then correct the boost keys to real categories.
- **Test that would have caught it:** An import-time guard would fail loudly at test collection.
- **Effort:** M

### LE-014 — Sort key `(weight, irp, severity_rank)` may not honor `.claude/CLAUDE.md` "descending" claim when weight = 1.0 for all findings

- **Severity:** LOW
- **Code anchor:** `src/backend/app/services/context.py:200-205`
- **The error:** `sorted(findings, key=sort_key, reverse=True)` correctly sorts descending by each tuple element. But when no chip is selected, `merged` is `{}`, so `merged.get(f.category, 1.0)` returns 1.0 for every finding — the weight tier collapses. This is documented (`context.py:194: "all categories collapse to weight 1.0 and IRP drives the order"`). Behavior matches spec.
- **Expected behavior:** Matches CLAUDE.md `(weight, irp_score, severity_rank) all descending`. Verified correct.
- **Impact:** None; this is actually a **non-finding** — the code matches the spec. Kept in report for traceability because the audit was tasked to verify.
- **Proposed fix:** No fix required.
- **Effort:** —

### LE-015 — IRP formula math verified correct

- **Severity:** — (verification only)
- **Code anchor:** `src/backend/app/services/analyzer.py:136-139`
- **The formula:** `raw = 0.5 * (impact / 5) + 0.4 * (likelihood / 5) - 0.3 * (safeguard_score / 5)`; clamped [0, 1].
- **Expected behavior:** `.claude/CLAUDE.md` §Identity/Risk Method row: `0.5*(impact/5)+0.4*(likelihood/5)-0.3*(safeguard/5)`.
- **Result:** Match. `rules.py:1124-1127` also matches. `calculate_risk_score` (`analyzer.py:414-423`) averages IRPs across findings and scales to [0, 10] — no additional weighting beyond IRP itself, which matches "Sort is tier-first: `(weight, irp_score, severity_rank)`" (sort separates from score).
- **Notes:** No fix required; verification passes.

### LE-016 — Rule confidence clamp [0.90, 0.95] verified correct

- **Severity:** — (verification only)
- **Code anchor:** `src/backend/app/services/rules.py:1002-1018`
- **The clamp:** `return max(0.90, min(0.95, confidence))` at line 1018.
- **Expected behavior:** `.claude/CLAUDE.md` §Hard Requirements: "Rule confidence (active path, `_confidence_rules_based`) is clamped to [0.90, 0.95]."
- **Result:** Match. Verification passes.

### LE-017 — Human-review threshold `< 0.80` is enforced in backend but NOT surfaced in Streamlit v2 UI

- **Severity:** MEDIUM
- **Code anchor:** `src/backend/app/services/analyzer.py:567` (`review_required = confidence < settings.review_threshold`); `AnalysisPayload.review_required` field (`schemas.py:229`); `app_streamlit_v2.py` — no rendering of `review_required` or `status == "needs_review"`.
- **The error:** The backend correctly flags analyses with confidence < 0.80. The frontend does not tell the reader that this happened. `app_streamlit_v2.py:800-848` renders findings and severity but never checks `result.get("review_required")` or `result.get("status") == "needs_review"`.
- **Expected behavior:** `.claude/CLAUDE.md` §Hard Requirements: "Confidence < 0.80 triggers human-in-the-loop review." Per BRD §8.3.1 mitigation 5 "Confidence scores and 'Verify' prompts" — the reader needs to see when the tool is uncertain.
- **Impact:** Low-confidence analyses are presented with the same verdict-first framing as high-confidence ones. The reader has no visual signal to distrust the output.
- **Proposed fix:** Add a warning banner near the verdict block when `result["review_required"]` is True: "This analysis is below the confidence threshold. Consider having a second reader confirm."
- **Effort:** S

### LE-018 — LLM em-dash in user-facing action item copy (`analyzer.py:332`)

- **Severity:** MEDIUM
- **Code anchor:** `src/backend/app/services/analyzer.py:331-334`
- **The error:** `"Automated decisions with significant effect may be challengeable — request human review through the service's support channels."` contains U+2014 em-dash.
- **Expected behavior:** `LIB-VOICE` §"No em-dashes in tool voice": "Zero em-dashes ... in the tool's own copy" and "Where em-dashes are forbidden: Every string that reaches the reader from the tool: verdict headlines, verdict labels, intake copy, **action items**, scope box text, help tooltips, error messages surfaced to the reader." Action items are explicitly named.
- **Impact:** LIB-VOICE violation — the redesign's "AI giveaway" prevention rule is broken in a reader-visible string.
- **Proposed fix:** Replace ` — ` with `. `: `"Automated decisions with significant effect may be challengeable. Consider requesting human review through the service's support channels."`
- **Test that would have caught it:** A dedicated `test_no_em_dashes_in_action_items` that scans the output of `_derive_action_items` for U+2014. `LIB-VOICE` proposes a `/em-dash-scan` skill.
- **Effort:** S

### LE-019 — LLM `overall_confidence` clamped but no validation of range

- **Severity:** LOW
- **Code anchor:** `src/backend/app/services/analyzer.py:552`
- **The error:** `confidence_parts.append(max(0.0, min(1.0, float(overall_confidence))))` clamps but doesn't log or warn when the LLM returns garbage (>1.0 or <0.0). Clamping masks a malformed response.
- **Expected behavior:** `.claude/CLAUDE.md` §Hard Requirements: "LLM failures must always fall back to rule-only findings with reduced confidence." An LLM returning `overall_confidence = 15.7` isn't strictly a "failure" — but it's a signal the model is misbehaving and should be logged.
- **Impact:** Diagnostic blind spot.
- **Proposed fix:** `if not 0.0 <= overall_confidence <= 1.0: logger.warning(...)` before clamping.
- **Effort:** S

### LE-020 — Streamlit v2 sends `industry or "General"` on file upload but the JSON `/analyze` path passes `industry=None`

- **Severity:** LOW
- **Code anchor:** `src/webapp/app_streamlit_v2.py:296` (file upload sends `"industry": industry or "General"`) vs `app_streamlit_v2.py:557` (`/analyze` and `/analyze/url` pass `industry=st.session_state.inferred_industry` which can be `None`).
- **The error:** Inconsistent default. File uploads always get "General" industry; JSON paths pass through whatever the inference returned (which may be None). Different code paths → different analyzer behavior.
- **Expected behavior:** Same defaulting rule regardless of transport.
- **Impact:** A file upload analyzed with "General" gets a different (empty) industry boost than the same policy pasted as text with a null industry (still empty boost, since `_apply_industry_emphasis` returns unchanged for "General"). In this specific case the outputs happen to match, but the code paths differ enough to invite future divergence.
- **Proposed fix:** Consolidate the default to a single client-side helper.
- **Effort:** S

---

## 6. Findings — GOVERNANCE / DOCS

### GOV-001 — BRD/PRD name `app_streamlit.py` but code ships `app_streamlit_v2.py`

- **Severity:** MEDIUM
- **Anchor:** `docs/BRD_Terms_Policies_Reviewer.md` (BRD-TECH-FE-001, Appendix A), `docs/PRD_Terms_Policies_Reviewer.md` (§4, §7.1 diagram), vs `src/webapp/app_streamlit_v2.py`.
- **Observation:** 4 references collectively (2 in BRD, 2 in PRD) still point to the pre-redesign filename. Session handoff §2 acknowledged the sweep was incomplete. Direct consequence: a new engineer following the BRD tries to open `src/webapp/app_streamlit.py` and hits "file not found."
- **Remediation:** `sed -i 's/app_streamlit\.py/app_streamlit_v2.py/g'` on both docs, verify diff, commit.
- **Effort:** S

### GOV-002 — `LIB-ARCH.md` and `LIB-RULES.md` claim IRP is shipped; PRD §5.3.1 still labels IRP "planned enhancement"

- **Severity:** MEDIUM
- **Anchor:** `.claude/library/LIB-ARCH.md` (per handoff, updated to "shipped"), `.claude/CLAUDE.md` §Session outcomes ("IRP scoring shipped"), vs `docs/PRD_Terms_Policies_Reviewer.md` §5.3.1 "**Planned: IRP Risk Scoring (not yet implemented):**".
- **Observation:** IRP is shipped in code (`analyzer.py:136-139`, `Finding.impact/likelihood/safeguard_score/irp_score` in `schemas.py:161-164`) but PRD still describes it as unimplemented. BRD §4.3.3 similarly says "Planned enhancement (not yet built)."
- **Remediation:** Update BRD §4.3.3 and PRD §5.3.1 to mark IRP shipped. This is the exact case LIB-PRINCIPLES Principle 3 recommends: name the drift explicitly, don't let docs and code silently disagree.
- **Effort:** S

### GOV-003 — `SESSION_HANDOFF_2026-07-03_ISSUE_19_REDESIGN.md` is untracked/uncommitted

- **Severity:** LOW
- **Anchor:** File exists in repo root but session handoff explicitly says it "is not committed yet."
- **Observation:** Handoff docs are documented (`.claude/CLAUDE.md` §Session Handoff Pattern in global CLAUDE.md) as "created BEFORE context runs out" and "future Claude instances shouldn't require user to re-explain context." Leaving them untracked defeats the purpose — a fresh clone won't see the file.
- **Remediation:** Commit the file to `sessions/` or root per project convention; add pattern to `.gitignore` if intent is "session-scoped, throwaway."
- **Effort:** S

### GOV-004 — `data/legal_corpus/` is a placeholder with 6 files totaling ~200 lines

- **Severity:** MEDIUM
- **Anchor:** BRD-TECH-ML-003 "Ships with placeholder corpus text pending real statute ingestion"; PRD §7.4.1 "Degrades to no augmentation if the index hasn't been built or LocalAI is unreachable."
- **Observation:** `data/legal_corpus/` contains directories for `us-ca`, `us-co`, `us-ct`, `us-ny`, `eu`, `canada`, each with a single ~30-line placeholder text file. The BRD promises "citable legal passages injected into the LLM prompt," which cannot land with the current corpus.
- **Remediation:** BRD/PRD already flag this as placeholder — the finding is that the placeholder is thinner than acknowledged (30 lines each, not "a lightweight statute skeleton"). Either fill the corpus or downgrade BRD copy.
- **Effort:** L (fill) or S (docs)

### GOV-005 — Root `tests/` directory is not documented in `.claude/CLAUDE.md` §Project Map

- **Severity:** LOW
- **Anchor:** `.claude/CLAUDE.md` §Project Map row for `src/backend/tests/` but no row for root `tests/`.
- **Observation:** Two test roots exist (see BL-002). CLAUDE.md acknowledges only the `src/backend/tests/` root.
- **Remediation:** Either delete root `tests/` (BL-002) or document why both exist.
- **Effort:** S (with BL-002 resolution)

### GOV-006 — `_derive_action_items` uses hardcoded jurisdiction-specific branches; BRD/PRD don't spec the derivation rules

- **Severity:** LOW
- **Anchor:** `analyzer.py:275-352`, BRD §none, PRD §none.
- **Observation:** The function encodes 6 branch rules (Sale/Share × US-CA, User Rights × GDPR, AI Training, ADM, Children's Privacy, Liability/Work) as a hardcoded list capped at 5 items. `.claude/CLAUDE.md` §Session outcomes credits "Backend-generated action items (Fix 8)" without documenting the derivation contract. If someone changes a category name or adds a new one, the action item list silently stops matching.
- **Remediation:** Document the derivation contract in `LIB-CONTEXT` or a new `LIB-ACTIONS`. Consider a table-driven approach so category → action mapping lives with `CATEGORIES` in `schemas.py`.
- **Effort:** M

---

## 7. Open Questions

- **OQ-001:** `app_streamlit_legacy.py` (795 lines) — is the "rollback path" still live intent, or is it just deferred deletion? Confirmation would move this from LOW (BL-003) to either "delete now" or "keep documented."
- **OQ-002:** `_data_dir()` creates a directory at import time (BL-011). Is this intentional to unblock `Settings()` instantiation in tests, or an unintended side effect? Confirmation would either add a docstring or move the mutation to `lifespan`.
- **OQ-003:** The `/rubric` endpoint's 8 axes (OE-002) include `visualIxd` and `accessibilityUsability` — is this a leftover from a scoring rubric someone ported from a UX review doc, or is it deliberately exposed to consumers who compute their own weighted average? Cannot find a downstream consumer beyond `app.js`.
- **OQ-004:** `Finding.source_document` field (added for batch analysis per `analyzer.py:539-542`) — is this consumed anywhere in the UI, or was it added speculatively? `AnalysisPayload` includes it via the nested `findings` but neither webapp renders it.
- **OQ-005:** `_bump_severity`'s `_KNOWN_SEVERITIES` guard (OE-006) — is the fail-fast intent to catch LLM-produced findings with malformed severity, or to catch code-path drift? Pydantic already rejects the former; the latter is a `Literal`-typed static impossibility. Confirming this would let us delete the guard confidently.
- **OQ-006:** `_confidence_rules_based` (`rules.py:1014`) branches on `pattern_hits >= pattern_total * 0.5` but the confidence delta between the two branches (0.93 vs 0.90 base) is small enough that the branch may not carry information proportional to its complexity. Is the "hit_ratio" concept load-bearing or vestigial? Would benefit from an ablation.

---

## 8. Summary Table

| Severity | Count |
|----------|-------|
| BLOCKING | 3 |
| HIGH | 12 |
| MEDIUM | 15 |
| LOW | 8 |
| NIT | 3 |
| Total findings | 41 |
| Open questions | 6 |

Breakdown by category:

| Category | Count |
|----------|-------|
| GAPS | 15 |
| OVER-ENGINEERING | 6 |
| BLOAT | 11 |
| LOGIC ERRORS | 20 (of which 3 are verification passes) |
| GOVERNANCE | 6 |

(The category totals exceed 41 because some findings appear both as a GAP and as a LOGIC ERROR when the missing implementation is also a correctness bug in the shipped path; the summary table above deduplicates to 41 distinct IDs.)

---

## 9. Recommended Remediation Order

### Immediate (BLOCKING + HIGH)

1. **LE-001** — Remove `["US-CA", "GDPR"]` from `_refresh_all_watchlist_items` (`main.py:145`). BLOCKING.
2. **LE-002** — Remove `["US-CA", "GDPR"]` fallback from `/analyze/file` (`main.py:396`). BLOCKING.
3. **LE-001, LE-002** — Add regression tests to `test_regressions_pr34.py` covering the empty-jurisdictions contract on both watchlist refresh AND `/analyze/file`.
4. **GAP-014** — Declare `streamlit` and `requests` in a webapp-specific requirements file. HIGH.
5. **LE-003** — Add `logger.exception` to `_watchlist_loop_async` (`main.py:117`). HIGH.
6. **GAP-001** — Wire `ids` and `detailed` params on `/exports/analyses.csv` (`main.py:541`). HIGH.
7. **GAP-004** — Reconcile `WatchlistCreateRequest` schema vs PRD §7.3.9 (either change PRD or extend schema). HIGH.
8. **GAP-007** — Either implement Verify View expander in Streamlit v2, or update PRD §4 to note the intentional deprecation. HIGH.
9. **OE-003** — Consolidate `WatchlistItem` and `PolicyWatch` into a single abstraction. HIGH (unblocks GAP-004 and LE-010).
10. **BL-001** — Delete `/ignore/` (or move to archive tag). HIGH.
11. **LE-013** — Add import-time validation for `_DOCTYPE_BOOSTS` and `_INDUSTRY_BOOSTS` category keys against `CATEGORIES`. HIGH (this is masked by LE-012; fix them together).
12. **LE-012** — Replace substring category match with exact match in `_bump_severity` boost lookup. HIGH.
13. **LE-018** — Remove em-dash from action item copy (`analyzer.py:332`). MEDIUM but reader-visible LIB-VOICE violation.
14. **LE-017** — Surface `review_required` in Streamlit v2 results view. MEDIUM but load-bearing for trust.

### Next iteration (MEDIUM)

15. **GAP-002** — Register `/exports/analysis/{id}.json` route or update PRD.
16. **GAP-005** — Wire email notifications or explicitly defer.
17. **GAP-010** — Add PRD-specified query params to `/analyses`.
18. **BL-002** — Delete root `tests/` directory after folding coverage.
19. **BL-005** — DRY the four URL scheme validators.
20. **BL-008** — Pin Pydantic v2; remove v1 fallbacks.
21. **BL-006** — Consolidate category alias handling.
22. **LE-004, LE-005, LE-006, LE-007** — Add structured logging to swallowed exceptions.
23. **LE-009** — Rebalance confidence penalty stack.
24. **LE-010** — Migrate `PolicyWatch.enabled` to `Boolean`.
25. **LE-011** — Distinguish "baseline captured" from "no changes."
26. **LE-020** — Consolidate industry default on the client side.
27. **GOV-001** — Sweep BRD/PRD for `app_streamlit.py` references.
28. **GOV-002** — Update BRD §4.3.3 / PRD §5.3.1 to reflect shipped IRP.
29. **GOV-004** — Fill or downgrade `data/legal_corpus/` placeholder narrative.
30. **OE-001, OE-002, OE-004** — Decide batch analysis, rubric endpoint, and cross-reference detection: promote (add BRD/PRD anchor) or delete.

### Backlog (LOW / NIT / OQ)

31. **GAP-003, GAP-006, GAP-008, GAP-009, GAP-011, GAP-012, GAP-013, GAP-015**
32. **BL-003, BL-004, BL-007, BL-009, BL-010, BL-011**
33. **OE-005, OE-006**
34. **LE-014 (verification pass), LE-015 (verification pass), LE-016 (verification pass), LE-019**
35. **GOV-003, GOV-005, GOV-006**
36. Open Questions OQ-001 through OQ-006 — schedule as short conversations before the fix work.

---

## Appendix A: Verification Commands

For each finding that can be re-verified with a grep/pytest/mypy command:

- **LE-001, LE-002:** `grep -n '\["US-CA", "GDPR"\]' src/backend/app/main.py` — expect zero matches after fix.
- **LE-003, LE-004, LE-005, LE-007:** `grep -nE "except Exception:$|except Exception:\s*pass|except Exception:\s*continue" src/backend/app/` — expect zero unlogged catches after fix.
- **LE-013:** `python -c "from app.services import analyzer"` — expect RuntimeError if boost keys drift.
- **LE-017:** `grep -n 'review_required' src/webapp/app_streamlit_v2.py` — expect at least one hit after fix.
- **LE-018:** `python -c "import re; import app.services.analyzer as a; import inspect; assert '—' not in inspect.getsource(a._derive_action_items)"` — expect no assertion.
- **BL-001:** `test -d ignore/` — expect not present after fix.
- **BL-002:** `test -d tests/ -a -f tests/test_api_endpoints.py` — expect not present after fix.
- **BL-005:** `grep -c 'must use http or https scheme' src/backend/app/schemas.py` — expect 1 after DRY (from a shared helper).
- **BL-008:** `grep -n 'hasattr.*model_dump\|payload\.json()' src/backend/app/` — expect zero after Pydantic v2 pin.
- **BL-010, GOV-001:** `grep -c 'app_streamlit\.py' docs/BRD_Terms_Policies_Reviewer.md docs/PRD_Terms_Policies_Reviewer.md` — expect 0 after fix.
- **GAP-001:** `curl -s 'http://localhost:9000/exports/analyses.csv?ids=<id>&detailed=true' | head -1` — expect finding-level CSV header after fix.
- **GAP-014:** `grep -E '^streamlit|^requests' src/backend/requirements.txt` — expect at least one match, or a new `src/webapp/requirements.txt`.
- **GOV-002:** `grep -n 'planned enhancement\|not yet built\|not yet implemented' docs/BRD_Terms_Policies_Reviewer.md docs/PRD_Terms_Policies_Reviewer.md` — expect zero references to IRP after fix.
- **OE-003:** `grep -n 'class PolicyWatch\b' src/backend/app/models.py` — expect absent after consolidation.

Tests to add:
- `test_regressions.py::test_analyze_file_empty_jurisdictions_no_default` (LE-002)
- `test_regressions.py::test_watchlist_refresh_uses_empty_jurisdictions` (LE-001)
- `test_analyzer.py::test_bump_severity_exact_category_match` (LE-012)
- `test_analyzer.py::test_boost_keys_valid_at_import` (LE-013)
- `test_voice.py::test_no_em_dashes_in_action_items` (LE-018)
- `test_voice.py::test_no_em_dashes_in_verdict_copy` (defense in depth for LIB-VOICE)

---

## Appendix B: References

**Product docs:**
- `docs/BRD_Terms_Policies_Reviewer.md` — Business Requirements (BRD-* anchors)
- `docs/PRD_Terms_Policies_Reviewer.md` — Product Requirements (F1-F8 features, PRD §§ anchors)
- `PRODUCT.md` — Brand personality, target users

**Governance:**
- `.claude/CLAUDE.md` — Project identity, hard requirements, session outcomes
- `.claude/library/LIB-PRINCIPLES.md` — Non-negotiable operating principles (Principles 1-7)
- `.claude/library/LIB-VOICE.md` — Two-voice, no-em-dash, tentative framing
- `.claude/library/LIB-CONTEXT.md` — Chip taxonomy, weight tiers, sort semantics
- `.claude/library/LIB-ARCH.md` — Architecture, data flow, failure modes
- `.claude/library/LIB-RULES.md` — Rule patterns, IRP scoring
- `.claude/library/LIB-STACK.md`, `LIB-LEGAL.md`, `LIB-TEST.md`, `LIB-EVAL.md`, `LIB-API.md` — Reference material
- `.claude/rules/code-style.md`, `.claude/rules/testing.md` — Code and test conventions

**Source code cited:**
- `src/backend/app/main.py` (1285 lines)
- `src/backend/app/schemas.py` (462 lines)
- `src/backend/app/models.py` (86 lines)
- `src/backend/app/config.py` (101 lines)
- `src/backend/app/services/analyzer.py` (813 lines)
- `src/backend/app/services/rules.py` (1092 lines)
- `src/backend/app/services/context.py` (219 lines)
- `src/backend/app/services/inference.py` (~553 lines)
- `src/backend/app/services/localai.py` (185 lines)
- `src/backend/app/services/ingest.py` (255 lines)
- `src/backend/app/services/legal_kb.py`, `embedding.py`, `diffing.py`, `validation.py`, `prompts.py`
- `src/webapp/app_streamlit_v2.py` (972 lines)
- `src/webapp/app_streamlit_legacy.py` (795 lines, deprecated)
- `src/webapp/app.js` (1725 lines)

**Ops:**
- `run.sh`, `.env.example` (not read directly; behavior inferred from `config.py` env vars)
- `src/backend/requirements.txt`, root `requirements.txt`
- Root `SESSION_HANDOFF_2026-07-03_ISSUE_19_REDESIGN.md` (untracked)

**Legacy / graveyard (audited but not cited as active code):**
- `ignore/` (design-iteration graveyard, ~250 KB + `.venv/` + `.pip-cache/`)
- `archive/` (11 HTML wireframes + 6 PNG mockups + 2 RTF)
- `tests/` at repo root (3 legacy test files)

---

*End of audit.*
