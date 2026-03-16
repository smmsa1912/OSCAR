from __future__ import annotations

from oscar.prompt_builder import ACTION_SCHEMA, SYSTEM_PROMPT, build_prompt


def test_system_prompt_mentions_focus_and_reliability_rules() -> None:
    assert "active window title" in SYSTEM_PROMPT
    assert "Prefer save_file" in SYSTEM_PROMPT
    assert "Prefer close_app" in SYSTEM_PROMPT
    assert "open_app with url" in SYSTEM_PROMPT
    assert "up, down, left, and right" in SYSTEM_PROMPT
    assert "coordinate grid overlay" in SYSTEM_PROMPT
    assert "Do not claim that an app is open" in SYSTEM_PROMPT
    assert "Prefer terminal_command" in SYSTEM_PROMPT
    assert "Prefer uia_click" in SYSTEM_PROMPT
    assert "exact provided user-specific folder paths" in SYSTEM_PROMPT


def test_build_prompt_includes_context_history_schema_and_rules() -> None:
    history = [
        {
            "action": "open_app",
            "app_name": "notepad",
            "reasoning": "Launch Notepad directly.",
            "task_complete": False,
            "launch_confirmed": False,
        }
    ]

    prompt = build_prompt(
        "Open Notepad and type Hello",
        history,
        screen_size=(1920, 1080),
        step_number=2,
        max_steps=20,
        active_window_title="Untitled - Notepad",
        active_process_name="notepad.exe",
        cursor_position=(640, 480),
        known_paths={"downloads": r"C:\Users\andre\Downloads", "desktop": r"C:\Users\andre\Desktop"},
        ui_controls=[{"text": "OK", "automation_id": "CommandButton_6", "control_type": "Button"}],
    )

    assert "Open Notepad and type Hello" in prompt
    assert "Current step: 2 of 20." in prompt
    assert "Current screen size: 1920x1080." in prompt
    assert "Active window title: Untitled - Notepad." in prompt
    assert "Active process: notepad.exe." in prompt
    assert "Current cursor position: (640, 480)." in prompt
    assert '"action": "open_app"' in prompt
    assert '"terminal_command"' in ACTION_SCHEMA
    assert '"uia_click"' in ACTION_SCHEMA
    assert ACTION_SCHEMA in prompt
    assert "Prefer open_app with profile_name" in prompt
    assert "Prefer uia_click" in prompt
    assert "coordinate grid overlay" in prompt
    assert "Do not claim that an app is open" in prompt
    assert "Prefer terminal_command" in prompt
    assert "Exact user-specific folder paths:" in prompt
    assert r"C:\\Users\\andre\\Downloads" in prompt
    assert '"automation_id": "CommandButton_6"' in prompt
    assert "Recent execution note:" in prompt

