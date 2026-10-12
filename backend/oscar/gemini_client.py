"""Gemini client helpers for OSCAR."""

from __future__ import annotations

import io
import json
import sys
import time
from typing import Any

from oscar import config
from oscar.prompt_builder import SYSTEM_PROMPT
from oscar.utils.logging import get_logger, log_event
from oscar.vision.refinement import normalize_grid_coordinate


RECOMMENDED_MODEL = "gemini-2.5-flash"

LOGGER = get_logger("gemini_client")


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


def _build_new_sdk_config(genai: Any, *, system_prompt: str, temperature: float) -> Any:
    types_module = getattr(genai, "types", None)
    if types_module is not None and hasattr(types_module, "GenerateContentConfig"):
        return types_module.GenerateContentConfig(
            systemInstruction=system_prompt,
            temperature=temperature,
            response_mime_type="application/json",
        )

    return {
        "systemInstruction": system_prompt,
        "temperature": temperature,
        "response_mime_type": "application/json",
    }


def _build_model_backend(
    genai: Any,
    *,
    api_key: str,
    model_name: str,
    temperature: float,
    system_prompt: str,
    timeout_seconds: float,
):
    if hasattr(genai, "Client"):
        try:
            types_module = getattr(genai, "types", None)
            client_kwargs: dict[str, Any] = {"api_key": api_key}
            if types_module is not None and hasattr(types_module, "HttpOptions"):
                client_kwargs["http_options"] = types_module.HttpOptions(
                    timeout=int(timeout_seconds * 1000)
                )
            client = genai.Client(**client_kwargs)
            generation_config = _build_new_sdk_config(
                genai,
                system_prompt=system_prompt,
                temperature=temperature,
            )
        except Exception as exc:
            raise GeminiResponseError(
                f"Failed to initialize the Gemini client (google-genai): {_format_exception(exc)}"
            ) from exc

        return (
            "google-genai",
            lambda prompt, screenshot: client.models.generate_content(
                model=model_name,
                contents=[item for item in [prompt, screenshot] if item is not None],
                config=generation_config,
            ),
        )

    if hasattr(genai, "GenerativeModel"):
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(
                model_name=model_name,
                system_instruction=system_prompt,
                generation_config={
                    "temperature": temperature,
                    "response_mime_type": "application/json",
                },
            )
        except Exception as exc:
            raise GeminiResponseError(
                "Failed to initialize the Gemini client (google-generativeai): "
                f"{_format_exception(exc)}"
            ) from exc

        return (
            "google-generativeai",
            lambda prompt, screenshot: model.generate_content(
                [prompt]
                if screenshot is None
                else [prompt, _build_legacy_image_part(screenshot)],
                request_options={"timeout": timeout_seconds},
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

import re as _re

_JSON_FENCE_PATTERN = _re.compile(
    r"```(?:json)?\s*\n?(.*?)\n?\s*```",
    _re.DOTALL,
)


def _is_valid_json(text: str) -> bool:
    """Return whether *text* is parseable as a JSON object."""
    try:
        result = json.loads(text)
        return isinstance(result, dict)
    except (json.JSONDecodeError, ValueError):
        return False


def _extract_balanced_braces(text: str) -> str | None:
    """Find the first balanced ``{ ... }`` block via brace counting.

    Correctly handles quoted strings and escape sequences so nested
    JSON objects don't short-circuit the search.
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i, ch in enumerate(text[start:], start):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _extract_json_text(response_text: str) -> str:
    """Extract a JSON object from a raw LLM response.

    Uses three strategies in order:
    1. Look for \\`\\`\\`json fenced blocks.
    2. Balanced-brace extraction (handles nested JSON + quoted strings).
    3. Simple first-'{' / last-'}' fallback.
    """
    # Strategy 1: fenced code block
    fence_match = _JSON_FENCE_PATTERN.search(response_text)
    if fence_match:
        candidate = fence_match.group(1).strip()
        if _is_valid_json(candidate):
            return candidate

    # Strategy 2: balanced brace extraction
    balanced = _extract_balanced_braces(response_text)
    if balanced and _is_valid_json(balanced):
        return balanced

    # Strategy 3: legacy first/last brace (least reliable)
    start_index = response_text.find("{")
    end_index = response_text.rfind("}")
    if start_index != -1 and end_index != -1 and end_index >= start_index:
        candidate = response_text[start_index : end_index + 1]
        if _is_valid_json(candidate):
            return candidate

    raise ValueError("Gemini response did not contain a valid JSON object.")


def _parse_response_text(response_text: str) -> dict[str, Any]:
    return json.loads(_extract_json_text(response_text))


def _is_transient_request_error(exc: Exception) -> bool:
    lowered = str(exc).lower()
    return any(
        token in lowered
        for token in (
            "429",
            "500",
            "502",
            "503",
            "504",
            "service unavailable",
            "temporarily unavailable",
            "backend error",
            "resource exhausted",
        )
    )


def _generate_json_response(
    generate_content,
    *,
    prompt: str,
    screenshot: Any,
    retries: int,
) -> dict[str, Any]:
    last_error: Exception | None = None
    retry_interval = max(config.RETRY_INITIAL_INTERVAL_SECONDS, 0.05)

    for attempt_index in range(retries + 1):
        attempt_prompt = prompt
        if attempt_index > 0:
            attempt_prompt = f"{prompt}\n\nThe previous response was invalid. Return only one valid JSON object."

        try:
            response = generate_content(attempt_prompt, screenshot)
        except Exception as exc:
            last_error = exc
            if attempt_index >= retries or not _is_transient_request_error(exc):
                raise
            time.sleep(retry_interval)
            retry_interval = min(
                retry_interval * max(config.RETRY_BACKOFF_FACTOR, 1.0),
                max(config.RETRY_MAX_INTERVAL_SECONDS, retry_interval),
            )
            continue
        response_text = _extract_text(response)
        try:
            return _parse_response_text(response_text)
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = exc

    raise GeminiResponseError(
        f"Gemini returned invalid JSON after {retries + 1} attempt(s)."
    ) from last_error


def ask_gemini(
    screenshot: Any | None,
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
        system_prompt=SYSTEM_PROMPT,
        timeout_seconds=config.GEMINI_TIMEOUT_SECONDS,
    )

    try:
        response = _generate_json_response(
            generate_content,
            prompt=prompt,
            screenshot=screenshot,
            retries=retries,
        )
        log_event(LOGGER, "llm_response", model=resolved_model, action=response.get("action"))
        return response
    except GeminiResponseError:
        raise
    except Exception as exc:
        log_event(LOGGER, "llm_error", model=resolved_model, error=str(exc))
        raise GeminiResponseError(
            _build_request_error_message(sdk_name, resolved_model, exc)
        ) from exc


def refine_click_action(
    screenshot: Any,
    action: dict[str, Any],
    *,
    model_name: str | None = None,
    api_key: str | None = None,
    temperature: float = 0.0,
    retries: int = 0,
) -> dict[str, Any]:
    """Normalize coordinate fallbacks without recomputing brittle pixel offsets."""

    del model_name, api_key, temperature, retries
    if action.get("element_id") is not None or screenshot is None:
        return action
    if action.get("x") is None or action.get("y") is None:
        return action

    width, height = getattr(screenshot, "size", (None, None))
    if not isinstance(width, int) or not isinstance(height, int):
        return action

    refined = dict(action)
    refined["x"] = normalize_grid_coordinate(refined["x"], width)
    refined["y"] = normalize_grid_coordinate(refined["y"], height)
    return refined
