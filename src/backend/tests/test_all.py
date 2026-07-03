from __future__ import annotations

import csv
from datetime import datetime, timezone
from io import StringIO
from types import SimpleNamespace
from typing import get_args
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.config import settings
from app.models import Analysis as AnalysisModel
from app.schemas import (
    AnalysisPayload,
    AnalyzeRequest,
    Jurisdiction,
    WatchlistItemPayload,
)
from app.services import localai
from app.services.analyzer import AnalysisResult
from app.services.embedding import chunk_text, rrf_fuse
from app.services.ingest import _validate_url
from app.services.rules import detect_findings


def _fake_analysis_result(
    *,
    name: str | None,
    document_text: str,
    doc_type: str | None = None,
    source_url: str | None = None,
) -> AnalysisResult:
    payload = AnalysisPayload(
        id=str(uuid4()),
        name=name,
        doc_type=doc_type,
        source_url=source_url,
        document_text=document_text,
        line_offsets=[0],
        status="completed",
        review_required=False,
        confidence=0.95,
        risk_score=1.0,
        grade="A",
        created_at=datetime.now(timezone.utc),
        findings=[],
        summary="Mocked analysis",
    )
    return AnalysisResult(payload=payload, issues=[])


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/evil",
        "http://10.0.0.1/evil",
        "http://192.168.1.1/evil",
        "http://172.16.0.1/evil",
        "http://169.254.169.254/metadata",
        "file:///etc/passwd",
        "ftp://example.com",
    ],
)
def test_validate_url_blocks_ssrf_targets(url):
    with pytest.raises(ValueError):
        _validate_url(url)


def test_validate_url_allows_public_https(monkeypatch):
    from app.services import ingest

    monkeypatch.setattr(
        ingest.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(2, 1, 6, "", ("93.184.216.34", 0))],
    )
    _validate_url("https://example.com/terms")


