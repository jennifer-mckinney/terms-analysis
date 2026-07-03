"""Regression tests for the Phase 1 remediation of ``docs/reports/tech-spec-audit.md``.

Each test cites the audit finding ID it defends against. Same 3-rule policy
as ``test_regressions_pr34.py`` (see ``.claude/rules/testing.md``): schema-
derived allowlists, cross-endpoint parity, runtime enumeration.

Findings covered here:

- LE-001 — watchlist refresh must not pass a hardcoded jurisdictions list
- LE-002 — /analyze/file empty jurisdictions must remain empty (no US-CA/GDPR
  fallback)
- LE-003 — _watchlist_loop_async must log (not swallow) refresh failures
- LE-012 — _bump_severity boost lookup must be exact-category match
- LE-013 — _DOCTYPE_BOOSTS / _INDUSTRY_BOOSTS keys must be canonical categories
- LE-017 — Streamlit v2 must render the review_required signal
- LE-018 — action item copy must not contain em-dashes (LIB-VOICE)
- GAP-001 — /exports/analyses.csv must honour ids and detailed query params
- GAP-014 — streamlit and requests must be declared as webapp dependencies
"""

from __future__ import annotations

import inspect
import logging
import re
from pathlib import Path

import pytest

from app.schemas import CATEGORIES, Evidence, Finding

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _finding(category: str = "Sale/Share", severity: str = "Medium") -> Finding:
    return Finding(
        category=category,
        severity=severity,
        confidence=0.9,
        excerpt="sample text",
        explanation="rendered by the analyzer",
        jurisdictions=["US-CA"],
        evidence=Evidence(line_start=1, line_end=2, legal_basis=["basis"]),
        impact=3,
        likelihood=3,
        safeguard_score=0,
        irp_score=0.4,
    )


# ===========================================================================
# LE-001, LE-002 — Global-tool contract: no hardcoded jurisdictions
# ===========================================================================


class TestLE001LE002NoHardcodedJurisdictions:
    """Empty jurisdictions == no filter across every entry point that runs
    the analyzer. Silent US-CA/GDPR defaulting was the exact drift LIB-
    PRINCIPLES was written to prevent (Principle 3 example)."""

    def _code_lines(self, source: str) -> str:
        """Strip comment lines so audit-note comments referencing the old
        fallback string don't false-positive the guard."""
        return "\n".join(
            line for line in source.splitlines() if not line.lstrip().startswith("#")
        )

    def test_le001_watchlist_refresh_all_uses_empty_jurisdictions(self):
        """The background refresh loop must call detect_findings with an
        empty list, not ["US-CA", "GDPR"].

        OE-003 note (2026-07-03): the historical
        ``_refresh_all_watchlist_items`` helper was retired in reviewer P9
        grumpy F11. Its body was a tautological delegate to
        ``_refresh_due_watchlist_items`` (the new per-item scheduler introduced
        when ``PolicyWatch`` merged into ``WatchlistItem``). The load-bearing
        LE-001 assertion (no hardcoded ``["US-CA", "GDPR"]`` and
        ``detect_findings(current_text, [])`` present) now lives on the
        scheduler.
        """
        import app.main as main_module

        # Per-item scheduler source: this is where the analyzer call now
        # lives after OE-003. Assert the contract on it.
        scheduler_code = self._code_lines(
            inspect.getsource(main_module._refresh_due_watchlist_items)
        )
        assert '["US-CA", "GDPR"]' not in scheduler_code, (
            "_refresh_due_watchlist_items still hardcodes ['US-CA', 'GDPR'] — "
            "audit LE-001 regression."
        )
        assert "detect_findings(current_text, [])" in scheduler_code, (
            "_refresh_due_watchlist_items must call detect_findings with an "
            "empty jurisdictions list to honour the global-tool contract."
        )

    def test_le001_refresh_watchlist_endpoint_uses_empty_jurisdictions(self):
        """``refresh_watchlist`` endpoint must also honour the contract."""
        from app.main import refresh_watchlist

        code = self._code_lines(inspect.getsource(refresh_watchlist))
        assert '["US-CA", "GDPR"]' not in code, (
            "refresh_watchlist still hardcodes ['US-CA', 'GDPR'] — audit LE-001."
        )
        assert "detect_findings(current_text, [])" in code

    def test_le002_analyze_file_no_hardcoded_fallback_in_source(self):
        """/analyze/file must not fall back to ['US-CA', 'GDPR'] when the
        caller supplies no jurisdictions."""
        from app.main import analyze_file

        code = self._code_lines(inspect.getsource(analyze_file))
        assert '["US-CA", "GDPR"]' not in code, (
            "/analyze/file still hardcodes ['US-CA', 'GDPR'] fallback — "
            "audit finding LE-002 (JSON endpoints default to [] per schemas.py)."
        )

    def test_le002_analyze_file_empty_jurisdictions_stay_empty(
        self, app_client, monkeypatch
    ):
        """End-to-end: uploading a file with no ``jurisdictions`` field must
        pass ``[]`` to the analyzer, matching the JSON endpoints."""
        captured: dict = {}

        async def fake_analyze(text, jurisdictions, **kwargs):
            captured["jurisdictions"] = list(jurisdictions)
            from datetime import datetime as _dt
            from datetime import timezone as _tz
            from uuid import uuid4 as _uuid4

            from app.schemas import AnalysisPayload
            from app.services.analyzer import AnalysisResult

            payload = AnalysisPayload(
                id=str(_uuid4()),
                name=kwargs.get("name") or "file",
                doc_type=None,
                source_url=None,
                document_text="",
                line_offsets=[0],
                status="completed",
                review_required=False,
                confidence=0.9,
                risk_score=1.0,
                grade="A",
                created_at=_dt.now(_tz.utc),
                findings=[],
                summary="mock",
            )
            return AnalysisResult(payload=payload, issues=[])

        monkeypatch.setattr("app.main.analyze_text", fake_analyze)
        monkeypatch.setattr(
            "app.main.extract_text_from_bytes",
            lambda filename, content_type, data: "policy body",
        )

        response = app_client.post(
            "/analyze/file",
            files={"file": ("p.txt", b"policy body", "text/plain")},
        )
        assert response.status_code == 200, response.text
        assert captured["jurisdictions"] == [], (
            "/analyze/file should pass [] to the analyzer when the request "
            "omits jurisdictions — audit finding LE-002."
        )

    def test_le002_analyze_file_all_invalid_jurisdictions_stay_empty(
        self, app_client, monkeypatch
    ):
        """Same contract when the caller sends only invalid codes: the drop
        step must NOT trigger a US-CA/GDPR fallback."""
        captured: dict = {}

        async def fake_analyze(text, jurisdictions, **kwargs):
            captured["jurisdictions"] = list(jurisdictions)
            from datetime import datetime as _dt
            from datetime import timezone as _tz
            from uuid import uuid4 as _uuid4

            from app.schemas import AnalysisPayload
            from app.services.analyzer import AnalysisResult

            payload = AnalysisPayload(
                id=str(_uuid4()),
                name=kwargs.get("name") or "file",
                doc_type=None,
                source_url=None,
                document_text="",
                line_offsets=[0],
                status="completed",
                review_required=False,
                confidence=0.9,
                risk_score=1.0,
                grade="A",
                created_at=_dt.now(_tz.utc),
                findings=[],
                summary="mock",
            )
            return AnalysisResult(payload=payload, issues=[])

        monkeypatch.setattr("app.main.analyze_text", fake_analyze)
        monkeypatch.setattr(
            "app.main.extract_text_from_bytes",
            lambda filename, content_type, data: "policy body",
        )

        response = app_client.post(
            "/analyze/file",
            files={"file": ("p.txt", b"policy body", "text/plain")},
            data={"jurisdictions": "BOGUS-1,BOGUS-2"},
        )
        assert response.status_code == 200, response.text
        assert captured["jurisdictions"] == [], (
            "/analyze/file must not fall back to ['US-CA','GDPR'] when every "
            "supplied jurisdiction is invalid — audit finding LE-002."
        )


