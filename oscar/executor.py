"""Validation and execution of OSCAR actions."""

from __future__ import annotations

import subprocess
import sys
import time
from typing import Any

SUPPORTED_ACTIONS = {
    "click",
    "double_click",
    "right_click",
    "type",
    "scroll",
    "hotkey",
    "press",
    "open_app",
    "screenshot",
    "wait",
    "done",
}

KEY_ALIASES = {
    "control": "ctrl",
    "cmd": "winleft" if sys.platform == "win32" else "command",
    "command": "winleft" if sys.platform == "win32" else "command",
    "option": "alt",
    "return": "enter",
    "spacebar": "space",
    "win": "winleft",
    "windows": "winleft",
}


class ActionValidationError(ValueError):
    """Raised when a model action is not safe to execute."""


def _get_pyautogui():
    try:
        import pyautogui
    except Exception as exc:  # pragma: no cover - dependency/platform specific
        raise RuntimeError("pyautogui is required for action execution.") from exc
    return pyautogui


def _normalize_key_name(key: str) -> str:
    cleaned_key = key.strip().lower()
    return KEY_ALIASES.get(cleaned_key, cleaned_key)


def _open_app(app_name: str) -> None:
    try:
        if sys.platform == "win32":
            subprocess.Popen(
                ["cmd", "/c", "start", "", app_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            subprocess.Popen(
                [app_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except OSError as exc:
        raise ActionValidationError(f"Failed to open app '{app_name}': {exc}") from exc


def _require_non_empty_string(action: dict[str, Any], key: str) -> str:
    value = action.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ActionValidationError(f"Action field '{key}' must be a non-empty string.")
    return value.strip()


def _require_bool(action: dict[str, Any], key: str, *, default: bool | None = None) -> bool:
    value = action.get(key)
    if value is None and default is not None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "false"}:
            return lowered == "true"
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value in {0, 1}:
        return bool(value)
    raise ActionValidationError(f"Action field '{key}' must be a boolean.")


def _require_number(action: dict[str, Any], key: str) -> int | float:
    value = action.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ActionValidationError(f"Action field '{key}' must be numeric.")
    return value


def _require_coordinate(
    action: dict[str, Any],
    key: str,
    screen_size: tuple[int, int] | None,
) -> int:
    value = _require_number(action, key)
    coordinate = int(value)
    if screen_size is not None:
        width, height = screen_size
        limit = width if key == "x" else height
        if coordinate < 0 or coordinate >= limit:
            raise ActionValidationError(
                f"Action field '{key}'={coordinate} is outside the current screen bounds."
            )
    return coordinate


def _normalize_key_list(keys: Any) -> list[str]:
    if not isinstance(keys, list) or not keys:
        raise ActionValidationError("Hotkey actions require a non-empty 'keys' list.")

    cleaned_keys = []
    for key in keys:
        if not isinstance(key, str) or not key.strip():
            raise ActionValidationError("Hotkey keys must be non-empty strings.")
        cleaned_keys.append(_normalize_key_name(key))
    return cleaned_keys


def validate_action(
    action: dict[str, Any],
    screen_size: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """Validate and normalize a model action before execution."""

    if not isinstance(action, dict):
        raise ActionValidationError("Gemini response must be a JSON object.")

    action_name = action.get("action")
    if action_name not in SUPPORTED_ACTIONS:
        raise ActionValidationError(f"Unsupported action '{action_name}'.")

    normalized: dict[str, Any] = {
        "action": action_name,
        "reasoning": _require_non_empty_string(action, "reasoning"),
        "task_complete": _require_bool(action, "task_complete", default=False),
    }

    if action_name in {"click", "double_click", "right_click", "scroll"}:
        normalized["x"] = _require_coordinate(action, "x", screen_size)
        normalized["y"] = _require_coordinate(action, "y", screen_size)

    if action_name == "type":
        normalized["text"] = _require_non_empty_string(action, "text")

    if action_name == "hotkey":
        normalized["keys"] = _normalize_key_list(action.get("keys"))

    if action_name == "press":
        normalized["key"] = _normalize_key_name(_require_non_empty_string(action, "key"))

    if action_name == "open_app":
        normalized["app_name"] = _require_non_empty_string(action, "app_name")

    if action_name == "scroll":
        direction = _require_non_empty_string(action, "direction").lower()
        if direction not in {"up", "down"}:
            raise ActionValidationError("Scroll direction must be 'up' or 'down'.")
        amount = int(_require_number(action, "amount"))
        if amount <= 0:
            raise ActionValidationError("Scroll amount must be greater than zero.")
        normalized["direction"] = direction
        normalized["amount"] = amount

    if action_name == "wait":
        seconds = float(_require_number(action, "seconds"))
        if seconds < 0:
            raise ActionValidationError("Wait seconds must be non-negative.")
        normalized["seconds"] = seconds

    if normalized["task_complete"] and action_name != "done":
        raise ActionValidationError("task_complete can only be true when action is 'done'.")

    if action_name == "done" and not normalized["task_complete"]:
        raise ActionValidationError("The 'done' action must set task_complete to true.")

    return normalized


def execute_action(action: dict[str, Any]) -> None:
    """Execute a validated action."""

    action_name = action["action"]
    if action_name in {"screenshot", "done"}:
        return

    if action_name == "wait":
        time.sleep(action["seconds"])
        return

    if action_name == "open_app":
        _open_app(action["app_name"])
        return

    pyautogui = _get_pyautogui()

    if action_name == "click":
        pyautogui.click(x=action["x"], y=action["y"])
        return

    if action_name == "double_click":
        pyautogui.doubleClick(x=action["x"], y=action["y"])
        return

    if action_name == "right_click":
        pyautogui.rightClick(x=action["x"], y=action["y"])
        return

    if action_name == "type":
        pyautogui.typewrite(action["text"], interval=0.05)
        return

    if action_name == "hotkey":
        pyautogui.hotkey(*action["keys"])
        return

    if action_name == "press":
        pyautogui.press(action["key"])
        return

    if action_name == "scroll":
        clicks = action["amount"] if action["direction"] == "up" else -action["amount"]
        pyautogui.scroll(clicks, x=action["x"], y=action["y"])
        return

    raise ActionValidationError(f"Unsupported action '{action_name}'.")
