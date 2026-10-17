"""Uploads and documents (§5.1, §5.2, §13.4).

Files go straight from the browser to Cloud Storage with a 15-minute signed PUT URL; the API
never proxies document bytes. Registration then checks the object really exists, enforces
the size cap, and records its sha256."""

import hashlib

from fastapi import APIRouter, Depends, Response
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import document_out, load_shipment
from app.auth import Principal, get_principal
from app.config import get_settings
from app.db.models import Document, DocumentPage, Upload
from app.db.engine import get_session
from app.domain.enums import DocTypeSource, DocumentStatus, ShipmentStatus
from app.domain.status import EDITABLE, assert_transition
from app.errors import AppError, ErrorCode, not_found
from app.ids import new_id
from app.schemas import api
from app.services import audit
from app.services.documents_io import ACCEPTED_CONTENT_TYPES
from app.services.storage import get_storage, original_object

router = APIRouter(tags=["documents"])


def _assert_editable(status: str) -> None:
    if status not in EDITABLE:
        raise AppError(ErrorCode.SHIPMENT_NOT_REVIEWABLE,
                       f"Documents cannot be changed while the shipment is {status}.", details={"status": status})


async def _document_count(session: AsyncSession, shipment_id: str) -> int:
    return (await session.execute(select(func.count()).select_from(Document).where(
        Document.shipment_id == shipment_id))).scalar_one()


@router.post("/shipments/{shipment_id}/upload-urls", response_model=api.UploadUrlsResponse)
async def create_upload_urls(shipment_id: str, body: api.UploadUrlsRequest, p: Principal = Depends(get_principal),
                             session: AsyncSession = Depends(get_session)):
    s = get_settings()
    shipment = await load_shipment(session, p, shipment_id, for_update=True)
    _assert_editable(shipment.status)
    if await _document_count(session, shipment.id) + len(body.files) > s.max_files_per_shipment:
        raise AppError(ErrorCode.VALIDATION_FAILED,
                       f"A shipment can hold at most {s.max_files_per_shipment} files.", field="files")
    for i, f in enumerate(body.files):
        if f.size_bytes > s.max_file_bytes:
            raise AppError(ErrorCode.FILE_TOO_LARGE, f"{f.filename} exceeds the {s.max_file_bytes // (1024 * 1024)} MB limit.",
                           field=f"files.{i}.size_bytes")
        if f.content_type.lower() not in ACCEPTED_CONTENT_TYPES:
            raise AppError(ErrorCode.UNSUPPORTED_FILE_TYPE, f"{f.content_type} is not a supported file type.",
                           field=f"files.{i}.content_type",
                           details={"supported": sorted(ACCEPTED_CONTENT_TYPES)})

    storage = get_storage()
    out = []
    for f in body.files:
        upload_id = new_id("up")
        obj = original_object(p.org_id, shipment.id, upload_id)
        url, expires = await storage.signed_put_url(obj, f.content_type, s.upload_url_ttl_seconds)
        session.add(Upload(id=upload_id, shipment_id=shipment.id, org_id=p.org_id, filename=f.filename,
                           content_type=f.content_type, size_bytes=f.size_bytes, object_name=obj))
        out.append(api.UploadUrlOut(upload_id=upload_id, filename=f.filename, signed_url=url,
                                    headers={"Content-Type": f.content_type}, expires_at=expires))
    if shipment.status != ShipmentStatus.UPLOADING:
        assert_transition(shipment.status, ShipmentStatus.UPLOADING)
        shipment.status = ShipmentStatus.UPLOADING
        shipment.version += 1
    await session.commit()
    return api.UploadUrlsResponse(uploads=out)