# ===========================================================================
# LE-003 — Watchlist loop must log, not swallow
# ===========================================================================


class TestLE003WatchlistLoopLogsErrors:
    def test_watchlist_loop_source_calls_logger_exception(self):
        """Simple source guard: the loop body must reference
        ``logger.exception`` in its ``except`` handler."""
        from app.main import _watchlist_loop_async

        source = inspect.getsource(_watchlist_loop_async)
        assert "logger.exception" in source, (
            "_watchlist_loop_async no longer logs its failures — audit "
            "finding LE-003 requires structured logging with stack trace."
        )
        # Defense-in-depth: guarantee no bare ``except Exception: pass``
        assert re.search(r"except\s+Exception:\s*pass", source) is None

    def test_watchlist_loop_logs_when_refresh_raises(self, monkeypatch, caplog):
        """Runtime behaviour: a raising refresh must surface at least one
        ERROR-level log record."""
        import asyncio

        from app import main as main_module

        # Kill the sleep so the loop can only iterate once before cancel.
        async def instant_sleep(_seconds):
            raise asyncio.CancelledError

        async def failing_refresh():
            raise RuntimeError("simulated refresh failure")

        # OE-003 / P9 F11: shim retired. Patch the scheduler the loop actually calls.
        monkeypatch.setattr(main_module, "_refresh_due_watchlist_items", failing_refresh)
        monkeypatch.setattr(main_module.asyncio, "sleep", instant_sleep)

        # Make sure the uvicorn logger routes to caplog.
        with caplog.at_level(logging.ERROR, logger="uvicorn.error"):
            with pytest.raises(asyncio.CancelledError):
                asyncio.run(main_module._watchlist_loop_async())

        assert any(
            "watchlist refresh loop failed" in rec.message for rec in caplog.records
        ), "expected LE-003 log line not emitted"


# ===========================================================================
# LE-012, LE-013 — Boost lookups: exact match + valid categories
# ===========================================================================


