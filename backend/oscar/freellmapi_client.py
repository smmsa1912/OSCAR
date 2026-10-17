"""OpenAI-compatible client for an FreeLLMAPI gateway.

Uses the standard library and FreeLLMAPI OpenAI-compatible endpoint.
Configure ``FREELLMAPI_BASE_URL`` as the API prefix (usually ending in ``/v1``).
"""
from __future__ import annotations

import base64
import io
import json
import urllib.error
import urllib.request
from typing import Any

from oscar import config
from oscar.diagnostics import sanitize_text
from oscar.prompt_builder import SYSTEM_PROMPT
from oscar.token_budget import estimate_text_tokens, reserve_request, settle_request
from oscar.utils.logging import get_logger, log_event

LOGGER = get_logger("freellmapi_client")


class FreeLLMAPIResponseError(RuntimeError):
    """Raised when FreeLLMAPI cannot return a valid action object."""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
    ) -> None:
        self.retryable = retryable
        self.status_code = status_code
        super().__init__(sanitize_text(message))


def _endpoint(base_url: str, suffix: str) -> str:
    base = base_url.strip().rstrip("/")
    if not base:
        raise FreeLLMAPIResponseError("FREELLMAPI_BASE_URL is not configured.")
    if base.endswith(suffix):
        return base
    return f"{base}/{suffix.lstrip('/')}"


def _image_data_url(image: Any) -> str | None:
    """Downscale and JPEG-compress screenshots before sending them to cloud models."""
    if image is None:
        return None
    try:
        # Pillow images support convert/thumbnail; the PNG fallback keeps the
        # helper usable with lightweight test doubles and compatible image wrappers.
        if hasattr(image, "size") and hasattr(image, "convert"):
            prepared = image.convert("RGB")
            prepared.thumbnail(
                (config.FREELLMAPI_MAX_IMAGE_DIMENSION, config.FREELLMAPI_MAX_IMAGE_DIMENSION)
            )
            buffer = io.BytesIO()
            prepared.save(buffer, format="JPEG", quality=75, optimize=True)
            encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
            return f"data:image/jpeg;base64,{encoded}"
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/png;base64,{encoded}"
    except Exception as exc:
        raise FreeLLMAPIResponseError("Could not encode screenshot for FreeLLMAPI.") from exc


def _bounded_prompt(prompt: str) -> str:
    """Bound prompt size while retaining task instructions and recent context."""
    limit = config.FREELLMAPI_MAX_PROMPT_CHARS
    if len(prompt) <= limit:
        return prompt
    marker = "\n[Earlier context omitted to respect OSCAR's prompt-size limit.]\n"
    available = max(0, limit - len(marker))
    head = int(available * 0.55)
    tail = available - head
    return prompt[:head] + marker + (prompt[-tail:] if tail else "")


def _extract_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    if start >= 0:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if escaped:
                escaped = False
                continue
            if char == "\\" and in_string:
                escaped = True
                continue
            if char == '"':
                in_string = not in_string
            elif not in_string and char == "{":
                depth += 1
            elif not in_string and char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(text[start:index + 1])
                        if isinstance(parsed, dict):
                            return parsed
                    except json.JSONDecodeError:
                        break
    raise FreeLLMAPIResponseError("FreeLLMAPI response did not contain a valid JSON object.")


