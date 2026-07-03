# User Decision Brief — 2026-07-03

> Companion to `docs/reports/tech-spec-audit.md` and `SESSION_HANDOFF_2026-07-03_TECH_SPEC_AUDIT_REMEDIATION.md`.
> Purpose: give the user the specific facts and options needed to unblock four open items:
> A1 — Flow 2 Batch Analysis (PRD §1082)
> A2 — GAP-004 Watchlist contract mismatch (PRD §7.3.9)
> A3 — OE-003 `WatchlistItem` vs `PolicyWatch` canonicalization
> A4 — BL-001 `/ignore/` graveyard removal
>
> Every option below is annotated with a recommendation. All research was read-only. No source files were modified.

---

## A1 — Flow 2 Batch Analysis (PRD §1082)

### What Flow 2 was supposed to be (per PRD)

PRD §6.2 (lines 1079-1100) describes a 12-step Researcher persona flow:

1. Researcher has a CSV with 50 platform URLs.
2. Navigates to a "Batch Analysis" surface (assumed to be in the flagship UI).
3. Uploads CSV with columns `name, url, jurisdiction`.
4. Selects a shared jurisdiction (e.g. GDPR) and doc_type (e.g. Privacy Policy).
5. Clicks "Analyze All".
6. Watches a progress bar (e.g. "5/50 completed").
7. Waits ~20 minutes (25s/policy).
8. Reviews a **sortable, filterable results table** (by grade, risk score, findings count; filter by severity/category).
9. Exports "All as CSV (Detailed)" — 1,000+ rows.
10. Imports into R for statistical analysis.
11. Visualizes distributions.
12. Cites methodology in a paper.

Edge cases the PRD explicitly promises: partial URL failures logged and skipped; pause/resume for long batches; rate-limiting throttle.

PRD §7.3.13 (line 1579) confirms the endpoint side of the deal: `POST /analyze/batch` accepts `AnalyzeBatchRequest`, returns `BatchAnalysisResult`, includes **cross-reference detection** between documents.

### What actually shipped (backend only)

Backend endpoint: `src/backend/app/main.py:443-501`.

```python
@app.post("/analyze/batch", response_model=dict)
async def analyze_batch(request: AnalyzeBatchRequest, db: Session = Depends(get_db)):
    ...
    for item in batch_req.items:
        if item.url:
            try:
                text = await fetch_url_text(item.url)
                if text:
                    documents.append((text, item.name, item.url, item.doc_type))
            except Exception as e:
                logger.error(f"Failed to fetch URL {item.url}: {e}")
                continue
    ...
    results, cross_refs = await analyze_batch_documents(...)
    ...
    return batch_result.model_dump()
```

Request/response contract (`src/backend/app/schemas.py:361-399`):

```python
class BatchItem(BaseModel):
    url: Optional[str]
    name: Optional[str]
    doc_type: Optional[DocType]

class AnalyzeBatchRequest(BaseModel):
    items: List[BatchItem]                # min_items=1
    industry: Optional[IndustryProfile]
    jurisdictions: List[Jurisdiction]     # default []
    mode: Literal["full", "quick"]        # default "full"
    detect_cross_references: bool         # default True
    context: List[ContextChip]            # default []

class BatchAnalysisResult(BaseModel):
    batch_id: str
    analysis_mode: str
    items: List[AnalysisPayload]
    cross_references: List[dict]          # loose dict shape
    created_at: datetime
```

**Confirmed no UI wiring in Streamlit v2 or legacy:**
`grep -ni "batch" src/webapp/app_streamlit_v2.py src/webapp/app_streamlit_legacy.py` returned **zero hits.** Neither Streamlit UI mentions batch, exposes a CSV upload for multi-URL, or renders `BatchAnalysisResult`.

**What is missing to satisfy PRD §6.2 acceptance:**

