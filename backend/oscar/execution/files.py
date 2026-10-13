"""File-oriented execution helpers."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Callable

from oscar import config


_POWERSHELL_USERPROFILE_PATTERN = re.compile(r"\$env:USERPROFILE", re.IGNORECASE)


def _resolve_file_path(
    path: str,
    *,
    rewrite_known_user_paths: Callable[[str], str],
) -> Path:
    user_home = os.path.expanduser("~")
    sanitized = _POWERSHELL_USERPROFILE_PATTERN.sub(lambda _match: user_home, path.strip())
    rewritten = rewrite_known_user_paths(sanitized)
    expanded = os.path.expandvars(os.path.expanduser(rewritten))
    return Path(expanded)


def execute_open_file(
    action: dict[str, Any],
    *,
    rewrite_known_user_paths: Callable[[str], str],
    build_launch_command: Callable[..., tuple[list[str], Any]],
    launch_process: Callable[[list[str], str], None],
    wait_for_condition: Callable[..., Any],
    default_retry_policy: Callable[[float], Any],
    focus_app_window: Callable[[str, float], bool],
    app_window_exists: Callable[[str], bool],
    app_launch_delay: float,
    platform_name: str,
) -> dict[str, Any]:
    file_path = _resolve_file_path(
        str(action["file_path"]),
        rewrite_known_user_paths=rewrite_known_user_paths,
    )
    if config.OSCAR_DRY_RUN:
        return {"dry_run": True, "execution_confirmed": False, "would_execute": "open_file", "file_path": str(file_path)}
    app_name = action.get("app_name")

    if app_name:
        command, _spec = build_launch_command(app_name)
        command = [*command, str(file_path)]
    elif platform_name == "win32":
        command = ["cmd.exe", "/c", "start", "", str(file_path)]
    else:
        command = [str(file_path)]

    launch_process(command, error_message=f"Failed to open file '{file_path}'")
    verified = True
    if app_name:
        verified = bool(
            wait_for_condition(
                lambda: focus_app_window(app_name, timeout=0.0)
                or app_window_exists(app_name),
                policy=default_retry_policy(app_launch_delay),
            )
        )
    return {"file_path": str(file_path), "launch_confirmed": verified}


def execute_save_file(
    action: dict[str, Any],
    *,
    error_cls: type[Exception],
    rewrite_known_user_paths: Callable[[str], str],
    get_pyautogui: Callable[[], Any],
    get_active_window_info: Callable[[], dict[str, Any]],
    wait_for_condition: Callable[..., Any],
    default_retry_policy: Callable[[float], Any],
    save_dialog_is_ready: Callable[[dict[str, Any] | None], bool],
    type_interval: float,
    save_dialog_delay: float,
) -> dict[str, Any]:
    file_path = _resolve_file_path(
        str(action["file_path"]),
        rewrite_known_user_paths=rewrite_known_user_paths,
    )
    if config.OSCAR_DRY_RUN:
        return {"dry_run": True, "execution_confirmed": False, "would_execute": "save_file", "file_path": str(file_path)}
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise error_cls(
            f"Failed to prepare save directory '{file_path.parent}': {exc}"
        ) from exc

    active_window = get_active_window_info()
    active_title = str(active_window.get("title") or "").lower()
    active_process = str(active_window.get("process_name") or "").lower()
    pyautogui = get_pyautogui()

    shortcut_sequences: list[tuple[str, ...]] = []
    if "code" in active_process or "visual studio code" in active_title:
        shortcut_sequences.append(("ctrl", "shift", "s"))
    shortcut_sequences.append(("ctrl", "s"))
    if ("ctrl", "shift", "s") not in shortcut_sequences:
        shortcut_sequences.append(("ctrl", "shift", "s"))

    attempted_sequences: list[str] = []
    for sequence in shortcut_sequences:
        attempted_sequences.append("+".join(sequence))
        pyautogui.hotkey(*sequence)
        if file_path.exists():
            return {"file_path": str(file_path), "execution_confirmed": True}

        dialog_ready = wait_for_condition(
            lambda: save_dialog_is_ready(active_window),
            policy=default_retry_policy(save_dialog_delay),
        )
        if not dialog_ready:
            continue

        pyautogui.hotkey("ctrl", "a")
        pyautogui.typewrite(str(file_path), interval=type_interval)
        pyautogui.press("enter")
        saved = wait_for_condition(
            lambda: file_path.exists(),
            policy=default_retry_policy(max(save_dialog_delay, 2.0)),
        )
        if saved:
            return {"file_path": str(file_path), "execution_confirmed": True}

    raise error_cls(
        "Save operation could not be verified after trying: "
        + ", ".join(attempted_sequences)
    )
