"""End-to-end pipeline over the shared fixture scenarios (§8.1), with the AI stub."""

from conftest import analyze, upload_scenario, verdicts


async def test_clean_fcl_is_green(client):
    m = await analyze(client, await upload_scenario(client, "clean_fcl"))
    v = verdicts(m)
    assert m["status"] in ("AWAITING_REVIEW", "REVIEWED")
    assert "DISAGREE" not in v.values(), v
    for key in ("quantity", "hs_code", "product_description", "invoice_total", "gross_weight", "container_numbers"):
        assert v[key] == "AGREE", (key, v[key])
    # Principle 2.5: a field carried by one document is never green.
    assert v["vessel_name"] == "SINGLE_SOURCE"
    assert {c["document_id"] for g in m["field_groups"] for f in g["fields"] for c in f["cells"]} == {
        d["document_id"] for d in m["documents"]}


async def test_quantity_weight_conflict(client):
    sid = await upload_scenario(client, "quantity_weight_conflict")
    v = verdicts(await analyze(client, sid))
    assert v["quantity"] == "DISAGREE"
    assert v["gross_weight"] == "DISAGREE"
    assert v["net_weight"] == "DISAGREE"
    r = await client.get(f"/api/v1/shipments/{sid}/discrepancies")
    items = {d["field_key"]: d for d in r.json()["items"]}
    qty = items["quantity"]
    assert qty["severity"] == "BLOCKING"
    assert qty["explanation_state"] == "READY"
    pl = next(d for d in (await client.get(f"/api/v1/shipments/{sid}")).json()["documents"]
              if d["doc_type"] == "PACKING_LIST")
    assert qty["likely_incorrect_document_id"] == pl["document_id"]
    assert qty["suggested_value"] == "100 PCS"
    cell = next(c for c in qty["cells"] if c["document_id"] == pl["document_id"])
    assert cell["raw_value"] == "95 PCS"
    prov = cell["provenance"]
    assert prov["page"] == 1 and len(prov["bbox"]) == 4 and all(0 <= b <= 1 for b in prov["bbox"])
    assert prov["prompt_version"] and prov["model"]


async def test_hs_digit_mismatch_is_root_match_not_disagreement(client):
    v = verdicts(await analyze(client, await upload_scenario(client, "hs_digit_mismatch")))
    assert v["hs_code"] == "AGREE_AT_HS_ROOT"


async def test_description_drift(client):
    v = verdicts(await analyze(client, await upload_scenario(client, "description_drift")))
    assert v["product_description"] == "DISAGREE"


async def test_currency_mismatch_is_never_converted(client):
    v = verdicts(await analyze(client, await upload_scenario(client, "currency_mismatch")))
    assert v["currency"] == "DISAGREE"


async def test_missing_coo_is_reported(client):
    m = await analyze(client, await upload_scenario(client, "missing_coo"))
    assert any(x["doc_type"] == "CERTIFICATE_OF_ORIGIN" for x in m["missing_documents"])


async def test_single_document_is_all_single_source(client):
    sid = await upload_scenario(client, "single_document")
    v = verdicts(await analyze(client, sid))
    assert v and set(v.values()) <= {"SINGLE_SOURCE", "CANNOT_VERIFY"}
    assert "AGREE" not in v.values()


async def test_corrupt_and_protected_is_partial_success(client):
    sid = await upload_scenario(client, "corrupt_and_protected")
    m = await analyze(client, sid)
    by_name = {d["filename"]: d for d in m["documents"]}
    assert by_name["bill_of_lading_corrupt.pdf"]["error_code"] == "DOCUMENT_CORRUPT"
    assert by_name["customs_declaration_protected.pdf"]["error_code"] == "DOCUMENT_PASSWORD_PROTECTED"
    assert m["status"] in ("AWAITING_REVIEW", "REVIEWED")
    cov = (await client.get(f"/api/v1/shipments/{sid}/coverage")).json()
    assert {d["filename"] for d in cov["unchecked_documents"]} >= {"bill_of_lading_corrupt.pdf",
                                                                   "customs_declaration_protected.pdf"}
    assert cov["out_of_scope"]


async def test_duplicate_doc_type_supersedes_one(client):
    m = await analyze(client, await upload_scenario(client, "duplicate_doc_type"))
    invoices = [d for d in m["documents"] if d["doc_type"] == "COMMERCIAL_INVOICE"]
    assert len(invoices) == 2
    assert sorted(d["status"] for d in invoices) == ["EXTRACTED", "SUPERSEDED"]


async def test_events_are_recorded_for_replay(client):
    from app.db.engine import sessionmaker
    from app.services import events

    sid = await upload_scenario(client, "clean_fcl")
    await analyze(client, sid)
    detail = (await client.get(f"/api/v1/shipments/{sid}")).json()
    async with sessionmaker()() as s:
        evs = await events.replay(s, org_id="org_dev", shipment_id=sid, after_id=None,
                                  run_id=detail["current_run"]["run_id"])
    types = [e["type"] for e in evs]
    assert "document.classified" in types and types[-1] == "pipeline.completed"
    stages = {e["data"]["stage"] for e in evs if e["type"] == "pipeline.stage"}
    assert stages == {"INGEST", "CLASSIFY", "EXTRACT", "RECONCILE", "EXPLAIN", "READY"}


async def test_duplicate_task_delivery_is_idempotent(client):
    from sqlalchemy import func, select

    from app.db.engine import sessionmaker
    from app.db.models import FieldVerdict
    from app.worker.orchestrator import run_stage

    sid = await upload_scenario(client, "clean_fcl")
    await analyze(client, sid)
    run_id = (await client.get(f"/api/v1/shipments/{sid}")).json()["current_run"]["run_id"]

    async def count() -> int:
        async with sessionmaker()() as s:
            return (await s.execute(select(func.count()).select_from(FieldVerdict).where(
                FieldVerdict.run_id == run_id))).scalar_one()

    before = await count()
    status = await run_stage({"org_id": "org_dev", "shipment_id": sid, "run_id": run_id, "stage": "RECONCILE"})
    assert status == 200
    assert await count() == before
