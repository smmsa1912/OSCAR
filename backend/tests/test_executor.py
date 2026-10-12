from __future__ import annotations

import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from oscar import executor
from oscar.execution.files import execute_open_file
from oscar.executor import ActionValidationError, execute_action, validate_action


def test_validate_action_rejects_out_of_bounds_coordinates() -> None:
    with pytest.raises(
        ActionValidationError, match="outside the current screen bounds"
    ):
        validate_action(
            {
                "action": "click",
                "x": 1200,
                "y": 10,
                "reasoning": "Click the target.",
                "task_complete": False,
            },
            screen_size=(100, 100),
        )


def test_validate_action_maps_normalized_coordinates_to_screen_pixels() -> None:
    action = validate_action(
        {
            "action": "click",
            "x": 500,
            "y": 250,
            "reasoning": "Click the midpoint on the normalized grid.",
            "task_complete": False,
        },
        screen_size=(1920, 1080),
    )

    assert action["x"] == 960
    assert action["y"] == 270


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


def test_validate_action_accepts_semantic_browser_and_shortcut_actions() -> None:
    browser_action = validate_action(
        {
            "action": "browser_search",
            "query": "red pandas",
            "browser_name": "chrome",
            "profile_name": "Andrew",
            "reasoning": "Search semantically in the browser.",
            "task_complete": False,
        }
    )
    shortcut_action = validate_action(
        {
            "action": "shortcut",
            "shortcut_name": "os.open_settings",
            "reasoning": "Use the named shortcut.",
            "task_complete": False,
        }
    )

    assert browser_action["query"] == "red pandas"
    assert browser_action["browser_name"] == "chrome"
    assert browser_action["profile_name"] == "Andrew"
    assert shortcut_action["shortcut_name"] == "os.open_settings"


def test_validate_action_accepts_browser_type() -> None:
    action = validate_action(
        {
            "action": "browser_type",
            "target_text": "Your name",
            "text": "Andrew",
            "selector_strategy": "label",
            "reasoning": "Type into the named browser field semantically.",
            "task_complete": False,
        }
    )

    assert action["target_text"] == "Your name"
    assert action["text"] == "Andrew"
    assert action["selector_strategy"] == "label"


def test_validate_action_accepts_browser_get_tabs_and_partial_tab_switch() -> None:
    get_tabs_action = validate_action(
        {
            "action": "browser_get_tabs",
            "reasoning": "Inspect the current tabs first.",
            "task_complete": False,
        }
    )
    switch_action = validate_action(
        {
            "action": "browser_switch_tab",
            "url": "https://web.whatsapp.com",
            "title_contains": "WhatsApp",
            "reasoning": "Switch by URL and partial title.",
            "task_complete": False,
        }
    )

    assert get_tabs_action["action"] == "browser_get_tabs"
    assert switch_action["url"] == "https://web.whatsapp.com"
    assert switch_action["title_contains"] == "WhatsApp"


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


def test_execute_action_dispatches_pyautogui_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


def test_execute_action_open_app_uses_launch_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    popen_calls: list[tuple[list[str], object, object]] = []

    def fake_popen(args, stdout=None, stderr=None):
        popen_calls.append((args, stdout, stderr))
        return object()

    monkeypatch.setattr(executor, "app_window_exists", lambda _app_name: False)
    monkeypatch.setattr(executor, "wait_for_condition", lambda predicate, policy: True)
    monkeypatch.setattr(
        executor,
        "build_launch_command",
        lambda app_name, profile_name=None, url=None: (
            [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                "--profile-directory=Default",
            ],
            object(),
        ),
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
            [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                "--profile-directory=Default",
            ],
            subprocess.DEVNULL,
            subprocess.DEVNULL,
        )
    ]


def test_execute_action_open_app_refuses_duplicate_launch_when_existing_focus_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    with pytest.raises(ActionValidationError, match="refusing to launch a duplicate"):
        execute_action(
            {
                "action": "open_app",
                "app_name": "notepad",
                "reasoning": "Focus the existing Notepad window instead of opening another one.",
                "task_complete": False,
            }
        )

    assert popen_calls == []


def test_execute_action_open_app_focuses_existing_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    focus_calls: list[str] = []
    monkeypatch.setattr(executor, "app_window_exists", lambda _app_name: True)
    monkeypatch.setattr(
        executor,
        "focus_app_window",
        lambda app_name, timeout: focus_calls.append(app_name) or True,
    )
    monkeypatch.setattr(executor.config, "WINDOW_FOCUS_TIMEOUT", 2.0)
    result = execute_action(
        {
            "action": "open_app",
            "app_name": "notepad",
            "reasoning": "Focus Notepad directly.",
            "task_complete": False,
        }
    )

    assert focus_calls == ["notepad"]
    assert result == {"launch_confirmed": True}


