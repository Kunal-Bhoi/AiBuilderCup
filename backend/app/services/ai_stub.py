"""In-process stand-in for ai-service (AI_MODE=stub, §8).

It is deliberately honest about being a stub: model name "stub", no LLM, no vision.
  classify   title / filename keywords
  extract    parses "Label: value" lines from the PDF text layer (works on samples/*.pdf)
  reconcile  app/services/rules.py, the same deterministic reconciler vertex mode uses
  explain    majority-vote assessment, labelled LOW/MODERATE confidence

Fixture overrides: contracts/fixtures/ai/extract/<filename stem>.json replaces the parsed
extraction for that file (used for scans with no text layer)."""

import json
import re
from collections import defaultdict
from pathlib import Path

from app.config import get_settings
from app.domain.enums import DocType
from app.domain.fields import FIELD_LABELS, applicable_fields
from app.schemas import ai
from app.services.rules import LABEL_TO_FIELD, normalise, reconcile  # noqa: F401  (re-exported)

STUB_USAGE = dict(model="stub", model_version="0", latency_ms=1)

# ---------------------------------------------------------------- classify

_TYPE_KEYWORDS: list[tuple[str, DocType]] = [
    ("commercial invoice", DocType.COMMERCIAL_INVOICE),
    ("packing list", DocType.PACKING_LIST),
    ("bill of lading", DocType.BILL_OF_LADING),
    ("air waybill", DocType.AIR_WAYBILL),
    ("certificate of origin", DocType.CERTIFICATE_OF_ORIGIN),
    ("purchase order", DocType.PURCHASE_ORDER),
    ("customs declaration", DocType.CUSTOMS_DECLARATION),
    ("bill of entry", DocType.CUSTOMS_DECLARATION),
    ("insurance certificate", DocType.INSURANCE_CERTIFICATE),
    ("invoice", DocType.COMMERCIAL_INVOICE),
    ("packing", DocType.PACKING_LIST),
    ("lading", DocType.BILL_OF_LADING),
    ("bl", DocType.BILL_OF_LADING),
    ("awb", DocType.AIR_WAYBILL),
    ("origin", DocType.CERTIFICATE_OF_ORIGIN),
    ("coo", DocType.CERTIFICATE_OF_ORIGIN),
    ("po", DocType.PURCHASE_ORDER),
    ("declaration", DocType.CUSTOMS_DECLARATION),
]


def _guess_type(filename: str, text: str | None) -> tuple[DocType, float]:
    title = (text or "").strip().splitlines()[0].casefold() if (text or "").strip() else ""
    for kw, t in _TYPE_KEYWORDS:
        if " " in kw and kw in title:
            return t, 0.97
    stem = re.sub(r"[^a-z0-9]+", " ", Path(filename).stem.casefold())
    tokens = set(stem.split())
    for kw, t in _TYPE_KEYWORDS:
        if (" " in kw and kw in stem) or kw in tokens:
            return t, 0.8
    return DocType.UNKNOWN, 0.2


def classify(req: ai.ClassifyRequest) -> ai.ClassifyResponse:
    docs = []
    for d in req.documents:
        t, conf = _guess_type(d.filename, d.text_layer_excerpt)
        docs.append(ai.ClassifiedDocument(document_id=d.document_id, doc_type=t.value, confidence=conf))
    by_type: dict[str, list[str]] = defaultdict(list)
    for d in docs:
        if d.doc_type != DocType.UNKNOWN:
            by_type[d.doc_type].append(d.document_id)
    duplicates = [
        ai.DuplicateGroup(doc_type=t, document_ids=ids, primary_document_id=ids[-1])
        for t, ids in by_type.items()
        if len(ids) > 1
    ]
    return ai.ClassifyResponse(
        request_id=req.request_id,
        documents=docs,
        duplicates=duplicates,
        usage=ai.Usage(prompt_version="stub.classify.v1", **STUB_USAGE),
    )

# ---------------------------------------------------------------- extract

_LINE_H = 0.0215  # samples/generate.py layout: 18pt leading on an 842pt page
_TOP = 0.0855


def _load_override(filename: str | None) -> dict | None:
    if not filename:
        return None
    p = Path(get_settings().ai_stub_fixtures_dir) / "extract" / f"{Path(filename).stem}.json"
    return json.loads(p.read_text()) if p.exists() else None


