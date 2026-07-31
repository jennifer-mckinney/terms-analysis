format: visual-sketch
date: 2026-07-03
companion-to: docs/plans/2026-07-03-results-view-revamp-report-card.md
purpose: render each of the 5 open-questions as side-by-side ASCII wireframes so you can pick before I write the implementation plan
convention: (o) = filled, ( ) = outline, [~~~] = tappable button, [see ▸] = inline reveal, (i) = info-popover trigger

# Results-View Revamp — Visual Sketches for 5 Design Choices

Each choice below shows 2-3 options as ASCII wireframes at roughly the same fidelity. Streamlit-native throughout.

---

## Q1 — Voice for `for_child` findings

Sample input: `"Facial recognition is enabled for photo tagging."`
Reader: a parent evaluating an app for their 10-year-old.

### A. Strict observational (LIB-VOICE V2 unchanged)

```
┌───────────────────────────────────────────────────────────┐
│ Data                                              B-  (i) │
│ what's collected                                          │
│                                                           │
│ ▸ Facial recognition appears to be enabled for photo     │
│   tagging. A child using this service may be identified   │
│   by systems that scan images.                            │
│   [see the exact wording ▸]                              │
│                                                           │
│ ▸ Location data appears to be collected and tracked.     │
│   Precise geolocation on a child's device raises the      │
│   stakes for who else may see it.                         │
│   [see the exact wording ▸]                              │
└───────────────────────────────────────────────────────────┘
```

Feel: Neutral, journalistic. "About the policy," not "to you."

Pros: LIB-VOICE V2 stays clean and enforceable. Same voice for all 5 chips.
Cons: Reads coolly. Parent may feel it's talking around them.

---

### B. Full second-person under `for_child` (codified V2 exception)

```
┌───────────────────────────────────────────────────────────┐
│ Data                                              B-  (i) │
│ what's collected                                          │
│                                                           │
│ ▸ This service can recognize your child's face for       │
│   photo tagging. Your child could be identified by        │
│   systems that scan images.                               │
│   [see the exact wording ▸]                              │
│                                                           │
│ ▸ This service tracks your child's location. Precise     │
│   geolocation raises the stakes for who could see where  │
│   your child is.                                          │
│   [see the exact wording ▸]                              │
└───────────────────────────────────────────────────────────┘
```

Feel: Warm, personal, directly addresses the parent.

Pros: Highest emotional connection for the parent audience. Matches how a trusted friend would explain it.
Cons: Requires codifying an exception in LIB-VOICE (P6). All other chips have to explain why they don't get warm voice.

---

### C. Split: observational anchors, second-person per-finding under for_child (recommended)

```
┌───────────────────────────────────────────────────────────┐
│ Overall grade                            C+          (i)  │
│ Concerns to weigh                                         │
│                                                           │
│ For a child, a few things here may be worth               │
│ understanding first. Personal data appears to be shared,  │
│ facial recognition is enabled, and terms can change       │
│ without notice.                                           │
├───────────────────────────────────────────────────────────┤
│ Data                                              B-  (i) │
│ what's collected                                          │
│                                                           │
│ ▸ This service watches for your child's face in photos   │
│   to tag them. That's more identifying data than most     │
│   families expect to hand over.                           │
│   [see the exact wording ▸]                              │
└───────────────────────────────────────────────────────────┘
```

Feel: Newspaper headline over a personal letter. Anchors stay authoritative; per-finding copy gets warm.

Pros: Keeps LIB-VOICE V2 pure at the "load-bearing" level (verdict headlines, labels, narrative anchor, scope note). Warmth lives only inside the observations where it lands hardest. Easiest to codify: "second-person allowed inside per-finding observation copy when for_child chip is active."
Cons: Requires the rule to be documented + tested; risk of drift over time.

---

## Q2 — Rubric visibility depth

What appears on the surface. Everything else lives in `(i)` popovers.

### A. Grade + domain grades visible; IRP + score hidden (recommended)

```
┌───────────────────────────────────────────────────────────┐
│  Policy review                                             │
│                                                            │
│  SnapKidz privacy policy                                   │
│  Reviewed for: parent evaluating for a child               │
│                                                            │
│  Overall grade   C+                                  (i)  │
│  Concerns to weigh                                         │
│                                                            │
│  For a child, a few things here may be worth               │
│  understanding first. ...                                  │
│                                                            │
│  Data          B-   (i)                                    │
│  Data use      C    (i)                                    │
│  Terms of use  C+   (i)                                    │
│  Privacy rights D+  (i)                                    │
└───────────────────────────────────────────────────────────┘
```

