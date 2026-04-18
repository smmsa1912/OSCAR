from __future__ import annotations

import pytest

from oscar.context import TaskContext
from oscar.memory import TaskMemory, build_action_fingerprint
from oscar.routing import ActionRouter, RetryManager, RetryStrategy
from oscar.runtime import ActionResult


class FakeAgent:
    def __init__(self, route: str) -> None:
        self.route = route
        self.calls: list[dict] = []

    async def run(self, action, *_args):
        self.calls.append(dict(action))
        return ActionResult(success=True, route=self.route, action=str(action["action"]))


@pytest.mark.anyio
async def test_action_router_prefers_shortcut_for_known_os_open_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router = ActionRouter(
        browser_agent=FakeAgent("browser"),
        terminal_agent=FakeAgent("terminal"),
        shortcut_handler=FakeAgent("shortcut"),
        ui_agent=FakeAgent("ui"),
    )
    result = await router.dispatch(
        {"action": "open_app", "app_name": "settings", "reasoning": "Open Settings."},
        TaskContext(task="open settings", current_working_directory="A:\\Andrew\\Code\\OSCAR_codex"),
        TaskMemory(),
    )

    assert result.route == "shortcut"


def test_action_router_respects_explicit_route_override() -> None:
    router = ActionRouter(
        browser_agent=FakeAgent("browser"),
        terminal_agent=FakeAgent("terminal"),
        shortcut_handler=FakeAgent("shortcut"),
        ui_agent=FakeAgent("ui"),
    )
    route = router.choose_route(
        {"action": "browser_navigate", "url": "https://example.com"},
        TaskContext(
            task="use browser to do the task",
            current_working_directory="A:\\Andrew\\Code\\OSCAR_codex",
        ),
        TaskMemory(),
    )

    assert route == "browser"


def test_action_router_applies_recent_failure_penalty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router = ActionRouter(
        browser_agent=FakeAgent("browser"),
        terminal_agent=FakeAgent("terminal"),
        shortcut_handler=FakeAgent("shortcut"),
        ui_agent=FakeAgent("ui"),
    )
    memory = TaskMemory()
    memory.record_step(
        {"action": "open_app", "app_name": "settings"},
        "shortcut",
        {"success": False},
        success=False,
        failure_reason="failed",
    )
    monkeypatch.setattr("oscar.routing.config.ROUTE_FAILURE_PENALTY", 100)

    route = router.choose_route(
        {"action": "open_app", "app_name": "settings"},
        TaskContext(task="open settings", current_working_directory="A:\\Andrew\\Code\\OSCAR_codex"),
        memory,
    )

    assert route == "ui"


def test_action_router_normalizes_uia_click_text_into_target_text() -> None:
    router = ActionRouter(
        browser_agent=FakeAgent("browser"),
        terminal_agent=FakeAgent("terminal"),
        shortcut_handler=FakeAgent("shortcut"),
        ui_agent=FakeAgent("ui"),
    )

    normalized = router.normalize_action(
        {
            "action": "uia_click",
            "text": "PERFORMANCE",
            "control_type": "Text",
            "reasoning": "Click the PERFORMANCE control.",
            "task_complete": False,
        }
    )

    assert normalized == {
        "action": "ui_click",
        "button": "left",
        "target_text": "PERFORMANCE",
        "control_type": "Text",
        "reasoning": "Click the PERFORMANCE control.",
        "task_complete": False,
    }


def test_action_router_aligns_ui_click_to_visible_control() -> None:
    router = ActionRouter(
        browser_agent=FakeAgent("browser"),
        terminal_agent=FakeAgent("terminal"),
        shortcut_handler=FakeAgent("shortcut"),
        ui_agent=FakeAgent("ui"),
    )

    prepared = router.prepare_action(
        {
            "action": "ui_click",
            "x": 170,
            "y": 142,
            "reasoning": "Click the PERFORMANCE section in the left navigation pane.",
            "task_complete": False,
        },
        TaskContext(
            task="open omen gaming hub and tell me the performance mode",
            current_working_directory="A:\\Andrew\\Code\\OSCAR_codex",
            ui_controls=[
                {
                    "text": "PERFORMANCE",
                    "control_type": "Text",
                    "automation_id": "",
                    "left": 40,
                    "top": 90,
                    "right": 240,
                    "bottom": 120,
                    "actionable": True,
                }
            ],
        ),
    )

    assert prepared["target_text"] == "PERFORMANCE"
    assert prepared["control_type"] == "Text"
    assert prepared["x"] == 140
    assert prepared["y"] == 105