def test_execute_action_open_app_uses_shortcut_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_pyautogui = FakePyAutoGUI()
    popen_calls: list[list[str]] = []
    shortcut_spec = type("ShortcutSpec", (), {"shortcut_keys": ("winleft", "i")})()

    monkeypatch.setattr(executor, "_get_pyautogui", lambda: fake_pyautogui)
    monkeypatch.setattr(executor, "app_window_exists", lambda _app_name: False)
    monkeypatch.setattr(executor, "wait_for_condition", lambda predicate, policy: True)
    monkeypatch.setattr(
        executor,
        "build_launch_command",
        lambda app_name, profile_name=None, url=None: (
            ["cmd.exe", "/c", "start", "", "ms-settings:"],
            shortcut_spec,
        ),
    )
    monkeypatch.setattr(
        executor.subprocess,
        "Popen",
        lambda args, stdout=None, stderr=None: popen_calls.append(args),
    )

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
    monkeypatch.setattr(
        executor,
        "get_active_window_info",
        lambda: {"title": "Untitled - Notepad", "process_name": "notepad.exe"},
    )
    monkeypatch.setattr(executor.config, "WINDOW_FOCUS_TIMEOUT", 2.0)

    execute_action(
        {
            "action": "close_app",
            "app_name": "notepad",
            "reasoning": "Close Notepad directly.",
            "task_complete": False,
        }
    )

    assert fake_pyautogui.calls == [("hotkey", "alt", "f4")]


def test_execute_action_blocks_close_app_for_oscar_desktop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_pyautogui = FakePyAutoGUI()
    monkeypatch.setattr(executor, "_get_pyautogui", lambda: fake_pyautogui)
    monkeypatch.setattr(executor, "app_window_exists", lambda _app_name: True)
    monkeypatch.setattr(executor, "focus_app_window", lambda app_name, timeout: True)
    monkeypatch.setattr(
        executor,
        "get_active_window_info",
        lambda: {"title": "OSCAR", "process_name": "oscar.exe"},
    )
    monkeypatch.setattr(executor.config, "WINDOW_FOCUS_TIMEOUT", 0.0)

    with pytest.raises(
        ActionValidationError,
        match="Refused to close or modify the OSCAR desktop application",
    ):
        execute_action(
            {
                "action": "close_app",
                "app_name": "oscar",
                "reasoning": "Close OSCAR.",
                "task_complete": False,
            }
        )

    assert fake_pyautogui.calls == []


def test_execute_action_save_file_uses_save_shortcut_and_creates_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_pyautogui = FakePyAutoGUI()
    target_file = Path("workspace_artifacts") / "Project Folder" / "Hello World.txt"
    wait_calls = {"count": 0}

    monkeypatch.setattr(executor, "_get_pyautogui", lambda: fake_pyautogui)
    monkeypatch.setattr(executor.config, "TYPEWRITE_INTERVAL", 0.08)
    monkeypatch.setattr(
        executor,
        "get_active_window_info",
        lambda: {"title": "Editor", "process_name": "code.exe"},
    )
    monkeypatch.setattr(Path, "mkdir", lambda self, parents=False, exist_ok=False: None)

    def fake_exists(self: Path):
        return str(self) == str(target_file) and wait_calls["count"] >= 2

    def fake_wait_for_condition(predicate, policy):
        wait_calls["count"] += 1
        return True

    monkeypatch.setattr(Path, "exists", fake_exists)
    monkeypatch.setattr(executor, "_save_dialog_is_ready", lambda previous_window=None: True)
    monkeypatch.setattr(executor, "wait_for_condition", fake_wait_for_condition)

    result = execute_action(
        {
            "action": "save_file",
            "file_path": str(target_file),
            "reasoning": "Save the file to a custom directory.",
            "task_complete": False,
        }
    )

    assert fake_pyautogui.calls == [
        ("hotkey", "ctrl", "shift", "s"),
        ("hotkey", "ctrl", "a"),
        ("typewrite", str(target_file), 0.08),
        ("press", "enter"),
    ]
    assert result == {"file_path": str(target_file), "execution_confirmed": True}


