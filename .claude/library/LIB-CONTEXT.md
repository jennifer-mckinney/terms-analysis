# LIB-CONTEXT — context chip taxonomy, weight tiers, sort semantics, verdict copy
loads: on-trigger
scope: project
xref: [[LIB-VOICE]] [[LIB-RULES#IRP]] [[LIB-PRINCIPLES#P6]] [[docs/wireframes/issue-19-design-decisions.md]]

status: shipped PR #34 (issue #19 redesign). ground truth for `services/context.py` + `src/webapp/app_streamlit_v2.py`.

## chips

Copy verbatim from `CONTEXT_CHIPS` in `src/webapp/app_streamlit_v2.py`. `value` = stable backend id; `label` = chip text; `sub` = italic help under label.

| value | label | italic sub-line |
|-------|-------|-----------------|
| `want_understand` | I want to understand what I am agreeing to | *Nice to know before you tap "I agree." No judgment if you already did.* |
| `for_child` | Something my child wants to use | *Games, apps, social platforms. We will help you see what matters.* |
| `for_care` | Helping someone I care about with this | *A family member, extended family, and/or a friend.* |
| `for_work` | For work or a vendor pick | *A tool the team might use, or an agreement to sign.* |
| `just_curious` | Just curious | *Sometimes it is good to just know. No pressure either way.* |

### CTX1: chips-are-canonical-Literal
rule: chips are the canonical `ContextChip` Literal in `src/backend/app/schemas.py`; `main.py::_VALID_CHIPS` derived at module load via `frozenset(get_args(ContextChip))`
because: drift fails at import

## priority-order

```python
_CHIP_PRIORITY: list[ContextChip] = [
    "for_child",
    "for_care",
    "for_work",
    "want_understand",
    "just_curious",
]
```

### CTX2: personal-stakes-win-headline
rule: personal-stakes lenses win the verdict headline over professional lenses
apply: when multi-select includes both `for_child` and `for_work`, child lens frames the verdict
because: parent checking on behalf of child at work → child harm horizon more consequential; reader can deselect the child chip if disagreement
scope: controls verdict copy ONLY (headline + label); does NOT control surfacing order (surfacing sums weights, see CTX5)

## weight-tier-scale

| Tier | Weight | Semantics |
|------|--------|-----------|
| Baseline | 1.0 | Category not specifically privileged for this chip. IRP drives its order. |
| Boosted | 2.0 | Category is meaningful in this context; surfaces above IRP-equal baseline items. |
| Priority | 2.5 | Top handful for this context. |
| Signature | 3.0 | Defining risk for this context. Always surfaces first if present. |

### CTX3: for_work-sub-tier-weights
rule: `for_work` uses intermediate rungs (2.2, 2.4, 2.6, 2.8) not in base scale
detail: Liability 3.0, Unilateral Changes 2.8, Data Security 2.6, Breach Notification 2.5, Cross-Border Transfer 2.4, ADM 2.2
because: only chip that needs finer vendor-review differentiation

## category-weights

Dumped verbatim from `services/context.py` — authoritative.

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

### CTX4: baseline-chips-are-empty
rule: `want_understand` and `just_curious` weight maps MUST be empty
because: reader expressed no specific lens; collapse to IRP-driven order

### CTX5: category-weight-drift-guard
rule: every key in `CATEGORY_WEIGHTS` MUST be validated against `schemas.CATEGORIES` at module load
enforcement: raises at import if unknown key; drift fails before serve
xref: [[LIB-RULES#category-taxonomy]]

## multi-select

### CTX6: sum-and-cap
rule: weights sum across selected chips, capped at 3.0

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

example: `for_child` + `for_care` → Dark Patterns = 2.0 + 3.0 = **3.0 (capped)**; Data Sale/Sharing = 2.0 + 2.0 = **3.0 (capped)**; Children's Privacy = 3.0 + 0 = **3.0**; Health Data = 0 + 2.5 = **2.5**
because: cap prevents multi-select from dominating; picking every chip degrades to "everything important" → IRP takes over

## sort-key

### CTX7: tier-first-sort
rule: sort key is `(weight, irp_score, severity_rank)`, all descending

```python
def sort_key(f: Finding) -> tuple[float, float, int]:
    weight = merged.get(f.category, 1.0)
    irp = f.irp_score if f.irp_score is not None else _severity_fallback(f.severity)
    return (weight, irp, _SEVERITY_RANK.get(f.severity, 0))

return sorted(findings, key=sort_key, reverse=True)
```

order:
1. context weight leads — 3.0-weighted category always outranks 2.0, regardless of IRP or severity
2. IRP breaks ties within a weight tier
3. severity rank is final tie-breaker

baseline_chips: `want_understand`, `just_curious` collapse all categories to 1.0 → IRP drives entire sort

### CTX8: severity-fallback-for-legacy
rule: legacy findings without `irp_score` use `_severity_fallback`: `{"Critical": 0.9, "High": 0.75, "Medium": 0.5, "Low": 0.25}`

### CTX9: category-not-found-default
rule: category-not-found defaults to weight `1.0`, NOT zero
because: unweighted category is baseline; zero would exile below every weighted item — wrong for `just_curious`-style baselines

## verdict-headlines

`VERDICT_HEADLINE` in `context.py`, keyed by `(context_chip, action_readiness)`. Observational + tentative — see LIB-VOICE for rules.

| Chip | Go | Review | Stop |
|------|----|--------|------|
| `want_understand` | This policy is clearer than most. | A few things here may be worth understanding before agreement. | Multiple parts of this policy may work against the reader's privacy. |
| `for_child` | For a child, this policy is clearer than most. | For a child, a few things here may be worth understanding first. | This service may not be built with children in mind. |
| `for_care` | This policy is clearer than most for someone being helped. | A few things here may be worth explaining to the person being helped. | Some parts of this policy could take advantage of someone unfamiliar with online agreements. |
| `for_work` | For work use, this policy holds up better than most. | For work use, a few clauses here deserve a second look before sign-off. | For work use, several clauses here could put the business on the hook. |
| `just_curious` | This policy is relatively clear. | There are a few things worth noting here. | This policy has several notable practices. |

## verdict-labels

`VERDICT_LABEL` in `context.py`. Short, actionable, never grades. See LIB-VOICE §V9.

| Chip | Go | Review | Stop |
|------|----|--------|------|
| `want_understand` | Reasonable | Worth a closer read | Serious concerns |
| `for_child` | Reasonable for a child | Worth a closer read for a child | Not built for children |
| `for_care` | Reasonable to share | Worth reviewing together | Concerning to share |
| `for_work` | Workable | Worth a legal pass | Not vendor-safe as written |
| `just_curious` | Clear | Worth noting | Notable practices |

## public-api

| Function | Purpose |
|----------|---------|
| `resolve_context(context: list[ContextChip]) -> ContextChip` | picks strongest chip from multi-select via `_CHIP_PRIORITY`; returns `want_understand` if empty |
| `apply_category_weights(findings, context) -> list[Finding]` | returns re-sorted list; does NOT mutate `irp_score` |
| `verdict_headline(context, action_readiness) -> str` | long verdict sentence |
| `verdict_label(context, action_readiness) -> str` | short chip label |

## import-time-drift-guard

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

### CTX10: same-guard-in-analyzer
rule: `analyzer.py` has the same import-time guard for its category-keyed dicts
xref: [[.claude/rules/testing.md#R1]]

## deferred

### CTX11: chips-under-consideration
rule: `for_compliance_review` and `already_agreed` deferred pending usage data on the shipped 5
xref: [[docs/wireframes/issue-19-design-decisions.md]]

### CTX12: backend-top-things-followup
rule: backend LLM top-things generation currently derived client-side from `finding.explanation` in `app_streamlit_v2.py`; backend-driven generation is a follow-up
