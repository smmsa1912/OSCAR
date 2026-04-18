from __future__ import annotations

import pytest

import oscar.orchestrator as orchestrator_module
from oscar.context import TaskContext
from oscar.memory import TaskMemory
from oscar.orchestrator import ContextUpdater, Orchestrator
from oscar.runtime import ActionResult


class FakePlanner:
    def __init__(self) -> None:
        self.calls: list[tuple[TaskContext, TaskMemory]] = []
        self._actions = iter(
            [
                {"action": "terminal_command", "command": "git status", "reasoning": "Check git.", "task_complete": False},
                {"action": "done", "reasoning": "Finished.", "task_complete": True},
            ]
        )

    async def plan_next_action(self, context: TaskContext, memory: TaskMemory):
        self.calls.append((context, memory))
        return next(self._actions)


class FakeRouter:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def dispatch(self, action, context, memory, forced_route=None):
        self.calls.append(dict(action))
        return ActionResult(
            success=True,
            route="terminal",
            action=str(action["action"]),
            context_updates={
                "current_working_directory": "A:\\Andrew\\Code\\OSCAR_codex",
                "last_command_result": {
                    "command": "git status",
                    "cwd": "A:\\Andrew\\Code\\OSCAR_codex",
                    "stdout": "clean",
                    "stderr": "",
                    "exit_code": 0,
                    "success": True,
                },
            },
        )


class FakeRetryManager:
    def __init__(self, router=None) -> None:
        self.calls: list[tuple[dict, ActionResult]] = []

    async def resolve(self, action, result, context, memory):
        self.calls.append((dict(action), result))
        return action, result


@pytest.mark.anyio
async def test_orchestrator_passes_memory_and_updates_context_without_ui_snapshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    planner = FakePlanner()
    router = FakeRouter()
    retry_manager = FakeRetryManager()
    updater = ContextUpdater()
    ui_events: list[dict] = []
    screenshot_calls: list[object] = []
    trace_calls: list[dict] = []

    async def ui_callback(event: dict) -> None:
        ui_events.append(event)

    monkeypatch.setattr(
        "oscar.orchestrator.capture_screenshot",
        lambda _region=None: (screenshot_calls.append(object()) or object(), (800, 600)),
    )
    monkeypatch.setattr(
        "oscar.orchestrator.get_system_specs",
        lambda: {
            "os_version": "Windows 11",
            "manufacturer": "HP",
            "cpu_model": "Ryzen",
            "total_ram": "16.0 GB",
        },
    )
    monkeypatch.setattr(
        "oscar.orchestrator.get_active_window_info",
        lambda: {"title": "PowerShell", "process_name": "powershell.exe", "hwnd": 1},
    )
    monkeypatch.setattr("oscar.orchestrator.list_visible_windows", lambda limit=12: [])
    monkeypatch.setattr("oscar.orchestrator.capture_active_window_controls", lambda limit=20: [])
    monkeypatch.setattr("oscar.orchestrator.get_cursor_position", lambda: (10, 20))
    monkeypatch.setattr(
        "oscar.orchestrator.write_run_log",
        lambda **kwargs: tmp_path / "run.json",
    )
    monkeypatch.setattr(
        "oscar.trace.ExecutionTrace.log_step",
        lambda self, **kwargs: trace_calls.append(dict(kwargs)),
    )
    monkeypatch.setattr(
        "oscar.trace.ExecutionTrace.write_json",
        lambda self, logs_dir=None: tmp_path / "trace.json",
    )

    outcome = await Orchestrator(
        planner=planner,
        router=router,
        retry_manager=retry_manager,
        context_updater=updater,
    ).run("git status", ui_callback=ui_callback)

    assert outcome.log_path == tmp_path / "run.json"
    assert outcome.trace_path == tmp_path / "trace.json"
    event_types = [event["type"] for event in ui_events]
    assert "task_started" in event_types
    assert "planner_reasoning" in event_types
    assert "step_result" in event_types
    assert ui_events[-1]["type"] == "task_finalized"
    assert ui_events[-1]["status"] == "completed"
    assert len(planner.calls) >= 1
    assert planner.calls[-1][0].last_command_result is not None
    assert planner.calls[-1][0].last_command_result.command == "git status"
    assert planner.calls[-1][0].system_specs["manufacturer"] == "HP"
    assert screenshot_calls == []
    assert len(trace_calls) == 1
    assert trace_calls[0]["retry_index"] == 0
    assert outcome.status == "completed"


