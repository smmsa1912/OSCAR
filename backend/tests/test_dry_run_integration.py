from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from oscar import config, orchestrator as orchestrator_module
from oscar.context import TaskContext
from oscar.orchestrator import ContextUpdater, Orchestrator
from oscar.routing import ActionRouter


class _SequencePlanner:
    def __init__(self, action: dict[str, Any]) -> None:
        self._actions = iter(
            [
                action,
                {
                    "action": "done",
                    "reasoning": "Dry-run integration check complete.",
                    "task_complete": True,
                },
            ]
        )

    async def plan_next_action(self, context, memory):
        return next(self._actions)


class _Memory:
    def snapshot(self):
        return {"recent_apps": [], "recent_paths": [], "recent_actions": []}

    def record(self, *_args, **_kwargs):
        return None

    def save(self):
        return None


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("action", "expected_route"),
    [
        (
            {
                "action": "click",
                "x": 12,
                "y": 24,
                "reasoning": "Click a test coordinate.",
                "task_complete": False,
            },
            "ui",
        ),
        (
            {
                "action": "browser_navigate",
                "url": "https://example.com",
                "reasoning": "Navigate in the browser.",
                "task_complete": False,
            },
            "browser",
        ),
        (
            {
                "action": "terminal_command",
                "command": "Get-Location",
                "reasoning": "Inspect the working directory.",
                "task_complete": False,
            },
            "terminal",
        ),
        (
            {
                "action": "shortcut",
                "shortcut_name": "os.open_settings",
                "reasoning": "Open Settings.",
                "task_complete": False,
            },
            "shortcut",
        ),
    ],
)
async def test_orchestrator_routes_actions_without_side_effects_in_dry_run(
    action: dict[str, Any],
    expected_route: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Exercise the real orchestrator and router while forbidding OS/browser/process effects."""
    monkeypatch.setattr(config, "OSCAR_DRY_RUN", True)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("a real side effect was attempted during dry-run")

    # These functions cover the main low-level side-effect boundaries. Route-specific
    # dry-run guards should return before any of them are reached.
    monkeypatch.setattr("oscar.executor._get_pyautogui", forbidden)
    monkeypatch.setattr("oscar.executor._launch_process", forbidden)
    monkeypatch.setattr("oscar.agents.terminal_agent.asyncio.create_subprocess_exec", forbidden)
    monkeypatch.setattr("oscar.agents.shortcut_handler.ShortcutHandler._get_pyautogui", forbidden)
    monkeypatch.setattr("oscar.orchestrator.get_active_window_info", forbidden)
    monkeypatch.setattr("oscar.orchestrator.get_system_specs", forbidden)
    monkeypatch.setattr("oscar.orchestrator.list_visible_windows", forbidden)
    monkeypatch.setattr("oscar.orchestrator.capture_screenshot", forbidden)
    monkeypatch.setattr("oscar.orchestrator.capture_active_window_controls", forbidden)
    monkeypatch.setattr("oscar.orchestrator.get_cursor_position", forbidden)
    monkeypatch.setattr("oscar.orchestrator.focus_oscar_app_window", forbidden)

    monkeypatch.setattr(
        "oscar.orchestrator.PersistentMemoryStore.load", lambda: _Memory()
    )
    monkeypatch.setattr(
        "oscar.orchestrator.write_run_log", lambda **_kwargs: tmp_path / "run.json"
    )
    monkeypatch.setattr(
        "oscar.trace.ExecutionTrace.write_json",
        lambda self, logs_dir=None: tmp_path / "trace.json",
    )

    events: list[dict[str, Any]] = []

    async def ui_callback(event: dict[str, Any]) -> None:
        events.append(event)

    orchestrator = Orchestrator(
        planner=_SequencePlanner(action),
        router=ActionRouter(),
        context_updater=ContextUpdater(),
    )
    outcome = await orchestrator.run(
        f"dry-run integration: {action['action']}", ui_callback=ui_callback
    )

    step_result = next(
        event
        for event in events
        if event.get("type") == "step_result"
        and event.get("route") == expected_route
        and event.get("result", {}).get("data", {}).get("dry_run") is True
    )
    result_payload = step_result["result"]
    assert outcome.status == "completed"
    assert step_result["route"] == expected_route
    assert step_result["success"] is True
    assert result_payload["data"]["dry_run"] is True
    assert result_payload["data"]["execution_confirmed"] is False


@pytest.mark.anyio
async def test_orchestrator_stops_as_failed_when_planner_requests_stop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(config, "OSCAR_DRY_RUN", True)
    monkeypatch.setattr(
        "oscar.orchestrator.PersistentMemoryStore.load", lambda: _Memory()
    )
    monkeypatch.setattr(
        "oscar.orchestrator.write_run_log", lambda **_kwargs: tmp_path / "run.json"
    )
    monkeypatch.setattr(
        "oscar.trace.ExecutionTrace.write_json",
        lambda self, logs_dir=None: tmp_path / "trace.json",
    )

    class StopPlanner:
        async def plan_next_action(self, _context, _memory):
            return {
                "action": "done",
                "reasoning": "Stopped after repeated model errors.",
                "task_complete": False,
                "stop_execution": True,
                "failure_reason": "repeated_model_errors",
            }

    events: list[dict[str, Any]] = []

    async def ui_callback(event: dict[str, Any]) -> None:
        events.append(event)

    outcome = await Orchestrator(
        planner=StopPlanner(), router=ActionRouter(), context_updater=ContextUpdater()
    ).run("test planner stop handling", ui_callback=ui_callback)

    assert outcome.status == "failed"
    assert outcome.final_message == "Stopped after repeated model errors."
    assert any(
        event.get("type") == "task_stopped"
        and event.get("failure_reason") == "repeated_model_errors"
        for event in events
    )
    assert not any(event.get("type") == "task_completed" for event in events)
