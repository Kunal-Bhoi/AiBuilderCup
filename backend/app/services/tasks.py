"""Stage dispatch. One Cloud Task per stage (§11.2), pushed to worker-service with an OIDC
token. Locally: `inline` runs the stage as an asyncio task in-process (development only;
Cloud Run may stop an instance after the response, so production never does this) and
`sync` awaits it (tests)."""

import asyncio
import json
import re
from typing import Any

from app.config import get_settings
from app.errors import AppError, ErrorCode
from app.logging import log

_background: set[asyncio.Task] = set()
_client: Any = None


def _task_name(payload: dict[str, Any]) -> str:
    # Cloud Tasks de-duplicates by name, which is a first line of idempotency.
    raw = f"{payload['shipment_id']}-{payload['run_id']}-{payload['stage']}-{payload.get('attempt', 1)}"
    return re.sub(r"[^A-Za-z0-9_-]", "-", raw)[:500]


def _create_cloud_task(payload: dict[str, Any]) -> None:
    global _client
    from google.api_core.exceptions import AlreadyExists
    from google.cloud import tasks_v2

    s = get_settings()
    if _client is None:
        _client = tasks_v2.CloudTasksClient()
    parent = _client.queue_path(s.gcp_project, s.gcp_region, s.tasks_queue)
    url = f"{s.worker_url.rstrip('/')}/internal/tasks/run"
    task = tasks_v2.Task(
        name=f"{parent}/tasks/{_task_name(payload)}",
        http_request=tasks_v2.HttpRequest(
            http_method=tasks_v2.HttpMethod.POST,
            url=url,
            headers={"Content-Type": "application/json"},
            body=json.dumps(payload).encode(),
            oidc_token=tasks_v2.OidcToken(service_account_email=s.tasks_service_account, audience=s.worker_url),
        ),
        dispatch_deadline={"seconds": 1800},
    )
    try:
        _client.create_task(parent=parent, task=task)
    except AlreadyExists:
        log.info("task_already_exists", extra={"stage": payload["stage"]})


async def enqueue(payload: dict[str, Any]) -> None:
    s = get_settings()
    from app.worker.orchestrator import run_stage

    if s.tasks_mode == "cloudtasks":
        if not (s.gcp_project and s.worker_url and s.tasks_service_account):
            raise AppError(ErrorCode.INTERNAL, "Cloud Tasks is not configured.")
        await asyncio.to_thread(_create_cloud_task, payload)
    elif s.tasks_mode == "sync":
        await run_stage(payload)
    else:
        t = asyncio.create_task(run_stage(payload))
        _background.add(t)
        t.add_done_callback(_background.discard)
    log.info("stage_enqueued", extra={"stage": payload["stage"], "shipment_id": payload["shipment_id"]})
