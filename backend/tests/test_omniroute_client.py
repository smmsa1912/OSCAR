from __future__ import annotations

import base64
import io
import json
import urllib.error

import pytest
from PIL import Image

from oscar import config
from oscar.omniroute_client import (
    OmniRouteResponseError,
    _endpoint,
    _bounded_prompt,
    _extract_json_object,
    ask_omniroute,
    list_omniroute_models,
)


@pytest.fixture(autouse=True)
def isolate_token_usage_state(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    monkeypatch.setattr(config, "OMNIROUTE_MAX_DAILY_TOKENS", 50000)


class FakeResponse:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()


def test_endpoint_appends_openai_compatible_paths() -> None:
    assert _endpoint("http://localhost:8080/v1/", "/chat/completions") == (
        "http://localhost:8080/v1/chat/completions"
    )
    assert _endpoint("http://localhost:8080/v1/models", "/models") == (
        "http://localhost:8080/v1/models"
    )


@pytest.mark.parametrize(
    "content",
    [
        '{"action":"wait","seconds":1}',
        '```json\n{"action":"done"}\n```',
        'Action: {"action":"click","x":12,"y":34} okay',
    ],
)
def test_extracts_json_action(content: str) -> None:
    assert _extract_json_object(content)["action"] in {"wait", "done", "click"}


def test_rejects_non_object_json() -> None:
    with pytest.raises(OmniRouteResponseError, match="valid JSON object"):
        _extract_json_object('["not", "an object"]')


def test_ask_omniroute_sends_model_prompt_and_screenshot(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode())
        return FakeResponse({"choices": [{"message": {"content": '{"action":"click","x":1,"y":2}'}}]})

    monkeypatch.setattr(config, "OMNIROUTE_BASE_URL", "http://localhost:8080/v1")
    monkeypatch.setattr(config, "OMNIROUTE_API_KEY", "unit-test-key")
    monkeypatch.setattr(config, "OMNIROUTE_MODEL", "vision-model")
    monkeypatch.setattr(config, "OMNIROUTE_TIMEOUT_SECONDS", 9.0)
    monkeypatch.setattr("oscar.omniroute_client.urllib.request.urlopen", fake_urlopen)

    class Image:
        def save(self, buffer, format):
            assert format == "PNG"
            buffer.write(b"image bytes")

    action = ask_omniroute(Image(), "Click the button.")

    assert action == {"action": "click", "x": 1, "y": 2}
    assert captured["url"] == "http://localhost:8080/v1/chat/completions"
    assert captured["timeout"] == 9.0
    assert captured["headers"]["Authorization"] == "Bearer unit-test-key"
    payload = captured["payload"]
    assert payload["model"] == "vision-model"
    assert payload["response_format"] == {"type": "json_object"}
    content = payload["messages"][1]["content"]
    assert content[0]["text"] == "Click the button."
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_ask_omniroute_fails_clearly_without_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "OMNIROUTE_MODEL", "")
    with pytest.raises(OmniRouteResponseError, match="OMNIROUTE_MODEL"):
        ask_omniroute(None, "Do a thing.")


def test_http_errors_are_normalized_without_response_body_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_urlopen(_request, timeout):
        raise urllib.error.HTTPError(
            "http://localhost/v1/chat/completions", 429, "limited", {},
            io.BytesIO(b"api_key=super-secret-value"),
        )

    monkeypatch.setattr(config, "OMNIROUTE_BASE_URL", "http://localhost/v1")
    monkeypatch.setattr(config, "OMNIROUTE_MODEL", "model")
    monkeypatch.setattr("oscar.omniroute_client.urllib.request.urlopen", failing_urlopen)

    with pytest.raises(OmniRouteResponseError) as error:
        ask_omniroute(None, "Hello")
    assert error.value.status_code == 429
    assert error.value.retryable is True
    assert "super-secret-value" not in str(error.value)


def test_lists_models_from_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        return FakeResponse({"data": [{"id": "model-a"}, {"id": "model-b"}, "invalid"]})

    monkeypatch.setattr(config, "OMNIROUTE_BASE_URL", "http://localhost:8080/v1")
    monkeypatch.setattr("oscar.omniroute_client.urllib.request.urlopen", fake_urlopen)

    models = list_omniroute_models(timeout=3)
    assert seen["url"] == "http://localhost:8080/v1/models"
    assert [item["id"] for item in models] == ["model-a", "model-b"]


