"""FastAPI WebSocket server for the OSCAR desktop application."""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from oscar.orchestrator import Orchestrator
from oscar.diagnostics import sanitize_text
from oscar.utils.logging import configure_logging, get_logger


LOGGER = get_logger("server")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    yield


app = FastAPI(
    title="OSCAR Desktop Agent API",
    version="0.1.0",
    description="WebSocket bridge for streaming OSCAR autonomous agent state.",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


def _extract_task(message: dict[str, Any]) -> str:
    task = message.get("prompt") or message.get("task")
    return str(task or "").strip()


@app.websocket("/ws/oscar")
async def oscar_websocket(websocket: WebSocket) -> None:
    """Accept task requests and stream live orchestrator state to the client."""

    await websocket.accept()
    send_lock = asyncio.Lock()

    async def send_json(payload: dict[str, Any]) -> None:
        async with send_lock:
            await websocket.send_json(payload)

    await send_json(
        {
            "type": "connection",
            "status": "connected",
            "message": "OSCAR WebSocket ready.",
        }
    )

    while True:
        try:
            message = await websocket.receive_json()
        except WebSocketDisconnect:
            LOGGER.info("OSCAR WebSocket client disconnected.")
            return
        except json.JSONDecodeError:
            await send_json(
                {
                    "type": "server_error",
                    "status": "error",
                    "error": "Invalid JSON message.",
                }
            )
            continue

        if not isinstance(message, dict):
            await send_json(
                {
                    "type": "server_error",
                    "status": "error",
                    "error": "WebSocket messages must be JSON objects.",
                }
            )
            continue

        message_type = str(message.get("type") or "").strip()
        if message_type == "ping":
            await send_json({"type": "pong", "status": "connected"})
            continue

        if message_type != "start_task":
            await send_json(
                {
                    "type": "server_error",
                    "status": "error",
                    "error": "Expected a start_task message.",
                    "expected_shape": {
                        "type": "start_task",
                        "prompt": "Open Notepad and type hello",
                    },
                }
            )
            continue

        task = _extract_task(message)
        if not task:
            await send_json(
                {
                    "type": "server_error",
                    "status": "error",
                    "error": "start_task requires a non-empty prompt or task field.",
                }
            )
            continue

        await send_json(
            {
                "type": "task_accepted",
                "status": "running",
                "task": task,
            }
        )

        async def send_to_websocket(event: dict[str, Any]) -> None:
            await send_json(event)

        try:
            outcome = await Orchestrator().run(task, ui_callback=send_to_websocket)
        except WebSocketDisconnect:
            LOGGER.info("OSCAR WebSocket disconnected while task was running.")
            return
        except asyncio.CancelledError:
            await send_json(
                {
                    "type": "server_cancelled",
                    "status": "cancelled",
                    "task": task,
                }
            )
            raise
        except Exception as exc:
            error_id = uuid.uuid4().hex[:12]
            # Keep raw exception messages and tracebacks out of the client-facing
            # event and ordinary logs; provider exceptions may contain secrets.
            LOGGER.error(
                "OSCAR task failed (error_id=%s, error_type=%s, detail=%s)",
                error_id,
                type(exc).__name__,
                sanitize_text(str(exc)) or "(no details)",
            )
            await send_json(
                {
                    "type": "server_error",
                    "status": "error",
                    "task": task,
                    "error": (
                        "Task failed unexpectedly. "
                        "Check local OSCAR logs using the error ID."
                    ),
                    "error_id": error_id,
                }
            )
            continue

        await send_json(
            {
                "type": "server_outcome",
                "status": outcome.status,
                "task": task,
                "final_message": outcome.final_message,
                "log_path": str(outcome.log_path),
                "trace_path": str(outcome.trace_path),
            }
        )
