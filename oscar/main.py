"""CLI entrypoint and agent loop for OSCAR."""

from __future__ import annotations

import argparse
import difflib
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from oscar import config
from oscar.executor import execute_action, validate_action
from oscar.gemini_client import ask_gemini
from oscar.prompt_builder import build_prompt
from oscar.run_logger import write_run_log
from oscar.screen import capture_screenshot
from oscar.window_control import (
    app_window_exists,
    focus_app_window,
    get_active_window_info,
    get_cursor_position,
    normalize_app_name,
    resolve_app_spec,
)


def _resolve_user_home_directory() -> Path:
    user_profile = os.getenv("USERPROFILE")
    if user_profile:
        return Path(user_profile)

    home_drive = os.getenv("HOMEDRIVE")
    home_path = os.getenv("HOMEPATH")
    if home_drive and home_path:
        return Path(f"{home_drive}{home_path}")

    return Path.home()


USER_HOME_DIR = _resolve_user_home_directory()
OPEN_PREFIXES = ("open ", "launch ", "start ")
BROWSER_APP_PATTERN = r"google chrome|chrome|browser|microsoft edge|edge|brave|firefox"
PROFILE_FRAGMENT = r"(?:\s+(?:and\s+)?use\s+(?P<profile>.+?)\s+profile)?"
BROWSER_SEARCH_PATTERN = re.compile(
    rf"^(?:open|launch|start)\s+(?P<app>{BROWSER_APP_PATTERN})"
    rf"{PROFILE_FRAGMENT}"
    r"(?:\s*,\s*|\s+and\s+|\s+then\s+)?(?:search(?:\s+for)?|look\s+for|look\s+up|find)\s+(?P<query>.+)$",
    re.IGNORECASE,
)
BROWSER_NAVIGATE_PATTERN = re.compile(
    rf"^(?:open|launch|start)\s+(?P<app>{BROWSER_APP_PATTERN})"
    rf"{PROFILE_FRAGMENT}"
    r"(?:\s*,\s*|\s+and\s+|\s+then\s+)?(?:go\s+to|goto|navigate\s+to|visit)\s+(?P<url>.+)$",
    re.IGNORECASE,
)
OPEN_AND_TEXT_PATTERN = re.compile(
    r"^(?:open|launch|start)\s+(?P<app>.+?)(?:\s*,\s*|\s+and\s+|\s+then\s+|\s+)(?P<verb>type|write|enter|input)\s+(?P<text>.+)$",
    re.IGNORECASE,
)
CLOSE_APP_PATTERN = re.compile(r"^(?:close|exit|quit)\s+(?P<app>.+)$", re.IGNORECASE)
SAVE_COMMAND_PATTERN = re.compile(
    r"(?:\s*,\s*|\s+and\s+)(?:save(?:\s+it|\s+the\s+file)?\s+(?:in|to)\s+(?:the\s+)?)",
    re.IGNORECASE,
)
APP_SEPARATOR_PATTERN = re.compile(r"\s*,\s*|\s+and\s+|\s+then\s+", re.IGNORECASE)
KNOWN_SAVE_FOLDERS = {
    "downloads": USER_HOME_DIR / "Downloads",
    "download": USER_HOME_DIR / "Downloads",
    "desktop": USER_HOME_DIR / "Desktop",
    "dekstop": USER_HOME_DIR / "Desktop",
    "desk top": USER_HOME_DIR / "Desktop",
}
IMAGE_SEARCH_HINTS = ("image", "images", "photo", "photos", "picture", "pictures", "wallpaper")
WINDOWS_PATH_PATTERN = re.compile(r"^(?:[a-zA-Z]:[\\/]|\\\\|\.[\\/]|\.\.[\\/])")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _build_terminal_done_action(reasoning: str) -> dict[str, object]:
    return {
        "action": "done",
        "reasoning": reasoning,
        "task_complete": True,
    }


def _strip_wrapping_quotes(text: str) -> str:
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        return text[1:-1]
    return text


def _normalize_url(url: str) -> str:
    cleaned = _strip_wrapping_quotes(url.strip())
    if re.match(r"^[a-z][a-z0-9+\-.]*://", cleaned, re.IGNORECASE):
        return cleaned
    if " " not in cleaned and "." in cleaned:
        return f"https://{cleaned}"
    return cleaned


