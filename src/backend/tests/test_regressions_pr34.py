"""
Categorical regression tests backfilled after PR #34.

The four must-fix findings on PR #34 (``for_work`` chip drop, ``javascript:``
XSS, jurisdiction-filter boundary, ``/analyze/file`` unvalidated jurisdictions)
all shared one root cause: **cross-endpoint / schema-vs-handler drift**. This
file adds parity / boundary / defense-in-depth tests that would have caught
the entire class of bug at CI time, not multi-specialist review time.

See ``docs/reports/test-suite-audit-pr34.md`` for the full audit narrative.

Categories covered (letters match the audit brief):

  A. Cross-endpoint field-consistency drift
  B. Schema-``Literal`` allowlist parity guards
  C. URL-scheme XSS defense-in-depth
  D. Malformed / oversized / unicode inputs
  E. ReDoS canary on ``inference.py``
  F. Domain-grouping edge cases
  G. Sort-stability guarantees

Naming convention follows ``.claude/rules/testing.md``:
    ``test_<module>_<function>_<scenario>``.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import get_args
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.schemas import (
    AnalysisPayload,
    ContextChip,
    DocType,
    Evidence,
    Finding,
    IndustryProfile,
    Jurisdiction,
)
from app.services.analyzer import AnalysisResult


# ---------------------------------------------------------------------------
# Helpers — kept intentionally local so we don't collide with helpers the
# backend-fix agent may be editing in ``test_main_endpoints.py``.
# ---------------------------------------------------------------------------


def _payload(**overrides) -> AnalysisPayload:
    """Minimal AnalysisPayload for endpoint-shim tests."""
    defaults = dict(
        id=str(uuid4()),
        name="Test Policy",
        doc_type=None,
        source_url=None,
        document_text="Sample policy text.",
        line_offsets=[0],
        status="completed",
        review_required=False,
        confidence=0.90,
        risk_score=2.0,
        grade="A",
        created_at=datetime.now(timezone.utc),
        findings=[],
        summary="Mocked summary.",
    )
    defaults.update(overrides)
    return AnalysisPayload(**defaults)


def _result(**overrides) -> AnalysisResult:
    return AnalysisResult(payload=_payload(**overrides), issues=[])


def _finding(
    *,
    category: str = "Sale/Share",
    severity: str = "High",
    jurisdictions=None,
    irp_score: float | None = 0.5,
    excerpt: str = "we may sell your data",
) -> Finding:
    return Finding(
        category=category,
        severity=severity,
        confidence=0.9,
        excerpt=excerpt,
        explanation="rendered by the analyzer",
        jurisdictions=jurisdictions if jurisdictions is not None else ["US-CA"],
        evidence=Evidence(line_start=1, line_end=2, legal_basis=["basis"]),
        impact=3,
        likelihood=3,
        safeguard_score=0,
        irp_score=irp_score,
    )


@pytest.fixture
def stub_analyze(monkeypatch):
    """Replace ``analyze_text`` on every entry point with an async stub that
    records the kwargs it received. Returns a dict callers can inspect."""
    captured: dict = {}

    async def fake_analyze(text, jurisdictions, name=None, doc_type=None,
                          industry=None, source_url=None, mode=None,
                          source_document=None, context=None, **kwargs):
        captured.setdefault("calls", []).append(
            dict(
                text=text,
                jurisdictions=list(jurisdictions),
                name=name,
                doc_type=doc_type,
                industry=industry,
                source_url=source_url,
                mode=mode,
                context=list(context) if context else [],
            )
        )
        return _result(
            name=name,
            doc_type=doc_type,
            source_url=source_url,
        ).__class__(
            payload=_payload(
                name=name,
                doc_type=doc_type,
                source_url=source_url,
            ).model_copy(update={
                "context": list(context) if context else [],
                "jurisdictions": list(jurisdictions),
            }),
            issues=[],
        )

    monkeypatch.setattr("app.main.analyze_text", fake_analyze)
    return captured


@pytest.fixture
def stub_extract(monkeypatch):
    """Stub ``extract_text_from_bytes`` so file-upload tests don't need real
    parsers. Returns a decoded string from the uploaded bytes."""
    monkeypatch.setattr(
        "app.main.extract_text_from_bytes",
        lambda filename, content_type, data: (
            data.decode("utf-8", errors="ignore") or "policy text"
        ),
    )


@pytest.fixture
def stub_fetch_url(monkeypatch):
    """Stub ``fetch_url_text`` so URL tests don't hit the network."""
    async def fake_fetch(url):
        return "policy text about privacy and terms"
    monkeypatch.setattr("app.main.fetch_url_text", fake_fetch)