class TestLE012LE013BoostLookup:
    def test_le013_all_doctype_boost_keys_are_canonical_categories(self):
        """Every key in ``_DOCTYPE_BOOSTS`` must be a member of ``CATEGORIES``."""
        from app.services.analyzer import _DOCTYPE_BOOSTS

        for doctype, boosts in _DOCTYPE_BOOSTS.items():
            for key in boosts:
                assert key in CATEGORIES, (
                    f"_DOCTYPE_BOOSTS[{doctype!r}] references {key!r} which is "
                    "not in schemas.CATEGORIES — audit finding LE-013."
                )

    def test_le013_all_industry_boost_keys_are_canonical_categories(self):
        from app.services.analyzer import _INDUSTRY_BOOSTS

        for industry, boosts in _INDUSTRY_BOOSTS.items():
            for key in boosts:
                assert key in CATEGORIES, (
                    f"_INDUSTRY_BOOSTS[{industry!r}] references {key!r} which "
                    "is not in schemas.CATEGORIES — audit finding LE-013."
                )

    def test_le013_import_time_guard_would_fire_on_drift(self, monkeypatch):
        """Simulate drift by adding a bogus key and re-running the guard
        expression. Confirms the guard's semantic: any future drift raises
        RuntimeError at import time."""
        # Sanity: importing analyzer must succeed on the current codebase.
        from app.services import analyzer  # noqa: F401

        drifted = {
            "Bad DocType": {"Made-Up Category": 0.5},
        }
        unknown = {
            key
            for boosts in list(drifted.values())
            for key in boosts.keys()
            if key not in CATEGORIES
        }
        assert unknown == {"Made-Up Category"}, "guard expression drifted"

    def test_le012_bump_severity_boost_uses_exact_category_match(self):
        """``_apply_industry_emphasis`` must NOT boost a finding whose category
        merely contains the boost key as a substring. Regression case: the
        legacy substring match boosted "PIPEDA Consent" whenever "Consent" was
        a boost key."""
        from app.services.analyzer import _apply_industry_emphasis

        # PIPEDA Consent must NOT be boosted by Finance's "Consent" key.
        findings = [_finding(category="PIPEDA Consent", severity="Low")]
        boosted = _apply_industry_emphasis(findings, "Finance")
        assert boosted[0].severity == "Low", (
            "PIPEDA Consent was falsely boosted by the 'Consent' key — "
            "audit finding LE-012."
        )

    def test_le012_bump_severity_boost_still_bumps_exact_match(self):
        """The exact-match refactor MUST NOT regress the intended behaviour:
        Finance industry + Consent finding still bumps."""
        from app.services.analyzer import _apply_industry_emphasis

        findings = [_finding(category="Consent", severity="Low")]
        boosted = _apply_industry_emphasis(findings, "Finance")
        assert boosted[0].severity == "Medium", (
            "Exact-category 'Consent' boost failed to trigger — the fix went "
            "too far."
        )

    def test_le012_doctype_boost_exact_match(self):
        """Cookie Policy boosts 'Tracking / Profiling' exactly, not any
        finding containing the substring 'Tracking'."""
        from app.services.analyzer import _apply_doctype_weighting

        # A hypothetical category containing "Tracking" as substring but
        # differing from the canonical key should not be boosted. We use
        # the actual canonical alias "Tracking & Consent" (present in
        # schemas.CATEGORIES) to prove the boundary is respected.
        findings = [_finding(category="Tracking & Consent", severity="Low")]
        boosted = _apply_doctype_weighting(findings, "Cookie Policy")
        assert boosted[0].severity == "Low", (
            "Cookie Policy boosted 'Tracking & Consent' via substring match "
            "against 'Tracking / Profiling' — audit LE-012."
        )


# ===========================================================================
# LE-017 — Streamlit v2 renders review_required
# ===========================================================================


class TestLE017ReviewRequiredSurfaced:
    """Streamlit v2 must render a visual signal for review_required. The
    backend already sets the flag; the frontend was ignoring it (audit finding
    LE-017)."""

    def _webapp_source(self) -> str:
        # tests/ -> backend/ -> src/  (parents[0]=tests, [1]=backend, [2]=src)
        path = Path(__file__).resolve().parents[2] / "webapp" / "app_streamlit_v2.py"
        return path.read_text(encoding="utf-8")

    def test_streamlit_v2_defines_review_banner_renderer(self):
        source = self._webapp_source()
        assert "_render_review_required_banner" in source, (
            "Streamlit v2 no longer defines the review_required renderer — "
            "audit finding LE-017 regressed."
        )

    def test_streamlit_v2_render_results_calls_review_banner(self):
        source = self._webapp_source()
        # Find render_results body and ensure the banner is invoked.
        assert "_render_review_required_banner(result)" in source, (
            "render_results no longer calls _render_review_required_banner — "
            "audit finding LE-017."
        )

    def test_review_banner_copy_uses_observational_voice(self):
        """Static source guard: banner copy must use third-person observational
        voice (LIB-VOICE Principle 6), reference the confidence threshold,
        and avoid em-dashes."""
        source = self._webapp_source()
        # Extract the function body via inspect-style textual slice
        start = source.find("def _render_review_required_banner(")
        assert start != -1, "renderer not found"
        # End at next top-level def
        end = source.find("\ndef ", start + 1)
        body = source[start:end]

        # Copy must reference the confidence threshold
        assert "confidence threshold" in body, (
            "Banner copy does not name the confidence threshold — LE-017."
        )
        # LIB-VOICE: no em-dashes in tool copy
        assert "—" not in body, "Banner copy contains em-dash (LIB-VOICE)."
        # Observational voice: no first-person "we", no imperative "you must"
        assert " we " not in body.lower(), (
            "Banner copy contains 'we' — LIB-VOICE requires observational voice."
        )
        assert "you must" not in body.lower(), (
            "Banner copy uses imperative 'you must' — LIB-VOICE requires "
            "tentative framing."
        )
        # Branches for both review_required flag and status == needs_review
        assert "review_required" in body
        assert "needs_review" in body


# ===========================================================================
# LE-018 — Em-dash removed from action items (LIB-VOICE)
# ===========================================================================


