"""Write example ai-service request/response pairs to contracts/fixtures/ai/examples/, produced by
running the in-process stub over the quantity_weight_conflict sample. These are what the backend
sends and what it parses: the reference for confirming the DRAFT classify/reconcile/explain shapes.

    uv run python samples/generate.py && uv run python scripts/export_ai_fixtures.py
"""

import sys
from pathlib import Path

import pypdfium2 as pdfium

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import ai_stub  # noqa: E402
from app.schemas import ai  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT.parent / "contracts" / "fixtures" / "ai" / "examples"
OUT.mkdir(parents=True, exist_ok=True)
URL = "https://storage.googleapis.com/BUCKET/orgs/ORG/shipments/SHP/pages/{doc}/0001.png?X-Goog-Signature=..."


def dump(name: str, model) -> None:
    (OUT / f"{name}.json").write_text(model.model_dump_json(indent=2) + "\n")


docs = []
for i, p in enumerate(sorted((ROOT / "samples" / "out" / "quantity_weight_conflict").glob("*.pdf"))):
    text = pdfium.PdfDocument(str(p))[0].get_textpage().get_text_range()
    docs.append((f"doc_EXAMPLE{i}", p.name, text))

page = lambda d: [ai.PageRef(page=1, image_url=URL.format(doc=d), width_px=1654, height_px=2339)]  # noqa: E731
creq = ai.ClassifyRequest(request_id="req_EXAMPLE_CLASSIFY", documents=[
    ai.ClassifyDocumentIn(document_id=d, filename=n, page_count=1, pages=page(d), text_layer_excerpt=t[:2000])
    for d, n, t in docs])
cres = ai_stub.classify(creq)
dump("classify.request", creq)
dump("classify.response", cres)

types = {c.document_id: c.doc_type for c in cres.documents}
fields = []
for d, n, t in docs:
    ereq = ai.ExtractRequest(request_id=f"req_EXAMPLE_EXTRACT_{d}", document_id=d, doc_type=types[d], pages=page(d),
                             text_layer=t)
    eres = ai_stub.extract(ereq, None)
    if types[d] == "PACKING_LIST":
        dump("extract.request", ereq)
        dump("extract.response", eres)
    for f in eres.fields:
        fields.append(ai.ReconcileFieldIn(document_id=d, field_key=f.field_key, raw_value=f.raw_value,
                                          normalized_value=f.normalized_value, normalized_unit=f.normalized_unit,
                                          confidence=f.confidence, cell_status="PRESENT"))
rreq = ai.ReconcileRequest(request_id="req_EXAMPLE_RECONCILE", shipment_id="shp_EXAMPLE",
                           documents=[ai.ReconcileDocumentIn(document_id=d, doc_type=types[d]) for d, _, _ in docs],
                           fields=fields)
rres = ai_stub.reconcile(rreq)
dump("reconcile.request", rreq)
dump("reconcile.response", rres)

qty = [f for f in fields if f.field_key == "quantity"]
xreq = ai.ExplainRequest(request_id="req_EXAMPLE_EXPLAIN", shipment_id="shp_EXAMPLE", field_key="quantity",
                         verdict="DISAGREE",
                         values=[ai.ExplainValueIn(document_id=f.document_id, doc_type=types[f.document_id],
                                                   raw_value=f.raw_value, normalized_value=f.normalized_value,
                                                   confidence=f.confidence) for f in qty],
                         related_fields=[ai.RelatedField(field_key="hs_code", value="8471300100")])
dump("explain.request", xreq)
dump("explain.response", ai_stub.explain(xreq))
print(f"wrote examples to {OUT}")
