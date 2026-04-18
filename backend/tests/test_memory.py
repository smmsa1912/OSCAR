from __future__ import annotations

from oscar.memory import TaskMemory, build_action_fingerprint
from oscar.runtime import ActionResult


def test_task_memory_tracks_recent_steps_failures_and_successes() -> None:
    memory = TaskMemory()
    failed = ActionResult(
        success=False,
        route="browser",
        action="browser_click",
        failure_reason="selector_not_found",
    )
    succeeded = ActionResult(
        success=True,
        route="terminal",
        action="terminal_command",
        data={"exit_code": 0},
    )

    memory.record_step(
        {"action": "browser_click", "text": "Images"},
        "browser",
        failed,
        success=False,
        failure_reason=failed.failure_reason,
    )
    memory.record_step(
        {"action": "terminal_command", "command": "git status"},
        "terminal",
        succeeded,
        success=True,
    )

    assert len(memory.get_recent_steps()) == 2
    assert len(memory.get_failures()) == 1
    assert len(memory.get_successes()) == 1
    assert memory.last_success_for("terminal") is not None


def test_task_memory_detects_recent_failure_and_consecutive_failures() -> None:
    memory = TaskMemory()
    for _index in range(2):
        memory.record_step(
            {"action": "browser_click", "text": "Images"},
            "browser",
            {"success": False},
            success=False,
            failure_reason="selector_not_found",
        )

    last = memory.steps[-1]
    assert memory.was_recent_failure(last.fingerprint or "")
    assert memory.consecutive_failures_for("browser") == 2
    assert memory.consecutive_failures_for_fingerprint(last.fingerprint or "") == 2


def test_action_fingerprint_ignores_reasoning_text() -> None:
    first = build_action_fingerprint(
        {
            "action": "browser_click",
            "text": "Images",
            "reasoning": "Click the Images tab using the most reliable path.",
        },
        "browser",
    )
    second = build_action_fingerprint(
        {
            "action": "browser_click",
            "text": "Images",
            "reasoning": "Try the Images tab again with a different explanation.",
        },
        "browser",
    )

    assert first == "browser|browser_click|images"
    assert second == first


def test_action_fingerprint_uses_ui_text_when_target_text_is_missing() -> None:
    fingerprint = build_action_fingerprint(
        {
            "action": "ui_click",
            "text": "performance",
            "reasoning": "Click the performance section.",
        },
        "ui",
    )

    assert fingerprint == "ui|ui_click|performance"


def test_action_fingerprint_buckets_nearby_ui_coordinates() -> None:
    first = build_action_fingerprint(
        {
            "action": "ui_click",
            "x": 312,
            "y": 166,
            "reasoning": "Try the visible button.",
            "timestamp": "2026-04-06T12:00:00+05:30",
        },
        "ui",
    )
    second = build_action_fingerprint(
        {
            "action": "ui_click",
            "x": 313,
            "y": 166,
            "reasoning": "Try the visible button again.",
            "timestamp": "2026-04-06T12:00:01+05:30",
        },
        "ui",
    )

    assert first == "ui|ui_click|x:320|y:160"
    assert second == first


def test_task_memory_counts_scroll_failures_as_ui_family() -> None:
    memory = TaskMemory()
    for x in (312, 313):
        memory.record_step(
            {
                "action": "scroll",
                "x": x,
                "y": 540,
                "direction": "down",
                "amount": 1,
            },
            "ui",
            {"success": False},
            success=False,
            failure_reason="scroll_failed",
        )

    assert memory.consecutive_failures_for("ui") == 2
