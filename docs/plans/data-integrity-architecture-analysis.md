# DATA INTEGRITY & ARCHITECTURE ANALYSIS
## AI Terms & Policies Reviewer — Current State → Future State

**Project:** terms-analysis
**Date:** 2026-02-07
**Scope:** Full analysis pipeline integrity — rule engine, LLM integration, validation, planned RAG pipeline
**Compliance Target:** Macro F1 >= 0.70, Kappa >= 0.65, confidence-gated human-in-the-loop review

---

## 1. EXECUTIVE SUMMARY

### System Identity

| Key | Value |
|-----|-------|
| Purpose | Analyze Terms of Service / Privacy Policies for compliance risks |
| Detection Method | Rule-based regex → LLM augmentation → merge → validation |
| Risk Scoring | IRP: `0.5*(I/5) + 0.4*(L/5) - 0.3*(S/5)` |
| Jurisdictions | US-CA (CCPA/CPRA), EU (GDPR) — planned: PIPEDA, US-CO, US-CT, US-NY |
| Quality Gate | Confidence < 0.80 triggers human review |

### Architecture Maturity

| Layer | Current State | Target State | Gap Severity |
|-------|---------------|--------------|-------------|
| Rule Engine | 9 categories, 38 regex patterns | Same + RAG-augmented pattern suggestions | LOW |
| LLM Integration | LM Studio client, single model | Ollama + SaulLM-7B, legal-domain inference | **HIGH** |
| Embeddings | None | FAISS + modernbert-legal-8192 | **CRITICAL** |
| Legal Corpus | None | EUR-Lex, CCPA/CPRA, PIPEDA chunked + indexed | **CRITICAL** |
| Validation | Hallucination guards, citation checks | Same + cross-reference against legal corpus | MEDIUM |
| Data Storage | SQLite, full text in DB | Same + vector index for legal text | MEDIUM |
| Test Coverage | ~5-8% (5 tests) | 85% line, 75% branch | **HIGH** |

---

## 2. CURRENT ANALYSIS PIPELINE — INTEGRITY AUDIT

### 2.1 End-to-End Data Flow (Today)

```
User Input (text/URL/file)
    |
    v
[STAGE 1: Ingestion] — ingest.py
    - File type detection (txt, html, pdf, docx, rtf)
    - Text extraction (BeautifulSoup, pypdf, python-docx, striprtf, pytesseract OCR)
    - Encoding detection (utf-8, utf-16, latin-1 fallback)
    - Normalization (CRLF → LF, strip whitespace)
    |
    v
[STAGE 2: Truncation] — analyzer.py:24-27
    - Hard cap at MAX_INPUT_CHARS (20,000 chars)
    - Silent truncation: no warning to user if document exceeds limit
    |
    v
[STAGE 3: Rule Detection] — rules.py
    - 9 categories × 38 regex patterns against full text
    - Jurisdiction filtering (skip patterns not relevant to selected jurisdictions)
    - Confidence calculation: 0.25 + 0.5*base + 0.15*hit_ratio + 0.1*density
    - Confidence clamping: [0.35, 0.95]
    |
    v
[STAGE 4: LLM Augmentation] — lm_studio.py
    - Line-numbered text + rule findings sent to LLM
    - System prompt: "legal-risk analyst" role, JSON-only output
    - Temperature: 0.1, max_tokens: 1200
    - Endpoint: /v1/chat/completions (OpenAI-compatible API)
    |
    v
[STAGE 5: LLM Response Parsing] — analyzer.py:95-110
    - JSON decode of raw content string
    - Finding construction with Pydantic validation
    - Legal basis filter: findings without legal_basis are DROPPED
    - Dropped findings penalize confidence
    |
    v
[STAGE 6: Merge] — analyzer.py:150-162
    - Deduplication key: (category.lower(), excerpt[:120].lower())
    - Rule findings take priority (processed first in iteration)
    - No confidence blending for near-duplicates
    |
    v
[STAGE 7: Validation] — validation.py
    - Hallucination detection: missing excerpt, invalid line numbers, out-of-range lines
    - Citation coverage: excerpt verified against cited line span
    - Missing jurisdictions check
    - Missing legal basis check
    - Confidence penalty: 0.03/issue + 0.07/missing_citation + 0.08/hallucination
    - Coverage threshold: < 70% citation coverage triggers additional penalty
    |
    v
[STAGE 8: Scoring & Grading] — analyzer.py:46-67
    - Risk score: weighted average of severity (Low=0.2, Med=0.5, High=0.8, Crit=1.0) × 10
    - Grade: A (< 3.5), A- (< 4.5), B (< 5.5), B- (< 6.5), C+ (< 7.5), C (< 8.5), D+
    - Review flag: confidence < 0.80
    |
    v
[STAGE 9: Persistence] — main.py
    - SQLite: analyses table (full result JSON), review_items table, watchlist_items table
    - Review items auto-created when confidence < threshold
    |
    v
Output to User (via SPA or API)
```

