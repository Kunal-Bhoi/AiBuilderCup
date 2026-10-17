"""Page renders and provenance snippets (§5.1, FRONTEND-SPEC §11.4).

/image returns JSON with a 5-minute signed URL. /crop returns image/png directly; it needs the
Bearer token, so the frontend fetches it as a blob. Pages were rendered once at ingest."""

import asyncio
from collections import OrderedDict

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import load_document
from app.auth import Principal, get_principal
from app.config import get_settings
from app.db.engine import get_session
from app.db.models import DocumentPage
from app.errors import AppError, ErrorCode, not_found
from app.schemas import api
from app.services.documents_io import crop_png
from app.services.storage import get_storage

router = APIRouter(tags=["pages"])

_page_cache: OrderedDict[str, bytes] = OrderedDict()
_CACHE_SIZE = 64


async def _page_png(uri: str) -> bytes:
    if uri in _page_cache:
        _page_cache.move_to_end(uri)
        return _page_cache[uri]
    storage = get_storage()
    data = await storage.download(storage.object_name(uri))
    _page_cache[uri] = data
    if len(_page_cache) > _CACHE_SIZE:
        _page_cache.popitem(last=False)
    return data


async def _page(session: AsyncSession, p: Principal, document_id: str, page: int) -> DocumentPage:
    await load_document(session, p, document_id)
    row = (await session.execute(select(DocumentPage).where(
        DocumentPage.document_id == document_id, DocumentPage.page == page))).scalar_one_or_none()
    if row is None:
        raise not_found("Page")
    return row


@router.get("/documents/{document_id}/pages/{page}/image", response_model=api.PageImageOut)
async def page_image(document_id: str, page: int, p: Principal = Depends(get_principal),
                     session: AsyncSession = Depends(get_session)):
    row = await _page(session, p, document_id, page)
    storage = get_storage()
    url, expires = await storage.signed_get_url(storage.object_name(row.gcs_uri), get_settings().read_url_ttl_seconds)
    return api.PageImageOut(document_id=document_id, page=page, url=url, expires_at=expires,
                            width_px=row.width_px, height_px=row.height_px)


def _parse_bbox(raw: str) -> tuple[float, float, float, float]:
    try:
        x0, y0, x1, y1 = (float(v) for v in raw.split(","))
    except ValueError:
        raise AppError(ErrorCode.VALIDATION_FAILED, "bbox must be four comma-separated numbers.", field="bbox")
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise AppError(ErrorCode.VALIDATION_FAILED, "bbox must be normalised [x0,y0,x1,y1] with 0 <= x0 < x1 <= 1.",
                       field="bbox")
    return x0, y0, x1, y1


@router.get("/documents/{document_id}/pages/{page}/crop", response_class=Response,
            responses={200: {"content": {"image/png": {}}}})
async def page_crop(document_id: str, page: int, bbox: str = Query(..., description="x0,y0,x1,y1 normalised 0..1"),
                    p: Principal = Depends(get_principal), session: AsyncSession = Depends(get_session)):
    box = _parse_bbox(bbox)
    row = await _page(session, p, document_id, page)
    png = await asyncio.to_thread(crop_png, await _page_png(row.gcs_uri), box)
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=300"})
