"""Structured execution trace persisted for each run."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from oscar import config


@dataclass
class TraceStep:
    """A single structured attempt in the execution trace."""

    step_index: int
    action: dict[str, Any]
    route: str
    success: bool
    duration_ms: int
    retry_index: int
    failure_reason: str | None = None
    fallback_used: str | None = None
    context_snapshot: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_index": self.step_index,
            "action": self.action,
            "route": self.route,
            "success": self.success,
            "duration_ms": self.duration_ms,
            "retry_index": self.retry_index,
            "failure_reason": self.failure_reason,
            "fallback_used": self.fallback_used,
            "context_snapshot": self.context_snapshot,
        }


class ExecutionTrace:
    """Append-only run trace used for debugging routing and retries."""

    def __init__(self, *, task: str) -> None:
        self.task = task
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.steps: list[TraceStep] = []

    def log_step(
        self,
        *,
        action: dict[str, Any],
        route: str,
        success: bool,
        duration_ms: int,
        retry_index: int,
        failure_reason: str | None = None,
        fallback_used: str | None = None,
        context_snapshot: dict[str, Any] | None = None,
    ) -> TraceStep:
        step = TraceStep(
            step_index=len(self.steps) + 1,
            action=dict(action),
            route=route,
            success=success,
            duration_ms=duration_ms,
            retry_index=retry_index,
            failure_reason=failure_reason,
            fallback_used=fallback_used,
            context_snapshot=context_snapshot,
        )
        self.steps.append(step)
        return step

    def build_payload(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "started_at": self.started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "steps": [step.to_dict() for step in self.steps],
        }

    def write_json(self, *, logs_dir: str | Path | None = None) -> Path:
        target_dir = Path(logs_dir) if logs_dir is not None else config.LOGS_DIR
        target_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        trace_path = target_dir / f"{timestamp}_trace.json"
        suffix = 1
        while trace_path.exists():
            trace_path = target_dir / f"{timestamp}_trace_{suffix}.json"
            suffix += 1
        trace_path.write_text(
            json.dumps(self.build_payload(), indent=2),
            encoding="utf-8",
        )
        return trace_path
