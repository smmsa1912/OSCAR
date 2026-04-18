"""Runtime task context shared across planning, routing, and execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class LastCommandResult:
    """Structured details about the most recent terminal command."""

    command: str | None = None
    cwd: str | None = None
    stdout: str | None = None
    stderr: str | None = None
    exit_code: int | None = None
    success: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "cwd": self.cwd,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "success": self.success,
        }


@dataclass
class TaskContext:
    """Current environment snapshot available to the planner and router."""

    task: str
    current_working_directory: str
    system_specs: dict[str, Any] = field(default_factory=dict)
    active_window_title: str | None = None
    active_process_name: str | None = None
    active_window_hwnd: int | None = None
    browser_url: str | None = None
    browser_title: str | None = None
    browser_tabs: list[dict[str, Any]] = field(default_factory=list)
    last_command_result: LastCommandResult | None = None
    visible_windows: list[dict[str, Any]] = field(default_factory=list)
    ui_controls: list[dict[str, Any]] = field(default_factory=list)
    ui_element_summary: str | None = None
    current_local_time: str | None = None
    screen_size: tuple[int, int] | None = None
    persistent_memory: dict[str, Any] = field(default_factory=dict)
    screenshot: Any | None = field(default=None, repr=False, compare=False)

    def snapshot(self) -> "TaskContext":
        """Return a deep copy for retry isolation — prevents stale partial state."""
        import copy
        return copy.deepcopy(self)

    def refresh_timestamp(self) -> None:
        self.current_local_time = datetime.now().astimezone().isoformat(timespec="seconds")

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "current_working_directory": self.current_working_directory,
            "system_specs": self.system_specs,
            "active_window_title": self.active_window_title,
            "active_process_name": self.active_process_name,
            "active_window_hwnd": self.active_window_hwnd,
            "browser_url": self.browser_url,
            "browser_title": self.browser_title,
            "browser_tabs": self.browser_tabs,
            "last_command_result": (
                self.last_command_result.to_dict()
                if self.last_command_result is not None
                else None
            ),
            "visible_windows": self.visible_windows,
            "ui_controls": self.ui_controls,
            "ui_element_summary": self.ui_element_summary,
            "current_local_time": self.current_local_time,
            "screen_size": self.screen_size,
            "persistent_memory": self.persistent_memory,
        }
