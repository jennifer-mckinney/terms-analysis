"""
Tests for Enhancement 6: Change Detection & Diffs
Tests for policy snapshots, watches, and token-level diffing.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from uuid import uuid4

from app.models import PolicySnapshot, WatchlistItem
from app.services.diffing import content_hash, diff_tokens, tokenize_text


class TestContentHash:
    """Test SHA-256 content hashing."""
    
    def test_content_hash_consistency(self):
        """Same content produces same hash."""
        text = "This is a policy document."
        hash1 = content_hash(text)
        hash2 = content_hash(text)
        assert hash1 == hash2
    
    def test_content_hash_different(self):
        """Different content produces different hashes."""
        text1 = "Original policy content."
        text2 = "Modified policy content."
        hash1 = content_hash(text1)
        hash2 = content_hash(text2)
        assert hash1 != hash2
    
    def test_content_hash_empty(self):
        """Empty string produces valid hash."""
        empty_hash = content_hash("")
        assert len(empty_hash) == 64  # SHA-256 hex is 64 chars


class TestTokenization:
    """Test text tokenization."""
    
    def test_tokenize_simple(self):
        """Tokenize simple text."""
        text = "We collect data."
        tokens = tokenize_text(text)
        token_strings = [t[0] for t in tokens]
        assert "We" in token_strings
        assert "collect" in token_strings
        assert "data" in token_strings
    
    def test_tokenize_multiline(self):
        """Tokenize multiline text with line numbers."""
        text = "Line one content.\nLine two content."
        tokens = tokenize_text(text)
        # Should have tokens from both lines
        line_numbers = set(t[1] for t in tokens)
        assert 1 in line_numbers
        assert 2 in line_numbers
    
    def test_tokenize_empty(self):
        """Tokenize empty text."""
        tokens = tokenize_text("")
        assert len(tokens) == 0
    
    def test_tokenize_punctuation(self):
        """Tokenize text with punctuation."""
        text = "We may share data, including information."
        tokens = tokenize_text(text)
        token_strings = [t[0] for t in tokens]
        assert "," in token_strings
        assert "." in token_strings


class TestDiffTokens:
    """Test token-level diffing."""
    
    def test_diff_identical(self):
        """Identical texts produce no changes."""
        text = "Privacy policy text."
        result = diff_tokens(text, text)
        assert result["change_count"] == 0
        assert len(result["added"]) == 0
        assert len(result["removed"]) == 0
    
    def test_diff_added_tokens(self):
        """Detect added tokens."""
        old = "We collect data."
        new = "We collect personal data."
        result = diff_tokens(old, new)
        assert result["change_count"] > 0
        assert len(result["added"]) > 0
    
    def test_diff_removed_tokens(self):
        """Detect removed tokens."""
        old = "We collect personal data."
        new = "We collect data."
        result = diff_tokens(old, new)
        assert result["change_count"] > 0
        assert len(result["removed"]) > 0
    
    def test_diff_replaced_tokens(self):
        """Detect replaced tokens."""
        old = "We retain data for 1 year."
        new = "We retain data for 2 years."
        result = diff_tokens(old, new)
        assert result["change_count"] > 0
        # Should have both removed and added
        assert len(result["removed"]) > 0
        assert len(result["added"]) > 0
    
    def test_diff_severity_classification(self):
        """Test severity classification of changes."""
        old = "We use data."
        new = "We use sensitive data."
        result = diff_tokens(old, new)
        # "sensitive" is a high-severity keyword
        severity_summary = result["severity_summary"]
        assert severity_summary["high"] > 0 or severity_summary["medium"] > 0
    
    def test_diff_large_text(self):
        """Test diffing large policy texts."""
        old = "Privacy Policy\n" + ("We collect data.\n" * 100)
        new = "Privacy Policy\n" + ("We collect personal data.\n" * 100)
        result = diff_tokens(old, new)
        assert result["change_count"] > 0
        assert len(result["added"]) > 0


class TestPolicySnapshotModel:
    """Test PolicySnapshot database model."""
    
    def test_create_snapshot(self, db_session):
        """Create a policy snapshot."""
        snapshot = PolicySnapshot(
            id=str(uuid4()),
            url="https://example.com/privacy",
            content_hash=content_hash("Test content"),
            captured_at=datetime.now(timezone.utc),
            raw_text="Test content",
        )
        db_session.add(snapshot)
        db_session.commit()
        
        retrieved = db_session.query(PolicySnapshot).filter_by(id=snapshot.id).first()
        assert retrieved is not None
        assert retrieved.url == "https://example.com/privacy"
    
    def test_snapshot_deduplication(self, db_session):
        """Snapshots with same URL and hash are deduplicated."""
        url = "https://example.com/privacy"
        content = "Test content"
        hash_val = content_hash(content)
        
        # Create first snapshot
        snap1 = PolicySnapshot(
            id=str(uuid4()),
            url=url,
            content_hash=hash_val,
            captured_at=datetime.now(timezone.utc),
            raw_text=content,
        )
        db_session.add(snap1)
        db_session.commit()
        
        # Query should find it
        existing = db_session.query(PolicySnapshot).filter_by(
            url=url,
            content_hash=hash_val
        ).first()
        assert existing is not None
        assert existing.id == snap1.id


class TestWatchlistItemMergedFields:
    """OE-003 (2026-07-03): ``PolicyWatch`` was merged into ``WatchlistItem``.

    These tests replace the deleted ``TestPolicyWatchModel`` class. They assert
    the fields formerly on ``PolicyWatch`` now live on ``WatchlistItem`` with
    the right types (in particular ``enabled`` is a real ``Boolean``, not the
    old string ``"true"`` — LE-010 fix).
    """

    def test_watchlist_item_has_merged_fields(self, db_session):
        item = WatchlistItem(
            id=str(uuid4()),
            vendor="example.com",
            source_url="https://example.com/tos",
            user_id="user123",
            check_frequency=86400,
            enabled=True,
            notes="added from CLI test",
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(item)
        db_session.commit()

        retrieved = db_session.query(WatchlistItem).filter_by(id=item.id).first()
        assert retrieved is not None
        assert retrieved.source_url == "https://example.com/tos"
        assert retrieved.check_frequency == 86400
        # ``enabled`` is stored and read back as a real bool, not a string.
        assert retrieved.enabled is True
        assert isinstance(retrieved.enabled, bool)
        assert retrieved.user_id == "user123"
        assert retrieved.notes == "added from CLI test"

    def test_watchlist_item_enabled_false_is_boolean(self, db_session):
        item = WatchlistItem(
            id=str(uuid4()),
            vendor="example.com",
            source_url="https://example.com/paused",
            enabled=False,
        )
        db_session.add(item)
        db_session.commit()
        retrieved = db_session.query(WatchlistItem).filter_by(id=item.id).first()
        assert retrieved.enabled is False


class TestSnapshotEndpoints:
    """Test snapshot API endpoints."""
    
    def test_create_snapshot_endpoint(self, app_client, db_session, monkeypatch):
        """Test POST /snapshots endpoint."""
        # Mock fetch_url_text to avoid actual HTTP calls
        import asyncio
        
        async def mock_fetch_url_text(url):
            return "Test policy content"
        
        def sync_mock_fetch(*args, **kwargs):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(mock_fetch_url_text(*args, **kwargs))
            finally:
                loop.close()
        
        import app.main
        import app.services.ingest
        original_fetch = app.services.ingest.fetch_url_text
        
        # Patch both locations
        app.services.ingest.fetch_url_text = mock_fetch_url_text
        monkeypatch.setattr(app.main, "fetch_url_text", mock_fetch_url_text)
        
        try:
            response = app_client.post("/snapshots?url=https://example.com/policy")
            assert response.status_code == 200
            data = response.json()
            assert data["url"] == "https://example.com/policy"
            assert data["content_hash"]
            assert data["captured_at"]
        finally:
            app.services.ingest.fetch_url_text = original_fetch
    
    def test_get_snapshots_endpoint(self, app_client, db_session):
        """Test GET /snapshots endpoint with url query parameter."""
        # Create test snapshots
        url = "https://example.com/policy"
        for i in range(3):
            snapshot = PolicySnapshot(
                id=str(uuid4()),
                url=url,
                content_hash=content_hash(f"Content {i}"),
                captured_at=datetime.now(timezone.utc),
                raw_text=f"Content {i}",
            )
            db_session.add(snapshot)
        db_session.commit()
        
        # Use query parameter for URL
        response = app_client.get("/snapshots", params={"url": url})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3
        assert all(item["url"] == url for item in data)
    
    def test_get_snapshot_detail(self, app_client, db_session):
        """Test GET /snapshots/detail/{snapshot_id} endpoint."""
        snapshot = PolicySnapshot(
            id=str(uuid4()),
            url="https://example.com/policy",
            content_hash=content_hash("Test content"),
            captured_at=datetime.now(timezone.utc),
            raw_text="Test content",
        )
        db_session.add(snapshot)
        db_session.commit()
        
        response = app_client.get(f"/snapshots/detail/{snapshot.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == snapshot.id
        assert data["raw_text"] == "Test content"
    
    def test_get_snapshots_not_found(self, app_client):
        """Test getting snapshots for non-existent URL."""
        fake_url = "https://nonexistent.com/policy"
        response = app_client.get("/snapshots", params={"url": fake_url})
        assert response.status_code == 404


class TestDiffEndpoint:
    """Test diff API endpoint."""
    
    def test_diff_two_snapshots(self, app_client, db_session):
        """Test GET /diff/{snapshot_id_1}/{snapshot_id_2} endpoint."""
        url = "https://example.com/policy"
        
        # Create two snapshots with different content
        snap1 = PolicySnapshot(
            id=str(uuid4()),
            url=url,
            content_hash=content_hash("Original content"),
            captured_at=datetime.now(timezone.utc),
            raw_text="Original content",
        )
        snap2 = PolicySnapshot(
            id=str(uuid4()),
            url=url,
            content_hash=content_hash("Modified content"),
            captured_at=datetime.now(timezone.utc),
            raw_text="Modified content",
        )
        db_session.add(snap1)
        db_session.add(snap2)
        db_session.commit()
        
        response = app_client.get(f"/diff/{snap1.id}/{snap2.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["snapshot_1_id"] == snap1.id
        assert data["snapshot_2_id"] == snap2.id
        assert data["change_count"] > 0
    
    def test_diff_different_urls(self, app_client, db_session):
        """Test diffing snapshots from different URLs fails."""
        snap1 = PolicySnapshot(
            id=str(uuid4()),
            url="https://example.com/policy1",
            content_hash=content_hash("Content 1"),
            captured_at=datetime.now(timezone.utc),
            raw_text="Content 1",
        )
        snap2 = PolicySnapshot(
            id=str(uuid4()),
            url="https://example.com/policy2",
            content_hash=content_hash("Content 2"),
            captured_at=datetime.now(timezone.utc),
            raw_text="Content 2",
        )
        db_session.add(snap1)
        db_session.add(snap2)
        db_session.commit()
        
        response = app_client.get(f"/diff/{snap1.id}/{snap2.id}")
        assert response.status_code == 400
    
    def test_diff_not_found(self, app_client):
        """Test diffing with non-existent snapshots."""
        response = app_client.get(f"/diff/nonexistent1/nonexistent2")
        assert response.status_code == 404


class TestPolicyWatchDeprecatedEndpoints:
    """OE-003: ``/policy-watch/*`` endpoints are deprecated shims.

    Replaces the deleted ``TestPolicyWatchEndpoints`` class. The migration
    landed in main.py as 308 redirects for CRUD paths and a 410 Gone for the
    snapshot subpath — see the design note above the shim handlers in main.py.
    """

    def test_policy_watch_post_returns_308_redirect(self, app_client):
        # 308 preserves method + body; do not follow redirects so we can
        # observe the raw status.
        response = app_client.post(
            "/policy-watch",
            json={"url": "https://example.com/privacy", "check_frequency": 3600},
            follow_redirects=False,
        )
        assert response.status_code == 308
        assert response.headers.get("Location") == "/watchlist"
        assert response.headers.get("Deprecation") == "true"
        assert response.headers.get("Sunset") == "2026-10-01"

    def test_policy_watch_get_returns_308_redirect(self, app_client):
        response = app_client.get("/policy-watch", follow_redirects=False)
        assert response.status_code == 308
        assert response.headers.get("Location") == "/watchlist"

    def test_policy_watch_delete_returns_308_redirect(self, app_client):
        response = app_client.delete(
            "/policy-watch/some-id", follow_redirects=False
        )
        assert response.status_code == 308
        assert response.headers.get("Location") == "/watchlist/some-id"
        assert response.headers.get("Deprecation") == "true"

    def test_policy_watch_snapshot_returns_410_gone(self, app_client):
        response = app_client.post("/policy-watch/some-id/snapshot")
        assert response.status_code == 410
        body = response.json()
        assert "successor" in body
        assert body["successor"] == "/watchlist/{id}/refresh"
        assert response.headers.get("Deprecation") == "true"


class TestIntegration:
    """Integration tests for the full snapshot and diff workflow.

    Rewritten for OE-003: the workflow now runs against the merged
    ``/watchlist`` endpoint set (``POST /watchlist`` + ``POST /snapshots`` +
    ``GET /diff``) instead of the deprecated ``/policy-watch/*`` endpoints.
    """

    def test_full_workflow(self, app_client, db_session, monkeypatch):
        """Create watchlist item, capture two snapshots, compare diffs."""
        call_count = [0]

        async def mock_fetch_url_text(url):
            call_count[0] += 1
            if call_count[0] == 1:
                return "Original privacy policy content here."
            return "Original privacy policy content here. Updated section added."

        import app.main
        import app.services.ingest
        original_fetch = app.services.ingest.fetch_url_text

        app.services.ingest.fetch_url_text = mock_fetch_url_text
        app.main.fetch_url_text = mock_fetch_url_text

        try:
            # 1. Create watchlist item with the OE-003 merged optional fields.
            watch_payload = {
                "vendor": "example.com",
                "source_url": "https://example.com/privacy",
                "user_id": "user123",
                "check_frequency": 86400,
            }
            resp = app_client.post("/watchlist", json=watch_payload)
            assert resp.status_code == 200
            body = resp.json()
            assert body["check_frequency"] == 86400
            assert body["user_id"] == "user123"

            # 2. Capture first snapshot via the general /snapshots endpoint.
            resp = app_client.post(
                "/snapshots", params={"url": "https://example.com/privacy"}
            )
            assert resp.status_code == 200
            snap1_id = resp.json()["id"]

            # 3. Second snapshot with different content.
            resp = app_client.post(
                "/snapshots", params={"url": "https://example.com/privacy"}
            )
            if resp.status_code == 200:
                snap2_id = resp.json()["id"]
                # 4. Compare.
                resp = app_client.get(f"/diff/{snap1_id}/{snap2_id}")
                assert resp.status_code == 200
                diff_data = resp.json()
                assert diff_data["url"] == "https://example.com/privacy"
                assert diff_data["change_count"] > 0
        finally:
            app.services.ingest.fetch_url_text = original_fetch
            app.main.fetch_url_text = original_fetch
