"""Tests for the jurisdiction/doc_type/industry inference service.

Covers ``app/services/inference.py`` — the Phase 1 backend behind the
Streamlit v2 intake (issue #19). Signals are exercised in isolation
(URL-only, text-only, both) and the combined ``infer_all`` return shape
is verified end-to-end.

Naming: ``test_inference_<function>_<scenario>``.
"""

from __future__ import annotations

import pytest

from app.schemas import InferResponse
from app.services.inference import (
    infer_all,
    infer_doc_type,
    infer_industry,
    infer_jurisdictions,
)


# ---------------------------------------------------------------------------
# URL TLD detection
# ---------------------------------------------------------------------------


class TestInferJurisdictionsByTld:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://example.co.uk/privacy", "UK-GDPR"),
            ("https://example.uk/privacy", "UK-GDPR"),
            ("https://example.fr/privacy", "GDPR"),
            ("https://example.de/legal", "GDPR"),
            ("https://example.eu/privacy", "GDPR"),
            ("https://example.ca/privacy", "PIPEDA"),
            ("https://example.au/privacy", "APP"),
            ("https://example.br/politica", "LGPD"),
            ("https://example.in/privacy", "DPDP"),
            ("https://example.jp/privacy", "APPI"),
            ("https://example.kr/privacy", "PIPA"),
            ("https://example.za/privacy", "POPIA"),
            ("https://example.ng/privacy", "NDPR"),
            ("https://example.ke/privacy", "PDPA-KE"),
            ("https://example.th/privacy", "PDPA-TH"),
        ],
    )
    def test_inference_infer_jurisdictions_url_tld(self, url, expected):
        jurisdictions, signals = infer_jurisdictions(url, None)
        assert expected in jurisdictions
        assert signals["tld"], f"tld signal not populated for {url}"

    def test_inference_infer_jurisdictions_co_uk_matches_before_uk(self):
        # Longest-suffix rule: .co.uk should hit .co.uk, not fall through to .uk.
        _, signals = infer_jurisdictions("https://acme.co.uk/privacy", None)
        assert any(".co.uk" in s for s in signals["tld"])

    def test_inference_infer_jurisdictions_unknown_tld_returns_empty(self):
        jurisdictions, _ = infer_jurisdictions("https://example.xyz/privacy", None)
        assert jurisdictions == []


# ---------------------------------------------------------------------------
# Explicit statute mentions in text
# ---------------------------------------------------------------------------


class TestInferJurisdictionsByStatute:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("This policy complies with the CCPA.", "US-CA"),
            ("Governed by the California Consumer Privacy Act.", "US-CA"),
            ("We follow CPRA obligations.", "US-CA"),
            ("This policy honours the GDPR.", "GDPR"),
            ("Per General Data Protection Regulation Art. 6.", "GDPR"),
            ("Regulation (EU) 2016/679 applies.", "GDPR"),
            ("Governed by UK GDPR.", "UK-GDPR"),
            ("Data Protection Act 2018 applies.", "UK-GDPR"),
            ("Compliant with PIPEDA.", "PIPEDA"),
            ("Under Law 25 in Quebec.", "CA-QC"),
            ("This policy honors LGPD requirements.", "LGPD"),
            ("Applies under Lei Geral de Proteção de Dados.", "LGPD"),
            ("Governed by DPDP Act.", "DPDP"),
            ("APPI applies to Japanese residents.", "APPI"),
            ("POPIA is our framework.", "POPIA"),
            ("Under the Privacy Act 1988 (Cth).", "APP"),
            ("EU AI Act obligations for GPAI.", "EU-AI-ACT"),
            ("Under the Colorado AI Act (SB 205).", "US-CO"),
            ("SHIELD Act notice.", "US-NY"),
            ("TDPSA compliance details.", "US-TX"),
            ("VCDPA opt-out rights.", "US-VA"),
            ("CTDPA disclosure obligations.", "US-CT"),
            ("Illinois BIPA consent.", "US-IL"),
            ("COPPA parental consent required.", "US-FED"),
            ("HIPAA privacy rule.", "US-FED"),
        ],
    )
    def test_inference_infer_jurisdictions_statute_matches(self, text, expected):
        jurisdictions, signals = infer_jurisdictions(None, text)
        assert expected in jurisdictions, f"{expected} missing for text: {text!r}"
        assert signals["statute"], "statute signal not populated"

    def test_inference_cpa_only_matches_in_colorado_context(self):
        # Bare "CPA" without Colorado context should NOT trigger US-CO.
        jurisdictions, _ = infer_jurisdictions(None, "Our CPA reviewed the books.")
        assert "US-CO" not in jurisdictions

        # But with Colorado context it should.
        jurisdictions, _ = infer_jurisdictions(
            None, "The Colorado CPA sets consumer opt-out rights."
        )
        assert "US-CO" in jurisdictions


