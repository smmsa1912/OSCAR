from __future__ import annotations

from dataclasses import dataclass

import pytest

import oscar.gemini_client as gemini_client
from oscar.gemini_client import GeminiResponseError, ask_gemini, refine_click_action


class FakeImage:
    def save(self, buffer, format: str) -> None:  # noqa: A002 - matches PIL signature
        assert format == "PNG"
        buffer.write(b"fake-image-bytes")


class FakeCroppableImage(FakeImage):
    def __init__(self, size: tuple[int, int] = (1920, 1080)) -> None:
        self.size = size
        self.crop_box: tuple[int, int, int, int] | None = None
        self.resize_calls: list[tuple[int, int]] = []

    def crop(self, box: tuple[int, int, int, int]) -> "FakeCroppableImage":
        self.crop_box = box
        return FakeCroppableImage((box[2] - box[0], box[3] - box[1]))

    def resize(self, size: tuple[int, int], _resample=None) -> "FakeCroppableImage":
        self.resize_calls.append(size)
        self.size = size
        return self


@dataclass
class FakeResponse:
    text: str


class FakeModel:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[list[object]] = []

    def generate_content(self, parts: list[object]) -> FakeResponse:
        self.calls.append(parts)
        return FakeResponse(self._responses.pop(0))


class FakeFailingModel:
    def __init__(self, error_message: str = "boom") -> None:
        self.error_message = error_message

    def generate_content(self, parts: list[object]) -> FakeResponse:
        raise RuntimeError(self.error_message)


class FakeGenAI:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.configured_api_key: str | None = None
        self.model_args: dict[str, object] | None = None
        self.model = FakeModel(self.responses)

    def configure(self, api_key: str) -> None:
        self.configured_api_key = api_key

    def GenerativeModel(
        self,
        *,
        model_name: str,
        system_instruction: str,
        generation_config: dict[str, object],
    ) -> FakeModel:
        self.model_args = {
            "model_name": model_name,
            "system_instruction": system_instruction,
            "generation_config": generation_config,
        }
        return self.model


class FakeFailingGenAI:
    def __init__(self, error_message: str = "boom") -> None:
        self.error_message = error_message

    def configure(self, api_key: str) -> None:
        self.configured_api_key = api_key

    def GenerativeModel(
        self,
        *,
        model_name: str,
        system_instruction: str,
        generation_config: dict[str, object],
    ) -> FakeFailingModel:
        return FakeFailingModel(self.error_message)


class FakeModernModels:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def generate_content(
        self,
        *,
        model: str,
        contents: list[object],
        config: object,
    ) -> FakeResponse:
        self.calls.append(
            {
                "model": model,
                "contents": contents,
                "config": config,
            }
        )
        return FakeResponse(self._responses.pop(0))


class FakeModernClient:
    def __init__(self, responses: list[str], api_key: str) -> None:
        self.api_key = api_key
        self.models = FakeModernModels(responses)


class FakeModernTypes:
    @staticmethod
    def GenerateContentConfig(**kwargs):
        return kwargs


class FakeModernGenAI:
    types = FakeModernTypes()

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.client: FakeModernClient | None = None

    def Client(self, *, api_key: str) -> FakeModernClient:
        self.client = FakeModernClient(self.responses, api_key)
        return self.client


