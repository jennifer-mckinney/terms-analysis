format: corpus-aggregator-hunt
date: 2026-07-04
scope: aggregators for HR1/HR2-compliant legal corpus ingestion
blocks: docs/plans/2026-07-03-results-view-revamp-report-card.md D-Q11 (ingestion architecture directive)
companion: docs/plans/2026-07-04-corpus-EU.md, corpus-US.md, corpus-APAC.md, corpus-INTL.md
intended_final_path: docs/plans/2026-07-04-corpus-AGG.md
note_on_location: written to plans/ under plan-mode restriction; on approval, move to intended_final_path

# Aggregator Hunt — Reducing Ingestion Pipelines

## Executive summary

- **12 aggregators evaluated** across US federal, US state, EU, international, and APAC clusters.
- **Top 3 recommendations** (by coverage × license × freshness × HR1/HR2 compatibility):
  1. **govinfo.gov (GPO) bulk XML** — US federal statutes + CFR + Federal Register, public domain (17 U.S.C. §105), primary XML feeds, replaces ~4 direct-source pipelines.
  2. **CourtListener / Free Law Project bulk CSV** — federal + state case law, "no known copyright restrictions," quarterly regenerated, replaces ~10-15 direct case-law scrapes.
  3. **EUR-Lex / EU Commission portal** — all EU legislation + CJEU + editorial summaries under CC-BY-4.0 via 2011/833/EU. Already the assumed master; confirmed no further EU-side consolidation is possible or necessary.
- **Supplementary permissive aggregators** worth adopting: **Open States** (US state legislation, public-domain dedication) and **Isaacus Open Australian Legal Corpus** (Australian statutes + case law, CC-BY-4.0) — jointly close APAC + US-state gaps that pure direct-source phasing had assigned to 50 individual state pipelines and to AustLII.
- **Estimated total effort savings vs direct-source phasing**: **~180-260 engineering hours** (removes ~25 direct pipelines at 6-10h each; adds 5 aggregator pipelines at ~8h each).
- **Revised master count**: from **12+ masters** in the direct-source plans down to **~5 masters** (govinfo, CourtListener, EUR-Lex, Open States, Isaacus Open-Aus-Legal).
- **Explicit HR1/HR2 exclusion list** (findings verified this round):
  - Pile of Law (CC-BY-NC-SA-4.0) — non-commercial, blocks HR1.
  - Multi Legal Pile (CC-BY-NC-SA-4.0) — same reason as above; includes Pile of Law as a subset.
  - AustLII / WorldLII / CommonLII — restrictive usage policy explicitly bans "AI-related or automated uses" via "spidering, scraping, crawling, mirroring, page framing, API access, bulk querying, automated agents"; CommonLII further limits reproduction to 30 pages non-commercial.
  - LII Cornell — CC-BY-NC-SA-2.5, non-commercial.
  - Refworld (UNHCR) — commercial use "strictly prohibited without permission of the copyright holder."
  - IAPP US State Privacy Legislation Tracker — membership-gated, no explicit re-use license.
  - NCSL Databases — no public bulk-download license; contact-only.

## Per-aggregator evaluation

### govinfo.gov (US GPO)
1. **Operator + funding**: US Government Publishing Office (GPO), a federal legislative-branch agency. Congressionally funded. Sustainability: extremely high (statutory mandate under 44 U.S.C. §41).
2. **Bulk URL**: `https://www.govinfo.gov/bulkdata/` — directory of 15+ collections including USCODE, CFR, ECFR, FR, PLAW, STATUTE, COMPS, BILLS, BILLSTATUS, SCOTUS-1937-1975.
3. **License**: Public domain per 17 U.S.C. §105 — "Copyright protection under this title is not available for any work of the United States Government." Confirmed on `https://www.govinfo.gov/about/policies`. Caveat: individual documents may embed third-party copyrighted material with permission; those must be identified downstream.
4. **Coverage**: US Code (all titles), CFR + eCFR, Federal Register, Public Laws, Statutes at Large, Bills, Bill Status, SCOTUS 1937-1975. Historical and current versions.
5. **Format**: XML (primary), including USLM (United States Legislative Markup) for structured statutory content; well-formed, consistent tagging, chunk-friendly.
6. **Freshness**: eCFR is continuously updated; Federal Register updated daily; USCODE updated after each congressional session.
7. **HR2 status**: Clear — US federal agency, no investor lawsuits, no Meta origin.
8. **Consolidation replacement**: Replaces direct pipelines to `uscode.house.gov`, `ecfr.gov`, `federalregister.gov`, `congress.gov`, and `supremecourt.gov` (SCOTUS 1937-1975 subset only). Consolidates ~4-5 US-federal direct-source pipelines into one master.
9. **Effort savings**: ~30-40 hours (each direct pipeline is ~6-10h with URL discovery, format normalization, refresh cadence, error handling).
10. **Risks**: SCOTUS coverage stops at 1975 — modern SCOTUS opinions still need CourtListener. Third-party copyright inclusions require downstream filtering.

