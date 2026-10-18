"""AI_MODE=vertex without GCP: the model call is replaced by a fake, everything around it is real.
Covers the bbox conversion (AI-SPEC Appendix C), confidence blending, the response mapping, the
explainer's id guard, classification fallbacks, error mapping and schema translation."""

import asyncio

import httpx
import pytest

from app.domain.fields import CANONICAL_FIELDS, applicable_fields
from app.errors import AppError, ErrorCode
from app.prompts import FIELD_HINTS
from app.schemas import ai
from app.services import ai_vertex, llm
from app.services.ai_vertex import (
    VertexAIClient,
    _Extraction,
    _Field,
    blended_confidence,
    text_layer_agreement,
    to_canonical_bbox,
    to_extract_response,
)

USAGE = ai.Usage(input_tokens=1000, output_tokens=200, model="gemini-test", model_version="gemini-test-001",
                 prompt_version="extract.packing_list.v1", latency_ms=5)


# ---------------------------------------------------------------- Appendix C: bounding boxes

def test_bbox_conversion_is_not_transposed():
    # A wide, short box near the top of the page. Gemini order: ymin=100, xmin=200, ymax=150, xmax=900
    out = to_canonical_bbox([100, 200, 150, 900])
    assert out == [0.2, 0.1, 0.9, 0.15]
    width, height = out[2] - out[0], out[3] - out[1]
    assert width > height, "Transposed: a wide box came out tall."


@pytest.mark.parametrize("box,expected", [
    ([-20, 50, 1200, 400], [0.05, 0.0, 0.4, 1.0]),   # out of range is clamped, never dropped
    ([150, 900, 100, 200], [0.2, 0.1, 0.9, 0.15]),   # corners given in the wrong order are reordered
    ([100, 200, 100, 900], None),                     # no area
    ([1, 2, 3], None),
    (None, None),
])
def test_bbox_edge_cases(box, expected):
    assert to_canonical_bbox(box) == expected


# ---------------------------------------------------------------- confidence (AI-SPEC §11.3)

def test_value_missing_from_the_text_layer_drops_below_the_floor():
    assert blended_confidence(0.95, True, True) > 0.9
    assert blended_confidence(0.95, False, False) < 0.55   # likely hallucination -> LOW_CONFIDENCE
    assert blended_confidence(0.95, None, True) == pytest.approx(0.9625, abs=1e-3)  # scans: no text signal


def test_text_layer_agreement_ignores_spacing_and_punctuation():
    index = "".join(ch for ch in "invoicenumberinv20260141".casefold())
    assert text_layer_agreement(index, None, "INV-2026-0141") is True
    assert text_layer_agreement(index, None, "INV-2026-9999") is False
    assert text_layer_agreement(None, None, "anything") is None


# ---------------------------------------------------------------- response mapping

def _req(doc_type="PACKING_LIST", text_layer="PACKING LIST\nQuantity: 95 PCS\nGross weight: 48 kg"):
    return ai.ExtractRequest(request_id="r", document_id="doc_1", doc_type=doc_type, text_layer=text_layer,
                             pages=[ai.PageRef(page=1, image_url="x", width_px=10, height_px=10)])


