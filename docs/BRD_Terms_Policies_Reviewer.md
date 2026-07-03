# Business Requirements Document: AI Terms & Policies Reviewer

**Version:** 1.1
**Date:** 2026-07-03
**Status:** Draft for Approval
**Document Owner:** Product Management
**Stakeholders:** Executive Leadership, Legal, Engineering, Product, Privacy Advocates
**Related Documents:** PRD_Terms_Policies_Reviewer.md, PRODUCT.md, `.claude/library/LIB-PRINCIPLES.md`, `.claude/library/LIB-CONTEXT.md`, `.claude/library/LIB-VOICE.md`

## Change History

| Version | Date | Summary |
|---------|------|---------|
| 1.1 | 2026-07-03 | Tech-spec audit remediation Phase 3 (Option A — accept shipped behavior; rewrite BRD; no code change). Codified the **global-tool contract**: `jurisdictions=[]` means "no filter" across rules, LLM post-filter, and Streamlit resolution — no silent US-CA + GDPR default anywhere (new BRD-CONSTRAINT-01, referenced across §Executive Summary, §Product Architecture, §Appendix A). Reconciled IRP scoring language from "planned enhancement" to shipped (per PR #34 and PRD v2.1+ §F3.1). Added BRD-CONSTRAINT-02 codifying hardware permissions (camera / mic / contacts / location) as scope caveats only, never a chip or domain group with findings, per LIB-PRINCIPLES Principle 4. Personal path removed from header. |
| 1.0 | 2026-02-13 | Initial draft for approval — problem statement, market analysis, business model, financial projections, product architecture, jurisdiction coverage (30 codes), industry profiles. |

---

## Executive Summary

### Business Opportunity

The AI Terms & Policies Reviewer is a privacy-focused web application that analyzes Terms of Service and Privacy Policies to identify high-risk clauses, map compliance requirements, and explain legal implications in plain language. Built on a foundation of client-side processing and local LLM inference via LocalAI (Apertus 8B, 1,000+ languages; EuroLLM 22B, EU legal specialist), the tool democratizes access to sophisticated legal document analysis without compromising user privacy.

**Current State:** Working prototype with:
- Multi-format document ingestion (URLs, PDFs, DOCX, RTF, HTML, text)
- Impact / Likelihood / Safeguards ("IRP") composite risk scoring per finding, shipped in PR #34 (formula `0.5*(impact/5) + 0.4*(likelihood/5) − 0.3*(safeguard/5)`, aggregated to a 0-10 document score and a 7-band letter grade). Severity-weighted averaging remains as a fallback for legacy findings without IRP fields.
- Multi-jurisdiction compliance mapping (30 jurisdiction codes spanning US federal/state, EU/UK, Canada, Latin America, Africa, Asia-Pacific, and AI-law frameworks) — filter is **user-selected**; an empty selection is treated as "no filter" per BRD-CONSTRAINT-01 (see Product Architecture)
- Industry-specific analysis profiles
- FastAPI backend with SQLite storage
- Streamlit UI (`app_streamlit_v2.py`, sole UI; `app_streamlit_legacy.py` is the v1 rollback path)
- Legal-knowledge-base RAG retrieval (numpy-exhaustive + BM25/RRF), shipped with placeholder corpus text pending real statute ingestion

### Strategic Goals

1. **Validate Product-Market Fit:** Transition from prototype to production-ready MVP within 6 months
2. **Privacy Leadership:** Establish as the privacy-first alternative to cloud-based legal tech
3. **User Acquisition:** Achieve 1,000 active users within 12 months of public launch
4. **Open Source Community:** Build contributor base and establish trust through transparency
5. **Sustainable Monetization:** Identify revenue model (freemium SaaS vs. enterprise licensing vs. open-core)

### Investment Request

**Total Budget:** $450K over 12 months

**Allocation:**
- Engineering & Product Development: $225K (50%)
- ML/AI Model Optimization: $90K (20%)
- Legal & Compliance Validation: $68K (15%)
- Go-to-Market (Community, Marketing): $45K (10%)
- Infrastructure & Tools: $22K (5%)

### Expected Returns

**12-Month Goals:**
- 1,000+ active users (free tier)
- 50+ paying customers (if freemium model)
- 90%+ clause detection accuracy (validated by legal experts)
- 3+ strategic partnerships (privacy advocacy organizations)
- Open source contributions from 10+ external developers

### Success Criteria

- Product-market fit validation with NPS ≥40
- Legal accuracy validated at ≥85% precision/recall by third-party audit
- <5% user churn monthly
- Average analysis time <30 seconds
- Successfully process 95%+ of common ToS/Privacy Policy formats

---

## Business Case

### Problem Statement

#### Market Pain Points

**For Individual Consumers:**
- Average ToS length is 6,000+ words requiring 20+ minutes to read
- 91% of users accept terms without reading them
- Legal jargon makes understanding rights waivers nearly impossible
- No accessible tools for automated risk analysis
- Existing tools send documents to cloud servers (privacy concern)

**For Privacy Advocates & Researchers:**
- Manual policy analysis is time-consuming and inconsistent
- Difficult to track policy changes across multiple services
- No standardized methodology for risk assessment
- Limited tools for comparative analysis across vendors

**For Small Organizations:**
- Can't afford $300-500/hour for legal review of vendor agreements
- Vendor proliferation (100+ SaaS tools) makes comprehensive review impossible
- Compliance requirements (GDPR, CCPA, PIPEDA) demand documentation
- Risk of regulatory fines for inadequate vendor due diligence

#### Competitive Landscape Gap

**Existing Solutions:**
- **ToS;DR:** Manual community ratings, limited coverage (2,000 services), no automated analysis
- **Enterprise Tools (LawGeex, Kira):** Expensive ($10K-100K+), cloud-based, focused on legal teams
- **Privacy Compliance Platforms (OneTrust):** Enterprise-only, internal compliance focus, not vendor assessment

**Market Gap:** No privacy-respecting, affordable, automated tool for consumers and small organizations that runs locally and maintains data sovereignty.

### Proposed Solution

The AI Terms & Policies Reviewer addresses this gap through:

#### Core Value Propositions

**1. Privacy-First Architecture**
- Client-side document processing
- Local LLM inference via LocalAI (zero VC, Apache 2.0)
- Apertus 8B (Swiss AI Initiative / EPFL+ETH, Apache 2.0, 1,000+ languages)
- EuroLLM 22B (EU Horizon + EuroHPC consortium, Apache 2.0, EU legal corpus)
- No document upload to external servers
- User maintains complete data control

**2. Comprehensive Risk Analysis**
- IRP (Impact / Likelihood / Safeguards) composite risk scoring per finding (shipped in PR #34 — see Risk Scoring Methodology below). Severity-weighted averaging remains as a fallback for legacy findings without IRP fields.
- 9 core risk categories (data sharing, automated decisions, dark patterns, retention, user rights, minors, sensitive data, unilateral changes, liability), expanded in practice to ~50 categories across 64 rule patterns
- Multi-jurisdiction compliance mapping (30 jurisdiction codes) — filter is user-selected; empty selection means "no filter" (BRD-CONSTRAINT-01)
- Industry-specific analysis profiles

**3. Accessible & Transparent**
- Plain language explanations
- Evidence citations from source documents
- Letter grades (A-F) for quick assessment
- Open source codebase for transparency and trust

**4. Flexible Deployment**
- Web application for ease of use
- Local installation for maximum privacy
- API access for integration
- Export options (PDF, CSV, JSON)

#### Technical Differentiation

| Feature | Our Solution | ToS;DR | Enterprise Tools |
|---------|-------------|--------|------------------|
| Privacy-First | Yes (local) | Yes | No (cloud) |
| Automated Analysis | Yes (AI) | No (manual) | Yes (cloud AI) |
| Multi-Format Input | 6 formats | Text only | Limited |
| Jurisdiction Mapping | 30 jurisdictions + AI law | No | Limited |
| Multilingual Analysis | 1,000+ languages (Apertus) | No | English/EU only |
| AI Law Analysis | EU AI Act, CoE CETS 225, OECD-AI, UNESCO-AI | No | Limited |
| Cost | Free/Low | Free | $10K-100K+ |
| Open Source | Yes | Yes | No |
| Vendor Comparison | Yes | No | No |
| Watchlist Monitoring | Yes | No | Yes |

---

## Market Analysis

### Target Market Sizing

#### Total Addressable Market (TAM)

**Privacy-Conscious Consumers:**
- Global privacy-aware internet users: 500M
- English-speaking markets: 150M

> **Multilingual expansion (v2.0):** Apertus 8B supports 1,000+ languages. Addressable multilingual market expands TAM to 500M+ privacy-conscious global users.

- TAM = 150M × $10 avg. spend = **$1.5B**

**SMB & Startups:**
- Small businesses with vendor management needs: 40M globally
- Addressable in primary markets: 8M
- TAM = 8M × $300 avg. spend = **$2.4B**

**Researchers & Advocates:**
- Privacy researchers, legal academics, policy analysts: 100K
- TAM = 100K × $500 = **$50M**

**Total TAM: $4.0B**

#### Serviceable Obtainable Market (SOM)

**Year 1 Target:**
- 1,000 active users (free tier)
- 50 paying customers @ $20/month avg. = $12K annual revenue
- 3 organizational partnerships

**Year 2 Target:**
- 5,000 active users
- 300 paying customers = $72K annual revenue
- 10 organizational partnerships
- API licensing deals

### Customer Segments

#### Segment 1: Parents with Children Under 18 (35% of users)

**Demographics:**
- Age: 30-50
- Parents with kids ages 5-17
- Tech Literacy: Low to Medium
- Primary concern: Child safety online

**Context:**
- Children use apps, games, social media, educational platforms
- Worried about data collection from minors
- Limited time to read lengthy terms of service
- Want to protect children from predatory practices
- Often make account decisions on behalf of children

**Goals:**
- Quickly assess if apps/services are safe for children
- Understand what data is collected from minors
- Identify age-inappropriate content or features
- Ensure COPPA compliance and child protection measures
- Make informed decisions about which services kids can use

**Pain Points:**
- Don't have time to read 20+ page privacy policies
- Can't understand legal terminology
- Unsure which apps comply with COPPA (Children's Online Privacy Protection Act)
- Services change terms without notification
- No easy way to compare child safety across platforms
- Concerned about targeted advertising to children

**User Journey:**
1. Child asks to download new gaming app
2. Parent opens AI Terms Reviewer on phone
3. Pastes app store link or privacy policy URL
4. Reviews risk score focused on "Minors Protection" category
5. Checks if parental consent is required
6. Reviews data sharing and advertising practices
7. Makes decision to allow or deny based on findings

**Acquisition:**
- Parenting forums and communities (Reddit r/parenting, BabyCenter)
- PTA associations and school newsletters
- Child safety organizations (Common Sense Media, Family Online Safety Institute)
- Partnerships with children's advocacy groups
- Social media (parenting influencers, Facebook groups)

#### Segment 2: Small Businesses (40% of users)

**Demographics:**
- Company size: 1-50 employees
- Industries: Retail, services, consulting, e-commerce, local businesses
- Tech Literacy: Low to Medium
- Legal Resources: Little to none

**Context:**
- Using multiple SaaS tools (email marketing, CRM, payment processors, cloud storage)
- No in-house legal counsel or compliance officer
- Budget-conscious, can't afford legal reviews
- Handling customer data and need to comply with privacy laws
- Growing awareness of GDPR, CCPA, and data breach liability

**Goals:**
- Ensure vendor agreements don't expose business to liability
- Understand data protection obligations
- Comply with privacy regulations (GDPR, CCPA, state laws)
- Document due diligence for business insurance or audits
- Make informed vendor selection decisions
- Protect customer and employee data

**Pain Points:**
- Legal review costs $300-500/hour (unaffordable)
- Don't understand legal jargon in vendor contracts
- Using 20-40 different vendors, impossible to review all agreements
- Fear of regulatory fines (GDPR fines up to €20M or 4% revenue)
- No idea which clauses are actually risky
- Vendors update terms without clear notice
- Need documentation for insurance, loans, or business sales

**User Journey:**
1. Receives vendor agreement from payment processor
2. Uploads PDF to AI Terms Reviewer
3. Reviews risk score and liability clauses
4. Focuses on data sharing, indemnification, and compliance sections
5. Exports PDF report for business records
6. Uses findings to negotiate with vendor or seek alternatives
7. Stores analysis in compliance documentation folder

**Acquisition:**
- Small business associations (NFIB, local chambers of commerce)
- Founder communities (Indie Hackers, Product Hunt)
- SaaS marketplaces (G2, Capterra)
- Small business advisors (accountants, insurance brokers)
- LinkedIn and small business Facebook groups

#### Segment 3: Privacy, Human Rights, and Tech Ethics Advocates (25% of users)

**Demographics:**
- Age: 25-55
- Occupations: Researchers, policy analysts, activists, journalists, lawyers
- Tech Literacy: Medium to High
- Focus Areas: Privacy rights, digital rights, ethical AI, platform governance

**Context:**
- Working for NGOs, think tanks, academic institutions, or as independent advocates
- Monitoring tech companies and government platforms
- Researching policy implications and corporate practices
- Publishing reports, academic papers, or investigative journalism
- Advocating for regulatory reform and consumer protection
- Limited organizational budgets

**Goals:**
- Systematically analyze policies across multiple platforms
- Identify patterns of concerning practices (dark patterns, rights violations)
- Document evidence for advocacy campaigns or reports
- Compare policies across jurisdictions and industries
- Track policy changes over time
- Educate the public about their rights
- Influence policy and regulation

**Pain Points:**
- Manual analysis of hundreds of policies is time-prohibitive
- Need reproducible, transparent methodology for credible research
- Existing tools are proprietary or too expensive
- Difficult to track when companies quietly change terms
- Hard to demonstrate systematic patterns across industry
- Need evidence citations for reports and testimony
- Complex regulatory landscape across jurisdictions

**User Journey:**
1. Compiles list of 50-100 social media/AI platform policies
2. Bulk analyzes policies via URL input
3. Reviews findings for patterns (e.g., mandatory arbitration clauses)
4. Exports detailed CSV with evidence citations
5. Performs statistical analysis and creates visualizations
6. Incorporates findings into research report or campaign
7. Cites methodology and shares dataset with other researchers
8. Monitors watchlist for policy changes by major platforms

**Acquisition:**
- Privacy and digital rights organizations (EFF, Access Now, Privacy International)
- Academic conferences (Privacy Law Scholars Conference, TPRC)
- Research networks and mailing lists
- Investigative journalism networks
- Human rights organizations (Amnesty International, Human Rights Watch)
- Open source and transparency communities

---

## Product Architecture

### Current Implementation

**Technology Stack:**

**Frontend — Streamlit only:**
- **Streamlit v2** (`src/webapp/app_streamlit_v2.py`) — sole UI, launched by `run.sh` on port 8501 (issue #19 plain-language redesign)
- **Streamlit v1 legacy** (`src/webapp/app_streamlit_legacy.py`) — v1 rollback path, selected via `STREAMLIT_UI=v1`
- Streamlit theming via `.streamlit/config.toml` (primary color, background, font-family)
- **Note:** The pre-redesign vanilla-JS SPA (`index.html` / `app.js` / `style.css`) was retired in Phase 4 of the issue #19 remediation. Streamlit v2 is now the sole path.

**Backend:**
- FastAPI (Python 3.11+)
- SQLite database (`data/terms_analysis.db`)
- Located in: `src/backend/app/`
- Services: `analyzer.py` (orchestration), `ingest.py` (document extraction + SSRF-guarded URL fetch), `rules.py` (pattern detection), `validation.py`, `diffing.py` (watchlist change detection), `embedding.py` (BM25 + dense RRF chunk selection), `legal_kb.py` (legal-KB retrieval), `localai.py` (LLM client)

**AI/ML:**
- LocalAI inference (Apache 2.0) routing between Apertus-8B-Instruct (world/multilingual) and EuroLLM-22B-Instruct (EU legal specialist), selected per-document by language detection
- API endpoint: `http://localhost:8080/v1` (`LOCALAI_BASE_URL`)
- Legal-knowledge-base retrieval (`legal_kb.py`): numpy-exhaustive exact search over an embedded statute corpus (`data/legal_corpus/`), fused with BM25 via Reciprocal Rank Fusion, injecting citable legal passages into the LLM prompt. Ships with placeholder corpus text pending real statute ingestion (see Appendix A note).

**Document Processing:**
- PDF, DOCX, RTF, HTML, plain text support (OCR fallback for scanned PDFs)
- URL fetching and extraction (SSRF-protected — blocks private/loopback/link-local ranges)
- Text normalization and preprocessing

**Database Schema:**
- `Analysis` — one row per analysis: document text, risk score, grade, confidence, full findings payload (`result_json`)
- `ReviewItem` — findings flagged for human review (confidence < 0.80), linked to `Analysis`
- `WatchlistItem` — monitored vendor URLs, change/risk-delta tracking
- `PolicySnapshot` / `PolicyWatch` — historical policy versions and watch schedules (token-level diffing)

### API Endpoints

24 business endpoints plus `/health` (25 routes total), grouped as follows (see `src/backend/app/main.py`):

| Group | Endpoints | Purpose |
|-------|-----------|----------|
| Analyze | `POST /analyze`, `/analyze/url`, `/analyze/file`, `/analyze/batch` | Analyze text, URL, uploaded file, or a batch with cross-reference detection |
| Results | `GET /analyses`, `/analyses/{id}`, `/rubric` | List/retrieve analyses, aggregate rubric scores |
| Exports | `GET /exports/analysis/{id}`, `/exports/analysis/{id}.pdf`, `/exports/analyses.csv` | JSON, PDF, and bulk CSV export |
| Review queue | `GET /reviews`, `POST /reviews/{id}` | List and approve/reject low-confidence findings |
| Watchlist | `GET/POST /watchlist`, `DELETE /watchlist/{id}`, `POST /watchlist/{id}/refresh` | Vendor monitoring |
| Snapshots & diff | `GET/POST /snapshots`, `GET /snapshots/detail/{id}`, `GET /diff/{id1}/{id2}` | Historical versions, token-level diffing |
| Policy watch | `POST/GET /policy-watch`, `DELETE /policy-watch/{id}`, `POST /policy-watch/{id}/snapshot` | Scheduled policy monitoring |

### Risk Scoring Methodology

**Shipped in PR #34 — IRP (Impact / Likelihood / Safeguards) composite** (`analyzer.py::_compute_irp`):

\[
\text{irp\_score}(f) = 0.5 \times \frac{f.\text{impact}}{5} + 0.4 \times \frac{f.\text{likelihood}}{5} - 0.3 \times \frac{f.\text{safeguard\_score}}{5}, \quad \text{clamped to } [0, 1]
\]

`Finding` schema fields for `impact`, `likelihood`, `safeguard_score`, and `irp_score` are live. `rules.py::_seed_irp` seeds rule-generated findings from `_CATEGORY_IRP_DEFAULTS` (38 categories mapped). LLM prompts request the same three fields per finding. The hybrid merge takes `impact` and `likelihood` from rules as the baseline and takes `safeguard_score = max(rule, llm)`. Sort is **tier-first**: `(weight, irp_score, severity_rank)` all descending — context chip weight leads, IRP score breaks ties within tier.

**Legacy fallback (kept for findings without IRP fields):** severity-weighted average — `score = 10 * (sum(weight(f.severity)) / |findings|)` with `weight = {Low: 0.2, Medium: 0.5, High: 0.8, Critical: 1.0}`.

**Grade Mapping** (0-10 scale, higher = worse; source `analyzer.py::_grade`):
- **A:** score < 3.5
- **A-:** 3.5 <= score < 4.5
- **B:** 4.5 <= score < 5.5
- **B-:** 5.5 <= score < 6.5
- **C+:** 6.5 <= score < 7.5
- **C:** 7.5 <= score < 8.5
- **D+:** score >= 8.5

**Risk Categories:** the original design specified 9 conceptual categories (Data Sharing, Automated Decisions, Dark Patterns, Retention, User Rights, Minors, Sensitive Data, Unilateral Changes, Liability). Actual rule coverage has grown well beyond this baseline — `rules.py` implements ~50 category labels across 64 `RulePattern` entries, adding AI Act sub-categories (High-Risk AI, Prohibited AI, Automated Decision-Making, AI Training, GPAI, etc.) and industry-specific blocks (HIPAA, FERPA, PCI DSS, COPPA) layered on top of the 9-category framework. The canonical shipped label set is `src/backend/app/schemas.py::CATEGORIES` (see PRD §F3.2 for the full list).

### Jurisdiction Support

**Current Coverage — 30 jurisdiction codes, all with rule coverage** (`schemas.py`). The user selects zero or more of these at analysis time; the tool applies the filter across rules, LLM post-filter, and Streamlit resolution. Selection semantics are governed by BRD-CONSTRAINT-01 (see below).

- US: `US-FED`, `US-CA`, `US-NY`, `US-TX`, `US-VA`, `US-CO`, `US-CT`, `US-IL`, `US-NJ`, `US-MN`, `US-OR`
- International privacy: `GDPR`, `UK-GDPR`, `LGPD` (Brazil), `PIPEDA` (Canada), `CA-QC` (Quebec Law 25), `POPIA` (South Africa), `PDPA-KE` (Kenya), `DPDP` (India), `APPI` (Japan), `PIPA` (South Korea), `APP` (Australia), `PDPA-TH` (Thailand), `NDPR` (Nigeria)
- International frameworks: `ICCPR-17`, `COE-108`
- AI law: `EU-AI-ACT`, `COE-AI-225`, `OECD-AI`, `UNESCO-AI`

### BRD Constraints (global tool contract)

The two constraints below are non-negotiable operating requirements for the tool, derived from the session outcomes documented in `.claude/CLAUDE.md` §Session outcomes (2026-07-03) and formalized in `.claude/library/LIB-PRINCIPLES.md`. They apply across rules, LLM post-filter, Streamlit UI, all API endpoints, and any downstream automation (watchlist refresh, background loops, batch analysis).

#### BRD-CONSTRAINT-01 — `jurisdictions=[]` means "no filter"

**Rule:** An empty jurisdictions list (`jurisdictions=[]` in API requests, or an empty multi-select in the UI) is treated as "no filter" — the tool applies rules for all 30 supported jurisdictions and does not silently substitute any default subset. There is no US-CA + GDPR fallback, no per-endpoint default, and no per-user-locale inference.

**Scope of enforcement (all paths must honor this):**
- `POST /analyze`, `POST /analyze/url`, `POST /analyze/file`, `POST /analyze/batch`
- Watchlist refresh (`POST /watchlist/{id}/refresh`) and background loop (`_watchlist_loop_async`, `_refresh_all_watchlist_items`)
- Policy-watch snapshot endpoints
- LLM post-filter (`analyzer._filter_by_jurisdiction`)
- Streamlit v2 jurisdiction resolution (dropdowns default to blank; `index=None`)

**Why:** Silent defaults produce results that a nervous non-expert reader cannot reconcile with the input they gave the tool. Surfacing the empty-filter case as "no filter" preserves the tool's honesty contract (LIB-VOICE §Scope-honesty gap) and lets the user opt in to jurisdictional narrowing when they know which ones apply. US-CA and GDPR remain first-class supported jurisdictions (see §Jurisdiction Support) — they are simply not applied silently when the caller did not ask for them.

**References:** `.claude/CLAUDE.md` §Session outcomes (2026-07-03), `.claude/library/LIB-PRINCIPLES.md` Principle 3 (surface drift, do not silently execute), audit findings LE-001 / LE-002 (regression tests in `src/backend/tests/test_audit_phase1_fixes.py`).

#### BRD-CONSTRAINT-02 — Hardware permissions are scope caveats only

**Rule:** The tool analyzes document text only. Hardware permissions (camera, microphone, contacts, location) are surfaced verbatim in the scope box as a limit of the tool — they are never a context chip, never a domain group with findings, and never a category in `schemas.CATEGORIES`. Text-level mentions of camera / mic / contacts / location that appear in a policy are analyzed under their existing content categories (for example, precise geolocation under `Sensitive Data`), not under a hardware-permission bucket.

**Why:** The tool reads policy text, not runtime permission manifests. Any UI or API surface that implied hardware analysis would over-claim capability and violate the scope-honesty gap. Real-world practice divergence — what the app actually requests versus what the policy says — is likewise out of scope and surfaced in the scope box.

**References:** `.claude/library/LIB-PRINCIPLES.md` Principle 4 (hard scope limits are non-negotiable), `.claude/library/LIB-VOICE.md` §Scope-honesty gap, `terms_analysis_scope_limits.md` (auto-memory).

### Industry Profiles

**Supported Industries:**
- Retail & E-commerce
- Financial Services
- Healthcare
- Gaming & Entertainment
- Social Media
- Education

---

## Business Model

### Revenue Model Options

**Option 1: Freemium SaaS (Recommended)**

**Free Tier:**
- 5 analyses per month
- Basic risk scoring
- Single jurisdiction analysis
- Watermarked PDF exports

**Individual Tier - $9.99/month:**
- Unlimited analyses
- Multi-jurisdiction support
- All industry profiles
- Clean exports (PDF, CSV, JSON)
- Watchlist (up to 10 documents)

**Professional Tier - $29/month:**
- Everything in Individual
- Watchlist (up to 50 documents)
- Change detection and alerts
- Vendor comparison (up to 3)
- API access (1,000 calls/month)
- Priority support

**Organization Tier - $99/month:**
- Team accounts (up to 5 users)
- Unlimited watchlist
- 10-vendor comparison
- API access (10,000 calls/month)
- Custom analysis parameters
- Dedicated support

**Year 1 Revenue Projection:**
- 1,000 free users
- 40 Individual ($9.99) = $4,800
- 8 Professional ($29) = $2,800
- 2 Organization ($99) = $2,400
- **Total: $10,000 ARR**

**Option 2: Open Core Model**

- Core product fully open source (MIT or Apache 2.0)
- Revenue from:
  - Enterprise features (SSO, audit logs, advanced API)
  - Managed hosting service
  - Priority support contracts
  - Custom model training
  - White-label licensing

**Option 3: Grant-Funded & Nonprofit**

- Operate as nonprofit or fiscal sponsorship
- Revenue from:
  - Privacy advocacy grants
  - Research institution partnerships
  - Donations from users
  - Foundation support (Mozilla, Ford, MacArthur)

**Recommended Approach:** Start with Option 1 (Freemium SaaS), maintain open source core, explore Option 2 for enterprise customers, and pursue Option 3 grants for specific research/advocacy initiatives.

### Cost Structure

**Year 1 Operating Costs:**

**Personnel:**
- Lead Engineer (full-time): $150K
- ML Engineer (part-time): $75K
- Legal Advisor (consulting): $50K
- Product Manager (part-time): $60K
- **Total Personnel: $335K**

**Infrastructure:**
- Hosting (web app, backend): $3K
- Development tools: $2K
- Domain, SSL, CDN: $1K
- LLM API (fallback): $2K
- **Total Infrastructure: $8K**

**Legal & Compliance:**
- Third-party accuracy audit: $30K
- Professional liability insurance: $8K
- Legal review (ToS, disclaimers): $15K
- Regulatory research subscriptions: $6K
- **Total Legal: $59K**

**Marketing & Community:**
- Content creation: $15K
- Conference sponsorships: $10K
- Community management: $12K
- Open source program: $8K
- **Total Marketing: $45K**

**Total Year 1 Costs: $447K**

**Unit Economics (Freemium Model):**
- CAC (organic): ~$50 per paying customer
- LTV (12-month retention): $9.99 × 12 × 0.75 margin = $90
- LTV:CAC = 1.8 (target: improve to 3.0+ by Year 2)

---

## Go-to-Market Strategy

### Launch Strategy

#### Phase 1: Private Beta (Months 1-2)

**Objectives:**
- Validate MVP with 50 beta testers
- Achieve 80%+ detection accuracy
- Collect qualitative feedback
- Identify critical bugs

**Activities:**
- Recruit beta testers from privacy communities
- Conduct weekly user interviews
- Implement feedback rapidly
- Build initial content library

**Success Metrics:**
- 50 beta users recruited
- 80%+ average detection accuracy
- <30 second average analysis time
- NPS ≥30

#### Phase 2: Public Launch (Month 3)

**Launch Channels:**
- Product Hunt (aim for top 5)
- Hacker News (Show HN)
- Reddit (r/privacy, r/opensource)
- Privacy-focused tech press (EFF, RestorePrivacy)

**Launch Assets:**
- Demo video (2-3 minutes)
- Launch blog post
- Open source GitHub repository
- Documentation site
- Sample analyses of popular services

**Launch Offers:**
- Lifetime 50% discount for first 100 users
- Free Professional tier for verified nonprofit employees
- Open source contributor recognition program

**Target Outcomes:**
- 500+ new users in launch week
- 20+ paying customers in Month 1
- 10+ media mentions
- 100+ GitHub stars

#### Phase 3: Community Building (Months 4-6)

**Activities:**
- Monthly "Policy Analysis" blog posts
- Comparative analyses of major platforms
- Privacy awareness campaigns
- Open source contribution program
- Partnership outreach to privacy orgs

### Acquisition Channels

#### Channel 1: Open Source Community (40% of users)

**Tactics:**
- Maintain active GitHub repository
- Contribute to privacy-related projects
- Speak at open source conferences
- Create developer documentation
- Accept community contributions

**Budget:** $10K (conference sponsorships, community management)

#### Channel 2: Content Marketing (30% of users)

**Tactics:**
- Blog: Policy analysis deep dives
- Comparison reports (Platform X vs Y)
- Privacy guides and resources
- SEO for terms like "privacy policy analyzer"
- Guest posts on privacy blogs

**Budget:** $15K (content creation, SEO tools)

#### Channel 3: Privacy Community Partnerships (20% of users)

**Partnerships:**
- Electronic Frontier Foundation
- Privacy International
- Mozilla Foundation
- RestorePrivacy
- PrivacyTools.io

**Tactics:**
- Co-branded educational content
- Tool recommendations
- Research collaborations
- Event sponsorships

**Budget:** $15K (sponsorships, partnership development)

#### Channel 4: Product-Led Growth (10% of users)

**Tactics:**
- Shareable analysis results
- "Analyze this policy" bookmarklet
- API for third-party integrations
- Embed widgets for websites
- Viral sharing mechanisms

**Budget:** $5K (feature development)

### Retention Strategy

**Onboarding:**
- Interactive product tour
- Sample analysis walkthrough
- Educational tooltips
- Video tutorials

**Engagement:**
- Watchlist change alerts (email)
- Monthly privacy newsletter
- New feature announcements
- Community highlights

**Churn Prevention:**
- Usage monitoring and re-engagement emails
- Feedback collection
- Feature request voting
- Downgrade option before cancellation

---

## Key Performance Indicators (KPIs)

### Product Metrics

**User Acquisition:**
- New user signups per week
- Activation rate (% completing first analysis)
- Traffic sources and conversion rates
- Viral coefficient (referrals per user)

**Engagement:**
- Daily/Monthly Active Users (DAU/MAU)
- Analyses per user per month
- Average session duration
- Return user rate (7-day, 30-day)
- Watchlist adoption rate

**Quality:**
- Detection accuracy (precision/recall/F1)
- Average analysis completion time
- Error rate (failed analyses)
- User-reported false positives
- System uptime

### Business Metrics

**Revenue (if freemium):**
- MRR/ARR
- Free-to-paid conversion rate
- Average revenue per user (ARPU)
- Customer lifetime value (LTV)
- Churn rate by tier

**Growth:**
- Month-over-month user growth
- CAC by channel
- LTV:CAC ratio
- Payback period

**Community:**
- GitHub stars/forks/contributors
- Documentation page views
- API adoption rate
- Partnership referrals

### Targets

**Month 3 (Launch):**
- 500 total users
- 20 paying customers
- 85% detection accuracy
- <30 second analysis time
- 100 GitHub stars

**Month 6:**
- 1,000 total users
- 50 paying customers
- 90% detection accuracy
- 3 organizational partnerships
- 250 GitHub stars

**Month 12:**
- 2,500 total users
- 150 paying customers
- $15K MRR
- 5 organizational partnerships
- 500 GitHub stars
- 10+ external contributors

---

## Risk Analysis

### Technical Risks

#### Risk 1: LLM Detection Accuracy Below Target

**Likelihood:** Medium  
**Impact:** Critical

**Description:** Local LLM models may not achieve 85%+ precision/recall, undermining user trust.

**Mitigation:**
- Test multiple LLM models (Llama, Mistral, Phi)
- Implement rule-based fallbacks for common patterns
- Create high-quality training dataset (500+ labeled examples)
- Hybrid approach: LLM + regex + keyword matching
- Continuous validation against test suite
- Third-party legal audit of accuracy

**Contingency:**
- If accuracy <75%, pivot to human-in-the-loop model
- Provide confidence scores with all findings
- Clear disclaimers about limitations

#### Risk 2: Document Format Compatibility Issues

**Likelihood:** Medium  
**Impact:** Medium

**Description:** Complex or proprietary document formats may fail to parse correctly.

**Mitigation:**
- Support 6 common formats (PDF, DOCX, RTF, HTML, TXT, URL)
- Use robust parsing libraries (PyPDF2, python-docx, BeautifulSoup)
- Implement format detection and fallback mechanisms
- Allow manual text paste as backup
- User feedback mechanism for failed parses

**Contingency:**
- Focus on URL and text paste as primary methods
- Provide format conversion guidance
- Partner with document conversion services if needed

#### Risk 3: Performance Degradation at Scale

**Likelihood:** Low  
**Impact:** Medium

**Description:** Analysis time increases significantly with user growth.

**Mitigation:**
- Implement caching for previously analyzed documents
- Optimize LLM prompts for speed
- Async processing for uploads
- Database indexing and query optimization
- Load testing before public launch

### Market Risks

#### Risk 4: Low User Willingness to Pay

**Likelihood:** Medium  
**Impact:** High

**Description:** Users value the tool but won't pay for premium features.

**Mitigation:**
- Validate pricing through user interviews
- Offer compelling free tier to build user base
- Focus on high-value features for paid tiers (watchlist, API, comparison)
- Consider alternative monetization (grants, donations, partnerships)
- B2B focus on organizations with budgets

**Contingency:**
- Pivot to open core model with enterprise features
- Pursue nonprofit/grant funding route
- Partnership revenue (affiliate, white-label)

#### Risk 5: Privacy Concerns About LLM Processing

**Likelihood:** Low  
**Impact:** High

**Description:** Users concerned about document privacy even with local processing.

**Mitigation:**
- Transparent architecture documentation
- No cloud upload policy clearly stated
- Open source code for verification
- Privacy audit by trusted third party
- Local-first marketing emphasis
- Option to run completely offline

### Legal Risks

#### Risk 6: Liability for Incorrect Analysis

**Likelihood:** Low  
**Impact:** Critical

**Description:** User relies on tool, suffers harm, sues for damages.

**Mitigation:**
- Prominent disclaimers: "Not legal advice"
- Terms of Service with liability limitations
- Professional liability insurance ($2M coverage)
- Encourage users to consult attorneys for important decisions
- Confidence scores and "Verify" prompts
- Third-party accuracy validation

**Legal Review:**
- Engage legal tech specialist to review ToS/disclaimers ($15K)
- Annual legal audit of risk exposure
- E&O insurance policy ($8K annually)

#### Risk 7: Regulatory Compliance Changes

**Likelihood:** Medium  
**Impact:** Medium

**Description:** Privacy regulations change, making analysis outdated.

**Mitigation:**
- Subscribe to legal research services (LexisNexis)
- Display "Last updated" dates on regulatory guidance
- Versioned regulation database
- Quarterly legal advisor review
- Automated alerts for regulation changes
- Email notifications to users when criteria change

### Competitive Risks

#### Risk 8: Big Tech Launches Similar Tool

**Likelihood:** Low  
**Impact:** Medium

**Description:** Google, Microsoft, or privacy platform adds similar analysis feature.

**Mitigation:**
- Privacy-first positioning as key differentiator
- Open source moat and community trust
- Focus on specific niche (privacy advocates, small orgs)
- Build switching costs through watchlist and saved analyses
- Position as complementary, offer API for integration

---

## Implementation Roadmap

### Phase 1: MVP Refinement (Months 1-3)

**Goal:** Production-ready MVP with validated accuracy.

**Key Deliverables:**
- [ ] Improve detection accuracy to 85%+ F1 score
- [ ] Complete all 6 document format parsers
- [ ] Implement caching and performance optimization
- [ ] Build PDF export functionality
- [ ] Create comprehensive test suite (500+ examples)
- [ ] Third-party legal accuracy audit
- [ ] Write user documentation
- [ ] Design polished UI/UX (based on wireframes)
- [ ] Implement error handling and edge cases
- [ ] Set up monitoring and analytics

**Team:**
- Lead Engineer (full-time)
- ML Engineer (part-time)
- Legal Advisor (consulting)

**Budget:** $110K

**Success Criteria:**
- 85%+ F1 score on test dataset
- <30 second average analysis time
- 95%+ successful document processing rate
- Legal audit confirms methodology validity

### Phase 2: Private Beta (Months 2-3)

**Goal:** Validate product-market fit with 50 users.

**Key Deliverables:**
- [ ] Recruit 50 beta testers from privacy communities
- [ ] Weekly user interviews and feedback sessions
- [ ] Iterate on UI/UX based on feedback
- [ ] Fix critical bugs and edge cases
- [ ] Collect testimonials and case studies
- [ ] Measure NPS and user satisfaction

**Success Criteria:**
- 50 active beta users
- NPS ≥30
- 80%+ user activation rate (complete first analysis)
- <10% error rate on analyses

### Phase 3: Public Launch (Month 3)

**Goal:** Launch to public with 500+ users in first week.

**Key Deliverables:**
- [ ] Open source GitHub repository
- [ ] Launch website and documentation
- [ ] Product Hunt launch
- [ ] Hacker News "Show HN" post
- [ ] Privacy community announcements
- [ ] Demo video and screenshots
- [ ] Sample analyses of popular services
- [ ] Pricing page and payment integration

**Marketing:**
- Product Hunt campaign
- Privacy blogger outreach
- Reddit posts (r/privacy, r/opensource)
- Twitter/Mastodon presence
- Press release to tech media

**Success Criteria:**
- 500+ new users in launch week
- Top 5 on Product Hunt
- 20+ paying customers
- 10+ media mentions
- 100+ GitHub stars

### Phase 4: Feature Expansion (Months 4-6)

**Goal:** Add differentiating features and improve retention.

**Key Deliverables:**
- [ ] Watchlist monitoring with change detection
- [ ] Vendor comparison (side-by-side)
- [ ] API launch with documentation
- [ ] CSV/JSON export options
- [ ] Mobile-responsive design improvements
- [ ] Browser bookmarklet for quick analysis
- [ ] Email notification system
- [ ] Advanced filtering and search

**Success Criteria:**
- 1,000 total users
- 50 paying customers
- 30%+ watchlist adoption
- 10+ API integrations
- <5% monthly churn

### Phase 5: Growth & Partnerships (Months 7-12)

**Goal:** Scale to 2,500 users and establish strategic partnerships.

**Key Deliverables:**
- [ ] Partnership with 3+ privacy organizations
- [ ] Content marketing program (blog, guides)
- [ ] Community contribution program
- [ ] Comparative analysis reports
- [ ] Conference presentations
- [ ] API marketplace listing
- [ ] White-label licensing option
- [ ] Enterprise features (team accounts, SSO)

**Success Criteria:**
- 2,500 total users
- 150 paying customers
- $15K MRR
- 3+ organizational partnerships
- 500+ GitHub stars
- 10+ external code contributors

---

## Financial Projections

### Revenue Projections (Freemium Model)

#### Year 1 Monthly Progression

| Month | Free Users | Paid Users | MRR | Cumulative Revenue |
|-------|-----------|-----------|-----|--------------------|
| M1-2 (Beta) | 50 | 0 | $0 | $0 |
| M3 (Launch) | 500 | 20 | $300 | $300 |
| M4 | 650 | 30 | $450 | $750 |
| M6 | 1,000 | 50 | $750 | $2,250 |
| M9 | 1,500 | 90 | $1,350 | $6,150 |
| M12 | 2,500 | 150 | $2,250 | $13,500 |

**Assumptions:**
- 5% free-to-paid conversion rate (conservative)
- Average ARPU: $15/month (mix of Individual, Professional, Organization tiers)
- 5% monthly churn rate
- Tier distribution: 60% Individual, 30% Professional, 10% Organization

**Year 1 Total Revenue: $13,500**

#### Year 2 Projections

| Quarter | Free Users | Paid Users | Quarterly Revenue | ARR Exit |
|---------|-----------|-----------|------------------|----------|
| Q1 | 4,000 | 250 | $11,250 | $45K |
| Q2 | 6,000 | 400 | $18,000 | $72K |
| Q3 | 9,000 | 600 | $27,000 | $108K |
| Q4 | 12,000 | 850 | $38,250 | $153K |

**Year 2 Total Revenue: $94,500**

**Growth Drivers:**
- Improved conversion through feature additions
- Word-of-mouth and viral growth
- Content marketing and SEO
- Partnership referrals
- API and integration revenue

### Cost Projections

#### Year 1 Expenses

| Category | Annual Cost | % of Total |
|----------|-------------|------------|
| Personnel | $335,000 | 75% |
| Legal & Compliance | $59,000 | 13% |
| Marketing & Community | $45,000 | 10% |
| Infrastructure | $8,000 | 2% |
| **Total** | **$447,000** | **100%** |

**Year 1 P&L:**
- Revenue: $13,500
- Operating Expenses: $447,000
- **Net Loss: ($433,500)**

#### Year 2 Expenses (Scaled)

| Category | Annual Cost | % of Total |
|----------|-------------|------------|
| Personnel | $450,000 | 70% |
| Legal & Compliance | $45,000 | 7% |
| Marketing & Sales | $80,000 | 12% |
| Infrastructure | $20,000 | 3% |
| Operations | $50,000 | 8% |
| **Total** | **$645,000** | **100%** |

**Year 2 P&L:**
- Revenue: $94,500
- Operating Expenses: $645,000
- **Net Loss: ($550,500)**

### Funding Requirements

**Initial Investment: $450K**

**Use of Funds:**
- 18-month runway for core team
- Product development and validation
- Legal accuracy audit and compliance
- Go-to-market and community building
- Infrastructure and tools

**Break-Even Analysis:**
- Break-even revenue: ~$54K/month MRR
- Required paying customers: ~3,600 @ $15 ARPU
- Projected timeline: Month 24-30 at current growth rates

**Alternative Funding Sources:**
- Privacy advocacy grants (Mozilla, Ford Foundation)
- Open source sponsorships (GitHub Sponsors, Open Collective)
- Strategic partnerships with privacy organizations
- Research grants from academic institutions

---

## Success Metrics & OKRs

### Q1 2026 (Beta & Launch)

**Objective 1: Launch production-ready MVP**
- KR1: Achieve 85%+ F1 score on 500-document test set
- KR2: Complete legal accuracy audit with ≥80% validation
- KR3: Public launch with 500+ users in Week 1

**Objective 2: Validate product-market fit**
- KR1: 50 beta users complete testing with NPS ≥30
- KR2: 80%+ user activation rate (complete first analysis)
- KR3: Collect 20+ qualitative user testimonials

### Q2 2026 (Growth)

**Objective 1: Scale user base and engagement**
- KR1: Reach 1,000 total users
- KR2: Achieve 5% free-to-paid conversion rate
- KR3: <5% monthly churn for paid users

**Objective 2: Build community and partnerships**
- KR1: 250+ GitHub stars
- KR2: Secure 2 organizational partnerships
- KR3: 5+ external code contributions accepted

### Q3-Q4 2026 (Scale)

**Objective 1: Achieve sustainable growth trajectory**
- KR1: 2,500 total users, 150 paying customers
- KR2: $15K MRR ($180K ARR)
- KR3: 90%+ detection accuracy (validated)

**Objective 2: Establish market presence**
- KR1: 3+ strategic partnerships with privacy orgs
- KR2: 500+ GitHub stars, 10+ contributors
- KR3: 10+ API integrations or white-label deals

---

## Appendices

### Appendix A: Technical Specifications

**File Structure:**
```
terms-analysis/
├── src/
│   ├── webapp/                       # Frontend — Streamlit only
│   │   ├── app_streamlit_v2.py       # Streamlit v2 (sole UI, :8501, default)
│   │   └── app_streamlit_legacy.py   # v1 rollback (STREAMLIT_UI=v1)
│   ├── backend/                  # FastAPI backend
│   │   ├── app/
│   │   │   ├── main.py           # API routes (24 endpoints + /health)
│   │   │   ├── services/
│   │   │   │   ├── analyzer.py   # Orchestration, risk scoring
│   │   │   │   ├── ingest.py     # Document extraction, SSRF-guarded URL fetch
│   │   │   │   ├── rules.py      # Pattern-based detection (64 patterns)
│   │   │   │   ├── validation.py
│   │   │   │   ├── diffing.py    # Watchlist change detection
│   │   │   │   ├── embedding.py  # BM25 + dense RRF chunk selection
│   │   │   │   ├── legal_kb.py   # Legal-KB retrieval (numpy-exhaustive + BM25/RRF)
│   │   │   │   └── localai.py    # LLM client (Apertus/EuroLLM routing)
│   │   │   ├── models.py         # Database models
│   │   │   └── config.py         # Configuration
│   │   └── tests/                # pytest suite
│   └── demos/                    # Prototype versions
├── docs/
│   ├── specs/               # Requirements, rubric
│   ├── wireframes/          # UI designs
│   ├── plans/               # Architecture plans
│   └── reports/             # Analysis reports
├── data/
│   ├── terms_analysis.db    # SQLite database (gitignored)
│   └── legal_corpus/        # Legal-KB source text (tracked; index/metadata gitignored)
├── .env                     # Environment config
└── run.sh                   # Launch script (backend + Streamlit)
```

**Environment Variables:**
- `LOCALAI_BASE_URL`: LocalAI endpoint (default: `http://localhost:8080/v1`)
- `MODEL_WORLD` / `MODEL_EU`: Apertus / EuroLLM model names for language-routed inference
- `DATABASE_URL`: SQLite database path (default: `sqlite:///./data/terms_analysis.db`)
- `REVIEW_THRESHOLD`: confidence threshold for human review (default: `0.80`)
- `RRF_K`, `LEGAL_KB_TOP_K`: legal-KB retrieval tuning

**Development Workflow:**
1. Start a LocalAI server with Apertus-8B-Instruct (world model) and EuroLLM-22B-Instruct (EU specialist) loaded
2. Run `./run.sh` — launches the backend (port 9000) and Streamlit UI (port 8501) together
3. UI at `http://localhost:8501`
4. API docs available at `http://localhost:9000/docs`

### Appendix B: Risk Rubric Details

**Clause Detection Categories (original 9-category framework — actual rule coverage has grown to ~50 category labels / 64 patterns; these remain the core conceptual buckets):**

1. **Data Sharing**: Third-party sales, data broker relationships, cross-border transfers
2. **Automated Decisions**: ADM without human review, profiling, scoring
3. **Dark Patterns**: Deceptive consent, pre-checked boxes, hidden opt-outs
4. **Retention**: Indefinite storage, vague deletion timelines
5. **User Rights**: Missing GDPR/CCPA rights (access, deletion, portability)
6. **Minors**: Inadequate COPPA protections, age verification
7. **Sensitive Data**: Biometrics, health records, financial data
8. **Unilateral Changes**: Policy modifications without notice/consent
9. **Liability**: Excessive disclaimers, forced arbitration, class action waivers

**Scoring Parameters (shipped in PR #34 — Impact / Likelihood / Safeguards axes are live on the `Finding` schema; see Risk Scoring Methodology for the composite formula and grade thresholds):**
- **Impact** (1-5): Severity of potential harm to users
- **Likelihood** (1-5): Probability clause will be exercised
- **Safeguards** (1-5): Protections/limitations in place

**Jurisdiction-Specific Flags:**
- GDPR: Lawful basis, DPO, data transfers, breach notification
- CCPA: Sale opt-out, do not sell, consumer rights
- PIPEDA: Consent requirements, accountability principle
- COPPA: Parental consent, age verification

### Appendix C: Competitive Analysis

**Feature Comparison Matrix:**

| Feature | Our Tool | ToS;DR | Common Terms | LawGeex | OneTrust |
|---------|----------|--------|--------------|---------|----------|
| Automated Analysis | Yes (AI) | No | Partial | Yes | Yes |
| Privacy-First | Yes (local) | Yes | No | No | No |
| Multi-Format Input | 6 types | Text | Text | Limited | Limited |
| Risk Scoring | IRP composite (shipped) + severity-weighted fallback | Letter grade | Simple | Proprietary | Proprietary |
| Jurisdiction Mapping | 30 jurisdictions + AI law | No | No | Limited | Yes |
| Vendor Comparison | Yes | No | No | No | No |
| Watchlist/Monitoring | Yes | No | No | No | Yes |
| API Access | Yes | No | No | Yes | Yes |
| Open Source | Yes | Yes | No | No | No |
| Cost | $0-99/mo | Free | $4.99/mo | $10K+/yr | $50K+/yr |

### Appendix D: Legal Disclaimers

**Tool Limitations:**
- Provides informational analysis only, not legal advice
- Does not replace qualified legal counsel
- No guarantee of analysis completeness or accuracy
- Not liable for decisions made based on analysis
- Results should be independently verified
- Users encouraged to consult attorneys for important matters

**Terms of Service Requirements:**
- Clear disclaimer: "Not legal advice"
- Liability limitations
- No warranties expressed or implied
- User accepts risk of reliance
- Indemnification clause
- Mandatory arbitration (consider carefully)

**Insurance Coverage:**
- Professional liability (E&O): $2M coverage
- General liability: $1M coverage
- Cyber liability: $1M coverage
- Annual cost: ~$8K-10K

### Appendix E: Grant Opportunities

**Potential Funding Sources:**

**Privacy Advocacy:**
- Mozilla Foundation (privacy/security grants: $50K-150K)
- Electronic Frontier Foundation (fellowships)
- Open Technology Fund ($10K-900K)
- DuckDuckGo Privacy Challenge ($25K)

**Research & Academic:**
- National Science Foundation (SBIR/STTR)
- Knight Foundation (journalism/transparency)
- MacArthur Foundation (digital rights)
- Ford Foundation (technology and society)

**Open Source:**
- GitHub Sponsors (recurring donations)
- Open Collective (community funding)
- NLnet Foundation (€5K-50K)
- Prototype Fund (€47K)

**Startup/Tech:**
- Y Combinator (if for-profit pivot)
- Fast Forward (nonprofit accelerator)
- Echoing Green (social innovation)
- Ashoka Fellowship (system change)

---

## Approval & Next Steps

### Decision Criteria

This project proceeds to execution if:

1. **Funding secured**: $450K committed (investment, grants, or combination)
2. **Team committed**: Lead Engineer, ML Engineer, Legal Advisor
3. **Technical validation**: 80%+ accuracy achievable with current approach
4. **Legal review**: Liability exposure acceptable with insurance/disclaimers
5. **Market validation**: Beta user feedback confirms need (NPS ≥30)

### Immediate Next Steps

**Week 1-2:**
- [ ] Secure funding commitment
- [ ] Finalize team hiring/contracting
- [ ] Legal review engagement ($15K)
- [ ] Set up third-party accuracy audit process
- [ ] Create detailed technical roadmap

**Month 1 Deliverables:**
- [ ] Team fully onboarded
- [ ] Legal review completed
- [ ] Test dataset (500+ documents) compiled
- [ ] Accuracy baseline established
- [ ] Beta recruitment campaign launched

### Monitoring & Reporting

**Weekly:**
- Development progress standups
- Blocker identification and resolution
- User feedback review

**Monthly:**
- KPI dashboard review
- Budget vs. actuals
- Roadmap adjustments
- Risk register updates

**Quarterly:**
- OKR assessment
- Strategic pivots if needed
- Funding/runway review
- Partnership progress

---

## Document Approval

**Prepared By:** Product Management
**Date:** 2026-07-03
**Version:** 1.1

**Recommended For Approval:**

The AI Terms & Policies Reviewer BRD outlines a compelling privacy-first solution to a significant market need. The project builds on an existing working prototype, has clear technical feasibility, and addresses a underserved market segment. The privacy-focused positioning and open source approach provide strong differentiation and community trust.

**Approval Signatures:**

| Name | Title | Date |
|------|-------|------|
| | Project Lead | |
| | Engineering Lead | |
| | Legal Advisor | |
| | Business Sponsor | |

**Next Review Date:** May 13, 2026 (Quarterly update)

---

## References

[1] Privacy-conscious internet users: Pew Research Center (2024)
[2] ToS reading statistics: Deloitte Privacy Index (2025)
[3] Legal review costs: American Bar Association Fee Survey (2025)
[4] SMB legal counsel: NSBA Survey (2025)
[5] SaaS tool proliferation: BetterCloud State of SaaSOps (2025)
[6] GDPR fine statistics: DLA Piper GDPR Fines Tracker (2025)
[7] LegalTech market sizing: Thomson Reuters Legal Tech Report (2025)
[8] Open source sustainability: GitHub Open Source Survey (2024)
