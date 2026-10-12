from __future__ import annotations

import json
from datetime import datetime, timezone

from oscar.run_logger import write_run_log


def test_write_run_log_creates_directory_and_writes_json(tmp_path) -> None:
    started_at = datetime(2026, 3, 12, 10, 0, 0, tzinfo=timezone.utc)
    finished_at = datetime(2026, 3, 12, 10, 0, 5, tzinfo=timezone.utc)

    log_path = write_run_log(
        task="Open Notepad",
        history=[
            {
                "action": "click",
                "x": 10,
                "y": 10,
                "reasoning": "Open Start.",
                "task_complete": False,
            }
        ],
        started_at=started_at,
        finished_at=finished_at,
        status="completed",
        model_name="gemini-1.5-flash",
        max_steps=20,
        action_delay=0.5,
        logs_dir=tmp_path / "logs",
    )

    payload = json.loads(log_path.read_text(encoding="utf-8"))
    assert log_path.parent.name == "logs"
    assert payload["task"] == "Open Notepad"
    assert payload["status"] == "completed"
    assert payload["steps_taken"] == 1
    assert payload["error"] is None


def test_write_run_log_persists_errors(tmp_path) -> None:
    log_path = write_run_log(
        task="Bad task",
        history=[],
        started_at="2026-03-12T10:00:00+00:00",
        finished_at="2026-03-12T10:00:01+00:00",
        status="failed",
        error="boom",
        logs_dir=tmp_path / "logs",
    )

    payload = json.loads(log_path.read_text(encoding="utf-8"))
    assert payload["error"] == "boom"


def test_write_run_log_redacts_credentials_recursively(tmp_path) -> None:
    log_path = write_run_log(
        task="Request with api_key=super-secret-value",
        history=[
            {
                "action": "request",
                "headers": {"Authorization": "Bearer abc.def.ghi"},
                "note": "Google key AIza12345678901234567890123456789012",
            }
        ],
        started_at="2026-03-12T10:00:00+00:00",
        finished_at="2026-03-12T10:00:01+00:00",
        status="failed",
        error="provider returned api_key=other-secret",
        logs_dir=tmp_path / "logs",
    )

    serialized = log_path.read_text(encoding="utf-8")
    payload = json.loads(serialized)
    assert "super-secret-value" not in serialized
    assert "abc.def.ghi" not in serialized
    assert "AIza12345678901234567890123456789012" not in serialized
    assert "other-secret" not in serialized
    assert payload["history"][0]["headers"]["Authorization"] == "[REDACTED]"


def test_write_run_log_bounds_long_diagnostic_strings(tmp_path) -> None:
    log_path = write_run_log(
        task="x" * 9000,
        history=[],
        started_at="start",
        finished_at="finish",
        status="failed",
        logs_dir=tmp_path / "logs",
    )
    payload = json.loads(log_path.read_text(encoding="utf-8"))
    assert len(payload["task"]) < 8100
    assert payload["task"].endswith("…[truncated]")
