"""Analysis: start the pipeline, stream progress, and read results (§5.1, §5.3)."""

import asyncio
import json
from collections import defaultdict
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import (
    cell_out,
    current_run,
    list_documents,
    load_shipment,
    matrix_document_out,
    missing_out,
)
from app.auth import Principal, get_principal
from app.db.engine import get_session, sessionmaker
from app.db.models import AnalysisRun, Decision, Discrepancy, Document, ExtractedField, FieldVerdict
from app.domain.enums import DocumentStatus, ShipmentStatus, Stage, Verdict
from app.domain.fields import FIELD_GROUP_OF, FIELD_GROUPS, FIELD_LABELS, OUT_OF_SCOPE, OUT_OF_SCOPE_KEYS
from app.domain.status import ANALYZABLE
from app.errors import AppError, ErrorCode
from app.ids import new_id, ulid
from app.logging import get_trace_id
from app.schemas import api
from app.services import audit, events
from app.services.tasks import enqueue

router = APIRouter(tags=["analysis"])


@router.post("/shipments/{shipment_id}/analyze", status_code=202, response_model=api.AnalyzeResponse)
async def analyze(shipment_id: str, p: Principal = Depends(get_principal), session: AsyncSession = Depends(get_session)):
    shipment = await load_shipment(session, p, shipment_id, for_update=True)
    if shipment.status not in ANALYZABLE:
        raise AppError(ErrorCode.SHIPMENT_NOT_REVIEWABLE,
                       f"Analysis cannot start while the shipment is {shipment.status}.", details={"status": shipment.status})
    docs = await list_documents(session, shipment)
    if not docs:
        raise AppError(ErrorCode.INSUFFICIENT_DOCUMENTS, "Upload at least one document before analysis.")

    run_id = new_id("run")
    trace_id = get_trace_id() or ulid().lower()
    session.add(AnalysisRun(id=run_id, shipment_id=shipment.id, org_id=p.org_id, state="QUEUED", trace_id=trace_id))
    shipment.current_run_id = run_id
    shipment.status = ShipmentStatus.QUEUED
    shipment.version += 1
    await events.publish(session, org_id=p.org_id, shipment_id=shipment.id, run_id=run_id, type="pipeline.stage",
                         data={"stage": Stage.INGEST.value, "state": "QUEUED"})
    await audit.record(session, org_id=p.org_id, shipment_id=shipment.id, actor_type="USER", actor_id=p.user_id,
                       event_type="analysis.requested", payload={"run_id": run_id, "document_count": len(docs)})
    await session.commit()
    await enqueue({"org_id": p.org_id, "shipment_id": shipment.id, "run_id": run_id, "stage": Stage.INGEST.value,
                   "trace_id": trace_id, "attempt": 1})
    await session.refresh(shipment)
    return api.AnalyzeResponse(shipment_id=shipment.id, run_id=run_id, status=shipment.status)


def _sse(event: dict) -> str:
    body = {k: event[k] for k in ("type", "shipment_id", "at", "data")}
    return f"id: {event['id']}\nevent: {event['type']}\ndata: {json.dumps(body)}\n\n"


@router.get("/shipments/{shipment_id}/events", response_class=StreamingResponse,
            responses={200: {"content": {"text/event-stream": {}}}})
