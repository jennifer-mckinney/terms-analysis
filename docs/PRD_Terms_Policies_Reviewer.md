# Product Requirements Document: AI Terms & Policies Reviewer

**Version:** 2.4
**Date:** 2026-07-03
**Status:** Draft for Development
**Product Manager:** [Name]
**Engineering Lead:** [Name]
**Related Documents:** BRD_Terms_Policies_Reviewer.md, PRODUCT.md, `.claude/library/LIB-CONTEXT.md`, `.claude/library/LIB-VOICE.md`, `.claude/library/LIB-RULES.md`, `.claude/library/LIB-PRINCIPLES.md`

## Change History

| Version | Date | Summary |
|---------|------|---------|
| 2.4 | 2026-07-03 | OE-003 landed — `PolicyWatch` merged into `WatchlistItem`. §7.3.9 (`POST /watchlist`) and §5.6.1 (F6.1) codify the merged model: subject is `vendor` + `source_url` (not `analysis_id`), with optional `check_frequency` (per-item seconds, 300-604800 range), `enabled` (boolean, LE-010 fix — previously stored as the string `"true"` on `PolicyWatch`), `user_id`, and `notes`. `check_frequency` is now honored by `_watchlist_loop_async` (previously written to `PolicyWatch.check_frequency` and silently ignored — a user setting `check_frequency=3600` believed hourly refreshes were happening; they were not). Response payload exposes computed `next_check_at = last_checked + check_frequency`. §5.6.2 F6.2 updated: per-item cadence replaces the prior "global server setting" wording. Legacy `/policy-watch/*` endpoints return `308 Permanent Redirect` to `/watchlist/*` (root, list, delete) with `Deprecation: true` + `Sunset: 2026-10-01` headers; `/policy-watch/{id}/snapshot` returns `410 Gone` (cannot be redirected because the id lookup no longer resolves). Data migration script at `src/backend/scripts/migrate_policywatch_to_watchlist.py` folds existing `policy_watches` rows into `watchlist_items` idempotently. Database schema section rewritten: `policy_watches` table removed; `watchlist_items` extended with the 4 merged columns. |
| 2.3 | 2026-07-03 | Flow 2 codified as API-only for MVP. UI-bound acceptance criteria (nav surface, CSV upload widget, progress bar, sortable results table, "Export All as CSV" button) removed from §6.2. OPEN QUESTION at §6.2 resolved: batch UI is a P2 follow-up tracked separately. Added JSON `POST /analyze/batch` payload example in §6.2 so researchers can `curl` the endpoint directly. §7.3.13 endpoint spec annotated with API-only status and pointer to optional CSV helper at `src/backend/scripts/batch_analyze.py`. Rationale: synchronous endpoint cannot survive a real 50-URL run behind HTTP proxies without an async job model, which is a multi-day architecture change, not a UI wire-up. |
| 2.2 | 2026-07-03 | Tech-spec audit remediation follow-up. Resolved three v2.1 `OPEN QUESTION` markers: (a) URL fetch timeout separated from LLM inference timeout — new dedicated `LM_URL_FETCH_TIMEOUT_S` env var (default 30 seconds), distinct from `LM_REQUEST_TIMEOUT_S` (60 seconds) which now governs LLM inference only (§F1.1, §Additional shipped endpoints); (b) text paste cap set to `MAX_INPUT_CHARS = 50000` with paste-time whitespace normalization (strip leading/trailing, collapse internal runs) applied before the length check (§F1.3); (c) Flow 2 batch UI question remains open pending research (§Flow 2 marked `[BLOCKED ON RESEARCH]`). Category taxonomy expanded to codify LE-013 alignment: added canonical shipped category list (~50 labels) with explicit call-out of the seven boost-only labels (`Arbitration / Dispute`, `Third-Party Sharing`, `Sub-processors`, `Data Transfer`, `Intellectual Property`, `Transparency`, `In-App Purchases`) that must be present in both `schemas.CATEGORIES` and the boost dicts (§F3.2). |
| 2.1 | 2026-07-03 | Reconciliation refresh triggered by `docs/reports/tech-spec-audit.md`. IRP scoring reclassified from "planned enhancement" to shipped (§F3.1, §F4.1, §MVP Acceptance, Appendix D) with real 0-10-scale grade thresholds (A / A- / B / B- / C+ / C / D+) sourced from `analyzer.py::_grade`. Context chip taxonomy, 4-domain grouping, Streamlit v2, `/infer`, and schema-derived allowlists documented as shipped (PR #34, commits `e4fd706` -> `b5ea947`). AnalysisPayload API contract (§API Endpoints Specification) extended with the 8 v2 fields: `action_readiness`, `completeness`, `context`, `jurisdictions`, `verdict_headline`, `verdict_label`, `top_by_domain`, `action_items`. Personal path removed from header. |
| 2.0 | 2026-06-27 | AI Law Analysis (F8), expanded jurisdiction coverage (30 codes), multilingual analysis (1,000+ languages), LocalAI inference stack. |

---

## Document Purpose

This PRD translates the business goals outlined in the BRD into detailed product specifications, feature requirements, user flows, and technical implementation details. While the BRD answers "why" and "what's the business case," this PRD answers "what exactly are we building" and "how will it work."

**Key Difference from BRD:**
- **BRD:** Problem statement, market analysis, business model, financial projections
- **PRD:** Feature specifications, user personas, user flows, UI/UX requirements, technical architecture, acceptance criteria

---

## Executive Summary

### Product Vision

Build a privacy-first web application that empowers individuals and small organizations to analyze Terms of Service and Privacy Policies through automated AI analysis, identifying high-risk clauses, mapping regulatory compliance, and providing actionable insights—all while keeping user data local and private.

### Success Metrics (from BRD)

- 1,000 active users within 12 months
- 90%+ clause detection accuracy (precision/recall)
- <30 second average analysis time
- NPS ≥40
- <5% monthly churn

### MVP Scope (Phase 1 - Months 1-3)

**In Scope:**
- Multi-format document ingestion (URL, file upload, text paste)
- IRP (Impact / Likelihood / Safeguards) risk scoring across ~50 risk categories, shipped in PR #34 (see §F3.1 for formula and grade thresholds)
- Multi-jurisdiction support (30 codes: US federal/state, EU/UK, Canada, Latin America, Africa, Asia-Pacific, AI-law frameworks)
- Basic results view with findings breakdown
- PDF export
- Local LLM inference via LocalAI (Apertus 8B world model, EuroLLM 22B EU specialist)
- Multilingual analysis: 1,000+ languages (Apertus), 35 EU languages (EuroLLM)
- AI Law analysis: EU AI Act, US federal/state AI regulations, international AI ethics frameworks

**Out of Scope (Future Phases):**
- Watchlist monitoring and change detection
- Vendor comparison (side-by-side)
- API for third-party integration
- Team accounts and collaboration
- Mobile app

---

## User Personas

### Persona 1: Privacy-Conscious Patricia

**Demographics:**
- Age: 32
- Occupation: Software Engineer
- Tech Literacy: High
- Privacy Awareness: Very high

**Context:**
- Uses VPNs, encrypted messaging, ad blockers
- Reads privacy policies "when she has time"
- Active in r/privacy subreddit
- Has 20+ online accounts

**Goals:**
- Quickly assess if a new service respects privacy
- Understand data sharing and collection practices
- Make informed decisions before signing up
- Share findings with privacy-conscious friends

**Pain Points:**
- Privacy policies are too long and filled with legal jargon
- Can't tell which clauses are actually risky
- No way to compare policies across services
- Existing tools send documents to cloud (trust issue)

**User Journey:**
1. Discovers new AI service she wants to try
2. Opens AI Terms Reviewer tool
3. Pastes privacy policy URL
4. Reviews risk score and key findings
5. Checks data sharing and retention clauses
6. Decides whether to use service
7. Shares analysis with friends on Reddit

**Edge Cases:**
- Privacy policy behind authentication/paywall
- Policy in PDF format (scanned, not text)
- Policy split across multiple pages
- Policy uses non-standard terminology

### Persona 2: Startup Founder Sam

**Demographics:**
- Age: 38
- Occupation: CEO of 15-person startup
- Tech Literacy: Medium-high
- Legal Experience: None

**Context:**
- Bootstrap-funded, no legal counsel
- Uses 40+ SaaS vendors
- Worried about GDPR/CCPA compliance
- Preparing for Series A due diligence

**Goals:**
- Perform vendor due diligence quickly
- Document compliance for investors/auditors
- Identify risky vendor agreements
- Avoid regulatory fines

**Pain Points:**
- Legal review costs $300-500/hour
- Can't afford to review 40+ vendor agreements
- Investors asking about data protection practices
- Unsure which vendors pose compliance risks

**User Journey:**
1. Receives vendor agreement from new SaaS tool
2. Uploads PDF to AI Terms Reviewer
3. Reviews overall risk score (C+ grade)
4. Focuses on data sharing and liability findings
5. Exports PDF report for records
6. Follows up with vendor on concerning clauses
7. Stores analysis in due diligence folder

**Edge Cases:**
- Vendor agreement is DOCX with complex formatting
- Agreement includes multiple annexes
- Non-standard terms unique to vendor's industry
- Agreement references other documents not provided

### Persona 3: Researcher Rachel

**Demographics:**
- Age: 29
- Occupation: PhD Candidate in Law/Technology
- Tech Literacy: Medium
- Research Focus: Platform governance

**Context:**
- Analyzing 100+ platform policies for dissertation
- Needs systematic, comparable methodology
- Publishing findings in academic journals
- Limited budget for analysis tools

**Goals:**
- Analyze large corpus of policies systematically
- Export data for statistical analysis
- Compare policies across platforms and time
- Cite transparent methodology in papers

**Pain Points:**
- Manual analysis is time-consuming and inconsistent
- Existing tools are expensive or proprietary
- Need to show methodology is rigorous and reproducible
- Difficulty tracking policy changes over time

**User Journey:**
1. Compiles list of 100 platform URLs
2. Analyzes each policy via URL input
3. Reviews findings for consistency
4. Exports all analyses as CSV
5. Imports into R for statistical analysis
6. Cites tool methodology in paper
7. Shares analysis corpus with other researchers

**Edge Cases:**
- Platform uses multiple policies (ToS + Privacy + GDPR)
- Policy text retrieved via API or JavaScript rendering
- Historical versions needed (Internet Archive)
- Need to analyze same policy in multiple jurisdictions

### Persona 4: AI Compliance Officer Alex

**Demographics:**
- Age: 41
- Occupation: Chief Privacy & AI Officer, mid-size fintech
- Tech Literacy: High
- Legal Experience: JD + 10 years compliance

**Context:**
- EU AI Act obligations taking effect 2025–2026
- Manages vendor AI risk assessments
- Responsible for documenting GPAI model usage
- Reports to board on AI governance posture

**Goals:**
- Identify vendor AI systems classified as high-risk under EU AI Act
- Flag automated decision-making clauses missing human review rights
- Document AI training data consent for regulatory audit trail
- Ensure Colorado AI Act SB 205 compliance for US operations

**Pain Points:**
- Vendor agreements don't use EU AI Act terminology — hard to map clauses manually
- No tool surfaces AI law findings alongside standard privacy findings
- Need evidence-backed exports for regulatory submissions

---

### Persona 5: Parent Morgan

**Demographics:**
- Age: 38
- Occupation: Teacher
- Tech Literacy: Low-medium
- Primary concern: Children's safety in AI-powered apps

**Context:**
- Children use AI tutoring apps, social platforms, and gaming services
- Worried about AI profiling, recommendation algorithms, and data training use
- Reads very little legal text; relies on plain-language summaries
- Wants a simple yes/no: "Is this app safe for my 10-year-old?"

**Goals:**
- Understand if AI systems are used to profile or target children
- Know if kids' data trains AI models
- Identify COPPA compliance gaps in AI-powered apps
- Decide quickly without legal expertise

**Pain Points:**
- Terms of Service for kids' apps are long and opaque
- AI-specific risks (training data, behavioral profiling) buried in legalese
- No existing tool combines children's privacy + AI law analysis

---

## Implementation Status Note (2026-07-03)

An independent UI/UX validation pass (live Playwright run) found several feature-requirement gaps between this spec and the running app, summarized here rather than annotated inline on every checkbox below. The vanilla-JS SPA fallback was retired in Phase 4 of the issue #19 remediation; Streamlit v2 (`app_streamlit_v2.py`) is now the sole UI. Status notes below reflect the Streamlit-only state:

- **F1.3 (character count, short-text warning)**: **resolved.** Streamlit shows a live character counter with a short-text warning (computed in `app_streamlit_v2.py`).
- **F2.1 (30-code jurisdiction multi-select with flags/Select-All/Clear-All)**: **resolved.** Streamlit exposes all 30 jurisdiction codes with Select-All / Clear-All controls (`st.multiselect`).
- **F3.1/F4.1 (grade/score display)**: **resolved.** `render_grade_summary()` shows grade / risk-score / confidence in Streamlit.
- **F4.3 (Verify View)**: **resolved.** Streamlit has a "View in full document" Verify View expander.
- **F5.1 (PDF export)**: was broken by a backend route-ordering bug (fixed, see issue #16). Streamlit's export exposes both PDF and JSON download paths.
- **Dark mode**: Streamlit follows the OS/browser theme automatically per Streamlit's own theming model, with no in-app toggle; `.streamlit/config.toml` sets the palette.

Given this, the remaining gap between the two UIs (per issue #17/#19) is now narrow: both surface the same core findings, grade, and Verify View.

## Implementation Status Note — v2.1 addendum (2026-07-03)

Landed via PR #34 (`claude/issue-19-plain-language-redesign`) across 4 commits — `e4fd706` (feature) -> `2626e2b` (must-fix) -> `671d3e5` (P1/P2 + audit) -> `b5ea947` (CI green cleanup). 702 tests passing, 98.06% coverage. Cross-reference: `.claude/CLAUDE.md` §Session outcomes (2026-07-03).

- **Streamlit v2 shipped as flagship UI**, gated by `STREAMLIT_UI=v2` in `run.sh` (v2 is the default; `v1` legacy retained as rollback path via `app_streamlit_legacy.py`). File: `src/webapp/app_streamlit_v2.py` (~972 lines). Layout: teal palette, two-view state, tabbed input (link / text / file), 5 multi-select context option cards, hover-triggered contextual help, 4 domain sections rendered from `AnalysisPayload.top_by_domain`, always-visible scope box, dynamic action items from `AnalysisPayload.action_items`.
- **IRP scoring** — see §F3.1.
- **Context chip taxonomy** — 5 chips aligned to BRD segments: `want_understand`, `for_child`, `for_care`, `for_work`, `just_curious`. Weight tier scale: 1.0 baseline, 2.0 boosted, 2.5 priority, 3.0 signature. Multi-select merger sums weights across chips, capped at 3.0. Full weight table and priority order: LIB-CONTEXT.
- **Domain-grouped results** — findings group into 4 fixed domains via `analyzer._group_by_domain`: `Data` (collection), `Data use`, `Terms of use`, `Privacy rights`. Category-to-domain mapping in `analyzer._DOMAIN_MAP` covers ~50 categories. Hardware permissions (camera / mic / contacts / location) are a **scope caveat only, never a domain with findings** — hard scope limit per LIB-PRINCIPLES Principle 4.
- **Global-tool contract** — empty `jurisdictions=[]` treated as "no filter" across rules + LLM post-filter + Streamlit resolution. No US-CA + GDPR default fallback anywhere. Location dropdowns default to blank (`index=None`).
- **Schema-derived allowlists via `typing.get_args()`** — `_VALID_CHIPS` and `_VALID_JURISDICTIONS` in `main.py` derived at module load: `frozenset(get_args(ContextChip))`. `schemas.CATEGORIES` is the canonical frozenset for finding category strings; `context.py` and `analyzer.py` validate their category-keyed dicts against it at import time. Any future drift fails at import, not at CI review.
- **`POST /infer` endpoint shipped** — see §Additional shipped endpoints.
- **Regression coverage** — `test_regressions_pr34.py` (30 tests) covers cross-endpoint consistency via `typing.get_args()` runtime iteration, schema-Literal allowlist parity, XSS defense-in-depth (blocks `javascript:` / `data:` / `vbscript:` scheme URLs), malformed inputs, ReDoS canary on `inference.py`, domain-grouping edges, and sort stability.

## Feature Requirements

### F1: Document Ingestion

**Priority:** P0 (MVP)
**User Story:** As a user, I want to input policy documents in multiple formats so I can analyze any type of document I encounter.

#### F1.1: URL Input

**Acceptance Criteria:**
- [ ] User can paste a URL into input field
- [ ] System validates URL format before submission
- [ ] System fetches HTML content from URL
- [ ] System extracts text content from HTML
- [ ] System handles JavaScript-rendered content
- [ ] System displays loading state during fetch (estimated: 3-10 seconds)
- [ ] System shows error message if URL is invalid or unreachable
- [ ] System displays success confirmation with document preview

**Technical Notes:**
- Use `requests` library with User-Agent header
- Follow redirects (max 5 hops)
- Timeout: URL fetch has a dedicated **30-second** timeout controlled by `LM_URL_FETCH_TIMEOUT_S` env var (default **30 seconds**, `src/backend/app/config.py`, wired into `services/ingest.py`). This is distinct from `LM_REQUEST_TIMEOUT_S` (default **60 seconds**), which governs LLM inference calls only. Separating the two lets a slow origin server fail fast without blocking the longer LLM inference window that legitimate large-policy analyses may need.
- Handle 4xx/5xx errors gracefully
- Extract text with BeautifulSoup4, prioritize `<article>`, `<main>`, `<div class="policy">` containers
- Strip navigation, footer, ads
- Preserve paragraph structure

**Edge Cases:**
- URL requires authentication → Show error: "This document requires authentication. Please copy and paste the text instead."
- URL is behind CAPTCHA → Same as above
- URL redirects to PDF → Automatically switch to PDF processing
- Multiple URLs in field → Use first URL, ignore rest
- URL contains tracking parameters → Strip before display

**UI Mockup Reference:** `docs/wireframes/reviewer_wireframe_v2.png` - Input section

#### F1.2: File Upload

**Acceptance Criteria:**
- [ ] User can drag and drop file or click to browse
- [ ] System accepts: PDF, DOCX, RTF, HTML, TXT files
- [ ] System validates file size against `MAX_UPLOAD_BYTES` (default **10 MB = 10 * 1024 * 1024 bytes**, `src/backend/app/config.py:84-85`)
- [ ] System validates file type by content, not just extension
- [ ] System displays file name and size after selection
- [ ] System shows upload progress indicator
- [ ] System extracts text from uploaded file
- [ ] System handles password-protected files with clear error
- [ ] System handles scanned PDFs with OCR fallback
- [ ] PDF page count capped at `MAX_PDF_PAGES` (default **100 pages**, `MAX_PDF_PAGES` env var)

**Technical Notes:**
- Use `python-magic` for content type validation
- PDF: PyPDF2 + pdfplumber (fallback to OCR if text extraction fails)
- DOCX: python-docx
- RTF: striprtf
- HTML: BeautifulSoup4
- OCR: Tesseract (local only, opt-in)
- Store original filename and upload timestamp

**Edge Cases:**
- Scanned PDF (image-based) → Attempt OCR, warn user accuracy may be lower
- Encrypted/password-protected → Error: "This file is password-protected. Please save as unprotected and try again."
- Corrupt file → Error: "Unable to read file. Please check file integrity."
- File exceeds 10MB → Error: "File too large (max 10MB). Consider pasting text instead."
- Empty file → Error: "File appears to be empty."

**UI Mockup Reference:** `docs/wireframes/reviewer_wireframe_v2.png` - File upload area

#### F1.3: Text Paste

**Acceptance Criteria:**
- [ ] User can paste text directly into textarea
- [ ] Textarea auto-expands to fit content (max height: 400px)
- [ ] System shows character count (live update)
- [ ] System accepts up to `MAX_INPUT_CHARS` characters (default **50,000**, `src/backend/app/config.py`, env-overridable). The `/infer` endpoint separately caps at 200,000 characters (`schemas.py`) because inference is a lighter-weight signal path that does not run the full rule + LLM pipeline.
- [ ] On paste, the system strips leading and trailing whitespace, collapses internal runs of repeated whitespace into a single space, and then applies the `MAX_INPUT_CHARS` length check. This preserves paragraph breaks (double newlines) while preventing accidental whitespace bloat from pushing legitimate paste content over the cap.
- [ ] System preserves paragraph breaks and basic formatting
- [ ] Paste button is disabled if textarea is empty
- [ ] System shows warning if text appears incomplete (e.g., <1000 chars)

**Technical Notes:**
- Use `<textarea>` with `maxlength` matching `MAX_INPUT_CHARS`
- Character counter: `{current}/{max}`
- Normalize line breaks to `\n`
- Trim leading/trailing whitespace
- Preserve internal whitespace structure
- Server-side truncation happens in `analyzer._truncate_text` at `src/backend/app/services/analyzer.py:142-145`

**Edge Cases:**
- Text exceeds `MAX_INPUT_CHARS` → Auto-truncate, show warning
- Text includes HTML tags → Display raw (don't render as HTML)
- Text is very short (<500 chars) → Show warning: "This text appears short. Is this the complete policy?"
- Empty paste → Disable analyze button, show prompt: "Paste policy text here"

**UI Mockup Reference:** `docs/wireframes/reviewer_wireframe_v2.png` - Text input tab

### F2: Analysis Configuration

**Priority:** P0 (MVP)
**User Story:** As a user, I want to specify jurisdictions and document type so the analysis is relevant to my context.

#### F2.1: Jurisdiction Selection

**Acceptance Criteria:**
- [x] User can select one or more jurisdictions via checkboxes
- [x] Default: **empty selection = "no filter"** (global-tool contract shipped in PR #34). No hardcoded US-CA + GDPR fallback. Location dropdowns default to blank (`index=None`).
- [ ] System shows flag icons for visual recognition
- [ ] System displays jurisdiction full name on hover
- [ ] Selection persists across sessions (localStorage)
- [x] "Select All" and "Clear All" quick actions available

**Supported Jurisdictions (30 — matches `Jurisdiction` Literal in `schemas.py`):**

*US Federal & State*
1. **US-FED** — US Federal (COPPA, HIPAA, GLBA, FTC § 5, CAN-SPAM)
2. **US-CA** — California (CCPA/CPRA)
3. **US-TX** — Texas (TDPSA)
4. **US-VA** — Virginia (VCDPA)
5. **US-CO** — Colorado (CPA + AI Act SB 205)
6. **US-CT** — Connecticut (CTDPA)
7. **US-IL** — Illinois (BIPA + AEIA)
8. **US-NY** — New York (SHIELD Act)
9. **US-NJ** — New Jersey (NJDPA)
10. **US-MN** — Minnesota (MCDPA)
11. **US-OR** — Oregon (OCPA)

*International Privacy*
12. **GDPR** — European Union (GDPR)
13. **UK-GDPR** — United Kingdom (UK GDPR + DPA 2018)
14. **LGPD** — Brazil (LGPD)
15. **PIPEDA** — Canada (PIPEDA)
16. **CA-QC** — Quebec (Law 25)
17. **POPIA** — South Africa (POPIA)
18. **PDPA-KE** — Kenya (PDPA 2019)
19. **DPDP** — India (DPDP Act 2023)
20. **APPI** — Japan (APPI)
21. **PIPA** — South Korea (PIPA)
22. **APP** — Australia (Privacy Act / APPs)
23. **PDPA-TH** — Thailand (PDPA)
24. **NDPR** — Nigeria (NDPR)

*International Frameworks*
25. **ICCPR-17** — UN ICCPR Article 17 (173 state parties)
26. **COE-108** — Council of Europe Convention 108+

*AI Law*
27. **EU-AI-ACT** — EU AI Act (Regulation 2024/1689)
28. **COE-AI-225** — Council of Europe CETS 225 (AI Framework Convention)
29. **OECD-AI** — OECD AI Principles (2024, 46+ countries)
30. **UNESCO-AI** — UNESCO Recommendation on Ethics of AI (2021, 193 member states)

**Technical Notes:**
- Store jurisdiction codes: `US-FED`, `US-CA`, `US-TX`, `US-VA`, `US-CO`, `US-CT`, `US-IL`, `US-NY`, `US-NJ`, `US-MN`, `US-OR`, `GDPR`, `UK-GDPR`, `LGPD`, `PIPEDA`, `CA-QC`, `POPIA`, `PDPA-KE`, `DPDP`, `APPI`, `PIPA`, `APP`, `PDPA-TH`, `NDPR`, `ICCPR-17`, `COE-108`, `EU-AI-ACT`, `COE-AI-225`, `OECD-AI`, `UNESCO-AI`
- Analysis filters findings by selected jurisdictions
- Different jurisdictions trigger different rule patterns (all 30 codes have `RulePattern` coverage in `rules.py`)

**Edge Cases:**
- No jurisdiction selected → Analysis runs with **no jurisdiction filter** (returns findings across all rule patterns). This is the intended global-tool contract, not a fallback state. UI may surface a "Rules applied for: all jurisdictions" chip using `AnalysisPayload.jurisdictions` (empty list echoes back).
- All jurisdictions selected → May increase analysis time, show warning

**UI Mockup Reference:** `docs/wireframes/reviewer_wireframe_v2.png` - Configuration panel

#### F2.2: Document Type Selection

**Acceptance Criteria:**
- [ ] User can select document type from dropdown
- [ ] Options: Privacy Policy, Terms of Service, Cookie Policy, Data Processing Agreement, Combined
- [ ] Default: "Privacy Policy"
- [ ] Selection affects risk category emphasis and scoring

**Document Types:**
- **Privacy Policy:** Focus on data collection, sharing, retention, user rights
- **Terms of Service:** Focus on liability, arbitration, user obligations, changes
- **Cookie Policy:** Focus on tracking, consent, third-party cookies
- **Data Processing Agreement (DPA):** Focus on processor obligations, security, sub-processors
- **Combined:** Analyze as Privacy Policy + Terms of Service

**Technical Notes:**
- Document type influences LLM prompts and rule patterns
- Affects which risk categories are prioritized in scoring

#### F2.3: Industry Profile (Optional)

**Acceptance Criteria:**
- [ ] User can optionally select industry profile
- [ ] Options: Retail, Finance, Healthcare, Gaming, Social Media, AI / Tech Platform, Education, General
- [ ] Default: "General" (no industry-specific emphasis)
- [ ] Industry selection highlights relevant compliance requirements

**Industry Profiles:**
- **Healthcare:** HIPAA considerations, PHI handling, BAA requirements
- **Finance:** GLBA, PCI-DSS, financial data protections
- **Education:** FERPA, COPPA (students under 13)
- **Social Media:** Age verification, content moderation, data portability
- **AI / Tech Platform:** EU AI Act compliance, automated decision-making disclosure, AI training data consent, GPAI model transparency, Colorado AI Act consequential decisions
- **Gaming:** Child safety, loot boxes, virtual currency
- **Retail:** PCI-DSS, customer data, loyalty programs

**Technical Notes:**
- Industry adds context to LLM prompts
- Highlights industry-specific regulatory risks
- Optional field; does not block analysis if not selected

### F3: Risk Analysis Engine

**Priority:** P0 (MVP)
**User Story:** As a user, I want the system to automatically detect risky clauses and calculate an overall risk score so I can quickly assess the document.

#### F3.1: Risk Scoring

**Status:** IRP (Impact / Likelihood / Safeguards) scoring is **shipped**. Landed in PR #34 (commits `e4fd706` -> `b5ea947`). `Finding` carries `impact`, `likelihood`, `safeguard_score`, and a computed `irp_score` (`src/backend/app/schemas.py:161-164`); the composite is computed by `analyzer.py::_compute_irp` (`src/backend/app/services/analyzer.py:136-139`), seeded per-category by `rules.py::_seed_irp`, and requested from the LLM in `prompts.py`. Hybrid merge takes `impact`/`likelihood` from the rule as baseline and `safeguard_score = max(rule, llm)`. Cross-reference: LIB-RULES §IRP Scoring, LIB-CONTEXT §sort semantics, `.claude/CLAUDE.md` §Identity (Risk Method row).

**IRP Formula (shipped):**
- **Composite:** `irp_score = 0.5 * (impact / 5) + 0.4 * (likelihood / 5) - 0.3 * (safeguard_score / 5)`, clamped to `[0, 1]` and rounded to 4 decimals.
- **Per-finding fields:** `impact` (1-5), `likelihood` (1-5), `safeguard_score` (0-5), `irp_score` (0.0-1.0). Defaults when unseeded: `impact=2`, `likelihood=3`, `safeguard_score=0`.
- **Overall document score:** aggregated on a **0-10 scale (higher = worse)** via severity-weighted average of finding scores (`analyzer.py::calculate_risk_score`). The IRP composite drives per-finding ranking; the 0-10 aggregate drives the letter grade. This is deliberate — LIB-RULES documents the split.

**Grade Thresholds (shipped, 0-10 scale, `analyzer.py::_grade` at `src/backend/app/services/analyzer.py:426-439`):**

| Grade | Risk Score Range | Meaning |
|-------|------------------|---------|
| A     | `< 3.5`          | Low risk |
| A-    | `3.5 - 4.5`      | Low-moderate risk |
| B     | `4.5 - 5.5`      | Moderate risk |
| B-    | `5.5 - 6.5`      | Moderate-elevated risk |
| C+    | `6.5 - 7.5`      | Elevated risk |
| C     | `7.5 - 8.5`      | High risk |
| D+    | `>= 8.5`         | Very high risk |

Note: the shipped scale intentionally does not include `D`, `D-`, or `F` grades — the tool's voice (see LIB-VOICE) avoids alarming language, and the `D+` ceiling was chosen so the worst grade still reads as "worth a closer read" rather than "critical failure." Any request to add lower grades is scope drift per LIB-PRINCIPLES Principle 3 and must be surfaced.

**Impact Scoring (1-5):**
- **5 - Catastrophic:** Identity theft, financial fraud, major privacy violation, irreversible harm.
- **4 - High:** Significant data exposure, major rights waiver, hard-to-reverse consequence.
- **3 - Medium:** Moderate privacy concern, limited data sharing.
- **2 - Low (default):** Minor inconvenience, standard industry practice.
- **1 - Trivial:** Informational, no real risk.

**Likelihood Scoring (1-5):**
- **5 - Automatic / Routine:** Clause describes an always-on / current practice.
- **4 - Likely:** Clause allows the practice with few limitations.
- **3 - Possible (default):** Conditional or situational language.
- **2 - Unlikely:** Heavily restricted or rare circumstances.
- **1 - Extremely Rare:** Theoretical possibility only.

**Safeguard Scoring (0-5):**
- **5 - Full Mitigation:** Multiple protections, explicit user control, transparency, hard limits.
- **4 - Strong:** Meaningful protections and user rights.
- **3 - Moderate:** Basic protections, limited user control.
- **2 - Weak:** Minimal protections, little transparency.
- **1 - Minimal:** Nominal safeguards only.
- **0 - None (default):** No protections, no user recourse.

**Sort semantics (shipped):**
- Findings sort **tier-first**: `(context_weight, irp_score, severity_rank)` all descending — context chip weight leads, IRP breaks ties within a tier, severity is the tiebreaker of last resort. Legacy findings without `irp_score` fall back to severity weight. Full detail: LIB-CONTEXT.

**Technical Notes:**
- `_compute_irp` at `src/backend/app/services/analyzer.py:136-139` is the single source of truth for the composite.
- `_seed_irp` in `rules.py` seeds rule-generated findings from `_CATEGORY_IRP_DEFAULTS` (38 categories mapped).
- LLM prompts request `impact` / `likelihood` / `safeguard_score` per finding; missing values fall back to defaults above.
- Confidence is a separate signal (see F3.4); it is not part of the IRP composite.

**UI Display:**
- Overall grade: large letter with color coding derived from the 7-band table above.
- Overall risk score: numeric (0.00-10.00), 2 decimal places.
- Per-finding IRP: numeric (0.00-1.00), 4 decimal places (surfaced in the expanded finding card, see F4.2).
- Risk level label: mapped from grade to the calmer verbal band ("Low" / "Moderate" / "Elevated" / "High") — no "Critical" verbal label to preserve the LIB-VOICE calm-confidence register.

#### F3.2: Risk Categories (9 Core Types — expanded in practice to ~50)

**Note:** the 9 categories below are the original conceptual framework. Actual rule coverage in `rules.py` has grown to ~50 category labels across 64 `RulePattern` entries — additional AI Act sub-categories (High-Risk AI, Prohibited AI, Automated Decision-Making, AI Training, AI-Generated Content, GPAI, AI Training Opt-Out, Algorithmic Accountability, Human Oversight, AI Non-Discrimination) and industry-specific blocks (HIPAA, FERPA, PCI DSS, COPPA) layer on top of these 9 buckets rather than replacing them.

**Acceptance Criteria:**
- [ ] System detects and categorizes findings into risk types (9 core + expanded jurisdiction/industry-specific categories)
- [ ] Each finding is assigned exactly one primary category
- [ ] System displays category icon and color
- [ ] User can filter findings by category
- [ ] System shows count of findings per category

**Category Definitions (core 9):**

**1. Data Sharing**
- **What:** Third-party sales, data broker relationships, cross-border transfers
- **Detection:** Keywords: "sell", "share", "third party", "partner", "affiliate", "transfer"
- **Jurisdictions:** US-CA (sale opt-out), GDPR (lawful basis, adequacy)
- **Icon:** 🔗 Share icon
- **Color:** Orange

**2. Automated Decisions**
- **What:** Algorithmic decision-making, profiling, scoring without human review
- **Detection:** Keywords: "automated", "profiling", "algorithm", "machine learning", "AI decision"
- **Jurisdictions:** GDPR (Art. 22), US-CA (ADM disclosure)
- **Icon:** 🤖 Robot icon
- **Color:** Purple

**3. Dark Patterns**
- **What:** Deceptive consent, pre-checked boxes, hidden opt-outs, confusing language
- **Detection:** Keywords: "pre-checked", "by using", "continued use", "deemed acceptance"
- **Jurisdictions:** GDPR (valid consent), US-CA (clear disclosure)
- **Icon:** 🎭 Mask icon
- **Color:** Red

**4. Retention**
- **What:** Indefinite storage, vague deletion timelines, no data minimization
- **Detection:** Keywords: "indefinitely", "as long as", "necessary", "reasonable period"
- **Jurisdictions:** GDPR (storage limitation), PIPEDA (retention limits)
- **Icon:** 📦 Box icon
- **Color:** Brown

**5. User Rights**
- **What:** Missing or limited access, correction, deletion, portability rights
- **Detection:** Absence of rights language, "may deny", "at our discretion"
- **Jurisdictions:** GDPR (DSAR rights), US-CA (consumer rights)
- **Icon:** ⚖️ Scale icon
- **Color:** Blue

**6. Minors**
- **What:** Inadequate child protections, missing COPPA compliance, age verification
- **Detection:** Keywords: "children", "under 13", "minors", "parental consent"
- **Jurisdictions:** US-FED (COPPA), GDPR (Art. 8)
- **Icon:** 👶 Child icon
- **Color:** Yellow

**7. Sensitive Data**
- **What:** Biometrics, health data, financial info, precise geolocation
- **Detection:** Keywords: "biometric", "health", "medical", "financial", "location"
- **Jurisdictions:** US-CA (sensitive PI), GDPR (special categories)
- **Icon:** 🔒 Lock icon
- **Color:** Dark red

**8. Unilateral Changes**
- **What:** Policy modifications without notice, forced acceptance, no grandfathering
- **Detection:** Keywords: "at any time", "without notice", "sole discretion", "continued use"
- **Jurisdictions:** GDPR (transparency), US-CA (material changes)
- **Icon:** 📝 Document icon
- **Color:** Gray

**9. Liability**
- **What:** Excessive disclaimers, forced arbitration, class action waivers, indemnification
- **Detection:** Keywords: "arbitration", "class action", "waive", "indemnify", "no liability"
- **Jurisdictions:** US-FED (consumer protection), State laws
- **Icon:** ⚠️ Warning icon
- **Color:** Orange-red

**Canonical Shipped Category List (`schemas.CATEGORIES`):**

The 9 conceptual buckets above group ~50 canonical category labels shipped in `src/backend/app/schemas.py::CATEGORIES`. This frozenset is the single source of truth: any category-keyed dict in `rules.py`, `analyzer.py`, or `context.py` is validated against it at import time (audit finding LE-013 — see §Implementation Status Note — v2.1 addendum).

The canonical labels are:

- **Data-collection:** `Sensitive Data`, `Sensitive Data / Opt-Out`, `Biometric Data`, `Health Data`, `Financial Data`, `Children's Privacy`, `Collection Notice`, `Minors`
- **Data-use:** `AI Training`, `AI Training Opt-Out`, `AI Training (Opt-Out)`, `Sale/Share`, `Data Sale / Sharing`, `Third-Party Sharing`, `Tracking / Profiling`, `Tracking & Consent`, `Marketing Communications`, `Purpose Limitation`, `ADM`, `Automated Decision-Making`, `Consequential AI Decisions`, `High-Risk AI`, `Prohibited AI`, `GPAI / Generative AI`, `AI-Generated Content`, `Algorithmic Accountability`, `Human Oversight`, `AI Non-Discrimination`, `Transparency`
- **Terms-of-use:** `Liability`, `Arbitration / Dispute`, `Intellectual Property`, `In-App Purchases`, `Unilateral Changes`, `Dark Patterns`, `Deceptive Practices`, `Retention`, `Breach Notification`, `Data Security`, `Consent`, `Sub-processors`
- **Privacy-rights:** `User Rights`, `Data Rights`, `Individual Rights`, `Privacy Rights`, `Cross-Border Transfer`, `Data Transfer`, `COPPA Compliance`, `HIPAA Compliance`, `FERPA Compliance`, `PCI DSS Compliance`, `PIPEDA Consent`, `LGPD Rights`, `APPI Disclosure`, `DPDP Consent`, `POPIA Processing`, `PIPA Processing`, `APP Privacy`, `UK Data Rights`, `Privacy as Human Right`, `Serious Privacy Invasion`

**LE-013 taxonomy alignment (v2.2, 2026-07-03):** the Phase 1 remediation switched `_DOCTYPE_BOOSTS` / `_INDUSTRY_BOOSTS` from case-insensitive substring lookup to exact-category match. That change surfaced nine boost keys that had been firing on unrelated substrings ("Consent" matching "PIPEDA Consent", and so on). Rather than delete them, the following labels are canonical here and expected to be present in `schemas.CATEGORIES`, `_DOCTYPE_BOOSTS`, and `_INDUSTRY_BOOSTS`: `Arbitration / Dispute` (ToS), `Third-Party Sharing` (Privacy Policy / Cookie Policy / DPA), `Sub-processors` (DPA), `Data Transfer` (DPA), `Intellectual Property` (ToS), `Transparency` (AI / Tech Platform), `In-App Purchases` (Gaming). `Data Retention` is aliased to `Retention`, and `Liability Limitation` is aliased to `Liability` — both aliases remain canonical for the boost dicts only, no new schema entry required.

**Technical Notes:**
- Each category has rule-based regex patterns + LLM semantic detection
- LLM provides context and explains why clause matches category
- System combines rule-based and LLM results, prioritizing higher confidence

#### F3.3: Evidence Binding

**Acceptance Criteria:**
- [ ] Every finding includes excerpt from source document
- [ ] Excerpt is 1-3 sentences (max 500 characters)
- [ ] System stores line numbers (start, end) for highlighting
- [ ] User can click "View in Context" to see full paragraph
- [ ] Excerpts preserve original formatting and punctuation
- [ ] System highlights exact matched text in yellow

**Technical Notes:**
- Store document with line numbers: `{line_num}: {text}`
- Finding object: `{excerpt, line_start, line_end, legal_basis: []}`
- Legal basis: Array of applicable regulations (e.g., `["CCPA § 1798.100", "GDPR Art. 13"]`)
- Use `difflib` for fuzzy matching if text changed slightly

**UI Display:**
- Show excerpt in quote block
- "View in Context" button opens modal with full section
- Highlight matched text in context view
- Show line numbers in left margin

#### F3.4: Confidence Scoring & Review Queue

**Acceptance Criteria:**
- [ ] System calculates confidence score (0-1) for each finding
- [ ] Confidence <0.80 triggers "Needs Review" flag
- [ ] Findings flagged for review appear in review queue
- [ ] User can approve, reject, or edit flagged findings
- [ ] System learns from user feedback (future: ML retraining)

**Confidence Factors:**
- **Rule-based match:** Base confidence 0.75
- **LLM semantic match:** Base confidence 0.85
- **Both match:** Confidence 0.95
- **LLM + legal citation:** Confidence 0.90
- **Ambiguous language detected:** -0.10 confidence
- **Industry-specific jargon:** -0.05 confidence

**Review Queue Actions:**
- **Approve:** Keep finding, mark as verified, confidence → 1.0
- **Reject:** Remove finding from results, log for ML training
- **Edit:** User can modify category, severity, or excerpt
- **Add Note:** User can add context or explanation

**Technical Notes:**
- Store review actions in `review_items` table
- Link to original analysis via foreign key
- Track reviewer, timestamp, action, notes

### F4: Results Display

**Priority:** P0 (MVP)
**User Story:** As a user, I want to see analysis results in a clear, actionable format so I can quickly understand the risks.

#### F4.1: Overview Summary

**Acceptance Criteria:**
- [x] Display overall grade (7-band shipped scale: A / A- / B / B- / C+ / C / D+) prominently at top
- [x] Show overall risk score (0.00-10.00) as numeric value; per-finding IRP (0.00-1.00) surfaced in expanded finding card (F4.2)
- [x] Display risk level label with color coding derived from grade band
- [x] Show total findings count
- [x] Display breakdown by severity (High/Medium/Low; Critical accepted from LLM but folded into High for verbal labels per LIB-VOICE)
- [x] Show confidence indicator (% of findings with confidence >=0.80)
- [x] Display "Needs Review" badge when `action_readiness == "Review"` or `review_required == True`
- [x] Show analysis timestamp and jurisdiction(s) — `AnalysisPayload.jurisdictions` echoes back the filter set
- [x] Show context-appropriate `verdict_headline` and `verdict_label` chip (see LIB-CONTEXT for verdict copy rotation semantics)
- [x] Show `completeness` fraction (0.0-1.0) indicating share of expected policy sections detected

**Layout:**
```
┌─────────────────────────────────────┐
│  RISK GRADE: C+                     │
│  ████████░░░░ 6.8 / 10              │
│                                     │
│  📊 12 Findings                     │
│  🔴 4 High  🟡 5 Medium  🟢 3 Low   │
│                                     │
│  ⚠️ 2 Findings Need Review          │
│  ✓ 85% Confidence                   │
│                                     │
│  📍 US-CA, GDPR                  │
│  🕒 Analyzed: Feb 13, 2026 8:49 PM  │
└─────────────────────────────────────┘
```

**Technical Notes:**
- Use Card component with prominent visual hierarchy
- Color coding: A/B=green, C=yellow, D/F=red
- Risk gauge: Visual progress bar (0-10 scale)
- Findings counts are interactive (click to filter)

#### F4.2: Findings List

**Acceptance Criteria:**
- [ ] Display all findings in collapsible cards
- [ ] Show category icon, name, and severity badge
- [ ] Display excerpt (truncated if >200 chars)
- [ ] Show confidence indicator
- [ ] Allow expanding card to see full details
- [ ] Enable filtering by category, severity, confidence
- [ ] Enable sorting by severity, confidence, category
- [ ] Show "View in Context" link

**Finding Card Layout:**
```
┌────────────────────────────────────────────┐
│ 🔗 Data Sharing                    [HIGH]  │
│ ─────────────────────────────────────────  │
│ "We may share personal information with    │
│  third-party partners for marketing..."    │
│                                            │
│ ⚖️ Triggers CCPA opt-out rights           │
│ 📄 Lines 120-126  |  🎯 86% Confidence     │
│ [View in Context] [Edit] [Flag for Review]│
└────────────────────────────────────────────┘
```

**Expanded Card Shows:**
- Full excerpt (no truncation)
- Plain language explanation
- Applicable jurisdictions with flag icons
- Legal basis citations (e.g., "CCPA § 1798.115")
- Impact/Likelihood/Safeguards scores
- IRP score for this finding
- Recommendations (if any)

**Filters:**
- **Category:** Checkboxes for all 9 categories
- **Severity:** High, Medium, Low
- **Confidence:** ≥90%, 80-89%, <80% (Needs Review)
- **Jurisdiction:** US-CA, GDPR, etc.

**Sorting:**
- Severity (High → Low, default)
- Confidence (Low → High, for review priority)
- Category (alphabetical)
- Line number (document order)

#### F4.3: Verify View

**Acceptance Criteria:**
- [ ] User can click "Verify" to see full document with highlights
- [ ] System displays document in left pane, findings in right pane
- [ ] Clicking finding highlights corresponding text in document
- [ ] Highlighted sections show line numbers
- [ ] User can navigate between findings with prev/next buttons
- [ ] Highlight colors match severity (red=high, yellow=medium, green=low)
- [ ] User can add annotations/notes

**Layout:**
```
┌──────────────────┬──────────────────┐
│  DOCUMENT        │  FINDINGS        │
│                  │                  │
│  1. Introduction │  [Finding 1]     │
│  2. Data we...   │  ├─ Category     │
│  ...             │  ├─ Severity     │
│  120. We may ■   │  └─ Confidence   │
│  share personal  │                  │
│  information ■   │  [Finding 2]     │
│  with third...   │  ...             │
│                  │                  │
│  [◄ Prev] [Next ►]│  [Export] [Print]│
└──────────────────┴──────────────────┘
```

**Technical Notes:**
- Use split-pane layout with resizable divider
- Store document with line numbers in database
- Highlight matches using `<mark>` tags with severity classes
- Smooth scroll to highlighted section
- Preserve text formatting (paragraphs, line breaks)

**UI Mockup Reference:** `docs/wireframes/reviewer_wireframe_v2.png` - Verify view

#### F4.4: Plain Language Explanations

**Acceptance Criteria:**
- [ ] Every finding includes user-friendly explanation
- [ ] Explanation avoids legal jargon
- [ ] Explanation describes practical impact
- [ ] Explanation suggests user actions (if applicable)
- [ ] Explanations are concise (2-4 sentences, max 300 chars)
- [ ] Links to "Learn More" external resources (optional)

**Example Explanations:**

**Data Sharing (High Severity):**
> "This policy allows the company to sell or share your personal information with third parties for marketing purposes. Under California law (CCPA), you have the right to opt out of this data sale. Look for a 'Do Not Sell My Personal Information' link."

**Forced Arbitration (High Severity):**
> "You're agreeing to settle disputes through arbitration instead of going to court. This means you can't sue the company or join a class action lawsuit. Arbitration often favors companies and limits your legal options."

**Vague Retention (Medium Severity):**
> "The policy doesn't specify how long they keep your data. Under GDPR, companies should only keep data as long as necessary. You can request deletion of your data at any time."

**Technical Notes:**
- LLM generates explanation based on finding context
- Fallback to template if LLM fails
- Templates stored in `explanation_templates` table
- Explanation quality validated during accuracy audit

### F5: Export & Reporting

**Priority:** P0 (MVP)
**User Story:** As a user, I want to export analysis results so I can save, share, or document my findings.

#### F5.1: PDF Export

**Acceptance Criteria:**
- [ ] User can click "Export PDF" button
- [ ] System generates professional PDF report
- [ ] PDF includes document name, analysis date, jurisdiction(s)
- [ ] PDF shows overall grade and risk score
- [ ] PDF lists all findings with excerpts and explanations
- [ ] PDF includes Verify view section with highlighted excerpts
- [ ] PDF is paginated with header/footer
- [ ] PDF size: <2MB for typical analysis
- [ ] Generation time: <10 seconds

**PDF Structure:**
1. **Cover Page:** Document name, grade, date, logo
2. **Executive Summary:** Overall risk assessment, key findings
3. **Detailed Findings:** Each finding with full details
4. **Evidence Excerpts:** Highlighted sections from source
5. **Methodology:** Brief explanation of IRP scoring
6. **Disclaimer:** "Not legal advice" statement

**Technical Notes:**
- Use `reportlab` or `weasyprint` for PDF generation
- Template: Professional layout with branding
- Include page numbers, table of contents
- Export endpoint: `GET /exports/analysis/{id}.pdf`

#### F5.2: JSON Export

**Acceptance Criteria:**
- [ ] User can export analysis as JSON file
- [ ] JSON includes all raw data (findings, scores, excerpts, line numbers)
- [ ] JSON structure is documented and versioned
- [ ] JSON is formatted (pretty-printed) for readability
- [ ] JSON includes schema version for future compatibility

**JSON Structure:**
```json
{
  "schema_version": "1.0",
  "analysis_id": "uuid",
  "document_name": "Example Privacy Policy",
  "analyzed_at": "2026-02-13T20:49:00Z",
  "jurisdictions": ["US-CA", "GDPR"],
  "risk_score": 6.8,
  "grade": "C+",
  "confidence": 0.85,
  "findings": [
    {
      "id": "uuid",
      "category": "Data Sharing",
      "severity": "High",
      "confidence": 0.86,
      "excerpt": "...",
      "explanation": "...",
      "impact": 4,
      "likelihood": 4,
      "safeguards": 2,
      "irp_score": 0.76,
      "evidence": {
        "line_start": 120,
        "line_end": 126,
        "legal_basis": ["CCPA § 1798.115"]
      },
      "jurisdictions": ["US-CA"]
    }
  ]
}
```

**Technical Notes:**
- Export endpoint: `GET /exports/analysis/{id}.json`
- Use `json.dumps(indent=2)` for formatting
- Include `Content-Disposition: attachment` header

#### F5.3: CSV Export (Bulk)

**Acceptance Criteria:**
- [ ] User can export multiple analyses as CSV
- [ ] CSV includes summary data for each analysis
- [ ] CSV columns: ID, Name, Date, Jurisdiction(s), Grade, Risk Score, Findings Count, High/Med/Low counts
- [ ] CSV is properly escaped (handles commas, quotes)
- [ ] Option to include detailed findings (one row per finding)

**CSV Structure (Summary):**
```csv
ID,Name,Date,Jurisdictions,Grade,Risk Score,Total Findings,High,Medium,Low,Confidence
uuid1,"Example Privacy Policy",2026-02-13,"US-CA|GDPR",C+,6.8,12,4,5,3,0.85
uuid2,"Another ToS",2026-02-12,"US-FED",B,4.2,8,1,3,4,0.91
```

**CSV Structure (Detailed):**
```csv
Analysis ID,Document Name,Finding ID,Category,Severity,Confidence,Excerpt,Line Start,Line End
uuid1,"Example Privacy Policy",f1,Data Sharing,High,0.86,"We may share...",120,126
uuid1,"Example Privacy Policy",f2,Retention,Medium,0.82,"We keep data...",145,150
```

**Technical Notes:**
- Export endpoint: `GET /exports/analyses.csv?detailed=true`
- Use Python `csv` module with proper escaping
- Support filtering by date range, jurisdiction

### F6: Watchlist Monitoring

**Priority:** P1 (Phase 4 - Months 4-6)
**User Story:** As a user, I want to monitor policies for changes over time so I'm alerted when vendors update their terms.

#### F6.1: Add to Watchlist

**Acceptance Criteria (v2.4, 2026-07-03 — OE-003 merged model):**
- [ ] User can add a vendor + URL pair to the watchlist (subject is the vendor / URL, not the analysis id). If the user is starting from a completed analysis, the analysis reference lives in the free-text `notes` field or in the response's `last_analysis_id` column — it is not a required request field.
- [ ] System stores `source_url` and current policy text hash (`last_document_hash`).
- [ ] User can set a per-item check frequency via the optional `check_frequency` field (seconds; range 300 to 604800, i.e. 5 minutes to 7 days). UI dropdown mapping: daily = 86400, weekly = 604800, monthly = 2592000 (30 days). When the caller omits `check_frequency`, the item stores the ORM default (86400s / 24h) and the background refresh loop falls back to `settings.watchlist_refresh_seconds` at scheduler time via `_effective_check_frequency`.
- [ ] User can add free-text notes via the optional `notes` field (max 1024 chars).
- [ ] User can enable / disable an item via the optional `enabled` boolean (default `True`). When `enabled=False`, the background refresh loop skips the item entirely.
- [ ] System confirms addition with the `WatchlistItemPayload` response, including computed `next_check_at` (equal to `last_checked + check_frequency`; null when disabled).

**Schema (shipped):** `WatchlistCreateRequest` in `src/backend/app/schemas.py` — `vendor: str` (required, min length 1), `source_url: Optional[str]` (http/https only, hostname required, defense-in-depth against `javascript:` schemes), `check_frequency: Optional[int]` (300 to 604800 seconds), `enabled: Optional[bool]` (defaults True), `user_id: Optional[str]` (alphanumeric plus `@._-`, max 255), `notes: Optional[str]` (max 1024).

#### F6.2: Change Detection

**Acceptance Criteria (v2.4, 2026-07-03 — per-item cadence, OE-003):**
- [ ] Background loop (`_watchlist_loop_async` in `main.py`) refreshes only items whose `last_checked + check_frequency` is in the past AND whose `enabled` flag is True. Previously the loop woke on a single global `settings.watchlist_refresh_seconds` interval and refreshed every item every tick; the per-item contract is now honored.
- [ ] Cadence is per-item, sourced from the `check_frequency` column. The server-side `settings.watchlist_refresh_seconds` remains as a global fallback when an item is inserted with the column left at its default and no override.
- [ ] System compares new text to stored `last_document_text` / `last_document_hash`.
- [ ] System calculates diff (added / removed / changed lines) via `diffing.diff_summary`.
- [ ] System re-analyzes changed policies via `rules.detect_findings(text, [])` — the empty `jurisdictions` list preserves the global-tool contract (LIB-PRINCIPLES Principle 1 — no silent US-CA + GDPR default).
- [ ] System calculates `risk_delta` (score change vs. `last_risk_score`).
- [ ] Loop clamps its wakeup interval to `[_WATCHLIST_LOOP_MIN_SLEEP_S, _WATCHLIST_LOOP_MAX_SLEEP_S]` (60s to 3600s) so an empty watchlist or a very-long-cadence backlog does not hang the scheduler.
- [ ] System sends email notification if significant change (±1.0 risk score or new high-severity finding). **Note:** email dispatch itself is deferred — tracked separately under BRD-ROADMAP-P4-D007.

#### F6.3: Watchlist Dashboard

**Acceptance Criteria:**
- [ ] User can view all monitored documents
- [ ] Dashboard shows last checked date, next check date
- [ ] Dashboard highlights items with recent changes
- [ ] User can manually trigger re-check
- [ ] User can remove items from watchlist
- [ ] User can compare current vs. previous version

**UI Mockup Reference:** `docs/wireframes/dashboard_wireframe_v2.png`

### F7: Vendor Comparison

**Priority:** P1 (Phase 4 - Months 4-6)
**User Story:** As a user, I want to compare policies side-by-side so I can choose the better option.

#### F7.1: Comparison View

**Acceptance Criteria:**
- [ ] User can select 2-3 analyses to compare
- [ ] System displays side-by-side comparison table
- [ ] Table shows overall grades, risk scores
- [ ] Table compares findings by category
- [ ] Table highlights differences (better/worse/same)
- [ ] User can export comparison as PDF

**Comparison Table:**
```
┌──────────────┬───────────┬───────────┬───────────┐
│ Metric       │ Vendor A  │ Vendor B  │ Vendor C  │
├──────────────┼───────────┼───────────┼───────────┤
│ Overall Grade│ C+ (6.8)  │ B (4.5) ✓│ D (7.9)   │
│ Data Sharing │ 3 High    │ 1 Medium✓│ 4 High    │
│ Retention    │ 2 Medium  │ 1 Low ✓  │ 2 Medium  │
│ User Rights  │ Missing ✗ │ Complete✓│ Limited   │
│ Liability    │ Arbitrate │ Both     │ Arbitrate │
└──────────────┴───────────┴───────────┴───────────┘
```

**Technical Notes:**
- Normalize findings for comparison (same categories, weights)
- Highlight "best choice" with green checkmark
- Show winner per category

### F8: AI Law Analysis

**Priority:** P1 (MVP+ — rule detection ships with MVP; full UI surface is post-MVP)
**User Story:** As a user, I want the tool to flag clauses relevant to AI regulations so I understand my rights and the service's obligations under AI-specific laws.

**Note:** AI law rule detection (pattern matching) is active from initial release. The dedicated AI Law findings view (F8.1–F8.5 UI) ships in the first post-MVP release.

#### F8.1: AI Training Data Detection

**Acceptance Criteria:**
- [ ] System detects clauses where user data may be used to train AI/ML models
- [ ] System flags missing opt-out rights for AI training use
- [ ] System maps findings to CPPA AI Regulations, EU AI Act Recital 107, OECD AI Principle 1.3

#### F8.2: Automated Decision-Making Disclosure

**Acceptance Criteria:**
- [ ] System detects fully automated decisions with legal or significant effects
- [ ] System flags absence of human review rights
- [ ] System maps to GDPR Art. 22, EU AI Act Art. 86, Colorado AI Act SB 205

#### F8.3: High-Risk AI System Disclosure

**Acceptance Criteria:**
- [ ] System detects use of AI in regulated sectors (credit, employment, education, healthcare, law enforcement)
- [ ] System flags missing transparency notices required by EU AI Act Arts. 13–14
- [ ] System maps to EU AI Act Annex III high-risk categories

#### F8.4: Biometric AI Processing

**Acceptance Criteria:**
- [ ] System detects facial recognition, biometric identifiers, and real-time biometric surveillance
- [ ] System flags consent and retention requirements under Illinois BIPA
- [ ] System flags EU AI Act Art. 5 prohibition on real-time remote biometric identification in public spaces

#### F8.5: GPAI / Foundation Model Transparency

**Acceptance Criteria:**
- [ ] System detects services built on general-purpose AI or large language models
- [ ] System maps to EU AI Act Title VIII (Arts. 51–56) obligations
- [ ] System flags copyright and training data provenance disclosure gaps

**Technical Notes:**
- AI law patterns are implemented in `services/rules.py` under jurisdiction codes: `EU-AI-ACT`, `COE-AI-225`, `OECD-AI`, `UNESCO-AI`, `US-CO`
- No additional LLM prompting required — pure rule-based detection with LLM confirmation pass
- AI law findings surface in the same findings UI as privacy findings

---

## User Flows

### Flow 1: First-Time User Analyzes Privacy Policy

1. **Landing:** User visits app homepage
2. **Input:** User selects "URL" tab, pastes `https://example.com/privacy`
3. **Configure:** User keeps default jurisdictions (US-CA, GDPR), selects "Privacy Policy" type
4. **Submit:** User clicks "Analyze" button
5. **Processing:** Loading spinner shows "Fetching document... Analyzing clauses... Calculating risk..." (15-30 seconds)
6. **Results:** Results page displays:
   - Overall grade (C+) with risk gauge
   - 12 findings breakdown (4 High, 5 Medium, 3 Low)
   - Findings list (collapsed)
7. **Explore:** User expands "Data Sharing (High)" finding
   - Reads excerpt: "We may share personal information..."
   - Reads explanation: "This triggers CCPA opt-out rights..."
   - Clicks "View in Context" to see full paragraph
8. **Verify:** User clicks "Verify" button
   - Split-pane view opens
   - Clicks finding in right pane
   - Corresponding text highlights in left pane (yellow)
9. **Export:** User clicks "Export PDF"
   - PDF generates and downloads (3 seconds)
   - User saves PDF for records
10. **Done:** User closes tab, satisfied with analysis

**Edge Cases Handled:**
- URL returns 404 → Error: "Unable to fetch document. Please check the URL."
- URL requires JavaScript → Fallback to text paste with instructions
- Analysis takes >60 seconds → Show "Still analyzing... this is taking longer than usual"
- No high-risk findings → Congratulatory message: "This policy has relatively low risk!"

### Flow 2: Researcher Bulk Analyzes Policies (API-only for MVP)

**Decision (v2.3, 2026-07-03):** Flow 2 Batch Analysis ships as **API-only** for this release. UI treatment (CSV upload, progress bar, sortable table, "Export All as CSV" button) is a P2 follow-up tracked separately. Rationale: the synchronous `POST /analyze/batch` endpoint cannot survive a real 50-URL run behind HTTP proxies without an async job model, which is a multi-day architecture change, not a UI wire-up. Shipping API-only lets researchers proceed today via scripted access while the async story is scoped independently.

**Persona narrative.** The researcher (a compliance analyst, a graduate student, or an in-house counsel building a longitudinal dataset) needs to analyze tens of privacy policies as a batch and get structured JSON back for downstream analysis (R, pandas, Jupyter). They are comfortable with a terminal and can script `curl` calls, so they do not need a UI to be productive. What they need is a documented, stable JSON contract and an endpoint they can hit in a loop.

1. **Prepare:** Researcher assembles a list of policy URLs (or raw text bodies) in whatever format is convenient (CSV, JSON, Python list).
2. **Author request:** Researcher constructs an `AnalyzeBatchRequest` JSON body targeting `POST /analyze/batch`. Example payload:

    ```json
    {
      "items": [
        {"name": "Acme ToS",    "url": "https://acme.example.com/terms",   "doc_type": "terms_of_service"},
        {"name": "Acme Policy", "url": "https://acme.example.com/privacy", "doc_type": "privacy_policy"},
        {"name": "Beta Policy", "url": "https://beta.example.com/privacy", "doc_type": "privacy_policy"}
      ],
      "industry": "healthcare",
      "jurisdictions": ["GDPR"],
      "mode": "full",
      "detect_cross_references": true,
      "context": ["for_work"]
    }
    ```

3. **Call the endpoint:** Researcher submits with `curl`:

    ```bash
    curl -X POST http://localhost:9000/analyze/batch \
      -H 'Content-Type: application/json' \
      -d @batch_request.json > batch_result.json
    ```

    An empty `jurisdictions: []` means "no jurisdiction filter" (global-tool contract, see LIB-CONTEXT). US-CA + GDPR is not applied by default.
4. **Receive results:** Response is a `BatchAnalysisResult` containing a `batch_id`, per-item `AnalysisPayload` objects (grade, `top_by_domain`, `action_items`, `verdict_headline`, findings), and optional `cross_references` when `detect_cross_references=true`.
5. **Downstream analysis:** Researcher writes their own script to flatten the JSON into a dataframe, sort/filter, plot distributions, or export to CSV. Progress tracking (which item is done) and export formatting are the researcher's responsibility for this release.
6. **Cite:** Researcher references tool methodology (IRP scoring, category taxonomy, jurisdiction coverage) in their publication. Backend contract is stable and versioned via the PRD Change History.

**Edge Cases Handled (API surface):**
- Some URLs fail → per-item error surfaces in that item's `AnalysisPayload`; sibling items still return successfully. Batch does not fail-fast.
- Individual item text exceeds `MAX_INPUT_CHARS` → that item is rejected at schema-validation time with a 422; other items proceed.
- LLM unavailable → each item degrades to rule-only findings with reduced confidence (see Hard Requirements).
- Very large batches → synchronous endpoint means the caller holds the connection open for the full duration. For runs >20 URLs, callers should either split into smaller batches or wait for the async-job successor endpoint (P2).

**Out of Scope for This Release (tracked as P2 follow-ups):**
- Batch UI wired into the Streamlit v2 view (nav surface, CSV upload widget, progress bar, sortable results table, "Export All as CSV" button).
- Async job model with pause/resume, background workers, and job-status polling.
- Rate-limiting / throttling controls on outbound fetches beyond what `ingest.py` already applies per request.

**Optional CLI wrapper.** For researchers who prefer a CSV-in / CSV-out shape without writing their own client, a thin shell helper is available at `src/backend/scripts/batch_analyze.py`. It reads a CSV with columns `name,url,jurisdiction`, calls `POST /analyze/batch` in a single request, and writes summary rows to a result CSV. The helper is a convenience, not the contract; the contract is the JSON endpoint above.

### Flow 3: Founder Reviews Vendor Agreement Before Signing

1. **Context:** Founder receives PDF agreement from SaaS vendor
2. **Upload:** Opens AI Terms Reviewer, drags PDF into upload area
3. **Configure:** Selects jurisdictions (US-CA, GDPR), type (Data Processing Agreement), industry (Healthcare)
4. **Submit:** Clicks "Analyze"
5. **Processing:** Extracts text from PDF (5 seconds), analyzes (20 seconds)
6. **Results:** Grade D (7.5) with 15 findings
7. **Review Key Findings:**
   - **High:** "Unlimited sub-processor rights" → Concern for HIPAA compliance
   - **High:** "No liability for data breaches" → Unacceptable risk
   - **Medium:** "30-day termination notice" → Standard
8. **Action:** Founder exports PDF report
9. **Follow-Up:** Founder emails vendor: "We have concerns about clauses X and Y. Can we negotiate?"
10. **Negotiate:** Vendor revises agreement
11. **Re-Analyze:** Founder uploads revised PDF, confirms improvements (Grade B, 8 findings)
12. **Decide:** Founder signs agreement, stores analysis in due diligence folder

**Edge Cases Handled:**
- PDF is scanned (image) → OCR activated automatically, warn about potential accuracy issues
- PDF has 100+ pages → Process in chunks, may take 2-3 minutes
- Agreement references external documents → Flag: "This agreement references other documents not included in this analysis"

---

## Technical Architecture

### System Architecture

```
┌─────────────────────────────────────────────────────┐
│              FRONTEND — Streamlit only              │
│  Streamlit v2 (:8501, app_streamlit_v2.py)          │
│  v1 rollback (STREAMLIT_UI=v1, app_streamlit_legacy)│
│                                                     │
│  ┌───────────┐  ┌──────────┐  ┌─────────────┐     │
│  │  Input UI │  │ Results  │  │  Verify     │     │
│  │           │→ │ Display  │→ │  View       │     │
│  └───────────┘  └──────────┘  └─────────────┘     │
└─────────────────────────────────────────────────────┘
                        ↓ HTTP/REST
┌─────────────────────────────────────────────────────┐
│                 BACKEND (FastAPI, :9000)            │
│               (src/backend/app/)                    │
│                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────┐ │
│  │  Ingestion   │  │  Analysis    │  │ Legal KB  │ │
│  │  (ingest.py) │→ │ (analyzer.py)│←→│(legal_kb  │ │
│  │              │  │              │  │  .py)     │ │
│  │ - URL fetch  │  │ - Rule-based │  │ numpy +   │ │
│  │ - File parse │  │ - LLM calls  │  │ BM25/RRF  │ │
│  │ - Text norm  │  │ - Scoring    │  │           │ │
│  └──────────────┘  └──────────────┘  └───────────┘ │
│         ↓                   ↓                       │
│  ┌──────────────────────────────────┐              │
│  │       Database (SQLite)          │              │
│  │     data/terms_analysis.db       │              │
│  │                                  │              │
│  │  - Analysis (incl. result_json)  │              │
│  │  - ReviewItem                    │              │
│  │  - WatchlistItem (OE-003 merged) │              │
│  │  - PolicySnapshot                 │              │
│  └──────────────────────────────────┘              │
└─────────────────────────────────────────────────────┘
                        ↓ HTTP/REST
┌─────────────────────────────────────────────────────┐
│                LocalAI (Local LLM)                  │
│         http://localhost:8080/v1                    │
│                                                     │
│  - Models: Apertus-8B-Instruct / EuroLLM-22B-Instruct│
│  - Inference: Local GPU/CPU                         │
│  - No data sent to cloud                            │
└─────────────────────────────────────────────────────┘
```

Note: `services/embedding.py` (BM25 + dense RRF chunk selection for over-length *documents*) is a separate module from `legal_kb.py` (retrieval over the embedded *legal corpus*) — both are wired into `analyzer.py::analyze_text()`.

### Database Schema

Actual schema (`src/backend/app/models.py`) is a single denormalized `Analysis` row per analysis (findings stored as a JSON blob) plus review/watchlist/snapshot tables — not the normalized `analyses`/`findings` design originally specified below:

#### Table: `analyses` (model: `Analysis`)

```sql
CREATE TABLE analyses (
    id TEXT PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    doc_name TEXT,
    doc_type TEXT,
    source_url TEXT,
    source_type TEXT,       -- 'url', 'file', 'text'
    source_value TEXT,
    status TEXT DEFAULT 'completed',
    confidence REAL NOT NULL,
    risk_score REAL NOT NULL,
    grade TEXT NOT NULL,
    document_text TEXT NOT NULL,
    result_json TEXT NOT NULL  -- full findings payload, serialized JSON
);
```

#### Table: `review_items` (model: `ReviewItem`)

```sql
CREATE TABLE review_items (
    id TEXT PRIMARY KEY,
    analysis_id TEXT NOT NULL,
    status TEXT DEFAULT 'pending', -- 'pending', 'approved', 'rejected'
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (analysis_id) REFERENCES analyses(id) ON DELETE CASCADE
);
```

#### Table: `watchlist_items` (model: `WatchlistItem`) — v2.4 OE-003 merged shape

The four merged columns (`user_id`, `check_frequency`, `enabled`, `created_at`) plus `notes` are the OE-003 fold-in — see PRD Change History v2.4 and `docs/reports/user-decision-brief-2026-07-03.md` A3.

```sql
CREATE TABLE watchlist_items (
    id TEXT PRIMARY KEY,
    vendor TEXT NOT NULL,
    source_url TEXT,
    status TEXT NOT NULL DEFAULT 'No Changes',
    -- OE-003 merged columns (previously on the retired ``policy_watches`` table):
    user_id TEXT,                              -- nullable; opaque user id for multi-tenant deployments
    check_frequency INTEGER NOT NULL DEFAULT 86400,  -- per-item refresh cadence in seconds, honored by _watchlist_loop_async
    enabled BOOLEAN NOT NULL DEFAULT TRUE,     -- proper boolean (LE-010 fix — PolicyWatch stored the string "true")
    notes TEXT,                                -- free-text notes / tags
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- Existing diff / risk columns:
    last_checked TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    changes_since TIMESTAMP,
    change_count INTEGER NOT NULL DEFAULT 0,
    risk_delta REAL NOT NULL DEFAULT 0.0,
    change_summary TEXT,
    last_document_text TEXT,
    last_document_hash TEXT,
    last_risk_score REAL,
    last_analysis_id TEXT,
    FOREIGN KEY (last_analysis_id) REFERENCES analyses(id)
);
```

#### Table: `policy_snapshots` (model: `PolicySnapshot`)

```sql
CREATE TABLE policy_snapshots (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    raw_text TEXT NOT NULL
);
```

**Note (v2.4, 2026-07-03):** the legacy `policy_watches` table was retired when its rows were folded into `watchlist_items` under OE-003. Existing deployments run `src/backend/scripts/migrate_policywatch_to_watchlist.py` to migrate rows before dropping the table. The migration is idempotent — matched rows update in place (nullable columns are filled without overwriting diff-side values); orphan rows insert new `watchlist_items` with the URL hostname synthesized as `vendor`.

### API Endpoints Specification

#### POST `/analyze`

**Description:** Analyze pasted text

**Request:** `AnalyzeRequest` (see `src/backend/app/schemas.py:167-192`).

```json
{
  "text": "string (required, min 1 char, server-side truncated to MAX_INPUT_CHARS = 20000 by default)",
  "name": "string (optional)",
  "doc_type": "Privacy Policy | Terms of Service | Cookie Policy | Data Processing Agreement | Combined",
  "industry": "General | Retail | Finance | Healthcare | Gaming | Social Media | AI / Tech Platform | Education",
  "source_url": "http(s) URL (optional; javascript: / data: / vbscript: schemes rejected at the schema layer)",
  "jurisdictions": ["US-CA", "GDPR", "..."],
  "mode": "full | quick",
  "context": ["want_understand | for_child | for_care | for_work | just_curious"]
}
```

- `jurisdictions=[]` is treated as **no filter** (global-tool contract; no US-CA + GDPR default). Location dropdowns in the intake default to blank.
- `context` values are validated against `frozenset(get_args(ContextChip))` — the schema-derived allowlist in `main.py`. Invalid chips return 400.

**Response (200 OK):** `AnalysisPayload` (see `src/backend/app/schemas.py:220-262`). Example:

```json
{
  "id": "uuid",
  "name": "Example Privacy Policy",
  "doc_type": "Privacy Policy",
  "industry": "General",
  "source_url": "https://example.com/privacy",
  "status": "completed",
  "review_required": false,
  "confidence": 0.85,
  "risk_score": 6.8,
  "grade": "C+",
  "created_at": "2026-02-13T20:49:00Z",
  "analysis_mode": "full",
  "estimated_time": 12.4,
  "summary": "...",
  "action_readiness": "Review",
  "completeness": 0.75,
  "context": ["want_understand"],
  "jurisdictions": ["US-CA", "GDPR"],
  "verdict_headline": "There are a few things here worth a closer read.",
  "verdict_label": "Worth a closer read",
  "top_by_domain": {
    "Data": [ /* up to 2 Finding objects */ ],
    "Data use": [ /* up to 2 Finding objects */ ],
    "Terms of use": [ /* up to 2 Finding objects */ ],
    "Privacy rights": [ /* up to 2 Finding objects */ ]
  },
  "action_items": [
    "Consider requesting your data export before signing up.",
    "This policy allows advertising use — check if you can opt out."
  ],
  "findings": [
    {
      "category": "Sale/Share",
      "severity": "High",
      "confidence": 0.86,
      "excerpt": "We may share personal information...",
      "explanation": "This policy allows...",
      "impact": 4,
      "likelihood": 4,
      "safeguard_score": 2,
      "irp_score": 0.68,
      "evidence": {
        "line_start": 120,
        "line_end": 126,
        "legal_basis": ["CCPA § 1798.115"]
      },
      "jurisdictions": ["US-CA"],
      "needs_review": false
    }
  ]
}
```

**AnalysisPayload — v2 fields (shipped in PR #34):**

The following 8 fields were added to `AnalysisPayload` alongside the plain-language redesign (issue #19). Type sources: `src/backend/app/schemas.py:220-262`.

| Field | Type | Default | Semantics |
|-------|------|---------|-----------|
| `action_readiness` | `Literal["Go", "Review", "Stop"]` | `"Review"` | High-level recommendation. `Go` = low risk + high completeness; `Stop` = high risk; `Review` = everything in between. Feeds the results-view verdict chip and the "Needs Review" badge (F4.1). |
| `completeness` | `float` in `[0.0, 1.0]` | `0.0` | Fraction of expected policy sections detected. Checklist: user rights, retention, contact, opt-out, ADM, security, third-party, minors. Computed by `analyzer._compute_completeness`. |
| `context` | `List[ContextChip]` | `[]` | Echo of the reader's context chip selections from the intake (`want_understand`, `for_child`, `for_care`, `for_work`, `just_curious`). Values are validated against `frozenset(get_args(ContextChip))` at request time. See LIB-CONTEXT §Chip taxonomy. |
| `jurisdictions` | `List[Jurisdiction]` | `[]` | Jurisdiction codes the analysis was filtered against — echoes the request so the UI can display "Rules applied for: ...". Empty list explicitly means "no filter" (global-tool contract). |
| `verdict_headline` | `Optional[str]` | `None` | Context-appropriate verdict sentence rendered on the results overview. Composed by `services/context.py::verdict_headline(context, action_readiness)`. Rotation semantics: strongest chip in priority order (`for_child` > `for_care` > `for_work` > `want_understand` > `just_curious`) selects the copy variant. LIB-VOICE governs tone (tentative framings, no em-dashes, no directive "you should"). |
| `verdict_label` | `Optional[str]` | `None` | Short chip label variant of the verdict (e.g. `"Worth a closer read"`, `"Looks manageable"`). Same rotation semantics as `verdict_headline`. Never a letter grade — LIB-VOICE forbids grade-as-label. |
| `top_by_domain` | `dict[str, list[Finding]]` | `{}` | Top findings grouped into the 4 fixed domains: `"Data"` (collection), `"Data use"`, `"Terms of use"`, `"Privacy rights"`. Max 2 findings per domain, 8 total. Category-to-domain mapping lives in `analyzer._DOMAIN_MAP`. Hardware permissions (camera / mic / contacts / location) are scope caveats only and are never a domain here. |
| `action_items` | `List[str]` | `[]` | Backend-generated reader-actionable next steps derived from findings + jurisdictions. Backend-side derivation keeps the frontend thin — `app_streamlit_v2.py` renders these verbatim. Copy MUST follow LIB-VOICE (tentative framing, no em-dashes). |

Note: `AnalysisPayload` also carries `document_text` (optional), `line_offsets` (for Verify View coordinate mapping), `summary`, `analysis_mode`, and `estimated_time`. `findings_count` in the JSON example above is derived by the frontend from `findings[]` — it is not a shipped field on the schema.

**Error Responses:**
- `400 Bad Request`: Invalid input (missing text, invalid jurisdiction / chip against the schema-derived allowlists)
- `413 Payload Too Large`: Text exceeds `MAX_INPUT_CHARS` (default 20,000 — see §API Notes on limits)
- `500 Internal Server Error`: Analysis failed
- `503 Service Unavailable`: LocalAI unreachable

#### POST `/analyze/url`

**Description:** Analyze document from URL

**Request:** `AnalyzeUrlRequest` (see `src/backend/app/schemas.py:195-217`).

```json
{
  "url": "https://example.com/privacy (required, http or https only)",
  "name": "string (optional)",
  "doc_type": "string (optional)",
  "industry": "string (optional)",
  "jurisdictions": ["array (optional; empty = no filter)"],
  "mode": "full | quick",
  "context": ["...ContextChip values..."]
}
```

- No US-CA + GDPR default fallback — an empty `jurisdictions` array means "no filter" (global-tool contract).
- `javascript:` / `data:` / `vbscript:` schemes are rejected at the schema layer via `_validate_url_scheme`; SSRF-target rejection happens downstream in `ingest._validate_url`.

**Response:** `AnalysisPayload` (same as `/analyze`).

**Error Responses:**
- `400 Bad Request`: Invalid URL format or non-http(s) scheme
- `404 Not Found`: URL unreachable or returns 404
- `408 Request Timeout`: URL fetch timeout (see `LM_URL_FETCH_TIMEOUT_S`, default 30 seconds — distinct from `LM_REQUEST_TIMEOUT_S`, which governs LLM inference)
- `422 Unprocessable Entity`: Unable to extract text from URL

#### POST `/analyze/file`

**Description:** Analyze uploaded file

**Request:** `multipart/form-data`
- `file`: File (required, max 10MB)
- `name`: string (optional)
- `doc_type`: string (optional)
- `jurisdictions`: comma-separated string (optional)
- `industry`: string (optional)

**Response:** Same as `/analyze`

**Error Responses:**
- `400 Bad Request`: No file provided
- `413 Payload Too Large`: File exceeds 10MB
- `415 Unsupported Media Type`: File type not supported
- `422 Unprocessable Entity`: Unable to extract text from file

#### GET `/analyses`

**Description:** List all analyses (paginated)

**Query Parameters:**
- `limit`: integer (default: 20, max: 100)
- `offset`: integer (default: 0)
- `sort`: "created_at" | "risk_score" | "grade" (default: created_at)
- `order`: "asc" | "desc" (default: desc)
- `filter_grade`: "A" | "B" | "C" | "D" | "F"
- `filter_review_required`: boolean

**Response:**
```json
{
  "total": 42,
  "limit": 20,
  "offset": 0,
  "analyses": [
    {
      "id": "uuid",
      "name": "Example Privacy Policy",
      "doc_type": "Privacy Policy",
      "risk_score": 6.8,
      "grade": "C+",
      "confidence": 0.85,
      "review_required": false,
      "findings_count": 12,
      "jurisdictions": ["US-CA", "GDPR"],
      "created_at": "2026-02-13T20:49:00Z"
    }
  ]
}
```

#### GET `/analyses/{id}`

**Description:** Get specific analysis with full details

**Response:** Same as POST `/analyze` response

**Error Responses:**
- `404 Not Found`: Analysis ID does not exist

#### GET `/reviews`

**Description:** Get review queue (findings with confidence <0.80)

**Response:**
```json
{
  "pending_count": 5,
  "reviews": [
    {
      "id": "uuid",
      "analysis_id": "uuid",
      "analysis_name": "Example Policy",
      "finding": { /* finding object */ },
      "status": "pending",
      "created_at": "2026-02-13T20:50:00Z"
    }
  ]
}
```

#### POST `/reviews/{id}`

**Description:** Approve, reject, or edit finding under review

**Request:**
```json
{
  "action": "approve | reject | edit",
  "notes": "string (optional)",
  "edits": { /* if action=edit */
    "category": "string (optional)",
    "severity": "string (optional)",
    "excerpt": "string (optional)"
  }
}
```

**Response:**
```json
{
  "success": true,
  "review_id": "uuid",
  "status": "approved | rejected",
  "updated_at": "2026-02-13T21:00:00Z"
}
```

#### GET `/watchlist`

**Description:** List all watchlist items. Returns a JSON array of `WatchlistItemPayload` records (see `POST /watchlist` for the field-by-field response shape). Ordered by `last_checked DESC`.

**Response (shape per item — v2.4 OE-003 merged model):**
```json
[
  {
    "id": "uuid",
    "vendor": "Google",
    "source_url": "https://policies.google.com/privacy",
    "status": "No Changes",
    "last_checked": "2026-07-03T12:00:00Z",
    "changes_since": null,
    "change_count": 0,
    "risk_delta": 0.0,
    "change_summary": null,
    "user_id": "alex@example.com",
    "check_frequency": 604800,
    "enabled": true,
    "notes": "Weekly cadence for the CCPA change tracker.",
    "created_at": "2026-07-03T12:00:00Z",
    "next_check_at": "2026-07-10T12:00:00Z"
  }
]
```

#### POST `/watchlist`

**Description:** Add a vendor + URL to the watchlist. Subject is the vendor and URL (not a prior analysis id). Backed by `WatchlistCreateRequest` in `src/backend/app/schemas.py` — see F6.1 for the full field-by-field acceptance contract.

**Request (v2.4 shipped shape, OE-003 merged model):**
```json
{
  "vendor": "Google",
  "source_url": "https://policies.google.com/privacy",
  "check_frequency": 604800,
  "enabled": true,
  "user_id": "alex@example.com",
  "notes": "Weekly cadence for the CCPA change tracker. See analysis 8f2a-…"
}
```

Field notes:
- `vendor` (str, required, min length 1) — display name shown in the watchlist dashboard.
- `source_url` (Optional[str]) — must use http or https and include a hostname. `javascript:` / `data:` / `vbscript:` schemes are rejected at the schema layer.
- `check_frequency` (Optional[int], seconds, 300 to 604800) — per-item refresh cadence. UI dropdown mapping: daily = 86400, weekly = 604800, monthly = 2592000. Omit to accept the ORM default (86400s / 24h). Honored by `_watchlist_loop_async` (previously carried on `PolicyWatch` and silently ignored — see OE-003).
- `enabled` (Optional[bool], default `True`) — when False the background refresh loop skips this item. Boolean, not string (LE-010 fix).
- `user_id` (Optional[str], max 255, alphanumeric + `@._-`) — opaque user identifier; nullable so single-user deployments do not need to set it.
- `notes` (Optional[str], max 1024) — free-text notes. Callers who want to link back to a prior analysis include the id here (or set it out-of-band on `WatchlistItem.last_analysis_id` after the first refresh).

**Response:** `WatchlistItemPayload`

```json
{
  "id": "uuid",
  "vendor": "Google",
  "source_url": "https://policies.google.com/privacy",
  "status": "No Changes",
  "last_checked": "2026-07-03T12:00:00Z",
  "changes_since": null,
  "change_count": 0,
  "risk_delta": 0.0,
  "change_summary": null,
  "user_id": "alex@example.com",
  "check_frequency": 604800,
  "enabled": true,
  "notes": "Weekly cadence for the CCPA change tracker. See analysis 8f2a-…",
  "created_at": "2026-07-03T12:00:00Z",
  "next_check_at": "2026-07-10T12:00:00Z"
}
```

`next_check_at` is computed at response-render time as `last_checked + check_frequency` (falls back to the global `settings.watchlist_refresh_seconds` when the item omitted `check_frequency`, per `_effective_check_frequency`). Returns `null` when `enabled=False`.

**Deprecated companion:** the `/policy-watch/*` endpoint family was merged into `/watchlist/*` on 2026-07-03 (OE-003). See the deprecation-shim block below for the 308 / 410 response contract.

#### GET `/exports/analysis/{id}.pdf`

**Description:** Export analysis as PDF

**Response:** Binary PDF file with `Content-Disposition: attachment`

#### GET `/exports/analysis/{id}.json`

**Description:** Export analysis as JSON

**Response:** JSON file with full analysis data

#### GET `/exports/analyses.csv`

**Description:** Export multiple analyses as CSV

**Query Parameters:**
- `ids`: comma-separated analysis IDs (optional, default: all)
- `detailed`: boolean (default: false) - include findings or just summary

**Response:** CSV file with `Content-Disposition: attachment`

#### Additional shipped endpoints not in the original spec

These exist in `main.py` and are documented here for completeness (JSON shapes follow the same conventions as the endpoints above):

- `POST /analyze/batch` — analyze multiple documents in one request with cross-reference detection (`AnalyzeBatchRequest` -> `BatchAnalysisResult`). **API-only for this release:** consumers are expected to script their own progress tracking and export formatting. Batch UI (CSV upload, progress bar, sortable results table, "Export All as CSV" button) is deferred as a P2 follow-up, tracked separately [issue TBD, link once filed]. Optional CSV-in/CSV-out helper at `src/backend/scripts/batch_analyze.py`. See §6.2 Flow 2 for full researcher narrative and sample payload.
- `POST /infer` — **shipped in PR #34.** Accepts a URL and/or policy text and returns inferred `jurisdictions`, `doc_type`, `industry`, plus `location_needed` (bool) and `detected_signals` (dict). TLD-based jurisdiction inference + statute / regulatory-body / geographic keyword scan. Text capped at 200,000 chars (`schemas.py:339`); `@lru_cache` on hot paths; pre-compiled regexes; observability logging. Request: `InferRequest`; response: `InferResponse` (`src/backend/app/schemas.py:334-358`).
- `GET /rubric` — aggregate rubric scores across analyses
- `GET/POST /snapshots`, `GET /snapshots/detail/{id}` — capture/list historical policy snapshots (SHA-256 deduplicated)
- `GET /diff/{snapshot_id_1}/{snapshot_id_2}` — token-level diff between two snapshots, with keyword-based severity classification
- `POST/GET /policy-watch`, `DELETE /policy-watch/{id}` — **deprecated (OE-003, 2026-07-03).** Return `308 Permanent Redirect` to `/watchlist`, `/watchlist`, `/watchlist/{id}` respectively, with headers `Deprecation: true`, `Sunset: 2026-10-01`, and `Link: </watchlist>; rel="successor-version"`. 308 (vs 301) preserves the HTTP method and request body — a client POSTing to `/policy-watch` will replay to `/watchlist`, though the field rename (`url` -> `source_url`) means clients that depended on the old field name must update their request payload. `POST /policy-watch/{id}/snapshot` returns `410 Gone` (the id lookup no longer resolves after the merge; a redirect to `/watchlist/{id}/refresh` would 404 in the general case). Migration script for existing `policy_watches` rows: `src/backend/scripts/migrate_policywatch_to_watchlist.py`.

### LLM Integration Specification

#### LocalAI Configuration

**Requirements:**
- LocalAI running locally on same network
- Model loaded (recommended: LocalAI model (Apertus 8B or EuroLLM 22B))
- API endpoint: `http://localhost:8080/v1` (configurable via `LOCALAI_BASE_URL`)
- Model env vars: `MODEL_WORLD` for Apertus 8B, `MODEL_EU` for EuroLLM 22B
- **Legal-KB augmentation:** before the LLM call, `analyzer.py` retrieves relevant legal-corpus passages via `legal_kb.py` (numpy-exhaustive + BM25/RRF over `data/legal_corpus/`) and injects them into the prompt as citable context (see `prompts.py::build_user_prompt`'s `legal_context` parameter). Degrades to no augmentation if the index hasn't been built or LocalAI is unreachable.
- **Operational note:** `run.sh`/`.env.example` previously set unrelated `LM_STUDIO_*` variables that never wired into these settings — fixed so `run.sh` now exports `LOCALAI_BASE_URL`/`MODEL_WORLD`/`MODEL_EU` directly.

**Model Selection Criteria:**
- Context window: ≥8K tokens (for long documents)
- Instruction-following capability
- JSON output support
- Speed: <10 seconds inference for 2K token input

#### Prompt Template

**System Prompt:**
```
You are a privacy and legal policy analyzer. Your task is to identify risky clauses in Terms of Service and Privacy Policies.

Analyze the provided policy text and identify clauses that fall into these categories:
1. Data Sharing: Third-party sales, data broker relationships
2. Automated Decisions: ADM/profiling without human review
3. Dark Patterns: Deceptive consent, hidden opt-outs
4. Retention: Indefinite storage, vague deletion
5. User Rights: Missing access/correction/deletion rights
6. Minors: Inadequate child protections
7. Sensitive Data: Biometrics, health, financial data
8. Unilateral Changes: Terms modifications without notice
9. Liability: Excessive disclaimers, forced arbitration

For each finding, provide:
- category: One of the 9 categories above
- severity: High | Medium | Low
- confidence: 0.0-1.0 (how certain are you?)
- excerpt: The specific clause (1-3 sentences, max 500 chars)
- explanation: Plain language explanation (2-4 sentences, max 300 chars)
- impact: 1-5 (severity of potential harm)
- likelihood: 1-5 (probability clause will be exercised)
- safeguards: 1-5 (protections in place)
- line_start: Line number where clause begins
- line_end: Line number where clause ends
- legal_basis: Array of applicable regulations (e.g., ["CCPA § 1798.115"])
- jurisdictions: Array of applicable jurisdictions (e.g., ["US-CA", "GDPR"])

Output ONLY valid JSON. No markdown, no explanations outside JSON.
```

**User Prompt (with line numbers):**
```
Analyze this policy for jurisdiction(s): US-CA, GDPR
Document type: Privacy Policy
Industry: General

=== POLICY TEXT (line numbered) ===
1: Privacy Policy
2:
3: Last updated: January 1, 2026
4:
5: Introduction
6: This Privacy Policy describes how Example Company ("we", "us", "our") collects,
7: uses, and shares your personal information.
...
120: Data Sharing
121: We may share your personal information with third-party partners for marketing
122: purposes. These partners may use your data to send you promotional offers.
123: You can opt out by contacting us at privacy@example.com.
...

=== END POLICY TEXT ===

Provide findings as JSON array:
[
  {
    "category": "Data Sharing",
    "severity": "High",
    "confidence": 0.86,
    "excerpt": "We may share your personal information with third-party partners for marketing purposes.",
    "explanation": "This policy allows the company to share your data with third parties for marketing. Under California law (CCPA), you have the right to opt out of data sales.",
    "impact": 4,
    "likelihood": 4,
    "safeguards": 2,
    "line_start": 121,
    "line_end": 123,
    "legal_basis": ["CCPA § 1798.115", "CCPA § 1798.120"],
    "jurisdictions": ["US-CA"]
  }
]
```

#### Fallback Strategy

**If LocalAI fails:**
1. Use rule-based detection only
2. Lower confidence scores by 0.15
3. Flag analysis for review
4. Log error for debugging
5. Continue with results (don't block user)

**If LocalAI returns invalid JSON:**
1. Attempt to fix common issues (extra text, missing brackets)
2. If unfixable, use rule-based results only
3. Lower confidence, flag for review

**If LocalAI times out (>60 seconds):**
1. Cancel request
2. Use rule-based results only
3. Show warning to user: "Analysis took longer than expected. Results may be less comprehensive."

---

## Acceptance Criteria & Testing

### MVP Acceptance Criteria

**Must Have (P0):**
- [ ] User can analyze documents via URL, file upload, or text paste
- [ ] System supports PDF, DOCX, RTF, HTML, TXT formats
- [x] System detects the 9 core risk categories (expanded to ~50 in practice) with 80%+ accuracy
- [x] System calculates a per-finding IRP (Impact / Likelihood / Safeguards) composite score, aggregates to an overall 0-10 risk score, and assigns a letter grade from the 7-band shipped scale (A / A- / B / B- / C+ / C / D+) — shipped in PR #34 (see §F3.1)
- [ ] System displays findings with excerpts and explanations
- [ ] User can view findings in Verify view with highlighting
- [ ] User can export analysis as PDF
- [ ] System completes analysis in <30 seconds (typical document)
- [ ] System runs locally without cloud uploads
- [ ] UI is keyboard accessible (WCAG AA)

**Should Have (P1):**
- [ ] User can add documents to watchlist
- [ ] System detects policy changes automatically
- [ ] User can compare 2-3 vendors side-by-side
- [ ] System supports CSV export for bulk analysis
- [ ] UI supports dark mode

**Could Have (P2):**
- [ ] Browser extension for one-click analysis
- [ ] API for third-party integration
- [ ] Team accounts with shared workspaces
- [ ] Custom rubric configuration
- [ ] Historical version tracking

### Test Plan

#### Unit Tests

**Ingestion Service:**
- [ ] `test_url_fetch_success()` - Valid URL returns text
- [ ] `test_url_fetch_404()` - 404 URL raises error
- [ ] `test_url_timeout()` - Timeout after 30 seconds
- [ ] `test_pdf_extraction()` - PDF text extracted correctly
- [ ] `test_docx_extraction()` - DOCX text extracted correctly
- [ ] `test_scanned_pdf_ocr()` - OCR fallback works
- [ ] `test_file_size_limit()` - Files >10MB rejected
- [ ] `test_text_normalization()` - Line breaks preserved

**Analysis Service:**
- [ ] `test_irp_calculation()` - IRP formula correct
- [ ] `test_grade_assignment()` - Grades match IRP ranges
- [ ] `test_rule_based_detection()` - Regex patterns match
- [ ] `test_llm_integration()` - LocalAI called correctly
- [ ] `test_confidence_scoring()` - Confidence calculated correctly
- [ ] `test_review_threshold()` - <0.80 triggers review
- [ ] `test_jurisdiction_filtering()` - Findings filtered by jurisdiction
- [ ] `test_evidence_binding()` - Line numbers stored

#### Integration Tests

- [ ] `test_end_to_end_url()` - URL → Analysis → Results
- [ ] `test_end_to_end_file()` - File Upload → Analysis → Results
- [ ] `test_llm_failure_fallback()` - Rule-only if LocalAI down
- [ ] `test_export_pdf()` - PDF generates correctly
- [ ] `test_export_json()` - JSON structure valid
- [ ] `test_watchlist_workflow()` - Add → Check → Notify

#### Accuracy Tests (Gold Dataset)

**Dataset:**
- 100 real privacy policies and ToS
- Manually labeled by legal expert
- Ground truth: All risky clauses identified, categorized, severity assigned

**Metrics:**
- **Precision:** % of detected clauses that are truly risky
- **Recall:** % of true risky clauses detected
- **F1 Score:** Harmonic mean of precision and recall
- **Target:** F1 ≥ 0.85, Precision ≥ 0.90, Recall ≥ 0.85

**Per-Category Accuracy:**
- Data Sharing: F1 ≥ 0.90 (high priority)
- Automated Decisions: F1 ≥ 0.85
- Dark Patterns: F1 ≥ 0.80 (hard to detect)
- Retention: F1 ≥ 0.85
- User Rights: F1 ≥ 0.90 (high priority)
- Minors: F1 ≥ 0.85
- Sensitive Data: F1 ≥ 0.88
- Unilateral Changes: F1 ≥ 0.85
- Liability: F1 ≥ 0.87

**Evaluation Process:**
1. Run all 100 documents through system
2. Compare results to ground truth
3. Calculate precision, recall, F1 per category and overall
4. Identify false positives and false negatives
5. Analyze error patterns
6. Iterate on rules and prompts
7. Third-party legal expert reviews sample (20 random documents)
8. Expert validates accuracy ≥85% agreement

#### Usability Tests

**Participants:** 5 users per persona (15 total)

**Tasks:**
1. Analyze a privacy policy from URL
2. Find and explain a high-risk finding
3. View finding in context (Verify view)
4. Export results as PDF
5. Add document to watchlist

**Success Metrics:**
- Task completion rate: ≥90%
- Time to complete Task 1: <3 minutes
- Time to find high-risk finding: <1 minute
- SUS (System Usability Scale) score: ≥70
- NPS (Net Promoter Score): ≥40

**Questions:**
- "How easy was it to understand the risk score?" (1-5)
- "How confident are you in the accuracy of findings?" (1-5)
- "Would you use this tool before accepting terms?" (Yes/No)
- "Would you recommend this to others?" (NPS)

#### Performance Tests

**Load Testing:**
- 10 concurrent users analyzing documents
- Backend handles 10 requests without degradation
- Response time: <30 seconds for typical document
- Database queries: <100ms

**Stress Testing:**
- 50 concurrent users
- System degrades gracefully (queue requests)
- No crashes or data corruption

**Document Size Testing:**
- Small document (1,000 words): <10 seconds
- Medium document (5,000 words): <20 seconds
- Large document (10,000 words): <30 seconds
- Very large document (20,000 words): <60 seconds or show warning

---

## UI/UX Specifications

### Design System

#### Color Palette

**Primary Colors:**
- Primary Blue: `#2563EB` (buttons, links)
- Dark Blue: `#1E40AF` (hover states)
- Light Blue: `#DBEAFE` (backgrounds)

**Semantic Colors:**
- Success Green: `#10B981` (A/B grades, positive actions)
- Warning Yellow: `#F59E0B` (C grade, cautions)
- Danger Red: `#EF4444` (D/F grades, high severity)
- Info Blue: `#3B82F6` (informational notices)

**Neutrals:**
- Gray 900: `#111827` (headings)
- Gray 700: `#374151` (body text)
- Gray 500: `#6B7280` (secondary text)
- Gray 300: `#D1D5DB` (borders)
- Gray 100: `#F3F4F6` (backgrounds)
- White: `#FFFFFF`

**Dark Mode:**
- Background: `#1F2937`
- Surface: `#374151`
- Text: `#F9FAFB`
- Border: `#4B5563`

#### Typography

**Font Family:**
- System font stack: `-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif`
- Monospace (code): `'SF Mono', 'Monaco', 'Courier New', monospace`

**Type Scale:**
- H1: 36px, font-weight 700, line-height 1.2
- H2: 30px, font-weight 700, line-height 1.3
- H3: 24px, font-weight 600, line-height 1.4
- H4: 20px, font-weight 600, line-height 1.4
- Body: 16px, font-weight 400, line-height 1.5
- Small: 14px, font-weight 400, line-height 1.5
- Tiny: 12px, font-weight 400, line-height 1.4

#### Spacing

**Scale (rem):**
- 0.25rem (4px)
- 0.5rem (8px)
- 0.75rem (12px)
- 1rem (16px)
- 1.5rem (24px)
- 2rem (32px)
- 3rem (48px)
- 4rem (64px)

**Component Spacing:**
- Button padding: 12px 24px
- Card padding: 24px
- Section margin: 48px
- Input padding: 12px 16px

#### Components

**Buttons:**
- Primary: Blue background, white text, rounded 8px
- Secondary: Gray border, gray text, rounded 8px
- Danger: Red background, white text, rounded 8px
- Disabled: Gray background, gray text, cursor not-allowed
- Hover: Darken by 10%
- Focus: 2px outline, offset 2px

**Cards:**
- Background: White (light) / Gray 800 (dark)
- Border: 1px solid Gray 300 (light) / Gray 700 (dark)
- Border radius: 12px
- Shadow: 0 1px 3px rgba(0,0,0,0.1)
- Padding: 24px

**Inputs:**
- Border: 1px solid Gray 300
- Border radius: 8px
- Padding: 12px 16px
- Focus: 2px blue outline
- Error: Red border, red helper text
- Disabled: Gray background, cursor not-allowed

**Badges:**
- High Severity: Red background, white text, rounded full
- Medium Severity: Yellow background, gray text, rounded full
- Low Severity: Green background, white text, rounded full
- Padding: 4px 12px
- Font size: 12px, font-weight 600

### Accessibility Requirements

**WCAG 2.2 Level AA Compliance:**

**Color Contrast:**
- [ ] Text: 4.5:1 minimum (body text)
- [ ] Large text (18px+): 3:1 minimum
- [ ] UI components: 3:1 minimum
- [ ] Use tools: WebAIM Contrast Checker

**Keyboard Navigation:**
- [ ] All interactive elements keyboard accessible
- [ ] Logical tab order (top to bottom, left to right)
- [ ] Visible focus indicators (2px outline)
- [ ] No keyboard traps
- [ ] Shortcuts: `Ctrl+K` (search), `Ctrl+E` (export), `Esc` (close modals)

**Screen Reader Support:**
- [ ] Semantic HTML (nav, main, article, aside)
- [ ] ARIA labels for icons and controls
- [ ] ARIA live regions for dynamic content
- [ ] Alt text for all images
- [ ] Form labels properly associated

**Touch Targets:**
- [ ] Minimum size: 44×44px
- [ ] Spacing: 8px between targets
- [ ] Responsive design: Mobile-first

**Responsive Breakpoints:**
- Mobile: <640px
- Tablet: 640px-1024px
- Desktop: >1024px

---

## Success Metrics & KPIs

### Product Metrics (Week 1-4 Post-Launch)

**Activation:**
- [ ] 60% of signups complete first analysis within 24 hours
- [ ] Average time to first analysis: <5 minutes
- [ ] 80% of analyses succeed without errors

**Engagement:**
- [ ] Average analyses per user: ≥3 per month
- [ ] Return rate (7-day): ≥30%
- [ ] Return rate (30-day): ≥20%
- [ ] Verify view usage: ≥40% of users

**Quality:**
- [ ] Detection accuracy: F1 ≥0.85
- [ ] Average confidence: ≥0.85
- [ ] Review queue backlog: <10% of findings
- [ ] Error rate: <5% of analyses

### User Satisfaction (Month 3, 6, 12)

- [ ] NPS: ≥40 (target: 50+)
- [ ] SUS Score: ≥70 (target: 80+)
- [ ] "Would use again": ≥80%
- [ ] "Would recommend": ≥70%

### Performance (Continuous Monitoring)

- [ ] Average analysis time: <30 seconds (p50)
- [ ] 95th percentile: <45 seconds
- [ ] Page load time: <3 seconds
- [ ] API response time (p95): <500ms
- [ ] System uptime: ≥99.5%

---

## Launch Readiness Checklist

### Pre-Launch (T-4 weeks)

**Development:**
- [ ] All P0 features complete and tested
- [ ] Unit test coverage ≥80%
- [ ] Integration tests passing
- [ ] Accuracy evaluation complete (F1 ≥0.85)
- [ ] Performance tests passing
- [ ] Security audit complete

**Legal & Compliance:**
- [ ] Terms of Service drafted and reviewed
- [ ] Privacy Policy published
- [ ] Disclaimers prominently displayed
- [ ] Professional liability insurance obtained ($2M)
- [ ] Third-party legal accuracy audit complete

**Documentation:**
- [ ] User guide published
- [ ] API documentation complete (if applicable)
- [ ] FAQ page created
- [ ] Video tutorials produced (2-3 minutes each)
- [ ] Methodology whitepaper published

**Infrastructure:**
- [ ] Production environment configured
- [ ] Database backups automated
- [ ] Monitoring and alerting setup (Sentry, logs)
- [ ] CDN configured for static assets
- [ ] SSL certificate installed

### Beta Launch (T-2 weeks)

- [ ] 50 beta testers recruited
- [ ] Beta feedback collected (NPS, SUS, qualitative)
- [ ] Critical bugs fixed
- [ ] UI/UX improvements implemented
- [ ] Testimonials collected

### Public Launch (T-0)

- [ ] Launch blog post published
- [ ] Product Hunt launch scheduled
- [ ] Hacker News post drafted
- [ ] Reddit posts in r/privacy, r/opensource
- [ ] Twitter/Mastodon announcements
- [ ] Email to waitlist (if any)
- [ ] Press release to tech media
- [ ] Demo video published on YouTube

### Post-Launch (T+1 week)

- [ ] Monitor analytics daily
- [ ] Respond to user feedback
- [ ] Fix critical bugs within 24 hours
- [ ] Collect testimonials
- [ ] Iterate on feedback

---

## Appendices

### Appendix A: Wireframe References

1. **Input View:** `docs/wireframes/reviewer_wireframe_v2.png`
2. **Results View:** `docs/wireframes/reviewer_wireframe_v2.png`
3. **Verify View:** `docs/wireframes/reviewer_wireframe_v2.png`
4. **Dashboard:** `docs/wireframes/dashboard_wireframe_v2.png`

### Appendix B: Sample Findings

**Example 1: Data Sharing (High Severity)**
```json
{
  "category": "Data Sharing",
  "severity": "High",
  "confidence": 0.88,
  "excerpt": "We may share your personal information with third-party advertising partners who may use it to deliver targeted ads across the internet.",
  "explanation": "This policy allows the company to share your data with advertisers. Under CCPA, you have the right to opt out of this data sharing. Look for a 'Do Not Sell My Personal Information' link on their website.",
  "impact": 4,
  "likelihood": 5,
  "safeguards": 2,
  "irp_score": 0.82,
  "legal_basis": ["CCPA § 1798.120", "GDPR Art. 6"],
  "jurisdictions": ["US-CA", "GDPR"]
}
```

**Example 2: Forced Arbitration (High Severity)**
```json
{
  "category": "Liability",
  "severity": "High",
  "confidence": 0.91,
  "excerpt": "You agree to resolve any disputes through binding arbitration and waive your right to a jury trial or to participate in a class action lawsuit.",
  "explanation": "This clause prevents you from suing the company in court or joining a class action. Arbitration typically favors companies and limits your legal options. Some states restrict such clauses.",
  "impact": 5,
  "likelihood": 3,
  "safeguards": 1,
  "irp_score": 0.79,
  "legal_basis": ["Federal Arbitration Act", "State consumer protection laws"],
  "jurisdictions": ["US-FED"]
}
```

**Example 3: Vague Retention (Medium Severity)**
```json
{
  "category": "Retention",
  "severity": "Medium",
  "confidence": 0.84,
  "excerpt": "We retain your personal information for as long as necessary to provide our services and for legitimate business purposes.",
  "explanation": "The policy doesn't specify how long they keep your data. Under GDPR, companies must define retention periods and delete data when no longer needed. You can request deletion at any time.",
  "impact": 3,
  "likelihood": 4,
  "safeguards": 3,
  "irp_score": 0.58,
  "legal_basis": ["GDPR Art. 5(1)(e)", "GDPR Art. 17"],
  "jurisdictions": ["GDPR"]
}
```

### Appendix C: Error Messages

**User-Facing Errors:**

- **URL Unreachable:** "We couldn't fetch the document from this URL. Please check the URL and try again, or paste the text directly."
- **File Too Large:** "This file is too large (max 10MB). Please try pasting the text instead, or contact us for help."
- **Unsupported Format:** "We don't support this file type yet. Please try PDF, DOCX, RTF, HTML, or TXT."
- **Analysis Failed:** "Something went wrong during analysis. Please try again. If this persists, contact support."
- **LocalAI Unavailable:** "Our analysis engine is currently unavailable. Please make sure LocalAI is running and try again."
- **Empty Document:** "This document appears to be empty or we couldn't extract any text. Please check the file and try again."

**Developer Errors (Logs):**

- `ERR_LLM_TIMEOUT`: LocalAI request timeout after 60 seconds
- `ERR_LLM_INVALID_JSON`: LLM returned non-JSON response
- `ERR_PARSE_FAILED`: Document parsing failed (PDF/DOCX/RTF)
- `ERR_DB_WRITE`: Database write operation failed
- `ERR_CONFIDENCE_LOW`: All findings have confidence <0.70

### Appendix D: Glossary

- **IRP Score:** Impact / Likelihood / Safeguards composite score per finding, `0.5*(impact/5) + 0.4*(likelihood/5) - 0.3*(safeguard/5)`, clamped to `[0, 1]`. See §F3.1.
- **Overall Risk Score:** Document-level aggregate on a 0-10 scale (higher = worse), rendered as a letter grade via the 7-band table in §F3.1.
- **Context Chip:** Reader-supplied intake signal (`want_understand`, `for_child`, `for_care`, `for_work`, `just_curious`) that biases which findings surface first and swaps verdict copy. See LIB-CONTEXT.
- **Verdict Headline / Label:** Context-appropriate sentence + short chip label rendered on the results overview; rotation logic in `services/context.py`, copy conventions in LIB-VOICE.
- **Action Readiness:** High-level `Go` / `Review` / `Stop` recommendation derived from risk and completeness.
- **Completeness:** Fraction (0.0-1.0) of expected policy sections detected (rights, retention, contact, opt-out, ADM, security, third-party, minors).
- **Top-by-Domain:** Top findings grouped into 4 fixed buckets — `Data`, `Data use`, `Terms of use`, `Privacy rights` — capped at 2 per domain and 8 total.
- **Action Items:** Backend-generated reader-actionable next steps derived from findings + jurisdictions, returned on `AnalysisPayload` so the frontend does not have to know the derivation rules.
- **Confidence:** How certain the system is about a finding (0-1 scale)
- **Finding:** A detected risky clause in a policy
- **Severity:** High, Medium, or Low risk level
- **Excerpt:** Short quote from the policy (evidence)
- **Evidence Binding:** Linking findings to specific text with line numbers
- **Review Queue:** Findings with confidence <0.80 needing human review
- **Watchlist:** Documents monitored for changes over time
- **Verify View:** Split-pane view showing document with highlights
- **LLM:** Large Language Model (AI used for analysis)
- **LocalAI:** Open-source, zero-VC local inference server (Apache 2.0) that serves GGUF models via an OpenAI-compatible API. Used as the inference backend for Apertus 8B and EuroLLM 22B.
- **HITL:** Human-in-the-loop (manual review process)

---

## Approval & Sign-Off

**PRD Prepared By:** [Product Manager Name]
**Date:** 2026-07-03
**Version:** 2.4

**Review & Approval:**

| Role | Name | Signature | Date |
|------|------|-----------|------|
| Product Manager | | | |
| Engineering Lead | | | |
| Design Lead | | | |
| QA Lead | | | |
| Legal Advisor | | | |

**Ready for Development:** [ ] Yes [ ] No (pending changes)

**Next Steps:**
1. Engineering team reviews technical feasibility
2. Design creates high-fidelity mockups
3. Engineering creates technical design document
4. Sprint planning for MVP (12 weeks)
5. Development begins Week 1 of March 2026

---

**Related Documents:**
- BRD: `docs/BRD_Terms_Policies_Reviewer.md`
- Technical Design: TBD
- API Specification: TBD
- Test Plan: TBD
