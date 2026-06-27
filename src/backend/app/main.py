from __future__ import annotations

import asyncio
import csv
import json
import logging
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from io import BytesIO, StringIO
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from .config import settings
from .database import db_session, get_db, init_db
from .models import Analysis, ReviewItem, WatchlistItem
from .schemas import (
    AnalysisPayload,
    AnalysisSummary,
    AnalyzeRequest,
    AnalyzeUrlRequest,
    ReviewItemPayload,
    ReviewUpdate,
    RubricScores,
    WatchlistCreateRequest,
    WatchlistItemPayload,
)
from .services.analyzer import analyze_text, calculate_risk_score
from .services.diffing import content_hash, diff_summary
from .services.ingest import extract_text_from_bytes, fetch_url_text
from .services.rules import detect_findings


logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    task: asyncio.Task | None = None
    if settings.watchlist_refresh_seconds > 0:
        task = asyncio.create_task(_watchlist_loop_async())
    yield
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Terms Analysis Backend", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "model_world": settings.model_world,
        "model_eu": settings.model_eu,
        "review_threshold": settings.review_threshold,
    }


async def _watchlist_loop_async() -> None:
    while True:
        try:
            await _refresh_all_watchlist_items()
        except Exception:
            pass
        await asyncio.sleep(settings.watchlist_refresh_seconds)


async def _refresh_all_watchlist_items() -> None:
    with db_session() as db:
        if settings.watchlist_refresh_seconds <= 0:
            return
        items = (
            db.query(WatchlistItem)
            .filter(WatchlistItem.source_url.isnot(None))
            .all()
        )
        for item in items:
            try:
                if item.source_url is None:
                    continue
                text = await fetch_url_text(item.source_url)
            except Exception:
                item.status = "Check Failed"
                continue
            current_text = text or ""
            new_hash = content_hash(current_text)
            change_count, summary = diff_summary(item.last_document_text or "", current_text)
            changed = item.last_document_hash and item.last_document_hash != new_hash
            now = datetime.now(timezone.utc)
            item.last_checked = now
            rule_findings = detect_findings(current_text, ["US-CA", "GDPR"])
            new_score = calculate_risk_score(rule_findings)
            if item.last_risk_score is not None:
                item.risk_delta = round(new_score - item.last_risk_score, 2)
            else:
                item.risk_delta = 0.0
            item.last_risk_score = new_score
            if changed:
                item.status = "Updated"
                item.changes_since = now
                item.change_count = change_count
                item.change_summary = summary or "Policy updated."
            else:
                item.status = "No Changes"
                item.change_count = 0
                item.change_summary = ""
            item.last_document_text = current_text[:50_000]
            item.last_document_hash = new_hash
        db.commit()


def _clamp(value: float, lower: float = 0.0, upper: float = 10.0) -> float:
    return max(lower, min(upper, value))


def _persist_analysis(
    payload: AnalysisPayload,
    source_type: str,
    source_value: str | None,
    doc_type: str | None,
    source_url: str | None,
    db: Session,
) -> None:
    """Persist an analysis payload and optional review item to the database."""
    if hasattr(payload, "model_dump_json"):
        payload_json = payload.model_dump_json()
    else:
        payload_json = payload.json()

    analysis = Analysis(
        id=payload.id,
        source_type=source_type,
        source_value=source_value,
        doc_name=payload.name,
        doc_type=doc_type,
        source_url=source_url,
        status=payload.status,
        confidence=payload.confidence,
        risk_score=payload.risk_score,
        grade=payload.grade,
        document_text=payload.document_text,
        result_json=payload_json,
    )
    db.add(analysis)

    if payload.review_required:
        db.add(ReviewItem(id=str(uuid4()), analysis_id=payload.id, status="pending"))

    db.commit()


