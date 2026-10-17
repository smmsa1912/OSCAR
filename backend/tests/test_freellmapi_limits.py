from __future__ import annotations

import pytest

from oscar import config
from oscar.freellmapi_client import (
    FreeLLMAPIResponseError,
    _bounded_prompt,
    ask_freellmapi,
)


def test_freellmapi_prompt_uses_its_own_character_limit(monkeypatch) -> None:
    monkeypatch.setattr(config, "FREELLMAPI_MAX_PROMPT_CHARS", 1000)
    monkeypatch.setattr(config, "OMNIROUTE_MAX_PROMPT_CHARS", 7000)

    bounded = _bounded_prompt("A" * 2500)

    assert len(bounded) == 1000
    assert "Earlier context omitted" in bounded


def test_freellmapi_request_guard_uses_its_own_token_cap(monkeypatch) -> None:
    monkeypatch.setattr(config, "FREELLMAPI_MAX_REQUEST_TOKENS", 512)
    monkeypatch.setattr(config, "OMNIROUTE_MAX_REQUEST_TOKENS", 5000)

    with pytest.raises(FreeLLMAPIResponseError, match="FREELLMAPI_MAX_REQUEST_TOKENS"):
        ask_freellmapi(None, "Open Notepad", model_name="auto")
