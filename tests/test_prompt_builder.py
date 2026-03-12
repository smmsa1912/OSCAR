from __future__ import annotations

from oscar.prompt_builder import ACTION_SCHEMA, SYSTEM_PROMPT, build_prompt


def test_system_prompt_mentions_reliable_shortcuts() -> None:
    assert "Prefer open_app" in SYSTEM_PROMPT
    assert "Prefer press and hotkey actions" in SYSTEM_PROMPT


def test_build_prompt_includes_task_history_schema_and_rules() -> None:
    history = [
        {
            "action": "click",
            "x": 120,
            "y": 220,
            "reasoning": "Open the start menu.",
            "task_complete": False,
        }
    ]

    prompt = build_prompt(
        "Open Notepad and type Hello",
        history,
        screen_size=(1920, 1080),
        step_number=2,
        max_steps=20,
    )

    assert "Open Notepad and type Hello" in prompt
    assert "Current step: 2 of 20." in prompt
    assert "Current screen size: 1920x1080." in prompt
    assert '"action": "click"' in prompt
    assert '"action": "click" | "double_click" | "right_click" | "type" | "scroll" | "hotkey" | "press" | "open_app"' in ACTION_SCHEMA
    assert ACTION_SCHEMA in prompt
    assert "Prefer open_app to launch apps like Notepad" in prompt
