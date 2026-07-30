format: design-plan
date: 2026-07-03
branch: TBD (new branch off main after current push lands)
owner: Jennifer McKinney (design lead) + Claude (implementation partner)
status: DRAFT — awaiting user review
anchors: PRODUCT.md §Brand Personality, TECH_SPEC §11 UI Specification, LIB-VOICE, LIB-CONTEXT, BRD §Customer Segments, PRD §User Personas
supersedes: current TECH_SPEC §11.3 Results view (8-stacked-section layout)

# Results View Revamp — "Report Card" Metaphor

## 1. Core insight

The current results view leans **threat-scanner**: dashboard tiles, IRP badges, severity tags, "legal details expander". PRODUCT.md brand intent is **trusted guide, "I've got you"**. The gap between those two is what feels clunky.

The revamp reframes the results view as a **report card**.

Report cards have a shape everyone recognizes:

- Top: who it's for + overall grade + a one-line narrative anchor from the teacher.
- Per subject: letter grade + written comment explaining the grade.
- Notes: attendance / behavior / caveats.
- Signature at the bottom: what to do next.

That shape carries the whole rubric (legitimacy) *and* the whole warmth (personalized narrative) at the same time. It resolves the "no visible grade" vs "conversational" tension — the grade IS the anchor, and the writing around it is what makes it warm.

## 2. Design principles (revised)

| # | Principle | Comes from |
|---|-----------|------------|
| D1 | Rubric-backed. Nothing said without the score/weight to back it up. | User directive 2026-07-03. |
| D2 | Grade, risk score, IRP visible — with **info icons** that unpack the rubric in plain speak + small diagrams/graphics on request. | User directive 2026-07-03. |
| D3 | Findings render as short observations with a "let's look at this" tone, ordered by grade impact — it's a story, not a table. | User directive 2026-07-03. |
| D4 | Summary at the top anchors the message and sets the tone for what follows. | User directive 2026-07-03. |
| D5 | Chip context materially changes what is said — findings connect to the reader's context choices. Personal. | User directive 2026-07-03. |
| D6 | Voice per LIB-VOICE V2 in results (third-person observational; no `you`/`we`/`our`/`your` in tool voice). Exception carve-out for `for_child` under review (see §7 open questions). | LIB-VOICE. |
| D7 | Streamlit-native. No framework swap. Everything achievable with stock Streamlit widgets (`st.container`, `st.form`, `st.popover`, `st.metric`, `st.expander`). | User: "Streamlit is non-negotiable." |
| D8 | Hard scope limits (hardware permissions, real-world-practice divergence) remain always-visible per LIB-PRINCIPLES P4. Rendered as a "teacher's note" at the bottom, not a scary boxed disclosure at the top. | LIB-PRINCIPLES P4. |
| D9 | Empty domains hide entirely. No "Nothing notable surfaced under X." | Deadpan violates D3. |

## 3. New results view — top to bottom

Each section maps to a report-card element.

### 3.1 Report card header (replaces current verdict card + grade metrics row)

Shape:

```
┌────────────────────────────────────────────────────────┐
│  Report on: SnapKidz privacy policy                    │
│  Reviewed for: parent evaluating for a child           │
│                                                        │
│  Overall grade    C+     [ⓘ how we got this]          │
│  Concerns to weigh                                     │
│                                                        │
│  For a child, a few things here may be worth           │
│  understanding first. Personal data appears to be      │
│  shared with advertising partners, facial recognition  │
│  is enabled for photo features, and terms can change   │
│  without notice. Details below.                        │
└────────────────────────────────────────────────────────┘
```

Elements:
- **Line 1**: doc title (from ingested metadata or filename or URL host).
- **Line 2**: `Reviewed for: <chip label(s)>` — this is the current "Reviewed for:" summary, moved into the header.
- **Overall grade** (large): letter grade per LIB-RULES §Risk-Grade Thresholds.
- **Info icon `ⓘ how we got this`**: opens a `st.popover` with a plain-speak breakdown (see §4 below).
- **Grade sub-label**: current `verdict_label` per chip (e.g., "Concerns to weigh", "Worth a legal pass"). This IS the label, not a separate line.
- **Narrative anchor paragraph** (2-4 sentences): sets tone. This is the "summary at top" from D4. Sourced from `AnalysisPayload.verdict_headline` (current) + 1-2 sentences generated from the top-scoring findings for the reader's chip context. Currently the backend emits only `verdict_headline` — needs a new field `verdict_narrative` (see §5.b implementation).

