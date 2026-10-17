"""Shared error taxonomy (§7). Every error leaving this service uses one envelope."""

from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.logging import get_request_id, log


class ErrorCode(StrEnum):
    VALIDATION_FAILED = "VALIDATION_FAILED"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    FORBIDDEN_ORG_MISMATCH = "FORBIDDEN_ORG_MISMATCH"
    SHIPMENT_NOT_FOUND = "SHIPMENT_NOT_FOUND"
    CONFLICT_STALE_VERSION = "CONFLICT_STALE_VERSION"
    DECISION_REASON_REQUIRED = "DECISION_REASON_REQUIRED"
    SHIPMENT_NOT_REVIEWABLE = "SHIPMENT_NOT_REVIEWABLE"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    UNSUPPORTED_FILE_TYPE = "UNSUPPORTED_FILE_TYPE"
    DOCUMENT_PASSWORD_PROTECTED = "DOCUMENT_PASSWORD_PROTECTED"
    DOCUMENT_CORRUPT = "DOCUMENT_CORRUPT"
    DOCUMENT_PAGE_LIMIT_EXCEEDED = "DOCUMENT_PAGE_LIMIT_EXCEEDED"
    NO_TEXT_OR_IMAGE_CONTENT = "NO_TEXT_OR_IMAGE_CONTENT"
    AI_SERVICE_UNAVAILABLE = "AI_SERVICE_UNAVAILABLE"
    AI_SERVICE_TIMEOUT = "AI_SERVICE_TIMEOUT"
    MODEL_RATE_LIMITED = "MODEL_RATE_LIMITED"
    MODEL_SAFETY_BLOCK = "MODEL_SAFETY_BLOCK"
    MODEL_MALFORMED_OUTPUT = "MODEL_MALFORMED_OUTPUT"
    TOKEN_BUDGET_EXCEEDED = "TOKEN_BUDGET_EXCEEDED"
    INSUFFICIENT_DOCUMENTS = "INSUFFICIENT_DOCUMENTS"
    INTERNAL = "INTERNAL"


# code -> (http status, retryable)
ERROR_TABLE: dict[ErrorCode, tuple[int, bool]] = {
    ErrorCode.VALIDATION_FAILED: (400, False),
    ErrorCode.UNAUTHENTICATED: (401, False),
    ErrorCode.FORBIDDEN_ORG_MISMATCH: (403, False),
    ErrorCode.SHIPMENT_NOT_FOUND: (404, False),
    ErrorCode.CONFLICT_STALE_VERSION: (409, False),
    ErrorCode.DECISION_REASON_REQUIRED: (422, False),
    ErrorCode.SHIPMENT_NOT_REVIEWABLE: (422, False),
    ErrorCode.FILE_TOO_LARGE: (413, False),
    ErrorCode.UNSUPPORTED_FILE_TYPE: (415, False),
    ErrorCode.DOCUMENT_PASSWORD_PROTECTED: (422, False),
    ErrorCode.DOCUMENT_CORRUPT: (422, False),
    ErrorCode.DOCUMENT_PAGE_LIMIT_EXCEEDED: (422, False),
    ErrorCode.NO_TEXT_OR_IMAGE_CONTENT: (422, False),
    ErrorCode.AI_SERVICE_UNAVAILABLE: (503, True),
    ErrorCode.AI_SERVICE_TIMEOUT: (504, True),
    ErrorCode.MODEL_RATE_LIMITED: (429, True),
    ErrorCode.MODEL_SAFETY_BLOCK: (422, False),
    ErrorCode.MODEL_MALFORMED_OUTPUT: (502, True),
    ErrorCode.TOKEN_BUDGET_EXCEEDED: (429, False),
    ErrorCode.INSUFFICIENT_DOCUMENTS: (422, False),
    ErrorCode.INTERNAL: (500, True),
}


class AppError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        field: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field
        self.details = details or {}

    @property
    def http_status(self) -> int:
        return ERROR_TABLE[self.code][0]

    @property
    def retryable(self) -> bool:
        return ERROR_TABLE[self.code][1]

    def envelope(self) -> dict[str, Any]:
        return error_envelope(self.code, self.message, field=self.field, details=self.details)


def error_envelope(
    code: ErrorCode,
    message: str,
    *,
    field: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "error": {
            "code": code.value,
            "message": message,
            "retryable": ERROR_TABLE[code][1],
            "field": field,
            "request_id": get_request_id(),
            "details": details or {},
        }
    }


def not_found(what: str = "Shipment") -> AppError:
    # Org mismatch and absence look identical so a shared link never leaks existence.
    return AppError(ErrorCode.SHIPMENT_NOT_FOUND, f"{what} not found.")


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(exc.envelope(), status_code=exc.http_status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        errors = exc.errors()
        first = errors[0] if errors else {}
        loc = [str(p) for p in first.get("loc", []) if p not in ("body", "query", "path")]
        return JSONResponse(
            error_envelope(
                ErrorCode.VALIDATION_FAILED,
                first.get("msg", "Request validation failed."),
                field=".".join(loc) or None,
                details={"errors": [{"loc": e.get("loc"), "msg": e.get("msg")} for e in errors]},
            ),
            status_code=400,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            code, msg = ErrorCode.SHIPMENT_NOT_FOUND, "Not found."
        elif exc.status_code == 401:
            code, msg = ErrorCode.UNAUTHENTICATED, "Authentication required."
        elif exc.status_code in (400, 405, 422):
            code, msg = ErrorCode.VALIDATION_FAILED, str(exc.detail)
        else:
            code, msg = ErrorCode.INTERNAL, str(exc.detail)
        return JSONResponse(error_envelope(code, msg), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        log.exception("unhandled_error", extra={"error_type": type(exc).__name__})
        return JSONResponse(
            error_envelope(ErrorCode.INTERNAL, "An unexpected error occurred."), status_code=500
        )