def _compute_rubric_scores(records: list[Analysis]) -> RubricScores:
    total = len(records)
    avg_risk = sum(record.risk_score or 0.0 for record in records) / total
    avg_conf = sum(record.confidence or 0.0 for record in records) / total
    review_rate = sum(1 for record in records if record.status == "needs_review") / total

    base = _clamp(10 - avg_risk)
    confidence_score = _clamp(avg_conf * 10)
    review_score = _clamp(10 - review_rate * 10)

    return RubricScores(
        productIntegrity=_clamp(base),
        legalSignalQuality=_clamp(confidence_score),
        privacySecurity=_clamp(base * 0.9 + confidence_score * 0.1),
        accessibilityUsability=_clamp(review_score * 0.6 + confidence_score * 0.4),
        visualIxd=_clamp(review_score * 0.5 + base * 0.5),
        performanceReliability=_clamp(review_score * 0.7 + base * 0.3),
        governanceReadiness=_clamp(review_score),
        overall=_clamp((base + confidence_score + review_score) / 3),
    )


@app.post("/analyze", response_model=AnalysisPayload)
async def analyze(request: AnalyzeRequest, db: Session = Depends(get_db)):
    logger.info(
        "Analyze request: type=text len=%s jurisdictions=%s",
        len(request.text),
        request.jurisdictions,
    )
    resolved_name = request.name or request.source_url or "Pasted Document"
    result = await analyze_text(
        request.text,
        request.jurisdictions,
        name=resolved_name,
        doc_type=request.doc_type,
        source_url=request.source_url,
    )
    payload = result.payload
    _persist_analysis(
        payload=payload,
        source_type="text",
        source_value=request.source_url,
        doc_type=request.doc_type,
        source_url=request.source_url,
        db=db,
    )
    return payload


@app.post("/analyze/url", response_model=AnalysisPayload)
async def analyze_url(request: AnalyzeUrlRequest, db: Session = Depends(get_db)):
    logger.info(
        "Analyze request: type=url url=%s jurisdictions=%s",
        request.url,
        request.jurisdictions,
    )
    try:
        text = await fetch_url_text(request.url)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})
    except Exception:
        return JSONResponse(status_code=500, content={"detail": "Failed to fetch URL"})

    if not text:
        raise HTTPException(status_code=400, detail="URL content is empty")

    resolved_name = request.name or request.url
    result = await analyze_text(
        text,
        request.jurisdictions,
        name=resolved_name,
        doc_type=request.doc_type,
        source_url=request.url,
    )
    payload = result.payload
    _persist_analysis(
        payload=payload,
        source_type="url",
        source_value=request.url,
        doc_type=request.doc_type,
        source_url=request.url,
        db=db,
    )
    return payload


