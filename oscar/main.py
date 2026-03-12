"""CLI entrypoint and agent loop for OSCAR."""

from __future__ import annotations

import argparse
import difflib
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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


OPEN_PREFIXES = ("open ", "launch ", "start ")
BROWSER_APP_PATTERN = r"google chrome|chrome|browser|microsoft edge|edge"
BROWSER_SEARCH_PATTERN = re.compile(
    rf"^(?:open|launch|start)\s+(?P<app>{BROWSER_APP_PATTERN})"
    r"(?:\s+use\s+(?P<profile>.+?)\s+profile)?"
    r"(?:\s*,\s*|\s+and\s+|\s+then\s+)?search(?:\s+for)?\s+(?P<query>.+)$",
    re.IGNORECASE,
)
BROWSER_NAVIGATE_PATTERN = re.compile(
    rf"^(?:open|launch|start)\s+(?P<app>{BROWSER_APP_PATTERN})"
    r"(?:\s+use\s+(?P<profile>.+?)\s+profile)?"
    r"(?:\s*,\s*|\s+and\s+|\s+then\s+)?(?:go\s+to|goto|navigate\s+to|visit)\s+(?P<url>.+)$",
    re.IGNORECASE,
)
OPEN_AND_TYPE_PATTERN = re.compile(
    r"^(?:open|launch|start)\s+(?P<app>.+?)(?:\s*,\s*|\s+and\s+|\s+then\s+)type\s+(?P<text>.+)$",
    re.IGNORECASE,
)
SAVE_LOCATION_PATTERN = re.compile(
    r"^(?P<text>.+?)(?:\s*,\s*|\s+and\s+)(?:save(?:\s+it|\s+the\s+file)?\s+in\s+(?:the\s+)?)?(?P<folder>[a-zA-Z ]+?)(?:\s+folder)?\.?$",
    re.IGNORECASE,
)
APP_SEPARATOR_PATTERN = re.compile(r"\s*,\s*|\s+and\s+|\s+then\s+", re.IGNORECASE)
KNOWN_SAVE_FOLDERS = {
    "downloads": Path.home() / "Downloads",
    "download": Path.home() / "Downloads",
    "desktop": Path.home() / "Desktop",
    "dekstop": Path.home() / "Desktop",
    "desk top": Path.home() / "Desktop",
}


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


def _normalize_save_folder(folder_name: str) -> Path | None:
    normalized = normalize_app_name(folder_name)
    if normalized in KNOWN_SAVE_FOLDERS:
        return KNOWN_SAVE_FOLDERS[normalized]

    matches = difflib.get_close_matches(normalized, list(KNOWN_SAVE_FOLDERS.keys()), n=1, cutoff=0.82)
    if matches:
        return KNOWN_SAVE_FOLDERS[matches[0]]
    return None


def _extract_save_destination(text: str) -> tuple[str, Path | None]:
    match = SAVE_LOCATION_PATTERN.match(text.strip())
    if match is None:
        return text, None

    folder = _normalize_save_folder(match.group("folder"))
    if folder is None:
        return text, None

    return match.group("text").strip(), folder


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


def _extract_multi_open_apps(task: str) -> list[str] | None:
    split_task = _split_open_task(task)
    if split_task is None:
        return None

    _normalized_task, remainder = split_task
    if re.search(r"\b(type|search|save|goto|go\s+to|navigate|visit|profile)\b", remainder, re.IGNORECASE):
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


def _extract_open_and_type_task(task: str) -> tuple[str, str, Path | None] | None:
    normalized_task = " ".join(task.strip().split())
    match = OPEN_AND_TYPE_PATTERN.match(normalized_task)
    if match is None:
        return None

    app_name = _clean_app_name_fragment(match.group("app"))
    text = match.group("text").strip()
    text, save_folder = _extract_save_destination(text)
    text = _strip_wrapping_quotes(text)
    if not app_name or not text:
        return None

    return app_name, text, save_folder


def _build_output_file_path(app_name: str, folder: Path) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = "oscar_note" if app_name == "notepad" else f"oscar_{app_name.replace(' ', '_')}"
    return str((folder / f"{stem}_{timestamp}.txt").resolve())


