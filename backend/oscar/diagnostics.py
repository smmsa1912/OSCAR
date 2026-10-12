"""Helpers for keeping diagnostic artifacts useful without leaking secrets."""

from __future__ import annotations

import re
from typing import Any

# These patterns intentionally target common credential formats, not arbitrary
# long strings, so normal task descriptions and trace values remain readable.
_SECRET_PATTERNS = (
    re.compile(r"(?i)(\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|password)\b\s*[:=]\s*)([^\s,;]+)"),
    re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
)
_SENSITIVE_KEY_PARTS = ("api_key", "apikey", "token", "secret", "password", "authorization", "cookie")
_MAX_DIAGNOSTIC_STRING = 8_000


def sanitize_text(value: str) -> str:
    """Redact common credential patterns and bound diagnostic string size."""
    text = value
    for pattern in _SECRET_PATTERNS:
        if pattern.groups >= 2:
            text = pattern.sub(r"\1[REDACTED]", text)
        else:
            text = pattern.sub("[REDACTED]", text)
    if len(text) > _MAX_DIAGNOSTIC_STRING:
        text = text[:_MAX_DIAGNOSTIC_STRING] + "…[truncated]"
    return text


def sanitize_for_log(value: Any, *, key: str | None = None) -> Any:
    """Recursively sanitize values before they are written to diagnostic logs."""
    if key and any(part in key.lower() for part in _SENSITIVE_KEY_PARTS):
        return "[REDACTED]"
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, dict):
        return {str(item_key): sanitize_for_log(item_value, key=str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_for_log(item) for item in value]
    return value