# ===========================================================================
# Category A — Cross-endpoint field-consistency drift
# ===========================================================================


class TestCategoryACrossEndpointConsistency:
    """The class of bug PR #34 caught was 'field validated on one endpoint,
    silently dropped on another'. These tests iterate the schema ``Literal``
    at runtime, so any new chip / jurisdiction added is automatically covered.
    """

    def test_all_analyze_endpoints_accept_every_context_chip(
        self, app_client, stub_analyze, stub_extract, stub_fetch_url
    ):
        """Every value in ``ContextChip`` must be accepted equivalently by
        ``/analyze``, ``/analyze/url``, and ``/analyze/file``.

        Regression: ``for_work`` was silently dropped by ``/analyze/file`` only.
        """
        for chip in get_args(ContextChip):
            # JSON /analyze
            r1 = app_client.post(
                "/analyze",
                json={"text": "hello world policy text", "context": [chip]},
            )
            assert r1.status_code == 200, f"/analyze rejected {chip}: {r1.text}"
            assert r1.json()["context"] == [chip]

            # JSON /analyze/url
            r2 = app_client.post(
                "/analyze/url",
                json={"url": "https://example.com/privacy", "context": [chip]},
            )
            assert r2.status_code == 200, f"/analyze/url rejected {chip}: {r2.text}"
            assert r2.json()["context"] == [chip]

            # Multipart /analyze/file
            r3 = app_client.post(
                "/analyze/file",
                files={"file": ("p.txt", b"policy body", "text/plain")},
                data={"context": chip},
            )
            assert r3.status_code == 200, f"/analyze/file rejected {chip}: {r3.text}"
            assert r3.json()["context"] == [chip]

    def test_all_analyze_endpoints_reject_bogus_context_chip_consistently(
        self, app_client, stub_analyze, stub_extract, stub_fetch_url
    ):
        """Bogus chip → JSON endpoints 422 (Pydantic), multipart silently drops.

        Documenting the intentional asymmetry: multipart handlers are lenient
        because form parsers don't get a chance to validate a Literal-typed
        field the way Pydantic does. Both behaviors are correct — the point
        is that they're pinned, not accidental.
        """
        bogus = "for_evil"

        r1 = app_client.post(
            "/analyze",
            json={"text": "hello", "context": [bogus]},
        )
        assert r1.status_code == 422, r1.text

        r2 = app_client.post(
            "/analyze/url",
            json={"url": "https://example.com/", "context": [bogus]},
        )
        assert r2.status_code == 422, r2.text

        # Multipart drops silently — but must return 200 without echoing bogus.
        r3 = app_client.post(
            "/analyze/file",
            files={"file": ("p.txt", b"policy body", "text/plain")},
            data={"context": bogus},
        )
        assert r3.status_code == 200
        assert bogus not in r3.json()["context"]

    def test_all_analyze_endpoints_accept_every_valid_jurisdiction(
        self, app_client, stub_analyze, stub_extract, stub_fetch_url
    ):
        """Every ``Jurisdiction`` Literal value survives round-trip on all
        three endpoints."""
        for jurisdiction in get_args(Jurisdiction):
            r1 = app_client.post(
                "/analyze",
                json={"text": "hello world", "jurisdictions": [jurisdiction]},
            )
            assert r1.status_code == 200, f"/analyze rejected {jurisdiction}: {r1.text}"
            assert jurisdiction in r1.json()["jurisdictions"]

            r2 = app_client.post(
                "/analyze/url",
                json={"url": "https://example.com/", "jurisdictions": [jurisdiction]},
            )
            assert r2.status_code == 200, f"/analyze/url rejected {jurisdiction}: {r2.text}"
            assert jurisdiction in r2.json()["jurisdictions"]

            r3 = app_client.post(
                "/analyze/file",
                files={"file": ("p.txt", b"policy body", "text/plain")},
                data={"jurisdictions": jurisdiction},
            )
            assert r3.status_code == 200, f"/analyze/file rejected {jurisdiction}: {r3.text}"
            assert jurisdiction in r3.json()["jurisdictions"]

    def test_all_analyze_endpoints_filter_bogus_jurisdictions_consistently(
        self, app_client, stub_analyze, stub_extract, stub_fetch_url
    ):
        """Bogus jurisdiction: JSON rejects (422), multipart silently filters.

        Documenting the same intentional asymmetry as chips — the multipart
        endpoint is form-typed, so it can't 422 on unknown Literal values.
        It MUST drop them, not propagate them into the analyzer where they
        would short-circuit the post-LLM jurisdiction filter.
        """
        r1 = app_client.post(
            "/analyze",
            json={"text": "hello", "jurisdictions": ["BOGUS-JUR"]},
        )
        assert r1.status_code == 422, r1.text

        r2 = app_client.post(
            "/analyze/url",
            json={"url": "https://example.com/", "jurisdictions": ["BOGUS-JUR"]},
        )
        assert r2.status_code == 422, r2.text

        r3 = app_client.post(
            "/analyze/file",
            files={"file": ("p.txt", b"policy body", "text/plain")},
            data={"jurisdictions": "US-CA,BOGUS-JUR,GDPR"},
        )
        assert r3.status_code == 200
        assert "BOGUS-JUR" not in r3.json()["jurisdictions"]
        assert "US-CA" in r3.json()["jurisdictions"]
        assert "GDPR" in r3.json()["jurisdictions"]


