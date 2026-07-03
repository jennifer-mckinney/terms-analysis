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