def _build_browser_search_url(query: str) -> str:
    lowered_query = normalize_app_name(query)
    is_image_search = any(re.search(rf"\b{hint}\b", lowered_query) for hint in IMAGE_SEARCH_HINTS)
    base_url = "https://www.google.com/search?tbm=isch&q=" if is_image_search else "https://www.google.com/search?q="
    return f"{base_url}{quote_plus(query)}"


def _clean_app_name_fragment(app_name: str) -> str:
    cleaned = re.sub(r"\b(app|application)$", "", app_name, flags=re.IGNORECASE)
    return normalize_app_name(cleaned.strip(" .,\t"))


def _split_open_task(task: str) -> tuple[str, str] | None:
    normalized_task = " ".join(task.strip().split())
    lowered_task = normalized_task.lower()

    prefix = next((candidate for candidate in OPEN_PREFIXES if lowered_task.startswith(candidate)), None)
    if prefix is None:
        return None

    remainder = normalized_task[len(prefix) :].strip()
    if not remainder:
        return None

    return normalized_task, remainder


def _looks_like_windows_path(value: str) -> bool:
    return bool(WINDOWS_PATH_PATTERN.match(value))


def _strip_folder_suffix(value: str) -> str:
    lowered = normalize_app_name(value)
    if lowered.endswith(" folder") and not _looks_like_windows_path(value) and "\\" not in value and "/" not in value:
        return value[: -len(" folder")].strip()
    return value


def _normalize_save_folder(folder_name: str) -> Path | None:
    normalized = normalize_app_name(_strip_folder_suffix(folder_name))
    if normalized in KNOWN_SAVE_FOLDERS:
        return KNOWN_SAVE_FOLDERS[normalized]

    matches = difflib.get_close_matches(normalized, list(KNOWN_SAVE_FOLDERS.keys()), n=1, cutoff=0.82)
    if matches:
        return KNOWN_SAVE_FOLDERS[matches[0]]
    return None


def _resolve_save_destination(location: str) -> Path | None:
    cleaned = _strip_wrapping_quotes(location.strip().rstrip("."))
    if not cleaned:
        return None

    named_folder = _normalize_save_folder(cleaned)
    if named_folder is not None:
        return named_folder

    if cleaned.endswith(":" ) and len(cleaned) == 2 and cleaned[0].isalpha():
        cleaned = f"{cleaned}\\"

    if _looks_like_windows_path(cleaned) or "\\" in cleaned or "/" in cleaned:
        return Path(cleaned)

    return None


def _extract_save_destination(text: str) -> tuple[str, Path | None]:
    match = SAVE_COMMAND_PATTERN.search(text)
    if match is None:
        return text, None

    main_text = text[: match.start()].strip(" ,")
    destination = _resolve_save_destination(text[match.end() :])
    if destination is None:
        return text, None

    return main_text, destination


def _extract_browser_search_task(task: str) -> tuple[str, str | None, str] | None:
    normalized_task = " ".join(task.strip().split())
    match = BROWSER_SEARCH_PATTERN.match(normalized_task)
    if match is None:
        return None

    app_name = _clean_app_name_fragment(match.group("app"))
    profile_name = match.group("profile")
    query = _strip_wrapping_quotes(match.group("query").strip())
    if not app_name or not query:
        return None

    return app_name, profile_name.strip() if profile_name else None, query


def _extract_browser_navigation_task(task: str) -> tuple[str, str | None, str] | None:
    normalized_task = " ".join(task.strip().split())
    match = BROWSER_NAVIGATE_PATTERN.match(normalized_task)
    if match is None:
        return None

    app_name = _clean_app_name_fragment(match.group("app"))
    profile_name = match.group("profile")
    url = _normalize_url(match.group("url"))
    if not app_name or not url:
        return None

    return app_name, profile_name.strip() if profile_name else None, url


def _extract_close_task(task: str) -> str | None:
    normalized_task = " ".join(task.strip().split())
    match = CLOSE_APP_PATTERN.match(normalized_task)
    if match is None:
        return None

    app_name = _clean_app_name_fragment(match.group("app"))
    if not app_name:
        return None
    return app_name