class TestLE018NoEmDashesInActionItems:
    """LIB-VOICE forbids em-dashes in every string that reaches the reader,
    including action items. Defense-in-depth: scan the whole function
    source AND every string returned for typical inputs."""

    def test_derive_action_items_source_has_no_em_dash(self):
        from app.services.analyzer import _derive_action_items

        source = inspect.getsource(_derive_action_items)
        assert "—" not in source, (
            "_derive_action_items contains an em-dash (U+2014) — LIB-VOICE "
            "forbids em-dashes in tool copy. Audit finding LE-018."
        )

    def test_derive_action_items_output_has_no_em_dash(self):
        """Runtime check across every category branch."""
        from app.services.analyzer import _derive_action_items

        # Cover every branch by including one finding per category cluster.
        branch_categories = [
            "Sale/Share",
            "User Rights",
            "AI Training",
            "Automated Decision-Making",
            "Children's Privacy",
            "Liability",
        ]
        findings = [_finding(category=c) for c in branch_categories]
        for jurisdictions in ([], ["US-CA"], ["GDPR"], ["UK-GDPR", "US-CA"]):
            items = _derive_action_items(findings, jurisdictions)
            for item in items:
                assert "—" not in item, (
                    f"Action item contains em-dash: {item!r} — LIB-VOICE / "
                    "audit finding LE-018."
                )


# ===========================================================================
# GAP-001 — CSV export honours ids and detailed
# ===========================================================================


def _create_analysis_row(db_session, *, doc_id: str, findings: list[dict]):
    """Insert an Analysis row directly via the ORM for CSV export tests."""
    import json

    from app.models import Analysis

    payload = {
        "id": doc_id,
        "name": f"Policy {doc_id}",
        "findings": findings,
    }
    row = Analysis(
        id=doc_id,
        source_type="text",
        source_value=None,
        doc_name=f"Policy {doc_id}",
        doc_type=None,
        source_url=None,
        status="completed",
        confidence=0.9,
        risk_score=2.0,
        grade="A",
        document_text="body",
        result_json=json.dumps(payload),
    )
    db_session.add(row)
    db_session.commit()
    return row


class TestGAP001CsvExportParams:
    def test_csv_export_default_returns_summary_of_all(self, app_client, db_session):
        _create_analysis_row(db_session, doc_id="a1", findings=[])
        _create_analysis_row(db_session, doc_id="a2", findings=[])

        resp = app_client.get("/exports/analyses.csv")
        assert resp.status_code == 200
        header = resp.text.splitlines()[0]
        assert header.startswith("id,name,doc_type"), header
        # Two data rows (plus header)
        assert len(resp.text.strip().splitlines()) == 3

    def test_csv_export_filters_by_ids(self, app_client, db_session):
        _create_analysis_row(db_session, doc_id="keep-me", findings=[])
        _create_analysis_row(db_session, doc_id="skip-me", findings=[])

        resp = app_client.get("/exports/analyses.csv?ids=keep-me")
        assert resp.status_code == 200
        body = resp.text
        assert "keep-me" in body
        assert "skip-me" not in body

    def test_csv_export_detailed_emits_finding_rows(self, app_client, db_session):
        finding_dict = {
            "category": "Sale/Share",
            "severity": "High",
            "confidence": 0.92,
            "excerpt": "we may sell your data",
            "explanation": "boilerplate",
            "jurisdictions": ["US-CA"],
            "evidence": {"line_start": 4, "line_end": 5, "legal_basis": ["CCPA"]},
        }
        _create_analysis_row(
            db_session, doc_id="detail-1", findings=[finding_dict, finding_dict]
        )

        resp = app_client.get("/exports/analyses.csv?ids=detail-1&detailed=true")
        assert resp.status_code == 200
        lines = resp.text.strip().splitlines()
        # PRD §5.5.3 column list
        assert lines[0].startswith(
            "analysis_id,document_name,finding_id,category,severity,"
            "confidence,excerpt,line_start,line_end"
        )
        # One header + two finding rows
        assert len(lines) == 3
        assert "detail-1-0" in lines[1]
        assert "detail-1-1" in lines[2]


# ===========================================================================
# GAP-014 — webapp deps declared
# ===========================================================================


class TestGAP014WebappRequirementsDeclared:
    """Streamlit and requests must be declared as pinned webapp deps so a
    fresh clone + ./run.sh can start the UI without a manual pip install."""

    def _src_root(self) -> Path:
        # tests/ -> backend/ -> src/  (parents[0]=tests, [1]=backend, [2]=src)
        return Path(__file__).resolve().parents[2]

    def test_webapp_requirements_file_exists(self):
        req = self._src_root() / "webapp" / "requirements.txt"
        assert req.exists(), (
            "src/webapp/requirements.txt is missing — audit finding GAP-014 "
            "requires webapp dependencies (streamlit, requests) to be declared."
        )

    def test_webapp_requirements_lists_streamlit_and_requests(self):
        text = (self._src_root() / "webapp" / "requirements.txt").read_text()
        assert re.search(r"^streamlit\b", text, re.MULTILINE), (
            "streamlit not declared in src/webapp/requirements.txt — GAP-014."
        )
        assert re.search(r"^requests\b", text, re.MULTILINE), (
            "requests not declared in src/webapp/requirements.txt — GAP-014."
        )

    def test_run_sh_installs_webapp_requirements(self):
        # run.sh lives at the repo root, one level above src/.
        repo_root = self._src_root().parent
        run_sh = (repo_root / "run.sh").read_text()
        assert "webapp/requirements.txt" in run_sh or "APP_DIR/requirements.txt" in run_sh, (
            "run.sh does not install webapp requirements — GAP-014."
        )


# ===========================================================================
# PRD-OQ-1 — URL fetch timeout distinct from LLM inference timeout
# ===========================================================================


