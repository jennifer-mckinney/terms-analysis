# Issue #19 — Design Decisions & Rationale

Companion to `issue-19-plain-language-design.html` (interactive mockup) and `issue-19-brd-prd-compliance.md` (requirements traceability).

This document logs every non-obvious design decision with its reasoning, the tradeoffs considered, and the anchor requirement it satisfies. Intended for:
- Design sign-off on issue #19
- Handoff to the Streamlit implementation phase
- Reference when future iterations need to know "why is it like this"

---

## 1. Voice architecture: two voices, one product

### Decision
Intake uses first-person warm voice ("What's on your mind?", "We're here to help"). Results uses third-person observational voice (no "you," "we," "us," "our"). The two views are stylistically distinct on purpose.

### Reasoning
- **Intake** is a conversation with the reader who is present at the keyboard. Warm "we" and "you" build trust and lower the barrier to pasting a policy. Anchors to PRODUCT.md brand personality ("Clear, Calm, Empowering… trusted guide").
- **Results** may be read by someone OTHER than the reader who pasted the policy. A parent may forward the review to their teen. A caretaker may show findings to a family member. Possessive "your data is used" only lands if the reader IS the subject. Observational "photos, posts, and activity are used" lands for any reader.

### Tradeoffs considered
- Uniformly warm voice throughout: rejected because results possessives create subtle mismatch when the reader is checking for someone else.
- Uniformly observational voice throughout: rejected because intake reads as clinical and cold, undermining PRODUCT.md's "Calm, Empowering" personality.
- Two voices with clear transition: accepted. The transition happens at the intake → results boundary and is barely perceptible in normal use.

### Anchors
- Issue #19 §Problem #1 (verdict labels aren't actionable — need voice suited to non-experts)
- PRODUCT.md §Brand Personality
- User feedback: "not use possessive words as the user could be representing more than themselves"

---

## 2. Tentative, observational language on results

### Decision
Results copy uses "may," "perhaps," "possibly," "might," "some," "a possible…" throughout the tool voice. Never "you should," "we recommend," or "the tool has determined."

### Reasoning
Therapist-curious approach invites the reader to form their own judgment. Directive language ("you should not agree") short-circuits agency — the reader is told what to conclude before understanding what was found. Observational language ("a few things that stood out") gives the reader the analysis and trusts them with the decision.

Analogy: a good doctor says "here's what I noticed on the imaging" and then discusses. A bad doctor says "you have X, so you need Y." Legal risk analysis for non-experts should behave more like the good doctor.

### Tradeoffs considered
- Direct verdict labels (STOP / CAUTION / GO): rejected because they short-circuit reader agency and match PRODUCT.md's explicit anti-reference "security scanner alarm aesthetic."
- Purely factual language ("the policy states"): kept as a base register, but softened with tentative qualifiers where the tool is drawing an inference vs. quoting the policy directly.

### Anchors
- Issue #19 §Problem #1
- PRODUCT.md §Brand Personality
- User feedback: "no you or we or us… 'a possible…' 'perhaps…' etc"

---

## 3. No em-dashes in tool voice

### Decision
Zero em-dashes (`—`, U+2014) in the tool's own copy. Em-dashes remain only inside verbatim quotes of the analyzed policy (Facebook's own words in the mockup).

### Reasoning
User flagged em-dashes as an "AI giveaway." Extensive em-dash use in generated text has become a shibboleth signaling machine origin. Removing them makes the copy read as human-written and reinforces the trusted-guide personality.

Structurally, em-dashes were replaced with periods (splits a sentence into two), commas (softer connector), or colons (introduces list or explanation). None of these substitutions were mechanical — each was reviewed for reading flow.

### Tradeoffs considered
- Keep em-dashes for prosody: rejected. The AI-detection signal outweighs the rhythmic benefit.
- Replace with en-dashes: rejected. Same problem, slightly different symbol.
- Use unicode punctuation more expressively (semicolons, parenthetical asides): partially adopted where it improved clarity.

### Anchors
- User feedback: "no long dashes… AI giveaway"

---

## 4. BRD-segment-aligned context taxonomy + domain-grouped results

