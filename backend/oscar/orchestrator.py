"""Async orchestrator for routed OSCAR task execution."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

import anyio

from oscar import config
from oscar.diagnostics import sanitize_text
from oscar.brain.planner import BrainPlanner, GeminiBrain
from oscar.context import LastCommandResult, TaskContext
from oscar.core.persistent_memory import PersistentMemoryStore
from oscar.executor import execute_action, validate_action
from oscar.memory import TaskMemory, action_family_for, build_action_fingerprint
from oscar.routing import ActionRouter, RetryManager
from oscar.run_logger import write_run_log
from oscar.runtime import ActionResult
from oscar.screen import capture_screenshot
from oscar.system_profiler import get_system_specs
from oscar.trace import ExecutionTrace
from oscar.ui_automation import capture_active_window_controls
from oscar.utils.logging import configure_logging, get_logger, log_event
from oscar.utils.paths import render_known_path_strings
from oscar.window_control import (
    focus_oscar_app_window,
    get_active_window_info,
    get_cursor_position,
    list_visible_windows,
)


LOGGER = get_logger("orchestrator")

UIEventCallback = Callable[[dict[str, Any]], Awaitable[None]]


def _json_safe(value: Any) -> Any:
    """Round-trip through JSON so UI callbacks never receive unserializable data."""

    return json.loads(json.dumps(value, default=str))


@dataclass
class OrchestratorOutcome:
    """Final outcome and artifact paths for a task run."""

    log_path: Path
    trace_path: Path
    status: str
    final_message: str | None = None


class ContextUpdater:
    """Apply structured action results back onto the shared task context."""

    def __init__(self, *, system_specs: dict[str, Any] | None = None) -> None:
        self.system_specs = dict(system_specs) if system_specs is not None else None

    async def apply(
        self,
        context: TaskContext,
        action: dict[str, Any],
        result,
    ) -> TaskContext:
        updates = dict(result.context_updates or {})
        browser_url = updates.get("browser_url") or updates.get("url")
        browser_title = updates.get("browser_title") or updates.get("title")
        if browser_url is not None:
            context.browser_url = browser_url
        if browser_title is not None:
            context.browser_title = browser_title
        if updates.get("browser_tabs") is not None:
            context.browser_tabs = list(updates["browser_tabs"])
        if updates.get("current_working_directory"):
            context.current_working_directory = str(updates["current_working_directory"])
        if updates.get("ui_controls") is not None:
            context.ui_controls = list(updates["ui_controls"])
        if updates.get("ui_element_summary") is not None:
            context.ui_element_summary = str(updates["ui_element_summary"])
        if updates.get("last_command_result"):
            last = updates["last_command_result"]
            context.last_command_result = LastCommandResult(
                command=last.get("command"),
                cwd=last.get("cwd"),
                stdout=last.get("stdout"),
                stderr=last.get("stderr"),
                exit_code=last.get("exit_code"),
                success=last.get("success"),
            )
        return await self.refresh_environment(
            context,
            include_ui=(
                result.route == "ui"
                or not result.success
                or bool(result.data.get("native_browser"))
            ),
        )

    async def refresh_environment(
        self,
        context: TaskContext,
        *,
        include_ui: bool = False,
    ) -> TaskContext:
        active_window = await anyio.to_thread.run_sync(get_active_window_info)
        if self.system_specs is None:
            self.system_specs = dict(await anyio.to_thread.run_sync(get_system_specs))
        context.system_specs = dict(self.system_specs)
        context.active_window_title = active_window.get("title")  # type: ignore[assignment]
        context.active_process_name = active_window.get("process_name")  # type: ignore[assignment]
        context.active_window_hwnd = active_window.get("hwnd")  # type: ignore[assignment]
        context.current_local_time = datetime.now().astimezone().isoformat(
            timespec="seconds"
        )
        context.visible_windows = await anyio.to_thread.run_sync(
            lambda: list_visible_windows(limit=12)
        )
        if include_ui:
            # Screenshot capture is one of the most expensive context updates, so
            # only pay for it when UI planning or failure investigation needs it.
            screenshot, screen_size = await anyio.to_thread.run_sync(
                lambda: capture_screenshot(config.SCREENSHOT_REGION)
            )
            context.screenshot = screenshot
            context.screen_size = screen_size
            context.ui_controls = await anyio.to_thread.run_sync(
                lambda: capture_active_window_controls(limit=20)
            )
            context.ui_element_summary = "\n".join(
                f"#{control.get('element_id')} {control.get('control_type') or 'Control'} {str(control.get('text') or control.get('automation_id') or control.get('class_name') or '').strip()}".strip()
                for control in context.ui_controls
            )
        else:
            context.screenshot = None
            context.ui_controls = []
            context.ui_element_summary = None
        return context


class Orchestrator:
    """Plan, route, execute, retry, remember, and trace one OSCAR task."""

    def __init__(
        self,
        *,
        planner: BrainPlanner | None = None,
        router: ActionRouter | None = None,
        retry_manager: RetryManager | None = None,
        context_updater: ContextUpdater | None = None,
    ) -> None:
        self.planner = planner or GeminiBrain()
        self.router = router or ActionRouter()
        self.retry_manager = retry_manager or RetryManager(router=self.router)
        self.context_updater = context_updater or ContextUpdater()

    async def run(
        self,
        task: str,
        ui_callback: UIEventCallback | None = None,
    ) -> OrchestratorOutcome:
        if not task or not task.strip():
            raise ValueError("A non-empty task is required.")

        configure_logging(config.LOG_LEVEL)
        started_at = datetime.now(timezone.utc)
        memory = TaskMemory()
        persistent_memory = PersistentMemoryStore.load()
        trace = ExecutionTrace(task=task)
        history: list[dict[str, Any]] = []
        status = "failed"
        error_message: str | None = None
        final_message: str | None = None
        log_path: Path | None = None
        trace_path: Path | None = None
        finalization_failures: list[str] = []
        await self._emit_ui_event(
            ui_callback,
            "task_started",
            task=task,
            status="running",
            max_steps=config.MAX_STEPS,
        )
        context = await self.context_updater.refresh_environment(
            TaskContext(task=task, current_working_directory=str(Path.cwd())),
            include_ui=False,
        )
        context.persistent_memory = persistent_memory.snapshot()
        await self._emit_ui_event(
            ui_callback,
            "context_ready",
            task=task,
            status="running",
            active_window_title=context.active_window_title,
            active_process_name=context.active_process_name,
            current_working_directory=context.current_working_directory,
            current_local_time=context.current_local_time,
            visible_windows=context.visible_windows,
        )

        try:
            for step_index in range(config.MAX_STEPS):
                step_number = step_index + 1
                planned_action = await self.planner.plan_next_action(context, memory)
                await self._emit_ui_event(
                    ui_callback,
                    "planner_reasoning",
                    step=step_number,
                    status="planned",
                    action=planned_action.get("action"),
                    reasoning=planned_action.get("reasoning"),
                    payload=planned_action,
                )
                action = (
                    self.router.prepare_action(planned_action, context)
                    if hasattr(self.router, "prepare_action")
                    and planned_action.get("action") not in {"done", "wait_until"}
                    else dict(planned_action)
                )
                await self._emit_ui_event(
                    ui_callback,
                    "step_started",
                    step=step_number,
                    status="running",
                    action=action.get("action"),
                    reasoning=action.get("reasoning"),
                    payload=action,
                )
                print(f"[STEP {step_number}] ACTION → {action}")
                if action.get("action") == "done":
                    print(
                        f"[STEP {step_number}] RESULT → success=True, route=system"
                    )
                    history.append(dict(action))
                    final_message = str(action.get("reasoning") or "").strip() or None
                    status = "completed"
                    await self._emit_ui_event(
                        ui_callback,
                        "task_completed",
                        step=step_number,
                        status=status,
                        action="done",
                        reasoning=final_message,
                        success=True,
                        final_message=final_message,
                    )
                    break

                preflight_result = self._preflight_action(action, context, memory)
                if preflight_result is not None:
                    result = preflight_result
                    resolved_action = dict(action)
                elif action.get("action") == "wait_until":
                    result = await self._execute_control_action(action, context)
                    resolved_action = dict(action)
                else:
                    result = await self.router.dispatch(action, context, memory)
                    memory.record_step(
                        action,
                        result.route,
                        result,
                        success=result.success,
                        failure_reason=result.failure_reason,
                        retry_count=0,
                    )
                    resolved_action, result = await self.retry_manager.resolve(
                        action,
                        result,
                        context,
                        memory,
                    )

                await self._emit_ui_event(
                    ui_callback,
                    "step_result",
                    step=step_number,
                    status="succeeded" if result.success else "failed",
                    action=resolved_action.get("action"),
                    reasoning=resolved_action.get("reasoning"),
                    route=result.route,
                    success=result.success,
                    confidence=result.confidence,
                    failure_reason=result.failure_reason,
                    retryable=result.retryable,
                    attempts=result.attempts,
                    fallback_chain=result.fallback_chain,
                    strategy=result.strategy,
                    result=result.to_dict(),
                    payload=resolved_action,
                )

                if preflight_result is not None or action.get("action") == "wait_until":
                    memory.record_step(
                        resolved_action,
                        result.route,
                        result,
                        success=result.success,
                        failure_reason=result.failure_reason,
                        retry_count=0,
                    )

                step_entry = dict(resolved_action)
                step_entry.update(result.to_dict())
                history.append(step_entry)
                persistent_memory.record(resolved_action, result)
                context.persistent_memory = persistent_memory.snapshot()
                context = await self.context_updater.apply(context, resolved_action, result)
                # Persist only the final post-retry outcome for each planner step so
                # traces are easier to read and map cleanly to high-level intent.
                trace.log_step(
                    action=resolved_action,
                    route=result.route,
                    success=result.success,
                    duration_ms=result.duration_ms,
                    retry_index=max(result.attempts - 1, 0),
                    failure_reason=result.failure_reason,
                    fallback_used=(
                        " -> ".join(result.fallback_chain)
                        if result.fallback_chain
                        else None
                    ),
                    context_snapshot=context.to_dict(),
                )
                log_event(
                    LOGGER,
                    "orchestrator_step",
                    step=step_index + 1,
                    action=resolved_action.get("action"),
                    route=result.route,
                    success=result.success,
                    failure_reason=result.failure_reason,
                )
                print(
                    f"[STEP {step_number}] RESULT → success={result.success}, route={result.route}"
                )
                if result.strategy:
                    print(f"[RETRY] Strategy → {result.strategy}")
                if result.failure_reason:
                    print(f"[ERROR] {result.failure_reason}")

                delay = float(result.data.get("delay") or 0.0)
                if delay > 0:
                    print(f"[WAIT] Sleeping for {delay:.2f} seconds...")
                    await self._emit_ui_event(
                        ui_callback,
                        "step_waiting",
                        step=step_number,
                        status="waiting",
                        action=resolved_action.get("action"),
                        seconds=delay,
                        reasoning=resolved_action.get("reasoning"),
                    )
                    await asyncio.sleep(delay)

                if resolved_action.get("task_complete") or (
                    result.success and resolved_action.get("action") == "done"
                ):
                    if final_message is None:
                        final_message = (
                            str(resolved_action.get("reasoning") or "").strip() or None
                        )
                    status = "completed"
                    await self._emit_ui_event(
                        ui_callback,
                        "task_completed",
                        step=step_number,
                        status=status,
                        action=resolved_action.get("action"),
                        reasoning=final_message,
                        success=True,
                        final_message=final_message,
                    )
                    break
                if (
                    result.data.get("stop_execution")
                    or (
                        not result.success
                        and memory.consecutive_failures_for(
                            action_family_for(resolved_action)
                        )
                        >= 2
                    )
                ):
                    status = "failed"
                    await self._emit_ui_event(
                        ui_callback,
                        "task_stopped",
                        step=step_number,
                        status=status,
                        action=resolved_action.get("action"),
                        reasoning=resolved_action.get("reasoning"),
                        success=False,
                        failure_reason=result.failure_reason,
                    )
                    break
            else:
                status = "max_steps_reached"
                await self._emit_ui_event(
                    ui_callback,
                    "task_max_steps_reached",
                    status=status,
                    max_steps=config.MAX_STEPS,
                )
        except asyncio.CancelledError:
            status = "failed"
            error_message = "Execution cancelled"
            final_message = "Execution cancelled."
            await self._emit_ui_event(
                ui_callback,
                "task_cancelled",
                status=status,
                error=error_message,
                final_message=final_message,
            )
        except Exception as exc:
            status = "failed"
            error_message = sanitize_text(str(exc))
            await self._emit_ui_event(
                ui_callback,
                "task_failed",
                status=status,
                error=error_message,
                error_type=exc.__class__.__name__,
            )
            raise
        finally:
            # Each cleanup step is isolated: a memory or trace write failure must
            # not prevent the remaining diagnostics and UI finalization from running.
            try:
                persistent_memory.save()
            except Exception as exc:
                finalization_failures.append("persistent_memory")
                LOGGER.warning(
                    "Task finalization step persistent_memory failed: %s",
                    sanitize_text(str(exc)),
                )

            try:
                trace_path = trace.write_json()
            except Exception as exc:
                finalization_failures.append("trace")
                LOGGER.warning(
                    "Task finalization step trace failed: %s", sanitize_text(str(exc))
                )

            try:
                log_path = write_run_log(
                    task=task,
                    history=history,
                    started_at=started_at,
                    finished_at=datetime.now(timezone.utc),
                    status=status,
                    error=error_message,
                    model_name=config.GEMINI_MODEL,
                    max_steps=config.MAX_STEPS,
                    action_delay=config.ACTION_DELAY,
                    trace_path=str(trace_path) if trace_path is not None else None,
                    memory=memory.get_recent_steps(config.MAX_STEPS),
                    known_paths=render_known_path_strings(),
                    cursor_position=get_cursor_position(),  # sync is fine here — outside event loop
                )
            except Exception as exc:
                finalization_failures.append("run_log")
                LOGGER.warning(
                    "Task finalization step run_log failed: %s", sanitize_text(str(exc))
                )

            await self._emit_ui_event(
                ui_callback,
                "task_finalized",
                task=task,
                status=status,
                error=(error_message or (
                    "One or more diagnostic artifacts could not be saved."
                    if finalization_failures else None
                )),
                final_message=final_message,
                log_path=str(log_path) if log_path is not None else None,
                trace_path=str(trace_path) if trace_path is not None else None,
                finalization_failures=list(finalization_failures),
            )
            await self._restore_ui_host_focus(ui_callback)

        if finalization_failures:
            # Reached only when the task's primary execution did not raise; an
            # exception already propagating from the main block is never masked.
            raise RuntimeError(
                "OSCAR task finalization failed for: " + ", ".join(finalization_failures)
            )
        assert log_path is not None
        assert trace_path is not None
        return OrchestratorOutcome(
            log_path=log_path,
            trace_path=trace_path,
            status=status,
            final_message=final_message,
        )

    async def _emit_ui_event(
        self,
        ui_callback: UIEventCallback | None,
        event_type: str,
        **fields: Any,
    ) -> None:
        if ui_callback is None:
            return
        payload = {
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **fields,
        }
        try:
            await ui_callback(_json_safe(payload))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOGGER.warning("UI callback failed for event %s: %s", event_type, exc)

    async def _restore_ui_host_focus(
        self,
        ui_callback: UIEventCallback | None,
    ) -> None:
        if ui_callback is None:
            return
        try:
            await anyio.to_thread.run_sync(
                lambda: focus_oscar_app_window(timeout=config.WINDOW_FOCUS_TIMEOUT)
            )
        except Exception as exc:
            LOGGER.warning("Failed to restore OSCAR app focus: %s", exc)

    async def _execute_control_action(
        self,
        action: dict[str, Any],
        context: TaskContext,
    ) -> ActionResult:
        normalized = validate_action(action, context.screen_size)
        try:
            payload = await anyio.to_thread.run_sync(execute_action, normalized) or {}
        except asyncio.CancelledError:
            return ActionResult(
                success=False,
                route="system",
                action=str(action.get("action") or "wait_until"),
                confidence=0.1,
                failure_reason="Execution cancelled",
                retryable=True,
            )
        return ActionResult(
            success=True,
            route="system",
            action=str(action.get("action") or "wait_until"),
            confidence=1.0,
            data=payload,
            retryable=False,
        )

    def _preflight_action(
        self,
        action: dict[str, Any],
        context: TaskContext,
        memory: TaskMemory,
    ) -> ActionResult | None:
        normalized_action = (
            dict(action)
            if action.get("action") == "wait_until"
            else (
                self.router.prepare_action(action, context)
                if hasattr(self.router, "prepare_action")
                else (
                    self.router.normalize_action(action)
                    if hasattr(self.router, "normalize_action")
                    else dict(action)
                )
            )
        )
        route = (
            "system"
            if normalized_action.get("action") == "wait_until"
            else (
                self.router.choose_route(normalized_action, context, memory)
                if hasattr(self.router, "choose_route")
                else str(getattr(self.router, "route", "ui"))
            )
        )
        fingerprint = build_action_fingerprint(normalized_action, route)
        if memory.was_recent_failure(fingerprint):
            return ActionResult(
                success=False,
                route=route,
                action=str(normalized_action.get("action") or action.get("action") or "unknown"),
                confidence=0.0,
                failure_reason="Blocked repeated failed action by fingerprint.",
                retryable=False,
                data={"fingerprint": fingerprint},
                strategy="memory_guard",
            )
        action_family = action_family_for(normalized_action)
        if memory.consecutive_failures_for(action_family) >= 2:
            return ActionResult(
                success=False,
                route=route,
                action=str(normalized_action.get("action") or action.get("action") or "unknown"),
                confidence=0.0,
                failure_reason=f"Stopped after repeated {action_family} failures.",
                retryable=False,
                data={"stop_execution": True, "fingerprint": fingerprint},
                strategy="hard_stop",
            )
        return None


def run_task(task: str) -> OrchestratorOutcome:
    """Run the async orchestrator from sync entrypoints."""

    config.enable_windows_dpi_awareness()
    policy_factory = getattr(asyncio, "WindowsProactorEventLoopPolicy", None)
    if policy_factory is not None and not isinstance(
        asyncio.get_event_loop_policy(),
        policy_factory,
    ):
        # Playwright and the terminal agent both spawn child processes. On Windows
        # that requires a proactor-capable event loop policy.
        asyncio.set_event_loop_policy(policy_factory())
    return asyncio.run(Orchestrator().run(task))
