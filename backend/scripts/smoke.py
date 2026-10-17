"""End-to-end smoke test against a running api-service (local or Cloud Run).

    uv run python scripts/smoke.py --base http://localhost:8080 --scenario quantity_weight_conflict
    uv run python scripts/smoke.py --base https://api-xxxx.a.run.app --token "$FIREBASE_ID_TOKEN"

Creates a shipment, uploads a sample scenario through signed URLs, starts analysis, follows
the SSE stream to completion, prints the matrix, decides every finding and issues the report."""

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

import httpx

SAMPLES = Path(__file__).resolve().parents[1] / "samples" / "out"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8080")
    ap.add_argument("--scenario", default="quantity_weight_conflict")
    ap.add_argument("--token")
    ap.add_argument("--no-decide", action="store_true")
    a = ap.parse_args()

    headers = {"Authorization": f"Bearer {a.token}"} if a.token else {}
    c = httpx.Client(base_url=f"{a.base.rstrip('/')}/api/v1", headers=headers, timeout=60)

    def check(r: httpx.Response) -> dict:
        if r.status_code >= 300:
            print(r.status_code, r.text, file=sys.stderr)
            sys.exit(1)
        return r.json() if r.content else {}

    paths = sorted((SAMPLES / a.scenario).glob("*.pdf"))
    sid = check(c.post("/shipments", json={"reference": f"SMOKE-{a.scenario}-{uuid.uuid4().hex[:6]}"}))["shipment_id"]
    ups = check(c.post(f"/shipments/{sid}/upload-urls", json={"files": [
        {"filename": p.name, "size_bytes": p.stat().st_size, "content_type": "application/pdf"} for p in paths]}))["uploads"]
    for u, p in zip(ups, paths):
        r = httpx.put(u["signed_url"], content=p.read_bytes(), headers=u["headers"], timeout=60)
        assert r.status_code < 300, (r.status_code, r.text)
    check(c.post(f"/shipments/{sid}/documents", json={"upload_ids": [u["upload_id"] for u in ups]}))
    t0 = time.time()
    check(c.post(f"/shipments/{sid}/analyze"))
    print(f"shipment {sid}: analysing {len(paths)} documents")

    with c.stream("GET", f"/shipments/{sid}/events", timeout=None) as stream:
        for line in stream.iter_lines():
            if not line.startswith("data: "):
                continue
            ev = json.loads(line[6:])
            print(f"  {time.time() - t0:5.1f}s {ev['type']:22} {json.dumps(ev['data'])[:110]}")
            if ev["type"] in ("pipeline.completed", "pipeline.failed"):
                break

    m = check(c.get(f"/shipments/{sid}/matrix"))
    print(f"\nstatus {m['status']}  counts {m['verdict_counts']}")
    for g in m["field_groups"]:
        for f in g["fields"]:
            vals = " | ".join((cell["raw_value"] or cell["cell_status"])[:22] for cell in f["cells"])
            print(f"  {f['verdict']:17} {f['label']:22} {vals}")
    for miss in m["missing_documents"]:
        print(f"  missing: {miss['doc_type']} ({miss['severity']})")
    if a.no_decide:
        return 0

    for d in check(c.get(f"/shipments/{sid}/discrepancies"))["items"]:
        body = ({"action": "ACCEPT_SUGGESTION"} if d["suggested_value"] else
                {"action": "DISMISS_AS_NOT_AN_ISSUE", "reason": "Reviewed against source documents in smoke test."})
        check(c.post(f"/discrepancies/{d['discrepancy_id']}/decision", json={**body, "expected_version": d["version"]}))
    rep = check(c.post(f"/shipments/{sid}/report"))
    print(f"\nreport {rep['report_id']} sha256 {rep['content_sha256'][:16]}… signed with {rep['kms_key_version']}")
    print(f"effectiveness: {check(c.get('/org/effectiveness'))['by_action']}")
    print(f"audit chain: {check(c.get('/org/audit/verify'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