@app.post("/analyze/file", response_model=AnalysisPayload)
async def analyze_file(
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    doc_type: str | None = Form(default=None),
    jurisdictions: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    logger.info(
        "Analyze request: type=file filename=%s content_type=%s",
        file.filename,
        file.content_type,
    )
    max_bytes = settings.max_upload_bytes
    data = b""
    while True:
        chunk = await file.read(65536)
        if not chunk:
            break
        data += chunk
        if len(data) > max_bytes:
            raise HTTPException(
                status_code=413, detail="File exceeds maximum upload size"
            )
    text = extract_text_from_bytes(file.filename, file.content_type, data)
    if not text:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    selected_jurisdictions = (
        [j.strip() for j in jurisdictions.split(",") if j.strip()]
        if jurisdictions
        else ["US-CA", "GDPR"]
    )

    resolved_name = name or file.filename
    result = await analyze_text(
        text,
        selected_jurisdictions,
        name=resolved_name,
        doc_type=doc_type,
        source_url=None,
    )
    payload = result.payload
    _persist_analysis(
        payload=payload,
        source_type="file",
        source_value=file.filename,
        doc_type=doc_type,
        source_url=None,
        db=db,
    )
    return payload


@app.get("/analyses", response_model=list[AnalysisSummary])
def list_analyses(limit: int = 25, db: Session = Depends(get_db)):
    records = (
        db.query(Analysis)
        .order_by(Analysis.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        AnalysisSummary(
            id=record.id,
            name=record.doc_name,
            doc_type=record.doc_type,
            source_url=record.source_url,
            status=record.status,
            confidence=record.confidence,
            risk_score=record.risk_score,
            grade=record.grade,
            created_at=record.created_at,
        )
        for record in records
    ]


@app.get("/rubric", response_model=RubricScores | None)
def get_rubric_scores(db: Session = Depends(get_db)):
    records = db.query(Analysis).all()
    if not records:
        return None
    return _compute_rubric_scores(records)


@app.get("/analyses/{analysis_id}", response_model=AnalysisPayload)
def get_analysis(analysis_id: str, db: Session = Depends(get_db)):
    record = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Analysis not found")
    try:
        data = json.loads(record.result_json)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Stored analysis is invalid")
    return AnalysisPayload(**data)


@app.get("/exports/analysis/{analysis_id}")
def export_analysis_json(analysis_id: str, db: Session = Depends(get_db)):
    record = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return json.loads(record.result_json)


@app.get("/exports/analyses.csv")
def export_analyses_csv(db: Session = Depends(get_db)):
    records = db.query(Analysis).order_by(Analysis.created_at.desc()).all()
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id",
        "name",
        "doc_type",
        "source_url",
        "status",
        "confidence",
        "risk_score",
        "grade",
        "created_at",
    ])
    for record in records:
        writer.writerow(
            [
                record.id,
                record.doc_name or "",
                record.doc_type or "",
                record.source_url or "",
                record.status,
                f"{record.confidence:.2f}",
                f"{record.risk_score:.2f}",
                record.grade,
                record.created_at.isoformat(),
            ]
        )
    return Response(content=output.getvalue(), media_type="text/csv")


@app.get("/exports/analysis/{analysis_id}.pdf")
def export_analysis_pdf(analysis_id: str, db: Session = Depends(get_db)):
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
    except ImportError:
        raise HTTPException(status_code=500, detail="PDF export dependency missing")

    record = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Analysis not found")

    data = json.loads(record.result_json)
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    pdf.setFont("Helvetica", 11)
    text = pdf.beginText(40, 750)
    text.textLine(f"Analysis ID: {data.get('id')}")
    text.textLine(f"Name: {data.get('name')}")
    text.textLine(f"Type: {data.get('doc_type')}")
    text.textLine(f"Status: {data.get('status')}")
    text.textLine(f"Confidence: {data.get('confidence')}")
    text.textLine(f"Risk Score: {data.get('risk_score')}")
    text.textLine("")
    text.textLine("Findings:")
    for finding in data.get("findings", []):
        text.textLine(f"- {finding.get('category')} ({finding.get('severity')})")
        text.textLine(f"  Excerpt: {finding.get('excerpt')}")
        text.textLine(f"  Explanation: {finding.get('explanation')}")
        text.textLine("")
    pdf.drawText(text)
    pdf.showPage()
    pdf.save()
    buffer.seek(0)
    return Response(content=buffer.read(), media_type="application/pdf")