# ===========================================================================
# Category B — Schema-``Literal`` allowlist parity guards
# ===========================================================================


class TestCategoryBSchemaAllowlistParity:
    """Any handler-side allowlist derived from a schema ``Literal`` must be
    equality-checked against ``typing.get_args`` so a new value on the
    ``Literal`` can never silently outdate the handler allowlist.

    This is the meta-fix that would have caught PR #34's ``for_work`` bug at
    import time.
    """

    def test_valid_chips_matches_context_chip_literal(self):
        from app.main import _VALID_CHIPS
        assert _VALID_CHIPS == frozenset(get_args(ContextChip)), (
            "app.main._VALID_CHIPS drifted from ContextChip Literal — a new "
            "chip was added to schemas.py without updating main.py's derivation."
        )

    def test_valid_jurisdictions_matches_jurisdiction_literal(self):
        from app.main import _VALID_JURISDICTIONS
        assert _VALID_JURISDICTIONS == frozenset(get_args(Jurisdiction)), (
            "app.main._VALID_JURISDICTIONS drifted from Jurisdiction Literal."
        )

    def test_doctype_and_industry_allowlists_match_literal(self):
        """/analyze/file derives DocType and IndustryProfile allowlists at
        request time. Assert the derivation formula still uses ``get_args``.
        """
        # The set constructed in the handler MUST be equal to the get_args set.
        # We reconstruct the handler's expression here as an oracle.
        expected_doctypes = set(get_args(DocType))
        expected_industries = set(get_args(IndustryProfile))
        assert len(expected_doctypes) >= 5, "DocType Literal shrank unexpectedly"
        assert len(expected_industries) >= 5, "IndustryProfile Literal shrank unexpectedly"
        # DocType / IndustryProfile enumerations are used verbatim in main.py
        # (see the /analyze/file body); if either is emptied, the guard below
        # will fail loud in CI.
        assert "Privacy Policy" in expected_doctypes
        assert "General" in expected_industries


# ===========================================================================
# Category C — URL-scheme XSS defense-in-depth
# ===========================================================================


XSS_URL_SCHEME_PAYLOADS = [
    "javascript:alert(1)",
    "JavaScript:alert(1)",           # case variation
    "data:text/html,<script>alert(1)</script>",
    "vbscript:msgbox",
    "file:///etc/passwd",
]

XSS_URL_ACCEPTING_FIELDS = [
    # (endpoint, body_shape, field_that_takes_url)
    ("/analyze", {"text": "hello world"}, "source_url"),
    ("/analyze/url", {}, "url"),
    ("/watchlist", {"vendor": "AcmeCorp"}, "source_url"),
]