def _extract_multi_open_apps(task: str) -> list[str] | None:
    split_task = _split_open_task(task)
    if split_task is None:
        return None

    _normalized_task, remainder = split_task
    if re.search(
        r"\b(type|write|enter|input|search|look\s+for|look\s+up|find|save|goto|go\s+to|navigate|visit|profile)\b",
        remainder,
        re.IGNORECASE,
    ):
        return None

    raw_parts = [part for part in APP_SEPARATOR_PATTERN.split(remainder) if part.strip()]
    if len(raw_parts) < 2:
        return None

    resolved_apps: list[str] = []
    for raw_part in raw_parts:
        app_name = _clean_app_name_fragment(raw_part)
        if not app_name:
            return None
        spec = resolve_app_spec(app_name)
        if not spec.is_known:
            return None
        if spec.canonical_name not in resolved_apps:
            resolved_apps.append(spec.canonical_name)

    return resolved_apps if len(resolved_apps) > 1 else None


def _extract_open_and_text_task(task: str) -> tuple[str, str, Path | None] | None:
    normalized_task = " ".join(task.strip().split())
    match = OPEN_AND_TEXT_PATTERN.match(normalized_task)
    if match is None:
        return None

    app_name = _clean_app_name_fragment(match.group("app"))
    text = match.group("text").strip()
    text, save_destination = _extract_save_destination(text)
    text = _strip_wrapping_quotes(text)
    if not app_name or not text:
        return None

    return app_name, text, save_destination


def _suggest_file_stem(text: str, app_name: str) -> str:
    cleaned = _strip_wrapping_quotes(text)
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if cleaned:
        return cleaned[:80]
    if app_name == "notepad":
        return "oscar_note"
    return f"oscar_{app_name.replace(' ', '_')}"


def _build_output_file_path(app_name: str, text: str, destination: Path) -> str:
    target_path = destination.expanduser()
    if not target_path.is_absolute() and not _looks_like_windows_path(str(target_path)):
        target_path = (Path.cwd() / target_path).resolve()

    if target_path.suffix:
        return str(target_path)

    file_stem = _suggest_file_stem(text, app_name)
    suffix = ".txt" if app_name == "notepad" else ".txt"
    return str(target_path / f"{file_stem}{suffix}")


