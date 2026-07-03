# LIB-RULES: Rule Engine Patterns & Scoring

> **Status (2026-07-03):** rewritten to match `services/rules.py` and `services/analyzer.py` exactly. The previous version of this file described a 9-category/dead-clamp/precedence-merge/"IRP" model that diverged from the live code on every one of those points — see git history if the old conceptual framework is useful context, but treat everything below as ground truth for the current implementation.

## Risk Categories: ~50 categories, 64 patterns

`PATTERNS` in `rules.py` has grown far past the original 9-category framework. It now covers ~50 distinct `category` values across 64 `RulePattern` entries, spanning:
- The original core set: Sale/Share, ADM, Dark Patterns, Retention, User Rights, Minors, Sensitive Data, Unilateral Changes, Liability.
- AI Act sub-categories: AI Training (Opt-Out), AI Non-Discrimination, AI-Generated Content, Algorithmic Accountability, Automated Decision-Making, Consequential AI Decisions, GPAI / Generative AI, High-Risk AI, Human Oversight, Prohibited AI.
- Industry/regulation-specific blocks: COPPA Compliance, FERPA Compliance, HIPAA Compliance, PCI DSS Compliance, Health Data, Financial Data, Breach Notification, Children's Privacy.
- Per-jurisdiction international blocks: APP Privacy (Australia), APPI Disclosure (Japan), DPDP Consent (India), LGPD Rights (Brazil), PIPA/PIPEDA/POPIA Processing, UK Data Rights, Cross-Border Transfer, Serious Privacy Invasion, Privacy as Human Right.
- General categories: Collection Notice, Data Rights, Data Security, Deceptive Practices, Individual Rights, Marketing Communications, Privacy Rights, Purpose Limitation, Sensitive Data / Opt-Out, Tracking & Consent.

Each `RulePattern` carries: `category`, `severity` (Low/Medium/High/Critical), `jurisdictions` (list of applicable `Jurisdiction` codes), one or more regex `patterns`, and a legal-basis citation. `detect_findings()` only evaluates a rule if its `jurisdictions` intersects the requested jurisdiction list.

## Rule-Based Confidence Formula (active path: `_confidence_rules_based`)

```python
base = SEVERITY_BASE.get(severity, 0.6)  # {"Low": 0.45, "Medium": 0.6, "High": 0.75, "Critical": 0.9} — computed but currently unused in the return value
hit_ratio = pattern_hits / pattern_total if pattern_total else 0.0
if pattern_hits >= pattern_total * 0.5:
    confidence = 0.93 + (0.02 * min(1.0, hit_ratio))   # 0.93-0.95
else:
    confidence = 0.90 + (0.03 * hit_ratio)              # 0.90-0.93
return max(0.90, min(0.95, confidence))
```

Rule-based finding confidence is always clamped to **[0.90, 0.95]** — rules are pattern-matched, so they're treated as inherently high-confidence. There is a separate, unused `_confidence()` helper elsewhere in `rules.py` from an earlier design (clamped to `[0.35, 0.95]` with a different formula involving `density`); it is dead code, not the active path.

## Hybrid Merge Strategy (`analyzer.py::_merge_findings`)

Rule findings and LLM findings are matched by key `(category.lower(), excerpt.strip()[:120].lower())` — **not** a simple "LLM wins ties" precedence rule:

- **Match on both sides:** confidence becomes a weighted average — `0.6 * rule_confidence + 0.4 * llm_confidence`, clamped to `[0.0, 1.0]`. `needs_review` is set if the hybrid confidence is `< 0.6`.
- **Rule-only match:** kept as-is (confidence stays in the [0.90, 0.95] rule-based range).
- **LLM-only match:** kept as-is, with `needs_review` set if `llm_confidence < 0.6`.

LLM findings with no `evidence.legal_basis` are dropped entirely before merging (tracked as `dropped_for_legal`).

## Top-Level Analysis Confidence (distinct from per-finding confidence)

`analyze_text()` computes an overall `confidence` for the `AnalysisPayload` — this is a different value from any individual finding's confidence:

```python
confidence = mean(validation.confidence, llm_overall_confidence)  # llm_overall_confidence only if present
if mode == "quick":
    confidence *= 0.85
else:
    if summary is None:              # no LLM payload came back at all
        confidence *= 0.8
    elif not llm_findings:           # LLM responded but found nothing
        confidence *= 0.85
    if dropped_for_legal:
        confidence *= max(0.5, 1 - (0.1 * dropped_for_legal))
confidence = max(0.0, min(1.0, confidence))
```

Confidence `< 0.80` (see `config.py::review_threshold`) triggers human-in-the-loop review at the analysis level, independent of any individual finding's `needs_review` flag.

## Risk Score & Grade (`analyzer.py::calculate_risk_score` / `_grade`)

```python
weights = {"Low": 0.2, "Medium": 0.5, "High": 0.8, "Critical": 1.0}
risk_score = round((sum(weights[f.severity] for f in findings) / len(findings)) * 10, 2)  # 0-10 scale
```

```python
def _grade(score):  # score is 0-10, higher = worse
    if score >= 8.5: return "D+"
    if score >= 7.5: return "C"
    if score >= 6.5: return "C+"
    if score >= 5.5: return "B-"
    if score >= 4.5: return "B"
    if score >= 3.5: return "A-"
    return "A"
```

An Impact/Likelihood/Safeguards ("IRP") formula — `IRP = 0.5*(Impact/5) + 0.4*(Likelihood/5) - 0.3*(Safeguards/5)` — is a **planned, not-yet-implemented enhancement** (see `docs/plans/2026-06-24-open-source-rag-pipeline.md` Task 7). It is not wired into any current code path; do not describe it as current behavior.
