from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text

from .database import Base


class Analysis(Base):
    __tablename__ = "analyses"

    id = Column(String, primary_key=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    doc_name = Column(String, nullable=True)
    doc_type = Column(String, nullable=True)
    source_url = Column(String, nullable=True)
    source_type = Column(String, nullable=False)
    source_value = Column(String, nullable=True)
    status = Column(String, nullable=False)
    confidence = Column(Float, nullable=False)
    risk_score = Column(Float, nullable=False)
    grade = Column(String, nullable=False)
    document_text = Column(Text, nullable=True)
    result_json = Column(Text, nullable=False)


class ReviewItem(Base):
    __tablename__ = "review_items"

    id = Column(String, primary_key=True, index=True)
    analysis_id = Column(
        String, ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False
    )
    status = Column(String, nullable=False, default="pending")
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"

    id = Column(String, primary_key=True, index=True)
    vendor = Column(String, nullable=False)
    source_url = Column(String, nullable=True)
    status = Column(String, nullable=False, default="No Changes")
    # OE-003 merged fields (previously on PolicyWatch — see docs/reports/user-decision-brief-2026-07-03.md).
    # ``user_id`` is nullable because the tool remains local-single-user by default; it exists so
    # multi-tenant deployments can attribute watches without a schema migration. ``check_frequency``
    # is per-item seconds and is now honored by ``_watchlist_loop_async`` — previously ``PolicyWatch``
    # carried this field but nothing consumed it (silent user-facing bug). ``enabled`` is a real
    # Boolean here (LE-010 fix — ``PolicyWatch.enabled`` was a string ``"true"``). ``created_at`` is
    # separate from ``last_checked`` so we can compute ``next_check_at = last_checked + check_frequency``
    # and display "added on" independently of last poll time.
    user_id = Column(String, nullable=True)
    check_frequency = Column(Integer, nullable=False, default=86400)  # seconds (24 hours default)
    enabled = Column(Boolean, nullable=False, default=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    last_checked = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    changes_since = Column(DateTime, nullable=True)
    change_count = Column(Integer, nullable=False, default=0)
    risk_delta = Column(Float, nullable=False, default=0.0)
    change_summary = Column(Text, nullable=True)
    last_document_text = Column(Text, nullable=True)
    last_document_hash = Column(String, nullable=True)
    last_risk_score = Column(Float, nullable=True)
    last_analysis_id = Column(String, nullable=True)


class PolicySnapshot(Base):
    """Historical snapshots of policies tracked in the watchlist."""
    __tablename__ = "policy_snapshots"

    id = Column(String, primary_key=True, index=True)
    url = Column(String, nullable=False, index=True)
    content_hash = Column(String, nullable=False, index=True)
    captured_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    raw_text = Column(Text, nullable=False)


# OE-003: ``PolicyWatch`` was merged into ``WatchlistItem`` (2026-07-03). See the
# decision brief in ``docs/reports/user-decision-brief-2026-07-03.md`` (A3). The
# old ``policy_watches`` table is intentionally not declared here — deployments
# that had rows in it should run ``scripts/migrate_policywatch_to_watchlist.py``
# to move them into ``watchlist_items`` before dropping the legacy table.