def _request_json(url: str, *, method: str = "GET", payload: dict[str, Any] | None = None,
                  timeout: float | None = None) -> dict[str, Any]:
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if config.FREELLMAPI_API_KEY:
        headers["Authorization"] = f"Bearer {config.FREELLMAPI_API_KEY}"
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    request_timeout = config.FREELLMAPI_TIMEOUT_SECONDS if timeout is None else timeout
    try:
        with urllib.request.urlopen(request, timeout=request_timeout) as response:
            decoded = json.loads(response.read().decode("utf-8"))
        if not isinstance(decoded, dict):
            raise FreeLLMAPIResponseError("FreeLLMAPI returned an unexpected API response format.")
        return decoded
    except urllib.error.HTTPError as exc:
        # Do not echo server response bodies: they can contain request or credential data.
        retryable = exc.code in {408, 425, 429} or 500 <= exc.code <= 599
        raise FreeLLMAPIResponseError(
            f"FreeLLMAPI returned HTTP {exc.code}.",
            retryable=retryable,
            status_code=exc.code,
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        # Avoid echoing the configured URL: it may contain sensitive query parameters.
        raise FreeLLMAPIResponseError(
            f"Could not reach FreeLLMAPI endpoint ({exc.__class__.__name__}).",
            retryable=True,
        ) from exc
    except json.JSONDecodeError as exc:
        raise FreeLLMAPIResponseError("FreeLLMAPI returned invalid JSON from its API endpoint.") from exc


def ask_freellmapi(
    screenshot: Any | None,
    prompt: str,
    *,
    model_name: str | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Request one structured action from an OpenAI-compatible chat endpoint."""
    model = (model_name or config.FREELLMAPI_MODEL).strip()
    if not model:
        raise FreeLLMAPIResponseError("FREELLMAPI_MODEL is not configured.")

    bounded_prompt = _bounded_prompt(prompt)
    user_content: Any = bounded_prompt
    image_url = _image_data_url(screenshot)
    if image_url:
        user_content = [
            {"type": "text", "text": bounded_prompt},
            {"type": "image_url", "image_url": {"url": image_url}},
        ]
    system_prompt = SYSTEM_PROMPT + "\nReturn exactly one JSON object."
    image_tokens = 1200 if image_url else 0
    estimated_input = estimate_text_tokens(system_prompt + bounded_prompt) + image_tokens
    estimated_request = estimated_input + config.FREELLMAPI_MAX_OUTPUT_TOKENS
    if estimated_request > config.FREELLMAPI_MAX_REQUEST_TOKENS:
        raise FreeLLMAPIResponseError(
            f"OSCAR blocked this FreeLLMAPI request: estimated size {estimated_request} "
            f"tokens exceeds FREELLMAPI_MAX_REQUEST_TOKENS "
            f"({config.FREELLMAPI_MAX_REQUEST_TOKENS}). Reduce prompt/image size or adjust "
            "the FreeLLMAPI request cap if appropriate."
        )
    endpoint = _endpoint(config.FREELLMAPI_BASE_URL, "/chat/completions")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.2,
        "max_tokens": config.FREELLMAPI_MAX_OUTPUT_TOKENS,
        "response_format": {"type": "json_object"},
    }
    reservation = reserve_request(
        estimated_input,
        config.FREELLMAPI_MAX_OUTPUT_TOKENS,
    )
    try:
        body = _request_json(endpoint, method="POST", payload=payload, timeout=timeout)
    except Exception:
        # Keep the conservative reservation and make its status visible in the
        # local ledger; a failed response is not proof the gateway did not bill.
        settle_request(
            reservation, None, model_name=model, outcome="failed_or_unknown"
        )
        raise
    usage = body.get("usage")
    actual_tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
    if not isinstance(actual_tokens, int) or actual_tokens <= 0:
        prompt_tokens = usage.get("prompt_tokens") if isinstance(usage, dict) else None
        completion_tokens = usage.get("completion_tokens") if isinstance(usage, dict) else None
        if (
            isinstance(prompt_tokens, int) and prompt_tokens > 0
            and isinstance(completion_tokens, int) and completion_tokens >= 0
        ):
            actual_tokens = prompt_tokens + completion_tokens
        else:
            actual_tokens = None
    settle_request(reservation, actual_tokens, model_name=model, outcome="success")
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise FreeLLMAPIResponseError("FreeLLMAPI returned an unexpected chat-completion response.") from exc
    if isinstance(content, list):
        content = "\n".join(
            item.get("text", "") for item in content if isinstance(item, dict)
        )
    if not isinstance(content, str):
        raise FreeLLMAPIResponseError("FreeLLMAPI returned an unsupported message content format.")
    action = _extract_json_object(content)
    log_event(LOGGER, "llm_response", provider="freellmapi", model=model, action=action.get("action"))
    return action


def list_freellmapi_models(*, timeout: float | None = None) -> list[dict[str, Any]]:
    """Return models exposed by the configured gateway's OpenAI-compatible API."""
    endpoint = _endpoint(config.FREELLMAPI_BASE_URL, "/models")
    body = _request_json(endpoint, timeout=timeout)
    data = body.get("data")
    if not isinstance(data, list):
        raise FreeLLMAPIResponseError("FreeLLMAPI models endpoint returned an unexpected response.")
    return [item for item in data if isinstance(item, dict)]
