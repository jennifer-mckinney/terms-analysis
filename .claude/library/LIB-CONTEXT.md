# LIB-CONTEXT: Context Chip Taxonomy & Surfacing Bias

> **Status (2026-07-03):** shipped in PR #34 (issue #19 redesign). This documents the context-chip system as implemented in `src/backend/app/services/context.py` and consumed by `src/webapp/app_streamlit_v2.py`. Treat this as ground truth for reader-intent modeling.

## The five chips

Copy is taken verbatim from `CONTEXT_CHIPS` in `src/webapp/app_streamlit_v2.py`. `value` is the stable id used in the backend contract; `label` is the chip text; `sub` is the italic help copy shown under the label.

| value | label | italic sub-line |
|-------|-------|-----------------|
| `want_understand` | I want to understand what I am agreeing to | *Nice to know before you tap "I agree." No judgment if you already did.* |
| `for_child` | Something my child wants to use | *Games, apps, social platforms. We will help you see what matters.* |
| `for_care` | Helping someone I care about with this | *A family member, extended family, and/or a friend.* |
| `for_work` | For work or a vendor pick | *A tool the team might use, or an agreement to sign.* |
| `just_curious` | Just curious | *Sometimes it is good to just know. No pressure either way.* |

The chips are the canonical `ContextChip` Literal in `src/backend/app/schemas.py`. `main.py::_VALID_CHIPS` is derived at module load via `frozenset(get_args(ContextChip))` so drift fails at import.

## Priority order (verdict copy only)

```python
_CHIP_PRIORITY: list[ContextChip] = [
    "for_child",
    "for_care",
    "for_work",
    "want_understand",
    "just_curious",
]
```

Rationale: **personal-stakes lenses win the headline over professional lenses.** When someone selects both `for_child` and `for_work`, the child lens frames the verdict — the professional context is a secondary concern. Reason: if a parent is checking a policy on behalf of their child at work (an EdTech vendor pick, say), the harm horizon on the child side is more consequential than the vendor-onboarding side. If the reader disagrees, they can deselect the child chip.

This priority controls **verdict copy only** (which headline + label the reader sees). It does **not** control surfacing order — surfacing sums weights across all selected chips (see below).

## Weight tier scale

| Tier | Weight | Semantics |
|------|--------|-----------|
| Baseline | 1.0 | Category is not specifically privileged for this chip. IRP drives its order. |
| Boosted | 2.0 | Category is meaningful in this context; surfaces above IRP-equal baseline items. |
| Priority | 2.5 | Category is one of the top handful the reader should notice for this context. |
| Signature | 3.0 | Category is the defining risk for this context. Always surfaces first if present. |

`for_work` uses one intermediate rung not in the base tier scale (2.2, 2.4, 2.6, 2.8) to differentiate the vendor-review categories at finer granularity — Liability at 3.0, Unilateral Changes at 2.8, Data Security at 2.6, Breach Notification at 2.5, Cross-Border Transfer at 2.4, ADM at 2.2. This is the only chip that uses sub-tier weights.

## Full `CATEGORY_WEIGHTS` reference

Dumped verbatim from `services/context.py` — treat this table as authoritative and re-generate if the file changes.

```python
CATEGORY_WEIGHTS: dict[ContextChip, dict[str, float]] = {
    "want_understand": {},  # baseline, IRP-driven only
    "for_child": {
        "Children's Privacy": 3.0,
        "COPPA Compliance": 3.0,
        "Minors": 3.0,
        "Biometric Data": 2.5,
        "AI Training": 2.5,
        "Sensitive Data": 2.5,
        "Tracking / Profiling": 2.0,
        "Dark Patterns": 2.0,
        "Data Sale / Sharing": 2.0,
        "Sale/Share": 2.0,
    },
    "for_care": {
        "Dark Patterns": 3.0,
        "Deceptive Practices": 3.0,
        "Consequential AI Decisions": 2.5,
        "Automated Decision-Making": 2.5,
        "ADM": 2.5,
        "Health Data": 2.5,
        "Data Sale / Sharing": 2.0,
        "Sale/Share": 2.0,
    },
    "for_work": {
        "Liability": 3.0,
        "Unilateral Changes": 2.8,
        "Data Security": 2.6,
        "Breach Notification": 2.5,
        "Cross-Border Transfer": 2.4,
        "Automated Decision-Making": 2.2,
        "ADM": 2.2,
        "Retention": 2.2,
        "Sale/Share": 2.2,
        "Data Sale / Sharing": 2.2,
        "Purpose Limitation": 2.0,
    },
    "just_curious": {},  # baseline, IRP-driven only
}
```

Two chips (`want_understand` and `just_curious`) are **intentionally empty**. They collapse to IRP-driven order — the reader has expressed no specific lens, so the tool defaults to "show what the composite risk score says matters."

Every key in this dict is validated against `schemas.CATEGORIES` at module load. If a category name changes in `schemas.py` and this dict is not updated, `context.py` raises at import.

## Multi-select semantics

**Weights are summed across all selected chips, capped at 3.0.** From `_merge_weights` in `context.py`:

```python
def _merge_weights(context: list[ContextChip]) -> dict[str, float]:
    if not context:
        return {}
    merged: dict[str, float] = {}
    for chip in context:
        for cat, w in CATEGORY_WEIGHTS.get(chip, {}).items():
            merged[cat] = min(merged.get(cat, 0.0) + w, 3.0)
    return merged
```

