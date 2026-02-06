# LIB-RULES: Rule Engine Patterns & IRP Scoring

## 9 Risk Categories

| Category | Severity | Jurisdictions | Pattern Count | Legal Basis |
|----------|----------|---------------|---------------|-------------|
| Sale/Share | High | US-CA | 4 | CCPA/CPRA opt-out |
| ADM | High | GDPR | 4 | GDPR Art. 22 |
| Dark Patterns | Medium | US-CA, GDPR | 5 | GDPR consent, CPRA consent |
| Retention | Medium | US-CA, GDPR | 5 | GDPR Art. 5(1)(e), CPRA retention |
| User Rights | Medium | US-CA, GDPR | 6 | GDPR Art. 15-18, CCPA/CPRA rights |
| Minors | High | US-CA, GDPR | 3 | GDPR Art. 8, CPRA minors |
| Sensitive Data | High | US-CA, GDPR | 4 | GDPR Art. 9, CPRA SPI |
| Unilateral Changes | Medium | US-CA, GDPR | 3 | Unfair terms notice |
| Liability | Medium | US-CA, GDPR | 3 | Consumer protection fairness |

## Confidence Formula

```
confidence = 0.25 + 0.5 * severity_base + 0.15 * hit_ratio + 0.1 * density
```

| Severity | Base Value |
|----------|-----------|
| Low | 0.45 |
| Medium | 0.60 |
| High | 0.75 |
| Critical | 0.90 |

- `hit_ratio` = patterns matched / total patterns for rule
- `density` = min(1.0, total_matches / 5)
- Final confidence clamped to [0.35, 0.95]

## IRP Scoring (Demo v7)

```
IRP = 0.5 * (Impact/5) + 0.4 * (Likelihood/5) - 0.3 * (Safeguards/5)
```

| Color | IRP Range |
|-------|-----------|
| Red | >= 0.75 |
| Yellow | 0.45 - 0.74 |
| Green | < 0.45 |

## Risk Score to Grade (Backend)

```python
def _grade(score):  # score is 0-10
    if score < 3: return "A"
    if score < 5: return "B"
    if score < 7: return "C+"
    if score < 8: return "C"
    if score < 9: return "D+"
    return "D"
```

## Risk Score Calculation

```python
severity_weights = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}
risk_score = (sum of weighted severities / count) * 2.5  # scaled to 0-10
```

## Merge Strategy

Rule findings + LLM findings are deduplicated by key: `(category, excerpt[:80])`.
LLM findings take precedence when keys collide.

## Confidence Modifiers (Analyzer)

| Condition | Modifier |
|-----------|----------|
| LLM offline (returns None) | confidence *= 0.8 |
| LLM returns empty findings | confidence *= 0.85 |
| LLM findings dropped for missing legal_basis | additional penalty |