def _infer_bootstrap_actions(task: str) -> tuple[list[dict[str, Any]], bool] | None:
    browser_search = _extract_browser_search_task(task)
    if browser_search is not None:
        app_name, profile_name, query = browser_search
        actions: list[dict[str, Any]] = [
            {
                "action": "open_app",
                "app_name": app_name,
                "reasoning": f"Launch {app_name} directly using the deterministic app launcher.",
                "task_complete": False,
            },
            {
                "action": "hotkey",
                "keys": ["ctrl", "l"],
                "reasoning": "Focus the browser address bar for the search query.",
                "task_complete": False,
            },
            {
                "action": "type",
                "text": query,
                "reasoning": f"Type '{query}' into the browser address bar.",
                "task_complete": False,
            },
            {
                "action": "press",
                "key": "enter",
                "reasoning": "Submit the browser address bar contents.",
                "task_complete": False,
            },
            _build_terminal_done_action(
                f"The browser was opened{f' with the {profile_name} profile' if profile_name else ''} and the query was submitted."
            ),
        ]
        if profile_name:
            actions[0]["profile_name"] = profile_name
        return actions, True

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
                "reasoning": f"Launch {app_name} directly using the deterministic app launcher.",
                "task_complete": False,
            }
            for app_name in multi_open_apps
        ]
        actions.append(
            _build_terminal_done_action(
                "The requested apps were opened directly without relying on screen clicks."
            )
        )
        return actions, True

    open_and_type = _extract_open_and_type_task(task)
    if open_and_type is not None:
        app_name, text, save_folder = open_and_type
        actions: list[dict[str, Any]] = [
            {
                "action": "open_app",
                "app_name": app_name,
                "reasoning": f"Launch {app_name} directly using the deterministic app launcher.",
                "task_complete": False,
            },
            {
                "action": "type",
                "text": text,
                "reasoning": f"Type the requested text into {app_name} after it opens.",
                "task_complete": False,
            },
        ]
        if save_folder is not None and resolve_app_spec(app_name).canonical_name == "notepad":
            file_path = _build_output_file_path(app_name, save_folder)
            actions.append(
                {
                    "action": "save_file",
                    "file_path": file_path,
                    "reasoning": f"Save the Notepad document to {save_folder.name} as {Path(file_path).name}.",
                    "task_complete": False,
                }
            )
            actions.append(
                _build_terminal_done_action(
                    f"The requested app '{app_name}' was opened, the text was typed, and the file was saved to {file_path}."
                )
            )
            return actions, True

        if save_folder is None:
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
        for marker in (" and ", " then ", ", then ", ", search ", ", type ", " search ", " type ", " goto ", " go to ")
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
            "reasoning": f"Launch {app_name} directly using the deterministic app launcher.",
            "task_complete": False,
        }
    ]
    if task_is_complete:
        actions.append(
            _build_terminal_done_action(f"The requested app '{app_name}' was launched directly.")
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


def _is_pure_open_app(action: dict[str, Any]) -> bool:
    return action["action"] == "open_app" and not action.get("profile_name") and not action.get("url")


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

        if _is_pure_open_app(action) and focus_app_window(current_app_target, timeout=0.3):
            time.sleep(config.FOCUS_SETTLE_DELAY)
            return current_app_target

        execute_action(action)

        if focus_app_window(current_app_target, timeout=config.APP_LAUNCH_DELAY):
            time.sleep(config.FOCUS_SETTLE_DELAY)
            return current_app_target

        if app_window_exists(current_app_target):
            return current_app_target

        active_window = get_active_window_info()
        spec = resolve_app_spec(current_app_target)
        if not spec.is_known:
            time.sleep(config.APP_LAUNCH_DELAY)
            return current_app_target

        raise RuntimeError(
            f"Expected '{current_app_target}' to open and receive focus, but the active window is "
            f"'{active_window.get('title') or 'Unknown'}' ({active_window.get('process_name') or 'Unknown'})."
        )

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