### 2.2 Integrity Checkpoints — What EXISTS Today

| Checkpoint | Location | What It Validates | Adequate? |
|------------|----------|-------------------|-----------|
| Pydantic schema validation | `schemas.py` | Finding structure, confidence [0,1], risk [0,10], severity enum | YES |
| Confidence clamping | `rules.py:167` | Rule confidence within [0.35, 0.95] | YES |
| Line number validation | `validation.py:35-40` | line_start >= 1, line_end >= 1, start <= end, within doc range | YES |
| Excerpt verification | `validation.py:46-55` | Excerpt text exists in cited line span (normalized comparison) | YES |
| Legal basis filter | `analyzer.py:105-107` | LLM findings without legal_basis are dropped | YES |
| LLM failure fallback | `analyzer.py:118-119` | If LLM returns None, confidence reduced by 20% | PARTIAL |
| Hallucination penalties | `validation.py:59-64` | Cumulative penalties for each validation failure | YES |
| Review threshold gate | `analyzer.py:128-129` | confidence < 0.80 triggers human review | YES |

### 2.3 Integrity Checkpoints — What Is MISSING

| Gap | Severity | Description | Stage |
|-----|----------|-------------|-------|
| No input size warning | MEDIUM | `_truncate_text()` silently truncates at 20k chars. User doesn't know analysis is partial. | Stage 2 |
| No document language detection | MEDIUM | Non-English documents processed without warning. Rules are English-only regex. | Stage 1 |
| No LLM response timeout tracking | HIGH | `request_timeout_s=60` exists but no metric on how often timeouts occur. Silent degradation. | Stage 4 |
| No LLM model version tracking | **CRITICAL** | No record of which LLM model produced which findings. If model changes, historical comparisons are invalid. | Stage 4 |
| No merge conflict resolution | MEDIUM | When rule and LLM find same category but different excerpts/severity, first-seen wins. No confidence blending. | Stage 6 |
| No finding provenance | HIGH | Each finding has no `source` field (rule vs LLM). Cannot audit which engine found what. | Stage 6 |
| No validation of LLM JSON schema | HIGH | LLM output parsed with bare `Finding(**item)` in try/except. Malformed fields silently dropped. | Stage 5 |
| No document hash tracking per analysis | MEDIUM | `diffing.py` has `content_hash()` but analysis records don't store document hash. Cannot detect re-analysis of same text. | Stage 9 |
| No confidence calibration dataset | HIGH | Confidence formula is hand-tuned. No empirical validation that 0.80 threshold is optimal. | Stage 8 |
| No category coverage reporting | MEDIUM | If a document triggers 0 findings for a jurisdiction, no report of "clean" categories. Could be false negative. | Stage 3 |

---

## 3. RULE ENGINE INTEGRITY

### 3.1 Current Pattern Analysis

**File:** `src/backend/app/services/rules.py` (202 lines)

| Category | Severity | Jurisdictions | Pattern Count | Pattern Quality |
|----------|----------|---------------|---------------|----------------|
| Sale/Share | High | US-CA | 4 | MEDIUM — `\bshare\b.*\bpersonal\b` over-matches (e.g., "share personal stories") |
| ADM | High | GDPR | 4 | GOOD — specific legal terms |
| Dark Patterns | Medium | US-CA, GDPR | 5 | GOOD — captures consent coercion |
| Retention | Medium | US-CA, GDPR | 5 | MEDIUM — `\bretain\b` over-matches |
| User Rights | Medium | US-CA, GDPR | 6 | LOW — `\baccess\b` extremely broad |
| Minors | High | US-CA, GDPR | 3 | GOOD — specific triggers |
| Sensitive Data | High | US-CA, GDPR | 4 | MEDIUM — `\bsensitive\b` context-dependent |
| Unilateral Changes | Medium | US-CA, GDPR | 3 | GOOD — clear patterns |
| Liability | Medium | US-CA, GDPR | 3 | GOOD — specific legal terms |

