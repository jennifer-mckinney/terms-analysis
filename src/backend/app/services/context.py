"""Context-chip tuning for analyzer results.

Phase 1 backend for the Streamlit v2 redesign (issue #19). The intake exposes
five context chips capturing the reader's stated intent:

  - ``want_understand`` — "I want to understand what I'm agreeing to"
  - ``for_child``       — "Something my child wants to use"
  - ``for_care``        — "Helping someone I care about with this"
  - ``for_work``        — "For work / business use"
  - ``just_curious``    — "Just curious"

Selecting one or more chips tunes two things:

  1. **Surfacing order** — findings whose categories matter more in that
     context are boosted so they appear first (does not mutate ``irp_score``).
     Sort is **tier-first**: category weight leads, IRP breaks ties within
     tier, severity is the final tie-breaker.
  2. **Verdict copy** — the Go/Review/Stop verdict headline and chip label are
     rewritten in the reader's language.

When more than one chip is selected, ``resolve_context`` picks the strongest
(``for_child`` > ``for_care`` > ``for_work`` > ``want_understand`` >
``just_curious``) for verdict copy, while ``apply_category_weights`` sums
weights across all selected chips (capped at 3.0) so multiple contexts can
compound their surfacing bias.
"""

from __future__ import annotations

from ..schemas import CATEGORIES, ContextChip, Finding


# Weight tier scale: 1.0 baseline · 2.0 boosted · 2.5 priority · 3.0 signature
# Category weights per context chip. Keys are matched exactly against
# ``finding.category``; multi-context selections are merged via
# ``_merge_weights`` (sum, capped at 3.0). Weights only affect surfacing
# order — they never mutate the finding's ``irp_score``.
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


# Verdict headline templates per context, keyed by action_readiness.
VERDICT_HEADLINE: dict[ContextChip, dict[str, str]] = {
    "want_understand": {
        "Go": "This policy is clearer than most.",
        "Review": "A few things here may be worth understanding before agreement.",
        "Stop": "Multiple parts of this policy may work against the reader's privacy.",
    },
    "for_child": {
        "Go": "For a child, this policy is clearer than most.",
        "Review": "For a child, a few things here may be worth understanding first.",
        "Stop": "This service may not be built with children in mind.",
    },
    "for_care": {
        "Go": "This policy is clearer than most for someone being helped.",
        "Review": "A few things here may be worth explaining to the person being helped.",
        "Stop": "Some parts of this policy could take advantage of someone unfamiliar with online agreements.",
    },
    "for_work": {
        "Go": "For work use, this policy holds up better than most.",
        "Review": "For work use, a few clauses here deserve a second look before sign-off.",
        "Stop": "For work use, several clauses here could put the business on the hook.",
    },
    "just_curious": {
        "Go": "This policy is relatively clear.",
        "Review": "There are a few things worth noting here.",
        "Stop": "This policy has several notable practices.",
    },
}


# Short verdict chip label per context.
VERDICT_LABEL: dict[ContextChip, dict[str, str]] = {
    "want_understand": {"Go": "Reasonable", "Review": "Worth a closer read", "Stop": "Serious concerns"},
    "for_child": {"Go": "Reasonable for a child", "Review": "Worth a closer read for a child", "Stop": "Not built for children"},
    "for_care": {"Go": "Reasonable to share", "Review": "Worth reviewing together", "Stop": "Concerning to share"},
    "for_work": {"Go": "Workable", "Review": "Worth a legal pass", "Stop": "Not vendor-safe as written"},
    "just_curious": {"Go": "Clear", "Review": "Worth noting", "Stop": "Notable practices"},
}


# Validate that every category we weight is a known category. This fails loudly
# at import time if ``CATEGORY_WEIGHTS`` drifts from the canonical taxonomy in
# ``schemas.CATEGORIES`` (Fix 5, string-coupling guard).
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


# Priority order when the user selects multiple chips (verdict copy only).
_CHIP_PRIORITY: list[ContextChip] = [
    "for_child",
    "for_care",
    "for_work",
    "want_understand",
    "just_curious",
]

# Numeric ranking used as a final tie-breaker in the sort key.
_SEVERITY_RANK: dict[str, int] = {"Low": 1, "Medium": 2, "High": 3, "Critical": 4}


def resolve_context(context: list[ContextChip]) -> ContextChip:
    """Pick the strongest context if multiple are selected (verdict copy only).

    Priority: ``for_child`` > ``for_care`` > ``for_work`` > ``want_understand``
    > ``just_curious``. Returns ``want_understand`` if no chips are provided,
    matching the intake's default framing ("I want to understand...").

    Note: this is used only for verdict copy selection. Surfacing order in
    ``apply_category_weights`` sums weights across ALL selected chips (with a
    3.0 cap), so multi-select compounds the bias rather than picking one.
    """
    if not context:
        return "want_understand"
    for chip in _CHIP_PRIORITY:
        if chip in context:
            return chip
    return "want_understand"


def _merge_weights(context: list[ContextChip]) -> dict[str, float]:
    """Sum weights across selected chips, capped at 3.0. Baseline categories stay at 1.0."""
    if not context:
        return {}
    merged: dict[str, float] = {}
    for chip in context:
        for cat, w in CATEGORY_WEIGHTS.get(chip, {}).items():
            merged[cat] = min(merged.get(cat, 0.0) + w, 3.0)
    return merged


def _severity_fallback(severity: str) -> float:
    """Approximate IRP from severity when irp_score is missing."""
    return {"Critical": 0.9, "High": 0.75, "Medium": 0.5, "Low": 0.25}.get(severity, 0.5)


def apply_category_weights(
    findings: list[Finding], context: list[ContextChip]
) -> list[Finding]:
    """Return findings sorted so context weight tier leads.

    IRP breaks ties within tier, severity as final tie-breaker. Does NOT
    mutate the findings themselves — only affects surfacing order.

    Sort key: ``(weight, irp, severity_rank)`` all descending. This makes the
    sort tier-first — a category with a higher weight always outranks a
    category with a lower weight, regardless of IRP or severity. When no
    context is supplied (or only baseline chips), all categories collapse to
    weight 1.0 and IRP drives the order.
    """
    if not findings:
        return list(findings)
    merged = _merge_weights(context or [])

    def sort_key(f: Finding) -> tuple[float, float, int]:
        weight = merged.get(f.category, 1.0)
        irp = f.irp_score if f.irp_score is not None else _severity_fallback(f.severity)
        return (weight, irp, _SEVERITY_RANK.get(f.severity, 0))

    return sorted(findings, key=sort_key, reverse=True)


def verdict_headline(context: list[ContextChip], action_readiness: str) -> str:
    """Return a context-appropriate verdict sentence for the reader."""
    chip = resolve_context(context)
    table = VERDICT_HEADLINE.get(chip, VERDICT_HEADLINE["want_understand"])
    return table.get(action_readiness, table.get("Review", ""))


def verdict_label(context: list[ContextChip], action_readiness: str) -> str:
    """Return a short context-appropriate verdict chip label."""
    chip = resolve_context(context)
    table = VERDICT_LABEL.get(chip, VERDICT_LABEL["want_understand"])
    return table.get(action_readiness, table.get("Review", ""))
