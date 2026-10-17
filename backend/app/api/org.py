"""Organisation-level reports: approval effectiveness (IMDA dimension 2: "regularly audit the
effectiveness of such human approvals") and audit-chain verification."""

import statistics

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import Principal, get_principal
from app.db.engine import get_session
from app.db.models import AuditEvent, Decision, Discrepancy, ModelInvocation, Shipment
from app.domain.enums import DecisionAction
from app.schemas import api
from app.services import audit

router = APIRouter(tags=["org"])


@router.get("/org/effectiveness", response_model=api.EffectivenessResponse)
async def effectiveness(p: Principal = Depends(get_principal), session: AsyncSession = Depends(get_session)):
    org = p.org_id
    # Only discrepancies of each shipment's current run count; superseded runs were never reviewed.
    current = select(Discrepancy).join(Shipment, (Shipment.id == Discrepancy.shipment_id) &
                                       (Shipment.current_run_id == Discrepancy.run_id)).where(
        Discrepancy.org_id == org, Shipment.deleted_at.is_(None)).subquery()

    total = (await session.execute(select(func.count()).select_from(current))).scalar_one()
    by_severity = dict((await session.execute(select(current.c.severity, func.count()).group_by(current.c.severity))).all())

    rows = (await session.execute(
        select(Decision.action, current.c.field_key, Decision.decided_at, current.c.created_at, Decision.discrepancy_id)
        .join(current, current.c.id == Decision.discrepancy_id).where(Decision.org_id == org)
        .order_by(Decision.decided_at)
    )).all()
    latest = {r.discrepancy_id: r for r in rows}  # the last decision per finding is the effective one
    by_action: dict[str, int] = {}
    by_field: dict[str, dict[str, int]] = {}
    for r in latest.values():
        by_action[r.action] = by_action.get(r.action, 0) + 1
        by_field.setdefault(r.field_key, {})
        by_field[r.field_key][r.action] = by_field[r.field_key].get(r.action, 0) + 1
    durations = [(r.decided_at - r.created_at).total_seconds() for r in latest.values()]

    followed = (await session.execute(
        select(AuditEvent.payload["followed_assessment"].astext)
        .where(AuditEvent.org_id == org, AuditEvent.event_type == "decision.recorded"))).scalars().all()
    judged = [f for f in followed if f in ("true", "false")]

    decided = len(latest)
    accept = by_action.get(DecisionAction.ACCEPT_SUGGESTION, 0)
    override = by_action.get(DecisionAction.OVERRIDE, 0)
    cost = (await session.execute(select(func.coalesce(func.sum(ModelInvocation.cost_usd), 0),
                                         func.count(func.distinct(ModelInvocation.shipment_id)))
                                  .where(ModelInvocation.org_id == org))).one()
    analyzed = (await session.execute(select(func.count()).select_from(Shipment).where(
        Shipment.org_id == org, Shipment.current_run_id.is_not(None), Shipment.deleted_at.is_(None)))).scalar_one()
    return api.EffectivenessResponse(
        org_id=org, shipments_analyzed=analyzed, discrepancies_total=total, decisions_total=len(rows),
        by_action=by_action, by_severity=by_severity,
        by_field=[api.EffectivenessByField(field_key=k, total=sum(v.values()), by_action=v)
                  for k, v in sorted(by_field.items(), key=lambda kv: -sum(kv[1].values()))],
        suggestion_acceptance_rate=accept / decided if decided else None,
        override_rate=override / decided if decided else None,
        override_against_assessment_rate=judged.count("false") / len(judged) if judged else None,
        median_seconds_to_decision=statistics.median(durations) if durations else None,
        undecided_discrepancies=total - decided,
        cost={"total_usd": float(cost[0]), "per_shipment_avg_usd": float(cost[0]) / cost[1] if cost[1] else 0.0},
    )


@router.get("/org/audit/verify", response_model=api.AuditVerifyResponse)
async def verify_audit(p: Principal = Depends(get_principal), session: AsyncSession = Depends(get_session)):
    return api.AuditVerifyResponse(**await audit.verify_chain(session, p.org_id))
