"""EXTRACT: one AI call per document, concurrent under a semaphore of 4 (§11.2).

Every applicable field gets a row, including ones the model did not return, because an
omitted field is indistinguishable from a forgotten one (principle 2.2). Invented field keys
and values for non-applicable fields are discarded. Partial success is a success.

Extraction cache (§11.4): an identical file (same sha256) already extracted as the same
document type in this org is copied instead of re-billed. The copied rows keep their
original model, prompt version and timestamp, so the finding stays re-performable."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import delete, func, select

from app.db.models import Document, DocumentPage, ExtractedField
from app.domain.enums import CellStatus, DocType, DocumentStatus
from app.domain.fields import applicable_fields
from app.errors import AppError, ErrorCode
from app.ids import new_id
from app.logging import log
from app.schemas import ai
from app.worker.context import StageContext

_UNREADABLE_TO_CELL = {"FIELD_ABSENT": CellStatus.ABSENT}


def _clamp_bbox(bbox: list[float] | None) -> list[Decimal] | None:
    if not bbox or len(bbox) != 4:
        return None
    vals = [min(1.0, max(0.0, float(v))) for v in bbox]
    if vals != [float(v) for v in bbox]:
        log.warning("bbox_clamped")
    return [Decimal(str(round(v, 5))) for v in vals]


async def _cached_rows(ctx: StageContext, session, doc: Document) -> list[ExtractedField] | None:
    prior = (await session.execute(
        select(ExtractedField.document_id, ExtractedField.run_id)
        .join(Document, Document.id == ExtractedField.document_id)
        .where(Document.org_id == ctx.org_id, Document.sha256 == doc.sha256, Document.doc_type == doc.doc_type,
               ExtractedField.run_id != ctx.run_id)
        .order_by(ExtractedField.extracted_at.desc())
        .limit(1)
    )).first()
    if prior is None:
        return None
    rows = (await session.execute(select(ExtractedField).where(
        ExtractedField.document_id == prior.document_id, ExtractedField.run_id == prior.run_id))).scalars().all()
    return [
        ExtractedField(
            document_id=doc.id, shipment_id=ctx.shipment_id, org_id=ctx.org_id, field_key=r.field_key,
            raw_value=r.raw_value, normalized_value=r.normalized_value, normalized_unit=r.normalized_unit,
            confidence=r.confidence, cell_status=r.cell_status, page=r.page, bbox=r.bbox, model=r.model,
            model_version=r.model_version, prompt_version=r.prompt_version, extracted_at=r.extracted_at,
            run_id=ctx.run_id,
        )
        for r in rows
    ]


def _rows_from_response(ctx: StageContext, doc: Document, resp: ai.ExtractResponse) -> list[ExtractedField]:
    floor = ctx.settings.confidence_floor
    wanted = applicable_fields(doc.doc_type)
    now = datetime.now(UTC)
    u = resp.usage
    common = dict(document_id=doc.id, shipment_id=ctx.shipment_id, org_id=ctx.org_id, model=u.model,
                  model_version=u.model_version, prompt_version=u.prompt_version, extracted_at=now, run_id=ctx.run_id)
    rows: dict[str, ExtractedField] = {}
    for f in resp.fields:
        if f.field_key not in wanted:
            log.warning("discarded_field", extra={"field_key": f.field_key, "document_id": doc.id})
            continue
        if f.field_key in rows or f.raw_value in (None, ""):
            continue
        conf = min(1.0, max(0.0, f.confidence))
        rows[f.field_key] = ExtractedField(
            field_key=f.field_key, raw_value=f.raw_value, normalized_value=f.normalized_value,
            normalized_unit=f.normalized_unit, confidence=Decimal(str(round(conf, 3))),
            cell_status=CellStatus.PRESENT if conf >= floor else CellStatus.LOW_CONFIDENCE,
            page=f.provenance.page, bbox=_clamp_bbox(f.provenance.bbox), **common,
        )
    for uf in resp.unreadable_fields:
        if uf.field_key in wanted and uf.field_key not in rows:
            rows[uf.field_key] = ExtractedField(
                field_key=uf.field_key, confidence=Decimal("0"),
                cell_status=_UNREADABLE_TO_CELL.get(uf.reason, CellStatus.UNREADABLE), **common)
    for key in wanted:
        if key not in rows:
            rows[key] = ExtractedField(field_key=key, confidence=Decimal("0"), cell_status=CellStatus.ABSENT, **common)
    return list(rows.values())


async def _extract_one(ctx: StageContext, doc_id: str, sem: asyncio.Semaphore) -> AppError | None:
    s = ctx.settings
    async with sem, ctx.session() as session:
        doc = await session.get(Document, doc_id)
        rows = await _cached_rows(ctx, session, doc)
        if rows is None:
            pages = (await session.execute(
                select(DocumentPage).where(DocumentPage.document_id == doc.id).order_by(DocumentPage.page)
            )).scalars().all()
            refs = []
            for p in pages[: s.max_pages_per_extract]:
                url, _ = await ctx.storage.signed_get_url(ctx.storage.object_name(p.gcs_uri), 15 * 60)
                refs.append(ai.PageRef(page=p.page, image_url=url, width_px=p.width_px, height_px=p.height_px))
            req = ai.ExtractRequest(
                request_id=new_id("req"), document_id=doc.id, doc_type=doc.doc_type, pages=refs, text_layer=doc.text_layer,
                options=ai.ExtractOptions(confidence_floor=s.confidence_floor, max_pages=s.max_pages_per_extract),
            )
            try:
                resp = await ctx.ai.extract(req, doc.filename)
            except AppError as exc:
                if not exc.retryable:
                    doc.status, doc.error_code = DocumentStatus.FAILED, exc.code.value
                    await ctx.publish(session, "document.failed", {"document_id": doc.id, "error_code": exc.code.value,
                                                                    "retryable": False, "message": exc.message})
                    await session.commit()
                return exc
            await ctx.record_usage(session, resp.usage, document_id=doc.id)
            rows = _rows_from_response(ctx, doc, resp)
        await session.execute(delete(ExtractedField).where(ExtractedField.document_id == doc.id,
                                                           ExtractedField.run_id == ctx.run_id))
        session.add_all(rows)
        doc.status, doc.error_code = DocumentStatus.EXTRACTED, None
        await session.commit()
    return None


async def run(ctx: StageContext) -> None:
    async with ctx.session() as session:
        docs = [d for d in await ctx.documents(session, DocumentStatus.CLASSIFIED) if d.doc_type != DocType.UNKNOWN]
    total = len(docs)
    await ctx.progress("RUNNING", completed=0, total=total)

    sem = asyncio.Semaphore(ctx.settings.extract_concurrency)
    completed = 0

    async def one(doc_id: str) -> AppError | None:
        nonlocal completed
        err = await _extract_one(ctx, doc_id, sem)
        completed += 1
        await ctx.progress("RUNNING", completed=completed, total=total)
        return err

    errors = [e for e in await asyncio.gather(*(one(d.id) for d in docs)) if e is not None]
    retryable = [e for e in errors if e.retryable]
    if retryable and len(retryable) == len(docs):
        raise retryable[0]  # nothing extracted and the cause is transient: let the queue retry

    async with ctx.session() as session:
        with_fields = (await session.execute(
            select(func.count(func.distinct(ExtractedField.document_id))).where(
                ExtractedField.shipment_id == ctx.shipment_id, ExtractedField.run_id == ctx.run_id,
                ExtractedField.raw_value.is_not(None))
        )).scalar_one()
    if with_fields < ctx.settings.min_documents_with_fields:
        raise AppError(ErrorCode.INSUFFICIENT_DOCUMENTS,
                       "No document produced any readable fields, so nothing can be cross-checked.",
                       details={"documents_with_fields": with_fields})
    await ctx.progress("SUCCEEDED", completed=total, total=total)