def test_execute_action_wait_returns_delay_without_sleep() -> None:
    result = execute_action(
        {
            "action": "wait",
            "seconds": 1.5,
            "reasoning": "Wait for loading.",
            "task_complete": False,
        }
    )

    assert result == {"delay": 1.5, "execution_confirmed": True}


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


def test_execute_action_terminal_command_requires_terminal_agent() -> None:
    with pytest.raises(
        ActionValidationError,
        match="terminal_command actions must be executed through TerminalAgent",
    ):
        execute_action(
            {
                "action": "terminal_command",
                "command": "Get-ChildItem .",
                "working_directory": r"C:\Users\andre",
                "reasoning": "List files through the terminal.",
                "task_complete": False,
            }
        )


def test_validate_action_accepts_uia_click() -> None:
    action = validate_action(
        {
            "action": "uia_click",
            "target_text": "OK",
            "control_type": ["Button", "Hyperlink"],
            "class_name": "NavigationViewItem",
            "reasoning": "Click the labeled OK button through UI Automation.",
            "task_complete": False,
        }
    )

    assert action["target_text"] == "OK"
    assert action["control_type"] == ["Button", "Hyperlink"]
    assert action["class_name"] == "NavigationViewItem"


def test_execute_action_uia_click_uses_ui_automation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        executor,
        "invoke_active_window_control",
        lambda **kwargs: calls.append(kwargs)
        or {
            "element_id": 7,
            "text": "OK",
            "control_type": "Button",
        },
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

    assert result == {
        "execution_confirmed": True,
        "element_id": 7,
        "target_text": "OK",
        "control_type": "Button",
    }
    assert calls == [
        {
            "target_text": "OK",
            "control_type": "Button",
            "automation_id": None,
            "class_name": None,
            "element_id": None,
        }
    ]


def test_validate_action_accepts_click_with_element_id() -> None:
    action = validate_action(
        {
            "action": "click",
            "element_id": 7,
            "reasoning": "Click the numbered Set-of-Mark target.",
            "task_complete": False,
        }
    )

    assert action["element_id"] == 7


