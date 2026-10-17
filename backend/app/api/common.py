"""Org-scoped loaders and serializers shared by the API routers.

Every loader takes the principal's org_id and filters on it. A row in another org is
reported exactly like a missing row, so a shared link never leaks existence (§13.1)."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import Principal
from app.db.models import AnalysisRun, Document, ExtractedField, ModelInvocation, Shipment
from app.errors import not_found
from app.schemas import api


async def load_shipment(session: AsyncSession, p: Principal, shipment_id: str, *, for_update: bool = False) -> Shipment:
    q = select(Shipment).where(Shipment.id == shipment_id, Shipment.org_id == p.org_id, Shipment.deleted_at.is_(None))
    if for_update:
        q = q.with_for_update()
    shipment = (await session.execute(q)).scalar_one_or_none()
    if shipment is None:
        raise not_found()
    return shipment


async def load_document(session: AsyncSession, p: Principal, document_id: str) -> Document:
    doc = (await session.execute(
        select(Document).join(Shipment, Shipment.id == Document.shipment_id).where(
            Document.id == document_id, Document.org_id == p.org_id, Shipment.deleted_at.is_(None))
    )).scalar_one_or_none()
    if doc is None:
        raise not_found("Document")
    return doc


async def current_run(session: AsyncSession, shipment: Shipment) -> AnalysisRun | None:
    if not shipment.current_run_id:
        return None
    return await session.get(AnalysisRun, shipment.current_run_id)


async def list_documents(session: AsyncSession, shipment: Shipment) -> list[Document]:
    return list((await session.execute(
        select(Document).where(Document.shipment_id == shipment.id, Document.org_id == shipment.org_id)
        .order_by(Document.created_at, Document.id)
    )).scalars())


def document_out(d: Document) -> api.DocumentOut:
    return api.DocumentOut(
        document_id=d.id, filename=d.filename, doc_type=d.doc_type,
        doc_type_confidence=float(d.doc_type_confidence) if d.doc_type_confidence is not None else None,
        doc_type_source=d.doc_type_source, page_count=d.page_count, status=d.status, error_code=d.error_code,
        superseded_by=d.superseded_by, size_bytes=d.size_bytes, content_type=d.content_type, sha256=d.sha256,
        created_at=d.created_at,
    )


def matrix_document_out(d: Document) -> api.MatrixDocumentOut:
    return api.MatrixDocumentOut(
        document_id=d.id, filename=d.filename, doc_type=d.doc_type,
        doc_type_confidence=float(d.doc_type_confidence) if d.doc_type_confidence is not None else None,
        doc_type_source=d.doc_type_source, page_count=d.page_count, status=d.status, error_code=d.error_code,
        superseded_by=d.superseded_by,
    )


async def run_out(session: AsyncSession, run: AnalysisRun | None) -> api.RunOut | None:
    if run is None:
        return None
    cost = (await session.execute(
        select(func.coalesce(func.sum(ModelInvocation.cost_usd), 0), func.coalesce(func.sum(ModelInvocation.input_tokens), 0),
               func.coalesce(func.sum(ModelInvocation.output_tokens), 0))
        .where(ModelInvocation.shipment_id == run.shipment_id, ModelInvocation.occurred_at >= run.created_at)
    )).one()
    return api.RunOut(
        run_id=run.id, state=run.state, stage=run.current_stage, error_code=run.error_code,
        error_message=run.error_message, started_at=run.created_at, finished_at=run.finished_at,
        verdict_counts=run.verdict_counts or {}, cost_usd=float(cost[0]), input_tokens=int(cost[1]),
        output_tokens=int(cost[2]),
    )


def missing_out(run: AnalysisRun | None) -> list[api.MissingDocumentOut]:
    return [api.MissingDocumentOut(**m) for m in (run.missing_documents if run else [])]


def cell_out(f: ExtractedField | None, document_id: str) -> api.CellOut:
    if f is None:
        return api.CellOut(document_id=document_id, cell_status="NOT_APPLICABLE", raw_value=None,
                           normalized_value=None, confidence=0.0, provenance=None)
    return api.CellOut(
        document_id=f.document_id, cell_status=f.cell_status, raw_value=f.raw_value,
        normalized_value=f.normalized_value, normalized_unit=f.normalized_unit, confidence=float(f.confidence),
        provenance=api.ProvenanceOut(
            page=f.page, bbox=[float(b) for b in f.bbox] if f.bbox else None, model=f.model,
            model_version=f.model_version, prompt_version=f.prompt_version, extracted_at=f.extracted_at,
        ),
    )
