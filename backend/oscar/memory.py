"""Persistent in-memory record of task attempts and outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


COORDINATE_BUCKET_SIZE = 20


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _bucket_coordinate(value: Any, *, bucket_size: int = COORDINATE_BUCKET_SIZE) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ""
    bucket = int(round(float(value) / float(bucket_size)) * bucket_size)
    return str(bucket)


def build_action_fingerprint(action: dict[str, Any], route: str) -> str:
    """Return a stable fingerprint for repeated-failure suppression.

    Intentionally ignore free-form reasoning text. Runtime retries only work if the
    same action maps to the same fingerprint across planning iterations.
    """

    action_name = _normalize_text(action.get("action"))
    if action_name == "terminal_command":
        return f"terminal|{_normalize_text(action.get('command'))}"
    if action_name.startswith("browser"):
        if action_name == "browser_type":
            identifier = (
                f"{_normalize_text(action.get('target_text'))}|"
                f"{_normalize_text(action.get('text'))}"
            )
        else:
            identifier = _normalize_text(
                action.get("url")
                or action.get("target_text")
                or action.get("text")
                or action.get("query")
            )
        return f"browser|{action_name}|{identifier}"
    if action_name == "shortcut":
        return f"shortcut|{_normalize_text(action.get('shortcut_name'))}"
    if action_name == "wait_until":
        identifier = _normalize_text(action.get("timestamp") or action.get("time_of_day"))
        return f"system|wait_until|{identifier}"
    if action_name in {"ui_click", "click", "double_click", "right_click"}:
        if action.get("element_id") is not None:
            return f"ui|{action_name}|id:{action.get('element_id')}"
        target = action.get("target_text") or action.get("text")
        if target:
            return f"ui|{action_name}|{_normalize_text(target)}"
        x_bucket = _bucket_coordinate(action.get("x"))
        y_bucket = _bucket_coordinate(action.get("y"))
        return f"ui|{action_name}|x:{x_bucket}|y:{y_bucket}"
    if action_name == "scroll":
        x_bucket = _bucket_coordinate(action.get("x"))
        y_bucket = _bucket_coordinate(action.get("y"))
        direction = _normalize_text(action.get("direction"))
        amount = _normalize_text(action.get("amount"))
        return (
            f"ui|scroll|direction:{direction}|amount:{amount}|"
            f"x:{x_bucket}|y:{y_bucket}"
        )
    return f"{route}|{action_name}"


def action_family_for(action: dict[str, Any]) -> str:
    """Collapse actions into broad families for retry heuristics."""

    action_name = _normalize_text(action.get("action"))
    if action_name.startswith("browser_"):
        return "browser"
    if action_name in {
        "ui_click",
        "click",
        "double_click",
        "right_click",
        "uia_click",
        "type",
        "press",
        "hotkey",
        "scroll",
        "open_app",
        "focus_app",
        "close_app",
        "close_tab",
        "open_file",
        "save_file",
        "new_document",
    }:
        return "ui"
    if action_name.startswith("ui_"):
        return "ui"
    if action_name == "shortcut":
        return "shortcut"
    if action_name == "terminal_command":
        return "terminal"
    return action_name or "unknown"


@dataclass
class StepRecord:
    """One routed execution attempt."""

    action: dict[str, Any]
    route: str
    result: dict[str, Any]
    timestamp: str
    success: bool
    failure_reason: str | None = None
    retry_count: int = 0
    fallback_from: str | None = None
    fingerprint: str | None = None
    action_family: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "route": self.route,
            "result": self.result,
            "timestamp": self.timestamp,
            "success": self.success,
            "failure_reason": self.failure_reason,
            "retry_count": self.retry_count,
            "fallback_from": self.fallback_from,
            "fingerprint": self.fingerprint,
            "action_family": self.action_family,
        }


class TaskMemory:
    """Store recent attempts so the planner and router can avoid dead ends."""

    def __init__(self) -> None:
        self._steps: list[StepRecord] = []

    @property
    def steps(self) -> list[StepRecord]:
        return list(self._steps)

    def record_step(
        self,
        action: dict[str, Any],
        route: str,
        result: dict[str, Any] | Any,
        *,
        success: bool,
        failure_reason: str | None = None,
        retry_count: int = 0,
        fallback_from: str | None = None,
    ) -> StepRecord:
        result_payload = (
            result.to_dict() if hasattr(result, "to_dict") else dict(result or {})
        )
        fingerprint = build_action_fingerprint(action, route)
        step = StepRecord(
            action=dict(action),
            route=route,
            result=result_payload,
            timestamp=datetime.now(timezone.utc).isoformat(),
            success=success,
            failure_reason=failure_reason,
            retry_count=retry_count,
            fallback_from=fallback_from,
            fingerprint=fingerprint,
            action_family=action_family_for(action),
        )
        self._steps.append(step)
        return step

    def get_recent_steps(self, n: int = 5) -> list[dict[str, Any]]:
        return [step.to_dict() for step in self._steps[-max(int(n), 0) :]]

    def get_failures(self) -> list[dict[str, Any]]:
        return [step.to_dict() for step in self._steps if not step.success]

    def get_successes(self) -> list[dict[str, Any]]:
        return [step.to_dict() for step in self._steps if step.success]

    def was_recent_failure(self, fingerprint: str) -> bool:
        return bool(
            self._steps
            and self._steps[-1].fingerprint == fingerprint
            and not self._steps[-1].success
        )

    def has_failed_fingerprint(self, fingerprint: str) -> bool:
        return any(
            step.fingerprint == fingerprint and not step.success for step in self._steps
        )

    def consecutive_failures_for_fingerprint(self, fingerprint: str) -> int:
        count = 0
        for step in reversed(self._steps):
            if step.fingerprint != fingerprint:
                break
            if step.success:
                break
            count += 1
        return count

    def last_success_for(self, route: str) -> dict[str, Any] | None:
        for step in reversed(self._steps):
            if step.route == route and step.success:
                return step.to_dict()
        return None

    def consecutive_failures_for(self, action_family: str) -> int:
        count = 0
        for step in reversed(self._steps):
            action_name = _normalize_text(step.action.get("action"))
            if step.action_family != action_family and action_name != _normalize_text(action_family):
                break
            if step.success:
                break
            count += 1
        return count