def test_connection_error_does_not_echo_configured_url(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_urlopen(_request, timeout):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(config, "OMNIROUTE_BASE_URL", "http://user:password@example.test/v1?token=hidden")
    monkeypatch.setattr(config, "OMNIROUTE_MODEL", "model")
    monkeypatch.setattr("oscar.omniroute_client.urllib.request.urlopen", failing_urlopen)

    with pytest.raises(OmniRouteResponseError) as error:
        ask_omniroute(None, "Hello")
    assert error.value.retryable is True
    assert "password" not in str(error.value)
    assert "hidden" not in str(error.value)



def test_prompt_is_bounded_and_keeps_recent_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "OMNIROUTE_MAX_PROMPT_CHARS", 1000)
    prompt = "BEGIN " + ("x" * 1500) + " RECENT-CONTEXT"
    bounded = _bounded_prompt(prompt)
    assert len(bounded) <= 1000
    assert bounded.startswith("BEGIN")
    assert bounded.endswith("RECENT-CONTEXT")
    assert "Earlier context omitted" in bounded


def test_request_sets_output_token_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode())
        return FakeResponse({
            "choices": [{"message": {"content": '{"action":"done","task_complete":true}'}}],
            "usage": {"total_tokens": 123},
        })

    monkeypatch.setattr(config, "OMNIROUTE_BASE_URL", "http://localhost:8080/v1")
    monkeypatch.setattr(config, "OMNIROUTE_MODEL", "test-model")
    monkeypatch.setattr(config, "OMNIROUTE_MAX_OUTPUT_TOKENS", 256)
    monkeypatch.setattr(config, "OMNIROUTE_MAX_REQUEST_TOKENS", 6000)
    monkeypatch.setattr("oscar.omniroute_client.urllib.request.urlopen", fake_urlopen)

    assert ask_omniroute(None, "Do one small thing.")["action"] == "done"
    assert captured["payload"]["max_tokens"] == 256



def test_screenshot_is_resized_and_jpeg_compressed(monkeypatch: pytest.MonkeyPatch) -> None:
    from oscar.omniroute_client import _image_data_url

    monkeypatch.setattr(config, "OMNIROUTE_MAX_IMAGE_DIMENSION", 1024)
    data_url = _image_data_url(Image.new("RGB", (1600, 1200), color="white"))
    assert data_url is not None
    assert data_url.startswith("data:image/jpeg;base64,")
    encoded = data_url.split(",", 1)[1]
    with Image.open(io.BytesIO(base64.b64decode(encoded))) as compressed:
        assert compressed.size == (1024, 768)
        assert compressed.format == "JPEG"



def test_usage_metadata_reconciles_daily_ledger_and_records_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from oscar import token_budget

    def fake_urlopen(request, timeout):
        payload = json.loads(request.data.decode())
        return FakeResponse({
            "choices": [{"message": {"content": '{"action":"done","task_complete":true}'}}],
            "usage": {"prompt_tokens": 90, "completion_tokens": 33, "total_tokens": 123},
        })

    monkeypatch.setattr(config, "OMNIROUTE_BASE_URL", "http://localhost:8080/v1")
    monkeypatch.setattr(config, "OMNIROUTE_MODEL", "test-model")
    monkeypatch.setattr("oscar.omniroute_client.urllib.request.urlopen", fake_urlopen)

    assert ask_omniroute(None, "Do one small thing.")["action"] == "done"
    ledger = json.loads((tmp_path / "omniroute_token_usage.json").read_text(encoding="utf-8"))
    assert ledger["estimated_tokens"] == 123
    assert ledger["provider_reported_tokens"] == 123
    assert ledger["provider_reported_requests"] == 1
    assert ledger["last_model"] == "test-model"
    assert ledger["last_usage_source"] == "provider_reported"


def test_missing_usage_metadata_is_reported_as_estimate_not_actual(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    def fake_urlopen(request, timeout):
        return FakeResponse({
            "choices": [{"message": {"content": '{"action":"wait","seconds":1}'}}],
        })

    monkeypatch.setattr(config, "OMNIROUTE_BASE_URL", "http://localhost:8080/v1")
    monkeypatch.setattr(config, "OMNIROUTE_MODEL", "auto/best-fast")
    monkeypatch.setattr("oscar.omniroute_client.urllib.request.urlopen", fake_urlopen)

    assert ask_omniroute(None, "Short test.")["action"] == "wait"
    ledger = json.loads((tmp_path / "omniroute_token_usage.json").read_text(encoding="utf-8"))
    assert ledger["estimated_tokens"] > 0
    assert ledger["provider_reported_tokens"] == 0
    assert ledger["estimated_only_requests"] == 1
    assert ledger["last_model"] == "auto/best-fast"
    assert ledger["last_usage_source"] == "estimated_reservation_no_provider_usage"
