# LIB-RULES — rule engine, confidence formulas, IRP scoring, hybrid merge
loads: on-trigger
scope: project
xref: [[LIB-ARCH]] [[LIB-CONTEXT]] [[LIB-EVAL]] [[.claude/CLAUDE.md#hard-requirements]]

status (2026-07-03): matches `services/rules.py` and `services/analyzer.py`. Previous version diverged (9-category/dead-clamp/"IRP" model) — see git history if needed but treat everything below as ground truth.

## risk-categories

### R1: ~50-categories-64-patterns
rule: `PATTERNS` in `rules.py` covers ~50 distinct `category` values across 64 `RulePattern` entries
coverage:
  core: Sale/Share, ADM, Dark Patterns, Retention, User Rights, Minors, Sensitive Data, Unilateral Changes, Liability
  ai_act: AI Training (Opt-Out), AI Non-Discrimination, AI-Generated Content, Algorithmic Accountability, Automated Decision-Making, Consequential AI Decisions, GPAI / Generative AI, High-Risk AI, Human Oversight, Prohibited AI
  industry_regulation: COPPA Compliance, FERPA Compliance, HIPAA Compliance, PCI DSS Compliance, Health Data, Financial Data, Breach Notification, Children's Privacy
  jurisdiction: APP Privacy (AU), APPI Disclosure (JP), DPDP Consent (IN), LGPD Rights (BR), PIPA/PIPEDA/POPIA Processing, UK Data Rights, Cross-Border Transfer, Serious Privacy Invasion, Privacy as Human Right
  general: Collection Notice, Data Rights, Data Security, Deceptive Practices, Individual Rights, Marketing Communications, Privacy Rights, Purpose Limitation, Sensitive Data / Opt-Out, Tracking & Consent

### R2: RulePattern-shape
rule: each `RulePattern` MUST carry `category`, `severity` (Low/Medium/High/Critical), `jurisdictions` (list of `Jurisdiction` codes), one or more regex `patterns`, and a legal-basis citation

### R3: jurisdiction-intersection-required
rule: `detect_findings()` evaluates a rule only if its `jurisdictions` intersects the requested jurisdiction list

## rule-confidence-formula

### R4: active-path-clamp
rule: rule-based finding confidence clamped to [0.90, 0.95] via `_confidence_rules_based`
because: rules are pattern-matched → inherently high-confidence

```python
base = SEVERITY_BASE.get(severity, 0.6)  # {"Low": 0.45, "Medium": 0.6, "High": 0.75, "Critical": 0.9} — currently unused in return
hit_ratio = pattern_hits / pattern_total if pattern_total else 0.0
if pattern_hits >= pattern_total * 0.5:
    confidence = 0.93 + (0.02 * min(1.0, hit_ratio))   # 0.93-0.95
else:
    confidence = 0.90 + (0.03 * hit_ratio)              # 0.90-0.93
return max(0.90, min(0.95, confidence))
```

### R5: dead-alternate-confidence-helper
rule: the separate `_confidence()` helper (clamped to [0.35, 0.95] with density term) is dead code from an earlier design
apply: do NOT wire back into the active path without ADR

## hybrid-merge

### R6: match-key
rule: rule + LLM findings matched by `(category.lower(), excerpt.strip()[:120].lower())` — NOT precedence

### R7: match-on-both-sides
rule: when both match → confidence = `0.6 * rule_confidence + 0.4 * llm_confidence`, clamped [0.0, 1.0]; `needs_review` set if hybrid < 0.6

### R8: rule-only-match
rule: kept as-is (confidence stays in [0.90, 0.95])

### R9: llm-only-match
rule: kept as-is; `needs_review` set if `llm_confidence < 0.6`

### R10: llm-must-have-legal-basis
rule: LLM findings with no `evidence.legal_basis` MUST be dropped before merging
tracking: counted as `dropped_for_legal`

## top-level-analysis-confidence

### R11: analysis-confidence-formula
rule: `analyze_text()` computes an overall `AnalysisPayload.confidence`, distinct from per-finding confidence

```python
confidence = mean(validation.confidence, llm_overall_confidence)  # llm_overall_confidence only if present
if mode == "quick":
    confidence *= 0.85
else:
    if summary is None:              # no LLM payload
        confidence *= 0.8
    elif not llm_findings:           # LLM responded, found nothing
        confidence *= 0.85
    if dropped_for_legal:
        confidence *= max(0.5, 1 - (0.1 * dropped_for_legal))
confidence = max(0.0, min(1.0, confidence))
```

### R12: HITL-at-analysis-level
rule: `confidence < 0.80` (see `config.py::review_threshold`) triggers HITL review at analysis level
independent_of: any individual finding's `needs_review` flag

## risk-score-and-grade

### R13: risk-score-formula
```python
weights = {"Low": 0.2, "Medium": 0.5, "High": 0.8, "Critical": 1.0}
risk_score = round((sum(weights[f.severity] for f in findings) / len(findings)) * 10, 2)  # 0-10
```

### R14: grade-thresholds
```python
def _grade(score):  # 0-10, higher = worse
    if score >= 8.5: return "D+"
    if score >= 7.5: return "C"
    if score >= 6.5: return "C+"
    if score >= 5.5: return "B-"
    if score >= 4.5: return "B"
    if score >= 3.5: return "A-"
    return "A"
```

## IRP

### R15: irp-formula
rule: `irp_score = clamp(0.5*(impact/5) + 0.4*(likelihood/5) - 0.3*(safeguard_score/5), 0, 1)`

### R16: irp-fields
rule: `Finding` schema carries these fields

| Field | Type | Default | Range | Meaning |
|-------|------|---------|-------|---------|
| `impact` | int | 2 | 1-5 | Harm if clause enforced (1=trivial, 5=catastrophic) |
| `likelihood` | int | 3 | 1-5 | How automatic/probable clause activation is |
| `safeguard_score` | int | 0 | 0-5 | Existing mitigations in the document |
| `irp_score` | float? | None | 0-1 | Composite IRP score |

score_range:
- Max risk (impact=5, likelihood=5, safeguard=0): 0.90
- Fully mitigated (impact=1, likelihood=1, safeguard=5): 0.0 (clamped from -0.12)
- Typical Sale/Share (impact=4, likelihood=5, safeguard=0): 0.80
- Prohibited AI (impact=5, likelihood=1, safeguard=0): 0.58

### R17: rule-irp-seed
rule: rule-based findings seed IRP from `_CATEGORY_IRP_DEFAULTS` (38 categories mapped) via `_seed_irp(category)`
default: `safeguard_score=0` at detection time (no mitigations assumed)

### R18: llm-irp-request
rule: LLM prompt MUST request `impact`, `likelihood`, `safeguard_score` per finding; `irp_score` computed from those fields after parsing

### R19: hybrid-irp
rule: hybrid findings use rule `impact`/`likelihood` as baseline; `safeguard_score = max(rule, llm)`; `irp_score` recomputed
because: benefit of the doubt for user protections

### R20: risk-score-uses-irp-when-present
rule: `calculate_risk_score()` uses `irp_score` when present; falls back to severity weight for legacy findings without IRP

```python
scores = [
    f.irp_score if f.irp_score is not None
    else severity_weights.get(f.severity, 0.5)
    for f in findings
]
risk_score = round((sum(scores) / len(scores)) * 10, 2)  # 0-10
```

### R21: grade-thresholds-unchanged
rule: grade thresholds unchanged when IRP-driven (A < 3.5, ... D+ >= 8.5) — see R14

## sort-tier-first

### R22: sort-key
rule: sort key = `(weight, irp_score, severity_rank)`, all descending

```python
def sort_key(f: Finding) -> tuple[float, float, int]:
    weight = merged.get(f.category, 1.0)
    irp = f.irp_score if f.irp_score is not None else _severity_fallback(f.severity)
    return (weight, irp, _SEVERITY_RANK.get(f.severity, 0))
```

order:
1. context weight leads — 3.0-weighted category always outranks 2.0, regardless of IRP
2. IRP breaks ties within a weight tier
3. severity rank is final tie-breaker

baseline_chips: `want_understand`, `just_curious` collapse all categories to 1.0 → IRP drives entire sort
xref: [[LIB-CONTEXT#CTX7]]

## category-taxonomy

### R23: pin-via-frozenset
rule: canonical finding categories live as `CATEGORIES: frozenset[str]` in `src/backend/app/schemas.py`
guard: `services/context.py::CATEGORY_WEIGHTS` and `services/analyzer.py::_CATEGORY_IRP_DEFAULTS` validate keys against this frozenset at module load
enforcement: drift raises `RuntimeError` before server starts

### R24: add-category-checklist
rule: adding a rule-engine category MUST also update `schemas.CATEGORIES`; if it belongs in IRP-defaults or context weights, add there too
because: otherwise backend refuses to import

## global-tool-contract

### R25: empty-jurisdictions-no-filter
rule: `jurisdictions=[]` treated as "no filter" across entire pipeline
detail:
  - `rules.py::detect_findings` evaluates every rule if requested list empty
  - LLM post-filter passes every finding through if empty
  - Streamlit resolves empty selection to "no filter"

### R26: no-default-jurisdiction-fallback
rule: NO default jurisdiction fallback anywhere
forbidden: silently substituting US-CA + GDPR when reader hasn't picked
because: removed in PR #34 — global tool, blank defaults, reader specifies (or doesn't)
