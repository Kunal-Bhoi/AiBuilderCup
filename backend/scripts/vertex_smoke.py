"""Live check of the Vertex AI path on one document: classify, extract, explain. Run it once after
enabling Vertex AI, before deploying, to confirm the model, location and API surface work.

    gcloud auth application-default login
    GCP_PROJECT=aibuildercup-512008 AI_MODE=vertex uv run python scripts/vertex_smoke.py
    # options: --file path/to/scan.jpg --doc-type PACKING_LIST
    # env:     VERTEX_LOCATION (default global), GEMINI_MODEL, GEMINI_API=interactions|generate_content

Prints the model, API surface, tokens and cost, and every extracted field with its page and box.
Exits non-zero with the mapped error code if the call fails (e.g. MODEL_REQUEST_REJECTED when the
Vertex AI API is not enabled or the model is not served in that location)."""

import argparse
import asyncio
import subprocess
import sys

from ai_harness import ROOT, cost_usd, get_ai_client, get_settings, load

from app.errors import AppError
from app.schemas import ai


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="defaults to the packing list of the quantity_weight_conflict sample")
    ap.add_argument("--doc-type", help="skip classification and extract as this type")
    a = ap.parse_args()
    s = get_settings()
    if s.ai_mode != "vertex":
        print("Set AI_MODE=vertex (this script checks the live Vertex AI path).", file=sys.stderr)
        return 2
    path = a.file
    if path is None:
        sample = ROOT / "samples" / "out" / "quantity_weight_conflict" / "packing_list.pdf"
        if not sample.exists():
            subprocess.run([sys.executable, str(ROOT / "samples" / "generate.py")], check=True)
        path = str(sample)
    print(f"model={s.gemini_model} location={s.vertex_location} api={s.gemini_api} project={s.gcp_project or '(ADC default)'}")

    from pathlib import Path

    doc = await load(Path(path), "doc_smoke")
    if doc.error:
        print(f"ingest failed: {doc.error}", file=sys.stderr)
        return 1
    client = get_ai_client()
    total_cost = 0.0
    try:
        doc_type = a.doc_type
        if not doc_type:
            c = await client.classify(ai.ClassifyRequest(request_id="smoke-classify", documents=[ai.ClassifyDocumentIn(
                document_id=doc.document_id, filename=doc.filename, page_count=len(doc.pages), pages=doc.pages[:1],
                text_layer_excerpt=(doc.text_layer or "")[:2000] or None)]))
            doc_type = c.documents[0].doc_type
            total_cost += cost_usd(c.usage) if c.usage else 0
            print(f"classify: {doc_type} ({c.documents[0].confidence:.2f})  tokens {c.usage.input_tokens}/{c.usage.output_tokens}")
        e = await client.extract(ai.ExtractRequest(request_id="smoke-extract", document_id=doc.document_id, doc_type=doc_type,
                                                   pages=doc.pages, text_layer=doc.text_layer), doc.filename)
        total_cost += cost_usd(e.usage)
        print(f"extract: {len(e.fields)} fields, {len(e.unreadable_fields)} absent/unreadable, warnings={e.warnings}  "
              f"tokens {e.usage.input_tokens}/{e.usage.output_tokens}  prompt {e.usage.prompt_version}  model {e.usage.model_version}")
        for f in e.fields:
            print(f"  {f.field_key:20} {f.raw_value!r:40} norm={f.normalized_value!r:16} conf={f.confidence:.2f} "
                  f"page={f.provenance.page} bbox={f.provenance.bbox}")
        if len(e.fields) >= 1:
            f = e.fields[0]
            x = await client.explain(ai.ExplainRequest(
                request_id="smoke-explain", shipment_id="shp_smoke", field_key=f.field_key, verdict="DISAGREE", values=[
                    ai.ExplainValueIn(document_id="doc_a", doc_type=doc_type, raw_value=f.raw_value,
                                      normalized_value=f.normalized_value, confidence=f.confidence),
                    ai.ExplainValueIn(document_id="doc_b", doc_type="COMMERCIAL_INVOICE", raw_value="(a different value)",
                                      normalized_value="other", confidence=0.9)]))
            total_cost += cost_usd(x.usage) if x.usage else 0
            print(f"explain: {x.assessment_confidence} likely_incorrect={x.likely_incorrect_document_id}: {x.explanation}")
    except AppError as exc:
        print(f"FAILED: {exc.code.value}: {exc.message}", file=sys.stderr)
        return 1
    print(f"OK. Model cost for this check: US${total_cost:.5f}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