| PRD step | Shipped? |
|---|---|
| 2 — "Batch Analysis" nav surface | No |
| 3 — CSV upload with `name,url,jurisdiction` columns | No (endpoint takes JSON `items[]`) |
| 4 — Shared jurisdiction/doc_type selector | No |
| 6 — Progress bar (X/N completed) | No — endpoint is a blocking single request |
| 8 — Sortable/filterable results table | No |
| 9 — "Export All as CSV (Detailed)" | No batch-scoped export; single-analysis CSV only |
| Edge case — pause/resume | No |
| Edge case — per-URL failure list | Failures are `logger.error`'d but not returned in `BatchAnalysisResult` (see audit LE-008) |

### Decision options

#### Option A — Build the batch UI in Streamlit v2 for the next release

**Scope of work:**
- New Streamlit page or tab: "Batch Analysis" (Researcher flow).
- CSV upload widget (schema `name,url,jurisdiction`).
- Shared jurisdiction + doc_type selectors.
- Progress rendering — likely requires converting `/analyze/batch` into a job model (start-job / poll-status / get-results) or streaming SSE. Current endpoint is synchronous; a 50-URL batch at 25s each = ~20 minutes of held HTTP connection.
- Results table with sort + filter.
- Batch CSV export (all findings across all analyses, 1,000+ rows).
- Per-URL failure list surfaced in `BatchAnalysisResult` (also fixes LE-008).

**Trade-offs:**
- **Dev cost:** Large. Streamlit's `st.file_uploader` + `st.dataframe(with sort/filter)` handles most of the UI cheaply; the hard part is converting the endpoint to an async job model so a 20-minute request doesn't die behind proxy timeouts (`app_streamlit_v2.py:288` already sets a 400s client timeout — well below the ~1200s a 50-item batch would need).
- **User coverage:** Enables Persona 3 (Researcher) on the flagship UI. PRD §3.3 explicitly names this persona and PRD §6.2 is that persona's canonical flow.
- **PRD-code alignment:** Closes the biggest UI gap in the tech spec audit.
- **Risk:** Cross-reference detection (`OE-004` in audit) becomes a supported feature. Currently `cross_references: List[dict]` has no schema — you would need to type it before shipping to users.

**Effort estimate:** 3-5 days including the async-job refactor and testing.

#### Option B — Reclassify Flow 2 as "API-only" and remove the UI acceptance criteria from PRD §1082

**Scope of work:**
- Rewrite PRD §6.2 as "Researcher Bulk Analyzes Policies (API-only for MVP)".
- Delete Steps 2, 3, 6, 8, 9 acceptance criteria (all UI-bound).
- Add a code snippet showing the JSON POST body — this becomes the researcher's entry point.
- Add a note under §7.3.13: "Consumers of `POST /analyze/batch` are expected to script their own progress tracking and export formatting."
- Retain the endpoint. Retain cross-reference detection (or gate it — see audit OE-001/OE-004).
- Optional: expose a CLI wrapper in `src/backend/scripts/` for researchers who don't want to write curl.

**Trade-offs:**
- **Dev cost:** Small. ~1 day of PRD editing + optional CLI wrapper.
- **User coverage:** Researcher persona keeps the capability but has to hit the API directly. Removes the "no-code researcher" segment implied by PRD §3.3.
- **PRD-code alignment:** Immediate — the PRD now describes what shipped.
- **Risk:** Any future marketing that promises "Batch Analysis in the UI" needs a code change. Also invites deletion of `OE-001`/`OE-004` (batch endpoint + cross-refs) if downstream traction is zero.

### Recommendation

**Option B (API-only + PRD rewrite)** for this release, with a note that Option A is the follow-up work when researcher demand is proven.

Rationale:
1. The batch endpoint's blocking synchronous shape doesn't survive a real 50-URL run behind any HTTP proxy. Fixing that (async job model, polling, or SSE) is a multi-day architecture change, not a UI wire-up.
2. Persona 3 (Researcher) can already use the endpoint via curl / a 20-line Python script — the same population that will "Import CSV into R for statistical analysis" (PRD step 10) is comfortable with `requests.post`.
3. Shipping the UI half-finished (synchronous 20-minute request, no pause/resume, no per-URL failure list) makes the PRD claim technically true but user-hostile — worse than an honest "API-only" story.
4. Option A is not foreclosed. The PRD rewrite adds "Batch UI is a P2 follow-up — track under a new issue" so the option to build it later stays open.

---