async def stream_events(shipment_id: str, request: Request, p: Principal = Depends(get_principal),
                        session: AsyncSession = Depends(get_session),
                        last_event_id: str | None = Header(None, alias="Last-Event-ID")):
    """SSE progress. Replays the current run's events (or everything after Last-Event-ID), then
    streams live ones. A ': heartbeat' comment every 15 s keeps proxies from closing the stream."""
    shipment = await load_shipment(session, p, shipment_id)
    run_id = shipment.current_run_id
    await session.close()
    after = int(last_event_id) if last_event_id and last_event_id.isdigit() else None

    async def gen():
        q = await events.broker.subscribe(shipment_id)
        last = after or 0
        try:
            async with sessionmaker()() as s:
                backlog = await events.replay(s, org_id=p.org_id, shipment_id=shipment_id, after_id=after, run_id=run_id)
            for ev in backlog:
                last = max(last, ev["id"])
                yield _sse(ev)
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                except TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                if ev.get("truncated"):
                    async with sessionmaker()() as s:
                        ev = await events.fetch_event(s, ev["id"])
                    if ev is None:
                        continue
                if ev["id"] <= last:
                    continue
                last = ev["id"]
                yield _sse(ev)
        finally:
            events.broker.unsubscribe(shipment_id, q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


async def _run_rows(session: AsyncSession, shipment_id: str, run_id: str | None):
    if not run_id:
        return [], [], {}
    fields = (await session.execute(select(ExtractedField).where(
        ExtractedField.shipment_id == shipment_id, ExtractedField.run_id == run_id))).scalars().all()
    verdicts = (await session.execute(select(FieldVerdict).where(
        FieldVerdict.shipment_id == shipment_id, FieldVerdict.run_id == run_id))).scalars().all()
    dsc = {d.field_key: d.id for d in (await session.execute(select(Discrepancy).where(
        Discrepancy.shipment_id == shipment_id, Discrepancy.run_id == run_id))).scalars()}
    return fields, verdicts, dsc


@router.get("/shipments/{shipment_id}/matrix", response_model=api.MatrixResponse)
async def matrix(shipment_id: str, p: Principal = Depends(get_principal), session: AsyncSession = Depends(get_session)):
    """One round trip per table for the current run, grouped in Python: O(D·F) rows."""
    shipment = await load_shipment(session, p, shipment_id)
    run = await current_run(session, shipment)
    docs = await list_documents(session, shipment)
    fields, verdicts, dsc = await _run_rows(session, shipment.id, shipment.current_run_id)

    by_cell = {(f.field_key, f.document_id): f for f in fields}
    verdict_by_key = {v.field_key: v for v in verdicts}
    grid_docs = [d for d in docs if d.status == DocumentStatus.EXTRACTED]

    groups = []
    for group, entries in FIELD_GROUPS.items():
        rows = []
        for key, label in entries:
            v = verdict_by_key.get(key)
            if v is None or v.verdict == Verdict.NOT_APPLICABLE:
                continue
            rows.append(api.FieldRowOut(
                field_key=key, label=label, verdict=v.verdict, verdict_reason=v.verdict_reason,
                discrepancy_id=dsc.get(key), value_groups=v.value_groups,
                cells=[cell_out(by_cell.get((key, d.id)), d.id) for d in grid_docs],
            ))
        if rows:
            groups.append(api.FieldGroupOut(group=group, fields=rows))

    return api.MatrixResponse(
        shipment_id=shipment.id, status=shipment.status, run_id=shipment.current_run_id,
        generated_at=run.finished_at if run else None,
        documents=[matrix_document_out(d) for d in docs], field_groups=groups,
        missing_documents=missing_out(run), out_of_scope_fields=OUT_OF_SCOPE_KEYS,
        verdict_counts=(run.verdict_counts if run else {}) or {},
    )


async def discrepancy_views(session: AsyncSession, shipment, *, include_decided: bool,
                            only_id: str | None = None) -> list[api.DiscrepancyOut]:
    if not shipment.current_run_id:
        return []
    q = select(Discrepancy).where(Discrepancy.shipment_id == shipment.id, Discrepancy.run_id == shipment.current_run_id)
    if only_id:
        q = q.where(Discrepancy.id == only_id)
    items = list((await session.execute(q.order_by(Discrepancy.created_at, Discrepancy.id))).scalars())
    if not items:
        return []
    decisions = defaultdict(list)
    for dec in (await session.execute(select(Decision).where(
            Decision.discrepancy_id.in_([d.id for d in items])).order_by(Decision.decided_at))).scalars():
        decisions[dec.discrepancy_id].append(dec)
    docs = [d for d in await list_documents(session, shipment) if d.status == DocumentStatus.EXTRACTED]
    fields = (await session.execute(select(ExtractedField).where(
        ExtractedField.shipment_id == shipment.id, ExtractedField.run_id == shipment.current_run_id,
        ExtractedField.field_key.in_({d.field_key for d in items})))).scalars().all()
    by_cell = {(f.field_key, f.document_id): f for f in fields}

    sev_order = {"BLOCKING": 0, "WARNING": 1, "INFO": 2}
    out = []
    for d in sorted(items, key=lambda x: (sev_order.get(x.severity, 3), x.created_at)):
        latest = decisions[d.id][-1] if decisions[d.id] else None
        if latest and not include_decided:
            continue
        out.append(api.DiscrepancyOut(
            discrepancy_id=d.id, shipment_id=d.shipment_id, field_key=d.field_key,
            label=FIELD_LABELS.get(d.field_key, d.field_key), verdict=d.verdict, verdict_reason=d.verdict_reason,
            severity=d.severity, explanation=d.explanation, explanation_state=d.explanation_state,
            assessment_confidence=d.assessment_confidence, likely_incorrect_document_id=d.likely_incorrect_document_id,
            suggested_document_id=d.suggested_document_id, suggested_value=d.suggested_value, version=d.version,
            decided=latest is not None, latest_decision=decision_out(latest, d.field_key) if latest else None,
            cells=[cell_out(by_cell.get((d.field_key, doc.id)), doc.id) for doc in docs
                   if (d.field_key, doc.id) in by_cell],
            created_at=d.created_at,
        ))
    return out


def decision_out(dec: Decision, field_key: str) -> api.DecisionOut:
    return api.DecisionOut(
        decision_id=dec.id, discrepancy_id=dec.discrepancy_id, shipment_id=dec.shipment_id, field_key=field_key,
        action=dec.action, chosen_document_id=dec.chosen_document_id, chosen_value=dec.chosen_value,
        reason=dec.reason, actor_user_id=dec.actor_user_id, decided_at=dec.decided_at,
    )


@router.get("/shipments/{shipment_id}/discrepancies", response_model=api.DiscrepancyList)
async def list_discrepancies(shipment_id: str, include_decided: bool = Query(False),
                             p: Principal = Depends(get_principal), session: AsyncSession = Depends(get_session)):
    shipment = await load_shipment(session, p, shipment_id)
    return api.DiscrepancyList(shipment_id=shipment.id, run_id=shipment.current_run_id,
                               items=await discrepancy_views(session, shipment, include_decided=include_decided))


_UNCHECKED_REASON = {
    DocumentStatus.FAILED: "The document could not be processed.",
    DocumentStatus.SUPERSEDED: "Another document of the same type was used instead.",
    DocumentStatus.REGISTERED: "The document was added after the last analysis.",
}


@router.get("/shipments/{shipment_id}/coverage", response_model=api.CoverageResponse)
async def coverage(shipment_id: str, p: Principal = Depends(get_principal), session: AsyncSession = Depends(get_session)):
    """Principle 2.4: what was NOT checked is reported as prominently as what was."""
    shipment = await load_shipment(session, p, shipment_id)
    run = await current_run(session, shipment)
    docs = await list_documents(session, shipment)
    _, verdicts, _ = await _run_rows(session, shipment.id, shipment.current_run_id)

    def cf(v: FieldVerdict) -> api.CoverageField:
        return api.CoverageField(field_key=v.field_key, label=FIELD_LABELS.get(v.field_key, v.field_key),
                                 group=FIELD_GROUP_OF.get(v.field_key, ""), verdict=v.verdict)

    bucket: dict[str, list[api.CoverageField]] = defaultdict(list)
    for v in verdicts:
        if v.verdict in (Verdict.AGREE, Verdict.DISAGREE, Verdict.AGREE_AT_HS_ROOT, Verdict.TOLERANCE_MATCH):
            bucket["checked"].append(cf(v))
        else:
            bucket[v.verdict].append(cf(v))

    unchecked = []
    for d in docs:
        reason = None
        if d.status in _UNCHECKED_REASON:
            reason = _UNCHECKED_REASON[DocumentStatus(d.status)]
        elif d.doc_type == "UNKNOWN":
            reason = "The document type could not be identified, so no fields were extracted. Set the type and re-run."
        if reason:
            unchecked.append(api.UncheckedDocument(document_id=d.id, filename=d.filename, doc_type=d.doc_type,
                                                   status=d.status, error_code=d.error_code, reason=reason))
    return api.CoverageResponse(
        shipment_id=shipment.id, run_id=shipment.current_run_id,
        checked_fields=bucket["checked"], single_source_fields=bucket[Verdict.SINGLE_SOURCE],
        cannot_verify_fields=bucket[Verdict.CANNOT_VERIFY], not_applicable_fields=bucket[Verdict.NOT_APPLICABLE],
        out_of_scope=[api.OutOfScopeOut(key=o.key, label=o.label, reason=o.reason) for o in OUT_OF_SCOPE],
        unchecked_documents=unchecked, missing_documents=missing_out(run),
    )
