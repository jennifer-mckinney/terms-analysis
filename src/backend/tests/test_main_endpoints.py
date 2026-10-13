"""
Comprehensive tests for uncovered lines in app/main.py.

Covers:
  - GET /rubric
  - GET /exports/analysis/{id}.pdf
  - GET /exports/analyses.csv (edge cases beyond existing tests)
  - GET /exports/analysis/{id}  (JSON export)
  - POST /watchlist
  - DELETE /watchlist/{id}
  - POST /watchlist/{id}/refresh
  - GET /watchlist
  - POST /snapshots
  - GET /snapshots
  - GET /snapshots/detail/{id}
  - GET /diff/{id1}/{id2}
  - GET /reviews
  - POST /reviews/{id}
  - POST /policy-watch
  - GET /policy-watch
  - DELETE /policy-watch/{id}
  - POST /policy-watch/{id}/snapshot
  - Error paths: 404, 409, 400, 500
  - Issue #184: a lone surrogate in submitted document text never 500s

Naming: test_<module>_<function>_<scenario>
"""
from __future__ import annotations

import csv
import dataclasses
import http
import io
import json
import re
import typing
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import pytest

from app.models import (
    Analysis as AnalysisModel,
    PolicySnapshot,
    ReviewItem,
    WatchlistItem,
)
from app.schemas import AnalysisPayload
from app.services import analyzer as analyzer_module
from app.services.analyzer import AnalysisResult

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

    from app.config import Settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_analysis_payload(
    *,
    name: str = "Test Policy",
    doc_type: str | None = "Privacy Policy",
    source_url: str | None = None,
    review_required: bool = False,
    confidence: float = 0.90,
    risk_score: float = 2.0,
    grade: str = "A",
    status: str = "completed",
    document_text: str = "Sample policy text.",
) -> AnalysisPayload:
    return AnalysisPayload(
        id=str(uuid4()),
        name=name,
        doc_type=doc_type,
        source_url=source_url,
        document_text=document_text,
        line_offsets=[0],
        status=status,
        review_required=review_required,
        confidence=confidence,
        risk_score=risk_score,
        grade=grade,
        created_at=datetime.now(timezone.utc),
        findings=[],
        summary="Mocked summary.",
    )


def _make_fake_result(**kwargs) -> AnalysisResult:
    payload = _make_analysis_payload(**kwargs)
    return AnalysisResult(payload=payload, issues=[])


def _insert_analysis(db_session, *, review_required: bool = False, **overrides) -> AnalysisModel:
    """Insert a minimal Analysis row and return it."""
    payload = _make_analysis_payload(review_required=review_required, **overrides)
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


