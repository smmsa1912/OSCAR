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


def test_execution_trace_redacts_credentials_in_actions_and_context() -> None:
    trace = ExecutionTrace(task="send api_key=do-not-log")
    trace.log_step(
        action={"action": "request", "api_key": "raw-secret", "detail": "Bearer top.secret.token"},
        route="test",
        success=False,
        duration_ms=1,
        retry_index=0,
        context_snapshot={"password": "also-secret"},
    )

    serialized = json.dumps(trace.build_payload())
    assert "do-not-log" not in serialized
    assert "raw-secret" not in serialized
    assert "top.secret.token" not in serialized
    assert "also-secret" not in serialized



def test_execution_trace_redacts_credentials_from_failure_and_context(tmp_path) -> None:
    trace = ExecutionTrace(task="provider failure api_key=secret-value")
    trace.log_step(
        action={"action": "request", "token": "secret-token"},
        route="browser",
        success=False,
        duration_ms=20,
        retry_index=2,
        failure_reason="Authorization: Bearer abc.def.ghi",
        context_snapshot={"note": "password=hunter2"},
    )

    path = trace.write_json(logs_dir=tmp_path)
    serialized = path.read_text(encoding="utf-8")

    assert "secret-value" not in serialized
    assert "secret-token" not in serialized
    assert "abc.def.ghi" not in serialized
    assert "hunter2" not in serialized
    payload = json.loads(serialized)
    assert payload["steps"][0]["success"] is False
    assert payload["steps"][0]["retry_index"] == 2
