from __future__ import annotations

import pytest

from oscar.brain.planner import GeminiBrain, ModelBrain
from oscar.context import TaskContext
from oscar.gemini_client import GeminiResponseError
from oscar.memory import TaskMemory


def _context(task: str, **overrides):
    values = {
        "task": task,
        "current_working_directory": "A:\\workspace\\project",
        "current_local_time": "2026-04-06T18:00:00+05:30",
    }
    values.update(overrides)
    return TaskContext(**values)


@pytest.mark.anyio
async def test_planner_answers_current_time_directly_from_context() -> None:
    planner = GeminiBrain(ask_model=lambda *_args, **_kwargs: {"action": "wait"})

    action = await planner.plan_next_action(
        _context("tell me current time"),
        TaskMemory(),
    )

    assert action == {
        "action": "done",
        "reasoning": "The current local time is 2026-04-06T18:00:00+05:30.",
        "task_complete": True,
    }


@pytest.mark.anyio
async def test_planner_answers_current_date_directly_from_context() -> None:
    planner = GeminiBrain(ask_model=lambda *_args, **_kwargs: {"action": "wait"})

    action = await planner.plan_next_action(
        _context("todays date?"),
        TaskMemory(),
    )

    assert action == {
        "action": "done",
        "reasoning": "Today's local date is 2026-04-06.",
        "task_complete": True,
    }


@pytest.mark.anyio
async def test_planner_does_not_shortcut_remote_time_difference_question() -> None:
    planner = GeminiBrain(
        ask_model=lambda *_args, **_kwargs: {
            "action": "browser_search",
            "query": "current time in Canada time difference with India",
            "reasoning": "This requires looking up another region's current time.",
            "task_complete": False,
        }
    )

    action = await planner.plan_next_action(
        _context("current time in Canada and tell me time difference from my time"),
        TaskMemory(),
    )

    assert action == {
        "action": "browser_search",
        "query": "current time canada time difference",
        "reasoning": "This requires looking up another region's current time.",
        "task_complete": False,
    }


@pytest.mark.anyio
async def test_planner_returns_wait_until_before_future_timed_work() -> None:
    planner = GeminiBrain(ask_model=lambda *_args, **_kwargs: {"action": "done"})

    action = await planner.plan_next_action(
        _context(
            "when the time reaches 6:05 PM open chrome and visit github.com",
            current_local_time="2026-04-06T18:00:00+05:30",
        ),
        TaskMemory(),
    )

    assert action["action"] == "wait_until"
    assert action["timestamp"] == "2026-04-06T18:05:00+05:30"


@pytest.mark.anyio
async def test_planner_post_processes_browser_search_queries() -> None:
    planner = GeminiBrain(
        ask_model=lambda *_args, **_kwargs: {
            "action": "browser_search",
            "query": "please search for a pomerian dog image on google",
            "reasoning": "Search the web.",
            "task_complete": False,
        }
    )

    action = await planner.plan_next_action(
        _context("search for a pomerian dog image"),
        TaskMemory(),
    )

    assert action["action"] == "browser_search"
    assert action["query"] == "pomeranian dog"


@pytest.mark.anyio
async def test_planner_normalizes_navigation_url() -> None:
    planner = GeminiBrain(
        ask_model=lambda *_args, **_kwargs: {
            "action": "browser_navigate",
            "url": "github.com",
            "reasoning": "Open GitHub.",
            "task_complete": False,
        }
    )

    action = await planner.plan_next_action(
        _context("open github"),
        TaskMemory(),
    )

    assert action["action"] == "browser_navigate"
    assert action["url"] == "https://github.com"


@pytest.mark.anyio
async def test_planner_recovers_from_model_json_errors() -> None:
    def broken_model(*_args, **_kwargs):
        raise GeminiResponseError("Gemini returned invalid JSON")

    planner = GeminiBrain(ask_model=broken_model)

    action = await planner.plan_next_action(
        _context("open notepad"),
        TaskMemory(),
    )

    assert action == {
        "action": "wait",
        "seconds": 3,
        "reasoning": "Recovering from a model response or planning error.",
        "task_complete": False,
    }


