"""worker-service entry point. Cloud Tasks pushes one stage per request with an OIDC token
minted for the tasks service account. Cloud Run IAM (run.invoker) is the first gate; the token
is checked here as well so the endpoint is safe even if ingress were opened by mistake."""

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.errors import AppError, ErrorCode
from app.worker.orchestrator import run_stage

router = APIRouter(include_in_schema=False)


def _verify_oidc(token: str) -> dict:
    import google.auth.transport.requests
    import google.oauth2.id_token

    s = get_settings()
    return google.oauth2.id_token.verify_oauth2_token(token, google.auth.transport.requests.Request(), audience=s.worker_url)


@router.post("/internal/tasks/run")
async def run_task(request: Request) -> JSONResponse:
    s = get_settings()
    if s.tasks_mode == "cloudtasks":
        header = request.headers.get("Authorization", "")
        try:
            claims = await asyncio.to_thread(_verify_oidc, header.removeprefix("Bearer ").strip())
        except Exception:
            raise AppError(ErrorCode.UNAUTHENTICATED, "Invalid task token.")
        if claims.get("email") != s.tasks_service_account:
            raise AppError(ErrorCode.UNAUTHENTICATED, "Unexpected task caller.")
    payload = await request.json()
    for key in ("org_id", "shipment_id", "run_id", "stage"):
        if key not in payload:
            raise AppError(ErrorCode.VALIDATION_FAILED, f"Missing {key}.", field=key)
    status = await run_stage(payload)
    return JSONResponse({"status": status}, status_code=status)
