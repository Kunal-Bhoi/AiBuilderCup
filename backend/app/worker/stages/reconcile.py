"""RECONCILE: the AI service turns all extracted fields into one verdict per field; the backend
stores verdicts and opens a discrepancy for every verdict a human has to look at.

Severity: DISAGREE is BLOCKING, CANNOT_VERIFY is WARNING, AGREE_AT_HS_ROOT and
TOLERANCE_MATCH are INFO. Every one of them needs a decision before the shipment is REVIEWED:
a rounding difference or a national HS extension is not the same as agreement, and a
broker is entitled to see and sign off on it."""

from collections import Counter

from sqlalchemy import delete, select

from app.db.models import AnalysisRun, Discrepancy, ExtractedField, FieldVerdict
from app.domain.enums import DocumentStatus, ExplanationState, Severity, Verdict
from app.ids import new_id
from app.schemas import ai
from app.worker.context import StageContext

SEVERITY = {
    Verdict.DISAGREE: Severity.BLOCKING,
    Verdict.CANNOT_VERIFY: Severity.WARNING,
    Verdict.AGREE_AT_HS_ROOT: Severity.INFO,
    Verdict.TOLERANCE_MATCH: Severity.INFO,
}


async def run(ctx: StageContext) -> None:
    await ctx.progress("RUNNING")
    async with ctx.session() as session:
        docs = await ctx.documents(session, DocumentStatus.EXTRACTED)
        doc_ids = [d.id for d in docs]
        fields = (await session.execute(select(ExtractedField).where(
            ExtractedField.run_id == ctx.run_id, ExtractedField.document_id.in_(doc_ids)))).scalars().all()

        resp = await ctx.ai.reconcile(ai.ReconcileRequest(
            request_id=new_id("req"), shipment_id=ctx.shipment_id,
            documents=[ai.ReconcileDocumentIn(document_id=d.id, doc_type=d.doc_type) for d in docs],
            fields=[ai.ReconcileFieldIn(
                document_id=f.document_id, field_key=f.field_key, raw_value=f.raw_value,
                normalized_value=f.normalized_value, normalized_unit=f.normalized_unit,
                confidence=float(f.confidence), cell_status=f.cell_status) for f in fields],
            options=ai.ReconcileOptions(confidence_floor=ctx.settings.confidence_floor),
        ))
        await ctx.record_usage(session, resp.usage)

        # Idempotent on redelivery: replace this run's verdicts and discrepancies.
        await session.execute(delete(Discrepancy).where(Discrepancy.shipment_id == ctx.shipment_id,
                                                        Discrepancy.run_id == ctx.run_id))
        await session.execute(delete(FieldVerdict).where(FieldVerdict.shipment_id == ctx.shipment_id,
                                                         FieldVerdict.run_id == ctx.run_id))
        counts: Counter[str] = Counter()
        for v in resp.verdicts:
            verdict = Verdict(v.verdict)
            counts[verdict.value] += 1
            session.add(FieldVerdict(
                shipment_id=ctx.shipment_id, org_id=ctx.org_id, field_key=v.field_key, verdict=verdict.value,
                verdict_reason=v.verdict_reason, value_groups=[g.model_dump() for g in v.value_groups], run_id=ctx.run_id,
            ))
            if verdict in SEVERITY:
                needs_explainer = verdict == Verdict.DISAGREE
                session.add(Discrepancy(
                    id=new_id("dsc"), shipment_id=ctx.shipment_id, org_id=ctx.org_id, field_key=v.field_key,
                    severity=SEVERITY[verdict].value, verdict=verdict.value, verdict_reason=v.verdict_reason,
                    explanation=None if needs_explainer else v.verdict_reason,
                    explanation_state=(ExplanationState.PENDING if needs_explainer else ExplanationState.NOT_REQUIRED).value,
                    run_id=ctx.run_id,
                ))

        run = await session.get(AnalysisRun, ctx.run_id)
        known = {m["doc_type"] for m in run.missing_documents}
        run.missing_documents = run.missing_documents + [
            m.model_dump() for m in resp.missing_documents if m.doc_type not in known]
        run.verdict_counts = {k: v for k, v in counts.items() if k != Verdict.NOT_APPLICABLE}
        await session.commit()
    await ctx.progress("SUCCEEDED")