# ---------------------------------------------------------------------------
# Regulatory body mentions
# ---------------------------------------------------------------------------


class TestInferJurisdictionsByRegulator:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Contact CNIL for complaints.", "GDPR"),
            ("Contact the ICO for complaints.", "UK-GDPR"),
            ("AEPD is the supervisory authority.", "GDPR"),
            ("Complaints to the Garante.", "GDPR"),
            ("ANPD is our regulator.", "LGPD"),
            ("OAIC is the supervisor.", "APP"),
            ("Report to the FTC.", "US-FED"),
        ],
    )
    def test_inference_infer_jurisdictions_regulator_matches(self, text, expected):
        jurisdictions, signals = infer_jurisdictions(None, text)
        assert expected in jurisdictions
        assert signals["regulator"], "regulator signal not populated"


# ---------------------------------------------------------------------------
# Geographic scope phrases
# ---------------------------------------------------------------------------


class TestInferJurisdictionsByGeography:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("These rights apply to California residents.", "US-CA"),
            ("For EEA data subjects, additional rights apply.", "GDPR"),
            ("For residents of the European Economic Area.", "GDPR"),
            ("EU residents have the right to erasure.", "GDPR"),
            ("UK residents may contact the ICO.", "UK-GDPR"),
            ("For Canadian residents, PIPEDA applies.", "PIPEDA"),
            ("Quebec residents have additional rights.", "CA-QC"),
            ("Illinois residents may opt out.", "US-IL"),
            ("New York residents receive breach notification.", "US-NY"),
        ],
    )
    def test_inference_infer_jurisdictions_geo_matches(self, text, expected):
        jurisdictions, signals = infer_jurisdictions(None, text)
        assert expected in jurisdictions
        assert signals["geography"], "geography signal not populated"


# ---------------------------------------------------------------------------
# Currency + language pairing
# ---------------------------------------------------------------------------


class TestInferJurisdictionsCurrencyLanguage:
    def test_inference_infer_jurisdictions_pound_uk_phrase_triggers_uk(self):
        text = "Prices are shown in £; British customers have additional rights."
        jurisdictions, signals = infer_jurisdictions(None, text)
        assert "UK-GDPR" in jurisdictions
        assert any("£" in s for s in signals["currency_language"])

    def test_inference_infer_jurisdictions_euro_eu_language_triggers_gdpr(self):
        text = "Cost: €10. Datenschutz und personenbezogene daten sind wichtig."
        jurisdictions, signals = infer_jurisdictions(None, text)
        assert "GDPR" in jurisdictions
        assert signals["currency_language"], "currency_language signal missing"


# ---------------------------------------------------------------------------
# Language heuristic fallback
# ---------------------------------------------------------------------------


class TestInferJurisdictionsLanguageHeuristic:
    def test_inference_infer_jurisdictions_french_keywords_default_to_gdpr(self):
        text = (
            "Politique de confidentialité: nous traitons vos données personnelles "
            "conformément à notre engagement pour la vie privée."
        )
        jurisdictions, signals = infer_jurisdictions(None, text)
        assert "GDPR" in jurisdictions
        assert signals["language_heuristic"], "language_heuristic signal missing"


# ---------------------------------------------------------------------------
# Fallback / location_needed
# ---------------------------------------------------------------------------


class TestInferJurisdictionsFallback:
    def test_inference_infer_jurisdictions_no_signals_returns_empty(self):
        # infer_jurisdictions returns [] when nothing fires — infer_all layers on
        # the fallback + location_needed flag.
        jurisdictions, signals = infer_jurisdictions(None, "generic text")
        assert jurisdictions == []
        # All signal buckets are empty lists (present but empty).
        assert all(v == [] for v in signals.values())


# ---------------------------------------------------------------------------
# Doc type inference
# ---------------------------------------------------------------------------


