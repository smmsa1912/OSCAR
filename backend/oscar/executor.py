"""Validation and execution of OSCAR actions."""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta
from typing import Any

from oscar import config
from oscar.execution.files import execute_open_file, execute_save_file
from oscar.execution.windows import (
    execute_focus_app,
    execute_open_app,
    execute_window_hotkey_action,
)
from oscar.ui_automation import (
    capture_active_window_controls,
    get_last_ui_automation_error,
    invoke_active_window_control,
    focus_visible_search_input,
    resolve_active_window_control,
    uia_get_visible_elements,
)
from oscar.user_paths import rewrite_known_user_paths
from oscar.utils.retry import RetryPolicy, wait_for_condition
from oscar.vision.refinement import refined_box_center
from oscar.window_control import (
    app_window_exists,
    build_launch_command,
    focus_app_window,
    is_oscar_app_name,
    is_protected_control_window,
    get_active_window_info,
    normalize_app_name,
)

SUPPORTED_ACTIONS = {
    "browser_open",
    "browser_navigate",
    "browser_get_tabs",
    "browser_search",
    "browser_switch_tab",
    "browser_click",
    "browser_find",
    "browser_type",
    "browser_wait_for",
    "browser_extract",
    "shortcut",
    "ui_click",
    "click",
    "double_click",
    "right_click",
    "uia_click",
    "uia_get_visible_elements",
    "uia_click_fallback_search",
    "type",
    "scroll",
    "hotkey",
    "press",
    "open_app",
    "focus_app",
    "open_file",
    "new_document",
    "close_tab",
    "close_app",
    "save_file",
    "terminal_command",
    "screenshot",
    "wait",
    "wait_until",
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
    config.enable_windows_dpi_awareness()
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


def _require_string_or_string_list(
    action: dict[str, Any],
    key: str,
) -> str | list[str]:
    value = action.get(key)
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            raise ActionValidationError(f"Action field '{key}' must be a non-empty string or list of strings.")
        return cleaned
    if isinstance(value, list) and value:
        cleaned_items: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ActionValidationError(
                    f"Action field '{key}' must contain only non-empty strings."
                )
            cleaned_items.append(item.strip())
        return cleaned_items
    raise ActionValidationError(
        f"Action field '{key}' must be a non-empty string or list of strings."
    )


def _require_bool(
    action: dict[str, Any], key: str, *, default: bool | None = None
) -> bool:
    value = action.get(key)
    if value is None and default is not None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "false"}:
            return lowered == "true"
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value in {0, 1}
    ):
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
        if value < 0:
            raise ActionValidationError(
                f"Action field '{key}'={value} is outside the current screen bounds."
            )
        if coordinate <= 1000:
            coordinate = int((float(value) / 1000.0) * limit)
            if limit > 0:
                coordinate = max(0, min(coordinate, limit - 1))
        if coordinate < 0 or coordinate >= limit:
            raise ActionValidationError(
                f"Action field '{key}'={coordinate} is outside the current screen bounds."
            )
    return coordinate


def _require_element_id(action: dict[str, Any], key: str = "element_id") -> int:
    value = action.get(key)
    if isinstance(value, bool):
        raise ActionValidationError(f"Action field '{key}' must be a positive integer.")
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            value = int(stripped)
    if not isinstance(value, (int, float)):
        raise ActionValidationError(f"Action field '{key}' must be a positive integer.")
    element_id = int(value)
    if element_id <= 0:
        raise ActionValidationError(f"Action field '{key}' must be greater than zero.")
    return element_id


def _resolve_element_control(element_id: int) -> dict[str, Any]:
    control = resolve_active_window_control(element_id=element_id)
    if control is None:
        raise ActionValidationError(
            f"Could not find a visible UI control for element_id={element_id}."
        )
    return control


def _center_of_control(control: dict[str, Any]) -> tuple[int, int]:
    return refined_box_center(control)


def _hydrate_action_from_element_id(action: dict[str, Any]) -> dict[str, Any]:
    if action.get("element_id") is None:
        return action

    control = _resolve_element_control(int(action["element_id"]))
    updated = dict(action)
    updated.setdefault("target_text", control.get("text") or None)
    updated.setdefault("automation_id", control.get("automation_id") or None)
    updated.setdefault("control_type", control.get("control_type") or None)

    if updated.get("action") in {"click", "double_click", "right_click", "scroll", "ui_click"}:
        center_x, center_y = _center_of_control(control)
        updated.setdefault("x", center_x)
        updated.setdefault("y", center_y)

    return updated


