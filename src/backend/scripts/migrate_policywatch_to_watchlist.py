"""OE-003 data migration: fold ``policy_watches`` rows into ``watchlist_items``.

Background
----------
On 2026-07-03 the ``PolicyWatch`` model was merged into ``WatchlistItem`` (see
``docs/reports/user-decision-brief-2026-07-03.md`` A3). The old
``policy_watches`` table remains in existing SQLite databases until this
script has been run. Two rows can point at the same URL:

* one from the shipped ``/policy-watch`` endpoint (schedule / cadence side)
* one from the shipped ``/watchlist`` endpoint (diff / risk side)

They were previously independent; this migration reconciles them.

Contract
--------
For each row in ``policy_watches``:

1. Try to find a ``watchlist_items`` row where ``source_url == policy_watches.url``.
2. If found: fill in the merged fields (``user_id``, ``check_frequency``,
   ``enabled`` cast to bool, ``created_at``) on the existing row. Do not
   overwrite already-set values with ``NULL`` — the diff side is the newer
   truth for those columns.
3. If not found: insert a new ``watchlist_items`` row with the URL as
   ``source_url`` and a synthesised ``vendor`` derived from the URL hostname.

The script is idempotent — running twice does not duplicate rows. It counts
matched-updates and new-inserts and logs both.

Manual usage
------------
::

    cd src/backend
    .venv/bin/python scripts/migrate_policywatch_to_watchlist.py

The script is safe to run against production. Wrap the invocation in the
usual DB backup / snapshot procedure.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

# Allow ``python scripts/migrate_policywatch_to_watchlist.py`` invocation
# from ``src/backend/`` without needing ``PYTHONPATH`` set.
_HERE = Path(__file__).resolve()
_BACKEND_ROOT = _HERE.parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from sqlalchemy import inspect, text  # noqa: E402

from app.database import Base, engine, get_db  # noqa: E402
from app.models import WatchlistItem  # noqa: E402

logger = logging.getLogger("migrate_policywatch_to_watchlist")


def _vendor_from_url(url: str) -> str:
    """Derive a display ``vendor`` string from a URL hostname.

    "https://policies.google.com/privacy" -> "policies.google.com"
    Falls back to "Unknown vendor" when the URL cannot be parsed.
    """
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if host:
            return host
    except Exception:
        pass
    return "Unknown vendor"


def _cast_enabled(raw: object) -> bool:
    """Cast the legacy string ``enabled`` value to a real bool (LE-010).

    The old ``PolicyWatch.enabled`` column stored ``"true"`` / ``"false"`` as
    strings. Handle any casing plus common aliases; default to True (matches
    the historical default when the column was set to ``"true"``).
    """
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return True
    text_val = str(raw).strip().lower()
    if text_val in {"false", "0", "no", "off", "disabled"}:
        return False
    return True


def _legacy_table_present() -> bool:
    """Return True when the legacy ``policy_watches`` table still exists.

    Fresh deployments (post-OE-003) never had it; the migration is a no-op
    there. Existing deployments still have the table until it's dropped.
    """
    insp = inspect(engine)
    return "policy_watches" in insp.get_table_names()


def migrate() -> tuple[int, int]:
    """Perform the migration.

    Returns ``(matched_updates, new_inserts)``.
    """
    if not _legacy_table_present():
        logger.info(
            "policy_watches table not present — nothing to migrate. This is expected "
            "on a fresh install."
        )
        return (0, 0)

    # Ensure the target table exists (also expected on any live DB, but harmless).
    Base.metadata.create_all(bind=engine, tables=[WatchlistItem.__table__])

    matched_updates = 0
    new_inserts = 0

    db = next(get_db())
    try:
        # Read all legacy rows in one shot. On a very large table this could be
        # streamed, but the legacy table is bounded by user-created watches —
        # a few thousand rows at most in the field.
        legacy_rows = db.execute(
            text(
                "SELECT id, url, user_id, check_frequency, last_check, enabled, "
                "created_at FROM policy_watches"
            )
        ).mappings().all()

        for row in legacy_rows:
            url = row["url"]
            if not url:
                # Defensive: skip malformed rows rather than crash the batch.
                logger.warning("Skipping policy_watches row %s with empty url", row["id"])
                continue

            enabled = _cast_enabled(row["enabled"])
            created_at = row["created_at"] or datetime.now(timezone.utc)
            check_frequency = row["check_frequency"] or 86400

            existing = (
                db.query(WatchlistItem)
                .filter(WatchlistItem.source_url == url)
                .first()
            )
            if existing is not None:
                # Only fill in blanks — do not overwrite diff-side data.
                changed = False
                if existing.user_id is None and row["user_id"]:
                    existing.user_id = row["user_id"]
                    changed = True
                # ``check_frequency`` defaults to 86400 at the ORM level, so
                # treat "server default" as still fillable if the legacy value
                # was set differently.
                if not existing.check_frequency or existing.check_frequency == 86400:
                    if check_frequency and check_frequency != existing.check_frequency:
                        existing.check_frequency = check_frequency
                        changed = True
                # ``enabled`` similarly defaults to True; adopt legacy False.
                if existing.enabled is True and enabled is False:
                    existing.enabled = False
                    changed = True
                if existing.created_at is None:
                    existing.created_at = created_at
                    changed = True
                if changed:
                    matched_updates += 1
                # else: idempotent no-op re-run.
            else:
                # Synthesize a new WatchlistItem row so cadence/enabled/etc.
                # continue to be honored by the refresh loop.
                new_item = WatchlistItem(
                    id=str(uuid4()),
                    vendor=_vendor_from_url(url),
                    source_url=url,
                    status="No Changes",
                    change_count=0,
                    risk_delta=0.0,
                    user_id=row["user_id"],
                    check_frequency=check_frequency,
                    enabled=enabled,
                    notes=None,
                    created_at=created_at,
                    # ``last_checked`` defaults to now(); we do not have a
                    # last-observed policy body from the legacy row, so
                    # ``last_document_text`` / ``last_document_hash`` stay
                    # NULL and the first refresh loop tick will seed them.
                )
                db.add(new_item)
                new_inserts += 1

        db.commit()
    finally:
        db.close()

    logger.info(
        "OE-003 migration complete: matched_updates=%s new_inserts=%s",
        matched_updates,
        new_inserts,
    )
    return matched_updates, new_inserts


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    updates, inserts = migrate()
    print(f"matched_updates={updates} new_inserts={inserts}")