## A2 — GAP-004 Watchlist contract mismatch (PRD §7.3.9)

### PRD-documented request (§7.3.9, line 1535-1550)

```json
POST /watchlist
{
  "analysis_id": "uuid (required)",
  "frequency": "daily | weekly | monthly (default: weekly)",
  "notes": "string (optional)"
}
```

Response envelope (per PRD):
```json
{
  "success": true,
  "watchlist_item_id": "uuid",
  "next_check_at": "2026-02-20T12:00:00Z"
}
```

Semantic model: "watch a **previously-analyzed document** for policy changes over time. Subject is the analysis. Cadence is a coarse tier (daily / weekly / monthly). Notes are free-text."

### Shipped request (`src/backend/app/schemas.py:316-331`)

```python
class WatchlistCreateRequest(BaseModel):
    vendor: str = Field(..., min_length=1)
    source_url: Optional[str] = None

    @field_validator("source_url")
    @classmethod
    def validate_source_url_scheme(cls, v):
        # rejects non-http(s), requires hostname
        ...
```

Endpoint (`main.py:975-999`) writes rows to `watchlist_items` (`models.py:46-61`) with `vendor`, `source_url`, `status`, `change_count`, `risk_delta`. **No FK to `analyses`.** **No `frequency`.** **No `notes`.** The refresh loop (`main.py:113-119`) uses a **single global interval** (`settings.watchlist_refresh_seconds`) for every item.

Semantic model: "watch a **new vendor URL** for policy publication changes. Subject is the URL. Cadence is global (server-side setting). No user-supplied notes."

### Which model better serves the BRD user need

BRD refs (from `docs/BRD_Terms_Policies_Reviewer.md`):

- **BRD line 144:** "Watchlist Monitoring | Yes | No | Yes" (in a persona/feature matrix).
- **BRD line 324:** the Researcher persona (Persona 3, Alex): "Monitors watchlist for policy changes by major platforms" — subject is *platforms* (i.e., known vendors), not one-off analyses.
- **BRD line 367:** "`WatchlistItem` — monitored vendor URLs, change/risk-delta tracking" — this is the shipped model.
- **BRD line 442-454:** Watchlist tier limits ("Watchlist (up to 10 documents)", "up to 50", "unlimited") — plural "documents" is neutral; either model fits.
- **BRD line 649:** "Watchlist change alerts (email)" — cadence is implicit but not specified as per-item.

The BRD leans slightly toward the **shipped (vendor+URL) model** — the Researcher persona description is about tracking known platforms, not re-checking specific analyses. But PRD §7.3.9 flatly contradicts this by naming `analysis_id` as the subject.

Note: PRD §5.6.1 (F6.1, line 934-941) has acceptance criteria that straddle both models:
- "User can add analyzed document to watchlist" → analysis_id shape
- "System stores URL and current policy text hash" → URL shape
- "User can set check frequency (daily, weekly, monthly)" → per-item cadence

So PRD §5.6 assumes **both** — a hybrid that stores URL + hash *and* links to the source analysis *and* has per-item cadence.

### Decision options

#### Option A — Migrate code to PRD shape

Add `analysis_id: UUID`, `frequency: Literal["daily","weekly","monthly"]`, `notes: Optional[str]` to `WatchlistCreateRequest`. Add same fields to `WatchlistItem` model. Convert `_watchlist_loop_async` to a per-item scheduler that respects each row's frequency. Enforce `analysis_id` FK to `analyses.id`.

**Trade-offs:**
- Dev cost: **M-L.** Schema migration, endpoint rewrite, refresh-loop scheduler rewrite, tests. Blocked by OE-003 — you would be rebuilding half of `WatchlistItem` while `PolicyWatch` still exists as a parallel abstraction.
- BRD alignment: Better matches PRD §5.6.1 hybrid criteria.
- Risk: Existing `WatchlistItem` rows have no `analysis_id`; migration path needs a nullable phase or a backfill from `source_url` lookups.

#### Option B — Update PRD to codify the shipped shape

