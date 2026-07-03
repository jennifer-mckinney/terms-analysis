# LIB-EVAL: Evaluation Rubric & Quality Metrics

> **Status (2026-07-03):** the two sections below describe two different things that are easy to conflate. "Rubric Categories" is the BRD/PRD-specified *design* — a 1-5 human-scored rubric with per-category weights and a 4.2 pass threshold, intended for qualitative design review. "Computed Rubric" is what `main.py::_compute_rubric_scores()` actually implements today — a 0-10 scale, unweighted mean of three derived heuristics (`base`, `confidence_score`, `review_score`), with no per-category weighting and no 4.2 threshold anywhere in the code. Treat the computed version as a rough automated proxy for the specified rubric, not an implementation of it — same "spec vs. shipped approximation" pattern as the IRP/severity-weighted risk score (see LIB-RULES).

## Rubric Categories (7 weighted) — BRD/PRD spec, not what the backend computes today

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

## Computed Rubric (Backend `_compute_rubric_scores`) — what actually ships today

Derived from all stored `Analysis` records, on a **0-10 scale** (not 1-5):

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
| `overall` | `(base + confidence_score + review_score) / 3` — an unweighted mean of the three underlying scores, **not** a weighted average of the 7 category fields above |

There is no per-category weighting (20%/25%/15%/... from the spec table) anywhere in this function — every category field is a different linear combination of just three underlying signals (`base`, `confidence_score`, `review_score`), each itself a proxy: `base` from average risk score, `confidence_score` from average analysis confidence, `review_score` from the human-review rate.

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
