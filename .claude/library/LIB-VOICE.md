# LIB-VOICE: Copy Voice Conventions

> **Status (2026-07-03):** shipped in PR #34 (issue #19 redesign). These conventions took multiple iterations to nail during the redesign — capturing them here so future sessions don't re-litigate. Anchor doc: `docs/wireframes/issue-19-design-decisions.md` §§ 1, 2, 3. Brand personality anchor: `PRODUCT.md` §Brand Personality — "Clear, Calm, Empowering… trusted guide, not threat scanner."

## Two-voice architecture

**Intake uses first-person warm voice. Results uses third-person observational voice.** The two views are stylistically distinct on purpose.

### Intake voice — first person, warm

Reader is at the keyboard. Uses "we" (the tool) and "you" (the reader) to build trust and lower the barrier to pasting a policy. Examples from `app_streamlit_v2.py`:

- "What's on your mind?"
- "We're here to help."
- "Nice to know before you tap 'I agree.'"
- "We will help you see what matters."

Voice register: friendly, conversational, non-clinical. Anchors to PRODUCT.md's "Clear, Calm, Empowering… trusted guide" personality.

### Results voice — third person, observational

Reader may not be the person the policy applies to. A parent may forward the review to their teen. A caretaker may show findings to a family member. Possessive "your data is used" only lands if the reader IS the subject. Observational "photos, posts, and activity are used" lands for any reader.

**No `you`, `we`, `us`, `our`, `your` in results copy.** Ever. This is a hard rule.

Examples from `context.py::VERDICT_HEADLINE`:

- "This policy is clearer than most." (not "your policy")
- "A few things here may be worth understanding before agreement." (not "before you agree")
- "For a child, this policy is clearer than most." (not "your child")
- "For work use, several clauses here could put the business on the hook." (not "your business")

### Transition point

The voice shift happens at intake -> results boundary. In normal use it's barely perceptible — the reader has moved from "telling the tool what they want" to "reading what the tool found." The shift matches the emotional shift.

### Rejected alternatives

- **Uniformly warm voice throughout** — rejected. Results possessives create subtle mismatch when the reader is checking for someone else.
- **Uniformly observational voice throughout** — rejected. Intake reads clinical and cold, undermines the brand personality.

## No em-dashes in tool voice

Zero em-dashes (`—`, U+2014) in the tool's own copy. Em-dashes remain only inside verbatim quotes of the analyzed policy (e.g., a Facebook clause the tool is quoting back).

### Why

User flagged em-dashes as an "AI giveaway." Extensive em-dash use in generated text has become a shibboleth signaling machine origin. Removing them makes the copy read as human-written and reinforces the trusted-guide personality.

### Substitutions

Em-dashes replaced with:
- **Periods** — splits a sentence into two. Cleanest replacement for parenthetical thought interruption.
- **Commas** — softer connector for clauses that were only lightly separated.
- **Colons** — introduces a list or explanation.
- **Restructuring** — sometimes the em-dash was doing work no substitute could replicate; rewrite the sentence.

Substitutions are **not mechanical**. Each replacement is reviewed for reading flow. If a period creates a run of choppy short sentences, restructure instead.

### Where em-dashes are still allowed

- **Inside verbatim quotes of the analyzed policy.** The tool doesn't rewrite what the policy says.
- **Inside code, docstrings, and internal comments in `.claude/library/*.md` and `docs/*.md`.** These are engineering documents, not tool voice.
- **Inside this file.** Meta-documentation about the rule, not the rule itself.

### Where em-dashes are forbidden

- Every string that reaches the reader from the tool: verdict headlines, verdict labels, intake copy, action items, scope box text, help tooltips, error messages surfaced to the reader.

### Enforcement

No hook or linter enforces this currently. It's a copy-review responsibility during PR review. A `/em-dash-scan` skill is proposed in the session handoff.

## Tentative framings

Results copy uses **"may," "perhaps," "possibly," "might," "some," "a possible…"** throughout the tool voice. Never "you should," "we recommend," or "the tool has determined."

### Why

