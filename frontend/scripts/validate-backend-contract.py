"""Validate frontend fixtures and optional captured browser requests using backend models.
Run with the backend's Python dependencies installed. This script does not access a database.
"""
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
frontend = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(frontend.parent / "backend"))
from app.schemas import api

models = {
    "shipment": api.ShipmentDetail, "summary": api.ShipmentSummary,
    "matrix": api.MatrixResponse, "findings": api.DiscrepancyList,
    "coverage": api.CoverageResponse, "report": api.ReportOut, "decisions": api.DecisionList,
}
fixtures = json.loads((frontend / "src/mocks/backend-contract.json").read_text(encoding="utf-8"))
for key, model in models.items():
    model.model_validate(fixtures[key])
print(f"Validated {len(models)} response fixtures against actual backend models.")

if len(sys.argv) > 1:
    requests = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    count = 0
    for request in requests:
        path, method, body = request["path"], request["method"], request.get("body")
        model = (
            api.ShipmentCreate if path == "/shipments" and method == "POST"
            else api.UploadUrlsRequest if path.endswith("/upload-urls")
            else api.RegisterDocumentsRequest if path.endswith("/documents") and method == "POST"
            else api.DocumentPatch if method == "PATCH"
            else api.DecisionRequest if path.endswith("/decision")
            else None
        )
        if model:
            model.model_validate(body)
            count += 1
    print(f"Validated {count} captured request bodies against actual backend models.")