def _normalize_key_list(keys: Any) -> list[str]:
    if not isinstance(keys, list) or not keys:
        raise ActionValidationError("Hotkey actions require a non-empty 'keys' list.")

    cleaned_keys = []
    for key in keys:
        if not isinstance(key, str) or not key.strip():
            raise ActionValidationError("Hotkey keys must be non-empty strings.")
        cleaned_keys.append(_normalize_key_name(key))
    return cleaned_keys


def _parse_wait_until(action: dict[str, Any]) -> datetime:
    timestamp = action.get("timestamp")
    if isinstance(timestamp, str) and timestamp.strip():
        return datetime.fromisoformat(timestamp.strip())

    time_of_day = action.get("time_of_day")
    if isinstance(time_of_day, str) and time_of_day.strip():
        value = time_of_day.strip()
        format_string = "%H:%M:%S" if value.count(":") == 2 else "%H:%M"
        parsed_time = datetime.strptime(value, format_string).time()
        now = datetime.now().astimezone()
        target = now.replace(
            hour=parsed_time.hour,
            minute=parsed_time.minute,
            second=parsed_time.second,
            microsecond=0,
        )
        if target <= now:
            target = target + timedelta(days=1)
        return target

    raise ActionValidationError("wait_until actions require 'timestamp' or 'time_of_day'.")


def _seconds_until(target: datetime) -> float:
    now = datetime.now(target.tzinfo) if target.tzinfo is not None else datetime.now()
    remaining = (target - now).total_seconds()
    return max(remaining, 0.0)


def _is_close_window_hotkey(keys: list[str]) -> bool:
    lowered = {key.lower() for key in keys}
    return "alt" in lowered and "f4" in lowered


def _is_close_tab_hotkey(keys: list[str]) -> bool:
    lowered = {key.lower() for key in keys}
    return "ctrl" in lowered and "w" in lowered


def _launch_process(command: list[str], *, error_message: str) -> None:
    try:
        subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        raise ActionValidationError(f"{error_message}: {exc}") from exc


def _default_retry_policy(timeout_seconds: float) -> RetryPolicy:
    return RetryPolicy(
        timeout_seconds=max(timeout_seconds, 0.0),
        initial_interval=config.RETRY_INITIAL_INTERVAL_SECONDS,
        max_interval=config.RETRY_MAX_INTERVAL_SECONDS,
        backoff=max(config.RETRY_BACKOFF_FACTOR, 1.0),
    )


