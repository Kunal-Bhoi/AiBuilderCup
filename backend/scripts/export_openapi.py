"""Write contracts/openapi.yaml from the FastAPI app, so the contract cannot drift from the code.

    uv run python scripts/export_openapi.py
"""

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app  # noqa: E402

out = Path(__file__).resolve().parents[2] / "contracts" / "openapi.yaml"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(yaml.safe_dump(app.openapi(), sort_keys=False, allow_unicode=True))
print(f"wrote {out}")