### Decision
5 intake chips mapped to BRD customer segments. Results are grouped into 4 fixed domain sections regardless of context, but the context weights determine WHICH findings surface into each domain group.

**Chip taxonomy:**
| Chip | BRD Segment | Rubric alignment |
|---|---|---|
| `want_understand` | Personal use (baseline) | IRP-driven, no reweighting |
| `for_child` | Segment 1 (Parents, 35%) | Privacy & Security + AI Law Signal (child-specific) |
| `for_care` | Personal use (caregiver variant) | Privacy & Security + Legal Signal (dark patterns) |
| `for_work` | Segment 2 (Small Businesses, 40%) | Legal Signal + Governance Readiness |
| `just_curious` | Segment 3 (Advocates, 25%) — exploratory | IRP-driven, no reweighting |

**Domain groups on results screen** (fixed order, always shown):
1. **Data** — what's collected
2. **Data use** — how it's used
3. **Terms of use** — the agreement itself
4. **Privacy rights** — what can still be exercised

Domain sections cap at 2 findings each, 8 findings total. Empty domains render as "Nothing notable surfaced under X."

### Reasoning
Previous single flat "top things" list interleaved data / data use / terms / privacy findings, making it hard to see each concern distinctly. Domain grouping is a mental-model win: readers who care about "what's collected" and readers who care about "what recourse exists" can each find their answer in a labeled section.

Persona-based chip axis was rejected as over-engineering — BRD segments are 3 clear customer groups, and 5 chips (one per segment plus baseline variants) cover them without a persona/domain 2D matrix.

### Tradeoffs considered
- Persona chips + domain chips (2-question intake): rejected — form bloat, most readers won't pick both.
- Domain chips only, no persona axis: rejected — loses the "who this is for" caution weighting (child-specific concerns need child-specific surfacing bias).
- More chips (compliance review, already-agreed, etc.): rejected — over-engineering. Revisit with real usage data.

### Financial Data axis dropped
`Financial Data` category was in `for_care` weights. Removed because the same concerns are already reachable via `Sale/Share`, `Sensitive Data`, `Dark Patterns`, and `Deceptive Practices` in the `for_care` weight dict. A dedicated axis was redundant.

### Anchors
- BRD §Market Analysis (3 customer segments)
- User feedback: "data use, terms of use, privacy, hardware and data are very separate"
- User feedback: "drop financial exploitation explicit weighting/score"

---

## 5. Multi-context handling: sum-cap-3.0 merger + tier-first sort

### Decision
Multi-selection of chips is first-class:
- **Weight merger:** `merged[cat] = min(sum(weights_by_chip[cat]), 3.0)`. Rewards agreement (two chips both boosting a category = amplification into Signature tier). Cap prevents pathological stacking.
- **Sort key:** `(weight, irp_score, severity_rank)` descending. Weight tier dominates; IRP breaks ties within tier; severity as final tie-breaker.
- **Weight tier scale:** 1.0 baseline · 2.0 boosted · 2.5 priority · 3.0 signature.
- **Verdict copy:** primary chip via priority (`for_child > for_care > for_work > want_understand > just_curious`) drives headline + label. Secondary chips referenced in the "Tuned for:" chip on results screen ("Tuned for: {primary bold}, {secondary}").

### Reasoning
Previous multiplicative sort (`irp_score * weight`) let high-IRP baseline findings beat context-boosted lower-IRP findings, undermining the "context leads" design principle. Tier-first sort makes context weight the dominant sort key.

The sum-cap merger amplifies when multiple selected chips agree on a category (e.g., both `for_child` and `for_work` boost `Sale/Share` → capped at 3.0 = Signature tier), while `max()` alone would leave it at whichever chip's weight was higher.

### Hardware scope limit (hard project constraint)
The tool analyzes the words in a policy document only. Two things it fundamentally cannot check are always surfaced in the "What wasn't checked" scope box on results:
1. What permissions the app actually requests on a phone (camera, microphone, contacts, location). Those live in device Settings.
2. Whether real-world practices match what this policy says.

Never add a "hardware asks" chip to intake — selecting it would trigger no analysis. Never propose a domain group for hardware findings on the results screen — there aren't any.

