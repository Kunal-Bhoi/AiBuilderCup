"""Signed pre-submission report (§5.1). Only issuable from REVIEWED: every discrepancy has a
human decision before the report exists (principle 2.1 as a state machine)."""

import base64
import hashlib
from collections import defaultdict
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.analysis import discrepancy_views
from app.api.common import current_run, list_documents, load_shipment
from app.auth import Principal, get_principal, require_approver
from app.config import get_settings
from app.db.engine import get_session
from app.db.models import AuditEvent, FieldVerdict, ModelInvocation, Report, Shipment
from app.domain.enums import ShipmentStatus, Verdict
from app.domain.fields import FIELD_LABELS, OUT_OF_SCOPE
from app.domain.status import assert_transition
from app.errors import AppError, ErrorCode, not_found
from app.ids import new_id
from app.schemas import api
from app.services import audit
from app.services.report import ReportData, build_pdf
from app.services.signing import ALGORITHM, sign_digest
from app.services.storage import get_storage, report_object

router = APIRouter(tags=["reports"])


async def _report_out(report: Report) -> api.ReportOut:
    storage = get_storage()
    url, expires = await storage.signed_get_url(storage.object_name(report.gcs_uri), get_settings().read_url_ttl_seconds)
    return api.ReportOut(
        report_id=report.id, shipment_id=report.shipment_id, issued_by=report.issued_by, issued_at=report.issued_at,
        content_sha256=report.content_sha256, signature_algorithm=ALGORITHM,
        signature_b64=base64.b64encode(report.signature).decode(), kms_key_version=report.kms_key_version,
        download_url=url, expires_at=expires,
    )


async def _collect(session: AsyncSession, shipment: Shipment, p: Principal, report_id: str) -> ReportData:
    run = await current_run(session, shipment)
    docs = await list_documents(session, shipment)
    names = {d.id: d.doc_type or d.filename for d in docs}
    views = await discrepancy_views(session, shipment, include_decided=True)
    findings = []
    for v in views:
        values = "; ".join(f"{names.get(c.document_id, c.document_id)}: {c.raw_value or c.cell_status.value}" for c in v.cells)
        dec = v.latest_decision
        findings.append({
            "label": v.label, "verdict": v.verdict.value, "severity": v.severity.value, "values": values,
            "assessment": (f"{v.assessment_confidence}: {v.explanation}" if v.assessment_confidence else v.explanation),
            "action": dec.action.value if dec else None, "reason": dec.reason if dec else None,
            "decided": f"{dec.actor_user_id} at {dec.decided_at.isoformat()}" if dec else None,
        })
    verdicts = (await session.execute(select(FieldVerdict).where(
        FieldVerdict.shipment_id == shipment.id, FieldVerdict.run_id == shipment.current_run_id))).scalars().all()
    by_verdict = defaultdict(list)
    for v in verdicts:
        by_verdict[v.verdict].append(FIELD_LABELS.get(v.field_key, v.field_key))
    models = (await session.execute(
        select(ModelInvocation.stage, ModelInvocation.model, ModelInvocation.model_version, ModelInvocation.prompt_version,
               func.count(), func.coalesce(func.sum(ModelInvocation.cost_usd), 0))
        .where(ModelInvocation.shipment_id == shipment.id, ModelInvocation.occurred_at >= run.created_at)
        .group_by(ModelInvocation.stage, ModelInvocation.model, ModelInvocation.model_version, ModelInvocation.prompt_version)
    )).all()
    head = (await session.execute(select(AuditEvent.hash).where(AuditEvent.org_id == p.org_id)
                                  .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc()).limit(1))).scalar_one_or_none()
    return ReportData(
        report_id=report_id, shipment_reference=shipment.reference, shipment_id=shipment.id, run_id=run.id,
        issued_at=datetime.now(UTC).isoformat(), issued_by=f"{p.email} ({p.user_id})",
        documents=[{"filename": d.filename, "doc_type": d.doc_type or "-", "status": d.status, "error_code": d.error_code,
                    "sha256": d.sha256} for d in docs],
        verdict_counts=run.verdict_counts or {}, findings=findings,
        single_source=by_verdict[Verdict.SINGLE_SOURCE], cannot_verify=by_verdict[Verdict.CANNOT_VERIFY],
        missing_documents=run.missing_documents or [],
        out_of_scope=[{"label": o.label, "reason": o.reason} for o in OUT_OF_SCOPE],
        models=[{"stage": m[0], "model": m[1], "model_version": m[2], "prompt_version": m[3], "calls": m[4]} for m in models],
        audit_head=head, cost_usd=float(sum(m[5] for m in models)),
    )


@router.post("/shipments/{shipment_id}/report", status_code=201, response_model=api.ReportOut)
async def issue_report(shipment_id: str, p: Principal = Depends(require_approver),
                       session: AsyncSession = Depends(get_session)):
    shipment = await load_shipment(session, p, shipment_id, for_update=True)
    if shipment.status != ShipmentStatus.REVIEWED:
        raise AppError(ErrorCode.SHIPMENT_NOT_REVIEWABLE,
                       "A report can only be issued once every finding has a decision.", details={"status": shipment.status})
    assert_transition(shipment.status, ShipmentStatus.REPORT_ISSUED)

    report_id = new_id("rpt")
    pdf = build_pdf(await _collect(session, shipment, p, report_id))
    digest = hashlib.sha256(pdf).digest()
    signature, key_version = await sign_digest(digest)
    uri = await get_storage().upload(report_object(p.org_id, shipment.id, report_id), pdf, "application/pdf")

    report = Report(id=report_id, shipment_id=shipment.id, org_id=p.org_id, gcs_uri=uri, content_sha256=digest.hex(),
                    kms_key_version=key_version, signature=signature, issued_by=p.user_id)
    session.add(report)
    shipment.status = ShipmentStatus.REPORT_ISSUED
    shipment.version += 1
    await audit.record(session, org_id=p.org_id, shipment_id=shipment.id, actor_type="USER", actor_id=p.user_id,
                       event_type="report.issued",
                       payload={"report_id": report_id, "content_sha256": digest.hex(), "kms_key_version": key_version})
    await session.commit()
    await session.refresh(report)
    return await _report_out(report)


@router.get("/shipments/{shipment_id}/report", response_model=api.ReportOut)
async def get_report(shipment_id: str, p: Principal = Depends(get_principal), session: AsyncSession = Depends(get_session)):
    shipment = await load_shipment(session, p, shipment_id)
    report = (await session.execute(select(Report).where(Report.shipment_id == shipment.id, Report.org_id == p.org_id)
                                    .order_by(Report.issued_at.desc()).limit(1))).scalar_one_or_none()
    if report is None:
        raise not_found("Report")
    return await _report_out(report)
