"""Gemini on Vertex AI: the single place for model ids, API surface, retries, error mapping and
token accounting (AI-SPEC §9, §12, §16). Nothing else in the codebase talks to a model.

API surface. The Interactions API is the current one (`generateContent` is marked Legacy), and
google-genai routes it to Vertex at projects/{project}/locations/{location}. GEMINI_API switches
to `generate_content` without changing any caller, should a model or region not serve it yet.

Model rules that cost marks or correctness if ignored (AI-SPEC §12.1):
  - temperature is never set (Gemini 3 degrades below 1.0); determinism comes from the
    response schema and the deterministic reconciler, not from sampling
  - thinking_level only, never together with a thinking budget (the API returns 400)
  - response schemas are flat and closed: OpenAPI 3.0 subset for generate_content, the same
    schema translated to JSON Schema for Interactions; callers validate with Pydantic after
  - store=False: trade documents are commercially sensitive and are not kept server-side

Retries: 3 attempts with exponential backoff and jitter on 429/5xx/timeouts, then the §7 code is
raised so the worker can choose between a Cloud Tasks retry and a recorded permanent failure.
A reply that is not valid JSON for the schema gets one repair attempt with the error appended."""

import asyncio
import base64
import json
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

import httpx
from pydantic import ValidationError

from app.config import get_settings
from app.errors import AppError, ErrorCode
from app.logging import log
from app.schemas import ai

T = TypeVar("T")

MAX_ATTEMPTS = 3
SAFETY_REASONS = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "IMAGE_SAFETY", "MODEL_ARMOR", "JAILBREAK"}


@dataclass(frozen=True)
class Text:
    text: str


@dataclass(frozen=True)
class Image:
    data: bytes
    mime_type: str = "image/png"


Part = Text | Image


@dataclass
class _Reply:
    text: str
    input_tokens: int
    output_tokens: int
    model_version: str


_client: Any = None


def _get_client() -> Any:
    global _client
    if _client is None:
        from google import genai
        from google.genai import types

        s = get_settings()
        project = s.gcp_project
        if not project:
            try:
                import google.auth

                _, project = google.auth.default()
            except Exception:
                project = None
        if not project:
            raise AppError(ErrorCode.MODEL_REQUEST_REJECTED,
                           "Vertex AI needs GCP_PROJECT, or application default credentials with a project.")
        _client = genai.Client(vertexai=True, project=project, location=s.vertex_location,
                               http_options=types.HttpOptions(timeout=int(s.ai_timeout_seconds * 1000)))
    return _client


def to_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """OpenAPI-subset schema -> JSON Schema: `nullable: true` becomes a ["type", "null"] pair."""
    out: dict[str, Any] = {}
    nullable = schema.get("nullable", False)
    if "type" in schema:
        out["type"] = [schema["type"], "null"] if nullable else schema["type"]
    for key in ("description", "required", "minimum", "maximum", "minItems", "maxItems"):
        if key in schema:
            out[key] = schema[key]
    if "enum" in schema:
        out["enum"] = list(schema["enum"]) + ([None] if nullable else [])
    if "properties" in schema:
        out["properties"] = {k: to_json_schema(v) for k, v in schema["properties"].items()}
    if "items" in schema:
        out["items"] = to_json_schema(schema["items"])
    return out


def _thinking_level() -> str | None:
    level = get_settings().gemini_thinking_level
    return level.strip().lower() if level and level.strip() else None


async def _call_interactions(model: str, system: str, parts: list[Part], schema: dict[str, Any]) -> _Reply:
    s = get_settings()
    content: list[dict[str, Any]] = []
    for p in parts:
        if isinstance(p, Text):
            content.append({"type": "text", "text": p.text})
        else:
            content.append({"type": "image", "mime_type": p.mime_type, "data": base64.b64encode(p.data).decode()})
    generation: dict[str, Any] = {"max_output_tokens": s.gemini_max_output_tokens}
    if level := _thinking_level():
        generation["thinking_level"] = level
    interaction = await _get_client().aio.interactions.create(
        model=model, input=content, system_instruction=system, generation_config=generation, store=False,
        response_format={"type": "text", "mime_type": "application/json", "schema": to_json_schema(schema)},
        timeout=s.ai_timeout_seconds,
    )
    status = str(getattr(interaction, "status", "completed"))
    if status != "completed":
        detail = json.dumps([getattr(e, "message", str(e)) for e in (getattr(interaction, "errors", None) or [])])
        if any(word in detail.upper() for word in ("SAFETY", "BLOCKED", "PROHIBITED")):
            raise AppError(ErrorCode.MODEL_SAFETY_BLOCK, "The model declined to process this content.")
        if status == "budget_exceeded":
            raise AppError(ErrorCode.TOKEN_BUDGET_EXCEEDED, "The model call exceeded its token budget.")
        raise AppError(ErrorCode.MODEL_MALFORMED_OUTPUT, f"The model did not complete (status {status}).")
    usage = getattr(interaction, "usage", None)
    return _Reply(
        text=interaction.output_text or "",
        input_tokens=getattr(usage, "total_input_tokens", None) or 0,
        output_tokens=(getattr(usage, "total_output_tokens", None) or 0) + (getattr(usage, "total_thought_tokens", None) or 0),
        model_version=str(getattr(interaction, "model", None) or model),
    )


