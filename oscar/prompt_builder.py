"""Prompt construction for the Gemini step planner."""

from __future__ import annotations

import json

SYSTEM_PROMPT = """You are OSCAR, an AI agent that controls a computer by analyzing screenshots.
You will be given:
1. A screenshot of the current screen state
2. The user's goal/task
3. History of actions already taken
4. The active window title, active process, and current cursor position

Your job is to decide the SINGLE NEXT ACTION to take to progress toward the goal.
Always choose the most reliable action available.
Prefer open_app for launching or refocusing applications directly instead of clicking search UI.
Prefer open_app with url for browser searches or navigation instead of typing into the address bar when possible.
Prefer close_app over mouse clicks when the task is to close a window.
Prefer press and hotkey actions over coordinate clicks when a keyboard shortcut can do the job.
Use press for keys like enter, tab, escape, up, down, left, and right when keyboard navigation is more reliable than clicking.
Prefer save_file when a plain text file must be saved to a specific path.
For Chrome tasks, prefer open_app with profile_name when a named profile is requested.
If multiple apps are requested, open them one at a time and avoid reopening apps that are already open.
Before typing or sending hotkeys, make sure the intended app is focused based on the active window/process information.
If a previous action did not visibly change the screen, switch strategy instead of repeating it.
Do not click Chrome profile tiles or Save As sidebar folders when open_app or save_file can achieve the same result more reliably.
Always respond ONLY in valid JSON matching the schema provided.
Never include explanation outside the JSON block.
When the task is fully complete, set task_complete to true with action: done.
Be precise with coordinates and only use mouse actions when the target truly requires pointing."""

ACTION_SCHEMA = """{
  "action": "click" | "double_click" | "right_click" | "type" | "scroll" | "hotkey" | "press" | "open_app" | "close_app" | "save_file" | "screenshot" | "wait" | "done",
  "x": 500,
  "y": 300,
  "text": "hello",
  "keys": ["ctrl", "s"],
  "key": "enter",
  "app_name": "notepad",
  "profile_name": "Andrew",
  "url": "https://github.com",
  "file_path": "C:\\\\Users\\\\andre\\\\Desktop\\\\Hello World.txt",
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
    active_window_title: str | None = None,
    active_process_name: str | None = None,
    cursor_position: tuple[int, int] | None = None,
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

    if active_window_title is not None or active_process_name is not None:
        parts.extend(
            [
                "",
                f"Active window title: {active_window_title or 'Unknown'}.",
                f"Active process: {active_process_name or 'Unknown'}.",
            ]
        )

    if cursor_position is not None:
        cursor_x, cursor_y = cursor_position
        parts.extend(
            [
                f"Current cursor position: ({cursor_x}, {cursor_y}).",
            ]
        )

    parts.extend(
        [
            "",
            "Recent action history:",
            rendered_history,
            "",
            "Reliability rules:",
            "- Prefer open_app to launch or refocus apps like Notepad, Calculator, Chrome, Edge, Explorer, Task Manager, PowerShell, VS Code, Brave, or Firefox.",
            "- Prefer open_app with profile_name for named Chrome profiles instead of clicking the profile picker.",
            "- Prefer open_app with url for browser searches or navigation instead of typing into the address bar when possible.",
            "- Prefer close_app when the user asks to close a window.",
            "- Prefer press or hotkey for Start/Search, Enter, Tab, Escape, Alt+Tab, Win shortcuts, and menu navigation.",
            "- Use press with up/down/left/right or tab/enter when keyboard navigation is safer than a mouse click.",
            "- Prefer save_file when saving a plain text document to a concrete path is the next step.",
            "- Only type when the intended app is focused based on the active window and process context.",
            "- If multiple apps are requested, open them one at a time and do not reopen windows that are already open.",
            "- Do not click Chrome profile tiles or Save As sidebar folders when a deterministic action can avoid that click.",
            "- If the last action failed or the screen did not change, choose a different action instead of repeating the same click.",
            "",
            "Return one JSON object only. Follow this schema exactly:",
            ACTION_SCHEMA,
            "",
            "If the task is complete, respond with action 'done' and task_complete true.",
        ]
    )

    return "\n".join(parts)
