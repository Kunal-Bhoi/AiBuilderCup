"""Tests run against a real PostgreSQL database (never SQLite), the in-process AI stub, and
TASKS_MODE=sync so a call to /analyze returns after the whole pipeline has run."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_tmp = tempfile.mkdtemp(prefix="tradecheck-test-")
os.environ.update({
    "DATABASE_URL": os.environ.get("TEST_DATABASE_URL",
                                   "postgresql+asyncpg://tradecheck:tradecheck@localhost:5432/tradecheck_test"),
    "TASKS_MODE": "sync",
    "AI_MODE": "stub",
    "AUTH_MODE": "dev",
    "STORAGE_MODE": "local",
    "SIGNING_MODE": "local",
    "SERVICE_ROLE": "all",
    "LOCAL_STORAGE_DIR": f"{_tmp}/storage",
    "LOCAL_SIGNING_KEY": f"{_tmp}/signing_key.pem",
    "AI_STUB_FIXTURES_DIR": str(ROOT.parent / "contracts" / "fixtures" / "ai"),
    "PUBLIC_BASE_URL": "http://testserver",
})

SAMPLES = ROOT / "samples" / "out"


def _migrate() -> None:
    env = dict(os.environ)
    for cmd in (["alembic", "downgrade", "base"], ["alembic", "upgrade", "head"]):
        subprocess.run([sys.executable, "-m", *cmd], cwd=ROOT, env=env, check=True, capture_output=True)


def pytest_sessionstart(session) -> None:
    _migrate()
    subprocess.run([sys.executable, str(ROOT / "samples" / "generate.py")], check=True, capture_output=True)


@pytest.fixture(scope="session")
async def client():
    import httpx

    from app.db.engine import dispose
    from app.main import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as c:
        yield c
    await dispose()


async def upload_scenario(client, scenario: str, files: list[str] | None = None, headers: dict | None = None) -> str:
    """Create a shipment and upload every PDF of a sample scenario through the signed-URL flow."""
    import uuid

    headers = headers or {}
    paths = sorted((SAMPLES / scenario).glob("*.pdf"))
    if files is not None:
        paths = [p for p in paths if p.name in files]
    r = await client.post("/api/v1/shipments", json={"reference": f"{scenario}-{uuid.uuid4().hex[:8]}"}, headers=headers)
    assert r.status_code == 201, r.text
    sid = r.json()["shipment_id"]
    r = await client.post(f"/api/v1/shipments/{sid}/upload-urls", headers=headers, json={"files": [
        {"filename": p.name, "size_bytes": p.stat().st_size, "content_type": "application/pdf"} for p in paths]})
    assert r.status_code == 200, r.text
    uploads = r.json()["uploads"]
    for u, p in zip(uploads, paths):
        put = await client.put(u["signed_url"].replace("http://testserver", ""), content=p.read_bytes(),
                               headers=u["headers"])
        assert put.status_code == 200, put.text
    r = await client.post(f"/api/v1/shipments/{sid}/documents", headers=headers,
                          json={"upload_ids": [u["upload_id"] for u in uploads]})
    assert r.status_code == 201, r.text
    return sid


async def analyze(client, sid: str, headers: dict | None = None) -> dict:
    r = await client.post(f"/api/v1/shipments/{sid}/analyze", headers=headers or {})
    assert r.status_code == 202, r.text
    r = await client.get(f"/api/v1/shipments/{sid}/matrix", headers=headers or {})
    assert r.status_code == 200, r.text
    return r.json()


def verdicts(matrix: dict) -> dict[str, str]:
    return {f["field_key"]: f["verdict"] for g in matrix["field_groups"] for f in g["fields"]}