def test_ask_gemini_returns_parsed_json(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_genai = FakeGenAI(
        [
            '{"action":"wait","seconds":1,"reasoning":"Let the UI update.","task_complete":false}'
        ]
    )
    monkeypatch.setattr("oscar.gemini_client._load_genai", lambda: fake_genai)

    action = ask_gemini(
        FakeImage(),
        "Take the next step.",
        api_key="secret",
        model_name="unit-test-model",
    )

    assert action["action"] == "wait"
    assert fake_genai.configured_api_key == "secret"
    assert fake_genai.model_args is not None
    assert fake_genai.model_args["model_name"] == "unit-test-model"
    assert fake_genai.model_args["generation_config"]["response_mime_type"] == "application/json"


def test_ask_gemini_supports_google_genai_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_genai = FakeModernGenAI(
        ['{"action":"done","reasoning":"Finished.","task_complete":true}']
    )
    monkeypatch.setattr("oscar.gemini_client._load_genai", lambda: fake_genai)

    action = ask_gemini(
        FakeImage(),
        "Take the next step.",
        api_key="secret",
        model_name="gemini-2.5-flash",
    )

    assert action["action"] == "done"
    assert fake_genai.client is not None
    assert fake_genai.client.api_key == "secret"
    assert fake_genai.client.models.calls[0]["model"] == "gemini-2.5-flash"
    assert fake_genai.client.models.calls[0]["contents"][0] == "Take the next step."
    assert fake_genai.client.models.calls[0]["config"]["response_mime_type"] == "application/json"


def test_ask_gemini_allows_prompt_only_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_genai = FakeModernGenAI(
        ['{"action":"done","reasoning":"Finished.","task_complete":true}']
    )
    monkeypatch.setattr("oscar.gemini_client._load_genai", lambda: fake_genai)

    action = ask_gemini(
        None,
        "Take the next step.",
        api_key="secret",
        model_name="gemini-2.5-flash",
    )

    assert action["action"] == "done"
    assert fake_genai.client is not None
    assert fake_genai.client.models.calls[0]["contents"] == ["Take the next step."]


def test_ask_gemini_retries_once_for_invalid_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_genai = FakeGenAI(
        [
            "not valid json",
            '{"action":"done","reasoning":"The task is complete.","task_complete":true}',
        ]
    )
    monkeypatch.setattr("oscar.gemini_client._load_genai", lambda: fake_genai)

    action = ask_gemini(FakeImage(), "Retry please.", api_key="secret")

    assert action["action"] == "done"
    assert len(fake_genai.model.calls) == 2
    assert "previous response was invalid" in fake_genai.model.calls[1][0]


def test_ask_gemini_surfaces_underlying_request_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("oscar.gemini_client._load_genai", lambda: FakeFailingGenAI())

    with pytest.raises(GeminiResponseError, match="boom"):
        ask_gemini(FakeImage(), "Retry please.", api_key="secret")


def test_ask_gemini_adds_hint_for_missing_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error_message = "404 NOT_FOUND. {'error': {'code': 404, 'message': 'models/gemini-1.5-flash is not found'}}"
    monkeypatch.setattr(
        "oscar.gemini_client._load_genai",
        lambda: FakeFailingGenAI(error_message),
    )

    with pytest.raises(GeminiResponseError, match="Try GEMINI_MODEL=gemini-2.5-flash"):
        ask_gemini(
            FakeImage(),
            "Retry please.",
            api_key="secret",
            model_name="gemini-1.5-flash",
        )


def test_ask_gemini_raises_after_retry_is_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_genai = FakeGenAI(["still bad", "still bad"])
    monkeypatch.setattr("oscar.gemini_client._load_genai", lambda: fake_genai)

    with pytest.raises(GeminiResponseError, match="invalid JSON"):
        ask_gemini(FakeImage(), "Retry please.", api_key="secret")


def test_ask_gemini_retries_transient_backend_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"count": 0}
    sleep_calls: list[float] = []

    def flaky_generate_content(_prompt, _screenshot):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("503 service unavailable")
        return FakeResponse(
            '{"action":"done","reasoning":"Recovered after retry.","task_complete":true}'
        )

    monkeypatch.setattr(
        "oscar.gemini_client.time.sleep",
        lambda seconds: sleep_calls.append(seconds),
    )

    result = gemini_client._generate_json_response(
        flaky_generate_content,
        prompt="Retry please.",
        screenshot=FakeImage(),
        retries=1,
    )

    assert result["action"] == "done"
    assert calls["count"] == 2
    assert sleep_calls


def test_refine_click_action_normalizes_grid_coordinates_for_raw_fallbacks() -> None:
    screenshot = FakeCroppableImage()
    original_action = {
        "action": "click",
        "x": 500,
        "y": 250,
        "reasoning": "Click the browser profile button.",
        "task_complete": False,
    }

    action = refine_click_action(
        screenshot,
        original_action,
        api_key="secret",
        model_name="unit-test-model",
    )

    assert action["x"] == 960
    assert action["y"] == 270
    assert action["reasoning"] == original_action["reasoning"]



def test_ask_gemini_does_not_retry_non_transient_request_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"count": 0}

    def fail_with_auth_error(_prompt, _screenshot):
        calls["count"] += 1
        raise RuntimeError("401 unauthorized")

    monkeypatch.setattr(
        "oscar.gemini_client._load_genai",
        lambda: FakeGenAI([]),
    )
    # Exercise retry policy directly, independent of SDK initialization.
    with pytest.raises(RuntimeError, match="401 unauthorized"):
        gemini_client._generate_json_response(
            fail_with_auth_error,
            prompt="test",
            screenshot=None,
            retries=3,
        )

    assert calls["count"] == 1


def test_ask_gemini_does_not_retry_timeout_without_explicit_timeout_policy() -> None:
    calls = {"count": 0}

    def timeout(_prompt, _screenshot):
        calls["count"] += 1
        raise TimeoutError("provider request timed out")

    with pytest.raises(TimeoutError, match="timed out"):
        gemini_client._generate_json_response(
            timeout,
            prompt="test",
            screenshot=None,
            retries=3,
        )

    assert calls["count"] == 1