@pytest.mark.anyio
async def test_context_updater_captures_ui_state_for_failed_non_ui_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    updater = ContextUpdater()
    screenshot_calls: list[object] = []

    monkeypatch.setattr(
        "oscar.orchestrator.capture_screenshot",
        lambda _region=None: (screenshot_calls.append(object()) or object(), (800, 600)),
    )
    monkeypatch.setattr(
        "oscar.orchestrator.get_active_window_info",
        lambda: {"title": "Edge", "process_name": "msedge.exe", "hwnd": 2},
    )
    monkeypatch.setattr("oscar.orchestrator.list_visible_windows", lambda limit=12: [])
    monkeypatch.setattr(
        "oscar.orchestrator.capture_active_window_controls",
        lambda limit=20: [{"text": "Retry"}],
    )

    context = TaskContext(task="open page", current_working_directory="A:\\Andrew\\Code\\OSCAR_codex")
    result = ActionResult(
        success=False,
        route="browser",
        action="browser_click",
        failure_reason="selector_not_found",
    )

    updated = await updater.apply(context, {"action": "browser_click", "text": "Images"}, result)

    assert len(screenshot_calls) == 1
    assert updated.ui_controls == [{"text": "Retry"}]


@pytest.mark.anyio
async def test_context_updater_captures_ui_state_for_native_browser_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    updater = ContextUpdater()
    screenshot_calls: list[object] = []

    monkeypatch.setattr(
        "oscar.orchestrator.capture_screenshot",
        lambda _region=None: (screenshot_calls.append(object()) or object(), (1280, 720)),
    )
    monkeypatch.setattr(
        "oscar.orchestrator.get_active_window_info",
        lambda: {"title": "WhatsApp", "process_name": "chrome.exe", "hwnd": 2},
    )
    monkeypatch.setattr("oscar.orchestrator.list_visible_windows", lambda limit=12: [])
    monkeypatch.setattr(
        "oscar.orchestrator.capture_active_window_controls",
        lambda limit=20: [{"text": "Prasand College"}],
    )

    context = TaskContext(task="tell me the last whatsapp message", current_working_directory="A:\\Andrew\\Code\\OSCAR_codex")
    result = ActionResult(
        success=True,
        route="browser",
        action="browser_navigate",
        data={"native_browser": True},
    )

    updated = await updater.apply(context, {"action": "browser_navigate", "url": "https://web.whatsapp.com"}, result)

    assert len(screenshot_calls) == 1
    assert updated.ui_controls == [{"text": "Prasand College"}]


@pytest.mark.anyio
async def test_orchestrator_logs_only_final_retry_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    class FailingRouter:
        async def dispatch(self, action, context, memory, forced_route=None):
            return ActionResult(
                success=False,
                route="browser",
                action=str(action["action"]),
                failure_reason="selector_not_found",
            )

    class RetryingManager:
        async def resolve(self, action, result, context, memory):
            return (
                {"action": "browser_click", "text": "Images", "task_complete": False},
                ActionResult(
                    success=True,
                    route="browser",
                    action="browser_click",
                    attempts=2,
                    fallback_chain=["browser"],
                    context_updates={
                        "browser_url": "https://www.google.com/search?q=red+pandas",
                        "browser_title": "red pandas - Google Search",
                    },
                ),
            )

    planner = FakePlanner()
    trace_calls: list[dict] = []

    monkeypatch.setattr(
        "oscar.orchestrator.capture_screenshot",
        lambda _region=None: (object(), (800, 600)),
    )
    monkeypatch.setattr(
        "oscar.orchestrator.get_active_window_info",
        lambda: {"title": "Edge", "process_name": "msedge.exe", "hwnd": 2},
    )
    monkeypatch.setattr("oscar.orchestrator.list_visible_windows", lambda limit=12: [])
    monkeypatch.setattr("oscar.orchestrator.capture_active_window_controls", lambda limit=20: [])
    monkeypatch.setattr("oscar.orchestrator.get_cursor_position", lambda: (10, 20))
    monkeypatch.setattr(
        "oscar.orchestrator.write_run_log",
        lambda **kwargs: tmp_path / "run.json",
    )
    monkeypatch.setattr(
        "oscar.trace.ExecutionTrace.log_step",
        lambda self, **kwargs: trace_calls.append(dict(kwargs)),
    )
    monkeypatch.setattr(
        "oscar.trace.ExecutionTrace.write_json",
        lambda self, logs_dir=None: tmp_path / "trace.json",
    )

    await Orchestrator(
        planner=planner,
        router=FailingRouter(),
        retry_manager=RetryingManager(),
        context_updater=ContextUpdater(),
    ).run("git status")

    assert len(trace_calls) == 1
    assert trace_calls[0]["action"] == {
        "action": "browser_click",
        "text": "Images",
        "task_complete": False,
    }
    assert trace_calls[0]["retry_index"] == 1
    assert trace_calls[0]["fallback_used"] == "browser"