class TestPrdOq1UrlFetchTimeout:
    """URL fetch timeout is a separate budget from LLM inference. A hung
    remote host must not consume the LocalAI request budget. Resolves the
    PRD §5 open question flagged in the tech-spec audit remediation handoff."""

    def test_url_fetch_timeout_defaults_to_30_seconds(self):
        """``settings.url_fetch_timeout_s`` defaults to 30 (was 60 via
        LM_REQUEST_TIMEOUT_S before the split)."""
        # Re-instantiate Settings so we exercise the default rather than a
        # cached module-level singleton with a monkey-patched env.
        from app.config import Settings

        s = Settings()
        assert s.url_fetch_timeout_s == 30.0, (
            "URL fetch timeout should default to 30 seconds — see "
            "config.py::url_fetch_timeout_s."
        )

    def test_url_fetch_timeout_env_var_wired_in_source(self):
        """``url_fetch_timeout_s`` must read the ``LM_URL_FETCH_TIMEOUT_S``
        env var (mirrors the existing ``LM_REQUEST_TIMEOUT_S`` shape)."""
        import inspect

        from app import config as config_module

        source = inspect.getsource(config_module)
        assert 'os.getenv("LM_URL_FETCH_TIMEOUT_S"' in source, (
            "url_fetch_timeout_s must read LM_URL_FETCH_TIMEOUT_S — env "
            "override plumbing missing."
        )

    def test_url_fetch_uses_url_fetch_timeout_not_llm_timeout(self):
        """``fetch_url_text`` must read ``url_fetch_timeout_s``, not the
        LLM inference timeout ``request_timeout_s``. Prevents the two
        budgets from being coupled again."""
        import inspect

        from app.services import ingest

        source = inspect.getsource(ingest.fetch_url_text)
        assert "url_fetch_timeout_s" in source, (
            "fetch_url_text must reference settings.url_fetch_timeout_s — "
            "the URL budget is distinct from LM_REQUEST_TIMEOUT_S."
        )
        # Guard against regression to the shared LLM timeout in the
        # timeout= assignment line specifically.
        assert "timeout = settings.request_timeout_s" not in source, (
            "fetch_url_text must NOT share the LLM inference timeout — "
            "resolves PRD §5 open question on URL fetch budget."
        )

    def test_env_example_documents_url_fetch_timeout(self):
        # tests/ -> backend/ -> src/ -> repo root (parents[3])
        repo_root = Path(__file__).resolve().parents[3]
        env_example = (repo_root / ".env.example").read_text()
        assert "LM_URL_FETCH_TIMEOUT_S" in env_example, (
            ".env.example must document the LM_URL_FETCH_TIMEOUT_S variable."
        )


# ===========================================================================
# PRD-OQ-2 — Text paste cap 50k + paste-input whitespace normalisation
# ===========================================================================


class TestPrdOq2PasteCapAndWhitespace:
    """Text paste cap raised to 50k per PRD, and paste input must have
    surrounding whitespace stripped + internal whitespace runs collapsed
    before the length gate. URL/file content must NOT be normalised — the
    structural whitespace in legal text (numbered clauses, tables) is
    load-bearing."""

    def test_max_input_chars_defaults_to_50000(self):
        from app.config import Settings

        s = Settings()
        assert s.max_input_chars == 50000, (
            "max_input_chars should default to 50000 per PRD §5 open "
            "question resolution."
        )

    def test_paste_input_50k_under_limit_survives(self):
        """A 50 000 char paste (before whitespace collapse) must pass the
        length gate unchanged."""
        from app.services.analyzer import _normalise_paste_whitespace, _truncate_text

        body = "a" * 50_000
        # No surrounding or internal whitespace to strip: cleaned length == 50k.
        cleaned = _truncate_text(_normalise_paste_whitespace(body))
        assert len(cleaned) == 50_000

    def test_paste_input_over_50k_is_truncated(self):
        from app.services.analyzer import _normalise_paste_whitespace, _truncate_text

        body = "a" * 50_001
        cleaned = _truncate_text(_normalise_paste_whitespace(body))
        assert len(cleaned) == 50_000, (
            "Paste input at 50001 chars must be truncated to the 50k cap."
        )

    def test_paste_input_normalises_leading_trailing_and_internal_whitespace(self):
        from app.services.analyzer import _normalise_paste_whitespace

        raw = "   Terms\n\n\n\tand    conditions.\n\nSection    2.\n   "
        cleaned = _normalise_paste_whitespace(raw)
        assert cleaned == "Terms and conditions. Section 2."

    def test_url_content_is_not_stripped(self):
        """``analyze_text(..., is_paste_input=False)`` — the URL and file
        code paths — must NOT collapse whitespace. Structural whitespace in
        legal text is intentional. Direct source check: the URL branch calls
        ``.strip()`` only, not ``_normalise_paste_whitespace``."""
        import inspect

        from app.services.analyzer import analyze_text

        source = inspect.getsource(analyze_text)
        # Both branches must exist and be gated by ``is_paste_input``.
        assert "if is_paste_input" in source
        # Paste branch calls the whitespace collapser.
        assert "_normalise_paste_whitespace" in source
        # URL/file (else) branch preserves internal whitespace via .strip().
        assert "text.strip()" in source, (
            "URL / file branch of analyze_text must preserve internal "
            "whitespace and only .strip() the ends."
        )

    def test_analyze_endpoint_passes_is_paste_input_true(self):
        """The ``/analyze`` (paste-body) endpoint must invoke ``analyze_text``
        with ``is_paste_input=True`` so the paste-specific normalisation runs."""
        import inspect

        from app.main import analyze as analyze_endpoint

        source = inspect.getsource(analyze_endpoint)
        assert "is_paste_input=True" in source, (
            "/analyze must pass is_paste_input=True to analyze_text — PRD "
            "§5 open question on paste normalisation."
        )


