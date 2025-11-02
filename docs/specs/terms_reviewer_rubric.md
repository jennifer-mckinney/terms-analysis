# Online AI Apps Terms & Policies Reviewer — Evaluation Rubric

Use this rubric to assess design quality, legal signal quality, privacy posture, accessibility, and integration of the **User App**, **Verify View**, and **Rolling Dashboard**. Score each criterion 1–5 (1 = insufficient, 3 = acceptable, 5 = exemplary). Target average ≥4.2 before pilot.

## 1. Product Integrity (Weight 20%)
- **Purpose clarity**: Users can explain what the tool does in one sentence after 30s.  
- **Mental model**: Flow from input → overview → findings → actions → verify makes intuitive sense.  
- **Cohesion**: User app and dashboard share tokens, layout rhythm, and component vocabulary.

## 2. Legal Signal Quality (Weight 25%)
- **Issue precision**: Detected categories (ADM, sale/share, dark patterns, retention, missing rights) map to correct clauses.  
- **Evidence binding**: Every claim is backed by a visible excerpt and legal hook; Verify view highlights exact lines.  
- **Jurisdiction mapping**: Findings and templates adapt when jurisdiction changes.

## 3. Privacy & Security (Weight 15%)
- **Data minimization**: Defaults to local analysis; opt-in controls for aggregation are prominent and explained.  
- **Anonymization quality**: Aggregates strip identifiers and store only needed fields.  
- **Transparency**: Model card is discoverable and truthful about limitations.

## 4. Accessibility & Usability (Weight 15%)
- **Keyboard & focus**: Tabs, filters, dialogs, and buttons are keyboard operable with visible focus.  
- **Contrast & size**: Text and controls meet WCAG AA contrast; touch targets ≥ 44px.  
- **Help density**: Info icons explain purpose/“why” without overwhelming the screen.

## 5. Visual & Interaction Design (Weight 10%)
- **Hierarchy**: Clear typography scale, spacing, and grouping.  
- **Feedback**: Hover, pressed, and loading states are consistent and subtle.  
- **Dark/Light parity**: Equal legibility and tone in both modes.

## 6. Performance & Reliability (Weight 10%)
- **Perceived speed**: First interaction and subsequent updates feel instantaneous in-browser.  
- **Resilience**: App handles empty inputs, long text, and repeated actions gracefully.  
- **State persistence**: Aggregates persist (localStorage) and refresh without reload.

## 7. Governance Readiness (Weight 5%)
- **Exportability**: JSON export and print-ready summary are accurate and complete.  
- **Audit path**: Verify view + evidence excerpts are sufficient to reconstruct a finding.  
- **Change control**: Versioning approach is defined for prompts/rules and dashboards.

---

### Scoring Sheet
| Category | Weight | Score (1-5) | Weighted |
|---|---:|---:|---:|
| Product Integrity | 0.20 |  |  |
| Legal Signal Quality | 0.25 |  |  |
| Privacy & Security | 0.15 |  |  |
| Accessibility & Usability | 0.15 |  |  |
| Visual & Interaction Design | 0.10 |  |  |
| Performance & Reliability | 0.10 |  |  |
| Governance Readiness | 0.05 |  |  |
| **Total** | **1.00** |  |  |

**Pass threshold:** ≥4.2 average. **Critical blockers:** any criterion ≤2 in Legal Signal, Privacy, or Accessibility.

