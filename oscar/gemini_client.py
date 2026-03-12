"""Gemini client helpers for OSCAR."""

from __future__ import annotations

import io
import json
import sys
from typing import Any

from oscar import config
from oscar.prompt_builder import SYSTEM_PROMPT


RECOMMENDED_MODEL = "gemini-2.5-flash"


class GeminiResponseError(RuntimeError):
    """Raised when Gemini cannot produce a usable action payload."""


def _load_genai():
    try:
        import google.genai as genai
    except ImportError:
        try:
            import google.generativeai as genai
        except ImportError as exc:
            raise RuntimeError(
                "A Gemini SDK is not installed for this Python interpreter "
                f"({sys.executable}). Install it in the active environment with "
                "'python -m pip install -r requirements.txt' or "
                "'python -m pip install google-genai'."
            ) from exc
    return genai


def _format_exception(exc: Exception) -> str:
    message = str(exc).strip()
    if not message:
        return exc.__class__.__name__
    return f"{exc.__class__.__name__}: {message}"


def _build_request_error_message(sdk_name: str, model_name: str, exc: Exception) -> str:
    base_message = f"Gemini request failed ({sdk_name}): {_format_exception(exc)}"
    lowered = str(exc).lower()
    if "404" in lowered and "not_found" in lowered and "model" in lowered:
        return (
            f"{base_message}. The configured GEMINI_MODEL '{model_name}' is not available. "
            f"Try GEMINI_MODEL={RECOMMENDED_MODEL}."
        )
    return base_message


def _build_legacy_image_part(screenshot: Any) -> dict[str, bytes | str]:
    buffer = io.BytesIO()
    screenshot.save(buffer, format="PNG")
    return {"mime_type": "image/png", "data": buffer.getvalue()}


def _build_new_sdk_config(genai: Any, *, temperature: float) -> Any:
    types_module = getattr(genai, "types", None)
    if types_module is not None and hasattr(types_module, "GenerateContentConfig"):
        return types_module.GenerateContentConfig(
            systemInstruction=SYSTEM_PROMPT,
            temperature=temperature,
        )

    return {
        "systemInstruction": SYSTEM_PROMPT,
        "temperature": temperature,
    }


def _build_model_backend(
    genai: Any,
    *,
    api_key: str,
    model_name: str,
    temperature: float,
):
    if hasattr(genai, "Client"):
        try:
            client = genai.Client(api_key=api_key)
            generation_config = _build_new_sdk_config(genai, temperature=temperature)
        except Exception as exc:
            raise GeminiResponseError(
                f"Failed to initialize the Gemini client (google-genai): {_format_exception(exc)}"
            ) from exc

        return (
            "google-genai",
            lambda prompt, screenshot: client.models.generate_content(
                model=model_name,
                contents=[prompt, screenshot],
                config=generation_config,
            ),
        )

    if hasattr(genai, "GenerativeModel"):
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(
                model_name=model_name,
                system_instruction=SYSTEM_PROMPT,
                generation_config={"temperature": temperature},
            )
        except Exception as exc:
            raise GeminiResponseError(
                "Failed to initialize the Gemini client (google-generativeai): "
                f"{_format_exception(exc)}"
            ) from exc

        return (
            "google-generativeai",
            lambda prompt, screenshot: model.generate_content(
                [prompt, _build_legacy_image_part(screenshot)]
            ),
        )

    raise GeminiResponseError("No supported Gemini SDK API was found.")


def _extract_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if text:
        return text

    parts: list[str] = []
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        if content is None:
            continue
        for part in getattr(content, "parts", []) or []:
            part_text = getattr(part, "text", None)
            if part_text:
                parts.append(part_text)

    return "".join(parts)


def _extract_json_text(response_text: str) -> str:
    start_index = response_text.find("{")
    end_index = response_text.rfind("}")
    if start_index == -1 or end_index == -1 or end_index < start_index:
        raise ValueError("Gemini response did not contain a JSON object.")
    return response_text[start_index : end_index + 1]


def _parse_response_text(response_text: str) -> dict[str, Any]:
    return json.loads(_extract_json_text(response_text))


def ask_gemini(
    screenshot: Any,
    prompt: str,
    *,
    model_name: str | None = None,
    api_key: str | None = None,
    temperature: float = 0.2,
    retries: int = 1,
) -> dict[str, Any]:
    """Send the current screenshot and prompt to Gemini and parse the JSON reply."""

    genai = _load_genai()
    resolved_api_key = api_key or config.require_api_key()
    resolved_model = model_name or config.GEMINI_MODEL
    sdk_name, generate_content = _build_model_backend(
        genai,
        api_key=resolved_api_key,
        model_name=resolved_model,
        temperature=temperature,
    )

    last_error: Exception | None = None

    for attempt_index in range(retries + 1):
        attempt_prompt = prompt
        if attempt_index > 0:
            attempt_prompt = (
                f"{prompt}\n\nThe previous response was invalid. Return only one valid JSON object."
            )

        try:
            response = generate_content(attempt_prompt, screenshot)
        except Exception as exc:
            raise GeminiResponseError(
                _build_request_error_message(sdk_name, resolved_model, exc)
            ) from exc

        response_text = _extract_text(response)
        try:
            return _parse_response_text(response_text)
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = exc

    raise GeminiResponseError(
        f"Gemini returned invalid JSON after {retries + 1} attempt(s)."
    ) from last_error