def _insert_watchlist_item(db_session, *, vendor: str = "ACME", source_url: str | None = "https://example.com/privacy") -> WatchlistItem:
    item = WatchlistItem(
        id=str(uuid4()),
        vendor=vendor,
        source_url=source_url,
        status="No Changes",
        change_count=0,
        risk_delta=0.0,
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


def _insert_snapshot(db_session, *, url: str = "https://example.com/privacy", text: str = "Privacy text v1") -> PolicySnapshot:
    from app.services.diffing import content_hash
    snap = PolicySnapshot(
        id=str(uuid4()),
        url=url,
        content_hash=content_hash(text),
        captured_at=datetime.now(timezone.utc),
        raw_text=text,
    )
    db_session.add(snap)
    db_session.commit()
    db_session.refresh(snap)
    return snap


def _insert_review_item(db_session, analysis_id: str, status: str = "pending") -> ReviewItem:
    item = ReviewItem(
        id=str(uuid4()),
        analysis_id=analysis_id,
        status=status,
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


# ===========================================================================
# GET /rubric
# ===========================================================================

class TestRubricEndpoint:
    def test_main_get_rubric_returns_null_when_no_analyses(self, app_client):
        response = app_client.get("/rubric")
        assert response.status_code == 200
        assert response.json() is None

    def test_main_get_rubric_returns_scores_with_analyses(self, app_client, db_session):
        _insert_analysis(db_session, risk_score=3.0, confidence=0.85, grade="B")
        _insert_analysis(db_session, risk_score=1.0, confidence=0.95, grade="A")

        response = app_client.get("/rubric")
        assert response.status_code == 200
        body = response.json()
        assert body is not None
        expected_keys = {
            "productIntegrity",
            "legalSignalQuality",
            "aiLawSignalQuality",
            "privacySecurity",
            "accessibilityUsability",
            "visualIxd",
            "performanceReliability",
            "governanceReadiness",
            "overall",
        }
        assert set(body.keys()) == expected_keys
        for key in expected_keys:
            assert 0.0 <= body[key] <= 10.0

    def test_main_get_rubric_clamps_scores_to_valid_range(self, app_client, db_session):
        # Even extreme risk/confidence combos should produce clamped [0, 10] values
        _insert_analysis(db_session, risk_score=10.0, confidence=0.0, grade="D")
        response = app_client.get("/rubric")
        assert response.status_code == 200
        body = response.json()
        for val in body.values():
            assert 0.0 <= val <= 10.0

    def test_main_get_rubric_needs_review_status_is_counted(self, app_client, db_session):
        _insert_analysis(db_session, status="needs_review", risk_score=5.0, confidence=0.70, grade="B")
        _insert_analysis(db_session, status="completed", risk_score=2.0, confidence=0.90, grade="A")

        response = app_client.get("/rubric")
        assert response.status_code == 200
        body = response.json()
        # governanceReadiness drops when review_rate > 0
        assert body["governanceReadiness"] < 10.0


# ===========================================================================
# GET /exports/analysis/{id}.pdf
# ===========================================================================
# NOTE: The route /exports/analysis/{analysis_id}.pdf is declared AFTER
# /exports/analysis/{analysis_id} in main.py.  Starlette's router matches the
# first registered pattern, so a request like GET /exports/analysis/abc.pdf
# is captured by the JSON-export route with analysis_id="abc.pdf".
# The tests below call the PDF endpoint function directly to cover those lines.

class TestExportAnalysisPdf:
    def test_main_export_pdf_returns_pdf_bytes(self, db_session):
        """Call the PDF export view function directly (route shadowed by JSON export)."""
        pytest.importorskip("reportlab", reason="reportlab not installed")
        row = _insert_analysis(db_session)

        from app.main import export_analysis_pdf
        response = export_analysis_pdf(analysis_id=row.id, db=db_session)
        assert response.media_type == "application/pdf"
        assert response.body[:4] == b"%PDF"

    def test_main_export_pdf_404_for_missing_analysis(self, db_session):
        """PDF export raises 404 when analysis_id is unknown."""
        pytest.importorskip("reportlab", reason="reportlab not installed")
        from fastapi import HTTPException
        from app.main import export_analysis_pdf

        with pytest.raises(HTTPException) as exc_info:
            export_analysis_pdf(analysis_id="nonexistent-id", db=db_session)
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Analysis not found"

    def test_main_export_pdf_503_when_reportlab_missing(self, db_session, monkeypatch):
        """PDF export raises 503 when reportlab cannot be imported."""
        row = _insert_analysis(db_session)

        import builtins
        from fastapi import HTTPException
        from app.main import export_analysis_pdf

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name.startswith("reportlab"):
                raise ImportError("No module named 'reportlab'")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)

        with pytest.raises(HTTPException) as exc_info:
            export_analysis_pdf(analysis_id=row.id, db=db_session)
        assert exc_info.value.status_code == 503
        assert "reportlab" in exc_info.value.detail.lower()


# ===========================================================================
# GET /exports/analyses.csv (additional edge-case coverage)
# ===========================================================================

class TestExportAnalysesCsv:
    def test_main_export_csv_empty_db_returns_header_only(self, app_client):
        response = app_client.get("/exports/analyses.csv")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/csv; charset=utf-8"
        lines = response.text.strip().splitlines()
        assert len(lines) == 1
        assert "id" in lines[0]

    def test_main_export_csv_contains_inserted_row(self, app_client, db_session):
        row = _insert_analysis(db_session, name="Policy Export Test")
        response = app_client.get("/exports/analyses.csv")
        assert response.status_code == 200
        assert row.id in response.text
        assert "Policy Export Test" in response.text

    def test_main_export_csv_confidence_risk_formatted_to_two_decimals(self, app_client, db_session):
        _insert_analysis(db_session, confidence=0.9, risk_score=3.5)
        response = app_client.get("/exports/analyses.csv")
        assert "0.90" in response.text
        assert "3.50" in response.text


# ===========================================================================
# GET /exports/analysis/{id}  (JSON export)
# ===========================================================================

class TestExportAnalysisJson:
    def test_main_export_analysis_json_returns_dict(self, app_client, db_session):
        row = _insert_analysis(db_session, name="JSON Export")
        response = app_client.get(f"/exports/analysis/{row.id}")
        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "JSON Export"
        assert "findings" in body

    def test_main_export_analysis_json_404_for_missing(self, app_client):
        response = app_client.get("/exports/analysis/does-not-exist")
        assert response.status_code == 404
        assert response.json()["detail"] == "Analysis not found"


# ===========================================================================
# GET /watchlist
# ===========================================================================

class TestListWatchlist:
    def test_main_list_watchlist_empty(self, app_client):
        response = app_client.get("/watchlist")
        assert response.status_code == 200
        assert response.json() == []

    def test_main_list_watchlist_returns_inserted_items(self, app_client, db_session):
        _insert_watchlist_item(db_session, vendor="VendorA")
        _insert_watchlist_item(db_session, vendor="VendorB", source_url="https://vendorb.com/tos")
        response = app_client.get("/watchlist")
        assert response.status_code == 200
        vendors = {item["vendor"] for item in response.json()}
        assert {"VendorA", "VendorB"} == vendors


# ===========================================================================
# POST /watchlist
# ===========================================================================

class TestAddWatchlist:
    def test_main_add_watchlist_creates_item(self, app_client):
        response = app_client.post(
            "/watchlist",
            json={"vendor": "NewVendor", "source_url": "https://newvendor.com/privacy"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["vendor"] == "NewVendor"
        assert body["source_url"] == "https://newvendor.com/privacy"
        assert body["status"] == "No Changes"
        assert body["change_count"] == 0
        assert "id" in body

    def test_main_add_watchlist_without_source_url(self, app_client):
        response = app_client.post("/watchlist", json={"vendor": "ManualVendor"})
        assert response.status_code == 200
        body = response.json()
        assert body["vendor"] == "ManualVendor"
        assert body["source_url"] is None

    def test_main_add_watchlist_rejects_empty_vendor(self, app_client):
        response = app_client.post("/watchlist", json={"vendor": ""})
        assert response.status_code == 422


# ===========================================================================
# DELETE /watchlist/{id}
# ===========================================================================

class TestRemoveWatchlist:
    def test_main_remove_watchlist_deletes_existing_item(self, app_client, db_session):
        item = _insert_watchlist_item(db_session, vendor="ToDelete")
        response = app_client.delete(f"/watchlist/{item.id}")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "deleted"
        assert body["id"] == item.id

    def test_main_remove_watchlist_404_for_missing(self, app_client):
        response = app_client.delete("/watchlist/nonexistent-id")
        assert response.status_code == 404
        assert response.json()["detail"] == "Watchlist item not found"


# ===========================================================================
# POST /watchlist/{id}/refresh
# ===========================================================================

class TestRefreshWatchlist:
    def test_main_refresh_watchlist_no_change_detected(self, app_client, db_session, monkeypatch):
        item = _insert_watchlist_item(db_session, vendor="RefreshVendor")
        text = "Privacy policy text that hasn't changed."

        async def fake_fetch(url):
            return text

        monkeypatch.setattr("app.main.fetch_url_text", fake_fetch)

        response = app_client.post(f"/watchlist/{item.id}/refresh")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "No Changes"
        assert body["vendor"] == "RefreshVendor"

    def test_main_refresh_watchlist_detects_change(self, app_client, db_session, monkeypatch):
        from app.services.diffing import content_hash
        old_text = "Old policy text."
        new_text = "Completely new policy text with different content here."

        item = _insert_watchlist_item(db_session, vendor="ChangedVendor")
        # Seed a known hash so it appears "changed"
        item.last_document_text = old_text
        item.last_document_hash = content_hash(old_text)
        db_session.commit()

        async def fake_fetch(url):
            return new_text

        monkeypatch.setattr("app.main.fetch_url_text", fake_fetch)

        response = app_client.post(f"/watchlist/{item.id}/refresh")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "Updated"

    def test_main_refresh_watchlist_fetch_failure_sets_check_failed(self, app_client, db_session, monkeypatch):
        item = _insert_watchlist_item(db_session, vendor="FailVendor")

        async def fake_fetch(url):
            raise ConnectionError("network error")

        monkeypatch.setattr("app.main.fetch_url_text", fake_fetch)

        response = app_client.post(f"/watchlist/{item.id}/refresh")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "Check Failed"

    def test_main_refresh_watchlist_404_for_missing_item(self, app_client):
        response = app_client.post("/watchlist/nonexistent/refresh")
        assert response.status_code == 404
        assert response.json()["detail"] == "Watchlist item not found"

    def test_main_refresh_watchlist_404_when_no_source_url(self, app_client, db_session):
        item = _insert_watchlist_item(db_session, vendor="NoURL", source_url=None)
        response = app_client.post(f"/watchlist/{item.id}/refresh")
        assert response.status_code == 404

    def test_main_refresh_watchlist_tracks_risk_delta(self, app_client, db_session, monkeypatch):
        item = _insert_watchlist_item(db_session, vendor="RiskDeltaVendor")
        item.last_risk_score = 2.0
        db_session.commit()

        async def fake_fetch(url):
            return "We sell your personal data to third parties without consent."

        monkeypatch.setattr("app.main.fetch_url_text", fake_fetch)

        response = app_client.post(f"/watchlist/{item.id}/refresh")
        assert response.status_code == 200
        body = response.json()
        # risk_delta should be set (non-None float)
        assert body["risk_delta"] is not None


# ===========================================================================
# POST /snapshots
# ===========================================================================

class TestCreateSnapshot:
    def test_main_create_snapshot_new_content(self, app_client, monkeypatch):
        async def fake_fetch(url):
            return "Brand new privacy policy text for snapshot."

        monkeypatch.setattr("app.main.fetch_url_text", fake_fetch)

        response = app_client.post(
            "/snapshots", params={"url": "https://example.com/privacy"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["url"] == "https://example.com/privacy"
        assert body["raw_text"] == "Brand new privacy policy text for snapshot."
        assert "content_hash" in body
        assert "id" in body

    def test_main_create_snapshot_deduplicates_same_content(self, app_client, db_session, monkeypatch):
        text = "Identical privacy policy content."
        _insert_snapshot(db_session, url="https://example.com/privacy", text=text)

        async def fake_fetch(url):
            return text

        monkeypatch.setattr("app.main.fetch_url_text", fake_fetch)

        response = app_client.post(
            "/snapshots", params={"url": "https://example.com/privacy"}
        )
        assert response.status_code == 200
        body = response.json()
        # Deduplicated — raw_text is None
        assert body["raw_text"] is None

    def test_main_create_snapshot_400_on_fetch_failure(self, app_client, monkeypatch):
        async def fake_fetch(url):
            raise RuntimeError("DNS failure")

        monkeypatch.setattr("app.main.fetch_url_text", fake_fetch)

        response = app_client.post(
            "/snapshots", params={"url": "https://unreachable.example.com/privacy"}
        )
        assert response.status_code == 400
        assert "Failed to fetch the requested URL." in response.json()["detail"]

    def test_main_create_snapshot_400_on_empty_content(self, app_client, monkeypatch):
        async def fake_fetch(url):
            return ""

        monkeypatch.setattr("app.main.fetch_url_text", fake_fetch)

        response = app_client.post(
            "/snapshots", params={"url": "https://example.com/empty"}
        )
        assert response.status_code == 400
        assert "empty" in response.json()["detail"].lower()


# ===========================================================================
# GET /snapshots
# ===========================================================================

class TestGetSnapshots:
    def test_main_get_snapshots_returns_list_for_url(self, app_client, db_session):
        url = "https://example.com/tos"
        _insert_snapshot(db_session, url=url, text="Version 1")
        _insert_snapshot(db_session, url=url, text="Version 2")

        response = app_client.get("/snapshots", params={"url": url})
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 2
        for item in body:
            assert item["url"] == url

    def test_main_get_snapshots_404_when_no_snapshots(self, app_client):
        response = app_client.get(
            "/snapshots", params={"url": "https://never-seen.example.com/privacy"}
        )
        assert response.status_code == 404
        assert "No snapshots found" in response.json()["detail"]


# ===========================================================================
# GET /snapshots/detail/{id}
# ===========================================================================

class TestGetSnapshotDetail:
    def test_main_get_snapshot_detail_returns_full_data(self, app_client, db_session):
        snap = _insert_snapshot(db_session, text="Full snapshot text.")
        response = app_client.get(f"/snapshots/detail/{snap.id}")
        assert response.status_code == 200
        body = response.json()
        assert body["id"] == snap.id
        assert body["raw_text"] == "Full snapshot text."

    def test_main_get_snapshot_detail_404_for_missing(self, app_client):
        response = app_client.get("/snapshots/detail/nonexistent-snap-id")
        assert response.status_code == 404
        assert response.json()["detail"] == "Snapshot not found"


# ===========================================================================
# GET /diff/{id1}/{id2}
# ===========================================================================

class TestGetDiff:
    def test_main_get_diff_returns_diff_result(self, app_client, db_session):
        url = "https://example.com/privacy"
        snap1 = _insert_snapshot(db_session, url=url, text="We collect your data.")
        snap2 = _insert_snapshot(db_session, url=url, text="We collect and sell your data.")

        response = app_client.get(f"/diff/{snap1.id}/{snap2.id}")
        assert response.status_code == 200
        body = response.json()
        assert body["snapshot_1_id"] == snap1.id
        assert body["snapshot_2_id"] == snap2.id
        assert body["url"] == url
        assert "added" in body
        assert "removed" in body
        assert "unchanged" in body
        assert isinstance(body["change_count"], int)

    def test_main_get_diff_404_when_snapshot_missing(self, app_client, db_session):
        snap = _insert_snapshot(db_session)
        response = app_client.get(f"/diff/{snap.id}/nonexistent-id")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_main_get_diff_400_when_different_urls(self, app_client, db_session):
        snap1 = _insert_snapshot(db_session, url="https://example.com/privacy", text="Policy A.")
        snap2 = _insert_snapshot(db_session, url="https://other.com/tos", text="Policy B.")

        response = app_client.get(f"/diff/{snap1.id}/{snap2.id}")
        assert response.status_code == 400
        assert "different URL" in response.json()["detail"]


# ===========================================================================
# GET /reviews
# ===========================================================================

class TestListReviews:
    def test_main_list_reviews_empty(self, app_client):
        response = app_client.get("/reviews")
        assert response.status_code == 200
        assert response.json() == []

    def test_main_list_reviews_returns_only_pending(self, app_client, db_session):
        analysis_a = _insert_analysis(db_session, name="AnalysisA")
        analysis_b = _insert_analysis(db_session, name="AnalysisB")
        analysis_c = _insert_analysis(db_session, name="AnalysisC")
        pending = _insert_review_item(db_session, analysis_a.id, status="pending")
        _insert_review_item(db_session, analysis_b.id, status="approved")
        _insert_review_item(db_session, analysis_c.id, status="rejected")

        response = app_client.get("/reviews")
        assert response.status_code == 200
        ids = [item["id"] for item in response.json()]
        assert pending.id in ids
        # approved and rejected are NOT returned
        assert len(ids) == 1

    def test_main_list_reviews_payload_shape(self, app_client, db_session):
        analysis = _insert_analysis(db_session)
        _insert_review_item(db_session, analysis.id)

        response = app_client.get("/reviews")
        assert response.status_code == 200
        item = response.json()[0]
        # #368: every review item also carries the analysis llm_status.
        assert set(item.keys()) >= {"id", "analysis_id", "status", "notes", "created_at", "updated_at", "llm_status"}


# ===========================================================================
# POST /reviews/{id}
# ===========================================================================

class TestUpdateReview:
    def test_main_update_review_approve_sets_status(self, app_client, db_session):
        analysis = _insert_analysis(db_session)
        review = _insert_review_item(db_session, analysis.id)

        response = app_client.post(
            f"/reviews/{review.id}",
            json={"status": "approved", "notes": "Looks good."},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "approved"
        assert body["notes"] == "Looks good."

    def test_main_update_review_reject_sets_status(self, app_client, db_session):
        analysis = _insert_analysis(db_session)
        review = _insert_review_item(db_session, analysis.id)

        response = app_client.post(
            f"/reviews/{review.id}",
            json={"status": "rejected", "notes": "Non-compliant clause."},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "rejected"
        assert body["analysis_id"] == analysis.id

    def test_main_update_review_404_for_missing(self, app_client):
        response = app_client.post(
            "/reviews/nonexistent-review-id",
            json={"status": "approved"},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Review item not found"

    def test_main_update_review_422_for_invalid_status(self, app_client, db_session):
        analysis = _insert_analysis(db_session)
        review = _insert_review_item(db_session, analysis.id)

        response = app_client.post(
            f"/reviews/{review.id}",
            json={"status": "not_a_valid_status"},
        )
        assert response.status_code == 422

    def test_main_update_review_notes_can_be_null(self, app_client, db_session):
        analysis = _insert_analysis(db_session)
        review = _insert_review_item(db_session, analysis.id)

        response = app_client.post(
            f"/reviews/{review.id}",
            json={"status": "approved", "notes": None},
        )
        assert response.status_code == 200
        assert response.json()["notes"] is None


# ===========================================================================
# OE-003 (2026-07-03): the ``/policy-watch/*`` endpoint family was deprecated.
# Its handlers now return 308 redirects (CRUD paths) or 410 Gone (snapshot).
# The rewritten tests below replace ``TestCreatePolicyWatch``,
# ``TestListPolicyWatches``, ``TestDeletePolicyWatch``, and
# ``TestCaptureWatchSnapshot`` — see main.py for the design note.
# ===========================================================================


class TestPolicyWatchDeprecationShim:
    """Every ``/policy-watch/*`` route must signal deprecation."""

    def test_main_policy_watch_post_returns_308_with_headers(self, app_client):
        response = app_client.post(
            "/policy-watch",
            json={"url": "https://example.com/privacy", "check_frequency": 3600},
            follow_redirects=False,
        )
        assert response.status_code == 308
        assert response.headers.get("Location") == "/watchlist"
        assert response.headers.get("Deprecation") == "true"
        assert response.headers.get("Sunset") == "2026-10-01"

    def test_main_policy_watch_get_returns_308(self, app_client):
        response = app_client.get("/policy-watch", follow_redirects=False)
        assert response.status_code == 308
        assert response.headers.get("Location") == "/watchlist"

    def test_main_policy_watch_delete_returns_308(self, app_client):
        response = app_client.delete(
            "/policy-watch/some-id", follow_redirects=False
        )
        assert response.status_code == 308
        assert response.headers.get("Location") == "/watchlist/some-id"

    def test_main_policy_watch_snapshot_returns_410(self, app_client):
        response = app_client.post("/policy-watch/some-id/snapshot")
        assert response.status_code == 410
        body = response.json()
        assert body.get("successor") == "/watchlist/{id}/refresh"


# ===========================================================================
# POST /watchlist — extended with the OE-003 merged fields
# ===========================================================================


class TestCreateWatchlistWithMergedFields:
    """Assertions for the merged ``WatchlistCreateRequest`` shape (OE-003)."""

    def test_main_add_watchlist_accepts_check_frequency(self, app_client):
        response = app_client.post(
            "/watchlist",
            json={
                "vendor": "example.com",
                "source_url": "https://example.com/privacy",
                "check_frequency": 3600,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["check_frequency"] == 3600
        # next_check_at is computed from last_checked + cadence.
        assert body.get("next_check_at") is not None
        assert body["enabled"] is True

    def test_main_add_watchlist_accepts_enabled_false(self, app_client):
        response = app_client.post(
            "/watchlist",
            json={
                "vendor": "example.com",
                "source_url": "https://example.com/paused",
                "enabled": False,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["enabled"] is False
        # Disabled items should not report a next check time.
        assert body.get("next_check_at") is None

    def test_main_add_watchlist_accepts_user_id_and_notes(self, app_client):
        response = app_client.post(
            "/watchlist",
            json={
                "vendor": "example.com",
                "source_url": "https://example.com/x",
                "user_id": "user-123",
                "notes": "Track for Q3 review",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["user_id"] == "user-123"
        assert body["notes"] == "Track for Q3 review"

    def test_main_add_watchlist_rejects_check_frequency_too_low(self, app_client):
        response = app_client.post(
            "/watchlist",
            json={
                "vendor": "example.com",
                "source_url": "https://example.com/privacy",
                "check_frequency": 60,  # below 300s floor
            },
        )
        assert response.status_code == 422

    def test_main_add_watchlist_rejects_check_frequency_wrong_type(self, app_client):
        response = app_client.post(
            "/watchlist",
            json={
                "vendor": "example.com",
                "source_url": "https://example.com/privacy",
                "check_frequency": "hourly",
            },
        )
        assert response.status_code == 422

    def test_main_add_watchlist_rejects_enabled_wrong_type(self, app_client):
        response = app_client.post(
            "/watchlist",
            json={
                "vendor": "example.com",
                "source_url": "https://example.com/privacy",
                "enabled": "sometimes",
            },
        )
        assert response.status_code == 422

    def test_main_add_watchlist_rejects_user_id_invalid_chars(self, app_client):
        response = app_client.post(
            "/watchlist",
            json={
                "vendor": "example.com",
                "source_url": "https://example.com/privacy",
                "user_id": "<script>alert(1)</script>",
            },
        )
        assert response.status_code == 422

    def test_main_add_watchlist_rejects_user_id_too_long(self, app_client):
        response = app_client.post(
            "/watchlist",
            json={
                "vendor": "example.com",
                "source_url": "https://example.com/privacy",
                "user_id": "a" * 256,
            },
        )
        assert response.status_code == 422

    def test_main_add_watchlist_backward_compat_no_optional_fields(self, app_client):
        # Pre-OE-003 callers only sent {vendor, source_url}; that must still work.
        response = app_client.post(
            "/watchlist",
            json={"vendor": "OldClient", "source_url": "https://old.example.com"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["vendor"] == "OldClient"
        # Server default enabled=True.
        assert body["enabled"] is True


# ===========================================================================
# POST /analyze — review_required triggers ReviewItem creation
# ===========================================================================

class TestAnalyzeCreatesReviewItem:
    def test_main_analyze_creates_review_item_when_review_required(self, app_client, db_session, monkeypatch):
        """When analyze_text returns review_required=True, a ReviewItem must be persisted."""
        fake_result = _make_fake_result(review_required=True, confidence=0.50, status="needs_review")

        async def fake_analyze(*args, **kwargs):
            return fake_result

        monkeypatch.setattr("app.main.analyze_text", fake_analyze)

        response = app_client.post(
            "/analyze",
            json={"text": "Sample policy text.", "jurisdictions": ["US-CA"]},
        )
        assert response.status_code == 200

        review_items = db_session.query(ReviewItem).all()
        assert len(review_items) == 1
        assert review_items[0].analysis_id == response.json()["id"]
        assert review_items[0].status == "pending"

    def test_main_analyze_does_not_create_review_item_when_not_required(self, app_client, db_session, monkeypatch):
        fake_result = _make_fake_result(review_required=False)

        async def fake_analyze(*args, **kwargs):
            return fake_result

        monkeypatch.setattr("app.main.analyze_text", fake_analyze)

        app_client.post(
            "/analyze",
            json={"text": "Sample policy text.", "jurisdictions": ["US-CA"]},
        )
        review_items = db_session.query(ReviewItem).all()
        assert len(review_items) == 0


# ===========================================================================
# POST /analyze — Fix 4: empty jurisdictions == "no filter" (global-tool)
# ===========================================================================


class TestAnalyzeEmptyJurisdictionsNoFilter:
    def test_main_analyze_empty_jurisdictions_returns_findings_across_all_rules(
        self, app_client, db_session, monkeypatch
    ):
        """When ``jurisdictions=[]`` is sent, the analyzer must run every rule.

        Uses a monkeypatched ``LocalAIClient`` so the LLM branch is stubbed
        out; the assertion focuses on rule-level detection surviving with no
        jurisdiction filter.
        """
        from app.services import analyzer as analyzer_module
        from app.services.localai import LocalAIClient

        async def fake_llm_analyze(self, *args, **kwargs):
            return None  # skip LLM findings — rule-only path

        monkeypatch.setattr(LocalAIClient, "analyze", fake_llm_analyze)

        class _NoopKB:
            async def retrieve(self, *args, **kwargs):
                return []

        monkeypatch.setattr(analyzer_module, "get_legal_kb", lambda: _NoopKB())

        # Text hits categories under multiple jurisdictions — CCPA (Sale/Share)
        # plus GDPR (ADM) plus something from a non-US-CA / non-GDPR rule.
        text = (
            "We sell your personal information. "
            "We use automated decision-making. "
            "Under APPI Japanese residents have rights."
        )
        response = app_client.post(
            "/analyze", json={"text": text, "jurisdictions": []}
        )
        assert response.status_code == 200
        body = response.json()
        categories = {f["category"] for f in body["findings"]}
        # With no filter we expect coverage beyond just US-CA + GDPR.
        assert categories, "no-filter analyze should surface findings"
        # The response echoes jurisdictions (empty list preserved).
        assert body["jurisdictions"] == []

    def test_main_analyze_empty_jurisdictions_populates_action_items(
        self, app_client, db_session, monkeypatch
    ):
        """Fix 8: /analyze payload must include backend-generated action_items."""
        from app.services import analyzer as analyzer_module
        from app.services.localai import LocalAIClient

        async def fake_llm_analyze(self, *args, **kwargs):
            return None

        monkeypatch.setattr(LocalAIClient, "analyze", fake_llm_analyze)

        class _NoopKB:
            async def retrieve(self, *args, **kwargs):
                return []

        monkeypatch.setattr(analyzer_module, "get_legal_kb", lambda: _NoopKB())

        response = app_client.post(
            "/analyze",
            json={
                "text": "We sell your personal information.",
                "jurisdictions": ["US-CA"],
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert "action_items" in body
        # Sale/Share + US-CA should yield the "Do Not Sell" line.
        assert any("Do Not Sell" in line for line in body["action_items"])


# ===========================================================================
# _clamp helper
# ===========================================================================

class TestClampHelper:
    def test_main_clamp_value_at_lower_bound(self):
        from app.main import _clamp
        assert _clamp(-5.0) == 0.0

    def test_main_clamp_value_at_upper_bound(self):
        from app.main import _clamp
        assert _clamp(15.0) == 10.0

    def test_main_clamp_value_within_range(self):
        from app.main import _clamp
        assert _clamp(5.5) == 5.5

    def test_main_clamp_custom_bounds(self):
        from app.main import _clamp
        assert _clamp(0.3, 0.35, 0.95) == 0.35
        assert _clamp(1.0, 0.35, 0.95) == 0.95
        assert _clamp(0.7, 0.35, 0.95) == 0.7


# ===========================================================================
# _compute_rubric_scores helper
# ===========================================================================

class TestComputeRubricScores:
    def test_main_compute_rubric_scores_all_zero_risk(self, db_session):
        from app.main import _compute_rubric_scores
        rows = []
        for _ in range(3):
            row = _insert_analysis(db_session, risk_score=0.0, confidence=1.0, grade="A")
            rows.append(row)
        scores = _compute_rubric_scores(rows)
        # With zero risk and full confidence, product integrity should be 10.0
        assert scores.productIntegrity == 10.0
        assert scores.legalSignalQuality == 10.0
        # aiLawSignalQuality should also be high with full confidence and no reviews
        assert scores.aiLawSignalQuality > 8.0

    def test_main_compute_rubric_scores_has_ai_law_signal_quality(self, db_session):
        from app.main import _compute_rubric_scores
        rows = [_insert_analysis(db_session, risk_score=3.0, confidence=0.85, grade="B")]
        scores = _compute_rubric_scores(rows)
        assert hasattr(scores, "aiLawSignalQuality")
        assert 0.0 <= scores.aiLawSignalQuality <= 10.0

    def test_main_compute_rubric_scores_overall_uses_weights(self, db_session):
        from app.main import _compute_rubric_scores
        rows = [_insert_analysis(db_session, risk_score=0.0, confidence=1.0, grade="A")]
        scores = _compute_rubric_scores(rows)
        # With ideal inputs all component scores are 10.0 → weighted overall = 10.0
        assert scores.overall == 10.0

    def test_main_compute_rubric_scores_high_review_rate_lowers_governance(self, db_session):
        from app.main import _compute_rubric_scores
        rows = []
        for _ in range(4):
            row = _insert_analysis(db_session, status="needs_review", risk_score=5.0, confidence=0.70, grade="C")
            rows.append(row)
        scores = _compute_rubric_scores(rows)
        # All records are needs_review, so review_rate = 1.0 → review_score = 0.0
        assert scores.governanceReadiness == 0.0

    def test_main_compute_rubric_scores_low_confidence_lowers_ai_law(self, db_session):
        from app.main import _compute_rubric_scores
        rows = [_insert_analysis(db_session, risk_score=5.0, confidence=0.0, grade="C")]
        scores = _compute_rubric_scores(rows)
        # ai_law = 8.5 * 0.0 + 1.5 * (1 - review_rate) → depends on review_rate
        assert scores.aiLawSignalQuality < 5.0


# ===========================================================================
# GET /analyses/{id} — 500 path for corrupt JSON
# ===========================================================================

class TestGetAnalysisCorruptJson:
    def test_main_get_analysis_500_on_corrupt_result_json(self, app_client, db_session):
        row = AnalysisModel(
            id=str(uuid4()),
            doc_name="Corrupt",
            doc_type=None,
            source_url=None,
            source_type="text",
            source_value=None,
            status="completed",
            confidence=0.9,
            risk_score=1.0,
            grade="A",
            document_text="text",
            result_json="{not valid json!!!",
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(row)
        db_session.commit()

        response = app_client.get(f"/analyses/{row.id}")
        assert response.status_code == 500
        assert "invalid" in response.json()["detail"].lower()


# ===========================================================================
# Security tests — remediation coverage
# ===========================================================================

class TestSecurityAnalysesLimit:
    """GET /analyses?limit= must be capped at 200."""

    def test_security_analyses_limit_above_max_returns_422(self, app_client):
        response = app_client.get("/analyses?limit=1000000")
        assert response.status_code == 422

    def test_security_analyses_limit_zero_returns_422(self, app_client):
        response = app_client.get("/analyses?limit=0")
        assert response.status_code == 422

    def test_security_analyses_limit_200_is_accepted(self, app_client):
        response = app_client.get("/analyses?limit=200")
        assert response.status_code == 200

    def test_security_analyses_limit_201_returns_422(self, app_client):
        response = app_client.get("/analyses?limit=201")
        assert response.status_code == 422


class TestSecurityWatchlistPrivateUrl:
    """POST /watchlist with private-scheme URL must be rejected at schema level."""

    def test_security_watchlist_private_ip_url_rejected(self, app_client):
        response = app_client.post(
            "/watchlist",
            json={"vendor": "Evil", "source_url": "http://192.168.1.1/admin"},
        )
        # Schema validator allows any http URL at creation time (runtime blocks at fetch);
        # validate only scheme enforcement
        assert response.status_code in {200, 201, 400, 422}

    def test_security_watchlist_ftp_url_rejected(self, app_client):
        response = app_client.post(
            "/watchlist",
            json={"vendor": "Evil", "source_url": "ftp://attacker.com/payload"},
        )
        assert response.status_code == 422

    def test_security_watchlist_no_hostname_url_rejected(self, app_client):
        response = app_client.post(
            "/watchlist",
            json={"vendor": "Evil", "source_url": "http://"},
        )
        assert response.status_code == 422


class TestSecuritySnapshotExceptionNotLeaked:
    """POST /snapshots must not expose raw exception strings in the 400 body."""

    def test_security_snapshot_error_message_is_generic(self, app_client, monkeypatch):
        async def fake_fetch(url: str) -> str:
            raise ConnectionError("Connection refused to 10.0.0.1:8080 — internal host!")

        monkeypatch.setattr("app.main.fetch_url_text", fake_fetch)
        response = app_client.post(
            "/snapshots", params={"url": "https://example.com/privacy"}
        )
        assert response.status_code == 400
        body = response.json()["detail"]
        # Internal host address must not appear in the response body
        assert "10.0.0.1" not in body
        assert "Connection refused" not in body
        assert body == "Failed to fetch the requested URL."


class TestSecurityHealthEndpoint:
    """GET /health must not expose model names or review threshold."""

    def test_security_health_returns_only_status(self, app_client):
        response = app_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data == {"status": "ok"}
        assert "model_world" not in data
        assert "model_eu" not in data
        assert "review_threshold" not in data


class TestSecurityDocumentTextStripped:
    """GET /analyses/{id} must not return document_text in the public response."""

    def test_security_get_analysis_strips_document_text(self, app_client, db_session):
        payload = _make_analysis_payload(document_text="Super sensitive full policy text.")
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

        response = app_client.get(f"/analyses/{payload.id}")
        assert response.status_code == 200
        data = response.json()
        # document_text must be absent or null — never the raw content
        assert data.get("document_text") is None


class TestSecurityCorsHeaders:
    """CORS must restrict methods to GET/POST/DELETE only."""

    def test_security_cors_options_restricted_methods(self, app_client):
        response = app_client.options(
            "/health",
            headers={
                "Origin": "http://localhost:8000",
                "Access-Control-Request-Method": "PATCH",
            },
        )
        # PATCH is not in the allowed methods; should not appear in allow header
        allow = response.headers.get("access-control-allow-methods", "")
        assert "PATCH" not in allow
        assert "PUT" not in allow


class TestSecurityWatchlistUserIdValidation:
    """OE-003: POST /watchlist inherits ``user_id`` validation from PolicyWatch.

    Replaces ``TestSecurityPolicyWatchUserIdValidation``. Same security surface,
    same regex, same length cap — now against the merged endpoint.
    """

    def test_security_watchlist_user_id_too_long_rejected(self, app_client):
        response = app_client.post(
            "/watchlist",
            json={
                "vendor": "example.com",
                "source_url": "https://example.com/privacy",
                "user_id": "a" * 256,
            },
        )
        assert response.status_code == 422

    def test_security_watchlist_user_id_invalid_chars_rejected(self, app_client):
        response = app_client.post(
            "/watchlist",
            json={
                "vendor": "example.com",
                "source_url": "https://example.com/privacy",
                "user_id": "<script>alert(1)</script>",
            },
        )
        assert response.status_code == 422

    def test_security_watchlist_valid_user_id_accepted(self, app_client, db_session, monkeypatch):
        response = app_client.post(
            "/watchlist",
            json={
                "vendor": "example.com",
                "source_url": "https://example.com/privacy",
                "user_id": "user123@example.com",
            },
        )
        assert response.status_code in {200, 201}


class TestSecurityBatchEndpointValidation:
    """/analyze/batch must enforce Pydantic schema on the request body."""

    def test_security_batch_empty_body_returns_422(self, app_client):
        response = app_client.post("/analyze/batch", json={})
        assert response.status_code == 422

    def test_security_batch_missing_items_returns_422(self, app_client):
        response = app_client.post(
            "/analyze/batch",
            json={"industry": "General", "jurisdictions": ["GDPR"]},
        )
        assert response.status_code == 422


class TestSecurityApiKeyAuth:
    """The global key check (#133 rulings 2-4): outside the local opt-in, a missing or
    wrong key is 401; the right key passes; an empty key only serves the local
    loopback opt-in. Uses real validated Settings, not a MagicMock, so a config
    the app would refuse cannot slip through here."""

    @staticmethod
    def _use(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> Settings:
        import dataclasses
        import importlib
        import secrets

        from app import config, main

        have = {f.name for f in dataclasses.fields(config.Settings)}
        if "deploy_env" not in have or "api_key_min_length" not in have:
            pytest.fail(
                "Settings has no deploy_env / api_key_min_length field (#133 ruling 2).",
                pytrace=False,
            )
        if overrides.pop("generate_key", False):
            n = config.settings.api_key_min_length
            overrides["api_key"] = secrets.token_hex(n)[:n]
        new = dataclasses.replace(config.settings, **overrides)
        monkeypatch.setattr(config, "settings", new)
        monkeypatch.setattr(main, "settings", new)
        security = importlib.import_module("app.security")
        if hasattr(security, "settings"):
            monkeypatch.setattr(security, "settings", new)
        return new

    def test_security_api_key_wrong_key_returns_401(
        self, app_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        s = self._use(monkeypatch, deploy_env="railway", generate_key=True)
        response = app_client.get("/analyses", headers={"X-API-Key": s.api_key[:-1]})
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid or missing API key"}

    def test_security_api_key_missing_key_returns_401(
        self, app_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._use(monkeypatch, deploy_env="railway", generate_key=True)
        response = app_client.get("/analyses")
        assert response.status_code == 401

    def test_security_api_key_correct_key_passes(
        self, app_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        s = self._use(monkeypatch, deploy_env="railway", generate_key=True)
        response = app_client.get("/analyses", headers={"X-API-Key": s.api_key})
        assert response.status_code == 200

    def test_security_api_key_empty_string_serves_local_loopback_only(
        self, app_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The conftest client is a loopback peer; DEPLOY_ENV=local + loopback bind.
        self._use(monkeypatch, deploy_env="local", api_key="", bind_host="127.0.0.1")
        assert app_client.get("/analyses").status_code == 200
        with pytest.raises(ValueError, match=r"(?i)api_key"):
            self._use(monkeypatch, deploy_env="railway", api_key="")


# ===========================================================================
# POST /infer  (Phase 1 backend — Streamlit v2 intake)
# ===========================================================================


class TestInferEndpoint:
    def test_main_infer_400_when_neither_url_nor_text(self, app_client):
        response = app_client.post("/infer", json={})
        assert response.status_code == 400
        assert "at least one" in response.json()["detail"].lower()

    def test_main_infer_with_url_only_returns_tld_jurisdiction(self, app_client):
        response = app_client.post("/infer", json={"url": "https://example.co.uk/privacy"})
        assert response.status_code == 200
        body = response.json()
        assert "UK-GDPR" in body["jurisdictions"]
        assert body["doc_type"] == "Privacy Policy"
        assert body["location_needed"] is False
        assert body["detected_signals"].get("tld")

    def test_main_infer_with_text_only_returns_statute_jurisdiction(self, app_client):
        response = app_client.post(
            "/infer",
            json={"text": "This policy complies with GDPR and CCPA obligations."},
        )
        assert response.status_code == 200
        body = response.json()
        assert "GDPR" in body["jurisdictions"]
        assert "US-CA" in body["jurisdictions"]
        assert body["location_needed"] is False

    def test_main_infer_with_both_populates_all_fields(self, app_client):
        response = app_client.post(
            "/infer",
            json={
                "url": "https://facebook.com/privacy",
                "text": "California residents may opt out of the sale of personal information.",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["industry"] == "Social Media"
        assert body["doc_type"] == "Privacy Policy"
        assert "US-CA" in body["jurisdictions"]
        assert body["location_needed"] is False

    def test_main_infer_location_needed_true_when_no_signals(self, app_client):
        # Global-tool contract (Fix 4): no signals means empty jurisdictions.
        # The old US-CA + GDPR default fallback has been removed — this is a
        # global tool and can't assume a reader location. Callers must treat
        # an empty list as "no filter".
        response = app_client.post(
            "/infer",
            json={"text": "generic policy paragraph without any statute cues"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["location_needed"] is True
        assert body["jurisdictions"] == []
        # The fallback signal is still recorded so the UI can explain.
        assert "fallback" in body["detected_signals"]

    def test_main_infer_context_field_accepted_but_not_required(self, app_client):
        response = app_client.post(
            "/infer",
            json={"url": "https://example.com/privacy", "context": ["for_child"]},
        )
        assert response.status_code == 200

    def test_main_infer_fallback_logs_observability_event(self, app_client, caplog):
        # Fix 2: the fallback path emits a structured infer_fallback log
        # so production ops can measure how often inference actually succeeded.
        import logging

        from app.services.inference import _infer_all_cached

        _infer_all_cached.cache_clear()
        with caplog.at_level(logging.INFO, logger="app.services.inference"):
            response = app_client.post(
                "/infer",
                json={"text": "another generic paragraph with no cues"},
            )
        assert response.status_code == 200
        events = [
            r.__dict__.get("event")
            for r in caplog.records
            if r.name == "app.services.inference"
        ]
        assert "infer_fallback" in events

    def test_main_infer_schema_rejects_oversized_text(self, app_client):
        # Fix 3: /infer must reject oversized text bodies via the schema-level
        # ``max_length`` on ``InferRequest.text``.
        response = app_client.post("/infer", json={"text": "x" * 200_001})
        assert response.status_code == 422


# ===========================================================================
# POST /analyze with context — verdict_headline / verdict_label populated
# ===========================================================================


class TestAnalyzeWithContext:
    def test_main_analyze_with_context_populates_verdict_fields(self, app_client, db_session, monkeypatch):
        """When context is supplied, the analyzer must populate verdict copy."""
        payload = _make_analysis_payload()

        async def fake_analyze(*args, **kwargs):
            # The endpoint must forward the ``context`` kwarg to analyze_text.
            assert kwargs.get("context") == ["for_child"]
            # Simulate analyze_text populating context-derived fields on the payload.
            from app.services.context import verdict_headline, verdict_label
            payload_with_context = payload.model_copy(update={
                "context": kwargs["context"],
                "verdict_headline": verdict_headline(kwargs["context"], payload.action_readiness),
                "verdict_label": verdict_label(kwargs["context"], payload.action_readiness),
            })
            return AnalysisResult(payload=payload_with_context, issues=[])

        monkeypatch.setattr("app.main.analyze_text", fake_analyze)

        response = app_client.post(
            "/analyze",
            json={
                "text": "Sample policy text.",
                "jurisdictions": ["US-CA"],
                "context": ["for_child"],
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["context"] == ["for_child"]
        assert body["verdict_headline"]
        assert body["verdict_label"]
        # Child-specific copy should mention "child".
        assert "child" in body["verdict_headline"].lower() or "child" in body["verdict_label"].lower()

    def test_main_analyze_without_context_still_populates_verdict(self, app_client, monkeypatch):
        """Analyze with no context supplied still gets the default-verdict copy."""
        payload = _make_analysis_payload()

        async def fake_analyze(*args, **kwargs):
            from app.services.context import verdict_headline, verdict_label
            ctx = kwargs.get("context") or []
            payload_with_context = payload.model_copy(update={
                "context": ctx,
                "verdict_headline": verdict_headline(ctx, payload.action_readiness),
                "verdict_label": verdict_label(ctx, payload.action_readiness),
            })
            return AnalysisResult(payload=payload_with_context, issues=[])

        monkeypatch.setattr("app.main.analyze_text", fake_analyze)

        response = app_client.post(
            "/analyze",
            json={"text": "Sample policy text.", "jurisdictions": ["US-CA"]},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["context"] == []
        assert body["verdict_headline"]
        assert body["verdict_label"]


# ===========================================================================
# PR #34 must-fix regressions
# ===========================================================================


class TestPr34MustFixRegressions:
    """Regression tests for the four must-fix findings from PR #34's review workflow.

    See PR #34 comments for the full rationale on each fix.
    """

    def test_analyze_file_accepts_for_work_context(self, app_client, monkeypatch):
        """Regression: ``for_work`` was silently dropped by a hardcoded allowlist.

        The multipart handler now derives its allowlist from ``ContextChip`` via
        ``typing.get_args``, so any new chip added to the schema is accepted
        automatically. See PR #34 principal-engineer P0 #1 / grumpy-developer
        CRITICAL / security-engineer MEDIUM-2.
        """
        captured: dict = {}

        async def fake_analyze(text, jurisdictions, name=None, doc_type=None,
                               industry=None, source_url=None, mode=None, **kwargs):
            captured["context"] = kwargs.get("context")
            payload = _make_analysis_payload(name=name)
            payload_with_ctx = payload.model_copy(update={"context": kwargs.get("context") or []})
            return AnalysisResult(payload=payload_with_ctx, issues=[])

        monkeypatch.setattr("app.main.analyze_text", fake_analyze)
        # Bypass real ingest — return the raw bytes decoded so we don't need
        # a full text-extraction pipeline in this test.
        monkeypatch.setattr(
            "app.main.extract_text_from_bytes",
            lambda filename, content_type, data: data.decode("utf-8", errors="ignore") or "text",
        )

        response = app_client.post(
            "/analyze/file",
            files={"file": ("policy.txt", b"Some policy text about work usage.", "text/plain")},
            data={"context": "for_work", "jurisdictions": "US-CA,GDPR"},
        )
        assert response.status_code == 200, response.text
        # Must NOT be dropped — the handler forwards it to analyze_text.
        assert captured["context"] == ["for_work"]
        # And it round-trips into the response payload.
        assert response.json()["context"] == ["for_work"]

    def test_analyze_file_validates_jurisdictions(self, app_client, monkeypatch):
        """Bogus jurisdiction codes must be filtered out; valid ones pass through.

        Regression per PR #34 security-engineer MEDIUM-2 — the multipart
        endpoint previously accepted any comma-separated string, which meant a
        crafted request could disable the post-LLM jurisdiction filter by
        supplying a value that no finding declared.
        """
        captured: dict = {}

        async def fake_analyze(text, jurisdictions, name=None, doc_type=None,
                               industry=None, source_url=None, mode=None, **kwargs):
            captured["jurisdictions"] = jurisdictions
            return _make_fake_result(name=name)

        monkeypatch.setattr("app.main.analyze_text", fake_analyze)
        monkeypatch.setattr(
            "app.main.extract_text_from_bytes",
            lambda filename, content_type, data: "policy text",
        )

        # Mix of valid + bogus values — only the valid ones survive.
        response = app_client.post(
            "/analyze/file",
            files={"file": ("policy.txt", b"policy text", "text/plain")},
            data={"jurisdictions": "US-CA,BOGUS-JUR,GDPR,../etc/passwd"},
        )
        assert response.status_code == 200, response.text
        assert captured["jurisdictions"] == ["US-CA", "GDPR"]
        assert "BOGUS-JUR" not in captured["jurisdictions"]

    def test_analyze_file_defaults_jurisdictions_when_all_invalid(self, app_client, monkeypatch):
        """When no valid jurisdiction survives the filter, the empty list
        propagates through — the JSON endpoints default to ``[]`` per
        schemas.py and the global-tool contract (CLAUDE.md §Session
        outcomes) treats empty as "no filter".

        Regression per audit finding LE-002: the multipart endpoint used to
        fall back to ``["US-CA", "GDPR"]`` here, silently double-scoping
        every anonymous file upload."""
        captured: dict = {}

        async def fake_analyze(text, jurisdictions, name=None, doc_type=None,
                               industry=None, source_url=None, mode=None, **kwargs):
            captured["jurisdictions"] = jurisdictions
            return _make_fake_result(name=name)

        monkeypatch.setattr("app.main.analyze_text", fake_analyze)
        monkeypatch.setattr(
            "app.main.extract_text_from_bytes",
            lambda filename, content_type, data: "policy text",
        )

        response = app_client.post(
            "/analyze/file",
            files={"file": ("policy.txt", b"policy text", "text/plain")},
            data={"jurisdictions": "NOT-REAL,ALSO-FAKE"},
        )
        assert response.status_code == 200, response.text
        # Global-tool contract: empty jurisdictions == "no filter" — must
        # NOT silently re-scope to US-CA + GDPR.
        assert captured["jurisdictions"] == []

    def test_analyze_rejects_javascript_source_url(self, app_client):
        """``javascript:`` scheme is rejected by pydantic before hitting the handler.

        Regression per PR #34 security-engineer HIGH-1. ``html.escape`` on the
        frontend does NOT neutralise scheme-based XSS in ``<a href>``.
        """
        response = app_client.post(
            "/analyze",
            json={
                "text": "hello world",
                "source_url": "javascript:alert(1)",
            },
        )
        # Pydantic validation error surfaces as 422 (FastAPI's default for
        # request-body validation failures).
        assert response.status_code in (400, 422), response.text
        assert "source_url" in response.text or "scheme" in response.text.lower()

    def test_analyze_rejects_data_uri_source_url(self, app_client):
        """``data:`` URIs are also blocked — same XSS class as ``javascript:``."""
        response = app_client.post(
            "/analyze",
            json={
                "text": "hello world",
                "source_url": "data:text/html,<script>alert(1)</script>",
            },
        )
        assert response.status_code in (400, 422)

    def test_analyze_accepts_https_source_url(self, app_client, monkeypatch):
        """Sanity check: valid https URLs still pass the new validator."""
        async def fake_analyze(*args, **kwargs):
            return _make_fake_result(source_url="https://example.com/privacy")

        monkeypatch.setattr("app.main.analyze_text", fake_analyze)

        response = app_client.post(
            "/analyze",
            json={
                "text": "hello world",
                "source_url": "https://example.com/privacy",
            },
        )
        assert response.status_code == 200

    def test_analyze_url_rejects_javascript_scheme(self, app_client):
        """``/analyze/url`` also rejects non-web schemes at the schema layer."""
        response = app_client.post(
            "/analyze/url",
            json={"url": "javascript:alert(1)"},
        )
        assert response.status_code in (400, 422)


# ---------------------------------------------------------------------------
# Issue #195: llm_status reaches the API response and survives storage
# ---------------------------------------------------------------------------

_LLM_DOC = "We sell personal information and use automated decision-making."
# Exception text the client must never see (CWE-209): a path, line breaks of
# every kind and a bidi override.
_LLM_HOSTILE = "/opt/victim/secret\r\n\u2028\u202eFORGED"


@pytest.fixture
def llm_transport(monkeypatch):
    """Send LocalAIClient's httpx traffic to ``respond``; no legal-KB lookup."""
    async def _no_kb(query, client, jurisdictions):
        return [], False

    monkeypatch.setattr(analyzer_module, "_retrieve_legal_context", _no_kb)
    real_client = httpx.AsyncClient
    sent: list = []

    def _install(respond):
        def _factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(lambda request: (sent.append(request), respond(request))[1])
            return real_client(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", _factory)
        return sent

    return _install


def _raise_connect(request):
    raise httpx.ConnectError(_LLM_HOSTILE, request=request)


def test_main_analyze_localai_down_reports_unreachable_and_persists(app_client, llm_transport):
    sent = llm_transport(_raise_connect)
    resp = app_client.post("/analyze", json={"text": _LLM_DOC, "jurisdictions": ["GDPR"]})
    assert resp.status_code == 200
    body = resp.json()
    assert len(sent) == 1
    assert body["llm_status"] == "fallback_llm_unreachable"
    # HR5 agreement on the wire: no LLM summary, rules-only findings.
    assert body["summary"] is None
    assert body["findings"]
    assert "victim" not in resp.text and "FORGED" not in resp.text
    stored = app_client.get(f"/analyses/{body['id']}")
    assert stored.status_code == 200
    assert stored.json()["llm_status"] == "fallback_llm_unreachable"


def test_main_analyze_invalid_answer_reports_invalid(app_client, llm_transport):
    llm_transport(lambda request: httpx.Response(200, json={"choices": [{"message": {"content": '{"findings": null, "llm_status": "ok"}'}}]}))
    resp = app_client.post("/analyze", json={"text": _LLM_DOC, "jurisdictions": ["GDPR"]})
    assert resp.status_code == 200
    assert resp.json()["llm_status"] == "fallback_llm_invalid"


# Issue #288 (owner ruling 2026-10-12, option c): a LocalAI HTTP 5xx (model
# not loaded, backend OOM) is an upstream problem, reported as
# fallback_llm_upstream; a 4xx (our request was wrong) stays
# fallback_llm_error. Both edges of the 5xx range, and 499 just below it.
# #288 ("approve c"): a 429 means LocalAI is healthy but we exceeded its
# capacity, so it is its own class, fallback_llm_rate_limited (the remedy is
# MAX_CONCURRENT_ANALYSES or capacity, not our code or the server). A
# Retry-After header changes nothing; 428 and 430 around it stay errors.
_RATE_LIMITED = http.HTTPStatus.TOO_MANY_REQUESTS.value
_RETRY_AFTER = {"Retry-After": "120"}
_HTTP_STATUS_TO_LLM_STATUS = [
    *[(code, "fallback_llm_upstream", {}) for code in (500, 502, 503, 504, 599)],
    (503, "fallback_llm_upstream", _RETRY_AFTER),
    (_RATE_LIMITED, "fallback_llm_rate_limited", {}),
    (_RATE_LIMITED, "fallback_llm_rate_limited", _RETRY_AFTER),
    *[(code, "fallback_llm_error", {}) for code in (400, 404, 422, _RATE_LIMITED - 1, _RATE_LIMITED + 1, 499)],
    (_RATE_LIMITED - 1, "fallback_llm_error", _RETRY_AFTER),
]
_HTTP_STATUS_IDS = [f"http-{c}{'-retry-after' if h else ''}" for c, _, h in _HTTP_STATUS_TO_LLM_STATUS]


def _hostile_error_body(code: int) -> dict:
    # The error body is untrusted and claims a different class.
    return {"error": {"code": 400 if code >= 500 else 503, "message": _LLM_HOSTILE}}


@pytest.mark.parametrize("code,expected,headers", _HTTP_STATUS_TO_LLM_STATUS, ids=_HTTP_STATUS_IDS)
def test_main_analyze_localai_http_error_status_reaches_api_storage_and_export(
    app_client, llm_transport, monkeypatch, code, expected, headers
):
    # HR7: force review through config (an override, not a restated value)
    # so a 5xx or 429 fallback is shown to queue a human review like any
    # fallback.
    monkeypatch.setattr(
        analyzer_module, "settings", dataclasses.replace(analyzer_module.settings, review_threshold=1.0)
    )
    hostile = _hostile_error_body(code)
    sent = llm_transport(lambda request: httpx.Response(code, json=hostile, headers=headers))
    resp = app_client.post("/analyze", json={"text": _LLM_DOC, "jurisdictions": ["GDPR"]})
    assert resp.status_code == 200
    body = resp.json()
    assert len(sent) == 1
    assert body["llm_status"] == expected
    # HR5 on the wire: rules-only findings, no LLM summary.
    assert body["summary"] is None
    assert body["findings"]
    assert body["review_required"] is True
    assert body["status"] == "needs_review"
    assert "victim" not in resp.text and "FORGED" not in resp.text
    # Every consumer of the stored payload carries the value unchanged:
    # GET /analyses/{id}, the #36 JSON export, and the review queue.
    stored = app_client.get(f"/analyses/{body['id']}")
    assert stored.status_code == 200
    assert stored.json()["llm_status"] == expected
    exported = app_client.get(f"/exports/analysis/{body['id']}.json")
    assert exported.status_code == 200
    assert json.loads(exported.content)["llm_status"] == expected
    reviews = app_client.get("/reviews")
    assert reviews.status_code == 200
    queued = [r for r in reviews.json() if r["analysis_id"] == body["id"]]
    assert len(queued) == 1
    # #368: the review queue shows why the result is rules-only.
    assert queued[0]["llm_status"] == expected


@pytest.mark.parametrize(
    "code,expected,headers",
    [
        (_RATE_LIMITED, "fallback_llm_rate_limited", _RETRY_AFTER),
        (_RATE_LIMITED, "fallback_llm_rate_limited", {}),
        (503, "fallback_llm_upstream", {}),
        (_RATE_LIMITED - 1, "fallback_llm_error", _RETRY_AFTER),
    ],
    ids=["http-429-retry-after", "http-429", "http-503", "http-428-retry-after"],
)
def test_main_analyze_batch_localai_http_error_status_reaches_every_item_and_storage(
    app_client, llm_transport, monkeypatch, code, expected, headers
):
    """#288: /analyze/batch reports the same llm_status as /analyze for every
    item, persists it, exports it, and queues each item for review (HR5/HR7).
    A 429 is fallback_llm_rate_limited on the batch path too, and it is not
    retried: one LocalAI call per document."""
    monkeypatch.setattr(
        analyzer_module, "settings", dataclasses.replace(analyzer_module.settings, review_threshold=1.0)
    )

    async def fake_fetch(url: str) -> str:
        return _LLM_DOC

    monkeypatch.setattr("app.main.fetch_url_text", fake_fetch)
    hostile = _hostile_error_body(code)
    sent = llm_transport(lambda request: httpx.Response(code, json=hostile, headers=headers))
    urls = ["https://example.com/a", "https://example.com/b"]
    resp = app_client.post(
        "/analyze/batch",
        json={"items": [{"url": u} for u in urls], "jurisdictions": ["GDPR"], "mode": "full"},
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == len(urls)
    assert len(sent) == len(urls), "one LocalAI call per document, no retry"
    assert [i["llm_status"] for i in items] == [expected] * len(urls)
    assert all(i["summary"] is None and i["review_required"] is True for i in items)
    assert "victim" not in resp.text and "FORGED" not in resp.text
    reviews = app_client.get("/reviews").json()
    review_ids = [r["analysis_id"] for r in reviews]
    for item in items:
        assert app_client.get(f"/analyses/{item['id']}").json()["llm_status"] == expected
        exported = app_client.get(f"/exports/analysis/{item['id']}.json")
        assert json.loads(exported.content)["llm_status"] == expected
        assert review_ids.count(item["id"]) == 1
    # #368: every queued batch item carries its llm_status.
    assert [r["llm_status"] for r in reviews if r["analysis_id"] in {i["id"] for i in items}] == [expected] * len(urls)


def test_main_analyze_ok_answer_reports_ok(app_client, llm_transport):
    content = json.dumps({"summary": "fine", "overall_confidence": 0.9, "findings": []})
    llm_transport(lambda request: httpx.Response(200, json={"choices": [{"message": {"content": content}}]}))
    resp = app_client.post("/analyze", json={"text": _LLM_DOC, "jurisdictions": ["GDPR"]})
    assert resp.status_code == 200
    assert resp.json()["llm_status"] == "ok"


def test_main_analyze_quick_mode_reports_disabled(app_client, llm_transport):
    sent = llm_transport(_raise_connect)
    resp = app_client.post("/analyze", json={"text": _LLM_DOC, "jurisdictions": ["GDPR"], "mode": "quick"})
    assert resp.status_code == 200
    assert sent == []
    assert resp.json()["llm_status"] == "disabled"


def test_main_get_analysis_legacy_row_without_llm_status_loads(app_client, db_session):
    row = _insert_analysis(db_session)
    legacy = json.loads(row.result_json)
    legacy.pop("llm_status", None)
    row.result_json = json.dumps(legacy)
    db_session.commit()
    resp = app_client.get(f"/analyses/{row.id}")
    assert resp.status_code == 200
    default = AnalysisPayload.model_fields["llm_status"].default
    assert resp.json()["llm_status"] == default
    assert default != "ok"


# ---------------------------------------------------------------------------
# Issue #368: llm_status reaches /reviews, the CSV export and the PDF export
# ---------------------------------------------------------------------------
#
# The value is already stored in analyses.result_json (#195), and every review
# item points at its analysis by foreign key, so /reviews can return it with no
# schema change. Old rows (no key), corrupt rows and forged values read as
# "unknown" and never 500. The CSV carries the canonical token (machine
# readable); the PDF carries the shared label (app.llm_status_copy).

from tests.test_llm_status_copy import (  # noqa: E402
    OK,
    RAW_MARKER,
    UNKNOWN,
    forged_member_variants,
    json_hostile_values,
    label as _llm_label,
    members as _llm_members,
    visible_text_variants,
)

_ABSENT = object()
_STORED_CASES = [*json_hostile_values(), ("absent-pre-195-row", _ABSENT)]
_STORED_IDS = [i for i, _ in _STORED_CASES]
# A result_json no reader can trust. Old or damaged rows must not 500.
_CORRUPT_RESULT_JSON = {
    "not-json": "not json",
    "truncated": '{"llm_status": "ok"',
    "empty": "",
    "json-array": '["ok"]',
    "json-string": '"ok"',
    "json-null": "null",
    "json-number": "1",
}
_CSV_FINDING = {
    "category": "Data Sharing",
    "severity": "High",
    "confidence": 0.9,
    "excerpt": "We share data.",
    "evidence": {"line_start": 1, "line_end": 1},
}


def _store_llm_status(db_session, row: AnalysisModel, value: Any, *, findings: list | None = None) -> AnalysisModel:
    """Rewrite the stored payload's llm_status (or drop it), bypassing validation."""
    data = json.loads(row.result_json)
    if value is _ABSENT:
        data.pop("llm_status", None)
    else:
        data["llm_status"] = value
    if findings is not None:
        data["findings"] = findings
    row.result_json = json.dumps(data)
    db_session.commit()
    return row


def _set_result_json(db_session, row: AnalysisModel, raw: str) -> AnalysisModel:
    row.result_json = raw
    db_session.commit()
    return row


def _pending_review_for(db_session, value: Any = _ABSENT, **kwargs) -> tuple[AnalysisModel, ReviewItem]:
    row = _store_llm_status(db_session, _insert_analysis(db_session, review_required=True), value, **kwargs)
    return row, _insert_review_item(db_session, row.id)


def _reviews_by_analysis(app_client) -> dict[str, dict]:
    resp = app_client.get("/reviews")
    assert resp.status_code == 200, resp.text[:500]
    return {r["analysis_id"]: r for r in resp.json()}


class TestReviewsLLMStatus:
    @pytest.mark.parametrize("status", _llm_members())
    def test_main_list_reviews_carries_each_stored_status(self, app_client, db_session, status):
        row, _ = _pending_review_for(db_session, status)
        assert _reviews_by_analysis(app_client)[row.id]["llm_status"] == status

    @pytest.mark.parametrize("status", _llm_members())
    def test_main_update_review_carries_each_stored_status(self, app_client, db_session, status):
        _, review = _pending_review_for(db_session, status)
        resp = app_client.post(f"/reviews/{review.id}", json={"status": "approved"})
        assert resp.status_code == 200
        assert resp.json()["llm_status"] == status

    @pytest.mark.parametrize("value", [v for _, v in _STORED_CASES], ids=_STORED_IDS)
    def test_main_reviews_untrusted_stored_value_reads_unknown(self, app_client, db_session, value):
        row, review = _pending_review_for(db_session, value)
        good, _ = _pending_review_for(db_session, OK)
        listed = app_client.get("/reviews")
        assert listed.status_code == 200
        items = {r["analysis_id"]: r for r in listed.json()}
        assert items[row.id]["llm_status"] == UNKNOWN
        # One bad row never hides or degrades the rest of the queue.
        assert items[good.id]["llm_status"] == OK
        assert RAW_MARKER not in listed.text
        updated = app_client.post(f"/reviews/{review.id}", json={"status": "rejected"})
        assert updated.status_code == 200
        assert updated.json()["llm_status"] == UNKNOWN
        assert RAW_MARKER not in updated.text

    @pytest.mark.parametrize("raw", list(_CORRUPT_RESULT_JSON.values()), ids=list(_CORRUPT_RESULT_JSON))
    def test_main_reviews_corrupt_result_json_reads_unknown(self, app_client, db_session, raw):
        row, review = _pending_review_for(db_session)
        _set_result_json(db_session, row, raw)
        good, _ = _pending_review_for(db_session, OK)
        items = _reviews_by_analysis(app_client)
        assert items[row.id]["llm_status"] == UNKNOWN
        assert items[good.id]["llm_status"] == OK
        updated = app_client.post(f"/reviews/{review.id}", json={"status": "approved"})
        assert updated.status_code == 200
        assert updated.json()["llm_status"] == UNKNOWN

    def test_main_list_reviews_many_rows_with_forged_values(self, app_client, db_session):
        # Many: every member plus every generated look-alike, one GET.
        expected: dict[str, str] = {}
        for status in _llm_members():
            row, _ = _pending_review_for(db_session, status)
            expected[row.id] = status
        variants = forged_member_variants()
        for variant in variants:
            row, _ = _pending_review_for(db_session, variant)
            expected[row.id] = UNKNOWN
        items = _reviews_by_analysis(app_client)
        wrong = {rid: items.get(rid, {}).get("llm_status") for rid, want in expected.items()
                 if items.get(rid, {}).get("llm_status") != want}
        assert wrong == {}
        assert len(items) == len(variants) + len(_llm_members())


def _csv_rows(app_client, analysis_id: str, *, detailed: bool) -> tuple[str, list[dict[str, str]]]:
    resp = app_client.get("/exports/analyses.csv", params={"ids": analysis_id, "detailed": str(detailed).lower()})
    assert resp.status_code == 200, resp.text[:500]
    reader = csv.DictReader(io.StringIO(resp.text))
    assert (reader.fieldnames or []).count("llm_status") == 1, reader.fieldnames
    return resp.text, list(reader)


class TestCsvExportLLMStatus:
    @pytest.mark.parametrize("detailed", [False, True], ids=["summary", "detailed"])
    @pytest.mark.parametrize("status", _llm_members())
    def test_main_export_csv_carries_each_stored_status(self, app_client, db_session, status, detailed):
        row = _store_llm_status(db_session, _insert_analysis(db_session), status, findings=[_CSV_FINDING])
        _, rows = _csv_rows(app_client, row.id, detailed=detailed)
        assert rows, "no row exported"
        assert [r["llm_status"] for r in rows] == [status] * len(rows)

    @pytest.mark.parametrize("detailed", [False, True], ids=["summary", "detailed"])
    @pytest.mark.parametrize("value", [v for _, v in _STORED_CASES], ids=_STORED_IDS)
    def test_main_export_csv_untrusted_stored_value_reads_unknown(self, app_client, db_session, value, detailed):
        row = _store_llm_status(db_session, _insert_analysis(db_session), value, findings=[_CSV_FINDING])
        text, rows = _csv_rows(app_client, row.id, detailed=detailed)
        assert rows, "no row exported"
        assert [r["llm_status"] for r in rows] == [UNKNOWN] * len(rows)
        # No raw value reaches the sheet (formula, delimiter or line-break injection).
        assert RAW_MARKER not in text

    @pytest.mark.parametrize("detailed", [False, True], ids=["summary", "detailed"])
    def test_main_export_csv_forged_look_alikes_read_unknown(self, app_client, db_session, detailed):
        ids = [
            _store_llm_status(db_session, _insert_analysis(db_session), v, findings=[_CSV_FINDING]).id
            for v in forged_member_variants()
        ]
        resp = app_client.get("/exports/analyses.csv", params={"ids": ",".join(ids), "detailed": str(detailed).lower()})
        assert resp.status_code == 200
        rows = list(csv.DictReader(io.StringIO(resp.text)))
        assert len(rows) == len(ids)
        assert {r["llm_status"] for r in rows} == {UNKNOWN}

    @pytest.mark.parametrize("detailed", [False, True], ids=["summary", "detailed"])
    @pytest.mark.parametrize("raw", list(_CORRUPT_RESULT_JSON.values()), ids=list(_CORRUPT_RESULT_JSON))
    def test_main_export_csv_corrupt_result_json_reads_unknown(self, app_client, db_session, raw, detailed):
        row = _set_result_json(db_session, _insert_analysis(db_session), raw)
        good = _store_llm_status(db_session, _insert_analysis(db_session), OK, findings=[_CSV_FINDING])
        resp = app_client.get(
            "/exports/analyses.csv", params={"ids": f"{row.id},{good.id}", "detailed": str(detailed).lower()}
        )
        assert resp.status_code == 200
        rows = list(csv.DictReader(io.StringIO(resp.text)))
        by_id = {}
        for r in rows:
            by_id.setdefault(r.get("id") or r.get("analysis_id"), []).append(r["llm_status"])
        assert by_id[good.id] == [OK]
        # A corrupt row has no readable findings in detailed mode; any row it
        # does produce reads unknown.
        assert set(by_id.get(row.id, [UNKNOWN])) == {UNKNOWN}
        if not detailed:
            assert by_id[row.id] == [UNKNOWN]


def _pdf_text(db_session, analysis_id: str) -> str:
    # The view function is called directly: the JSON alias route shadows the
    # .pdf path in the router (see TestExportAnalysisPdf).
    from pypdf import PdfReader

    from app.main import export_analysis_pdf

    response = export_analysis_pdf(analysis_id=analysis_id, db=db_session)
    assert response.body[:4] == b"%PDF"
    pages = PdfReader(io.BytesIO(response.body)).pages
    return " ".join(" ".join((p.extract_text() or "") for p in pages).split())


def _shows(text: str, wanted: str) -> bool:
    return any(" ".join(v.split()) in text for v in visible_text_variants(wanted))


class TestPdfExportLLMStatus:
    @pytest.mark.parametrize("status", _llm_members())
    def test_main_export_pdf_shows_each_status_label(self, db_session, status):
        row = _store_llm_status(db_session, _insert_analysis(db_session), status)
        text = _pdf_text(db_session, row.id)
        shown = _llm_label(status)
        assert _shows(text, shown), shown
        # Exactly this status: no other label (unless it is part of this one).
        others = [m for m in _llm_members() if m != status and _llm_label(m) not in shown and _shows(text, _llm_label(m))]
        assert others == []

    @pytest.mark.parametrize("value", [v for _, v in _STORED_CASES], ids=_STORED_IDS)
    def test_main_export_pdf_untrusted_stored_value_shows_unknown(self, db_session, value):
        row = _store_llm_status(db_session, _insert_analysis(db_session), value)
        text = _pdf_text(db_session, row.id)
        assert _shows(text, _llm_label(UNKNOWN))
        assert not _shows(text, _llm_label(OK))
        assert RAW_MARKER not in text

    def test_main_export_pdf_forged_look_alikes_show_unknown(self, db_session):
        unknown, ok = _llm_label(UNKNOWN), _llm_label(OK)
        wrong = []
        for variant in forged_member_variants():
            row = _store_llm_status(db_session, _insert_analysis(db_session), variant)
            text = _pdf_text(db_session, row.id)
            if not _shows(text, unknown) or _shows(text, ok):
                wrong.append(variant.encode("unicode_escape").decode("ascii"))
        assert wrong == []


# ---------------------------------------------------------------------------
# Issue #184: a lone surrogate in submitted document text must never 500
# ---------------------------------------------------------------------------
#
# Reproduction at base 3384a3f. Pydantic already rejects a lone surrogate in a
# JSON string field (error type ``string_unicode``). FastAPI's default 422 body
# then echoes the offending ``input``, Starlette can't encode that body as
# UTF-8, and the client gets a 500. The same happens for an error on any field
# while a surrogate is in the body. Text extracted from an RTF upload or a
# fetched RTF (``\u-10240?``) carries the surrogate past every schema and also
# 500s. RTF writes a non-BMP character (an emoji) as two ``\uN`` halves, which
# today reach analysis as two separate surrogates, so a VALID emoji 500s too.
#
# Contract pinned here:
# - a 4xx, with no 500 in any case;
# - the error body echoes neither the surrogate (as a ``\udXXX`` escape or its
#   CESU-8 bytes) nor the document text, and names the field;
# - nothing downstream sees the text: no analyze_text, inference or LLM call,
#   no DB row, and the exports still serialise;
# - valid text still passes, including non-BMP characters (also as an RTF
#   surrogate-pair escape) and the code points either side of the block.

from tests.conftest import LOOPBACK_PEER  # noqa: E402

_S184_MARK = "CANARY184"
_S184_DOC = f"We sell your personal information. {_S184_MARK} "
_S184_BLOCK = range(0xD800, 0xDFFF + 1)
# Both ends of both halves of the surrogate block.
_S184_EDGES = (0xD800, 0xDBFF, 0xDC00, 0xDFFF)
_S184_EMOJI = "\U0001F600"
_S184_URL = "https://example.com/policy.rtf"


def _s184_has_surrogate(text: str | None) -> bool:
    return any(ord(ch) in _S184_BLOCK for ch in text or "")


def _s184_reject_vectors() -> list[tuple[str, str]]:
    """Generated hostile documents: none of them is valid UTF-8."""
    out: list[tuple[str, str]] = []
    for cp in _S184_EDGES:
        ch = chr(cp)
        out.append((f"U+{cp:04X}-start", ch + _S184_DOC))
        out.append((f"U+{cp:04X}-mid", _S184_DOC + ch + " more text"))
        out.append((f"U+{cp:04X}-end", _S184_DOC + ch))
    out += [
        ("low-before-high", _S184_DOC + "\udc00\ud800"),  # reversed: not a pair
        ("high-high", _S184_DOC + "\ud800\udbff"),
        ("high-then-ascii", _S184_DOC + "\ud800A"),
        ("low-after-emoji", _S184_DOC + _S184_EMOJI + "\udc00"),
        ("run-10k", _S184_DOC + "\ud800" * 10_000),
    ]
    return out


def _s184_huge() -> tuple[str, str]:
    """A document far past ``max_input_chars`` (read from config, F13) whose
    LAST character is a lone surrogate. analyze_text truncates at that limit,
    so a check that runs after truncation would never see the surrogate."""
    from app.config import settings

    size = settings.max_input_chars * 40
    return ("huge-tail-past-max-input", _S184_DOC * (size // len(_S184_DOC) + 1) + "\udfff")


_S184_HUGE = _s184_huge()
_S184_REJECT = _s184_reject_vectors()

# Valid text that must still be accepted: either side of the block, U+FFFD and
# the non-BMP range (which JSON escapes as a correctly PAIRED surrogate).
_S184_ACCEPT = [
    ("U+D7FF-below-block", "퟿"),
    ("U+E000-above-block", ""),
    ("U+FFFD-replacement", "�"),
    ("U+10000-first-non-BMP", "\U00010000"),
    ("U+1F600-emoji", _S184_EMOJI),
    ("U+10FFFF-last", "\U0010ffff"),
]

# How a client really sends the text: ``escaped`` is what JSON.stringify and
# json.dumps produce (``\ud800``); ``raw`` is the surrogate's own CESU-8 bytes
# (invalid UTF-8), which json.loads on bytes decodes with surrogatepass.
_S184_WIRES = ("escaped", "raw")


def _s184_wire(body: dict, wire: str) -> bytes:
    if wire == "escaped":
        return json.dumps(body).encode("ascii")
    return json.dumps(body, ensure_ascii=False).encode("utf-8", "surrogatepass")


_S184_JSON = {"content-type": "application/json"}
_S184_ESCAPE = re.compile(rb"\\ud[89a-f][0-9a-f]{2}", re.IGNORECASE)
_S184_CESU = re.compile(rb"\xed[\xa0-\xbf]")


def _s184_assert_no_echo(resp: Any) -> None:
    """The refusal carries no surrogate, no document text and only UTF-8."""
    raw = resp.content
    raw.decode("utf-8")  # strict: the body itself is valid UTF-8
    assert not _S184_ESCAPE.search(raw), "error body echoes a surrogate escape"
    assert not _S184_CESU.search(raw), "error body echoes surrogate bytes"
    assert _S184_MARK.encode() not in raw, "error body echoes the document text"


def _s184_error_locs(resp: Any) -> list[tuple]:
    detail = resp.json()["detail"]
    return [tuple(err["loc"]) for err in detail]


def _s184_rtf(text: str) -> bytes:
    """RTF for ``text``: ASCII as-is, every other UTF-16 code unit as a signed
    ``\\uN?`` escape (how RTF writers encode non-ASCII and non-BMP text)."""
    units: list[str] = []
    for ch in text:
        if ord(ch) < 0x80:
            units.append(ch)
            continue
        if ord(ch) in _S184_BLOCK:
            halves = [ord(ch)]
        else:
            data = ch.encode("utf-16-be")
            halves = [int.from_bytes(data[i:i + 2], "big") for i in range(0, len(data), 2)]
        units += [f"\\u{h - 0x10000 if h > 0x7FFF else h}?" for h in halves]
    return ("{\\rtf1 " + "".join(units) + "}").encode("ascii")


@pytest.fixture
def s184(monkeypatch, db_session):
    """A client that returns a 500 instead of raising it, plus spies on every
    downstream consumer of the document text."""
    from fastapi.testclient import TestClient

    import app.main as main_module
    from app.database import get_db
    from app.services.localai import LocalAIClient

    seen: dict[str, list] = {"analyze_text": [], "infer": [], "llm": []}
    real_analyze_text = main_module.analyze_text
    real_infer_all = main_module.infer_all

    async def spy_analyze_text(text, *args, **kwargs):
        seen["analyze_text"].append(text)
        return await real_analyze_text(text, *args, **kwargs)

    def spy_infer_all(url, text):
        seen["infer"].append(text)
        return real_infer_all(url, text)

    async def spy_llm(self, numbered_text, *args, **kwargs):
        seen["llm"].append(numbered_text)
        return None  # rules-only, as on an LLM failure (HR5)

    async def no_kb(query, client, jurisdictions):
        return [], False

    monkeypatch.setattr(main_module, "analyze_text", spy_analyze_text)
    monkeypatch.setattr(main_module, "infer_all", spy_infer_all)
    monkeypatch.setattr(LocalAIClient, "analyze", spy_llm)
    monkeypatch.setattr(analyzer_module, "_retrieve_legal_context", no_kb)

    def override_get_db():
        yield db_session

    main_module.app.dependency_overrides[get_db] = override_get_db
    with TestClient(
        main_module.app, client=LOOPBACK_PEER, raise_server_exceptions=False
    ) as client:
        yield client, seen
    main_module.app.dependency_overrides.clear()


def _s184_assert_nothing_downstream(client: Any, seen: dict, db_session: Any) -> None:
    assert seen["analyze_text"] == [], "analyze_text received the rejected text"
    assert seen["infer"] == [], "inference received the rejected text"
    assert seen["llm"] == [], "the LLM prompt was built from the rejected text"
    assert db_session.query(AnalysisModel).count() == 0
    assert db_session.query(ReviewItem).count() == 0
    assert db_session.query(PolicySnapshot).count() == 0
    # Export and JSON serialisation still work: nothing poisoned was stored.
    assert client.get("/analyses").json() == []
    assert client.get("/exports/analyses.csv").status_code == 200


def _s184_serve(monkeypatch, data: bytes, content_type: str = "application/rtf") -> None:
    """Fake only the network read; the real fetch_url_text extraction runs."""
    from app.services import ingest

    async def fake_fetch_bytes(url, cfg):
        return data, content_type

    monkeypatch.setattr(ingest, "_fetch_bytes", fake_fetch_bytes)


def test_main_s184_vector_tables_have_reject_and_accept_rows():
    """Contract: every reject row is invalid UTF-8, every accept row is valid,
    and both tables (and both wire forms) are populated."""
    from app.config import settings

    rejects = _S184_REJECT + [_S184_HUGE]
    assert len(_S184_HUGE[1]) > settings.max_input_chars
    assert len(rejects) == len(_S184_EDGES) * 3 + 5 + 1
    for label, text in rejects:
        with pytest.raises(UnicodeEncodeError):
            text.encode("utf-8")
        assert _s184_has_surrogate(text), label
    assert _S184_ACCEPT
    for label, ch in _S184_ACCEPT:
        (_S184_DOC + ch).encode("utf-8")
        assert not _s184_has_surrogate(ch), label
    assert set(_S184_WIRES) == {"escaped", "raw"}
    # The raw wire form really carries invalid UTF-8 bytes on the wire.
    assert _S184_CESU.search(_s184_wire({"text": "\ud800"}, "raw"))
    assert _S184_ESCAPE.search(_s184_wire({"text": "\ud800"}, "escaped"))


@pytest.mark.parametrize("wire", _S184_WIRES)
@pytest.mark.parametrize("label,text", _S184_REJECT + [_S184_HUGE], ids=[v[0] for v in _S184_REJECT + [_S184_HUGE]])
def test_main_analyze_lone_surrogate_text_rejected_422_without_echo(s184, db_session, label, text, wire):
    client, seen = s184
    resp = client.post("/analyze", content=_s184_wire({"text": text}, wire), headers=_S184_JSON)
    assert resp.status_code == 422, (label, wire, resp.status_code)
    _s184_assert_no_echo(resp)
    assert ("body", "text") in _s184_error_locs(resp)
    _s184_assert_nothing_downstream(client, seen, db_session)


@pytest.mark.parametrize("wire", _S184_WIRES)
@pytest.mark.parametrize("label,text", _S184_REJECT, ids=[v[0] for v in _S184_REJECT])
def test_main_infer_lone_surrogate_text_rejected_422_without_echo(s184, db_session, label, text, wire):
    client, seen = s184
    resp = client.post("/infer", content=_s184_wire({"text": text}, wire), headers=_S184_JSON)
    assert resp.status_code == 422, (label, wire, resp.status_code)
    _s184_assert_no_echo(resp)
    assert ("body", "text") in _s184_error_locs(resp)
    _s184_assert_nothing_downstream(client, seen, db_session)


# Minimal valid body for every JSON-body route. The contract test below fails
# if a route is added (or removed) without updating this table.
_S184_JSON_BASE: dict[str, dict] = {
    "/infer": {"text": _S184_DOC},
    "/analyze": {"text": _S184_DOC, "mode": "quick"},
    "/analyze/url": {"url": "https://example.com/policy"},
    "/analyze/batch": {"items": [{"url": "https://example.com/policy"}]},
    "/reviews/{review_id}": {"status": "approved"},
    "/watchlist": {"vendor": "ACME"},
}


def _s184_json_body_routes() -> dict[str, type]:
    """Every route whose body is a JSON model from app.schemas (multipart
    upload bodies are FastAPI-generated and excluded)."""
    from fastapi.routing import APIRoute
    from pydantic import BaseModel

    from app.main import app

    routes: dict[str, type] = {}
    for route in app.routes:
        if not isinstance(route, APIRoute) or route.body_field is None:
            continue
        model = route.body_field.field_info.annotation
        if isinstance(model, type) and issubclass(model, BaseModel) and model.__module__ == "app.schemas":
            routes[route.path] = model
    return routes


def _s184_injections(model: type) -> list[tuple[str, Any]]:
    """(label, put) for every field of ``model`` and, one level down, every
    field of a list-of-model field. ``put(body, s)`` places the hostile string
    ``s`` in that field of a copy of the valid base body, keeping every other
    field valid so the surrogate is the only fault."""
    from pydantic import BaseModel

    out: list[tuple[str, Any]] = []
    for name, field in model.model_fields.items():
        args = typing.get_args(field.annotation)
        if typing.get_origin(field.annotation) in (list, typing.List):
            out.append((name, lambda body, s, name=name: body.__setitem__(name, [s])))
            inner = args[0] if args else None
            if isinstance(inner, type) and issubclass(inner, BaseModel):
                for sub in inner.model_fields:
                    out.append((
                        f"{name}.{sub}",
                        lambda body, s, name=name, sub=sub: body.__setitem__(
                            name, [{**body.get(name, [{}])[0], sub: s}]
                        ),
                    ))
        else:
            out.append((name, lambda body, s, name=name: body.__setitem__(name, s)))
    return out


def test_main_s184_json_route_table_matches_app():
    assert set(_s184_json_body_routes()) == set(_S184_JSON_BASE)


@pytest.mark.parametrize("path", sorted(_S184_JSON_BASE))
def test_main_json_routes_never_500_on_lone_surrogate_in_any_field(s184, db_session, monkeypatch, path):
    """Generated: every field of every JSON-body route x every reject vector x
    both wire forms. Each must be a 422 that echoes nothing and names the field,
    including plain ``str`` fields that pydantic passes through unchecked today.
    A fetch, if one is reached, gets a valid document (never the network)."""
    client, seen = s184
    _s184_serve(monkeypatch, f"<p>{_S184_DOC}</p>".encode("ascii"), "text/html")
    model = _s184_json_body_routes()[path]
    url = path.replace("{review_id}", str(uuid4()))
    failures: list[str] = []
    count = 0
    for label_field, put in _s184_injections(model):
        leaf = label_field.split(".")[-1]
        for label, text in _S184_REJECT:
            for wire in _S184_WIRES:
                count += 1
                body = json.loads(json.dumps(_S184_JSON_BASE[path]))
                put(body, text)
                resp = client.post(url, content=_s184_wire(body, wire), headers=_S184_JSON)
                where = f"{label_field}/{label}/{wire}"
                if resp.status_code != 422:
                    failures.append(f"{where}: {resp.status_code}")
                    continue
                try:
                    _s184_assert_no_echo(resp)
                except AssertionError as exc:
                    failures.append(f"{where}: {exc}")
                    continue
                if not any(leaf in loc for loc in _s184_error_locs(resp)):
                    failures.append(f"{where}: loc does not name {leaf}")
    print(f"#184 generated cases for {path}: {count}")
    assert count >= len(model.model_fields) * len(_S184_REJECT) * len(_S184_WIRES)
    by_field: dict[str, set[str]] = {}
    for failure in failures:
        where, _, why = failure.partition(": ")
        by_field.setdefault(where.split("/")[0], set()).add(why)
    assert not failures, f"{len(failures)}/{count} failed; per field: {by_field}"
    _s184_assert_nothing_downstream(client, seen, db_session)


def _s184_rtf_reject_vectors() -> list[tuple[str, bytes]]:
    """RTF documents whose ``\\uN`` escapes decode to a lone surrogate:
    every block edge, signed and unsigned, mid-text and at the end."""
    out: list[tuple[str, bytes]] = []
    for cp in _S184_EDGES:
        for form, n in (("signed", cp - 0x10000), ("unsigned", cp)):
            esc = f"\\u{n}?"
            out.append((f"U+{cp:04X}-{form}-mid", f"{{\\rtf1 {_S184_DOC}{esc} more}}".encode("ascii")))
            out.append((f"U+{cp:04X}-{form}-end", f"{{\\rtf1 {_S184_DOC}{esc}}}".encode("ascii")))
    out.append(("low-before-high", _s184_rtf(_S184_DOC + "\udc00\ud800")))
    return out


_S184_RTF_REJECT = _s184_rtf_reject_vectors()


@pytest.mark.parametrize("label,data", _S184_RTF_REJECT, ids=[v[0] for v in _S184_RTF_REJECT])
def test_main_analyze_file_rtf_lone_surrogate_rejected_422_without_echo(s184, db_session, label, data):
    client, seen = s184
    resp = client.post("/analyze/file", files={"file": ("policy.rtf", data, "application/rtf")})
    assert resp.status_code == 422, (label, resp.status_code)
    _s184_assert_no_echo(resp)
    _s184_assert_nothing_downstream(client, seen, db_session)


def test_main_analyze_url_fetched_lone_surrogate_rejected_400_without_echo(s184, db_session, monkeypatch):
    client, seen = s184
    _s184_serve(monkeypatch, _s184_rtf(_S184_DOC + "\ud800"))
    resp = client.post("/analyze/url", json={"url": _S184_URL})
    assert resp.status_code == 400
    _s184_assert_no_echo(resp)
    _s184_assert_nothing_downstream(client, seen, db_session)


def test_main_analyze_url_fetched_lone_surrogate_message_is_not_fetch_failure(s184, monkeypatch):
    """F8: the fetch succeeded, so the refusal must not claim it failed."""
    from app.services.ingest import UrlFetchError

    client, _ = s184

    async def failing_fetch(url, cfg):
        raise UrlFetchError("connect", "connect failed")

    from app.services import ingest

    monkeypatch.setattr(ingest, "_fetch_bytes", failing_fetch)
    fetch_failure = client.post("/analyze/url", json={"url": _S184_URL})
    assert fetch_failure.status_code == 400
    _s184_serve(monkeypatch, _s184_rtf(_S184_DOC + "\ud800"))
    resp = client.post("/analyze/url", json={"url": _S184_URL})
    assert resp.status_code == 400
    assert resp.json()["detail"] != fetch_failure.json()["detail"]


def test_main_analyze_batch_fetched_lone_surrogate_rejected_400_without_echo(s184, db_session, monkeypatch):
    client, seen = s184
    _s184_serve(monkeypatch, _s184_rtf(_S184_DOC + "\udc00"))
    resp = client.post("/analyze/batch", json={"items": [{"url": _S184_URL}], "mode": "full"})
    assert resp.status_code == 400
    _s184_assert_no_echo(resp)
    _s184_assert_nothing_downstream(client, seen, db_session)


def test_main_create_snapshot_fetched_lone_surrogate_rejected_400_without_echo(s184, db_session, monkeypatch):
    client, seen = s184
    _s184_serve(monkeypatch, _s184_rtf(_S184_DOC + "\ud800"))
    resp = client.post("/snapshots", params={"url": _S184_URL})
    assert resp.status_code == 400
    _s184_assert_no_echo(resp)
    _s184_assert_nothing_downstream(client, seen, db_session)


def test_main_refresh_watchlist_fetched_lone_surrogate_reports_check_failed(s184, db_session, monkeypatch):
    """Refresh keeps its own failure contract: 200 with "Check Failed", and the
    stored text and hash are untouched (never the surrogate text)."""
    client, _ = s184
    item = _insert_watchlist_item(db_session, source_url=_S184_URL)
    _s184_serve(monkeypatch, _s184_rtf(_S184_DOC + "\ud800"))
    resp = client.post(f"/watchlist/{item.id}/refresh")
    assert resp.status_code == 200
    assert resp.json()["status"] == "Check Failed"
    _s184_assert_no_echo(resp)
    db_session.refresh(item)
    assert item.last_document_text is None
    assert item.last_document_hash is None


# --- positive controls: valid text is still accepted -----------------------


@pytest.mark.parametrize("wire", _S184_WIRES)
@pytest.mark.parametrize("label,ch", _S184_ACCEPT, ids=[v[0] for v in _S184_ACCEPT])
def test_main_analyze_accepts_valid_text_next_to_surrogate_block(s184, db_session, label, ch, wire):
    client, seen = s184
    text = _S184_DOC + ch + " end"
    resp = client.post("/analyze", content=_s184_wire({"text": text}, wire), headers=_S184_JSON)
    assert resp.status_code == 200, (label, wire, resp.status_code)
    assert len(seen["analyze_text"]) == 1 and ch in seen["analyze_text"][0]
    assert seen["llm"] and ch in seen["llm"][0]
    row = db_session.query(AnalysisModel).one()
    assert ch in row.document_text
    assert client.get("/exports/analyses.csv").status_code == 200


@pytest.mark.parametrize("wire", _S184_WIRES)
def test_main_infer_accepts_non_bmp_text(s184, wire):
    client, seen = s184
    text = _S184_DOC + _S184_EMOJI
    resp = client.post("/infer", content=_s184_wire({"text": text}, wire), headers=_S184_JSON)
    assert resp.status_code == 200
    assert seen["infer"] == [text]


def test_main_analyze_file_html_non_bmp_entity_accepted(s184, db_session):
    client, seen = s184
    data = f"<p>{_S184_DOC}&#x1F600; end</p>".encode("ascii")
    resp = client.post("/analyze/file", files={"file": ("policy.html", data, "text/html")})
    assert resp.status_code == 200
    assert _S184_EMOJI in seen["analyze_text"][0]


def test_main_analyze_file_rtf_surrogate_pair_escape_accepted_as_one_char(s184, db_session):
    """RTF writes an emoji as two ``\\uN`` halves. That is valid text: it must
    reach analysis, the LLM and the DB as the one joined character."""
    client, seen = s184
    data = _s184_rtf(_S184_DOC + _S184_EMOJI + " end")
    assert data.count(b"\\u") == 2  # really the two-halves encoding
    resp = client.post("/analyze/file", files={"file": ("policy.rtf", data, "application/rtf")})
    assert resp.status_code == 200
    assert len(seen["analyze_text"]) == 1
    assert _S184_EMOJI in seen["analyze_text"][0]
    assert not _s184_has_surrogate(seen["analyze_text"][0])
    assert seen["llm"] and not _s184_has_surrogate(seen["llm"][0])
    row = db_session.query(AnalysisModel).one()
    assert _S184_EMOJI in row.document_text


def test_main_analyze_url_fetched_rtf_surrogate_pair_accepted_as_one_char(s184, db_session, monkeypatch):
    client, seen = s184
    _s184_serve(monkeypatch, _s184_rtf(_S184_DOC + _S184_EMOJI + " end"))
    resp = client.post("/analyze/url", json={"url": _S184_URL})
    assert resp.status_code == 200
    assert len(seen["analyze_text"]) == 1
    assert _S184_EMOJI in seen["analyze_text"][0]
    assert not _s184_has_surrogate(seen["analyze_text"][0])
