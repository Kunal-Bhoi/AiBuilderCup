"""Structured JSON logging to stdout (Cloud Logging picks it up as jsonPayload).

Never log field values or filenames: they are commercially sensitive (§14).
Log keys, counts, ids and stages only."""

import contextvars
import json
import logging
import sys
from datetime import UTC, datetime

_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
_trace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("trace_id", default=None)

_RESERVED = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}


def set_request_context(request_id: str | None, trace_id: str | None = None) -> None:
    _request_id.set(request_id)
    _trace_id.set(trace_id)


def get_request_id() -> str | None:
    return _request_id.get()


def get_trace_id() -> str | None:
    return _trace_id.get()


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "time": datetime.now(UTC).isoformat(),
            "logger": record.name,
            "request_id": _request_id.get(),
            "trace_id": _trace_id.get(),
        }
        for key, value in vars(record).items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


log = logging.getLogger("tradecheck")
