from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from oscar import server


def test_websocket_does_not_expose_internal_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_run(self, task, ui_callback=None):
        raise RuntimeError("api_key=secret-test-value")

    logged_errors: list[tuple[str, tuple[object, ...]]] = []

    def capture_error(message: str, *args: object) -> None:
        logged_errors.append((message, args))

    monkeypatch.setattr(server.LOGGER, "error", capture_error)
    monkeypatch.setattr(server.Orchestrator, "run", fail_run)
    client = TestClient(server.app)

    with client.websocket_connect("/ws/oscar") as websocket:
        websocket.receive_json()  # connection event
        websocket.send_json(
            {
                "type": "start_task",
                "prompt": "Test an internal failure",
            }
        )
        websocket.receive_json()  # task_accepted
        response = websocket.receive_json()

    assert response["type"] == "server_error"
    assert response["status"] == "error"
    assert response["error_id"]
    assert "secret-test-value" not in str(response)
    assert "api_key=" not in str(response)
    assert "error_type" not in response
    # Local diagnostics retain a redacted summary for debugging.
    assert logged_errors
    logged_message = " ".join(
        [logged_errors[0][0], *(str(value) for value in logged_errors[0][1])]
    )
    assert "error_id=" in logged_message
    assert "secret-test-value" not in logged_message
    assert "api_key=[REDACTED]" in logged_message


def test_health_endpoint_returns_ok() -> None:
    client = TestClient(server.app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