Feel: Clean report card. Grades tell the story; taps let readers dig.

Pros: Rubric legitimacy preserved. Visual noise low. Every number reachable in 1 tap.
Cons: Power users need to expand every popover to see IRP / score.

---

### B. Grade only visible; domain grades + everything else on demand

```
┌───────────────────────────────────────────────────────────┐
│  Policy review                                             │
│                                                            │
│  SnapKidz privacy policy                                   │
│  Reviewed for: parent evaluating for a child               │
│                                                            │
│  Overall grade   C+                                  (i)  │
│  Concerns to weigh                                         │
│                                                            │
│  For a child, a few things here may be worth               │
│  understanding first. ...                                  │
│                                                            │
│  Data              (i)                                     │
│  Data use          (i)                                     │
│  Terms of use      (i)                                     │
│  Privacy rights    (i)                                     │
└───────────────────────────────────────────────────────────┘
```

Feel: Softest, most conversational. Domains named but ungraded on the surface.

Pros: Least dashboard-y. Grade sits alone as the anchor.
Cons: Reader can't skim which domain is worst without tapping every popover. Loses the "at-a-glance" story shape you asked for.

---

### C. Everything visible: grade + score + IRP surfaced

```
┌───────────────────────────────────────────────────────────┐
│  Policy review                                             │
│                                                            │
│  SnapKidz privacy policy                                   │
│  Reviewed for: parent evaluating for a child               │
│                                                            │
│  Overall grade   C+   score 6.8/10                    (i)  │
│  Concerns to weigh                                         │
│                                                            │
│  For a child, a few things here may be worth               │
│  understanding first. ...                                  │
│                                                            │
│  Data          B-   IRP 0.63   score 4.5    (i)           │
│  Data use      C    IRP 0.71   score 5.2    (i)           │
│  Terms of use  C+   IRP 0.68   score 6.8    (i)           │
│  Privacy rights D+  IRP 0.79   score 8.1    (i)           │
└───────────────────────────────────────────────────────────┘
```

Feel: Compliance dashboard. Everything on the surface.

Pros: No hidden state; power users happy.
Cons: This is the "clunky" you called out. IRP and score numbers on the surface are the threat-scanner vibe. Report-card metaphor breaks.

---

## Q3 — Info-icon `(i)` popover graphics

What the popover contents look like when a reader taps `(i)` next to the overall grade.

### A. ASCII bars in the popover markdown

```
┌── How this grade was computed ──────────────────┐
│                                                  │
│ Overall grade: C+                                │
│                                                  │
│ Grades by section:                               │
│                                                  │
│   Data           B-   ██████░░░░                 │
│   Data use       C    █████░░░░░                 │
│   Terms of use   C+   ████░░░░░░                 │
│   Privacy rights D+   ██░░░░░░░░                 │
│                                                  │
│ Higher-impact findings likely to affect this     │
│ reader push the grade down. For a child,         │
│ "Children's Privacy" counts more than other      │
│ findings.                                        │
│                                                  │
│ [see the formula ▸]                              │
└──────────────────────────────────────────────────┘
```

Pros: Zero new dependencies. Ships fast. Works in any Streamlit version. Same rendering everywhere.
Cons: ASCII bars are quaint. Not as "polished."

---

### B. `st.bar_chart` inside popover (recommended)

```
┌── How this grade was computed ──────────────────┐
│                                                  │
│ Overall grade: C+                                │
│                                                  │
│ Grades by section:                               │
│                                                  │
│   [Streamlit renders real horizontal bar chart:  │
│    Data           |======                        │
│    Data use       |=====                         │
│    Terms of use   |====                          │
│    Privacy rights |==                            │
│    theme-tinted, snaps to app palette]           │
│                                                  │
│ Higher-impact findings likely to affect this     │
│ reader push the grade down. For a child,         │
│ "Children's Privacy" counts more than other      │
│ findings.                                        │
│                                                  │
│ [see the formula ▸]                              │
└──────────────────────────────────────────────────┘
```

Pros: Streamlit-native, no new dep, real bars, adopts the app theme automatically. Feels "of a piece" with the rest of the UI.
Cons: Bar chart alone; no interactive tooltip.

---

### C. Plotly inside popover (richest, adds dependency)