def _infer_bootstrap_actions(task: str) -> tuple[list[dict[str, Any]], bool] | None:
    close_task = _extract_close_task(task)
    if close_task is not None:
        if not app_window_exists(close_task):
            return [
                _build_terminal_done_action(
                    f"The requested app '{close_task}' is already closed or has no visible window."
                )
            ], True
        return (
            [
                {
                    "action": "close_app",
                    "app_name": close_task,
                    "reasoning": f"Focus {close_task} and close its window without using mouse clicks.",
                    "task_complete": False,
                }
            ],
            False,
        )

    browser_search = _extract_browser_search_task(task)
    if browser_search is not None:
        app_name, profile_name, query = browser_search
        search_url = _build_browser_search_url(query)
        action: dict[str, Any] = {
            "action": "open_app",
            "app_name": app_name,
            "url": search_url,
            "reasoning": f"Launch {app_name} directly to the search results for '{query}'.",
            "task_complete": False,
        }
        if profile_name:
            action["profile_name"] = profile_name
        return [action, _build_terminal_done_action(f"The browser was opened and searched for '{query}'.")], True

    browser_navigation = _extract_browser_navigation_task(task)
    if browser_navigation is not None:
        app_name, profile_name, url = browser_navigation
        action: dict[str, Any] = {
            "action": "open_app",
            "app_name": app_name,
            "url": url,
            "reasoning": f"Launch {app_name} directly to {url} using the deterministic app launcher.",
            "task_complete": False,
        }
        if profile_name:
            action["profile_name"] = profile_name
        return [action, _build_terminal_done_action(f"The browser was opened and navigated to {url}.")], True

    multi_open_apps = _extract_multi_open_apps(task)
    if multi_open_apps is not None:
        actions = [
            {
                "action": "open_app",
                "app_name": app_name,
                "reasoning": f"Open or focus {app_name} directly using the deterministic app launcher.",
                "task_complete": False,
            }
            for app_name in multi_open_apps
        ]
        actions.append(
            _build_terminal_done_action(
                "The requested apps were opened or focused directly without relying on screen clicks."
            )
        )
        return actions, True

    open_and_text = _extract_open_and_text_task(task)
    if open_and_text is not None:
        app_name, text, save_destination = open_and_text
        is_new_instance = resolve_app_spec(app_name).canonical_name == "notepad"
        open_reason = (
            f"Open a new {app_name} window directly using the deterministic app launcher."
            if is_new_instance
            else f"Open or focus {app_name} directly using the deterministic app launcher."
        )
        open_action: dict[str, Any] = {
            "action": "open_app",
            "app_name": app_name,
            "reasoning": open_reason,
            "task_complete": False,
        }
        if is_new_instance:
            open_action["new_instance"] = True

        actions: list[dict[str, Any]] = [
            open_action,
            {
                "action": "type",
                "text": text,
                "reasoning": f"Type the requested text into {app_name} after it is focused.",
                "task_complete": False,
            },
        ]

        if save_destination is not None and resolve_app_spec(app_name).canonical_name == "notepad":
            file_path = _build_output_file_path(app_name, text, save_destination)
            actions.append(
                {
                    "action": "save_file",
                    "file_path": file_path,
                    "reasoning": f"Save the Notepad document directly to {Path(file_path).parent} as {Path(file_path).name}.",
                    "task_complete": False,
                }
            )
            actions.append(
                _build_terminal_done_action(
                    f"The requested app '{app_name}' was opened, the text was typed, and the file was saved to {file_path}."
                )
            )
            return actions, True

        if save_destination is None:
            actions.append(
                _build_terminal_done_action(
                    f"The requested app '{app_name}' was opened and the requested text was typed."
                )
            )
            return actions, True

        return actions, False

    split_task = _split_open_task(task)
    if split_task is None:
        return None

    _normalized_task, remainder = split_task
    conjunction_positions = [
        remainder.lower().find(marker)
        for marker in (
            " and ",
            " then ",
            ", then ",
            ", search ",
            ", type ",
            ", write ",
            " search ",
            " type ",
            " write ",
            " goto ",
            " go to ",
            " look for ",
            " find ",
        )
        if remainder.lower().find(marker) != -1
    ]
    app_name = remainder
    task_is_complete = True
    if conjunction_positions:
        cut_index = min(conjunction_positions)
        app_name = remainder[:cut_index].strip()
        task_is_complete = False

    app_name = _clean_app_name_fragment(app_name)
    if not app_name:
        return None

    actions: list[dict[str, Any]] = [
        {
            "action": "open_app",
            "app_name": app_name,
            "reasoning": f"Open or focus {app_name} directly using the deterministic app launcher.",
            "task_complete": False,
        }
    ]
    if task_is_complete:
        actions.append(
            _build_terminal_done_action(f"The requested app '{app_name}' was opened or focused directly.")
        )

    return actions, task_is_complete


def _action_delay(action: dict[str, Any]) -> float:
    if action["action"] in {"wait", "done", "open_app"}:
        return 0.0
    return config.ACTION_DELAY


def _ensure_target_focus(app_name: str, action_name: str) -> None:
    if focus_app_window(app_name, timeout=config.WINDOW_FOCUS_TIMEOUT):
        time.sleep(config.FOCUS_SETTLE_DELAY)
        return

    active_window = get_active_window_info()
    raise RuntimeError(
        f"Expected '{app_name}' to be focused before '{action_name}', but the active window "
        f"is '{active_window.get('title') or 'Unknown'}' ({active_window.get('process_name') or 'Unknown'})."
    )