**Total: 9 categories, 37 patterns**

### 3.2 Pattern Precision Risks

| Risk | Severity | Pattern | Problem |
|------|----------|---------|---------|
| False positive: "access" | HIGH | `User Rights: r"access"` | Matches "access to our website", "access your account" — not rights-related |
| False positive: "share" | HIGH | `Sale/Share: r"\bshare\b.*\bpersonal\b"` | Matches "share personal experiences" |
| False positive: "retain" | MEDIUM | `Retention: r"retain"` | Matches "retain the right to..." (not data retention) |
| False positive: "sensitive" | MEDIUM | `Sensitive Data: r"sensitive"` | Matches "time-sensitive" |
| Missing PIPEDA patterns | HIGH | None | No Canadian jurisdiction patterns exist. PIPEDA rules needed for expansion. |
| Missing US state patterns | HIGH | None | Colorado, Connecticut, New York rules all missing. |
| No negative patterns | MEDIUM | All | No exclusion patterns to filter common false positives |

### 3.3 Confidence Formula Analysis

**Formula:** `score = 0.25 + 0.5 * base + 0.15 * hit_ratio + 0.1 * density`

| Component | Weight | Range | Risk |
|-----------|--------|-------|------|
| Constant | 0.25 | 0.25 | Ensures minimum confidence even with weak match. May be too high for single-pattern hits. |
| Severity base | 0.50 | 0.225–0.45 | Dominates the score. High severity = high confidence regardless of match quality. |
| Hit ratio | 0.15 | 0–0.15 | Rewards matching multiple patterns. Good signal. |
| Density | 0.10 | 0–0.10 | Rewards repeated matches. Capped at 5 occurrences. |

**Maximum possible:** 0.25 + 0.45 + 0.15 + 0.10 = 0.95 (matches clamp ceiling)
**Minimum possible:** 0.25 + 0.225 + 0 + 0.02 = 0.495 (but clamped to 0.35 floor)

**Issue:** A single match of a High-severity pattern produces confidence ~0.60, which is well above the 0.35 floor but below the 0.80 review threshold. This seems well-calibrated, but without empirical validation against labeled data, we cannot verify.

---

## 4. LLM INTEGRATION INTEGRITY

### 4.1 Current State (LM Studio Client)

**File:** `src/backend/app/services/lm_studio.py` (89 lines)

| Aspect | Current | Risk |
|--------|---------|------|
| Endpoint | `/v1/chat/completions` | LOW — standard OpenAI-compatible API |
| Model | `qwen3-vl-4b-instruct-mlx` (config default) | **HIGH** — general model, not legal-domain |
| Temperature | 0.1 | GOOD — low creativity for factual analysis |
| Max tokens | 1200 | MEDIUM — may truncate findings for complex documents |
| Timeout | 60s | ADEQUATE |
| Error handling | Returns `None` on any failure | GOOD — graceful degradation to rule-only |

### 4.2 LLM Failure Modes

| Failure Mode | Current Handling | Adequacy |
|-------------|-----------------|----------|
| HTTP connection refused | Returns None, falls back to rules | GOOD |
| HTTP 4xx/5xx | Returns None, logs status + body[:300] | GOOD |
| JSON decode failure (invalid JSON) | Returns None, logs warning | GOOD |
| Missing `choices[0].message.content` path | Returns None, logs warning | GOOD |
| Valid JSON but wrong schema | Bare `Finding(**item)` in try/except, silently drops | **POOR** — no logging of dropped findings |
| Hallucinated content (plausible but wrong) | Validation catches some via citation check | **PARTIAL** — cannot catch semantically plausible hallucinations |
| Model returns findings for wrong jurisdiction | No jurisdiction cross-check post-LLM | **MISSING** |
| Model invents legal basis | No legal basis verification | **MISSING** |