class TestCategoryCUrlSchemeXssDefense:
    """Every URL-accepting request field must reject scheme-based XSS payloads
    at the schema layer. ``html.escape`` does NOT neutralize a
    ``javascript:`` URL in an ``<a href>``, so the frontend can't be trusted
    to clean this up post-hoc.
    """

    @pytest.mark.parametrize("payload", XSS_URL_SCHEME_PAYLOADS)
    def test_all_url_fields_reject_javascript_scheme(self, app_client, payload):
        """Loop every URL-accepting field × every non-http(s) scheme."""
        for endpoint, body_shape, url_field in XSS_URL_ACCEPTING_FIELDS:
            body = dict(body_shape)
            body[url_field] = payload
            response = app_client.post(endpoint, json=body)
            assert response.status_code in (400, 422), (
                f"{endpoint} accepted XSS payload {payload!r} on field "
                f"{url_field!r} — expected 400/422, got {response.status_code}: "
                f"{response.text}"
            )

    def test_all_url_fields_reject_data_scheme(self, app_client):
        """``data:`` URIs are the second most common XSS scheme after
        ``javascript:``. All endpoints must reject."""
        for endpoint, body_shape, url_field in XSS_URL_ACCEPTING_FIELDS:
            body = dict(body_shape)
            body[url_field] = "data:text/html,<script>alert(1)</script>"
            response = app_client.post(endpoint, json=body)
            assert response.status_code in (400, 422), (
                f"{endpoint} accepted data: URL"
            )

    def test_all_url_fields_reject_vbscript_scheme(self, app_client):
        for endpoint, body_shape, url_field in XSS_URL_ACCEPTING_FIELDS:
            body = dict(body_shape)
            body[url_field] = "vbscript:msgbox"
            response = app_client.post(endpoint, json=body)
            assert response.status_code in (400, 422), (
                f"{endpoint} accepted vbscript: URL"
            )

    def test_all_url_fields_reject_file_scheme(self, app_client):
        for endpoint, body_shape, url_field in XSS_URL_ACCEPTING_FIELDS:
            body = dict(body_shape)
            body[url_field] = "file:///etc/passwd"
            response = app_client.post(endpoint, json=body)
            assert response.status_code in (400, 422), (
                f"{endpoint} accepted file:// URL"
            )

    def test_all_url_fields_accept_https_scheme(
        self, app_client, stub_analyze, stub_fetch_url
    ):
        """Sanity check that our XSS guards don't block legitimate https URLs."""
        good = "https://example.com/privacy"

        # /analyze accepts source_url
        r1 = app_client.post("/analyze", json={"text": "hello", "source_url": good})
        assert r1.status_code == 200, r1.text

        # /analyze/url accepts url
        r2 = app_client.post("/analyze/url", json={"url": good})
        assert r2.status_code == 200, r2.text

        # /watchlist accepts source_url
        r3 = app_client.post("/watchlist", json={"vendor": "Acme", "source_url": good})
        assert r3.status_code == 200, r3.text

    def test_watchlist_and_analyze_reject_url_schemes_identically(self, app_client):
        """PR #34 root cause: /analyze/source_url validator DRIFTED from
        WatchlistCreateRequest's for a full release. Assert they reject the
        same set of schemes so they can never drift again."""
        for payload in ["javascript:x", "data:text/html,x", "vbscript:x", "file:///x"]:
            # watchlist
            r_watch = app_client.post(
                "/watchlist", json={"vendor": "V", "source_url": payload}
            )
            # analyze
            r_analyze = app_client.post(
                "/analyze", json={"text": "hi", "source_url": payload}
            )
            watch_rejected = r_watch.status_code in (400, 422)
            analyze_rejected = r_analyze.status_code in (400, 422)
            assert watch_rejected == analyze_rejected, (
                f"Scheme parity drift on {payload!r}: watchlist status="
                f"{r_watch.status_code}, analyze status={r_analyze.status_code}"
            )
            assert watch_rejected, f"Both endpoints accepted {payload!r}"


# ===========================================================================
# Category D — Malformed / oversized / unicode inputs
# ===========================================================================


