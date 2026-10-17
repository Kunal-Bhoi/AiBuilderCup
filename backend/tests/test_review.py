"""Decisions, report gating and signing, audit chain, error envelope and authorisation."""

import base64

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed

from conftest import analyze, upload_scenario


async def _open(client, sid):
    return (await client.get(f"/api/v1/shipments/{sid}/discrepancies")).json()["items"]


async def test_decision_rules_and_report(client):
    sid = await upload_scenario(client, "quantity_weight_conflict")
    await analyze(client, sid)

    r = await client.post(f"/api/v1/shipments/{sid}/report")
    assert r.status_code == 422 and r.json()["error"]["code"] == "SHIPMENT_NOT_REVIEWABLE"

    items = await _open(client, sid)
    qty = next(d for d in items if d["field_key"] == "quantity")

    r = await client.post(f"/api/v1/discrepancies/{qty['discrepancy_id']}/decision",
                          json={"action": "OVERRIDE", "chosen_value": "100 PCS", "reason": "short", "expected_version": qty["version"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "DECISION_REASON_REQUIRED"
    assert r.json()["error"]["field"] == "reason"

    r = await client.post(f"/api/v1/discrepancies/{qty['discrepancy_id']}/decision",
                          headers={"X-Dev-Role": "VIEWER"},
                          json={"action": "ACCEPT_SUGGESTION", "expected_version": qty["version"]})
    assert r.status_code == 403

    r = await client.post(f"/api/v1/discrepancies/{qty['discrepancy_id']}/decision",
                          json={"action": "ACCEPT_SUGGESTION", "expected_version": qty["version"]})
    assert r.status_code == 201, r.text
    assert r.json()["decision"]["actor_user_id"] == "user_dev"
    assert r.json()["decision"]["chosen_value"] == "100 PCS"

    # A second write against the old version loses.
    r = await client.post(f"/api/v1/discrepancies/{qty['discrepancy_id']}/decision",
                          json={"action": "FLAG_FOR_FOLLOW_UP", "expected_version": qty["version"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "CONFLICT_STALE_VERSION"

    for d in await _open(client, sid):
        r = await client.post(f"/api/v1/discrepancies/{d['discrepancy_id']}/decision",
                              json={"action": "DISMISS_AS_NOT_AN_ISSUE", "reason": "Checked against the original shipper copy.",
                                    "expected_version": d["version"]})
        assert r.status_code == 201, r.text
    assert (await client.get(f"/api/v1/shipments/{sid}")).json()["status"] == "REVIEWED"

    r = await client.post(f"/api/v1/shipments/{sid}/report")
    assert r.status_code == 201, r.text
    rep = r.json()
    pdf = (await client.get(rep["download_url"].replace("http://testserver", ""))).content
    assert pdf.startswith(b"%PDF")

    import hashlib

    from app.services.signing import public_key_pem

    digest = hashlib.sha256(pdf).digest()
    assert digest.hex() == rep["content_sha256"]
    key = serialization.load_pem_public_key(public_key_pem().encode())
    key.verify(base64.b64decode(rep["signature_b64"]), digest, ec.ECDSA(Prehashed(hashes.SHA256())))

    assert (await client.get(f"/api/v1/shipments/{sid}")).json()["status"] == "REPORT_ISSUED"
    assert (await client.get(f"/api/v1/shipments/{sid}/report")).status_code == 200
    hist = (await client.get(f"/api/v1/shipments/{sid}/decisions")).json()["items"]
    assert len(hist) >= 3

    eff = (await client.get("/api/v1/org/effectiveness")).json()
    assert eff["decisions_total"] >= 3 and "ACCEPT_SUGGESTION" in eff["by_action"]


async def test_page_image_and_crop(client):
    sid = await upload_scenario(client, "clean_fcl")
    m = await analyze(client, sid)
    doc = m["documents"][0]["document_id"]
    r = await client.get(f"/api/v1/documents/{doc}/pages/1/image")
    assert r.status_code == 200 and r.json()["width_px"] > 0
    r = await client.get(f"/api/v1/documents/{doc}/pages/1/crop", params={"bbox": "0.08,0.07,0.9,0.12"})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content.startswith(b"\x89PNG")
    r = await client.get(f"/api/v1/documents/{doc}/pages/1/crop", params={"bbox": "0.9,0.1,0.1,0.2"})
    assert r.status_code == 400 and r.json()["error"]["field"] == "bbox"


async def test_cross_org_access_looks_like_not_found(client):
    sid = await upload_scenario(client, "single_document")
    r = await client.get(f"/api/v1/shipments/{sid}", headers={"X-Dev-Org": "org_other", "X-Dev-User": "intruder"})
    assert r.status_code == 404
    err = r.json()["error"]
    assert err["code"] == "SHIPMENT_NOT_FOUND" and err["retryable"] is False and err["request_id"]


async def test_upload_validation(client):
    sid = (await client.post("/api/v1/shipments", json={"reference": "upload-validation"})).json()["shipment_id"]
    r = await client.post(f"/api/v1/shipments/{sid}/upload-urls",
                          json={"files": [{"filename": "a.pdf", "size_bytes": 60 * 1024 * 1024, "content_type": "application/pdf"}]})
    assert r.status_code == 413 and r.json()["error"]["code"] == "FILE_TOO_LARGE"
    r = await client.post(f"/api/v1/shipments/{sid}/upload-urls",
                          json={"files": [{"filename": "a.exe", "size_bytes": 10, "content_type": "application/x-msdownload"}]})
    assert r.status_code == 415 and r.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"
    r = await client.post("/api/v1/shipments", json={})
    assert r.status_code == 400 and r.json()["error"]["code"] == "VALIDATION_FAILED"


async def test_list_pagination(client):
    first = (await client.get("/api/v1/shipments", params={"limit": 2})).json()
    assert len(first["items"]) == 2 and first["next_cursor"]
    second = (await client.get("/api/v1/shipments", params={"limit": 2, "cursor": first["next_cursor"]})).json()
    assert not {s["shipment_id"] for s in first["items"]} & {s["shipment_id"] for s in second["items"]}


async def test_audit_chain_verifies_and_is_append_only(client):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    from app.db.engine import sessionmaker

    r = await client.get("/api/v1/org/audit/verify")
    assert r.status_code == 200 and r.json()["valid"] is True and r.json()["events_checked"] > 0
    async with sessionmaker()() as s:
        with pytest.raises(DBAPIError):
            await s.execute(text("UPDATE audit_events SET event_type = 'tampered' WHERE org_id = 'org_dev'"))
        await s.rollback()
        with pytest.raises(DBAPIError):
            await s.execute(text("DELETE FROM audit_events WHERE org_id = 'org_dev'"))
        await s.rollback()
