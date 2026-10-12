"""Structured logging helpers for OSCAR."""

from __future__ import annotations

import json
import logging
from typing import Any

from oscar.diagnostics import sanitize_for_log, sanitize_text


class SanitizingFormatter(logging.Formatter):
    """Redact common secrets from messages and exception tracebacks."""

    def format(self, record: logging.LogRecord) -> str:
        rendered = super().format(record)
        return sanitize_text(rendered)

    def formatException(self, exc_info) -> str:  # noqa: N802 - logging API name
        return sanitize_text(super().formatException(exc_info))


def configure_logging(level: str = "INFO") -> None:
    """Configure a compact structured logger once per process."""

    root = logging.getLogger("oscar")
    if root.handlers:
        root.setLevel(level.upper())
        for handler in root.handlers:
            handler.setFormatter(
                SanitizingFormatter("%(asctime)s %(name)s %(levelname)s %(message)s")
            )
        return

    handler = logging.StreamHandler()
    handler.setFormatter(
        SanitizingFormatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    )
    root.addHandler(handler)
    root.setLevel(level.upper())
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"oscar.{name}")


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    """Emit a structured event after recursively sanitizing its fields."""
    payload = sanitize_for_log({"event": event, **fields})
    logger.info(json.dumps(payload, default=str))
