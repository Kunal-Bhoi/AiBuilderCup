"""EXPLAIN: one call per disagreement, concurrent, best-effort, capped per shipment (AI-SPEC §12.4, §13).

If an explain call fails the discrepancy still exists, marked UNAVAILABLE. The finding is the
product; the explanation is an aid. This stage never fails the pipeline."""

import asyncio

from sqlalchemy import select

from app.db.models import Discrepancy, Document, ExtractedField, FieldVerdict
from app.domain.enums import CellStatus, ExplanationState, Verdict
from app.errors import AppError
from app.ids import new_id
from app.logging import log
from app.schemas import ai
from app.worker.context import StageContext

RELATED = ["product_description", "hs_code", "quantity", "quantity_uom", "currency", "incoterm", "country_of_origin"]


async def _explain_one(ctx: StageContext, dsc_id: str, sem: asyncio.Semaphore) -> None:
    async with sem, ctx.session() as session:
        d = await session.get(Discrepancy, dsc_id)
        rows = (await session.execute(
            select(ExtractedField, Document.doc_type)
            .join(Document, Document.id == ExtractedField.document_id)
            .where(ExtractedField.run_id == ctx.run_id, ExtractedField.shipment_id == ctx.shipment_id,
                   ExtractedField.field_key == d.field_key,
                   ExtractedField.cell_status.in_([CellStatus.PRESENT, CellStatus.LOW_CONFIDENCE]))
        )).all()
        agreed = (await session.execute(select(FieldVerdict).where(
            FieldVerdict.run_id == ctx.run_id, FieldVerdict.shipment_id == ctx.shipment_id,
            FieldVerdict.field_key.in_(RELATED), FieldVerdict.verdict == Verdict.AGREE))).scalars().all()
        # Grounding: only the conflicting values and agreed related fields, never the whole document set.
        req = ai.ExplainRequest(
            request_id=new_id("req"), shipment_id=ctx.shipment_id, field_key=d.field_key, verdict=d.verdict,
            values=[ai.ExplainValueIn(document_id=f.document_id, doc_type=t, raw_value=f.raw_value,
                                      normalized_value=f.normalized_value, confidence=float(f.confidence)) for f, t in rows],
            related_fields=[ai.RelatedField(field_key=v.field_key,
                                            value=(v.value_groups[0]["normalized_value"] if v.value_groups else None))
                            for v in agreed],
        )
        try:
            resp = await ctx.ai.explain(req)
        except AppError as exc:
            d.explanation_state = ExplanationState.UNAVAILABLE
            await session.commit()
            log.warning("explain_unavailable", extra={"discrepancy_id": d.id, "error_code": exc.code.value})
            return
        await ctx.record_usage(session, resp.usage)
        valid_ids = {f.document_id for f, _ in rows}
        wrong = resp.likely_incorrect_document_id if resp.likely_incorrect_document_id in valid_ids else None
        d.explanation = resp.explanation
        d.assessment_confidence = resp.assessment_confidence if resp.assessment_confidence in ("HIGH", "MODERATE", "LOW") else None
        d.likely_incorrect_document_id = wrong
        d.suggested_value = resp.suggested_value
        if resp.suggested_value is not None:
            match = next((f.document_id for f, _ in rows
                          if f.document_id != wrong and resp.suggested_value in (f.raw_value, f.normalized_value)), None)
            d.suggested_document_id = match
        d.explanation_state = ExplanationState.READY if resp.explanation else ExplanationState.UNAVAILABLE
        await session.commit()


async def run(ctx: StageContext) -> None:
    async with ctx.session() as session:
        pending = (await session.execute(select(Discrepancy).where(
            Discrepancy.shipment_id == ctx.shipment_id, Discrepancy.run_id == ctx.run_id,
            Discrepancy.explanation_state == ExplanationState.PENDING).order_by(Discrepancy.created_at))).scalars().all()
        cap = ctx.settings.explain_cap
        for d in pending[cap:]:
            d.explanation_state = ExplanationState.UNAVAILABLE
        await session.commit()
        ids = [d.id for d in pending[:cap]]

    await ctx.progress("RUNNING", completed=0, total=len(ids))
    sem = asyncio.Semaphore(ctx.settings.extract_concurrency)
    results = await asyncio.gather(*(_explain_one(ctx, i, sem) for i in ids), return_exceptions=True)
    for r in results:
        if isinstance(r, Exception):
            log.warning("explain_crashed", extra={"error_type": type(r).__name__})
    async with ctx.session() as session:
        # Anything still pending after a crash is marked unavailable, never dropped.
        for d in (await session.execute(select(Discrepancy).where(
                Discrepancy.id.in_(ids), Discrepancy.explanation_state == ExplanationState.PENDING))).scalars():
            d.explanation_state = ExplanationState.UNAVAILABLE
        await session.commit()
    await ctx.progress("SUCCEEDED", completed=len(ids), total=len(ids))