```
┌── How this grade was computed ──────────────────┐
│                                                  │
│ Overall grade: C+                                │
│                                                  │
│  [Plotly interactive horizontal bar chart:       │
│   hover for exact score, color-graded by tier,   │
│   click to isolate a domain]                     │
│                                                  │
│ + hover reveals: "Data: B-, score 4.5,           │
│   IRP 0.63, primary category Children's Privacy" │
│                                                  │
│ Higher-impact findings likely to affect this     │
│ reader push the grade down.                      │
└──────────────────────────────────────────────────┘
```

Pros: Interactivity, hover tooltips, richest visuals, best-looking.
Cons: Adds Plotly dependency. Larger bundle. Needs dep-audit (HR1/HR2/HR3 checks).

---

## Q4 — Verdict narrative source

The 2-4 sentence tone-setting paragraph under the overall grade.

### A. Template only (deterministic)

```
┌───────────────────────────────────────────────────────────┐
│  Overall grade   C+                                        │
│  Concerns to weigh                                         │
│                                                            │
│  For a child, a few things here may be worth understanding │
│  first. Personal data may be shared with third parties.    │
│  Facial recognition appears to be enabled. Terms can       │
│  change without notice.                                    │
└───────────────────────────────────────────────────────────┘
```

Generation: stitches verdict_headline + top 3 finding categories via templates.

Pros: Deterministic, cheap, always works, no LLM dependency.
Cons: Reads stitched. Repetitive across policies. Never sounds crafted.

---

### B. LLM only (warmest)

```
┌───────────────────────────────────────────────────────────┐
│  Overall grade   C+                                        │
│  Concerns to weigh                                         │
│                                                            │
│  For a child, this policy needs some thought before        │
│  signing up. The most notable concerns center on what      │
│  happens to a child's photos and location once the app     │
│  has them — and how the terms can shift without warning.   │
└───────────────────────────────────────────────────────────┘
```

Generation: LLM with strict prompt + JSON schema.

Pros: Warm, contextual, sounds crafted for THIS policy.
Cons: Adds latency (~2-4s). Breaks entirely if LLM down. Violates HR5 (LLM failures must fall back to rules).

---

### C. LLM with template fallback (recommended)

```
┌───────────────────────────────────────────────────────────┐
│  Overall grade   C+                                        │
│  Concerns to weigh                                         │
│                                                            │
│  For a child, this policy needs some thought before        │
│  signing up. The most notable concerns center on what      │
│  happens to a child's photos and location once the app     │
│  has them.                                                 │
│                                                            │
│  (if LLM is unreachable, silently falls back to Option A   │
│   template — reader never sees the difference)             │
└───────────────────────────────────────────────────────────┘
```

Generation: LLM path first; on failure/timeout, template renders.

Pros: Warm when possible; never breaks; matches HR5 fallback pattern. Same tone across chips because prompt is chip-lensed.
Cons: Two code paths to maintain.

---

## Q5 — Vocabulary at the top of the page

Same layout, different top-label word.

### A. "Policy review" (recommended)

```
┌───────────────────────────────────────────────────────────┐
│  Policy review                                             │
│  SnapKidz privacy policy · reviewed for a child            │
│                                                            │
│  Overall grade   C+                                  (i)  │
│  Concerns to weigh                                         │
└───────────────────────────────────────────────────────────┘
```

Feel: Neutral, adult, professional. Report-card SHAPE without report-card language.

---

### B. "Report card"

```
┌───────────────────────────────────────────────────────────┐
│  Report card                                               │
│  SnapKidz privacy policy · reviewed for a child            │
│                                                            │
│  Overall grade   C+                                  (i)  │
│  Concerns to weigh                                         │
└───────────────────────────────────────────────────────────┘
```

Feel: Playful, on-brand for the metaphor, may feel infantilizing to some adult readers (privacy advocates, small biz owners).

---

### C. "Policy check"

```
┌───────────────────────────────────────────────────────────┐
│  Policy check                                              │
│  SnapKidz privacy policy · reviewed for a child            │
│                                                            │
│  Overall grade   C+                                  (i)  │
│  Concerns to weigh                                         │
└───────────────────────────────────────────────────────────┘
```

Feel: Casual, conversational, "quick check" energy. Neutral for any audience.

---

## Composite view — recommended combination

For reference: what the top of a real results view looks like if you pick the recommended option for each question (Q1: C split, Q2: A grade+domain, Q3: B st.bar_chart, Q4: C LLM+fallback, Q5: A "Policy review").

