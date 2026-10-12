"""Provider-neutral action-model interface and configured gateway factory.

The planner depends on this small contract rather than a specific vendor SDK.
Provider selection remains explicit through ``LLM_PROVIDER``. When OmniRoute is
selected, optional role-specific model IDs enable conservative task-based routing.
"""
from __future__ import annotations

from typing import Any, Protocol

from oscar import config
from oscar.diagnostics import sanitize_text
from oscar.token_budget import TokenBudgetExceeded


class ModelGatewayError(RuntimeError):
    """Normalized provider failure safe to surface to the planner and logs."""

    def __init__(
        self,
        provider: str,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
    ) -> None:
        self.provider = provider
        self.retryable = retryable
        self.status_code = status_code
        super().__init__(sanitize_text(message))


class ActionModelGateway(Protocol):
    """Contract implemented by each model provider adapter."""

    provider_name: str
    default_model: str

    def generate_action(
        self,
        screenshot: Any | None,
        prompt: str,
        *,
        model_name: str | None = None,
    ) -> dict[str, Any]:
        """Return one structured action dictionary."""


class GeminiGateway:
    provider_name = "gemini"

    def __init__(self) -> None:
        self.default_model = config.GEMINI_MODEL

    def generate_action(
        self,
        screenshot: Any | None,
        prompt: str,
        *,
        model_name: str | None = None,
    ) -> dict[str, Any]:
        from oscar.gemini_client import GeminiResponseError, ask_gemini

        try:
            return ask_gemini(screenshot, prompt, model_name=model_name or self.default_model)
        except Exception as exc:
            retryable = bool(getattr(exc, "retryable", False))
            status_code = getattr(exc, "status_code", None)
            message = str(exc) if isinstance(exc, GeminiResponseError) else (
                f"{exc.__class__.__name__} while requesting Gemini."
            )
            raise ModelGatewayError(
                self.provider_name,
                message,
                retryable=retryable,
                status_code=status_code,
            ) from exc


class OmniRouteGateway:
    provider_name = "omniroute"

    def __init__(self) -> None:
        self.default_model = config.OMNIROUTE_MODEL

    @staticmethod
    def select_model(screenshot: Any | None, prompt: str) -> str:
        """Select a configured role model without guessing model capabilities.

        Screenshot requests prefer the explicitly configured vision model. Text
        requests with clear multi-step/analysis cues prefer the reasoning model;
        other text requests prefer the fast model. Missing role IDs fall back to
        the single configured default model.
        """
        if not config.OMNIROUTE_AUTO_ROUTING:
            selected = config.OMNIROUTE_MODEL
        elif screenshot is not None:
            selected = config.OMNIROUTE_MODEL_VISION or config.OMNIROUTE_MODEL
        else:
            text = prompt.lower()
            reasoning_cues = (
                "step by step", "compare", "analyze", "analyse", "debug",
                "plan", "multi-step", "multiple steps", "why does",
                "investigate", "troubleshoot", "complex",
            )
            selected = (
                config.OMNIROUTE_MODEL_REASONING
                if any(cue in text for cue in reasoning_cues)
                else config.OMNIROUTE_MODEL_FAST
            ) or config.OMNIROUTE_MODEL
        if not selected:
            raise ModelGatewayError(
                "omniroute",
                "No OmniRoute model is configured. Set OMNIROUTE_MODEL or a role-specific model ID.",
            )
        return selected

    def generate_action(
        self,
        screenshot: Any | None,
        prompt: str,
        *,
        model_name: str | None = None,
    ) -> dict[str, Any]:
        from oscar.omniroute_client import OmniRouteResponseError, ask_omniroute

        selected_model = model_name or self.select_model(screenshot, prompt)
        try:
            return ask_omniroute(screenshot, prompt, model_name=selected_model)
        except Exception as exc:
            retryable = bool(getattr(exc, "retryable", False))
            status_code = getattr(exc, "status_code", None)
            # Only fail over on errors explicitly classified as transient. Do not
            # change models after malformed output or non-retryable request errors.
            fallback_model = config.OMNIROUTE_MODEL_FALLBACK
            if retryable and fallback_model and fallback_model != selected_model:
                try:
                    return ask_omniroute(screenshot, prompt, model_name=fallback_model)
                except Exception as fallback_exc:
                    exc = fallback_exc
                    retryable = bool(getattr(exc, "retryable", False))
                    status_code = getattr(exc, "status_code", None)
            message = str(exc) if isinstance(
                exc, (OmniRouteResponseError, TokenBudgetExceeded)
            ) else f"{exc.__class__.__name__} while requesting OmniRoute."
            raise ModelGatewayError(
                self.provider_name,
                message,
                retryable=retryable,
                status_code=status_code,
            ) from exc


def create_model_gateway(provider_name: str | None = None) -> ActionModelGateway:
    """Create the explicitly configured provider adapter."""
    selected = (provider_name or config.LLM_PROVIDER).strip().lower()
    if selected == "gemini":
        return GeminiGateway()
    if selected == "omniroute":
        return OmniRouteGateway()
    raise ValueError(
        f"Unsupported LLM_PROVIDER {selected!r}; choose 'gemini' or 'omniroute'."
    )