def test_action_router_preserves_grid_cell_and_screen_size() -> None:
    router = ActionRouter(
        browser_agent=FakeAgent("browser"),
        terminal_agent=FakeAgent("terminal"),
        shortcut_handler=FakeAgent("shortcut"),
        ui_agent=FakeAgent("ui"),
    )

    prepared = router.prepare_action(
        {
            "action": "uia_click",
            "grid_cell": "C2",
            "element_id": 1,
            "target_text": "Minimize",
            "reasoning": "Use the grid fallback for the search input.",
            "task_complete": False,
        },
        TaskContext(
            task="search settings",
            current_working_directory="A:\\Andrew\\Code\\OSCAR_codex",
            screen_size=(1000, 1000),
            ui_controls=[
                {
                    "element_id": 1,
                    "text": "Minimize",
                    "control_type": "Button",
                    "left": 0,
                    "top": 0,
                    "right": 40,
                    "bottom": 30,
                }
            ],
        ),
    )

    assert prepared["grid_cell"] == "C2"
    assert prepared["screen_size"] == (1000, 1000)
    assert prepared["element_id"] == 1


def test_action_router_hydrates_scroll_coordinates_from_screen_size() -> None:
    router = ActionRouter(
        browser_agent=FakeAgent("browser"),
        terminal_agent=FakeAgent("terminal"),
        shortcut_handler=FakeAgent("shortcut"),
        ui_agent=FakeAgent("ui"),
    )

    prepared = router.prepare_action(
        {
            "action": "scroll",
            "direction": "down",
            "amount": 1,
            "reasoning": "Scroll the current page.",
            "task_complete": False,
        },
        TaskContext(
            task="scroll down",
            current_working_directory="A:\\Andrew\\Code\\OSCAR_codex",
            screen_size=(1920, 1080),
        ),
    )

    assert prepared["x"] == 960
    assert prepared["y"] == 540


def test_retry_strategy_escalates_browser_selector_failures() -> None:
    strategy = RetryStrategy()
    decision = strategy.next_attempt(
        {"action": "browser_click", "text": "Images", "selector_strategy": "role"},
        ActionResult(
            success=False,
            route="browser",
            action="browser_click",
            failure_reason="selector_not_found:Images",
        ),
        TaskContext(task="click images", current_working_directory="A:\\Andrew\\Code\\OSCAR_codex"),
        TaskMemory(),
        0,
    )

    assert decision.action is not None
    assert decision.action["selector_strategy"] == "label"


def test_action_router_blocks_browser_after_repeated_failures() -> None:
    router = ActionRouter(
        browser_agent=FakeAgent("browser"),
        terminal_agent=FakeAgent("terminal"),
        shortcut_handler=FakeAgent("shortcut"),
        ui_agent=FakeAgent("ui"),
    )
    memory = TaskMemory()
    for _ in range(2):
        memory.record_step(
            {"action": "browser_click", "text": "Images"},
            "browser",
            {"success": False},
            success=False,
            failure_reason="selector_not_found",
        )

    route = router.choose_route(
        {"action": "browser_click", "text": "Images"},
        TaskContext(task="click Images", current_working_directory="A:\\Andrew\\Code\\OSCAR_codex"),
        memory,
    )

    assert route == "ui"


def test_retry_strategy_self_heals_missing_playwright_once_per_session() -> None:
    strategy = RetryStrategy()
    browser_action = {"action": "browser_search", "query": "red pandas"}
    failure = ActionResult(
        success=False,
        route="browser",
        action="browser_search",
        failure_reason="Executable doesn't exist. Please run playwright install",
    )

    first = strategy.next_attempt(
        browser_action,
        failure,
        TaskContext(task="search", current_working_directory="A:\\Andrew\\Code\\OSCAR_codex"),
        TaskMemory(),
        0,
    )
    second = strategy.next_attempt(
        browser_action,
        failure,
        TaskContext(task="search", current_working_directory="A:\\Andrew\\Code\\OSCAR_codex"),
        TaskMemory(),
        0,
    )

    assert first.action == {
        "action": "terminal_command",
        "command": "playwright install",
        "reasoning": "Install the missing Playwright browser binaries before retrying the browser action.",
        "task_complete": False,
    }
    assert first.forced_route == "terminal"
    assert first.resume_action == browser_action
    assert second.stop is True


