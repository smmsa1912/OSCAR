"""Structured logging helpers for OSCAR."""

from __future__ import annotations

import json
import logging
from typing import Any


def configure_logging(level: str = "INFO") -> None:
    """Configure a compact structured logger once per process."""

    root = logging.getLogger("oscar")
    if root.handlers:
        root.setLevel(level.upper())
        return

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    root.addHandler(handler)
    root.setLevel(level.upper())
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"oscar.{name}")


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    payload = {"event": event, **fields}
    logger.info(json.dumps(payload, default=str))

