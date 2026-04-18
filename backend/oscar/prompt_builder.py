"""Prompt construction for the Gemini step planner."""

from __future__ import annotations

import json
from typing import Any


SYSTEM_PROMPT = """You are OSCAR, an AI agent that controls a desktop computer from screenshots and structured runtime context.
Mandatory rules:
- Before any browser action except browser_navigate, ALWAYS call browser_get_tabs() first.
- Before any uia_click, ALWAYS call uia_get_visible_elements() first.
- Never assume tab titles contain notification badges. Prefer URL matching first and partial title matching second.
- If an action fails, analyze the error and the freshly observed current state, then try a different strategy instead of repeating the same action.

You receive:
1. The user task
2. The current screenshot when visual context is required
3. Recent action history and recent failures
4. Active window/process details
5. Known user paths resolved at runtime
6. Optional UI automation controls and visible windows
7. Current browser URL/title and terminal working directory when available
8. System/hardware information and persistent short-term memory from recent runs

You must choose the SINGLE BEST NEXT ACTION.
Your internal workflow is:
1. Silently decompose the task into reliable steps.
2. Silently evaluate the strongest tool for the immediate next step.
3. Silently self-critique the draft action:
   - Is there a more deterministic option?
   - Can this be verified immediately after execution?
   - Does it avoid blind clicking or hardcoded paths?
4. Output only the revised final JSON action.

Reliability rules:
- Prefer deterministic actions before visual guessing.
- Prefer terminal_command for explicit filesystem, project, or shell work.
- Prefer browser_open, browser_get_tabs, browser_navigate, browser_search, browser_switch_tab, browser_click, browser_find, browser_type, browser_wait_for, and browser_extract for web tasks before any desktop click fallback.
- Prefer focus_app or open_app over clicking taskbar icons, start menu tiles, or search panes.
- Prefer shortcut over raw hotkey when a named shortcut exists.
- Prefer uia_get_visible_elements before any semantic UI click, then use uia_click or element_id when a visible accessible control is available.
- Use uia_click_fallback_search only as a final deterministic fallback when a visible search box can navigate to the requested destination more reliably than repeated clicks.
- Only use raw x/y coordinates as the last resort, and then use the normalized 1000x1000 screenshot grid instead of raw pixels.
- Never interact with OSCAR's own desktop app window as part of the task. If OSCAR is in the foreground, first focus the real target app. Only return focus to OSCAR after the task ends.
- Never hardcode user names, absolute home paths, or guessed profile names. Use only runtime-provided paths and context.
- NEVER use PowerShell variables like $env:USERPROFILE in file_path arguments. Use standard absolute Windows paths (e.g., C:\\Users\\Username\\Desktop) or use the ~ symbol for the user home directory.
- Never repeat a failed action unless the strategy has materially changed.
- Never mark the task complete until the requested result has been observed or deterministically confirmed.
- Verify every step before moving on.

Browser rules:
- Treat browser app names like chrome, edge, brave, and firefox as apps, not URLs.
- For website work, prefer semantic browser actions instead of OS-level typing and clicking.
- Convert long natural-language search requests into short keyword queries.
- Break browser work into small semantic steps such as open, switch tab, navigate, search, click, type, wait, extract, and download follow-up actions.

Desktop rules:
- Before clicking or typing, make sure the target app/window is the intended one from runtime context.
- Prefer keyboard navigation and accessibility controls over raw pointer input.
- Use visible Set-of-Mark element_id values whenever available.
- If raw x/y is unavoidable, return coordinates on the normalized 1000x1000 screenshot grid where (0,0) is top-left and (1000,1000) is bottom-right.

Completion rules:
- If the task can be answered directly from runtime context, respond with action done.
- When the task is complete, return action done with task_complete true.
- Output ONLY valid JSON matching the schema.

Strategic Playbook (Fallback Heuristics):
- App Launching: If open_app fails to find an application, do NOT try it again. Instead, use the shortcut tool with os.search, followed by a type action to search the OS natively.
- File Editing: If you need to create or edit a file and UI text editors are failing, pivot immediately to the terminal agent. Use standard shell commands (echo, cat) or write a quick Python script to manipulate the file.
- PowerShell File Writes: When using PowerShell here-strings, put the opening @" or @' at the very end of its own line and the closing "@ or '@ at the start of its own line. Prefer Set-Content -LiteralPath for generated files.
- UI Interaction: If semantic element_id clicks fail or return empty elements, do not guess element IDs. Pivot immediately to using the vision grid_cell coordinates."""


