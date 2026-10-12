"""Run logging for OSCAR executions."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from oscar import config
from oscar.diagnostics import sanitize_for_log


def _serialize_timestamp(value: datetime | str) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return value


def build_run_payload(
    *,
    task: str,
    history: list[dict[str, Any]],
    started_at: datetime | str,
    finished_at: datetime | str,
    status: str,
    error: str | None = None,
    model_name: str | None = None,
    max_steps: int | None = None,
    action_delay: float | None = None,
    trace_path: str | None = None,
    memory: list[dict[str, Any]] | None = None,
    known_paths: dict[str, str] | None = None,
    cursor_position: tuple[int, int] | None = None,
    model_budget: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Build a serializable run log payload."""

    return sanitize_for_log({
        "task": task,
        "started_at": _serialize_timestamp(started_at),
        "finished_at": _serialize_timestamp(finished_at),
        "status": status,
        "model": model_name or config.GEMINI_MODEL,
        "max_steps": max_steps if max_steps is not None else config.MAX_STEPS,
        "action_delay": (
            action_delay if action_delay is not None else config.ACTION_DELAY
        ),
        "steps_taken": len(history),
        "history": history,
        "error": error,
        "trace_path": trace_path,
        "memory": memory or [],
        "known_paths": known_paths or {},
        "cursor_position": cursor_position,
        "model_budget": model_budget,
    })


def write_run_log(
    *,
    task: str,
    history: list[dict[str, Any]],
    started_at: datetime | str,
    finished_at: datetime | str,
    status: str,
    error: str | None = None,
    model_name: str | None = None,
    max_steps: int | None = None,
    action_delay: float | None = None,
    trace_path: str | None = None,
    memory: list[dict[str, Any]] | None = None,
    known_paths: dict[str, str] | None = None,
    cursor_position: tuple[int, int] | None = None,
    model_budget: dict[str, int] | None = None,
    logs_dir: str | Path | None = None,
) -> Path:
    """Persist a sanitized run log as JSON and return the path.

    Common credential formats are redacted by ``build_run_payload`` before
    serialization. Callers should still avoid placing secrets in task text.
    """

    target_dir = Path(logs_dir) if logs_dir is not None else config.LOGS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    payload = build_run_payload(
        task=task,
        history=history,
        started_at=started_at,
        finished_at=finished_at,
        status=status,
        error=error,
        model_name=model_name,
        max_steps=max_steps,
        action_delay=action_delay,
        trace_path=trace_path,
        memory=memory,
        known_paths=known_paths,
        cursor_position=cursor_position,
        model_budget=model_budget,
    )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    log_path = target_dir / f"{timestamp}_run.json"
    suffix = 1
    while log_path.exists():
        log_path = target_dir / f"{timestamp}_run_{suffix}.json"
        suffix += 1

    log_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return log_path