@app.get("/reviews", response_model=list[ReviewItemPayload])
def list_reviews(db: Session = Depends(get_db)):
    items = db.query(ReviewItem).filter(ReviewItem.status == "pending").all()
    return [
        ReviewItemPayload(
            id=item.id,
            analysis_id=item.analysis_id,
            status=item.status,
            notes=item.notes,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
        for item in items
    ]


@app.post("/reviews/{review_id}", response_model=ReviewItemPayload)
def update_review(review_id: str, update: ReviewUpdate, db: Session = Depends(get_db)):
    item = db.query(ReviewItem).filter(ReviewItem.id == review_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Review item not found")
    item.status = update.status
    item.notes = update.notes
    db.commit()
    db.refresh(item)
    return ReviewItemPayload(
        id=item.id,
        analysis_id=item.analysis_id,
        status=item.status,
        notes=item.notes,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@app.get("/watchlist", response_model=list[WatchlistItemPayload])
def list_watchlist(db: Session = Depends(get_db)):
    items = db.query(WatchlistItem).order_by(WatchlistItem.last_checked.desc()).all()
    return [
        WatchlistItemPayload(
            id=item.id,
            vendor=item.vendor,
            source_url=item.source_url,
            status=item.status,
            last_checked=item.last_checked,
            changes_since=item.changes_since,
            change_count=item.change_count,
            risk_delta=item.risk_delta,
            change_summary=item.change_summary,
        )
        for item in items
    ]


@app.post("/watchlist", response_model=WatchlistItemPayload)
def add_watchlist(request: WatchlistCreateRequest, db: Session = Depends(get_db)):
    item = WatchlistItem(
        id=str(uuid4()),
        vendor=request.vendor,
        source_url=request.source_url,
        status="No Changes",
        change_count=0,
        risk_delta=0.0,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return WatchlistItemPayload(
        id=item.id,
        vendor=item.vendor,
        source_url=item.source_url,
        status=item.status,
        last_checked=item.last_checked,
        changes_since=item.changes_since,
        change_count=item.change_count,
        risk_delta=item.risk_delta,
        change_summary=item.change_summary,
    )


@app.delete("/watchlist/{item_id}", response_model=dict)
def remove_watchlist(item_id: str, db: Session = Depends(get_db)):
    item = db.query(WatchlistItem).filter(WatchlistItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Watchlist item not found")
    db.delete(item)
    db.commit()
    return {"status": "deleted", "id": item_id}


@app.post("/watchlist/{item_id}/refresh", response_model=WatchlistItemPayload)
async def refresh_watchlist(item_id: str, db: Session = Depends(get_db)):
    item = db.query(WatchlistItem).filter(WatchlistItem.id == item_id).first()
    if not item or not item.source_url:
        raise HTTPException(status_code=404, detail="Watchlist item not found")

    try:
        text = await fetch_url_text(item.source_url)
    except Exception:
        item.status = "Check Failed"
        db.commit()
        db.refresh(item)
        return WatchlistItemPayload(
            id=item.id,
            vendor=item.vendor,
            source_url=item.source_url,
            status=item.status,
            last_checked=item.last_checked,
            changes_since=item.changes_since,
            change_count=item.change_count,
            risk_delta=item.risk_delta,
            change_summary=item.change_summary,
        )

    current_text = text or ""
    new_hash = content_hash(current_text)
    change_count, summary = diff_summary(item.last_document_text or "", current_text)
    changed = item.last_document_hash and item.last_document_hash != new_hash
    now = datetime.now(timezone.utc)
    item.last_checked = now
    rule_findings = detect_findings(current_text, ["US-CA", "GDPR"])
    new_score = calculate_risk_score(rule_findings)
    if item.last_risk_score is not None:
        item.risk_delta = round(new_score - item.last_risk_score, 2)
    else:
        item.risk_delta = 0.0
    item.last_risk_score = new_score
    if changed:
        item.status = "Updated"
        item.changes_since = now
        item.change_count = change_count
        item.change_summary = summary or "Policy updated."
    else:
        item.status = "No Changes"
        item.change_count = 0
        item.change_summary = ""

    item.last_document_text = current_text[:50_000]
    item.last_document_hash = new_hash
    db.commit()
    db.refresh(item)
    return WatchlistItemPayload(
        id=item.id,
        vendor=item.vendor,
        source_url=item.source_url,
        status=item.status,
        last_checked=item.last_checked,
        changes_since=item.changes_since,
        change_count=item.change_count,
        risk_delta=item.risk_delta,
        change_summary=item.change_summary,
    )
