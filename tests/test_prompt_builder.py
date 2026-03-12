from __future__ import annotations

from oscar.prompt_builder import ACTION_SCHEMA, SYSTEM_PROMPT, build_prompt


def test_system_prompt_mentions_focus_and_profile_rules() -> None:
    assert "active window title" in SYSTEM_PROMPT
    assert "Prefer save_file" in SYSTEM_PROMPT
    assert "profile_name" in SYSTEM_PROMPT


def test_build_prompt_includes_context_history_schema_and_rules() -> None:
    history = [
        {
            "action": "open_app",
            "app_name": "notepad",
            "reasoning": "Launch Notepad directly.",
            "task_complete": False,
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
    )

    assert "Open Notepad and type Hello" in prompt
    assert "Current step: 2 of 20." in prompt
    assert "Current screen size: 1920x1080." in prompt
    assert "Active window title: Untitled - Notepad." in prompt
    assert "Active process: notepad.exe." in prompt
    assert "Current cursor position: (640, 480)." in prompt
    assert '"action": "open_app"' in prompt
    assert '"action": "click" | "double_click" | "right_click" | "type" | "scroll" | "hotkey" | "press" | "open_app" | "save_file"' in ACTION_SCHEMA
    assert ACTION_SCHEMA in prompt
    assert "Prefer open_app with profile_name" in prompt
