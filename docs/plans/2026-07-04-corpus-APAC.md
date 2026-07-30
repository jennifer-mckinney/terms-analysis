---
format: corpus-ingestion-plan
date: 2026-07-04
scope: APAC (Australia + Singapore)
floor_version: 2026-current
blocks: docs/plans/2026-07-03-results-view-revamp-report-card.md D-Q11
companion:
  - docs/plans/2026-07-04-corpus-EU.md
  - docs/plans/2026-07-04-corpus-US.md
xref:
  - .claude/library/LIB-LEGAL.md
  - .claude/skills/legal-kb/SKILL.md
  - src/backend/app/services/legal_kb.py
constraints:
  - Planning only. No statute text downloaded into data/legal_corpus/.
  - No code changes. No git operations.
  - Every claim carries a URL verified via WebFetch or WebSearch on 2026-07-03.
  - Floor version is 2026-current: Australia = Compilation 4 June 2026; Singapore = current PDPA text on SSO as of 2026-07-03.
---

# APAC Corpus Ingestion Plan

## Purpose

Unblock D-Q11 (APAC jurisdictions gap) of the results-view revamp. The revamp requires citation-grade rendering of Australian Privacy Principles (APPs) and Singapore PDPA provisions, which cannot ship while `data/legal_corpus/` holds only US + EU placeholders. This plan defines the ingestion contract per statute so an executor session can run the fetch/chunk/index pipeline without further research.

## Version floor and verification date

- **Floor**: 2026-current. Both statutes must be ingested at their most recent 2026 amended compilation.
- **Verification date**: All source URLs and version identifiers below were verified via WebFetch or WebSearch on **2026-07-03**.

## Statutes in scope