### 3.2 Per-domain "subject grade" cards (replaces current 4 empty-tolerant domain boxes)

Only render domains that have findings (D9). For each domain that has findings:

```
┌────────────────────────────────────────────────────────┐
│  Data         B-   [ⓘ how graded]                     │
│  what's collected                                      │
│                                                        │
│  ▸ Facial recognition is enabled for photo features.  │
│    For a child, that's more identifying data than       │
│    most families expect to hand over.                  │
│    [see the exact wording ▸]                          │
│                                                        │
│  ▸ Location data is collected and tracked.            │
│    Precise geolocation on a child's device raises       │
│    the stakes for who else might see where they are.   │
│    [see the exact wording ▸]                          │
└────────────────────────────────────────────────────────┘
```

Elements per subject:
- **Domain name** (Data / Data use / Terms of use / Privacy rights) — larger.
- **Domain grade** (letter) — derived from the aggregate IRP of findings in that domain. Same rubric as overall grade, applied to the domain's subset. New backend field (see §5.b).
- **Info icon `ⓘ how graded`**: same popover pattern as §3.1 but scoped to this domain.
- **Domain sub-label** (current: "what's collected", "how it's used", etc.) — smaller, still present.
- **Findings as observations** — 1-2 per domain, ordered by IRP within the domain. Each is:
  - Short observation (1-2 sentences), tone: "let's look at this," rewritten from `finding.explanation` PLUS the chip-context lens (D5).
  - Collapsed exact-wording link `[see the exact wording ▸]` that reveals the excerpt inline (small, quoted, escaped). Not an expander at page-level; per-finding.

Findings are NOT prefixed with "High" / "Medium" severity chips. The grade of the domain and the position in the ordered list carries the weight. If a reader wants the severity, IRP, or category label, the "how graded" popover shows them (§4).

### 3.3 What to do next (replaces current suggestions section)

```
┌────────────────────────────────────────────────────────┐
│  What might help next                                  │
│                                                        │
│  • Look for parental supervision controls in the app  │
│    before letting a child sign up.                     │
│  • Check whether facial recognition can be turned off  │
│    in settings.                                        │
│  • Watch for a policy-change notification — this one   │
│    can update without warning.                         │
└────────────────────────────────────────────────────────┘
```

This is the current `action_items` field, but chip-tuned (per D5 and CONTENT-1 issue). Currently action items are chip-invariant — needs the fix from §5.a issue.

### 3.4 Teacher's note (replaces current scope box)

Rendered near the bottom, still always-visible per P4, but no longer boxed and framed as formal disclosure:

```
A note on what this review checked

Only the words in the policy. Not what permissions the app
actually requests on a phone (camera, microphone, contacts,
location — those live in device Settings). Not whether the
company's real-world practices match what the policy says.
```

Same information as the current scope box. Different framing — softer prefix, no bold "**What was checked**" headers, prose flow instead of bullet list. Still verbatim on the two hard scope limits per P4.

### 3.5 Report signature

```
Reviewed 2026-07-03 · policy last modified 2026-07-03 · analysis id #a3c3227
[export as PDF] [export as JSON] [export as CSV]
```

