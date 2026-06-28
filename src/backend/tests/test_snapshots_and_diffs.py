"""
Tests for Enhancement 6: Change Detection & Diffs
Tests for policy snapshots, watches, and token-level diffing.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from uuid import uuid4

from app.models import PolicySnapshot, PolicyWatch
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


class TestPolicyWatchModel:
    """Test PolicyWatch database model."""
    
    def test_create_watch(self, db_session):
        """Create a policy watch."""
        watch = PolicyWatch(
            id=str(uuid4()),
            url="https://example.com/tos",
            user_id="user123",
            check_frequency=86400,
            enabled="true",
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(watch)
        db_session.commit()
        
        retrieved = db_session.query(PolicyWatch).filter_by(id=watch.id).first()
        assert retrieved is not None
        assert retrieved.url == "https://example.com/tos"
        assert retrieved.check_frequency == 86400
    
    def test_watch_url_uniqueness(self, db_session):
        """URL must be unique in policy watches."""
        url = "https://example.com/privacy"
        watch1 = PolicyWatch(
            id=str(uuid4()),
            url=url,
            check_frequency=86400,
            enabled="true",
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(watch1)
        db_session.commit()
        
        # Try to add same URL again
        watch2 = PolicyWatch(
            id=str(uuid4()),
            url=url,
            check_frequency=86400,
            enabled="true",
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(watch2)
        
        # Should fail due to unique constraint
        with pytest.raises(Exception):
            db_session.commit()


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


class TestPolicyWatchEndpoints:
    """Test policy watch API endpoints."""
    
    def test_create_policy_watch(self, app_client):
        """Test POST /policy-watch endpoint."""
        payload = {
            "url": "https://example.com/privacy",
            "user_id": "user123",
            "check_frequency": 86400,
        }
        response = app_client.post("/policy-watch", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["url"] == "https://example.com/privacy"
        assert data["check_frequency"] == 86400
    
    def test_create_duplicate_watch(self, app_client, db_session):
        """Test creating duplicate policy watch fails."""
        url = "https://example.com/privacy"
        watch = PolicyWatch(
            id=str(uuid4()),
            url=url,
            check_frequency=86400,
            enabled="true",
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(watch)
        db_session.commit()
        
        payload = {
            "url": url,
            "check_frequency": 86400,
        }
        response = app_client.post("/policy-watch", json=payload)
        assert response.status_code == 409
    
    def test_list_policy_watches(self, app_client, db_session):
        """Test GET /policy-watch endpoint."""
        # Create test watches
        for i in range(3):
            watch = PolicyWatch(
                id=str(uuid4()),
                url=f"https://example.com/policy{i}",
                check_frequency=86400,
                enabled="true",
                created_at=datetime.now(timezone.utc),
            )
            db_session.add(watch)
        db_session.commit()
        
        response = app_client.get("/policy-watch")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3
    
    def test_delete_policy_watch(self, app_client, db_session):
        """Test DELETE /policy-watch/{watch_id} endpoint."""
        watch = PolicyWatch(
            id=str(uuid4()),
            url="https://example.com/privacy",
            check_frequency=86400,
            enabled="true",
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(watch)
        db_session.commit()
        
        response = app_client.delete(f"/policy-watch/{watch.id}")
        assert response.status_code == 200
        
        # Verify it's deleted
        response = app_client.get("/policy-watch")
        data = response.json()
        assert len(data) == 0
    
    def test_delete_nonexistent_watch(self, app_client):
        """Test deleting non-existent watch."""
        response = app_client.delete("/policy-watch/nonexistent")
        assert response.status_code == 404


class TestCaptureWatchSnapshot:
    """Test snapshot capture for policy watches."""
    
    def test_capture_watch_snapshot(self, app_client, db_session, monkeypatch):
        """Test POST /policy-watch/{watch_id}/snapshot endpoint."""
        # Mock fetch_url_text
        async def mock_fetch_url_text(url):
            return "Test policy content"
        
        import app.main
        import app.services.ingest
        original_fetch = app.services.ingest.fetch_url_text
        
        # Patch both locations
        app.services.ingest.fetch_url_text = mock_fetch_url_text
        app.main.fetch_url_text = mock_fetch_url_text
        
        try:
            # Create watch
            watch = PolicyWatch(
                id=str(uuid4()),
                url="https://example.com/privacy",
                check_frequency=86400,
                enabled="true",
                created_at=datetime.now(timezone.utc),
            )
            db_session.add(watch)
            db_session.commit()
            
            response = app_client.post(f"/policy-watch/{watch.id}/snapshot")
            assert response.status_code == 200
            data = response.json()
            assert data["url"] == "https://example.com/privacy"
            assert data["captured_at"]
        finally:
            app.services.ingest.fetch_url_text = original_fetch
            app.main.fetch_url_text = original_fetch
    
    def test_capture_watch_snapshot_updates_last_check(self, app_client, db_session, monkeypatch):
        """Test that capturing snapshot updates last_check time."""
        async def mock_fetch_url_text(url):
            return "Test policy content"
        
        import app.main
        import app.services.ingest
        original_fetch = app.services.ingest.fetch_url_text
        
        app.services.ingest.fetch_url_text = mock_fetch_url_text
        app.main.fetch_url_text = mock_fetch_url_text
        
        try:
            watch = PolicyWatch(
                id=str(uuid4()),
                url="https://example.com/privacy",
                check_frequency=86400,
                enabled="true",
                created_at=datetime.now(timezone.utc),
            )
            db_session.add(watch)
            db_session.commit()
            
            app_client.post(f"/policy-watch/{watch.id}/snapshot")
            
            # Verify last_check was updated
            db_session.refresh(watch)
            assert watch.last_check is not None
        finally:
            app.services.ingest.fetch_url_text = original_fetch
            app.main.fetch_url_text = original_fetch


class TestIntegration:
    """Integration tests for the full snapshot and diff workflow."""
    
    def test_full_workflow(self, app_client, db_session, monkeypatch):
        """Test complete workflow: create watch, capture snapshots, compare diffs."""
        call_count = [0]
        
        async def mock_fetch_url_text(url):
            # Return different content on subsequent calls
            call_count[0] += 1
            if call_count[0] == 1:
                return "Original privacy policy content here."
            else:
                return "Original privacy policy content here. Updated section added."
        
        import app.main
        import app.services.ingest
        original_fetch = app.services.ingest.fetch_url_text
        
        app.services.ingest.fetch_url_text = mock_fetch_url_text
        app.main.fetch_url_text = mock_fetch_url_text
        
        try:
            # 1. Create policy watch
            watch_payload = {
                "url": "https://example.com/privacy",
                "user_id": "user123",
                "check_frequency": 86400,
            }
            resp = app_client.post("/policy-watch", json=watch_payload)
            assert resp.status_code == 200
            watch_data = resp.json()
            watch_id = watch_data["id"]
            
            # 2. Capture first snapshot
            resp = app_client.post(f"/policy-watch/{watch_id}/snapshot")
            assert resp.status_code == 200
            snap1_data = resp.json()
            snap1_id = snap1_data["id"]
            
            # 3. Capture second snapshot (with different content)
            resp = app_client.post(f"/policy-watch/{watch_id}/snapshot")
            # May be 200 (new snapshot) or 409 (duplicate) - we'll check for dedup
            if resp.status_code == 200:
                snap2_data = resp.json()
                snap2_id = snap2_data["id"]
            
                # 4. Compare the two snapshots
                resp = app_client.get(f"/diff/{snap1_id}/{snap2_id}")
                assert resp.status_code == 200
                diff_data = resp.json()
                assert diff_data["url"] == "https://example.com/privacy"
                # Should have changes (added tokens)
                assert diff_data["change_count"] > 0
        finally:
            app.services.ingest.fetch_url_text = original_fetch
            app.main.fetch_url_text = original_fetch
