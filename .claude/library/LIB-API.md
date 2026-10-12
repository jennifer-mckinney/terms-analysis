# LIB-API — endpoints, request/response schemas, error contracts
loads: on-trigger
scope: project
xref: [[LIB-ARCH]] [[LIB-RULES]] [[LIB-CONTEXT]] [[.claude/rules/testing.md#R2]]

status (2026-10-12): endpoint map = 26 business routes + `/health` = 27 total, verified against the `@app.*` decorators in `main.py` (grep count = 30, minus the three key-protected docs routes `/openapi.json`, `/docs` and `/redoc`, which are not listed). `/infer` added per SO8.

## endpoint-map

| Method | Path | Auth | Request | Response | Notes |
|--------|------|------|---------|----------|-------|
| GET | `/health` | None (own rate limit) | — | `{status, model_world, model_eu, review_threshold}` | Health check |
| POST | `/infer` | API key | `InferRequest` (JSON: `url?`, `text?`) | `InferResponse` (jurisdictions, doc_type, industry hints) | TLD/text signals; `@lru_cache` on hot paths; see SO8 |
| POST | `/analyze` | API key + analysis admission | `AnalyzeRequest` (JSON) | `AnalysisPayload` | Text analysis |
| POST | `/analyze/url` | API key + analysis admission | `AnalyzeUrlRequest` (JSON) | `AnalysisPayload` | URL fetch + analysis |
| POST | `/analyze/file` | API key + analysis admission | multipart: `file`, `name?`, `doc_type?`, `jurisdictions?` | `AnalysisPayload` | File upload |
| POST | `/analyze/batch` | API key + batch admission | `AnalyzeBatchRequest` | `dict` (per-item) | Batch of URLs/files |
| GET | `/analyses` | API key | query: `skip`, `limit` | `List[AnalysisSummary]` | Paginated list |
| GET | `/rubric` | API key | — | `RubricScores \| None` | Computed from all analyses |
| GET | `/analyses/{id}` | API key | path: `id` | `AnalysisPayload` | 404 if missing |
| GET | `/exports/analyses.csv` | API key | — | CSV download | |
| GET | `/exports/analysis/{id}.pdf` | API key | path: `id` | PDF download | Requires reportlab; route registered BEFORE both JSON routes below so not shadowed |
| GET | `/exports/analysis/{id}.json` | API key | path: `id` | JSON attachment: stored analysis + `schema_version`, indent 2 | PRD F5.2 path (#36); registered BEFORE the alias below |
| GET | `/exports/analysis/{id}` | API key | path: `id` | JSON attachment (as `.json`) | Alias of `.json`: same handler, byte-identical response |
| GET | `/reviews` | API key | — | `List[ReviewItemPayload]` | Pending reviews |
| POST | `/reviews/{id}` | API key | `ReviewUpdate` | `ReviewItemPayload` | Approve/reject |
| GET | `/watchlist` | API key | — | `List[WatchlistItemPayload]` | All items |
| POST | `/watchlist` | API key | `WatchlistCreateRequest` | `WatchlistItemPayload` | Add vendor |
| DELETE | `/watchlist/{id}` | API key | path: `id` | `{detail}` | Remove vendor |
| POST | `/watchlist/{id}/refresh` | API key | path: `id` | `WatchlistItemPayload` | Re-fetch + diff |
| GET | `/snapshots` | API key | — | `List[PolicySnapshotListItem]` | Lightweight (no `raw_text`) |
| GET | `/snapshots/detail/{id}` | API key | path: `id` | `PolicySnapshotPayload` | Full incl. `raw_text` |
| POST | `/snapshots` | API key | body: `{url}` | `PolicySnapshotPayload` | Fetch + hash + store |
| GET | `/diff/{id1}/{id2}` | API key | path: two snapshot ids | `DiffResult` | Token-level diff |
| POST | `/policy-watch` | API key | `PolicyWatchCreateRequest` | `PolicyWatchPayload` | Register watch |
| GET | `/policy-watch` | API key | — | `List[PolicyWatchPayload]` | All watches |
| DELETE | `/policy-watch/{id}` | API key | path: `id` | `{detail}` | Remove watch |
| POST | `/policy-watch/{id}/snapshot` | API key | path: `id` | `PolicySnapshotPayload` | Manually trigger snapshot |

### API1: api-key-auth
rule: since #133 every route runs the global `security.enforce_access` dependency: a pre-auth rate limit by peer, then the `X-API-Key` check (401 on a missing or wrong key). `/health` has its own limit and needs no key. With `DEPLOY_ENV=local`, an empty key and a loopback bind, loopback peers without a forwarding header are served without a key. In the Auth column, "API key" means this global check; "analysis admission" / "batch admission" add the per-client and per-key limits and the concurrency cap (`security.analysis_admission` / `security.batch_admission`)

### API2: export-route-ordering
rule: in `main.py` the export routes register in this order: `/exports/analysis/{id}.pdf`, then `/exports/analysis/{id}.json`, then the alias `/exports/analysis/{id}`
because: Starlette matches routes in registration order and `{id}` is greedy, so the alias registered earlier would capture `<id>.pdf` or `<id>.json` as a literal ID and 404
body (PRD F5.2, #36): both JSON routes share one handler. It returns the stored analysis plus one top-level `schema_version` (`schemas.EXPORT_SCHEMA_VERSION`), as `json.dumps(indent=2)` UTF-8 with `Content-Type: application/json` and `Content-Disposition: attachment; filename="analysis-<id>.json"`. Any character in the ID outside `A-Z a-z 0-9 . _ -` becomes `_` in the filename. Errors (404, 401, 429) stay compact JSON with no Content-Disposition

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
  "findings": [...], "summary": "...",
  "legal_grounding": true,
  "legal_grounding_authoritative": false,
  "llm_status": "ok",
  "legal_context": [
    {"jurisdiction": "GDPR", "law": "gdpr", "section": "Article 17 — Right to erasure",
     "status": "placeholder", "score": 0.0328}
  ]
}
```

### API6: legal-grounding-fields (issue #91)
rule: `legal_grounding` (bool, default false) = the legal-KB index loaded and retrieval ran against it. True even when every candidate fell below `LEGAL_KB_MIN_SCORE` (then `legal_context=[]`; only possible when the floor is set) and even when every passage is placeholder text. False when the index is missing or empty, retrieval errored (incl. zero-norm query embedding = broken embedder, or a KB returning no `RetrievalStatus`), or `mode=quick`; `legal_context` is then always `[]` and no KB passage reached the LLM prompt
rule: `legal_grounding_authoritative` (bool, default false) = `legal_grounding` AND `LEGAL_KB_MIN_SCORE` is set AND at least one citation has a status in the allowlist `schemas.AUTHORITATIVE_STATUSES` = `{"in_force"}` (vocabulary from legal-corpus-ingester `pipeline/status_rules.py::resolve_status`) AND is a citation with a known, requested jurisdiction (any known one when none was requested) (SO5: none requested = `jurisdictions=[]`); known = in `schemas.KNOWN_JURISDICTIONS`, derived from the `Jurisdiction` Literal. Fails closed: null, unknown, typo, `not_yet_in_force` and `placeholder` statuses are NOT authoritative, and neither is a passage with a null, blank or unrecognised jurisdiction (in every mode) or one from another jurisdiction (retrieval falls back to the full corpus when no passage matches the requested ones; those passages are labelled OUT OF JURISDICTION in the prompt). One table decides both the flag and the prompt labels: `schemas.passage_label_keys` / `PASSAGE_LABELS`. Clients MUST use this, not `legal_grounding`, before presenting an analysis as grounded in law
rule: relevance floor `LEGAL_KB_MIN_SCORE` defaults to unset = DISABLED (owner ruling 2026-10-07, "Disabled + loud"): NO_MATCH cannot be reported without a floor, a WARNING is logged at startup, and `legal_grounding_authoritative` is forced false. A set value must be finite and in (-1, 1] or startup fails (-1 keeps every candidate, so it is rejected as the disabled floor in disguise). `LEGAL_KB_TOP_K` must be an integer >= 1 or startup fails
rule: prompt labels: every passage that is not authoritative law for the analysis carries a label from `schemas.PASSAGE_LABELS` (UNVERIFIED PLACEHOLDER, NOT YET IN FORCE, UNVERIFIED PROVENANCE for null/unknown status, UNKNOWN JURISDICTION for a null, blank or unrecognised jurisdiction, OUT OF JURISDICTION), and the prompt's NEVER-cite rule names every marker. Each passage is one header line `[<jurisdiction> <section>]`, emitted only by `prompts.render_passage_header`: the canonical `KNOWN_JURISDICTIONS` code or `Law` (never the raw value) and the section through `schemas.normalise_section_title` with whitespace collapsed, so it holds no `[`, `]` or line break. Every line of passage text follows behind `prompts.PASSAGE_BODY_PREFIX` (`    > `), so no text line can look like a header
rule: index metadata: every chunk must be an object with a string `text`; `jurisdiction`, `law`, `section`, `status` must each be a string or null, every string key and value must be valid UTF-8 (no lone surrogate, as `json.loads` makes from `"\ud800"`), and `section` must hold no control / line-break character. Undecodable bytes in a metadata or corpus file are `LegalKBIndexCorruptError` too, for build, load and `load_from_bundle`. `section` is first normalised by `schemas.normalise_section_title` (`[`/`]` become `(`/`)`, format (Cf) characters are stripped), so `## Article 6 [Lawfulness]` is valid. One `legal_kb._validate_chunks` runs at build (per corpus file, before anything is embedded or written; the `index` CLI then exits 1 with no index written) and at load, where anything else is `LegalKBIndexCorruptError` (ERROR, analysis ungrounded, still 200), never a response-validation 500. A jurisdiction holding a Cf character is unknown (rejected, not stripped)
rule: `legal_context` (List[LegalCitation], default `[]`) = KB passages supplied to the LLM prompt; metadata only, no passage text
schema: `LegalCitation` = `{jurisdiction?: str, law?: str, section?: str, status?: str, score?: float}`; `status` is always stripped + lower-cased (`"placeholder"` = synthetic, non-authoritative text); `score` is the RRF fusion score (rank-based, not a probability)
because: the shipped corpus is entirely `# Status: PLACEHOLDER`, so "retrieval ran" and "grounded in law" must be separate signals
back_compat: rows stored before these fields existed load with the false / `[]` defaults

### API7: llm-status (issue #195)
rule: `llm_status` (`schemas.LLMStatus`, default `"unknown"`) = outcome of the LLM step: `ok` (a validated `LLMAnswer` was used) | `fallback_llm_unreachable` (httpx `TransportError`, incl. timeouts) | `fallback_llm_invalid` (a 2xx answer failed parsing or `LLMAnswer`) | `fallback_llm_error` (non-2xx, model selection, prompt build, encoding, unforeseen exception) | `disabled` (quick mode). Every `fallback_*` value means HR5 rules-only findings with reduced confidence and `review_required` from the settings threshold. `"unknown"` appears only on rows stored before #195; a fresh analysis never emits it
rule: the value is a fixed token: never exception text, never set by the model's answer, never derived from a client attribute; `ok` comes only from a returned, validated answer
because: operators and the UI must tell a LocalAI outage from an always-fallback bug (G0-2 F2-S2) from a normal run
back_compat: additive; one new field with a default, nothing else on the payload changed

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
