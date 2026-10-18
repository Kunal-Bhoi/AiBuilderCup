"""AI_MODE=vertex: Gemini on Vertex AI, in-process inside the worker. Same interface as the stub
and the HTTP client, so no stage, table, endpoint or screen changes with the mode.

  classify   Gemini, page 1 + text excerpt, one call per document (cheap model tier)
  extract    Gemini, one call per document, every page as a separately labelled image so the
             page index is known by construction (AI-SPEC §11.1), boxes converted once here
  reconcile  NO model: app/services/rules.py (principle 2.6, the comparison is code)
  explain    Gemini, only the conflicting values and agreed related fields (§14)
"""

import asyncio
import re
import unicodedata

import httpx
from pydantic import BaseModel

from app import prompts
from app.config import get_settings
from app.domain.enums import DocType
from app.domain.fields import applicable_fields
from app.errors import AppError, ErrorCode
from app.logging import log
from app.schemas import ai
from app.services import llm, rules
from app.services.storage import get_storage

TEXT_LAYER_LIMIT = 30_000
CLASSIFY_EXCERPT_LIMIT = 2_000
CLASSIFY_CONCURRENCY = 4
_NULL_REASON = {"field_absent": "FIELD_ABSENT", "region_illegible": "REGION_ILLEGIBLE", "ambiguous": "AMBIGUOUS"}


# ---------------------------------------------------------------- model-facing schemas

class _Classification(BaseModel):
    doc_type: str
    confidence: float
    evidence: str | None = None


class _Field(BaseModel):
    name: str
    value: str | None = None
    page: int | None = None
    box_2d: list[float] | None = None
    raw_text: str | None = None
    confidence: float = 0.0
    null_reason: str | None = None


class _Extraction(BaseModel):
    fields: list[_Field]


class _Explanation(BaseModel):
    explanation: str | None = None
    likely_incorrect_document_id: str | None = None
    suggested_value: str | None = None
    assessment_confidence: str | None = None


def _nullable(schema: dict) -> dict:
    return {**schema, "nullable": True}


