"""Shared helpers for pipeline stages."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.engine import sessionmaker
from app.db.models import AnalysisRun, Document, ModelInvocation, Shipment
from app.domain.enums import DocumentStatus, Stage
from app.schemas import ai as ai_schema
from app.services import events
from app.services.ai_client import cost_usd, get_ai_client
from app.services.storage import get_storage


@dataclass
class StageContext:
    org_id: str
    shipment_id: str
    run_id: str
    stage: Stage
    trace_id: str | None = None

    @property
    def settings(self) -> Settings:
        return get_settings()

    @property
    def ai(self):
        return get_ai_client()

    @property
    def storage(self):
        return get_storage()

    def session(self) -> AsyncSession:
        return sessionmaker()()

    async def publish(self, session: AsyncSession, type: str, data: dict[str, Any]) -> None:
        await events.publish(session, org_id=self.org_id, shipment_id=self.shipment_id, run_id=self.run_id,
                             type=type, data=data)

    async def progress(self, state: str, completed: int | None = None, total: int | None = None) -> None:
        async with self.session() as s:
            data: dict[str, Any] = {"stage": self.stage.value, "state": state}
            if completed is not None:
                data["completed"] = completed
            if total is not None:
                data["total"] = total
            await self.publish(s, "pipeline.stage", data)
            await s.execute(update(AnalysisRun).where(AnalysisRun.id == self.run_id).values(current_stage=self.stage.value))
            await s.commit()

    async def documents(self, session: AsyncSession, *statuses: DocumentStatus) -> list[Document]:
        q = select(Document).where(Document.org_id == self.org_id, Document.shipment_id == self.shipment_id)
        if statuses:
            q = q.where(Document.status.in_([s.value for s in statuses]))
        return list((await session.execute(q.order_by(Document.created_at, Document.id))).scalars())

    async def record_usage(self, session: AsyncSession, usage: ai_schema.Usage | None, *, document_id: str | None = None,
                           outcome: str = "OK") -> None:
        if usage is None:
            return
        session.add(ModelInvocation(
            org_id=self.org_id, shipment_id=self.shipment_id, document_id=document_id, stage=self.stage.value,
            model=usage.model, model_version=usage.model_version, prompt_version=usage.prompt_version,
            input_tokens=usage.input_tokens, output_tokens=usage.output_tokens, cost_usd=cost_usd(usage),
            latency_ms=usage.latency_ms, outcome=outcome,
        ))

    async def shipment(self, session: AsyncSession) -> Shipment:
        return (await session.execute(
            select(Shipment).where(Shipment.id == self.shipment_id, Shipment.org_id == self.org_id)
        )).scalar_one()


async def set_shipment_status(session: AsyncSession, shipment: Shipment, status: str) -> None:
    shipment.status = status
    shipment.version += 1
    shipment.updated_at = datetime.now(UTC)


def utcnow() -> datetime:
    return datetime.now(UTC)
