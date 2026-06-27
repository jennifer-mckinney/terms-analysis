# Online AI Apps Terms & Policies Reviewer — Evaluation Rubric

Use this rubric to assess design quality, legal signal quality, privacy posture, accessibility, and integration of the **User App**, **Verify View**, and **Rolling Dashboard**. Score each criterion 1–5 (1 = insufficient, 3 = acceptable, 5 = exemplary). Target average ≥4.2 before pilot.

## 1. Product Integrity (Weight 20%)
- **Purpose clarity**: Users can explain what the tool does in one sentence after 30s.  
- **Mental model**: Flow from input → overview → findings → actions → verify makes intuitive sense.  
- **Cohesion**: User app and dashboard share tokens, layout rhythm, and component vocabulary.

## 2. Legal Signal Quality (Weight 20%)
- **Issue precision**: Detected categories (ADM, sale/share, dark patterns, retention, missing rights) map to correct clauses.  
- **Evidence binding**: Every claim is backed by a visible excerpt and legal hook; Verify view highlights exact lines.  
- **Jurisdiction mapping**: Findings and templates adapt when jurisdiction changes.

## 3. AI Law Signal Quality (Weight 10%)
- **AI training disclosure**: Tool detects clauses where user data trains AI/ML models and flags missing opt-out rights.
- **Automated decision-making**: Tool surfaces fully automated decisions lacking human review rights (GDPR Art. 22, EU AI Act Art. 86, Colorado AI Act SB 205).
- **High-risk AI sectors**: Tool identifies AI use in regulated sectors (credit, employment, education, healthcare) and maps to EU AI Act Annex III.
- **Biometric AI**: Tool detects biometric identifier collection and flags Illinois BIPA + EU AI Act Art. 5 prohibition on real-time biometric surveillance.
- **GPAI / foundation model transparency**: Tool flags services built on general-purpose AI models and maps to EU AI Act Title VIII obligations.

## 4. Privacy & Security (Weight 10%)
- **Data minimization**: Defaults to local analysis; opt-in controls for aggregation are prominent and explained.  
- **Anonymization quality**: Aggregates strip identifiers and store only needed fields.  
- **Transparency**: Model card is discoverable and truthful about limitations.

## 5. Accessibility & Usability (Weight 15%)
- **Keyboard & focus**: Tabs, filters, dialogs, and buttons are keyboard operable with visible focus.  
- **Contrast & size**: Text and controls meet WCAG AA contrast; touch targets ≥ 44px.  
- **Help density**: Info icons explain purpose/“why” without overwhelming the screen.

## 6. Visual & Interaction Design (Weight 10%)
- **Hierarchy**: Clear typography scale, spacing, and grouping.  
- **Feedback**: Hover, pressed, and loading states are consistent and subtle.  
- **Dark/Light parity**: Equal legibility and tone in both modes.

## 7. Performance & Reliability (Weight 10%)
- **Perceived speed**: First interaction and subsequent updates feel instantaneous in-browser.  
- **Resilience**: App handles empty inputs, long text, and repeated actions gracefully.  
- **State persistence**: Aggregates persist (localStorage) and refresh without reload.

## 8. Governance Readiness (Weight 5%)
- **Exportability**: JSON export and print-ready summary are accurate and complete.  
- **Audit path**: Verify view + evidence excerpts are sufficient to reconstruct a finding.  
- **Change control**: Versioning approach is defined for prompts/rules and dashboards.

---

### Scoring Sheet
| Category | Weight | Score (1-5) | Weighted |
|---|---:|---:|---:|
| Product Integrity | 0.20 |  |  |
| Legal Signal Quality | 0.20 |  |  |
| AI Law Signal Quality | 0.10 |  |  |
| Privacy & Security | 0.10 |  |  |
| Accessibility & Usability | 0.15 |  |  |
| Visual & Interaction Design | 0.10 |  |  |
| Performance & Reliability | 0.10 |  |  |
| Governance Readiness | 0.05 |  |  |
| **Total** | **1.00** |  |  |

**Pass threshold:** ≥4.2 average. **Critical blockers:** any criterion ≤2 in Legal Signal, AI Law Signal, Privacy, or Accessibility.

