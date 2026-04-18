from __future__ import annotations

from oscar.prompt_builder import ACTION_SCHEMA, SYSTEM_PROMPT, build_prompt


def test_system_prompt_mentions_self_critique_and_reliability_rules() -> None:
    assert "self-critique" in SYSTEM_PROMPT.lower()
    assert "Before any browser action except browser_navigate, ALWAYS call browser_get_tabs() first." in SYSTEM_PROMPT
    assert "Before any uia_click, ALWAYS call uia_get_visible_elements() first." in SYSTEM_PROMPT
    assert "Prefer deterministic actions before visual guessing" in SYSTEM_PROMPT
    assert "browser_get_tabs" in SYSTEM_PROMPT
    assert "browser_type" in SYSTEM_PROMPT
    assert "uia_click_fallback_search" in SYSTEM_PROMPT
    assert '"grid_cell"' in ACTION_SCHEMA
    assert "terminal_command" in SYSTEM_PROMPT
    assert "normalized 1000x1000 screenshot grid" in SYSTEM_PROMPT
    assert "Never hardcode user names" in SYSTEM_PROMPT
    assert "Verify every step" in SYSTEM_PROMPT
    assert "Output ONLY valid JSON" in SYSTEM_PROMPT
    assert "Use visible Set-of-Mark element_id values whenever available" in SYSTEM_PROMPT
    assert "NEVER use PowerShell variables like $env:USERPROFILE in file_path arguments" in SYSTEM_PROMPT
    assert r"C:\Users\Username\Desktop" in SYSTEM_PROMPT
    assert "When using PowerShell here-strings" in SYSTEM_PROMPT
    assert "Prefer Set-Content -LiteralPath" in SYSTEM_PROMPT
    assert "Never interact with OSCAR's own desktop app window" in SYSTEM_PROMPT


def test_build_prompt_includes_runtime_context_and_persistent_memory() -> None:
    prompt = build_prompt(
        "Open the browser and search for red pandas",
        [{"action": "browser_open", "reasoning": "Open the browser.", "task_complete": False}],
        screen_size=(1920, 1080),
        step_number=2,
        max_steps=20,
        active_window_title="Example",
        active_process_name="msedge.exe",
        system_specs={
            "os_version": "Windows 11",
            "manufacturer": "HP",
        },
        cursor_position=(640, 480),
        known_paths={
            "downloads": r"C:\Users\user\Downloads",
            "desktop": r"C:\Users\user\Desktop",
        },
        ui_controls=[{"text": "Search", "element_id": 3, "control_type": "Edit"}],
        visible_windows=[{"title": "Edge", "process_name": "msedge.exe"}],
        current_local_time="2026-04-06T18:00:00+05:30",
        terminal_working_directory=r"C:\Users\user\Desktop",
        browser_url="https://example.com",
        browser_title="Example",
        browser_tabs=[{"id": 1, "title": "Example", "url": "https://example.com", "active": True}],
        failure_history=[{"action": {"action": "browser_click"}, "failure_reason": "selector_not_found"}],
        persistent_memory={
            "recent_apps": ["chrome"],
            "recent_paths": [r"C:\Users\user\Desktop"],
        },
        ui_element_summary="#3 Edit Search",
    )

    assert "Current step: 2 of 20." in prompt
    assert "Known runtime paths:" in prompt
    assert "Persistent short-term memory from recent runs:" in prompt
    assert '"recent_apps": [' in prompt
    assert "Observed visible UI elements:" in prompt
    assert "Most recently observed browser tabs:" in prompt
    assert "Observed UI summary:" in prompt
    assert '"element_id": 3' in prompt
    assert "Recent failures to avoid unless strategy changes:" in prompt
    assert "Mandatory reasoning checklist" in prompt
    assert ACTION_SCHEMA in prompt


def test_prompt_schema_avoids_user_specific_examples() -> None:
    assert "Andrew" not in SYSTEM_PROMPT
    assert "C:\\Users\\andre" not in ACTION_SCHEMA
    assert "<runtime path from known_paths or observed context>" in ACTION_SCHEMA
