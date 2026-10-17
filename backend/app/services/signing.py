"""Report signing. Cloud KMS asymmetric EC P-256 / SHA-256 in production: a report signed by a
KMS key cannot be forged by anyone with database access. A local PEM key for development.
scripts/verify_report.py checks a signature with only the public key."""

import asyncio
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed

from app.config import get_settings

ALGORITHM = "ECDSA_P256_SHA256"


def _local_key() -> ec.EllipticCurvePrivateKey:
    path = Path(get_settings().local_signing_key)
    if path.exists():
        return serialization.load_pem_private_key(path.read_bytes(), password=None)
    key = ec.generate_private_key(ec.SECP256R1())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    return key


def _sign_sync(digest: bytes) -> tuple[bytes, str]:
    s = get_settings()
    if s.signing_mode == "kms":
        from google.cloud import kms

        client = kms.KeyManagementServiceClient()
        resp = client.asymmetric_sign(request={"name": s.kms_key_version, "digest": {"sha256": digest}})
        return resp.signature, s.kms_key_version
    key = _local_key()
    sig = key.sign(digest, ec.ECDSA(Prehashed(hashes.SHA256())))
    return sig, "local:" + Path(s.local_signing_key).name


async def sign_digest(digest: bytes) -> tuple[bytes, str]:
    return await asyncio.to_thread(_sign_sync, digest)


def public_key_pem() -> str:
    s = get_settings()
    if s.signing_mode == "kms":
        from google.cloud import kms

        return kms.KeyManagementServiceClient().get_public_key(request={"name": s.kms_key_version}).pem
    return _local_key().public_key().public_bytes(serialization.Encoding.PEM,
                                                  serialization.PublicFormat.SubjectPublicKeyInfo).decode()