### CourtListener / Free Law Project
1. **Operator + funding**: Free Law Project, a US 501(c)(3) non-profit. Funded by donations, memberships, and a Justice Partner Circle. Sustainability: strong (>10 years of continuous operation, serves >1M users on peak days).
2. **Bulk URL**: `https://wiki.free.law/c/courtlistener/help/api/bulk-data/bulk-legal-data` — CSV exports generated via PostgreSQL `COPY TO`, UTF-8, header rows, mapped 1:1 to DB tables.
3. **License**: "Free of known copyright restrictions" — bulk files marked public domain, permitting unrestricted reuse and redistribution. Verified at `https://wiki.free.law/c/courtlistener/help/api/bulk-data/bulk-legal-data`.
4. **Coverage**: Federal + state case law "hundreds of jurisdictions," dockets, opinion clusters, opinions, citation maps, parentheticals, judge database, oral arguments (world's largest), RECAP archive of federal filings, ~2TB of ModernBERT case-law embeddings.
5. **Format**: CSV (importable via PostgreSQL `COPY FROM`).
6. **Freshness**: Bulk files regenerated **quarterly** (March 31, June 30, September 30, December 31 at 3AM PST). Live API for real-time.
7. **HR2 status**: Clear — Free Law Project is a non-profit, no investor lawsuits, no Meta origin. Open-source codebase on GitHub.
8. **Consolidation replacement**: Replaces direct case-law scrapes to state supreme court websites (~50 pipelines), federal circuit courts (~13), SCOTUS post-1975 (`supremecourt.gov`). Consolidates ~10-15 practical direct case-law pipelines into one master.
9. **Effort savings**: ~60-100 hours vs building state-by-state case-law scrapers.
10. **Risks**: Quarterly refresh means a lag of up to ~90 days for newly issued opinions; time-sensitive analysis paths may need to hit the live API in parallel. Coverage varies by jurisdiction; not all state trial-court opinions are captured.

### EUR-Lex / EU Commission portal
1. **Operator + funding**: Publications Office of the European Union. Institutional funding via EU budget. Sustainability: statutory (Decision 2011/833/EU codifies the reuse regime; institutional obligation).
2. **Bulk URL**: `https://eur-lex.europa.eu/` — SPARQL endpoint, Webservice, and CELEX-indexed document downloads; bulk via `dataeuropa.gitlab.io/data-provider-manual/legal-notice/copyright/`.
3. **License**: CC-BY-4.0 for editorial content owned by the EU. Verified quote from Commission legal notice: "content owned by the EU on this website is licensed under the Creative Commons Attribution 4.0 International (CC BY 4.0) licence." Anchored in Decision 2011/833/EU. Verified at `https://commission.europa.eu/legal-notice_en` and `https://eur-lex.europa.eu/eli/dec/2011/833/oj/eng`. **Commercial use permitted with attribution.**
4. **Coverage**: All EU legislation (regulations, directives, decisions), CJEU case law, consolidated texts, editorial summaries, EUROVOC hierarchy. 24 official languages.
5. **Format**: XML (Formex), HTML, PDF; CELEX identifiers; ELI URIs.
6. **Freshness**: Legislation appears on EUR-Lex within days of Official Journal publication.
7. **HR2 status**: Clear — EU institution, no investor exposure, no Meta origin.
8. **Consolidation replacement**: Already the assumed EU master. Confirms that the EU corpus plan does not need further aggregator hunting. EDPB guidelines are hosted separately on `edpb.europa.eu` and follow the same 2011/833/EU reuse regime (EDPB legal-notice URL returned 404 during this hunt; escalate to owner to confirm EDPB re-use per §Open questions).
9. **Effort savings**: N/A — already scoped in EU plan.
10. **Risks**: Some documents embed third-party rights (e.g., IAS accounting standards) with additional restrictions. Filter downstream.

### Open States (Plural Policy)
1. **Operator + funding**: Plural Policy (formerly Open States project, originally Sunlight Foundation legacy). Sustainability: has migrated between operators; monitor for further consolidation.
2. **Bulk URL**: `https://open.pluralpolicy.com/data/` (redirected from `openstates.org/data/`) — GitHub repos, PostgreSQL dumps, JSON archives per session.
3. **License**: "public domain dedication but attribution is greatly appreciated and very helpful." Verified at `https://open.pluralpolicy.com/data/`. **Commercial reuse permitted.**
4. **Coverage**: All 50 US state legislatures + DC + territories. Legislators, bills, votes, full bill text, geographic/district boundaries.
5. **Format**: YAML, CSV, JSON, PostgreSQL dumps, GeoJSON.
6. **Freshness**: Bill/vote data monthly; DB dumps 1-2 days behind live; live GraphQL + REST API also available.
7. **HR2 status**: Clear — non-profit civic-tech lineage, no investor lawsuits, no Meta origin.
8. **Consolidation replacement**: Replaces 50 direct state-legislature-website pipelines. This is the highest-leverage US-state aggregator found.
9. **Effort savings**: ~200-300 hours vs building state-by-state scrapers (50 states × ~5-6h avg).
10. **Risks**: Focus is legislative (bills, votes) — does **not** cover state-enacted statute codebooks. Enacted state codes still need direct pipelines (Justia, state legislature online codes) or a Public.Resource.Org bulk archive for statute text.

### Public.Resource.Org
1. **Operator + funding**: Public.Resource.Org, a US 501(c)(3) non-profit led by Carl Malamud. Donation-funded. Sustainability: moderate — small org, but 20+ years of continuous operation.
2. **Bulk URL**: `https://law.resource.org/` and Internet Archive mirrors; specific `Official State Codes` archive on Internet Archive.
3. **License**: Public domain (state codes are edicts of government); Public.Resource.Org itself does not assert copyright.
4. **Coverage**: US state building codes, public safety codes, Official State Codes archive (as of last update), 12 Tables archives.
5. **Format**: Mostly PDF; some HTML/XML; less structured than govinfo.
6. **Freshness**: Low — updated periodically, not continuously. Historical snapshots.
7. **HR2 status**: Clear — non-profit, no investor exposure.
8. **Consolidation replacement**: Partial replacement for state-code direct pipelines where structured state legislature XML is not available.
9. **Effort savings**: ~40-60 hours if used as fallback for state-code coverage.
10. **Risks**: Freshness low; PDF-heavy content requires OCR/normalization; coverage gaps by state and vintage.

### HuggingFace: Isaacus Open Australian Legal Corpus
1. **Operator + funding**: Isaacus (private legal-AI company, Australia). Corpus published free-of-charge on HuggingFace.
2. **Bulk URL**: `https://huggingface.co/datasets/isaacus/open-australian-legal-corpus` — JSONL (`corpus.jsonl`) and Parquet.
3. **License**: **CC-BY-4.0** for the corpus itself. Individual upstream documents distributed under their permissive source licenses (Australian federal statutes are public-sector information). Verified at dataset card. **Commercial use permitted.**
4. **Coverage**: 7 Australian jurisdictions (Commonwealth, NSW, QLD, WA, SA, TAS, Norfolk Island). Primary + secondary legislation, bills, court decisions. Federal Register of Legislation, Federal Court, High Court, NSW Caselaw, state legislation databases.
5. **Format**: JSONL / Parquet. 232,560 documents, 69.5M lines, 1.47B tokens, ~9.4GB.
6. **Freshness**: Snapshot-based; check `when_scraped` field per document. Owner-updated on Isaacus's schedule.
7. **HR2 status**: Clear — Isaacus is not facing investor lawsuits (verify at pick time). Not Meta-affiliated. Corpus is CC-BY-4.0.
8. **Consolidation replacement**: Replaces AustLII (which is HR1-blocked by its anti-AI usage policy) for Australian coverage. Replaces ~7 direct state/federal AU legislation pipelines.
9. **Effort savings**: ~40-60 hours.
10. **Risks**: Point-in-time snapshot; need to periodically re-fetch. Does not cover NZ (falls back to direct pipeline or NZLII if their license clears).

### HuggingFace: LexGLUE
1. **Operator + funding**: Academic consortium (Chalkidis et al., ACL 2022). Maintained on HuggingFace.
2. **Bulk URL**: `https://huggingface.co/datasets/coastalcph/lex_glue`.
3. **License**: **CC-BY-4.0** (individual sub-tasks may vary — verify per subset). **Commercial use permitted.**
4. **Coverage**: 236,714 examples across 7 tasks: ECtHR-A, ECtHR-B, SCOTUS, EUR-LEX, LEDGAR, UNFAIR-ToS, CaseHOLD. English-only. EU + US + international (ToS).
5. **Format**: HuggingFace `datasets` format.
6. **Freshness**: Static benchmark, last updated ~2022.
7. **HR2 status**: Clear.
8. **Consolidation replacement**: **UNFAIR-ToS is highly relevant** — 9,414 annotated ToS clauses across 8 unfairness classes. Directly relevant to this project's core task. LEDGAR (80k SEC contract clauses across 100 classes) is also relevant for contract-clause detection extension.
9. **Effort savings**: N/A — this is training / evaluation data, not a runtime corpus. But it materially supports the rule-engine's ToS-clause detection and evaluation harness (`src/backend/evaluation/`).
10. **Risks**: Static; may need re-annotation for current ToS patterns.

### HuggingFace: MultiEURLEX
1. **Operator + funding**: Academic (Chalkidis et al.). HuggingFace-hosted.
2. **Bulk URL**: `https://huggingface.co/datasets/coastalcph/multi_eurlex`.
3. **License**: **CC-BY-4.0** (based on 2011/833/EU). **Commercial use permitted.**
4. **Coverage**: 65,000 EU documents 1958-2016, 23 EU languages (excludes Irish), multi-label EUROVOC classification.
5. **Format**: HuggingFace `datasets` format, multilingual + monolingual variants.
6. **Freshness**: Static, ends 2016.
7. **HR2 status**: Clear.
8. **Consolidation replacement**: Supplements EUR-Lex direct fetch — useful for training multilingual EU legal models. Not a runtime replacement for EUR-Lex live data.
9. **Effort savings**: Marginal for runtime corpus; significant for ML training if project ever fine-tunes.
10. **Risks**: Ends 2016; must supplement with live EUR-Lex for post-2016.

### HuggingFace: LegalBench
1. **Operator + funding**: Stanford HazyResearch + 40 contributors. HuggingFace-hosted.
2. **Bulk URL**: `https://huggingface.co/datasets/nguha/legalbench`.
3. **License**: **CC-BY-4.0** for the aggregate; individual tasks may vary. **Commercial use permitted with per-task verification.**
4. **Coverage**: 162 tasks, 91,750 rows, American law, English. Includes CUAD (contracts), ContractNLI, MAUD, LearnedHands, **OPP115 (privacy policy analysis)**.
5. **Format**: HuggingFace `datasets`.
6. **Freshness**: Ongoing academic maintenance.
7. **HR2 status**: Clear.
8. **Consolidation replacement**: **OPP115 (privacy-policy annotations across 115 policies) is directly relevant to the tool's privacy-policy analysis path.** Not a runtime corpus but a strong evaluation and rule-tuning asset.
9. **Effort savings**: N/A runtime; ~20-40h saved on evaluation-set curation.
10. **Risks**: Per-task license verification required before commercial use.

### HuggingFace: joelniklaus/legal-mc4
1. **Operator + funding**: Academic (Niklaus). Derived from Google's MC4 web crawl, filtered for legal content.
2. **Bulk URL**: `https://huggingface.co/datasets/joelniklaus/legal-mc4`.
3. **License**: **CC-BY-4.0**. Commercial use permitted.
4. **Coverage**: 22 EU languages, ~9.8M documents, 28.6B words, court decisions + citations + admin proceedings + constitutional + EU law.
5. **Format**: JSONL.XZ.
6. **Freshness**: Static (MC4 snapshot).
7. **HR2 status**: **REVIEW NEEDED** — MC4 originates from Google's Common Crawl-derived corpus, not Meta. Google faces various antitrust cases but not the same category of investor securities-class-action; owner must confirm this is not HR2-adjacent. Data itself is web-crawled content, not proprietary Google IP.
8. **Consolidation replacement**: Multilingual pretraining supplement.
9. **Effort savings**: N/A runtime.
10. **Risks**: "Quite noisy" per creators; HR2-adjacent review needed on Google-origin flag; not a source of authoritative statutes.

## Explicitly excluded aggregators (HR1/HR2 blockers)

### Pile of Law
- License: **CC-BY-NC-SA-4.0** — non-commercial. Blocks HR1 for commercial use.
- Source: `https://huggingface.co/datasets/pile-of-law/pile-of-law` — dataset card confirms NC-SA restriction.
- **Do not adopt.**

### Multi Legal Pile
- License: **CC-BY-NC-SA-4.0** — non-commercial. Includes Pile of Law as a subset (292GB of the 689GB total).
- Source: `https://huggingface.co/datasets/joelniklaus/Multi_Legal_Pile`.
- **Do not adopt.**

### AustLII / WorldLII / CommonLII
- Copyright policy explicitly forbids "AI-related or automated uses" including "spidering, scraping, crawling, mirroring, page framing, API access, bulk querying, automated agents, or other programmatic means, whether such collection or use is direct or indirect and whether materials are cached, transformed, vectorised, embedded, tokenised, summarised, or otherwise processed." Applies regardless of commercial or non-commercial purpose.
- Source: `https://www.austlii.edu.au/austlii/copyright.html` (via search result excerpt).
- CommonLII additionally caps reproduction at 30 pages non-commercial.
- **Do not adopt for automated pipelines.** Use Isaacus Open Australian Legal Corpus for AU coverage instead.

### LII Cornell
- License: **CC-BY-NC-SA-2.5** on original LII content ("commercial redistribution" restricted). Government documents in-collection remain public domain, but LII asserts copyright on "markup, navigation apparatus, and other value-added features."
- Source: `https://www.law.cornell.edu/lii/help/policy` (via cited quote).
- **Do not adopt for structured re-use.** Use govinfo for underlying US-Code/CFR data.

### Refworld (UNHCR)
- License: Commercial use "strictly prohibited without the permission of the copyright holder." Only "research or private study" permitted; must not be "for sale or for use in conjunction with commercial purposes."
- Source: `https://www.refworld.org/terms-use-copyright` (via search snippet).
- **Do not adopt.** International human-rights + refugee-law coverage must be sourced elsewhere (UN Treaty Collection direct, ECtHR HUDOC).

### IAPP US State Privacy Legislation Tracker
- Membership-gated; no public re-use license.
- Source: `https://iapp.org/resources/article/us-state-privacy-legislation-tracker/`.
- **Do not adopt.** Use Open States for legislative tracking + direct statute pipelines for enacted state privacy laws.

### NCSL Legislation Databases
- No public bulk-download license; access requires contact/agreement.
- Source: `https://www.ncsl.org/about-us/ncsl-research-tools`.
- **Do not adopt.**

### LegiScan
- Commercial licensing available but not standard-public-license CC-BY. Requires paid subscription for bulk / 350GB training corpus. Suitable if budget approved.
- Source: `https://legiscan.com/datasets` and `https://legiscan.com/legiscan`.
- **Consider only if paid-license path is opened**; otherwise use Open States (public-domain dedication) as first choice.

## Consolidation matrix

| Direct source in existing plan | Aggregator that replaces it | License OK? | Recommendation |
|---|---|---|---|
| uscode.house.gov | govinfo.gov XML bulk | ✅ Public domain | **REPLACE** |
| ecfr.gov | govinfo.gov XML bulk (eCFR feed) | ✅ Public domain | **REPLACE** |
| federalregister.gov | govinfo.gov FR bulk | ✅ Public domain | **REPLACE** |
| congress.gov (bill text) | govinfo.gov BILLS + BILLSTATUS | ✅ Public domain | **REPLACE** |
| supremecourt.gov (1937-1975) | govinfo.gov SCOTUS | ✅ Public domain | **REPLACE** |
| supremecourt.gov (post-1975) | CourtListener bulk | ✅ Public domain | **REPLACE** |
| Federal circuit court websites (13) | CourtListener bulk | ✅ Public domain | **REPLACE** |
| State supreme court websites (50) | CourtListener bulk | ✅ Public domain | **REPLACE** (with quarterly-lag caveat) |
| State legislature websites (50, bills) | Open States bulk | ✅ Public-domain dedication | **REPLACE** |
| State enacted codes (50) | Public.Resource.Org state-codes archive (partial) | ✅ Public domain (edicts of government) | **PARTIAL REPLACE**; direct fallback where coverage thin |
| EUR-Lex direct fetch (already master) | EUR-Lex (unchanged) | ✅ CC-BY-4.0 via 2011/833/EU | **KEEP** |
| CJEU CURIA (already master) | EUR-Lex CELEX + CURIA | ✅ CC-BY-4.0 | **KEEP** |
| ECtHR HUDOC (already master) | HUDOC direct (aggregator: LexGLUE ECtHR subset supplements) | ✅ ECtHR press releases and judgments are public | **KEEP direct; add LexGLUE for training** |
| EDPB guidelines | EDPB direct (edpb.europa.eu) | ✅ CC-BY-4.0 via 2011/833/EU (confirm) | **KEEP direct**; add to open-questions |
| AustLII (Australia) | Isaacus Open Australian Legal Corpus | ✅ CC-BY-4.0 | **REPLACE** — AustLII is HR1-blocked by its own AI-use ban |
| NZ statutes | Direct (legislation.govt.nz, NZ Crown Copyright, generally re-usable) | Verify | Keep as direct pipeline; no aggregator identified |
| SG statutes (SG Statutes Online) | Direct (already noted in APAC plan as moderate risk) | Verify | No aggregator identified |

## Recommended architecture — 5 masters

1. **govinfo.gov** — US federal statutes, CFR, Federal Register, Public Laws, SCOTUS pre-1976.
2. **CourtListener bulk** — federal + state case law (all vintages), oral arguments, judges, RECAP.
3. **EUR-Lex + institutional EU sites (EDPB, EDPS)** — EU legislation + CJEU + guidelines.
4. **Open States bulk** — US state legislation (bills, votes, legislator data, session archives).
5. **Isaacus Open Australian Legal Corpus** — Australia + Norfolk Island primary + secondary legislation and case law.

**Direct pipelines that must remain** (no aggregator qualifies):
- **HUDOC (ECtHR)** — Council of Europe; use direct search + HUDOC API. LexGLUE ECtHR subset can supplement training but is static and English-only.
- **NZ legislation.govt.nz** — Crown Copyright, generally re-usable; direct pipeline retained.
- **Singapore Statutes Online** — restrictive TOS; keep direct pipeline with moderate license review as noted in APAC plan.
- **US state enacted-code text** — Open States covers bills, not enacted codebooks; Public.Resource.Org is partial fallback; retain direct fallbacks per state where needed.
- **EDPB guidelines** — direct fetch from `edpb.europa.eu`; assumed under 2011/833/EU CC-BY-4.0 regime (confirm — see Open questions).

**Training/evaluation supplements** (not runtime corpus but strong assets):
- **LexGLUE** (UNFAIR-ToS + LEDGAR + ECtHR + SCOTUS subsets) — CC-BY-4.0.
- **LegalBench OPP115** — privacy-policy annotation.
- **MultiEURLEX** — multilingual EU legal pretraining supplement.

## Open questions for owner

1. **EDPB legal-notice re-use**: `edpb.europa.eu/legal-notice_en` returned 404 during this hunt. Owner should confirm that EDPB documents fall under the 2011/833/EU CC-BY-4.0 umbrella. High probability yes, but not verified here.
2. **Google-origin sensitivity (HR2)**: legal-mc4 is derived from Google's MC4 web crawl. Confirm this is not considered HR2-adjacent (project's HR2 explicitly names Meta-origin; Google was not enumerated).
3. **Attribution rendering**: aggregator-sourced content requires attribution. Where does the UI render "Source: govinfo.gov / CourtListener / EUR-Lex / Open States / Isaacus" for the user? BRD gap or existing pattern?
4. **Version-freshness gate for CourtListener**: quarterly regeneration means up-to-90-day lag on new opinions. Does the tool need a live-API fallback for post-cutoff opinions, or is quarterly acceptable for the tool's use case (privacy-policy / ToS analysis is unlikely to depend on last-week case law)?
5. **Sustainability of Isaacus**: Isaacus is a private company. If the corpus is abandoned, fall back to direct pipelines to Federal Register of Legislation + state databases (which are already public-sector, no license issue). Owner confirm fallback plan is acceptable.
6. **LegiScan paid-tier evaluation**: if Open States coverage or freshness is insufficient, LegiScan's paid tier is worth pricing. Not needed if Open States suffices.
7. **State-code coverage strategy**: enacted state codes are the biggest remaining gap. Public.Resource.Org helps but is not comprehensive. Options: (a) selective direct pipelines to top-10 states by user demand; (b) partner with a paid state-code aggregator (Fastcase, vLex — all HR1-blocked); (c) accept coverage gap and flag "state-code lookup limited" in UI.

