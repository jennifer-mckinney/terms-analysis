# LIB-EVAL — rubric, F1/Kappa, quality targets
loads: on-trigger
scope: project
xref: [[LIB-RULES]] [[docs/BRD_Terms_Policies_Reviewer.md]] [[docs/PRD_Terms_Policies_Reviewer.md]]

status (2026-10-11, #153): "spec-rubric" = the human-scored rubric in `docs/specs/terms_reviewer_rubric.md` (1-5 per category, 8 weighted categories, 4.2 pass); its Scoring Sheet is the single source of truth for category names and weights. "computed-rubric" = what `GET /rubric` (`main.py::_compute_rubric_scores()`) returns today: 0-10 per category from heuristic signals, with `overall` as the spec-weighted sum of the 8 category fields. Treat the computed fields as a heuristic proxy for the spec categories, not a measurement of them.

## spec-rubric

### E1: rubric-scale-and-thresholds
rule: the spec (`docs/specs/terms_reviewer_rubric.md`, Scoring Sheet) is 8 weighted categories, 1-5 per category, pass threshold >= 4.2 average, critical blocker if any criterion <= 2 in Legal Signal, AI Law Signal, Privacy, or Accessibility
scope: qualitative design review, not what backend computes today
because: weights below must equal the spec Scoring Sheet; `tests/test_docs_rubric_parity.py` fails on any drift

| Category | Weight | Target | What It Measures |
|----------|--------|--------|------------------|
| Product Integrity | 20% | >= 4.2 | Purpose clarity, mental model, cohesion |
| Legal Signal Quality | 20% | >= 4.2 | Issue precision, evidence binding, jurisdiction mapping |
| AI Law Signal Quality | 10% | >= 4.2 | AI training disclosure, automated decisions, high-risk sectors, biometric AI, GPAI transparency |
| Privacy & Security | 10% | >= 4.2 | Data minimization, anonymization, transparency |
| Accessibility & Usability | 15% | >= 4.2 | Keyboard nav, contrast, help density |
| Visual & Interaction Design | 10% | >= 4.2 | Hierarchy, feedback, dark/light parity |
| Performance & Reliability | 10% | >= 4.2 | Perceived speed, resilience, state persistence |
| Governance Readiness | 5% | >= 4.2 | Exportability, audit path, change control |

## computed-rubric

label: heuristic-proxy
empty-response: `null` (HTTP 200) when there are no analysis records

### E2: computed-scale-is-0-to-10
rule: `_compute_rubric_scores()` uses 0-10 scale, NOT 1-5

### E3: underlying-signals
rule: seven category fields are linear combinations of three derived signals (`base`, `confidence_score`, `review_score`); `aiLawSignalQuality` is computed straight from the raw aggregates `avg_confidence` and `review_rate` with fixed coefficients 8.5 and 1.5; every field is clamped to 0-10

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
| `aiLawSignalQuality` | `clamp(8.5 * avg_confidence + 1.5 * (1 - review_rate))` |
| `overall` | `clamp(0.20 * productIntegrity + 0.20 * legalSignalQuality + 0.10 * aiLawSignalQuality + 0.10 * privacySecurity + 0.15 * accessibilityUsability + 0.10 * visualIxd + 0.10 * performanceReliability + 0.05 * governanceReadiness)` — spec-weighted sum of the 8 category fields, weights from the spec Scoring Sheet |

### E4: spec-weighting-applies-to-overall-only
rule: `overall` applies the spec Scoring Sheet weights to the 8 computed category fields; the category fields themselves are heuristic proxies (E3), not spec scores
because: pattern is same "spec vs. shipped approximation" as IRP vs. severity-weighted risk score (see LIB-RULES); the weights are restated as literals in `main.py` today, and `tests/test_docs_rubric_parity.py` pins `/rubric` to the spec weights

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
