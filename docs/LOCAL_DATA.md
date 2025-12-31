# Local Data Handling and Backups

## Storage Locations
- SQLite database: `data/terms_analysis.db` (created when the backend starts).
- Exports: generated on demand via the `/exports/*` endpoints and downloaded by the browser.
- Cached artifacts: OCR and extracted text live in memory only; raw document text is persisted in SQLite.

## Local-Only Model Usage
- The application calls LM Studio on the LAN (`LM_STUDIO_BASE_URL`).
- No cloud APIs are used by default. Keep the LM Studio host accessible only on your trusted network.

## Backup Guidance
- **Quick backup**: copy the SQLite database file.
  ```bash
  cp data/terms_analysis.db backups/terms_analysis_$(date +%Y%m%d).db
  ```
- **Structured export**: use the CSV or JSON export endpoints for analyses.
  - CSV: `GET /exports/analyses.csv`
  - JSON: `GET /exports/analysis/{id}`

## Restore Guidance
- Stop the backend, replace `data/terms_analysis.db` with the backup, then restart the backend.
- If the schema changes, recreate the database by deleting the file and re-running the app.

## Deletion and Retention
- To purge data completely, delete `data/terms_analysis.db`.
- Consider encrypted disk storage if you store sensitive policies locally.

## Configuration Tips
- Keep `.env` local and uncommitted.
- Use `WATCHLIST_REFRESH_SECONDS` to control the watchlist polling interval.
