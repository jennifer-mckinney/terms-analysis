---
format: corpus-ingestion-plan-addendum
date: 2026-07-04
scope: AU child protections + AU human agency in ADM
floor_version: 2026-current
parent: docs/plans/2026-07-04-corpus-APAC.md
blocks: docs/plans/2026-07-03-results-view-revamp-report-card.md D-Q11
target_output_path: docs/plans/2026-07-04-corpus-APAC-child-agency.md
xref:
  - .claude/library/LIB-LEGAL.md
  - .claude/skills/legal-kb/SKILL.md
  - src/backend/app/services/legal_kb.py
constraints:
  - Planning only. No statute text downloaded into data/legal_corpus/.
  - No code changes. No git operations.
  - Every claim carries a URL verified via WebFetch or WebSearch on 2026-07-03/04.
  - Floor version is 2026-current — see per-entry compilation IDs / registration dates below.
---

# Australia Child Protections + Human Agency Addendum

## Purpose

This addendum extends `docs/plans/2026-07-04-corpus-APAC.md` (parent APAC plan) with two thematic sub-corpora that the parent plan flagged as out-of-scope-for-cluster but load-bearing for the results-view revamp:

1. **AU child protections** — Online Safety Act 2021 (Cth) and its subordinate instruments (BOSE Determination, RAS Declaration, Social Media Minimum Age framework), the OAIC Children's Online Privacy Code (in exposure-draft), and the Age Assurance Technology Trial outputs that inform "reasonable steps" under the SMMA obligation.
2. **AU human agency in ADM** — the Attorney-General's Privacy Act Review ADM recommendations (Tranche 1 already enacted, ADM transparency provisions in grace period to 10 December 2026), the Voluntary AI Safety Standard 2024 (now superseded by the October 2025 Guidance for AI Adoption — both indexed as advisory), the National Framework for the Assurance of AI in Government, and AI Ethics Principles.

The parent APAC plan explicitly deferred the Voluntary AI Safety Standard and AI Ethics Framework ("§ AI guidance — Out of scope for this cluster (defer)"). This addendum takes both up, plus the child-protection stack that the parent plan only referenced as scoping (Online Safety Act 2021 was listed for "Terms-of-Service scoping only" — this addendum turns it into a first-class corpus entry).

## Version floor and verification date

- **Floor**: 2026-current.
- **Verification date**: All source URLs and version identifiers verified via WebFetch or WebSearch on **2026-07-03 / 2026-07-04**.

## Materials in scope

