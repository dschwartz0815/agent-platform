"""
Structured JSON logging for the platform.

Every log record is emitted as a single JSON line:
  {"ts": "...", "level": "INFO", "logger": "app.routers.graphs", "msg": "...", "request_id": "..."}

Request IDs are threaded through via a ContextVar set by RequestIDMiddleware in main.py.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from typing import Any

# Set by RequestIDMiddleware before each request; read by the formatter.
request_id_var: ContextVar[str] = ContextVar("request_id", default="")

# Standard LogRecord attributes — never re-emit these as extras
_BUILTIN_FIELDS = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "taskName", "message", "asctime",
})


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()

        entry: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.message,
        }

        rid = request_id_var.get("")
        if rid:
            entry["request_id"] = rid

        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)

        if record.stack_info:
            entry["stack"] = self.formatStack(record.stack_info)

        # Emit any extra= fields passed by callers
        for key, val in record.__dict__.items():
            if key in _BUILTIN_FIELDS or key.startswith("_"):
                continue
            if key in entry:
                continue
            try:
                json.dumps(val)
                entry[key] = val
            except (TypeError, ValueError):
                entry[key] = str(val)

        return json.dumps(entry, default=str)


def configure_logging(level: str = "INFO") -> None:
    """
    Install the JSON formatter on the root logger.
    Call once at application startup, before any loggers are created.
    """
    root = logging.getLogger()
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Silence chatty libraries that add no value at INFO
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