def _save_dialog_is_ready(previous_window: dict[str, Any] | None = None) -> bool:
    active = get_active_window_info()
    active_title = str(active.get("title") or "").strip().lower()
    previous_title = str((previous_window or {}).get("title") or "").strip().lower()
    if active_title and active_title != previous_title and "save" in active_title:
        return True

    try:
        controls = capture_active_window_controls(limit=30)
    except Exception:
        controls = []

    for control in controls:
        control_type = str(control.get("control_type") or "").lower()
        text = str(control.get("text") or "").lower()
        if control_type == "edit":
            return True
        if control_type == "button" and text in {"save", "save as"}:
            return True
    return False


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
        if action.get("element_id") is not None:
            normalized["element_id"] = _require_element_id(action)
        if action.get("x") is not None or action.get("y") is not None:
            normalized["x"] = _require_coordinate(action, "x", screen_size)
            normalized["y"] = _require_coordinate(action, "y", screen_size)
        has_target = normalized.get("element_id") is not None or (normalized.get("x") is not None and normalized.get("y") is not None)

        if action_name in {"click", "double_click", "right_click", "scroll"} and not has_target:
            raise ActionValidationError(f"{action_name} actions require either element_id or x/y coordinates.")

    if action_name == "browser_get_tabs":
        if action.get("browser_name") is not None:
            normalized["browser_name"] = _require_non_empty_string(
                {"browser_name": action.get("browser_name")}, "browser_name"
            )
        if action.get("profile_name") is not None:
            normalized["profile_name"] = _require_non_empty_string(
                {"profile_name": action.get("profile_name")}, "profile_name"
            )

    if action_name in {"browser_click", "browser_find", "browser_wait_for", "browser_switch_tab"}:
        target_text = action.get("text") or action.get("name") or action.get("title_contains")
        if target_text is not None:
            normalized["text"] = _require_non_empty_string({"text": target_text}, "text")
        selector_strategy = action.get("selector_strategy")
        if selector_strategy is not None:
            normalized["selector_strategy"] = _require_non_empty_string(
                action, "selector_strategy"
            )
        if action.get("browser_name") is not None:
            normalized["browser_name"] = _require_non_empty_string(
                {"browser_name": action.get("browser_name")}, "browser_name"
            )
        if action.get("profile_name") is not None:
            normalized["profile_name"] = _require_non_empty_string(
                {"profile_name": action.get("profile_name")}, "profile_name"
            )
        if action_name == "browser_switch_tab":
            if action.get("url") is not None:
                normalized["url"] = _require_non_empty_string({"url": action.get("url")}, "url")
            if action.get("title_contains") is not None:
                normalized["title_contains"] = _require_non_empty_string(
                    {"title_contains": action.get("title_contains")},
                    "title_contains",
                )
            if normalized.get("url") is None and normalized.get("text") is None and normalized.get("title_contains") is None:
                raise ActionValidationError(
                    "browser_switch_tab actions require 'url' or 'title_contains'."
                )

    if action_name == "browser_type":
        normalized["target_text"] = _require_non_empty_string(action, "target_text")
        normalized["text"] = _require_non_empty_string(action, "text")
        selector_strategy = action.get("selector_strategy")
        if selector_strategy is not None:
            normalized["selector_strategy"] = _require_non_empty_string(
                action, "selector_strategy"
            )
        if action.get("browser_name") is not None:
            normalized["browser_name"] = _require_non_empty_string(
                {"browser_name": action.get("browser_name")}, "browser_name"
            )
        if action.get("profile_name") is not None:
            normalized["profile_name"] = _require_non_empty_string(
                {"profile_name": action.get("profile_name")}, "profile_name"
            )

    if action_name == "browser_search":
        normalized["query"] = _require_non_empty_string(action, "query")
        if action.get("browser_name") is not None:
            normalized["browser_name"] = _require_non_empty_string(
                {"browser_name": action.get("browser_name")}, "browser_name"
            )
        if action.get("profile_name") is not None:
            normalized["profile_name"] = _require_non_empty_string(
                {"profile_name": action.get("profile_name")}, "profile_name"
            )

    if action_name == "browser_navigate":
        normalized["url"] = _require_non_empty_string(action, "url")
        if action.get("wait_timeout_seconds") is not None:
            normalized["wait_timeout_seconds"] = float(
                _require_number(action, "wait_timeout_seconds")
            )
        if action.get("browser_name") is not None:
            normalized["browser_name"] = _require_non_empty_string(
                {"browser_name": action.get("browser_name")}, "browser_name"
            )
        if action.get("profile_name") is not None:
            normalized["profile_name"] = _require_non_empty_string(
                {"profile_name": action.get("profile_name")}, "profile_name"
            )

    if action_name == "browser_open":
        normalized["browser_name"] = _require_non_empty_string(
            {"browser_name": action.get("browser_name") or "chromium"},
            "browser_name",
        )
        if action.get("profile_name") is not None:
            normalized["profile_name"] = _require_non_empty_string(
                action, "profile_name"
            )
        if action.get("session_mode") is not None:
            normalized["session_mode"] = _require_non_empty_string(
                action, "session_mode"
            )

    if action_name == "shortcut":
        normalized["shortcut_name"] = _require_non_empty_string(action, "shortcut_name")
        if action.get("text") is not None:
            normalized["text"] = _require_non_empty_string(action, "text")

    if action_name == "ui_click":
        target_text = action.get("target_text")
        automation_id = action.get("automation_id")
        class_name = action.get("class_name")
        if action.get("element_id") is not None:
            normalized["element_id"] = _require_element_id(action)
        if target_text is not None:
            normalized["target_text"] = _require_non_empty_string(action, "target_text")
        if automation_id is not None:
            normalized["automation_id"] = _require_non_empty_string(action, "automation_id")
        if class_name is not None:
            normalized["class_name"] = _require_non_empty_string(action, "class_name")
        if action.get("control_type") is not None:
            normalized["control_type"] = _require_string_or_string_list(action, "control_type")
        if action.get("button") is not None:
            normalized["button"] = _require_non_empty_string(action, "button")
        if action.get("x") is not None:
            normalized["x"] = _require_coordinate(action, "x", screen_size)
        if action.get("y") is not None:
            normalized["y"] = _require_coordinate(action, "y", screen_size)
        if (
            normalized.get("element_id") is None
            and target_text is None
            and automation_id is None
            and action.get("x") is None
            and action.get("y") is None
        ):
            raise ActionValidationError(
                "ui_click actions require element_id, target_text, automation_id, or x/y coordinates."
            )

    if action_name == "uia_click":
        target_text = action.get("target_text")
        automation_id = action.get("automation_id")
        class_name = action.get("class_name")
        if action.get("element_id") is not None:
            normalized["element_id"] = _require_element_id(action)
        if (
            target_text is None
            and automation_id is None
            and class_name is None
            and action.get("element_id") is None
        ):
            raise ActionValidationError(
                "uia_click actions require 'target_text', 'automation_id', 'class_name', or 'element_id'."
            )
        if target_text is not None:
            normalized["target_text"] = _require_non_empty_string(action, "target_text")
        if automation_id is not None:
            normalized["automation_id"] = _require_non_empty_string(
                action, "automation_id"
            )
        if class_name is not None:
            normalized["class_name"] = _require_non_empty_string(action, "class_name")
        if action.get("control_type") is not None:
            normalized["control_type"] = _require_string_or_string_list(action, "control_type")

    if action_name == "uia_get_visible_elements":
        max_depth = int(_require_number(action, "max_depth")) if action.get("max_depth") is not None else 3
        if max_depth <= 0:
            raise ActionValidationError("uia_get_visible_elements max_depth must be greater than zero.")
        normalized["max_depth"] = max_depth

    if action_name == "uia_click_fallback_search":
        normalized["text"] = _require_non_empty_string(action, "text")

    if action_name == "type":
        normalized["text"] = _require_non_empty_string(action, "text")

    if action_name == "hotkey":
        normalized["keys"] = _normalize_key_list(action.get("keys"))

    if action_name == "press":
        normalized["key"] = _normalize_key_name(
            _require_non_empty_string(action, "key")
        )

    if action_name in {
        "open_app",
        "focus_app",
        "close_app",
        "new_document",
        "close_tab",
    }:
        normalized["app_name"] = normalize_app_name(
            _require_non_empty_string(action, "app_name")
        )

    if action_name == "open_app":
        normalized["new_instance"] = _require_bool(
            action, "new_instance", default=False
        )
        profile_name = action.get("profile_name")
        if profile_name is not None:
            if not isinstance(profile_name, str) or not profile_name.strip():
                raise ActionValidationError(
                    "Action field 'profile_name' must be a non-empty string."
                )
            normalized["profile_name"] = profile_name.strip()
        url = action.get("url")
        if url is not None:
            if not isinstance(url, str) or not url.strip():
                raise ActionValidationError(
                    "Action field 'url' must be a non-empty string."
                )
            normalized["url"] = url.strip()

    if action_name == "open_file":
        normalized["file_path"] = _require_non_empty_string(action, "file_path")
        app_name = action.get("app_name")
        if app_name is not None:
            normalized["app_name"] = normalize_app_name(
                _require_non_empty_string(action, "app_name")
            )

    if action_name == "save_file":
        normalized["file_path"] = _require_non_empty_string(action, "file_path")

    if action_name == "terminal_command":
        normalized["command"] = _require_non_empty_string(action, "command")
        working_directory = action.get("working_directory")
        if working_directory is not None:
            if not isinstance(working_directory, str) or not working_directory.strip():
                raise ActionValidationError(
                    "Action field 'working_directory' must be a non-empty string."
                )
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

    if action_name == "wait_until":
        timestamp = action.get("timestamp")
        time_of_day = action.get("time_of_day")
        if timestamp is None and time_of_day is None:
            raise ActionValidationError("wait_until actions require 'timestamp' or 'time_of_day'.")
        if timestamp is not None:
            normalized["timestamp"] = _require_non_empty_string(action, "timestamp")
        if time_of_day is not None:
            normalized["time_of_day"] = _require_non_empty_string(action, "time_of_day")

    if normalized["task_complete"] and action_name != "done":
        normalized["task_complete"] = False

    if action_name == "done" and not normalized["task_complete"]:
        raise ActionValidationError("The 'done' action must set task_complete to true.")

    return normalized


