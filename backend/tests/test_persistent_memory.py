from __future__ import annotations

import json
from pathlib import Path

from oscar.core.persistent_memory import PersistentMemoryStore
from oscar.runtime import ActionResult


def test_persistent_memory_round_trips_recent_state() -> None:
    store_path = Path("workspace_session_memory.json")
    captured: dict[str, str] = {}

    def fake_write_text(self: Path, data: str, encoding: str = "utf-8") -> int:
        captured[str(self)] = data
        return len(data)

    def fake_read_text(self: Path, encoding: str = "utf-8") -> str:
        return captured[str(self)]

    def fake_exists(self: Path) -> bool:
        return str(self) in captured

    original_write_text = Path.write_text
    original_read_text = Path.read_text
    original_exists = Path.exists
    original_mkdir = Path.mkdir
    try:
        Path.write_text = fake_write_text  # type: ignore[method-assign]
        Path.read_text = fake_read_text  # type: ignore[method-assign]
        Path.exists = fake_exists  # type: ignore[method-assign]
        Path.mkdir = lambda self, parents=False, exist_ok=False: None  # type: ignore[method-assign]

        store = PersistentMemoryStore(path=store_path)
        store.record(
            {
                "action": "open_app",
                "app_name": "chrome",
                "working_directory": "A:\\workspace",
            },
            ActionResult(
                success=True,
                route="browser",
                action="browser_open",
                data={"created_paths": ["A:\\workspace\\notes.txt"]},
            ),
        )
        store.save()

        loaded = PersistentMemoryStore.load(store_path)
    finally:
        Path.write_text = original_write_text  # type: ignore[method-assign]
        Path.read_text = original_read_text  # type: ignore[method-assign]
        Path.exists = original_exists  # type: ignore[method-assign]
        Path.mkdir = original_mkdir  # type: ignore[method-assign]

    assert json.loads(captured[str(store_path)])["recent_apps"] == ["chrome"]
    assert loaded.recent_apps == ["chrome"]
    assert "A:\\workspace" in loaded.recent_paths
    assert "A:\\workspace\\notes.txt" in loaded.recent_paths
    assert loaded.recent_actions[-1] == {
        "action": "open_app",
        "route": "browser",
        "success": True,
    }


def test_persistent_memory_dedupes_latest_paths() -> None:
    store = PersistentMemoryStore(path=Path("session_memory.json"))

    for _ in range(3):
        store.record(
            {"action": "terminal_command", "file_path": "A:\\workspace\\alpha.txt"},
            ActionResult(success=True, route="terminal", action="terminal_command"),
        )

    assert store.recent_paths == ["A:\\workspace\\alpha.txt"]
