"""Runs one pipeline stage per task delivery (§11.2).

Idempotency: INSERT ... ON CONFLICT DO NOTHING into job_runs keyed by
sha256(shipment_id + stage + run_id). A duplicate delivery of a finished stage is
acknowledged with 200 and does nothing.

Return codes, which Cloud Tasks acts on:
  200  success, or a permanent failure that has been recorded (never retry those)
  429/503/504  retryable failure; the queue backs off and redelivers
  500  unexpected bug (also retried)
On the final attempt a retryable failure is recorded as permanent so a shipment never
sits in PROCESSING forever."""

import hashlib
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.config import get_settings
from app.db.models import AnalysisRun, JobRun
from app.domain.enums import ShipmentStatus, Stage, next_stage
from app.domain.status import can_transition
from app.errors import AppError, ErrorCode
from app.ids import new_id
from app.logging import log, set_request_context
from app.services import audit
from app.worker.context import StageContext, set_shipment_status, utcnow
from app.worker.stages import classify, explain, extract, ingest, ready, reconcile

MAX_ATTEMPTS = 5

STAGES: dict[Stage, Callable[[StageContext], Awaitable[None]]] = {
    Stage.INGEST: ingest.run,
    Stage.CLASSIFY: classify.run,
    Stage.EXTRACT: extract.run,
    Stage.RECONCILE: reconcile.run,
    Stage.EXPLAIN: explain.run,
    Stage.READY: ready.run,
}


def idempotency_key(shipment_id: str, stage: str, run_id: str) -> str:
    return hashlib.sha256(f"{shipment_id}{stage}{run_id}".encode()).hexdigest()


async def run_stage(payload: dict[str, Any]) -> int:
    set_request_context(new_id("req"), payload.get("trace_id"))
    ctx = StageContext(org_id=payload["org_id"], shipment_id=payload["shipment_id"], run_id=payload["run_id"],
                       stage=Stage(payload["stage"]), trace_id=payload.get("trace_id"))
    key = idempotency_key(ctx.shipment_id, ctx.stage.value, ctx.run_id)
    log_ctx = {"shipment_id": ctx.shipment_id, "org_id": ctx.org_id, "stage": ctx.stage.value, "run_id": ctx.run_id}

    async with ctx.session() as s:
        res = await s.execute(
            insert(JobRun)
            .values(id=new_id("job"), shipment_id=ctx.shipment_id, org_id=ctx.org_id, stage=ctx.stage.value,
                    state="RUNNING", idempotency_key=key, started_at=utcnow())
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
        )
        job = (await s.execute(select(JobRun).where(JobRun.idempotency_key == key))).scalar_one()
        if res.rowcount == 0:
            if job.state in ("SUCCEEDED", "FAILED", "SKIPPED"):
                log.info("duplicate_delivery_acknowledged", extra=log_ctx)
                return 200
            job.attempt += 1
        shipment = await ctx.shipment(s)
        if shipment.current_run_id != ctx.run_id or shipment.deleted_at is not None:
            job.state, job.finished_at = "SKIPPED", utcnow()
            await s.commit()
            log.info("stale_run_skipped", extra=log_ctx)
            return 200
        if ctx.stage == Stage.INGEST and can_transition(shipment.status, ShipmentStatus.PROCESSING):
            await set_shipment_status(s, shipment, ShipmentStatus.PROCESSING)
            run = await s.get(AnalysisRun, ctx.run_id)
            run.state = "RUNNING"
        attempt = job.attempt
        await s.commit()

    log.info("stage_started", extra={**log_ctx, "attempt": attempt})
    try:
        await STAGES[ctx.stage](ctx)
    except AppError as exc:
        final = attempt >= MAX_ATTEMPTS or get_settings().tasks_mode != "cloudtasks"
        if exc.retryable and not final:
            await _mark_job(key, "RETRYING", exc.code.value)
            log.warning("stage_retryable_failure", extra={**log_ctx, "error_code": exc.code.value})
            return exc.http_status if exc.http_status in (429, 503, 504) else 503
        await fail_pipeline(ctx, exc.code, exc.message, retryable=exc.retryable)
        await _mark_job(key, "FAILED", exc.code.value)
        return 200
    except Exception:
        log.exception("stage_crashed", extra=log_ctx)
        if attempt >= MAX_ATTEMPTS or get_settings().tasks_mode != "cloudtasks":
            await fail_pipeline(ctx, ErrorCode.INTERNAL, "An unexpected error occurred.", retryable=True)
            await _mark_job(key, "FAILED", ErrorCode.INTERNAL.value)
            return 200
        await _mark_job(key, "RETRYING", ErrorCode.INTERNAL.value)
        return 500

    await _mark_job(key, "SUCCEEDED", None)
    log.info("stage_succeeded", extra=log_ctx)
    nxt = next_stage(ctx.stage)
    if nxt is not None:
        from app.services.tasks import enqueue

        await enqueue({**payload, "stage": nxt.value, "attempt": 1})
    return 200


async def _mark_job(key: str, state: str, error_code: str | None) -> None:
    from app.db.engine import sessionmaker

    async with sessionmaker()() as s:
        job = (await s.execute(select(JobRun).where(JobRun.idempotency_key == key))).scalar_one()
        job.state, job.error_code = state, error_code
        if state in ("SUCCEEDED", "FAILED"):
            job.finished_at = utcnow()
        await s.commit()


async def fail_pipeline(ctx: StageContext, code: ErrorCode, message: str, *, retryable: bool) -> None:
    async with ctx.session() as s:
        shipment = await ctx.shipment(s)
        if can_transition(shipment.status, ShipmentStatus.FAILED):
            await set_shipment_status(s, shipment, ShipmentStatus.FAILED)
        run = await s.get(AnalysisRun, ctx.run_id)
        if run:
            run.state, run.error_code, run.error_message, run.finished_at = "FAILED", code.value, message, utcnow()
        await ctx.publish(s, "pipeline.failed", {"error_code": code.value, "retryable": retryable,
                                                 "stage": ctx.stage.value, "message": message})
        await audit.record(s, org_id=ctx.org_id, shipment_id=ctx.shipment_id, event_type="pipeline.failed",
                           payload={"run_id": ctx.run_id, "stage": ctx.stage.value, "error_code": code.value})
        await s.commit()
    log.warning("pipeline_failed", extra={"shipment_id": ctx.shipment_id, "stage": ctx.stage.value, "error_code": code.value})
