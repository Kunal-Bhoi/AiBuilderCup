"""Object storage. GCS with v4 signed URLs in production; a local directory with
HMAC-signed URLs (served by app/api/local_storage.py) for development.

Signed URLs: 15 minutes for upload, 5 minutes for read, minted per request, never stored (§13.3)."""

import asyncio
import hashlib
import hmac
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlencode

from app.config import get_settings


class Storage:
    def uri(self, object_name: str) -> str:
        raise NotImplementedError

    def object_name(self, uri: str) -> str:
        return uri.split("://", 1)[1].split("/", 1)[1] if uri.startswith("gs://") else uri.split("://", 1)[1]

    async def signed_put_url(self, object_name: str, content_type: str, ttl: int) -> tuple[str, datetime]:
        raise NotImplementedError

    async def signed_get_url(self, object_name: str, ttl: int) -> tuple[str, datetime]:
        raise NotImplementedError

    async def size(self, object_name: str) -> int | None:
        raise NotImplementedError

    async def download(self, object_name: str) -> bytes:
        raise NotImplementedError

    async def upload(self, object_name: str, data: bytes, content_type: str) -> str:
        raise NotImplementedError


class LocalStorage(Storage):
    def __init__(self, root: str, base_url: str, secret: str):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.base_url = base_url.rstrip("/")
        self.secret = secret.encode()

    def uri(self, object_name: str) -> str:
        return f"local://{object_name}"

    def path(self, object_name: str) -> Path:
        p = (self.root / object_name).resolve()
        if not p.is_relative_to(self.root):
            raise ValueError("path escapes storage root")
        return p

    def sign(self, method: str, object_name: str, exp: int) -> str:
        msg = f"{method}\n{object_name}\n{exp}".encode()
        return hmac.new(self.secret, msg, hashlib.sha256).hexdigest()

    def verify(self, method: str, object_name: str, exp: int, sig: str) -> bool:
        return exp >= int(time.time()) and hmac.compare_digest(self.sign(method, object_name, exp), sig)

    def _url(self, method: str, object_name: str, ttl: int) -> tuple[str, datetime]:
        exp = int(time.time()) + ttl
        q = urlencode({"exp": exp, "sig": self.sign(method, object_name, exp)})
        return f"{self.base_url}/local-storage/{quote(object_name)}?{q}", datetime.fromtimestamp(exp, UTC)

    async def signed_put_url(self, object_name: str, content_type: str, ttl: int) -> tuple[str, datetime]:
        return self._url("PUT", object_name, ttl)

    async def signed_get_url(self, object_name: str, ttl: int) -> tuple[str, datetime]:
        return self._url("GET", object_name, ttl)

    async def size(self, object_name: str) -> int | None:
        p = self.path(object_name)
        return p.stat().st_size if p.exists() else None

    async def download(self, object_name: str) -> bytes:
        return await asyncio.to_thread(self.path(object_name).read_bytes)

    async def upload(self, object_name: str, data: bytes, content_type: str) -> str:
        p = self.path(object_name)
        p.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(p.write_bytes, data)
        return self.uri(object_name)


class GcsStorage(Storage):
    def __init__(self, bucket: str):
        from google.cloud import storage

        self.client = storage.Client()
        self.bucket = self.client.bucket(bucket)
        self.bucket_name = bucket

    def uri(self, object_name: str) -> str:
        return f"gs://{self.bucket_name}/{object_name}"

    def _signing_kwargs(self) -> dict:
        """On Cloud Run there is no private key; sign through the IAM signBlob API using
        the service account's own access token (needs roles/iam.serviceAccountTokenCreator on itself)."""
        import google.auth
        from google.auth.transport.requests import Request

        creds, _ = google.auth.default()
        if not creds.valid:
            creds.refresh(Request())
        email = getattr(creds, "service_account_email", None)
        if email and email != "default":
            return {"service_account_email": email, "access_token": creds.token}
        return {}

    def _sign(self, object_name: str, method: str, ttl: int, content_type: str | None) -> str:
        blob = self.bucket.blob(object_name)
        return blob.generate_signed_url(
            version="v4",
            expiration=timedelta(seconds=ttl),
            method=method,
            content_type=content_type,
            **self._signing_kwargs(),
        )

    async def signed_put_url(self, object_name: str, content_type: str, ttl: int) -> tuple[str, datetime]:
        url = await asyncio.to_thread(self._sign, object_name, "PUT", ttl, content_type)
        return url, datetime.now(UTC) + timedelta(seconds=ttl)

    async def signed_get_url(self, object_name: str, ttl: int) -> tuple[str, datetime]:
        url = await asyncio.to_thread(self._sign, object_name, "GET", ttl, None)
        return url, datetime.now(UTC) + timedelta(seconds=ttl)

    async def size(self, object_name: str) -> int | None:
        def _size() -> int | None:
            blob = self.bucket.get_blob(object_name)
            return blob.size if blob else None

        return await asyncio.to_thread(_size)

    async def download(self, object_name: str) -> bytes:
        return await asyncio.to_thread(self.bucket.blob(object_name).download_as_bytes)

    async def upload(self, object_name: str, data: bytes, content_type: str) -> str:
        await asyncio.to_thread(self.bucket.blob(object_name).upload_from_string, data, content_type=content_type)
        return self.uri(object_name)


_storage: Storage | None = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        s = get_settings()
        if s.storage_mode == "gcs":
            if not s.gcs_bucket:
                raise RuntimeError("GCS_BUCKET is required when STORAGE_MODE=gcs")
            _storage = GcsStorage(s.gcs_bucket)
        else:
            _storage = LocalStorage(s.local_storage_dir, s.public_base_url, s.local_url_secret)
    return _storage


def original_object(org_id: str, shipment_id: str, upload_id: str) -> str:
    return f"orgs/{org_id}/shipments/{shipment_id}/originals/{upload_id}"


def page_object(org_id: str, shipment_id: str, document_id: str, page: int) -> str:
    return f"orgs/{org_id}/shipments/{shipment_id}/pages/{document_id}/{page:04d}.png"


def report_object(org_id: str, shipment_id: str, report_id: str) -> str:
    return f"orgs/{org_id}/shipments/{shipment_id}/reports/{report_id}.pdf"