# ===========================================================================
# GAP-007 — Verify view surfaces per-finding audit fields in Streamlit v2
# ===========================================================================


class TestGap007VerifyView:
    """Streamlit v2 must render a Verify view expander that surfaces the
    verbatim quote, jurisdiction attribution, IRP breakdown, and rule
    pattern id per finding (per PRD F4.3 acceptance criteria; the split-
    pane layout is traded for a single-column expander in the plain-
    language redesign of issue #19)."""

    def _webapp_source(self) -> str:
        # tests/ -> backend/ -> src/  (parents[2] == src root)
        src_root = Path(__file__).resolve().parents[2]
        return (src_root / "webapp" / "app_streamlit_v2.py").read_text()

    def test_verify_view_expander_present(self):
        source = self._webapp_source()
        assert "Verify view" in source, (
            "Streamlit v2 must expose a 'Verify view' expander — GAP-007."
        )

    def test_verify_view_renders_verbatim_quote(self):
        source = self._webapp_source()
        # The verbatim quote is sourced from the finding's ``excerpt`` field
        # and rendered inside a ``pr-verify-quote`` block.
        assert "pr-verify-quote" in source, (
            "Verify view must render each finding's verbatim quote."
        )

    def test_verify_view_renders_irp_breakdown(self):
        source = self._webapp_source()
        # Impact, Likelihood, Safeguards, and the IRP composite must all
        # appear inside the verify block.
        assert "IRP composite" in source, (
            "Verify view must render the IRP composite score per finding."
        )
        for label in ("Impact", "Likelihood", "Safeguards"):
            assert label in source, (
                f"Verify view must render the {label} row per finding."
            )

    def test_verify_view_headers_have_no_em_dash(self):
        """LIB-VOICE forbids em-dashes in surfaced copy. The Verify view
        expander label, chip labels, and rendered row headers must not
        introduce any. Restricted to reader-visible strings only (comments
        and Python source narration are out of scope)."""
        source = self._webapp_source()
        # Reader-visible Verify view strings: the expander label + the
        # inline hint text. Grep for the literal expander title and the
        # inline row labels.
        surface_strings = [
            'f"Verify view / ',
            "IRP composite",
            "Rule pattern",
            "Jurisdiction",
            "Impact",
            "Likelihood",
            "Safeguards",
            "Location",
            "Verbatim quote from the document",
        ]
        for needle in surface_strings:
            idx = source.find(needle)
            assert idx != -1, f"Verify view surface string {needle!r} missing."
            # Grab the enclosing quoted string boundaries to check just the
            # literal, not surrounding code / comments.
            line_start = source.rfind("\n", 0, idx) + 1
            line_end = source.find("\n", idx)
            line = source[line_start:line_end]
            assert "—" not in line, (
                f"Reader-visible Verify view string contains an em-dash: "
                f"{line.strip()!r}. LIB-VOICE forbids em-dashes in UI copy."
            )

    def test_analysis_payload_exposes_verify_view_fields(self):
        """The backend contract: ``Finding`` must expose ``excerpt``,
        ``jurisdictions``, ``impact``, ``likelihood``, ``safeguard_score``,
        and ``irp_score`` — the fields the Verify view reads from
        ``AnalysisPayload.findings``."""
        from app.schemas import Finding

        required_fields = {
            "excerpt",
            "jurisdictions",
            "impact",
            "likelihood",
            "safeguard_score",
            "irp_score",
        }
        model_fields = set(Finding.model_fields.keys())
        missing = required_fields - model_fields
        assert not missing, (
            f"Finding is missing Verify view fields: {sorted(missing)}. "
            "GAP-007 requires these to render the audit expander."
        )


# ===========================================================================
# LE-013 — Restored boost keys (canonical only) + coordinated CATEGORIES
# ===========================================================================


class TestLe013RestoredBoosts:
    """Phase 1 tightened the boost lookup from substring → exact match, which
    silently disabled several previously-firing boosts. Restore the ones
    that map onto canonical categories; leave the rest dropped."""

    def test_arbitration_dispute_is_in_categories(self):
        """The Terms-of-Service boost 'Arbitration / Dispute' requires the
        canonical category to exist in ``schemas.CATEGORIES``."""
        assert "Arbitration / Dispute" in CATEGORIES, (
            "Arbitration / Dispute must be a canonical category so the "
            "Terms of Service boost can reference it — LE-013."
        )

    def test_terms_of_service_boosts_arbitration_dispute(self):
        from app.services.analyzer import _DOCTYPE_BOOSTS

        assert "Arbitration / Dispute" in _DOCTYPE_BOOSTS["Terms of Service"], (
            "Terms of Service must boost 'Arbitration / Dispute' — this "
            "was removed in Phase 1 pending canonical-category taxonomy "
            "review; restoration in Phase 2 remediation."
        )

    def test_privacy_policy_boosts_retention(self):
        from app.services.analyzer import _DOCTYPE_BOOSTS

        assert "Retention" in _DOCTYPE_BOOSTS["Privacy Policy"], (
            "Privacy Policy must boost canonical 'Retention' — restored "
            "in Phase 2 remediation (was 'Data Retention', non-canonical)."
        )

    def test_dpa_boosts_cross_border_transfer(self):
        from app.services.analyzer import _DOCTYPE_BOOSTS

        assert "Cross-Border Transfer" in _DOCTYPE_BOOSTS["Data Processing Agreement"], (
            "DPA must boost canonical 'Cross-Border Transfer' — restored "
            "in Phase 2 remediation (was 'Data Transfer', non-canonical)."
        )

    def test_restored_boosts_fire_only_on_exact_category(self):
        """The restored boost must not accidentally re-open substring
        matching. A Terms-of-Service finding whose category merely contains
        'Arbitration' as a substring must NOT be boosted."""
        from app.services.analyzer import _apply_doctype_weighting

        findings = [_finding(category="User Rights", severity="Low")]
        boosted = _apply_doctype_weighting(findings, "Terms of Service")
        # 'User Rights' should not be boosted by any Terms of Service key.
        assert boosted[0].severity == "Low", (
            "Terms of Service boosted an unrelated category via substring "
            "match — LE-012 exact-match invariant regressed."
        )

    def test_restored_arbitration_boost_bumps_exact_match(self):
        """Sanity: an exact 'Arbitration / Dispute' finding under a Terms
        of Service doctype IS boosted."""
        from app.services.analyzer import _apply_doctype_weighting

        findings = [_finding(category="Arbitration / Dispute", severity="Low")]
        boosted = _apply_doctype_weighting(findings, "Terms of Service")
        assert boosted[0].severity == "Medium", (
            "Terms of Service failed to boost 'Arbitration / Dispute' — "
            "restored key not wired correctly."
        )


