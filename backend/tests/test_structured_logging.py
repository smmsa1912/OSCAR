from __future__ import annotations

import io
import logging

from oscar.utils.logging import SanitizingFormatter, log_event


def test_sanitizing_formatter_redacts_message_and_exception() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(SanitizingFormatter("%(levelname)s %(message)s"))
    logger = logging.getLogger("oscar.tests.sanitizing_formatter")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    try:
        logger.warning("provider error api_key=super-secret-value")
        try:
            raise RuntimeError("Authorization: Bearer abc.def.ghi")
        except RuntimeError:
            logger.exception("model request failed")
    finally:
        logger.removeHandler(handler)

    output = stream.getvalue()
    assert "super-secret-value" not in output
    assert "abc.def.ghi" not in output
    assert "[REDACTED]" in output


def test_log_event_redacts_sensitive_fields() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger("oscar.tests.structured_event")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    try:
        log_event(
            logger,
            "provider_failure",
            api_key="super-secret-value",
            detail="request failed with api_key=another-secret",
        )
    finally:
        logger.removeHandler(handler)

    output = stream.getvalue()
    assert "super-secret-value" not in output
    assert "another-secret" not in output
    assert "[REDACTED]" in output
