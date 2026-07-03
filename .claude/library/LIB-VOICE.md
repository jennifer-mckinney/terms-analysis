# LIB-VOICE — copy voice conventions (shipped PR #34, issue #19)
loads: on-trigger
scope: project
xref: [[LIB-CONTEXT]] [[PRODUCT.md#brand-personality]] [[docs/wireframes/issue-19-design-decisions.md]] [[LIB-PRINCIPLES#P6]]

## two-voice-architecture

### V1: intake = first-person warm
rule: intake copy uses "we" (tool) + "you" (reader); friendly, conversational, non-clinical
examples: "What's on your mind?" / "We're here to help." / "Nice to know before you tap 'I agree.'"
because: reader is at keyboard; lowers barrier to pasting a policy; anchors to PRODUCT.md "trusted guide" personality

### V2: results = third-person observational
rule: results copy MUST NOT use `you`, `we`, `us`, `our`, `your`
because: reader may not be the subject of the policy (parent forwards to teen; caretaker shows family); possessives only land if reader IS subject; observational lands for any reader
examples:
  ok: "This policy is clearer than most." / "photos, posts, and activity are used"
  not_ok: "your policy" / "before you agree" / "your child" / "your business"
xref: [[LIB-CONTEXT#verdict-headlines]] [[LIB-CONTEXT#verdict-labels]]

### V3: voice transition
rule: voice shifts at intake→results boundary; no in-place register mixing

### V4-rejected: uniformly-warm
rule: MUST NOT use warm voice in results
because: possessives mismatch when reader is checking for someone else

### V5-rejected: uniformly-observational
rule: MUST NOT use observational voice in intake
because: reads clinical and cold; undermines brand personality

## no-em-dashes-in-tool-voice

### V6: no em-dash in tool voice
rule: zero em-dashes (`—`, U+2014) in any string that reaches the reader from the tool
scope_forbidden: verdict headlines, verdict labels, intake copy, action items, scope box text, help tooltips, error messages surfaced to reader
scope_allowed: verbatim quotes of the analyzed policy; code + docstrings + `.claude/library/*.md` + `docs/*.md`; this file
because: user flagged as "AI giveaway" / shibboleth for machine origin; removing reinforces trusted-guide personality
enforcement: PR-review responsibility; `/em-dash-scan` skill proposed

### V7: em-dash substitutions
rule: replace em-dashes with periods (split into two sentences), commas (soft connector), colons (list/explanation), or restructure the sentence
must: review each substitution for reading flow; if periods produce choppy runs, restructure instead
not_permitted: mechanical global replace

## tentative-framings

### V8: tentative language required in results
rule: use "may / perhaps / possibly / might / some / a possible…"
forbidden: "you should" / "we recommend" / "the tool determined" / "you must" / "this will"
because: therapist-curious framing invites reader's own judgment; directive language short-circuits agency; good-doctor analogy — "here's what I noticed" not "you have X so you need Y"

## verdict-labels-actionable

### V9: verdict labels are actions, not grades
rule: verdict labels tell reader what to do next, not a letter grade
because: grade labels short-circuit reader agency (see "F", stop reading); match PRODUCT.md anti-reference "security scanner alarm aesthetic"
rotation: labels rotate by context chip (see `context.py::VERDICT_LABEL` and LIB-CONTEXT)
grade_field_still_exists: `AnalysisPayload.grade` present for machine consumption; not primary UI verdict

| grade-style (rejected) | actionable (shipped) |
|------------------------|-----------------------|
| USE CAUTION | Worth a closer read |
| STOP | Not vendor-safe as written |
| GO | Workable |
| CRITICAL RISK | Serious concerns |
| SAFE | Reasonable |

## scope-honesty-gap

### V10: always-visible scope box
rule: results view MUST render a "what was / wasn't checked" box; never optional; never collapsible below fold
because: if reader thinks tool checked things it didn't, they trust a green verdict beyond what it earned

### V11: hard scope limits (verbatim, never chip, never domain group)
rule: two limits are surfaced verbatim in the scope box, always
limit_1_hardware: camera / microphone / contacts / location — tool reads policy text, not app manifest; can flag "we may request camera" clause but cannot report what app ACTUALLY requests
limit_2_practice_divergence: tool analyzes what policy says, not what company does; well-written policy the company violates will read as low risk
xref: [[LIB-PRINCIPLES#P4]] [[terms_analysis_scope_limits.md]]

### V12: scope box voice
rule: scope box uses observational third-person (V2), not first-person
examples:
  ok: "X was not checked" / "this review does not cover X"
  not_ok: "we didn't check X"

## brand-anchor

### V13: PRODUCT.md is the tie-breaker
rule: when a copy decision is contested, walk back to PRODUCT.md brand personality — "Clear, Calm, Empowering. Trusted guide, not threat scanner."
anti_references: generic SaaS blue-gradient dashboard; legal document clutter; security scanner alarm aesthetic; anything implying reader needs to be an expert
tie_breaker_question: "Does this line make a nervous non-expert feel calmer or more alarmed?"

## voice-review-checklist

### V14: mandatory review checklist for tool-facing copy
rule: apply this checklist to every change touching intake, results, error messages, scope box
1. voice register: intake (first-person warm) or results (third-person observational)?
2. em-dashes: any `—` outside verbatim policy quote? fix
3. directive language: "you should" / "we recommend" / "the tool determined"? rewrite tentative (V8)
4. possessives in results: "your" / "our" / "we"? rewrite observational (V2)
5. verdict label: reads as action, not grade? (V9)
6. scope-honesty: hardware + real-world-practice mentioned visibly? (V10, V11)
7. PRODUCT.md anchor: does this help reader feel Clear, Calm, Empowered? (V13)