def classify_schema() -> dict:
    return {"type": "object", "required": ["doc_type", "confidence", "evidence"], "properties": {
        "doc_type": {"type": "string", "enum": [t.value for t in DocType]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "evidence": _nullable({"type": "string"}),
    }}


def extract_schema(field_keys: list[str]) -> dict:
    row = {"type": "object", "required": ["name", "value", "null_reason", "page", "box_2d", "raw_text", "confidence"], "properties": {
        "name": {"type": "string", "enum": field_keys},
        "value": _nullable({"type": "string"}),
        "null_reason": _nullable({"type": "string", "enum": list(_NULL_REASON)}),
        "page": _nullable({"type": "integer"}),
        "box_2d": _nullable({"type": "array", "items": {"type": "integer"}, "minItems": 4, "maxItems": 4,
                             "description": "[ymin, xmin, ymax, xmax] normalised 0-1000, origin top-left"}),
        "raw_text": _nullable({"type": "string"}),
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    }}
    return {"type": "object", "required": ["fields"], "properties": {"fields": {"type": "array", "items": row}}}


def explain_schema(document_ids: list[str]) -> dict:
    return {"type": "object", "required": ["explanation", "likely_incorrect_document_id", "suggested_value", "assessment_confidence"],
            "properties": {
                "explanation": {"type": "string"},
                "likely_incorrect_document_id": _nullable({"type": "string", "enum": document_ids}),
                "suggested_value": _nullable({"type": "string"}),
                "assessment_confidence": {"type": "string", "enum": ["HIGH", "MODERATE", "LOW"]},
            }}


# ---------------------------------------------------------------- provenance and confidence

def to_canonical_bbox(box_2d: list[float] | None) -> list[float] | None:
    """Gemini [ymin, xmin, ymax, xmax] on 0..1000  ->  canonical [x0, y0, x1, y1] on 0..1.

    Y FIRST on the way in, X FIRST on the way out (AI-SPEC Appendix C). This is the only place
    in the system that knows the model's native format. Out-of-range values are clamped, never
    dropped; a box with no area is reported as no box."""
    if not box_2d or len(box_2d) != 4:
        return None
    try:
        y_min, x_min, y_max, x_max = (max(0.0, min(1.0, float(v) / 1000.0)) for v in box_2d)
    except (TypeError, ValueError):
        return None
    x0, x1 = sorted((x_min, x_max))
    y0, y1 = sorted((y_min, y_max))
    if x1 - x0 <= 0 or y1 - y0 <= 0:
        return None
    return [round(x0, 5), round(y0, 5), round(x1, 5), round(y1, 5)]


def _canon(text: str) -> str:
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", text).casefold())


def text_layer_agreement(text_index: str | None, raw_text: str | None, value: str) -> bool | None:
    """Does the page's embedded text contain what the model claims to have read? None = no text layer."""
    if text_index is None:
        return None
    for candidate in (value, raw_text):
        c = _canon(candidate or "")
        if c and c in text_index:
            return True
    return False


def blended_confidence(self_report: float, text_agrees: bool | None, format_ok: bool) -> float:
    """AI-SPEC §11.3: a self-reported confidence correlates poorly with correctness, so combine it
    with two cheap, independent signals. A value missing from an existing text layer is a strong
    hallucination signal. The weights are a starting point to be calibrated by scripts/evaluate.py."""
    sr = max(0.0, min(1.0, float(self_report)))
    fmt = 1.0 if format_ok else 0.0
    if text_agrees is None:
        score = 0.75 * sr + 0.25 * fmt
    else:
        score = 0.5 * sr + 0.3 * (1.0 if text_agrees else 0.0) + 0.2 * fmt
    return round(score, 3)


def to_extract_response(req: ai.ExtractRequest, out: _Extraction, usage: ai.Usage, sent_pages: list[int]) -> ai.ExtractResponse:
    """Model rows -> the frozen ExtractResponse. Pure: no I/O, so it is unit-tested directly."""
    wanted = set(applicable_fields(req.doc_type))
    text_index = _canon(req.text_layer) if req.text_layer else None
    fields: dict[str, ai.ExtractedFieldOut] = {}
    unreadable: dict[str, str] = {}
    warnings: set[str] = set()
    for f in out.fields:
        if f.name not in wanted:
            log.warning("discarded_field", extra={"field_key": f.name, "document_id": req.document_id})
            continue
        if f.name in fields or f.name in unreadable:
            continue
        value = (f.value or "").strip()
        if not value:
            unreadable[f.name] = _NULL_REASON.get(f.null_reason or "", "FIELD_ABSENT")
            continue
        page = f.page if f.page in sent_pages else None
        if page is None:
            warnings.add("PROVENANCE_PAGE_UNVERIFIED")
        bbox = to_canonical_bbox(f.box_2d) if page is not None else None
        normalized, unit = rules.normalise(f.name, value)
        fields[f.name] = ai.ExtractedFieldOut(
            field_key=f.name, raw_value=value, normalized_value=normalized, normalized_unit=unit,
            confidence=blended_confidence(f.confidence, text_layer_agreement(text_index, f.raw_text, value), normalized is not None),
            provenance=ai.Provenance(page=page, bbox=bbox),
        )
    return ai.ExtractResponse(
        request_id=req.request_id, document_id=req.document_id, fields=list(fields.values()),
        unreadable_fields=[ai.UnreadableField(field_key=k, reason=r) for k, r in unreadable.items()],
        usage=usage, warnings=sorted(warnings),
    )


# ---------------------------------------------------------------- page images

async def page_bytes(ref: ai.PageRef) -> bytes:
    """Read a rendered page. In-process the worker passes the storage URI, so no signed URL round
    trip is needed and it works identically on local storage and GCS."""
    try:
        if ref.storage_uri:
            storage = get_storage()
            return await storage.download(storage.object_name(ref.storage_uri))
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(ref.image_url)
            r.raise_for_status()
            return r.content
    except Exception as exc:
        raise AppError(ErrorCode.INTERNAL, "A rendered page could not be read from storage.") from exc


def _sum_usage(usages: list[ai.Usage]) -> ai.Usage | None:
    if not usages:
        return None
    first = usages[0]
    return ai.Usage(input_tokens=sum(u.input_tokens for u in usages), output_tokens=sum(u.output_tokens for u in usages),
                    model=first.model, model_version=first.model_version, prompt_version=first.prompt_version,
                    latency_ms=max(u.latency_ms for u in usages))


# ---------------------------------------------------------------- the client

class VertexAIClient:
    async def classify(self, req: ai.ClassifyRequest) -> ai.ClassifyResponse:
        s = get_settings()
        model = s.gemini_model_classify or s.gemini_model
        sem = asyncio.Semaphore(CLASSIFY_CONCURRENCY)

        async def one(d: ai.ClassifyDocumentIn) -> tuple[ai.ClassifiedDocument, ai.Usage]:
            async with sem:
                version, text = prompts.classify(d.filename, (d.text_layer_excerpt or "")[:CLASSIFY_EXCERPT_LIMIT] or None)
                parts: list[llm.Part] = [llm.Text(text)]
                if d.pages:
                    parts += [llm.Text(f"Page {d.pages[0].page}"), llm.Image(await page_bytes(d.pages[0]))]
                out, usage = await llm.generate_json(stage="classify", model=model, prompt_version=version, system=prompts.SYSTEM,
                                                     parts=parts, schema=classify_schema(), parse=_Classification.model_validate)
                doc_type = out.doc_type if out.doc_type in DocType.__members__ else DocType.UNKNOWN.value
                return ai.ClassifiedDocument(document_id=d.document_id, doc_type=doc_type,
                                             confidence=max(0.0, min(1.0, out.confidence))), usage

        results = await asyncio.gather(*(one(d) for d in req.documents), return_exceptions=True)
        docs, usages, errors = [], [], []
        for d, r in zip(req.documents, results, strict=True):
            if isinstance(r, BaseException):
                if not isinstance(r, AppError):
                    raise r
                errors.append(r)
                # Unclassified is honest: the document is listed as unchecked and the user can set its type.
                docs.append(ai.ClassifiedDocument(document_id=d.document_id, doc_type=DocType.UNKNOWN.value, confidence=0.0))
                log.warning("classify_failed", extra={"document_id": d.document_id, "error_code": r.code.value})
                continue
            docs.append(r[0])
            usages.append(r[1])
        retryable = [e for e in errors if e.retryable]
        if retryable:
            # A transient failure must not become a permanent UNKNOWN: classification is page 1 on the
            # cheap tier, so re-running the stage is cheap and the queue retries with backoff. Only a
            # non-retryable failure (e.g. a safety block) is recorded as UNKNOWN for the user to set.
            raise retryable[0]
        return ai.ClassifyResponse(request_id=req.request_id, documents=docs, usage=_sum_usage(usages))

    async def extract(self, req: ai.ExtractRequest, filename: str | None = None) -> ai.ExtractResponse:
        s = get_settings()
        field_keys = applicable_fields(req.doc_type)
        if not field_keys or not req.pages:
            return ai.ExtractResponse(request_id=req.request_id, document_id=req.document_id)
        pages = req.pages[: req.options.max_pages]
        images = await asyncio.gather(*(page_bytes(p) for p in pages))
        version, text = prompts.extract(req.doc_type, field_keys, [p.page for p in pages])
        parts: list[llm.Part] = [llm.Text(text)]
        for p, data in zip(pages, images, strict=True):
            parts += [llm.Text(f"Page {p.page}"), llm.Image(data)]
        if req.text_layer:
            parts.append(llm.Text("Embedded text layer of this document, in reading order. It may be incomplete or "
                                  "out of order. Use it to read characters precisely, but take page and box_2d from "
                                  "the images.\n" + req.text_layer[:TEXT_LAYER_LIMIT]))
        out, usage = await llm.generate_json(stage="extract", model=s.gemini_model, prompt_version=version, system=prompts.SYSTEM,
                                             parts=parts, schema=extract_schema(field_keys), parse=_Extraction.model_validate)
        return to_extract_response(req, out, usage, [p.page for p in pages])

    async def reconcile(self, req: ai.ReconcileRequest) -> ai.ReconcileResponse:
        return rules.reconcile(req)

    async def explain(self, req: ai.ExplainRequest) -> ai.ExplainResponse:
        s = get_settings()
        ids = list(dict.fromkeys(v.document_id for v in req.values))
        version, text = prompts.explain(req)
        out, usage = await llm.generate_json(stage="explain", model=s.gemini_model, prompt_version=version, system=prompts.SYSTEM,
                                             parts=[llm.Text(text)], schema=explain_schema(ids), parse=_Explanation.model_validate)
        confidence = (out.assessment_confidence or "").upper()
        return ai.ExplainResponse(
            request_id=req.request_id, usage=usage,
            explanation=(out.explanation or "").strip() or None,
            likely_incorrect_document_id=out.likely_incorrect_document_id if out.likely_incorrect_document_id in ids else None,
            suggested_value=(out.suggested_value or "").strip() or None,
            assessment_confidence=confidence if confidence in ("HIGH", "MODERATE", "LOW") else None,
        )
