from __future__ import annotations

import asyncio
import csv
import json
import logging
import typing
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from io import BytesIO, StringIO
from uuid import uuid4
from xml.sax.saxutils import escape as _xml_escape

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from .config import settings
from .database import db_session, get_db, init_db
from .models import Analysis, PolicySnapshot, PolicyWatch, ReviewItem, WatchlistItem
from .schemas import (
    AnalysisPayload,
    AnalysisSummary,
    AnalyzeBatchRequest,
    AnalyzeRequest,
    AnalyzeUrlRequest,
    BatchAnalysisResult,
    DiffResult,
    DiffToken,
    DocType,
    IndustryProfile,
    PolicySnapshotListItem,
    PolicySnapshotPayload,
    PolicyWatchCreateRequest,
    PolicyWatchPayload,
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
from .services.ingest import extract_text_from_bytes, fetch_url_text
from .services.rules import detect_findings

logger = logging.getLogger("uvicorn.error")


def _verify_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Enforce API key auth when settings.api_key is set.  No-op when unset."""
    required = settings.api_key
    if not required:
        return
    if x_api_key != required:
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


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


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
        "Analyze request: type=text len=%s jurisdictions=%s mode=%s",
        len(request.text),
        request.jurisdictions,
        request.mode,
    )
    resolved_name = request.name or request.source_url or "Pasted Document"
    result = await analyze_text(
        request.text,
        request.jurisdictions,
        name=resolved_name,
        doc_type=request.doc_type,
        industry=request.industry,
        source_url=request.source_url,
        mode=request.mode,
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
        industry=request.industry,
        source_url=request.url,
        mode=request.mode,
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
        industry=industry,
        source_url=None,
        mode=mode,
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
    
    # Analyze documents in batch
    results, cross_refs = await analyze_batch_documents(
        documents,
        batch_req.industry,
        batch_req.jurisdictions,
        batch_req.mode,
        batch_req.detect_cross_references,
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
        raise HTTPException(status_code=500, detail="PDF export dependency missing")

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


@app.post("/policy-watch", response_model=PolicyWatchPayload)
def create_policy_watch(request: PolicyWatchCreateRequest, db: Session = Depends(get_db)):
    """Create a new policy watch configuration."""
    # Check if URL is already being watched
    existing = db.query(PolicyWatch).filter(PolicyWatch.url == request.url).first()
    if existing:
        raise HTTPException(status_code=409, detail="URL is already being watched")
    
    watch = PolicyWatch(
        id=str(uuid4()),
        url=request.url,
        user_id=request.user_id,
        check_frequency=request.check_frequency,
        enabled="true",
        created_at=datetime.now(timezone.utc),
    )
    db.add(watch)
    db.commit()
    db.refresh(watch)
    
    return PolicyWatchPayload(
        id=watch.id,
        url=watch.url,
        user_id=watch.user_id,
        check_frequency=watch.check_frequency,
        last_check=watch.last_check,
        enabled=watch.enabled,
        created_at=watch.created_at,
    )


@app.get("/policy-watch", response_model=list[PolicyWatchPayload])
def list_policy_watches(db: Session = Depends(get_db)):
    """List all policy watches."""
    watches = db.query(PolicyWatch).order_by(PolicyWatch.created_at.desc()).all()
    return [
        PolicyWatchPayload(
            id=watch.id,
            url=watch.url,
            user_id=watch.user_id,
            check_frequency=watch.check_frequency,
            last_check=watch.last_check,
            enabled=watch.enabled,
            created_at=watch.created_at,
        )
        for watch in watches
    ]


@app.delete("/policy-watch/{watch_id}", response_model=dict)
def delete_policy_watch(watch_id: str, db: Session = Depends(get_db)):
    """Delete a policy watch configuration."""
    watch = db.query(PolicyWatch).filter(PolicyWatch.id == watch_id).first()
    if not watch:
        raise HTTPException(status_code=404, detail="Policy watch not found")
    
    db.delete(watch)
    db.commit()
    return {"status": "deleted", "id": watch_id}


@app.post("/policy-watch/{watch_id}/snapshot", response_model=PolicySnapshotPayload)
async def capture_watch_snapshot(watch_id: str, db: Session = Depends(get_db)):
    """Capture a new snapshot for a watched policy."""
    watch = db.query(PolicyWatch).filter(PolicyWatch.id == watch_id).first()
    if not watch:
        raise HTTPException(status_code=404, detail="Policy watch not found")
    
    try:
        text = await fetch_url_text(watch.url)
    except Exception as e:
        logger.warning("Policy-watch URL fetch failed for %s: %s", watch.url, e)
        raise HTTPException(status_code=400, detail="Failed to fetch the requested URL.")
    
    if not text:
        raise HTTPException(status_code=400, detail="URL content is empty")
    
    # Check if this content already exists
    content_hash_val = content_hash(text)
    existing = (
        db.query(PolicySnapshot)
        .filter(PolicySnapshot.url == watch.url, PolicySnapshot.content_hash == content_hash_val)
        .first()
    )
    
    if existing:
        # Update last_check time
        watch.last_check = datetime.now(timezone.utc)
        db.commit()
        return PolicySnapshotPayload(
            id=existing.id,
            url=existing.url,
            content_hash=existing.content_hash,
            captured_at=existing.captured_at,
            raw_text=None,
        )
    
    # Create new snapshot
    snapshot = PolicySnapshot(
        id=str(uuid4()),
        url=watch.url,
        content_hash=content_hash_val,
        captured_at=datetime.now(timezone.utc),
        raw_text=text,
    )
    db.add(snapshot)
    watch.last_check = datetime.now(timezone.utc)
    db.commit()
    db.refresh(snapshot)
    
    return PolicySnapshotPayload(
        id=snapshot.id,
        url=snapshot.url,
        content_hash=snapshot.content_hash,
        captured_at=snapshot.captured_at,
        raw_text=snapshot.raw_text,
    )