def test_mapping_converts_boxes_normalises_and_guards_keys():
    out = _Extraction(fields=[
        _Field(name="quantity", value="95 PCS", page=1, box_2d=[100, 200, 150, 900], raw_text="Quantity: 95 PCS", confidence=0.9),
        _Field(name="quantity", value="100 PCS", page=1, box_2d=[0, 0, 10, 10], confidence=0.9),   # duplicate: first wins
        _Field(name="invoice_total", value="USD 1.00", page=1, confidence=0.9),                   # not applicable here
        _Field(name="made_up_field", value="x", page=1, confidence=0.9),                          # invented key
        _Field(name="gross_weight", value="48 kg", page=7, box_2d=[1, 2, 3, 4], confidence=0.9),  # page never sent
        _Field(name="net_weight", value=None, null_reason="region_illegible", confidence=0.0),
        _Field(name="package_count", value="  ", null_reason=None, confidence=0.0),
    ])
    resp = to_extract_response(_req(), out, USAGE, sent_pages=[1])
    by_key = {f.field_key: f for f in resp.fields}
    assert set(by_key) == {"quantity", "gross_weight"}
    q = by_key["quantity"]
    assert (q.raw_value, q.normalized_value, q.normalized_unit) == ("95 PCS", "95", "PCS")
    assert q.provenance.page == 1 and q.provenance.bbox == [0.2, 0.1, 0.9, 0.15]
    assert q.confidence > 0.9
    g = by_key["gross_weight"]
    assert g.provenance.page is None and g.provenance.bbox is None  # an unverifiable page is never trusted
    assert "PROVENANCE_PAGE_UNVERIFIED" in resp.warnings
    assert {u.field_key: u.reason for u in resp.unreadable_fields} == {"net_weight": "REGION_ILLEGIBLE",
                                                                       "package_count": "FIELD_ABSENT"}
    assert resp.usage.model == "gemini-test"


def test_every_canonical_field_has_a_prompt_hint():
    assert set(FIELD_HINTS) == set(CANONICAL_FIELDS)


# ---------------------------------------------------------------- the client with a fake model

class FakeLLM:
    """Stands in for llm.generate_json. Records each call and answers from a per-stage script."""

    def __init__(self, answers):
        self.answers, self.calls = answers, []

    async def __call__(self, *, stage, model, prompt_version, system, parts, schema, parse):
        self.calls.append({"stage": stage, "model": model, "prompt_version": prompt_version, "parts": parts, "schema": schema})
        answer = self.answers[stage]
        if isinstance(answer, Exception):
            raise answer
        data = answer(parts, schema) if callable(answer) else answer
        return parse(data), ai.Usage(input_tokens=10, output_tokens=5, model=model, model_version=model,
                                     prompt_version=prompt_version, latency_ms=1)


@pytest.fixture
def page_png(monkeypatch):
    async def fake_page_bytes(ref):
        return b"\x89PNG fake"
    monkeypatch.setattr(ai_vertex, "page_bytes", fake_page_bytes)


def run(coro):
    return asyncio.run(coro)


def test_extract_sends_labelled_pages_and_only_applicable_fields(monkeypatch, page_png):
    fake = FakeLLM({"extract": {"fields": [{"name": "quantity", "value": "95 PCS", "page": 2, "box_2d": [100, 200, 150, 900],
                                            "raw_text": "Quantity: 95 PCS", "confidence": 0.9, "null_reason": None}]}})
    monkeypatch.setattr(llm, "generate_json", fake)
    req = ai.ExtractRequest(request_id="r", document_id="d", doc_type="PACKING_LIST", text_layer="Quantity: 95 PCS",
                            pages=[ai.PageRef(page=n, image_url="x", width_px=1, height_px=1) for n in (1, 2)])
    resp = run(VertexAIClient().extract(req))
    call = fake.calls[0]
    labels = [p.text for p in call["parts"] if isinstance(p, llm.Text) and p.text.startswith("Page ")]
    assert labels == ["Page 1", "Page 2"]
    assert sum(isinstance(p, llm.Image) for p in call["parts"]) == 2
    enum = call["schema"]["properties"]["fields"]["items"]["properties"]["name"]["enum"]
    assert enum == applicable_fields("PACKING_LIST")
    assert call["prompt_version"] == "extract.packing_list.v1"
    assert resp.fields[0].provenance.page == 2


