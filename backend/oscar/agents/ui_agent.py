"""UI fallback executor built on top of the existing low-level executor."""

from __future__ import annotations

import asyncio
from typing import Any

import anyio

from oscar import config
from oscar.executor import ActionValidationError, execute_action
from oscar.runtime import ActionResult
from oscar.ui_automation import resolve_active_window_control
from oscar.vision.grid_overlay import grid_cell_to_pixel
from oscar.window_control import get_active_window_info
from oscar.window_control import app_window_exists, focus_app_window


def _is_pyautogui_fail_safe_exception(exc: Exception) -> bool:
    return (
        exc.__class__.__name__ == "FailSafeException"
        and exc.__class__.__module__.startswith("pyautogui")
    )


def _raise_critical_exception(exc: Exception) -> None:
    if _is_pyautogui_fail_safe_exception(exc):
        raise exc


def _error_data(exc: Exception) -> dict[str, str]:
    return {
        "error_type": exc.__class__.__name__,
        "error_message": str(exc),
    }


_GRID_CELL_EXCLUSIVE_KEYS = (
    "element_id",
    "automation_id",
    "target_text",
    "control_type",
    "x",
    "y",
)


class UIAgent:
    """Last-resort UI automation path."""

    async def run(self, action: dict[str, Any]) -> ActionResult:
        # Guard this route before normalization or verification. In particular,
        # _verify_action may inspect/focus a window for open_app/focus_app even
        # when the lower-level executor correctly returned a dry-run result.
        if config.OSCAR_DRY_RUN:
            action_name = str(action.get("action") or "ui_click")
            return ActionResult(
                success=True,
                route="ui",
                action=action_name,
                confidence=1.0,
                data={
                    "dry_run": True,
                    "execution_confirmed": False,
                    "would_execute": action_name,
                    "message": "Dry-run enabled; no UI action or verification was executed.",
                },
                retryable=False,
            )

        normalized = self._normalize_action(action)
        fallback_action = self._coordinate_fallback_action(action, normalized)

        try:
            metadata = await self._execute(normalized)
        except asyncio.CancelledError:
            return ActionResult(
                success=False,
                route="ui",
                action=str(action.get("action") or "ui_click"),
                confidence=0.1,
                failure_reason="Execution cancelled",
                retryable=True,
            )
        except ActionValidationError as exc:
            if fallback_action is None:
                return ActionResult(
                    success=False,
                    route="ui",
                    action=str(action.get("action") or "ui_click"),
                    confidence=0.2,
                    failure_reason=str(exc),
                    retryable=True,
                    data=_error_data(exc),
                )
            try:
                fallback_metadata = await self._execute(fallback_action)
            except asyncio.CancelledError:
                return ActionResult(
                    success=False,
                    route="ui",
                    action=str(action.get("action") or "ui_click"),
                    confidence=0.1,
                    failure_reason="Execution cancelled",
                    retryable=True,
                )
            except Exception as fallback_exc:
                _raise_critical_exception(fallback_exc)
                return ActionResult(
                    success=False,
                    route="ui",
                    action=str(action.get("action") or "ui_click"),
                    confidence=0.15,
                    failure_reason=str(fallback_exc),
                    retryable=True,
                    data=_error_data(fallback_exc),
                )
            payload = fallback_metadata if isinstance(fallback_metadata, dict) else {}
            payload.setdefault("execution_confirmed", True)
            payload.setdefault("verification_source", "semantic_coordinate_fallback")
            payload.setdefault("fallback_used", "coordinate_click")
            return ActionResult(
                success=True,
                route="ui",
                action=str(action.get("action") or "ui_click"),
                confidence=0.45,
                data=payload,
                retryable=False,
            )
        except Exception as exc:
            _raise_critical_exception(exc)
            return ActionResult(
                success=False,
                route="ui",
                action=str(action.get("action") or "ui_click"),
                confidence=0.1,
                failure_reason=str(exc),
                retryable=False,
                data=_error_data(exc),
            )

        payload = metadata if isinstance(metadata, dict) else {}
        verified, confidence = await self._verify_action(action, normalized, payload)
        return ActionResult(
            success=verified,
            route="ui",
            action=str(action.get("action") or "ui_click"),
            confidence=confidence,
            data=payload,
            failure_reason=payload.get("execution_error")
            or (None if verified else "UI action outcome was not verifiable."),
            retryable=not verified,
        )

    async def _execute(self, action: dict[str, Any]) -> dict[str, Any] | None:
        def _runner():
            return execute_action(action)

        return await anyio.to_thread.run_sync(_runner)

    def _normalize_action(self, action: dict[str, Any]) -> dict[str, Any]:
        action_name = action.get("action")
        if action_name != "ui_click":
            return dict(action)

        normalized: dict[str, Any] = {
            "reasoning": action.get("reasoning") or "Use UI fallback automation.",
            "task_complete": bool(action.get("task_complete", False)),
        }
        grid_cell = str(action.get("grid_cell") or "").strip()
        if grid_cell:
            normalized["grid_cell"] = grid_cell
            for key in _GRID_CELL_EXCLUSIVE_KEYS:
                normalized.pop(key, None)

        semantic_target = action.get("target_text") or action.get("text") or action.get("name")
        if (
            not grid_cell
            and (
                semantic_target
                or action.get("automation_id")
                or action.get("element_id") is not None
            )
        ):
            normalized["action"] = "uia_click"
            if semantic_target:
                normalized["target_text"] = semantic_target
            if action.get("automation_id"):
                normalized["automation_id"] = action["automation_id"]
            if action.get("control_type"):
                normalized["control_type"] = action["control_type"]
            if action.get("element_id") is not None:
                normalized["element_id"] = int(action["element_id"])
            return normalized

        button = str(action.get("button") or "left")
        normalized["action"] = {
            "double": "double_click",
            "right": "right_click",
        }.get(button, "click")

        # Priority: grid cell reference > raw x/y coordinates
        if grid_cell and action.get("screen_size"):
            try:
                sw, sh = action["screen_size"]
                cx, cy = grid_cell_to_pixel(grid_cell, screen_width=sw, screen_height=sh)
                normalized["x"] = cx
                normalized["y"] = cy
                normalized["_grid_resolved"] = grid_cell
                normalized.pop("grid_cell", None)
            except (ValueError, TypeError):
                pass

        if not grid_cell and "x" not in normalized and action.get("x") is not None:
            normalized["x"] = int(action["x"])
        if not grid_cell and "y" not in normalized and action.get("y") is not None:
            normalized["y"] = int(action["y"])
        return normalized

    async def _verify_action(
        self,
        original_action: dict[str, Any],
        normalized_action: dict[str, Any],
        payload: dict[str, Any],
    ) -> tuple[bool, float]:
        if payload.get("execution_confirmed") is True and normalized_action.get("action") == "uia_click":
            before_title = str(original_action.get("active_window_title") or "").strip().lower()
            after_window = await anyio.to_thread.run_sync(get_active_window_info)
            after_title = str(after_window.get("title") or "").strip().lower()
            element_id = payload.get("element_id") or normalized_action.get("element_id")
            if element_id is not None:
                control = await anyio.to_thread.run_sync(
                    lambda: resolve_active_window_control(element_id=int(element_id))
                )
                if control is not None:
                    return True, 0.7
            if before_title and after_title and before_title != after_title:
                return True, 0.75
            return True, 0.6

        action_name = str(normalized_action.get("action") or "")
        
        if payload.get("execution_confirmed") is True:
            if action_name in {"uia_get_visible_elements", "uia_click_fallback_search"}:
                return True, 0.85
            return True, 0.4

        app_name = str(normalized_action.get("app_name") or "").strip()

        if action_name in {"open_app", "focus_app"} and app_name:
            # Deterministic desktop launches do not always return immediate metadata,
            # so verify them by checking the real window state after the launch/focus.
            verified = await anyio.to_thread.run_sync(
                lambda: focus_app_window(app_name, timeout=config.APP_LAUNCH_DELAY)
                or app_window_exists(app_name)
            )
            return verified, 0.8 if verified else 0.2

        if action_name == "open_file" and (payload.get("file_path") or normalized_action.get("file_path")):
            if app_name:
                verified = await anyio.to_thread.run_sync(
                    lambda: focus_app_window(app_name, timeout=config.APP_LAUNCH_DELAY)
                    or app_window_exists(app_name)
                )
                return verified, 0.75 if verified else 0.2
            return True, 0.6

        if action_name in {
            "type",
            "press",
            "hotkey",
            "scroll",
            "click",
            "double_click",
            "right_click",
            "wait",
        }:
            # These input actions are ephemeral, but if dispatch completed without an
            # exception we should treat them as sent rather than falsely failing them.
            payload.setdefault("execution_confirmed", True)
            payload.setdefault("verification_source", "input_dispatch")
            return True, 0.55

        if original_action.get("action") == "ui_click" and action_name == "uia_click":
            return False, 0.2

        return False, 0.2

    def _coordinate_fallback_action(
        self,
        original_action: dict[str, Any],
        normalized_action: dict[str, Any],
    ) -> dict[str, Any] | None:
        if normalized_action.get("action") != "uia_click":
            return None
        # Raw coordinates are the final fallback only when the planner or router
        # explicitly supplied them. Do not silently downgrade semantic UIA actions
        # into coordinate guesses based on a stale control snapshot.
        if original_action.get("x") is None or original_action.get("y") is None:
            return None

        button = str(original_action.get("button") or "left").lower()
        fallback_action = {
            "action": {
                "double": "double_click",
                "right": "right_click",
            }.get(button, "click"),
            "x": int(original_action["x"]),
            "y": int(original_action["y"]),
            "reasoning": (
                f"{original_action.get('reasoning') or 'Use UI fallback automation.'} "
                "UI Automation could not activate the matched control, so fall back to the aligned control center."
            ).strip(),
            "task_complete": bool(original_action.get("task_complete", False)),
        }
        return fallback_action
