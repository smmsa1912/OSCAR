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


def test_freellmapi_output_limit_is_independent_of_omniroute(monkeypatch, tmp_path) -> None:
    import json

    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({
                "choices": [{"message": {"content": '{\"action\":\"done\"}'}}],
                "usage": {"total_tokens": 42},
            }).encode()

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode())
        return Response()

    monkeypatch.setattr(config, "FREELLMAPI_MAX_PROMPT_CHARS", 5000)
    monkeypatch.setattr(config, "FREELLMAPI_MAX_OUTPUT_TOKENS", 128)
    monkeypatch.setattr(config, "OMNIROUTE_MAX_OUTPUT_TOKENS", 2048)
    monkeypatch.setattr(config, "FREELLMAPI_MAX_REQUEST_TOKENS", 8000)
    monkeypatch.setattr(config, "OMNIROUTE_MAX_DAILY_TOKENS", 50000)
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    monkeypatch.setattr("oscar.freellmapi_client.urllib.request.urlopen", fake_urlopen)

    assert ask_freellmapi(None, "Do one thing", model_name="auto")["action"] == "done"
    assert captured["payload"]["max_tokens"] == 128
    assert captured["payload"]["messages"][0]["content"].endswith("\nReturn exactly one JSON object.")
    assert "\\nReturn exactly one JSON object." not in captured["payload"]["messages"][0]["content"]


def test_freellmapi_endpoint_error_does_not_reserve_tokens(monkeypatch, tmp_path) -> None:
    from oscar import token_budget

    monkeypatch.setattr(config, "FREELLMAPI_BASE_URL", "")
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    monkeypatch.setattr(config, "FREELLMAPI_MAX_REQUEST_TOKENS", 8000)
    monkeypatch.setattr(config, "OMNIROUTE_MAX_DAILY_TOKENS", 50000)

    with pytest.raises(FreeLLMAPIResponseError, match="BASE_URL"):
        ask_freellmapi(None, "Do one thing", model_name="auto")
    assert not (tmp_path / "omniroute_token_usage.json").exists()


def test_freellmapi_image_dimension_is_independent_of_omniroute(monkeypatch) -> None:
    import base64
    import io
    from PIL import Image
    from oscar.freellmapi_client import _image_data_url

    monkeypatch.setattr(config, "FREELLMAPI_MAX_IMAGE_DIMENSION", 512)
    monkeypatch.setattr(config, "OMNIROUTE_MAX_IMAGE_DIMENSION", 1024)
    data_url = _image_data_url(Image.new("RGB", (1600, 1200), color="white"))

    assert data_url is not None
    with Image.open(io.BytesIO(base64.b64decode(data_url.split(",", 1)[1]))) as image:
        assert image.size == (512, 384)
