# LIB-API — endpoints, request/response schemas, error contracts
loads: on-trigger
scope: project
xref: [[LIB-ARCH]] [[LIB-RULES]] [[LIB-CONTEXT]] [[.claude/rules/testing.md#R2]]

status (2026-07-03): endpoint map = 24 business routes + `/health` = 25 total, verified against `main.py` `@app.*` decorators.

## endpoint-map

| Method | Path | Auth | Request | Response | Notes |
|--------|------|------|---------|----------|-------|
| GET | `/health` | None | — | `{status, model_world, model_eu, review_threshold}` | Health check |
| POST | `/analyze` | None | `AnalyzeRequest` (JSON) | `AnalysisPayload` | Text analysis |
| POST | `/analyze/url` | None | `AnalyzeUrlRequest` (JSON) | `AnalysisPayload` | URL fetch + analysis |
| POST | `/analyze/file` | None | multipart: `file`, `name?`, `doc_type?`, `jurisdictions?` | `AnalysisPayload` | File upload |
| POST | `/analyze/batch` | None | `AnalyzeBatchRequest` | `dict` (per-item) | Batch of URLs/files |
| GET | `/analyses` | None | query: `skip`, `limit` | `List[AnalysisSummary]` | Paginated list |
| GET | `/rubric` | None | — | `RubricScores \| None` | Computed from all analyses |
| GET | `/analyses/{id}` | None | path: `id` | `AnalysisPayload` | 404 if missing |
| GET | `/exports/analyses.csv` | None | — | CSV download | |
| GET | `/exports/analysis/{id}.pdf` | None | path: `id` | PDF download | Requires reportlab; route registered BEFORE JSON export below so not shadowed |
| GET | `/exports/analysis/{id}` | None | path: `id` | JSON download | |
| GET | `/reviews` | None | — | `List[ReviewItemPayload]` | Pending reviews |
| POST | `/reviews/{id}` | None | `ReviewUpdate` | `ReviewItemPayload` | Approve/reject |
| GET | `/watchlist` | None | — | `List[WatchlistItemPayload]` | All items |
| POST | `/watchlist` | None | `WatchlistCreateRequest` | `WatchlistItemPayload` | Add vendor |
| DELETE | `/watchlist/{id}` | None | path: `id` | `{detail}` | Remove vendor |
| POST | `/watchlist/{id}/refresh` | None | path: `id` | `WatchlistItemPayload` | Re-fetch + diff |
| GET | `/snapshots` | None | — | `List[PolicySnapshotListItem]` | Lightweight (no `raw_text`) |
| GET | `/snapshots/detail/{id}` | None | path: `id` | `PolicySnapshotPayload` | Full incl. `raw_text` |
| POST | `/snapshots` | None | body: `{url}` | `PolicySnapshotPayload` | Fetch + hash + store |
| GET | `/diff/{id1}/{id2}` | None | path: two snapshot ids | `DiffResult` | Token-level diff |
| POST | `/policy-watch` | None | `PolicyWatchCreateRequest` | `PolicyWatchPayload` | Register watch |
| GET | `/policy-watch` | None | — | `List[PolicyWatchPayload]` | All watches |
| DELETE | `/policy-watch/{id}` | None | path: `id` | `{detail}` | Remove watch |
| POST | `/policy-watch/{id}/snapshot` | None | path: `id` | `PolicySnapshotPayload` | Manually trigger snapshot |

### API1: no-auth-currently
rule: no route requires authentication; there is no API-key or session auth layer in the shipped backend

### API2: pdf-route-ordering
rule: `/exports/analysis/{id}.pdf` MUST be registered BEFORE `/exports/analysis/{id}` in `main.py`
because: FastAPI would otherwise shadow the PDF route with the JSON route

### API3: cross-endpoint-field-parity
rule: a field validated on `/analyze` MUST be validated identically on `/analyze/url`, `/analyze/file`, `/analyze/batch`
xref: [[.claude/rules/testing.md#R2]]

## request-schemas

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

### API4: check_frequency-bounds
rule: `check_frequency` in seconds, constrained to `[300, 604800]` (5 min to 7 days)

## response-schemas

### Finding
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

### AnalysisPayload
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

### API5: raw_text-inclusion
rule: `raw_text` included on `GET /snapshots/detail/{id}` and `POST /snapshots`; omitted from lightweight `GET /snapshots` list
because: bandwidth

## errors

| Status | When |
|--------|------|
| 400 | Empty text, invalid URL, unsupported file type |
| 404 | Analysis/review/watchlist item not found |
| 500 | Unexpected server error |
