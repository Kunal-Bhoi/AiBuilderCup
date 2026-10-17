"""Pipeline progress events: persisted to pipeline_events and fanned out with Postgres
LISTEN/NOTIFY. This replaces the spec's Memorystore Redis pub/sub.

Why it is correct across Cloud Run instances: the worker writes the event row and calls
pg_notify inside one transaction, so the notification is delivered on commit to every
api instance holding a LISTEN connection, and the row is there for Last-Event-ID replay.
SSE is an optimisation, never the source of truth (§5.3)."""

import asyncio
import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import raw_connection
from app.db.models import PipelineEvent
from app.logging import log

CHANNEL = "shipment_events"


def _event_dict(ev: PipelineEvent) -> dict[str, Any]:
    at = ev.at if isinstance(ev.at, datetime) else datetime.now(UTC)
    return {
        "id": ev.id,
        "type": ev.type,
        "shipment_id": ev.shipment_id,
        "at": at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "data": ev.data,
    }


async def publish(
    session: AsyncSession, *, org_id: str, shipment_id: str, run_id: str | None, type: str, data: dict[str, Any]
) -> None:
    """Persist and notify. Delivered when the caller's transaction commits."""
    ev = PipelineEvent(org_id=org_id, shipment_id=shipment_id, run_id=run_id, type=type, data=data,
                       at=datetime.now(UTC))
    session.add(ev)
    await session.flush()
    payload = json.dumps(_event_dict(ev))
    if len(payload.encode()) > 7900:  # NOTIFY payload limit is 8000 bytes
        payload = json.dumps({"id": ev.id, "shipment_id": shipment_id, "type": type, "truncated": True})
    await session.execute(text("SELECT pg_notify(:c, :p)"), {"c": CHANNEL, "p": payload})


async def replay(session: AsyncSession, *, org_id: str, shipment_id: str, after_id: int | None,
                 run_id: str | None) -> list[dict[str, Any]]:
    q = select(PipelineEvent).where(PipelineEvent.org_id == org_id, PipelineEvent.shipment_id == shipment_id)
    if after_id is not None:
        q = q.where(PipelineEvent.id > after_id)
    elif run_id is not None:
        q = q.where(PipelineEvent.run_id == run_id)
    rows = (await session.execute(q.order_by(PipelineEvent.id))).scalars().all()
    return [_event_dict(r) for r in rows]


async def fetch_event(session: AsyncSession, event_id: int) -> dict[str, Any] | None:
    ev = await session.get(PipelineEvent, event_id)
    return _event_dict(ev) if ev else None


class EventBroker:
    """One LISTEN connection per process, fanned out to per-shipment asyncio queues."""

    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._conn = None
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None

    async def _ensure_listening(self) -> None:
        async with self._lock:
            if self._conn is not None and not self._conn.is_closed():
                return
            self._conn = await raw_connection()
            await self._conn.add_listener(CHANNEL, self._on_notify)
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._keepalive())
            log.info("event_broker_listening")

    async def _keepalive(self) -> None:
        while self._subs or self._conn is not None:
            await asyncio.sleep(30)
            try:
                if self._conn is None or self._conn.is_closed():
                    self._conn = None
                    if self._subs:
                        await self._ensure_listening()
                else:
                    await self._conn.execute("SELECT 1")
            except Exception:
                log.warning("event_broker_reconnect")
                self._conn = None

    def _on_notify(self, _conn, _pid, _channel, payload: str) -> None:
        try:
            event = json.loads(payload)
        except ValueError:
            return
        for q in list(self._subs.get(event.get("shipment_id", ""), ())):
            q.put_nowait(event)

    async def subscribe(self, shipment_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subs[shipment_id].add(q)
        try:
            await self._ensure_listening()
        except Exception:
            log.warning("event_broker_unavailable")
        return q

    def unsubscribe(self, shipment_id: str, q: asyncio.Queue) -> None:
        subs = self._subs.get(shipment_id)
        if subs:
            subs.discard(q)
            if not subs:
                self._subs.pop(shipment_id, None)

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
        if self._conn is not None and not self._conn.is_closed():
            await self._conn.close()
        self._conn = None


broker = EventBroker()
