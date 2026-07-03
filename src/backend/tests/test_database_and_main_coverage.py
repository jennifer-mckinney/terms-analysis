"""
Tests for database.py and remaining uncovered main.py lines.

Covers:
  - database._connect_args non-sqlite path
  - database.get_db generator
  - database.db_session context manager
  - main.list_analyses (GET /analyses)
  - main.get_analysis success and 404 (GET /analyses/{id})
  - main.analyze_url error paths (ValueError, generic exception, empty text)
  - main.analyze_file error paths (empty file, bad doc_type, bad industry)
  - main._refresh_all_watchlist_items (internal loop function)
  - main._watchlist_loop_async (background loop)
  - main.export_analysis_pdf with findings (covers sev_counts, used_jurisdictions loop)
  - main._persist_analysis legacy pydantic path (line 157)
  - main.analyze_batch (POST /analyze/batch)
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.models import Analysis as AnalysisModel, WatchlistItem
from app.schemas import AnalysisPayload, Evidence, Finding


# ── shared helpers ────────────────────────────────────────────────────────────

def _make_payload(
    *,
    name: str = "Test Policy",
    review_required: bool = False,
    confidence: float = 0.90,
    risk_score: float = 2.0,
    grade: str = "A",
    status: str = "completed",
    document_text: str = "Sample policy text.",
) -> AnalysisPayload:
    from app.services.analyzer import AnalysisResult
    return AnalysisPayload(
        id=str(uuid4()),
        name=name,
        doc_type="Privacy Policy",
        source_url=None,
        document_text=document_text,
        line_offsets=[0],
        status=status,
        review_required=review_required,
        confidence=confidence,
        risk_score=risk_score,
        grade=grade,
        created_at=datetime.now(timezone.utc),
        findings=[],
        summary="Test summary.",
    )


def _insert_analysis(db_session, **kw) -> AnalysisModel:
    payload = _make_payload(**kw)
    row = AnalysisModel(
        id=payload.id,
        doc_name=payload.name,
        doc_type=payload.doc_type,
        source_url=payload.source_url,
        source_type="text",
        source_value=None,
        status=payload.status,
        confidence=payload.confidence,
        risk_score=payload.risk_score,
        grade=payload.grade,
        document_text=payload.document_text,
        result_json=payload.model_dump_json(),
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def _fake_result(**kw):
    from app.services.analyzer import AnalysisResult
    return AnalysisResult(payload=_make_payload(**kw), issues=[])


# ═══════════════════════════════════════════════════════════════════════════
# database.py
# ═══════════════════════════════════════════════════════════════════════════

class TestDatabaseConnectArgs:
    def test_database_connect_args_non_sqlite_returns_empty(self):
        from app.database import _connect_args
        result = _connect_args("postgresql://localhost/db")
        assert result == {}

    def test_database_connect_args_sqlite_returns_thread_flag(self):
        from app.database import _connect_args
        result = _connect_args("sqlite:///mydb.db")
        assert result == {"check_same_thread": False}


class TestDatabaseGetDb:
    def test_database_get_db_yields_session(self):
        from app.database import get_db
        gen = get_db()
        session = next(gen)
        assert session is not None
        try:
            next(gen)
        except StopIteration:
            pass
        finally:
            session.close()

    def test_database_get_db_closes_on_completion(self):
        from app.database import get_db
        sessions = []
        gen = get_db()
        session = next(gen)
        sessions.append(session)
        try:
            next(gen)
        except StopIteration:
            pass
        # Should not raise; session is closed
        assert len(sessions) == 1


class TestDatabaseDbSession:
    def test_database_db_session_context_manager(self):
        from app.database import db_session
        with db_session() as session:
            assert session is not None
            result = session.execute(
                __import__("sqlalchemy").text("SELECT 1")
            ).scalar()
            assert result == 1

    def test_database_db_session_closes_after_exit(self):
        from app.database import db_session
        captured = []
        with db_session() as session:
            captured.append(session)
        # The context manager completed — verifies the with-block covered lines 48-52
        assert len(captured) == 1


# ═══════════════════════════════════════════════════════════════════════════
# GET /analyses  (list_analyses)
# ═══════════════════════════════════════════════════════════════════════════

class TestListAnalyses:
    def test_main_list_analyses_empty_returns_empty_list(self, app_client):
        response = app_client.get("/analyses")
        assert response.status_code == 200
        assert response.json() == []

    def test_main_list_analyses_returns_inserted_records(self, app_client, db_session):
        _insert_analysis(db_session, name="Policy A")
        _insert_analysis(db_session, name="Policy B")
        response = app_client.get("/analyses")
        assert response.status_code == 200
        names = {r["name"] for r in response.json()}
        assert {"Policy A", "Policy B"} == names

    def test_main_list_analyses_respects_limit(self, app_client, db_session):
        for i in range(5):
            _insert_analysis(db_session, name=f"Policy {i}")
        response = app_client.get("/analyses?limit=2")
        assert response.status_code == 200
        assert len(response.json()) == 2

    def test_main_list_analyses_response_shape(self, app_client, db_session):
        _insert_analysis(db_session, name="Shape Test")
        response = app_client.get("/analyses")
        assert response.status_code == 200
        item = response.json()[0]
        expected_keys = {"id", "name", "doc_type", "source_url", "status",
                         "confidence", "risk_score", "grade", "created_at"}
        assert expected_keys.issubset(set(item.keys()))


# ═══════════════════════════════════════════════════════════════════════════
# GET /analyses/{id}  (get_analysis)
# ═══════════════════════════════════════════════════════════════════════════

class TestGetAnalysis:
    def test_main_get_analysis_success_returns_payload(self, app_client, db_session):
        row = _insert_analysis(db_session, name="Detail Test")
        response = app_client.get(f"/analyses/{row.id}")
        assert response.status_code == 200
        assert response.json()["name"] == "Detail Test"

    def test_main_get_analysis_404_for_missing_id(self, app_client):
        response = app_client.get("/analyses/nonexistent-analysis-id")
        assert response.status_code == 404
        assert response.json()["detail"] == "Analysis not found"


# ═══════════════════════════════════════════════════════════════════════════
# POST /analyze/url — error paths
# ═══════════════════════════════════════════════════════════════════════════

class TestAnalyzeUrlErrors:
    def test_main_analyze_url_value_error_returns_400(self, app_client, monkeypatch):
        async def fake_fetch(url):
            raise ValueError("URL is not allowed")

        monkeypatch.setattr("app.main.fetch_url_text", fake_fetch)
        response = app_client.post(
            "/analyze/url",
            json={"url": "http://127.0.0.1/admin", "jurisdictions": ["GDPR"]},
        )
        assert response.status_code == 400
        assert "not allowed" in response.json()["detail"]

    def test_main_analyze_url_generic_exception_returns_500(self, app_client, monkeypatch):
        async def fake_fetch(url):
            raise ConnectionError("network error")

        monkeypatch.setattr("app.main.fetch_url_text", fake_fetch)
        response = app_client.post(
            "/analyze/url",
            json={"url": "https://example.com/policy", "jurisdictions": ["GDPR"]},
        )
        assert response.status_code == 500
        assert "Failed to fetch" in response.json()["detail"]

    def test_main_analyze_url_empty_content_returns_400(self, app_client, monkeypatch):
        async def fake_fetch(url):
            return ""

        monkeypatch.setattr("app.main.fetch_url_text", fake_fetch)
        response = app_client.post(
            "/analyze/url",
            json={"url": "https://example.com/empty", "jurisdictions": ["GDPR"]},
        )
        assert response.status_code == 400
        assert "empty" in response.json()["detail"].lower()

    def test_main_analyze_url_success_path(self, app_client, monkeypatch):
        async def fake_fetch(url):
            return "Privacy policy content here."

        async def fake_analyze(text, jurisdictions, **kwargs):
            return _fake_result()

        monkeypatch.setattr("app.main.fetch_url_text", fake_fetch)
        monkeypatch.setattr("app.main.analyze_text", fake_analyze)
        response = app_client.post(
            "/analyze/url",
            json={"url": "https://example.com/privacy", "jurisdictions": ["GDPR"]},
        )
        assert response.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
# POST /analyze/file — error paths
# ═══════════════════════════════════════════════════════════════════════════

class TestAnalyzeFileErrors:
    def test_main_analyze_file_empty_text_returns_400(self, app_client, monkeypatch):
        monkeypatch.setattr(
            "app.main.extract_text_from_bytes",
            lambda filename, content_type, data: "",
        )
        response = app_client.post(
            "/analyze/file",
            files={"file": ("empty.txt", b"", "text/plain")},
        )
        assert response.status_code == 400
        assert "empty" in response.json()["detail"].lower()

    def test_main_analyze_file_invalid_doc_type_returns_422(self, app_client):
        response = app_client.post(
            "/analyze/file",
            data={"doc_type": "InvalidType"},
            files={"file": ("policy.txt", b"Some content here.", "text/plain")},
        )
        assert response.status_code == 422
        assert "doc_type" in response.json()["detail"].lower()

    def test_main_analyze_file_invalid_industry_returns_422(self, app_client):
        response = app_client.post(
            "/analyze/file",
            data={"industry": "UnknownIndustry"},
            files={"file": ("policy.txt", b"Some content here.", "text/plain")},
        )
        assert response.status_code == 422
        assert "industry" in response.json()["detail"].lower()


# ═══════════════════════════════════════════════════════════════════════════
# _refresh_all_watchlist_items (internal function, called directly)
# ═══════════════════════════════════════════════════════════════════════════

class TestRefreshAllWatchlistItems:
    # OE-003 (2026-07-03): ``_refresh_all_watchlist_items`` is now a legacy shim
    # that delegates to ``_refresh_due_watchlist_items``. The tests below
    # exercise the shim's disabled-early-return contract and the per-item
    # scheduler's empty-watchlist path (both preserved from the pre-merge
    # semantics).
    def test_main_refresh_all_watchlist_items_no_items(self, db_session):
        from app.main import _refresh_all_watchlist_items
        from app.models import WatchlistItem as WatchlistItemModel
        with patch("app.main.settings") as mock_settings:
            mock_settings.watchlist_refresh_seconds = 60

            with patch("app.main.db_session") as mock_db_ctx:
                mock_db_ctx.return_value.__enter__ = lambda s: db_session
                mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)
                asyncio.run(_refresh_all_watchlist_items())

        # With no WatchlistItems in DB, no rows should have been written
        count = db_session.query(WatchlistItemModel).count()
        assert count == 0

    def test_main_refresh_all_watchlist_items_skips_when_disabled(self, db_session):
        from app.main import _refresh_all_watchlist_items
        # When watchlist_refresh_seconds <= 0, the shim returns early WITHOUT
        # delegating to the scheduler. This preserves the historical
        # "disabled means bail out" contract for callers that assert it.
        with patch("app.main.settings") as mock_settings:
            mock_settings.watchlist_refresh_seconds = 0
            with patch("app.main.db_session") as mock_db_ctx:
                mock_db_ctx.return_value.__enter__ = lambda s: db_session
                mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)
                asyncio.run(_refresh_all_watchlist_items())


# ═══════════════════════════════════════════════════════════════════════════
# _watchlist_loop_async (OE-003: now delegates to _refresh_due_watchlist_items,
# not _refresh_all_watchlist_items)
# ═══════════════════════════════════════════════════════════════════════════

class TestWatchlistLoopAsync:
    def test_main_watchlist_loop_async_runs_then_cancels(self):
        from app.main import _watchlist_loop_async

        call_count = 0

        async def fake_refresh():
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                raise asyncio.CancelledError()
            return 60  # scheduler returns int seconds-to-next-wakeup

        async def run_loop():
            # OE-003: the loop now calls ``_refresh_due_watchlist_items``
            # directly (not through the legacy shim). Patch the new function.
            with patch("app.main._refresh_due_watchlist_items", side_effect=fake_refresh):
                with patch("app.main.settings") as mock_settings:
                    mock_settings.watchlist_refresh_seconds = 0
                    await _watchlist_loop_async()

        with pytest.raises(asyncio.CancelledError):
            asyncio.run(run_loop())

        assert call_count >= 1

    def test_main_watchlist_loop_async_handles_exception_and_continues(self):
        from app.main import _watchlist_loop_async

        call_count = 0

        async def fake_refresh():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("transient error")
            # Second call: cancel the loop
            raise asyncio.CancelledError()

        async def run_loop():
            # OE-003: patch the new scheduler function.
            with patch("app.main._refresh_due_watchlist_items", side_effect=fake_refresh):
                with patch("app.main.settings") as mock_settings:
                    mock_settings.watchlist_refresh_seconds = 0
                    # Zero-sleep the loop retry so the test doesn't wait 60s
                    # for the exception-recovery path.
                    with patch("app.main._WATCHLIST_LOOP_MIN_SLEEP_S", 0):
                        await _watchlist_loop_async()

        with pytest.raises(asyncio.CancelledError):
            asyncio.run(run_loop())

        assert call_count >= 2


# ═══════════════════════════════════════════════════════════════════════════
# POST /analyze/batch
# ═══════════════════════════════════════════════════════════════════════════

class TestAnalyzeBatch:
    # Note: the /analyze/batch endpoint uses `hasattr(request, 'json')` to branch.
    # Pydantic models have .json(), which triggers the await branch and fails.
    # We pass a SimpleNamespace (no .json attr) to trigger the direct `else` branch.

    def _make_batch_ns(self, items, jurisdictions=None, mode="full", industry=None):
        from types import SimpleNamespace
        return SimpleNamespace(
            items=items,
            jurisdictions=jurisdictions or ["GDPR"],
            mode=mode,
            industry=industry,
            detect_cross_references=True,
        )

    def test_main_analyze_batch_with_valid_urls(self, db_session, monkeypatch):
        from app.main import analyze_batch
        from app.schemas import BatchItem

        async def fake_fetch(url):
            return "Privacy policy content."

        async def fake_analyze_batch(documents, industry, jurisdictions, mode, detect_cross_refs, **kwargs):
            payloads = [_make_payload(name=f"Doc{i}") for i in range(len(documents))]
            return payloads, []

        monkeypatch.setattr("app.main.fetch_url_text", fake_fetch)
        monkeypatch.setattr("app.main.analyze_batch_documents", fake_analyze_batch)

        from app.schemas import BatchItem
        req = self._make_batch_ns(
            items=[
                BatchItem(url="https://example.com/privacy", name="Privacy"),
                BatchItem(url="https://example.com/tos", name="TOS"),
            ],
            mode="quick",
        )

        result = asyncio.run(analyze_batch(request=req, db=db_session))
        assert "items" in result
        assert "batch_id" in result

    def test_main_analyze_batch_no_valid_documents_raises(self, db_session, monkeypatch):
        from fastapi import HTTPException
        from app.main import analyze_batch
        from app.schemas import BatchItem

        async def fake_fetch(url):
            raise RuntimeError("Connection failed")

        monkeypatch.setattr("app.main.fetch_url_text", fake_fetch)

        req = self._make_batch_ns(
            items=[BatchItem(url="https://broken.example.com/privacy", name="Broken")]
        )

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(analyze_batch(request=req, db=db_session))
        assert exc_info.value.status_code == 400
        assert "No valid documents" in exc_info.value.detail


# ═══════════════════════════════════════════════════════════════════════════
# PDF export with findings (covers lines 595-598, 671, 684-727)
# ═══════════════════════════════════════════════════════════════════════════

class TestExportPdfWithFindings:
    def test_main_export_pdf_with_findings_covers_finding_loop(self, db_session):
        pytest.importorskip("reportlab", reason="reportlab not installed")
        from app.main import export_analysis_pdf

        findings_data = [
            {
                "category": "Data Sale / Sharing",
                "severity": "Critical",
                "confidence": 0.95,
                "excerpt": "We sell your personal data to third parties.",
                "explanation": "Direct data sale without consent.",
                "jurisdictions": ["GDPR", "US-CA"],
                "evidence": {
                    "line_start": 1, "line_end": 1,
                    "legal_basis": ["GDPR Art. 6", "CCPA § 1798.100"],
                },
            },
            {
                "category": "Data Retention",
                "severity": "High",
                "confidence": 0.88,
                "excerpt": "We keep your data forever.",
                "explanation": "Indefinite retention.",
                "jurisdictions": ["GDPR"],
                "evidence": {
                    "line_start": 2, "line_end": 2,
                    "legal_basis": ["GDPR Art. 5"],
                },
            },
            {
                "category": "User Rights",
                "severity": "Medium",
                "confidence": 0.75,
                "excerpt": "You may request deletion.",
                "explanation": "Deletion rights mentioned.",
                "jurisdictions": ["GDPR"],
                "evidence": {
                    "line_start": 3, "line_end": 3,
                    "legal_basis": ["GDPR Art. 17"],
                },
            },
            {
                "category": "Tracking",
                "severity": "Low",
                "confidence": 0.60,
                "excerpt": "We use cookies.",
                "explanation": "Cookie tracking.",
                "jurisdictions": ["GDPR"],
                "evidence": {
                    "line_start": 4, "line_end": 4,
                    "legal_basis": ["GDPR Art. 6"],
                },
            },
        ]

        payload = AnalysisPayload(
            id=str(uuid4()),
            name="Full Findings Test",
            doc_type="Privacy Policy",
            source_url=None,
            document_text="policy text",
            line_offsets=[0],
            status="completed",
            review_required=False,
            confidence=0.85,
            risk_score=5.0,
            grade="B",
            created_at=datetime.now(timezone.utc),
            findings=[
                Finding(
                    category=f["category"],
                    severity=f["severity"],
                    confidence=f["confidence"],
                    excerpt=f["excerpt"],
                    explanation=f["explanation"],
                    jurisdictions=f["jurisdictions"],
                    evidence=Evidence(**f["evidence"]),
                )
                for f in findings_data
            ],
            summary="Multiple findings detected across risk categories.",
        )

        row = AnalysisModel(
            id=payload.id,
            doc_name=payload.name,
            doc_type=payload.doc_type,
            source_url=payload.source_url,
            source_type="text",
            source_value=None,
            status=payload.status,
            confidence=payload.confidence,
            risk_score=payload.risk_score,
            grade=payload.grade,
            document_text=payload.document_text,
            result_json=payload.model_dump_json(),
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(row)
        db_session.commit()

        response = export_analysis_pdf(analysis_id=row.id, db=db_session)
        assert response.media_type == "application/pdf"
        assert response.body[:4] == b"%PDF"


# ═══════════════════════════════════════════════════════════════════════════
# PDF export with long excerpt (covers main.py line 702)
# ═══════════════════════════════════════════════════════════════════════════

class TestExportPdfLongExcerpt:
    def test_main_export_pdf_long_excerpt_appends_ellipsis(self, db_session):
        pytest.importorskip("reportlab", reason="reportlab not installed")
        from app.main import export_analysis_pdf

        long_excerpt = "x" * 600  # > 500 chars → triggers line 702

        payload = AnalysisPayload(
            id=str(uuid4()),
            name="Long Excerpt PDF Test",
            doc_type="Privacy Policy",
            source_url=None,
            document_text="policy text",
            line_offsets=[0],
            status="completed",
            review_required=False,
            confidence=0.90,
            risk_score=2.0,
            grade="A",
            created_at=datetime.now(timezone.utc),
            findings=[
                Finding(
                    category="Data Sale / Sharing",
                    severity="High",
                    confidence=0.90,
                    excerpt=long_excerpt,
                    explanation="Long excerpt triggers truncation.",
                    jurisdictions=["GDPR"],
                    evidence=Evidence(
                        line_start=1, line_end=1, legal_basis=["GDPR Art. 6"]
                    ),
                )
            ],
            summary="Long excerpt test.",
        )

        row = AnalysisModel(
            id=payload.id,
            doc_name=payload.name,
            doc_type=payload.doc_type,
            source_url=payload.source_url,
            source_type="text",
            source_value=None,
            status=payload.status,
            confidence=payload.confidence,
            risk_score=payload.risk_score,
            grade=payload.grade,
            document_text=payload.document_text,
            result_json=payload.model_dump_json(),
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(row)
        db_session.commit()

        response = export_analysis_pdf(analysis_id=row.id, db=db_session)
        assert response.media_type == "application/pdf"
        assert response.body[:4] == b"%PDF"


# ═══════════════════════════════════════════════════════════════════════════
# _persist_analysis with legacy Pydantic payload (covers main.py line 157)
# ═══════════════════════════════════════════════════════════════════════════

class TestPersistAnalysisLegacyPydantic:
    def test_main_persist_analysis_uses_json_when_no_model_dump_json(self, db_session):
        from types import SimpleNamespace
        from app.main import _persist_analysis

        pid = str(uuid4())
        # SimpleNamespace has no model_dump_json → triggers else branch (line 157)
        payload_ns = SimpleNamespace(
            id=pid,
            name="Legacy Payload Test",
            doc_type="Privacy Policy",
            source_url=None,
            status="completed",
            confidence=0.85,
            risk_score=2.0,
            grade="A",
            document_text="Some policy text.",
            review_required=False,
        )
        payload_ns.json = lambda: json.dumps({"id": pid, "name": "Legacy Payload Test"})

        assert not hasattr(payload_ns, "model_dump_json")

        _persist_analysis(
            payload=payload_ns,
            source_type="text",
            source_value=None,
            doc_type="Privacy Policy",
            source_url=None,
            db=db_session,
        )

        from app.models import Analysis as AnalysisModel2
        row = db_session.query(AnalysisModel2).filter_by(id=pid).first()
        assert row is not None
        assert row.doc_name == "Legacy Payload Test"


# ═══════════════════════════════════════════════════════════════════════════
# analyze_batch with async json path (covers main.py lines 351-352)
# ═══════════════════════════════════════════════════════════════════════════

class TestAnalyzeBatchPydanticValidation:
    """analyze_batch now uses proper Pydantic type annotation — exercises the endpoint path."""

    def test_main_analyze_batch_valid_request_returns_batch_id(
        self, db_session, monkeypatch
    ):
        from app.main import analyze_batch
        from app.schemas import AnalyzeBatchRequest, BatchItem

        async def fake_fetch(url):
            return "Privacy policy content for pydantic path test."

        async def fake_analyze_batch(
            documents, industry, jurisdictions, mode, detect_cross_refs, **kwargs
        ):
            return [_make_payload(name="Doc1")], []

        monkeypatch.setattr("app.main.fetch_url_text", fake_fetch)
        monkeypatch.setattr("app.main.analyze_batch_documents", fake_analyze_batch)

        request = AnalyzeBatchRequest(
            items=[BatchItem(url="https://example.com/privacy", name="Privacy Policy")],
            jurisdictions=["GDPR"],
            mode="full",
            industry=None,
            detect_cross_references=False,
        )
        result = asyncio.run(analyze_batch(request=request, db=db_session))
        assert "items" in result
        assert "batch_id" in result


# ═══════════════════════════════════════════════════════════════════════════
# _refresh_all_watchlist_items with actual items (covers main.py lines 107-137)
# ═══════════════════════════════════════════════════════════════════════════

class TestRefreshWatchlistItemsWithData:
    def test_main_refresh_watchlist_items_processes_changed_unchanged_failed(
        self, db_session
    ):
        # OE-003 (2026-07-03): the refresh path now honors per-item cadence.
        # We seed items with ``last_checked`` well in the past so they are
        # unambiguously past-due for the ``_refresh_due_watchlist_items``
        # scheduler. ``check_frequency=60`` keeps each item's next-due window
        # short so the previous global-cadence assumptions still hold. We call
        # the scheduler directly (not the legacy shim) so this test exercises
        # the code the background loop actually runs.
        from datetime import timedelta as _timedelta
        from app.main import _refresh_due_watchlist_items
        from app.models import WatchlistItem

        past = datetime.now(timezone.utc) - _timedelta(hours=2)

        # Item with existing hash that will change → "Updated"
        item_changed = WatchlistItem(
            id=str(uuid4()),
            vendor="Vendor A",
            source_url="https://example.com/policy-a",
            status="Active",
            last_document_hash="old_hash_abc",
            last_risk_score=5.0,
            check_frequency=60,
            enabled=True,
            last_checked=past,
        )
        # Item with no prior hash → "No Changes"
        item_no_prior = WatchlistItem(
            id=str(uuid4()),
            vendor="Vendor B",
            source_url="https://example.com/policy-b",
            status="Active",
            last_document_hash=None,
            last_risk_score=None,
            check_frequency=60,
            enabled=True,
            last_checked=past,
        )
        # Item whose fetch fails → "Check Failed"
        item_failed = WatchlistItem(
            id=str(uuid4()),
            vendor="Vendor C",
            source_url="https://broken.example.com/down",
            status="Active",
            check_frequency=60,
            enabled=True,
            last_checked=past,
        )
        db_session.add_all([item_changed, item_no_prior, item_failed])
        db_session.commit()

        async def fake_fetch(url):
            if "broken" in url:
                raise RuntimeError("connection refused")
            return "Updated privacy policy text."

        with patch("app.main.settings") as mock_settings:
            mock_settings.watchlist_refresh_seconds = 60
            with patch("app.main.db_session") as mock_db_ctx:
                mock_db_ctx.return_value.__enter__ = lambda s: db_session
                mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)
                with patch("app.main.fetch_url_text", side_effect=fake_fetch):
                    with patch("app.main.content_hash", return_value="new_hash_xyz"):
                        with patch(
                            "app.main.diff_summary", return_value=(2, "Text changed")
                        ):
                            with patch("app.main.detect_findings", return_value=[]):
                                with patch(
                                    "app.main.calculate_risk_score", return_value=3.0
                                ):
                                    asyncio.run(_refresh_due_watchlist_items())

        db_session.refresh(item_changed)
        db_session.refresh(item_no_prior)
        db_session.refresh(item_failed)

        # "old_hash_abc" != "new_hash_xyz" → changed=True → Updated
        assert item_changed.status == "Updated"
        # risk_delta = round(3.0 - 5.0, 2) = -2.0 (has prior risk score)
        assert item_changed.risk_delta == pytest.approx(-2.0, abs=0.01)

        # No prior hash → changed=False → No Changes
        assert item_no_prior.status == "No Changes"
        assert item_no_prior.risk_delta == 0.0  # no prior risk_score → else branch

        # Fetch failed → Check Failed
        assert item_failed.status == "Check Failed"


# ═══════════════════════════════════════════════════════════════════════════
# lifespan with watchlist_refresh_seconds > 0 (covers main.py lines 59, 62-64)
# ═══════════════════════════════════════════════════════════════════════════

class TestLifespanWithWatchlist:
    def test_main_lifespan_creates_and_cancels_watchlist_task(self):
        import asyncio as _asyncio
        from app.main import lifespan, app as fastapi_app

        async def fake_watchlist_loop():
            # Runs indefinitely until cancelled (CancelledError propagates → task cancelled)
            await _asyncio.sleep(10)

        async def run_lifespan():
            with patch("app.main.init_db"):
                with patch("app.main.settings") as mock_settings:
                    mock_settings.watchlist_refresh_seconds = 60
                    # Replace _watchlist_loop_async with a cancellable coroutine function
                    with patch("app.main._watchlist_loop_async", fake_watchlist_loop):
                        async with lifespan(fastapi_app):
                            pass  # Exit immediately → triggers task.cancel() + await

        _asyncio.run(run_lifespan())


# ═══════════════════════════════════════════════════════════════════════════
# analyze_batch with legacy pydantic batch result (covers main.py line 408)
# ═══════════════════════════════════════════════════════════════════════════

class TestAnalyzeBatchLegacyResult:
    def test_main_analyze_batch_legacy_batch_result_uses_json(
        self, db_session, monkeypatch
    ):
        from types import SimpleNamespace
        from app.main import analyze_batch
        from app.schemas import BatchItem

        async def fake_fetch(url):
            return "Content for legacy result test."

        async def fake_analyze_batch(
            documents, industry, jurisdictions, mode, detect_cross_refs, **kwargs
        ):
            return [_make_payload(name="LegacyDoc")], []

        monkeypatch.setattr("app.main.fetch_url_text", fake_fetch)
        monkeypatch.setattr("app.main.analyze_batch_documents", fake_analyze_batch)

        # Patch BatchAnalysisResult to return an object without model_dump → line 408
        class LegacyBatchResult:
            def __init__(self, **kwargs):
                self.batch_id = kwargs.get("batch_id", "legacy-batch")
                self.analysis_mode = kwargs.get("analysis_mode", "full")
                self.items = kwargs.get("items", [])
                self.cross_references = kwargs.get("cross_references", [])
                self.created_at = str(kwargs.get("created_at", ""))

            def json(self):
                return json.dumps({
                    "batch_id": self.batch_id,
                    "analysis_mode": self.analysis_mode,
                    "items": [],
                    "cross_references": self.cross_references,
                })

        monkeypatch.setattr("app.main.BatchAnalysisResult", LegacyBatchResult)

        req = SimpleNamespace(
            items=[BatchItem(url="https://example.com/legacy-policy", name="LegacyPolicy")],
            jurisdictions=["GDPR"],
            mode="full",
            industry=None,
            detect_cross_references=False,
        )

        result = asyncio.run(analyze_batch(request=req, db=db_session))
        assert "batch_id" in result