@router.post("/shipments/{shipment_id}/documents", status_code=201, response_model=api.RegisterDocumentsResponse)
async def register_documents(shipment_id: str, body: api.RegisterDocumentsRequest, p: Principal = Depends(get_principal),
                             session: AsyncSession = Depends(get_session)):
    s = get_settings()
    shipment = await load_shipment(session, p, shipment_id, for_update=True)
    _assert_editable(shipment.status)
    uploads = {u.id: u for u in (await session.execute(select(Upload).where(
        Upload.id.in_(body.upload_ids), Upload.shipment_id == shipment.id, Upload.org_id == p.org_id))).scalars()}
    storage = get_storage()
    docs = []
    for i, upload_id in enumerate(body.upload_ids):
        u = uploads.get(upload_id)
        if u is None:
            raise AppError(ErrorCode.VALIDATION_FAILED, "Unknown upload id.", field=f"upload_ids.{i}")
        if u.document_id:  # registering twice is idempotent
            docs.append(await session.get(Document, u.document_id))
            continue
        size = await storage.size(u.object_name)
        if size is None:
            raise AppError(ErrorCode.VALIDATION_FAILED, f"{u.filename} has not been uploaded yet.",
                           field=f"upload_ids.{i}", details={"upload_id": upload_id})
        if size > s.max_file_bytes:
            raise AppError(ErrorCode.FILE_TOO_LARGE, f"{u.filename} exceeds the size limit.", field=f"upload_ids.{i}")
        blob = await storage.download(u.object_name)
        doc = Document(id=new_id("doc"), shipment_id=shipment.id, org_id=p.org_id, filename=u.filename,
                       gcs_uri=storage.uri(u.object_name), sha256=hashlib.sha256(blob).hexdigest(),
                       content_type=u.content_type, size_bytes=size, status=DocumentStatus.REGISTERED)
        session.add(doc)
        u.document_id = doc.id
        docs.append(doc)
    await session.flush()
    await audit.record(session, org_id=p.org_id, shipment_id=shipment.id, actor_type="USER", actor_id=p.user_id,
                       event_type="documents.registered",
                       payload={"document_ids": [d.id for d in docs], "sha256": [d.sha256 for d in docs]})
    await session.commit()
    for d in docs:
        await session.refresh(d)
    return api.RegisterDocumentsResponse(documents=[document_out(d) for d in docs])


@router.delete("/shipments/{shipment_id}/documents/{document_id}", status_code=204)
async def remove_document(shipment_id: str, document_id: str, p: Principal = Depends(get_principal),
                          session: AsyncSession = Depends(get_session)):
    shipment = await load_shipment(session, p, shipment_id, for_update=True)
    _assert_editable(shipment.status)
    doc = (await session.execute(select(Document).where(
        Document.id == document_id, Document.shipment_id == shipment.id, Document.org_id == p.org_id))).scalar_one_or_none()
    if doc is None:
        raise not_found("Document")
    await session.execute(delete(Upload).where(Upload.document_id == doc.id))
    await session.execute(delete(DocumentPage).where(DocumentPage.document_id == doc.id))
    await session.delete(doc)
    await audit.record(session, org_id=p.org_id, shipment_id=shipment.id, actor_type="USER", actor_id=p.user_id,
                       event_type="document.removed", payload={"document_id": document_id})
    await session.commit()
    return Response(status_code=204)


@router.patch("/shipments/{shipment_id}/documents/{document_id}", response_model=api.DocumentOut)
async def override_document_type(shipment_id: str, document_id: str, body: api.DocumentPatch,
                                 p: Principal = Depends(get_principal), session: AsyncSession = Depends(get_session)):
    shipment = await load_shipment(session, p, shipment_id, for_update=True)
    _assert_editable(shipment.status)
    doc = (await session.execute(select(Document).where(
        Document.id == document_id, Document.shipment_id == shipment.id, Document.org_id == p.org_id))).scalar_one_or_none()
    if doc is None:
        raise not_found("Document")
    previous = doc.doc_type
    doc.doc_type, doc.doc_type_source, doc.doc_type_confidence = body.doc_type.value, DocTypeSource.USER, 1
    await audit.record(session, org_id=p.org_id, shipment_id=shipment.id, actor_type="USER", actor_id=p.user_id,
                       event_type="document.type_overridden",
                       payload={"document_id": doc.id, "from": previous, "to": body.doc_type.value})
    await session.commit()
    await session.refresh(doc)
    return document_out(doc)