def test_run_task_prefers_windows_proactor_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    class ExistingPolicy:
        pass

    class FakeProactorPolicy:
        pass

    applied: list[object] = []

    monkeypatch.setattr(
        orchestrator_module.asyncio,
        "WindowsProactorEventLoopPolicy",
        FakeProactorPolicy,
        raising=False,
    )
    monkeypatch.setattr(
        orchestrator_module.asyncio,
        "get_event_loop_policy",
        lambda: ExistingPolicy(),
    )
    monkeypatch.setattr(
        orchestrator_module.asyncio,
        "set_event_loop_policy",
        lambda policy: applied.append(policy),
    )

    def fake_run(coro):
        coro.close()
        return "ok"

    monkeypatch.setattr(orchestrator_module.asyncio, "run", fake_run)

    assert orchestrator_module.run_task("git status") == "ok"
    assert len(applied) == 1
    assert isinstance(applied[0], FakeProactorPolicy)


@pytest.mark.anyio
async def test_orchestrator_executes_wait_until_as_control_action(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    class WaitPlanner:
        def __init__(self) -> None:
            self._actions = iter(
                [
                    {
                        "action": "wait_until",
                        "time_of_day": "11:45",
                        "reasoning": "Wait for the target time.",
                        "task_complete": False,
                    },
                    {"action": "done", "reasoning": "Finished.", "task_complete": True},
                ]
            )

        async def plan_next_action(self, context, memory):
            return next(self._actions)

    class UnexpectedRouter:
        async def dispatch(self, action, context, memory, forced_route=None):
            raise AssertionError("wait_until should bypass the router")

    class PassthroughRetryManager:
        async def resolve(self, action, result, context, memory):
            return action, result

    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr(
        "oscar.orchestrator.capture_screenshot",
        lambda _region=None: (object(), (800, 600)),
    )
    monkeypatch.setattr(
        "oscar.orchestrator.get_active_window_info",
        lambda: {"title": "Desktop", "process_name": "explorer.exe", "hwnd": 1},
    )
    monkeypatch.setattr("oscar.orchestrator.list_visible_windows", lambda limit=12: [])
    monkeypatch.setattr("oscar.orchestrator.capture_active_window_controls", lambda limit=20: [])
    monkeypatch.setattr("oscar.orchestrator.get_cursor_position", lambda: (10, 20))
    monkeypatch.setattr(
        "oscar.orchestrator.write_run_log",
        lambda **kwargs: tmp_path / "run.json",
    )
    monkeypatch.setattr(
        "oscar.trace.ExecutionTrace.write_json",
        lambda self, logs_dir=None: tmp_path / "trace.json",
    )
    monkeypatch.setattr("oscar.orchestrator.validate_action", lambda action, _screen=None: action)
    monkeypatch.setattr(
        "oscar.orchestrator.execute_action",
        lambda action: {"wait_until": action["time_of_day"], "delay": 2.5},
    )
    monkeypatch.setattr("oscar.orchestrator.asyncio.sleep", fake_sleep)

    outcome = await Orchestrator(
        planner=WaitPlanner(),
        router=UnexpectedRouter(),
        retry_manager=PassthroughRetryManager(),
        context_updater=ContextUpdater(),
    ).run("when time hits 11:45 open chrome")

    assert outcome.log_path == tmp_path / "run.json"
    assert outcome.trace_path == tmp_path / "trace.json"
    assert sleep_calls == [2.5]


@pytest.mark.anyio
async def test_orchestrator_blocks_recent_failed_fingerprint_before_execution(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    class RepeatingPlanner:
        def __init__(self) -> None:
            self._actions = iter(
                [
                    {
                        "action": "browser_click",
                        "text": "Images",
                        "reasoning": "Try the same click again.",
                        "task_complete": False,
                    },
                    {"action": "done", "reasoning": "Finished.", "task_complete": True},
                ]
            )

        async def plan_next_action(self, context, memory):
            return next(self._actions)

    class UnexpectedRouter:
        async def dispatch(self, action, context, memory, forced_route=None):
            raise AssertionError("preflight guard should stop this action before dispatch")

        def normalize_action(self, action):
            return dict(action)

        def choose_route(self, action, context, memory):
            return "browser"

    class PassthroughRetryManager:
        async def resolve(self, action, result, context, memory):
            raise AssertionError("preflight failures should not retry")

    monkeypatch.setattr(
        "oscar.orchestrator.capture_screenshot",
        lambda _region=None: (object(), (800, 600)),
    )
    monkeypatch.setattr(
        "oscar.orchestrator.get_active_window_info",
        lambda: {"title": "Edge", "process_name": "msedge.exe", "hwnd": 1},
    )
    monkeypatch.setattr("oscar.orchestrator.list_visible_windows", lambda limit=12: [])
    monkeypatch.setattr("oscar.orchestrator.capture_active_window_controls", lambda limit=20: [])
    monkeypatch.setattr("oscar.orchestrator.get_cursor_position", lambda: (10, 20))
    monkeypatch.setattr(
        "oscar.orchestrator.write_run_log",
        lambda **kwargs: tmp_path / "run.json",
    )
    monkeypatch.setattr(
        "oscar.trace.ExecutionTrace.write_json",
        lambda self, logs_dir=None: tmp_path / "trace.json",
    )

    orchestrator = Orchestrator(
        planner=RepeatingPlanner(),
        router=UnexpectedRouter(),
        retry_manager=PassthroughRetryManager(),
        context_updater=ContextUpdater(),
    )
    preloaded_memory = TaskMemory()
    preloaded_memory.record_step(
        {
            "action": "browser_click",
            "text": "Images",
            "reasoning": "First failed click.",
            "task_complete": False,
        },
        "browser",
        {"success": False},
        success=False,
        failure_reason="selector_not_found:Images",
    )
    monkeypatch.setattr("oscar.orchestrator.TaskMemory", lambda: preloaded_memory)

    outcome = await orchestrator.run("click Images")

    assert outcome.log_path == tmp_path / "run.json"


@pytest.mark.anyio
async def test_orchestrator_surfaces_final_message_for_direct_done(
    monkeypatch: pytest.MonkeyPatch, tmp_path, capsys
) -> None:
    class DonePlanner:
        async def plan_next_action(self, context, memory):
            return {
                "action": "done",
                "reasoning": "The current local time is 2026-03-27T00:26:38+05:30.",
                "task_complete": True,
            }

    monkeypatch.setattr(
        "oscar.orchestrator.capture_screenshot",
        lambda _region=None: (object(), (800, 600)),
    )
    monkeypatch.setattr(
        "oscar.orchestrator.get_active_window_info",
        lambda: {"title": "Desktop", "process_name": "explorer.exe", "hwnd": 1},
    )
    monkeypatch.setattr("oscar.orchestrator.list_visible_windows", lambda limit=12: [])
    monkeypatch.setattr("oscar.orchestrator.capture_active_window_controls", lambda limit=20: [])
    monkeypatch.setattr("oscar.orchestrator.get_cursor_position", lambda: (10, 20))
    monkeypatch.setattr(
        "oscar.orchestrator.write_run_log",
        lambda **kwargs: tmp_path / "run.json",
    )
    monkeypatch.setattr(
        "oscar.trace.ExecutionTrace.write_json",
        lambda self, logs_dir=None: tmp_path / "trace.json",
    )

    outcome = await Orchestrator(planner=DonePlanner()).run("tell me current time")

    output = capsys.readouterr().out
    assert outcome.final_message == "The current local time is 2026-03-27T00:26:38+05:30."
    assert outcome.status == "completed"
    assert "[STEP 1] ACTION" in output
    assert "[STEP 1] RESULT" in output


@pytest.mark.anyio
async def test_orchestrator_restores_oscar_focus_after_ui_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    focus_calls: list[float] = []

    class DonePlanner:
        async def plan_next_action(self, context, memory):
            return {
                "action": "done",
                "reasoning": "Finished.",
                "task_complete": True,
            }

    async def ui_callback(event: dict) -> None:
        return None

    monkeypatch.setattr(
        "oscar.orchestrator.capture_screenshot",
        lambda _region=None: (object(), (800, 600)),
    )
    monkeypatch.setattr(
        "oscar.orchestrator.get_active_window_info",
        lambda: {"title": "Desktop", "process_name": "explorer.exe", "hwnd": 1},
    )
    monkeypatch.setattr("oscar.orchestrator.list_visible_windows", lambda limit=12: [])
    monkeypatch.setattr("oscar.orchestrator.capture_active_window_controls", lambda limit=20: [])
    monkeypatch.setattr("oscar.orchestrator.get_cursor_position", lambda: (10, 20))
    monkeypatch.setattr(
        "oscar.orchestrator.write_run_log",
        lambda **kwargs: tmp_path / "run.json",
    )
    monkeypatch.setattr(
        "oscar.trace.ExecutionTrace.write_json",
        lambda self, logs_dir=None: tmp_path / "trace.json",
    )
    monkeypatch.setattr(
        "oscar.orchestrator.focus_oscar_app_window",
        lambda timeout=0.0: focus_calls.append(timeout) or True,
    )

    await Orchestrator(planner=DonePlanner()).run("finish", ui_callback=ui_callback)

    assert focus_calls == [orchestrator_module.config.WINDOW_FOCUS_TIMEOUT]
