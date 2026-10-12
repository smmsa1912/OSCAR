"""OpenAI-compatible client for an OmniRoute gateway.

The client deliberately uses the standard library so OmniRoute support does not
add another runtime dependency. The gateway must expose a chat-completions
compatible endpoint (normally ``/v1/chat/completions``).
"""
from __future__ import annotations

import base64
import io
import json
import urllib.error
import urllib.request
from typing import Any

from oscar import config
from oscar.prompt_builder import SYSTEM_PROMPT
from oscar.utils.logging import get_logger, log_event

LOGGER = get_logger("omniroute_client")


class OmniRouteResponseError(RuntimeError):
    """Raised when the OmniRoute gateway cannot return a valid action object."""


def _image_data_url(image: Any) -> str | None:
    if image is None:
        return None
    try:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/png;base64,{encoded}"
    except Exception as exc:
        raise OmniRouteResponseError("Could not encode screenshot for OmniRoute.") from exc


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
    # Allow harmless prose around a JSON object, while requiring a valid object.
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
    raise OmniRouteResponseError("OmniRoute response did not contain a valid JSON object.")


def ask_omniroute(
    screenshot: Any | None,
    prompt: str,
    *,
    model_name: str | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Request a JSON action from OmniRoute's OpenAI-compatible API."""
    base_url = config.OMNIROUTE_BASE_URL.rstrip("/")
    model = (model_name or config.OMNIROUTE_MODEL).strip()
    if not base_url:
        raise OmniRouteResponseError("OMNIROUTE_BASE_URL is not configured.")
    if not model:
        raise OmniRouteResponseError("OMNIROUTE_MODEL is not configured.")

    user_content: Any = prompt
    image_url = _image_data_url(screenshot)
    if image_url:
        user_content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": image_url}},
        ]
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT + "\nReturn exactly one JSON object."},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if config.OMNIROUTE_API_KEY:
        headers["Authorization"] = f"Bearer {config.OMNIROUTE_API_KEY}"
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout or config.OMNIROUTE_TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "\n".join(
                item.get("text", "") for item in content if isinstance(item, dict)
            )
        if not isinstance(content, str):
            raise OmniRouteResponseError("OmniRoute returned an unsupported message content format.")
        action = _extract_json_object(content)
        log_event(LOGGER, "llm_response", provider="omniroute", model=model, action=action.get("action"))
        return action
    except urllib.error.HTTPError as exc:
        # Do not include request headers or credential material in diagnostics.
        detail = exc.read(1000).decode("utf-8", errors="replace")
        raise OmniRouteResponseError(
            f"OmniRoute HTTP {exc.code} from {base_url}: {detail or exc.reason}"
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise OmniRouteResponseError(
            f"Could not reach OmniRoute at {base_url}: {exc.__class__.__name__}"
        ) from exc
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise OmniRouteResponseError("OmniRoute returned an unexpected API response format.") from exc
