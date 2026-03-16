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


def test_validate_action_coerces_task_complete_for_non_done_actions() -> None:
    action = validate_action(
        {
            "action": "click",
            "x": 20,
            "y": 10,
            "reasoning": "Click the target.",
            "task_complete": True,
        },
        screen_size=(100, 100),
    )

    assert action["task_complete"] is False


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


def test_validate_action_accepts_open_app_with_profile_and_new_instance() -> None:
    action = validate_action(
        {
            "action": "open_app",
            "app_name": "Google Chrome",
            "profile_name": "Andrew",
            "new_instance": True,
            "reasoning": "Launch Chrome with a named profile.",
            "task_complete": False,
        }
    )

    assert action["app_name"] == "google chrome"
    assert action["profile_name"] == "Andrew"
    assert action["new_instance"] is True


def test_validate_action_accepts_close_app() -> None:
    action = validate_action(
        {
            "action": "close_app",
            "app_name": "Notepad",
            "reasoning": "Close Notepad reliably.",
            "task_complete": False,
        }
    )

    assert action["app_name"] == "notepad"


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

    monkeypatch.setattr(executor, "app_window_exists", lambda _app_name: False)
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


def test_execute_action_open_app_launches_when_existing_focus_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    popen_calls: list[list[str]] = []

    def fake_popen(args, stdout=None, stderr=None):
        popen_calls.append(args)
        return object()

    monkeypatch.setattr(executor, "app_window_exists", lambda _app_name: True)
    monkeypatch.setattr(executor, "focus_app_window", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(executor.config, "WINDOW_FOCUS_TIMEOUT", 0.0)
    monkeypatch.setattr(
        executor,
        "build_launch_command",
        lambda app_name, profile_name=None, url=None: (["notepad.exe"], object()),
    )
    monkeypatch.setattr(executor.subprocess, "Popen", fake_popen)

    execute_action(
        {
            "action": "open_app",
            "app_name": "notepad",
            "reasoning": "Open a new notepad window.",
            "task_complete": False,
        }
    )

    assert popen_calls == [["notepad.exe"]]


def test_execute_action_open_app_focuses_existing_window(monkeypatch: pytest.MonkeyPatch) -> None:
    focus_calls: list[str] = []
    monkeypatch.setattr(executor, "app_window_exists", lambda _app_name: True)
    monkeypatch.setattr(executor, "focus_app_window", lambda app_name, timeout: focus_calls.append(app_name) or True)
    monkeypatch.setattr(executor.config, "WINDOW_FOCUS_TIMEOUT", 2.0)
    monkeypatch.setattr(executor.config, "FOCUS_SETTLE_DELAY", 0.0)
    monkeypatch.setattr(executor.time, "sleep", lambda _seconds: None)

    execute_action(
        {
            "action": "open_app",
            "app_name": "notepad",
            "reasoning": "Focus Notepad directly.",
            "task_complete": False,
        }
    )

    assert focus_calls == ["notepad"]


def test_execute_action_open_app_uses_shortcut_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_pyautogui = FakePyAutoGUI()
    popen_calls: list[list[str]] = []
    shortcut_spec = type("ShortcutSpec", (), {"shortcut_keys": ("winleft", "i")})()

    monkeypatch.setattr(executor, "_get_pyautogui", lambda: fake_pyautogui)
    monkeypatch.setattr(executor, "app_window_exists", lambda _app_name: False)
    monkeypatch.setattr(
        executor,
        "build_launch_command",
        lambda app_name, profile_name=None, url=None: (["cmd.exe", "/c", "start", "", "ms-settings:"], shortcut_spec),
    )
    monkeypatch.setattr(executor.subprocess, "Popen", lambda args, stdout=None, stderr=None: popen_calls.append(args))

    execute_action(
        {
            "action": "open_app",
            "app_name": "settings",
            "reasoning": "Open Settings with its Windows shortcut.",
            "task_complete": False,
        }
    )

    assert fake_pyautogui.calls == [("hotkey", "winleft", "i")]
    assert popen_calls == []


def test_execute_action_close_app_uses_alt_f4(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_pyautogui = FakePyAutoGUI()
    monkeypatch.setattr(executor, "_get_pyautogui", lambda: fake_pyautogui)
    monkeypatch.setattr(executor, "app_window_exists", lambda _app_name: True)
    monkeypatch.setattr(executor, "focus_app_window", lambda app_name, timeout: True)
    monkeypatch.setattr(executor.config, "WINDOW_FOCUS_TIMEOUT", 2.0)
    monkeypatch.setattr(executor.config, "FOCUS_SETTLE_DELAY", 0.0)
    monkeypatch.setattr(executor.time, "sleep", lambda _seconds: None)

    execute_action(
        {
            "action": "close_app",
            "app_name": "notepad",
            "reasoning": "Close Notepad directly.",
            "task_complete": False,
        }
    )

    assert fake_pyautogui.calls == [("hotkey", "alt", "f4")]


def test_execute_action_save_file_uses_save_shortcut_and_creates_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    fake_pyautogui = FakePyAutoGUI()
    sleep_calls: list[float] = []
    target_dir = tmp_path / "Andrew Folder"
    target_file = target_dir / "Hello World.txt"

    monkeypatch.setattr(executor, "_get_pyautogui", lambda: fake_pyautogui)
    monkeypatch.setattr(executor.time, "sleep", lambda seconds: sleep_calls.append(seconds))
    monkeypatch.setattr(executor.config, "SAVE_DIALOG_DELAY", 0.75)
    monkeypatch.setattr(executor.config, "ACTION_DELAY", 0.25)
    monkeypatch.setattr(executor.config, "TYPEWRITE_INTERVAL", 0.08)

    execute_action(
        {
            "action": "save_file",
            "file_path": str(target_file),
            "reasoning": "Save the file to a custom directory.",
            "task_complete": False,
        }
    )

    assert target_dir.exists()
    assert fake_pyautogui.calls == [
        ("hotkey", "ctrl", "s"),
        ("hotkey", "ctrl", "a"),
        ("typewrite", str(target_file), 0.08),
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



def test_validate_action_accepts_terminal_command() -> None:
    action = validate_action(
        {
            "action": "terminal_command",
            "command": "Get-ChildItem .",
            "working_directory": r"C:\Users\andre",
            "reasoning": "List files through the terminal.",
            "task_complete": False,
        }
    )

    assert action["command"] == "Get-ChildItem ."
    assert action["working_directory"] == r"C:\Users\andre"


def test_execute_action_terminal_command_returns_output(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    completed = subprocess.CompletedProcess(
        args=["powershell.exe", "-Command", "Get-ChildItem ."],
        returncode=0,
        stdout="alpha\nbeta\n",
        stderr="",
    )
    run_calls: list[dict[str, object]] = []

    def fake_run(args, stdout=None, stderr=None, text=None, cwd=None, timeout=None, check=None):
        run_calls.append(
            {
                "args": args,
                "cwd": cwd,
                "timeout": timeout,
                "check": check,
            }
        )
        return completed

    monkeypatch.setattr(executor, "_build_terminal_invocation", lambda command: ["powershell.exe", "-Command", command])
    monkeypatch.setattr(executor.subprocess, "run", fake_run)
    monkeypatch.setattr(executor.config, "TERMINAL_TIMEOUT_SECONDS", 12.0)
    monkeypatch.setattr(executor.config, "TERMINAL_OUTPUT_LIMIT", 200)

    result = execute_action(
        {
            "action": "terminal_command",
            "command": "Get-ChildItem .",
            "working_directory": str(tmp_path),
            "reasoning": "List files through the terminal.",
            "task_complete": False,
        }
    )

    assert result == {
        "command": "Get-ChildItem .",
        "command_exit_code": 0,
        "command_stdout": "alpha\nbeta",
        "command_stderr": "",
        "execution_confirmed": True,
    }
    assert run_calls == [
        {
            "args": ["powershell.exe", "-Command", "Get-ChildItem ."],
            "cwd": str(tmp_path),
            "timeout": 12.0,
            "check": False,
        }
    ]


def test_validate_action_accepts_uia_click() -> None:
    action = validate_action(
        {
            "action": "uia_click",
            "target_text": "OK",
            "control_type": "Button",
            "reasoning": "Click the labeled OK button through UI Automation.",
            "task_complete": False,
        }
    )

    assert action["target_text"] == "OK"
    assert action["control_type"] == "Button"


def test_execute_action_uia_click_uses_ui_automation(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        executor,
        "click_active_window_control",
        lambda **kwargs: calls.append(kwargs) or True,
    )

    result = execute_action(
        {
            "action": "uia_click",
            "target_text": "OK",
            "control_type": "Button",
            "reasoning": "Click the labeled OK button through UI Automation.",
            "task_complete": False,
        }
    )

    assert result is None
    assert calls == [{"target_text": "OK", "control_type": "Button", "automation_id": None}]


def test_execute_action_terminal_command_rewrites_known_user_folder(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    completed = subprocess.CompletedProcess(
        args=["powershell.exe", "-Command", "Get-ChildItem ."],
        returncode=0,
        stdout="done\n",
        stderr="",
    )
    run_calls: list[dict[str, object]] = []

    def fake_run(args, stdout=None, stderr=None, text=None, cwd=None, timeout=None, check=None):
        run_calls.append({"args": args, "cwd": cwd})
        return completed

    monkeypatch.setattr(executor, "_build_terminal_invocation", lambda command: ["powershell.exe", "-Command", command])
    monkeypatch.setattr(executor.subprocess, "run", fake_run)
    monkeypatch.setattr(executor, "rewrite_known_user_paths", lambda value: value.replace(r"C:\Users\Andrew\Downloads", str(tmp_path)))

    execute_action(
        {
            "action": "terminal_command",
            "command": r"Remove-Item 'C:\Users\Andrew\Downloads\Hello World.txt'",
            "working_directory": r"C:\Users\Andrew\Downloads",
            "reasoning": "Delete the file through PowerShell.",
            "task_complete": False,
        }
    )

    assert run_calls == [
        {
            "args": ["powershell.exe", "-Command", f"Remove-Item '{tmp_path}\\Hello World.txt'"],
            "cwd": str(tmp_path),
        }
    ]




