# Issue #19 — BRD / PRD Compliance Audit

Companion to `issue-19-plain-language-design.html`. Every BRD/PRD requirement below is anchored to its source and marked with the mockup's current state: **met** (rendered as designed), **partial** (rendered but with a caveat), or **gap** (not rendered — planned but outside the mockup's scope).

Source docs:
- `docs/BRD_Terms_Policies_Reviewer.md` v1.0
- `docs/PRD_Terms_Policies_Reviewer.md` v2.0
- Issue #19 (Design: plain-language guided intake + verdict-first results)
- `PRODUCT.md` (brand personality: Clear, Calm, Empowering)

---

## BRD requirements

| Req | Source | Status | Notes |
|---|---|---|---|
| Privacy-first, local processing | BRD §Core Value Propositions #1 | **met** | Privacy note: "Processed locally. Policy text is not stored. No account required." Reinforced in scope-box "Only the document itself was analyzed." |
| Multi-format ingestion (URL / PDF / DOCX / RTF / HTML / TXT) | BRD §Current State | **met** | 3 tabs: Paste link, Paste text, Upload file. File-drop accepts `.pdf,.docx,.rtf,.html,.txt` (per PRD F1.2). |
| Multi-jurisdiction compliance mapping (30 codes) | BRD §Jurisdiction Support | **met** | Jurisdictions inferred server-side per issue #19; user-facing selection uses plain country + region, not 30 codes. Location Q is conditional (only shows if inference fails). |
| Industry-specific analysis profiles | BRD §Industry Profiles | **partial** | Not user-facing in the intake per issue #19; industry inferred from URL domain (e.g., facebook.com → Social Media). Power users can override on results page ("Advanced" link — not shown in mockup). |
| Severity-weighted risk scoring + IRP | BRD §Risk Scoring Methodology + LIB-RULES | **met** | Overall risk score (7.8/10) + grade (C) shown as secondary context. Per-finding IRP breakdown (Impact, Likelihood, Safeguards) surfaced inside expanded legal details. |
| Plain-language explanations | BRD §Core Value Propositions #3 | **met** | Verdict, top-things, and per-finding `finding-plain` paragraphs all use non-legal language, therapist-curious tone, observational voice. |
| Evidence citations from source docs | BRD §Core Value Propositions #3 | **met** | Each finding shows: verbatim quote in `finding-excerpt`, legal citations in `finding-basis`, line references (`Lines X to Y`) with "See in policy →" entry point. |
| Letter grades A-F | BRD §Risk Scoring Methodology | **met** | Grade C. Higher risk. Shown as secondary label, not headline. Issue #19 explicitly demotes the letter grade to context per "letter grades" being a jargon barrier for non-experts. |
| Open source / trust through transparency | BRD §Core Value Propositions #3 | **met** | Scope box explicitly names what was and wasn't checked, prevents false confidence per issue #19 §Scope-honesty gap. |

## PRD F1: Document Ingestion

| Req | Source | Status | Notes |
|---|---|---|---|
| F1.1 URL Input | PRD F1.1 | **met** | Text input with URL placeholder + hint "Any URL that leads to a privacy policy or terms of service page works here." |
| F1.2 File Upload — PDF/DOCX/RTF/HTML/TXT, 10MB, drag-drop | PRD F1.2 | **met** | `.file-drop` with dashed border, hover state, "Drop a file here, or click to browse. PDF, DOCX, RTF, HTML, or TXT. Up to 10MB." |
| F1.3 Text Paste — 50k chars, char counter, short-text warning | PRD F1.3 | **partial** | Textarea with placeholder + footer note "Up to 50,000 characters. Text stays on this machine." Live char counter and short-text warning are behaviors not surfaced in the static mockup — retained as Streamlit implementation detail. |

## PRD F2: Analysis Configuration

| Req | Source | Status | Notes |
|---|---|---|---|
| F2.1 Jurisdiction Selection (30 codes, defaults US-CA + GDPR) | PRD F2.1 | **met** | Replaced with inference per issue #19. Conditional location Q: plain country + region names, only shows when inference can't determine jurisdiction. Country defaults from browser location; blank if VPN detected. |
| F2.2 Doc Type Selection (Privacy Policy / ToS / Cookie / DPA / Combined) | PRD F2.2 | **partial** | Inferred from URL domain and text signals. Not exposed in primary flow; "Advanced" override on results page (not shown in mockup). |
| F2.3 Industry Profile (optional) | PRD F2.3 | **partial** | Same treatment as F2.2 — inferred server-side, not shown in intake. |

## PRD F3: Risk Analysis Engine

