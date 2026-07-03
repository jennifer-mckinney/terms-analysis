# LIB-API: API Endpoints & Contracts

> **Status (2026-07-03):** endpoint map corrected — 24 business routes + `/health` = 25 total, verified against `main.py`'s `@app.*` decorators. Previous version of this file only listed 16 (missing batch analysis, snapshots, diff, and policy-watch).

## Endpoint Map

| Method | Path | Auth | Request | Response | Notes |
|--------|------|------|---------|----------|-------|
| GET | `/health` | None | — | `{status, model_world, model_eu, review_threshold}` | Health check |
| POST | `/analyze` | None | `AnalyzeRequest` (JSON) | `AnalysisPayload` | Text analysis |
| POST | `/analyze/url` | None | `AnalyzeUrlRequest` (JSON) | `AnalysisPayload` | URL fetch + analysis |
| POST | `/analyze/file` | None | multipart: `file`, `name?`, `doc_type?`, `jurisdictions?` | `AnalysisPayload` | File upload |
| POST | `/analyze/batch` | None | `AnalyzeBatchRequest` (JSON: `items: List[BatchItem]`) | `dict` (per-item results) | Batch of URLs/files |
| GET | `/analyses` | None | query: `skip`, `limit` | `List[AnalysisSummary]` | Paginated list |
| GET | `/rubric` | None | — | `RubricScores \| None` | Computed from all analyses |
| GET | `/analyses/{id}` | None | path: `id` | `AnalysisPayload` | Single analysis (404 if missing) |
| GET | `/exports/analyses.csv` | None | — | CSV file download | |
| GET | `/exports/analysis/{id}.pdf` | None | path: `id` | PDF file download | Requires reportlab; route registered *before* the JSON export route below it so it isn't shadowed |
| GET | `/exports/analysis/{id}` | None | path: `id` | JSON file download | |
| GET | `/reviews` | None | — | `List[ReviewItemPayload]` | Pending reviews |
| POST | `/reviews/{id}` | None | `ReviewUpdate` (JSON) | `ReviewItemPayload` | Approve/reject |
| GET | `/watchlist` | None | — | `List[WatchlistItemPayload]` | All watchlist items |
| POST | `/watchlist` | None | `WatchlistCreateRequest` (JSON) | `WatchlistItemPayload` | Add vendor |
| DELETE | `/watchlist/{id}` | None | path: `id` | `{detail}` | Remove vendor |
| POST | `/watchlist/{id}/refresh` | None | path: `id` | `WatchlistItemPayload` | Re-fetch + diff |
| GET | `/snapshots` | None | — | `List[PolicySnapshotListItem]` | Lightweight list (no `raw_text`) |
| GET | `/snapshots/detail/{id}` | None | path: `id` | `PolicySnapshotPayload` | Full snapshot incl. `raw_text` |
| POST | `/snapshots` | None | body: `{url}` | `PolicySnapshotPayload` | Fetch + hash + store a snapshot |
| GET | `/diff/{id1}/{id2}` | None | path: two snapshot ids | `DiffResult` | Token-level added/removed diff |
| POST | `/policy-watch` | None | `PolicyWatchCreateRequest` (JSON) | `PolicyWatchPayload` | Register a recurring watch |
| GET | `/policy-watch` | None | — | `List[PolicyWatchPayload]` | All registered watches |
| DELETE | `/policy-watch/{id}` | None | path: `id` | `{detail}` | Remove a watch |
| POST | `/policy-watch/{id}/snapshot` | None | path: `id` | `PolicySnapshotPayload` | Manually trigger a snapshot for a watch |

No route currently requires authentication (`Auth` column is `None` throughout) — there is no API-key or session-based auth layer in the shipped backend.

## Key Request Schemas

### AnalyzeRequest
```json
{"text": "...", "name?": "...", "doc_type?": "...", "source_url?": "...", "jurisdictions?": ["US-CA", "GDPR"]}
```

### AnalyzeUrlRequest
```json
{"url": "https://...", "name?": "...", "doc_type?": "...", "jurisdictions?": ["US-CA", "GDPR"]}
```

### ReviewUpdate
```json
{"status": "approved|rejected", "notes?": "..."}
```

### WatchlistCreateRequest
```json
{"vendor": "Acme Corp", "source_url?": "https://..."}
```

### AnalyzeBatchRequest
```json
{"items": [{"url?": "https://...", "name?": "...", "doc_type?": "..."}, ...]}
```

### PolicyWatchCreateRequest
```json
{"url": "https://...", "user_id?": "...", "check_frequency": 86400}
```
`check_frequency` is in seconds, constrained to `[300, 604800]` (5 minutes to 7 days).

## Key Response Schemas

### Finding (nested in AnalysisPayload)
```json
{
  "category": "Sale/Share",
  "severity": "High",
  "confidence": 0.86,
  "excerpt": "We may share...",
  "explanation": "May trigger opt-out...",
  "jurisdictions": ["US-CA"],
  "evidence": {"line_start": 120, "line_end": 126, "legal_basis": ["CCPA/CPRA opt-out"]}
}
```

### AnalysisPayload (key fields)
```json
{
  "id": "uuid", "status": "completed|needs_review", "review_required": false,
  "confidence": 0.91, "risk_score": 6.8, "grade": "C+",
  "findings": [...], "summary": "..."
}
```

### DiffResult
```json
{
  "snapshot_1_id": "uuid", "snapshot_2_id": "uuid", "url": "https://...",
  "created_at_1": "...", "created_at_2": "...",
  "added": [{"text": "..."}], "removed": [{"text": "..."}]
}
```

### PolicySnapshotPayload / PolicySnapshotListItem
```json
{"id": "uuid", "url": "https://...", "content_hash": "sha256...", "captured_at": "...", "raw_text?": "..."}
```
`raw_text` is included on `GET /snapshots/detail/{id}` and `POST /snapshots`, but omitted from the lightweight `GET /snapshots` list to save bandwidth.

## Error Responses

| Status | When |
|--------|------|
| 400 | Empty text, invalid URL, unsupported file type |
| 404 | Analysis/review/watchlist item not found |
| 500 | Unexpected server error |
