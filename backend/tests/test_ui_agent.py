from __future__ import annotations

import asyncio

import pytest

from oscar.executor import ActionValidationError
from oscar.agents.ui_agent import UIAgent


@pytest.mark.anyio
async def test_ui_agent_returns_retryable_failure_when_execution_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = UIAgent()

    async def fake_run_sync(_func):
        raise asyncio.CancelledError()

    monkeypatch.setattr("oscar.agents.ui_agent.anyio.to_thread.run_sync", fake_run_sync)

    result = await agent.run(
        {
            "action": "ui_click",
            "target_text": "OK",
            "reasoning": "Click OK.",
            "task_complete": False,
        }
    )

    assert result.success is False
    assert result.retryable is True
    assert result.failure_reason == "Execution cancelled"


@pytest.mark.anyio
async def test_ui_agent_does_not_swallow_pyautogui_failsafe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = UIAgent()

    class FailSafeException(Exception):
        __module__ = "pyautogui"

    async def fake_run_sync(_func):
        raise FailSafeException("abort")

    monkeypatch.setattr("oscar.agents.ui_agent.anyio.to_thread.run_sync", fake_run_sync)

    with pytest.raises(FailSafeException, match="abort"):
        await agent.run(
            {
                "action": "ui_click",
                "target_text": "OK",
                "reasoning": "Click OK.",
                "task_complete": False,
            }
        )


@pytest.mark.anyio
async def test_ui_agent_verifies_open_app_by_window_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = UIAgent()

    async def fake_run_sync(func):
        return func()

    monkeypatch.setattr("oscar.agents.ui_agent.anyio.to_thread.run_sync", fake_run_sync)
    monkeypatch.setattr("oscar.agents.ui_agent.execute_action", lambda action: None)
    monkeypatch.setattr("oscar.agents.ui_agent.focus_app_window", lambda app_name, timeout: True)
    monkeypatch.setattr("oscar.agents.ui_agent.app_window_exists", lambda app_name: True)

    result = await agent.run(
        {
            "action": "open_app",
            "app_name": "chrome",
            "reasoning": "Open Chrome.",
            "task_complete": False,
        }
    )

    assert result.success is True
    assert result.confidence == 0.8


@pytest.mark.anyio
async def test_ui_agent_treats_type_action_as_sent_when_no_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = UIAgent()

    async def fake_run_sync(func):
        return func()

    monkeypatch.setattr("oscar.agents.ui_agent.anyio.to_thread.run_sync", fake_run_sync)
    monkeypatch.setattr("oscar.agents.ui_agent.execute_action", lambda action: None)

    result = await agent.run(
        {
            "action": "type",
            "text": "hello",
            "reasoning": "Type text.",
            "task_complete": False,
        }
    )

    assert result.success is True
    assert result.data["execution_confirmed"] is True
    assert result.data["verification_source"] == "input_dispatch"


@pytest.mark.anyio
async def test_ui_agent_falls_back_to_aligned_coordinate_when_uia_click_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = UIAgent()
    calls: list[dict[str, object]] = []

    async def fake_run_sync(func):
        return func()

    def fake_execute(action):
        calls.append(dict(action))
        if action["action"] == "uia_click":
            raise ActionValidationError("Failed to find or click the requested UI automation control.")
        return None

    monkeypatch.setattr("oscar.agents.ui_agent.anyio.to_thread.run_sync", fake_run_sync)
    monkeypatch.setattr("oscar.agents.ui_agent.execute_action", fake_execute)

    result = await agent.run(
        {
            "action": "ui_click",
            "target_text": "PERFORMANCE",
            "control_type": "Text",
            "x": 140,
            "y": 105,
            "reasoning": "Click the PERFORMANCE control in the OMEN sidebar.",
            "task_complete": False,
        }
    )

    assert [call["action"] for call in calls] == ["uia_click", "click"]
    assert result.success is True
    assert result.data["fallback_used"] == "coordinate_click"
    assert result.confidence == 0.45


@pytest.mark.anyio
async def test_ui_agent_grid_cell_overrides_semantic_window_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = UIAgent()
    calls: list[dict[str, object]] = []

    async def fake_run_sync(func):
        return func()

    def fake_execute(action):
        calls.append(dict(action))
        return None

    monkeypatch.setattr("oscar.agents.ui_agent.anyio.to_thread.run_sync", fake_run_sync)
    monkeypatch.setattr("oscar.agents.ui_agent.execute_action", fake_execute)

    result = await agent.run(
        {
            "action": "ui_click",
            "grid_cell": "C2",
            "screen_size": (1000, 1000),
            "element_id": 1,
            "target_text": "Minimize",
            "automation_id": "Minimize",
            "control_type": "Button",
            "x": 5,
            "y": 5,
            "reasoning": "Use the grid fallback for the search input.",
            "task_complete": False,
        }
    )

    assert calls == [
        {
            "reasoning": "Use the grid fallback for the search input.",
            "task_complete": False,
            "action": "click",
            "x": 150,
            "y": 250,
            "_grid_resolved": "C2",
        }
    ]
    assert result.success is True
