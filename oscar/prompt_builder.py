"""Prompt construction for the Gemini step planner."""

from __future__ import annotations

import json

SYSTEM_PROMPT = """You are OSCAR, an AI agent that controls a computer by analyzing screenshots.
You will be given:
1. A screenshot of the current screen state
2. The user's goal/task
3. History of actions already taken

Your job is to decide the SINGLE NEXT ACTION to take to progress toward the goal.
Always choose the most reliable action available.
Prefer open_app for launching an application directly instead of clicking search UI.
Prefer press and hotkey actions over coordinate clicks when a keyboard shortcut can do the job.
If a previous action did not visibly change the screen, switch strategy instead of repeating it.
Always respond ONLY in valid JSON matching the schema provided.
Never include explanation outside the JSON block.
When the task is fully complete, set task_complete to true with action: done.
Be precise with coordinates and only use mouse actions when the target truly requires pointing."""

ACTION_SCHEMA = """{
  "action": "click" | "double_click" | "right_click" | "type" | "scroll" | "hotkey" | "press" | "open_app" | "screenshot" | "wait" | "done",
  "x": 500,
  "y": 300,
  "text": "hello",
  "keys": ["ctrl", "s"],
  "key": "enter",
  "app_name": "notepad",
  "direction": "down",
  "amount": 3,
  "seconds": 1.0,
  "reasoning": "why this is the next best step",
  "task_complete": false
}"""


def build_prompt(
    task: str,
    history: list[dict],
    *,
    screen_size: tuple[int, int] | None = None,
    step_number: int | None = None,
    max_steps: int | None = None,
    history_limit: int = 10,
) -> str:
    """Build the user prompt for the next Gemini call."""

    recent_history = history[-history_limit:]
    rendered_history = json.dumps(recent_history, indent=2) if recent_history else "[]"

    parts = [
        "User task:",
        task,
    ]

    if step_number is not None and max_steps is not None:
        parts.extend(
            [
                "",
                f"Current step: {step_number} of {max_steps}.",
            ]
        )

    if screen_size is not None:
        width, height = screen_size
        parts.extend(
            [
                "",
                f"Current screen size: {width}x{height}.",
            ]
        )

    parts.extend(
        [
            "",
            "Recent action history:",
            rendered_history,
            "",
            "Reliability rules:",
            "- Prefer open_app to launch apps like Notepad, Calculator, Edge, Explorer, or VS Code.",
            "- Prefer press or hotkey for Start/Search, Enter, Tab, Escape, Alt+Tab, Win shortcuts, and menu navigation.",
            "- If the last action failed or the screen did not change, choose a different action instead of repeating the same click.",
            "",
            "Return one JSON object only. Follow this schema exactly:",
            ACTION_SCHEMA,
            "",
            "If the task is complete, respond with action 'done' and task_complete true.",
        ]
    )

    return "\n".join(parts)
