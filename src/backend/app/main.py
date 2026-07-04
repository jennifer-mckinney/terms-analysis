from __future__ import annotations

import asyncio
import csv
import hmac
import json
import logging
import typing
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta, timezone
from io import BytesIO, StringIO
from typing import get_args
from uuid import uuid4
from xml.sax.saxutils import escape as _xml_escape

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from .config import settings
from .database import db_session, get_db, init_db
from .models import Analysis, PolicySnapshot, ReviewItem, WatchlistItem
from .schemas import (
    AnalysisPayload,
    AnalysisSummary,
    AnalyzeBatchRequest,
    AnalyzeRequest,
    AnalyzeUrlRequest,
    BatchAnalysisResult,
    ContextChip,
    CorpusMismatchError,
    DiffResult,
    DiffToken,
    DocType,
    IndustryProfile,
    InferRequest,
    InferResponse,
    Jurisdiction,
    PolicySnapshotListItem,
    PolicySnapshotPayload,
    ReviewItemPayload,
    ReviewUpdate,
    RubricScores,
    WatchlistCreateRequest,
    WatchlistItemPayload,
)
from .services.analyzer import (
    analyze_batch_documents,
    analyze_text,
    calculate_risk_score,
)
from .services.diffing import content_hash, diff_summary, diff_tokens
from .services.inference import infer_all
from .services.ingest import extract_text_from_bytes, fetch_url_text
from .services.rules import detect_findings

logger = logging.getLogger("uvicorn.error")

# Derive allowlists directly from the schema ``Literal`` definitions so that
# any change to the source enums (e.g. adding a new context chip) is picked up
# automatically. The hardcoded allowlist that used to live inside
# ``/analyze/file`` silently dropped the ``for_work`` chip after it was added
# to ``ContextChip`` — deriving from ``typing.get_args`` prevents that drift.
_VALID_CHIPS: frozenset[str] = frozenset(get_args(ContextChip))
_VALID_JURISDICTIONS: frozenset[str] = frozenset(get_args(Jurisdiction))