Example: reader selects `for_child` AND `for_care`.
- `Dark Patterns` = 2.0 (child) + 3.0 (care) = **3.0** (capped)
- `Data Sale / Sharing` = 2.0 (child) + 2.0 (care) = **3.0** (capped)
- `Children's Privacy` = 3.0 (child) + 0 (care) = **3.0**
- `Health Data` = 0 (child) + 2.5 (care) = **2.5**

The cap prevents multi-select from producing weights that dominate every other consideration. It also means the reader can't game the system by picking every chip — the effective ordering degrades to "everything is important" and IRP takes over.

## Sort key (tier-first)

From `apply_category_weights` in `context.py`:

```python
def sort_key(f: Finding) -> tuple[float, float, int]:
    weight = merged.get(f.category, 1.0)
    irp = f.irp_score if f.irp_score is not None else _severity_fallback(f.severity)
    return (weight, irp, _SEVERITY_RANK.get(f.severity, 0))

return sorted(findings, key=sort_key, reverse=True)
```

**All three dimensions descending.** Sort is **tier-first**:
1. **Category weight leads.** A category weighted 3.0 for the reader's context always outranks a category weighted 2.0, regardless of IRP or severity. This is the entire point — the reader told the tool what mattered to them, and the tool honors that as the top-priority dimension.
2. **IRP breaks ties within a weight tier.** Among two `for_child`-tagged Children's Privacy findings, the higher-IRP one surfaces first.
3. **Severity rank is the final tie-breaker.** Rare, but disambiguates when both weight and IRP are equal.

Baseline chips (`want_understand`, `just_curious`) collapse all categories to weight 1.0, so IRP drives the entire sort.

`_severity_fallback` provides an IRP approximation for legacy findings without `irp_score`: `{"Critical": 0.9, "High": 0.75, "Medium": 0.5, "Low": 0.25}`.

Category-not-found defaults to weight `1.0` — an unweighted category is baseline, not zero. Zero would exile it below every weighted item, which is wrong for `just_curious`-style baseline chips.

## Verdict headline templates

`VERDICT_HEADLINE` in `context.py`, keyed by `(context_chip, action_readiness)`. Copy is intentionally observational and tentative — see LIB-VOICE for the rules that generated this copy.

| Chip | Go | Review | Stop |
|------|----|--------|------|
| `want_understand` | This policy is clearer than most. | A few things here may be worth understanding before agreement. | Multiple parts of this policy may work against the reader's privacy. |
| `for_child` | For a child, this policy is clearer than most. | For a child, a few things here may be worth understanding first. | This service may not be built with children in mind. |
| `for_care` | This policy is clearer than most for someone being helped. | A few things here may be worth explaining to the person being helped. | Some parts of this policy could take advantage of someone unfamiliar with online agreements. |
| `for_work` | For work use, this policy holds up better than most. | For work use, a few clauses here deserve a second look before sign-off. | For work use, several clauses here could put the business on the hook. |
| `just_curious` | This policy is relatively clear. | There are a few things worth noting here. | This policy has several notable practices. |

## Verdict chip labels

`VERDICT_LABEL` in `context.py`. Short, actionable, never grades. The design decision was that labels should tell the reader **what to do next**, not what letter grade the policy earned. See LIB-VOICE §"Verdict labels are actionable" for the rationale.

| Chip | Go | Review | Stop |
|------|----|--------|------|
| `want_understand` | Reasonable | Worth a closer read | Serious concerns |
| `for_child` | Reasonable for a child | Worth a closer read for a child | Not built for children |
| `for_care` | Reasonable to share | Worth reviewing together | Concerning to share |
| `for_work` | Workable | Worth a legal pass | Not vendor-safe as written |
| `just_curious` | Clear | Worth noting | Notable practices |

## Public API of `services/context.py`

- `resolve_context(context: list[ContextChip]) -> ContextChip` — picks the strongest chip from a multi-select using `_CHIP_PRIORITY`. Returns `want_understand` if the list is empty (default intake framing).
- `apply_category_weights(findings: list[Finding], context: list[ContextChip]) -> list[Finding]` — returns a re-sorted list, **does not mutate** the findings' `irp_score`.
- `verdict_headline(context: list[ContextChip], action_readiness: str) -> str` — the long verdict sentence.
- `verdict_label(context: list[ContextChip], action_readiness: str) -> str` — the short chip label.

## Import-time drift guard

`CATEGORY_WEIGHTS` keys are validated against `schemas.CATEGORIES` at module load:

```python
_unknown_weight_keys = {
    cat
    for chip_weights in CATEGORY_WEIGHTS.values()
    for cat in chip_weights.keys()
    if cat not in CATEGORIES
}
if _unknown_weight_keys:
    raise RuntimeError(
        f"CATEGORY_WEIGHTS references unknown categories: "
        f"{sorted(_unknown_weight_keys)}. Update schemas.CATEGORIES."
    )
```

If a category is renamed in `schemas.py` and this file isn't updated, the backend refuses to start. Same guard exists in `analyzer.py` for its category-keyed dicts. See `.claude/rules/testing.md` §Rule 1 for the general pattern.

## Deferred / open

- `for_compliance_review` and `already_agreed` chips were considered but deferred pending usage data on the five shipped chips (see `docs/wireframes/issue-19-design-decisions.md`).
- Backend LLM top-things generation is currently derived client-side from `finding.explanation` in `app_streamlit_v2.py`. Backend-driven generation is a follow-up.