@pytest.mark.anyio
async def test_planner_injects_element_id_for_matching_visible_control() -> None:
    planner = GeminiBrain(
        ask_model=lambda *_args, **_kwargs: {
            "action": "ui_click",
            "target_text": "Performance",
            "control_type": "Button",
            "reasoning": "Open the performance section.",
            "task_complete": False,
        }
    )

    action = await planner.plan_next_action(
        _context(
            "open the performance section",
            ui_controls=[
                {
                    "element_id": 7,
                    "text": "Performance",
                    "control_type": "Button",
                }
            ],
        ),
        TaskMemory(),
    )

    assert action["action"] == "ui_click"
    assert action["element_id"] == 7


@pytest.mark.anyio
async def test_planner_critiques_raw_clicks_when_uia_targets_exist() -> None:
    responses = iter(
        [
            {
                "action": "click",
                "x": 500,
                "y": 500,
                "reasoning": "Guess a coordinate.",
                "task_complete": False,
            },
            {
                "action": "ui_click",
                "target_text": "Images",
                "reasoning": "Use the visible accessible control instead.",
                "task_complete": False,
            },
        ]
    )

    planner = GeminiBrain(ask_model=lambda *_args, **_kwargs: next(responses))

    action = await planner.plan_next_action(
        _context(
            "click the Images tab",
            ui_controls=[{"element_id": 3, "text": "Images", "control_type": "Button"}],
        ),
        TaskMemory(),
    )

    assert action["action"] == "ui_click"
    assert action["element_id"] == 3


@pytest.mark.anyio
async def test_planner_critiques_hardcoded_user_paths_and_revises() -> None:
    prompts: list[str] = []
    responses = iter(
        [
            {
                "action": "terminal_command",
                "command": r"Set-Content 'C:\Users\someone\Desktop\note.txt' 'hello'",
                "reasoning": "Write the file quickly.",
                "task_complete": False,
            },
            {
                "action": "terminal_command",
                "command": "Set-Content -LiteralPath \"$env:USERPROFILE\\Desktop\\note.txt\" -Value \"hello\"",
                "reasoning": "Use a runtime-resolved user path instead.",
                "task_complete": False,
            },
        ]
    )

    def fake_model(_screenshot, prompt, **_kwargs):
        prompts.append(prompt)
        return next(responses)

    planner = GeminiBrain(ask_model=fake_model)

    action = await planner.plan_next_action(
        _context("create a note on my desktop"),
        TaskMemory(),
    )

    assert action["action"] == "terminal_command"
    assert "$env:USERPROFILE\\Desktop\\note.txt" in action["command"]
    assert any("Do not hardcode user home paths" in prompt for prompt in prompts)


@pytest.mark.anyio
async def test_planner_keeps_model_shortcuts_open_ended_for_multi_step_tasks() -> None:
    planner = GeminiBrain(
        ask_model=lambda *_args, **_kwargs: {
            "action": "shortcut",
            "shortcut_name": "os.open_settings",
            "reasoning": "Open Settings first.",
            "task_complete": False,
        }
    )

    action = await planner.plan_next_action(
        _context("launch settings and turn on bluetooth"),
        TaskMemory(),
    )

    assert action == {
        "action": "shortcut",
        "shortcut_name": "os.open_settings",
        "reasoning": "Open Settings first.",
        "task_complete": False,
    }


@pytest.mark.anyio
async def test_planner_requires_browser_tab_observation_before_switching_tabs() -> None:
    responses = iter(
        [
            {
                "action": "browser_switch_tab",
                "url": "https://web.whatsapp.com",
                "title_contains": "WhatsApp",
                "reasoning": "Switch to the WhatsApp tab.",
                "task_complete": False,
            },
            {
                "action": "browser_get_tabs",
                "reasoning": "Inspect the currently open browser tabs before switching.",
                "task_complete": False,
            },
        ]
    )
    planner = GeminiBrain(ask_model=lambda *_args, **_kwargs: next(responses))

    action = await planner.plan_next_action(
        _context("switch to the WhatsApp tab", browser_url="https://github.com"),
        TaskMemory(),
    )

    assert action["action"] == "browser_get_tabs"