def _execute_action_with_state(
    action: dict[str, Any],
    *,
    current_app_target: str | None,
) -> str | None:
    action_name = action["action"]

    if action_name in {"type", "hotkey", "press", "save_file"} and current_app_target:
        _ensure_target_focus(current_app_target, action_name)

    if action_name == "open_app":
        current_app_target = action["app_name"]
        execute_action(action)

        if focus_app_window(current_app_target, timeout=config.APP_LAUNCH_DELAY):
            time.sleep(config.FOCUS_SETTLE_DELAY)
            return current_app_target

        if app_window_exists(current_app_target):
            time.sleep(config.FOCUS_SETTLE_DELAY)
            return current_app_target

        time.sleep(config.APP_LAUNCH_DELAY)
        return current_app_target

    if action_name == "close_app":
        execute_action(action)
        if config.ACTION_DELAY > 0:
            time.sleep(config.ACTION_DELAY)
        return None

    execute_action(action)

    delay_seconds = _action_delay(action)
    if delay_seconds > 0:
        time.sleep(delay_seconds)

    return current_app_target


def run_oscar(task: str) -> Path:
    """Run the OSCAR loop for a single task and return the saved log path."""

    if not task or not task.strip():
        raise ValueError("A non-empty task is required.")

    started_at = _now_utc()
    history: list[dict] = []
    status = "failed"
    error_message: str | None = None
    caught_exception: Exception | None = None
    completed_early = False
    bootstrap_offset = 0
    current_app_target: str | None = None

    try:
        inferred_bootstrap = _infer_bootstrap_actions(task)
        if inferred_bootstrap is not None:
            bootstrap_actions, completes_task = inferred_bootstrap
            bootstrap_offset = len([action for action in bootstrap_actions if action["action"] != "done"])

            for step_index, raw_action in enumerate(bootstrap_actions, start=1):
                action = validate_action(raw_action)
                history.append(action)
                print(f"Step {step_index}: {action['reasoning']}")

                if action["action"] == "done":
                    status = "completed"
                    completed_early = completes_task
                    print("Task completed!")
                    break

                current_app_target = _execute_action_with_state(
                    action,
                    current_app_target=current_app_target,
                )

        if not completed_early:
            for step_index in range(bootstrap_offset, config.MAX_STEPS):
                screenshot, screen_size = capture_screenshot(config.SCREENSHOT_REGION)
                active_window = get_active_window_info()
                cursor_position = get_cursor_position()
                prompt = build_prompt(
                    task,
                    history,
                    screen_size=screen_size,
                    step_number=step_index + 1,
                    max_steps=config.MAX_STEPS,
                    active_window_title=active_window.get("title"),  # type: ignore[arg-type]
                    active_process_name=active_window.get("process_name"),  # type: ignore[arg-type]
                    cursor_position=cursor_position,
                )
                raw_action = ask_gemini(screenshot, prompt, model_name=config.GEMINI_MODEL)
                action = validate_action(raw_action, screen_size=screen_size)
                history.append(action)

                print(f"Step {step_index + 1}: {action['reasoning']}")

                if action["action"] == "done":
                    status = "completed"
                    print("Task completed!")
                    break

                current_app_target = _execute_action_with_state(
                    action,
                    current_app_target=current_app_target,
                )
            else:
                status = "max_steps_reached"
                print(f"Reached the maximum number of steps ({config.MAX_STEPS}).")
    except Exception as exc:
        status = "failed"
        error_message = str(exc)
        caught_exception = exc
        print(f"OSCAR stopped: {exc}")

    finished_at = _now_utc()
    log_path = write_run_log(
        task=task,
        history=history,
        started_at=started_at,
        finished_at=finished_at,
        status=status,
        error=error_message,
        model_name=config.GEMINI_MODEL,
        max_steps=config.MAX_STEPS,
        action_delay=config.ACTION_DELAY,
    )
    print(f"Run log saved to {log_path}")

    if caught_exception is not None:
        raise caught_exception

    return log_path


def main(argv: list[str] | None = None) -> int:
    """Parse CLI arguments and run OSCAR."""

    parser = argparse.ArgumentParser(description="Run OSCAR OS automation tasks.")
    parser.add_argument("--task", help="Task for OSCAR to perform.")
    args = parser.parse_args(argv)

    task = args.task.strip() if args.task else input("Enter a task for OSCAR: ").strip()
    if not task:
        print("A task is required.")
        return 1

    try:
        run_oscar(task)
    except Exception:
        return 1

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
