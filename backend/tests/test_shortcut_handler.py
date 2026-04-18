from __future__ import annotations

from pathlib import Path

import pytest

from oscar.agents.shortcut_handler import ShortcutHandler


class FakeImage:
    def __init__(self, *, write_file: bool = True) -> None:
        self.write_file = write_file

    def save(self, path) -> None:
        if not self.write_file:
            return
        Path(path).write_bytes(b"fake-png")


class FakePyAutoGUI:
    def __init__(self, *, write_file: bool = True) -> None:
        self.write_file = write_file
        self.hotkeys: list[tuple[str, ...]] = []

    def hotkey(self, *keys: str) -> None:
        self.hotkeys.append(tuple(keys))

    def screenshot(self) -> FakeImage:
        return FakeImage(write_file=self.write_file)

    def typewrite(self, text: str) -> None:
        self.typed = text

    def press(self, key: str) -> None:
        self.pressed = key


@pytest.mark.anyio
async def test_shortcut_handler_takes_verifiable_screenshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    handler = ShortcutHandler()
    monkeypatch.setattr(handler, "_get_pyautogui", lambda: FakePyAutoGUI())
    monkeypatch.setattr(
        "oscar.agents.shortcut_handler.get_known_user_paths",
        lambda: {"pictures": tmp_path / "Pictures"},
    )

    result = await handler.run(
        {"action": "shortcut", "shortcut_name": "os.take_screenshot"}
    )

    assert result.success is True
    assert result.data["shortcut_name"] == "os.take_screenshot"
    assert Path(result.data["file_path"]).exists()
    assert result.data["verified"] is True


@pytest.mark.anyio
async def test_shortcut_handler_fails_when_screenshot_file_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    handler = ShortcutHandler()
    monkeypatch.setattr(
        handler,
        "_get_pyautogui",
        lambda: FakePyAutoGUI(write_file=False),
    )
    monkeypatch.setattr(
        "oscar.agents.shortcut_handler.get_known_user_paths",
        lambda: {"pictures": tmp_path / "Pictures"},
    )

    result = await handler.run(
        {"action": "shortcut", "shortcut_name": "os.take_screenshot"}
    )

    assert result.success is False
    assert result.failure_reason == "Screenshot file was not created."
