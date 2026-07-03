# Technical Specification — Terms & Policies Reviewer

> Version 1.0 — 2026-07-03
> Anchors: BRD (`docs/BRD_Terms_Policies_Reviewer.md`), PRD (`docs/PRD_Terms_Policies_Reviewer.md`), `PRODUCT.md`, `.claude/CLAUDE.md`, `.claude/library/LIB-*.md`.
> Governance: `.claude/library/LIB-PRINCIPLES.md`.

---

## 0. Purpose of This Document

### 0.1 Why this spec exists now

The Terms & Policies Reviewer has been running through multiple product-shaping cycles — a BRD (Feb 2026), a PRD (Jun 2026, revised for AI-law coverage), a plain-language redesign shipped as PR #34 (Jul 2026) — with no consolidated engineering specification that traces every shipped behavior back to a documented requirement. This document is the first canonical technical spec, retrofit against the running implementation. It exists to (a) produce a single reference that engineers and reviewers can trust, (b) surface every place where the shipped code diverges from BRD/PRD (or where the anchor docs are silent), and (c) formalize the traceability model going forward per LIB-PRINCIPLES §Principle 2.

### 0.2 Scope

The whole system. Backend (FastAPI, SQLite, LocalAI, legal-KB), Streamlit UI (v2 primary; v1 rollback via `STREAMLIT_UI=v1`), rule engine, LLM integration, RAG, verdict semantics, persistence, exports, watchlist, security, deployment, testing. Version 1.0 covers only what ships in the current `main` branch as of 2026-07-03 (post-PR #34 — 702 tests, 98.06% coverage [LIB-TEST §Current baseline]). The pre-redesign vanilla-JS SPA (`index.html` / `app.js` / `style.css`) was retired in Phase 4 of the issue #19 remediation; historical references remain in §12 for changelog continuity. Future work is called out only where it is already committed to via BRD/PRD or by an existing session handoff.

### 0.3 Non-goals

- Not a business case. Financial projections, TAM/SAM/SOM, and marketing plans belong in BRD [BRD §Financial Projections, §Go-to-Market Strategy] and are not restated here.
- Not a design document. Wireframes, color tokens, and copy sourcing decisions live in `docs/wireframes/` and LIB-VOICE / LIB-CONTEXT.
- Not a delivery plan. Roadmap, phasing, and OKRs are BRD/PRD content [BRD §Implementation Roadmap; PRD §Launch Readiness Checklist].
- Not a UI style guide. WCAG 2.2 AA is required [PRD §Accessibility Requirements], but per-token color and spacing choices are not enumerated here.

### 0.4 How to read it

Every substantive claim in this document carries an inline anchor of the form `[BRD §Section]`, `[PRD §Section]`, `[LIB-ARCH §Section]`, or `[src/backend/app/…]`. Sections that describe intentional divergence between the anchor docs and the shipped code are called out inline; the consolidated list is in §20. Claims that would be inference — where the code exists but no BRD/PRD anchor names the behavior — are marked `**OPEN QUESTION:**` inline and rolled up in §20.

Governance applied per LIB-PRINCIPLES: **do not infer, always cite BRD/PRD, surface drift** [LIB-PRINCIPLES §§1-3]. This document is retrofit, so drift is expected in high volume — the drift itself is a load-bearing output, not a defect.

---

## 1. System Overview

### 1.1 Product one-liner

> "A privacy-first local tool that reads Terms of Service and Privacy Policies and translates them into plain language risk assessments. It identifies high-risk clauses, maps compliance requirements to jurisdictions, and gives users the confidence to make informed consent decisions."
> — [PRODUCT.md §Product Purpose]

Brand personality — Clear, Calm, Empowering — "trusted guide, not threat scanner. Think 'I've got you,' not 'WARNING: CRITICAL RISK'" [PRODUCT.md §Brand Personality]. This anchor is load-bearing for every UI voice and copy decision (§11, §12, LIB-VOICE).

### 1.2 Business context

Strategic goals from [BRD §Executive Summary]:

1. Validate product-market fit — prototype to production-ready MVP in 6 months.
2. Privacy leadership — privacy-first alternative to cloud-based legal tech.
3. User acquisition — 1,000 active users within 12 months.
4. Open source community — contributor base, transparency-based trust.
5. Sustainable monetization — freemium SaaS vs enterprise licensing vs open-core (option TBD) [BRD §Business Model].

Market gap: existing solutions are either manual community ratings (ToS;DR — 2,000 services, no automation), enterprise-priced cloud tools (LawGeex, Kira — $10K–100K+), or compliance-focused enterprise platforms (OneTrust) [BRD §Competitive Landscape Gap]. No privacy-respecting, affordable, automated tool for consumers and small organizations exists.

### 1.3 Users and personas

Five personas are documented across BRD and PRD. The BRD segments users by acquisition (Parents 35%, Small Businesses 40%, Privacy Advocates 25%) [BRD §Customer Segments]; the PRD names five archetypes with journeys and edge cases [PRD §User Personas]:

1. **Privacy-Conscious Patricia** — SWE, high tech literacy, evaluating services before signup [PRD §Persona 1].
2. **Startup Founder Sam** — 15-person startup CEO, no legal counsel, vendor due diligence [PRD §Persona 2].
3. **Researcher Rachel** — Law/Tech PhD candidate, systematic corpus analysis, reproducible methodology [PRD §Persona 3].
4. **AI Compliance Officer Alex** — JD + 10y compliance, EU AI Act vendor risk assessment, Colorado AI Act obligations [PRD §Persona 4].
5. **Parent Morgan** — Teacher, low-medium tech literacy, "is this app safe for my 10-year-old" [PRD §Persona 5].

PRODUCT.md broadens beyond BRD/PRD to include "vibe coders auditing vendor APIs, compliance officers at nonprofits and government agencies, privacy advocates, and general consumers" [PRODUCT.md §Users]. The common thread is a "nervous non-expert reader whose trust is fragile" [LIB-PRINCIPLES §1]; the design principle "Plain language first — if the UI makes risk feel complex, it's failing" [PRODUCT.md §Design Principles] applies universally.

### 1.4 Hard requirements

Restated verbatim from [.claude/CLAUDE.md §Hard Requirements] and [LIB-PRINCIPLES §Principle 5]:

- All dependencies open source (Apache 2.0, MIT, BSD preferred).
- No tools/services from companies facing investor lawsuits — this excludes Meta-origin packages (no FAISS, no torch/PyTorch).
- All dependencies IRP Grade A or higher.
- All data local. No external API calls.
- LLM failures always fall back to rule-only findings with reduced confidence.
- No OpenAI. LLM inference is LocalAI + Apertus-8B / EuroLLM-22B, local only.
- Confidence < 0.80 triggers human-in-the-loop review [.claude/CLAUDE.md §Hard Requirements; `src/backend/app/config.py:81`].
- Rule confidence (active path) clamped to [0.90, 0.95] [LIB-RULES §Rule-Based Confidence Formula].
- Risk scores map to grades: A (<3.5), A- (3.5–4.5), B (4.5–5.5), B- (5.5–6.5), C+ (6.5–7.5), C (7.5–8.5), D+ (>=8.5) [`src/backend/app/services/analyzer.py:426`].

Two hard scope limits are non-negotiable per [LIB-PRINCIPLES §Principle 4] and appear verbatim in the results scope box (§11):

- **Hardware permissions** (camera, microphone, contacts, location) — not analyzed; the tool reads policy text, not manifests.
- **Real-world practice divergence** — not analyzed; the tool assesses what the policy says, not what the company does.

Any request that would appear to lift these limits is drift per [LIB-PRINCIPLES §Principle 3] and must be surfaced.

---

## 2. Architecture

### 2.1 Component map

Verified against `src/backend/app/` and `src/webapp/` inventory. Cross-referenced [LIB-ARCH §System Components].

| Component | Location | Role |
|---|---|---|
| Web UI | `src/webapp/app_streamlit_v2.py` (972 lines) | Streamlit v2, plain-language redesign, port 8501 — sole UI post-Phase-4 SPA retirement [LIB-ARCH §System Components] |
| Web UI — legacy | `src/webapp/app_streamlit_legacy.py` | Pre-redesign Streamlit, retained as rollback path via `STREAMLIT_UI=v1` flag [.claude/CLAUDE.md §Session outcomes] |
| API server | `src/backend/app/main.py` | FastAPI + Uvicorn, async, 24 business routes + `/health` + `/infer` = 26 total [LIB-API §Endpoint Map, verified against `src/backend/app/main.py`] |
| Rule engine | `src/backend/app/services/rules.py` (1,092 lines) | 64 `RulePattern` entries, ~50 category strings, 30 jurisdiction codes [LIB-RULES §Risk Categories; verified `grep -c "RulePattern("` = 64] |
| LLM client | `src/backend/app/services/localai.py` | httpx async client for LocalAI, language-routed Apertus/EuroLLM [`src/backend/app/services/localai.py:77`] |
| Document embeddings | `src/backend/app/services/embedding.py` | BM25 + Apertus + EuroLLM RRF ensemble for chunk selection. Not currently wired into `analyzer.py` [LIB-ARCH §System Components, marked "dead code"] |
| Legal knowledge base | `src/backend/app/services/legal_kb.py` | Numpy exhaustive + BM25/RRF retrieval over `data/legal_corpus/`, wired into `analyzer.py::analyze_text` [`src/backend/app/services/analyzer.py:477`] |
| Analyzer orchestration | `src/backend/app/services/analyzer.py` (813 lines) | Rules → legal-KB → LLM → validation → merge → IRP → domain group → verdict [§7] |
| Validator | `src/backend/app/services/validation.py` | Hallucination guard, citation checker, coverage ratio [§7.7] |
| Ingestion | `src/backend/app/services/ingest.py` | HTML/PDF/DOCX/RTF/TXT extraction, OCR fallback, SSRF-guarded URL fetch [§15.4] |
| Diffing | `src/backend/app/services/diffing.py` | SHA-256 content hash + unified/token diff for watchlist and snapshots [§13.3] |
| Prompts | `src/backend/app/services/prompts.py` | System prompt + user prompt builder including legal-KB context injection [§7.3] |
| Context | `src/backend/app/services/context.py` | Chip taxonomy, category weights, verdict copy [§5.4] |
| Inference (intake) | `src/backend/app/services/inference.py` | URL/text-based jurisdiction/doc-type/industry inference for the intake [§7.9] |
| Database | `src/backend/app/models.py` + `database.py` | SQLite + SQLAlchemy, 5 tables [§5.2] |
| Config | `src/backend/app/config.py` | Env-var driven frozen dataclass [§16] |

### 2.2 Data flow

Verbatim from [LIB-ARCH §Data Flow]:

```
User Input
  → Ingestion (normalize text — HTML/PDF/DOCX/RTF/TXT/OCR)
  → Rule Engine (regex detection, 64 patterns / 30 jurisdictions)
  → Legal KB retrieval (numpy exhaustive cosine + BM25/RRF over data/legal_corpus/)
  → LLM (analysis with line-numbered context + legal-KB citations, via LocalAI)
      LLM failure → rule-only findings, confidence *= 0.8
  → Merge (match rule + LLM findings by category+excerpt; hybrid 0.6×rule + 0.4×LLM confidence)
  → Validation (citation check, hallucination guard, confidence scoring)
  → IRP scoring (0.5×(impact/5) + 0.4×(likelihood/5) − 0.3×(safeguard/5))
  → Doctype + Industry emphasis (severity bumps for relevant categories)
  → Context weighting (tier-first sort: weight → IRP → severity_rank)
  → Domain grouping (Data / Data use / Terms of use / Privacy rights; max 2/domain, 8 total)
  → Verdict copy (headline + label per context chip + action_readiness)
  → SQLite persistence (result_json blob)
  → UI render (Streamlit v2, sole UI)
```

`analyze_text()` in `src/backend/app/services/analyzer.py:442` is the entry point that orchestrates the entire flow.

### 2.3 Deployment topology

`run.sh` orchestrates two long-running processes on two ports:

| Service | Command | Port | Purpose |
|---|---|---|---|
| Backend | `uvicorn app.main:app --host 0.0.0.0 --port 9000 --reload --app-dir src/backend` | 9000 | FastAPI |
| Streamlit UI | `streamlit run app_streamlit_v2.py --server.port 8501 --server.headless true` | 8501 | Sole UI (or `app_streamlit_legacy.py` if `STREAMLIT_UI=v1`) |

`run.sh` bootstraps a per-project venv at `src/backend/.venv`, installs `src/backend/requirements.txt` and (if present) `src/webapp/requirements.txt`, exports LocalAI env vars, and registers a `trap cleanup EXIT` handler that SIGTERMs both PIDs. `wait -n` keeps the script alive until any child exits so the trap runs under both interactive Ctrl+C and non-interactive SIGTERM.

### 2.4 External systems

- **LocalAI** — inference server (Apache 2.0, https://localai.io), default `http://localhost:8080/v1` via `LOCALAI_BASE_URL` [`src/backend/app/config.py:27`; LIB-LEGAL §Approved LLM Tools].
- **Apertus-8B-Instruct** — Swiss AI Initiative (EPFL/ETH/CSCS), Apache 2.0, 1,000+ languages, world/multilingual model [`config.py:31`; BRD §Technology Stack].
- **EuroLLM-22B-Instruct** — EU Horizon/EuroHPC, Apache 2.0, 35 EU languages, trained on Europarl/ECHR/EU regulatory corpora [`config.py:35`; BRD §Technology Stack].

Language routing between the two models uses `langdetect` (ISO 639-1) on the first 2,000 characters; if the detected code is in `EU_LANGUAGE_CODES` (default: 24 EU official languages) the request routes to EuroLLM, otherwise Apertus [`src/backend/app/services/localai.py:39`; LIB-STACK §Configuration].

`langdetect` is unmaintained since 2021 [LIB-STACK §Python Dependencies note]. If it fails to import or raise, `_detect_language` returns `None` and `_select_model` falls back to `MODEL_WORLD` (Apertus) — the tool degrades to a single model rather than crashing.

### 2.5 Constraints

Beyond the hard requirements (§1.4):

- **No FAISS** — Meta-origin dependency, rejected [LIB-STACK §Rejected Dependencies]. Legal-KB uses `numpy` exhaustive dot-product cosine similarity over an L2-normalized matrix persisted as a plain `.npy` file [LIB-LEGAL §Vector Store; `src/backend/app/services/legal_kb.py`].
- **No torch/PyTorch** — Meta-origin [LIB-STACK §Rejected Dependencies].
- **No Chinese-affiliated models** — Qwen, BAAI/bge-m3 rejected [LIB-LEGAL §REJECTED Tools].
- **No approximate nearest neighbor (HNSW)** — legal-risk analysis cannot tolerate false negatives from ANN [LIB-LEGAL §Vector Store; LIB-LEGAL §REJECTED Tools].
- **No cloud LLM APIs** — reader trust is a load-bearing brand promise [PRODUCT.md §Design Principles §4 "Trust through transparency … runs locally, respects privacy"].
- **LLM failure must not block** — every failure mode (LLM unreachable, invalid JSON, timeout, empty findings, missing legal_basis) has a documented rule-only fallback with a confidence multiplier [LIB-ARCH §Failure Modes; §7.5].

---

## 3. Functional Requirements

Each subsection covers one PRD feature block. Acceptance criteria are stated verbatim from PRD; shipped-status is verified against code; open questions are marked inline where the PRD is silent or where shipped diverges without a documented decision.

### 3.1 F1 — Document Ingestion [PRD §F1]

**User story:** "As a user, I want to input policy documents in multiple formats so I can analyze any type of document I encounter." [PRD §F1]

#### 3.1.1 F1.1 URL input

Acceptance criteria [PRD §F1.1]:
- User pastes URL; system validates URL format before submission.
- System fetches HTML, extracts text, handles JS-rendered content, displays loading state (3–10s), shows error on invalid/unreachable, displays success with preview.

Shipped [`src/backend/app/main.py:298` `POST /analyze/url`; `src/backend/app/services/ingest.py:197` `fetch_url_text`]:
- URL scheme validated at schema layer [`schemas.py:204` `AnalyzeUrlRequest._validate_url_scheme`] — rejects anything not `http` / `https`, requires a hostname.
- SSRF guard [`ingest.py:155` `_validate_url`]: blocks loopback (127.0.0.0/8, ::1), RFC 1918 private (10/8, 172.16/12, 192.168/16), link-local (169.254/16, fe80::/10), unique-local (fc00::/7). Applied both on initial request and on redirect [`ingest.py:206`].
- Redirect handling: `httpx.Response` follow_redirects up to a capped depth; `_BLOCKED_STATUSES = {401, 403, 407, 429, 503}` short-circuits fetch [`ingest.py:208`].
- Timeout: `LM_REQUEST_TIMEOUT_S` env var default 60s [`config.py:82`]. **OPEN QUESTION:** PRD specifies 30s timeout for URL fetch [PRD §F1.1 Technical Notes]; shipped default is 60s. Which is authoritative?

**OPEN QUESTION:** PRD requires "handles JavaScript-rendered content"; shipped ingestion is pure httpx + BeautifulSoup with no headless browser. JS-rendered SPAs will return their skeleton HTML, not their post-hydration text. Reconcile as either (a) update PRD to remove JS rendering, or (b) accept as future work.

#### 3.1.2 F1.2 File upload

Acceptance criteria [PRD §F1.2]:
- Drag-and-drop or click to browse; accepts PDF/DOCX/RTF/HTML/TXT; validates size (max 10MB); validates type by content, not extension; OCR fallback for scanned PDFs.

Shipped [`src/backend/app/main.py:340` `POST /analyze/file`; `src/backend/app/services/ingest.py:127` `extract_text_from_bytes`]:
- `max_upload_bytes` default 10 * 1024 * 1024 [`config.py:85`] — matches PRD.
- Content-type allowlist `_ALLOWED_CONTENT_TYPES` [`ingest.py:16`]: `text/plain`, `text/html`, `application/pdf`, `application/vnd.openxmlformats-officedocument.wordprocessingml.document` (DOCX), `application/msword`, `application/rtf`, `text/rtf`, `text/markdown`, `application/octet-stream`.
- Format-specific extractors: `pypdf.PdfReader` for PDF; `docx.Document` for DOCX; `striprtf.rtf_to_text` for RTF; `BeautifulSoup` for HTML; UTF-8/UTF-16/latin-1 decode ladder for text [`ingest.py:55`].
- OCR fallback: `pytesseract` optional import; `MAX_PDF_PAGES` default 100 [`config.py:97`].
- Content-based validation: **OPEN QUESTION:** PRD calls for `python-magic` content-type sniffing; shipped code trusts the `content-type` header on upload plus per-format extractor tolerance. Reconcile.

Streaming read [`main.py:359`]: chunks of 65,536 bytes, aborts with HTTP 413 if the running total exceeds `max_upload_bytes`.

#### 3.1.3 F1.3 Text paste

Acceptance criteria [PRD §F1.3]:
- Textarea with auto-expand (max 400px); character counter; up to 50,000 chars; preserves paragraph breaks; warning if text short (<1000 chars).

Shipped:
- `AnalyzeRequest.text` requires `min_length=1` [`schemas.py:168`]. Backend hard cap is `MAX_INPUT_CHARS=20000` [`config.py:83`; `analyzer.py:143` `_truncate_text`]. **OPEN QUESTION:** PRD says 50,000 chars; shipped default is 20,000. Reconcile.
- Character counter and short-text warning are UI concerns; PRD §Implementation Status Note (2026-07-03) confirms both are shipped in Streamlit [`app_streamlit_v2.py`].

### 3.2 F2 — Analysis Configuration [PRD §F2]

#### 3.2.1 F2.1 Jurisdiction selection

Acceptance criteria [PRD §F2.1]:
- Multi-select of 30 jurisdictions; Select-All/Clear-All; **default: US-CA + GDPR**.

Shipped:
- 30 codes as `Jurisdiction` Literal [`schemas.py:8`]. Enumerated: US-CA, US-FED, US-NY, US-TX, US-VA, US-CO, US-CT, US-IL, US-NJ, US-MN, US-OR, GDPR, UK-GDPR, LGPD, PIPEDA, CA-QC, POPIA, PDPA-KE, DPDP, APPI, PIPA, APP, PDPA-TH, NDPR, ICCPR-17, COE-108, EU-AI-ACT, COE-AI-225, OECD-AI, UNESCO-AI.
- Handler allowlist `_VALID_JURISDICTIONS = frozenset(get_args(Jurisdiction))` [`main.py:67`], per LIB-TEST §3-rule policy Rule 1.
- **Drift from PRD [surfaced per LIB-PRINCIPLES §Principle 3]:** Global-tool contract per PR #34 — empty `jurisdictions=[]` is treated as "no filter" across `rules.py::detect_findings`, LLM post-filter, and Streamlit resolution. **No US-CA + GDPR default fallback anywhere in the code** [LIB-RULES §Global-tool contract; `analyzer.py:528`; `.claude/CLAUDE.md §Session outcomes`]. The PRD default is stale — it was intentionally removed to avoid mis-scoping findings for the ~90% of users not in California [`src/webapp/app_streamlit_v2.py:321` `_location_to_jurisdictions` docstring]. One exception: `/analyze/file` multipart endpoint substitutes `["US-CA", "GDPR"]` when the form field parses to an empty list [`main.py:395`] — **OPEN QUESTION:** is this legacy behavior intended to persist, or should it be removed for global-tool contract parity?

#### 3.2.2 F2.2 Document type selection

Acceptance criteria [PRD §F2.2]: dropdown, options Privacy Policy / Terms of Service / Cookie Policy / Data Processing Agreement / Combined; default Privacy Policy.

Shipped: `DocType` Literal [`schemas.py:111`] matches exactly. Doc-type influences severity bumps via `_DOCTYPE_BOOSTS` [`analyzer.py:201`]; a boost >= 0.2 bumps severity one tier [`analyzer.py:355` `_bump_severity`]. Boosts applied per doc-type category (e.g., Privacy Policy boosts "Data Sale / Sharing" +0.3, "User Rights" +0.2).

#### 3.2.3 F2.3 Industry profile

Acceptance criteria [PRD §F2.3]: dropdown; options Retail / Finance / Healthcare / Gaming / Social Media / AI / Tech Platform / Education / General; default General.

Shipped: `IndustryProfile` Literal [`schemas.py:119`] matches. Industry influences severity via `_INDUSTRY_BOOSTS` [`analyzer.py:229`] — e.g., Healthcare +0.4 for "Health Data", AI / Tech Platform +0.4 for "Automated Decision-Making".

### 3.3 F3 — Risk Analysis Engine [PRD §F3]

#### 3.3.1 F3.1 Risk scoring

Acceptance criteria [PRD §F3.1]:
- The PRD documents both a **shipped** severity-weighted score (marked `[x]`) and a **planned** IRP formula (marked `[ ]`).

**Actual current status (post-PR #34, 2026-07-03) — supersedes the PRD's "planned enhancement" framing:**
- IRP is fully shipped [.claude/CLAUDE.md §Session outcomes; LIB-RULES §IRP Scoring].
- `Finding` schema carries `impact` (int 1-5, default 2), `likelihood` (int 1-5, default 3), `safeguard_score` (int 0-5, default 0), `irp_score` (float 0-1, optional) [`schemas.py:161`].
- Formula [`analyzer.py:136` `_compute_irp`]: `irp = clamp(0.5*(impact/5) + 0.4*(likelihood/5) - 0.3*(safeguard_score/5), 0, 1)`.
- Rule findings seed IRP from `_CATEGORY_IRP_DEFAULTS` (38 categories mapped) [`rules.py:900`; `rules.py:943` `_seed_irp`].
- LLM findings request `impact`, `likelihood`, `safeguard_score` per finding in the prompt [`prompts.py:54`], and `irp_score` is computed after parsing [`analyzer.py:504`].
- Hybrid: rule `impact`/`likelihood` baseline; `safeguard_score = max(rule, llm)`; IRP recomputed [`analyzer.py:646`].

**Risk score** [`analyzer.py:414` `calculate_risk_score`]: mean of per-finding `irp_score` (or severity-weight fallback for legacy findings) times 10, rounded to 2 decimals, on a 0–10 scale [LIB-RULES §Risk Score & Grade].

**Grade thresholds** [`analyzer.py:426` `_grade`]:

| Score range | Grade |
|---|---|
| `>= 8.5` | D+ |
| `[7.5, 8.5)` | C |
| `[6.5, 7.5)` | C+ |
| `[5.5, 6.5)` | B- |
| `[4.5, 5.5)` | B |
| `[3.5, 4.5)` | A- |
| `< 3.5` | A |

**Drift from PRD [surfaced]:** PRD §F3.1 describes an IRP grade table with A/B/C/D/F on a 0–1 scale (A <0.30, F >=0.85). The shipped grade table uses A / A- / B / B- / C+ / C / D+ on a 0–10 scale. The PRD table is stale.

#### 3.3.2 F3.2 Risk categories

Acceptance criteria [PRD §F3.2]: 9 core risk categories detected; each finding assigned one primary category; category filters; per-category counts.

Shipped: `schemas.CATEGORIES` [`schemas.py:50`] is a `frozenset[str]` of ~50 canonical category strings (§5.3 lists them all). The 9 conceptual buckets from BRD/PRD still exist (Data Sharing, Automated Decisions, Dark Patterns, Retention, User Rights, Minors, Sensitive Data, Unilateral Changes, Liability) but rule coverage has expanded to include AI Act sub-categories, industry-specific compliance blocks, and per-jurisdiction international blocks [BRD §Risk Categories note; LIB-RULES §Risk Categories].

Import-time drift guard [`context.py:121`; `analyzer.py:102`]: `CATEGORY_WEIGHTS` and `_DOMAIN_MAP` keys are validated against `schemas.CATEGORIES` — mismatch raises `RuntimeError` before the server starts (§8, §10).

#### 3.3.3 F3.3 Evidence binding

Acceptance criteria [PRD §F3.3]: every finding includes excerpt (1–3 sentences, max 500 chars); line_start/line_end; "View in Context"; matched text highlighted.

Shipped [`schemas.py:141` `Evidence`]:

| Field | Type | Constraint |
|---|---|---|
| `line_start` | int | `>= 1` |
| `line_end` | int | `>= 1` |
| `legal_basis` | List[str] | default `[]` |
| `start_offset` | int? | `>= 0`, char offset |
| `end_offset` | int? | `>= 0`, char offset |
| `context_before` | str? | 2-3 sentences before |
| `context_after` | str? | 2-3 sentences after |

Rule-based excerpts use a ±140-char window around the match [`rules.py:966` `_excerpt`]. `_extract_sentences` [`rules.py:972`] provides the ±2-sentence context. Validation checks that excerpt substring appears in document text [`validation.py:48`].

#### 3.3.4 F3.4 Confidence scoring and review queue

Acceptance criteria [PRD §F3.4]: confidence 0–1 per finding; <0.80 → review flag; approve/reject/edit actions.

Shipped:
- Rule-based `confidence` clamped to [0.90, 0.95] [`rules.py:1002` `_confidence_rules_based`; LIB-RULES §Rule-Based Confidence].
- LLM findings use model-reported confidence [`analyzer.py:497`].
- Hybrid confidence when rule + LLM match on `(category.lower(), excerpt[:120].lower())`: `0.6 * rule_confidence + 0.4 * llm_confidence`, clamped [0, 1] [`analyzer.py:642`; LIB-RULES §Hybrid Merge Strategy].
- Per-finding `needs_review = confidence < 0.6` [`analyzer.py:651`, `503`, `669`].
- Analysis-level `review_required = confidence < settings.review_threshold` (default 0.80) [`analyzer.py:567`; `config.py:81`].
- LLM findings missing `evidence.legal_basis` are dropped; each drop applies `confidence *= max(0.5, 1 - 0.1 * dropped_for_legal)` [`analyzer.py:498, 562`].
- Review actions supported: `approved` / `rejected` via `POST /reviews/{id}` [`main.py:872`; LIB-API §Endpoint Map]. **OPEN QUESTION:** PRD names an `edit` action; shipped `ReviewUpdate` schema is `Literal["approved", "rejected"]` [`schemas.py:274`]. Reconcile.

### 3.4 F4 — Results Display [PRD §F4]

#### 3.4.1 F4.1 Overview summary

Acceptance criteria [PRD §F4.1]: grade prominent; risk score numeric; total findings; severity breakdown; confidence indicator; needs-review badge; jurisdictions; timestamp.

Shipped: all fields carried on `AnalysisPayload` [`schemas.py:220`]. Streamlit v2 renders grade summary via `render_grade_summary` [PRD §Implementation Status Note; `src/webapp/app_streamlit_v2.py`].

**Drift from PRD [surfaced]:** PRD §F4.1 layout mockup shows an overall grade "A–F". Shipped grade set is `A / A- / B / B- / C+ / C / D+` — no D or F. Post-PR #34 the primary UI verdict is a context-aware **actionable label**, not a letter grade — the letter grade is retained on `AnalysisPayload.grade` for machine consumption but is not the primary UI verdict [LIB-VOICE §Verdict labels are actionable].

#### 3.4.2 F4.2 Findings list

Acceptance criteria [PRD §F4.2]: collapsible cards; category icon + severity badge; excerpt (truncated >200 chars); confidence; expandable; filter by category/severity/confidence; sort by severity/confidence/category/line; View-in-Context link.

Shipped: legal details expander in Streamlit v2 [`app_streamlit_v2.py:804`] renders per-finding severity tag, category, IRP badge, excerpt (HTML-escaped, quoted), plain-language explanation, legal basis, line reference, and IRP row (impact/likelihood/safeguard/confidence).

**Drift from PRD:** Post-PR #34 the flat findings list is replaced by a **domain-grouped** view (§10) with a "Legal details / N issues" expander for full listing. Filtering by category/severity/confidence is not surfaced in v2 UI. **OPEN QUESTION:** is the filter deferred, replaced, or removed?

#### 3.4.3 F4.3 Verify view

Acceptance criteria [PRD §F4.3]: split-pane document + findings; click finding to highlight; line numbers; prev/next; severity-colored highlights; annotations.

Shipped: PRD §Implementation Status Note (2026-07-03) confirms Streamlit has a "View in full document" Verify View expander. Annotations are not shipped. **OPEN QUESTION:** are annotations required for v1 or deferred?

#### 3.4.4 F4.4 Plain language explanations

Acceptance criteria [PRD §F4.4]: user-friendly explanation per finding; avoids jargon; describes practical impact; 2–4 sentences, max 300 chars.

Shipped: `Finding.explanation` field carries this [`schemas.py:156`]. Rule findings pull from `RulePattern.explanation`; LLM findings return their own [`prompts.py:52`].

### 3.5 F5 — Export and Reporting [PRD §F5]

#### 3.5.1 F5.1 PDF export

Acceptance criteria [PRD §F5.1]: professional PDF report; grade, score, findings, evidence excerpts, methodology, disclaimer; <2MB; <10s generation.

Shipped [`main.py:574` `GET /exports/analysis/{id}.pdf`]:
- ReportLab-based generation with severity color coding, jurisdiction legend, executive summary page + findings-by-severity pages [`main.py:600-826`].
- Grade badge with color per `_GRADE_COLORS` (A green through D+ dark red).
- XML-escaped user data via `_xml_escape` [`main.py:14`] — defense-in-depth against XSS in generated PDFs.
- Route registered before the `.json` route so the `{analysis_id}` path parameter doesn't shadow it — regression documented inline [`main.py:843`].

**Fixed regression:** route ordering bug reported by PRD §Implementation Status Note is patched.

#### 3.5.2 F5.2 JSON export

Acceptance criteria [PRD §F5.2]: raw analysis JSON; documented schema; pretty-printed; versioned.

Shipped: `GET /exports/analysis/{id}` returns `record.result_json` parsed to dict [`main.py:848`]. `schema_version` field is **not** present in the payload. **OPEN QUESTION:** PRD requires `schema_version`; not shipped.

#### 3.5.3 F5.3 CSV export (bulk)

Acceptance criteria [PRD §F5.3]: multi-analysis CSV; summary columns; escaped; option for detailed rows.

Shipped [`main.py:541` `GET /exports/analyses.csv`]: summary format only — columns `id, name, doc_type, source_url, status, confidence, risk_score, grade, created_at`. **Drift from PRD:** the `?detailed=true` query parameter for per-finding rows is not implemented. Findings-count breakdown (`high/medium/low` columns) is not implemented.

### 3.6 F6 — Watchlist Monitoring [PRD §F6]

Priority per PRD: P1 (Phase 4, Months 4-6). Shipped ahead of PRD schedule via `WatchlistItem` model and endpoints.

- `WatchlistItem` schema [`models.py:46`]: `vendor`, `source_url`, `status`, `last_checked`, `changes_since`, `change_count`, `risk_delta`, `change_summary`, `last_document_text` (capped 50KB), `last_document_hash`, `last_risk_score`, `last_analysis_id`.
- `POST /watchlist` adds; `DELETE /watchlist/{id}` removes; `POST /watchlist/{id}/refresh` re-fetches, diffs, and re-scores with `["US-CA", "GDPR"]` hard-coded [`main.py:976`]. **OPEN QUESTION:** watchlist refresh uses a hard-coded jurisdiction list; this contradicts the global-tool contract removal of default jurisdictions. Should this be aligned?
- Background refresh loop optional via `WATCHLIST_REFRESH_SECONDS` env var (default 0 = disabled) [`main.py:113`; `config.py:92`].
- Change frequency (daily/weekly/monthly) per PRD is **not implemented at the WatchlistItem level** — frequency scheduling lives on the separate `PolicyWatch` model with `check_frequency` in seconds [`models.py:76`].

Email notifications on significant change (PRD §F6.2) are **not shipped**. **OPEN QUESTION:** is email delivery deferred? No SMTP or mail-service config exists.

### 3.7 F7 — Vendor Comparison [PRD §F7]

Priority per PRD: P1 (Phase 4). **Not shipped.** No comparison endpoint, no side-by-side UI, no comparison PDF export. **OPEN QUESTION:** confirm this is deferred to a later release.

### 3.8 F8 — AI Law Analysis [PRD §F8]

Priority per PRD: P1 (MVP+ — rule detection ships with MVP; full UI surface post-MVP).

Shipped:
- AI-law jurisdiction codes present: EU-AI-ACT, COE-AI-225, OECD-AI, UNESCO-AI [`schemas.py:35`].
- AI-law categories: AI Training, AI Training Opt-Out, Automated Decision-Making, Consequential AI Decisions, High-Risk AI, Prohibited AI, GPAI / Generative AI, AI-Generated Content, Algorithmic Accountability, Human Oversight, AI Non-Discrimination [`schemas.py:60-79`].
- Colorado AI Act SB 205 mapped to US-CO jurisdiction [PRD §F2.1; §F8.2].
- Rubric field `aiLawSignalQuality` computed from AI-rule coverage estimate `8.5 * avg_conf + 1.5 * (1 - review_rate)` [`main.py:218`; note this is `8.5` because 12/64 rules cover AI law jurisdictions].

Dedicated AI-law findings view (F8.1–F8.5) does not exist as a separate UI section — AI-law findings surface in the same domain-grouped view as privacy findings [PRD §F8 Technical Notes].

---

## 4. Non-Functional Requirements

### 4.1 Performance

- Average analysis: <30 seconds [PRD §Executive Summary; PRD §Performance Tests]. Enforced by `LM_REQUEST_TIMEOUT_S=60` [`config.py:82`].
- `AnalysisPayload.estimated_time` records elapsed wall-clock per analysis [`analyzer.py:580, 599`].
- Document size caps [PRD §Performance Tests]: small <10s, medium <20s, large <30s, very large <60s or warning. Enforced structurally by `max_input_chars = 20000` [`config.py:83`] — silently truncates over-length input in `_truncate_text` [`analyzer.py:143`].

### 4.2 Availability

- Uptime target 99.5% [PRD §Performance]. **OPEN QUESTION:** no availability monitoring or SLA harness shipped; is this a deployment-time concern for the future SaaS phase?
- LLM outage tolerance: graceful degradation to rule-only, documented in [LIB-ARCH §Failure Modes].
- Legal-KB outage tolerance: retrieve returns `[]`, analysis proceeds without augmentation [LIB-ARCH §Failure Modes; `legal_kb.py`].

### 4.3 Security

Detailed in §15. Summary:
- Local-only inference, no external API calls [.claude/CLAUDE.md §Hard Requirements].
- SSRF guards on URL fetch [`ingest.py:155`].
- XSS defense-in-depth: URL scheme allowlist at schema layer [`schemas.py:177, 204, 322, 367`]; XML escaping in PDF export [`main.py:14`]; HTML escaping in Streamlit [`app_streamlit_v2.py`].
- ReDoS canary test [LIB-TEST §Categorical regression coverage; `test_regressions_pr34.py`].
- Optional HMAC-SHA256 API key [`main.py:70` `_verify_api_key`; `config.py:95`].

### 4.4 Privacy

- All processing local [PRODUCT.md §Design Principles §4].
- No document upload to external servers [BRD §Core Value Propositions §1].
- SQLite database local; `document_text` cap 50KB on `Analysis` record [`main.py:195`; `models.py:24`].
- Watchlist `last_document_text` cap 50KB [`main.py:161`; `models.py:58`].
- Public analysis detail response strips `document_text` [`main.py:537`].

### 4.5 Accessibility

- **WCAG 2.2 Level AA** [PRD §Accessibility Requirements; PRODUCT.md §Accessibility & Inclusion].
- Keyboard navigation, focus indicators, semantic HTML, ARIA labels, contrast 4.5:1 body / 3:1 large / 3:1 UI, touch targets 44×44px, reduced-motion variants [PRD §Accessibility Requirements].
- Responsive breakpoints Mobile <640px, Tablet 640–1024, Desktop >1024 [PRD §Responsive Breakpoints].
- **OPEN QUESTION:** no automated accessibility test harness (e.g. axe-core, pa11y) is present in `src/backend/tests/` or `src/webapp/`. Compliance is currently review-based only.

### 4.6 Internationalization

- Apertus 8B supports 1,000+ languages [BRD §Multilingual expansion; PRODUCT.md-adjacent claim].
- EuroLLM 22B supports 35 EU languages [BRD §Executive Summary; LIB-STACK §Configuration].
- Language routing via `langdetect` [`localai.py:39` `_select_model`] — EU codes → EuroLLM, all others → Apertus.
- Prompt templates are English-only [`prompts.py`]. **OPEN QUESTION:** BRD promises "1,000+ language" analysis but the system prompt is English. Confirmed by inspection: `SYSTEM_PROMPT` [`prompts.py:7`] is a fixed English string. The LLM can still analyze non-English document text, but the instructions to the LLM are English-only.

### 4.7 Cost model

- Zero external API cost — local inference only [BRD §Cost Structure line "$2K LLM API (fallback)" appears to conflict with .claude/CLAUDE.md §Hard Requirements ["No external API calls"] — **OPEN QUESTION**].
- Infrastructure cost dominated by LocalAI compute (GPU) and SQLite disk. Not directly captured in code.

---

## 5. Data Model

### 5.1 Pydantic schemas (`src/backend/app/schemas.py`)

#### 5.1.1 `Evidence` [`schemas.py:141`]

| Field | Type | Constraint | Notes |
|---|---|---|---|
| `line_start` | int | `>= 1` | Line number where clause begins |
| `line_end` | int | `>= 1` | Line number where clause ends |
| `legal_basis` | List[str] | default `[]` | Applicable statute citations |
| `start_offset` | int? | `>= 0` | Char offset of match |
| `end_offset` | int? | `>= 0` | Char offset of match end |
| `context_before` | str? | — | 2-3 sentences before match |
| `context_after` | str? | — | 2-3 sentences after match |

Anchor: [PRD §F3.3 Evidence Binding]. `context_before` / `context_after` are shipped fields not documented in PRD.

#### 5.1.2 `Finding` [`schemas.py:151`]

| Field | Type | Constraint | Anchor |
|---|---|---|---|
| `category` | str | validated against `CATEGORIES` at import | [LIB-RULES §Category taxonomy] |
| `severity` | Literal["Low","Medium","High","Critical"] | — | [PRD §F3.2] |
| `confidence` | float | [0.0, 1.0] | [PRD §F3.4] |
| `excerpt` | str | — | [PRD §F3.3] |
| `explanation` | str | — | [PRD §F4.4] |
| `jurisdictions` | List[Jurisdiction] | — | [PRD §F2.1] |
| `evidence` | Evidence | — | [PRD §F3.3] |
| `needs_review` | bool | default False | [PRD §F3.4] |
| `source_document` | str? | default None | Batch analysis provenance [LIB-API] |
| `impact` | int | [1, 5], default 2 | [LIB-RULES §IRP] |
| `likelihood` | int | [1, 5], default 3 | [LIB-RULES §IRP] |
| `safeguard_score` | int | [0, 5], default 0 | [LIB-RULES §IRP] |
| `irp_score` | float? | [0.0, 1.0], default None | [LIB-RULES §IRP] |

#### 5.1.3 `AnalyzeRequest` [`schemas.py:167`]

| Field | Type | Anchor |
|---|---|---|
| `text` | str, `min_length=1` | [PRD §F1.3] |
| `name` | str? | — |
| `doc_type` | DocType? | [PRD §F2.2] |
| `industry` | IndustryProfile? | [PRD §F2.3] |
| `source_url` | str? | scheme validator [§15] |
| `jurisdictions` | List[Jurisdiction], default `[]` | [PRD §F2.1] |
| `mode` | Literal["full","quick"], default "full" | **OPEN QUESTION:** not in PRD |
| `context` | List[ContextChip], default `[]` | [LIB-CONTEXT] |

#### 5.1.4 `AnalyzeUrlRequest`, `AnalyzeBatchRequest`, `BatchItem`

Same fields as `AnalyzeRequest` scoped to URL / file / batch inputs. `AnalyzeBatchRequest.items: List[BatchItem]` with `min_items=1`; `BatchItem` has `url?`, `name?`, `doc_type?` [`schemas.py:361`].

#### 5.1.5 `AnalysisPayload` [`schemas.py:220`]

25 fields including: `id`, `name`, `doc_type`, `industry`, `source_url`, `document_text`, `line_offsets`, `status`, `review_required`, `confidence`, `risk_score`, `grade`, `created_at`, `findings`, `summary`, `analysis_mode`, `estimated_time`, `action_readiness` (Literal["Go","Review","Stop"]), `completeness` (float [0.0, 1.0]), `context`, `jurisdictions`, `verdict_headline`, `verdict_label`, `top_by_domain` (dict[str, list[Finding]]), `action_items` (List[str]).

**Post-PR #34 additions [drift from PRD §Analysis Response]:** `action_readiness`, `completeness`, `context`, `jurisdictions`, `verdict_headline`, `verdict_label`, `top_by_domain`, `action_items` — none are described in PRD API contract. **OPEN QUESTION:** update PRD API contract to reflect shipped payload.

#### 5.1.6 `ContextChip` [`schemas.py:132`]

`Literal["want_understand", "for_child", "for_care", "for_work", "just_curious"]`. See §5.4 taxonomy.

#### 5.1.7 `Jurisdiction` [`schemas.py:8`]

30-value Literal enumerated in §3.2.1.

#### 5.1.8 `InferRequest` / `InferResponse` [`schemas.py:334`]

Powers intake auto-detection via `POST /infer` (§6). `InferRequest.text` capped at `max_length=200_000` chars to bound cache/regex work. `InferResponse.detected_signals` is an open dict of transparency signals.

#### 5.1.9 Other schemas

`ReviewItemPayload`, `ReviewUpdate`, `RubricScores` (8 fields + `overall`), `AnalysisSummary`, `WatchlistItemPayload`, `WatchlistCreateRequest`, `PolicySnapshotPayload`, `PolicySnapshotListItem`, `DiffToken`, `DiffResult`, `PolicyWatchPayload`, `PolicyWatchCreateRequest` (with `check_frequency: int, ge=300, le=604800` — 5 min to 7 days). All defined in `schemas.py`.

### 5.2 SQLAlchemy models (`src/backend/app/models.py`)

Five tables. Denormalized: findings serialized as JSON blob in `Analysis.result_json`, not a normalized `findings` table.

#### 5.2.1 `Analysis` [`models.py:10`]

| Column | Type | Constraint |
|---|---|---|
| `id` | String | PK, indexed |
| `created_at` | DateTime | default UTC now, NOT NULL |
| `doc_name` | String | nullable |
| `doc_type` | String | nullable |
| `source_url` | String | nullable |
| `source_type` | String | NOT NULL, one of `text`/`url`/`file`/`batch` |
| `source_value` | String | nullable |
| `status` | String | NOT NULL, one of `completed`/`needs_review` |
| `confidence` | Float | NOT NULL |
| `risk_score` | Float | NOT NULL |
| `grade` | String | NOT NULL |
| `document_text` | Text | nullable, capped 50KB [`main.py:195`] |
| `result_json` | Text | NOT NULL, serialized `AnalysisPayload` |

Anchor: [BRD §Database Schema, PRD §Database Schema] — both describe the shipped denormalized shape.

#### 5.2.2 `ReviewItem` [`models.py:28`]

| Column | Type | Constraint |
|---|---|---|
| `id` | String | PK, indexed |
| `analysis_id` | String | FK → analyses.id, ON DELETE CASCADE |
| `status` | String | default `pending` |
| `notes` | Text | nullable |
| `created_at` | DateTime | default UTC now |
| `updated_at` | DateTime | default UTC now, on-update UTC now |

#### 5.2.3 `WatchlistItem` [`models.py:46`]

Columns: `id`, `vendor` (NOT NULL), `source_url` (nullable), `status` (default "No Changes"), `last_checked` (default UTC now), `changes_since`, `change_count` (default 0), `risk_delta` (default 0.0), `change_summary` (Text), `last_document_text` (Text, capped 50KB), `last_document_hash` (SHA-256), `last_risk_score`, `last_analysis_id`.

#### 5.2.4 `PolicySnapshot` [`models.py:64`]

Columns: `id` (PK), `url` (NOT NULL, indexed), `content_hash` (SHA-256, indexed), `captured_at` (default UTC now, indexed), `raw_text` (Text, NOT NULL). Dedup on `(url, content_hash)` in `POST /snapshots` [`main.py:1068`].

#### 5.2.5 `PolicyWatch` [`models.py:76`]

Columns: `id` (PK), `url` (NOT NULL, UNIQUE, indexed), `user_id` (nullable), `check_frequency` (int seconds, default 86400 = 24h), `last_check`, `enabled` (String "true"/"false", default "true"), `created_at`.

### 5.3 Category taxonomy

Canonical `frozenset[str]` `CATEGORIES` [`schemas.py:50`], 52 members total (some are aliases). Grouped by [domain map from `analyzer._DOMAIN_MAP`, `analyzer.py:37`]:

**Data (collection):** Sensitive Data, Sensitive Data / Opt-Out, Biometric Data, Health Data, Financial Data, Children's Privacy, Collection Notice, Minors.

**Data use:** AI Training, AI Training Opt-Out, AI Training (Opt-Out) (alias), Sale/Share, Data Sale / Sharing (LLM alias), Tracking / Profiling, Tracking & Consent, Marketing Communications, Purpose Limitation, ADM, Automated Decision-Making, Consequential AI Decisions, High-Risk AI, Prohibited AI, GPAI / Generative AI, AI-Generated Content, Algorithmic Accountability, Human Oversight, AI Non-Discrimination.

**Terms of use:** Liability, Unilateral Changes, Dark Patterns, Deceptive Practices, Retention, Breach Notification, Data Security, Consent.

**Privacy rights:** User Rights, Data Rights, Individual Rights, Privacy Rights, Cross-Border Transfer, COPPA Compliance, HIPAA Compliance, FERPA Compliance, PCI DSS Compliance, PIPEDA Consent, LGPD Rights, APPI Disclosure, DPDP Consent, POPIA Processing, PIPA Processing, APP Privacy, UK Data Rights, Privacy as Human Right, Serious Privacy Invasion.

Every dict keyed on category name (`_DOMAIN_MAP`, `_CATEGORY_IRP_DEFAULTS`, `CATEGORY_WEIGHTS`) is validated against `CATEGORIES` at module load — mismatch raises `RuntimeError` [`context.py:121`; `analyzer.py:102`; LIB-RULES §Category taxonomy].

### 5.4 Context chip taxonomy [LIB-CONTEXT]

Five chips [`schemas.py:132`; `context.py:37`]:

| Value | Label (Streamlit v2 verbatim) | Italic sub-line |
|---|---|---|
| `want_understand` | I want to understand what I am agreeing to | *Nice to know before you tap "I agree." No judgment if you already did.* |
| `for_child` | Something my child wants to use | *Games, apps, social platforms. We will help you see what matters.* |
| `for_care` | Helping someone I care about with this | *A family member, extended family, and/or a friend.* |
| `for_work` | For work or a vendor pick | *A tool the team might use, or an agreement to sign.* |
| `just_curious` | Just curious | *Sometimes it is good to just know. No pressure either way.* |

Weight tier scale [LIB-CONTEXT §Weight tier scale]:

| Tier | Weight | Semantics |
|---|---|---|
| Baseline | 1.0 | Category not specifically privileged for this chip; IRP drives order |
| Boosted | 2.0 | Category is meaningful in this context |
| Priority | 2.5 | Category is one of top handful for this context |
| Signature | 3.0 | Category is the defining risk for this context |

`for_work` uses intermediate rungs (2.2 / 2.4 / 2.5 / 2.6 / 2.8) [LIB-CONTEXT §Weight tier scale]. Full `CATEGORY_WEIGHTS` reproduced verbatim from `context.py:37` in [LIB-CONTEXT §Full CATEGORY_WEIGHTS reference].

Multi-select weight merge [`context.py:166` `_merge_weights`]: sum across selected chips, capped at 3.0.

Priority order for verdict copy only [`context.py:135`]: `for_child > for_care > for_work > want_understand > just_curious`. Rationale: personal-stakes lenses win the headline over professional lenses [LIB-CONTEXT §Priority order].

### 5.5 Jurisdiction taxonomy

30 codes [`schemas.py:8`], grouped per [BRD §Jurisdiction Support]:

- **US Federal + State (11):** US-FED, US-CA, US-NY, US-TX, US-VA, US-CO, US-CT, US-IL, US-NJ, US-MN, US-OR.
- **International Privacy (13):** GDPR, UK-GDPR, LGPD, PIPEDA, CA-QC, POPIA, PDPA-KE, DPDP, APPI, PIPA, APP, PDPA-TH, NDPR.
- **International Frameworks (2):** ICCPR-17, COE-108.
- **AI Law (4):** EU-AI-ACT, COE-AI-225, OECD-AI, UNESCO-AI.

Every code has rule coverage in `rules.py` [BRD §Jurisdiction Support]. Human-readable framework names for PDF export in `_JURISDICTION_NAMES` [`main.py:636`].

---

## 6. API Contract

Cross-referenced against [LIB-API §Endpoint Map] and verified against `src/backend/app/main.py`. 24 business endpoints + `/health` + `/infer` = 26 total.

### 6.1 Authentication

Optional HMAC-compare API key [`main.py:70` `_verify_api_key`]. `API_KEY` env var; empty (default) disables auth for local dev. When set, every request must include `X-API-Key` header matching, verified with `hmac.compare_digest` (constant-time).

### 6.2 CORS

`ALLOWED_ORIGINS` env var, comma-separated [`config.py:86`]. Default: `http://localhost:8000,http://127.0.0.1:8000`. Extended by `run.sh` to include `:8501` (Streamlit). Methods: GET, POST, DELETE. Headers: Content-Type, X-API-Key. Credentials: allowed [`main.py:99`].

### 6.3 Endpoints

Full endpoint listing verified against `main.py` decorators [LIB-API §Endpoint Map].

#### 6.3.1 System

- `GET /health` → `{"status":"ok"}`. **Drift from LIB-API:** LIB-API §Endpoint Map documents a richer response `{status, model_world, model_eu, review_threshold}`. Shipped response is minimal. **OPEN QUESTION:** which is correct?

#### 6.3.2 Inference and analysis

- `POST /infer` → `InferResponse` [`main.py:255`]. **Drift from LIB-API:** LIB-API §Endpoint Map does not list `/infer` (documented under §Additional shipped endpoints in PRD). Should be added to LIB-API next revision.
- `POST /analyze` [`main.py:267`] → `AnalysisPayload`
- `POST /analyze/url` [`main.py:298`] → `AnalysisPayload`
- `POST /analyze/file` [`main.py:340`] → `AnalysisPayload` (multipart form)
- `POST /analyze/batch` [`main.py:432`] → `dict` (BatchAnalysisResult serialized)

#### 6.3.3 Reads and rubric

- `GET /analyses?limit=…` [`main.py:493`] → `List[AnalysisSummary]`. **OPEN QUESTION:** PRD §GET /analyses documents `skip`, `sort`, `order`, `filter_grade`, `filter_review_required`; shipped only supports `limit` (default 25, 1–200).
- `GET /rubric` [`main.py:520`] → `RubricScores | None`
- `GET /analyses/{id}` [`main.py:528`] → `AnalysisPayload` (with `document_text` stripped, 404 if missing)

#### 6.3.4 Exports

- `GET /exports/analyses.csv` [`main.py:541`] → CSV
- `GET /exports/analysis/{id}.pdf` [`main.py:574`] → PDF (503 if reportlab not installed; 404 if not found)
- `GET /exports/analysis/{id}` [`main.py:848`] → JSON (registered AFTER the `.pdf` route so the `{id}` path parameter doesn't shadow `.pdf`)

#### 6.3.5 Reviews

- `GET /reviews` [`main.py:856`] → `List[ReviewItemPayload]` (pending only)
- `POST /reviews/{id}` [`main.py:872`] → `ReviewItemPayload` (approve/reject only, no edit)

#### 6.3.6 Watchlist

- `GET /watchlist` [`main.py:891`] → `List[WatchlistItemPayload]`
- `POST /watchlist` [`main.py:910`] → `WatchlistItemPayload`
- `DELETE /watchlist/{id}` [`main.py:936`] → `{status, id}`
- `POST /watchlist/{id}/refresh` [`main.py:946`] → `WatchlistItemPayload`

#### 6.3.7 Snapshots and diff

- `GET /snapshots?url=…` [`main.py:1015`] → `List[PolicySnapshotListItem]` (404 if none)
- `GET /snapshots/detail/{id}` [`main.py:1038`] → `PolicySnapshotPayload` (with `raw_text`)
- `POST /snapshots?url=…` [`main.py:1054`] → `PolicySnapshotPayload` (deduplicates by `(url, content_hash)`)
- `GET /diff/{id1}/{id2}` [`main.py:1105`] → `DiffResult` (400 if URLs differ)

#### 6.3.8 Policy watch

- `POST /policy-watch` [`main.py:1168`] → `PolicyWatchPayload` (409 if URL already watched)
- `GET /policy-watch` [`main.py:1199`] → `List[PolicyWatchPayload]`
- `DELETE /policy-watch/{id}` [`main.py:1217`] → `{status, id}`
- `POST /policy-watch/{id}/snapshot` [`main.py:1229`] → `PolicySnapshotPayload` (manual snapshot trigger)

### 6.4 Error codes

Per [LIB-API §Error Responses]:

| Status | When |
|---|---|
| 400 | Empty text, invalid URL, unsupported file type, malformed body, diff mismatch |
| 404 | Analysis / review / watchlist item / snapshot / policy-watch not found |
| 409 | Policy-watch URL already exists |
| 413 | File upload exceeds `max_upload_bytes` |
| 422 | Invalid `doc_type` / `industry` on multipart upload |
| 500 | Unexpected server error, stored JSON invalid |
| 503 | PDF export unavailable (reportlab missing) |

Rate limits: not implemented. **OPEN QUESTION:** BRD/PRD do not specify a rate-limit contract; is one required for MVP?

---

## 7. Inference Pipeline

### 7.1 LocalAI configuration

- Endpoint: `LOCALAI_BASE_URL` (default `http://localhost:8080/v1`) [`config.py:27`; LIB-STACK §Configuration].
- Models: `MODEL_WORLD=apertus-8b-instruct`, `MODEL_EU=eurollm-22b-instruct` [`config.py:31,35`].
- Timeout: `LM_REQUEST_TIMEOUT_S=60` [`config.py:82`].
- Client: `LocalAIClient` in `src/backend/app/services/localai.py:77`.

### 7.2 Language routing

`_select_model(text)` [`localai.py:39`]:

1. If `LANGUAGE_DETECTION_ENABLED=false` → return `MODEL_WORLD` (Apertus).
2. Detect language via `langdetect` on first 2,000 chars [`localai.py:25`].
3. If detected ISO 639-1 code ∈ `EU_LANGUAGE_CODES` (24 EU official languages) → `MODEL_EU` (EuroLLM).
4. Else → `MODEL_WORLD`.

Failure paths: langdetect unavailable, detection raises → return `None` → route to Apertus [`localai.py:25`].

### 7.3 Prompt templates

**System prompt** [`prompts.py:7`]:

> "You are a legal-risk analyst for privacy policies and terms of service. Use only the provided document text. Do not invent facts. Return JSON only, no markdown."

**User prompt** [`prompts.py:14` `build_user_prompt(numbered_text, jurisdictions, rule_findings, legal_context)`]:

Includes:
- Requested jurisdictions.
- JSON schema for `summary`, `overall_confidence`, `findings[]` with each finding carrying `category`, `severity`, `confidence`, `excerpt`, `explanation`, `jurisdictions`, `impact`, `likelihood`, `safeguard_score`, `evidence: {line_start, line_end, legal_basis}`.
- Rules block: "Every finding must cite line numbers", "must include at least one legal_basis citation", "Only include issues supported by the text", "Keep categories short", "If there are no issues, return an empty findings list", "Estimate impact/likelihood/safeguard_score (0-5: mitigations visible in the document for this specific finding)".
- Optional legal-KB `legal_context` block: each retrieved passage prefixed by `[<jurisdiction> <section>]`; PLACEHOLDER-status passages get an inline `[UNVERIFIED PLACEHOLDER — not real statute text, do not cite as authoritative]` warning [`prompts.py:23`; LIB-LEGAL §RAG Architecture].
- Rule-based detections included verbatim for context.
- Line-numbered document text [`analyzer.py:148` `_with_line_numbers` — 4-digit zero-padded prefix].

### 7.4 LLM response schema

Per-finding fields expected: `category` (str), `severity` (Low/Medium/High/Critical), `confidence` (float), `excerpt` (str), `explanation` (str), `jurisdictions` (List[str]), `impact` (int 1-5), `likelihood` (int 1-5), `safeguard_score` (int 0-5), `evidence.line_start`, `evidence.line_end`, `evidence.legal_basis[]`. Parsed into `Finding` [`analyzer.py:497`]; invalid entries silently skipped.

Payload-level: `summary` (2-4 sentence string) and `overall_confidence` (float) [`analyzer.py:493`].

### 7.5 Merge algorithm

`_merge_findings(rule_findings, llm_findings)` [`analyzer.py:612`]:

- Key: `(category.lower(), excerpt.strip()[:120].lower())`.
- Rule findings processed first; if key matches an LLM finding:
  - `confidence = 0.6 * rule_confidence + 0.4 * llm_confidence`, clamped [0, 1].
  - `safeguard_score = max(rule.safeguard_score, llm.safeguard_score)`.
  - `impact`, `likelihood` = rule baseline.
  - `irp_score` recomputed via `_compute_irp`.
  - `needs_review = hybrid_confidence < 0.6`.
- Rule-only findings: kept as-is (confidence remains 0.90–0.95).
- LLM-only findings (not matched): kept as-is, with `needs_review = llm_confidence < 0.6`.
- LLM findings with empty `evidence.legal_basis` dropped **before** merging [`analyzer.py:498`], counted as `dropped_for_legal`.

### 7.6 Jurisdiction post-filter

LLM findings are filtered by requested jurisdictions [`analyzer.py:528`]:

- If `jurisdictions` non-empty: keep finding iff `finding.jurisdictions` intersects the requested set.
- If `jurisdictions` empty (global-tool contract): keep finding iff `finding.jurisdictions` is non-empty (unclaimed findings still dropped — an LLM finding without a declared jurisdiction is unverifiable).

Rule findings are jurisdiction-scoped at detection time in `detect_findings` (§8).

### 7.7 Validation

`validate_findings(findings, document_text)` [`validation.py:20`]:

- Missing excerpt → `hallucination_flags += 1`, issue logged.
- Invalid line numbers (`< 1` or `line_start > line_end`) → `hallucination_flags += 1`.
- Line numbers out of range → `hallucination_flags += 1`.
- Missing `jurisdictions` → issue logged.
- Missing `legal_basis` → `missing_citations += 1`, issue logged.
- Excerpt not found in document (after normalization: lowercase + whitespace collapse) → `hallucination_flags += 1`.
- Penalty: `0.03 * issues + 0.07 * missing_citations + 0.08 * hallucination_flags`, coverage penalty if `coverage_ratio < 0.7`.

Returns `ValidationResult(confidence: float, issues: List[str])`.

### 7.8 Overall confidence

`analyze_text` computes analysis-level confidence [`analyzer.py:550`]:

```
confidence = mean(validation.confidence, llm_overall_confidence)
if mode == "quick":
    confidence *= 0.85
else:
    if not summary:              # LLM returned no payload
        confidence *= 0.8
    elif not llm_findings:       # LLM responded but found nothing
        confidence *= 0.85
    if dropped_for_legal:
        confidence *= max(0.5, 1 - 0.1 * dropped_for_legal)
confidence = clamp(confidence, 0.0, 1.0)
```

`review_required = confidence < settings.review_threshold` [`analyzer.py:567`].

### 7.9 Intake inference

`POST /infer` [`main.py:255`; `services/inference.py`] powers the Streamlit v2 intake auto-detect:

Signal precision order [`inference.py` §Signals]:
1. URL TLD (`.co.uk` → UK-GDPR, `.eu`/`.de`/`.fr`/... → GDPR, `.ca` → PIPEDA, `.au` → APP, `.br` → LGPD, `.in` → DPDP, `.jp` → APPI, `.kr` → PIPA, `.za` → POPIA, `.mx` → LGPD, `.ng` → NDPR, `.ke` → PDPA-KE, `.th` → PDPA-TH).
2. Explicit statute mentions (CCPA, GDPR, LGPD, ...).
3. Regulatory body mentions (ICO, CNIL, ANPD, ...).
4. Geographic scope phrases ("California residents", "EEA data subjects", ...).
5. Currency + language pairing.
6. Language heuristic (fr/de/it/es/nl → GDPR).

If nothing fires: `jurisdictions = []`, `location_needed = True`. **No default US-CA + GDPR fallback** [LIB-RULES §Global-tool contract].

Regex patterns are pre-compiled at module load [`inference.py` note "Fix 7: regex pre-compilation"]. `@lru_cache(maxsize=128)` on the hot path [`inference.py:47`]. Text capped at 200,000 chars to bound cache and regex work [`schemas.py:339`].

### 7.10 Fallback behavior

Verbatim from [LIB-ARCH §Failure Modes]:

| Failure | Behavior |
|---|---|
| LLM unreachable (LocalAI down) | Rule-only, `confidence *= 0.8`, may trigger review |
| LLM returns invalid JSON | Rule-only, `confidence *= 0.8` |
| LLM returns empty findings | Keep rule findings, `confidence *= 0.85` |
| LLM findings missing legal_basis | Drop those findings, apply `dropped_for_legal` penalty |
| Legal-KB index missing/empty or embedding unreachable | `retrieve()` returns `[]`, LLM runs without augmentation |
| Legal-KB embedding dimension mismatch | Logged warning, retrieve returns `[]` |
| Legal-KB jurisdiction has no matching chunks | Fall back to searching full corpus |
| Parsing error / empty text | 400 with message |
| Confidence < 0.80 | Create review_item (HITL) |

---

## 8. Rule Engine

### 8.1 Structure

64 `RulePattern` entries in `PATTERNS` [`rules.py:21`; verified `grep -c "RulePattern(" rules.py` = 64]. ~50 unique `category` values (some rules share a category with different pattern shapes).

`RulePattern` dataclass [`rules.py:10`]:

| Field | Type | Semantics |
|---|---|---|
| `category` | str | Must be in `schemas.CATEGORIES` |
| `severity` | Severity | Low/Medium/High/Critical |
| `jurisdictions` | List[Jurisdiction] | Which jurisdiction codes this rule applies to |
| `explanation` | str | Reader-facing explanation |
| `legal_basis` | List[str] | Statute citations |
| `patterns` | List[str] | Regex patterns (case-insensitive) |
| `name` | str? | Optional human-readable rule name for docs/tests |

### 8.2 Detection pipeline

`detect_findings(text, jurisdictions)` [`rules.py:1035`]:

1. Build `jurisdiction_filter = set(jurisdictions) or None` — empty list means "no filter" [global-tool contract].
2. For each `RulePattern`:
   - Skip if filter is set and rule jurisdictions don't intersect.
   - `_match_stats(rule.patterns, text)` → find first match, count pattern hits and total matches [`rules.py:1021`].
   - If no match, skip.
   - Compute line numbers, excerpt (±140 chars window), context sentences (±2 sentences).
   - Compute confidence via `_confidence_rules_based` (§8.4).
   - Seed IRP via `_seed_irp(category)` (§8.3).
   - Emit `Finding` with all metadata.

`detect_high_severity_findings` [`analyzer.py:677`]: quick mode variant — iterates every pattern, only includes rules with severity `High` or `Critical`, seeds IRP the same way, uses fixed `confidence=0.8`.

### 8.3 IRP seeds

`_CATEGORY_IRP_DEFAULTS` [`rules.py:900`]: 38 categories mapped to `(impact, likelihood)`. Examples:

| Category | (Impact, Likelihood) |
|---|---|
| Sale/Share | (4, 5) |
| ADM | (5, 3) |
| Prohibited AI | (5, 1) |
| Children's Privacy | (5, 3) |
| Health Data | (5, 2) |
| Tracking / Profiling | (3, 5) |
| Retention | (3, 4) |
| Collection Notice | (2, 4) |

Unknown category defaults to `_IRP_DEFAULT = (2, 3)` [`rules.py:940`]. `_seed_irp(category, safeguard_score=0)` [`rules.py:943`] returns `(impact, likelihood, safeguard_score, irp_score)` — safeguard defaults to 0 at rule detection (no mitigations assumed).

### 8.4 Rule confidence

Active path `_confidence_rules_based` [`rules.py:1002`]:

```
hit_ratio = pattern_hits / pattern_total
if pattern_hits >= pattern_total * 0.5:
    confidence = 0.93 + 0.02 * min(1.0, hit_ratio)   # 0.93-0.95
else:
    confidence = 0.90 + 0.03 * hit_ratio              # 0.90-0.93
return clamp(confidence, 0.90, 0.95)
```

Anchor: [LIB-RULES §Rule-Based Confidence Formula]. Rules are inherently high-confidence because they're pattern-matched. Dead code — an older `_confidence` helper clamped to `[0.35, 0.95]` remains in the file but is not called [LIB-RULES §note].

### 8.5 Category → IRP defaults consistency

The 38 categories in `_CATEGORY_IRP_DEFAULTS` are a subset of `CATEGORIES` (52 total). Categories not present in defaults fall through to `_IRP_DEFAULT = (2, 3)`. **OPEN QUESTION:** should the remaining ~14 categories be given explicit IRP defaults, or is `(2, 3)` acceptable?

---

## 9. Verdict and Scoring Semantics

### 9.1 IRP formula

`_compute_irp(impact, likelihood, safeguard_score)` [`analyzer.py:136`]:

```
raw = 0.5 * (impact / 5) + 0.4 * (likelihood / 5) - 0.3 * (safeguard_score / 5)
irp_score = clamp(round(raw, 4), 0.0, 1.0)
```

Range:
- Max risk (impact=5, likelihood=5, safeguard=0): 0.90
- Fully mitigated (impact=1, likelihood=1, safeguard=5): 0.0 (clamped)
- Typical Sale/Share (impact=4, likelihood=5, safeguard=0): 0.80
- Prohibited AI (impact=5, likelihood=1, safeguard=0): 0.58

### 9.2 Score-to-grade

`_grade(score)` [`analyzer.py:426`] — 7-tier grade table (§3.3.1).

### 9.3 Action readiness

`_compute_action_readiness(risk_score, confidence, completeness)` [`analyzer.py:185`]:

- If `risk_score >= 7.0` or `completeness < 0.375` → "Stop"
- Elif `risk_score < 4.0` and `confidence >= 0.65` and `completeness >= 0.625` → "Go"
- Else → "Review"

Completeness computed by `_compute_completeness` [`analyzer.py:177`] against 8 pattern classes: user_rights, retention, minors, contact, opt_out, adm, security, third_party. Score is `found / 8` rounded to 2 decimals.

### 9.4 Context chip weight tiers

Full table in §5.4. Multi-chip merge: `_merge_weights` sums across selected chips, capped at 3.0 [`context.py:166`].

### 9.5 Sort key

`apply_category_weights` [`context.py:182`]:

```python
def sort_key(f: Finding) -> tuple[float, float, int]:
    weight = merged.get(f.category, 1.0)
    irp = f.irp_score if f.irp_score is not None else _severity_fallback(f.severity)
    return (weight, irp, _SEVERITY_RANK.get(f.severity, 0))

return sorted(findings, key=sort_key, reverse=True)
```

All three dimensions descending. Tier-first: category weight leads, IRP breaks ties within tier, severity_rank is final tie-breaker. Baseline chips (`want_understand`, `just_curious`) collapse all categories to weight 1.0, so IRP alone drives the sort. Sort is stable [LIB-TEST Category G].

`_severity_fallback` [`context.py:177`]: `{"Critical": 0.9, "High": 0.75, "Medium": 0.5, "Low": 0.25}` for legacy findings without `irp_score`.

Category-not-found defaults to weight 1.0 — baseline, not zero [LIB-CONTEXT §Sort key].

### 9.6 Verdict labels

Actionable labels [LIB-VOICE §Verdict labels are actionable]; verbatim from `context.py::VERDICT_LABEL`:

| Chip | Go | Review | Stop |
|---|---|---|---|
| `want_understand` | Reasonable | Worth a closer read | Serious concerns |
| `for_child` | Reasonable for a child | Worth a closer read for a child | Not built for children |
| `for_care` | Reasonable to share | Worth reviewing together | Concerning to share |
| `for_work` | Workable | Worth a legal pass | Not vendor-safe as written |
| `just_curious` | Clear | Worth noting | Notable practices |

Verdict headlines [`context.py::VERDICT_HEADLINE`]:

| Chip | Go | Review | Stop |
|---|---|---|---|
| `want_understand` | This policy is clearer than most. | A few things here may be worth understanding before agreement. | Multiple parts of this policy may work against the reader's privacy. |
| `for_child` | For a child, this policy is clearer than most. | For a child, a few things here may be worth understanding first. | This service may not be built with children in mind. |
| `for_care` | This policy is clearer than most for someone being helped. | A few things here may be worth explaining to the person being helped. | Some parts of this policy could take advantage of someone unfamiliar with online agreements. |
| `for_work` | For work use, this policy holds up better than most. | For work use, a few clauses here deserve a second look before sign-off. | For work use, several clauses here could put the business on the hook. |
| `just_curious` | This policy is relatively clear. | There are a few things worth noting here. | This policy has several notable practices. |

Both tables must remain em-dash-free per [LIB-VOICE §No em-dashes in tool voice]. Verified by inspection — no U+2014 in `context.py::VERDICT_HEADLINE` or `VERDICT_LABEL`.

---

## 10. Domain Grouping

### 10.1 Four domains

Fixed order [`analyzer.py:96` `_DOMAIN_ORDER`]:

1. **Data** — what's collected.
2. **Data use** — how it's used.
3. **Terms of use** — the agreement itself.
4. **Privacy rights** — what can still be exercised.

UI labels in Streamlit v2 [`app_streamlit_v2.py:777` `DOMAIN_LABELS`]. Reader-facing sub-labels: "what's collected", "how it's used", "the agreement itself", "what can still be exercised".

### 10.2 Category → domain map

`_DOMAIN_MAP` [`analyzer.py:37`] — full listing in §5.3. Import-time drift guard against `schemas.CATEGORIES` [`analyzer.py:102`].

### 10.3 Grouping algorithm

`_group_by_domain(findings, max_per_domain=2, max_total=8)` [`analyzer.py:110`]:

- Assumes findings are already sorted by context weight (via `apply_category_weights`).
- Iterate findings in order; assign to the first eligible domain slot.
- Each domain caps at 2 findings; total caps at 8.
- Domains with no eligible findings map to empty list — frontend renders "Nothing notable surfaced under X" [`app_streamlit_v2.py:791`].
- Findings whose category is not in `_DOMAIN_MAP` are silently skipped. **OPEN QUESTION:** should unmapped categories go to a default bucket or emit a log warning?

### 10.4 Hardware permissions

Per [LIB-PRINCIPLES §Principle 4] and [LIB-VOICE §Scope-honesty gap]: **Hardware permissions are never a domain group with findings**. They surface as a verbatim line in the scope box (§11): "What permissions the app actually requests on a phone (camera, microphone, contacts, location). Those live in device Settings." [`app_streamlit_v2.py:768`].

---

## 11. UI Specification — Streamlit v2 (Primary)

### 11.1 State machine

Two views, routed via `st.session_state["view"]` [`app_streamlit_v2.py:10`]:

- `intake` (default)
- `results`

Transition triggered by successful `POST /analyze*` return; `run_analysis()` sets view to results [`app_streamlit_v2.py:523`].

### 11.2 Intake view

Rendered by `render_intake` [`app_streamlit_v2.py:359`]. Structure:

1. Wordmark + intake headline: "What's on your mind?" [PRD §Implementation Status Note — voice per LIB-VOICE §Intake voice].
2. Context chip cards — 5 chips via `st.checkbox` styled with `pr-card-label` and `pr-card-sub` [`app_streamlit_v2.py:34`].
3. Optional section: location (country dropdown, US state dropdown), doc type, industry.
4. Input tabs: link / paste / upload (3-tab TabPanel).
5. Submit button.

Location dropdowns default to blank (`index=None`) [.claude/CLAUDE.md §Session outcomes]. Country: `COUNTRY_OPTIONS` [`app_streamlit_v2.py:63`] — 9 options. US state: `US_STATE_OPTIONS` [`app_streamlit_v2.py:74`] — 7 options.

`_location_to_jurisdictions` [`app_streamlit_v2.py:321`] maps user selection to jurisdiction codes; **no California + GDPR default fallback** — the docstring explicitly notes "mis-scope findings for the ~90% of world users who aren't in California" as the reason.

### 11.3 Results view

Rendered by `render_results` [`app_streamlit_v2.py:625`]. Structure:

1. Verdict card (headline + label + subline) — color-coded (`caution` amber, `go` green, `stop` red) [`app_streamlit_v2.py:129-137`].
2. Context chip summary — "Reviewed for: [chip labels]" via `_selected_context_labels` [`app_streamlit_v2.py:605`].
3. Grade summary metrics: risk score (0–10), completeness (0–100%), issues count with severity breakdown.
4. **Always-visible scope box** [`app_streamlit_v2.py:762`] — verbatim copy:
   > **What was checked:** The words in this policy. How it describes data collection, sharing, tracking, AI/automated decisions, and rights under applicable jurisdictions.
   >
   > **What wasn't checked:**
   > - What permissions the app actually requests on a phone (camera, microphone, contacts, location). Those live in device Settings.
   > - Whether real-world practices match what this policy says. Only the document itself was analyzed.
5. Domain-grouped top findings — 4 sections (Data / Data use / Terms of use / Privacy rights) each rendering up to 2 items from `top_by_domain`.
6. Legal details expander — full findings list with severity tag, category, IRP badge, excerpt (HTML-escaped), plain explanation, legal basis, line reference, IRP row.
7. Suggestions section — "Some things worth considering" — sourced from backend `AnalysisPayload.action_items` [`app_streamlit_v2.py:859`], falls back to generic pointer if empty.
8. Export bar — PDF, JSON, CSV via download buttons [`app_streamlit_v2.py:874`].

### 11.4 Voice

Enforced per [LIB-VOICE]:

- Intake: first-person warm ("we're here to help", "you", "your").
- Results: third-person observational (no "you", "we", "our", "your", "us").
- Tentative framings ("may", "possibly", "might") throughout results.
- No em-dashes (U+2014) anywhere in tool-voice strings — em-dash rule applies to intake copy, results copy, verdict headlines/labels, scope box, error messages. Em-dashes allowed only in verbatim quotes of the analyzed policy (rendered as HTML-escaped content inside `pr-finding-excerpt`).

### 11.5 Copy specimens (verbatim)

Intake headline: "What's on your mind?"

Chip labels and sub-lines: verbatim table in §5.4.

Verdict headlines and labels: verbatim tables in §9.6.

Scope box: verbatim in §11.3 point 4.

Suggestion header: "Some things worth considering"

Fallback suggestion: "Review the specific opt-out and rights mechanisms named in the legal details above."

Domain empty state: "Nothing notable surfaced under {domain}."

### 11.6 Feature flag

`STREAMLIT_UI` env var [`run.sh:24`]:

- `v2` (default) → `app_streamlit_v2.py`
- `v1` (legacy rollback) → `app_streamlit_legacy.py`
- Anything else → `run.sh` errors out with "STREAMLIT_UI must be 'v1' or 'v2'".

---

## 12. UI Specification — Retired JS SPA (historical)

### 12.1 Retirement decision

The pre-redesign vanilla-JS SPA (`src/webapp/index.html`, `app.js`, `style.css`) was retired in Phase 4 of the issue #19 remediation (2026-07-03). The three files were deleted, `run.sh` was reduced from three services to two (backend + Streamlit), and the pre-redesign UI is no longer part of the shipping product. Streamlit v2 (`app_streamlit_v2.py`) is the sole UI; `app_streamlit_legacy.py` remains as the `STREAMLIT_UI=v1` rollback path.

### 12.2 Historical context (retained for changelog continuity)

Pre-PR #34 the SPA carried: character counter and short-text warning, 30-jurisdiction scrollable checkbox list, grade summary header, Verify View modal, dark-mode toggle, and a JSON export. The independent UI/UX validation pass (2026-07-03) found the SPA had wider feature coverage than the then-nascent Streamlit v2, tracked as issue #17. Rather than bring the SPA to parity with the redesigned Streamlit v2, the user chose retirement — Streamlit v2 already carried the redesign anchor and the SPA had no reader constituency worth the maintenance surface.

Rationale for retirement over parity work:
- Streamlit v2 is the anchor for issue #19 plain-language redesign copy, verdict framing, context chips, and domain grouping — bringing a second UI to match doubles maintenance cost with no product benefit.
- CORS + dual-service run.sh + two-suite Playwright coverage added complexity with no offsetting user need.
- The `STREAMLIT_UI=v1` legacy Streamlit path preserves a Streamlit-only rollback if v2 regresses; the SPA was never used as a rollback path in practice.

---

## 13. Persistence and Data Storage

### 13.1 SQLite

- URL: `DATABASE_URL` env var, default `sqlite:///{data_dir}/terms_analysis.db` [`config.py:77`].
- Data directory: `TERMS_ANALYSIS_DATA_DIR` env var, default `{repo}/data` [`config.py:16`].
- ORM: SQLAlchemy declarative base in `src/backend/app/database.py`.
- Tables: `analyses`, `review_items`, `watchlist_items`, `policy_snapshots`, `policy_watches` (§5.2).
- Init: `init_db()` called on FastAPI lifespan startup [`main.py:81`].

### 13.2 Legal corpus

- Directory: `data/legal_corpus/<jurisdiction>/<law>.txt` [LIB-LEGAL §RAG Architecture].
- Verified subdirectories present [`ls data/legal_corpus/`]: `canada/`, `eu/`, `us-ca/`, `us-co/`, `us-ct/`, `us-ny/`.
- File format: leading `# Key: Value` metadata lines, `## Section N — Title` chunk headers [`legal_kb.py:_parse_corpus_file`].
- Content: currently placeholder text pending real statute ingestion [.claude/CLAUDE.md §Project Map; BRD §Executive Summary; LIB-LEGAL §RAG Architecture note].
- PLACEHOLDER status propagates via `PLACEHOLDER_STATUS = "placeholder"` [`legal_kb.py:47`] into prompt warnings [`prompts.py:23`].

### 13.3 Watchlist storage

- `WatchlistItem.last_document_text` capped at 50,000 chars [`main.py:161`; §5.2.3].
- `WatchlistItem.last_document_hash` uses SHA-256 via `content_hash` [`diffing.py`].

### 13.4 Snapshot and diff storage

- `PolicySnapshot.raw_text` stored in full (no cap — potentially unbounded). **OPEN QUESTION:** should snapshot `raw_text` be capped for disk-usage safety?
- Deduplication on `(url, content_hash)` [`main.py:1068`].
- `diff_tokens` returns added/removed/unchanged tokens with severity classification [`diffing.py`; §6.3.7].

---

## 14. RAG / Legal Knowledge Base

### 14.1 Three-layer ensemble

Per [LIB-LEGAL §RAG Architecture] and `legal_kb.py`:

1. **Sparse (BM25)** — `rank_bm25.BM25Okapi` [`embedding.py:_BM25`], keyword and defined-term match.
2. **Dense (Apertus embeddings)** — `LocalAIClient.embed()` against `MODEL_WORLD`, L2-normalized, exhaustive cosine similarity via `numpy` dot product.
3. **Fusion (RRF)** — Reciprocal Rank Fusion [`embedding.py:rrf_fuse`], `RRF_K=60` [`config.py:50`].

Note: [LIB-STACK §Python Dependencies] confirms `sentence-transformers`, `torch`, `faiss-cpu` are **not** added. Embeddings reuse the existing `LocalAIClient.embed()` HTTP call; the vector index is a plain numpy matrix.

### 14.2 No FAISS

Meta-origin dependency, rejected [LIB-LEGAL §REJECTED Tools; LIB-STACK §Rejected Dependencies]. Numpy exhaustive search chosen because:

- Correctness — exact search, no ANN false-negative risk on legal citations [LIB-LEGAL §Vector Store].
- Zero new dependencies — `numpy` already required.
- Corpus size — <50K chunks, exhaustive dot product costs nothing at this scale [LIB-LEGAL §Vector Store].
- Future: `sqlite-vec` (MIT, Alex Garcia) if corpus grows past 100K chunks [LIB-LEGAL §Vector Store].

### 14.3 Retrieval flow

`get_legal_kb().retrieve(query, client, jurisdictions)` [`legal_kb.py`; wired into `analyzer.py:477`]:

1. Build query text: `" ".join(jurisdictions) + " " + cleaned[:500]` [`analyzer.py:476`].
2. Filter corpus to jurisdiction-matching chunks; fall back to full corpus if no matches [LIB-ARCH §Failure Modes].
3. BM25 scores over filtered pool.
4. Dense embeddings query + cosine similarity over filtered pool.
5. RRF fusion with `k=60`.
6. Return top `LEGAL_KB_TOP_K` chunks (default 5, `config.py:74`) as dicts with `jurisdiction`, `section`, `text`, `status` keys.
7. Failure paths return `[]` — never raise into `analyze_text`.

### 14.4 Corpus placeholder status

Chunks marked `# Status: PLACEHOLDER` in the corpus file metadata carry `status="placeholder"` [`legal_kb.py:47`]. `prompts.py::build_user_prompt` [`prompts.py:23`] wraps such passages in `[UNVERIFIED PLACEHOLDER — not real statute text, do not cite as authoritative]` and adds a system-prompt directive to never cite placeholder text as legal basis. This preserves the ability to demonstrate the RAG pipeline while the real corpus is under ingestion (see issue #6).

---

## 15. Security

### 15.1 API authentication

- Optional API key via `X-API-Key` header [`main.py:70`].
- Env var `API_KEY` (default empty; empty disables auth for local dev) [`config.py:95`].
- Comparison via `hmac.compare_digest` — constant-time [`main.py:75`].
- Applied globally via FastAPI `Depends(_verify_api_key)` [`main.py:97`].

### 15.2 CORS

- `ALLOWED_ORIGINS` env var, comma-separated [`config.py:86`].
- Methods: GET, POST, DELETE. Headers: Content-Type, X-API-Key. Credentials allowed.

### 15.3 Input validation

- URL scheme allowlist at schema layer [`schemas.py:177, 204, 322, 367`] — rejects `javascript:`, `data:`, `vbscript:`, and any non-`http`/`https` scheme. Applied on:
  - `AnalyzeRequest.source_url`
  - `AnalyzeUrlRequest.url`
  - `WatchlistCreateRequest.source_url`
  - `BatchItem.url`
- Cross-endpoint parity guarded by `test_regressions_pr34.py` Category C [LIB-TEST].
- ReDoS canary on `inference.py` — synthetic pathological input must complete under budget [LIB-TEST Category E].

### 15.4 SSRF guards

`_validate_url` [`ingest.py:155`]:

- Rejects non-`http`/`https` schemes.
- Resolves hostname to IP; rejects if in `_BLOCKED_NETWORKS`:
  - IPv4: 127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16.
  - IPv6: ::1/128, fc00::/7, fe80::/10.
- Applied on initial fetch and on **every redirect** [`ingest.py:206`].

### 15.5 File upload limits

- Size: `max_upload_bytes` default 10 * 1024 * 1024 = 10MB [`config.py:85`].
- Streaming read with running-total check aborts at 65,536-byte chunk if exceeded (HTTP 413) [`main.py:359`].
- PDF page cap: `MAX_PDF_PAGES=100` [`config.py:97`].
- Text: `MAX_INPUT_CHARS=20000`; over-length is silently truncated [`analyzer.py:143`].

### 15.6 Response redaction

- `GET /analyses/{id}` strips `document_text` from the response payload [`main.py:537`] — public detail endpoint does not return raw document.
- `GET /snapshots` (list) omits `raw_text`; `GET /snapshots/detail/{id}` includes it [LIB-API].

### 15.7 PDF export escaping

- User-supplied content (name, category, excerpt, explanation, legal_basis, jurisdictions) run through `xml.sax.saxutils.escape` [`main.py:14`] before embedding in ReportLab paragraphs.
- Long excerpts truncated to 500 chars + "…" [`main.py:780`].

### 15.8 Local-only guarantee

- All processing occurs on the local machine [.claude/CLAUDE.md §Hard Requirements].
- No external API calls anywhere in the codebase. Verified: `httpx` calls target `LOCALAI_BASE_URL` (LocalAI, local by default) and user-supplied policy URLs (with SSRF guards).
- Legal corpus stored on-disk in `data/legal_corpus/`.
- SQLite database on-disk.

---

## 16. Configuration

### 16.1 Environment variables

Verified against `src/backend/app/config.py` and `.env.example`.

| Variable | Default | Purpose | Valid range |
|---|---|---|---|
| `LOCALAI_BASE_URL` | `http://localhost:8080/v1` | LocalAI endpoint | HTTP URL |
| `MODEL_WORLD` | `apertus-8b-instruct` | Multilingual/world model | Free-form model name |
| `MODEL_EU` | `eurollm-22b-instruct` | EU legal model | Free-form model name |
| `EU_LANGUAGE_CODES` | `bg,cs,da,de,el,en,es,et,fi,fr,ga,hr,hu,it,lt,lv,mt,nl,pl,pt,ro,sk,sl,sv` | ISO 639-1 codes routing to EuroLLM | Comma-separated codes |
| `LANGUAGE_DETECTION_ENABLED` | `true` | Toggle language routing | boolean |
| `RRF_K` | `60` | Reciprocal Rank Fusion constant | int ≥ 1 |
| `LEGAL_CORPUS_DIR` | `data/legal_corpus` | Corpus source dir | filesystem path |
| `LEGAL_KB_INDEX_PATH` | `data/legal_kb.npy` | Numpy index file | filesystem path |
| `LEGAL_KB_METADATA_PATH` | `data/legal_kb_metadata.json` | Chunk metadata | filesystem path |
| `LEGAL_KB_TOP_K` | `5` | Retrieval top-k | int ≥ 1 |
| `DATABASE_URL` | `sqlite:///{data_dir}/terms_analysis.db` | SQLite URL | SQLAlchemy URL |
| `REVIEW_THRESHOLD` | `0.80` | HITL confidence gate | float [0, 1] |
| `LM_REQUEST_TIMEOUT_S` | `60` | LocalAI request timeout (seconds) | float > 0 |
| `MAX_INPUT_CHARS` | `20000` | Max document text length | int ≥ 1 |
| `MAX_UPLOAD_BYTES` | `10485760` (10 MB) | Max file/HTTP size | int ≥ 1 |
| `MAX_PDF_PAGES` | `100` | PDF page cap for OCR | int ≥ 1 |
| `ALLOWED_ORIGINS` | `http://localhost:8000,http://127.0.0.1:8000` | CORS origins | Comma-separated URLs |
| `WATCHLIST_REFRESH_SECONDS` | `0` | Background refresh interval; 0 = off | int ≥ 0 |
| `API_KEY` | *(empty)* | Endpoint auth key; empty = disabled | string |
| `TERMS_ANALYSIS_DATA_DIR` | `{repo}/data` | Override data dir | filesystem path |

### 16.2 Feature flags

- `STREAMLIT_UI=v2` (default) or `v1` — Streamlit UI variant [`run.sh:24`].
- `LANGUAGE_DETECTION_ENABLED=true` — language routing on/off [`config.py:44`].
- `WATCHLIST_REFRESH_SECONDS=0` — background watchlist loop off by default [`config.py:92`].

---

## 17. Deployment and Operations

### 17.1 `run.sh` orchestration

Three-service supervisor (§2.3). Steps:

1. Load `.env` file if present [`run.sh:10`].
2. Validate `STREAMLIT_UI` value and pick entry point [`run.sh:24`].
3. Bootstrap venv at `src/backend/.venv` if missing.
4. Install `src/backend/requirements.txt`.
5. Export `LOCALAI_BASE_URL`, `MODEL_WORLD`, `MODEL_EU`, `ALLOWED_ORIGINS`, `API_BASE_URL`.
6. Launch backend (`uvicorn` on `BACKEND_PORT`, default 9000).
7. Launch fallback UI (`python -m http.server` on `PORT`, default 8000, in `src/webapp/`).
8. Launch primary UI (`streamlit run` on `STREAMLIT_PORT`, default 8501).
9. Register `trap cleanup EXIT` — SIGTERMs all three PIDs.
10. `wait -n` on all three PIDs — script stays alive until any exits.

### 17.2 Venv bootstrap

Backend venv only. Streamlit runs from the same backend venv (§2.3 launch commands use `$VENV_PATH/bin/python`).

### 17.3 Trap-cleanup

`cleanup()` function [`run.sh:99`] SIGTERMs each of `BACKEND_PID`, `FALLBACK_PID`, `STREAMLIT_PID` if set. `trap cleanup EXIT` ensures it fires on script exit whether from Ctrl+C or SIGTERM.

### 17.4 Logging

Structured logging via Python `logging` with the `uvicorn.error` logger [`main.py:59`; `localai.py:11`; `inference.py:33`]. Log-line format follows uvicorn defaults; no JSON structured log format is configured. **OPEN QUESTION:** BRD/PRD do not specify a structured logging contract; is one required?

### 17.5 Health checks

`GET /health` [`main.py:108`] returns `{"status": "ok"}`. No dependency-checking (LocalAI, DB) built into the health endpoint.

**OPEN QUESTION [surfaced §6.3.1]:** LIB-API §Endpoint Map documents a richer `/health` response including `model_world`, `model_eu`, `review_threshold`. Reconcile.

### 17.6 Background watchlist loop

`_watchlist_loop_async` [`main.py:113`] runs as an asyncio task, re-fetches all watchlist items with `source_url` every `WATCHLIST_REFRESH_SECONDS`. Disabled by default (interval=0). Cancelled on lifespan shutdown [`main.py:82-89`].

---

## 18. Testing Strategy

### 18.1 Suite structure

702 tests, 98.06% line coverage on `src/backend/` [.claude/CLAUDE.md §Session outcomes; LIB-TEST §Current baseline].

Test files at `src/backend/tests/`:

- `test_all.py` — broadest: API endpoints, SSRF, schema/config boundaries.
- `test_rules.py` — rule pattern detection, confidence formula, jurisdiction filtering.
- `test_enhancements.py` — rubric scoring, completeness/action-readiness.
- `test_ingest.py` — HTML/RTF extraction, SSRF-redirect regressions.
- `test_legal_kb.py` — chunking, embedding, jurisdiction filtering, graceful degradation.
- `test_llm_failure.py` — LLM offline/timeout/JSON-invalid fallbacks.
- `test_prompts.py` — legal_context placeholder warnings.
- `test_snapshots_and_diffs.py` — snapshot + diff + policy-watch CRUD.
- `test_analyzer.py` — orchestration, hybrid merge, IRP scoring, domain grouping.
- `test_context.py` — chip weights, `resolve_context`, `apply_category_weights`, verdict copy.
- `test_inference.py` — TLD/text detection, `@lru_cache`, ReDoS canary.
- `test_irp.py` — IRP formula, seeded defaults, hybrid safeguard-max merge.
- `test_main_endpoints.py` — per-endpoint validation, allowlist enforcement, `/infer`.
- `test_database_and_main_coverage.py` — branch coverage-fill.
- `test_regressions_pr34.py` — 30 categorical regression tests (§18.3).
- `test_services.py` — service-layer wiring.
- `test_validation.py` — hallucination guard, citation checker.

### 18.2 3-rule testing policy [`.claude/rules/testing.md`]

**Rule 1 — Schema-to-handler allowlist parity.** Any handler-level allowlist that validates against a Pydantic `Literal` must be derived via `typing.get_args()`. Tests assert equality between the handler allowlist and `get_args(Literal)`. Reference: `_VALID_CHIPS = frozenset(get_args(ContextChip))` [`main.py:66`].

**Rule 2 — Cross-endpoint field parity.** When a field is validated on `/analyze`, it must be validated the same way on `/analyze/url`, `/analyze/file`, `/analyze/batch`. Parity test iterates every Literal value and POSTs to every sibling endpoint.

**Rule 3 — Runtime enumeration over Literal values.** Tests use `typing.get_args()` to iterate Literal values, not hardcoded lists.

### 18.3 Regression test file [`test_regressions_pr34.py`]

30 tests, backfilled after PR #34, grouped by category letter [LIB-TEST §Categorical regression coverage]:

- **A. Cross-endpoint field consistency** — Rule 2 in practice.
- **B. Schema-Literal allowlist parity guards** — Rule 1 in practice.
- **C. URL-scheme XSS defense-in-depth** — rejects `javascript:`, `data:`, `vbscript:`.
- **D. Malformed / oversized / unicode inputs** — empty bodies, oversize text, control chars.
- **E. ReDoS canary on `inference.py`**.
- **F. Domain-grouping edge cases** — unknown categories default, empty `top_by_domain` renders.
- **G. Sort stability** — `apply_category_weights` deterministic.

### 18.4 CI

Not explicitly documented in `.claude/CLAUDE.md`. Session handoff references CI green cleanup in `b5ea947` commit. **OPEN QUESTION:** where does CI run, and against what gates? `.github/workflows/` was not inventoried in this pass.

Coverage gate: 98% baseline. Line coverage ≥ 85% target, branch ≥ 75% [`.claude/rules/testing.md §Quality Gates`].

### 18.5 Test conventions

- `pytest-asyncio` **not installed**. Async functions under test called via `asyncio.run(...)` from regular test functions. Adding `@pytest.mark.asyncio` silently skips the test [LIB-STACK §Test Dependencies; LIB-TEST §Conventions].
- `respx` **not installed**. Mock `httpx` via `httpx.MockTransport` patched into `httpx.AsyncClient.__init__` with `monkeypatch`. Pattern in `test_ingest.py::_patch_transport()`.
- Mock `LocalAIClient` with `unittest.mock` or hand-written fakes — never call a real LocalAI endpoint.
- In-memory SQLite (`sqlite:///:memory:`) for DB isolation.
- Endpoint tests override `get_db` via `app.dependency_overrides`.

### 18.6 Frontend testing gap

No automated coverage for `src/webapp/app_streamlit_v2.py` or `src/webapp/app_streamlit_legacy.py` [LIB-TEST §Known Remaining Gap]. Tracked as issue #30 — an intentional scoped backlog item, not an oversight.

`/webapp-testing` skill provides manual Playwright verification but is not part of the automated regression suite.

### 18.7 Evaluation

`src/backend/evaluation/` contains `evaluate.py` and `evaluate_dataset.py` [LIB-EVAL §Evaluation Scripts]:

- `evaluate.py` — rule engine against gold dataset; per-category TP/FP/FN; precision/recall/F1; macro-average F1.
- `evaluate_dataset.py` — extended with LLM; Cohen's Kappa; custom gold dataset path.

Quality targets [LIB-EVAL §Quality Targets]:

| Metric | Target |
|---|---|
| Macro F1 (rules only) | ≥ 0.70 |
| Per-category F1 | ≥ 0.60 |
| Cohen's Kappa | ≥ 0.65 |
| Validation confidence | ≥ 0.80 |
| False positive rate | ≤ 15% |

Gold dataset format: `{"text", "jurisdictions", "expected_categories"}` [LIB-EVAL §Gold Dataset Format].

---

## 19. Rollout and Migration

### 19.1 Streamlit UI rollout

- `STREAMLIT_UI=v2` is the default in `run.sh` [`run.sh:24`; .claude/CLAUDE.md §Session outcomes].
- `app_streamlit_legacy.py` retained as rollback path (`STREAMLIT_UI=v1`).
- No user-facing migration required — deployment change only.

### 19.2 Backwards compatibility

- `Finding.irp_score` optional (defaults to `None`) — legacy findings without IRP fall back to severity-weight for `calculate_risk_score` [`analyzer.py:414`; `context.py:_severity_fallback`].
- `Finding.impact / likelihood / safeguard_score` carry defaults (2 / 3 / 0) — legacy stored findings without these fields still deserialize.
- `AnalysisPayload` new fields (context, verdict_headline, verdict_label, top_by_domain, action_items, action_readiness, completeness, jurisdictions) all carry defaults or are optional — legacy `result_json` blobs still deserialize.

### 19.3 Schema drift guard

Import-time drift guards at:
- `services/context.py:121` — `CATEGORY_WEIGHTS` keys vs `schemas.CATEGORIES`.
- `services/analyzer.py:102` — `_DOMAIN_MAP` keys vs `schemas.CATEGORIES`.
- `main.py:66` — `_VALID_CHIPS` = `frozenset(get_args(ContextChip))`.
- `main.py:67` — `_VALID_JURISDICTIONS` = `frozenset(get_args(Jurisdiction))`.

Adding a category to `rules.py` requires adding it to `schemas.CATEGORIES` and, if applicable, `_DOMAIN_MAP`, `_CATEGORY_IRP_DEFAULTS`, `CATEGORY_WEIGHTS` — otherwise the backend refuses to start [LIB-RULES §Category taxonomy].

### 19.4 Global-tool jurisdiction migration

Default US-CA + GDPR fallback was removed in PR #34 [.claude/CLAUDE.md §Session outcomes]. This is a **breaking change** for any client that relied on the old default — clients must now explicitly pass jurisdictions or accept "no filter" behavior. The `/analyze/file` multipart endpoint retains the legacy substitution [`main.py:395`] — **OPEN QUESTION** whether to reconcile (§3.2.1).

---

## 20. Open Questions

Consolidated from inline `**OPEN QUESTION:**` markers, grouped by section. Each item is tagged with a proposed resolution path.

### 20.1 API contract

- **§6.3.1 `/health` response shape.** Shipped returns minimal `{"status":"ok"}`; LIB-API documents richer shape. Resolution: update LIB-API OR expand `/health` handler.
- **§6.3.3 `/analyses` query parameters.** PRD names `skip`, `sort`, `order`, `filter_grade`, `filter_review_required`; shipped only supports `limit`. Resolution: implement or update PRD to defer.
- **§6.4 Rate limits.** Not specified in BRD/PRD; not implemented. Resolution: escalate — is this required for MVP?
- **§17.5 `/health` LocalAI + DB dependency checks.** Not implemented. Resolution: escalate.

### 20.2 Feature gaps vs PRD

- **§3.1.1 URL fetch timeout.** PRD 30s vs shipped 60s. Resolution: update PRD or reduce timeout.
- **§3.1.1 JavaScript-rendered content.** PRD promises support; shipped ingestion is httpx-only. Resolution: update PRD to remove OR add headless browser support.
- **§3.1.2 `python-magic` content-sniffing.** PRD requires it; shipped uses header-based typing. Resolution: add python-magic or update PRD.
- **§3.1.3 Text paste limit.** PRD 50,000 chars vs shipped 20,000. Resolution: reconcile.
- **§3.2.1 `/analyze/file` legacy default `["US-CA", "GDPR"]`.** Contradicts global-tool contract. Resolution: align with contract by removing default.
- **§3.3.4 Review `edit` action.** PRD names it; shipped `ReviewUpdate` only supports approve/reject. Resolution: implement or update PRD to defer.
- **§3.4.2 Findings filter UI (category/severity/confidence).** Not shipped in Streamlit v2. Resolution: confirm deferred, replaced, or removed.
- **§3.4.3 Verify view annotations.** Not shipped. Resolution: confirm deferred.
- **§3.5.2 JSON export `schema_version`.** Missing from response. Resolution: add.
- **§3.5.3 CSV `?detailed=true`.** Not implemented. Resolution: implement or update PRD.
- **§3.5.3 CSV findings-count columns.** Not implemented. Resolution: implement or update PRD.
- **§3.6 Watchlist hard-coded jurisdictions in refresh.** Contradicts global-tool contract [`main.py:976`]. Resolution: align with contract.
- **§3.6 Watchlist email notifications.** Not shipped. Resolution: confirm deferred.
- **§3.7 F7 Vendor comparison.** Not shipped. Resolution: confirm deferred.
- **§4.5 Automated accessibility tests.** Not present. Resolution: add axe-core / pa11y OR document as review-based only.

### 20.3 Divergence from PRD documented in this spec

- **§3.4.1 Grade set.** PRD says A–F; shipped A / A- / B / B- / C+ / C / D+. Resolution: update PRD.
- **§3.3.1 IRP grade table.** PRD table uses 0–1 scale; shipped uses 0–10. Resolution: update PRD.
- **§5.1.5 `AnalysisPayload` new fields.** 8 fields not in PRD API contract. Resolution: update PRD.
- **§5.1.3 `mode` field (`full`/`quick`).** Not in PRD. Resolution: update PRD.
- **§10.3 Unmapped-category default in `_group_by_domain`.** Silent skip; may warrant a bucket. Resolution: escalate — should there be an "Other" bucket?
- **§13.4 `PolicySnapshot.raw_text` unbounded.** Resolution: escalate — cap needed?

### 20.4 Internationalization

- **§4.6 English-only system prompt.** BRD promises 1,000+ language analysis; shipped prompt is English. Resolution: escalate — do we translate prompts, or does the LLM handle multilingual instruction-following?
- **§4.7 "$2K LLM API (fallback)" in BRD Cost Structure.** Contradicts hard requirement "no external API calls". Resolution: update BRD.

### 20.5 Rule engine

- **§8.5 ~14 categories without explicit IRP defaults.** Fall through to `_IRP_DEFAULT = (2, 3)`. Resolution: audit and add explicit defaults, or accept default.

### 20.6 UI

- **§12.2 JS SPA parity spec.** Resolved 2026-07-03: SPA retired in Phase 4 of the issue #19 remediation; Streamlit v2 is sole UI; `app_streamlit_legacy.py` retained as v1 rollback via `STREAMLIT_UI=v1`.

### 20.7 Operations

- **§17.4 Structured logging.** Not present. Resolution: escalate — is JSON logging required for production?
- **§18.4 CI configuration.** Not inventoried. Resolution: audit `.github/workflows/` and document.

---

## Appendix A: Glossary

| Term | Definition | Anchor |
|---|---|---|
| **IRP** | Impact-Risk-Protection composite score, `0.5*(impact/5) + 0.4*(likelihood/5) - 0.3*(safeguard/5)`, clamped [0, 1] | [LIB-RULES §IRP; `analyzer.py:136`] |
| **Impact** | Harm if clause enforced, 1–5 scale (1=trivial, 5=catastrophic) | [`schemas.py:161`] |
| **Likelihood** | Probability clause activates, 1–5 (1=rare, 5=automatic) | [`schemas.py:162`] |
| **Safeguard score** | Existing mitigations offsetting risk, 0–5 (0=none, 5=full) | [`schemas.py:163`] |
| **Confidence** | Certainty in a finding, 0–1 | [PRD §F3.4] |
| **Finding** | A detected risky clause in a policy | [`schemas.py:151`] |
| **Category** | One of ~52 canonical strings identifying finding type | [`schemas.py:50` `CATEGORIES`] |
| **Severity** | Low / Medium / High / Critical | [`schemas.py:40`] |
| **Excerpt** | Short quote from policy as evidence for a finding | [PRD §F3.3] |
| **Evidence binding** | Linking findings to specific text with line numbers | [PRD §F3.3] |
| **Review queue** | Findings with confidence < 0.80 needing human review | [PRD §F3.4] |
| **Watchlist** | Vendor policies monitored for changes over time | [PRD §F6] |
| **Verify view** | Split-pane view showing document with highlights | [PRD §F4.3] |
| **LLM** | Large Language Model — Apertus 8B or EuroLLM 22B | [BRD §Technology Stack] |
| **LocalAI** | Local inference server (Apache 2.0, https://localai.io) | [PRD §Appendix D] |
| **HITL** | Human-in-the-loop review | [PRD §Appendix D] |
| **Global-tool contract** | Empty `jurisdictions=[]` = "no filter"; no default fallback | [LIB-RULES §Global-tool contract] |
| **Context chip** | Reader intent selector, one of 5 values | [LIB-CONTEXT] |
| **Domain** | One of 4 UI groupings: Data, Data use, Terms of use, Privacy rights | [`analyzer.py:96`] |
| **Action readiness** | Go / Review / Stop verdict | [`analyzer.py:185`] |
| **Completeness** | Fraction of expected policy sections detected, 0–1 | [`analyzer.py:177`] |
| **Verdict headline** | Context-aware verdict sentence for the reader | [LIB-VOICE §Verdict labels] |
| **Verdict label** | Short actionable verdict chip label | [LIB-VOICE §Verdict labels] |
| **Scope box** | Always-visible "what was / wasn't checked" block on results | [LIB-VOICE §Scope-honesty gap] |
| **RRF** | Reciprocal Rank Fusion, k=60 | [`config.py:50`; LIB-LEGAL §RAG Architecture] |
| **Legal KB** | Retrieval-augmented statute passages injected into LLM prompt | [LIB-LEGAL §RAG Architecture] |
| **SSRF** | Server-Side Request Forgery — blocked network ranges in ingest.py | [§15.4] |
| **ReDoS** | Regular expression Denial of Service — canary test in inference.py | [LIB-TEST Category E] |

---

## Appendix B: Traceability Matrix

Selected mappings between BRD/PRD requirements, spec sections, and code locations. Non-exhaustive — full matrix maintained separately.

| Requirement | BRD | PRD | Spec | Code |
|---|---|---|---|---|
| Multi-format ingestion (URL, PDF, DOCX, RTF, HTML, TXT) | §Executive Summary | §F1 | §3.1 | `src/backend/app/services/ingest.py` |
| Severity-weighted risk scoring | §Risk Scoring Methodology | §F3.1 (shipped) | §3.3.1, §9.1 | `src/backend/app/services/analyzer.py:414` |
| IRP scoring (Impact/Likelihood/Safeguards) | §Risk Scoring Methodology (planned) | §F3.1 (planned) | §3.3.1, §9.1 (shipped post-PR#34) | `analyzer.py:136`, `rules.py:943` |
| 30-jurisdiction coverage | §Jurisdiction Support | §F2.1 | §3.2.1, §5.5 | `schemas.py:8` |
| Multilingual analysis | §Multilingual expansion | §MVP Scope | §2.4, §4.6, §7.2 | `localai.py:39` |
| Local LLM inference (LocalAI) | §Core Value Propositions §1 | §LLM Integration Specification | §2.4, §7.1 | `localai.py`, `config.py:27` |
| AI Law analysis (EU AI Act, CoE CETS 225, OECD-AI, UNESCO-AI, US-CO) | §Technical Differentiation | §F8 | §3.8, §5.5 | `rules.py`, `schemas.py:35` |
| PDF export | §Executive Summary | §F5.1 | §3.5.1 | `main.py:574` |
| JSON export | §Core Value Propositions | §F5.2 | §3.5.2 | `main.py:848` |
| CSV export (bulk) | §Executive Summary | §F5.3 | §3.5.3 | `main.py:541` |
| Watchlist monitoring | §Technical Differentiation | §F6 | §3.6 | `main.py:891-1007` |
| Vendor comparison | §Technical Differentiation | §F7 | §3.7 (deferred) | Not shipped |
| Confidence < 0.80 → HITL review | §Business Case §Contingency | §F3.4 | §7.8 | `config.py:81`, `analyzer.py:567` |
| Plain-language explanations | §Core Value Propositions | §F4.4 | §3.4.4 | `schemas.py:156`, `rules.py::RulePattern.explanation` |
| Evidence binding with line numbers | §Executive Summary | §F3.3 | §3.3.3, §5.1.1 | `schemas.py:141`, `rules.py:1035` |
| Verify view | §Core Value Propositions | §F4.3 | §3.4.3 | Streamlit expander |
| Two-voice UI (intake warm, results observational) | — [LIB-VOICE only] | — | §11.4 | `context.py`, `app_streamlit_v2.py` |
| No em-dashes in tool voice | — [LIB-VOICE only] | — | §11.4 | Enforced by review |
| Scope box always visible | — [LIB-VOICE, LIB-PRINCIPLES] | — | §11.3, §11.5 | `app_streamlit_v2.py:762` |
| WCAG 2.2 AA | §Executive Summary | §Accessibility Requirements | §4.5 | — [review-based] |
| Multi-format PDF/DOCX/RTF/HTML/TXT | §Executive Summary | §F1.2 | §3.1.2 | `ingest.py:127` |
| Batch analysis | — | §Additional shipped endpoints | §6.3.2 | `main.py:432` |
| Snapshots + diff | — | §Additional shipped endpoints | §6.3.7 | `main.py:1015-1165` |
| Policy watch (recurring) | §Core Value Propositions | §Additional shipped endpoints | §6.3.8 | `main.py:1168-1284` |
| Rubric scoring | — [LIB-EVAL only] | — | §18.7 | `main.py:206`, `evaluation/evaluate.py` |
| Intake inference (`/infer`) | — | — [not documented] | §7.9 | `main.py:255`, `inference.py` |
| Context chips | — | — [not documented] | §5.4 | `context.py`, `app_streamlit_v2.py:34` |
| Domain grouping | — | — [not documented] | §10 | `analyzer.py:37, 110` |
| Verdict headline + label | — | — [not documented] | §9.6 | `context.py:79, 109` |
| Action items | — | — [not documented] | §11.3 | `analyzer.py:275` |
| Hard scope limits (hardware, real-world divergence) | — [LIB-PRINCIPLES] | — | §1.4, §10.4, §11.3 | `app_streamlit_v2.py:762` (scope box) |

Rows without a BRD or PRD anchor are flagged for follow-up: either (a) update BRD/PRD to name the requirement, or (b) treat as intentional undocumented internal design.

---

## Appendix C: References

Primary anchor documents (all paths relative to repo root):

| Doc | Path | Version / Date |
|---|---|---|
| Business Requirements | `docs/BRD_Terms_Policies_Reviewer.md` | 1.0 — 2026-02-13 |
| Product Requirements | `docs/PRD_Terms_Policies_Reviewer.md` | 2.0 — 2026-06-27 |
| Brand personality | `PRODUCT.md` | — |
| Project identity | `.claude/CLAUDE.md` | Post-PR #34, 2026-07-03 |
| Governance principles | `.claude/library/LIB-PRINCIPLES.md` | 2026-07-03 |
| Architecture reference | `.claude/library/LIB-ARCH.md` | Post-PR #34 |
| Stack reference | `.claude/library/LIB-STACK.md` | Post-PR #34 |
| Legal AI reference | `.claude/library/LIB-LEGAL.md` | Post-PR #34 |
| Test coverage reference | `.claude/library/LIB-TEST.md` | Post-PR #34 |
| API reference | `.claude/library/LIB-API.md` | 2026-07-03 |
| Rule engine reference | `.claude/library/LIB-RULES.md` | 2026-07-03 |
| Evaluation reference | `.claude/library/LIB-EVAL.md` | 2026-07-03 |
| Context chip reference | `.claude/library/LIB-CONTEXT.md` | 2026-07-03 |
| Voice reference | `.claude/library/LIB-VOICE.md` | 2026-07-03 |
| Code style rules | `.claude/rules/code-style.md` | — |
| Testing rules | `.claude/rules/testing.md` | Post-PR #34 |
| Session handoff | `SESSION_HANDOFF_2026-07-03_ISSUE_19_REDESIGN.md` | 2026-07-03 |

Source code (all under repo root):

- Backend: `src/backend/app/` (main.py, config.py, database.py, models.py, schemas.py, services/*)
- Frontend: `src/webapp/` (app_streamlit_v2.py, app_streamlit_legacy.py)
- Tests: `src/backend/tests/` (18 test modules)
- Evaluation: `src/backend/evaluation/`
- Legal corpus: `data/legal_corpus/` (canada, eu, us-ca, us-co, us-ct, us-ny subdirectories)
- Deployment: `run.sh`, `.env.example`, `src/backend/requirements.txt`
