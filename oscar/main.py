"""CLI entrypoint and agent loop for OSCAR."""

from __future__ import annotations

import argparse
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


OPEN_PREFIXES = ("open ", "launch ", "start ")
TYPE_CONNECTORS = (" and type ", " then type ", ", then type ")


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


def _extract_open_and_type_task(task: str) -> tuple[str, str] | None:
    split_task = _split_open_task(task)
    if split_task is None:
        return None

    _normalized_task, remainder = split_task
    lowered_remainder = remainder.lower()

    connector_positions = [
        (lowered_remainder.find(marker), marker)
        for marker in TYPE_CONNECTORS
        if lowered_remainder.find(marker) != -1
    ]
    if not connector_positions:
        return None

    cut_index, connector = min(connector_positions, key=lambda item: item[0])
    app_name = remainder[:cut_index].strip()
    text = remainder[cut_index + len(connector) :].strip()
    text = _strip_wrapping_quotes(text)

    app_name = re.sub(r"\b(app|application)$", "", app_name, flags=re.IGNORECASE).strip(" .")
    if not app_name or not text:
        return None

    return app_name, text


def _infer_bootstrap_actions(task: str) -> tuple[list[dict[str, Any]], bool] | None:
    open_and_type = _extract_open_and_type_task(task)
    if open_and_type is not None:
        app_name, text = open_and_type
        actions = [
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
            _build_terminal_done_action(
                f"The requested app '{app_name}' was opened and the requested text was typed."
            ),
        ]
        return actions, True

    split_task = _split_open_task(task)
    if split_task is None:
        return None

    _normalized_task, remainder = split_task
    lowered_remainder = remainder.lower()
    conjunction_positions = [
        lowered_remainder.find(marker)
        for marker in (" and ", " then ", ", then ")
        if lowered_remainder.find(marker) != -1
    ]
    app_name = remainder
    task_is_complete = True
    if conjunction_positions:
        cut_index = min(conjunction_positions)
        app_name = remainder[:cut_index].strip()
        task_is_complete = False

    app_name = re.sub(r"\b(app|application)$", "", app_name, flags=re.IGNORECASE).strip(" .")
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
    if action["action"] == "open_app":
        return config.APP_LAUNCH_DELAY
    if action["action"] == "wait":
        return 0.0
    if action["action"] == "done":
        return 0.0
    return config.ACTION_DELAY


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

                execute_action(action)
                delay_seconds = _action_delay(action)
                if delay_seconds > 0:
                    time.sleep(delay_seconds)

        if not completed_early:
            for step_index in range(bootstrap_offset, config.MAX_STEPS):
                screenshot, screen_size = capture_screenshot(config.SCREENSHOT_REGION)
                prompt = build_prompt(
                    task,
                    history,
                    screen_size=screen_size,
                    step_number=step_index + 1,
                    max_steps=config.MAX_STEPS,
                )
                raw_action = ask_gemini(screenshot, prompt, model_name=config.GEMINI_MODEL)
                action = validate_action(raw_action, screen_size=screen_size)
                history.append(action)

                print(f"Step {step_index + 1}: {action['reasoning']}")

                if action["action"] == "done":
                    status = "completed"
                    print("Task completed!")
                    break

                execute_action(action)
                delay_seconds = _action_delay(action)
                if delay_seconds > 0:
                    time.sleep(delay_seconds)
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
