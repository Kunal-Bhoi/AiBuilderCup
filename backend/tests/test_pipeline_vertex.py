"""End-to-end pipeline in AI_MODE=vertex with the model call faked (no GCP). The fake answers the
way Gemini does, boxes in [ymin, xmin, ymax, xmax] 0..1000, so this proves the whole path: worker
stages -> VertexAIClient -> bbox conversion -> database -> API, plus the token-budget failure."""

import re

import pytest

from app.config import get_settings
from app.domain.fields import FIELD_LABELS
from app.schemas import ai
from app.services import ai_client, ai_stub, llm
from app.services.ai_vertex import VertexAIClient
from conftest import analyze, upload_scenario, verdicts

FAKE_MODEL = "gemini-fake"


async def fake_generate_json(*, stage, model, prompt_version, system, parts, schema, parse):
    texts = [p.text for p in parts if isinstance(p, llm.Text)]
    usage = ai.Usage(input_tokens=1200, output_tokens=300, model=FAKE_MODEL, model_version=f"{FAKE_MODEL}-001",
                     prompt_version=prompt_version, latency_ms=3)
    if stage == "classify":
        excerpt = texts[0].split("Embedded text of the first page (may be incomplete):\n", 1)[-1]
        doc_type, conf = ai_stub._guess_type("", excerpt)
        return parse({"doc_type": doc_type.value, "confidence": conf, "evidence": None}), usage
    if stage == "extract":
        doc_type = re.match(r"extract\.(.+)\.v\d+$", prompt_version).group(1).upper()
        layer = next(t for t in texts if t.startswith("Embedded text layer")).split("\n", 1)[1]
        stub = ai_stub.extract(ai.ExtractRequest(request_id="x", document_id="x", doc_type=doc_type, pages=[], text_layer=layer))
        rows = []
        for f in stub.fields:
            x0, y0, x1, y1 = f.provenance.bbox
            rows.append({"name": f.field_key, "value": f.raw_value, "page": 1, "null_reason": None, "confidence": 0.95,
                         "box_2d": [round(y0 * 1000), round(x0 * 1000), round(y1 * 1000), round(x1 * 1000)],  # Gemini order
                         "raw_text": f"{FIELD_LABELS[f.field_key]}: {f.raw_value}"})
        rows += [{"name": u.field_key, "value": None, "page": None, "box_2d": None, "raw_text": None, "confidence": 0.0,
                  "null_reason": "field_absent"} for u in stub.unreadable_fields]
        return parse({"fields": rows}), usage
    if stage == "explain":
        return parse({"explanation": "The documents disagree; confirm with the shipper.", "likely_incorrect_document_id": None,
                      "suggested_value": None, "assessment_confidence": "LOW"}), usage
    raise AssertionError(stage)


@pytest.fixture
def vertex_mode(monkeypatch, request):
    """Swap in the Vertex client with a fake model. Each test gets its own org, because the
    extraction cache (same sha256 + doc type in one org) would otherwise reuse the stub-mode
    rows from the other test modules and the model would never be called."""
    monkeypatch.setattr(ai_client, "_client", VertexAIClient())
    monkeypatch.setattr(llm, "generate_json", fake_generate_json)
    return {"X-Dev-Org": f"org_vertex_{request.node.name}"[:60]}


async def test_vertex_mode_matrix_and_provenance(client, vertex_mode):
    h = vertex_mode
    sid = await upload_scenario(client, "quantity_weight_conflict", headers=h)
    v = verdicts(await analyze(client, sid, headers=h))
    assert v["quantity"] == "DISAGREE" and v["gross_weight"] == "DISAGREE"
    assert v["hs_code"] == "AGREE" and v["vessel_name"] == "SINGLE_SOURCE"

    items = {d["field_key"]: d for d in (await client.get(f"/api/v1/shipments/{sid}/discrepancies", headers=h)).json()["items"]}
    qty = items["quantity"]
    assert qty["explanation_state"] == "READY" and qty["likely_incorrect_document_id"] is None
    detail = (await client.get(f"/api/v1/shipments/{sid}", headers=h)).json()
    pl = next(d for d in detail["documents"] if d["doc_type"] == "PACKING_LIST")
    cell = next(c for c in qty["cells"] if c["document_id"] == pl["document_id"])
    prov = cell["provenance"]
    assert cell["raw_value"] == "95 PCS" and prov["model"] == FAKE_MODEL
    assert prov["prompt_version"] == "extract.packing_list.v1"
    x0, y0, x1, y1 = prov["bbox"]
    assert x1 - x0 > y1 - y0, "a wide label line must stay wide after conversion"
    assert x0 == pytest.approx(0.085, abs=0.002)
    assert detail["current_run"]["cost_usd"] > 0 and detail["current_run"]["input_tokens"] > 0


async def test_vertex_mode_clean_set_has_no_disagreement(client, vertex_mode):
    h = vertex_mode
    v = verdicts(await analyze(client, await upload_scenario(client, "clean_fcl", headers=h), headers=h))
    assert "DISAGREE" not in v.values()


async def test_token_budget_stops_reading_and_fails_honestly(client, vertex_mode, monkeypatch):
    monkeypatch.setattr(get_settings(), "token_budget_per_run", 1)
    h = vertex_mode
    sid = await upload_scenario(client, "clean_fcl", headers=h)
    r = await client.post(f"/api/v1/shipments/{sid}/analyze", headers=h)
    assert r.status_code == 202
    detail = (await client.get(f"/api/v1/shipments/{sid}", headers=h)).json()
    assert detail["status"] == "FAILED"
    assert detail["current_run"]["error_code"] == "INSUFFICIENT_DOCUMENTS"
    assert {d["error_code"] for d in detail["documents"]} == {"TOKEN_BUDGET_EXCEEDED"}