Therapist-curious approach invites the reader to form their own judgment. Directive language ("you should not agree") short-circuits agency — the reader is told what to conclude before understanding what was found. Observational language ("a few things that stood out") gives the reader the analysis and trusts them with the decision.

Analogy from the design decisions doc: a good doctor says "here's what I noticed on the imaging" and then discusses. A bad doctor says "you have X, so you need Y." Legal risk analysis for non-experts should behave more like the good doctor.

### Examples

- "A few things here may be worth understanding before agreement." (not "You must review these clauses")
- "For a child, a few things here may be worth understanding first." (not "This is unsafe for children")
- "Several clauses here could put the business on the hook." (not "This will expose the business to liability")

The tool suggests. The reader decides.

## Verdict labels are actionable, not grades

Verdict labels tell the reader **what to do next**, not what letter grade the policy earned.

Grade-style labels short-circuit reader agency (they see "F" and stop reading) and match PRODUCT.md's explicit anti-reference "security scanner alarm aesthetic."

### Comparison

| Grade-style (rejected) | Actionable (shipped) |
|------------------------|-----------------------|
| USE CAUTION | Worth a closer read |
| STOP | Not vendor-safe as written |
| GO | Workable |
| CRITICAL RISK | Serious concerns |
| SAFE | Reasonable |

Labels rotate by context so the action lands for the reader's actual situation. See `context.py::VERDICT_LABEL` for the full table (also reproduced in LIB-CONTEXT).

Letter grades are still surfaced in the underlying `AnalysisPayload.grade` field for machine consumption, but they're not the primary UI verdict.

## Scope-honesty gap

**Always-visible "what was / wasn't checked" box on results.** Never optional. Never collapsible below the fold.

### Why

The tool has hard scope limits it cannot cross. If the reader thinks the tool checked for things it didn't check, they'll trust a green verdict beyond what it earned. The scope box exists to be honest about what the finding set covers and what it doesn't.

### Hard scope limits

These are surfaced verbatim, never optional, never as a chip or a domain group with findings:

- **Hardware permissions** — camera, microphone, contacts, location. The tool does not analyze the manifest of what an app requests at install; it only reads the policy text. If the policy says "we may request camera access," the tool can flag that clause, but it cannot tell the reader what the app ACTUALLY requests. The scope box says so.
- **Real-world practice divergence** — the tool analyzes what the policy says, not what the company does. A well-written policy that the company violates in practice will read as low risk to the tool. The scope box says so.

### Copy pattern

The scope box uses observational third-person voice consistent with the rest of results. Not "we didn't check X," but "X was not checked" or "this review does not cover X."

## PRODUCT.md brand anchor

Every voice decision above derives from PRODUCT.md's brand personality section:

> **Clear, Calm, Empowering.** The tool handles serious subject matter (legal risk, data privacy) but should never feel alarming, bureaucratic, or exclusive. Think trusted guide, not threat scanner. Think "I've got you," not "WARNING: CRITICAL RISK."

Anti-references from the same doc:

- Generic SaaS blue-gradient dashboard (Salesforce-style, enterprise compliance tools)
- Legal document clutter — walls of tiny text, dense tables without hierarchy
- Security scanner alarm aesthetic — red-alert, threat-feed visual language, aggressive risk banners
- Anything that implies the user needs to be an expert to use it

When a copy decision is contested during review, walk it back to these anchors. "Does this line make a nervous non-expert feel calmer or more alarmed?" is the tie-breaker question.

## Voice review checklist

Use this when reviewing any change to tool-facing copy (intake, results, error messages, scope box):

1. **Which voice register?** Intake (first-person warm) or results (third-person observational)?
2. **Em-dashes?** Any `—` outside a verbatim policy quote? Fix.
3. **Directive language?** "You should," "we recommend," "the tool determined"? Rewrite to tentative.
4. **Possessives in results?** "Your," "our," "we"? Rewrite to observational.
5. **Verdict label actionable?** Reads as an action, not a grade?
6. **Scope-honesty preserved?** Hardware / real-world practice mentioned somewhere visible?
7. **Anchors to PRODUCT.md?** Does this help the reader feel Clear, Calm, Empowered?
