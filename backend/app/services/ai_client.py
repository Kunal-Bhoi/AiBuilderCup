"""Client for ai-service (§6). Service-to-service with a Google-signed OIDC ID token whose
audience is pinned to the ai-service URL. No user token ever reaches the AI service.

Retry: 3 attempts with exponential backoff and jitter on retryable errors (429/5xx/timeouts),
then the §7 code is raised so the worker can decide between a Cloud Tasks retry and a
recorded permanent failure."""

import asyncio
import random
import time
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.config import get_settings
from app.errors import AppError, ErrorCode
from app.logging import get_request_id, get_trace_id
from app.schemas import ai

T = TypeVar("T", bound=BaseModel)

_token: tuple[str, float] | None = None
_token_lock = asyncio.Lock()


async def _id_token(audience: str) -> str | None:
    global _token
    async with _token_lock:
        if _token and _token[1] > time.time() + 300:
            return _token[0]
        try:
            import google.auth.transport.requests
            import google.oauth2.id_token

            token = await asyncio.to_thread(
                google.oauth2.id_token.fetch_id_token, google.auth.transport.requests.Request(), audience
            )
        except Exception:
            return None  # local development against an unauthenticated ai-service
        _token = (token, time.time() + 3300)
        return token


class HttpAIClient:
    def __init__(self, base_url: str, timeout: float):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout)

    async def _post(self, path: str, body: BaseModel, out: type[T]) -> T:
        headers = {"Content-Type": "application/json"}
        if rid := get_request_id():
            headers["X-Request-Id"] = rid
        if tid := get_trace_id():
            headers["traceparent"] = f"00-{tid.ljust(32, '0')[:32]}-{random.getrandbits(64):016x}-01"
        if token := await _id_token(self.base_url):
            headers["Authorization"] = f"Bearer {token}"

        last: AppError | None = None
        for attempt in range(3):
            try:
                r = await self.client.post(path, content=body.model_dump_json(), headers=headers)
            except httpx.TimeoutException:
                last = AppError(ErrorCode.AI_SERVICE_TIMEOUT, "The AI service did not respond in time.")
            except httpx.HTTPError:
                last = AppError(ErrorCode.AI_SERVICE_UNAVAILABLE, "The AI service is unreachable.")
            else:
                if r.status_code < 300:
                    try:
                        return out.model_validate_json(r.content)
                    except ValidationError:
                        last = AppError(ErrorCode.MODEL_MALFORMED_OUTPUT, "The AI service returned a malformed response.")
                else:
                    last = _error_from_response(r)
            if not last.retryable:
                raise last
            await asyncio.sleep(min(8.0, 0.5 * 2**attempt) + random.random() * 0.5)
        assert last is not None
        raise last

    async def classify(self, req: ai.ClassifyRequest) -> ai.ClassifyResponse:
        return await self._post("/ai/v1/classify", req, ai.ClassifyResponse)

    async def extract(self, req: ai.ExtractRequest, filename: str | None = None) -> ai.ExtractResponse:
        return await self._post("/ai/v1/extract", req, ai.ExtractResponse)

    async def reconcile(self, req: ai.ReconcileRequest) -> ai.ReconcileResponse:
        return await self._post("/ai/v1/reconcile", req, ai.ReconcileResponse)

    async def explain(self, req: ai.ExplainRequest) -> ai.ExplainResponse:
        return await self._post("/ai/v1/explain", req, ai.ExplainResponse)


def _error_from_response(r: httpx.Response) -> AppError:
    try:
        err = r.json()["error"]
        code = ErrorCode(err["code"])
        return AppError(code, err.get("message", "AI service error."), details=err.get("details") or {})
    except Exception:
        if r.status_code == 429:
            return AppError(ErrorCode.MODEL_RATE_LIMITED, "The model is rate limited.")
        if r.status_code == 504:
            return AppError(ErrorCode.AI_SERVICE_TIMEOUT, "The AI service timed out.")
        if r.status_code >= 500:
            return AppError(ErrorCode.AI_SERVICE_UNAVAILABLE, f"The AI service failed with HTTP {r.status_code}.")
        return AppError(ErrorCode.MODEL_MALFORMED_OUTPUT, f"The AI service rejected the request with HTTP {r.status_code}.")


class StubAIClient:
    """AI_MODE=stub: same interface, runs app/services/ai_stub.py in-process."""

    async def classify(self, req: ai.ClassifyRequest) -> ai.ClassifyResponse:
        from app.services import ai_stub

        return ai_stub.classify(req)

    async def extract(self, req: ai.ExtractRequest, filename: str | None = None) -> ai.ExtractResponse:
        from app.services import ai_stub

        return ai_stub.extract(req, filename)

    async def reconcile(self, req: ai.ReconcileRequest) -> ai.ReconcileResponse:
        from app.services import ai_stub

        return ai_stub.reconcile(req)

    async def explain(self, req: ai.ExplainRequest) -> ai.ExplainResponse:
        from app.services import ai_stub

        return ai_stub.explain(req)


_client: HttpAIClient | StubAIClient | None = None


def get_ai_client() -> HttpAIClient | StubAIClient:
    global _client
    if _client is None:
        s = get_settings()
        if s.ai_mode == "http":
            if not s.ai_service_url:
                raise RuntimeError("AI_SERVICE_URL is required when AI_MODE=http")
            _client = HttpAIClient(s.ai_service_url, s.ai_timeout_seconds)
        else:
            _client = StubAIClient()
    return _client


def cost_usd(usage: ai.Usage) -> float:
    s = get_settings()
    if usage.model == "stub":
        return 0.0
    return round(usage.input_tokens / 1e6 * s.price_input_per_m + usage.output_tokens / 1e6 * s.price_output_per_m, 6)
