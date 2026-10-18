"""Shared by scripts/vertex_smoke.py and scripts/evaluate.py: run the AI client over files on disk
exactly the way the worker does, without a database. Ingest renders pages with the production
code path (documents_io.ingest_bytes) and stores them in local storage, so in-process clients
read them through PageRef.storage_uri just as they do in the worker."""

import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("STORAGE_MODE", "local")
os.environ.setdefault("LOCAL_STORAGE_DIR", tempfile.mkdtemp(prefix="tradecheck-harness-"))

from app.config import get_settings  # noqa: E402
from app.domain.enums import CellStatus, DocType  # noqa: E402
from app.domain.fields import applicable_fields  # noqa: E402
from app.schemas import ai  # noqa: E402
from app.services.ai_client import cost_usd, get_ai_client  # noqa: E402
from app.services.documents_io import IngestFailure, ingest_bytes  # noqa: E402
from app.services.storage import get_storage  # noqa: E402

AGREE_FAMILY = {"AGREE", "AGREE_AT_HS_ROOT", "TOLERANCE_MATCH"}


@dataclass
class LoadedDoc:
    document_id: str
    filename: str
    pages: list[ai.PageRef] = field(default_factory=list)
    text_layer: str | None = None
    error: str | None = None


async def load(path: Path, document_id: str) -> LoadedDoc:
    s = get_settings()
    try:
        out = ingest_bytes(path.read_bytes(), dpi=s.render_dpi, max_px=s.render_max_px, max_pages=s.max_pages_per_document)
    except IngestFailure as exc:
        return LoadedDoc(document_id, path.name, error=exc.code.value)
    storage = get_storage()
    refs = []
    for p in out.pages:
        uri = await storage.upload(f"harness/{document_id}/{p.page:04d}.png", p.png, "image/png")
        url, _ = await storage.signed_get_url(storage.object_name(uri), 900)
        refs.append(ai.PageRef(page=p.page, image_url=url, width_px=p.width_px, height_px=p.height_px, storage_uri=uri))
    return LoadedDoc(document_id, path.name, refs, out.text_layer)


def cells(resp: ai.ExtractResponse, doc_type: str) -> list[ai.ReconcileFieldIn]:
    """The worker's extract-stage rules (app/worker/stages/extract.py), without the ORM."""
    floor = get_settings().confidence_floor
    wanted = applicable_fields(doc_type)
    rows: dict[str, ai.ReconcileFieldIn] = {}
    for f in resp.fields:
        if f.field_key in wanted and f.field_key not in rows and f.raw_value:
            conf = min(1.0, max(0.0, f.confidence))
            rows[f.field_key] = ai.ReconcileFieldIn(
                document_id=resp.document_id, field_key=f.field_key, raw_value=f.raw_value, normalized_value=f.normalized_value,
                normalized_unit=f.normalized_unit, confidence=conf,
                cell_status=CellStatus.PRESENT if conf >= floor else CellStatus.LOW_CONFIDENCE)
    for u in resp.unreadable_fields:
        if u.field_key in wanted and u.field_key not in rows:
            rows[u.field_key] = ai.ReconcileFieldIn(
                document_id=resp.document_id, field_key=u.field_key, raw_value=None, normalized_value=None, normalized_unit=None,
                confidence=0.0, cell_status=CellStatus.ABSENT if u.reason == "FIELD_ABSENT" else CellStatus.UNREADABLE)
    for key in wanted:
        rows.setdefault(key, ai.ReconcileFieldIn(document_id=resp.document_id, field_key=key, raw_value=None, normalized_value=None,
                                                 normalized_unit=None, confidence=0.0, cell_status=CellStatus.ABSENT))
    return list(rows.values())


def primaries(types: dict[str, str], order: list[str]) -> set[str]:
    """The worker keeps the latest upload of each document type and supersedes the rest."""
    keep: dict[str, str] = {}
    for doc_id in order:
        t = types[doc_id]
        if t != DocType.UNKNOWN.value:
            keep[t] = doc_id
    return set(keep.values())


__all__ = ["AGREE_FAMILY", "LoadedDoc", "cells", "cost_usd", "get_ai_client", "get_settings", "load", "primaries"]
