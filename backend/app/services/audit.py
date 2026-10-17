"""Append-only, hash-chained audit trail (§10.1). The chain itself is computed by the
database trigger in alembic/versions/0002_audit_chain.py; this module writes events and
verifies the chain with the same canonical expression."""

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditEvent
from app.logging import get_request_id, get_trace_id


async def record(
    session: AsyncSession,
    *,
    org_id: str,
    event_type: str,
    payload: dict[str, Any],
    shipment_id: str | None = None,
    actor_type: str = "SYSTEM",
    actor_id: str | None = None,
) -> None:
    session.add(
        AuditEvent(
            org_id=org_id,
            shipment_id=shipment_id,
            actor_type=actor_type,
            actor_id=actor_id,
            event_type=event_type,
            payload=payload,
            request_id=get_request_id(),
            trace_id=get_trace_id(),
        )
    )
    await session.flush()


_VERIFY_SQL = text(
    """
    WITH chain AS (
      SELECT id, occurred_at, prev_hash, hash,
             lag(hash) OVER (ORDER BY occurred_at, id) AS expected_prev,
             encode(sha256(convert_to(
               coalesce(prev_hash, '') || payload::text ||
               to_char(occurred_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') ||
               event_type, 'UTF8')), 'hex') AS expected_hash
      FROM audit_events WHERE org_id = :org_id
    )
    SELECT id, (hash <> expected_hash) AS bad_hash,
           (prev_hash IS DISTINCT FROM expected_prev) AS bad_link
    FROM chain
    WHERE hash <> expected_hash OR prev_hash IS DISTINCT FROM expected_prev
    ORDER BY occurred_at, id LIMIT 1
    """
)


async def verify_chain(session: AsyncSession, org_id: str) -> dict[str, Any]:
    total = (await session.execute(text("SELECT count(*) FROM audit_events WHERE org_id = :o"), {"o": org_id})).scalar_one()
    row = (await session.execute(_VERIFY_SQL, {"org_id": org_id})).first()
    if row is None:
        return {"org_id": org_id, "valid": True, "events_checked": total, "first_break": None}
    return {
        "org_id": org_id,
        "valid": False,
        "events_checked": total,
        "first_break": {
            "event_id": row.id,
            "reason": "HASH_MISMATCH" if row.bad_hash else "BROKEN_LINK",
        },
    }
