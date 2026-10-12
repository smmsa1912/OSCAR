"""Planner interfaces and Gemini-backed planning."""

from __future__ import annotations

import json
from datetime import datetime
from functools import partial
from typing import Any, Protocol

import anyio

from oscar import config
from oscar.browser.query_utils import (
    extract_wait_until_datetime,
    normalize_url,
    simplify_search_query,
    task_requests_current_date,
    task_requests_current_time,
)
from oscar.context import TaskContext
from oscar.memory import TaskMemory, build_action_fingerprint
from oscar.prompt_builder import build_prompt
from oscar.utils.logging import get_logger, log_event
from oscar.utils.paths import generalize_known_user_paths, render_known_path_strings
from oscar.gemini_client import GeminiResponseError
from oscar.model_gateway import ActionModelGateway, create_model_gateway


LOGGER = get_logger("planner")


class BrainPlanner(Protocol):
    """Planner interface used by the orchestrator."""

    async def plan_next_action(
        self,
        context: TaskContext,
        memory: TaskMemory,
    ) -> dict[str, Any]:
        """Return the next semantic action for the current task."""


class ModelBrain:
    """Provider-neutral planner with critique-and-revise safeguards.

    ``ask_model`` remains available as a test/integration seam for compatibility.
    Without it, the configured gateway is selected by ``LLM_PROVIDER``.
    """

    def __init__(
        self,
        *,
        ask_model=None,
        provider: ActionModelGateway | None = None,
        prompt_builder=build_prompt,
        model_name: str | None = None,
    ) -> None:
        self.provider = provider
        self._model_name_explicit = model_name is not None
        if ask_model is None:
            self.provider = provider or create_model_gateway()
            self.ask_model = self.provider.generate_action
            default_model = self.provider.default_model
        else:
            self.ask_model = ask_model
            default_model = config.GEMINI_MODEL
        self.prompt_builder = prompt_builder
        self.model_name = model_name or default_model

    async def plan_next_action(
        self,
        context: TaskContext,
        memory: TaskMemory,
    ) -> dict[str, Any]:
        direct = self._direct_context_answer(context, memory)
        if direct is not None:
            return direct

        prompt = self._build_prompt(context, memory)
        try:
            action = await self._ask_model(prompt, context)
        except Exception as exc:
            return self._recover_from_model_error(exc)
        action = self._post_process_action(action, context)

        critique = self._critique_action(action, context, memory)
        if critique is not None:
            revision_prompt = (
                f"{prompt}\n\nDraft action to revise:\n{action}\n\n"
                f"Reliability critique:\n{critique}\n\n"
                "Return one improved next action as valid JSON only."
            )
            try:
                revised_action = await self._ask_model(revision_prompt, context)
            except Exception as exc:
                return self._recover_from_model_error(exc)
            action = self._post_process_action(revised_action, context)
            log_event(
                LOGGER,
                "planner_revision",
                critique=critique,
                revised_action=action.get("action"),
            )

        return action

    def _build_prompt(self, context: TaskContext, memory: TaskMemory) -> str:
        return self.prompt_builder(
            context.task,
            memory.get_recent_steps(5),
            step_number=len(memory.steps) + 1,
            max_steps=config.MAX_STEPS,
            screen_size=context.screen_size,
            active_window_title=context.active_window_title,
            active_process_name=context.active_process_name,
            system_specs=context.system_specs,
            known_paths=render_known_path_strings(),
            ui_controls=context.ui_controls,
            visible_windows=context.visible_windows,
            current_local_time=context.current_local_time,
            terminal_working_directory=context.current_working_directory,
            browser_url=context.browser_url,
            browser_title=context.browser_title,
            browser_tabs=context.browser_tabs,
            failure_history=memory.get_failures()[-5:],
            persistent_memory=context.persistent_memory,
            ui_element_summary=context.ui_element_summary,
        )

    async def _ask_model(self, prompt: str, context: TaskContext) -> dict[str, Any]:
        # Let the OmniRoute gateway select a role-specific model unless the caller
        # explicitly pinned one. Gemini and injected test adapters keep their legacy
        # configured-model behavior.
        selected_model = self.model_name
        if (
            not self._model_name_explicit
            and self.provider is not None
            and self.provider.provider_name == "omniroute"
            and config.OMNIROUTE_AUTO_ROUTING
        ):
            selected_model = None
        raw_action = await anyio.to_thread.run_sync(
            partial(
                self.ask_model,
                context.screenshot,
                prompt,
                model_name=selected_model,
            )
        )
        return dict(raw_action)

    def _recover_from_model_error(self, exc: Exception) -> dict[str, Any]:
        LOGGER.warning(
            "Recovering from planner model response error: %s",
            exc,
            exc_info=isinstance(exc, (GeminiResponseError, json.JSONDecodeError, ValueError)),
        )
        safe_error = str(exc).lower()
        if "token budget" in safe_error or "estimated size exceeds" in safe_error:
            return {
                "action": "done",
                "reasoning": (
                    "Stopped before another cloud request to respect OSCAR's configured "
                    "token budget. Reduce task scope or adjust the OmniRoute budget settings "
                    "if more steps are necessary."
                ),
                "task_complete": True,
            }
        return {
            "action": "wait",
            "seconds": 3,
            "reasoning": "Recovering from a model response or planning error.",
            "task_complete": False,
        }

    def _direct_context_answer(
        self,
        context: TaskContext,
        memory: TaskMemory,
    ) -> dict[str, Any] | None:
        asks_for_time = task_requests_current_time(context.task)
        asks_for_date = task_requests_current_date(context.task)
        if asks_for_time or asks_for_date:
            reference = self._parse_current_local_time(context.current_local_time)
            timestamp = reference.isoformat(timespec="seconds")
            if asks_for_time and asks_for_date:
                reasoning = f"The current local date and time is {timestamp}."
            elif asks_for_date:
                reasoning = f"Today's local date is {reference.date().isoformat()}."
            else:
                reasoning = f"The current local time is {timestamp}."
            return {
                "action": "done",
                "reasoning": reasoning,
                "task_complete": True,
            }

        target = extract_wait_until_datetime(
            context.task,
            reference_time=context.current_local_time,
        )
        if target is None:
            return None

        wait_action = {
            "action": "wait_until",
            "timestamp": target.isoformat(),
            "reasoning": (
                f"Wait until local time {target.strftime('%H:%M:%S')} before starting the requested work."
            ),
            "task_complete": False,
        }
        if memory.has_failed_fingerprint(build_action_fingerprint(wait_action, "system")):
            return None
        if self._seconds_until(target, context.current_local_time) > 1.0 and not self._has_completed_wait(
            memory,
            wait_action["timestamp"],
        ):
            return wait_action
        return None

    def _post_process_action(
        self,
        action: dict[str, Any],
        context: TaskContext,
    ) -> dict[str, Any]:
        normalized = dict(action)
        normalized.setdefault("reasoning", "Choose the most reliable next step.")
        normalized["task_complete"] = bool(normalized.get("task_complete", False))

        action_name = str(normalized.get("action") or "")
        for key in ("file_path", "working_directory", "command"):
            if isinstance(normalized.get(key), str):
                normalized[key] = generalize_known_user_paths(str(normalized[key]))
        if action_name == "browser_search" and normalized.get("query"):
            normalized["query"] = simplify_search_query(str(normalized["query"])) or str(
                normalized["query"]
            ).strip()
        if action_name == "browser_navigate" and normalized.get("url"):
            normalized["url"] = normalize_url(str(normalized["url"]))
        if action_name in {"ui_click", "uia_click"}:
            if normalized.get("target_text") is None and normalized.get("text"):
                normalized["target_text"] = normalized.get("text")
            matched_id = self._match_element_id(normalized, context.ui_controls)
            if matched_id is not None:
                normalized["element_id"] = matched_id
        return normalized

    def _critique_action(
        self,
        action: dict[str, Any],
        context: TaskContext,
        memory: TaskMemory,
    ) -> str | None:
        """Run all registered validation rules and return the first failure."""
        for rule in VALIDATION_RULES:
            result = rule.check(action, context, memory, planner=self)
            if result is not None:
                return result
        return None

    def _match_element_id(
        self,
        action: dict[str, Any],
        controls: list[dict[str, Any]],
    ) -> int | None:
        target_text = " ".join(str(action.get("target_text") or "").lower().split())
        automation_id = " ".join(str(action.get("automation_id") or "").lower().split())
        control_type = " ".join(str(action.get("control_type") or "").lower().split())
        for control in controls:
            control_text = " ".join(str(control.get("text") or "").lower().split())
            control_id = " ".join(str(control.get("automation_id") or "").lower().split())
            control_kind = " ".join(str(control.get("control_type") or "").lower().split())
            if target_text and control_text and target_text not in control_text:
                continue
            if automation_id and control_id and automation_id != control_id:
                continue
            if control_type and control_kind and control_type != control_kind:
                continue
            element_id = control.get("element_id")
            if isinstance(element_id, int) and element_id > 0:
                return element_id
        return None

    def _has_completed_wait(self, memory: TaskMemory, timestamp: str) -> bool:
        for item in reversed(memory.get_successes()):
            action_payload = item.get("action")
            if not isinstance(action_payload, dict):
                continue
            if action_payload.get("action") != "wait_until":
                continue
            if str(action_payload.get("timestamp") or "") == timestamp:
                return True
        return False

    def _recent_successful_action(
        self,
        memory: TaskMemory,
        action_name: str,
        *,
        window: int = 2,
    ) -> bool:
        for item in reversed(memory.get_successes()[-window:]):
            action_payload = item.get("action")
            if isinstance(action_payload, dict) and action_payload.get("action") == action_name:
                return True
        return False

    def _seconds_until(
        self,
        target: datetime,
        current_local_time: str | None,
    ) -> float:
        reference = self._parse_current_local_time(current_local_time)
        return (target - reference).total_seconds()

    def _parse_current_local_time(self, current_local_time: str | None) -> datetime:
        if current_local_time:
            try:
                return datetime.fromisoformat(current_local_time)
            except ValueError:
                pass
        return datetime.now().astimezone()