def test_execute_action_click_resolves_element_id_to_control_center(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_pyautogui = FakePyAutoGUI()
    monkeypatch.setattr(executor, "_get_pyautogui", lambda: fake_pyautogui)
    monkeypatch.setattr(
        executor,
        "resolve_active_window_control",
        lambda element_id: {
            "element_id": element_id,
            "left": 10,
            "top": 20,
            "right": 50,
            "bottom": 80,
        },
    )

    result = execute_action(
        {
            "action": "click",
            "element_id": 3,
            "reasoning": "Click the third Set-of-Mark target.",
            "task_complete": False,
        }
    )

    assert result is None
    assert fake_pyautogui.calls == [("click", 30, 50)]


def test_validate_action_accepts_focus_app_and_open_file() -> None:
    focus_action = validate_action(
        {
            "action": "focus_app",
            "app_name": "Visual Studio Code",
            "reasoning": "Bring the editor to the foreground.",
            "task_complete": False,
        }
    )
    open_file_action = validate_action(
        {
            "action": "open_file",
            "file_path": r"C:\Users\andre\Desktop\notes.txt",
            "app_name": "Visual Studio Code",
            "reasoning": "Open the requested file directly in the editor.",
            "task_complete": False,
        }
    )

    assert focus_action["app_name"] == "visual studio code"
    assert open_file_action["app_name"] == "visual studio code"
    assert open_file_action["file_path"].endswith("notes.txt")


def test_execute_action_focus_app_raises_when_window_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(executor, "app_window_exists", lambda _app_name: False)

    with pytest.raises(ActionValidationError, match="no visible window"):
        execute_action(
            {
                "action": "focus_app",
                "app_name": "notepad",
                "reasoning": "Focus Notepad safely.",
                "task_complete": False,
            }
        )


def test_execute_action_close_tab_uses_ctrl_w(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_pyautogui = FakePyAutoGUI()
    monkeypatch.setattr(executor, "_get_pyautogui", lambda: fake_pyautogui)
    monkeypatch.setattr(executor, "app_window_exists", lambda _app_name: True)
    monkeypatch.setattr(executor, "focus_app_window", lambda app_name, timeout: True)
    monkeypatch.setattr(
        executor,
        "get_active_window_info",
        lambda: {"title": "Untitled - Notepad", "process_name": "notepad.exe"},
    )
    monkeypatch.setattr(executor.config, "WINDOW_FOCUS_TIMEOUT", 0.0)

    execute_action(
        {
            "action": "close_tab",
            "app_name": "notepad",
            "reasoning": "Close only the current Notepad tab.",
            "task_complete": False,
        }
    )

    assert fake_pyautogui.calls == [("hotkey", "ctrl", "w")]


def test_execute_action_open_file_with_named_app_launches_editor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Keep the expected Windows profile independent of the account running pytest.
    monkeypatch.setenv("USERPROFILE", r"C:\Users\andre")
    popen_calls: list[list[str]] = []

    def fake_popen(args, stdout=None, stderr=None):
        popen_calls.append(args)
        return object()

    monkeypatch.setattr(
        executor,
        "build_launch_command",
        lambda app_name, profile_name=None, url=None: (["code.exe"], object()),
    )
    monkeypatch.setattr(executor.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(executor, "wait_for_condition", lambda predicate, policy: True)

    execute_action(
        {
            "action": "open_file",
            "app_name": "visual studio code",
            "file_path": r"C:\Users\andre\Desktop\notes.txt",
            "reasoning": "Open the requested file in VS Code.",
            "task_complete": False,
        }
    )

    assert popen_calls == [["code.exe", r"C:\Users\andre\Desktop\notes.txt"]]


def test_execute_open_file_sanitizes_powershell_userprofile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "oscar.execution.files.os.path.expanduser",
        lambda value: r"C:\Users\andre" if value == "~" else value,
    )
    launched: list[list[str]] = []

    result = execute_open_file(
        {
            "action": "open_file",
            "file_path": r"$env:USERPROFILE\Desktop\notes.txt",
            "reasoning": "Open the requested file.",
            "task_complete": False,
        },
        rewrite_known_user_paths=lambda value: value,
        build_launch_command=lambda *_args, **_kwargs: ([], object()),
        launch_process=lambda command, error_message: launched.append(command),
        wait_for_condition=lambda predicate, policy: True,
        default_retry_policy=lambda timeout: object(),
        focus_app_window=lambda app_name, timeout: True,
        app_window_exists=lambda app_name: True,
        app_launch_delay=0.0,
        platform_name="win32",
    )

    assert launched == [
        ["cmd.exe", "/c", "start", "", r"C:\Users\andre\Desktop\notes.txt"]
    ]
    assert result["file_path"] == r"C:\Users\andre\Desktop\notes.txt"


def test_execute_action_blocks_close_hotkey_on_protected_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_pyautogui = FakePyAutoGUI()
    monkeypatch.setattr(executor, "_get_pyautogui", lambda: fake_pyautogui)
    monkeypatch.setattr(
        executor,
        "get_active_window_info",
        lambda: {"title": "PowerShell", "process_name": "powershell.exe"},
    )

    with pytest.raises(ActionValidationError, match="Refused to send a close hotkey"):
        execute_action(
            {
                "action": "hotkey",
                "keys": ["alt", "f4"],
                "reasoning": "Close the current window.",
                "task_complete": False,
            }
        )

    assert fake_pyautogui.calls == []


def test_execute_action_blocks_close_hotkey_on_oscar_desktop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_pyautogui = FakePyAutoGUI()
    monkeypatch.setattr(executor, "_get_pyautogui", lambda: fake_pyautogui)
    monkeypatch.setattr(
        executor,
        "get_active_window_info",
        lambda: {"title": "OSCAR", "process_name": "oscar.exe"},
    )

    with pytest.raises(ActionValidationError, match="OSCAR control window"):
        execute_action(
            {
                "action": "hotkey",
                "keys": ["alt", "f4"],
                "reasoning": "Close the current window.",
                "task_complete": False,
            }
        )

    assert fake_pyautogui.calls == []



def test_validate_action_accepts_wait_until() -> None:
    action = validate_action(
        {
            "action": "wait_until",
            "time_of_day": "12:00:00",
            "reasoning": "Start at noon exactly.",
            "task_complete": False,
        }
    )

    assert action["time_of_day"] == "12:00:00"


def test_execute_action_wait_until_returns_delay_without_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = datetime.now().astimezone() + timedelta(seconds=90)

    monkeypatch.setattr(executor, "_parse_wait_until", lambda action: target)

    result = execute_action(
        {
            "action": "wait_until",
            "time_of_day": "12:00",
            "reasoning": "Start later.",
            "task_complete": False,
        }
    )

    assert result is not None
    assert result["wait_until"] == target.isoformat()
    assert result["delay"] == pytest.approx(90, abs=1.0)
    assert result["execution_confirmed"] is True