ACTION_SCHEMA = """{
  "action": "browser_open" | "browser_get_tabs" | "browser_navigate" | "browser_search" | "browser_switch_tab" | "browser_click" | "browser_find" | "browser_type" | "browser_wait_for" | "browser_extract" | "terminal_command" | "shortcut" | "ui_click" | "click" | "double_click" | "right_click" | "uia_click" | "uia_get_visible_elements" | "uia_click_fallback_search" | "type" | "scroll" | "hotkey" | "press" | "open_app" | "focus_app" | "open_file" | "new_document" | "close_tab" | "close_app" | "save_file" | "screenshot" | "wait" | "wait_until" | "done",
  "x": 500,
  "y": 500,
  "grid_cell": "C2",
  "element_id": 12,
  "target_text": "visible label from runtime UI snapshot",
  "control_type": "Button" | ["NavigationViewItem", "ListItem", "Button", "Hyperlink"],
  "automation_id": "runtime automation id",
  "class_name": "runtime class name",
  "text": "text to type or semantic browser label/tab name",
  "title_contains": "partial tab title text",
  "query": "short keyword query",
  "shortcut_name": "os.open_settings",
  "selector_strategy": "role",
  "browser_name": "chrome",
  "session_mode": "managed",
  "keys": ["ctrl", "s"],
  "key": "enter",
  "app_name": "settings",
  "profile_name": "<runtime-visible browser profile name if explicitly requested>",
  "url": "https://example.com",
  "file_path": "<runtime path from known_paths or observed context>",
  "command": "Get-ChildItem .",
  "working_directory": "<runtime working directory or known path>",
  "direction": "down",
  "amount": 3,
  "seconds": 1.0,
  "time_of_day": "12:00:00",
  "timestamp": "2026-04-06T12:00:00+05:30",
  "max_depth": 3,
  "reasoning": "short explanation of the most reliable next step",
  "expected_outcome": "what should change after this step",
  "verification_hint": "how OSCAR can confirm the step worked",
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
    system_specs: dict[str, Any] | None = None,
    cursor_position: tuple[int, int] | None = None,
    known_paths: dict[str, str] | None = None,
    ui_controls: list[dict[str, Any]] | None = None,
    visible_windows: list[dict[str, Any]] | None = None,
    current_local_time: str | None = None,
    terminal_working_directory: str | None = None,
    browser_url: str | None = None,
    browser_title: str | None = None,
    browser_tabs: list[dict[str, Any]] | None = None,
    failure_history: list[dict[str, Any]] | None = None,
    persistent_memory: dict[str, Any] | None = None,
    ui_element_summary: str | None = None,
) -> str:
    """Build the user prompt for the next Gemini call."""

    recent_history = history[-history_limit:]
    rendered_history = json.dumps(recent_history, indent=2) if recent_history else "[]"

    parts = ["User task:", task]

    if step_number is not None and max_steps is not None:
        parts.extend(["", f"Current step: {step_number} of {max_steps}."])

    if current_local_time is not None:
        parts.extend(["", f"Current local date/time: {current_local_time}."])

    if screen_size is not None:
        width, height = screen_size
        parts.extend(["", f"Current screen size: {width}x{height}."])

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
        parts.append(f"Current cursor position: ({cursor_x}, {cursor_y}).")

    if terminal_working_directory is not None:
        parts.extend(
            [
                "",
                f"Current terminal working directory: {terminal_working_directory}.",
            ]
        )

    if browser_url is not None or browser_title is not None:
        parts.extend(
            [
                "",
                f"Current browser URL: {browser_url or 'Unknown'}.",
                f"Current browser title: {browser_title or 'Unknown'}.",
            ]
        )

    if browser_tabs:
        parts.extend(["", "Most recently observed browser tabs:", json.dumps(browser_tabs, indent=2)])

    if known_paths:
        parts.extend(
            [
                "",
                "Known runtime paths:",
                json.dumps(known_paths, indent=2),
            ]
        )

    if system_specs:
        parts.extend(
            [
                "",
                "Current hardware/system profile:",
                json.dumps(system_specs, indent=2),
            ]
        )

    if persistent_memory:
        parts.extend(
            [
                "",
                "Persistent short-term memory from recent runs:",
                json.dumps(persistent_memory, indent=2),
            ]
        )

    if visible_windows:
        parts.extend(
            [
                "",
                "Visible top-level windows:",
                json.dumps(visible_windows[:12], indent=2),
            ]
        )

    if ui_controls:
        parts.extend(
            [
                "",
                "Observed visible UI elements:",
                json.dumps(ui_controls[:25], indent=2),
            ]
        )
        if ui_element_summary:
            parts.extend(["", "Observed UI summary:", ui_element_summary])

    parts.extend(["", "Recent action history:", rendered_history])

    if failure_history:
        parts.extend(
            [
                "",
                "Recent failures to avoid unless strategy changes:",
                json.dumps(failure_history[-5:], indent=2),
            ]
        )

    parts.extend(
        [
            "",
            "Mandatory reasoning checklist (do this internally before answering):",
            "- What is the most deterministic next step?",
            "- Is there a keyboard, terminal, browser, shortcut, or UIA method that is stronger than a pixel click?",
            "- How will OSCAR verify success immediately after the step?",
            "- Would this action repeat a recent failure or rely on a guessed path/value?",
            "",
            "Output schema:",
            ACTION_SCHEMA,
        ]
    )

    return "\n".join(parts)
