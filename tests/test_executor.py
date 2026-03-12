from __future__ import annotations

import subprocess

import pytest

from oscar import executor
from oscar.executor import ActionValidationError, execute_action, validate_action


def test_validate_action_rejects_out_of_bounds_coordinates() -> None:
    with pytest.raises(ActionValidationError, match="outside the current screen bounds"):
        validate_action(
            {
                "action": "click",
                "x": 200,
                "y": 10,
                "reasoning": "Click the target.",
                "task_complete": False,
            },
            screen_size=(100, 100),
        )


def test_validate_action_rejects_task_complete_without_done() -> None:
    with pytest.raises(ActionValidationError, match="task_complete"):
        validate_action(
            {
                "action": "click",
                "x": 20,
                "y": 10,
                "reasoning": "Click the target.",
                "task_complete": True,
            },
            screen_size=(100, 100),
        )


def test_validate_action_rejects_invalid_scroll_direction() -> None:
    with pytest.raises(ActionValidationError, match="Scroll direction"):
        validate_action(
            {
                "action": "scroll",
                "x": 20,
                "y": 10,
                "direction": "left",
                "amount": 2,
                "reasoning": "Scroll a bit.",
                "task_complete": False,
            },
            screen_size=(100, 100),
        )


def test_validate_action_normalizes_hotkey_aliases() -> None:
    action = validate_action(
        {
            "action": "hotkey",
            "keys": ["win", "r"],
            "reasoning": "Open the Run dialog.",
            "task_complete": False,
        }
    )

    assert action["keys"] == ["winleft", "r"]


def test_validate_action_normalizes_press_key_alias() -> None:
    action = validate_action(
        {
            "action": "press",
            "key": "Return",
            "reasoning": "Confirm the focused result.",
            "task_complete": False,
        }
    )

    assert action["key"] == "enter"


def test_validate_action_coerces_string_task_complete() -> None:
    action = validate_action(
        {
            "action": "wait",
            "seconds": 0.5,
            "reasoning": "Pause briefly.",
            "task_complete": "false",
        }
    )

    assert action["task_complete"] is False


def test_validate_action_accepts_open_app_with_profile() -> None:
    action = validate_action(
        {
            "action": "open_app",
            "app_name": "Google Chrome",
            "profile_name": "Andrew",
            "reasoning": "Launch Chrome with a named profile.",
            "task_complete": False,
        }
    )

    assert action["app_name"] == "google chrome"
    assert action["profile_name"] == "Andrew"


def test_validate_action_accepts_save_file() -> None:
    action = validate_action(
        {
            "action": "save_file",
            "file_path": r"C:\Users\andre\Downloads\oscar_note.txt",
            "reasoning": "Save the file directly to Downloads.",
            "task_complete": False,
        }
    )

    assert action["file_path"].endswith("oscar_note.txt")


class FakePyAutoGUI:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def click(self, *, x: int, y: int) -> None:
        self.calls.append(("click", x, y))

    def doubleClick(self, *, x: int, y: int) -> None:
        self.calls.append(("doubleClick", x, y))

    def rightClick(self, *, x: int, y: int) -> None:
        self.calls.append(("rightClick", x, y))

    def typewrite(self, text: str, *, interval: float) -> None:
        self.calls.append(("typewrite", text, interval))

    def hotkey(self, *keys: str) -> None:
        self.calls.append(("hotkey",) + keys)

    def press(self, key: str) -> None:
        self.calls.append(("press", key))

    def scroll(self, clicks: int, *, x: int, y: int) -> None:
        self.calls.append(("scroll", clicks, x, y))


def test_execute_action_dispatches_pyautogui_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_pyautogui = FakePyAutoGUI()
    monkeypatch.setattr(executor, "_get_pyautogui", lambda: fake_pyautogui)
    monkeypatch.setattr(executor.config, "TYPEWRITE_INTERVAL", 0.08)

    execute_action(
        {
            "action": "double_click",
            "x": 10,
            "y": 20,
            "reasoning": "Open the file.",
            "task_complete": False,
        }
    )
    execute_action(
        {
            "action": "type",
            "text": "Hello",
            "reasoning": "Enter text.",
            "task_complete": False,
        }
    )
    execute_action(
        {
            "action": "hotkey",
            "keys": ["ctrl", "s"],
            "reasoning": "Save the file.",
            "task_complete": False,
        }
    )
    execute_action(
        {
            "action": "press",
            "key": "enter",
            "reasoning": "Confirm the focused result.",
            "task_complete": False,
        }
    )
    execute_action(
        {
            "action": "scroll",
            "x": 10,
            "y": 20,
            "direction": "down",
            "amount": 3,
            "reasoning": "Move down.",
            "task_complete": False,
        }
    )

    assert fake_pyautogui.calls == [
        ("doubleClick", 10, 20),
        ("typewrite", "Hello", 0.08),
        ("hotkey", "ctrl", "s"),
        ("press", "enter"),
        ("scroll", -3, 10, 20),
    ]


def test_execute_action_open_app_uses_launch_command(monkeypatch: pytest.MonkeyPatch) -> None:
    popen_calls: list[tuple[list[str], object, object]] = []

    def fake_popen(args, stdout=None, stderr=None):
        popen_calls.append((args, stdout, stderr))
        return object()

    monkeypatch.setattr(
        executor,
        "build_launch_command",
        lambda app_name, profile_name=None, url=None: ([r"C:\Program Files\Google\Chrome\Application\chrome.exe", "--profile-directory=Default"], object()),
    )
    monkeypatch.setattr(executor.subprocess, "Popen", fake_popen)

    execute_action(
        {
            "action": "open_app",
            "app_name": "chrome",
            "profile_name": "Andrew",
            "reasoning": "Launch Chrome directly.",
            "task_complete": False,
        }
    )

    assert popen_calls == [
        (
            [r"C:\Program Files\Google\Chrome\Application\chrome.exe", "--profile-directory=Default"],
            subprocess.DEVNULL,
            subprocess.DEVNULL,
        )
    ]


def test_execute_action_save_file_uses_save_shortcut(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_pyautogui = FakePyAutoGUI()
    sleep_calls: list[float] = []
    monkeypatch.setattr(executor, "_get_pyautogui", lambda: fake_pyautogui)
    monkeypatch.setattr(executor.time, "sleep", lambda seconds: sleep_calls.append(seconds))
    monkeypatch.setattr(executor.config, "SAVE_DIALOG_DELAY", 0.75)
    monkeypatch.setattr(executor.config, "ACTION_DELAY", 0.25)
    monkeypatch.setattr(executor.config, "TYPEWRITE_INTERVAL", 0.08)

    execute_action(
        {
            "action": "save_file",
            "file_path": r"C:\Users\andre\Downloads\oscar_note.txt",
            "reasoning": "Save the file to Downloads.",
            "task_complete": False,
        }
    )

    assert fake_pyautogui.calls == [
        ("hotkey", "ctrl", "s"),
        ("hotkey", "ctrl", "a"),
        ("typewrite", r"C:\Users\andre\Downloads\oscar_note.txt", 0.08),
        ("press", "enter"),
    ]
    assert sleep_calls == [0.75, 0.25, 0.25]


def test_execute_action_wait_uses_time_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(executor.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    execute_action(
        {
            "action": "wait",
            "seconds": 1.5,
            "reasoning": "Wait for loading.",
            "task_complete": False,
        }
    )

    assert sleep_calls == [1.5]
