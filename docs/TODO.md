# TODO

## High Priority
- [x] Persist raw document text with line offsets for Verify view highlighting.
- [x] Add OCR fallback for scanned PDFs (local-only).
- [x] Add review queue UI (list, approve/reject, notes) tied to `/reviews`.

## Analysis and Validation
- [x] Enforce legal-basis citations for every finding in LLM output.
- [x] Add citation coverage checks and hallucination guards.
- [x] Expand rule patterns for US-CA + GDPR (sale/share, ADM, retention, rights).
- [x] Calibrate confidence scoring and threshold behavior.

## Watchlist
- [x] Implement scheduled URL re-fetch for watchlist items.
- [x] Compute diffs between versions and update `risk_delta`.
- [x] Surface change summaries in the watchlist UI.

## Exports
- [x] Add JSON/CSV/PDF export endpoints.
- [x] Wire Reports page to real export actions.

## UX and UI
- [x] Show “Needs Review” badges in the dashboard and analysis list.
- [x] Allow selecting jurisdictions in the UI.
- [x] Handle offline/back-end unavailable states gracefully.

## Testing and Evaluation
- [x] Build gold dataset for US-CA + GDPR and run F1/Kappa.
- [x] Add unit tests for ingestion and rule detectors.
- [x] Add integration tests for LocalAI failures and timeouts.

## Ops and Docs
- [x] Extend `run.sh` to start backend + frontend together.
- [x] Add `.env.example` with LocalAI, model paths, and DB settings.
- [x] Document local-only data handling and backup guidance.