def extract(req: ai.ExtractRequest, filename: str | None = None) -> ai.ExtractResponse:
    usage = ai.Usage(prompt_version=f"stub.extract.{req.doc_type.lower()}.v1",
                     input_tokens=len(req.text_layer or "") // 4, output_tokens=200, **STUB_USAGE)
    override = _load_override(filename)
    if override is not None:
        resp = ai.ExtractResponse.model_validate({**override, "request_id": req.request_id, "document_id": req.document_id})
        resp.usage = usage
        return resp

    wanted = set(applicable_fields(req.doc_type))
    found: dict[str, ai.ExtractedFieldOut] = {}
    unreadable: list[ai.UnreadableField] = []
    lines = (req.text_layer or "").splitlines()
    for i, line in enumerate(lines):
        if ":" not in line:
            continue
        label, value = line.split(":", 1)
        key = LABEL_TO_FIELD.get(label.strip().casefold())
        value = value.strip()
        if not key or key not in wanted or key in found:
            continue
        if not value or value.casefold() in {"[illegible]", "illegible", "?"}:
            unreadable.append(ai.UnreadableField(field_key=key, reason="REGION_ILLEGIBLE"))
            continue
        norm, unit = normalise(key, value)
        y0 = min(0.98, _TOP + i * _LINE_H)
        found[key] = ai.ExtractedFieldOut(
            field_key=key,
            raw_value=value,
            normalized_value=norm,
            normalized_unit=unit,
            confidence=0.93 if norm is not None else 0.4,
            provenance=ai.Provenance(page=1, bbox=[0.085, round(y0 - 0.014, 4), 0.9, round(y0 + 0.005, 4)]),
        )
        # "Quantity: 100 PCS" also carries the unit of measure.
        if key == "quantity" and unit and "quantity_uom" in wanted and "quantity_uom" not in found:
            found["quantity_uom"] = ai.ExtractedFieldOut(
                field_key="quantity_uom", raw_value=value.split()[-1], normalized_value=unit, confidence=0.9,
                provenance=found[key].provenance,
            )
    seen = set(found) | {u.field_key for u in unreadable}
    unreadable += [ai.UnreadableField(field_key=k, reason="FIELD_ABSENT") for k in sorted(wanted - seen)]
    return ai.ExtractResponse(
        request_id=req.request_id, document_id=req.document_id, fields=list(found.values()),
        unreadable_fields=unreadable, usage=usage,
        warnings=[] if req.text_layer else ["NO_TEXT_LAYER_STUB_CANNOT_READ_IMAGES"],
    )



# ---------------------------------------------------------------- explain

def explain(req: ai.ExplainRequest) -> ai.ExplainResponse:
    usage = ai.Usage(prompt_version="stub.explain.v1", **STUB_USAGE)
    groups: dict[str, list[ai.ExplainValueIn]] = defaultdict(list)
    for v in req.values:
        groups[v.normalized_value or ""].append(v)
    ranked = sorted(groups.values(), key=len, reverse=True)
    label = FIELD_LABELS.get(req.field_key, req.field_key)
    if len(ranked) < 2 or len(ranked[0]) == len(ranked[1]):
        return ai.ExplainResponse(
            request_id=req.request_id, usage=usage, assessment_confidence="LOW",
            explanation=f"The documents split evenly on {label.lower()}; there is no basis to say which is wrong. Check with the shipper.")
    majority, minority = ranked[0], [v for g in ranked[1:] for v in g]
    wrong = minority[0]
    names = ", ".join(v.doc_type.replace("_", " ").lower() for v in majority)
    return ai.ExplainResponse(
        request_id=req.request_id, usage=usage,
        assessment_confidence="MODERATE" if len(majority) >= 2 else "LOW",
        likely_incorrect_document_id=wrong.document_id,
        suggested_value=majority[0].raw_value,
        explanation=(f"The {wrong.doc_type.replace('_', ' ').lower()} states {label.lower()} as "
                     f"\"{wrong.raw_value}\", while the {names} agree on \"{majority[0].raw_value}\". "
                     f"The outlier is the likely error. This is a majority-vote assessment, not proof."),
    )
