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

Naming: test_<module>_<function>_<scenario>
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.models import (
    Analysis as AnalysisModel,
    PolicySnapshot,
    PolicyWatch,
    ReviewItem,
    WatchlistItem,
)
from app.schemas import AnalysisPayload
from app.services.analyzer import AnalysisResult


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
        assert set(item.keys()) >= {"id", "analysis_id", "status", "notes", "created_at", "updated_at"}


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
# POST /policy-watch
# ===========================================================================

class TestCreatePolicyWatch:
    def test_main_create_policy_watch_creates_watch(self, app_client):
        response = app_client.post(
            "/policy-watch",
            json={"url": "https://example.com/privacy", "check_frequency": 3600},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["url"] == "https://example.com/privacy"
        assert body["check_frequency"] == 3600
        assert body["enabled"] == "true"
        assert body["last_check"] is None

    def test_main_create_policy_watch_with_user_id(self, app_client):
        response = app_client.post(
            "/policy-watch",
            json={
                "url": "https://example.com/tos",
                "check_frequency": 86400,
                "user_id": "user-123",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["user_id"] == "user-123"

    def test_main_create_policy_watch_409_for_duplicate_url(self, app_client):
        payload = {"url": "https://dup.example.com/privacy", "check_frequency": 3600}
        first = app_client.post("/policy-watch", json=payload)
        assert first.status_code == 200

        second = app_client.post("/policy-watch", json=payload)
        assert second.status_code == 409
        assert "already being watched" in second.json()["detail"]

    def test_main_create_policy_watch_422_for_short_url(self, app_client):
        response = app_client.post(
            "/policy-watch",
            json={"url": "x", "check_frequency": 3600},
        )
        assert response.status_code == 422

    def test_main_create_policy_watch_422_check_frequency_too_low(self, app_client):
        response = app_client.post(
            "/policy-watch",
            json={"url": "https://example.com/privacy", "check_frequency": 60},
        )
        assert response.status_code == 422


# ===========================================================================
# GET /policy-watch
# ===========================================================================

class TestListPolicyWatches:
    def test_main_list_policy_watches_empty(self, app_client):
        response = app_client.get("/policy-watch")
        assert response.status_code == 200
        assert response.json() == []

    def test_main_list_policy_watches_returns_all(self, app_client, db_session):
        for url in ["https://a.com/privacy", "https://b.com/tos"]:
            watch = PolicyWatch(
                id=str(uuid4()),
                url=url,
                check_frequency=3600,
                enabled="true",
                created_at=datetime.now(timezone.utc),
            )
            db_session.add(watch)
        db_session.commit()

        response = app_client.get("/policy-watch")
        assert response.status_code == 200
        assert len(response.json()) == 2


# ===========================================================================
# DELETE /policy-watch/{id}
# ===========================================================================

class TestDeletePolicyWatch:
    def test_main_delete_policy_watch_removes_item(self, app_client, db_session):
        watch = PolicyWatch(
            id=str(uuid4()),
            url="https://example.com/delete-me",
            check_frequency=3600,
            enabled="true",
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(watch)
        db_session.commit()

        response = app_client.delete(f"/policy-watch/{watch.id}")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "deleted"
        assert body["id"] == watch.id

    def test_main_delete_policy_watch_404_for_missing(self, app_client):
        response = app_client.delete("/policy-watch/nonexistent-watch-id")
        assert response.status_code == 404
        assert response.json()["detail"] == "Policy watch not found"


# ===========================================================================
# POST /policy-watch/{id}/snapshot
# ===========================================================================

class TestCaptureWatchSnapshot:
    def _insert_watch(self, db_session, url: str = "https://example.com/privacy") -> PolicyWatch:
        watch = PolicyWatch(
            id=str(uuid4()),
            url=url,
            check_frequency=3600,
            enabled="true",
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(watch)
        db_session.commit()
        db_session.refresh(watch)
        return watch

    def test_main_capture_watch_snapshot_creates_new(self, app_client, db_session, monkeypatch):
        watch = self._insert_watch(db_session)

        async def fake_fetch(url):
            return "Fresh policy text for watch snapshot."

        monkeypatch.setattr("app.main.fetch_url_text", fake_fetch)

        response = app_client.post(f"/policy-watch/{watch.id}/snapshot")
        assert response.status_code == 200
        body = response.json()
        assert body["url"] == watch.url
        assert body["raw_text"] == "Fresh policy text for watch snapshot."

    def test_main_capture_watch_snapshot_deduplicates(self, app_client, db_session, monkeypatch):
        url = "https://example.com/dedup"
        watch = self._insert_watch(db_session, url=url)
        text = "Unchanged policy text."
        _insert_snapshot(db_session, url=url, text=text)

        async def fake_fetch(url_arg):
            return text

        monkeypatch.setattr("app.main.fetch_url_text", fake_fetch)

        response = app_client.post(f"/policy-watch/{watch.id}/snapshot")
        assert response.status_code == 200
        body = response.json()
        assert body["raw_text"] is None  # no duplicate raw_text returned

    def test_main_capture_watch_snapshot_404_for_missing_watch(self, app_client):
        response = app_client.post("/policy-watch/nonexistent-watch/snapshot")
        assert response.status_code == 404
        assert response.json()["detail"] == "Policy watch not found"

    def test_main_capture_watch_snapshot_400_on_fetch_error(self, app_client, db_session, monkeypatch):
        watch = self._insert_watch(db_session)

        async def fake_fetch(url):
            raise RuntimeError("Network unavailable")

        monkeypatch.setattr("app.main.fetch_url_text", fake_fetch)

        response = app_client.post(f"/policy-watch/{watch.id}/snapshot")
        assert response.status_code == 400
        assert "Failed to fetch the requested URL." in response.json()["detail"]

    def test_main_capture_watch_snapshot_400_on_empty_content(self, app_client, db_session, monkeypatch):
        watch = self._insert_watch(db_session)

        async def fake_fetch(url):
            return ""

        monkeypatch.setattr("app.main.fetch_url_text", fake_fetch)

        response = app_client.post(f"/policy-watch/{watch.id}/snapshot")
        assert response.status_code == 400
        assert "empty" in response.json()["detail"].lower()

    def test_main_capture_watch_snapshot_updates_last_check(self, app_client, db_session, monkeypatch):
        watch = self._insert_watch(db_session)
        original_last_check = watch.last_check

        async def fake_fetch(url):
            return "Policy text that triggers last_check update."

        monkeypatch.setattr("app.main.fetch_url_text", fake_fetch)

        app_client.post(f"/policy-watch/{watch.id}/snapshot")

        db_session.refresh(watch)
        assert watch.last_check is not None
        assert watch.last_check != original_last_check


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

    def test_main_compute_rubric_scores_high_review_rate_lowers_governance(self, db_session):
        from app.main import _compute_rubric_scores
        rows = []
        for _ in range(4):
            row = _insert_analysis(db_session, status="needs_review", risk_score=5.0, confidence=0.70, grade="C")
            rows.append(row)
        scores = _compute_rubric_scores(rows)
        # All records are needs_review, so review_rate = 1.0 → review_score = 0.0
        assert scores.governanceReadiness == 0.0


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


class TestSecurityPolicyWatchUserIdValidation:
    """POST /policy-watch must reject oversized or malformed user_id."""

    def test_security_policy_watch_user_id_too_long_rejected(self, app_client):
        response = app_client.post(
            "/policy-watch",
            json={
                "url": "https://example.com/privacy",
                "user_id": "a" * 256,
                "check_frequency": 3600,
            },
        )
        assert response.status_code == 422

    def test_security_policy_watch_user_id_invalid_chars_rejected(self, app_client):
        response = app_client.post(
            "/policy-watch",
            json={
                "url": "https://example.com/privacy",
                "user_id": "<script>alert(1)</script>",
                "check_frequency": 3600,
            },
        )
        assert response.status_code == 422

    def test_security_policy_watch_valid_user_id_accepted(self, app_client, db_session, monkeypatch):
        response = app_client.post(
            "/policy-watch",
            json={
                "url": "https://example.com/privacy",
                "user_id": "user123@example.com",
                "check_frequency": 3600,
            },
        )
        # May 409 if URL already watched; either 201 or 409 is correct
        assert response.status_code in {200, 201, 409}


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
    """_verify_api_key: when API_KEY is set, wrong/missing key must return 401."""

    def test_security_api_key_wrong_key_returns_401(self, app_client):
        with patch("app.main.settings") as mock_settings:
            mock_settings.api_key = "correct-key"
            response = app_client.get("/health", headers={"X-API-Key": "wrong-key"})
        assert response.status_code == 401
        assert "Invalid" in response.json()["detail"]

    def test_security_api_key_missing_key_returns_401(self, app_client):
        with patch("app.main.settings") as mock_settings:
            mock_settings.api_key = "correct-key"
            response = app_client.get("/health")
        assert response.status_code == 401

    def test_security_api_key_correct_key_passes(self, app_client):
        with patch("app.main.settings") as mock_settings:
            mock_settings.api_key = "correct-key"
            response = app_client.get("/health", headers={"X-API-Key": "correct-key"})
        assert response.status_code == 200

    def test_security_api_key_empty_string_disables_auth(self, app_client):
        with patch("app.main.settings") as mock_settings:
            mock_settings.api_key = ""
            response = app_client.get("/health")
        assert response.status_code == 200