def test_retry_strategy_stops_on_non_retryable_browser_blockers() -> None:
    strategy = RetryStrategy()
    decision = strategy.next_attempt(
        {"action": "browser_search", "query": "pomeranian dog"},
        ActionResult(
            success=False,
            route="browser",
            action="browser_search",
            failure_reason="Blocked by Google CAPTCHA",
            retryable=False,
            data={"blocked": True},
        ),
        TaskContext(task="search", current_working_directory="A:\\Andrew\\Code\\OSCAR_codex"),
        TaskMemory(),
        0,
    )

    assert decision.stop is True


def test_retry_strategy_simplifies_query_once_after_google_captcha() -> None:
    strategy = RetryStrategy()
    decision = strategy.next_attempt(
        {"action": "browser_search", "query": "cute pomeranian dog"},
        ActionResult(
            success=False,
            route="browser",
            action="browser_search",
            failure_reason="Blocked by Google CAPTCHA",
            retryable=False,
            data={"blocked": True},
        ),
        TaskContext(task="search", current_working_directory="A:\\Andrew\\Code\\OSCAR_codex"),
        TaskMemory(),
        0,
    )

    assert decision.action == {
        "action": "browser_search",
        "query": "pomeranian dog",
        "query_simplified": True,
    }
    assert decision.forced_route == "browser"


@pytest.mark.anyio
async def test_retry_manager_installs_playwright_then_resumes_browser_action() -> None:
    class FakeRouterWithRepair:
        def __init__(self) -> None:
            self.calls: list[tuple[dict, str | None]] = []

        async def dispatch(self, action, context, memory, forced_route=None):
            self.calls.append((dict(action), forced_route))
            if action["action"] == "terminal_command":
                return ActionResult(
                    success=True,
                    route="terminal",
                    action="terminal_command",
                    data={"stdout": "installed"},
                )
            return ActionResult(
                success=True,
                route="browser",
                action=str(action["action"]),
                data={"url": "https://www.google.com/search?q=red+pandas"},
            )

    router = FakeRouterWithRepair()
    manager = RetryManager(router=router, strategy=RetryStrategy(), max_attempts=4)
    memory = TaskMemory()
    action = {"action": "browser_search", "query": "red pandas"}
    initial_result = ActionResult(
        success=False,
        route="browser",
        action="browser_search",
        failure_reason="Executable doesn't exist. Please run playwright install",
    )

    resolved_action, result = await manager.resolve(
        action,
        initial_result,
        TaskContext(task="search", current_working_directory="A:\\Andrew\\Code\\OSCAR_codex"),
        memory,
    )

    assert resolved_action == action
    assert result.success is True
    assert result.attempts == 3
    assert result.fallback_chain == ["terminal"]
    assert router.calls[0] == (
        {
            "action": "terminal_command",
            "command": "playwright install",
            "reasoning": "Install the missing Playwright browser binaries before retrying the browser action.",
            "task_complete": False,
        },
        "terminal",
    )
    assert router.calls[1] == (action, "browser")
    assert memory.has_failed_fingerprint(
        build_action_fingerprint(
            {
                "action": "terminal_command",
                "command": "playwright install",
            },
            "terminal",
        )
    ) is False


@pytest.mark.anyio
async def test_retry_manager_stops_after_two_failures_for_same_action_type() -> None:
    class AlwaysFailRouter:
        def __init__(self) -> None:
            self.calls: list[tuple[dict, str | None]] = []

        async def dispatch(self, action, context, memory, forced_route=None):
            self.calls.append((dict(action), forced_route))
            return ActionResult(
                success=False,
                route=str(forced_route or "browser"),
                action=str(action["action"]),
                failure_reason="selector_not_found:Images",
            )

        def choose_route(self, action, context, memory):
            return "browser"

    router = AlwaysFailRouter()
    manager = RetryManager(router=router, strategy=RetryStrategy(), max_attempts=4)
    memory = TaskMemory()
    action = {"action": "browser_click", "text": "Images", "selector_strategy": "role"}
    initial_result = ActionResult(
        success=False,
        route="browser",
        action="browser_click",
        failure_reason="selector_not_found:Images",
    )
    memory.record_step(
        action,
        "browser",
        initial_result,
        success=False,
        failure_reason=initial_result.failure_reason,
    )

    resolved_action, result = await manager.resolve(
        action,
        initial_result,
        TaskContext(task="click images", current_working_directory="A:\\Andrew\\Code\\OSCAR_codex"),
        memory,
    )

    assert resolved_action["action"] == "browser_click"
    assert result.success is False
    assert result.attempts == 2
    assert len(router.calls) == 1