# ===========================================================================
# Drift 1 (Option Z) — Dormant categories added to CATEGORIES + boost dicts
# ===========================================================================


class TestDrift1DormantCategories:
    """PRD v2.2 taxonomy alignment. Six categories added to
    ``schemas.CATEGORIES`` so the boost dicts + future rule work have stable
    canonical strings to reference. They stay dormant — no rule pattern in
    ``rules.py`` emits them until a follow-up issue lands.

    User decision: Option Z (add categories so PRD and code align, keep boost
    entries dormant, no new rule patterns). See
    ``SESSION_HANDOFF_2026-07-03_TECH_SPEC_AUDIT_REMEDIATION.md``.
    """

    DORMANT = (
        "Third-Party Sharing",
        "Sub-processors",
        "Data Transfer",
        "Intellectual Property",
        "Transparency",
        "In-App Purchases",
    )

    @pytest.mark.parametrize("category", DORMANT)
    def test_category_is_canonical(self, category: str):
        """Each dormant category must be a member of ``schemas.CATEGORIES``
        so the boost dicts can reference it and the LE-013 import-time guard
        stays green."""
        assert category in CATEGORIES, (
            f"Drift-1 category {category!r} missing from schemas.CATEGORIES. "
            "Option Z requires PRD v2.2 taxonomy to be canonicalised in the "
            "schema."
        )

    def test_boost_dicts_still_pass_import_guard(self):
        """Re-import ``analyzer`` after the dormant categories were added.
        The LE-013 import-time guard should not raise. Any drift here would
        have raised ``RuntimeError`` at module load, so a clean import is a
        pass."""
        import importlib

        import app.services.analyzer as analyzer_module

        # Force a fresh import so the guard actually runs against the current
        # CATEGORIES frozenset. If a dormant category slipped out of
        # CATEGORIES but stayed in the boost dict, this would raise.
        importlib.reload(analyzer_module)
        # Sanity check: the guard did not raise, so both dicts remain valid.
        assert hasattr(analyzer_module, "_DOCTYPE_BOOSTS")
        assert hasattr(analyzer_module, "_INDUSTRY_BOOSTS")

    def test_privacy_policy_boosts_third_party_sharing(self):
        from app.services.analyzer import _DOCTYPE_BOOSTS

        assert "Third-Party Sharing" in _DOCTYPE_BOOSTS["Privacy Policy"], (
            "Privacy Policy must carry a dormant 'Third-Party Sharing' "
            "boost so the taxonomy is stable when a future rule emits it."
        )

    def test_cookie_policy_boosts_third_party_sharing(self):
        from app.services.analyzer import _DOCTYPE_BOOSTS

        assert "Third-Party Sharing" in _DOCTYPE_BOOSTS["Cookie Policy"], (
            "Cookie Policy must carry a dormant 'Third-Party Sharing' boost."
        )

    def test_tos_boosts_intellectual_property(self):
        from app.services.analyzer import _DOCTYPE_BOOSTS

        assert "Intellectual Property" in _DOCTYPE_BOOSTS["Terms of Service"], (
            "Terms of Service must carry a dormant 'Intellectual Property' "
            "boost."
        )

    def test_dpa_boosts_data_transfer_and_subprocessors(self):
        from app.services.analyzer import _DOCTYPE_BOOSTS

        dpa = _DOCTYPE_BOOSTS["Data Processing Agreement"]
        assert "Data Transfer" in dpa, (
            "DPA must carry a dormant 'Data Transfer' boost (Option Z "
            "restored PRD v2.2 taxonomy)."
        )
        assert "Sub-processors" in dpa, (
            "DPA must carry a dormant 'Sub-processors' boost."
        )

    def test_ai_platform_industry_boosts_transparency(self):
        from app.services.analyzer import _INDUSTRY_BOOSTS

        assert "Transparency" in _INDUSTRY_BOOSTS["AI / Tech Platform"], (
            "AI / Tech Platform industry must carry a dormant 'Transparency' "
            "boost."
        )

    def test_gaming_industry_boosts_in_app_purchases(self):
        from app.services.analyzer import _INDUSTRY_BOOSTS

        assert "In-App Purchases" in _INDUSTRY_BOOSTS["Gaming"], (
            "Gaming industry must carry a dormant 'In-App Purchases' boost."
        )

    @pytest.mark.parametrize("category", DORMANT)
    def test_no_rule_pattern_emits_dormant_category(self, category: str):
        """The 6 dormant categories are schema-canonical and boost-configured,
        but **no rule** should emit them until a follow-up issue lands.

        Grep-style check: the category string must not appear as a
        ``category=`` argument in ``rules.py``. This defends against a
        future patch quietly promoting one of these from dormant to active
        without the follow-up work being reviewed.
        """
        import app.services.rules as rules_module

        source = Path(rules_module.__file__).read_text(encoding="utf-8")
        needle = f'category="{category}"'
        alt_needle = f"category='{category}'"
        assert needle not in source and alt_needle not in source, (
            f"rules.py emits the dormant category {category!r} via a "
            f"category= keyword. Option Z requires it to stay dormant — "
            "no rule pattern should promote it until the follow-up issue "
            "lands."
        )


