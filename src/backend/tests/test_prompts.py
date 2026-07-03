from __future__ import annotations

from app.services.prompts import build_user_prompt


def test_build_user_prompt_includes_legal_context():
    context = [{"text": "Right to erasure text.", "jurisdiction": "EU", "section": "Article 17"}]
    prompt = build_user_prompt(
        numbered_text="0001| We sell your data.",
        jurisdictions=["GDPR"],
        rule_findings=[],
        legal_context=context,
    )
    assert "Article 17" in prompt
    assert "erasure" in prompt.lower()


def test_build_user_prompt_no_legal_context_still_works():
    prompt = build_user_prompt(
        numbered_text="0001| We sell your data.",
        jurisdictions=["US-CA"],
        rule_findings=[],
        legal_context=None,
    )
    assert "Analyze the document" in prompt
    assert "Relevant legal requirements" not in prompt


def test_build_user_prompt_empty_legal_context_list_omits_section():
    prompt = build_user_prompt(
        numbered_text="0001| We sell your data.",
        jurisdictions=["US-CA"],
        rule_findings=[],
        legal_context=[],
    )
    assert "Relevant legal requirements" not in prompt