Rewrite PRD §7.3.9 to describe the shipped `{vendor, source_url}` contract. Update §5.6.1 acceptance criteria to drop `analysis_id` and `notes`, drop per-item frequency. Add a note under §5.6.2 that the refresh cadence is a **global server setting** (`WATCHLIST_REFRESH_SECONDS`) not a per-item choice.

**Trade-offs:**
- Dev cost: **S.** ~1 day of PRD editing.
- BRD alignment: Matches BRD line 367 exactly. Loses PRD §5.6.1 "frequency" acceptance criterion.
- Risk: Any UI that assumes daily/weekly/monthly cadence controls (there is none in v2 today) would be deferred indefinitely.

#### Option C — Support both (union type)

Accept `WatchlistCreateRequestPRD` (analysis_id-based) **or** `WatchlistCreateRequestVendor` (vendor+url-based) at the same endpoint. Store both shapes in a unified `WatchlistItem` table with nullable `analysis_id`, nullable `frequency` (falling back to global), nullable `notes`, plus the existing `vendor`/`source_url`/`change_count`/`risk_delta` columns.

**Trade-offs:**
- Dev cost: **L.** Schema union types are fiddly in Pydantic v2 (`discriminated union` or manual `model_validator`). Refresh loop needs to handle "no URL, only analysis_id → look up analysis.source_url" branch. Tests grow ~2x.
- BRD alignment: Best (both persona flows served).
- Risk: Two paths through the same endpoint is exactly the kind of over-engineering the audit flags. Also invites the same OE-003 problem back at the schema layer.

### Dependency on GAP-006 / OE-003