async def _call_generate_content(model: str, system: str, parts: list[Part], schema: dict[str, Any]) -> _Reply:
    from google.genai import types

    s = get_settings()
    contents = [types.Part.from_text(text=p.text) if isinstance(p, Text) else types.Part.from_bytes(data=p.data, mime_type=p.mime_type)
                for p in parts]
    level = _thinking_level()
    config = types.GenerateContentConfig(
        system_instruction=system, response_mime_type="application/json", response_schema=schema,
        max_output_tokens=s.gemini_max_output_tokens,
        thinking_config=types.ThinkingConfig(thinking_level=level.upper()) if level else None,
    )
    resp = await _get_client().aio.models.generate_content(model=model, contents=contents, config=config)
    feedback = getattr(resp, "prompt_feedback", None)
    if feedback is not None and getattr(feedback, "block_reason", None):
        raise AppError(ErrorCode.MODEL_SAFETY_BLOCK, "The model declined to process this content.")
    candidates = resp.candidates or []
    finish = getattr(candidates[0], "finish_reason", None) if candidates else None
    if finish is not None and getattr(finish, "value", str(finish)) in SAFETY_REASONS:
        raise AppError(ErrorCode.MODEL_SAFETY_BLOCK, "The model declined to process this content.")
    usage = resp.usage_metadata
    return _Reply(
        text=resp.text or "",
        input_tokens=getattr(usage, "prompt_token_count", None) or 0,
        output_tokens=(getattr(usage, "candidates_token_count", None) or 0) + (getattr(usage, "thoughts_token_count", None) or 0),
        model_version=resp.model_version or model,
    )


def map_error(exc: BaseException) -> AppError:
    """SDK, HTTP and timeout failures -> the shared §7 taxonomy."""
    if isinstance(exc, AppError):
        return exc
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)) or "timeout" in type(exc).__name__.lower():
        return AppError(ErrorCode.AI_SERVICE_TIMEOUT, "The model did not respond in time.")
    status = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if isinstance(status, int):
        if status == 429:
            return AppError(ErrorCode.MODEL_RATE_LIMITED, "The model is rate limited.")
        if status in (408, 504):
            return AppError(ErrorCode.AI_SERVICE_TIMEOUT, "The model did not respond in time.")
        if status >= 500:
            return AppError(ErrorCode.AI_SERVICE_UNAVAILABLE, f"The model service failed with HTTP {status}.")
        return AppError(ErrorCode.MODEL_REQUEST_REJECTED,
                        f"The model service rejected the request with HTTP {status} (permission, project or configuration).")
    if isinstance(exc, httpx.HTTPError):
        return AppError(ErrorCode.AI_SERVICE_UNAVAILABLE, "The model service is unreachable.")
    return AppError(ErrorCode.AI_SERVICE_UNAVAILABLE, f"The model call failed ({type(exc).__name__}).")


async def _call_with_retry(model: str, system: str, parts: list[Part], schema: dict[str, Any]) -> _Reply:
    call = _call_interactions if get_settings().gemini_api == "interactions" else _call_generate_content
    last: AppError | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            return await call(model, system, parts, schema)
        except Exception as exc:  # noqa: BLE001 - every failure is mapped to the shared taxonomy
            last = map_error(exc)
            if not last.retryable or last.code == ErrorCode.MODEL_MALFORMED_OUTPUT:
                raise last from exc
        if attempt == MAX_ATTEMPTS - 1:
            break
        await asyncio.sleep(min(8.0, 0.5 * 2**attempt) + random.random() * 0.5)
    assert last is not None
    raise last


async def generate_json(*, stage: str, model: str, prompt_version: str, system: str, parts: list[Part],
                        schema: dict[str, Any], parse: Callable[[dict[str, Any]], T]) -> tuple[T, ai.Usage]:
    """One structured call. Returns the parsed result and its usage, including any repair call."""
    started = time.monotonic()
    tokens_in = tokens_out = 0
    model_version = model
    attempt_parts = list(parts)
    for repair in range(2):
        reply = await _call_with_retry(model, system, attempt_parts, schema)
        tokens_in, tokens_out, model_version = tokens_in + reply.input_tokens, tokens_out + reply.output_tokens, reply.model_version
        try:
            result = parse(json.loads(reply.text))
        except (ValueError, ValidationError) as exc:
            if repair == 0:
                # One repair attempt with the error appended (AI-SPEC §16), then give up.
                attempt_parts = [*parts, Text(f"Your previous reply was not valid for the required schema "
                                              f"({type(exc).__name__}: {str(exc)[:400]}). Reply again with only "
                                              f"JSON that matches the schema exactly.")]
                continue
            _log(stage, model, prompt_version, tokens_in, tokens_out, started, "MALFORMED")
            # from None: a ValidationError's text quotes the model output, i.e. document values, which must
            # never reach a log through the exception chain (§14).
            raise AppError(ErrorCode.MODEL_MALFORMED_OUTPUT, "The model returned output that does not match the schema.") from None
        usage = ai.Usage(input_tokens=tokens_in, output_tokens=tokens_out, model=model, model_version=model_version,
                         prompt_version=prompt_version, latency_ms=int((time.monotonic() - started) * 1000))
        _log(stage, model, prompt_version, tokens_in, tokens_out, started, "OK")
        return result, usage
    raise AssertionError("unreachable")


def _log(stage: str, model: str, prompt_version: str, tokens_in: int, tokens_out: int, started: float, outcome: str) -> None:
    # Counts and versions only: never prompts, values or filenames (§14).
    log.info("model_call", extra={"stage": stage, "model": model, "prompt_version": prompt_version, "api": get_settings().gemini_api,
                                  "input_tokens": tokens_in, "output_tokens": tokens_out, "outcome": outcome,
                                  "latency_ms": int((time.monotonic() - started) * 1000)})