def test_analyze_url_private_ip_returns_400(app_client):
    response = app_client.post(
        "/analyze/url",
        json={"url": "http://127.0.0.1/evil", "jurisdictions": ["US-CA", "GDPR"]},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "URL is not allowed"


def test_analyze_file_rejects_oversized_upload(app_client):
    original = settings.max_upload_bytes
    object.__setattr__(settings, "max_upload_bytes", 16)
    try:
        response = app_client.post(
            "/analyze/file",
            files={"file": ("large.txt", b"x" * 17, "text/plain")},
        )
    finally:
        object.__setattr__(settings, "max_upload_bytes", original)

    assert response.status_code == 413
    assert response.json()["detail"] == "File exceeds maximum upload size"


def test_analyze_file_accepts_small_valid_upload(
    app_client, monkeypatch, sample_privacy_policy_text
):
    captured = {}

    async def fake_analyze(text, jurisdictions, name=None, doc_type=None, industry=None, source_url=None, mode=None, **kwargs):
        captured.update(
            {
                "text": text,
                "jurisdictions": jurisdictions,
                "name": name,
                "doc_type": doc_type,
                "industry": industry,
                "source_url": source_url,
            }
        )
        return _fake_analysis_result(
            name=name,
            doc_type=doc_type,
            source_url=source_url,
            document_text=text,
        )

    monkeypatch.setattr("app.main.analyze_text", fake_analyze)

    response = app_client.post(
        "/analyze/file",
        files={"file": ("policy.txt", sample_privacy_policy_text.encode(), "text/plain")},
        data={"jurisdictions": "US-CA,GDPR", "doc_type": "Privacy Policy"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert captured["text"] == sample_privacy_policy_text
    assert captured["jurisdictions"] == ["US-CA", "GDPR"]
    assert captured["name"] == "policy.txt"
    assert captured["doc_type"] == "Privacy Policy"


def test_health_endpoint_returns_only_status(app_client):
    response = app_client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ok"}
    assert "model_world" not in body
    assert "model_eu" not in body
    assert "review_threshold" not in body
    assert "database_url" not in body
    assert "lm_studio_base_url" not in body


def test_export_analyses_csv_quotes_commas_and_newlines(app_client, db_session):
    now = datetime.now(timezone.utc)
    rows = [
        AnalysisModel(
            id="analysis-1",
            doc_name="Evil, Inc.",
            doc_type="vendor",
            source_url="https://example.com/one",
            source_type="file",
            source_value="one.txt",
            status="completed",
            confidence=0.91,
            risk_score=2.5,
            grade="A",
            document_text="text",
            result_json="{}",
            created_at=now,
        ),
        AnalysisModel(
            id="analysis-2",
            doc_name="Bad\nActor LLC",
            doc_type="vendor",
            source_url="https://example.com/two",
            source_type="file",
            source_value="two.txt",
            status="completed",
            confidence=0.75,
            risk_score=5.5,
            grade="B-",
            document_text="text",
            result_json="{}",
            created_at=now,
        ),
    ]
    db_session.add_all(rows)
    db_session.commit()

    response = app_client.get("/exports/analyses.csv")

    assert response.status_code == 200
    parsed = list(csv.reader(StringIO(response.text)))
    assert parsed[0] == [
        "id",
        "name",
        "doc_type",
        "source_url",
        "status",
        "confidence",
        "risk_score",
        "grade",
        "created_at",
    ]
    assert any(row[1] == "Evil, Inc." for row in parsed[1:])
    assert any(row[1] == "Bad\nActor LLC" for row in parsed[1:])
    assert '"Evil, Inc."' in response.text
    assert '"Bad\nActor LLC"' in response.text
    assert all(len(row) == 9 for row in parsed)


def test_export_pdf_route_is_not_shadowed_by_json_export_route(app_client, db_session):
    # Regression test: /exports/analysis/{id}.pdf was previously shadowed by
    # /exports/analysis/{id} (registered earlier), since {analysis_id} greedily
    # matches "<id>.pdf" too — both frontends' PDF export silently hit the JSON
    # route and got a 404 (found by independent UI/UX review).
    db_session.add(
        AnalysisModel(
            id="pdf-route-test",
            doc_name="PDF Route Test",
            doc_type="Privacy Policy",
            source_type="text",
            status="completed",
            confidence=0.9,
            risk_score=5.0,
            grade="B",
            document_text="text",
            result_json='{"findings": []}',
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()

    pdf_response = app_client.get("/exports/analysis/pdf-route-test.pdf")
    assert pdf_response.status_code == 200
    assert pdf_response.headers["content-type"] == "application/pdf"

    json_response = app_client.get("/exports/analysis/pdf-route-test")
    assert json_response.status_code == 200
    assert json_response.headers["content-type"].startswith("application/json")


def test_user_rights_generic_access_does_not_trigger():
    findings = detect_findings("Users can access services through the dashboard.", ["GDPR"])
    assert "User Rights" not in {finding.category for finding in findings}


@pytest.mark.parametrize(
    "text",
    [
        "You have the right to access your personal data.",
        "You have the right to delete your personal data.",
        "You have the right to erasure under applicable law.",
    ],
)
def test_user_rights_specific_phrases_do_trigger(text):
    findings = detect_findings(text, ["GDPR"])
    assert "User Rights" in {finding.category for finding in findings}


def test_global_jurisdiction_rules_fire_only_when_requested():
    assert "LGPD Rights" in {
        finding.category for finding in detect_findings("This notice references LGPD.", ["LGPD"])
    }
    assert "DPDP Consent" in {
        finding.category
        for finding in detect_findings("A data fiduciary must protect personal data.", ["DPDP"])
    }
    assert "DPDP Consent" in {
        finding.category
        for finding in detect_findings("The DPDP applies to this service.", ["DPDP"])
    }
    assert "Privacy as Human Right" in {
        finding.category
        for finding in detect_findings("Everyone has a right to privacy.", ["ICCPR-17"])
    }
    assert "ADM" not in {
        finding.category
        for finding in detect_findings("Automated decision-making is used.", ["LGPD"])
    }


def test_jurisdiction_literal_includes_expected_values():
    values = set(get_args(Jurisdiction))
    assert {"DPDP", "PIPA", "NDPR", "COE-108"}.issubset(values)


def test_default_jurisdiction_list_is_valid():
    request = AnalyzeRequest(text="policy text")
    assert request.jurisdictions == ["US-CA", "GDPR"]


@pytest.mark.parametrize(
    ("detected_language", "expected_model"),
    [("fr", "eu-model"), ("sw", "world-model"), (None, "world-model")],
)
def test_select_model_routes_by_language(monkeypatch, detected_language, expected_model):
    monkeypatch.setattr(
        localai,
        "settings",
        SimpleNamespace(
            language_detection_enabled=True,
            model_eu="eu-model",
            model_world="world-model",
            eu_language_codes=["fr", "en", "de"],
        ),
    )
    monkeypatch.setattr(localai, "_detect_language", lambda _text: detected_language)
    assert localai._select_model("sample text") == expected_model


def test_select_model_ignores_detection_when_disabled(monkeypatch):
    monkeypatch.setattr(
        localai,
        "settings",
        SimpleNamespace(
            language_detection_enabled=False,
            model_eu="eu-model",
            model_world="world-model",
            eu_language_codes=["fr"],
        ),
    )
    monkeypatch.setattr(localai, "_detect_language", lambda _text: "fr")
    assert localai._select_model("bonjour") == "world-model"


def test_rrf_fuse_single_ranker_scores():
    scores = rrf_fuse([[1.0, 0.5, 0.0]], k=60)
    assert scores == pytest.approx([1 / 61, 1 / 62, 1 / 63])


def test_rrf_fuse_combines_multiple_rankers():
    scores = rrf_fuse([[1.0, 0.0, 0.5], [0.0, 1.0, 0.5]], k=60)
    assert scores == pytest.approx(
        [
            (1 / 61) + (1 / 63),
            (1 / 63) + (1 / 61),
            (1 / 62) + (1 / 62),
        ]
    )


def test_chunk_text_short_text_returns_single_chunk():
    text = "short policy text"
    assert chunk_text(text, chunk_size=100, overlap=10) == [(0, text)]


def test_chunk_text_long_text_returns_multiple_overlapping_chunks():
    text = "aaaaa\nbbbbb\nccccc\nddddd\neeeee\n"
    chunks = chunk_text(text, chunk_size=14, overlap=8)

    assert len(chunks) > 1
    assert chunks[0][0] == 0
    assert chunks[1][0] < len(chunks[0][1])
    assert chunks[1][1].startswith("bbbbb\n")
    assert all(chunk_text_value for _, chunk_text_value in chunks)


def test_watchlist_item_payload_accepts_none_risk_delta():
    payload = WatchlistItemPayload(
        id="1",
        vendor="Vendor",
        status="No Changes",
        last_checked=datetime.now(timezone.utc),
        change_count=0,
        risk_delta=None,
    )
    assert payload.risk_delta is None


def test_watchlist_item_payload_accepts_float_risk_delta():
    payload = WatchlistItemPayload(
        id="1",
        vendor="Vendor",
        status="Updated",
        last_checked=datetime.now(timezone.utc),
        change_count=1,
        risk_delta=1.5,
    )
    assert payload.risk_delta == 1.5


def test_watchlist_item_payload_rejects_string_risk_delta():
    with pytest.raises(ValidationError):
        WatchlistItemPayload(
            id="1",
            vendor="Vendor",
            status="Updated",
            last_checked=datetime.now(timezone.utc),
            change_count=1,
            risk_delta="0",
        )


# ── New jurisdiction & AI law tests ──────────────────────────


def get_findings_for_text(text: str, jurisdictions: list[Jurisdiction]):
    return detect_findings(text, jurisdictions)


def test_coppa_triggers_on_children_under_13_text():
    findings = get_findings_for_text(
        "We collect data from children under 13 with verifiable parental consent",
        ["US-FED"],
    )
    assert "Children's Privacy" in {finding.category for finding in findings}


def test_coppa_triggers_on_coppa_keyword():
    findings = get_findings_for_text("This service is COPPA compliant", ["US-FED"])
    assert "Children's Privacy" in {finding.category for finding in findings}


def test_hipaa_triggers_on_phi_text():
    findings = get_findings_for_text(
        "We process protected health information as a covered entity",
        ["US-FED"],
    )
    assert "Health Data" in {finding.category for finding in findings}


def test_hipaa_triggers_on_hipaa_keyword():
    findings = get_findings_for_text(
        "A HIPAA Business Associate Agreement is required",
        ["US-FED"],
    )
    assert "Health Data" in {finding.category for finding in findings}


def test_glba_triggers_on_financial_information():
    findings = get_findings_for_text(
        "We share non-public personal financial information with affiliates",
        ["US-FED"],
    )
    assert "Financial Data" in {finding.category for finding in findings}


def test_ftc_triggers_on_contradictory_sharing_claim():
    findings = get_findings_for_text(
        "We never sell your data to third parties",
        ["US-FED"],
    )
    assert "Deceptive Practices" in {finding.category for finding in findings}


def test_canspam_triggers_on_commercial_email():
    findings = get_findings_for_text(
        "You can opt out of our promotional email communications at any time",
        ["US-FED"],
    )
    assert "Marketing Communications" in {finding.category for finding in findings}


def test_us_fed_rules_do_not_fire_for_gdpr_only():
    findings = get_findings_for_text(
        "This service is COPPA compliant and a HIPAA Business Associate Agreement is required",
        ["GDPR"],
    )
    assert findings == []


def test_bipa_triggers_on_biometric_identifier():
    findings = get_findings_for_text(
        "We collect facial geometry and fingerprint data for authentication",
        ["US-IL"],
    )
    assert "Biometric Data" in {finding.category for finding in findings}


def test_tdpsa_triggers_on_sensitive_data_and_data_broker():
    findings = get_findings_for_text(
        "We act as a data broker processing sensitive personal data",
        ["US-TX"],
    )
    assert "Sensitive Data / Opt-Out" in {finding.category for finding in findings}


def test_vcdpa_opt_out_triggers():
    findings = get_findings_for_text(
        "You have the right to opt-out of the sale of personal data and targeted advertising",
        ["US-VA"],
    )
    assert "User Rights" in {finding.category for finding in findings}


def test_ny_shield_triggers_on_private_information():
    findings = get_findings_for_text(
        "We maintain reasonable administrative and technical safeguards for private information",
        ["US-NY"],
    )
    assert "Data Security" in {finding.category for finding in findings}


def test_ny_shield_triggers_on_shield_act_keyword():
    findings = get_findings_for_text(
        "This policy complies with the New York SHIELD Act",
        ["US-NY"],
    )
    assert "Data Security" in {finding.category for finding in findings}


def test_eu_ai_act_high_risk_triggers():
    findings = get_findings_for_text(
        "Our high-risk AI system is used in employment screening",
        ["EU-AI-ACT"],
    )
    assert "High-Risk AI" in {finding.category for finding in findings}


def test_automated_decision_making_triggers():
    findings = get_findings_for_text(
        "Decisions are made by automated processing with no human review",
        ["EU-AI-ACT"],
    )
    assert "Automated Decision-Making" in {finding.category for finding in findings}


def test_ai_training_on_user_data_triggers():
    findings = get_findings_for_text(
        "We may use your content to train our AI models",
        ["EU-AI-ACT"],
    )
    assert "AI Training" in {finding.category for finding in findings}


def test_ai_generated_content_triggers():
    findings = get_findings_for_text(
        "Some responses are AI-generated and may not reflect human review",
        ["EU-AI-ACT"],
    )
    assert "AI-Generated Content" in {finding.category for finding in findings}


def test_gpai_foundation_model_triggers():
    findings = get_findings_for_text(
        "Our service is powered by a large language model",
        ["EU-AI-ACT"],
    )
    assert "GPAI / Generative AI" in {finding.category for finding in findings}


def test_ai_training_opt_out_triggers():
    findings = get_findings_for_text(
        "You may opt out of AI training using your data",
        ["EU-AI-ACT"],
    )
    assert "AI Training Opt-Out" in {finding.category for finding in findings}


def test_algorithmic_transparency_triggers():
    findings = get_findings_for_text(
        "Users have the right to an explanation of any algorithmic decision",
        ["EU-AI-ACT"],
    )
    assert "Algorithmic Accountability" in {finding.category for finding in findings}


def test_colorado_ai_consequential_decisions_triggers():
    findings = get_findings_for_text(
        "Our algorithm makes consequential decisions affecting consumers in employment",
        ["US-CO"],
    )
    assert "Consequential AI Decisions" in {finding.category for finding in findings}


def test_coe_oecd_human_oversight_triggers():
    findings = get_findings_for_text(
        "We maintain meaningful human oversight of all AI systems",
        ["COE-AI-225"],
    )
    assert "Human Oversight" in {finding.category for finding in findings}


def test_unesco_ai_nondiscrimination_triggers():
    findings = get_findings_for_text(
        "Our AI system is tested for algorithmic bias and discrimination",
        ["UNESCO-AI"],
    )
    assert "AI Non-Discrimination" in {finding.category for finding in findings}


def test_ai_law_rules_do_not_fire_for_unrelated_jurisdiction():
    findings = get_findings_for_text(
        "We may use your content to train our AI models",
        ["PIPEDA"],
    )
    assert findings == []


@pytest.mark.parametrize(
    "jurisdiction",
    [
        "US-FED",
        "US-CA",
        "US-TX",
        "US-VA",
        "US-CO",
        "US-CT",
        "US-IL",
        "US-NY",
        "GDPR",
        "UK-GDPR",
        "LGPD",
        "PIPEDA",
        "CA-QC",
        "POPIA",
        "PDPA-KE",
        "DPDP",
        "APPI",
        "PIPA",
        "APP",
        "PDPA-TH",
        "NDPR",
        "ICCPR-17",
        "COE-108",
        "EU-AI-ACT",
        "COE-AI-225",
        "OECD-AI",
        "UNESCO-AI",
    ],
)
def test_jurisdiction_literal_includes_all_27_codes(jurisdiction):
    request = AnalyzeRequest(text="policy text", jurisdictions=[jurisdiction])
    assert request.jurisdictions == [jurisdiction]


# ── CAN / EU / AUS jurisdiction tests ──────────────────────────


def test_pipeda_purpose_limitation_triggers():
    findings = get_findings_for_text(
        "We collect information only for the identified purposes stated in this policy",
        ["PIPEDA"],
    )
    assert "Purpose Limitation" in {finding.category for finding in findings}


def test_pipeda_breach_notification_triggers():
    findings = get_findings_for_text(
        "We notify the Privacy Commissioner of Canada of breaches posing a real risk of significant harm",
        ["PIPEDA"],
    )
    assert "Breach Notification" in {finding.category for finding in findings}


def test_quebec_law25_privacy_officer_triggers():
    findings = get_findings_for_text(
        "Our privacy officer oversees privacy by default practices under Law 25",
        ["CA-QC"],
    )
    assert "Privacy Rights" in {finding.category for finding in findings}


def test_quebec_law25_keyword_triggers():
    findings = get_findings_for_text(
        "This service complies with Quebec Bill 64 and the Commission d'accès à l'information",
        ["CA-QC"],
    )
    assert "Privacy Rights" in {finding.category for finding in findings}


def test_ca_qc_does_not_fire_for_gdpr_only():
    findings = get_findings_for_text(
        "Our privacy officer oversees privacy by default practices under Law 25",
        ["GDPR"],
    )
    assert "Privacy Rights" not in {finding.category for finding in findings}


def test_gdpr_data_transfer_sccs_triggers():
    findings = get_findings_for_text(
        "We transfer personal data to third countries using standard contractual clauses",
        ["GDPR"],
    )
    assert "Cross-Border Transfer" in {finding.category for finding in findings}


def test_gdpr_data_transfer_adequacy_triggers():
    findings = get_findings_for_text(
        "Data transfers are made under an adequacy decision by the European Commission",
        ["GDPR"],
    )
    assert "Cross-Border Transfer" in {finding.category for finding in findings}


def test_eprivacy_cookie_consent_triggers():
    findings = get_findings_for_text(
        "We require cookie consent before setting any non-essential cookies or analytics cookies",
        ["GDPR"],
    )
    assert "Tracking & Consent" in {finding.category for finding in findings}


def test_eprivacy_tracking_pixel_triggers():
    findings = get_findings_for_text(
        "Third-party tracking pixels are used to measure campaign performance",
        ["GDPR"],
    )
    assert "Tracking & Consent" in {finding.category for finding in findings}


def test_app_collection_notice_triggers():
    findings = get_findings_for_text(
        "We provide a collection notice stating the primary purpose for which personal information is collected",
        ["APP"],
    )
    assert "Collection Notice" in {finding.category for finding in findings}


def test_app_security_ndb_triggers():
    findings = get_findings_for_text(
        "Under the NDB scheme we notify the OAIC of eligible data breaches",
        ["APP"],
    )
    assert "Data Security" in {finding.category for finding in findings}


def test_app_access_correction_triggers():
    findings = get_findings_for_text(
        "Under APP 12 you may request access to the personal information we hold about you",
        ["APP"],
    )
    assert "Individual Rights" in {finding.category for finding in findings}


def test_app_rules_do_not_fire_for_us_only():
    findings = get_findings_for_text(
        "Under the NDB scheme and APP 12 you may request access to the personal information we hold about you",
        ["US-CA"],
    )
    assert "Data Security" not in {finding.category for finding in findings}
    assert "Individual Rights" not in {finding.category for finding in findings}


def test_ca_qc_is_valid_jurisdiction():
    request = AnalyzeRequest(text="policy text", jurisdictions=["CA-QC"])
    assert request.jurisdictions == ["CA-QC"]


# ── 2024-2026 currency update tests ──────────────────────────


def test_njdpa_triggers_on_new_jersey_privacy():
    findings = get_findings_for_text(
        "We comply with the New Jersey Data Protection Act and offer opt-out of profiling for consequential decisions",
        ["US-NJ"],
    )
    assert "User Rights" in {finding.category for finding in findings}


def test_mcdpa_triggers_on_minnesota_privacy():
    findings = get_findings_for_text(
        "Users in Minnesota have the right to question automated profiling decisions under MCDPA",
        ["US-MN"],
    )
    assert "User Rights" in {finding.category for finding in findings}


def test_ocpa_triggers_on_oregon_privacy():
    findings = get_findings_for_text(
        "Oregon consumers may opt out of the sale of personal data under OCPA",
        ["US-OR"],
    )
    assert "User Rights" in {finding.category for finding in findings}


def test_eu_ai_act_prohibited_ai_social_scoring_triggers():
    findings = get_findings_for_text(
        "We use social scoring to evaluate user behavior for service eligibility",
        ["EU-AI-ACT"],
    )
    assert "Prohibited AI" in {finding.category for finding in findings}


def test_eu_ai_act_prohibited_ai_biometric_public_triggers():
    findings = get_findings_for_text(
        "Our system performs real-time remote biometric identification in public spaces",
        ["EU-AI-ACT"],
    )
    assert "Prohibited AI" in {finding.category for finding in findings}


def test_eu_ai_act_prohibited_ai_emotion_workplace_triggers():
    findings = get_findings_for_text(
        "Emotion recognition technology is used in workplace monitoring",
        ["EU-AI-ACT"],
    )
    assert "Prohibited AI" in {finding.category for finding in findings}


def test_australian_privacy_tort_triggers_on_intrusion():
    findings = get_findings_for_text(
        "Any serious invasion of privacy through intrusion into seclusion may trigger our POLA 2024 obligations",
        ["APP"],
    )
    assert "Serious Privacy Invasion" in {finding.category for finding in findings}


def test_australian_privacy_tort_triggers_on_keyword():
    findings = get_findings_for_text(
        "This policy addresses the new statutory tort for misuse of private information under the Privacy Legislation Amendment",
        ["APP"],
    )
    assert "Serious Privacy Invasion" in {finding.category for finding in findings}


def test_uk_dua_recognised_legitimate_interests_triggers():
    findings = get_findings_for_text(
        "We rely on recognised legitimate interests under the Data Use and Access Act for this processing",
        ["UK-GDPR"],
    )
    assert "UK Data Rights" in {finding.category for finding in findings}


def test_uk_dua_smart_data_triggers():
    findings = get_findings_for_text(
        "We participate in the smart data scheme under the UK Data Use and Access framework",
        ["UK-GDPR"],
    )
    assert "UK Data Rights" in {finding.category for finding in findings}


@pytest.mark.parametrize("jurisdiction", ["US-NJ", "US-MN", "US-OR"])
def test_new_state_codes_are_valid_jurisdictions(jurisdiction):
    request = AnalyzeRequest(text="policy text", jurisdictions=[jurisdiction])
    assert request.jurisdictions == [jurisdiction]


# ── Orphaned code coverage tests ─────────────────────────────

def test_kenya_dpa_triggers_on_odpc():
    findings = get_findings_for_text(
        "We notify the Office of the Data Protection Commissioner (ODPC) of any Kenya personal data breach",
        ["PDPA-KE"],
    )
    assert len(findings) > 0, "Expected Kenya DPA rule to fire"


def test_thailand_pdpa_triggers_on_pdpc():
    findings = get_findings_for_text(
        "We notify the Personal Data Protection Committee within 72 hours of a breach under Thailand PDPA",
        ["PDPA-TH"],
    )
    assert len(findings) > 0, "Expected Thailand PDPA rule to fire"


def test_nigeria_ndpa_triggers_on_ndpc():
    findings = get_findings_for_text(
        "We comply with the Nigeria Data Protection Commission requirements under the NDPA and legacy NDPR",
        ["NDPR"],
    )
    assert len(findings) > 0, "Expected Nigeria NDPA rule to fire"


def test_all_30_jurisdiction_codes_have_at_least_one_rule():
    """Regression guard: every Jurisdiction code must map to at least one rule."""
    import typing
    from app.schemas import Jurisdiction
    from app.services.rules import PATTERNS

    all_codes = set(typing.get_args(Jurisdiction))
    covered = {j for r in PATTERNS for j in r.jurisdictions}
    orphans = all_codes - covered
    assert not orphans, f"Jurisdiction codes with no rules (add a RulePattern): {sorted(orphans)}"


# ── Phase 3: DocType Weighting (F2.2) ──────────────────────────────────────

from app.services.analyzer import _apply_doctype_weighting, _apply_industry_emphasis
from app.schemas import DocType, IndustryProfile


def _make_finding(category: str, severity: str) -> "Finding":
    from app.schemas import Evidence, Finding
    return Finding(
        category=category,
        severity=severity,
        confidence=0.9,
        excerpt="test excerpt",
        explanation="test explanation",
        jurisdictions=["US-CA"],
        evidence=Evidence(line_start=1, line_end=1, legal_basis=["Test basis"]),
    )


def test_doctype_privacy_policy_boosts_sale_share():
    f = _make_finding("Data Sale / Sharing", "Medium")
    result = _apply_doctype_weighting([f], "Privacy Policy")
    assert result[0].severity == "High", "Privacy Policy should bump Sale/Sharing Medium→High"


def test_doctype_tos_boosts_liability():
    f = _make_finding("Liability Limitation", "Medium")
    result = _apply_doctype_weighting([f], "Terms of Service")
    assert result[0].severity == "High"


def test_doctype_cookie_boosts_tracking():
    f = _make_finding("Tracking / Profiling", "Low")
    result = _apply_doctype_weighting([f], "Cookie Policy")
    assert result[0].severity == "Medium"


def test_doctype_none_no_change():
    f = _make_finding("Data Sale / Sharing", "Medium")
    result = _apply_doctype_weighting([f], None)
    assert result[0].severity == "Medium", "None doc_type must not alter severity"


def test_doctype_critical_not_promoted():
    f = _make_finding("Data Sale / Sharing", "Critical")
    result = _apply_doctype_weighting([f], "Privacy Policy")
    assert result[0].severity == "Critical", "Critical should not exceed Critical"


# ── Phase 3: Industry Emphasis (F2.3) ──────────────────────────────────────


def test_industry_healthcare_boosts_health_data():
    f = _make_finding("Health Data", "Medium")
    result = _apply_industry_emphasis([f], "Healthcare")
    assert result[0].severity == "High"


def test_industry_finance_boosts_financial_data():
    f = _make_finding("Financial Data", "Low")
    result = _apply_industry_emphasis([f], "Finance")
    assert result[0].severity == "Medium"


def test_industry_education_boosts_childrens_privacy():
    f = _make_finding("Children's Privacy", "Medium")
    result = _apply_industry_emphasis([f], "Education")
    assert result[0].severity == "High"


def test_industry_ai_tech_boosts_adm():
    f = _make_finding("Automated Decision-Making", "Medium")
    result = _apply_industry_emphasis([f], "AI / Tech Platform")
    assert result[0].severity == "High"


def test_industry_general_no_boost():
    f = _make_finding("Health Data", "Low")
    result = _apply_industry_emphasis([f], "General")
    assert result[0].severity == "Low"


def test_industry_none_no_change():
    f = _make_finding("Tracking / Profiling", "Medium")
    result = _apply_industry_emphasis([f], None)
    assert result[0].severity == "Medium"


# ── Phase 3: API schema validates DocType and IndustryProfile ────────────────


def test_analyze_request_accepts_valid_doc_type():
    from app.schemas import AnalyzeRequest
    req = AnalyzeRequest(
        text="Some policy text",
        doc_type="Privacy Policy",
        industry="Healthcare",
        jurisdictions=["US-CA"],
    )
    assert req.doc_type == "Privacy Policy"
    assert req.industry == "Healthcare"


def test_analyze_request_rejects_invalid_doc_type():
    from app.schemas import AnalyzeRequest
    with pytest.raises(ValidationError):
        AnalyzeRequest(text="x", doc_type="not-a-valid-type", jurisdictions=["US-CA"])


def test_analyze_request_rejects_invalid_industry():
    from app.schemas import AnalyzeRequest
    with pytest.raises(ValidationError):
        AnalyzeRequest(text="x", industry="Unknown Sector", jurisdictions=["US-CA"])


def test_doc_type_literal_covers_expected_values():
    import typing
    valid = set(typing.get_args(DocType))
    expected = {
        "Privacy Policy", "Terms of Service", "Cookie Policy",
        "Data Processing Agreement", "Combined",
    }
    assert expected.issubset(valid)


def test_industry_profile_literal_covers_expected_values():
    import typing
    valid = set(typing.get_args(IndustryProfile))
    expected = {
        "General", "Healthcare", "Finance", "Education",
        "Social Media", "AI / Tech Platform", "Gaming", "Retail",
    }
    assert expected.issubset(valid)
