# LIB-API: API Endpoints & Contracts

## Endpoint Map

| Method | Path | Auth | Request | Response | Notes |
|--------|------|------|---------|----------|-------|
| GET | `/health` | None | — | `{status, config}` | Health check |
| POST | `/analyze` | None | `AnalyzeRequest` (JSON) | `AnalysisPayload` | Text analysis |
| POST | `/analyze/url` | None | `AnalyzeUrlRequest` (JSON) | `AnalysisPayload` | URL fetch + analysis |
| POST | `/analyze/file` | None | multipart: `file`, `name?`, `doc_type?`, `jurisdictions?` | `AnalysisPayload` | File upload |
| GET | `/analyses` | None | query: `skip`, `limit` | `List[AnalysisSummary]` | Paginated list |
| GET | `/analyses/{id}` | None | path: `id` | `AnalysisPayload` | Single analysis (404 if missing) |
| GET | `/rubric` | None | — | `RubricScores` | Computed from all analyses |
| GET | `/exports/analysis/{id}` | None | path: `id` | JSON file download | |
| GET | `/exports/analyses.csv` | None | — | CSV file download | |
| GET | `/exports/analysis/{id}.pdf` | None | path: `id` | PDF file download | Requires reportlab |
| GET | `/reviews` | None | — | `List[ReviewItemPayload]` | Pending reviews |
| POST | `/reviews/{id}` | None | `ReviewUpdate` (JSON) | `ReviewItemPayload` | Approve/reject |
| GET | `/watchlist` | None | — | `List[WatchlistItemPayload]` | All watchlist items |
| POST | `/watchlist` | None | `WatchlistCreateRequest` (JSON) | `WatchlistItemPayload` | Add vendor |
| DELETE | `/watchlist/{id}` | None | path: `id` | `{detail}` | Remove vendor |
| POST | `/watchlist/{id}/refresh` | None | path: `id` | `WatchlistItemPayload` | Re-fetch + diff |

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

## Error Responses

| Status | When |
|--------|------|
| 400 | Empty text, invalid URL, unsupported file type |
| 404 | Analysis/review/watchlist item not found |
| 500 | Unexpected server error |