### 4.3 Migration Path: LM Studio → Ollama + SaulLM

**Current:** LM Studio (proprietary) + general-purpose model
**Target:** Ollama CLI (MIT) + SaulLM-7B-Instruct (MIT, trained on 30B legal tokens)

| Migration Risk | Severity | Description | Mitigation |
|----------------|----------|-------------|------------|
| API compatibility | LOW | Ollama serves same `/v1/chat/completions` endpoint | Update `LM_STUDIO_BASE_URL` env var only |
| Model output format | **HIGH** | SaulLM may produce different JSON structure than Qwen | Build golden test set, validate output schema before cutover |
| Legal domain accuracy | **POSITIVE** | SaulLM trained on EUR-Lex, US case law, UK legislation | Expected improvement in legal basis accuracy |
| Response latency | MEDIUM | 7B model on local hardware may be slower than 4B Qwen | Benchmark before cutover, may need timeout adjustment |
| Config tracking | HIGH | `config.py:30` default model is hardcoded | Must update default AND track model version per analysis |

**RULE: LLM Migration Checklist (MANDATORY)**

```
1. NEVER switch models without running golden test set comparison
2. Record model identifier with EVERY analysis result
3. If precision drops > 5% on golden test set, ROLLBACK
4. Update config.py defaults AND .env.example AND docs/DESIGN.md
5. Run full F1/Kappa evaluation before and after migration
```

### 4.4 Prompt Integrity

**File:** `src/backend/app/services/prompts.py` (55 lines)

| Aspect | Assessment |
|--------|------------|
| System prompt | Clear role definition, JSON-only instruction, no-hallucination guardrail | GOOD |
| Schema specification | Exact JSON schema in user prompt | GOOD |
| Line number instruction | "Every finding must cite line numbers" | GOOD |
| Legal basis instruction | "Every finding must include at least one legal_basis" | GOOD |
| Rule findings context | Passed as `rule_findings` for LLM to build upon | GOOD |
| Missing: few-shot examples | No examples of correct output | GAP — could reduce schema errors |
| Missing: jurisdiction-specific guidance | No jurisdiction-specific legal terms in prompt | GAP — LLM must infer from general knowledge |
| Missing: negative examples | No "do not include" examples | GAP — would reduce false positives |

---

## 5. VALIDATION PIPELINE INTEGRITY

### 5.1 Current Validation (validation.py)

**File:** `src/backend/app/services/validation.py` (67 lines)

| Check | What It Catches | Effectiveness |
|-------|----------------|---------------|
| Missing excerpt | Finding with empty excerpt field | HIGH — catches structural hallucination |
| Invalid line numbers | line_start < 1, line_end < 1, start > end | HIGH — catches nonsensical citations |
| Out-of-range lines | Line numbers exceed document length | HIGH — catches out-of-bounds hallucination |
| Missing jurisdictions | Finding without jurisdiction list | MEDIUM — structural check only |
| Missing legal basis | Finding without legal_basis list | HIGH — key quality signal |
| Citation coverage | Excerpt text verified in cited line span | **HIGHEST** — catches fabricated quotes |
| Low coverage penalty | < 70% of findings have verified citations | HIGH — flags systematic hallucination |

### 5.2 Validation Gaps

| Gap | Severity | What It Would Catch |
|-----|----------|---------------------|
| No jurisdiction cross-check | HIGH | Finding claims GDPR but document only analyzed for US-CA |
| No severity consistency check | MEDIUM | Same category found with conflicting severity by rule vs LLM |
| No duplicate category warning | LOW | Multiple findings for same category may indicate over-detection |
| No confidence floor enforcement post-validation | MEDIUM | Validation can reduce confidence below 0.0 floor (clamped at max(0.0,...) but penalties can stack) |
| No semantic validation | HIGH | Cannot verify that "Sale/Share" finding actually describes data sale, not "sharing stories" |
| No legal basis verification | **CRITICAL** | Cannot verify that cited legal basis (e.g., "GDPR Art. 22") is real and applicable |
| No cross-finding consistency | MEDIUM | Finding A says "no retention policy" while Finding B cites retention language |

### 5.3 Confidence Penalty Stack Risk