def test_explainer_cannot_blame_a_document_it_was_not_shown(monkeypatch):
    fake = FakeLLM({"explain": {"explanation": "The packing list is the outlier.", "likely_incorrect_document_id": "doc_other",
                                "suggested_value": "100 PCS", "assessment_confidence": "moderate"}})
    monkeypatch.setattr(llm, "generate_json", fake)
    req = ai.ExplainRequest(request_id="r", shipment_id="s", field_key="quantity", verdict="DISAGREE", values=[
        ai.ExplainValueIn(document_id="doc_a", doc_type="COMMERCIAL_INVOICE", raw_value="100 PCS", normalized_value="100", confidence=0.9),
        ai.ExplainValueIn(document_id="doc_b", doc_type="PACKING_LIST", raw_value="95 PCS", normalized_value="95", confidence=0.9)])
    resp = run(VertexAIClient().explain(req))
    assert resp.likely_incorrect_document_id is None
    assert resp.assessment_confidence == "MODERATE"
    assert fake.calls[0]["schema"]["properties"]["likely_incorrect_document_id"]["enum"] == ["doc_a", "doc_b"]


def _classify_req(n=2):
    return ai.ClassifyRequest(request_id="r", documents=[
        ai.ClassifyDocumentIn(document_id=f"doc_{i}", filename=f"f{i}.pdf", page_count=1,
                              pages=[ai.PageRef(page=1, image_url="x", width_px=1, height_px=1)]) for i in range(n)])


def test_classify_maps_unknown_types_and_failures_to_unknown(monkeypatch, page_png):
    answers = iter([{"doc_type": "NOT_A_TYPE", "confidence": 0.9, "evidence": None},
                    AppError(ErrorCode.MODEL_SAFETY_BLOCK, "blocked")])

    async def fake(**kw):
        a = next(answers)
        if isinstance(a, Exception):
            raise a
        return kw["parse"](a), ai.Usage(model="m", prompt_version="classify.v1")
    monkeypatch.setattr(llm, "generate_json", fake)
    resp = run(VertexAIClient().classify(_classify_req()))
    assert [d.doc_type for d in resp.documents] == ["UNKNOWN", "UNKNOWN"]


def test_classify_retries_when_every_document_failed_transiently(monkeypatch, page_png):
    monkeypatch.setattr(llm, "generate_json", FakeLLM({"classify": AppError(ErrorCode.MODEL_RATE_LIMITED, "429")}))
    with pytest.raises(AppError) as e:
        run(VertexAIClient().classify(_classify_req()))
    assert e.value.code == ErrorCode.MODEL_RATE_LIMITED


def test_reconcile_never_calls_a_model(monkeypatch):
    monkeypatch.setattr(llm, "generate_json", FakeLLM({}))   # any call would raise KeyError
    req = ai.ReconcileRequest(request_id="r", shipment_id="s",
                              documents=[ai.ReconcileDocumentIn(document_id="a", doc_type="COMMERCIAL_INVOICE")], fields=[])
    assert run(VertexAIClient().reconcile(req)).verdicts


# ---------------------------------------------------------------- llm plumbing

class _StatusError(Exception):
    def __init__(self, code):
        self.code = code


@pytest.mark.parametrize("exc,code", [
    (_StatusError(429), ErrorCode.MODEL_RATE_LIMITED),
    (_StatusError(503), ErrorCode.AI_SERVICE_UNAVAILABLE),
    (_StatusError(504), ErrorCode.AI_SERVICE_TIMEOUT),
    (_StatusError(403), ErrorCode.MODEL_REQUEST_REJECTED),   # e.g. API not enabled: not retried
    (httpx.ReadTimeout("t"), ErrorCode.AI_SERVICE_TIMEOUT),
    (httpx.ConnectError("c"), ErrorCode.AI_SERVICE_UNAVAILABLE),
])
def test_error_mapping(exc, code):
    assert llm.map_error(exc).code == code


def test_permission_errors_are_not_retried(monkeypatch):
    calls = []

    async def failing(*a):
        calls.append(1)
        raise _StatusError(403)
    monkeypatch.setattr(llm, "_call_interactions", failing)
    with pytest.raises(AppError) as e:
        run(llm._call_with_retry("m", "s", [llm.Text("x")], {"type": "object"}))
    assert e.value.code == ErrorCode.MODEL_REQUEST_REJECTED and e.value.retryable is False
    assert len(calls) == 1