# ── Rule-Engine Validation ────────────────────────────────────────────
#
# Each rule is a simple class with a ``check()`` method that returns a
# critique string on failure or ``None`` on pass.  This replaces the old
# monolithic ``if/elif`` stack and makes it trivial to add, remove, or
# reorder rules without merge conflicts.


class _ValidationRule:
    """Base class for planner validation rules."""

    def check(
        self,
        action: dict[str, Any],
        context: TaskContext,
        memory: TaskMemory,
        *,
        planner: GeminiBrain,
    ) -> str | None:
        raise NotImplementedError


class _WaitUntilRequired(_ValidationRule):
    """If the task has a future clock time, the first step must be wait_until."""

    def check(self, action, context, memory, *, planner):
        target_time = extract_wait_until_datetime(
            context.task,
            reference_time=context.current_local_time,
        )
        action_name = str(action.get("action") or "")
        if (
            target_time is not None
            and planner._seconds_until(target_time, context.current_local_time) > 1.0
            and action_name != "wait_until"
            and not planner._has_completed_wait(memory, target_time.isoformat())
        ):
            return "The task includes a future clock time, so the first step must be wait_until."
        return None


class _SearchQueryTooLong(_ValidationRule):
    """Browser search queries should be short keyword bursts."""

    def check(self, action, context, memory, *, planner):
        if str(action.get("action") or "") == "browser_search":
            query = str(action.get("query") or "").strip()
            if len(query.split()) > 5:
                return "The browser search query is too long. Use a shorter keyword query."
        return None