Fixes GAP-013 (#45 — analysis timestamp missing). Export bar moves to bottom, smaller.

## 4. Info-icon popovers — how they work

Every `ⓘ` icon opens a Streamlit `st.popover`. Contents follow a consistent structure:

### 4.1 Overall grade popover

```
How this grade was computed

Overall grade: C+

Every finding gets an IRP score — Impact, Likelihood, and any
Safeguards the policy names. Higher-impact findings that are
likely to affect this reader push the grade down.

For this context — parent evaluating for a child — the
grade weights the "Children's Privacy" and "Minors"
categories more heavily than other findings.

The grade tiers:
  A  clean, low practical concern
  B  worth a read, some to weigh
  C  meaningful concerns to weigh
  D  serious concerns

┌── Composition of THIS grade ──────────┐
│  Data           B-  ██████░░░░       │
│  Data use       C   ████░░░░░░       │
│  Terms of use   C+  █████░░░░░       │
│  Privacy rights D+  ██░░░░░░░░       │
└───────────────────────────────────────┘

Impact + likelihood - safeguards: [see the formula ▸]
```

Elements:
- Plain-speak grade explanation (3-4 sentences), personalized to chip.
- Grade tier legend (compact table).
- Composition bar chart per domain — rendered as ASCII bars OR `st.bar_chart` with domain grades. Compact.
- Nested link to the formula (opens a second, deeper popover with the IRP formula in symbolic form for users who want it).

### 4.2 Per-domain popover

Same shape, scoped to the domain. Shows:
- Which categories in that domain fired.
- Each category's IRP (impact, likelihood, safeguard) with a small "what's this?" for IRP itself.
- Chip weight applied to each category (per LIB-CONTEXT §Weight tier scale).

### 4.3 Per-finding info affordance

Findings themselves don't get an icon at line level (D3 — story tone, no severity chips). If the reader clicks `[see the exact wording ▸]` the excerpt is revealed inline. If they want the category and IRP for that specific finding, they get it through the domain popover (§4.2), which lists all findings.

### 4.4 Rubric-formula popover (deepest layer)

For readers who want the math:

```
IRP = 0.5 × (impact/5) + 0.4 × (likelihood/5) − 0.3 × (safeguards/5)

Impact         how bad the outcome could be if this fired          1-5
Likelihood     how likely it is to affect this reader               1-5
Safeguards     protections the policy explicitly names              0-5

Higher IRP means the finding weighs more toward the domain
and overall grade. Chip context also multiplies weight for
categories that matter more to this reader's situation
(for a child, "Children's Privacy" counts more).
```

Verbatim from LIB-RULES / LIB-CONTEXT. Plain-speak first, formula second, no jargon.

## 5. Implementation moves

Grouped by scope.

### 5.a — Chip context becomes causal (D5, CONTENT-1, CONTENT-2)

Backend changes in `src/backend/app/services/analyzer.py` + `context.py`:

- `_derive_action_items(payload, context)` — currently chip-invariant. Change to gate items by chip: only emit "For work/vendor use, escalate liability..." when `for_work` in context. Add chip-tuned items for `for_child` (parental supervision controls, facial recognition opt-out, policy-change notification), `for_care` (share-together framing), etc.
- Verify why `for_work` chip on the E2E fixture doesn't surface Liability / Cross-Border in `top_by_domain`. Audit rule pattern coverage for those categories. If coverage exists but IRP isn't beating Children's Privacy, the fix may be raising `_CATEGORY_WEIGHTS[for_work][Liability]` from its current tier.

Ticket refs: file as `[REVAMP] chip context must be causal, not decorative` (§6).

### 5.b — Backend fields for the new UI

New fields on `AnalysisPayload`:

- `verdict_narrative: str` — the 2-4 sentence tone-setting paragraph for §3.1. Generated from top-scoring findings for the reader's chip. LLM-generated when LLM is up, template-generated from top 3 findings when LLM is down.
- `domain_grades: Dict[str, str]` — per-domain letter grade (Data / Data use / Terms of use / Privacy rights).
- `finding_observations: Dict[str, str]` — per-finding rewritten observation copy (the "let's look at this" version of the plain-language `explanation`). Chip-lensed.
- `overall_grade_composition: Dict[str, {grade, weight_pct}]` — for the info popover bar chart.

All fields optional / backward-compatible. Existing consumers still work.

### 5.c — Streamlit v2 layout rewrite

`src/webapp/app_streamlit_v2.py::render_results`:

- Wrap intake in `st.form(...)` — closes UI-1 rerun-state race.
- Rewrite `render_results` structure to §3.1 → §3.2 → §3.3 → §3.4 → §3.5 flow.
- Use `st.popover(":information_source:")` (Streamlit ≥ 1.28) for every info icon.
- Kill: grade summary metrics row, IRP badges, severity tags in primary flow, "Legal details expander" as a page-level element, "Nothing notable surfaced under X" empty-domain lines.
- Move: exports bar to bottom.
- Add: analysis timestamp per GAP-013 #45.
- CSS: apply teal palette consistently across results panels; fix issue #31 `--color-text-hint` contrast to ≥ 4.5:1 AA.

### 5.d — Voice fixes (CONTENT-3, LOW)

`_SIMPLIFY_REPLACEMENTS` contains 18 second-person strings that violate LIB-VOICE V2. Design decision needed before implementing (see §7 open questions).

### 5.e — Test scaffolding

- Add pytest tests for `verdict_narrative` generation given each of the 5 chips + baseline fixture.
- Add pytest tests for chip-tuned `action_items` — parametrized over 5 chips, assert output differs.
- Add pytest for domain-grade computation.
- Update `simplification-check.sh` if `_SIMPLIFY_REPLACEMENTS` changes.
- Add Playwright test for `st.form(...)` chip-persistence — closes UI-1.
- Add screenshot regression tests for the 5 chip flows.

## 6. Follow-up GitHub issues to file

| ID | Title | Labels | Severity |
|----|-------|--------|----------|
| A | [REVAMP-E1] Results view: shift to report card metaphor | epic, ui, revamp | HIGH |
| B | [BUG] Streamlit rerun-state race loses chip selection on quick "Take a look" | bug, ui, streamlit | HIGH (from Phase 5.d UI-1) |
| C | [DEFECT] action_items are chip-invariant — for_work suggestion appears for just_curious | defect, backend, context | MEDIUM (from Phase 5.d CONTENT-1) |
| D | [AUDIT] rule engine may under-surface Liability + Cross-Border on for_work chip fixture | audit, rules, context | MEDIUM (from Phase 5.d CONTENT-2) |
| E | [DESIGN] _SIMPLIFY_REPLACEMENTS violates LIB-VOICE V2 (18 second-person strings) — resolve tension | design-decision, voice | LOW (from Phase 5.d CONTENT-3) |
| F | [GOV] LIB-PRINCIPLES P4 amendment — drop practice-divergence caveat | governance, docs | MEDIUM (D-Q9) |

Each issue links back to this plan doc. Issue A (revamp epic) opens with a link to §3 shape + §5.c implementation moves and closes when the shipped results view matches §3. Issue F tracks the P4 amendment separately for audit trail — governance changes get their own record.

## 7. Decisions LOCKED (2026-07-03 user review)

All 9 decisions confirmed by user 2026-07-03. This section preserves the reasoning for each decision.

### D-Q1 voice = C (split)

Observational voice everywhere at the "load-bearing" level (verdict headlines, verdict labels, narrative anchor, scope note). Second-person allowed inside per-finding observation copy ONLY when `for_child` chip is active.

Rationale: keeps LIB-VOICE V2 pure at the load-bearing level. Warmth only where it lands hardest (parent-to-child observation). Codified rule: "second-person allowed inside per-finding observation copy when for_child chip is active."

### D-Q2 rubric depth = A (grade + domain grades visible; IRP/score in popovers)

Overall grade, verdict label, per-domain grade letter are all on the surface. IRP score, risk score, severity tag, category name are revealed by tapping `(i)`.

Rationale: matches report-card metaphor. Legitimacy without dashboard chrome.

### D-Q3 popover graphics = B (`st.bar_chart`)

Info popovers use Streamlit's built-in `st.bar_chart` for the "grades by section" visualization. No Plotly.

Rationale: Streamlit-native, no new dep, theme-tinted automatically, HR1 open-source constraint holds without additional dep audit.

### D-Q4 verdict narrative source = C (LLM with template fallback)

The 2-4 sentence narrative anchor is LLM-generated with strict prompt + JSON schema; falls back to template on LLM failure/timeout.

Rationale: warm when possible, never breaks, matches HR5 fallback pattern.

### D-Q5 vocabulary = A ("Policy review")

Top-of-page label is "Policy review." Not "Report card" (school-y for adults) or "Policy check" (too casual).

Rationale: report-card SHAPE without report-card language. Adult, professional, neutral.

### D-Q6 scope caveat = reframe as "What else worth checking" (three-pointer helpful note)

Replaces the two-caveat scope box with a three-pointer actionable note directing readers to (a) the app's Terms of Use, (b) App Store Privacy Nutrition Label / Play Store Data Safety, (c) install-time permission requests in device Settings.

Rationale: ends the report on generous "here's what else to look at" energy instead of defensive disclaimer. See sketches doc for the layout.

### D-Q7 evidence layout = two-column with multi-span highlighting

Per-domain sections use a two-column layout: analysis observations on the left, source policy text on the right with all relevant line spans highlighted at once. Highlights are domain-tinted. Line numbers referenced in the observation copy anchor to the highlighted spans (click a line reference to scroll the right column).

Rationale: one excerpt-per-finding was thin. Findings usually stitch from multiple places; showing the pattern of what's called out demonstrates the analysis and prevents the "generic paraphrase" feel. Mobile: columns collapse into per-finding collapsible source panels.

Backend fields needed:
- `evidence.line_spans: List[LineSpan]` — replaces single line_start/line_end
- `grounded_in_count: int` — for the "Grounded in N places" line

### D-Q8 observation copy discipline = specificity rule

Every finding observation MUST cite ≥ 2 line spans OR MUST explicitly say "Grounded in 1 place: line N." If only one span grounds an observation, the writer must acknowledge that scope explicitly rather than paraphrasing.

Rationale: paraphrase without stitching is what makes the tool feel generic. Naming the exact line numbers in the observation copy makes the analysis feel earned.

Enforcement: LLM prompt template must include a "cite line numbers explicitly" instruction, and a validator check (extends `validation.py`) that flags observations without at least one `(line N)` or `(lines N-M)` inline reference.

### D-Q10 legal citation depth = C (all three surfaces)

Legal citations surface at three depths, layered:

1. **Per-finding "Under:" line** — always visible under each finding observation. Lists the specific statute/article/regulation citations from `finding.evidence.legal_basis`. Small, tight, present.
2. **Per-domain "(i) measured against" popover** — tap `(i)` next to the domain grade. Enumerates the full corpus the domain grade was computed against (per jurisdiction × article count). Shows the tool's "syllabus" for that grade.
3. **Right-column `[policy] [law]` toggle** — the source-doc column on the right toggles between the analyzed policy text (default view, with highlighted spans from the policy) and the retrieved legal-KB passages that supported the analysis. Same highlight colors coordinate policy-span → law-passage.

Rationale: the tool's core differentiation is the head-to-head between the analyzed document and cited law. Hiding that in an expander undersells the value. Three surfaces let readers dig at their preferred depth: skim ("Under:" line) → understand ("measured against" popover) → verify ("law" toggle side-by-side with policy).

Backend fields required (add to plan §5.b):
- `finding.evidence.legal_basis: List[str]` — already exists, needs UI surfacing
- `finding.legal_context_passages: List[LegalPassage]` — the retrieved legal-KB passages that grounded this specific finding (currently computed on backend for LLM prompt, discarded before returning to UI)
- `domain.measured_against: Dict[Jurisdiction, List[str]]` — enumeration per jurisdiction of which statute sections were activated in scoring this domain
- Optional `finding.legal_context_passages[i].placeholder_warning: bool` — flag when a passage comes from placeholder corpus (Q11)

### D-Q11 legal corpus rollout = B (block revamp until real corpus ingested for expanded jurisdiction set)

Scope expanded 2026-07-04 per user directive.

The revamp does NOT ship until real, sourced statute text is ingested for the full jurisdiction set below. This becomes an epic-scale ingestion workstream in parallel with the UI implementation.

**EU**
- **GDPR** — Regulation (EU) 2016/679 from EUR-Lex (CC-BY-4.0)
- **EU AI Act** — Regulation (EU) 2024/1689 from EUR-Lex (CC-BY-4.0)

**US federal**
- **COPPA** — 15 U.S.C. §§6501-6506 + 16 CFR Part 312 (public domain)
- **HIPAA / HITECH** — 45 CFR Parts 160, 162, 164 (public domain)
- **GLBA** — 15 U.S.C. §§6801-6809, Safeguards Rule 16 CFR Part 314 (public domain)
- **FERPA** — 20 U.S.C. §1232g + 34 CFR Part 99 (public domain)
- **FCRA** — 15 U.S.C. §§1681-1681x (public domain)
- **FTC Act §5** (unfair/deceptive practices, foundational for privacy enforcement) — 15 U.S.C. §45 (public domain)
- **Federal AI guidance** — Executive Order 14110 (2023), OMB M-24-10, NIST AI RMF 1.0 (public domain / federal)

**US state privacy laws** (comprehensive privacy statutes as of 2026-07-04)
- **US-CA** — CCPA / CPRA — Cal. Civ. Code §1798.100-199.100 from leginfo.legislature.ca.gov (public domain)
- **US-CO** — Colorado Privacy Act — Colo. Rev. Stat. §6-1-1301 et seq. (public domain)
- **US-CT** — CTDPA — Conn. Gen. Stat. §§42-515 to 42-525 (public domain)
- **US-NY** — SHIELD Act — N.Y. Gen. Bus. Law §899-aa/bb (public domain)
- **US-VA** — VCDPA — Va. Code §59.1-575 et seq. (public domain)
- **US-UT** — UCPA — Utah Code §13-61-101 et seq. (public domain)
- **US-TX** — TDPSA — Tex. Bus. & Com. Code Chapter 541 (public domain)
- **US-OR** — OCPA — Or. Rev. Stat. §646A.570 et seq. (public domain)
- **US-MT** — Montana Consumer Data Privacy Act (public domain)
- **US-DE** — Delaware Personal Data Privacy Act (public domain)
- **US-IA** — Iowa Consumer Data Protection Act (public domain)
- **US-IN** — Indiana Consumer Data Protection Act (public domain)
- **US-TN** — Tennessee Information Protection Act (public domain)
- **US-NH** — New Hampshire Data Privacy Act (public domain)
- **US-NJ** — New Jersey Data Privacy Act (public domain)
- (Corpus agent to enumerate any additional state laws effective on or before 2026-07-04.)

**Asia-Pacific**
- **Australia — general privacy** — Privacy Act 1988 (as amended 2022, 2024) + Australian Privacy Principles (APPs) from oaic.gov.au or legislation.gov.au (Crown copyright; check re-use terms per corpus agent)
- **Australia — child protections + human agency** (added 2026-07-04 per user directive):
  - **Online Safety Act 2021 (Cth)** — including Basic Online Safety Expectations (BOSE), Restricted Access System Declaration, cyberbullying scheme for children under 18
  - **Online Safety Amendment (Social Media Minimum Age) Act 2024** — under-16 social media ban, effective ~Dec 2025 through 2026 rollout. eSafety Commissioner enforcement guidance.
  - **OAIC Children's Privacy Code** — statutory code under the Privacy Act (per Privacy Act Review response); track 2025-2026 development status
  - **Attorney-General's Privacy Act Review response** — recommendations on ADM (automated decision making), child privacy, human review rights (Rec 19 series)
  - **Voluntary AI Safety Standard** (Sep 2024) — human agency + oversight guidance; 10 guardrails including human control over AI-affected decisions
  - **National Framework for Assurance of AI in Government** (2024) + updates
  - **Age Assurance Trial outcomes** (2024-2025) — informs child-protection technical requirements
- **Singapore** — PDPA (Personal Data Protection Act 2012, amended 2020, 2024) from pdpc.gov.sg / sso.agc.gov.sg (check re-use terms per corpus agent)

**International + soft-law frameworks + international courts** (added 2026-07-04 per user directive on public UN/EU links + ICC grouping)

*Soft-law and interpretive frameworks*
- **OECD AI Principles** (2019, updated 2024) — oecd.org (public re-use terms per OECD)
- **UNESCO Recommendation on the Ethics of AI** (2021) — unesco.org (typically CC-BY-SA-3.0-IGO or equivalent)
- **UN Guiding Principles on Business and Human Rights** (2011) — ohchr.org (UN public re-use)
- **UN Global Digital Compact** (2024) — un.org (UN public re-use)
- **Council of Europe Framework Convention on Artificial Intelligence** (opened for signature May 2024) — coe.int (Council of Europe re-use terms)
- **G7 Hiroshima AI Process** outputs (2023 + 2024 rolling) — g7.gc.ca / relevant G7-presidency URLs
- **EDPB Guidelines** (European Data Protection Board interpretive guidance) — edpb.europa.eu (public, CC-BY or Commission re-use)

*International courts and tribunals* (constitutive instruments + judgments with bearing on privacy / data / business + human rights)
- **International Criminal Court (ICC)** — Rome Statute (1998) + Rules of Procedure and Evidence + relevant Registry / Trust Fund for Victims policies on victim/witness data protection — icc-cpi.int (public)
- **International Court of Justice (ICJ)** — Statute + relevant judgments on state responsibility for privacy/data-related human rights — icj-cij.org (public)
- **European Court of Human Rights (ECtHR)** — European Convention on Human Rights Article 8 (right to respect for private and family life) + Article 10 (freedom of expression, relevant to platform policy) + material jurisprudence (Bărbulescu v Romania, Big Brother Watch v UK, Von Hannover series, etc.) — echr.coe.int / hudoc.echr.coe.int (public)
- **CJEU judgments** with material bearing on privacy policy interpretation (Schrems I/II, Weltimmo, Bara, Digital Rights Ireland, etc.) — curia.europa.eu (public)
- **Inter-American Court of Human Rights** — American Convention on Human Rights Article 11 + relevant privacy jurisprudence — corteidh.or.cr (public re-use terms per OAS)
- **African Court on Human and Peoples' Rights** — African Charter on Human and Peoples' Rights + Malabo Convention (data protection) — african-court.org (public)

These frameworks carry interpretive weight for Terms of Service and Privacy Policy analysis even where they are not directly enforceable against the drafter. The Business + Human Rights lens (UN Guiding Principles, ICC-adjacent state responsibility, ECtHR Article 8) is load-bearing for policy analysis in the tool's context. Scope agent (corpus-INTL) verifies re-use terms per source before ingestion; not every international court decision belongs in the corpus — the agent enumerates the specific instruments and top-N landmark judgments per court that materially inform privacy-policy compliance analysis.

Rationale: shipping the head-to-head revamp against placeholder statute text undermines the credibility of the whole redesign. If a reader clicks `[law]` and sees `[PLACEHOLDER — not real statute text]`, the tool's core value proposition breaks. The tool's current shipped v2 UI (rule engine + LLM + IRP) continues to work in production until the revamp is ready.

**Ingestion architecture directive (added 2026-07-04 per user)**: prefer AGGREGATED master-data sources over building 12+ direct-source pipelines. EUR-Lex is already the EU master (one source covers GDPR + AI Act + DSA + Data Act + DMA). govinfo.gov is the US federal master. For US states, evaluate IAPP US State Privacy Legislation Tracker + NCSL as consolidation layers. For international, evaluate HuggingFace Datasets legal corpora (Pile of Law is HR2-excluded because CC-BY-NC-SA blocks commercial use), WorldLII / BAILII / AustLII / CanLII (verify license each — several are CC-BY-NC which may block HR2), Free Law Project / CourtListener bulk data (open license, US case law focus). Corpus-AGG research agent evaluates each and reports which aggregators eliminate direct-source scraping/API/download work while remaining HR2-compliant.

**Imminent-statute treatment principle (added 2026-07-04 per user)**: statutes effective within approximately 12 months of the current date are corpus-ingested BEFORE their effective date, not deferred. The tool must be able to evaluate policies against imminent law during the run-up so readers can prepare. Concretely for 2026-07-04 as of now:
- **Colorado AI Act (SB 26-189, replaces the repealed SB 24-205)** — effective 2027-01-01 (~6 months away). STAYS IN PHASE 2 ingestion. Chunks tagged `status: not_yet_in_force, effective_date: 2027-01-01` so the UI can surface a "coming into force" badge if a reader is analyzing a Colorado-touching policy in the lead-up.
- **Singapore NRIC-for-authentication prohibition** — effective 2027-01-01. Same treatment.
- **Australia ADM transparency grace-period expiry** — 2026-12-10. Same treatment; imminent.
- **Any other state or federal statute** effective within 12 months of the current corpus refresh cycle → same treatment.

Override the earlier "Phase 4 deferrals" language for anything now falling inside this 12-month window. Corpus refresh cadence must include a scheduled sweep for imminent-effective statutes so the corpus is updated before they take effect.

**Rollout order** — corpus agent produces a phasing plan. Suggested:
1. Phase 1 — EU (GDPR, EU AI Act) + US federal foundations (COPPA, HIPAA, GLBA, FERPA, FCRA, FTC Act §5)
2. Phase 2 — US-CA + top 3-5 other state laws by traffic (US-CO, US-CT, US-VA, US-NY SHIELD, US-TX)
3. Phase 3 — remaining US state laws + Australia + Singapore
4. Phase 4 — Federal AI guidance (EO 14110, OMB M-24-10, NIST AI RMF)

Ship the revamp UI when Phase 1 + Phase 2 real corpus complete. Phases 3 + 4 add on rolling basis; UI shows inline placeholder warning per-jurisdiction until each phase lands.

Filed as separate epic issue (see §6). Blocks the results-view revamp epic close.

### D-Q9 P4 amendment = drop `limit_practice_divergence` from LIB-PRINCIPLES

Amend LIB-PRINCIPLES P4 to remove the "real-world practice divergence" caveat. Keep only the hardware/runtime-permission caveat.

Rationale: analyzing the policy IS analyzing the contract. Behavior monitoring is a separate discipline (compliance monitoring, breach research, investigative journalism), not something a policy-analysis tool should apologize for not doing. Conflates scope-of-tool with due-diligence-in-general.

Required governance changes:
- LIB-PRINCIPLES P4: drop `limit_practice_divergence` clause, simplify reasoning
- BRD-CONSTRAINT-02: rewrite to name only the hardware limit
- `src/webapp/app_streamlit_v2.py` scope box copy: replace with D-Q6 three-pointer note
- Test assertions on scope-box HTML: update to match new copy

Filed as separate governance issue for audit trail (see §6).

---

## 7-ARCHIVE. Historical: earlier open questions before user review

### Q1: `for_child` voice exception?

`_SIMPLIFY_REPLACEMENTS` uses second-person ("watches what you do", "your face", "You might not be able to ask them to delete your information") because the reader (parent) needs to hear it in the child's voice. Strict LIB-VOICE V2 says results copy MUST NOT use `you`/`your`.

Choices:
- **(a)** Rewrite all 18 replacements observational ("A child using this may be watched to serve better ads"). Preserves V2. Cooler tone.
- **(b)** Codify a `for_child`-only exception in LIB-VOICE. Warmer tone for parent audience.
- **(c)** Split: keep observational for verdict/narrative anchors, allow second-person only inside per-finding observations when `for_child` chip is active.

Recommend (c) — most defensible and preserves the warmth exactly where the parent needs it.

### Q2: How much of the rubric is "always visible" vs "on demand"?

- **(a)** Grade + domain grades visible; IRP + score + severity only inside info popovers.
- **(b)** Grade + score visible; domain grades + IRP inside popovers.
- **(c)** Grade only visible; everything else on demand.

Recommend (a) — matches report-card metaphor most directly.

### Q3: Info-icon rendering — text-only popover, or embedded graphics?

Streamlit `st.popover` can render markdown (fine for ASCII bars) OR small `st.bar_chart` / `st.plotly_chart` (real graphics). Real graphics feel more polished but add plotly/matplotlib dependency.

- **(a)** ASCII bars in the popover — no new dep, ships fast, minimalist.
- **(b)** `st.bar_chart` — Streamlit built-in, no new dep, real bars.
- **(c)** Plotly — richer, adds a dependency, best-looking.

Recommend (b) — Streamlit-native, no new deps, real bars.

### Q4: Verdict narrative — LLM-generated or template-generated?

- **(a)** Always template-generated from top findings (deterministic, cheap, less warm).
- **(b)** Always LLM-generated with a strict prompt (warm, but adds latency + LLM-fallback risk).
- **(c)** LLM-generated with template fallback per HR5 (LLM-fallback-to-rules).

Recommend (c) — matches existing HR5 pattern.

### Q5: Report card metaphor — does the language of "grade" and "subject" work, or does that pattern-match too school-y for adult readers?

Concern: some readers may find the metaphor infantilizing. Alternatives: "assessment card", "review at a glance", "policy report", etc.

Recommend: keep the visual pattern of a report card, but call it "Policy review" in the UI copy. The mental model helps; the vocabulary can stay adult.

## 8. What's NOT in this plan

- Not touching backend rule engine broadly — only the `_derive_action_items` gate + Liability/Cross-Border audit.
- Not changing hard scope limits, jurisdiction contract, IRP formula, chip taxonomy, or the 4-domain grouping.
- Not touching intake view except to wrap in `st.form(...)`.
- Not changing exports (PDF/JSON/CSV) — just relocating the bar.
- Not building filters/sort (GAP-008 #40) — decided against the "power-user surface" per D3 story shape. Filter/sort belongs in the JSON/CSV export layer for that audience.

## 9. Rollout

1. Merge current branch `claude/issue-19-arch-docs-followup` (in progress, waiting on you).
2. Cut new branch `revamp/results-report-card`.
3. Implement §5.a (chip context causal) — deploy behind existing `STREAMLIT_UI=v2` (no new flag needed since it's still v2, just improved).
4. Implement §5.b (backend fields) + §5.c (Streamlit layout).
5. Implement §5.d after Q1 answered.
6. Test scaffolding (§5.e) written alongside implementation, per P8 role separation.
7. Preview build for user review before merge.
8. Merge after user approval + P9 peer review.

## 10. Sizing estimate

Rough T-shirt sizing (implementation only, excluding design decisions):
- §5.a: M (2-3 days)
- §5.b: M (2-3 days)
- §5.c: L (4-6 days — most of the work)
- §5.d: S (1 day post-decision)
- §5.e: M (2-3 days spread across the above)

Total: ~2-3 weeks focused effort. Design decisions in §7 need to land before any implementation starts.
