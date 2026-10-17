"""Verify a pre-submission report's signature with nothing but the public key.
A third party can run this; it needs no database or service access.

    uv run python scripts/verify_report.py report.pdf --signature-b64 <sig> --public-key key.pem
    # public key for the KMS key:
    gcloud kms keys versions get-public-key 1 --key report-signing --keyring tradecheck \
        --location asia-southeast1 --output-file key.pem
"""

import argparse
import base64
import hashlib
import sys

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed

ap = argparse.ArgumentParser()
ap.add_argument("pdf")
ap.add_argument("--signature-b64", required=True)
ap.add_argument("--public-key", required=True)
ap.add_argument("--sha256", help="expected content_sha256 from the report metadata")
a = ap.parse_args()

digest = hashlib.sha256(open(a.pdf, "rb").read()).digest()
if a.sha256 and a.sha256 != digest.hex():
    sys.exit(f"FAIL: file hash {digest.hex()} does not match the recorded {a.sha256}")
key = serialization.load_pem_public_key(open(a.public_key, "rb").read())
try:
    key.verify(base64.b64decode(a.signature_b64), digest, ec.ECDSA(Prehashed(hashes.SHA256())))
except InvalidSignature:
    sys.exit("FAIL: signature does not match this file")
print(f"OK: signature valid for sha256 {digest.hex()}")
