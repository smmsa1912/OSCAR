from __future__ import annotations

from dataclasses import dataclass

import pytest

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
        ['{"action":"wait","seconds":1,"reasoning":"Let the UI update.","task_complete":false}']
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


def test_ask_gemini_supports_google_genai_client(monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_ask_gemini_retries_once_for_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_ask_gemini_adds_hint_for_missing_model(monkeypatch: pytest.MonkeyPatch) -> None:
    error_message = (
        "404 NOT_FOUND. {'error': {'code': 404, 'message': 'models/gemini-1.5-flash is not found'}}"
    )
    monkeypatch.setattr(
        "oscar.gemini_client._load_genai",
        lambda: FakeFailingGenAI(error_message),
    )

    with pytest.raises(GeminiResponseError, match="Try GEMINI_MODEL=gemini-2.5-flash"):
        ask_gemini(FakeImage(), "Retry please.", api_key="secret", model_name="gemini-1.5-flash")


def test_ask_gemini_raises_after_retry_is_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_genai = FakeGenAI(["still bad", "still bad"])
    monkeypatch.setattr("oscar.gemini_client._load_genai", lambda: fake_genai)

    with pytest.raises(GeminiResponseError, match="invalid JSON"):
        ask_gemini(FakeImage(), "Retry please.", api_key="secret")


def test_refine_click_action_returns_adjusted_coordinates(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_genai = FakeGenAI(['{"x": 118, "y": 222, "reasoning": "Use the center of the visible button."}'])
    screenshot = FakeCroppableImage()

    monkeypatch.setattr("oscar.gemini_client._load_genai", lambda: fake_genai)
    monkeypatch.setattr("oscar.gemini_client.config.ENABLE_CLICK_REFINEMENT", True)
    monkeypatch.setattr("oscar.gemini_client.config.CLICK_REFINEMENT_RADIUS", 120)
    monkeypatch.setattr("oscar.gemini_client.config.CLICK_REFINEMENT_MAX_SHIFT", 90)

    action = refine_click_action(
        screenshot,
        {
            "action": "click",
            "x": 100,
            "y": 200,
            "reasoning": "Click the browser profile button.",
            "task_complete": False,
        },
        api_key="secret",
        model_name="unit-test-model",
    )

    assert action["x"] == 118
    assert action["y"] == 222
    assert "Refined target" in action["reasoning"]
    assert screenshot.crop_box == (58, 162, 178, 282)


def test_refine_click_action_falls_back_when_refined_point_is_outside_crop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_genai = FakeGenAI(['{"x": 9999, "y": 9999, "reasoning": "Somewhere else."}'])
    screenshot = FakeCroppableImage()
    original_action = {
        "action": "click",
        "x": 100,
        "y": 200,
        "reasoning": "Click the browser profile button.",
        "task_complete": False,
    }

    monkeypatch.setattr("oscar.gemini_client._load_genai", lambda: fake_genai)
    monkeypatch.setattr("oscar.gemini_client.config.ENABLE_CLICK_REFINEMENT", True)
    monkeypatch.setattr("oscar.gemini_client.config.CLICK_REFINEMENT_RADIUS", 120)
    monkeypatch.setattr("oscar.gemini_client.config.CLICK_REFINEMENT_MAX_SHIFT", 90)

    action = refine_click_action(
        screenshot,
        original_action,
        api_key="secret",
        model_name="unit-test-model",
    )

    assert action == original_action


def test_refine_click_action_rejects_large_shift_within_crop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_genai = FakeGenAI(['{"x": 180, "y": 295, "reasoning": "The icon is farther away in the crop."}'])
    screenshot = FakeCroppableImage()
    original_action = {
        "action": "click",
        "x": 100,
        "y": 200,
        "reasoning": "Click the browser profile button.",
        "task_complete": False,
    }

    monkeypatch.setattr("oscar.gemini_client._load_genai", lambda: fake_genai)
    monkeypatch.setattr("oscar.gemini_client.config.ENABLE_CLICK_REFINEMENT", True)
    monkeypatch.setattr("oscar.gemini_client.config.CLICK_REFINEMENT_RADIUS", 120)
    monkeypatch.setattr("oscar.gemini_client.config.CLICK_REFINEMENT_MAX_SHIFT", 40)

    action = refine_click_action(
        screenshot,
        original_action,
        api_key="secret",
        model_name="unit-test-model",
    )

    assert action == original_action