@pytest.mark.anyio
async def test_planner_requires_visible_element_observation_before_uia_click() -> None:
    responses = iter(
        [
            {
                "action": "uia_click",
                "target_text": "Windows Update",
                "control_type": ["NavigationViewItem", "Hyperlink"],
                "reasoning": "Click the Windows Update entry.",
                "task_complete": False,
            },
            {
                "action": "uia_get_visible_elements",
                "max_depth": 3,
                "reasoning": "Inspect visible controls before choosing a semantic UI click.",
                "task_complete": False,
            },
        ]
    )
    planner = GeminiBrain(ask_model=lambda *_args, **_kwargs: next(responses))

    action = await planner.plan_next_action(
        _context("open Windows Update in Settings"),
        TaskMemory(),
    )

    assert action["action"] == "uia_get_visible_elements"


@pytest.mark.anyio
async def test_planner_critiques_window_control_for_input_intent() -> None:
    prompts: list[str] = []
    responses = iter(
        [
            {
                "action": "ui_click",
                "target_text": "Minimize",
                "automation_id": "Minimize",
                "reasoning": "Click the search input so I can type.",
                "task_complete": False,
            },
            {
                "action": "ui_click",
                "grid_cell": "C2",
                "reasoning": "Use grid fallback for the search input.",
                "task_complete": False,
            },
        ]
    )

    def fake_model(_screenshot, prompt, **_kwargs):
        prompts.append(prompt)
        return next(responses)

    memory = TaskMemory()
    memory.record_step(
        {"action": "uia_get_visible_elements"},
        "ui",
        {"success": True},
        success=True,
    )
    planner = GeminiBrain(ask_model=fake_model)

    action = await planner.plan_next_action(
        _context("search settings"),
        memory,
    )

    assert action["action"] == "ui_click"
    assert action["grid_cell"] == "C2"
    assert any(
        "CRITICAL: Your reasoning indicates you want to interact with an input or search bar"
        in prompt
        for prompt in prompts
    )



@pytest.mark.anyio
async def test_planner_error_recovery_message_is_not_json_specific() -> None:
    def unavailable_model(*_args, **_kwargs):
        raise RuntimeError("provider unavailable")

    planner = GeminiBrain(ask_model=unavailable_model)
    action = await planner.plan_next_action(_context("open notepad"), TaskMemory())

    assert action["action"] == "wait"
    assert "model response or planning error" in action["reasoning"]



def test_planner_stops_task_when_token_budget_is_exhausted() -> None:
    planner = GeminiBrain(ask_model=lambda *_args, **_kwargs: {"action": "wait"})
    action = planner._recover_from_model_error(
        RuntimeError("OSCAR stopped before the model request because this task reached its configured token budget")
    )
    assert action["action"] == "done"
    assert action["task_complete"] is True
    assert "token budget" in action["reasoning"]



@pytest.mark.anyio
async def test_omniroute_token_budget_error_stops_planning_without_retry() -> None:
    from oscar.token_budget import TokenBudgetExceeded

    class ExhaustedProvider:
        provider_name = "omniroute"
        default_model = "auto/best-fast"

        def generate_action(self, *_args, **_kwargs):
            raise TokenBudgetExceeded(
                "Today's configured OmniRoute token budget would be exceeded."
            )

    planner = ModelBrain(provider=ExhaustedProvider())
    action = await planner.plan_next_action(
        _context("Open the browser and search for a topic"),
        TaskMemory(),
    )
    assert action["action"] == "done"
    assert action["task_complete"] is True
    assert "token budget" in action["reasoning"].lower()
