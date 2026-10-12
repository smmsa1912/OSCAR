from __future__ import annotations

import pytest

from oscar import config
from oscar.brain.planner import GeminiBrain, ModelBrain
from oscar.model_gateway import (
    GeminiGateway,
    ModelGatewayError,
    OmniRouteGateway,
    create_model_gateway,
)


def test_default_gateway_is_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "LLM_PROVIDER", "gemini")
    gateway = create_model_gateway()
    assert isinstance(gateway, GeminiGateway)
    assert gateway.default_model == config.GEMINI_MODEL


def test_configured_gateway_can_select_omniroute(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "LLM_PROVIDER", "omniroute")
    monkeypatch.setattr(config, "OMNIROUTE_MODEL", "local-vision-model")
    gateway = create_model_gateway()
    assert isinstance(gateway, OmniRouteGateway)
    assert gateway.default_model == "local-vision-model"


def test_unknown_gateway_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported LLM_PROVIDER"):
        create_model_gateway("unknown")


def test_gateway_error_has_normalized_fields_and_redacts_secrets() -> None:
    error = ModelGatewayError(
        "omniroute",
        "HTTP 401 api_key=super-secret-value",
        retryable=False,
        status_code=401,
    )
    assert error.provider == "omniroute"
    assert error.retryable is False
    assert error.status_code == 401
    assert "super-secret-value" not in str(error)


def test_planner_defaults_to_configured_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "LLM_PROVIDER", "omniroute")
    monkeypatch.setattr(config, "OMNIROUTE_MODEL", "configured-model")
    planner = ModelBrain()
    assert isinstance(planner.provider, OmniRouteGateway)
    assert planner.model_name == "configured-model"


def test_gemini_brain_name_remains_backward_compatible() -> None:
    planner = GeminiBrain(ask_model=lambda *_args, **_kwargs: {"action": "wait"})
    assert isinstance(planner, ModelBrain)


def test_omniroute_selects_configured_vision_model_for_screenshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "OMNIROUTE_AUTO_ROUTING", True)
    monkeypatch.setattr(config, "OMNIROUTE_MODEL", "default-model")
    monkeypatch.setattr(config, "OMNIROUTE_MODEL_VISION", "vision-model")
    assert OmniRouteGateway.select_model(object(), "Click the Save button") == "vision-model"


def test_omniroute_routes_complex_text_to_reasoning_and_simple_text_to_fast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "OMNIROUTE_AUTO_ROUTING", True)
    monkeypatch.setattr(config, "OMNIROUTE_MODEL", "default-model")
    monkeypatch.setattr(config, "OMNIROUTE_MODEL_FAST", "fast-model")
    monkeypatch.setattr(config, "OMNIROUTE_MODEL_REASONING", "reasoning-model")
    assert OmniRouteGateway.select_model(None, "Open settings") == "fast-model"
    assert OmniRouteGateway.select_model(None, "Analyze the issue step by step") == "reasoning-model"


def test_omniroute_role_without_configured_model_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "OMNIROUTE_AUTO_ROUTING", True)
    monkeypatch.setattr(config, "OMNIROUTE_MODEL", "default-model")
    monkeypatch.setattr(config, "OMNIROUTE_MODEL_FAST", "")
    assert OmniRouteGateway.select_model(None, "Open settings") == "default-model"


def test_omniroute_explicit_model_override_wins_over_automatic_routing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from oscar import omniroute_client

    seen: list[str] = []
    monkeypatch.setattr(config, "OMNIROUTE_AUTO_ROUTING", True)
    monkeypatch.setattr(config, "OMNIROUTE_MODEL", "default-model")
    monkeypatch.setattr(config, "OMNIROUTE_MODEL_VISION", "vision-model")
    monkeypatch.setattr(
        omniroute_client,
        "ask_omniroute",
        lambda _screenshot, _prompt, *, model_name=None: seen.append(model_name) or {"action": "wait"},
    )
    assert OmniRouteGateway().generate_action(object(), "Click", model_name="pinned-model") == {"action": "wait"}
    assert seen == ["pinned-model"]


