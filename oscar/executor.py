"""Validation and execution of OSCAR actions."""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from oscar import config
from oscar.ui_automation import click_active_window_control
from oscar.user_paths import rewrite_known_user_paths
from oscar.window_control import (
    app_window_exists,
    build_launch_command,
    focus_app_window,
    get_active_window_info,
    normalize_app_name,
)

SUPPORTED_ACTIONS = {
    "click",
    "double_click",
    "right_click",
    "uia_click",
    "type",
    "scroll",
    "hotkey",
    "press",
    "open_app",
    "close_app",
    "save_file",
    "terminal_command",
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


def _truncate_output(value: str | None) -> str:
    text = (value or "").strip()
    limit = max(int(config.TERMINAL_OUTPUT_LIMIT), 0)
    if limit and len(text) > limit:
        return f"{text[:limit]}\n...[truncated]"
    return text


def _build_terminal_invocation(command: str) -> list[str]:
    if sys.platform == "win32":
        shell_path = (
            shutil.which("pwsh")
            or shutil.which("powershell")
            or shutil.which("powershell.exe")
            or "powershell.exe"
        )
        return [shell_path, "-NoProfile", "-NonInteractive", "-Command", command]

    shell_path = shutil.which("bash") or shutil.which("sh") or "/bin/sh"
    shell_flag = "-lc" if shell_path.endswith("bash") else "-c"
    return [shell_path, shell_flag, command]


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

    if action_name == "uia_click":
        target_text = action.get("target_text")
        automation_id = action.get("automation_id")
        control_type = action.get("control_type")
        if target_text is None and automation_id is None:
            raise ActionValidationError("uia_click actions require 'target_text' or 'automation_id'.")
        if target_text is not None:
            normalized["target_text"] = _require_non_empty_string(action, "target_text")
        if automation_id is not None:
            normalized["automation_id"] = _require_non_empty_string(action, "automation_id")
        if control_type is not None:
            normalized["control_type"] = _require_non_empty_string(action, "control_type")

    if action_name == "type":
        normalized["text"] = _require_non_empty_string(action, "text")

    if action_name == "hotkey":
        normalized["keys"] = _normalize_key_list(action.get("keys"))

    if action_name == "press":
        normalized["key"] = _normalize_key_name(_require_non_empty_string(action, "key"))

    if action_name in {"open_app", "close_app"}:
        normalized["app_name"] = normalize_app_name(_require_non_empty_string(action, "app_name"))

    if action_name == "open_app":
        normalized["new_instance"] = _require_bool(action, "new_instance", default=False)
        profile_name = action.get("profile_name")
        if profile_name is not None:
            if not isinstance(profile_name, str) or not profile_name.strip():
                raise ActionValidationError("Action field 'profile_name' must be a non-empty string.")
            normalized["profile_name"] = profile_name.strip()
        url = action.get("url")
        if url is not None:
            if not isinstance(url, str) or not url.strip():
                raise ActionValidationError("Action field 'url' must be a non-empty string.")
            normalized["url"] = url.strip()

    if action_name == "save_file":
        normalized["file_path"] = _require_non_empty_string(action, "file_path")

    if action_name == "terminal_command":
        normalized["command"] = _require_non_empty_string(action, "command")
        working_directory = action.get("working_directory")
        if working_directory is not None:
            if not isinstance(working_directory, str) or not working_directory.strip():
                raise ActionValidationError("Action field 'working_directory' must be a non-empty string.")
            normalized["working_directory"] = working_directory.strip()

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
        normalized["task_complete"] = False

    if action_name == "done" and not normalized["task_complete"]:
        raise ActionValidationError("The 'done' action must set task_complete to true.")

    return normalized


def execute_action(action: dict[str, Any]) -> dict[str, Any] | None:
    """Execute a validated action and optionally return execution metadata."""

    action_name = action["action"]
    if action_name in {"screenshot", "done"}:
        return None

    if action_name == "wait":
        time.sleep(action["seconds"])
        return None

    if action_name == "open_app":
        app_name = action["app_name"]
        should_focus_existing = (
            not action.get("new_instance")
            and not action.get("profile_name")
            and not action.get("url")
            and app_window_exists(app_name)
        )
        if should_focus_existing and focus_app_window(app_name, timeout=config.WINDOW_FOCUS_TIMEOUT):
            time.sleep(config.FOCUS_SETTLE_DELAY)
            return None

        command, spec = build_launch_command(
            app_name,
            profile_name=action.get("profile_name"),
            url=action.get("url"),
        )
        shortcut_keys = tuple(getattr(spec, "shortcut_keys", ()) or ())
        if shortcut_keys and not action.get("new_instance") and not action.get("profile_name") and not action.get("url"):
            pyautogui = _get_pyautogui()
            pyautogui.hotkey(*shortcut_keys)
            return None
        try:
            subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise ActionValidationError(f"Failed to open app '{app_name}': {exc}") from exc
        return None

    if action_name == "terminal_command":
        command_text = rewrite_known_user_paths(action["command"])
        invocation = _build_terminal_invocation(command_text)
        working_directory = action.get("working_directory")
        if working_directory is not None:
            cwd = Path(rewrite_known_user_paths(working_directory)).expanduser()
            if not cwd.exists() or not cwd.is_dir():
                raise ActionValidationError(
                    f"Working directory '{cwd}' does not exist or is not a directory."
                )
        else:
            cwd = None

        try:
            completed = subprocess.run(
                invocation,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=str(cwd) if cwd is not None else None,
                timeout=config.TERMINAL_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "command": command_text,
                "command_exit_code": -1,
                "command_stdout": _truncate_output(exc.stdout),
                "command_stderr": _truncate_output((exc.stderr or "") + f"\nCommand timed out after {config.TERMINAL_TIMEOUT_SECONDS} seconds."),
                "execution_confirmed": False,
            }
        except OSError as exc:
            raise ActionValidationError(f"Failed to run terminal command: {exc}") from exc

        return {
            "command": command_text,
            "command_exit_code": completed.returncode,
            "command_stdout": _truncate_output(completed.stdout),
            "command_stderr": _truncate_output(completed.stderr),
            "execution_confirmed": completed.returncode == 0,
        }

    if action_name == "uia_click":
        clicked = click_active_window_control(
            target_text=action.get("target_text"),
            control_type=action.get("control_type"),
            automation_id=action.get("automation_id"),
        )
        if not clicked:
            raise ActionValidationError("Failed to find or click the requested UI automation control.")
        return None

    pyautogui = _get_pyautogui()

    if action_name == "close_app":
        app_name = action["app_name"]
        if not app_window_exists(app_name):
            return None
        if not focus_app_window(app_name, timeout=config.WINDOW_FOCUS_TIMEOUT):
            active_window = get_active_window_info()
            raise ActionValidationError(
                f"Failed to focus '{app_name}' before closing; active window is "
                f"'{active_window.get('title') or 'Unknown'}' ({active_window.get('process_name') or 'Unknown'})."
            )
        time.sleep(config.FOCUS_SETTLE_DELAY)
        pyautogui.hotkey("alt", "f4")
        return None

    if action_name == "click":
        pyautogui.click(x=action["x"], y=action["y"])
        return None

    if action_name == "double_click":
        pyautogui.doubleClick(x=action["x"], y=action["y"])
        return None

    if action_name == "right_click":
        pyautogui.rightClick(x=action["x"], y=action["y"])
        return None

    if action_name == "type":
        pyautogui.typewrite(action["text"], interval=config.TYPEWRITE_INTERVAL)
        return None

    if action_name == "hotkey":
        pyautogui.hotkey(*action["keys"])
        return None

    if action_name == "press":
        pyautogui.press(action["key"])
        return None

    if action_name == "save_file":
        file_path = Path(rewrite_known_user_paths(action["file_path"])).expanduser()
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ActionValidationError(
                f"Failed to prepare save directory '{file_path.parent}': {exc}"
            ) from exc

        pyautogui.hotkey("ctrl", "s")
        time.sleep(config.SAVE_DIALOG_DELAY)
        pyautogui.hotkey("ctrl", "a")
        time.sleep(config.ACTION_DELAY)
        pyautogui.typewrite(str(file_path), interval=config.TYPEWRITE_INTERVAL)
        time.sleep(config.ACTION_DELAY)
        pyautogui.press("enter")
        return {"file_path": str(file_path)}

    if action_name == "scroll":
        clicks = action["amount"] if action["direction"] == "up" else -action["amount"]
        pyautogui.scroll(clicks, x=action["x"], y=action["y"])
        return None

    raise ActionValidationError(f"Unsupported action '{action_name}'.")
