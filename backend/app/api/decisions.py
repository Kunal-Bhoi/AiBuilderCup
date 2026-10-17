"""Human decisions (§5.2). The approver is always the authenticated user; there is no code path
that lets a client say who approved something. Optimistic concurrency on discrepancies.version."""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.analysis import decision_out
from app.api.common import load_shipment
from app.auth import Principal, get_principal, require_approver
from app.db.engine import get_session
from app.db.models import Decision, Discrepancy, Document
from app.domain.enums import DecisionAction, ShipmentStatus
from app.domain.status import DECIDABLE
from app.errors import AppError, ErrorCode, not_found
from app.ids import new_id
from app.schemas import api
from app.services import audit

router = APIRouter(tags=["decisions"])

REASON_REQUIRED = {DecisionAction.OVERRIDE, DecisionAction.DISMISS_AS_NOT_AN_ISSUE}
MIN_REASON = 10


@router.post("/discrepancies/{discrepancy_id}/decision", status_code=201, response_model=api.DecisionResponse)
async def record_decision(discrepancy_id: str, body: api.DecisionRequest, p: Principal = Depends(require_approver),
                          session: AsyncSession = Depends(get_session)):
    d = (await session.execute(select(Discrepancy).where(
        Discrepancy.id == discrepancy_id, Discrepancy.org_id == p.org_id))).scalar_one_or_none()
    if d is None:
        raise not_found("Discrepancy")
    shipment = await load_shipment(session, p, d.shipment_id, for_update=True)
    if shipment.status not in DECIDABLE or d.run_id != shipment.current_run_id:
        raise AppError(ErrorCode.SHIPMENT_NOT_REVIEWABLE,
                       "This finding is not open for review (the shipment was re-analysed or the report is issued).",
                       details={"status": shipment.status})

    reason = (body.reason or "").strip() or None
    if body.action in REASON_REQUIRED and (reason is None or len(reason) < MIN_REASON):
        raise AppError(ErrorCode.DECISION_REASON_REQUIRED,
                       f"A reason of at least {MIN_REASON} characters is required for {body.action.value}.", field="reason")

    chosen_doc, chosen_value = body.chosen_document_id, body.chosen_value
    if body.action == DecisionAction.ACCEPT_SUGGESTION:
        if d.suggested_value is None:
            raise AppError(ErrorCode.VALIDATION_FAILED, "There is no suggestion to accept for this finding.", field="action")
        chosen_doc, chosen_value = chosen_doc or d.suggested_document_id, chosen_value or d.suggested_value
    if body.action == DecisionAction.OVERRIDE and not (chosen_doc or chosen_value):
        raise AppError(ErrorCode.VALIDATION_FAILED, "An override needs a chosen document or value.", field="chosen_value")
    if chosen_doc is not None:
        ok = (await session.execute(select(Document.id).where(
            Document.id == chosen_doc, Document.shipment_id == shipment.id))).scalar_one_or_none()
        if ok is None:
            raise AppError(ErrorCode.VALIDATION_FAILED, "The chosen document is not part of this shipment.",
                           field="chosen_document_id")

    bumped = (await session.execute(
        update(Discrepancy).where(Discrepancy.id == d.id, Discrepancy.version == body.expected_version)
        .values(version=Discrepancy.version + 1).returning(Discrepancy.version)
    )).scalar_one_or_none()
    if bumped is None:
        await session.rollback()
        current = (await session.execute(select(Discrepancy.version).where(Discrepancy.id == discrepancy_id))).scalar_one()
        raise AppError(ErrorCode.CONFLICT_STALE_VERSION, "Someone else decided this finding first. Reload and review.",
                       details={"current_version": current})

    dec = Decision(id=new_id("dec"), discrepancy_id=d.id, shipment_id=shipment.id, org_id=p.org_id,
                   actor_user_id=p.user_id, action=body.action.value, chosen_document_id=chosen_doc,
                   chosen_value=chosen_value, reason=reason)
    session.add(dec)
    await session.flush()

    undecided = (await session.execute(select(func.count()).select_from(Discrepancy).where(
        Discrepancy.shipment_id == shipment.id, Discrepancy.run_id == shipment.current_run_id,
        ~select(Decision.id).where(Decision.discrepancy_id == Discrepancy.id).exists()))).scalar_one()
    if undecided == 0 and shipment.status == ShipmentStatus.AWAITING_REVIEW:
        shipment.status = ShipmentStatus.REVIEWED
    shipment.version += 1

    await audit.record(session, org_id=p.org_id, shipment_id=shipment.id, actor_type="USER", actor_id=p.user_id,
                       event_type="decision.recorded",
                       payload={"decision_id": dec.id, "discrepancy_id": d.id, "field_key": d.field_key,
                                "verdict": d.verdict, "action": dec.action, "chosen_document_id": chosen_doc,
                                "chosen_value": chosen_value, "reason": reason,
                                "followed_assessment": _followed(d, dec)})
    await session.commit()
    await session.refresh(dec)
    return api.DecisionResponse(decision=decision_out(dec, d.field_key), discrepancy_version=bumped,
                                shipment_status=shipment.status, remaining_undecided=undecided)


def _followed(d: Discrepancy, dec: Decision) -> bool | None:
    """Did the human agree with the explainer? Feeds the approval-effectiveness report."""
    if d.suggested_value is None and d.likely_incorrect_document_id is None:
        return None
    if dec.action == DecisionAction.ACCEPT_SUGGESTION:
        return True
    if dec.action == DecisionAction.OVERRIDE:
        return dec.chosen_value == d.suggested_value if dec.chosen_value else dec.chosen_document_id == d.suggested_document_id
    return None


@router.get("/shipments/{shipment_id}/decisions", response_model=api.DecisionList)
async def decision_history(shipment_id: str, p: Principal = Depends(get_principal),
                           session: AsyncSession = Depends(get_session)):
    shipment = await load_shipment(session, p, shipment_id)
    rows = (await session.execute(
        select(Decision, Discrepancy.field_key).join(Discrepancy, Discrepancy.id == Decision.discrepancy_id)
        .where(Decision.shipment_id == shipment.id, Decision.org_id == p.org_id).order_by(Decision.decided_at)
    )).all()
    return api.DecisionList(shipment_id=shipment.id, items=[decision_out(dec, key) for dec, key in rows])