def test_omniroute_retries_once_with_fallback_after_transient_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from oscar import omniroute_client

    seen: list[str] = []

    def fake_ask(_screenshot, _prompt, *, model_name=None):
        seen.append(model_name)
        if model_name == "fast-model":
            raise omniroute_client.OmniRouteResponseError(
                "gateway unavailable", retryable=True, status_code=503
            )
        return {"action": "wait"}

    monkeypatch.setattr(config, "OMNIROUTE_AUTO_ROUTING", True)
    monkeypatch.setattr(config, "OMNIROUTE_MODEL", "default-model")
    monkeypatch.setattr(config, "OMNIROUTE_MODEL_FAST", "fast-model")
    monkeypatch.setattr(config, "OMNIROUTE_MODEL_FALLBACK", "fallback-model")
    monkeypatch.setattr(omniroute_client, "ask_omniroute", fake_ask)
    assert OmniRouteGateway().generate_action(None, "Open settings") == {"action": "wait"}
    assert seen == ["fast-model", "fallback-model"]


def test_omniroute_does_not_fallback_for_non_retryable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from oscar import omniroute_client

    seen: list[str] = []

    def fake_ask(_screenshot, _prompt, *, model_name=None):
        seen.append(model_name)
        raise omniroute_client.OmniRouteResponseError("bad request", retryable=False, status_code=400)

    monkeypatch.setattr(config, "OMNIROUTE_AUTO_ROUTING", True)
    monkeypatch.setattr(config, "OMNIROUTE_MODEL", "default-model")
    monkeypatch.setattr(config, "OMNIROUTE_MODEL_FAST", "fast-model")
    monkeypatch.setattr(config, "OMNIROUTE_MODEL_FALLBACK", "fallback-model")
    monkeypatch.setattr(omniroute_client, "ask_omniroute", fake_ask)
    with pytest.raises(ModelGatewayError) as error:
        OmniRouteGateway().generate_action(None, "Open settings")
    assert error.value.status_code == 400
    assert seen == ["fast-model"]


def test_planner_leaves_omniroute_model_unpinned_for_automatic_routing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import anyio
    from types import SimpleNamespace

    class RecordingGateway:
        provider_name = "omniroute"
        default_model = "default-model"

        def __init__(self):
            self.model_name = "not-called"

        def generate_action(self, _screenshot, _prompt, *, model_name=None):
            self.model_name = model_name
            return {"action": "wait"}

    monkeypatch.setattr(config, "OMNIROUTE_AUTO_ROUTING", True)
    gateway = RecordingGateway()
    planner = ModelBrain(provider=gateway)
    anyio.run(planner._ask_model, "Open settings", SimpleNamespace(screenshot=None))
    assert gateway.model_name is None


def test_explicit_planner_model_disables_automatic_role_selection() -> None:
    planner = ModelBrain(provider=OmniRouteGateway(), model_name="pinned-model")
    assert planner.model_name == "pinned-model"
    assert planner._model_name_explicit is True



def test_omniroute_preserves_token_budget_error_and_does_not_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from oscar import omniroute_client
    from oscar.token_budget import TokenBudgetExceeded

    seen = []

    def exhausted(*_args, **_kwargs):
        seen.append("request")
        raise TokenBudgetExceeded(
            "Today's configured OmniRoute token budget would be exceeded."
        )

    monkeypatch.setattr(config, "OMNIROUTE_MODEL", "default-model")
    monkeypatch.setattr(config, "OMNIROUTE_MODEL_FAST", "fast-model")
    monkeypatch.setattr(config, "OMNIROUTE_MODEL_FALLBACK", "fallback-model")
    monkeypatch.setattr(omniroute_client, "ask_omniroute", exhausted)

    with pytest.raises(ModelGatewayError, match="token budget"):
        OmniRouteGateway().generate_action(None, "Open settings")
    assert seen == ["request"]