| Req | Source | Status | Notes |
|---|---|---|---|
| F3.1 Risk Scoring — severity-weighted + IRP formula | PRD F3.1 | **met** | Overall 7.8/10 with gradient risk-bar and dot marker at 78%. Per-finding IRP composite computed from Impact/Likelihood/Safeguards (backend already shipped this as of the IRP implementation session). |
| F3.2 Risk Categories (9 core + ~50 expanded) | PRD F3.2 | **met** | Categories shown per finding: AI Training, Data Sale / Sharing, Tracking / Profiling, Dark Patterns. 4 more (Retention, ADM, Children's Privacy, Cross-Border Transfer) referenced in the "+ 4 more issues" line. |
| F3.3 Evidence Binding — excerpt, line_start/end, legal_basis | PRD F3.3 | **met** | `finding-excerpt` (verbatim quote), `finding-loc` ("Lines X to Y in the source policy"), `finding-basis` (citations). "See in policy →" link entry point to Verify View. |
| F3.4 Confidence Scoring + Review Queue | PRD F3.4 | **partial** | Confidence % shown in each finding's IRP row (88-94% across the 4 shown). Review queue not visualized (implementation-side workflow, not user-facing per PRD). |

## PRD F4: Results Display

| Req | Source | Status | Notes |
|---|---|---|---|
| F4.1 Overview Summary — grade, risk score, findings breakdown | PRD F4.1 | **met** | Three score cards: Risk level (7.8/10, Grade C), Policy coverage (6/8 sections found), Issues found (8 total, 3 high · 4 medium · 1 low). |
| F4.2 Findings List — collapsible cards, filters, sorting | PRD F4.2 | **partial** | Collapsed `<details>` accordion with severity tag, category, IRP badge, excerpt, plain-language explanation, citations, line ref, IRP components, and confidence. Filters/sorting not exposed in this mockup (post-approval addition). |
| F4.3 Verify View — split-pane document + highlighted findings | PRD F4.3 | **partial** | Entry point present: each finding has a "See in policy →" link (`href="#verify-N"`) intended to open a modal or expanded pane. Actual split-pane implementation is a follow-up per PRD MVP scope. |
| F4.4 Plain Language Explanations | PRD F4.4 | **met** | Every finding has a `finding-plain` sentence. Top-things bullets are already plain-language observational translations. Verdict subline and action-list items all avoid jargon. |

## PRD F5: Export & Reporting

| Req | Source | Status | Notes |
|---|---|---|---|
| F5.1 PDF Export — executive summary, findings, evidence | PRD F5.1 | **met** | "Save PDF report" button in export bar. Backend implementation exists (see `main.py` PDF export endpoint). |
| F5.2 JSON Export — full findings payload | PRD F5.2 | **met** | "Download JSON" button. Backend endpoint exists. |
| F5.3 CSV Export (bulk) — summary + detailed | PRD F5.3 | **met** | "Download CSV" button. |

## PRD F6-F8

| Req | Source | Status | Notes |
|---|---|---|---|
| F6 Watchlist Monitoring | PRD F6 | **gap** | Post-MVP per PRD Phase 4 scope; entry point not needed in this mockup. |
| F7 Vendor Comparison | PRD F7 | **gap** | Post-MVP per PRD Phase 4 scope; entry point not needed in this mockup. |
| F8 AI Law Analysis (5 sub-features) | PRD F8 | **met** | Legal-details header names "EU AI Act" as a covered framework. AI Training finding cites EU AI Act Art. 50. Coverage card notes "Missing: AI training opt-out, ADM rights" for Facebook's policy. |

## Issue #19 requirements

| Req | Source | Status | Notes |
|---|---|---|---|
| Paste/link first, no gate | Issue #19 §Proposed design/Intake | **met** | Input box is the first interactive element on the intake page. No login, no required fields, no jurisdiction picker barrier. |
| Optional "Who is this for?" (via chips, invisible caution-weighting) | Issue #19 §Proposed design/Intake | **met** | Four option cards with italic sub-lines. Truly multi-select. Nothing pre-selected. "Something my child" invisibly maps to COPPA/children's privacy weighting server-side. |
| Optional "Roughly where do they live?" — conditional | Issue #19 §Proposed design/Intake | **met** | Only appears when jurisdiction can't be inferred from URL/text. Country defaults from browser location; blank if VPN detected. |
| Actionable verdict labels (not just grade) | Issue #19 §Problem #1 | **met** | "Worth a closer read" + specific verdict headline naming the concern ("A few things here may be worth understanding before agreement") + verdict subline naming the specific issue ("collecting data from apps and websites that aren't obviously connected"). |
| Critical info never hidden behind progressive disclosure | Issue #19 §Problem #2 | **met** | Verdict, scope box, and 4 top-things bullets are all above the collapsed legal details. The worst finding (IRP 0.80 Data Sale/Sharing) is surfaced as top-thing #3 in plain language. |
| Always-visible "what we did and didn't check" | Issue #19 §Problem #3 | **met** | Scope box between score cards and top-things. Uncollapsible. States exactly what was analyzed (policy text) and what wasn't (app permissions, real-world practices). |

## PRODUCT.md brand personality

| Req | Source | Status | Notes |
|---|---|---|---|
| Clear, Calm, Empowering (not scanner-alarm) | PRODUCT.md §Brand Personality | **met** | Amber "Worth a closer read" verdict (not red "STOP"). No exclamation marks, no scare tactics. Tentative language throughout ("may," "perhaps," "some things worth considering"). |
| Plain language first | PRODUCT.md §Design Principles #1 | **met** | Zero jargon in verdict, top-things, action list. Legal terms only inside collapsed detail. |
| Accessible to everyone | PRODUCT.md §Design Principles #3 | **met** | Reading level ~grade 8. No possessives in tool voice so the reader may be checking on behalf of someone else. Warm intake voice ("What's on your mind?") + observational results voice. |
| Trust through transparency | PRODUCT.md §Design Principles #4 | **met** | Scope box discloses limits. Legal citations available on demand. Line refs let readers verify findings against source. |
| Low friction, high signal | PRODUCT.md §Design Principles #5 | **met** | Intake is 3 elements (paste + optional cards + CTA). Results verdict is 1 line. Reader can decide from the verdict alone; drill down is optional. |
| No em-dashes anywhere in tool voice (AI giveaway) | User direction | **met** | Zero em-dashes in intake, results, verdict, top-things, actions, or hover help text. Em-dashes remain only inside verbatim Facebook policy quotes (Facebook's own words). |

## PRD UI/UX system

| Req | Source | Status | Notes |
|---|---|---|---|
| Design system palette | PRD F UI/UX/Color Palette | **partial** | Mockup uses teal `#0d6e8a` as primary (calmer per PRODUCT.md anti-references) instead of PRD-specified `#2563EB`. Flag: needs codification in the design system. |
| WCAG AA color contrast | PRD F UI/UX/Accessibility | **partial** | Body text on white background exceeds 4.5:1. Italic gray hover help text on light gray background is borderline — needs contrast verification in Streamlit implementation. |
| Keyboard navigation + visible focus | PRD F UI/UX/Accessibility | **gap** | Not yet audited in the mockup. Add during Streamlit implementation with `tabindex` and `:focus-visible` outlines. |
| 44×44px touch targets | PRD F UI/UX/Accessibility | **partial** | Option cards, buttons, tabs all exceed. Small links ("See in policy →", export buttons) approach the limit but stay above 44px vertical when the padding is counted. |
| Mobile-responsive | PRD F UI/UX/Responsive Breakpoints | **partial** | Layout is single-column, adapts naturally. Hover help hidden below 1100px viewport. Score cards may need to stack vertically on narrow viewports — Streamlit `st.columns` handles this. |

## Persona coverage

The Facebook privacy policy chosen for the mockup exercises all 5 PRD personas simultaneously:

| Persona | PRD ref | How mockup serves them |
|---|---|---|
| Patricia (privacy-conscious dev) | PRD Persona 1 | Full flow surfaces AI training, cross-app data sharing, tracking — her top concerns. |
| Sam (startup founder) | PRD Persona 2 | Score cards + JSON/CSV export support vendor-risk documentation. |
| Rachel (researcher) | PRD Persona 3 | CSV/JSON export supports bulk statistical analysis. Line references support methodology citation. |
| Alex (AI compliance officer) | PRD Persona 4 | AI Training finding cites EU AI Act Art. 50. IRP scores support regulatory documentation. Coverage card names missing ADM rights. |
| Morgan (Parent, low tech literacy) | PRD Persona 5 | "Something my child wants to use" option card. Plain-language top-things. Scope box addresses "not checked what permissions the app requests on a phone" directly. |

## Summary

| Total requirements audited | Met | Partial | Gap |
|---|---:|---:|---:|
| ~45 line items across BRD/PRD/Issue #19/PRODUCT.md | **~31** | **~10** | **~4** |

**Gaps** (all outside MVP scope for this mockup, tracked for follow-up):
- F6 Watchlist entry point (post-MVP)
- F7 Vendor Comparison entry point (post-MVP)
- Full keyboard nav + focus audit (Streamlit implementation)
- Dark mode variant (nice-to-have, out of scope for this mockup)

**Partials** to close during Streamlit implementation:
- Character counter + short-text warning on paste (F1.3)
- "Advanced" jurisdiction/doc-type/industry override on results page (F2.1-F2.3)
- Findings list filters + sorting UI (F4.2)
- Verify View split-pane modal (F4.3 — entry point exists, target view TBD)
- Full WCAG AA contrast audit
- Codify teal `#0d6e8a` as primary in the shared design system (resolves PRD/PRODUCT.md tension)
- Mobile-responsive score card stacking

**Committed decisions** shipped in this mockup:
- Two-voice design (intake warm we/you, results observational no you/we/us)
- No em-dashes in tool voice
- Hover-triggered contextual help (Streamlit-portable via CSS `:hover`)
- Verdict-first, always-visible scope, plain-language bullets, collapsed legal detail
- Live source URLs on crumb + action items