class _BrowserPrerequisite(_ValidationRule):
    """Most browser actions need a browser_get_tabs call first."""

    _EXEMPT_ACTIONS = {"browser_open", "browser_navigate", "browser_search", "browser_get_tabs"}

    def check(self, action, context, memory, *, planner):
        action_name = str(action.get("action") or "")
        if (
            action_name.startswith("browser_")
            and action_name not in self._EXEMPT_ACTIONS
            and not planner._recent_successful_action(memory, "browser_get_tabs")
        ):
            return "Before any browser action except navigation, first call browser_get_tabs to inspect the real open tabs."
        return None


class _UIAObservationRequired(_ValidationRule):
    """Semantic UI clicks need a uia_get_visible_elements call first."""

    def check(self, action, context, memory, *, planner):
        action_name = str(action.get("action") or "")
        if (
            action_name in {"uia_click", "ui_click"}
            and not planner._recent_successful_action(memory, "uia_get_visible_elements")
        ):
            return "Before any semantic UI click, first call uia_get_visible_elements so OSCAR observes the real visible controls."
        return None


class _PreferSemanticOverRawCoordinates(_ValidationRule):
    """Warn when raw coordinate actions are used despite a UI snapshot."""

    def check(self, action, context, memory, *, planner):
        action_name = str(action.get("action") or "")
        if action_name in {"click", "double_click", "right_click", "scroll"} and context.ui_controls:
            return "A UI snapshot is available, so prefer a semantic UI action or element_id before raw coordinates."
        return None


