"""OE-003 merge invariants.

The audit finding ``OE-003`` in ``docs/reports/tech-spec-audit.md`` called out
two overlapping "policy monitoring" abstractions (``WatchlistItem`` and
``PolicyWatch``). The user-decision brief on 2026-07-03 (A3) chose to
canonicalize on ``WatchlistItem`` and delete ``PolicyWatch``. These tests are
the load-bearing regression floor for that decision — if any of them fail,
the merge has regressed.

Key contract the tests defend:

* ``PolicyWatch`` and its schema shells are gone.
* ``WatchlistItem`` carries the 4 merged columns (``user_id``,
  ``check_frequency``, ``enabled``, ``created_at``) plus the ``notes``
  affordance from PRD §5.6.1.
* ``_watchlist_loop_async`` honors per-item ``check_frequency`` — this is the
  user-facing bug OE-003 exposed: previously the loop refreshed every item
  every wakeup on a single global cadence.
* ``enabled=False`` skips refresh in the background loop.
* ``POST /watchlist`` accepts the merged fields and rejects wrong types.
* ``/policy-watch/*`` returns the deprecation shims documented in main.py.

See ``docs/reports/user-decision-brief-2026-07-03.md`` A3 for the decision
narrative.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.models import WatchlistItem


# ---------------------------------------------------------------------------
# Import-level assertions
# ---------------------------------------------------------------------------


def test_policywatch_model_no_longer_importable():
    """The ``PolicyWatch`` ORM class must be gone (OE-003)."""
    with pytest.raises(ImportError):
        from app.models import PolicyWatch  # noqa: F401


def test_policywatch_schemas_no_longer_importable():
    """The ``PolicyWatchPayload`` / ``PolicyWatchCreateRequest`` schemas must be gone."""
    with pytest.raises(ImportError):
        from app.schemas import PolicyWatchPayload  # noqa: F401
    with pytest.raises(ImportError):
        from app.schemas import PolicyWatchCreateRequest  # noqa: F401


# ---------------------------------------------------------------------------
# ORM-level field presence
# ---------------------------------------------------------------------------


def test_watchlist_item_has_merged_columns():
    """All four merged columns must be present at the ORM level."""
    columns = {c.name for c in WatchlistItem.__table__.columns}
    for required in ("user_id", "check_frequency", "enabled", "created_at", "notes"):
        assert required in columns, f"WatchlistItem missing merged column: {required}"


def test_watchlist_item_enabled_is_boolean_type():
    """``enabled`` must be a Boolean column, not a String (LE-010 fix)."""
    from sqlalchemy import Boolean

    col = WatchlistItem.__table__.c.enabled
    assert isinstance(col.type, Boolean), (
        f"WatchlistItem.enabled type is {type(col.type).__name__}; expected Boolean"
    )


# ---------------------------------------------------------------------------
# Refresh-loop cadence honoring
# ---------------------------------------------------------------------------


def _make_item(
    db_session,
    *,
    check_frequency: int = 3600,
    enabled: bool = True,
    last_checked: datetime | None = None,
    source_url: str = "https://example.com/policy",
    vendor: str = "example.com",
) -> WatchlistItem:
    item = WatchlistItem(
        id=str(uuid4()),
        vendor=vendor,
        source_url=source_url,
        status="No Changes",
        change_count=0,
        risk_delta=0.0,
        check_frequency=check_frequency,
        enabled=enabled,
        last_checked=last_checked or datetime.now(timezone.utc),
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


def test_refresh_loop_skips_items_not_yet_due(db_session, monkeypatch):
    """An item whose ``last_checked + check_frequency`` is in the future is skipped."""
    from app import main as main_module

    fetched: list[str] = []

    async def fake_fetch(url):
        fetched.append(url)
        return "Some policy text."

    monkeypatch.setattr("app.main.fetch_url_text", fake_fetch)

    # last_checked = now → next due in 1 hour → should NOT be refreshed this tick.
    _make_item(
        db_session,
        check_frequency=3600,
        last_checked=datetime.now(timezone.utc),
        source_url="https://example.com/not-due",
    )

    with patch("app.main.db_session") as ctx:
        ctx.return_value.__enter__ = lambda s: db_session
        ctx.return_value.__exit__ = lambda *args: False
        asyncio.run(main_module._refresh_due_watchlist_items())

    assert fetched == [], "Refresh loop fetched an item that was not yet due"


def test_refresh_loop_refreshes_past_due_items(db_session, monkeypatch):
    """An item whose ``last_checked + check_frequency`` is in the past IS refreshed."""
    from app import main as main_module

    fetched: list[str] = []

    async def fake_fetch(url):
        fetched.append(url)
        return "Some policy text for the due item."

    monkeypatch.setattr("app.main.fetch_url_text", fake_fetch)

    # last_checked = 2 hours ago; cadence = 1 hour → 1 hour past due.
    two_hours_ago = datetime.now(timezone.utc) - timedelta(hours=2)
    _make_item(
        db_session,
        check_frequency=3600,
        last_checked=two_hours_ago,
        source_url="https://example.com/past-due",
    )

    with patch("app.main.db_session") as ctx:
        ctx.return_value.__enter__ = lambda s: db_session
        ctx.return_value.__exit__ = lambda *args: False
        asyncio.run(main_module._refresh_due_watchlist_items())

    assert fetched == ["https://example.com/past-due"], (
        f"Refresh loop did not fetch past-due item; fetched={fetched}"
    )


def test_refresh_loop_skips_disabled_items(db_session, monkeypatch):
    """``enabled=False`` must skip the refresh even when past due."""
    from app import main as main_module

    fetched: list[str] = []

    async def fake_fetch(url):
        fetched.append(url)
        return "Should never be fetched."

    monkeypatch.setattr("app.main.fetch_url_text", fake_fetch)

    two_hours_ago = datetime.now(timezone.utc) - timedelta(hours=2)
    _make_item(
        db_session,
        check_frequency=3600,
        last_checked=two_hours_ago,
        enabled=False,
        source_url="https://example.com/disabled",
    )

    with patch("app.main.db_session") as ctx:
        ctx.return_value.__enter__ = lambda s: db_session
        ctx.return_value.__exit__ = lambda *args: False
        asyncio.run(main_module._refresh_due_watchlist_items())

    assert fetched == [], "Disabled watchlist item was refreshed"


def test_refresh_loop_mixed_due_and_not_due(db_session, monkeypatch):
    """With two items — one past due, one not — only the past-due item is fetched."""
    from app import main as main_module

    fetched: list[str] = []

    async def fake_fetch(url):
        fetched.append(url)
        return "Content."

    monkeypatch.setattr("app.main.fetch_url_text", fake_fetch)

    now = datetime.now(timezone.utc)
    _make_item(
        db_session,
        check_frequency=3600,
        last_checked=now - timedelta(hours=2),
        source_url="https://example.com/due",
    )
    _make_item(
        db_session,
        check_frequency=3600,
        last_checked=now,
        source_url="https://example.com/notdue",
    )

    with patch("app.main.db_session") as ctx:
        ctx.return_value.__enter__ = lambda s: db_session
        ctx.return_value.__exit__ = lambda *args: False
        asyncio.run(main_module._refresh_due_watchlist_items())

    assert fetched == ["https://example.com/due"]


# ---------------------------------------------------------------------------
# Deprecation shim contract
# ---------------------------------------------------------------------------


def test_policy_watch_endpoints_return_deprecation_headers(app_client):
    """Every ``/policy-watch/*`` route must set Deprecation: true + Sunset: 2026-10-01."""
    routes = [
        ("POST", "/policy-watch", {"json": {"vendor": "x", "source_url": "https://x.com"}}),
        ("GET", "/policy-watch", {}),
        ("DELETE", "/policy-watch/some-id", {}),
    ]
    for method, path, kwargs in routes:
        response = app_client.request(method, path, follow_redirects=False, **kwargs)
        assert response.status_code == 308
        assert response.headers.get("Deprecation") == "true"
        assert response.headers.get("Sunset") == "2026-10-01"


def test_policy_watch_snapshot_returns_410_gone(app_client):
    """``/policy-watch/{id}/snapshot`` cannot be redirected — must return 410 Gone."""
    response = app_client.post("/policy-watch/any-id/snapshot")
    assert response.status_code == 410
    body = response.json()
    assert body["successor"] == "/watchlist/{id}/refresh"
    assert response.headers.get("Deprecation") == "true"
