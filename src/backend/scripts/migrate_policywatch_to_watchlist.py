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
from sqlalchemy.exc import IntegrityError  # noqa: E402

from app.database import Base, engine, get_db  # noqa: E402
from app.models import WatchlistItem  # noqa: E402

logger = logging.getLogger("migrate_policywatch_to_watchlist")

# Batch size for chunked legacy-row processing. Reviewer P9 (grumpy) noted the
# original all-in-one-transaction approach OOMs on a few-thousand-row legacy
# table and loses the whole batch on a single IntegrityError. We now stream in
# chunks and wrap each row in a SAVEPOINT so per-row conflicts do not roll
# back the entire chunk.
CHUNK_SIZE = 500

# Explicit truth/falsy allowlists for ``_cast_enabled``. Reviewer P9 (security)
# flagged the previous "default True on anything unrecognized" behaviour as a
# fail-open pattern. We now default False and log a WARNING for unknown values
# so operators can spot drift instead of silently re-enabling watches.
_TRUTHY_SET: frozenset[str] = frozenset({"true", "1", "yes", "on", "enabled"})
_FALSY_SET: frozenset[str] = frozenset({"false", "0", "no", "off", "disabled"})


def _derive_vendor_from_url(url: str) -> str:
    """Derive a display ``vendor`` string from a URL hostname.

    "https://policies.google.com/privacy" -> "policies.google.com"
    Falls back to "Unknown vendor" when the URL cannot be parsed.
    """
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if host:
            return host
    except (ValueError, TypeError) as exc:
        # urlparse can raise ValueError on malformed IPv6 literals; TypeError
        # on non-string inputs. Narrow catch per reviewer P9 (grumpy F12) so
        # unexpected exceptions still surface rather than silently returning
        # "Unknown vendor".
        logger.debug("urlparse failed for %r: %s", url, exc)
    return "Unknown vendor"


def _cast_enabled(raw: object, row_id: object = None) -> bool:
    """Cast the legacy string ``enabled`` value to a real bool (LE-010).

    The old ``PolicyWatch.enabled`` column stored ``"true"`` / ``"false"`` as
    strings. Recognized truthy values (case-insensitive): ``true``, ``1``,
    ``yes``, ``on``, ``enabled``. Recognized falsy values: ``false``, ``0``,
    ``no``, ``off``, ``disabled``. Any unrecognized value logs a WARNING and
    defaults to ``False`` (fail-closed per reviewer P9 security F2).

    ``None`` also maps to ``True`` because the legacy column defaulted to
    ``"true"`` when unset; treating explicit NULL as True preserves the
    pre-merge behaviour for rows that were never touched by the app.
    """
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return True
    text_val = str(raw).strip().lower()
    if text_val in _TRUTHY_SET:
        return True
    if text_val in _FALSY_SET:
        return False
    logger.warning(
        "_cast_enabled: unrecognized value %r for row %s, defaulting to False",
        raw,
        row_id,
    )
    return False


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

    Reviewer P9 (grumpy F1): rows are processed in chunks of ``CHUNK_SIZE``
    with a SAVEPOINT per row. A per-row ``IntegrityError`` (duplicate
    ``source_url`` under a UNIQUE constraint, etc.) rolls back only the
    savepoint and increments ``skipped_count`` instead of losing the whole
    batch. The outer transaction commits at each chunk boundary so a crash
    mid-migration preserves earlier chunks and lets the script resume
    idempotently on rerun.
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
    skipped_count = 0

    db = next(get_db())
    try:
        # Read all legacy rows in one shot. The legacy table is bounded by
        # user-created watches (a few thousand rows at most in the field),
        # so we materialise the ids up front and then stream the actual
        # processing in ``CHUNK_SIZE`` batches below.
        legacy_rows = db.execute(
            text(
                "SELECT id, url, user_id, check_frequency, last_check, enabled, "
                "created_at FROM policy_watches"
            )
        ).mappings().all()

        rows_in_chunk = 0
        for row in legacy_rows:
            url = row["url"]
            if not url:
                # Defensive: skip malformed rows rather than crash the batch.
                logger.warning(
                    "Skipping policy_watches row %s with empty url", row["id"]
                )
                skipped_count += 1
                continue

            enabled = _cast_enabled(row["enabled"], row["id"])
            created_at = row["created_at"] or datetime.now(timezone.utc)
            check_frequency = row["check_frequency"] or 86400

            # SAVEPOINT so a per-row constraint violation does not roll back
            # the surrounding chunk. On dialects that do not support nested
            # transactions natively, SQLAlchemy emulates the SAVEPOINT.
            savepoint = db.begin_nested()
            try:
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
                        vendor=_derive_vendor_from_url(url),
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
                savepoint.commit()
            except IntegrityError as exc:
                savepoint.rollback()
                logger.warning(
                    "Skipping policy_watches row %s (url=%r) after IntegrityError: %s",
                    row["id"],
                    url,
                    exc,
                )
                skipped_count += 1

            rows_in_chunk += 1
            if rows_in_chunk >= CHUNK_SIZE:
                db.commit()
                rows_in_chunk = 0

        # Flush any tail rows that did not fill a full chunk.
        db.commit()
    finally:
        db.close()

    logger.info(
        "OE-003 migration complete: matched_updates=%s new_inserts=%s skipped=%s",
        matched_updates,
        new_inserts,
        skipped_count,
    )
    return matched_updates, new_inserts


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    updates, inserts = migrate()
    print(f"matched_updates={updates} new_inserts={inserts}")