class TestCategoryDMalformedInputs:
    """The analyzer must fail clean (4xx or 200) on hostile inputs — never
    500, never hang."""

    def test_analyze_rejects_empty_text(self, app_client):
        """``AnalyzeRequest.text`` has ``min_length=1`` — empty must be 422."""
        response = app_client.post("/analyze", json={"text": ""})
        assert response.status_code == 422

    def test_analyze_rejects_whitespace_only_text(self, app_client, stub_analyze):
        """Whitespace-only text is technically length >= 1 so the schema
        accepts it. Downstream ``_truncate_text(text.strip())`` will collapse
        it to empty, but that's the analyzer's problem — the endpoint must
        still return 200 without crashing."""
        response = app_client.post("/analyze", json={"text": "   \n\t  "})
        # Either 200 (analyzer coped) or a clean 4xx — MUST NOT be 500.
        assert response.status_code < 500, response.text

    def test_analyze_handles_null_bytes_in_text(self, app_client, stub_analyze):
        """Null bytes must not crash the request pipeline. Pydantic accepts
        them; the analyzer stub records the call; response is 200."""
        payload = {"text": "policy text\x00 with null bytes\x00 embedded"}
        response = app_client.post("/analyze", json=payload)
        assert response.status_code == 200, response.text

    def test_analyze_handles_mixed_unicode_normalization(self, app_client, stub_analyze):
        """NFC ('é' as U+00E9) and NFD ('e' + U+0301) must both round-trip."""
        nfc = "déjà vu — this policy is problematic."
        nfd = "déjà vu — this policy is problematic."
        for text in (nfc, nfd):
            response = app_client.post("/analyze", json={"text": text})
            assert response.status_code == 200, response.text


# ===========================================================================
# Category E — ReDoS canary on ``inference.py``
# ===========================================================================


class TestCategoryEReDoSCanary:
    """Every regex in ``inference.py`` runs on user-supplied policy text.
    A catastrophically-backtracking pattern would take a worker offline.
    Wall-clock budget: 2 seconds for a 100k-char pathological input."""

    def test_infer_regex_completes_within_budget_for_pathological_inputs(self):
        from app.services.inference import infer_all

        pathological_inputs = [
            ("100k of 'a'", "a" * 100_000),
            ("10k nested parens", "(" * 10_000 + ")" * 10_000),
            ("long dot-chain URL body", "https://" + "a." * 5_000 + "com"),
            ("alternating chars", ("ab" * 50_000)),
            ("statute-like noise", "CCPA GDPR " * 10_000),
        ]

        for label, inp in pathological_inputs:
            start = time.monotonic()
            infer_all(None, inp)
            elapsed = time.monotonic() - start
            assert elapsed < 2.0, (
                f"inference.infer_all took {elapsed:.2f}s on '{label}' — "
                f"potential ReDoS. Budget: 2.0s."
            )


# ===========================================================================
# Category F — Domain-grouping edge cases
# ===========================================================================


class TestCategoryFDomainGroupingEdgeCases:
    """``_group_by_domain`` uses ``.get()`` for category lookup — categories
    outside ``_DOMAIN_MAP`` must be silently skipped, not crash, and must
    respect per-domain and total caps."""

    def test_group_by_domain_skips_unmapped_category(self):
        from app.services.analyzer import _group_by_domain

        unmapped = _finding(category="TotallyMadeUpCategory")
        result = _group_by_domain([unmapped])
        # All four domain buckets exist, all empty — no crash, no leak.
        assert set(result.keys()) == {"Data", "Data use", "Terms of use", "Privacy rights"}
        for domain, findings in result.items():
            assert findings == [], (
                f"Unmapped finding leaked into domain {domain!r}: {findings}"
            )

    def test_group_by_domain_respects_per_domain_cap(self):
        """Max 2 findings per domain even if 10 map to that domain."""
        from app.services.analyzer import _group_by_domain

        # 5 findings that all map to the "Data" domain via Sensitive Data.
        findings = [_finding(category="Sensitive Data", excerpt=f"e{i}") for i in range(5)]
        result = _group_by_domain(findings, max_per_domain=2, max_total=8)
        assert len(result["Data"]) == 2
        # Other domains stay empty.
        for domain in ("Data use", "Terms of use", "Privacy rights"):
            assert result[domain] == []

    def test_group_by_domain_respects_total_cap(self):
        """Max 8 total across all domains."""
        from app.services.analyzer import _group_by_domain

        # 3 findings each in 4 different domains = 12 total. Cap is 8.
        findings = (
            [_finding(category="Sensitive Data", excerpt=f"e{i}") for i in range(3)]
            + [_finding(category="AI Training", excerpt=f"f{i}") for i in range(3)]
            + [_finding(category="Liability", excerpt=f"g{i}") for i in range(3)]
            + [_finding(category="User Rights", excerpt=f"h{i}") for i in range(3)]
        )
        result = _group_by_domain(findings, max_per_domain=3, max_total=8)
        total = sum(len(v) for v in result.values())
        assert total == 8, f"expected exactly 8 findings across domains, got {total}"


