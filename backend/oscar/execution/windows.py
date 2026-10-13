"""Window and application execution helpers."""

from __future__ import annotations

from typing import Any, Callable

from oscar import config


def execute_focus_app(
    action: dict[str, Any],
    *,
    error_cls: type[Exception],
    app_window_exists: Callable[[str], bool],
    focus_app_window: Callable[[str, float], bool],
    get_active_window_info: Callable[[], dict[str, Any]],
    window_focus_timeout: float,
) -> dict[str, Any]:
    app_name = str(action["app_name"])
    if config.OSCAR_DRY_RUN:
        return {"dry_run": True, "execution_confirmed": False, "would_execute": "focus_app", "app_name": app_name}
    if not app_window_exists(app_name):
        raise error_cls(f"Cannot focus '{app_name}' because no visible window was found.")
    if not focus_app_window(app_name, timeout=window_focus_timeout):
        active_window = get_active_window_info()
        raise error_cls(
            f"Failed to focus '{app_name}'; active window is "
            f"'{active_window.get('title') or 'Unknown'}' ({active_window.get('process_name') or 'Unknown'})."
        )
    return {"launch_confirmed": True}


def execute_open_app(
    action: dict[str, Any],
    *,
    error_cls: type[Exception],
    app_window_exists: Callable[[str], bool],
    focus_app_window: Callable[[str, float], bool],
    build_launch_command: Callable[..., tuple[list[str], Any]],
    wait_for_condition: Callable[..., Any],
    default_retry_policy: Callable[[float], Any],
    launch_process: Callable[[list[str], str], None],
    app_launch_delay: float,
    window_focus_timeout: float,
    get_pyautogui: Callable[[], Any],
) -> dict[str, Any]:
    app_name = str(action["app_name"])
    if config.OSCAR_DRY_RUN:
        return {"dry_run": True, "execution_confirmed": False, "would_execute": "open_app", "app_name": app_name}
    should_focus_existing = (
        not action.get("new_instance")
        and not action.get("profile_name")
        and not action.get("url")
        and app_window_exists(app_name)
    )
    if should_focus_existing:
        if focus_app_window(app_name, timeout=window_focus_timeout):
            return {"launch_confirmed": True}
        raise error_cls(
            f"A visible '{app_name}' window already exists but could not be focused safely; refusing to launch a duplicate instance."
        )

    command, spec = build_launch_command(
        app_name,
        profile_name=action.get("profile_name"),
        url=action.get("url"),
    )
    shortcut_keys = tuple(getattr(spec, "shortcut_keys", ()) or ())
    if (
        shortcut_keys
        and not action.get("new_instance")
        and not action.get("profile_name")
        and not action.get("url")
    ):
        pyautogui = get_pyautogui()
        pyautogui.hotkey(*shortcut_keys)
        confirmed = wait_for_condition(
            lambda: focus_app_window(app_name, timeout=0.0) or app_window_exists(app_name),
            policy=default_retry_policy(app_launch_delay),
        )
        return {"launch_confirmed": bool(confirmed)}

    launch_process(command, error_message=f"Failed to open app '{app_name}'")
    confirmed = wait_for_condition(
        lambda: focus_app_window(app_name, timeout=0.0) or app_window_exists(app_name),
        policy=default_retry_policy(app_launch_delay),
    )
    return {"launch_confirmed": bool(confirmed)}


def execute_window_hotkey_action(
    action: dict[str, Any],
    *,
    error_cls: type[Exception],
    app_window_exists: Callable[[str], bool],
    focus_app_window: Callable[[str, float], bool],
    get_active_window_info: Callable[[], dict[str, Any]],
    is_protected_control_window: Callable[[dict[str, Any]], bool],
    is_oscar_app_name: Callable[[str], bool],
    get_pyautogui: Callable[[], Any],
    window_focus_timeout: float,
) -> None:
    action_name = str(action["action"])
    app_name = str(action["app_name"])
    if config.OSCAR_DRY_RUN:
        return {"dry_run": True, "execution_confirmed": False, "would_execute": action_name, "app_name": app_name}
    if is_oscar_app_name(app_name):
        raise error_cls("Refused to close or modify the OSCAR desktop application.")
    if action_name != "new_document" and not app_window_exists(app_name):
        return None
    if not focus_app_window(app_name, timeout=window_focus_timeout):
        active_window = get_active_window_info()
        raise error_cls(
            f"Failed to focus '{app_name}' before {action_name.replace('_', ' ')}; active window is "
            f"'{active_window.get('title') or 'Unknown'}' ({active_window.get('process_name') or 'Unknown'})."
        )
    active_window = get_active_window_info()
    if is_protected_control_window(active_window):
        raise error_cls("Refused to close or modify the OSCAR control window.")

    pyautogui = get_pyautogui()
    if action_name == "close_app":
        pyautogui.hotkey("alt", "f4")
        return None
    if action_name == "close_tab":
        pyautogui.hotkey("ctrl", "w")
        return None
    pyautogui.hotkey("ctrl", "n")
    return None