**Current penalty formula:**
```
penalty = 0.03 * len(issues) + 0.07 * missing_citations + 0.08 * hallucination_flags
```

**Worst case:** 10 findings, all with issues (0.30) + all missing citations (0.70) + all hallucinated (0.80) = penalty 1.80. Confidence floors at 0.0, triggering human review.

**Best case:** 0 issues = 0 penalty. Confidence passes through unchanged.

**Risk:** The penalty is ADDITIVE per finding. More findings = higher penalty potential, even if most findings are valid. A document with 20 findings where 2 are invalid gets penalized more heavily than a document with 3 findings where 1 is invalid. This penalizes thoroughness.

**Recommendation:** Normalize penalty by finding count: `penalty_per_finding = total_penalty / len(findings)`

---

## 6. PLANNED RAG PIPELINE — FUTURE STATE INTEGRITY

### 6.1 Planned Architecture

```
Legal Corpus (EUR-Lex, CCPA text, PIPEDA text)
    |
    v
[STAGE A: Chunking] — legal_kb.py (PLANNED)
    - Chunk legal texts by article/section (1000-2000 tokens)
    - Preserve section headers and article numbers
    - Store source jurisdiction and effective date
    |
    v
[STAGE B: Embedding] — embeddings.py (PLANNED)
    - Model: modernbert-embed-base-8192 (Apache 2.0)
    - Dimension: 768
    - Chunk text → vector
    |
    v
[STAGE C: Indexing] — FAISS (MIT)
    - IndexFlatIP (inner product) for initial implementation
    - Index per jurisdiction for efficient retrieval
    |
    v
[STAGE D: Retrieval] — At analysis time
    - Finding excerpt → embed → similarity search → top-k legal text chunks
    - Retrieved chunks augment LLM prompt with actual legal language
    |
    v
[STAGE E: Augmented Generation] — Enhanced prompts.py
    - System prompt includes retrieved legal context
    - LLM can cite specific articles/sections from retrieved chunks
    - Legal basis becomes VERIFIABLE against corpus
```

### 6.2 RAG Integrity Risks

| Risk | Severity | Description | Mitigation |
|------|----------|-------------|------------|
| Embedding model mismatch | **CRITICAL** | Query embeddings must use same model as corpus embeddings. Different models = meaningless similarity scores. | Track embedding model version in FAISS metadata. Reject queries if model mismatch. |
| Partial re-indexing | **CRITICAL** | If re-embedding fails midway, index contains mixed-model vectors. Similarity queries return garbage. | Atomic index rebuild: new index → verify → swap. Never modify live index. |
| Stale legal corpus | HIGH | Laws change. EUR-Lex articles get amended. CCPA/CPRA has regular updates. Stale chunks = wrong legal citations. | Track `effective_date` and `indexed_at` per chunk. Flag results from stale sources. |
| Chunk boundary errors | HIGH | If article is split across chunks, retrieval may return partial context. LLM gets incomplete legal text. | Overlap chunks by 200 tokens. Store `article_id` for chunk reassembly. |
| Irrelevant retrieval | MEDIUM | Similarity search returns legal text that is semantically similar but legally irrelevant (different jurisdiction, different topic). | Filter by jurisdiction before similarity search. Return similarity score for confidence weighting. |
| FAISS index corruption | MEDIUM | FAISS indexes are binary files. Corruption from interrupted writes is unrecoverable. | Snapshot before every rebuild. Verify index integrity after write. |
| Legal corpus licensing | LOW | All planned sources are open (EUR-Lex CC-BY-4.0, US law public domain, PIPEDA public domain). | Document license per source. Reject proprietary legal texts. |

### 6.3 RAG Integrity Rules

**RULE: Embedding Version Tracking (MANDATORY)**

```
Every FAISS index MUST include metadata file:
  - embedding_model: exact model identifier
  - embedding_dimension: integer
  - created_at: timestamp
  - chunk_count: integer
  - source_hash: SHA-256 of source corpus
  - jurisdictions: list of jurisdictions covered
```

**RULE: Atomic Index Rebuild**

```
NEVER modify a live FAISS index.
1. Build new index in temp directory
2. Verify: chunk count matches expected
3. Verify: 10 golden queries return expected results
4. Atomic swap: rename new index to production path
5. Keep previous index as rollback
```