def execute_action(action: dict[str, Any]) -> dict[str, Any] | None:
    """Execute a validated action and optionally return execution metadata."""

    action = _hydrate_action_from_element_id(action)
    action_name = action["action"]
    if action_name in {"screenshot", "done"}:
        return None

    if action_name == "wait":
        return {
            "delay": float(action["seconds"]),
            "execution_confirmed": True,
        }

    if action_name == "wait_until":
        target = _parse_wait_until(action)
        return {
            "wait_until": target.isoformat(),
            "delay": _seconds_until(target),
            "execution_confirmed": True,
        }

    if action_name == "focus_app":
        return execute_focus_app(
            action,
            error_cls=ActionValidationError,
            app_window_exists=app_window_exists,
            focus_app_window=focus_app_window,
            get_active_window_info=get_active_window_info,
            window_focus_timeout=config.WINDOW_FOCUS_TIMEOUT,
        )

    if action_name == "open_app":
        return execute_open_app(
            action,
            error_cls=ActionValidationError,
            app_window_exists=app_window_exists,
            focus_app_window=focus_app_window,
            build_launch_command=build_launch_command,
            wait_for_condition=wait_for_condition,
            default_retry_policy=_default_retry_policy,
            launch_process=_launch_process,
            app_launch_delay=config.APP_LAUNCH_DELAY,
            window_focus_timeout=config.WINDOW_FOCUS_TIMEOUT,
            get_pyautogui=_get_pyautogui,
        )

    if action_name == "open_file":
        return execute_open_file(
            action,
            rewrite_known_user_paths=rewrite_known_user_paths,
            build_launch_command=build_launch_command,
            launch_process=_launch_process,
            wait_for_condition=wait_for_condition,
            default_retry_policy=_default_retry_policy,
            focus_app_window=focus_app_window,
            app_window_exists=app_window_exists,
            app_launch_delay=config.APP_LAUNCH_DELAY,
            platform_name=sys.platform,
        )

    if action_name == "terminal_command":
        raise ActionValidationError(
            "terminal_command actions must be executed through TerminalAgent."
        )

    if action_name == "uia_get_visible_elements":
        payload = uia_get_visible_elements(max_depth=int(action.get("max_depth", 3)))
        payload["execution_confirmed"] = True
        return payload

    if action_name == "uia_click_fallback_search":
        matched_control = focus_visible_search_input()
        if matched_control is None:
            details = get_last_ui_automation_error()
            raise ActionValidationError(
                "Failed to focus a visible search input control."
                + (f" {details}" if details else "")
            )
        pyautogui = _get_pyautogui()
        pyautogui.hotkey("ctrl", "a")
        pyautogui.typewrite(action["text"], interval=config.TYPEWRITE_INTERVAL)
        pyautogui.press("enter")
        return {
            "execution_confirmed": True,
            "target_text": matched_control.get("text"),
            "control_type": matched_control.get("control_type"),
            "class_name": matched_control.get("class_name"),
        }

    if action_name == "uia_click":
        matched_control = invoke_active_window_control(
            target_text=action.get("target_text"),
            control_type=action.get("control_type"),
            automation_id=action.get("automation_id"),
            class_name=action.get("class_name"),
            element_id=action.get("element_id"),
        )
        if matched_control is None:
            details = get_last_ui_automation_error()
            raise ActionValidationError(
                "Failed to find or click the requested UI automation control."
                + (f" {details}" if details else "")
            )
        result = {"execution_confirmed": True}
        if matched_control.get("element_id") is not None:
            result["element_id"] = matched_control.get("element_id")
        if matched_control.get("text"):
            result["target_text"] = matched_control.get("text")
        if matched_control.get("control_type"):
            result["control_type"] = matched_control.get("control_type")
        return result

    if action_name in {"close_app", "close_tab", "new_document"}:
        return execute_window_hotkey_action(
            action,
            error_cls=ActionValidationError,
            app_window_exists=app_window_exists,
            focus_app_window=focus_app_window,
            get_active_window_info=get_active_window_info,
            is_protected_control_window=is_protected_control_window,
            is_oscar_app_name=is_oscar_app_name,
            get_pyautogui=_get_pyautogui,
            window_focus_timeout=config.WINDOW_FOCUS_TIMEOUT,
        )

    pyautogui = _get_pyautogui()

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
        if (
            _is_close_window_hotkey(action["keys"])
            or _is_close_tab_hotkey(action["keys"])
        ) and is_protected_control_window(get_active_window_info()):
            raise ActionValidationError(
                "Refused to send a close hotkey to the OSCAR control window."
            )
        pyautogui.hotkey(*action["keys"])
        return None

    if action_name == "press":
        pyautogui.press(action["key"])
        return None

    if action_name == "save_file":
        return execute_save_file(
            action,
            error_cls=ActionValidationError,
            rewrite_known_user_paths=rewrite_known_user_paths,
            get_pyautogui=_get_pyautogui,
            get_active_window_info=get_active_window_info,
            wait_for_condition=wait_for_condition,
            default_retry_policy=_default_retry_policy,
            save_dialog_is_ready=_save_dialog_is_ready,
            type_interval=config.TYPEWRITE_INTERVAL,
            save_dialog_delay=config.SAVE_DIALOG_DELAY,
        )

    if action_name == "scroll":
        clicks = action["amount"] if action["direction"] == "up" else -action["amount"]
        pyautogui.scroll(clicks, x=action["x"], y=action["y"])
        return None

    raise ActionValidationError(f"Unsupported action '{action_name}'.")