def test_one_repair_attempt_then_malformed(monkeypatch):
    replies = iter(["not json", '{"ok": true}'])

    async def reply(*a):
        return llm._Reply(text=next(replies), input_tokens=3, output_tokens=2, model_version="v")
    monkeypatch.setattr(llm, "_call_with_retry", reply)
    data, usage = run(llm.generate_json(stage="t", model="m", prompt_version="p", system="s", parts=[llm.Text("x")],
                                        schema={}, parse=lambda d: d))
    assert data == {"ok": True} and usage.input_tokens == 6   # the repair call is billed too

    replies = iter(["nope", "still nope"])
    with pytest.raises(AppError) as e:
        run(llm.generate_json(stage="t", model="m", prompt_version="p", system="s", parts=[llm.Text("x")],
                              schema={}, parse=lambda d: d))
    assert e.value.code == ErrorCode.MODEL_MALFORMED_OUTPUT


def test_json_schema_translation_keeps_nullability_without_unions():
    schema = ai_vertex.explain_schema(["a", "b"])
    js = llm.to_json_schema(schema)
    prop = js["properties"]["likely_incorrect_document_id"]
    assert prop["type"] == ["string", "null"] and prop["enum"] == ["a", "b", None]
    assert "anyOf" not in str(js) and "oneOf" not in str(js)


# ---------------------------------------------------------------- review regressions

@pytest.mark.parametrize("key,raw", [("invoice_date", "31/02/2025"), ("bl_date", "2025-02-30"),
                                     ("invoice_date", "00/00/2024"), ("invoice_total", "USD " + "9" * 40)])
def test_impossible_model_values_never_crash_normalisation(key, raw):
    from app.services import rules
    assert rules.normalise(key, raw) == (None, None)


def test_unparseable_value_is_kept_raw_and_not_trusted():
    out = _Extraction(fields=[_Field(name="invoice_date", value="31/02/2025", page=1, box_2d=[100, 200, 150, 900],
                                     raw_text="Invoice date: 31/02/2025", confidence=0.95)])
    resp = to_extract_response(_req("COMMERCIAL_INVOICE", "Invoice date: 31/02/2025"), out, USAGE, sent_pages=[1])
    f = resp.fields[0]
    assert f.raw_value == "31/02/2025" and f.normalized_value is None
    assert f.confidence < 0.9   # format check failed, so the blended confidence drops


def test_one_transient_classify_failure_retries_the_stage(monkeypatch, page_png):
    answers = iter([{"doc_type": "PACKING_LIST", "confidence": 0.9, "evidence": None},
                    AppError(ErrorCode.AI_SERVICE_UNAVAILABLE, "503")])

    async def fake(**kw):
        a = next(answers)
        if isinstance(a, Exception):
            raise a
        return kw["parse"](a), ai.Usage(model="m", prompt_version="classify.v1")
    monkeypatch.setattr(llm, "generate_json", fake)
    with pytest.raises(AppError) as e:
        run(VertexAIClient().classify(_classify_req()))
    assert e.value.retryable   # never a permanent UNKNOWN for a transient error


def test_malformed_output_does_not_chain_model_text(monkeypatch):
    async def reply(*a):
        return llm._Reply(text='{"secret_value": "ACME 48,250.00"}', input_tokens=1, output_tokens=1, model_version="v")
    monkeypatch.setattr(llm, "_call_with_retry", reply)

    def strict(d):
        raise ValueError(f"bad input {d}")
    with pytest.raises(AppError) as e:
        run(llm.generate_json(stage="t", model="m", prompt_version="p", system="s", parts=[llm.Text("x")], schema={}, parse=strict))
    assert e.value.__cause__ is None and e.value.__suppress_context__
