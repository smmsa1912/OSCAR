from __future__ import annotations

import json

from oscar.trace import ExecutionTrace


def test_execution_trace_logs_and_writes_json(tmp_path) -> None:
    trace = ExecutionTrace(task="open settings")
    trace.log_step(
        action={"action": "shortcut", "shortcut_name": "os.open_settings"},
        route="shortcut",
        success=True,
        duration_ms=12,
        retry_index=0,
        context_snapshot={"active_window_title": "Desktop"},
    )

    path = trace.write_json(logs_dir=tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["task"] == "open settings"
    assert payload["steps"][0]["route"] == "shortcut"
