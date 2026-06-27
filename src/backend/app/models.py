from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text

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
    last_checked = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    changes_since = Column(DateTime, nullable=True)
    change_count = Column(Integer, nullable=False, default=0)
    risk_delta = Column(Float, nullable=False, default=0.0)
    change_summary = Column(Text, nullable=True)
    last_document_text = Column(Text, nullable=True)
    last_document_hash = Column(String, nullable=True)
    last_risk_score = Column(Float, nullable=True)
    last_analysis_id = Column(String, nullable=True)
