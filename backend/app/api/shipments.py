"""Shipments: create, keyset-paginated list, detail, soft delete (§5.1)."""

import base64
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import current_run, document_out, list_documents, load_shipment, missing_out, run_out
from app.auth import Principal, get_principal
from app.db.engine import get_session
from app.db.models import Decision, Discrepancy, Document, Report, Shipment
from app.domain.enums import ShipmentStatus
from app.errors import AppError, ErrorCode
from app.ids import new_id
from app.schemas import api
from app.services import audit

router = APIRouter(tags=["shipments"])


def _encode_cursor(created_at: datetime, shipment_id: str) -> str:
    return base64.urlsafe_b64encode(f"{created_at.isoformat()}|{shipment_id}".encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        ts, sid = base64.urlsafe_b64decode(cursor.encode()).decode().split("|", 1)
        return datetime.fromisoformat(ts), sid
    except Exception:
        raise AppError(ErrorCode.VALIDATION_FAILED, "The cursor is invalid.", field="cursor")


def _undecided_filter(run_id_col):
    """Discrepancies of the shipment's current run that have no decision yet."""
    return and_(
        Discrepancy.run_id == run_id_col,
        ~select(Decision.id).where(Decision.discrepancy_id == Discrepancy.id).exists(),
    )


async def shipment_detail(session: AsyncSession, shipment: Shipment) -> api.ShipmentDetail:
    run = await current_run(session, shipment)
    docs = await list_documents(session, shipment)
    total = undecided = 0
    if shipment.current_run_id:
        total = (await session.execute(select(func.count()).select_from(Discrepancy).where(
            Discrepancy.shipment_id == shipment.id, Discrepancy.run_id == shipment.current_run_id))).scalar_one()
        undecided = (await session.execute(select(func.count()).select_from(Discrepancy).where(
            Discrepancy.shipment_id == shipment.id, _undecided_filter(shipment.current_run_id)))).scalar_one()
    report_id = (await session.execute(select(Report.id).where(Report.shipment_id == shipment.id)
                                       .order_by(Report.issued_at.desc()).limit(1))).scalar_one_or_none()
    return api.ShipmentDetail(
        shipment_id=shipment.id, reference=shipment.reference, status=shipment.status, version=shipment.version,
        created_by=shipment.created_by, created_at=shipment.created_at, updated_at=shipment.updated_at,
        documents=[document_out(d) for d in docs], current_run=await run_out(session, run),
        missing_documents=missing_out(run), open_discrepancy_count=undecided,
        decided_discrepancy_count=total - undecided, report_id=report_id,
    )


@router.post("/shipments", status_code=201, response_model=api.ShipmentDetail)
async def create_shipment(body: api.ShipmentCreate, p: Principal = Depends(get_principal),
                          session: AsyncSession = Depends(get_session)):
    shipment = Shipment(id=new_id("shp"), org_id=p.org_id, reference=body.reference.strip(),
                        status=ShipmentStatus.DRAFT, created_by=p.user_id)
    session.add(shipment)
    try:
        await session.flush()
    except IntegrityError:
        raise AppError(ErrorCode.VALIDATION_FAILED, "A shipment with this reference already exists.", field="reference")
    await audit.record(session, org_id=p.org_id, shipment_id=shipment.id, actor_type="USER", actor_id=p.user_id,
                       event_type="shipment.created", payload={"shipment_id": shipment.id})
    await session.commit()
    await session.refresh(shipment)
    return await shipment_detail(session, shipment)


@router.get("/shipments", response_model=api.ShipmentList)
async def list_shipments(cursor: str | None = None, limit: int = Query(20, ge=1, le=100),
                         p: Principal = Depends(get_principal), session: AsyncSession = Depends(get_session)):
    # Keyset pagination on (created_at DESC, id DESC): O(log n) per page at any depth.
    q = select(Shipment).where(Shipment.org_id == p.org_id, Shipment.deleted_at.is_(None))
    if cursor:
        ts, sid = _decode_cursor(cursor)
        q = q.where(or_(Shipment.created_at < ts, and_(Shipment.created_at == ts, Shipment.id < sid)))
    rows = list((await session.execute(q.order_by(Shipment.created_at.desc(), Shipment.id.desc()).limit(limit + 1))).scalars())
    page, more = rows[:limit], len(rows) > limit

    ids = [s.id for s in page]
    doc_counts = dict((await session.execute(
        select(Document.shipment_id, func.count()).where(Document.shipment_id.in_(ids)).group_by(Document.shipment_id))).all()) if ids else {}
    open_counts = dict((await session.execute(
        select(Discrepancy.shipment_id, func.count()).join(Shipment, Shipment.id == Discrepancy.shipment_id)
        .where(Discrepancy.shipment_id.in_(ids), _undecided_filter(Shipment.current_run_id))
        .group_by(Discrepancy.shipment_id))).all()) if ids else {}
    return api.ShipmentList(
        items=[api.ShipmentSummary(
            shipment_id=s.id, reference=s.reference, status=s.status, version=s.version,
            document_count=doc_counts.get(s.id, 0), open_discrepancy_count=open_counts.get(s.id, 0),
            created_at=s.created_at, updated_at=s.updated_at) for s in page],
        next_cursor=_encode_cursor(page[-1].created_at, page[-1].id) if more else None,
    )


@router.get("/shipments/{shipment_id}", response_model=api.ShipmentDetail)
async def get_shipment(shipment_id: str, p: Principal = Depends(get_principal),
                       session: AsyncSession = Depends(get_session)):
    return await shipment_detail(session, await load_shipment(session, p, shipment_id))


@router.delete("/shipments/{shipment_id}", status_code=204)
async def delete_shipment(shipment_id: str, p: Principal = Depends(get_principal),
                          session: AsyncSession = Depends(get_session)):
    shipment = await load_shipment(session, p, shipment_id, for_update=True)
    shipment.deleted_at = datetime.now(UTC)
    shipment.status = ShipmentStatus.ARCHIVED
    shipment.version += 1
    await audit.record(session, org_id=p.org_id, shipment_id=shipment.id, actor_type="USER", actor_id=p.user_id,
                       event_type="shipment.deleted", payload={"shipment_id": shipment.id})
    await session.commit()
    return Response(status_code=204)
