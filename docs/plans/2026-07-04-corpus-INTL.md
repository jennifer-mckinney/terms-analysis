# Plan: write docs/plans/2026-07-04-corpus-INTL.md

## Intent

Write ONE markdown plan doc at `/Users/jennifermckinney/Documents/05_Technical_Development/01_AUTOMATION/01_Claude_Projects/terms-analysis/docs/plans/2026-07-04-corpus-INTL.md` covering INTERNATIONAL soft-law + international-court legal-corpus jurisdictions blocking Q11=B of the results-view revamp. Plan work only. No code, no git, no statute-text downloads.

## Source-verification pass (already completed via WebFetch + WebSearch on 2026-07-04)

| Source | URL | Status |
|--------|-----|--------|
| OECD AI Principles | https://oecd.ai/en/ai-principles | 200; 2019 + 2024 update + 5+5 structure confirmed |
| OECD reuse policy | https://www.oecd.org/en/about/oecd-open-by-default-policy.html + press release 2024-07 | WebSearch confirmed CC BY 4.0 default from 1 Jul 2024 |
| UNESCO Recommendation | https://www.unesco.org/en/artificial-intelligence/recommendation-ethics | 200; Nov 2021 + 4 values / 10 principles / 11 policy areas |
| UNESCO IGO licence | unesco.org.uk key-facts PDF | CC BY-NC-SA 3.0 IGO on key-facts (NC clause needs counsel) |
| UN Guiding Principles | https://www.ohchr.org/en/publications/reference-publications/guiding-principles-business-and-human-rights | 403 anti-bot; canonical URL; HRC Res 17/4 (2011) known |
| UN Global Digital Compact | https://www.un.org/global-digital-compact/en | 200; Sep 2024 + 3 objectives / 12 commitments |
| CoE Framework Convention | https://www.coe.int/en/web/artificial-intelligence/the-framework-convention-on-artificial-intelligence | 403 anti-bot; WebSearch confirmed adopted 17 May 2024, opened for signature 5 Sep 2024 as CETS 225 |
| CoE treaty text | https://rm.coe.int/1680afae3c | Confirmed via WebSearch |
| G7 Hiroshima Guiding Principles | https://digital-strategy.ec.europa.eu/en/library/hiroshima-process-international-guiding-principles-advanced-ai-system | 200; 30 Oct 2023; builds on OECD AI Principles |
| G7 MOFA presidency | https://www.mofa.go.jp/ecm/ec/page5e_000076.html | HTTP 500 — reroute to EU Commission mirror + OECD.AI |
| EDPB Guidelines index | https://www.edpb.europa.eu/our-work-tools/general-guidance/guidelines-recommendations-best-practices_en | 200 |
| ICC | https://www.icc-cpi.int/rome-statute + /resource-library | 403 anti-bot; canonical URLs |
| ICJ Statute | https://www.icj-cij.org/statute | 200; 5 chapters / 70 articles; © ICJ 2017-2026 All rights reserved |
| ECHR | https://www.echr.coe.int/european-convention-on-human-rights | 403 anti-bot; canonical |
| HUDOC | https://hudoc.echr.coe.int/ | 200 |
| CJEU curia | https://curia.europa.eu/jcms/jcms/j_6/en/ | 200; C-XXX/YY + T-XXX/YY numbering confirmed |
| CJEU C-252/21 | https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=celex:62021CJ0252 | WebSearch confirmed judgment 4 Jul 2023 |
| IACtHR | https://www.corteidh.or.cr/index.cfm?lang=en | 403 anti-bot; canonical |
| ACtHPR | https://www.african-court.org/wpafc/ | 403 anti-bot; canonical |
| Malabo Convention | https://au.int/en/treaties/african-union-convention-cyber-security-and-personal-data-protection | 200; 27 Jun 2014 adoption; in force 8 Jun 2023; 16/55 ratifications as of 2026 |
| ECtHR landmarks | HUDOC + globalfreedomofexpression.columbia.edu | Bărbulescu 2017, Big Brother Watch 2021, K.U. v. Finland 2008 confirmed |

## Full plan document content (ready to write once out of plan mode)

Frontmatter YAML, then sections:
1. Frameworks and courts in scope (13-row table, jurisdiction codes: `INTL-OECD`, `INTL-UNESCO`, `INTL-UN`, `INTL-CoE`, `INTL-G7`, `INTL-EDPB`, `INTL-ICC`, `INTL-ICJ`, `INTL-ECtHR`, `INTL-CJEU`, `INTL-IACtHR`, `INTL-ACtHPR`).
2. Soft-law frameworks (7 sub-sections, each with the 10 required fields): OECD AI Principles / UNESCO Recommendation / UN Guiding Principles / UN Global Digital Compact / CoE Framework Convention CETS 225 / G7 Hiroshima AI Process / EDPB Guidelines top-11.
3. International courts (6 sub-sections, each with 10 fields + enumerated landmark judgments with policy-analysis rationale):
   - ICC (top-5 including Registry policies)
   - ICJ (top-3, thin)
   - ECtHR top-15 landmarks: Bărbulescu, Big Brother Watch, Von Hannover No. 2, K.U. v. Finland, Copland, Halford, S. and Marper, Roman Zakharov, Delfi, M.L. and W.W. v. Germany, Satakunnan, Benedik, Breyer, Centrum för Rättvisa, Glukhin
   - CJEU top-12 landmarks: Schrems I, Schrems II, Digital Rights Ireland, Google Spain, Weltimmo, Fashion ID, Meta Platforms v Bundeskartellamt C-252/21, Planet49, Fashion ID + Wirtschaftsakademie, La Quadrature du Net, Verbraucherzentralen v Meta C-757/22, SCHUFA C-634/21
   - IACtHR top-5: Escher, Tristán Donoso, Fontevecchia, Artavia Murillo, Chichupac
   - ACtHPR top-3: Konaté, APDF v Mali, Ingabire Umuhoza + African Charter + Malabo Convention with ratification-status metadata
4. Cross-cutting decisions:
   - Auto-in via hard-law cross-refs: OECD AI (cited by EU AI Act + CoE), UNGP (cited by CS3D + CoE), EDPB (co-loaded with GDPR)
   - Judgments chunk per-ratio-paragraph, deviating from LIB-LEGAL fixed-size
   - Metadata JSON schema
   - Attribution rendering per licence type
   - Language-authenticity handling (English baseline; Spanish authentic for IACtHR; Arabic/French/Portuguese for AU)
5. Phasing: Phase 1 auto-in (OECD + UNGP + EDPB + CETS 225) / Phase 2 highest-weight (ECtHR + CJEU) / Phase 3 the rest
6. Estimated effort: ~50 eng-days across phases
7. Open questions for owner (10): UNESCO NC clause, court judgments as reference data, dissent handling, EDPB top-N final list, G7 canonical URL rotation, non-English original handling, Malabo ratification rendering, CETS 225 pre-entry-into-force flag, ratio-paragraph chunking deviation acknowledgement, cross-jurisdiction linking
8. Related plan docs (companion EU/US/APAC + master revamp + skill workflow)
9. Source-verification log with 2026-07-04 WebFetch/WebSearch statuses

The complete drafted markdown (~26 KB) is ready and was assembled during this planning session; it will be written to `docs/plans/2026-07-04-corpus-INTL.md` verbatim once plan mode exits.