**RULE: Legal Corpus Freshness**

```
Every legal text chunk MUST include:
  - jurisdiction: source jurisdiction
  - article_id: specific article/section (e.g., "GDPR Art. 22")
  - effective_date: when the law took effect
  - indexed_at: when this text was indexed
  - source_url: canonical URL for the legal text

Flag any retrieval result where indexed_at > 90 days.
Re-index triggered when source legislation is amended.
```

**RULE: Retrieval Confidence Integration**

```
RAG retrieval scores MUST factor into finding confidence:
  - similarity >= 0.90: strong legal support → confidence boost +0.05
  - similarity 0.70-0.89: moderate support → no change
  - similarity < 0.70: weak support → confidence penalty -0.05
  - no retrieval result: no legal corpus match → flag for review
```

---

## 7. DATA STORAGE INTEGRITY

### 7.1 Current Database Schema

**File:** `src/backend/app/models.py` (57 lines)

| Table | Purpose | Key Fields | Integrity |
|-------|---------|------------|-----------|
| `analyses` | Full analysis results | id, result_json, confidence, risk_score, grade | ADEQUATE — stores full JSON payload |
| `review_items` | Human review queue | analysis_id FK, status, notes | ADEQUATE — FK constraint |
| `watchlist_items` | Policy monitoring | source_url, last_document_hash, last_risk_score | ADEQUATE — hash-based change detection |

### 7.2 Storage Integrity Gaps

| Gap | Severity | Description |
|-----|----------|-------------|
| No document hash in analyses | MEDIUM | Cannot detect if same document analyzed twice. `diffing.py:content_hash()` exists but not used in analyses table. |
| No model version in analyses | **HIGH** | Cannot audit which LLM model produced which results. Critical for migration tracking. |
| No finding provenance | HIGH | Cannot distinguish rule-only vs LLM findings in stored results. |
| SQLite WAL mode not configured | MEDIUM | Default journal mode. WAL would improve concurrent read/write for watchlist background thread. |
| No analysis versioning | MEDIUM | Re-analyzing same URL overwrites nothing (new UUID each time) but no link between versions. |
| No backup automation | MEDIUM | SQLite file at `data/terms_analysis.db` with no automated backup. |
| result_json is TEXT column | LOW | Full JSON stored as string. Query performance for aggregate analytics is poor. Could use JSON column type in SQLite 3.38+. |

### 7.3 Watchlist Integrity

**File:** `src/backend/app/main.py:68-118` — Background watchlist refresh loop

| Risk | Severity | Description |
|------|----------|-------------|
| `asyncio.run()` inside thread | MEDIUM | `_refresh_all_watchlist_items()` calls `asyncio.run(fetch_url_text())` inside a daemon thread. Creates new event loop per call. Works but not ideal. |
| Silent failure swallowing | **HIGH** | `_watchlist_loop()` catches ALL exceptions and continues. Network errors, DB errors, schema errors all silently swallowed. |
| No rate limiting for URL fetch | MEDIUM | Watchlist refresh fetches URLs without delay. If many URLs, could appear as scraping. |
| Hardcoded jurisdictions | MEDIUM | `detect_findings(text, ["US-CA", "GDPR"])` — watchlist refresh always uses US-CA + GDPR regardless of original analysis jurisdictions. |
| No change notification | LOW | Policy changes detected but no notification mechanism (email, webhook). |

---

## 8. SECURITY SURFACE AREA

### 8.1 Input Validation

| Vector | Current Protection | Gap |
|--------|-------------------|-----|
| Text input | Pydantic `min_length=1` | No max_length validation on API. `max_input_chars` is truncation, not rejection. |
| URL input | Pydantic `min_length=4` | No URL scheme validation. Could accept `file://`, `ftp://`, etc. SSRF risk. |
| File upload | Content type from client | No file size limit on API. Server memory could be exhausted. |
| Jurisdictions | Literal type ("US-CA", "GDPR") | GOOD — Pydantic enforces valid values |
| Analysis ID | String, used in DB query | SQLAlchemy parameterized queries prevent SQL injection |
| Review update | Literal status + optional notes | GOOD — status is enum-constrained |

### 8.2 CORS Configuration

