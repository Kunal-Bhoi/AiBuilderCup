"""INGEST (§11.3): validate, convert, render pages to PNG once, store them, keep the text layer.
Pages are rendered once at ingest and reused by every later run and every snippet request."""

import asyncio

from sqlalchemy import delete

from app.db.models import DocumentPage
from app.domain.enums import DocumentStatus
from app.errors import AppError, ErrorCode
from app.logging import log
from app.services.documents_io import IngestFailure, ingest_bytes
from app.services.storage import page_object
from app.worker.context import StageContext


async def run(ctx: StageContext) -> None:
    s = ctx.settings
    async with ctx.session() as session:
        docs = await ctx.documents(session)
        # A re-run keeps rendered pages and model/user document types; it resets per-run progress.
        for d in docs:
            if d.status in (DocumentStatus.CLASSIFIED, DocumentStatus.EXTRACTED):
                d.status = DocumentStatus.INGESTED
            if d.status == DocumentStatus.SUPERSEDED:
                d.status, d.superseded_by = DocumentStatus.INGESTED, None
        await session.commit()
        pending = [d.id for d in docs if d.status == DocumentStatus.REGISTERED]
        total = len(docs)

    await ctx.progress("RUNNING", completed=total - len(pending), total=total)
    done = total - len(pending)
    for doc_id in pending:
        async with ctx.session() as session:
            doc = next(d for d in await ctx.documents(session) if d.id == doc_id)
            try:
                blob = await ctx.storage.download(ctx.storage.object_name(doc.gcs_uri))
                out = await asyncio.to_thread(
                    ingest_bytes, blob, dpi=s.render_dpi, max_px=s.render_max_px, max_pages=s.max_pages_per_document
                )
            except IngestFailure as exc:
                doc.status, doc.error_code = DocumentStatus.FAILED, exc.code.value
                await ctx.publish(session, "document.failed", {"document_id": doc.id, "error_code": exc.code.value,
                                                                "retryable": False, "message": exc.message})
                await session.commit()
                done += 1
                await ctx.progress("RUNNING", completed=done, total=total)
                log.info("document_ingest_failed", extra={"document_id": doc.id, "error_code": exc.code.value})
                continue

            await session.execute(delete(DocumentPage).where(DocumentPage.document_id == doc.id))
            for p in out.pages:
                uri = await ctx.storage.upload(page_object(ctx.org_id, ctx.shipment_id, doc.id, p.page), p.png, "image/png")
                session.add(DocumentPage(document_id=doc.id, page=p.page, gcs_uri=uri, width_px=p.width_px, height_px=p.height_px))
            doc.page_count, doc.text_layer = out.page_count, out.text_layer
            doc.status, doc.error_code = DocumentStatus.INGESTED, None
            await session.commit()
        done += 1
        await ctx.progress("RUNNING", completed=done, total=total)

    async with ctx.session() as session:
        ok = await ctx.documents(session, DocumentStatus.INGESTED)
    if not ok:
        raise AppError(ErrorCode.INSUFFICIENT_DOCUMENTS, "No uploaded document could be read.")
    await ctx.progress("SUCCEEDED", completed=total, total=total)