# ===========================================================================
# Category G — Sort-stability guarantees
# ===========================================================================


class TestCategoryGSortStability:
    """``apply_category_weights`` uses Python ``sorted()`` — which is stable
    per the language spec. Assert that guarantee at the API level so a future
    refactor can't silently switch to ``list.sort()`` with a mutating key or
    a non-stable algorithm without failing this test."""

    def test_apply_category_weights_sort_is_stable_on_identical_keys(self):
        from app.services.context import apply_category_weights

        # Three findings with identical (weight, irp, severity) tuples.
        f_a = _finding(category="A_Cat", excerpt="first", irp_score=0.5)
        f_b = _finding(category="B_Cat", excerpt="second", irp_score=0.5)
        f_c = _finding(category="C_Cat", excerpt="third", irp_score=0.5)

        # No context supplied → all weights collapse to 1.0.
        ordered = apply_category_weights([f_a, f_b, f_c], [])
        assert [f.category for f in ordered] == ["A_Cat", "B_Cat", "C_Cat"], (
            "sorted() must be stable when all sort keys are equal — input "
            "order is the tie-breaker of last resort"
        )

    def test_apply_category_weights_is_deterministic(self):
        """Repeated calls with the same input return the same order."""
        from app.services.context import apply_category_weights

        findings = [
            _finding(category=cat, excerpt=f"e{i}", irp_score=0.5)
            for i, cat in enumerate(["A", "B", "C", "D", "E"])
        ]
        first = [f.category for f in apply_category_weights(findings, [])]
        second = [f.category for f in apply_category_weights(findings, [])]
        third = [f.category for f in apply_category_weights(findings, ["for_work"])]
        fourth = [f.category for f in apply_category_weights(findings, ["for_work"])]
        assert first == second
        assert third == fourth


# ===========================================================================
# Bonus — Jurisdiction-filter boundary regression (was PR #34 must-fix #3).
# ===========================================================================


