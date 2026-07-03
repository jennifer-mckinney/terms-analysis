# LIB-EVAL — rubric, F1/Kappa, quality targets
loads: on-trigger
scope: project
xref: [[LIB-RULES]] [[docs/BRD_Terms_Policies_Reviewer.md]] [[docs/PRD_Terms_Policies_Reviewer.md]]

status (2026-07-03): "Rubric Categories" = BRD/PRD spec (1-5 human-scored, weighted, 4.2 pass). "Computed Rubric" = what `main.py::_compute_rubric_scores()` implements today (0-10 scale, unweighted mean of three heuristics). Treat computed as a rough proxy for spec, not implementation of it.

## spec-rubric

### E1: rubric-scale-and-thresholds
rule: BRD/PRD spec is 7 weighted categories, 1-5 per category, pass threshold >= 4.2 average, critical blocker if any category <= 2
scope: qualitative design review, not what backend computes today

| Category | Weight | Target | What It Measures |
|----------|--------|--------|------------------|
| Product Integrity | 20% | >= 4.2 | Purpose clarity, mental model, cohesion |
| Legal Signal Quality | 25% | >= 4.2 | Issue precision, evidence binding, jurisdiction mapping |
| Privacy & Security | 15% | >= 4.2 | Data minimization, anonymization, transparency |
| Accessibility & Usability | 15% | >= 4.2 | Keyboard nav, contrast, help density |
| Visual & Interaction Design | 10% | >= 4.2 | Hierarchy, feedback, dark/light parity |
| Performance & Reliability | 10% | >= 4.2 | Perceived speed, resilience, state persistence |
| Governance Readiness | 5% | >= 4.2 | Exportability, audit path, change control |

## computed-rubric

### E2: computed-scale-is-0-to-10
rule: `_compute_rubric_scores()` uses 0-10 scale, NOT 1-5

### E3: three-underlying-signals
rule: every category field is a linear combination of three underlying signals — `base`, `confidence_score`, `review_score`

```python
base = clamp(10 - avg_risk_score)
confidence_score = clamp(avg_confidence * 10)
review_score = clamp(10 - review_rate * 10)  # review_rate = fraction with status == "needs_review"
```

| Field | Formula |
|-------|---------|
| `productIntegrity` | `base` |
| `legalSignalQuality` | `confidence_score` |
| `privacySecurity` | `0.9 * base + 0.1 * confidence_score` |
| `accessibilityUsability` | `0.6 * review_score + 0.4 * confidence_score` |
| `visualIxd` | `0.5 * review_score + 0.5 * base` |
| `performanceReliability` | `0.7 * review_score + 0.3 * base` |
| `governanceReadiness` | `review_score` |
| `overall` | `(base + confidence_score + review_score) / 3` — unweighted mean of three, NOT weighted average of the 7 fields above |

### E4: no-spec-weighting-in-code
rule: per-category spec weighting (20%/25%/15%/...) is NOT implemented anywhere in `_compute_rubric_scores`
because: pattern is same "spec vs. shipped approximation" as IRP vs. severity-weighted risk score (see LIB-RULES)

## evaluation-scripts

### E5: evaluate.py
rule: runs rule engine against gold dataset; computes per-category TP/FP/FN → Precision, Recall, F1 per category + macro-average F1

### E6: evaluate_dataset.py
rule: extended eval with optional LLM; computes Cohen's Kappa; supports custom gold dataset path

## gold-dataset-format

```json
[
  {
    "text": "policy text...",
    "jurisdictions": ["US-CA", "GDPR"],
    "expected_categories": ["Sale/Share", "Retention"]
  }
]
```

## quality-targets

| Metric | Target |
|--------|--------|
| Macro F1 (rules only) | >= 0.70 |
| Per-category F1 | >= 0.60 each |
| Cohen's Kappa | >= 0.65 |
| Validation confidence (no hallucinations) | >= 0.80 |
| False positive rate | <= 15% |