| Jurisdiction | Statute | Citation | Compilation / Revised Edition | Last amended | Source | License |
|---|---|---|---|---|---|---|
| AU (Cth) | Privacy Act 1988 (incl. Schedule 1 APPs) | Act No. 119 of 1988 (C2004A03712) | Compilation 4 June 2026 (C2026C00227) | 4 June 2026 | [legislation.gov.au/C2004A03712/latest/text](https://www.legislation.gov.au/C2004A03712/latest/text) | CC BY 4.0 (per legislation.gov.au terms-of-use) with Coat of Arms excluded |
| AU (Cth) | Notifiable Data Breaches (NDB) scheme | Part IIIC of Privacy Act 1988 | Same compilation as parent Act | 4 June 2026 | Same URL, Part IIIC | CC BY 4.0 |
| AU (Cth) | Online Safety Act 2021 (Cth) — Terms-of-Service scoping only | Act No. 76 of 2021 (C2021A00076) | Latest compilation | verify at fetch | [legislation.gov.au/C2021A00076/latest/text](https://www.legislation.gov.au/C2021A00076/latest/text) | CC BY 4.0 |
| SG | Personal Data Protection Act 2012 (PDPA) | Act 26 of 2012 | Current SSO published version | Amendments through 2020 Act + subsequent commencement instruments; Data Portability Obligation (Part 6B) still to commence as of 2026-07-03 | [sso.agc.gov.sg/Act/PDPA2012](https://sso.agc.gov.sg/Act/PDPA2012) | Government of Singapore copyright; SSO grants permission to reproduce legislation subject to [SSO Terms of Use](https://sso.agc.gov.sg/Terms-of-Use); graphics excluded; **not the authoritative text** |

Sources verified:
- AU Privacy Act version + license: WebFetch `https://www.legislation.gov.au/C2004A03712/latest/text` (2026-07-03) — returned Compilation Date "June 4, 2026", instrument ID `C2026C00227`, Schedule 1 = APPs (13 principles, 5 parts).
- AU CC BY 4.0 terms: WebFetch `https://www.legislation.gov.au/terms-of-use` (2026-07-03) — confirmed CC BY 4.0 with two attribution templates (modified vs unchanged).
- SG PDPA terms: WebSearch confirmed SSO terms permit reproduction of legislation subject to Terms of Use; SSO explicitly disclaims authoritative status.
- SG PDPA amendments status: WebSearch confirmed Data Portability Obligation (Part 6B) still not in force as of 2026-07-03; DPO notification requirement effective 1 June 2025; NRIC-for-authentication prohibition effective 1 January 2027.

## Statutes explicitly NOT in scope (this cluster)

- Australia: Spam Act 2003 (Cth), Do Not Call Register Act 2006 (Cth) — marketing-specific, out of ToS/PP scope for v1.
- Singapore: Cybersecurity Act 2018 — critical-info-infrastructure focus, out of scope for consumer ToS/PP analysis.

## Regulator guidance treated as advisory (not part of chunk index)

These are indexed for citation-only, but tagged `advisory=true` in metadata so IRP scoring never treats them as statute-grade evidence.

| Item | Citation weight | URL |
|---|---|---|
| OAIC APP Guidelines (chapter-per-APP) | advisory | [oaic.gov.au/privacy/australian-privacy-principles](https://www.oaic.gov.au/privacy/australian-privacy-principles) |
| Australian Voluntary AI Safety Standard | advisory | industry.gov.au (verify at fetch) |
| PDPC Advisory Guidelines on Key Concepts in the PDPA | advisory | [pdpc.gov.sg/.../advisory-guidelines-on-key-concepts-in-the-personal-data-protection-act](https://www.pdpc.gov.sg/guidelines-and-consultation/2020/03/advisory-guidelines-on-key-concepts-in-the-personal-data-protection-act) |
| PDPC Advisory Guidelines on the PDPA for Selected Topics (revised May 2024) | advisory | [pdpc.gov.sg/.../advisory-guidelines-on-the-pdpa-for-selected-topics-(revised-may-2024).pdf](https://www.pdpc.gov.sg/-/media/files/pdpc/pdf-files/advisory-guidelines/ag-on-selected-topics/advisory-guidelines-on-the-pdpa-for-selected-topics-(revised-may-2024).pdf) |
| PDPC Advisory Guidelines on Children's Personal Data (March 2024) | advisory | [pdpc.gov.sg/.../advisory-guidelines-on-the-pdpa-for-childrens-personal-data-in-the-digital-environment](https://www.pdpc.gov.sg/guidelines-and-consultation/2024/03/advisory-guidelines-on-the-pdpa-for-childrens-personal-data-in-the-digital-environment) |
| PDPC Advisory Guidelines on Use of Personal Data in AI Recommendation and Decision Systems (Feb 2024) | advisory | [pdpc.gov.sg/.../advisory-guidelines-on-use-of-personal-data-in-ai-recommendation-and-decision-systems](https://www.pdpc.gov.sg/guidelines-and-consultation/2024/02/advisory-guidelines-on-use-of-personal-data-in-ai-recommendation-and-decision-systems) |
| Model AI Governance Framework for Generative AI (2024, IMDA + PDPC / AI Verify Foundation) | advisory | [aiverifyfoundation.sg/downloads/Proposed_MGF_Gen_AI_2024.pdf](https://aiverifyfoundation.sg/downloads/Proposed_MGF_Gen_AI_2024.pdf) |

## Per-statute detail

### 1. Australia — Privacy Act 1988 (Cth) + Australian Privacy Principles

**1.1 Authoritative source URL**
- Statute (canonical, latest compilation): https://www.legislation.gov.au/C2004A03712/latest/text
- Schedule 1 (APPs) is embedded in the same document; render with a stable anchor `#Schedule_1`.
- OAIC APP guidance (advisory, chapter-per-APP): https://www.oaic.gov.au/privacy/australian-privacy-principles

**1.2 License / re-use terms**
- **License**: Creative Commons Attribution 4.0 International (CC BY 4.0).
- **Source of license**: legislation.gov.au terms-of-use page (WebFetched 2026-07-03).
- **Exclusions**: Commonwealth Coat of Arms; any third-party material flagged on the page.
- **Attribution template (unchanged content)**:
  > "Sourced from the Federal Register of Legislation at [YYYY-MM-DD]. For the latest information on Australian Government law please go to https://www.legislation.gov.au."
- **Attribution template (modified content, e.g. our chunking)**:
  > "Based on content from the Federal Register of Legislation at [YYYY-MM-DD]. For the latest information on Australian Government legislation please go to https://www.legislation.gov.au."
- **Commercial re-use permitted**: yes, under CC BY 4.0.
- **Legal-review gate**: LOW risk. Attribution template must be rendered on every citation-detail popover. Cutover checklist confirms attribution string present.

**1.3 Version identifier**
- Instrument ID: `C2004A03712` (Act ID, permanent).
- Latest compilation: `C2026C00227`, Compilation Date **4 June 2026**, Compilation No. verify at fetch.
- **Tranche 1 status (verified 2026-07-03)**: Privacy and Other Legislation Amendment Act 2024 received Royal Assent 10 December 2024. Most provisions in force 10 December 2024. Statutory tort of serious invasions of privacy commenced 10 June 2025. Automated-decision-making transparency provisions have a two-year grace period ending 10 December 2026 — flag this in metadata so the analyzer knows ADM provisions may not yet bind at analysis time.
- **Tranche 2 status (verified 2026-07-03)**: Not yet enacted. Expected to cover "fair and reasonable" collection/use test, possible removal of small-business + employee-records exemptions, GDPR-style rights (erasure, portability), expanded definition of "personal information". Ingestion plan MUST re-check status before executor session runs.

**1.4 Structural hierarchy**

```
Privacy Act 1988 (Cth)
  Part I  — Preliminary
    Division 1, Division 2, ...
      Subdivision A, B, ...
        Section 1, 2, 3, ...
  Part II — Information Privacy
  Part IIIA — Credit reporting
  Part IIIC — Notifiable Data Breaches (NDB)
  ...
  Schedule 1 — Australian Privacy Principles
    Part 1 (APP 1, APP 2)                    consideration of personal information privacy
    Part 2 (APP 3, APP 4, APP 5)             collection of personal information
    Part 3 (APP 6, APP 7, APP 8, APP 9)      dealing with personal information
    Part 4 (APP 10, APP 11)                  integrity of personal information
    Part 5 (APP 12, APP 13)                  access to, and correction of, personal information
```

APP text is a *natural chunk unit* distinct from the Act sections. Each APP is a self-contained obligation and should be chunked as one unit (one APP → one chunk), even if that produces a chunk smaller than the 512-token floor.

**1.5 Chunking recommendation**

Per [[LIB-LEGAL]]:
- Default: 512-1024 tokens per chunk, 128-token overlap.
- **APP exception**: one chunk per APP (APP 1 through APP 13 → 13 chunks). No overlap between APPs. Rationale: APPs are cited as atomic units ("APP 6", "APP 11.2"). Splitting an APP across chunks breaks the citation resolver.
- **Section chunking**: sections chunked at 512-1024 tokens with 128-token overlap. Sub-sections stay together within a chunk when possible.
- **Notifiable Data Breach (Part IIIC)**: chunk each section separately; the notification obligation (s 26WK) is a common citation target and must be its own chunk.

**1.6 Metadata schema per chunk**

```json
{
  "chunk_id": "au-privacy-act-1988-app-06",
  "jurisdiction": "AU",
  "statute_id": "C2004A03712",
  "compilation_id": "C2026C00227",
  "compilation_date": "2026-06-04",
  "citation_short": "APP 6",
  "citation_long": "Privacy Act 1988 (Cth), Schedule 1, Part 3, Australian Privacy Principle 6",
  "hierarchy": ["Schedule 1", "Part 3", "APP 6"],
  "structure_type": "app",
  "advisory": false,
  "in_force": true,
  "grace_period_note": null,
  "source_url": "https://www.legislation.gov.au/C2004A03712/latest/text#Schedule_1",
  "license": "CC-BY-4.0",
  "attribution_template": "unchanged | modified",
  "fetched_at": "YYYY-MM-DDTHH:MM:SSZ",
  "text_sha256": "..."
}
```

Structure_type values: `part`, `division`, `subdivision`, `section`, `app`, `schedule`.

**1.7 Rendering behavior in the revamp UI**

- Rule/LLM finding cites `"APP 6"` → resolver matches `citation_short == "APP 6"` → renders chunk in the citation-detail popover with the attribution template rendered inline.
- Compound citation `"APP 11.2"` → resolver matches the parent APP chunk (APP 11) and highlights sub-clause `.2` from the chunk text via a text-range offset stored in an auxiliary `subclauses` map.
- NDB citations `"Privacy Act s 26WK"` → resolver matches `citation_short == "s 26WK"` scoped to `structure_type == "section"`.
- Every citation popover MUST render: statute short-name, compilation date, "in force" badge (or grace-period note), source URL, CC BY 4.0 attribution string.

**1.8 Placeholder-to-real cutover checklist**

- [ ] Replace `data/legal_corpus/au/placeholder.txt` (or absence) with fetched Privacy Act text.
- [ ] Verify compilation ID matches C2026C00227 (or newer) at fetch time.
- [ ] Verify Schedule 1 APPs count = 13.
- [ ] Verify NDB Part IIIC present.
- [ ] Ingest OAIC APP Guidelines as `advisory=true` chunks (separate namespace).
- [ ] Populate `subclauses` map for APP 3, 6, 11, 12 (common sub-clause citations).
- [ ] Confirm CC BY 4.0 attribution string is rendered on every AU citation popover in the results-view revamp.
- [ ] Regenerate legal-KB numpy index (see `src/backend/app/services/legal_kb.py`).
- [ ] Add 3 gold-dataset fixtures citing APP 3, APP 6, APP 11 to verify F1 does not regress vs pre-AU baseline.
- [ ] Update `.claude/library/LIB-LEGAL.md` corpus table.

**1.9 Version-refresh policy**

- **Cadence**: annual (July check) + on notification.
- **Notification triggers**:
  - Subscribe to legislation.gov.au ATOM feed for `C2004A03712`.
  - Watchlist for Tranche 2 bill introduction; re-run ingestion within 30 days of Royal Assent.
  - Watchlist for 10 December 2026 (ADM grace-period end) — flip `in_force = true` on ADM-scoped chunks and drop `grace_period_note`.
- **Re-index gate**: any change to compilation ID triggers full re-fetch and re-chunk of the changed Parts / Schedules only (delta re-index).

**1.10 Legal-review gates**

- LOW risk (CC BY 4.0 covers commercial re-use). Legal review confirms attribution template rendering only.
- MEDIUM risk on Tranche 2 timing: if Tranche 2 lands between ingestion and revamp ship, we must decide whether to ship with Tranche 1 only + flagged pending changes, or delay. Owner decision required.

---

### 2. Singapore — Personal Data Protection Act 2012 (PDPA)

**2.1 Authoritative source URL**
- Statute (canonical): https://sso.agc.gov.sg/Act/PDPA2012
- PDPC portal (advisory guidelines): https://www.pdpc.gov.sg/guidelines-and-consultation
- **Important**: SSO explicitly labels its published text as *not the authoritative version*. Gold-standard is the printed Government Gazette. For our compliance-tool purposes SSO text is acceptable, but the citation popover MUST include the SSO disclaimer.

**2.2 License / re-use terms**
- **License**: Government of Singapore copyright. SSO Terms of Use grant "permission to users to use/reproduce Singapore legislation for print or electronic materials" subject to the [SSO Terms of Use](https://sso.agc.gov.sg/Terms-of-Use).
- **Exclusions**: graphics and images (not a concern for statute-body ingestion).
- **Commercial re-use**: permitted under SSO terms subject to conditions; **legal-review gate required** to confirm our specific use (fine-tuning / RAG index for a commercial compliance analyzer) falls inside the granted permission.
- **Attribution**: SSO does not publish a canonical short attribution template. Recommended attribution string (subject to counsel approval):
  > "Personal Data Protection Act 2012 (Singapore), sourced from Singapore Statutes Online (https://sso.agc.gov.sg) at [YYYY-MM-DD]. SSO text is not the authoritative version; the authoritative version is the printed Government Gazette."
- **Legal-review gate**: **MEDIUM–HIGH risk**. Must confirm with counsel (a) that SSO's grant covers our specific commercial re-use, (b) attribution wording, (c) whether we need to seek explicit AGC permission for the RAG use-case. Do NOT ship SG ingestion to production until this gate closes.

**2.3 Version identifier**
- Act ID: `PDPA2012` (Act 26 of 2012).
- Current version: latest published on SSO as of fetch date. Executor MUST capture the SSO "Published" date shown at the top of the Act page at fetch time and store in metadata.
- **Amendments status (verified 2026-07-03)**:
  - Personal Data Protection (Amendment) Act 2020 — mostly in force 1 February 2021.
  - Data Portability Obligation (Part 6B) — **still not in force** as of 2026-07-03. Chunks belonging to Part 6B must be tagged `in_force = false, pending_commencement = true` so IRP scoring does not treat them as binding obligations.
  - DPO notification requirement — in force 1 June 2025.
  - NRIC-for-authentication prohibition — in force 1 January 2027 (grace period; flag chunks with `grace_period_note`).
- **No further primary-statute amendment enacted in 2024-2026** beyond the above commencement instruments verified as of 2026-07-03. Executor MUST re-verify on fetch.

**2.4 Structural hierarchy**

```
Personal Data Protection Act 2012 (Act 26 of 2012)
  Part 1  — Preliminary
    Division 1, 2, ...
      Section 1, 2, 3, ...
  Part 2  — Administration (PDPC)
  Part 3  — Interpretation of Part 4 to Part 6C  (personal data, individual, organisation, etc.)
  Part 4  — General rules (Consent, Purpose, Notification, Access, Correction, ...)
  Part 5  — Care of personal data (Protection, Retention, Transfer limitation)
  Part 6  — Access to and correction of personal data
  Part 6A — Notification of data breaches
  Part 6B — Data portability                    [NOT YET IN FORCE — flag]
  Part 6C — (other, verify at fetch)
  Part 7  — Do Not Call Registry
  ...
  Schedules
```

Structural note: SSO renders Parts → Divisions → Sections. Sections are the primary citation unit (`PDPA §13`, `PDPA §24`). Executor MUST confirm exact Part numbering at fetch (some Parts may have been renumbered by commencement instruments).

**2.5 Chunking recommendation**

Per [[LIB-LEGAL]]:
- 512-1024 tokens per chunk, 128-token overlap.
- **Section chunking**: each Section is its own chunk floor. Sections longer than 1024 tokens split at the sub-section boundary with 128-token overlap.
- **Part 6A (breach notification)**: chunk sections individually — 26D (assessment), 26E (notification thresholds) are common citations.
- **Part 6B (portability)**: ingest but tag every chunk with `in_force = false`. If Part 6B is not in force at fetch time, IRP recomputation MUST NOT emit binding-obligation findings against Part 6B; instead surface as an informational note "SG portability right pending commencement".
- **Schedules**: chunk per numbered clause.

**2.6 Metadata schema per chunk**

```json
{
  "chunk_id": "sg-pdpa-2012-s13",
  "jurisdiction": "SG",
  "statute_id": "PDPA2012",
  "sso_published_date": "YYYY-MM-DD",
  "citation_short": "PDPA §13",
  "citation_long": "Personal Data Protection Act 2012 (Singapore), Part 4, Section 13",
  "hierarchy": ["Part 4", "Section 13"],
  "structure_type": "section",
  "advisory": false,
  "in_force": true,
  "pending_commencement": false,
  "grace_period_note": null,
  "source_url": "https://sso.agc.gov.sg/Act/PDPA2012#pr13-",
  "license": "SG-Gov-Copyright-SSO-Permission",
  "authoritative_disclaimer": "SSO text is not the authoritative version; the authoritative version is the printed Government Gazette.",
  "attribution_template": "...",
  "fetched_at": "YYYY-MM-DDTHH:MM:SSZ",
  "text_sha256": "..."
}
```

Structure_type values: `part`, `division`, `section`, `schedule`.

**2.7 Rendering behavior in the revamp UI**

- Rule/LLM finding cites `"PDPA §13"` → resolver matches `citation_short == "PDPA §13"` → renders chunk in citation-detail popover with the SSO disclaimer and attribution string rendered inline.
- Compound citation `"PDPA §26D(2)"` → resolver matches `s 26D` chunk and highlights sub-clause `(2)` via `subclauses` map.
- Part 6B citation (portability) → popover shows the "pending commencement" ribbon and IRP badge shows informational-only.
- Every SG citation popover MUST render: SSO source URL, SSO published date, authoritative-Gazette disclaimer, in-force status.

**2.8 Placeholder-to-real cutover checklist**

- [ ] **BLOCKING: legal-review sign-off** on SSO re-use for commercial RAG use-case + attribution wording (owner: legal counsel).
- [ ] Verify SSO published date at fetch and store in metadata.
- [ ] Verify Data Portability Obligation (Part 6B) in-force status at fetch; set `in_force`/`pending_commencement` accordingly.
- [ ] Tag DPO-notification and NRIC-authentication chunks with grace-period metadata.
- [ ] Ingest PDPC Advisory Guidelines as `advisory=true` in separate namespace.
- [ ] Confirm SSO disclaimer + attribution rendered on every SG citation popover.
- [ ] Regenerate legal-KB numpy index.
- [ ] Add 3 gold-dataset fixtures citing PDPA §13 (consent), §24 (protection), §26D (breach notification) to verify F1.
- [ ] Update `.claude/library/LIB-LEGAL.md` corpus table.

**2.9 Version-refresh policy**

- **Cadence**: annual (July check) + on notification.
- **Notification triggers**:
  - Watch PDPC newsroom RSS + AGC bill-tracker for PDPA amendment bills.
  - Watchlist for Part 6B (Data Portability) commencement — flip `in_force = true, pending_commencement = false` when notified.
  - Watchlist for 1 January 2027 (NRIC-authentication effective date) — drop grace-period note on affected chunks.
- **Re-index gate**: any SSO published-date change triggers a differential re-fetch of changed Parts.

**2.10 Legal-review gates**

- **MEDIUM–HIGH risk**. Executor MUST NOT ship SG ingestion to production until counsel confirms:
  1. SSO Terms of Use grant covers our commercial RAG / compliance-analyzer use-case.
  2. Attribution wording is acceptable.
  3. Whether AGC explicit permission letter is required (some commercial re-use scenarios need a letter).
- Fallback if counsel says no: ingest only regulator-published guidance (PDPC Advisory Guidelines) which are more permissively licensed; render statute citations as external hyperlinks with no inline text.

---

### 3. AI guidance (advisory)

**In scope (index as `advisory=true`, do not treat as statute-grade evidence)**:
- **PDPC Advisory Guidelines on Use of Personal Data in AI Recommendation and Decision Systems** (Feb 2024) — directly relevant to LLM-based ToS/PP claims about AI use of user data.
- **PDPC Advisory Guidelines on the PDPA for Children's Personal Data in the Digital Environment** (March 2024) — supports `for_child` context chip claims.
- **Model AI Governance Framework for Generative AI** (2024, IMDA + PDPC / AI Verify Foundation) — voluntary framework; useful for surfacing "beyond-compliance" recommendations but NOT for IRP-graded findings.

**Out of scope for this cluster (defer)**:
- Australian Voluntary AI Safety Standard — voluntary industry framework, not a statute; low citation-frequency in consumer ToS/PP. Re-evaluate in a future ingestion cycle.
- Australian AI Ethics Framework — same rationale.

---

## Cross-cutting decisions

### CC1: Crown-copyright attribution rendering pattern

- Every AU citation popover renders a footer strip: `Sourced from the Federal Register of Legislation at YYYY-MM-DD. CC BY 4.0. See https://www.legislation.gov.au`.
- Every SG citation popover renders a footer strip: `Sourced from Singapore Statutes Online (https://sso.agc.gov.sg) at YYYY-MM-DD. SSO text is not the authoritative version.`
- Attribution strip is a shared UI component; executor implements once, both jurisdictions consume.

### CC2: Metadata schema (JSON snippet)

Both jurisdictions share this envelope (jurisdiction-specific fields added as extensions):

```json
{
  "chunk_id": "string",
  "jurisdiction": "AU | SG",
  "statute_id": "string",
  "compilation_id": "string | null",
  "compilation_date": "YYYY-MM-DD | null",
  "sso_published_date": "YYYY-MM-DD | null",
  "citation_short": "string",
  "citation_long": "string",
  "hierarchy": ["string", "..."],
  "structure_type": "part | division | subdivision | section | app | schedule",
  "advisory": "bool",
  "in_force": "bool",
  "pending_commencement": "bool",
  "grace_period_note": "string | null",
  "source_url": "string",
  "license": "CC-BY-4.0 | SG-Gov-Copyright-SSO-Permission",
  "attribution_template": "string",
  "authoritative_disclaimer": "string | null",
  "fetched_at": "ISO8601 UTC",
  "text_sha256": "hex"
}
```

### CC3: Version-refresh cadence

- **Annual**: run `scripts/legal_kb/refresh_apac.py` (to be created — not in this plan's scope) each July.
- **Notification-driven**: subscribe to legislation.gov.au ATOM feed (AU) and monitor PDPC newsroom + AGC bill tracker (SG).
- **Grace-period tripwires**: 10 Dec 2026 (AU ADM), Part 6B commencement (SG portability, TBD), 1 Jan 2027 (SG NRIC).

### CC4: Governance interlocks

- Adding these jurisdictions does **not** alter `_VALID_JURISDICTIONS` in `main.py` — both `AU` and `SG` are already valid per `schemas.py` jurisdiction Literal (verify at executor session; if missing, that becomes a schema PR, not this ingestion PR).
- Legal-KB re-index runs `numpy` exhaustive search per HR2 (no FAISS). Confirm memory footprint after AU+SG ingest stays under existing budget.

---

## Estimated effort

| Statute | Fetch (hrs) | Chunk (hrs) | Test (hrs) | Legal review (hrs) | Total (hrs) |
|---|---|---|---|---|---|
| AU Privacy Act + Sched 1 APPs | 2 | 4 | 3 | 1 | 10 |
| AU NDB (Part IIIC, subset already in Privacy Act ingest) | 0.5 | 1 | 1 | 0 | 2.5 |
| SG PDPA | 2 | 5 | 3 | **4 (BLOCKING gate)** | 14 |
| OAIC APP Guidelines (advisory, chapter-per-APP) | 1.5 | 3 | 1 | 0 | 5.5 |
| PDPC Advisory Guidelines (3 documents) | 2 | 4 | 1 | 1 | 8 |
| Model AI Gov Framework GenAI | 0.5 | 1 | 0.5 | 0.5 | 2.5 |
| Cross-cutting: attribution UI + metadata schema wiring | — | 2 | 2 | — | 4 |
| **Total** | **8.5** | **20** | **11.5** | **6.5** | **46.5** |

Assumptions:
- One executor + one review pass, no rework beyond gold-fixture verification.
- SG legal-review gate assumed to resolve in 4 hrs of counsel time. If counsel requires an AGC permission letter, add ~2-4 weeks calendar time (not effort hours).

---

## Open questions for owner

1. **SG re-use license — BLOCKING**: does SSO's grant of "permission to use/reproduce Singapore legislation" extend to our commercial RAG use-case, or do we need a letter from AGC? Cannot ship SG ingestion without this call.
2. **AU Tranche 2 timing**: if Tranche 2 lands in the window between ingestion and revamp ship, do we (a) ship on Tranche 1 with flagged pending sections, (b) delay revamp until Tranche 2 ingested, or (c) ship Tranche 1 and hot-patch Tranche 2 post-launch?
3. **AU ADM grace period (ends 10 Dec 2026)**: ship pre- or post-cutover? Recommend pre-cutover with `grace_period_note` set and flip on the day.
4. **SG Part 6B (Data Portability, not yet in force)**: ingest as pending, or defer until commenced? Recommend ingest-as-pending so we're ready to flip.
5. **Advisory guidelines separation**: should advisory guidelines live in a separate index namespace (`legal_kb_advisory/`) or share the primary namespace with `advisory=true` filter? Recommend separate namespace for cleaner IRP-scoring boundaries.
6. **NRIC prohibition (1 Jan 2027)**: relevant to the ToS/PP analyzer at all? Recommend indexing as advisory since it's an authentication-practice rule, not a ToS-clause rule.
7. **Advisory-guidelines vs statute IRP weighting**: confirm that `advisory=true` chunks contribute to LLM context but NOT to rule-derived IRP scoring. Should be codified in the analyzer, not in this plan.

---

## Related plan docs

- Master revamp plan: [docs/plans/2026-07-03-results-view-revamp-report-card.md](2026-07-03-results-view-revamp-report-card.md) (blocks D-Q11 unblocked by this doc)
- Sketches: [docs/plans/2026-07-03-results-view-revamp-sketches.md](2026-07-03-results-view-revamp-sketches.md)
- Companion clusters (planned same date):
  - docs/plans/2026-07-04-corpus-EU.md
  - docs/plans/2026-07-04-corpus-US.md
- Legal-KB skill: [.claude/skills/legal-kb/SKILL.md](../../.claude/skills/legal-kb/SKILL.md)
- Chunking + retrieval reference: [.claude/library/LIB-LEGAL.md](../../.claude/library/LIB-LEGAL.md)

---

## Verification log

| Claim | Method | URL | Date |
|---|---|---|---|
| AU Privacy Act compilation date = 2026-06-04 (C2026C00227), Schedule 1 = 13 APPs in 5 Parts | WebFetch | https://www.legislation.gov.au/C2004A03712/latest/text | 2026-07-03 |
| AU legislation.gov.au = CC BY 4.0, Coat of Arms excluded, two attribution templates | WebFetch | https://www.legislation.gov.au/terms-of-use | 2026-07-03 |
| AU Tranche 1 in force since 10 Dec 2024; ADM provisions have grace period to 10 Dec 2026; Tranche 2 not yet enacted | WebSearch | Norton Rose Fulbright + Parliament of Australia bill digest + Attorney-General's Dept | 2026-07-03 |
| SG PDPA canonical source (SSO); SSO published version is *not* authoritative | WebSearch | https://sso.agc.gov.sg/Act/PDPA2012 + https://sso.agc.gov.sg/Terms-of-Use | 2026-07-03 |
| SG Data Portability Obligation (Part 6B) not yet in force; DPO effective 1 Jun 2025; NRIC prohibition effective 1 Jan 2027 | WebSearch | ICLG SG Data Protection 2025-26 + PDPC guidance + PwC SG | 2026-07-03 |
| PDPC Advisory Guidelines URLs (Key Concepts, Selected Topics revised May 2024, Children's Data March 2024, AI Recommendation Feb 2024) | WebSearch | https://www.pdpc.gov.sg/guidelines-and-consultation | 2026-07-03 |
| SG Model AI Governance Framework for GenAI (2024, IMDA + PDPC / AI Verify Foundation) | WebSearch | https://aiverifyfoundation.sg/downloads/Proposed_MGF_Gen_AI_2024.pdf | 2026-07-03 |
| OAIC hosts APP guidance chapter-per-APP (advisory), Commonwealth of Australia copyright | WebFetch | https://www.oaic.gov.au/privacy/australian-privacy-principles | 2026-07-03 |
