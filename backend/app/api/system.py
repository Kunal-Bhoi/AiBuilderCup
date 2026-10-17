"""Liveness, plus the local signed-URL endpoint used when STORAGE_MODE=local.

Cloud Run's front end reserves some paths ending in "z", so /healthz may be intercepted
there; /health is the dependable alias."""

from fastapi import APIRouter, Query, Request, Response

from app.config import get_settings
from app.errors import AppError, ErrorCode
from app.schemas import api
from app.services.storage import LocalStorage, get_storage

router = APIRouter(tags=["system"])
VERSION = "0.1.0"


def _health() -> api.Health:
    return api.Health(status="ok", service_role=get_settings().service_role, version=VERSION)


@router.get("/healthz", response_model=api.Health)
async def healthz():
    return _health()


@router.get("/health", response_model=api.Health)
async def health():
    return _health()


local_router = APIRouter(include_in_schema=False)


def _local() -> LocalStorage:
    storage = get_storage()
    assert isinstance(storage, LocalStorage)
    return storage


@local_router.put("/local-storage/{object_name:path}")
async def local_put(object_name: str, request: Request, exp: int = Query(...), sig: str = Query(...)):
    storage = _local()
    if not storage.verify("PUT", object_name, exp, sig):
        raise AppError(ErrorCode.UNAUTHENTICATED, "The upload URL is invalid or has expired.")
    body = await request.body()
    if len(body) > get_settings().max_file_bytes:
        raise AppError(ErrorCode.FILE_TOO_LARGE, "The file exceeds the size limit.")
    await storage.upload(object_name, body, request.headers.get("Content-Type", "application/octet-stream"))
    return Response(status_code=200)


@local_router.get("/local-storage/{object_name:path}")
async def local_get(object_name: str, exp: int = Query(...), sig: str = Query(...)):
    storage = _local()
    if not storage.verify("GET", object_name, exp, sig):
        raise AppError(ErrorCode.UNAUTHENTICATED, "The URL is invalid or has expired.")
    if await storage.size(object_name) is None:
        raise AppError(ErrorCode.SHIPMENT_NOT_FOUND, "Not found.")
    data = await storage.download(object_name)
    media = "image/png" if object_name.endswith(".png") else "application/pdf" if object_name.endswith(".pdf") else "application/octet-stream"
    return Response(data, media_type=media, headers={"Cache-Control": "private, max-age=300"})