```python
# main.py:40-46
allow_origins=settings.allowed_origins  # Default: localhost:8000
allow_credentials=True
allow_methods=["*"]
allow_headers=["*"]
```

**Assessment:** Configured with explicit origins (good) but uses wildcard methods/headers (medium risk). Adequate for local deployment. Needs tightening for production.

### 8.3 Secret Management

| Secret | Storage | Risk |
|--------|---------|------|
| LM_STUDIO_BASE_URL | Env var | LOW — localhost URL |
| DATABASE_URL | Env var / default | LOW — local SQLite path |
| No API keys | N/A | GOOD — no external API calls |
| No user auth | N/A | **HIGH** — no authentication on any endpoint |

### 8.4 Missing Security Controls

| Control | Status | Priority |
|---------|--------|----------|
| Request size limits | MISSING | P1 — memory exhaustion via large uploads |
| URL scheme validation | MISSING | P1 — SSRF via `file://` or internal URLs |
| Rate limiting | MISSING | P2 — endpoint abuse |
| Authentication | MISSING | P2 — all endpoints are public |
| HTTPS | MISSING | P2 — local-only for now |
| Input sanitization (HTML) | PARTIAL — BeautifulSoup strips scripts | P3 |
| CSP headers | MISSING | P3 — frontend serves static files |

---

## 9. IDENTIFIED CODEBASE GAPS (Priority Ordered)

### P0 — Must Fix Before Production

| # | Gap | File:Line | Fix |
|---|-----|-----------|-----|
| 1 | No LLM model version tracking per analysis | `analyzer.py:131` | Add `llm_model` and `llm_responded` fields to AnalysisPayload and Analysis model |
| 2 | No finding provenance (rule vs LLM) | `analyzer.py:150-162` | Add `source: Literal["rule", "llm", "merged"]` field to Finding schema |
| 3 | Silent exception swallowing in watchlist loop | `main.py:72-73` | Log exceptions. Track consecutive failures. Disable item after N failures. |
| 4 | URL scheme validation missing (SSRF) | `schemas.py:38` | Add URL validator: allow only `http://` and `https://` schemes |
| 5 | No file upload size limit | `main.py:254-266` | Add `max_upload_bytes` setting, reject oversized files |

### P1 — Required for Quality Targets

| # | Gap | File | Fix |
|---|-----|------|-----|
| 6 | Silent truncation (no user warning) | `analyzer.py:24-27` | Return truncation flag in AnalysisResult. Surface in API response. |
| 7 | Test coverage at ~5-8% | `src/backend/tests/` | Target: 85% line coverage. See LIB-TEST for priority order. |
| 8 | No golden test set for confidence calibration | N/A (new) | Create labeled dataset. Calibrate confidence formula empirically. |
| 9 | No F1/Kappa evaluation pipeline connected to CI | `src/backend/evaluation/` | Wire evaluation into test suite or pre-commit. |
| 10 | Penalty scales with finding count (penalizes thoroughness) | `validation.py:59-61` | Normalize penalty per finding. |

### P2 — Required for RAG Pipeline

| # | Gap | Fix |
|---|-----|-----|
| 11 | No embedding infrastructure | Build `embeddings.py` service with FAISS + modernbert-legal |
| 12 | No legal corpus management | Build `legal_kb.py` service for chunking/indexing legal texts |
| 13 | No retrieval-augmented prompts | Extend `prompts.py` with retrieved legal context |
| 14 | No embedding version tracking | Metadata sidecar for every FAISS index |
| 15 | No legal basis verification | Cross-reference LLM-cited legal basis against indexed corpus |

### P3 — Recommended

| # | Gap | Fix |
|---|-----|-----|
| 16 | Broad regex patterns (access, retain, sensitive) | Add negative patterns / context windows to reduce false positives |
| 17 | No language detection | Detect non-English text, warn user |
| 18 | No document deduplication | Use content_hash to detect re-analysis |
| 19 | SQLite WAL mode | Configure for better concurrent access |
| 20 | No analysis versioning / diff between runs | Link successive analyses of same URL |

---

## 10. QUALITY TARGETS & MEASUREMENT

### 10.1 Current Metrics