class _RawCoordinateFallback(_ValidationRule):
    """If UI controls exist, insist on element_id or target_text."""

    def check(self, action, context, memory, *, planner):
        action_name = str(action.get("action") or "")
        if action_name in {"click", "double_click", "right_click", "scroll", "ui_click"}:
            if context.ui_controls and action.get("element_id") is None and not action.get("target_text"):
                return "This action still relies on raw coordinates. Use UIA element_id or target_text unless every semantic option is exhausted."
        return None


class _PreferBrowserActionsOverKeyboard(_ValidationRule):
    """Raw keyboard input should not be used for browser tasks."""

    _BROWSER_TOKENS = ("browser", "chrome", "edge", "google", "website", "web")

    def check(self, action, context, memory, *, planner):
        action_name = str(action.get("action") or "")
        if action_name in {"type", "hotkey", "press"} and (
            context.browser_url
            or any(token in context.task.lower() for token in self._BROWSER_TOKENS)
        ):
            return "This looks like browser work. Prefer semantic browser actions instead of raw keyboard input."
        return None


class _PreferTabSwitchOverClick(_ValidationRule):
    """Tab management should use browser_switch_tab, not clicks."""

    def check(self, action, context, memory, *, planner):
        action_name = str(action.get("action") or "")
        if (
            context.browser_url
            and "tab" in context.task.lower()
            and action_name in {"browser_click", "browser_find", "click", "ui_click"}
        ):
            return "This looks like existing browser tab management. Prefer browser_switch_tab before clicking browser chrome."
        return None


class _AvoidDuplicateBrowserInstance(_ValidationRule):
    """Don't open a new browser when one is already available."""

    _BROWSER_TOKENS = ("browser", "chrome", "edge", "tab", "website")

    def check(self, action, context, memory, *, planner):
        action_name = str(action.get("action") or "")
        if (
            context.browser_url
            and action_name in {"browser_open", "open_app"}
            and any(token in context.task.lower() for token in self._BROWSER_TOKENS)
        ):
            return "A browser window is already available. Prefer browser_switch_tab, focus_app, or browser_navigate over opening another browser instance."
        return None