### Anchors
- User feedback: "context choice leads the weight/score priority"
- User feedback: "multi context as well"

---

## 6. Verdict-first, always-visible scope, plain-language bullets

### Decision
Results order (top to bottom): crumb, context chip, verdict card, score cards, always-visible scope box, top-4 plain-language bullets, collapsed legal details, action list, export bar, disclaimer.

Critical information is never behind progressive disclosure. Legal citations and IRP scores ARE behind a collapsed `<details>` accordion.

### Reasoning
Issue #19 identified three UX problems that this ordering resolves:

1. **Verdict labels aren't actionable** → verdict headline names the specific concern in plain language, at the top.
2. **Progressive disclosure hides critical info** → top-4 bullets are above the fold, always visible. The worst finding by IRP score becomes bullet #1 or #2, not buried in the legal accordion.
3. **Scope-honesty gap** → the "what was checked / what wasn't checked" box is uncollapsible, sits between score cards and top-things.

### Tradeoffs considered
- Grade letter as hero: rejected (issue #19 explicitly problematizes letter grades as jargon).
- All 8 findings visible ungrouped: rejected. Cognitive overload for non-experts.
- Progressive disclosure of the top-4 as well: rejected. Undermines the whole point (see #2 above).

### Anchors
- Issue #19 §Problem #1, #2, #3
- PRD F4.1, F4.4

---

## 7. Hover-triggered contextual help (not scroll-triggered)

### Decision
The right-side italic gray help text fades in when the cursor enters a section (via `mouseenter`) and fades out when the cursor leaves (via `mouseleave`). Position dynamically aligns to the hovered section's vertical center.

### Reasoning
Original design used `IntersectionObserver` for scroll-driven fade. Streamlit's re-render model breaks IntersectionObserver on every widget interaction (checkboxes toggle, buttons click). Hover triggers survive re-renders because they're pure CSS `:hover` states (or thin JS event listeners re-attached on each render).

Hover is also more intentional — the reader is choosing to explore that section, not passively scrolling past it. The help appears when the reader signals interest, disappears when they move on.

### Tradeoffs considered
- Scroll-driven fade (original): rejected due to Streamlit re-render fragility.
- Static persistent help under each section: considered but rejected — clutters the visual hierarchy.
- Custom Streamlit component wrapping the IntersectionObserver logic: rejected — over-engineered for the value delivered.
- Iframe embed of the HTML: rejected — loses widget integration.
- Interaction-driven help (right column changes based on last-touched widget): considered as a Streamlit approximation of hover but hover is preferable.

### Streamlit portability
Pure CSS `:hover` on `st.container(border=True)` elements, combined with a fixed-positioned help panel that's updated via `st.markdown(unsafe_allow_html=True)`. No JS needed in Streamlit.

### Anchors
- User feedback: "on mouse rollover in new section… card appears"
- User direction: "streamlit is the solution priority"

---

## 8. Color palette: teal instead of PRD-specified primary blue

### Decision
Primary interactive color is teal (`#0d6e8a`) with teal-soft (`#e6f4f8`) for selected/highlighted states. PRD F UI/UX spec calls for primary blue (`#2563EB`).

### Reasoning
PRODUCT.md anti-references explicitly exclude "generic SaaS blue-gradient dashboard (Salesforce-style, enterprise compliance tools)." The PRD-specified `#2563EB` reads as exactly that. Teal is calmer, more human, less corporate, and better aligned with the "Clear, Calm, Empowering… trusted guide, not threat scanner" personality.

### Tradeoffs considered
- Keep PRD blue: rejected — direct conflict with PRODUCT.md anti-reference.
- Introduce a full-color rework: rejected — teal is a targeted resolution, not a rebrand.
- Use a warmer color like sage or terracotta: rejected — teal preserves trustworthiness signal that legal analysis needs.

### Open decision
Codify teal `#0d6e8a` as the shared primary in the design system, replacing PRD's `#2563EB`. Requires a design-system update PR after issue #19 is signed off.

### Anchors
- PRODUCT.md §Anti-references
- PRD F UI/UX §Color Palette (superseded)

---

## 9. Location Q: conditional, plain names, VPN-aware defaults

### Decision
The "Where are you located?" question only appears when jurisdiction cannot be inferred from the pasted URL or policy text. When shown, uses plain country + region names (not jurisdiction codes). Country defaults to the browser's location. Field is left blank if a VPN is detected.

### Reasoning
- Conditional visibility keeps the intake minimal for the common case. Most privacy policies contain either explicit jurisdiction mentions ("California residents," "under GDPR") or TLD signals (`.co.uk`, `.eu`) that make the location Q redundant.
- Plain names (United States, California) beat jurisdiction codes (US-CA, GDPR) for the target reader — PRD Persona 5 (low-medium tech literacy) shouldn't have to decode acronyms.
- Browser-location defaults reduce friction. VPN detection prevents mis-defaulting for users who are traveling or protecting their real location.

### Subline copy
"Different regions offer different protections." Reframes location as beneficial context (protections FOR the reader) rather than restrictive rules (constraints ON the reader).

### Tradeoffs considered
- Always show location Q: rejected. Adds friction for common cases where inference succeeds.
- Auto-set location based on browser without asking: rejected. Silent behavior undermines transparency (contradicts PRODUCT.md §Design Principles #4).
- Default from IP geolocation server-side: rejected — VPN false positives, server-side inference conflicts with local processing.

### Anchors
- User feedback: "only pop up… great call out"
- User feedback on subline: "not really rules… drop the no need to be exact"
- User feedback on defaults: "defaults should be country based on browser location. If VPN used, then blank"

---

## 10. Live source URLs (crumb + action items)

### Decision
The reviewed URL (crumb) and any external references (Facebook opt-out, CNIL, Family Center, COPPA report) are actual clickable links opening in new tabs with `target="_blank" rel="noopener"`.

### Reasoning
- Reviewer trust: the reader can verify the source policy exists at the URL claimed
- Actionability: "California residents can opt out at facebook.com/privacy/policy" is meaningless if the link doesn't work
- Auditability: PRD F3.3 evidence binding requires the reader can verify findings against source

### Anchors
- User direction: "ensure source urls are live now"
- PRD F3.3 (evidence binding)

---

## 11. Multi-format input tabs (link, text, upload)

### Decision
Three tabs at the top of the input box: Paste link (text input), Paste text (textarea), Upload file (dashed drop zone accepting `.pdf,.docx,.rtf,.html,.txt`, up to 10MB). Each tab shows a different input panel and its own footer hint. Only one panel visible at a time.

### Reasoning
PRD F1.1-F1.3 mandates all three. The mockup makes each functional (not just visual placeholders). The switch is instant (`display: none` toggle) with no state loss on the currently-focused tab.

### Streamlit portability
`st.tabs()` with three tabs, each containing `st.text_input`, `st.text_area`, or `st.file_uploader` respectively. Native Streamlit widgets — no custom component needed.

### Anchors
- PRD F1.1, F1.2, F1.3

---

## 12. Verdict variants (Go / Review / Stop)

### Decision
The mockup shows one variant ("Review" — amber, "Worth a closer read"). The design supports three action-readiness states from the backend `action_readiness` enum:

| State | Label | Icon | Color | Sample headline |
|---|---|---|---|---|
| `Go` | Looks reasonable | ✓ | Green `#166534` | This policy is clearer than most. |
| `Review` | Worth a closer read | 👀 | Amber `#b45309` | A few things here may be worth understanding first. |
| `Stop` | Some serious concerns | ⛔ | Red `#991b1b` (calm, not scanner-alarm) | Multiple parts of this policy work against the reader's privacy. |

### Reasoning
Three states span the actionable range. Two would flatten nuance (Review does a lot of work). Four or more adds granularity that non-experts can't map to decisions.

Even the "Stop" red uses the same typography and layout — no flashing icons, no all-caps warnings. The color signals urgency without inducing panic. This anchors to PRODUCT.md's "trusted guide, not threat scanner."

### Anchors
- Backend `action_readiness` enum in `schemas.py`
- PRODUCT.md §Anti-references

---

## 13. IRP scores surfaced in expanded legal details only

### Decision
Per-finding IRP breakdown (Impact/Likelihood/Safeguards, e.g., "3/5, 4/5, 1/5") shows only inside the collapsed `<details>` accordion, alongside the confidence percentage. Not visible in the top-4 plain-language bullets.

### Reasoning
IRP components are meaningful to compliance officers (PRD Persona 4 — Alex) but noise for non-experts (PRD Personas 1, 3, 5). Progressive disclosure lets both audiences self-select.

The top-4 bullets already order findings by IRP internally — the highest-IRP finding surfaces as bullet #1. Expert users can drill into legal details to see the exact scores.

### Anchors
- Backend IRP implementation (shipped)
- PRD F3.4 (confidence scoring)

---

## 14. Removed developer-only annotations

### Decision
Any annotation whose purpose was to explain the design to reviewers (e.g., "Only shown when jurisdiction can't be inferred from the pasted text or URL") is either moved into the hover help text or deleted entirely. User-facing UI shows only user-facing content.

### Reasoning
Mockup should be as close as possible to production fidelity. Dev annotations blur the line and can leak into implementation if not scrubbed.

The hover help text is the appropriate channel for reviewer context — visible on hover, invisible in normal reader flow.

### Anchors
- User feedback: "circled was for your development not help text"

---

## Open decisions before Streamlit implementation

1. **Codify teal as primary** in the shared design system, deprecating PRD-specified `#2563EB`. Requires design-system update.
2. **Verify View split-pane design** — mockup has entry points ("See in policy →" links) but the target view is TBD. Options: modal overlay, in-page expansion, right-drawer.
3. **Advanced override on results page** — how does a power user override the inferred jurisdiction / doc type / industry? Likely a small "Adjust" link on the results page opening a settings panel.
4. **JS SPA fallback feature parity** — RESOLVED 2026-07-03: SPA retired in Phase 4 of the issue #19 remediation. Streamlit v2 is the sole UI.
5. **Dark mode** — PRD lists as "should have." Post-MVP for this pass but the palette needs a dark variant if pursued.
6. **Verify View modal contents** — line-numbered source doc with the finding excerpt highlighted, or full document with all findings highlighted at once?

---

## Implementation phases

**Phase 1: Streamlit rewrite** (target: 1 focused change, based on this settled design)
1. New `app_streamlit_v2.py` — plain-language flow (intake → results, single-page)
2. Backend endpoint `POST /infer` — takes URL/text, returns inferred `jurisdictions + doc_type + industry`
3. `services/inference.py` — signal ranking implementation (TLD, statute mention, regulatory body, geographic phrase, currency, language)
4. `services/context.py` — maps context-chip selections to backend caution-weighting and top-things surfacing bias
5. Feature flag `STREAMLIT_UI=v2` in `run.sh` (default `v2` after acceptance)
6. Keep old `app_streamlit.py` as `app_streamlit_legacy.py` for one release cycle (rollback path)

**Phase 2: JS SPA fallback update — SUPERSEDED**
Superseded 2026-07-03 by Phase 4 (SPA retirement). No parity work performed; SPA files (`index.html`, `app.js`, `style.css`) were deleted and `run.sh` reduced to backend + Streamlit only.

**Phase 3: Backend enhancements to support the design**
1. `AnalysisPayload.top_things_plain_language: List[str]` — 4 LLM-generated plain-language bullets, context-lens aware
2. `AnalysisPayload.action_items: List[dict]` — jurisdiction + context aware next steps with live URLs
3. LLM prompt update in `prompts.py` for both above, with fallback templates for LLM-unavailable state
4. Rule engine boost/demote per context lens

**Phase 4: Design system reconciliation**
1. Codify teal as primary
2. Publish palette + typography + spacing tokens as a shared module
3. Update PRD to reflect shipped decisions

---

## Reference

- Interactive mockup: `docs/wireframes/issue-19-plain-language-design.html`
- Requirements traceability: `docs/wireframes/issue-19-brd-prd-compliance.md`
- Source specs: `docs/BRD_Terms_Policies_Reviewer.md`, `docs/PRD_Terms_Policies_Reviewer.md`
- Brand: `PRODUCT.md`
- Issue: [#19](https://github.com/jennifer-mckinney/terms-analysis/issues/19)