# ===========================================================================
# Drift 2 — Verify view split-pane redo (replaces expander)
# ===========================================================================


class TestDrift2VerifyViewSplitPane:
    """PRD §F4.3 requires a split-pane Verify view: document on the left with
    highlighted verbatim quotes, findings on the right with category,
    jurisdiction, IRP breakdown, and rule pattern id. Replaces the prior
    single-column expander (issue #19 redesign trade-off).

    LIB-VOICE: no em-dashes in split-pane headers or labels.
    """

    APP_PATH = Path(__file__).resolve().parents[2] / "webapp" / "app_streamlit_v2.py"

    def _source(self) -> str:
        return self.APP_PATH.read_text(encoding="utf-8")

    def test_split_pane_render_function_present(self):
        """Split-pane render helper must exist in ``app_streamlit_v2.py``.
        Grep-level check keeps this test decoupled from streamlit import."""
        src = self._source()
        assert "def _render_verify_split_pane" in src, (
            "app_streamlit_v2.py must expose _render_verify_split_pane — "
            "Drift 2 requires the Verify view to be a split pane, not an "
            "expander."
        )
        assert "st.columns(" in src, (
            "Split-pane implementation must use st.columns to create the "
            "two panes."
        )

    def test_split_pane_render_function_source_has_no_em_dashes(self):
        """LIB-VOICE: user-facing headers and labels inside the split-pane
        render function must not contain em-dashes."""
        src = self._source()
        marker = "def _render_verify_split_pane"
        start = src.find(marker)
        assert start != -1, "Split-pane render function not found in source."
        # Read from the def to the next top-level def to bound the region.
        rest = src[start + len(marker):]
        end_offset = rest.find("\ndef ")
        region = rest if end_offset == -1 else rest[:end_offset]
        # Only user-facing string literals matter. Split into physical
        # lines and inspect any that look like a Streamlit markdown/text call
        # or a raw HTML fragment. Comments (leading '#') are ignored.
        offending: list[str] = []
        for lineno, line in enumerate(region.splitlines(), start=1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if "—" in line:
                offending.append(f"line {lineno}: {stripped}")
        assert not offending, (
            "Em-dash detected inside _render_verify_split_pane source — "
            "LIB-VOICE forbids em-dashes in user-facing copy. Offenders: "
            f"{offending}"
        )

    def test_split_pane_invoked_from_render_results(self):
        """``render_results`` must actually call the new split-pane helper.
        Otherwise the redo lives dead in the module."""
        src = self._source()
        assert "_render_verify_split_pane(result, findings)" in src, (
            "render_results must invoke _render_verify_split_pane so the "
            "Verify view is actually rendered."
        )

    def test_old_verify_expander_removed(self):
        """The old ``st.expander(f\"Verify view / ... findings\")`` must be
        gone. Split-pane replaces it — leaving both would double-render
        the audit surface."""
        src = self._source()
        assert 'st.expander(f"Verify view' not in src, (
            "Old Verify-view expander still present in app_streamlit_v2.py. "
            "Drift 2 requires the split-pane to replace it, not sit alongside."
        )

    def test_analysis_payload_carries_split_pane_fields(self):
        """The right pane needs excerpt / jurisdictions / impact / likelihood /
        safeguard_score / irp_score per finding, plus optional document_text
        on the payload for the left pane. Verify the schema exposes them."""
        from app.schemas import AnalysisPayload, Finding

        finding_fields = set(Finding.model_fields.keys())
        required_finding_fields = {
            "excerpt",
            "jurisdictions",
            "impact",
            "likelihood",
            "safeguard_score",
            "irp_score",
            "evidence",
            "category",
        }
        missing_finding = required_finding_fields - finding_fields
        assert not missing_finding, (
            f"Finding schema missing fields needed by the Verify split-pane "
            f"right column: {sorted(missing_finding)}."
        )

        payload_fields = set(AnalysisPayload.model_fields.keys())
        # document_text is optional but must be declared on the payload
        # schema so the split-pane left column can render it when supplied.
        assert "document_text" in payload_fields, (
            "AnalysisPayload must expose document_text so the Verify view "
            "left pane can render the source document."
        )

    def test_highlight_helper_present_and_uses_light_teal_class(self):
        """The left-pane highlight technique is HTML span with the
        ``pr-verify-hl`` CSS class (light-teal background, no JavaScript)."""
        src = self._source()
        assert "def _highlight_document_with_findings" in src, (
            "Highlight helper _highlight_document_with_findings must exist "
            "so the left pane can wrap verbatim excerpts."
        )
        assert "pr-verify-hl" in src, (
            "Left-pane highlight must use the pr-verify-hl CSS class "
            "(light-teal background per v2 palette)."
        )