Any of Options A/B/C is entangled with OE-003 (`WatchlistItem` vs `PolicyWatch` — see A3 below). Both watch abstractions carry cadence/subject/enabled state, and both have public endpoints. Consolidating them (audit's recommended remediation) is a prerequisite to a clean fix here. A3 needs to be resolved first.

### Recommendation

**Option B (update PRD to codify shipped shape)** — with two caveats:

1. Do NOT touch the code until OE-003 (A3) is decided. If `PolicyWatch` becomes the canonical abstraction, its `check_frequency` field (int seconds, per-item) would satisfy the PRD `frequency` acceptance criterion for free — Option B could be revisited as "codify the merged model."
2. Add a note in PRD §5.6.1 that per-item frequency is deferred until the watch-abstraction consolidation lands. Track that consolidation as its own issue.

Rationale: the shipped `{vendor, source_url}` shape aligns with the BRD's Researcher persona narrative (monitor known platforms). Adding `analysis_id + frequency + notes` requires either a large migration (Option A) or a schema union (Option C), and both are gated by OE-003 anyway. Cheaper to correct the PRD now, and re-open the question after A3 is settled.

---

## A3 — OE-003 pros/cons: `WatchlistItem` vs `PolicyWatch` (does it matter?)

### Side-by-side field comparison

| Field | `WatchlistItem` (`models.py:46-61`) | `PolicyWatch` (`models.py:75-85`) |
|---|---|---|
| `id` | String PK | String PK |
| Subject | `vendor: str` + `source_url: Optional[str]` | `url: str` (unique) |
| Ownership | none | `user_id: Optional[str]` |
| Cadence | none (global setting) | `check_frequency: Integer` (seconds, 300-604800) |
| Last check | `last_checked: DateTime` (required, defaults now) | `last_check: Optional[DateTime]` (nullable) |
| Enabled | *not tracked* | `enabled: String` **(bug: LE-010, stored as `"true"`)** |
| Created | *not tracked (last_checked used as proxy)* | `created_at: DateTime` |
| Change tracking | `changes_since: DateTime?`, `change_count: int`, `risk_delta: float`, `change_summary: Text?` | *not tracked* |
| Document text | `last_document_text: Text?`, `last_document_hash: String?` | *not tracked (uses separate `PolicySnapshot` table)* |
| Risk history | `last_risk_score: Float?`, `last_analysis_id: String?` | *not tracked* |

**Field-coverage asymmetry:** `WatchlistItem` is a **denormalized diff/risk row** (stores last-seen text + hash + risk). `PolicyWatch` is a **schedule row** (stores cadence + owner + enabled). They are complementary, not redundant — but neither table references the other, so the "schedule → row-to-refresh" join has to be made client-side or in application code.

### Endpoint / test / DB usage

| Consumer | `WatchlistItem` refs | `PolicyWatch` refs |
|---|---|---|
| `main.py` (endpoints + refresh loop) | 27 references, 4 endpoints: `GET/POST /watchlist`, `DELETE /watchlist/{id}`, `POST /watchlist/{id}/refresh`, plus `_watchlist_loop_async` background task | 8 references, 4 endpoints: `POST/GET /policy-watch`, `DELETE /policy-watch/{id}`, `POST /policy-watch/{id}/snapshot` |
| `schemas.py` | `WatchlistItemPayload`, `WatchlistCreateRequest` | `PolicyWatchPayload`, `PolicyWatchCreateRequest` |
| `models.py` | 1 class | 1 class (plus separate `PolicySnapshot`) |
| Tests | `test_main_endpoints.py` (12 refs), `test_all.py` (4 refs), `test_database_and_main_coverage.py` (10 refs), `test_regressions_pr34.py` (WatchlistCreateRequest schema tests) | `test_main_endpoints.py::TestCreatePolicyWatch`, `TestListPolicyWatches`, `TestDeletePolicyWatch`, `TestSecurityPolicyWatchUserIdValidation`; `test_snapshots_and_diffs.py::TestPolicyWatchModel`; **13 refs total** |
| Overlap | Both are exercised in `test_main_endpoints.py` in independent test classes; no test asserts the two tables should be consolidated. | |

**Downstream usage count:** `WatchlistItem` has ~44 code+test references; `PolicyWatch` has ~26. Neither is dead — both are actively tested and both have user-visible endpoint contracts.

### Migration complexity to consolidate

Following the audit's proposed remediation ("keep `WatchlistItem`, add `check_frequency` + `enabled: Boolean`, delete `PolicyWatch`"):

1. **Add columns** to `watchlist_items`: `check_frequency INTEGER NOT NULL DEFAULT 86400`, `enabled BOOLEAN NOT NULL DEFAULT TRUE`, `user_id VARCHAR NULLABLE`, `created_at DATETIME NOT NULL DEFAULT now()`.
2. **Migrate** any existing `PolicyWatch` rows into `WatchlistItem` (SQL join on `url = source_url`, else new row).
3. **Redirect** `/policy-watch/*` endpoints to the consolidated `/watchlist/*` endpoints (or keep as thin aliases for one deprecation cycle).
4. **Update refresh loop** to honor per-item `check_frequency` and per-item `enabled` (currently uses one global setting for cadence and never checks enabled).
5. **Update `PolicySnapshot`** to reference the merged table (currently references neither directly — just URL string).
6. **Fix LE-010** (`enabled: str → bool`) as part of the merge.
7. **Rewrite tests** — the two test classes exercise different behaviors, so both suites need to survive against the merged model.

**Effort:** L (large). Multi-file change plus a real SQLite migration.

### Does it matter? What breaks if we leave both as-is?

Concrete failure modes today, **short of a migration**:

1. **User-visible: none for now.** A user hitting `POST /watchlist` gets a vendor-tracking row. A user hitting `POST /policy-watch` gets a schedule row. They do not conflict; they simply serve two different (unlabeled) features.
2. **Data inconsistency risk:** If a user adds `https://example.com/privacy` to `/watchlist` AND to `/policy-watch`, the two rows exist independently, are refreshed independently (well — `PolicyWatch` isn't refreshed at all today; see below), and can produce contradictory `last_check` timestamps. The tool has no way to say "these are the same subject."
3. **Hidden feature gap: `PolicyWatch` is not refreshed by the background loop.** `_watchlist_loop_async` iterates `WatchlistItem` only (`main.py:113-160`). Nothing consumes `PolicyWatch.check_frequency`. So the `POST /policy-watch/{id}/snapshot` endpoint is manual-trigger-only. A user setting `check_frequency=3600` believes hourly checks are happening; they are not. **This is a silent user-facing bug** — arguably worse than cosmetic tech debt.
4. **Type drift signal (audit LE-010):** `PolicyWatch.enabled = "true"` (string) is a schema smell. If a future dev sets it to `"True"` or `"1"`, filters silently break. Type-checkers can't help.
5. **PRD/BRD confusion:** PRD §5.6 F6 acceptance criteria straddle both tables (see A2). New engineers touching F6 have to decide which abstraction to use. This is a documentation-cost multiplier for the whole watch feature area going forward.

### What does canonicalization unblock?

- **GAP-004** (A2). Any hybrid `frequency + analysis_id + notes` fix has to pick a table first.
- **LE-010** (`enabled` string→bool migration). Once you're migrating, do it once.
- **PRD §5.6.2 F6.2 change-detection notification (GAP-005 email).** Whichever table you notify from has to be the single source of "watch this URL." Two tables = ambiguity about which one drives emails.
- **Future BRD-ROADMAP-P4-D007** ("Email notification system") — same as above.
- **PRD §7.3.10** (watchlist listing/dashboard, F6.3) — dashboard must render one row per watched thing, not two-per-thing.

### Recommendation

**Canonicalize — consolidate `PolicyWatch` into `WatchlistItem`.** The primary trigger is failure mode #3 (silent user-facing bug: `PolicyWatch.check_frequency` is set but never honored). Everything else (schema drift, doc confusion, unblocking A2 / GAP-005 / LE-010) is downstream benefit.

**Sequencing:**
1. First: land the merge (adds columns to `watchlist_items`, redirects `/policy-watch/*`, migrates rows, honors per-item cadence in refresh loop). **File this as a distinct issue — it's L-effort, blocks 3 other findings, and is not safe to combine with a doc-only fix.**
2. Then: revisit A2 (GAP-004). With `check_frequency` on the merged table, PRD Option B (codify shipped shape) becomes trivial to describe.
3. Then: land LE-010 as part of the merge (`enabled` becomes `Boolean`).

**Do it now, not later.** Leaving both means the tool is quietly lying to users who use `POST /policy-watch`.

---

## A4 — BL-001 `/ignore/` graveyard contents

### Inventory

```
$ du -sh ignore/
227M	ignore/

$ du -sh ignore/*  (top 10 by size)
190M	ignore/src           <-- 179M is .venv + .pip-cache inside ignore/src/backend/
808K	ignore/docs
564K	ignore/data
480K	ignore/archive
 32K	ignore/tests
 12K	ignore/TESTING_GUIDE.md
 12K	ignore/IMPLEMENTATION_SUMMARY.md
8.0K	ignore/README.md
8.0K	ignore/GITHUB_SETUP.md
4.0K	ignore/run.sh
```

**Top-level structure:**
- `ignore/.claude/` (skills, library, rules — full mirror of the pre-redesign project instructions)
- `ignore/.git/` — a nested `.git` directory (an independent repository history for the graveyard). Not the main repo's `.git`.
- `ignore/.streamlit/`
- `ignore/AGENTS.md`, `README.md`, `PRODUCT.md`, `TESTING_GUIDE.md`, `IMPLEMENTATION_SUMMARY.md`, `GITHUB_SETUP.md`, `run.sh`, `requirements.txt` — pre-redesign roots
- `ignore/src/webapp/` — pre-redesign JS SPA + Streamlit iterations (this is the "design-iteration graveyard" the audit describes)
- `ignore/src/backend/` — an old backend mirror (dated Jun 28) plus **`.venv/` and `.pip-cache/` sub-dirs** (this is the 179M chunk)
- `ignore/src/demos/`, `ignore/src/backend/scripts/`, `ignore/src/backend/evaluation/` — old
- `ignore/tests/` — old test files
- `ignore/data/` — 564K, likely a snapshot of the pre-redesign legal_corpus or terms_analysis.db
- `ignore/archive/`, `ignore/docs/` — old wireframes and specs

### git-tracked status

```
$ git ls-files ignore/ | wc -l
0
```

**Zero files inside `ignore/` are tracked by the main repo's git.** They exist only in the working tree.

`.gitignore` (top of file) does NOT include a literal `ignore/` line. The dir is not explicitly listed. However, since no files under it are `git add`ed, and `du -sh ignore/.venv` etc. are matched by `.venv/` further down the ignore rules (`__pycache__/`, `.venv/`, `venv/`, `.mypy_cache/`), most of the sub-tree is *implicitly* ignored anyway. Only the human-authored files (README/AGENTS/etc.) inside `ignore/` would be candidates for accidental `git add`.

### References from active code

```
$ grep -rn "ignore/" src/ 2>/dev/null
(empty — no hits)
```

**No file inside `src/` imports, reads, or references anything under `ignore/`.** This matches the audit's finding.

### Decision options

#### Option A — git tag current state, then `git rm -r ignore/`, then add explicit `.gitignore` entry

**Steps:**
1. `git tag pre-graveyard-cleanup-2026-07-03` (marks a recovery point on the current tree even though `ignore/` isn't tracked, so `git checkout <tag>` at least reproduces "before we deleted the working-tree copy").
2. Because `ignore/` is untracked, `git rm -r ignore/` will fail — the actual command is `rm -rf ignore/` at the filesystem level.
3. Add `ignore/` to `.gitignore` (an explicit line) so any future `mkdir ignore` won't invite accidental staging.
4. Optional: preserve a compressed archive: `tar czf ignore-graveyard-2026-07-03.tar.gz ignore/ && rm -rf ignore/ && mv ignore-graveyard-2026-07-03.tar.gz ~/archives/` — keeps a physical backup outside the repo.

**Risk of recovery:** Because none of `ignore/` is git-tracked, `git tag` alone does NOT preserve the graveyard's contents. Deletion is irreversible unless step 4's tarball is done. **This is important — the tag protects nothing.** If you want recoverability, the tarball is mandatory.

**Disk savings:** 227M reclaimed.

**Downstream risk:** Zero — no active code references it.

#### Option B — Leave alone until a full graveyard audit is scheduled

**Steps:** none. Add `ignore/` to `.gitignore` as a belt-and-suspenders measure so it stays out of any future commit.

**Trade-offs:**
- **Disk usage:** 227M sitting on the developer's machine. Not in git, so it's not shipped with the repo. Only affects local workspace.
- **Cognitive cost:** New contributors see a `ignore/` directory with an old backend copy, an old `.venv`, an old `.git` — takes a few minutes to realize it's dead.
- **Risk of accidental reference:** With no files git-tracked and no code references, near-zero. The nested `.git/` inside means `git` commands run from `ignore/` operate on the graveyard, not the main repo — a mild footgun for anyone who `cd ignore` and runs `git log`.

### Recommendation

**Option A, with the tarball step mandatory (not optional).** Two additional guardrails:

1. Before deletion, run one final sanity grep against `docs/`: `grep -rn "ignore/" docs/ | grep -v tech-spec-audit`. If any doc points at `ignore/` for a wireframe or historical reference, decide per-doc whether to inline the content or delete the reference.
2. Add an explicit `ignore/` line to `.gitignore` even after deletion, so accidental re-creation of the directory doesn't invite staging.

Rationale:
- 227M is not trivial on a laptop, especially with a 179M nested `.venv`.
- The nested `.git/` inside `ignore/` is a real footgun (running `git` commands from that directory operates on a phantom repo).
- Nothing in active code references it — the delete is safe.
- The audit already labels this HIGH severity (BL-001) with recommended remediation matching Option A. Deferring is a paper-cut for every future contributor.

Skip only if the user wants to first re-open `ignore/src/webapp/` to confirm no wireframe iteration is worth salvaging into `docs/wireframes/`. That check is 15 minutes and can happen before Option A executes.

---

## Cross-cutting notes

- **All four items are independent-ish, but A2 blocks on A3.** Execute A3 first (schema consolidation), then A2 (PRD text following the merged model), then A1 and A4 in either order.
- **A4 is the fastest kill.** If the user wants a quick win, do A4 first (Option A).
- **A1 (Option B) and A2 (Option B) are both PRD-only edits.** Batch them into a single PRD v2.2 bump alongside the current v2.1 open questions from `SESSION_HANDOFF_2026-07-03_TECH_SPEC_AUDIT_REMEDIATION.md` §3.
- **A3 is the only item with real code-change cost.** File it as its own GitHub issue; do not roll it into any doc PR.

*End of brief.*