| Jurisdiction | Instrument | Citation | Effective / Version | Source | License |
|---|---|---|---|---|---|
| AU (Cth) | Online Safety Act 2021 (Cth) | Act No. 76 of 2021 (C2021A00076) | Compilation `C2024C00852`, Compilation Date 11 December 2024; 16 Parts including new Part 4A (Social Media Minimum Age) inserted by C2024A00127 | [legislation.gov.au/C2021A00076/latest/text](https://www.legislation.gov.au/C2021A00076/latest/text) | CC BY 4.0 (per legislation.gov.au terms-of-use) with Coat of Arms excluded |
| AU (Cth) | Online Safety Amendment (Social Media Minimum Age) Act 2024 | Act No. 127 of 2024 (C2024A00127) | Royal Assent 10 December 2024; substantive obligations commenced 10 December 2025 | [legislation.gov.au/C2024A00127/asmade](https://www.legislation.gov.au/C2024A00127/asmade) | CC BY 4.0 |
| AU (Cth) | Online Safety (Basic Online Safety Expectations) Determination 2022 | F2022L00062 | Compilation `F2024C00516`, Compilation Date 31 May 2024 (Amendment Determination 2024 registered 30 May 2024, effective 31 May 2024) | [legislation.gov.au/F2022L00062/latest/text](https://www.legislation.gov.au/F2022L00062/latest/text) | CC BY 4.0 |
| AU (Cth) | Online Safety (Restricted Access Systems) Declaration 2022 | F2022L00032 | In force since January 2022 | [legislation.gov.au/Details/F2022L00032](https://www.legislation.gov.au/Details/F2022L00032) | CC BY 4.0 |
| AU (Cth) | eSafety Social Media Minimum Age Regulatory Guidance | eSafety publication (advisory) | Released 16 September 2025; March 2026 compliance-implementation update | [esafety.gov.au/sites/default/files/2025-09/eSafety-SMMA-Regulatory-Guidance.pdf](https://www.esafety.gov.au/sites/default/files/2025-09/eSafety-SMMA-Regulatory-Guidance.pdf) + [March 2026 update](https://www.esafety.gov.au/sites/default/files/2026-03/SocialMediaMinimumAgeComplianceUpdateMarch2026.pdf) | Commonwealth copyright — verify at fetch; likely CC BY 4.0 |
| AU (Cth) | Age Assurance Technology Trial — Final Report | Dept of Infrastructure publication (advisory) | Report finalised end-June 2025; publicly released 1 September 2025 | [infrastructure.gov.au/department/media/publications/age-assurance-technology-trial-final-report](https://www.infrastructure.gov.au/department/media/publications/age-assurance-technology-trial-final-report) + [ageassurance.com.au/report](https://ageassurance.com.au/report/) | Commonwealth copyright; likely CC BY 4.0 — verify at fetch |
| AU (Cth) | OAIC Children's Online Privacy Code | Exposure Draft (statutory APP Code under Privacy Act 1988) | **In exposure-draft consultation** 31 March – 5 June 2026; must be **registered by 10 December 2026** | [oaic.gov.au/privacy/privacy-registers/privacy-codes/childrens-online-privacy-code](https://www.oaic.gov.au/privacy/privacy-registers/privacy-codes/childrens-online-privacy-code) | Commonwealth copyright; CC BY 4.0 typical for OAIC publications — verify at fetch |
| AU (Cth) | Privacy Act 1988 (Cth) — ADM transparency provisions (Tranche 1) | APP 1 amendments under Privacy and Other Legislation Amendment Act 2024 | Royal Assent 10 December 2024; ADM transparency provisions commence **10 December 2026** (two-year grace) | Already covered in parent plan; ADM sub-clauses tagged under this addendum | CC BY 4.0 |
| AU (Cth) | AG Government Response to Privacy Act Review — ADM recommendations (Proposal 19.1 – 19.4) | AG portfolio publication (advisory-status; source of statutory reform) | Government Response released 28 September 2023 | [ag.gov.au/rights-and-protections/publications/government-response-privacy-act-review-report](https://www.ag.gov.au/rights-and-protections/publications/government-response-privacy-act-review-report) | Commonwealth copyright — verify at fetch |
| AU (Cth) | Voluntary AI Safety Standard (VAISS) — 10 guardrails | Dept of Industry publication (voluntary) | Published September 2024; **superseded by** Guidance for AI Adoption (October 2025) but retained as history | [industry.gov.au/publications/voluntary-ai-safety-standard](https://www.industry.gov.au/publications/voluntary-ai-safety-standard) | Commonwealth copyright — verify at fetch |
| AU (Cth) | Guidance for AI Adoption — 6 essential practices | Dept of Industry publication (voluntary, current) | Published 21 October 2025; replaces VAISS 10 guardrails with 6 essential practices | industry.gov.au (verify at fetch) | Commonwealth copyright — verify at fetch |
| AU (Cth) | National Framework for the Assurance of AI in Government | Dept of Finance (government-only guidance) | Released 21 June 2024 by Data and Digital Ministers Meeting | [finance.gov.au/.../national-framework-assurance-artificial-intelligence-government](https://www.finance.gov.au/government/public-data/data-and-digital-ministers-meeting/national-framework-assurance-artificial-intelligence-government) + [PDF](https://www.finance.gov.au/sites/default/files/2024-06/National-framework-for-the-assurance-of-AI-in-government.pdf) | Commonwealth copyright — verify at fetch |
| AU (Cth) | AI Ethics Principles (8 principles) | Dept of Industry publication (voluntary) | Originally 2019; principles remain valid but 2024–2025 guidance layered on top | [industry.gov.au/publications/australias-ai-ethics-principles](https://www.industry.gov.au/publications/australias-ai-ethics-principles) | Commonwealth copyright — verify at fetch |

Materials **noted but explicitly out-of-scope for this addendum** (rationale in "Cross-cutting decisions §CC-Scope"):
- Digital ID Act 2024 (C2024A00025) — has express-consent framework, but its ToS/PP surface is narrower than the child+agency scope; defer to a future "AU identity + consent" addendum.
- Consumer Data Right (CDR) 2024 reset — same rationale; consent-flow changes relevant, but out-of-scope for child+agency corpus.
- Anti-Discrimination AI-related amendments — no primary-statute enactment verified as of 2026-07-04; monitor via version-refresh policy.

## Child protections

### Entry C-1: Online Safety Act 2021 (Cth) — full statute

**C-1.1 Authoritative source URL**
- Statute (canonical, latest compilation): https://www.legislation.gov.au/C2021A00076/latest/text
- Compilation `C2024C00852`, Compilation Date 11 December 2024.
- 16 Parts confirmed via WebFetch 2026-07-04. Structure includes new **Part 4A (Social Media Minimum Age)** inserted by C2024A00127.
- eSafety Commissioner portal (regulator, advisory): https://www.esafety.gov.au

**C-1.2 License / re-use terms**
- CC BY 4.0 per legislation.gov.au terms-of-use (already verified in parent APAC plan §1.2). Coat of Arms excluded.
- Attribution templates: reuse the two-template pattern already codified in parent plan §1.2.
- Commercial re-use: permitted.
- Legal-review gate: **LOW** (same as parent Privacy Act treatment).

**C-1.3 Version identifier**
- Instrument ID: `C2021A00076` (Act ID, permanent).
- Latest compilation: `C2024C00852`, Compilation Date 11 December 2024.
- Executor MUST re-check at fetch — SMMA framework rules were amended March 2026 (see §C-2), which may have triggered a further Act compilation. If so, update `compilation_id` and `compilation_date` accordingly.

**C-1.4 Structural hierarchy**

```
Online Safety Act 2021 (Cth)
  Part 1  — Preliminary
  Part 2  — eSafety Commissioner (functions and powers)
  Part 3  — Complaints, objections and investigations
  Part 4  — Basic Online Safety Expectations (ss 44–63)
  Part 4A — Social Media Minimum Age                       [INSERTED BY C2024A00127; commenced 10 Dec 2025]
  Part 5  — Cyber bullying material targeted at Australian children (ss 64–73)
  Part 6  — Non-consensual sharing of intimate images
  Part 7  — Cyber abuse material targeted at Australian adults
  Part 8  — Material depicting abhorrent violent conduct
  Part 9  — Online content scheme (incl. RAS at s 108)
  Part 10 — Enforcement
  Part 11 — Administrative provisions
  Part 12 — Special accounts
  Part 13 — Information gathering
  Part 14 — Investigative powers
  Part 15 — Disclosure
  Part 16 — Miscellaneous
```

Sections are the primary citation unit (e.g. `OSA s 44`, `OSA s 63C`).

**C-1.5 Chunking recommendation**

Per [[LIB-LEGAL]]:
- Default: 512–1024 tokens per chunk, 128-token overlap.
- **Section chunking**: each Section is its own chunk floor. Sections longer than 1024 tokens split at sub-section boundary with 128-token overlap.
- **Part 4 (BOSE) sections (ss 44–63)**: chunk section-by-section. Section 45 (Determination-making power) is a common citation target — its own chunk.
- **Part 4A (Social Media Minimum Age)**: chunk each section separately. The "reasonable steps" obligation section is a high-frequency citation and MUST be its own chunk.
- **Part 5 (Cyberbullying for children)**: chunk each section separately. Definitions ("Australian child", "cyber-bullying material") kept in the same chunk as the substantive obligation they qualify.
- **Part 9 s 108 (RAS)**: own chunk; cross-linked to the RAS Declaration entry §C-4.

**C-1.6 Metadata schema per chunk**

Extend the shared envelope defined in parent plan §CC2. New fields for this addendum:

```json
{
  "chunk_id": "au-online-safety-act-2021-s44",
  "jurisdiction": "AU",
  "sub_corpus": "AU-CHILD",
  "statute_id": "C2021A00076",
  "compilation_id": "C2024C00852",
  "compilation_date": "2024-12-11",
  "citation_short": "OSA s 44",
  "citation_long": "Online Safety Act 2021 (Cth), Part 4, Section 44",
  "hierarchy": ["Part 4", "Section 44"],
  "structure_type": "section",
  "advisory": false,
  "in_force": true,
  "grace_period_note": null,
  "regulator": "eSafety Commissioner",
  "child_protection_scope": true,
  "human_agency_scope": false,
  "source_url": "https://www.legislation.gov.au/C2021A00076/latest/text#part-4",
  "license": "CC-BY-4.0",
  "attribution_template": "unchanged | modified",
  "fetched_at": "YYYY-MM-DDTHH:MM:SSZ",
  "text_sha256": "..."
}
```

New fields introduced by this addendum (documented once here, applied to all AU-CHILD and AU-AGENCY entries): `sub_corpus`, `regulator`, `child_protection_scope`, `human_agency_scope`.

**C-1.7 Rendering behavior in the revamp UI**

- Rule/LLM finding cites `"OSA s 44"` → resolver matches `citation_short == "OSA s 44"` and `sub_corpus == "AU-CHILD"` → renders chunk with CC BY 4.0 attribution.
- Compound citation `"OSA s 63C(1)"` → resolver matches parent section chunk and highlights sub-clause via `subclauses` map.
- Child-protection findings surface in the "Privacy rights" domain group (per SO4) with a `child_protection_scope=true` badge that changes the copy voice: use the parent-facing tone documented in [[LIB-VOICE]].
- Cyberbullying-scheme citations render an "eSafety complaint route" ancillary link.

**C-1.8 Placeholder-to-real cutover checklist**

- [ ] Replace absent `data/legal_corpus/au-child/` with fetched OSA text (or subdivision within `data/legal_corpus/au/`).
- [ ] Verify compilation ID `C2024C00852` (or newer) at fetch time.
- [ ] Verify Part 4A (SMMA) present in structure.
- [ ] Verify Part 5 (children's cyberbullying) present.
- [ ] Confirm CC BY 4.0 attribution rendered on every OSA citation popover.
- [ ] Add 3 gold-dataset fixtures citing OSA s 44 (BOSE power), OSA s 63C (SMMA reasonable steps — verify section number at fetch), OSA s 108 (RAS).
- [ ] Regenerate legal-KB numpy index.
- [ ] Update `.claude/library/LIB-LEGAL.md` corpus table with the new `AU-CHILD` sub-corpus code.

**C-1.9 Version-refresh policy**

- **Cadence**: annual (July check) + on notification.
- **Notification triggers**:
  - Subscribe to legislation.gov.au ATOM feed for `C2021A00076`.
  - Monitor eSafety Commissioner newsroom for BOSE amendments and SMMA rules updates.
  - Watchlist for statutory review of Online Safety Act (HTI submission July 2024 signals a review cycle underway).
- **Re-index gate**: any compilation-ID change triggers full re-fetch and delta re-chunk of the changed Parts only.

**C-1.10 Legal-review gates**
- LOW risk (CC BY 4.0 covers commercial re-use). Attribution rendering check only.

### Entry C-2: Online Safety Amendment (Social Media Minimum Age) Act 2024

**C-2.1 Authoritative source URL**
- Amending Act: https://www.legislation.gov.au/C2024A00127/asmade
- Effect: this Act inserts Part 4A into the Online Safety Act 2021 (Cth); once compiled into the principal Act (C2021A00076), Part 4A sits inside the OSA compilation.
- Fact sheet (advisory): https://www.infrastructure.gov.au/department/media/publications/online-safety-amendment-social-media-minimum-age-bill-2024-fact-sheet
- eSafety enforcement guidance (advisory): https://www.esafety.gov.au/sites/default/files/2025-09/eSafety-SMMA-Regulatory-Guidance.pdf
- March 2026 compliance update (advisory): https://www.esafety.gov.au/sites/default/files/2026-03/SocialMediaMinimumAgeComplianceUpdateMarch2026.pdf

**C-2.2 License / re-use terms**
- Amending Act: CC BY 4.0 (legislation.gov.au). Attribution template as parent plan §1.2.
- eSafety guidance PDFs: Commonwealth copyright; verify at fetch — eSafety publications typically CC BY 4.0.
- Legal-review gate: **LOW** for the Act itself; **LOW-MEDIUM** for eSafety guidance (verify PDF-embedded copyright statement).

**C-2.3 Version identifier**
- Act ID: `C2024A00127` (Act No. 127 of 2024).
- Royal Assent: 10 December 2024.
- Substantive obligations commenced **10 December 2025** (age-restricted platforms must take reasonable steps to prevent under-16 accounts).
- Rules amended **March 2026** to add criteria for "age-restricted social media platform" — verify at fetch whether a fresh Act compilation was triggered.
- eSafety Regulatory Guidance version: 16 September 2025; March 2026 compliance update follows.

**C-2.4 Structural hierarchy**

The Act itself has a small top-level structure (typical amending Act):
```
Online Safety Amendment (Social Media Minimum Age) Act 2024
  Section 1 — Short title
  Section 2 — Commencement
  Section 3 — Schedules
  Schedule 1
    Part 1 — Amendments to the Online Safety Act 2021
    Part 2 — Other amendments (incl. Age Discrimination Act 2004)
    Part 3 — Transitional provisions
```

The substantive obligations live inside the amended OSA (Part 4A) after compilation. **Do not chunk this amending Act as a standalone corpus** — instead ingest Part 4A of OSA (§C-1) which carries the substantive rules. Ingest this amending Act only as a compilation-provenance record.

**C-2.5 Chunking recommendation**

- **Amending Act itself**: single chunk (short-title + commencement + schedules structure) tagged `structure_type == "amending_act_metadata"` — used for provenance in the citation popover, NOT for LLM retrieval.
- **Substantive text**: chunk inside §C-1 (OSA Part 4A). No duplication.
- **eSafety Regulatory Guidance PDF**: chunk per numbered section within the guidance document; typical guidance chunks are 512–1024 tokens with 128-token overlap. Tag `advisory=true`.
- **March 2026 compliance update PDF**: same chunking as the guidance; tag `advisory=true` and `advisory_type == "compliance-update"`.

**C-2.6 Metadata schema per chunk**

```json
{
  "chunk_id": "au-osa-smma-amending-act-metadata",
  "jurisdiction": "AU",
  "sub_corpus": "AU-CHILD",
  "statute_id": "C2024A00127",
  "citation_short": "OSA SMMA Amending Act",
  "citation_long": "Online Safety Amendment (Social Media Minimum Age) Act 2024 (Cth)",
  "structure_type": "amending_act_metadata",
  "advisory": false,
  "in_force": true,
  "commencement_date": "2025-12-10",
  "child_protection_scope": true,
  "source_url": "https://www.legislation.gov.au/C2024A00127/asmade",
  "license": "CC-BY-4.0"
}
```

Guidance PDFs use the standard chunk schema with `advisory=true`, `regulator="eSafety Commissioner"`, `advisory_type="regulatory-guidance" | "compliance-update"`.

**C-2.7 Rendering behavior in the revamp UI**

- Rule/LLM finding about "under-16 social media ban" → resolver returns the OSA Part 4A chunks (from §C-1) as statute-grade evidence, plus eSafety Regulatory Guidance chunks as advisory context.
- Popover shows: statute short-name, commencement date badge, eSafety guidance link, "reasonable steps" advisory note.
- Age-assurance findings render a link to the Age Assurance Trial Final Report (§C-3).

**C-2.8 Placeholder-to-real cutover checklist**

- [ ] Confirm Part 4A ingestion via §C-1 checklist.
- [ ] Ingest eSafety Regulatory Guidance PDF as advisory chunks in `AU-CHILD` sub-corpus.
- [ ] Ingest March 2026 compliance update PDF as advisory chunks.
- [ ] Add 1 gold-dataset fixture testing "SMMA reasonable steps" retrieval end-to-end.
- [ ] Verify amending-act metadata chunk renders correctly in the citation popover.

**C-2.9 Version-refresh policy**

- **Cadence**: quarterly (guidance can move faster than the statute).
- **Notification triggers**:
  - eSafety newsroom RSS for SMMA compliance updates.
  - Watchlist for further amendments to SMMA rules (March 2026 amendment is precedent).
- **Re-index gate**: any eSafety guidance version bump triggers advisory re-chunk.

**C-2.10 Legal-review gates**
- LOW for the statute. LOW-MEDIUM for guidance PDFs (verify CC BY status at fetch).

### Entry C-3: Age Assurance Technology Trial — Final Report

**C-3.1 Authoritative source URL**
- Landing page: https://www.infrastructure.gov.au/department/media/publications/age-assurance-technology-trial-final-report
- Trial website: https://ageassurance.com.au/report/
- Trial home: https://ageassurance.com.au/

**C-3.2 License / re-use terms**
- Commonwealth copyright; verify at fetch — infrastructure.gov.au publications are typically CC BY 4.0 with Coat of Arms exclusion.
- Legal-review gate: **LOW** (assuming CC BY 4.0 confirmed at fetch).

**C-3.3 Version identifier**
- Trial commenced: November 2024.
- Final report finalised: end of June 2025.
- Publicly released: **1 September 2025**.
- Scope: 48 vendors, 60+ distinct technologies assessed.

**C-3.4 Structural hierarchy**
- Multi-part report (document-native structure). Executor MUST fetch the report and inspect the table of contents to enumerate parts / chapters. Typical assurance-report structure: Executive Summary → Methodology → Findings → Recommendations → Annexes.

**C-3.5 Chunking recommendation**
- 512–1024 tokens per chunk, 128-token overlap.
- Chunk per numbered section within the report.
- Tag all chunks `advisory=true`. This is trial-evidence used to inform "reasonable steps" but is NOT a legally binding technical standard.
- Executive Summary chunk MUST include the top-level finding statement (privacy-preserving age assurance is feasible with layered techniques).

**C-3.6 Metadata schema per chunk**

```json
{
  "chunk_id": "au-age-assurance-trial-final-report-<section-slug>",
  "jurisdiction": "AU",
  "sub_corpus": "AU-CHILD",
  "advisory": true,
  "advisory_type": "trial-report",
  "regulator": "Department of Infrastructure, Transport, Regional Development, Communications, Sport and the Arts",
  "citation_short": "Age Assurance Trial Final Report (2025)",
  "publish_date": "2025-09-01",
  "child_protection_scope": true,
  "source_url": "https://ageassurance.com.au/report/",
  "license": "CC-BY-4.0",
  "attribution_template": "..."
}
```

**C-3.7 Rendering behavior in the revamp UI**
- SMMA-related findings surface Age Assurance Trial chunks as an ancillary "how might a platform verify age" evidence panel, styled distinctly from statute chunks.

**C-3.8 Placeholder-to-real cutover checklist**
- [ ] Confirm CC BY 4.0 or fetch permission.
- [ ] Extract full report ToC before chunking.
- [ ] Store all chunks in advisory namespace; IRP scoring must not treat these as binding.

**C-3.9 Version-refresh policy**
- Static report — no re-fetch cadence needed except in the event of a supplementary trial or errata publication.

**C-3.10 Legal-review gates**
- LOW (advisory report, likely CC BY 4.0).

### Entry C-4: Online Safety (Basic Online Safety Expectations) Determination 2022

**C-4.1 Authoritative source URL**
- Determination (canonical): https://www.legislation.gov.au/F2022L00062/latest/text
- Compilation `F2024C00516`, Compilation Date 31 May 2024.
- Amendment Determination 2024: registered 30 May 2024, effective 31 May 2024.
- eSafety regulatory guidance (advisory): https://www.esafety.gov.au/industry/basic-online-safety-expectations
- eSafety July 2024 Regulatory Guidance PDF: https://www.esafety.gov.au/sites/default/files/2024-07/Basic-Online-Safety-Expectations-regulatory-guidance-July-2024.pdf
- eSafety December 2025 update PDF: https://www.esafety.gov.au/sites/default/files/2025-12/Basic-Online-Safety-Expectations-Regulatory-Guidance-Updated-December2025.pdf

**C-4.2 License / re-use terms**
- Determination: CC BY 4.0 (legislation.gov.au).
- eSafety guidance PDFs: Commonwealth copyright — verify at fetch.
- Legal-review gate: LOW.

**C-4.3 Version identifier**
- Instrument ID: `F2022L00062`.
- Compilation: `F2024C00516`, 31 May 2024.
- Executor MUST re-check compilation ID at fetch; further BOSE amendments were consulted on in November 2023, so more amendments may land in 2026.

**C-4.4 Structural hierarchy**

```
Online Safety (Basic Online Safety Expectations) Determination 2022
  Part 1 — Preliminary
    s 1 (Name), s 3 (Authority), s 4 (Definitions)
  Part 2 — Basic online safety expectations
    Division 1 — Purpose (s 5)
    Division 2 — Safe use expectations (ss 6–10)
    Division 3 — Material and activity expectations (ss 11–12)
    Division 4 — Reports and complaints (ss 13–16)
    Division 5 — Information accessibility (ss 17–18)
    Division 6 — Record keeping (s 19)
    Division 7 — Commissioner dealings (ss 20–21)
```

Section is the primary citation unit.

**C-4.5 Chunking recommendation**
- 512–1024 tokens per chunk, 128-token overlap.
- Chunk per Section. Definitions section (s 4) kept whole where feasible (may exceed 1024; if so, split alphabetically at glossary-term boundaries with overlap).
- Division 3 (child-protection expectations) sections MUST be their own chunks — these are the highest-frequency citation targets for `for_child` chip.

**C-4.6 Metadata schema per chunk**

```json
{
  "chunk_id": "au-bose-2022-s11",
  "jurisdiction": "AU",
  "sub_corpus": "AU-CHILD",
  "statute_id": "F2022L00062",
  "compilation_id": "F2024C00516",
  "compilation_date": "2024-05-31",
  "citation_short": "BOSE s 11",
  "citation_long": "Online Safety (Basic Online Safety Expectations) Determination 2022, Part 2 Division 3, Section 11",
  "structure_type": "section",
  "advisory": false,
  "in_force": true,
  "regulator": "eSafety Commissioner",
  "child_protection_scope": true,
  "source_url": "https://www.legislation.gov.au/F2022L00062/latest/text",
  "license": "CC-BY-4.0"
}
```

**C-4.7 Rendering behavior in the revamp UI**
- BOSE citation resolves via `citation_short` prefix `BOSE`.
- Popover shows Determination short-name, Compilation Date badge, plus link to eSafety Regulatory Guidance if the section number matches a guidance heading (executor implements guidance→section index at ingest).

**C-4.8 Placeholder-to-real cutover checklist**
- [ ] Fetch F2022L00062 latest compilation.
- [ ] Verify Division 3 (child-protection) present.
- [ ] Ingest eSafety BOSE Regulatory Guidance PDFs (July 2024 + December 2025) as advisory.
- [ ] Add 2 gold-dataset fixtures citing BOSE s 6 (safe use) and BOSE s 12 (children access to class 2 material).

**C-4.9 Version-refresh policy**
- Cadence: annual + on notification. Subscribe to F2022L00062 ATOM feed.
- Watchlist: further BOSE amendment determinations (2023 consultation may yield further amendments in 2026).

**C-4.10 Legal-review gates**
- LOW.

### Entry C-5: Online Safety (Restricted Access Systems) Declaration 2022

**C-5.1 Authoritative source URL**
- Declaration: https://www.legislation.gov.au/Details/F2022L00032
- eSafety RAS consultation and background: https://www.esafety.gov.au/about-us/consultation-cooperation/restricted-access-system

**C-5.2 License / re-use terms**
- CC BY 4.0 (legislation.gov.au).
- Legal-review gate: LOW.

**C-5.3 Version identifier**
- Instrument ID: `F2022L00032`.
- In force since January 2022.
- Executor MUST verify latest compilation ID at fetch.

**C-5.4 Structural hierarchy**
- Short subordinate instrument — inspect at fetch. Typical structure: Preliminary → Declaration provisions → Reasonable-steps criteria. Chunk per section.

**C-5.5 Chunking recommendation**
- 512–1024 tokens per chunk, 128-token overlap. Chunk per section.

**C-5.6 Metadata schema per chunk**
- Standard `AU-CHILD` sub-corpus envelope; `citation_short` prefix `RAS Decl`.

**C-5.7 Rendering behavior in the revamp UI**
- Findings about "age-gate for restricted material" → resolver returns RAS Declaration chunks + OSA Part 9 s 108 (parent authority).

**C-5.8 Placeholder-to-real cutover checklist**
- [ ] Fetch and chunk RAS Declaration.
- [ ] Cross-link `hierarchy` metadata to OSA s 108.

**C-5.9 Version-refresh policy**
- Annual + on notification.

**C-5.10 Legal-review gates**
- LOW.

### Entry C-6: OAIC Children's Online Privacy Code

**C-6.1 Authoritative source URL**
- OAIC register page: https://www.oaic.gov.au/privacy/privacy-registers/privacy-codes/childrens-online-privacy-code
- Consultation Report + Exposure Draft artefacts hosted on OAIC portal.

**C-6.2 License / re-use terms**
- Commonwealth copyright; OAIC materials typically CC BY 4.0 — verify at fetch.
- Legal-review gate: **LOW-MEDIUM** while Code remains in exposure-draft (see status caveat §C-6.7).

**C-6.3 Version identifier**
- **Status as of 2026-07-04**: exposure draft; public consultation ran **31 March – 5 June 2026**.
- Statutory deadline: Code **must be registered by 10 December 2026** (two-year deadline flowing from Privacy and Other Legislation Amendment Act 2024, Royal Assent 10 December 2024).
- Legal basis: an **APP Code** registered under the Privacy Act 1988 (Cth).
- Recommended by **Proposal 16.5 of the Privacy Act Review Report** (parent plan already treats Privacy Act 1988 as ingested; this Code is a subordinate instrument).

**C-6.4 Structural hierarchy**
- Exposure-draft structure per WebFetch 2026-07-04: requirements for online services (SMS/RES/DIS as defined in Online Safety Act 2021), APP compliance specifications, additional child-specific handling requirements, application rules based on "likely to be accessed by children" test.
- Executor MUST re-fetch after registration (post 10 Dec 2026) to capture final structure — draft structure may change.

**C-6.5 Chunking recommendation**
- **While in exposure draft**: ingest as `advisory=true` and `advisory_type="exposure-draft"`. Do NOT treat as binding evidence in IRP scoring.
- Chunk per numbered requirement in the draft Code. 512–1024 tokens.
- **After registration**: flip `advisory=false` and `in_force=true`; re-chunk as needed against the registered instrument.

**C-6.6 Metadata schema per chunk**

```json
{
  "chunk_id": "au-childrens-online-privacy-code-exposure-draft-<slug>",
  "jurisdiction": "AU",
  "sub_corpus": "AU-CHILD",
  "citation_short": "COPC (Exposure Draft)",
  "citation_long": "Children's Online Privacy Code (Exposure Draft, OAIC, March 2026)",
  "advisory": true,
  "advisory_type": "exposure-draft",
  "in_force": false,
  "pending_commencement": true,
  "registration_deadline": "2026-12-10",
  "regulator": "OAIC",
  "child_protection_scope": true,
  "source_url": "https://www.oaic.gov.au/privacy/privacy-registers/privacy-codes/childrens-online-privacy-code",
  "license": "CC-BY-4.0 (verify at fetch)"
}
```

**C-6.7 Rendering behavior in the revamp UI**
- Findings that would otherwise cite the Code MUST render an "Exposure Draft — not yet in force" ribbon in the citation popover until `in_force=true` flips.
- Rule engine (`rules.py`) MUST NOT emit binding-obligation findings against exposure-draft chunks; the LLM path may cite them as forthcoming obligations with a "pending" badge.
- Once registered, findings surface in the "Privacy rights" domain with `for_child` chip boost.

**C-6.8 Placeholder-to-real cutover checklist**
- [ ] Fetch exposure-draft PDF or HTML from OAIC.
- [ ] Ingest as advisory with `pending_commencement=true`.
- [ ] Add watchlist item for OAIC registration announcement (target 10 Dec 2026).
- [ ] Post-registration: re-fetch, re-chunk, flip `advisory=false` + `in_force=true` + drop `pending_commencement`.
- [ ] Add 2 gold-dataset fixtures citing exposure-draft PIA obligation and parental-consent-under-15 rule; expect these to test the "pending" ribbon during exposure-draft window, then flip to binding after registration.

**C-6.9 Version-refresh policy**
- **Immediate triggers**: any OAIC announcement, especially registration.
- **Post-registration cadence**: annual + on notification.

**C-6.10 Legal-review gates**
- LOW-MEDIUM while in exposure draft (only substantive risk is rendering pending obligations as if binding).
- Post-registration: LOW.

## Human agency in ADM

### Entry A-1: Privacy Act 1988 (Cth) — ADM transparency provisions (Tranche 1)

**A-1.1 Authoritative source URL**
- Statute (parent): https://www.legislation.gov.au/C2004A03712/latest/text — already covered in parent plan §1.
- Amending Act: Privacy and Other Legislation Amendment Act 2024 (Royal Assent 10 Dec 2024).
- ADM provisions live inside **APP 1** (amended) — surface within Schedule 1 Part 1 of the Privacy Act.

**A-1.2 License / re-use terms**
- CC BY 4.0 (already covered).

**A-1.3 Version identifier**
- Provisions commence **10 December 2026** (two-year grace period).
- Parent plan already flags `grace_period_note` for these provisions; this addendum reuses the same field.

**A-1.4 Structural hierarchy**
- ADM sub-clauses inside APP 1 (privacy policy content requirement for automated decisions with significant effect).
- Parent plan §1.4 already lists APP 1 as one of 13 APPs; this addendum adds a sub-clauses map to APP 1 covering ADM-specific paragraphs.

**A-1.5 Chunking recommendation**
- Reuse the APP-1 chunk from parent plan §1.5 (one chunk per APP rule).
- Add a `subclauses` map for APP 1 covering the ADM-specific paragraphs so the citation resolver can highlight them independently.
- Tag the APP 1 chunk with a new field `has_pending_adm_subclauses = true` until 10 Dec 2026, then flip to false.

**A-1.6 Metadata schema per chunk**

Extend APP 1 chunk metadata:

```json
{
  "chunk_id": "au-privacy-act-1988-app-01",
  "sub_corpus": "AU-AGENCY",
  "human_agency_scope": true,
  "has_pending_adm_subclauses": true,
  "grace_period_note": "APP 1 ADM transparency sub-clauses commence 2026-12-10 per Privacy and Other Legislation Amendment Act 2024",
  "adm_subclauses": ["<offset-range-1>", "<offset-range-2>"],
  ...
}
```

Note: this APP 1 chunk carries both `sub_corpus` values indirectly — it belongs to the primary `AU-PRIV` corpus (parent plan) AND is tagged `AU-AGENCY` for retrieval within this addendum's scope. Executor MAY implement as a single chunk with a tag-list rather than duplicating.

**A-1.7 Rendering behavior in the revamp UI**
- Findings about "automated decision transparency" → resolver returns APP 1 chunk highlighting the ADM sub-clauses via `adm_subclauses` map, with a `grace_period_note` ribbon in the popover.
- Post-10-Dec-2026: drop the ribbon; treat as binding.

**A-1.8 Placeholder-to-real cutover checklist**
- [ ] Populate `adm_subclauses` offset-range list on the APP 1 chunk.
- [ ] Add gold-dataset fixture testing "ADM transparency" retrieval and grace-period ribbon rendering.
- [ ] Watchlist for 10 Dec 2026: flip flag; regression-test rendering.

**A-1.9 Version-refresh policy**
- Piggyback on parent plan §1.9 refresh cadence.
- Tripwire: 10 Dec 2026 grace-period end.

**A-1.10 Legal-review gates**
- LOW (identical to parent Privacy Act treatment).

### Entry A-2: AG Government Response to Privacy Act Review — ADM recommendations (Proposal 19.1 – 19.4)

**A-2.1 Authoritative source URL**
- Landing: https://www.ag.gov.au/rights-and-protections/publications/government-response-privacy-act-review-report
- Consultation portal: https://consultations.ag.gov.au/integrity/privacy-act-review-report/

**A-2.2 License / re-use terms**
- Commonwealth copyright — verify at fetch. AG portfolio materials frequently CC BY 4.0.
- Legal-review gate: LOW.

**A-2.3 Version identifier**
- Government Response released **28 September 2023**.
- Response endorses Proposal 19.1 (privacy policies must disclose types of personal information used in substantially automated decisions with legal or similarly significant effect) and Proposal 19.2 (individual right to request meaningful information about how such automated decisions are made).
- Proposal 19.1 flowed into Tranche 1 (§A-1); Proposal 19.2 (individual right) is Tranche 2 territory — not yet enacted as of 2026-07-04.

**A-2.4 Structural hierarchy**
- Document-native structure; Proposal 19-series lives under "Automated Decision-Making" heading. Enumerate at fetch.

**A-2.5 Chunking recommendation**
- 512–1024 tokens per chunk, 128-token overlap.
- Chunk per Proposal (i.e., 19.1, 19.2, 19.3, 19.4 as separate chunks).
- Tag `advisory=true`, `advisory_type="government-response"`. This document is a policy statement, NOT statute; NOT binding for rule scoring.

**A-2.6 Metadata schema per chunk**
- Standard `AU-AGENCY` envelope; `citation_short == "AG Response Proposal 19.1"` etc.

**A-2.7 Rendering behavior in the revamp UI**
- ADM findings surface Proposal 19-series chunks as "what's coming" advisory context alongside APP 1 statute chunks.

**A-2.8 Placeholder-to-real cutover checklist**
- [ ] Fetch AG Government Response document.
- [ ] Chunk per Proposal.
- [ ] Add 1 gold-dataset fixture testing "ADM right to explanation" pending-legislation retrieval.

**A-2.9 Version-refresh policy**
- Static document; no re-fetch cadence. Watchlist Tranche 2 for the codified equivalent.

**A-2.10 Legal-review gates**
- LOW (advisory).

### Entry A-3: Voluntary AI Safety Standard (VAISS) — 10 guardrails + Guidance for AI Adoption (2025 successor)

**A-3.1 Authoritative source URL**
- VAISS landing (as at Sep 2024): https://www.industry.gov.au/publications/voluntary-ai-safety-standard
- Guidance for AI Adoption (21 October 2025 successor): industry.gov.au — verify canonical URL at fetch.

**A-3.2 License / re-use terms**
- Commonwealth copyright — verify at fetch.
- Legal-review gate: LOW (voluntary, not statute).

**A-3.3 Version identifier**
- VAISS: published September 2024. 10 guardrails.
- **Superseded 21 October 2025** by "Guidance for AI Adoption" — 6 essential practices.
- Both are voluntary. Ingest **both** — VAISS as historical (for older ToS/PP citing "compliant with Voluntary AI Safety Standard"), Guidance for AI Adoption as current.

**A-3.4 Structural hierarchy**
- VAISS: 10 numbered guardrails. Guardrail 5 = "meaningful human oversight"; Guardrail 6 = "inform end-users about AI-enabled decisions, interactions and content".
- Guidance for AI Adoption: 6 essential practices. Enumerate at fetch.

**A-3.5 Chunking recommendation**
- Chunk per guardrail (VAISS) / per essential practice (Guidance for AI Adoption). Chunks tagged `advisory=true`, `advisory_type="voluntary-standard"`.
- Guardrail 5 and Guardrail 6 flagged `human_agency_scope=true` for direct retrieval on ADM/agency queries.

**A-3.6 Metadata schema per chunk**

```json
{
  "chunk_id": "au-vaiss-guardrail-05",
  "jurisdiction": "AU",
  "sub_corpus": "AU-AGENCY",
  "advisory": true,
  "advisory_type": "voluntary-standard",
  "supersession_status": "current | superseded",
  "superseded_by": "au-guidance-ai-adoption-practice-<n>",
  "citation_short": "VAISS Guardrail 5",
  "publish_date": "2024-09",
  "human_agency_scope": true,
  "source_url": "https://www.industry.gov.au/publications/voluntary-ai-safety-standard",
  "license": "verify at fetch"
}
```

**A-3.7 Rendering behavior in the revamp UI**
- "Human oversight" findings surface Guardrail 5 (VAISS) and its Guidance-for-AI-Adoption successor chunk side-by-side, with a "current/superseded" badge.

**A-3.8 Placeholder-to-real cutover checklist**
- [ ] Fetch VAISS + Guidance for AI Adoption.
- [ ] Populate `supersession_status` links between VAISS guardrails and Guidance-for-AI-Adoption practices.
- [ ] Add 2 gold-dataset fixtures: one testing Guardrail 5 retrieval, one testing Guidance-for-AI-Adoption human-oversight practice retrieval.

**A-3.9 Version-refresh policy**
- Voluntary standards move fast — quarterly check + on notification.

**A-3.10 Legal-review gates**
- LOW.

### Entry A-4: National Framework for the Assurance of AI in Government

**A-4.1 Authoritative source URL**
- Landing: https://www.finance.gov.au/government/public-data/data-and-digital-ministers-meeting/national-framework-assurance-artificial-intelligence-government
- PDF: https://www.finance.gov.au/sites/default/files/2024-06/National-framework-for-the-assurance-of-AI-in-government.pdf
- DTA pilot report: https://www.digital.gov.au/policy/ai/ai-assurance-framework-pilot-report/findings-recommendations

**A-4.2 License / re-use terms**
- Commonwealth copyright — verify at fetch.
- Legal-review gate: LOW.

**A-4.3 Version identifier**
- Released **21 June 2024** by Data and Digital Ministers Meeting.
- DTA pilot conducted **September–November 2024**; findings-and-recommendations report published subsequently.

**A-4.4 Structural hierarchy**
- 5 assurance cornerstones + assurance-practice suite mapped to 8 AI Ethics Principles.
- Enumerate at fetch.

**A-4.5 Chunking recommendation**
- Chunk per cornerstone and per practice, tagged `advisory=true`, `advisory_type="government-only-framework"`, `applies_to="government-agencies"`.
- **IMPORTANT**: this framework applies to government agencies, NOT to private-sector ToS/PP authors. Do NOT retrieve these chunks for private-sector findings unless the source ToS/PP is a government service.

**A-4.6 Metadata schema per chunk**

```json
{
  "chunk_id": "au-national-framework-ai-gov-cornerstone-<n>",
  "sub_corpus": "AU-AGENCY",
  "advisory": true,
  "advisory_type": "government-only-framework",
  "applies_to": "government-agencies",
  "human_agency_scope": true,
  "publish_date": "2024-06-21",
  "source_url": "https://www.finance.gov.au/sites/default/files/2024-06/National-framework-for-the-assurance-of-AI-in-government.pdf"
}
```

**A-4.7 Rendering behavior in the revamp UI**
- Retrieval filter must respect `applies_to == "government-agencies"`. Rule engine and LLM path filter out government-only framework chunks when the analyzed ToS/PP is a private-sector document.

**A-4.8 Placeholder-to-real cutover checklist**
- [ ] Fetch framework PDF.
- [ ] Chunk per cornerstone + practice.
- [ ] Wire `applies_to` filter into the retrieval path.
- [ ] Add 1 gold-dataset fixture verifying a private-sector ToS analysis does NOT surface government-only-framework chunks.

**A-4.9 Version-refresh policy**
- Annual + on Ministers Meeting notification.

**A-4.10 Legal-review gates**
- LOW.

### Entry A-5: AI Ethics Principles (8 principles)

**A-5.1 Authoritative source URL**
- Landing: https://www.industry.gov.au/publications/australias-ai-ethics-principles
- Companion "Implementing" doc: https://www.industry.gov.au/publications/implementing-australias-ai-ethics-principles-selection-responsible-ai-practices-and-resources

**A-5.2 License / re-use terms**
- Commonwealth copyright — verify at fetch.
- Legal-review gate: LOW.

**A-5.3 Version identifier**
- Originally 2019.
- Principles remain the reference set as of 2026-07-04. Layered guidance now sits above them (VAISS 2024 → Guidance for AI Adoption Oct 2025 → National Framework 2024).

**A-5.4 Structural hierarchy**
- 8 principles: fairness, accountability, transparency, reliability, privacy and security, human-centred values, contestability, human/social/environmental well-being.

**A-5.5 Chunking recommendation**
- Chunk per principle. Tag `advisory=true`, `advisory_type="voluntary-standard-foundational"`.
- Principles 6 (human-centred values) and 7 (contestability) flagged `human_agency_scope=true`.

**A-5.6 Metadata schema per chunk**
- Standard `AU-AGENCY` envelope; `citation_short == "AI Ethics Principle 6"` etc.

**A-5.7 Rendering behavior in the revamp UI**
- Contestability findings retrieve Principle 7 alongside VAISS Guardrail 5 for a layered "human agency" evidence panel.

**A-5.8 Placeholder-to-real cutover checklist**
- [ ] Fetch principles page.
- [ ] Chunk per principle.
- [ ] Cross-link to VAISS + Guidance-for-AI-Adoption successors.

**A-5.9 Version-refresh policy**
- Low cadence — principles are stable. Watch for supersession by newer framework.

**A-5.10 Legal-review gates**
- LOW.

### Entry A-6: Privacy Act Tranche 2 — Human review right for ADM (not yet enacted)

**A-6.1 Authoritative source URL**
- No enacted URL. Track AG portfolio bill-tracker: https://www.ag.gov.au + Parliament of Australia bills page.
- As of 2026-07-04: AG Michelle Rowland confirmed in February 2026 Senate estimates hearing that Tranche 2 is being progressed; no ETA. Verified via multiple firm-briefing sources (Ashurst, KWM, HSF Kramer).

**A-6.2 License / re-use terms**
- N/A until enacted.

**A-6.3 Version identifier**
- **Not yet enacted as of 2026-07-04**. Ingestion deferred to Phase 3.

**A-6.4 Structural hierarchy**
- Placeholder — structure will be defined on Bill introduction.

**A-6.5 – A-6.10 Chunking / metadata / rendering / cutover / refresh / legal-review**
- All deferred to Phase 3. This entry exists in this plan so the executor knows to monitor and slot in when Tranche 2 lands.
- **Watchlist trigger**: AG bill tracker + Parliament House bill search. Notify on introduction; ingest within 30 days of Royal Assent.

## Cross-cutting decisions

### CC-A1: Sub-corpus jurisdiction codes

New codes introduced by this addendum:
- `AU-CHILD` — Australian child-protection materials (Entries C-1 through C-6).
- `AU-AGENCY` — Australian human-agency-in-ADM materials (Entries A-1 through A-6).

**Decision**: use **sub-corpus tags** (not new top-level jurisdiction codes). A chunk can carry multiple `sub_corpus` values (e.g., APP 1 belongs to `AU-PRIV` from parent plan AND `AU-AGENCY` from this addendum). Rationale:
- Keeps `_VALID_JURISDICTIONS` in `schemas.py` stable (still `AU`, `SG`, etc.).
- Enables cross-corpus retrieval when a query hits both privacy AND agency dimensions (very common for ADM findings).
- Avoids the compound-code trap (`AU-PRIV-CHILD` is fragile and doesn't compose).

If schema constraint prevents multi-value sub_corpus, alternative is a `tags: string[]` field carrying `["au-child", "au-agency"]` etc. Executor to confirm implementation shape when wiring into `legal_kb.py`.

### CC-A2: Metadata schema additions

New fields introduced by this addendum (applied to all entries above):

| Field | Type | Values | Purpose |
|---|---|---|---|
| `sub_corpus` | string \| string[] | `AU-CHILD`, `AU-AGENCY`, plus parent-plan codes | Sub-corpus routing for retrieval |
| `regulator` | string | e.g., `eSafety Commissioner`, `OAIC`, `Department of Industry, Science and Resources`, `Department of Infrastructure...`, `Department of Finance`, `Attorney-General's Department` | Attribution + which regulator's guidance to pair |
| `child_protection_scope` | bool | true / false | Direct retrieval flag for `for_child` chip |
| `human_agency_scope` | bool | true / false | Direct retrieval flag for ADM findings |
| `advisory_type` | string | `regulatory-guidance`, `compliance-update`, `voluntary-standard`, `voluntary-standard-foundational`, `government-only-framework`, `trial-report`, `exposure-draft`, `government-response`, `amending_act_metadata` | Finer-grained advisory routing |
| `applies_to` | string | `private-sector`, `government-agencies`, `both` | Retrieval filter — prevents cross-scope leakage |
| `commencement_date` | ISO date \| null | e.g., `2025-12-10` | Distinct from compilation_date; used for badges |
| `registration_deadline` | ISO date \| null | e.g., `2026-12-10` (COPC) | Watchlist tripwire for exposure-draft materials |
| `has_pending_adm_subclauses` | bool | true / false | APP 1 grace-period flag |
| `adm_subclauses` | string[] | offset-range identifiers | Sub-clause highlight for APP 1 |
| `supersession_status` | string | `current`, `superseded` | For VAISS ↔ Guidance-for-AI-Adoption relationship |
| `superseded_by` | string | chunk_id | Successor pointer |
| `advisory` | bool (existing) | true / false | Reused from parent plan §CC2 |
| `pending_commencement` | bool (existing) | true / false | Reused from parent plan §CC2 |

### CC-A3: Attribution rendering

- All AU CC BY 4.0 materials use the parent plan's shared attribution strip (parent §CC1).
- Exposure-draft chunks (COPC) render a distinct amber "Exposure Draft — not yet in force" ribbon in the citation popover.
- Government-only-framework chunks render a distinct grey "Applies to government agencies only" badge and MUST NOT appear on private-sector analyses.
- VAISS chunks with `supersession_status == "superseded"` render a "Superseded by Guidance for AI Adoption (Oct 2025)" link inline.

### CC-A4: Interconnection with parent APAC plan

| Parent-plan entry | This addendum entry | Relationship |
|---|---|---|
| §1 AU Privacy Act 1988 (parent) | §A-1 APP 1 ADM sub-clauses | **SUPPLEMENTS** — adds ADM-specific sub-clauses map to APP 1 chunk. No new chunk; existing APP 1 chunk gains fields. |
| §1 (parent) advisory list — Australian Voluntary AI Safety Standard "defer" | §A-3 VAISS + Guidance for AI Adoption | **REPLACES** parent-plan deferral. Both indexed as advisory in this addendum. |
| §1 (parent) advisory list — Australian AI Ethics Framework "defer" | §A-5 AI Ethics Principles | **REPLACES** parent-plan deferral. Indexed as advisory. |
| §1 (parent) — Online Safety Act 2021 "Terms-of-Service scoping only" | §C-1 Online Safety Act 2021 (Cth) — full statute | **REPLACES** with first-class corpus entry. Ingest full statute, not scoping-reference only. |
| §CC1 (parent) — Crown-copyright attribution strip | §CC-A3 — attribution strip + exposure-draft ribbon + government-only badge | **SUPPLEMENTS** shared component with three new badge types. |
| §CC2 (parent) — Metadata schema envelope | §CC-A2 — new fields | **SUPPLEMENTS** envelope with 11 new fields. Backward-compatible: all new fields are optional. |
| §CC3 (parent) — Version-refresh cadence | Per-entry refresh policies + tripwires | **SUPPLEMENTS** — adds tripwires: 10 Dec 2026 (COPC registration + APP 1 ADM grace-period end), quarterly for eSafety guidance. |
| §CC4 (parent) — Governance interlocks | Interlock #1 no `_VALID_JURISDICTIONS` change; Interlock #2 add `sub_corpus` field | **SUPPLEMENTS** — confirms no schema Literal change needed. |

### CC-A5: Advisory-vs-statute IRP weighting (reinforces parent §7 open question)

- **Statute-grade** (`advisory=false`, `in_force=true`) — full IRP weight for rule findings.
- **In-force subordinate instruments** (BOSE Determination, RAS Declaration) — full statute-grade weight.
- **Exposure-draft** (COPC pre-registration) — retrieval-only for LLM context; rule engine MUST NOT emit binding findings.
- **Government response / policy document** (AG Response 2023) — retrieval-only for LLM context; not rule-binding.
- **Voluntary standard** (VAISS, Guidance for AI Adoption, AI Ethics Principles) — retrieval-only for LLM context; rule engine MAY emit "beyond-compliance recommendation" findings tagged accordingly.
- **Government-only framework** (National Framework for AI Assurance) — retrieval only when analyzed doc is government service; filter otherwise.

Codified in analyzer, not in this plan.

### CC-Scope: Materials noted-but-out-of-scope

| Material | Rationale for deferral |
|---|---|
| Digital ID Act 2024 (C2024A00025) | Has strong express-consent framework, but ToS/PP surface is narrower than child+agency; better fit for a future "AU identity + consent" addendum. |
| Consumer Data Right (CDR) 2024 reset | Same rationale — CDR consent-flow changes relevant but not aligned to child+agency scope. |
| Anti-Discrimination AI-related amendments | No primary-statute enactment verified as of 2026-07-04. Monitor via version-refresh policy. |

## Phasing recommendation

**Phase 1 (ship-ready, highest weight — ingest first)**:
1. Online Safety Act 2021 (Cth) full statute — §C-1
2. BOSE Determination 2022 — §C-4
3. RAS Declaration 2022 — §C-5
4. Voluntary AI Safety Standard (VAISS) 2024 + Guidance for AI Adoption (Oct 2025) — §A-3
5. AI Ethics Principles — §A-5
6. AG Government Response to Privacy Act Review (ADM Proposal 19-series) — §A-2

Rationale: all in force, all Crown-copyright with CC BY 4.0 defaults, high citation-frequency in consumer-facing ToS/PP.

**Phase 2 (in-flight — ingest with pending-status treatment)**:
7. Online Safety Amendment (SMMA) Act 2024 + eSafety Regulatory Guidance — §C-2
8. Age Assurance Technology Trial Final Report — §C-3
9. OAIC Children's Online Privacy Code — **exposure draft** — §C-6 (flip to `in_force=true` on registration, target 10 Dec 2026)
10. APP 1 ADM sub-clauses — §A-1 (flip `has_pending_adm_subclauses=false` on 10 Dec 2026)
11. National Framework for AI Assurance in Government — §A-4 (only used when analysing government-service ToS)

**Phase 3 (deferred — monitor watchlist)**:
12. Privacy Act Tranche 2 human-review right — §A-6 (not yet enacted; ingest within 30 days of Royal Assent)
13. Digital ID Act 2024, CDR 2024 reset, anti-discrimination AI amendments — noted out-of-scope; separate future addendum.

## Estimated effort

Assumptions match parent plan: one executor + one review pass.

| Entry | Fetch (hrs) | Chunk (hrs) | Test (hrs) | Legal review (hrs) | Total (hrs) |
|---|---|---|---|---|---|
| §C-1 Online Safety Act 2021 (16 Parts, full statute) | 3 | 6 | 3 | 1 | 13 |
| §C-2 SMMA Amending Act (metadata + eSafety guidance PDFs) | 1.5 | 3 | 2 | 0.5 | 7 |
| §C-3 Age Assurance Trial Report | 1 | 3 | 1 | 0.5 | 5.5 |
| §C-4 BOSE Determination 2022 + eSafety guidance | 1.5 | 3 | 2 | 0.5 | 7 |
| §C-5 RAS Declaration 2022 | 0.5 | 1 | 1 | 0.5 | 3 |
| §C-6 COPC Exposure Draft | 1 | 2 | 1 | 1 | 5 |
| §A-1 APP 1 ADM sub-clauses (extension of parent §1) | 0.5 | 1 | 1 | 0 | 2.5 |
| §A-2 AG Government Response Proposal 19-series | 1 | 2 | 1 | 0.5 | 4.5 |
| §A-3 VAISS + Guidance for AI Adoption | 1 | 2 | 1.5 | 0.5 | 5 |
| §A-4 National Framework for AI Assurance | 1 | 2 | 1.5 | 0.5 | 5 |
| §A-5 AI Ethics Principles | 0.5 | 1 | 1 | 0 | 2.5 |
| §A-6 Tranche 2 (deferred) | 0 | 0 | 0 | 0 | 0 (deferred) |
| Cross-cutting: metadata schema fields + attribution component + government-only filter | — | 3 | 3 | — | 6 |
| **Total (Phase 1 + Phase 2)** | **12.5** | **29** | **19** | **5.5** | **66** |

Phase 3 (Tranche 2) not included; estimate on Bill introduction.

## Open questions for owner

1. **Sub-corpus taxonomy — schema shape**: adopt `sub_corpus: string[]` or `tags: string[]` on chunk metadata? Recommend `sub_corpus: string[]` to keep taxonomy explicit; requires `legal_kb.py` accepting a list where currently a scalar is stored.
2. **COPC exposure-draft ingestion timing**: ingest during exposure-draft window (advisory only), or wait for 10 Dec 2026 registration? Recommend **ingest during exposure-draft** so the pending-obligation ribbon is battle-tested before the flip.
3. **SMMA and Age Assurance Trial coupling**: should Age Assurance Trial chunks always co-retrieve with SMMA queries, or gate on chip context (`for_child`)? Recommend co-retrieval by default.
4. **VAISS vs Guidance-for-AI-Adoption presentation**: show both side-by-side in the popover, or hide superseded VAISS unless the analyzed ToS explicitly references it? Recommend side-by-side with a "superseded" badge — audit-trail transparency wins.
5. **Government-only framework filter**: how does the analyzer detect "this ToS is for a government service"? Requires an upstream classifier signal. Recommend adding a boolean `is_government_service` to the `AnalysisPayload` fed by TLD/URL heuristics in `/infer` endpoint (SO8).
6. **AI Ethics Principles supersession**: are the 2019 8 principles still authoritative, or does the Guidance for AI Adoption (Oct 2025) replace them? Recommend treating both as advisory-current until Dept of Industry publishes explicit deprecation.
7. **Tranche 1 ADM grace-period (10 Dec 2026)**: hard-code the flip date in the ingestion metadata, or rely on manual watchlist review? Recommend hard-code with a fallback watchlist alert to force human confirmation.
8. **OAIC copyright status**: verify at fetch — assume CC BY 4.0 but confirm before shipping COPC ingestion.
9. **eSafety guidance PDFs licensing**: verify at fetch. If not CC BY 4.0, adjust chunk metadata `license` field and add attribution rendering.

## Related plan docs

- Parent APAC: [docs/plans/2026-07-04-corpus-APAC.md](2026-07-04-corpus-APAC.md)
- Master revamp: [docs/plans/2026-07-03-results-view-revamp-report-card.md](2026-07-03-results-view-revamp-report-card.md) (blocks D-Q11)
- EU + US companion clusters (planned same date):
  - docs/plans/2026-07-04-corpus-EU.md
  - docs/plans/2026-07-04-corpus-US.md
- Legal-KB skill: [.claude/skills/legal-kb/SKILL.md](../../.claude/skills/legal-kb/SKILL.md)
- Chunking + retrieval reference: [.claude/library/LIB-LEGAL.md](../../.claude/library/LIB-LEGAL.md)

## Verification log

| Claim | Method | URL | Date |
|---|---|---|---|
| OSA 2021 Compilation `C2024C00852`, Compilation Date 11 December 2024, 16 Parts incl. new Part 4A | WebFetch | https://www.legislation.gov.au/C2021A00076/latest/text | 2026-07-04 |
| Online Safety Amendment (SMMA) Act 2024: Assent 10 Dec 2024, substantive commencement 10 Dec 2025 | WebFetch + WebSearch | https://www.legislation.gov.au/C2024A00127/asmade + Parliament fact sheet | 2026-07-04 |
| SMMA affects YouTube, X, Facebook, Instagram, TikTok, Snapchat, Reddit, Twitch, Threads, Kick | WebSearch | Wikipedia + Bird & Bird + DLA Piper | 2026-07-04 |
| eSafety SMMA Regulatory Guidance released 16 Sep 2025; March 2026 compliance update | WebSearch | esafety.gov.au + Lexology | 2026-07-04 |
| Age Assurance Technology Trial: began Nov 2024, final report end-June 2025, released 1 Sep 2025, 48 vendors / 60+ technologies | WebSearch | Bird & Bird + infrastructure.gov.au + ageassurance.com.au | 2026-07-04 |
| BOSE Determination 2022 Compilation `F2024C00516`, Compilation Date 31 May 2024; Amendment Determination 2024 registered 30 May 2024 | WebFetch + WebSearch | https://www.legislation.gov.au/F2022L00062/latest/text + infrastructure.gov.au consultation | 2026-07-04 |
| RAS Declaration 2022 (`F2022L00032`) in force since January 2022 | WebSearch | legislation.gov.au + AUPJCHR 2022/15 | 2026-07-04 |
| COPC exposure draft consultation 31 Mar – 5 Jun 2026; must be registered by 10 Dec 2026; APP Code under Privacy Act 1988 | WebFetch + WebSearch | https://www.oaic.gov.au/privacy/privacy-registers/privacy-codes/childrens-online-privacy-code + DLA + Baker McKenzie | 2026-07-04 |
| APP 1 ADM transparency provisions commence 10 December 2026 (two-year grace) | WebSearch | Ashurst + JWS + Kennedys | 2026-07-04 |
| AG Government Response to Privacy Act Review released 28 September 2023; endorses Proposal 19.1 (privacy-policy ADM disclosure) and 19.2 (meaningful information right) | WebSearch | ag.gov.au + Law Council + PwC + Hawker Britton | 2026-07-04 |
| VAISS published Sep 2024 with 10 guardrails; Guardrail 5 = human oversight, Guardrail 6 = user transparency | WebSearch + WebFetch | industry.gov.au + Securiti + Ashurst + HSF Kramer | 2026-07-04 |
| Guidance for AI Adoption published 21 October 2025; 6 essential practices; supersedes VAISS | WebSearch | Nemko + industry.gov.au | 2026-07-04 |
| National Framework for Assurance of AI in Government released 21 June 2024 by Data and Digital Ministers Meeting; 5 cornerstones mapped to 8 AI Ethics Principles | WebSearch | finance.gov.au + DTA + Securiti + DataGuidance | 2026-07-04 |
| DTA pilot Sep–Nov 2024 with findings-and-recommendations report | WebSearch | digital.gov.au + dta.gov.au | 2026-07-04 |
| AI Ethics Principles = 8 (fairness, accountability, transparency, reliability, privacy/security, human-centred values, contestability, well-being); originally 2019, still current | WebSearch | industry.gov.au + White & Case | 2026-07-04 |
| Privacy Act Tranche 2 not yet enacted as of 2026-07; AG Rowland confirmed progressing in Feb 2026 Senate estimates | WebSearch | Norton Rose Fulbright + KWM + Ashurst + AMLCompliant | 2026-07-04 |
| Digital ID Act 2024 = C2024A00025 (noted out-of-scope for this addendum) | WebSearch | digitalidsystem.gov.au + legislation.gov.au + Maddocks | 2026-07-04 |
| CDR reset announced August 2024 (noted out-of-scope for this addendum) | WebSearch | Ashurst + Pinsent Masons + KWM | 2026-07-04 |