class TestInferDocType:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://example.com/privacy", "Privacy Policy"),
            ("https://example.com/privacy-policy", "Privacy Policy"),
            ("https://example.com/terms", "Terms of Service"),
            ("https://example.com/tos", "Terms of Service"),
            ("https://example.com/terms-of-service", "Terms of Service"),
            ("https://example.com/legal/terms", "Terms of Service"),
            ("https://example.com/cookie-policy", "Cookie Policy"),
            ("https://example.com/dpa", "Data Processing Agreement"),
            ("https://example.com/data-processing", "Data Processing Agreement"),
        ],
    )
    def test_inference_infer_doc_type_from_url(self, url, expected):
        assert infer_doc_type(url, None) == expected

    def test_inference_infer_doc_type_combined_when_text_has_both(self):
        text = "This is our privacy policy and terms of service. You agree to..."
        assert infer_doc_type(None, text) == "Combined"

    def test_inference_infer_doc_type_privacy_only(self):
        text = "Privacy policy: We describe personal information collected."
        # combined check requires both markers — this only has privacy.
        assert infer_doc_type(None, text) == "Privacy Policy"

    def test_inference_infer_doc_type_terms_only(self):
        text = "You agree to binding arbitration for all disputes."
        assert infer_doc_type(None, text) == "Terms of Service"

    def test_inference_infer_doc_type_none_when_no_input(self):
        assert infer_doc_type(None, None) is None

    def test_inference_infer_doc_type_default_privacy_policy(self):
        # URL supplied but neither URL nor text contains a strong marker.
        assert infer_doc_type("https://example.com/", None) == "Privacy Policy"


# ---------------------------------------------------------------------------
# Industry inference
# ---------------------------------------------------------------------------


class TestInferIndustry:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://facebook.com/privacy", "Social Media"),
            ("https://www.instagram.com/legal", "Social Media"),
            ("https://twitter.com/tos", "Social Media"),
            ("https://tiktok.com/legal", "Social Media"),
            ("https://reddit.com/privacy", "Social Media"),
        ],
    )
    def test_inference_infer_industry_social_media_domain(self, url, expected):
        assert infer_industry(url, None) == expected

    def test_inference_infer_industry_ai_tech_by_domain(self):
        assert infer_industry("https://openai.com/policies", None) == "AI / Tech Platform"
        assert infer_industry("https://anthropic.com/legal", None) == "AI / Tech Platform"

    def test_inference_infer_industry_healthcare_text(self):
        assert infer_industry(None, "We handle protected health information (PHI) per HIPAA.") == "Healthcare"

    def test_inference_infer_industry_finance_text(self):
        assert infer_industry(None, "We are a chartered bank handling financial data.") == "Finance"

    def test_inference_infer_industry_education_url(self):
        assert infer_industry("https://harvard.edu/privacy", None) == "Education"

    def test_inference_infer_industry_gaming_text(self):
        assert infer_industry(None, "This game includes multiplayer play for gamers.") == "Gaming"

    def test_inference_infer_industry_retail_text(self):
        assert infer_industry(None, "Add items to your cart and checkout at our online shop.") == "Retail"

    def test_inference_infer_industry_government_defaults_to_general(self):
        assert infer_industry("https://usa.gov/privacy", None) == "General"

    def test_inference_infer_industry_none_when_no_input(self):
        assert infer_industry(None, None) is None

    def test_inference_infer_industry_default_general(self):
        # URL supplied but no strong industry signals.
        assert infer_industry("https://example.com/privacy", None) == "General"


# ---------------------------------------------------------------------------
# location_needed / infer_all
# ---------------------------------------------------------------------------


class TestInferAll:
    def test_inference_infer_all_returns_infer_response(self):
        result = infer_all("https://example.co.uk/privacy", "GDPR text")
        assert isinstance(result, InferResponse)

    def test_inference_infer_all_populates_detected_signals(self):
        result = infer_all(
            "https://example.co.uk/privacy",
            "This policy is subject to CCPA and GDPR.",
        )
        # tld + statute signals should both fire.
        assert result.detected_signals
        assert "tld" in result.detected_signals
        assert "statute" in result.detected_signals

    def test_inference_infer_all_location_needed_true_when_no_signals(self):
        result = infer_all(None, "generic policy text with no cues")
        assert result.location_needed is True
        # Fallback jurisdictions applied.
        assert "US-CA" in result.jurisdictions
        assert "GDPR" in result.jurisdictions
        # Fallback signal recorded so the UI can explain.
        assert "fallback" in result.detected_signals

    def test_inference_infer_all_location_needed_false_when_signals_present(self):
        result = infer_all("https://example.fr/privacy", None)
        assert result.location_needed is False
        assert "GDPR" in result.jurisdictions

    def test_inference_infer_all_doc_type_and_industry_populated(self):
        result = infer_all(
            "https://facebook.com/privacy",
            "California residents have opt-out rights.",
        )
        assert result.doc_type == "Privacy Policy"
        assert result.industry == "Social Media"
        assert "US-CA" in result.jurisdictions

    def test_inference_infer_all_dedupes_jurisdictions(self):
        # CCPA + California Consumer Privacy Act + California residents should
        # yield US-CA only once.
        text = (
            "We follow the CCPA and California Consumer Privacy Act. "
            "California residents can opt out."
        )
        result = infer_all(None, text)
        assert result.jurisdictions.count("US-CA") == 1
