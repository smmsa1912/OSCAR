"""Route scoring, dispatch, and intelligent retry logic."""

from __future__ import annotations

import anyio
import re
from copy import deepcopy
from time import perf_counter
from typing import Any

from oscar import config
from oscar.agents.browser_agent import BrowserAgent
from oscar.agents.shortcut_handler import ShortcutHandler
from oscar.agents.terminal_agent import TerminalAgent
from oscar.agents.ui_agent import UIAgent
from oscar.browser.query_utils import simplify_search_query
from oscar.context import TaskContext
from oscar.memory import TaskMemory, action_family_for, build_action_fingerprint
from oscar.runtime import ActionResult, RetryDecision, RouteCandidate
from oscar.ui_automation import uia_get_visible_elements
from oscar.window_control import get_active_window_info


ROUTE_WEIGHTS = {
    "terminal": 100,
    "shortcut": 80,
    "browser": 60,
    "ui": 20,
}


class ActionRouter:
    """Choose the best route for an action and execute it."""

    def __init__(
        self,
        *,
        browser_agent: BrowserAgent | None = None,
        terminal_agent: TerminalAgent | None = None,
        shortcut_handler: ShortcutHandler | None = None,
        ui_agent: UIAgent | None = None,
    ) -> None:
        self.browser_agent = browser_agent or BrowserAgent()
        self.terminal_agent = terminal_agent or TerminalAgent()
        self.shortcut_handler = shortcut_handler or ShortcutHandler()
        self.ui_agent = ui_agent or UIAgent()

    async def dispatch(
        self,
        action: dict[str, Any],
        context: TaskContext,
        memory: TaskMemory,
        *,
        forced_route: str | None = None,
    ) -> ActionResult:
        prepared_action = self.prepare_action(action, context)
        route = forced_route or self.choose_route(prepared_action, context, memory)
        started = perf_counter()
        result = await self._execute(prepared_action, context, route)
        result.duration_ms = int((perf_counter() - started) * 1000)
        return result

    def prepare_action(
        self,
        action: dict[str, Any],
        context: TaskContext,
    ) -> dict[str, Any]:
        normalized_action = self.normalize_action(action)
        if normalized_action.get("grid_cell") and context.screen_size is not None:
            normalized_action = dict(normalized_action)
            normalized_action.setdefault("screen_size", context.screen_size)
        normalized_action = self._hydrate_scroll_coordinates(normalized_action, context)
        return self._align_action_to_ui_controls(normalized_action, context.ui_controls)

    def choose_route(
        self,
        action: dict[str, Any],
        context: TaskContext,
        memory: TaskMemory,
    ) -> str:
        candidates = self.build_candidates(action)
        if not candidates:
            return "ui"

        override = self._route_override(action, context)
        if override is not None and any(candidate.route == override for candidate in candidates):
            return override

        scored: list[RouteCandidate] = []
        action_name = str(action.get("action") or "")
        action_family = action_family_for(action)
        for candidate in candidates:
            if candidate.route == action_family and (
                memory.consecutive_failures_for(action_name) >= 2
                or memory.consecutive_failures_for(action_family) >= 2
            ):
                # Re-selecting the same route after repeated failures creates loops,
                # so route selection must move on once memory has enough evidence.
                continue
            fingerprint = build_action_fingerprint(action, candidate.route)
            score = candidate.score
            if memory.was_recent_failure(fingerprint):
                score -= config.ROUTE_FAILURE_PENALTY
            scored.append(
                RouteCandidate(route=candidate.route, score=score, reason=candidate.reason)
            )

        if not scored:
            if action_name in {"browser_click", "browser_find", "browser_wait_for"}:
                return "ui"
            return "terminal" if action_name == "terminal_command" else "ui"

        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[0].route

    def build_candidates(self, action: dict[str, Any]) -> list[RouteCandidate]:
        action_name = str(action.get("action") or "")
        if action_name == "terminal_command":
            return [RouteCandidate("terminal", ROUTE_WEIGHTS["terminal"], "terminal command")]
        if action_name == "shortcut":
            return [
                RouteCandidate("shortcut", ROUTE_WEIGHTS["shortcut"], "named shortcut"),
                RouteCandidate("ui", ROUTE_WEIGHTS["ui"], "ui fallback"),
            ]
        if action_name in {
            "browser_open",
            "browser_navigate",
            "browser_get_tabs",
            "browser_search",
            "browser_switch_tab",
            "browser_type",
            "browser_extract",
        }:
            return [RouteCandidate("browser", ROUTE_WEIGHTS["browser"], "browser semantic action")]
        if action_name in {"browser_click", "browser_find", "browser_type", "browser_wait_for"}:
            return [RouteCandidate("browser", ROUTE_WEIGHTS["browser"], "browser semantic action")]
        if action_name == "open_app":
            shortcut_name = self._shortcut_name_for_open_app(action)
            if shortcut_name is not None:
                return [
                    RouteCandidate("shortcut", ROUTE_WEIGHTS["shortcut"], "os shortcut available"),
                    RouteCandidate("ui", ROUTE_WEIGHTS["ui"], "desktop fallback"),
                ]
            return [RouteCandidate("ui", ROUTE_WEIGHTS["ui"], "desktop app action")]
        if action_name in {
            "ui_click",
            "click",
            "double_click",
            "right_click",
            "uia_click",
            "type",
            "press",
            "scroll",
            "save_file",
            "open_file",
            "focus_app",
            "close_app",
            "close_tab",
            "new_document",
            "uia_get_visible_elements",
            "uia_click_fallback_search",
            "wait",
            "wait_until",
        }:
            return [RouteCandidate("ui", ROUTE_WEIGHTS["ui"], "ui action")]
        return [RouteCandidate("ui", ROUTE_WEIGHTS["ui"], "fallback")]

    def normalize_action(self, action: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(action)
        action_name = normalized.get("action")
        app_name = str(normalized.get("app_name") or "").lower()
        if action_name == "open_app" and app_name in {
            "chrome",
            "google chrome",
            "browser",
            "microsoft edge",
            "edge",
            "brave",
            "firefox",
        }:
            if normalized.get("url"):
                return {
                    "action": "browser_navigate",
                    "url": normalized.get("url"),
                    "profile_name": normalized.get("profile_name"),
                    "browser_name": app_name,
                    "reasoning": normalized.get("reasoning"),
                    "task_complete": normalized.get("task_complete", False),
                }
            return {
                "action": "browser_open",
                "profile_name": normalized.get("profile_name"),
                "browser_name": app_name,
                "reasoning": normalized.get("reasoning"),
                "task_complete": normalized.get("task_complete", False),
            }
        if action_name == "open_app":
            shortcut_name = self._shortcut_name_for_open_app(normalized)
            if shortcut_name is not None:
                return {
                    "action": "shortcut",
                    "shortcut_name": shortcut_name,
                    "reasoning": normalized.get("reasoning"),
                    "task_complete": normalized.get("task_complete", False),
                }
        if action_name in {"click", "double_click", "right_click", "uia_click"}:
            button = {
                "double_click": "double",
                "right_click": "right",
            }.get(str(action_name), "left")
            normalized_action = {
                "action": "ui_click",
                "button": button,
                "reasoning": normalized.get("reasoning"),
                "task_complete": normalized.get("task_complete", False),
            }
            for key in (
                "x",
                "y",
                "target_text",
                "automation_id",
                "control_type",
                "element_id",
                "grid_cell",
                "screen_size",
            ):
                if key in normalized:
                    normalized_action[key] = normalized[key]
            semantic_text = normalized.get("target_text") or normalized.get("text") or normalized.get("name")
            if semantic_text and "target_text" not in normalized_action:
                normalized_action["target_text"] = semantic_text
            return normalized_action
        return normalized

    def _align_action_to_ui_controls(
        self,
        action: dict[str, Any],
        ui_controls: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if action.get("action") not in {"ui_click", "click", "double_click", "right_click", "uia_click"}:
            return action
        if not ui_controls:
            return action

        element_id = action.get("element_id")
        if element_id is not None:
            for control in ui_controls:
                try:
                    if int(control.get("element_id", 0)) != int(element_id):
                        continue
                except Exception:
                    continue
                aligned = dict(action)
                aligned["action"] = "ui_click"
                aligned["element_id"] = int(element_id)
                aligned["x"] = (int(control.get("left", 0)) + int(control.get("right", 0))) // 2
                aligned["y"] = (int(control.get("top", 0)) + int(control.get("bottom", 0))) // 2
                if control.get("text"):
                    aligned.setdefault("target_text", str(control["text"]))
                if control.get("automation_id"):
                    aligned.setdefault("automation_id", str(control["automation_id"]))
                if control.get("control_type"):
                    aligned.setdefault("control_type", str(control["control_type"]))
                aligned["reasoning"] = (
                    f"{action.get('reasoning') or 'Use UI automation.'} "
                    f"Matched this action to visible element_id {element_id}."
                ).strip()
                return aligned

        target_text = str(
            action.get("target_text") or action.get("text") or action.get("name") or ""
        ).strip()
        automation_id = str(action.get("automation_id") or "").strip()
        class_name = str(action.get("class_name") or "").strip()
        raw_control_type = action.get("control_type")
        if isinstance(raw_control_type, list):
            control_types = {" ".join(str(item or "").lower().split()) for item in raw_control_type}
        else:
            control_types = {
                " ".join(str(raw_control_type or "").lower().split())
            } if raw_control_type else set()
        reasoning = " ".join(str(action.get("reasoning") or "").lower().split())
        action_x = int(action.get("x", -10_000))
        action_y = int(action.get("y", -10_000))

        best_score = -1
        best_control: dict[str, Any] | None = None
        for control in ui_controls:
            if control.get("actionable") is False:
                continue
            try:
                left = int(control.get("left", 0))
                top = int(control.get("top", 0))
                right = int(control.get("right", 0))
                bottom = int(control.get("bottom", 0))
            except Exception:
                continue
            if right <= left or bottom <= top:
                continue

            control_text = " ".join(str(control.get("text") or "").lower().split())
            control_id = " ".join(str(control.get("automation_id") or "").lower().split())
            control_class = " ".join(str(control.get("class_name") or "").lower().split())
            control_kind = " ".join(str(control.get("control_type") or "").lower().split())
            center_x = (left + right) // 2
            center_y = (top + bottom) // 2
            score = 0

            if target_text:
                lowered_target = " ".join(target_text.lower().split())
                if control_text == lowered_target:
                    score += 20
                elif lowered_target and lowered_target in control_text:
                    score += 14
                elif control_text:
                    tokens = [token for token in lowered_target.split() if len(token) >= 3]
                    score += min(sum(token in control_text for token in tokens), 2) * 4

            if automation_id and control_id == " ".join(automation_id.lower().split()):
                score += 18
            if class_name and control_class == " ".join(class_name.lower().split()):
                score += 12
            if control_types and control_kind in control_types:
                score += 8

            if left <= action_x <= right and top <= action_y <= bottom:
                score += 10
            else:
                distance = abs(center_x - action_x) + abs(center_y - action_y)
                if distance <= 40:
                    score += 8
                elif distance <= 120:
                    score += 4

            if control_text and control_text in reasoning:
                score += 10
            elif control_text:
                reasoning_tokens = [token for token in control_text.split() if len(token) >= 3]
                score += min(sum(token in reasoning for token in reasoning_tokens), 2) * 3

            if score > best_score:
                best_score = score
                best_control = control

        if best_control is None or best_score < 8:
            return action

        left = int(best_control.get("left", 0))
        top = int(best_control.get("top", 0))
        right = int(best_control.get("right", 0))
        bottom = int(best_control.get("bottom", 0))
        center_x = (left + right) // 2
        center_y = (top + bottom) // 2
        label = str(
            best_control.get("text")
            or best_control.get("automation_id")
            or best_control.get("control_type")
            or "target"
        ).strip()

        aligned = dict(action)
        aligned["action"] = "ui_click"
        aligned["x"] = center_x
        aligned["y"] = center_y
        aligned["reasoning"] = (
            f"{action.get('reasoning') or 'Use UI automation.'} "
            f"Aligned this action to the visible UI control '{label}'."
        ).strip()
        if best_control.get("text"):
            aligned["target_text"] = str(best_control["text"])
        if best_control.get("automation_id"):
            aligned["automation_id"] = str(best_control["automation_id"])
        if best_control.get("class_name"):
            aligned["class_name"] = str(best_control["class_name"])
        if best_control.get("control_type"):
            aligned["control_type"] = str(best_control["control_type"])
        return aligned

    def _hydrate_scroll_coordinates(
        self,
        action: dict[str, Any],
        context: TaskContext,
    ) -> dict[str, Any]:
        if action.get("action") != "scroll":
            return action
        if action.get("x") is not None and action.get("y") is not None:
            return action
        if context.screen_size is None:
            return action

        width, height = context.screen_size
        hydrated = dict(action)
        hydrated.setdefault("x", width // 2)
        hydrated.setdefault("y", height // 2)
        hydrated["reasoning"] = (
            f"{action.get('reasoning') or 'Scroll the current view.'} "
            "The model did not specify scroll coordinates, so default to the current viewport center."
        ).strip()
        return hydrated

    async def _execute(
        self,
        action: dict[str, Any],
        context: TaskContext,
        route: str,
    ) -> ActionResult:
        if route == "browser":
            return await self.browser_agent.run(action)
        if route == "terminal":
            return await self.terminal_agent.run(action, context.current_working_directory)
        if route == "shortcut":
            shortcut_action = dict(action)
            if shortcut_action.get("action") != "shortcut":
                shortcut_name = self._shortcut_name_for_open_app(shortcut_action)
                shortcut_action = {
                    "action": "shortcut",
                    "shortcut_name": shortcut_name,
                    "reasoning": action.get("reasoning"),
                    "task_complete": action.get("task_complete", False),
                }
            return await self.shortcut_handler.run(shortcut_action)
        return await self.ui_agent.run(action)

    def _route_override(self, action: dict[str, Any], context: TaskContext) -> str | None:
        explicit = action.get("preferred_route") or action.get("route_override")
        if isinstance(explicit, str) and explicit.strip():
            return explicit.strip().lower()

        task_text = context.task.lower()
        if re.search(r"\b(in|via|use)\s+terminal\b", task_text):
            return "terminal"
        if re.search(r"\b(use|in)\s+browser\b", task_text):
            return "browser"
        if re.search(r"\b(shortcut|hotkey|keyboard shortcut)\b", task_text):
            return "shortcut"
        if re.search(r"\b(click on screen|on the screen|screen click)\b", task_text):
            return "ui"
        return None

    def _shortcut_name_for_open_app(self, action: dict[str, Any]) -> str | None:
        app_name = str(action.get("app_name") or "").lower()
        return {
            "file explorer": "os.open_explorer",
            "explorer": "os.open_explorer",
            "settings": "os.open_settings",
            "task manager": "os.open_task_manager",
            "taskmanager": "os.open_task_manager",
        }.get(app_name)


class RetryStrategy:
    """Reason-aware retry and fallback selection."""

    def __init__(self) -> None:
        self._playwright_install_attempted = False

    def next_attempt(
        self,
        action: dict[str, Any],
        result: ActionResult,
        context: TaskContext,
        memory: TaskMemory,
        retry_index: int,
    ) -> RetryDecision:
        action_name = str(action.get("action") or "")
        action_family = action_family_for(action)
        if (
            memory.consecutive_failures_for(action_name) >= 2
            or memory.consecutive_failures_for(action_family) >= 2
        ):
            return RetryDecision(stop=True)
        failure_reason = str(result.failure_reason or "")
        lowered_reason = failure_reason.lower()
        if action_name == "browser_search" and self._is_google_captcha_block(result):
            return self._next_google_captcha_attempt(action, memory)
        if result.success or not result.retryable:
            return RetryDecision(stop=True)
        if any(
            token in lowered_reason
            for token in (
                "blocked_page",
                "empty_results",
                "repeated_redirect",
                "repeated_query",
            )
        ):
            return RetryDecision(stop=True)

        if action_name.startswith("browser") and self._is_playwright_install_error(
            failure_reason
        ):
            if self._playwright_install_attempted:
                return RetryDecision(stop=True)
            self._playwright_install_attempted = True
            # A missing Playwright executable is repairable infrastructure drift, so
            # self-heal it once and then resume the original browser action.
            install_action = {
                "action": "terminal_command",
                "command": "playwright install",
                "reasoning": "Install the missing Playwright browser binaries before retrying the browser action.",
                "task_complete": False,
            }
            if memory.has_failed_fingerprint(
                build_action_fingerprint(install_action, "terminal")
            ):
                return RetryDecision(stop=True)
            return RetryDecision(
                action=install_action,
                forced_route="terminal",
                resume_action=deepcopy(action),
                reason="Install missing Playwright browser binaries before retrying.",
            )

        if action_name in {"browser_click", "browser_find", "browser_type", "browser_wait_for"}:
            if result.data.get("native_browser"):
                return self._next_native_browser_follow_up_attempt(
                    action,
                    memory,
                    retry_index,
                )
            return self._next_browser_selector_attempt(action, memory, retry_index)

        if action_name == "browser_switch_tab":
            return self._next_browser_tab_attempt(action, memory, retry_index)

        if action_name == "browser_navigate" and "timeout" in failure_reason.lower():
            return self._next_browser_navigation_attempt(action, memory, retry_index)

        if action_name == "terminal_command":
            return self._next_terminal_attempt(
                action,
                failure_reason,
                context,
                memory,
                retry_index,
            )

        if action_name == "shortcut":
            return self._next_shortcut_attempt(action, memory, retry_index)

        if action_name == "ui_click":
            return self._next_ui_attempt(action, context, memory, retry_index)

        return RetryDecision(stop=True)

    def _next_browser_tab_attempt(
        self,
        action: dict[str, Any],
        memory: TaskMemory,
        retry_index: int,
    ) -> RetryDecision:
        if retry_index == 0 and action.get("url"):
            updated = deepcopy(action)
            updated["title_contains"] = updated.get("title_contains") or updated.get("text")
            if not self._has_failed_variant(
                memory,
                "browser",
                updated,
                ("action", "url", "title_contains", "text"),
            ):
                return RetryDecision(
                    action=updated,
                    forced_route="browser",
                    reason="Retry tab switching with URL-first matching and looser partial title fallback.",
                )
        return RetryDecision(stop=True)

    def _next_google_captcha_attempt(
        self,
        action: dict[str, Any],
        memory: TaskMemory,
    ) -> RetryDecision:
        simplified_query = simplify_search_query(
            str(action.get("query") or ""),
            aggressive=True,
        )
        if (
            not simplified_query
            or simplified_query == str(action.get("query") or "")
            or action.get("query_simplified")
        ):
            return RetryDecision(stop=True)
        updated = deepcopy(action)
        updated["query"] = simplified_query
        updated["query_simplified"] = True
        if self._has_failed_variant(
            memory,
            "browser",
            updated,
            ("action", "query", "query_simplified"),
        ):
            return RetryDecision(stop=True)
        return RetryDecision(
            action=updated,
            forced_route="browser",
            reason="Retry browser search once with a simpler query after Google blocked the previous search.",
        )

    def _next_browser_selector_attempt(
        self,
        action: dict[str, Any],
        memory: TaskMemory,
        retry_index: int,
    ) -> RetryDecision:
        strategies = ["role", "label", "text", "partial_text", "aria", "test_id", "css"]
        current = str(action.get("selector_strategy") or strategies[0])
        try:
            current_index = strategies.index(current)
        except ValueError:
            current_index = 0
        for next_strategy in strategies[current_index + 1 :]:
            updated = deepcopy(action)
            updated["selector_strategy"] = next_strategy
            if self._has_failed_variant(
                memory,
                "browser",
                updated,
                ("action", "target_text", "text", "name", "selector_strategy"),
            ):
                continue
            return RetryDecision(
                action=updated,
                forced_route="browser",
                reason=f"Retry browser action with {updated['selector_strategy']} selector strategy.",
            )
        text = action.get("target_text") or action.get("text") or action.get("name")
        if action.get("action") == "browser_find" and text:
            shortcut_action = {
                "action": "shortcut",
                "shortcut_name": "browser.find",
                "text": text,
                "reasoning": action.get("reasoning"),
                "task_complete": action.get("task_complete", False),
                "target_app": "browser",
            }
            if not self._has_failed_variant(
                memory,
                "shortcut",
                shortcut_action,
                ("action", "shortcut_name", "text", "ensure_focus"),
            ):
                return RetryDecision(
                    action=shortcut_action,
                    forced_route="shortcut",
                    reason="Fallback to browser find shortcut.",
                )
        if action.get("action") == "browser_type":
            return RetryDecision(stop=True)
        if retry_index < config.MAX_ROUTE_ATTEMPTS - 1:
            ui_action = {
                "action": "ui_click",
                "target_text": text,
                "reasoning": action.get("reasoning"),
                "task_complete": action.get("task_complete", False),
            }
            if not self._has_failed_variant(
                memory,
                "ui",
                ui_action,
                ("action", "target_text", "automation_id", "x", "y", "uia_refined"),
            ):
                return RetryDecision(
                    action=ui_action,
                    forced_route="ui",
                    reason="Fallback to UI browser interaction after browser strategies were exhausted.",
                )
        return RetryDecision(stop=True)

    def _next_native_browser_follow_up_attempt(
        self,
        action: dict[str, Any],
        memory: TaskMemory,
        retry_index: int,
    ) -> RetryDecision:
        text = action.get("target_text") or action.get("text") or action.get("name")
        if action.get("action") == "browser_find" and text:
            shortcut_action = {
                "action": "shortcut",
                "shortcut_name": "browser.find",
                "text": text,
                "reasoning": action.get("reasoning"),
                "task_complete": action.get("task_complete", False),
                "target_app": "browser",
            }
            if not self._has_failed_variant(
                memory,
                "shortcut",
                shortcut_action,
                ("action", "shortcut_name", "text", "ensure_focus"),
            ):
                return RetryDecision(
                    action=shortcut_action,
                    forced_route="shortcut",
                    reason="Fallback to the desktop browser find shortcut.",
                )
        if action.get("action") == "browser_type":
            return RetryDecision(stop=True)
        if retry_index < config.MAX_ROUTE_ATTEMPTS - 1:
            ui_action = {
                "action": "ui_click",
                "target_text": text,
                "reasoning": action.get("reasoning"),
                "task_complete": action.get("task_complete", False),
            }
            if not self._has_failed_variant(
                memory,
                "ui",
                ui_action,
                ("action", "target_text", "automation_id", "x", "y", "uia_refined"),
            ):
                return RetryDecision(
                    action=ui_action,
                    forced_route="ui",
                    reason="Fallback to UI interaction in the user's desktop browser.",
                )
        return RetryDecision(stop=True)

    def _next_browser_navigation_attempt(
        self,
        action: dict[str, Any],
        memory: TaskMemory,
        retry_index: int,
    ) -> RetryDecision:
        longer_timeout = deepcopy(action)
        longer_timeout["wait_timeout_seconds"] = float(
            action.get("wait_timeout_seconds") or config.PLAYWRIGHT_TIMEOUT_SECONDS
        ) * 2

        reload_action = deepcopy(action)
        reload_action["reload"] = True

        reopen_action = deepcopy(action)
        reopen_action["reopen_session"] = True

        attempts = [
            ("Retry navigation with a longer timeout.", longer_timeout),
            ("Retry navigation after a reload.", reload_action),
            ("Retry navigation after reopening the browser session.", reopen_action),
        ]
        for reason, updated in attempts[retry_index:]:
            if self._has_failed_variant(
                memory,
                "browser",
                updated,
                ("action", "url", "wait_timeout_seconds", "reload", "reopen_session"),
            ):
                continue
            return RetryDecision(
                action=updated,
                forced_route="browser",
                reason=reason,
            )
        return RetryDecision(stop=True)

    def _next_terminal_attempt(
        self,
        action: dict[str, Any],
        failure_reason: str,
        context: TaskContext,
        memory: TaskMemory,
        retry_index: int,
    ) -> RetryDecision:
        if retry_index > 0:
            return RetryDecision(stop=True)
        lowered = failure_reason.lower()
        if any(token in lowered for token in ("path", "directory", "cannot find")):
            updated = deepcopy(action)
            updated["working_directory"] = context.current_working_directory
            if self._has_failed_variant(
                memory,
                "terminal",
                updated,
                ("action", "command", "working_directory"),
            ):
                return RetryDecision(stop=True)
            return RetryDecision(
                action=updated,
                forced_route="terminal",
                reason="Retry terminal command with corrected working directory.",
            )
        return RetryDecision(stop=True)

    def _next_shortcut_attempt(
        self,
        action: dict[str, Any],
        memory: TaskMemory,
        retry_index: int,
    ) -> RetryDecision:
        if retry_index == 0 and not action.get("ensure_focus"):
            updated = deepcopy(action)
            updated["ensure_focus"] = True
            if not self._has_failed_variant(
                memory,
                "shortcut",
                updated,
                ("action", "shortcut_name", "text", "ensure_focus"),
            ):
                return RetryDecision(
                    action=updated,
                    forced_route="shortcut",
                    reason="Retry shortcut after focusing the target app.",
                )
        shortcut_name = str(action.get("shortcut_name") or "")
        if shortcut_name == "os.open_settings":
            ui_action = {
                "action": "open_app",
                "app_name": "settings",
                "reasoning": action.get("reasoning"),
                "task_complete": action.get("task_complete", False),
            }
            if not self._has_failed_variant(
                memory,
                "ui",
                ui_action,
                ("action", "app_name"),
            ):
                return RetryDecision(
                    action=ui_action,
                    forced_route="ui",
                    reason="Fallback to UI app launch for Settings.",
                )
        return RetryDecision(stop=True)

    def _next_ui_attempt(
        self,
        action: dict[str, Any],
        context: TaskContext,
        memory: TaskMemory,
        retry_index: int,
    ) -> RetryDecision:
        if retry_index == 0 and action.get("target_text") and action.get("control_type") is not None:
            updated = deepcopy(action)
            updated["control_type"] = None
            if not self._has_failed_variant(
                memory,
                "ui",
                updated,
                ("action", "target_text", "automation_id", "class_name", "control_type", "x", "y"),
            ):
                return RetryDecision(
                    action=updated,
                    forced_route="ui",
                    reason="Retry UI action with looser control type matching.",
                )
        if retry_index <= 1 and (action.get("automation_id") or action.get("class_name")):
            updated = deepcopy(action)
            updated.pop("automation_id", None)
            updated.pop("class_name", None)
            if not self._has_failed_variant(
                memory,
                "ui",
                updated,
                ("action", "target_text", "automation_id", "class_name", "control_type", "x", "y"),
            ):
                return RetryDecision(
                    action=updated,
                    forced_route="ui",
                    reason="Retry UI action without brittle automation-id or class-name filters.",
                )
        if retry_index <= 1 and action.get("target_text") and self._ui_state_has_search_input(context):
            updated = {
                "action": "uia_click_fallback_search",
                "text": str(action.get("target_text")),
                "reasoning": action.get("reasoning"),
                "task_complete": action.get("task_complete", False),
            }
            if not self._has_failed_variant(
                memory,
                "ui",
                updated,
                ("action", "text"),
            ):
                return RetryDecision(
                    action=updated,
                    forced_route="ui",
                    reason="Fallback to searchable navigation through the visible app search box.",
                )
        return RetryDecision(stop=True)

    def _ui_state_has_search_input(self, context: TaskContext) -> bool:
        for control in context.ui_controls:
            control_type = " ".join(str(control.get("control_type") or "").strip().lower().split())
            if control_type not in {"edit", "combobox", "searchbox"}:
                continue
            label = " ".join(
                " ".join(
                    str(control.get(key) or "").strip().lower().split()
                )
                for key in ("text", "automation_id", "class_name")
            )
            if any(token in label for token in ("search", "find", "setting")):
                return True
        return False

    def _is_playwright_install_error(self, failure_reason: str) -> bool:
        lowered = failure_reason.lower()
        return "executable doesn't exist" in lowered or "playwright install" in lowered

    def _is_google_captcha_block(self, result: ActionResult) -> bool:
        return bool(
            result.data.get("blocked")
            or "blocked by google captcha" in str(result.failure_reason or "").lower()
        )

    def _has_failed_variant(
        self,
        memory: TaskMemory,
        route: str,
        action: dict[str, Any],
        keys: tuple[str, ...],
    ) -> bool:
        for step in memory.steps:
            if step.success or step.route != route:
                continue
            if any(step.action.get(key) != action.get(key) for key in keys):
                continue
            return True
        return False


class RetryManager:
    """Execute strategic retries and fallbacks for a single action."""

    def __init__(
        self,
        *,
        router: ActionRouter,
        strategy: RetryStrategy | None = None,
        max_attempts: int = min(config.MAX_ROUTE_ATTEMPTS, 3),
    ) -> None:
        self.router = router
        self.strategy = strategy or RetryStrategy()
        self.max_attempts = max_attempts

    async def resolve(
        self,
        action: dict[str, Any],
        result: ActionResult,
        context: TaskContext,
        memory: TaskMemory,
    ) -> tuple[dict[str, Any], ActionResult]:
        current_action = dict(action)
        current_result = result
        attempts = 1
        fallback_chain: list[str] = []

        while attempts < self.max_attempts and not current_result.success:
            current_result = await self._observe_failure_state(current_result, context)
            if memory.consecutive_failures_for(action_family_for(current_action)) >= 2:
                break
            decision = self.strategy.next_attempt(
                current_action,
                current_result,
                context,
                memory,
                attempts - 1,
            )
            if decision.stop or decision.action is None:
                break
            next_action = decision.action
            next_route = decision.forced_route or self.router.choose_route(
                next_action,
                context,
                memory,
            )
            next_fingerprint = build_action_fingerprint(next_action, next_route)
            if (
                memory.consecutive_failures_for(str(next_action.get("action") or "")) >= 2
                or memory.consecutive_failures_for(action_family_for(next_action)) >= 2
                or memory.consecutive_failures_for_fingerprint(next_fingerprint) >= 2
            ):
                break
            if next_action == current_action and next_route == current_result.route:
                break
            print(f"[RETRY] Strategy → {decision.reason or next_route}")
            current_result = await self.router.dispatch(
                next_action,
                context,
                memory,
                forced_route=next_route,
            )
            attempts += 1
            current_result.attempts = attempts
            current_result.strategy = current_result.strategy or decision.reason
            if next_route and next_route not in fallback_chain:
                fallback_chain.append(next_route)
            memory.record_step(
                next_action,
                current_result.route,
                current_result,
                success=current_result.success,
                failure_reason=current_result.failure_reason,
                retry_count=attempts - 1,
                fallback_from=current_action.get("action"),
            )

            if (
                decision.resume_action is not None
                and current_result.success
                and attempts < self.max_attempts
            ):
                resumed_action = deepcopy(decision.resume_action)
                current_result = await self.router.dispatch(
                    resumed_action,
                    context,
                    memory,
                    forced_route="browser",
                )
                attempts += 1
                current_result.attempts = attempts
                current_result.strategy = current_result.strategy or decision.reason
                memory.record_step(
                    resumed_action,
                    current_result.route,
                    current_result,
                    success=current_result.success,
                    failure_reason=current_result.failure_reason,
                    retry_count=attempts - 1,
                    fallback_from=next_action.get("action"),
                )
                current_action = resumed_action
                continue

            current_action = next_action

        current_result.attempts = attempts
        current_result.fallback_chain = fallback_chain
        return current_action, current_result

    async def _observe_failure_state(
        self,
        result: ActionResult,
        context: TaskContext,
    ) -> ActionResult:
        active_window = await anyio.to_thread.run_sync(get_active_window_info)
        browser_tabs: list[dict[str, Any]] = []
        try:
            browser_agent = getattr(self.router, "browser_agent", None)
            if browser_agent is not None and hasattr(browser_agent, "get_tabs"):
                tabs_result = await browser_agent.get_tabs()
                browser_tabs = list(
                    tabs_result.data.get("tabs") or tabs_result.data.get("browser_tabs") or []
                )
        except Exception as exc:
            browser_tabs = [{"error": str(exc)}]

        try:
            ui_state = await anyio.to_thread.run_sync(
                lambda: uia_get_visible_elements(max_depth=3)
            )
        except Exception as exc:
            ui_state = {"elements": [], "summary": f"uia_observation_failed: {exc}"}

        context.active_window_title = active_window.get("title")  # type: ignore[assignment]
        context.active_process_name = active_window.get("process_name")  # type: ignore[assignment]
        context.active_window_hwnd = active_window.get("hwnd")  # type: ignore[assignment]
        context.browser_tabs = browser_tabs
        context.ui_controls = list(ui_state.get("elements") or [])
        context.ui_element_summary = str(ui_state.get("summary") or "")

        observed_state = {
            "active_window": active_window,
            "browser_tabs": browser_tabs,
            "ui_visible_elements": ui_state.get("elements") or [],
            "ui_visible_summary": ui_state.get("summary") or "",
        }
        print(
            "[STATE] "
            f"active={active_window.get('title') or 'Unknown'}; "
            f"tabs={len(browser_tabs)}; "
            f"ui_elements={len(ui_state.get('elements') or [])}"
        )
        result.data.setdefault("observed_state", observed_state)
        result.context_updates.setdefault("browser_tabs", browser_tabs)
        result.context_updates.setdefault("ui_controls", list(ui_state.get("elements") or []))
        result.context_updates.setdefault("ui_element_summary", str(ui_state.get("summary") or ""))
        return result
