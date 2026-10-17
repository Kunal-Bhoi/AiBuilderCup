"""READY: hand the shipment to a human. Nothing proceeds without their decisions (principle 2.1)."""

from sqlalchemy import func, select

from app.db.models import AnalysisRun, Discrepancy
from app.domain.enums import ShipmentStatus
from app.services import audit
from app.worker.context import StageContext, set_shipment_status, utcnow


async def run(ctx: StageContext) -> None:
    async with ctx.session() as session:
        shipment = await ctx.shipment(session)
        await set_shipment_status(session, shipment, ShipmentStatus.AWAITING_REVIEW)
        open_count = (await session.execute(select(func.count()).select_from(Discrepancy).where(
            Discrepancy.shipment_id == ctx.shipment_id, Discrepancy.run_id == ctx.run_id))).scalar_one()
        if open_count == 0:
            # Nothing to decide. Still a human step: the report is issued explicitly by an approver.
            await set_shipment_status(session, shipment, ShipmentStatus.REVIEWED)
        run = await session.get(AnalysisRun, ctx.run_id)
        run.state, run.finished_at, run.current_stage = "SUCCEEDED", utcnow(), "READY"
        await ctx.publish(session, "pipeline.stage", {"stage": "READY", "state": "SUCCEEDED"})
        await ctx.publish(session, "pipeline.completed", {"verdict_counts": run.verdict_counts,
                                                          "discrepancy_count": open_count,
                                                          "status": shipment.status})
        await audit.record(session, org_id=ctx.org_id, shipment_id=ctx.shipment_id, actor_type="SYSTEM",
                           event_type="pipeline.completed",
                           payload={"run_id": ctx.run_id, "verdict_counts": run.verdict_counts,
                                    "discrepancy_count": open_count})
        await session.commit()