class _HardcodedPathDetector(_ValidationRule):
    """Reject actions that embed absolute user home paths."""

    def check(self, action, context, memory, *, planner):
        for key in ("file_path", "working_directory", "command"):
            value = str(action.get(key) or "")
            if value and "c:\\users\\" in value.lower():
                return "Do not hardcode user home paths. Use runtime-provided known paths or the current working directory."
        return None


class _StrictGridPayload(_ValidationRule):
    """Reject payloads that combine grid_cell and raw coordinates."""

    def check(self, action, context, memory, *, planner):
        if action.get("grid_cell") and (action.get("x") is not None or action.get("y") is not None):
            return "If grid_cell is used, do not output x and y coordinates."
        return None


class _UIAIntentMismatch(_ValidationRule):
    """Catch cases where the LLM tries to click an input but selects a Window Control."""

    _INPUT_INTENT_TOKENS = {"search", "type", "input", "compose"}
    _WINDOW_CONTROL_TOKENS = {"minimize", "close", "maximize"}

    def check(self, action, context, memory, *, planner):
        if str(action.get("action") or "") not in {"uia_click", "ui_click"}:
            return None

        reasoning = str(action.get("reasoning") or "").lower()
        if not any(token in reasoning for token in self._INPUT_INTENT_TOKENS):
            return None

        target_text = str(action.get("target_text") or "").lower()
        automation_id = str(action.get("automation_id") or "").lower()

        if any(token in target_text or token in automation_id for token in self._WINDOW_CONTROL_TOKENS):
            return (
                "CRITICAL: Your reasoning indicates you want to interact with an input "
                "or search bar, but you selected a Window Control button "
                "(Minimize/Close). You must find the correct target, or use grid_cell fallback."
            )
        return None


class _UIAControlTypeMismatch(_ValidationRule):
    """Catch element_id hallucinations where reasoning contradicts control_type.

    Example: The LLM says "click the OK button" but targets element_id 1 which
    is an Image control.  This forces it to select the real Button element or
    fall back to a grid_cell coordinate click.
    """

    _BUTTON_INTENT_TOKENS = {"button", "dismiss", "ok", "close", "cancel", "yes", "no", "accept", "confirm"}
    _WRONG_CONTROL_TYPES = {"image", "text", "statictext"}

    def check(self, action, context, memory, *, planner):
        action_name = str(action.get("action") or "")
        if action_name != "uia_click":
            return None

        reasoning = str(action.get("reasoning") or "").lower()
        control_type = str(action.get("control_type") or "").lower().strip()
        element_id = action.get("element_id")

        # If no explicit control_type on the action, try to look it up from
        # the current UI snapshot.
        if not control_type and element_id is not None and context.ui_controls:
            for ctrl in context.ui_controls:
                if ctrl.get("element_id") == element_id:
                    control_type = str(ctrl.get("control_type") or "").lower().strip()
                    break

        if not control_type or control_type not in self._WRONG_CONTROL_TYPES:
            return None

        # Check if the reasoning implies a button-like intent
        if any(token in reasoning for token in self._BUTTON_INTENT_TOKENS):
            return (
                "You are attempting to click an Image or Text element to dismiss a dialog. "
                "You must select the element_id corresponding to the actual 'Button' control, "
                "or use the grid_cell coordinate fallback."
            )
        return None


# Central rule registry — order matters (first match wins).
VALIDATION_RULES: list[_ValidationRule] = [
    _WaitUntilRequired(),
    _SearchQueryTooLong(),
    _StrictGridPayload(),
    _BrowserPrerequisite(),
    _UIAObservationRequired(),
    _UIAIntentMismatch(),
    _UIAControlTypeMismatch(),
    _PreferSemanticOverRawCoordinates(),
    _RawCoordinateFallback(),
    _PreferBrowserActionsOverKeyboard(),
    _PreferTabSwitchOverClick(),
    _AvoidDuplicateBrowserInstance(),
    _HardcodedPathDetector(),
]


# Backward-compatible public name retained for existing integrations.
GeminiBrain = ModelBrain
