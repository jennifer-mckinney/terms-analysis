"""Reader-facing copy for every ``schemas.LLMStatus`` value (issue #368).

This module is the single source of the label text. Every ``AnalysisPayload``
carries ``llm_status_label``, built here (#372), and the PDF export renders
``llm_status_label(token)``; the CSV export and ``/reviews`` carry the token
itself. No other module restates a label (``test_no_consumer_restates_a_label``).
The v2 UI never loads this module: it renders the ``llm_status_label`` field of
the API response (owner ruling 2026-10-14, "the front end needs to read from
the backend").

It imports the standard library only, so ``schemas`` can import it without a
cycle. The keys below therefore mirror ``schemas.LLMStatus`` instead of
importing it; ``test_every_member_except_unknown_is_known`` fails if a member
is added there without copy here.

Copy follows LIB-VOICE V2 (no you/we/us/our/your) and V6 (no em-dash).
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

# Prefix of every rules-only label: each fallback (HR5, reduced confidence)
# and quick mode, where the LLM never runs. Never part of the success or the
# unknown label (an old row may have had an LLM answer).
RULES_ONLY_MARKER = "Rules-only findings, reduced confidence"

_UNKNOWN = "unknown"

_LABELS: Mapping[str, str] = MappingProxyType(
    {
        "ok": "AI review completed: findings combine rules and the AI model.",
        "fallback_llm_unreachable": f"{RULES_ONLY_MARKER}: the AI model could not be reached.",
        "fallback_llm_upstream": f"{RULES_ONLY_MARKER}: the AI model service returned a server error.",
        "fallback_llm_rate_limited": f"{RULES_ONLY_MARKER}: the AI model service was over capacity.",
        "fallback_llm_invalid": f"{RULES_ONLY_MARKER}: the answer from the AI model failed validation.",
        "fallback_llm_error": f"{RULES_ONLY_MARKER}: the AI review step failed.",
        "disabled": f"{RULES_ONLY_MARKER}: quick mode skips the AI review.",
        _UNKNOWN: "AI review status unknown: this result does not record whether the AI model ran.",
    }
)


def llm_status_label(value: object) -> str:
    """Return the label for a status token; anything else reads as unknown.

    Total and fail closed: only an exact key matches (no case folding, no
    stripping); the ``str`` check keeps unhashable values (lists, dicts) out
    of the lookup. So a missing, forged, look-alike or non-string
    value can never borrow the success label or echo raw bytes into a sink.
    """
    if isinstance(value, str) and value in _LABELS:
        return _LABELS[value]
    return _LABELS[_UNKNOWN]
