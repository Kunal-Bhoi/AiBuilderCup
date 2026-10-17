"""CLASSIFY: identify document types, detect duplicates and missing required types (AI-SPEC §14).
Only documents without a type are sent to the model, so re-running after a user corrects
one type does not re-bill the others. User-set types are never overwritten."""

from decimal import Decimal

from sqlalchemy import select

from app.db.models import AnalysisRun, DocumentPage
from app.domain.enums import DocType, DocTypeSource, DocumentStatus
from app.domain.fields import REQUIRED_DOC_TYPES
from app.ids import new_id
from app.schemas import ai
from app.worker.context import StageContext


async def run(ctx: StageContext) -> None:
    await ctx.progress("RUNNING")
    async with ctx.session() as session:
        docs = await ctx.documents(session, DocumentStatus.INGESTED)
        to_classify = [d for d in docs if d.doc_type is None]

        result: ai.ClassifyResponse | None = None
        if to_classify:
            items = []
            for d in to_classify:
                first = (await session.execute(
                    select(DocumentPage).where(DocumentPage.document_id == d.id).order_by(DocumentPage.page).limit(1)
                )).scalar_one()
                url, _ = await ctx.storage.signed_get_url(ctx.storage.object_name(first.gcs_uri), 15 * 60)
                items.append(ai.ClassifyDocumentIn(
                    document_id=d.id, filename=d.filename, page_count=d.page_count or 1,
                    pages=[ai.PageRef(page=1, image_url=url, width_px=first.width_px, height_px=first.height_px)],
                    text_layer_excerpt=(d.text_layer or "")[:2000] or None,
                ))
            result = await ctx.ai.classify(ai.ClassifyRequest(request_id=new_id("req"), documents=items))
            await ctx.record_usage(session, result.usage)
            by_id = {c.document_id: c for c in result.documents}
            for d in to_classify:
                c = by_id.get(d.id)
                t = c.doc_type if c and c.doc_type in DocType.__members__ else DocType.UNKNOWN.value
                d.doc_type = t
                d.doc_type_confidence = Decimal(str(round(c.confidence if c else 0.0, 3)))
                d.doc_type_source = DocTypeSource.MODEL

        for d in docs:
            d.status = DocumentStatus.CLASSIFIED
            await ctx.publish(session, "document.classified", {
                "document_id": d.id, "doc_type": d.doc_type,
                "confidence": float(d.doc_type_confidence) if d.doc_type_confidence is not None else None,
                "doc_type_source": d.doc_type_source,
            })

        # Two documents of one type: the reconciler uses the primary (the model's choice, else the
        # latest upload) and the other is surfaced as superseded rather than silently dropped.
        primaries = {g.doc_type: g.primary_document_id for g in (result.duplicates if result else []) if g.primary_document_id}
        by_type: dict[str, list] = {}
        for d in docs:
            if d.doc_type and d.doc_type != DocType.UNKNOWN:
                by_type.setdefault(d.doc_type, []).append(d)
        for t, group in by_type.items():
            if len(group) < 2:
                continue
            primary = primaries.get(t) or group[-1].id
            for d in group:
                if d.id != primary:
                    d.status, d.superseded_by = DocumentStatus.SUPERSEDED, primary
                    await ctx.publish(session, "document.superseded", {"document_id": d.id, "superseded_by": primary})

        present = {d.doc_type for d in docs}
        missing = [m.model_dump() for m in (result.missing_documents if result else [])]
        for t in REQUIRED_DOC_TYPES:
            if t.value not in present and not any(m["doc_type"] == t.value for m in missing):
                missing.append({"doc_type": t.value, "severity": "WARNING",
                                "reason": f"No {t.value.replace('_', ' ').lower()} was uploaded, so its fields were not cross-checked."})
        run = await session.get(AnalysisRun, ctx.run_id)
        run.missing_documents = missing
        await session.commit()
    await ctx.progress("SUCCEEDED", completed=len(docs), total=len(docs))