def _verify_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Enforce API key auth when settings.api_key is set.  No-op when unset."""
    required = settings.api_key
    if not required:
        return
    if x_api_key is None or not hmac.compare_digest(x_api_key, required):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


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


app = FastAPI(
    title="Terms Analysis Backend",
    version="0.1.0",
    lifespan=lifespan,
    dependencies=[Depends(_verify_api_key)],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "X-API-Key"],
)


@app.exception_handler(CorpusMismatchError)
async def corpus_mismatch_handler(
    request: Request, exc: CorpusMismatchError
) -> JSONResponse:
    """Return HTTP 503 with a structured body when a bundle version mismatch is
    detected.  The ``X-Corpus-Mismatch`` header surfaces which MANIFEST field
    failed so callers can act on it without parsing the body."""
    return JSONResponse(
        status_code=503,
        content={"detail": str(exc)},
        headers={"X-Corpus-Mismatch": exc.dimension},
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# OE-003: minimum interval between loop wakeups when no cadence is configured
# and no items are due. Bounds CPU when the watchlist is empty. Also caps the
# sleep between per-item cadence checks so a very-long-cadence item does not
# starve a short-cadence item added later.
_WATCHLIST_LOOP_MIN_SLEEP_S = 60
_WATCHLIST_LOOP_MAX_SLEEP_S = 3600


def _effective_check_frequency(item: WatchlistItem) -> int:
    """OE-003 helper: per-item cadence with the global setting as a fallback.

    A user setting ``check_frequency=3600`` on an item now actually gets an
    hourly refresh — previously ``PolicyWatch.check_frequency`` was written and
    never consumed (silent user-facing bug).
    """
    if item.check_frequency and item.check_frequency > 0:
        return int(item.check_frequency)
    if settings.watchlist_refresh_seconds and settings.watchlist_refresh_seconds > 0:
        return int(settings.watchlist_refresh_seconds)
    return 0


def _compute_next_check_at(item: WatchlistItem) -> datetime | None:
    """Return the datetime at which this item is next due, or None if disabled."""
    if not getattr(item, "enabled", True):
        return None
    cadence = _effective_check_frequency(item)
    if cadence <= 0 or item.last_checked is None:
        return None
    last = item.last_checked
    # SQLite drops tzinfo on round-trip; assume UTC when naive to keep math safe.
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return last + timedelta(seconds=cadence)


async def _watchlist_loop_async() -> None:
    """OE-003: per-item cadence scheduler.

    Previously this loop woke on a single global ``watchlist_refresh_seconds``
    interval and refreshed every item every wakeup. That contract is now
    per-item: each ``WatchlistItem`` carries its own ``check_frequency``, and
    the loop refreshes only past-due, enabled items, then sleeps until the
    next-due wakeup (bounded by ``_WATCHLIST_LOOP_MIN_SLEEP_S`` /
    ``_WATCHLIST_LOOP_MAX_SLEEP_S`` so an empty watchlist or a
    very-long-cadence backlog does not hang the loop).
    """
    while True:
        try:
            sleep_for = await _refresh_due_watchlist_items()
        except Exception:
            # Audit finding LE-003: never swallow the refresh loop error
            # silently. Log with stack so ops has a signal when the loop
            # freezes (SQL error, network wedge, etc.).
            logger.exception(
                "watchlist refresh loop failed; retrying in %s s",
                _WATCHLIST_LOOP_MIN_SLEEP_S,
            )
            sleep_for = _WATCHLIST_LOOP_MIN_SLEEP_S
        await asyncio.sleep(sleep_for)


async def _refresh_due_watchlist_items() -> int:
    """Refresh only items whose ``last_checked + check_frequency`` is in the past
    and that are enabled. Returns the number of seconds to sleep until the next
    due item, clamped to ``[_WATCHLIST_LOOP_MIN_SLEEP_S, _WATCHLIST_LOOP_MAX_SLEEP_S]``.
    """
    with db_session() as db:
        items = (
            db.query(WatchlistItem)
            .filter(WatchlistItem.source_url.isnot(None))
            .all()
        )
        # Fast bail-out: if the watchlist is empty and no global cadence is
        # configured, sleep the max interval so we still tick.
        if not items:
            return (
                settings.watchlist_refresh_seconds
                if settings.watchlist_refresh_seconds > 0
                else _WATCHLIST_LOOP_MAX_SLEEP_S
            )
        now = datetime.now(timezone.utc)
        next_wakeup_deltas: list[float] = []
        for item in items:
            # OE-003: honor the per-item enable flag (LE-010 fix — was string).
            if not getattr(item, "enabled", True):
                continue
            cadence = _effective_check_frequency(item)
            if cadence <= 0:
                # No cadence configured (item + global both 0) — skip.
                continue
            next_due = _compute_next_check_at(item)
            if next_due is not None and next_due > now:
                # Not yet due — record how long until it is.
                next_wakeup_deltas.append((next_due - now).total_seconds())
                continue
            try:
                if item.source_url is None:
                    continue
                text = await fetch_url_text(item.source_url)
            except Exception:
                item.status = "Check Failed"
                item.last_checked = now
                next_wakeup_deltas.append(cadence)
                continue
            current_text = text or ""
            new_hash = content_hash(current_text)
            change_count, summary = diff_summary(item.last_document_text or "", current_text)
            changed = item.last_document_hash and item.last_document_hash != new_hash
            item.last_checked = now
            # Global-tool contract per PR #34 and CLAUDE.md §Session outcomes:
            # empty jurisdictions list == "no filter". Do not hardcode
            # ["US-CA", "GDPR"] here — that silently re-scopes every monitored
            # policy to two jurisdictions regardless of the reader's location.
            # Audit finding LE-001.
            rule_findings = detect_findings(current_text, [])
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
            next_wakeup_deltas.append(cadence)
        db.commit()
    if not next_wakeup_deltas:
        return _WATCHLIST_LOOP_MAX_SLEEP_S
    return int(max(_WATCHLIST_LOOP_MIN_SLEEP_S, min(_WATCHLIST_LOOP_MAX_SLEEP_S, min(next_wakeup_deltas))))


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
        document_text=(payload.document_text or "")[:50_000] or None,
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

    # AI Law Signal Quality: reward high confidence (AI rules firing reliably)
    # and penalise high needs-review rates (uncertain AI-law detections).
    # Static coverage bonus: 12/64 rules cover AI law jurisdictions → 8.5 base.
    ai_law = _clamp(8.5 * avg_conf + 1.5 * (1.0 - review_rate))

    product_integrity = _clamp(base)
    legal_signal = _clamp(confidence_score)
    ai_law_signal = ai_law
    privacy_security = _clamp(base * 0.9 + confidence_score * 0.1)
    accessibility = _clamp(review_score * 0.6 + confidence_score * 0.4)
    visual_ixd = _clamp(review_score * 0.5 + base * 0.5)
    performance = _clamp(review_score * 0.7 + base * 0.3)
    governance = _clamp(review_score)

    # Weighted overall per rubric spec weights
    weighted = (
        0.20 * product_integrity
        + 0.20 * legal_signal
        + 0.10 * ai_law_signal
        + 0.10 * privacy_security
        + 0.15 * accessibility
        + 0.10 * visual_ixd
        + 0.10 * performance
        + 0.05 * governance
    )

    return RubricScores(
        productIntegrity=product_integrity,
        legalSignalQuality=legal_signal,
        aiLawSignalQuality=ai_law_signal,
        privacySecurity=privacy_security,
        accessibilityUsability=accessibility,
        visualIxd=visual_ixd,
        performanceReliability=performance,
        governanceReadiness=governance,
        overall=_clamp(weighted),
    )


@app.post("/infer", response_model=InferResponse)
async def infer(request: InferRequest) -> InferResponse:
    """Infer jurisdictions, doc_type, and industry from URL and/or text.

    Feeds the Streamlit v2 intake: the UI shows what was auto-detected and only
    prompts the user for a location when ``location_needed`` is True.
    """
    if not request.url and not request.text:
        raise HTTPException(status_code=400, detail="Provide at least one of url or text")
    return infer_all(request.url, request.text)


@app.post("/analyze", response_model=AnalysisPayload)
async def analyze(request: AnalyzeRequest, db: Session = Depends(get_db)):
    logger.info(
        "Analyze request: type=text len=%s jurisdictions=%s mode=%s",
        len(request.text),
        request.jurisdictions,
        request.mode,
    )
    resolved_name = request.name or request.source_url or "Pasted Document"
    # ``/analyze`` is the paste-body endpoint: strip and collapse whitespace
    # before the length gate. URL and file endpoints leave whitespace as-is
    # so structural formatting in legal text survives.
    result = await analyze_text(
        request.text,
        request.jurisdictions,
        name=resolved_name,
        doc_type=request.doc_type,
        industry=request.industry,
        source_url=request.source_url,
        mode=request.mode,
        context=request.context,
        is_paste_input=True,
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
        "Analyze request: type=url url=%s jurisdictions=%s mode=%s",
        request.url,
        request.jurisdictions,
        request.mode,
    )
    try:
        text = await fetch_url_text(request.url)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})
    except Exception as exc:
        logger.error("Failed to fetch URL %s: %s", request.url, exc, exc_info=True)
        return JSONResponse(status_code=500, content={"detail": "Failed to fetch URL"})

    if not text:
        raise HTTPException(status_code=400, detail="URL content is empty")

    resolved_name = request.name or request.url
    result = await analyze_text(
        text,
        request.jurisdictions,
        name=resolved_name,
        doc_type=request.doc_type,
        industry=request.industry,
        source_url=request.url,
        mode=request.mode,
        context=request.context,
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
    industry: str | None = Form(default=None),
    jurisdictions: str | None = Form(default=None),
    mode: str | None = Form(default="full"),
    context: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    logger.info(
        "Analyze request: type=file filename=%s content_type=%s mode=%s",
        file.filename,
        file.content_type,
        mode,
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

    _valid_doc_types = set(typing.get_args(DocType))
    _valid_industries = set(typing.get_args(IndustryProfile))
    if doc_type is not None and doc_type not in _valid_doc_types:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid doc_type '{doc_type}'. Valid values: {sorted(_valid_doc_types)}",
        )
    if industry is not None and industry not in _valid_industries:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid industry '{industry}'. Valid values: {sorted(_valid_industries)}",
        )

    # ``jurisdictions`` arrives as a comma-separated list on multipart uploads.
    # Only recognised codes from the schema Literal are kept; unknown values are
    # dropped rather than propagated to the analyzer where they'd short-circuit
    # the post-LLM jurisdiction filter. When no valid values remain the request
    # falls through to the global-tool "no filter" contract (empty list), matching
    # AnalyzeRequest / AnalyzeUrlRequest defaults (schemas.py). Audit finding
    # LE-002 — do not restore a ["US-CA", "GDPR"] fallback here.
    selected_jurisdictions = (
        [j.strip() for j in jurisdictions.split(",") if j.strip() in _VALID_JURISDICTIONS]
        if jurisdictions
        else []
    )

    # ``context`` arrives as a comma-separated list on multipart uploads. Only
    # valid ContextChip values are propagated; anything else is silently dropped
    # so the form endpoint stays tolerant. Allowlist is derived from the schema
    # Literal at module load — see ``_VALID_CHIPS`` — so it can't drift when
    # new chips (e.g. ``for_work``) are added.
    selected_context = (
        [c.strip() for c in context.split(",") if c.strip() in _VALID_CHIPS]
        if context
        else []
    )

    resolved_name = name or file.filename
    result = await analyze_text(
        text,
        selected_jurisdictions,
        name=resolved_name,
        doc_type=doc_type,
        industry=industry,
        source_url=None,
        mode=mode,
        context=selected_context,
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


@app.post("/analyze/batch", response_model=dict)
async def analyze_batch(request: AnalyzeBatchRequest, db: Session = Depends(get_db)):
    """Analyze multiple documents in batch with cross-reference detection."""
    batch_req = request
    logger.info(
        "Batch analyze request: items=%d mode=%s detect_cross_refs=%s",
        len(batch_req.items),
        batch_req.mode,
        batch_req.detect_cross_references,
    )
    
    documents = []
    for item in batch_req.items:
        if item.url:
            try:
                text = await fetch_url_text(item.url)
                if text:
                    documents.append((text, item.name, item.url, item.doc_type))
            except Exception as e:
                logger.error(f"Failed to fetch URL {item.url}: {e}")
                continue
    
    if not documents:
        raise HTTPException(status_code=400, detail="No valid documents to analyze")
    
    # Analyze documents in batch. ``context`` may be absent on legacy request
    # shims (SimpleNamespace fixtures in older tests) — default to [].
    results, cross_refs = await analyze_batch_documents(
        documents,
        batch_req.industry,
        batch_req.jurisdictions,
        batch_req.mode,
        batch_req.detect_cross_references,
        context=getattr(batch_req, "context", None) or [],
    )
    
    # Persist analyses
    for result in results:
        _persist_analysis(
            payload=result,
            source_type="batch",
            source_value=result.source_url,
            doc_type=result.doc_type,
            source_url=result.source_url,
            db=db,
        )
    
    batch_result = BatchAnalysisResult(
        batch_id=str(uuid4()),
        analysis_mode=batch_req.mode,
        items=results,
        cross_references=cross_refs,
        created_at=datetime.now(timezone.utc),
    )
    
    if hasattr(batch_result, 'model_dump'):
        return batch_result.model_dump()
    else:
        return json.loads(batch_result.json())


@app.get("/analyses", response_model=list[AnalysisSummary])
def list_analyses(
    limit: int = Query(default=25, ge=1, le=200),
    db: Session = Depends(get_db),
):
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
    data["document_text"] = None  # strip raw text from public detail response
    return AnalysisPayload(**data)


@app.get("/exports/analyses.csv")
def export_analyses_csv(
    ids: str | None = Query(default=None, description="Comma-separated analysis IDs"),
    detailed: bool = Query(
        default=False,
        description="Emit one row per finding instead of one row per analysis",
    ),
    db: Session = Depends(get_db),
):
    """CSV export honouring PRD §7.3.12 ``ids`` and ``detailed`` params.

    Audit finding GAP-001. Streamlit v2 sends ``?ids={doc_id}&detailed=true``
    to produce a finding-level sheet for a single analysis. Prior behavior
    silently ignored both params and emitted a summary of every analysis.
    """
    query = db.query(Analysis).order_by(Analysis.created_at.desc())
    if ids:
        wanted = [i.strip() for i in ids.split(",") if i.strip()]
        if wanted:
            query = query.filter(Analysis.id.in_(wanted))
    records = query.all()

    output = StringIO()
    writer = csv.writer(output)

    if detailed:
        # Finding-level rows per PRD §5.5.3 column list.
        writer.writerow([
            "analysis_id",
            "document_name",
            "finding_id",
            "category",
            "severity",
            "confidence",
            "excerpt",
            "line_start",
            "line_end",
        ])
        for record in records:
            try:
                data = json.loads(record.result_json) if record.result_json else {}
            except json.JSONDecodeError:
                data = {}
            findings = data.get("findings") or []
            for idx, finding in enumerate(findings):
                evidence = finding.get("evidence") or {}
                writer.writerow([
                    record.id,
                    record.doc_name or "",
                    f"{record.id}-{idx}",
                    finding.get("category", ""),
                    finding.get("severity", ""),
                    f"{float(finding.get('confidence', 0.0)):.2f}",
                    (finding.get("excerpt") or "").replace("\n", " "),
                    evidence.get("line_start", ""),
                    evidence.get("line_end", ""),
                ])
        return Response(content=output.getvalue(), media_type="text/csv")

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
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import (
            HRFlowable,
            PageBreak,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError:
        raise HTTPException(status_code=503, detail="PDF export is not available — reportlab package not installed")

    record = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Analysis not found")

    data = json.loads(record.result_json)
    findings = data.get("findings", [])

    # ── Styles ────────────────────────────────────────────────────────────
    base = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle", parent=base["Title"], fontSize=22, spaceAfter=6
    )
    h2_style = ParagraphStyle(
        "H2", parent=base["Heading2"], fontSize=14, spaceAfter=4
    )
    h3_style = ParagraphStyle(
        "H3", parent=base["Heading3"], fontSize=11, spaceAfter=2
    )
    body_style = ParagraphStyle(
        "Body", parent=base["Normal"], fontSize=9, leading=13, spaceAfter=4
    )
    italic_style = ParagraphStyle(
        "Italic", parent=body_style, fontName="Helvetica-Oblique", backColor=colors.HexColor("#F5F5F5")
    )
    small_style = ParagraphStyle(
        "Small", parent=body_style, fontSize=8, textColor=colors.HexColor("#555555")
    )
    _SEV_COLORS = {
        "Critical": colors.HexColor("#DC2626"),
        "High": colors.HexColor("#EA580C"),
        "Medium": colors.HexColor("#D97706"),
        "Low": colors.HexColor("#16A34A"),
    }
    _GRADE_COLORS = {
        "A": colors.HexColor("#16A34A"),
        "A-": colors.HexColor("#65A30D"),
        "B": colors.HexColor("#CA8A04"),
        "B-": colors.HexColor("#D97706"),
        "C": colors.HexColor("#EA580C"),
        "C+": colors.HexColor("#DC2626"),
        "D+": colors.HexColor("#991B1B"),
    }

    _JURISDICTION_NAMES = {
        "US-CA": "California CCPA/CPRA",
        "US-FED": "US Federal (FTC, COPPA, HIPAA, GLBA, CAN-SPAM)",
        "US-NY": "New York SHIELD Act",
        "US-TX": "Texas TDPSA",
        "US-VA": "Virginia CDPA",
        "US-CO": "Colorado Privacy Act",
        "US-CT": "Connecticut CTDPA",
        "US-IL": "Illinois BIPA",
        "US-NJ": "New Jersey DPA",
        "US-MN": "Minnesota MCDPA",
        "US-OR": "Oregon Consumer Privacy Act",
        "GDPR": "EU General Data Protection Regulation",
        "UK-GDPR": "UK GDPR (post-Brexit)",
        "LGPD": "Brazil Lei Geral de Proteção de Dados",
        "PIPEDA": "Canada Personal Information Protection Act",
        "CA-QC": "Quebec Law 25",
        "POPIA": "South Africa Protection of Personal Information Act",
        "PDPA-KE": "Kenya Data Protection Act 2019",
        "DPDP": "India Digital Personal Data Protection Act 2023",
        "APPI": "Japan Act on Protection of Personal Information",
        "PIPA": "South Korea Personal Information Protection Act",
        "APP": "Australia Privacy Act / Privacy Principles",
        "PDPA-TH": "Thailand Personal Data Protection Act",
        "NDPR": "Nigeria Data Protection Act 2023",
        "ICCPR-17": "UN ICCPR Article 17 (Privacy)",
        "COE-108": "Council of Europe Convention 108+",
        "EU-AI-ACT": "EU Artificial Intelligence Act",
        "COE-AI-225": "Council of Europe AI Convention (CETS 225)",
        "OECD-AI": "OECD AI Principles",
        "UNESCO-AI": "UNESCO AI Ethics Recommendation",
    }

    # ── Collect stats ─────────────────────────────────────────────────────
    sev_counts: dict[str, int] = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0}
    used_jurisdictions: set[str] = set()
    for f in findings:
        sev = f.get("severity", "Low")
        sev_counts[sev] = sev_counts.get(sev, 0) + 1
        for j in f.get("jurisdictions", []):
            used_jurisdictions.add(j)

    grade = data.get("grade", "?")
    risk_score = data.get("risk_score", 0.0)
    confidence = data.get("confidence", 0.0)
    grade_color = _GRADE_COLORS.get(grade, colors.black)

    story = []

    # ── Page 1: Executive Summary ─────────────────────────────────────────
    story.append(Paragraph("Privacy &amp; Terms Analysis Report", title_style))
    story.append(Spacer(1, 6))

    meta_rows = [
        ["Document", data.get("name") or "Untitled"],
        ["Type", data.get("doc_type") or "—"],
        ["Industry", data.get("industry") or "—"],
        ["Analyzed", data.get("created_at", "")[:19].replace("T", " ")],
    ]
    meta_table = Table(meta_rows, colWidths=[1.5 * inch, 5 * inch])
    meta_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 12))

    # Grade badge
    grade_cell = [[Paragraph(f"<b>Grade: {grade}</b>", ParagraphStyle("GB", fontSize=16, textColor=colors.white))]]
    badge = Table(grade_cell, colWidths=[1.5 * inch])
    badge.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), grade_color),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("ROUNDEDCORNERS", [4]),
    ]))
    score_data = [
        [badge, Paragraph(
            f"<b>Risk Score:</b> {risk_score:.1f} / 10<br/>"
            f"<b>Confidence:</b> {confidence * 100:.0f}%<br/>"
            f"<b>Status:</b> {data.get('status', '—')}",
            body_style,
        )],
    ]
    score_table = Table(score_data, colWidths=[1.8 * inch, 4.7 * inch])
    score_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (1, 0), (1, 0), 16),
    ]))
    story.append(score_table)
    story.append(Spacer(1, 10))

    # Severity counts
    sev_row = [[
        Paragraph(f"<b><font color='#{c[1:]}'>&#9632;</font> {sev}:</b> {sev_counts[sev]}", body_style)
        for sev, c in [
            ("Critical", "#DC2626"), ("High", "#EA580C"),
            ("Medium", "#D97706"), ("Low", "#16A34A"),
        ]
    ]]
    sev_table = Table(sev_row, colWidths=[1.6 * inch] * 4)
    sev_table.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    story.append(sev_table)
    story.append(Spacer(1, 10))

    if data.get("summary"):
        story.append(Paragraph("<b>Summary</b>", h2_style))
        story.append(Paragraph(data["summary"], body_style))
        story.append(Spacer(1, 8))

    if used_jurisdictions:
        story.append(Paragraph(
            "<b>Jurisdictions:</b> " + ", ".join(sorted(used_jurisdictions)),
            small_style,
        ))

    story.append(PageBreak())

    # ── Page 2+: Findings grouped by severity ────────────────────────────
    for severity in ("Critical", "High", "Medium", "Low"):
        sev_findings = [f for f in findings if f.get("severity") == severity]
        if not sev_findings:
            continue

        sev_color = _SEV_COLORS.get(severity, colors.black)
        story.append(Paragraph(
            f"<font color='#{sev_color.hexval()[2:]}'><b>{severity} Findings ({len(sev_findings)})</b></font>",
            h2_style,
        ))
        story.append(HRFlowable(width="100%", thickness=1, color=sev_color, spaceAfter=6))

        for f in sev_findings:
            category = _xml_escape(f.get("category", "Unknown"))
            conf_pct = int((f.get("confidence") or 0) * 100)
            story.append(Paragraph(f"<b>{category}</b>", h3_style))
            story.append(Paragraph(
                f"Severity: <b>{_xml_escape(severity)}</b> &nbsp;|&nbsp; Confidence: {conf_pct}%",
                small_style,
            ))

            raw_excerpt = f.get("excerpt") or ""
            excerpt = _xml_escape(raw_excerpt[:500])
            if len(raw_excerpt) > 500:
                excerpt += "…"
            if excerpt:
                story.append(Spacer(1, 3))
                story.append(Paragraph(f'"{excerpt}"', italic_style))

            explanation = _xml_escape(f.get("explanation") or "")
            if explanation:
                story.append(Spacer(1, 3))
                story.append(Paragraph(explanation, body_style))

            legal = f.get("evidence", {}).get("legal_basis") or []
            if legal:
                story.append(Paragraph(
                    "<b>Legal basis:</b> " + "; ".join(_xml_escape(b) for b in legal),
                    small_style,
                ))

            jurs = f.get("jurisdictions") or []
            if jurs:
                story.append(Paragraph(
                    "<b>Jurisdictions:</b> " + ", ".join(_xml_escape(j) for j in jurs),
                    small_style,
                ))

            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#DDDDDD"), spaceAfter=6))
            story.append(Spacer(1, 4))

    # ── Last page: Jurisdiction Legend ────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph("Jurisdictions Referenced", h2_style))
    story.append(Spacer(1, 6))

    legend_data = [["Code", "Framework"]]
    for code, name in _JURISDICTION_NAMES.items():
        legend_data.append([code, name])

    legend_table = Table(legend_data, colWidths=[1.4 * inch, 5.1 * inch])
    legend_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F5F5")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#DDDDDD")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(legend_table)

    # ── Build PDF ─────────────────────────────────────────────────────────
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )
    doc.build(story)
    buffer.seek(0)
    return Response(content=buffer.read(), media_type="application/pdf")


# Registered AFTER the .pdf route above: Starlette matches path routes in
# registration order, and {analysis_id} would otherwise greedily match IDs
# ending in ".pdf" too, silently shadowing the PDF export route (issue found
# by independent UI/UX review — both frontends' "PDF export" were actually
# hitting this JSON route and getting a 404 for a literal "<id>.pdf" lookup).
@app.get("/exports/analysis/{analysis_id}")
def export_analysis_json(analysis_id: str, db: Session = Depends(get_db)):
    record = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return json.loads(record.result_json)


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


def _watchlist_item_to_payload(item: WatchlistItem) -> WatchlistItemPayload:
    """Build the response payload for a ``WatchlistItem``.

    Centralised so every endpoint (list, add, refresh, redirected policy-watch)
    surfaces the OE-003 merged fields (``check_frequency``, ``enabled``,
    ``user_id``, ``notes``, ``created_at``, ``next_check_at``) consistently.
    ``next_check_at`` is computed from ``last_checked + check_frequency``.
    """
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
        user_id=item.user_id,
        check_frequency=item.check_frequency,
        enabled=bool(item.enabled) if item.enabled is not None else None,
        notes=item.notes,
        created_at=item.created_at,
        next_check_at=_compute_next_check_at(item),
    )


@app.get("/watchlist", response_model=list[WatchlistItemPayload])
def list_watchlist(db: Session = Depends(get_db)):
    items = db.query(WatchlistItem).order_by(WatchlistItem.last_checked.desc()).all()
    return [_watchlist_item_to_payload(item) for item in items]


@app.post("/watchlist", response_model=WatchlistItemPayload)
def add_watchlist(request: WatchlistCreateRequest, db: Session = Depends(get_db)):
    # OE-003 merged fields — all optional so pre-merge callers keep working.
    # ``check_frequency`` falls back to ``settings.watchlist_refresh_seconds``
    # at scheduler time via ``_effective_check_frequency`` when the caller
    # omits it. Storing ``None`` here (not the global default) keeps the
    # per-item vs global distinction explicit.
    item = WatchlistItem(
        id=str(uuid4()),
        vendor=request.vendor,
        source_url=request.source_url,
        status="No Changes",
        change_count=0,
        risk_delta=0.0,
        user_id=request.user_id,
        check_frequency=request.check_frequency if request.check_frequency is not None else 86400,
        enabled=bool(request.enabled) if request.enabled is not None else True,
        notes=request.notes,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return _watchlist_item_to_payload(item)


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
        return _watchlist_item_to_payload(item)

    current_text = text or ""
    new_hash = content_hash(current_text)
    change_count, summary = diff_summary(item.last_document_text or "", current_text)
    changed = item.last_document_hash and item.last_document_hash != new_hash
    now = datetime.now(timezone.utc)
    item.last_checked = now
    # Global-tool contract per PR #34 and CLAUDE.md §Session outcomes:
    # empty jurisdictions list == "no filter". Audit finding LE-001.
    rule_findings = detect_findings(current_text, [])
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
    return _watchlist_item_to_payload(item)


# ────────────────────────────────────────────────────────────────────────────
# Policy Snapshots & Diffs (Enhancement 6)
# ────────────────────────────────────────────────────────────────────────────


@app.get("/snapshots", response_model=list[PolicySnapshotListItem])
def get_snapshots(url: str, db: Session = Depends(get_db)):
    """Get historical snapshots of a policy by URL."""
    snapshots = (
        db.query(PolicySnapshot)
        .filter(PolicySnapshot.url == url)
        .order_by(PolicySnapshot.captured_at.desc())
        .all()
    )
    if not snapshots:
        raise HTTPException(status_code=404, detail="No snapshots found for this URL")
    
    return [
        PolicySnapshotListItem(
            id=snapshot.id,
            url=snapshot.url,
            content_hash=snapshot.content_hash,
            captured_at=snapshot.captured_at,
        )
        for snapshot in snapshots
    ]


@app.get("/snapshots/detail/{snapshot_id}", response_model=PolicySnapshotPayload)
def get_snapshot_detail(snapshot_id: str, db: Session = Depends(get_db)):
    """Get full details of a specific snapshot."""
    snapshot = db.query(PolicySnapshot).filter(PolicySnapshot.id == snapshot_id).first()
    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    
    return PolicySnapshotPayload(
        id=snapshot.id,
        url=snapshot.url,
        content_hash=snapshot.content_hash,
        captured_at=snapshot.captured_at,
        raw_text=snapshot.raw_text,
    )


@app.post("/snapshots", response_model=PolicySnapshotPayload)
async def create_snapshot(url: str, db: Session = Depends(get_db)):
    """Capture a new snapshot of a policy by fetching its current content."""
    try:
        text = await fetch_url_text(url)
    except Exception as e:
        logger.warning("Snapshot URL fetch failed for %s: %s", url, e)
        raise HTTPException(status_code=400, detail="Failed to fetch the requested URL.")
    
    if not text:
        raise HTTPException(status_code=400, detail="URL content is empty")
    
    # Check if this content already exists for this URL
    content_hash_val = content_hash(text)
    existing = (
        db.query(PolicySnapshot)
        .filter(PolicySnapshot.url == url, PolicySnapshot.content_hash == content_hash_val)
        .first()
    )
    
    if existing:
        # Return existing snapshot instead of creating a duplicate
        return PolicySnapshotPayload(
            id=existing.id,
            url=existing.url,
            content_hash=existing.content_hash,
            captured_at=existing.captured_at,
            raw_text=None,  # Don't return full text on deduplication
        )
    
    # Create new snapshot
    snapshot = PolicySnapshot(
        id=str(uuid4()),
        url=url,
        content_hash=content_hash_val,
        captured_at=datetime.now(timezone.utc),
        raw_text=text,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    
    return PolicySnapshotPayload(
        id=snapshot.id,
        url=snapshot.url,
        content_hash=snapshot.content_hash,
        captured_at=snapshot.captured_at,
        raw_text=snapshot.raw_text,
    )


@app.get("/diff/{snapshot_id_1}/{snapshot_id_2}", response_model=DiffResult)
def get_diff(snapshot_id_1: str, snapshot_id_2: str, db: Session = Depends(get_db)):
    """Compare two policy snapshots and return token-level diffs."""
    snap1 = db.query(PolicySnapshot).filter(PolicySnapshot.id == snapshot_id_1).first()
    snap2 = db.query(PolicySnapshot).filter(PolicySnapshot.id == snapshot_id_2).first()
    
    if not snap1 or not snap2:
        raise HTTPException(status_code=404, detail="One or both snapshots not found")
    
    if snap1.url != snap2.url:
        raise HTTPException(
            status_code=400,
            detail="Cannot diff snapshots from different URLs"
        )
    
    # Get token-level diff
    diff_data = diff_tokens(snap1.raw_text, snap2.raw_text)
    
    # Convert token dicts to DiffToken objects
    added_tokens = [
        DiffToken(
            token=t["token"],
            type="added",
            line_number=t.get("line_number"),
            severity=t.get("severity", "low"),
        )
        for t in diff_data["added"]
    ]
    
    removed_tokens = [
        DiffToken(
            token=t["token"],
            type="removed",
            line_number=t.get("line_number"),
            severity=t.get("severity", "low"),
        )
        for t in diff_data["removed"]
    ]
    
    unchanged_tokens = [
        DiffToken(
            token=t["token"],
            type="unchanged",
            line_number=t.get("line_number"),
            severity=t.get("severity", "low"),
        )
        for t in diff_data["unchanged"]
    ]
    
    return DiffResult(
        snapshot_1_id=snapshot_id_1,
        snapshot_2_id=snapshot_id_2,
        url=snap1.url,
        created_at_1=snap1.captured_at,
        created_at_2=snap2.captured_at,
        added=added_tokens,
        removed=removed_tokens,
        unchanged=unchanged_tokens,
        change_count=diff_data["change_count"],
        severity_summary=diff_data["severity_summary"],
    )


# ────────────────────────────────────────────────────────────────────────────
# OE-003: /policy-watch/* deprecation shims (Sunset: 2026-10-01)
#
# The ``PolicyWatch`` model was merged into ``WatchlistItem`` on 2026-07-03.
# See ``docs/reports/user-decision-brief-2026-07-03.md`` A3 for rationale.
#
# Design choice on the shim shape:
#   * ``POST /policy-watch``, ``GET /policy-watch``, ``DELETE /policy-watch/{id}``
#     return **308 Permanent Redirect** to the corresponding ``/watchlist/*``
#     route. 308 (not 301) preserves the HTTP method and request body — a client
#     POSTing to ``/policy-watch`` will replay the same POST to ``/watchlist``.
#     The request shapes overlap: ``PolicyWatchCreateRequest.{url, user_id,
#     check_frequency}`` maps onto ``WatchlistCreateRequest.{source_url,
#     user_id, check_frequency}`` — however the field rename (``url`` ->
#     ``source_url``) means a naive replay will fail schema validation. That is
#     the cost of the shim: we redirect at the URL level, and clients that
#     depended on the old field name must update. The ``Deprecation`` and
#     ``Sunset`` headers signal this.
#   * ``POST /policy-watch/{id}/snapshot`` cannot be shimmed cleanly: the old
#     handler dereferenced a ``PolicyWatch`` id to look up a URL to fetch, and
#     no such row exists after the migration. The corresponding
#     ``/watchlist/{id}/refresh`` takes a ``WatchlistItem`` id, not a
#     ``PolicyWatch`` id, so a redirect would 404. Return **410 Gone** with a
#     JSON body pointing at the replacement.
# ────────────────────────────────────────────────────────────────────────────

_DEPRECATION_HEADERS = {
    "Deprecation": "true",
    "Sunset": "2026-10-01",
    "Link": '</watchlist>; rel="successor-version"',
    # RFC 7234 Warning header — surfaced by the security reviewer P9 (F3) so
    # clients that log Warning: on 308 responses see the concrete schema-drift
    # cost of the rename before their POST replay hits /watchlist and 422s.
    "Warning": '299 - "field rename: url -> source_url; refer to /watchlist schema"',
}


@app.post("/policy-watch")
@app.get("/policy-watch")
def policy_watch_root_deprecated():
    """OE-003 deprecation shim — redirect to ``/watchlist``."""
    return Response(
        status_code=308,
        headers={"Location": "/watchlist", **_DEPRECATION_HEADERS},
    )


@app.delete("/policy-watch/{watch_id}")
def policy_watch_delete_deprecated(watch_id: str):
    """OE-003 deprecation shim — redirect to ``/watchlist/{id}``.

    Note: a client that DELETEd a ``PolicyWatch`` id (a row that no longer
    exists) will now hit ``/watchlist/{watch_id}`` with the same id and get a
    404. That is the expected post-migration behavior — the caller must have
    a valid ``WatchlistItem`` id, which the migration script produces.
    """
    return Response(
        status_code=308,
        headers={"Location": f"/watchlist/{watch_id}", **_DEPRECATION_HEADERS},
    )


@app.post("/policy-watch/{watch_id}/snapshot")
def policy_watch_snapshot_deprecated(watch_id: str):
    """OE-003 deprecation shim — 410 Gone.

    A redirect to ``/watchlist/{id}/refresh`` would only work if ``watch_id``
    happened to also exist in ``watchlist_items`` under the same UUID. It does
    not, in the general case. Return 410 with pointer.
    """
    return JSONResponse(
        status_code=410,
        headers=_DEPRECATION_HEADERS,
        content={
            "detail": "The /policy-watch/* endpoints were merged into /watchlist/* on 2026-07-03. Use POST /watchlist/{id}/refresh with your WatchlistItem id instead.",
            "successor": "/watchlist/{id}/refresh",
        },
    )