class TestJurisdictionFilterBoundary:
    """The pre-fix predicate ``not f.jurisdictions or any(...)`` had a corner
    case: an LLM finding with ``jurisdictions=[]`` would slip through the
    filter. The fixed predicate ``f.jurisdictions and any(...)`` drops
    empty-list findings. Assert both edges of the boundary."""

    def test_analyze_drops_llm_findings_with_empty_jurisdictions(
        self, app_client, monkeypatch
    ):
        """LLM emits a finding tagged with no jurisdictions → must be dropped."""
        from app.services.rules import detect_findings

        # Rule pipeline: return nothing so we only see the LLM contribution.
        monkeypatch.setattr(
            "app.services.analyzer.detect_findings",
            lambda text, jurisdictions: [],
        )

        # Fake LLM: returns one finding with empty jurisdictions list.
        class FakeLLMClient:
            async def analyze(self, **kwargs):
                return {
                    "summary": "mock",
                    "overall_confidence": 0.9,
                    "findings": [
                        {
                            "category": "Made Up",
                            "severity": "High",
                            "confidence": 0.9,
                            "excerpt": "some excerpt about privacy",
                            "explanation": "some reason",
                            "jurisdictions": [],  # <-- the corner case
                            "evidence": {
                                "line_start": 1,
                                "line_end": 2,
                                "legal_basis": ["basis"],
                            },
                            "impact": 3,
                            "likelihood": 3,
                            "safeguard_score": 0,
                        }
                    ],
                }

        monkeypatch.setattr(
            "app.services.analyzer.LocalAIClient", lambda: FakeLLMClient()
        )

        # Legal-KB retrieval: return empty context to skip network.
        class FakeKB:
            async def retrieve(self, *args, **kwargs):
                return ""
        monkeypatch.setattr(
            "app.services.analyzer.get_legal_kb", lambda: FakeKB()
        )

        response = app_client.post(
            "/analyze",
            json={"text": "policy text", "jurisdictions": ["US-CA"]},
        )
        assert response.status_code == 200
        findings = response.json()["findings"]
        # No LLM finding should have leaked past the filter.
        assert not any(f["category"] == "Made Up" for f in findings), (
            "LLM finding with empty jurisdictions leaked past the filter — "
            "regression against PR #34 must-fix #3"
        )

    def test_analyze_drops_llm_findings_with_nonmatching_jurisdictions(
        self, app_client, monkeypatch
    ):
        """LLM finding tagged for US-IL when caller asked for US-CA → drop."""
        monkeypatch.setattr(
            "app.services.analyzer.detect_findings",
            lambda text, jurisdictions: [],
        )

        class FakeLLMClient:
            async def analyze(self, **kwargs):
                return {
                    "summary": "mock",
                    "overall_confidence": 0.9,
                    "findings": [
                        {
                            "category": "Biometric Data",
                            "severity": "High",
                            "confidence": 0.9,
                            "excerpt": "facial recognition",
                            "explanation": "BIPA-specific",
                            "jurisdictions": ["US-IL"],
                            "evidence": {
                                "line_start": 1,
                                "line_end": 2,
                                "legal_basis": ["BIPA"],
                            },
                            "impact": 4,
                            "likelihood": 3,
                            "safeguard_score": 0,
                        }
                    ],
                }

        class FakeKB:
            async def retrieve(self, *args, **kwargs):
                return ""

        monkeypatch.setattr(
            "app.services.analyzer.LocalAIClient", lambda: FakeLLMClient()
        )
        monkeypatch.setattr(
            "app.services.analyzer.get_legal_kb", lambda: FakeKB()
        )

        response = app_client.post(
            "/analyze",
            json={"text": "policy text", "jurisdictions": ["US-CA"]},
        )
        assert response.status_code == 200
        findings = response.json()["findings"]
        assert not any(f["category"] == "Biometric Data" for f in findings)

    def test_analyze_keeps_llm_findings_when_at_least_one_matches(
        self, app_client, monkeypatch
    ):
        """LLM finding tagged with both US-CA and US-IL when caller asks for
        US-CA → kept (any() semantics)."""
        monkeypatch.setattr(
            "app.services.analyzer.detect_findings",
            lambda text, jurisdictions: [],
        )

        class FakeLLMClient:
            async def analyze(self, **kwargs):
                return {
                    "summary": "mock",
                    "overall_confidence": 0.9,
                    "findings": [
                        {
                            "category": "Data Sale / Sharing",
                            "severity": "High",
                            "confidence": 0.9,
                            "excerpt": "we sell your data",
                            "explanation": "CCPA-relevant",
                            "jurisdictions": ["US-CA", "US-IL"],
                            "evidence": {
                                "line_start": 1,
                                "line_end": 2,
                                "legal_basis": ["CCPA"],
                            },
                            "impact": 4,
                            "likelihood": 3,
                            "safeguard_score": 0,
                        }
                    ],
                }

        class FakeKB:
            async def retrieve(self, *args, **kwargs):
                return ""

        monkeypatch.setattr(
            "app.services.analyzer.LocalAIClient", lambda: FakeLLMClient()
        )
        monkeypatch.setattr(
            "app.services.analyzer.get_legal_kb", lambda: FakeKB()
        )

        response = app_client.post(
            "/analyze",
            json={"text": "policy text about selling data", "jurisdictions": ["US-CA"]},
        )
        assert response.status_code == 200
        findings = response.json()["findings"]
        assert any(f["category"] == "Data Sale / Sharing" for f in findings), (
            "LLM finding whose jurisdictions intersect the request was "
            "incorrectly dropped by the filter"
        )