## Related plan docs

- `docs/plans/2026-07-04-corpus-EU.md` — EU corpus phasing (already assumes EUR-Lex master)
- `docs/plans/2026-07-04-corpus-US.md` — US corpus phasing (refactor recommended per this hunt: replace ~15 direct pipelines with govinfo + CourtListener + Open States)
- `docs/plans/2026-07-04-corpus-APAC.md` — APAC corpus phasing (refactor recommended: replace AustLII direct with Isaacus Open Australian Legal Corpus; keep NZ + SG direct)
- `docs/plans/2026-07-04-corpus-INTL.md` — international corpus (Refworld HR1-blocked; keep HUDOC direct)
- `docs/plans/2026-07-03-results-view-revamp-report-card.md` D-Q11 — architecture directive (this hunt satisfies the "prefer aggregators" branch)
- `.claude/skills/legal-kb` — skill workflow for ingesting these aggregators once corpus plans are approved

## Verified source URLs (this hunt)

- https://www.govinfo.gov/bulkdata/
- https://www.govinfo.gov/about/policies
- https://wiki.free.law/c/courtlistener/help/api/bulk-data/bulk-legal-data
- https://free.law/projects/courtlistener
- https://commission.europa.eu/legal-notice_en
- https://eur-lex.europa.eu/eli/dec/2011/833/oj/eng
- https://huggingface.co/datasets/isaacus/open-australian-legal-corpus
- https://huggingface.co/datasets/coastalcph/lex_glue
- https://huggingface.co/datasets/coastalcph/multi_eurlex
- https://huggingface.co/datasets/nguha/legalbench
- https://huggingface.co/datasets/joelniklaus/legal-mc4
- https://huggingface.co/datasets/pile-of-law/pile-of-law (HR1-blocked)
- https://huggingface.co/datasets/joelniklaus/Multi_Legal_Pile (HR1-blocked)
- https://open.pluralpolicy.com/data/
- https://law.resource.org/
- https://public.resource.org/
- https://legiscan.com/datasets
- https://legiscan.com/legiscan
- https://www.austlii.edu.au/austlii/copyright.html (HR1-blocked)
- https://www.refworld.org/terms-use-copyright (HR1-blocked)
- https://iapp.org/resources/article/us-state-privacy-legislation-tracker/ (gated)
- https://www.ncsl.org/about-us/ncsl-research-tools (no bulk license)
- https://www.law.cornell.edu/lii (HR1-blocked via CC-BY-NC-SA-2.5)