```
┌─────────────────────────────────────────────────────────────┐
│  Policy review                                               │
│                                                              │
│  SnapKidz privacy policy · reviewed for a child              │
│                                                              │
│  Overall grade   C+                                    (i)  │
│  Concerns to weigh                                           │
│                                                              │
│  For a child, this policy needs some thought before          │
│  signing up. The most notable concerns center on what        │
│  happens to a child's photos and location once the app       │
│  has them, and how the terms can shift without warning.      │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Data                                            B-    (i)  │
│  what's collected                                            │
│                                                              │
│  ▸ This service watches for your child's face in photos     │
│    to tag them. That's more identifying data than most       │
│    families expect to hand over.                             │
│    [see the exact wording ▸]                                │
│                                                              │
│  ▸ This service tracks your child's location. Precise       │
│    geolocation raises the stakes for who could see where    │
│    your child is.                                            │
│    [see the exact wording ▸]                                │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Data use                                        C     (i)  │
│  how it's used                                               │
│                                                              │
│  ▸ This service may use what a child does inside the app    │
│    to train AI systems. Most families expect a heads-up      │
│    and a way to opt out.                                     │
│    [see the exact wording ▸]                                │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Terms of use                                    C+    (i)  │
│  the agreement itself                                        │
│                                                              │
│  ▸ Terms can change without notice. Something a child        │
│    agreed to today may look different tomorrow.              │
│    [see the exact wording ▸]                                │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Privacy rights                                  D+    (i)  │
│  what can still be exercised                                 │
│                                                              │
│  ▸ Deletion rights appear to be limited. A child's           │
│    information may be harder to remove later than to add.    │
│    [see the exact wording ▸]                                │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  What might help next                                        │
│                                                              │
│  • Look for parental supervision controls before sign-up.   │
│  • Check whether facial recognition can be turned off.       │
│  • Watch for a policy-change notification.                   │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  What else worth checking                                    │
│                                                              │
│  This review looked at the privacy policy. For a fuller      │
│  picture, three other places sometimes tell more:            │
│                                                              │
│  · The app's Terms of Use. Data-related language sometimes  │
│    lives there and not in the Privacy Policy. Worth a read  │
│    side-by-side.                                             │
│                                                              │
│  · The App Store Privacy Nutrition Label (iOS) or Play      │
│    Store Data Safety section (Android). Platforms require   │
│    developers to declare what data is collected and how     │
│    it's used, in a standardized format that's easier to     │
│    scan than the policy itself.                              │
│                                                              │
│  · The permissions the app actually requests once installed.│
│    Camera, microphone, contacts, and location live in       │
│    device Settings. Sometimes what the app asks for at      │
│    install time is broader than what the policy suggests.   │
│                                                              │
│  Reviewed 2026-07-03 · policy last modified 2026-07-03      │
│                                                              │
│  [export as PDF]  [export as JSON]  [export as CSV]         │
└─────────────────────────────────────────────────────────────┘
```

## What the `(i)` popover looks like when tapped (using Q3-B)

```
┌── How this grade was computed ──────────────────────────┐
│                                                          │
│ Overall grade: C+                                        │
│                                                          │
│ Grades by section:                                       │
│                                                          │
│  [Streamlit horizontal bar chart, theme-tinted:]         │
│   Data           |======                                 │
│   Data use       |=====                                  │
│   Terms of use   |====                                   │
│   Privacy rights |==                                     │
│                                                          │
│ Every finding gets an IRP score — Impact, Likelihood,    │
│ and any Safeguards the policy names. Higher-impact       │
│ findings that are likely to affect this reader push      │
│ the grade down.                                          │
│                                                          │
│ For this context — parent evaluating for a child — the   │
│ grade weights "Children's Privacy" and "Minors" more     │
│ heavily than other findings.                             │
│                                                          │
│ Grade tiers:                                             │
│   A  clean, low practical concern                        │
│   B  worth a read, some to weigh                         │
│   C  meaningful concerns to weigh                        │
│   D  serious concerns                                    │
│                                                          │
│ [see the formula ▸]  [see the category weights ▸]        │
└──────────────────────────────────────────────────────────┘
```

## Decision request

Reply with 5 letters (one per question) — e.g. "C, A, B, C, A" — and I'll lock the design in the revamp plan doc and file the 5 GitHub issues. Or push back on any option and I'll re-sketch.
