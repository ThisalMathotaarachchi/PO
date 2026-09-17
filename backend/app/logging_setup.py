"""Structured logging without leaking secrets."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Any

_SECRET_KEYS = {
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "private_key",
    "access_key",
    "secret_key",
}

_SECRET_PATTERN = re.compile(
    r"(password|secret|token|api[_-]?key|authorization)\s*[:=]\s*([^\s,;]+)",
    re.IGNORECASE,
)


def redact_value(key: str, value: Any) -> Any:
    if key.lower() in _SECRET_KEYS or any(part in key.lower() for part in _SECRET_KEYS):
        return "[redacted]"
    if isinstance(value, str):
        return _SECRET_PATTERN.sub(r"\1=[redacted]", value)
    return value


def redact_mapping(data: dict[str, Any]) -> dict[str, Any]:
    return {k: redact_value(k, v) for k, v in data.items()}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_value("message", record.getMessage()),
        }
        extra = getattr(record, "extra_data", None)
        if isinstance(extra, dict):
            payload.update(redact_mapping(extra))
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger("po")
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"po.{name}")


def log_event(logger: logging.Logger, message: str, **fields: Any) -> None:
    logger.info(message, extra={"extra_data": redact_mapping(fields)})
