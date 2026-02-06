# LIB-EVAL: Evaluation Rubric & Quality Metrics

## Rubric Categories (7 weighted)

| Category | Weight | Target | What It Measures |
|----------|--------|--------|-----------------|
| Product Integrity | 20% | >= 4.2 | Purpose clarity, mental model, cohesion |
| Legal Signal Quality | 25% | >= 4.2 | Issue precision, evidence binding, jurisdiction mapping |
| Privacy & Security | 15% | >= 4.2 | Data minimization, anonymization, transparency |
| Accessibility & Usability | 15% | >= 4.2 | Keyboard nav, contrast, help density |
| Visual & Interaction Design | 10% | >= 4.2 | Hierarchy, feedback, dark/light parity |
| Performance & Reliability | 10% | >= 4.2 | Perceived speed, resilience, state persistence |
| Governance Readiness | 5% | >= 4.2 | Exportability, audit path, change control |

- Scale: 1-5 per category
- Pass threshold: >= 4.2 average
- Critical blocker: any category <= 2

## Computed Rubric (Backend `_compute_rubric_scores`)

Derived from all stored analyses:

| Metric | Source |
|--------|--------|
| productIntegrity | Based on review_required ratio |
| legalSignalQuality | Based on average confidence |
| privacySecurity | Based on jurisdiction coverage |
| accessibilityUsability | Fixed baseline (adjustable) |
| visualIxd | Fixed baseline |
| performanceReliability | Based on analysis count |
| governanceReadiness | Based on analyses with summaries |
| overall | Weighted average of all 7 |

## Evaluation Scripts

### evaluate.py
- Runs rule engine against gold dataset
- Computes per-category True Positives, False Positives, False Negatives
- Reports Precision, Recall, F1 per category
- Reports macro-average F1

### evaluate_dataset.py
- Extended evaluation with optional LLM
- Computes Cohen's Kappa for inter-rater agreement
- Supports custom gold dataset path

## Gold Dataset Format

```json
[
  {
    "text": "policy text...",
    "jurisdictions": ["US-CA", "GDPR"],
    "expected_categories": ["Sale/Share", "Retention"]
  }
]
```

## Quality Targets

| Metric | Target |
|--------|--------|
| Macro F1 (rules only) | >= 0.70 |
| Per-category F1 | >= 0.60 each |
| Cohen's Kappa | >= 0.65 |
| Validation confidence (no hallucinations) | >= 0.80 |
| False positive rate | <= 15% |