| Metric | Current | Target | Gap |
|--------|---------|--------|-----|
| Test coverage (line) | ~5-8% | 85% | **CRITICAL** |
| Test coverage (branch) | ~3% | 75% | **CRITICAL** |
| Macro F1 | Unknown (no evaluation run) | >= 0.70 | **UNKNOWN** |
| Cohen's Kappa | Unknown | >= 0.65 | **UNKNOWN** |
| False positive rate | Unknown | < 15% | **UNKNOWN** |
| LLM response rate | Unknown (no metrics) | >= 90% | **UNKNOWN** |
| Mean analysis latency | Unknown | < 30s | **UNKNOWN** |

### 10.2 Golden Test Set Requirements

```yaml
golden_test_set:
  description: "Curated policy-finding pairs verified by legal review"
  minimum_size: 50  # At minimum 50 policy documents with labeled findings
  categories:
    true_positives:
      - document: "policy_with_sale_share.txt"
        expected_findings: ["Sale/Share"]
        expected_severity: "High"
        expected_jurisdiction: "US-CA"

    true_negatives:
      - document: "clean_policy.txt"
        expected_findings: []  # No risks found

    edge_cases:
      - document: "ambiguous_retention.txt"
        expected_findings: ["Retention"]
        notes: "Contains 'retain the right' (not data retention)"

    jurisdiction_specific:
      - document: "gdpr_only_policy.txt"
        jurisdictions: ["GDPR"]
        expected_findings: ["ADM", "User Rights"]
        must_not_include: ["Sale/Share"]  # CCPA-only category

  refresh_schedule: "quarterly"
  expert_review: "on creation and after rule changes"
```

### 10.3 Pre-Deployment Quality Gate

```
BEFORE any deployment that touches rules, LLM integration, or validation:
  1. Run golden test set
  2. Calculate per-category F1
  3. Calculate macro F1 and Cohen's Kappa
  4. Compare against previous baseline

  PASS criteria:
    - Macro F1 >= 0.70
    - No single category F1 < 0.50
    - Kappa >= 0.65
    - No regression > 5% from previous baseline

  FAIL action:
    - Block deployment
    - Generate regression report
    - Route to human review
```

---

## 11. PEAS FRAMEWORK SELF-EVALUATION

### Agent Task: Terms & Policies Analysis

| Component | Definition | This System |
|-----------|------------|-------------|
| **Performance** | How success is measured | Macro F1 >= 0.70, Kappa >= 0.65, confidence-gated human review, risk score accuracy |
| **Environment** | Where the system operates | User-submitted documents (text, URL, file), local LLM inference, SQLite storage, legal corpus (planned) |
| **Actuators** | Actions the system can take | Regex pattern matching, LLM prompt/response, finding merge, validation, risk scoring, review flagging |
| **Sensors** | Information the system perceives | Document text, file metadata, LLM JSON responses, regex match positions, citation line spans |

### Environment Characteristics

| Property | Value | Impact |
|----------|-------|--------|
| Fully Observable | PARTIAL | Cannot see user intent; cannot verify if document is complete or truncated before ingestion |
| Deterministic | PARTIAL | Rules are deterministic; LLM responses are stochastic (temperature 0.1 reduces but doesn't eliminate) |
| Episodic | YES | Each analysis is independent; watchlist provides longitudinal tracking |
| Static | MOSTLY | Document doesn't change during analysis; but legal landscape evolves |
| Discrete | YES | Finite categories, bounded severity levels, clamped confidence |
| Single Agent | YES (today) | Rule engine + LLM treated as single pipeline; RAG adds retrieval agent |

---

## RESEARCH SOURCES

- Project codebase: `src/backend/app/` (11 Python files, ~1,500 lines)
- Existing evaluation framework: `src/backend/evaluation/`
- Existing test suite: `src/backend/tests/` (3 files, 5 tests)
- Project documentation: `docs/DESIGN.md`, `docs/TODO.md`
- `.claude/library/LIB-*.md` reference files
- Reference architecture: SRS AI Systems data integrity analysis (sunny-humming-hearth-agent-ad1c6f0.md)

---

*Report generated by AI Terms & Policies Reviewer architecture analysis*
*Methodology: End-to-end pipeline audit with PEAS self-evaluation*
*Next review: After RAG pipeline implementation*
