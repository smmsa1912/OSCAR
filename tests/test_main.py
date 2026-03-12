from __future__ import annotations

from pathlib import Path

import pytest

from oscar import main as oscar_main


def _focus_after_launch(*_args, **kwargs) -> bool:
    return kwargs.get("timeout") != 0.3


def test_run_oscar_bootstraps_simple_open_app_tasks(
    monkeypatch: pytest.MonkeyPatch, tmp_path, capsys
) -> None:
    executed: list[str] = []
    logged: dict[str, object] = {}

    monkeypatch.setattr(oscar_main.config, "ACTION_DELAY", 0.0)
    monkeypatch.setattr(oscar_main.config, "APP_LAUNCH_DELAY", 1.5)
    monkeypatch.setattr(oscar_main.config, "WINDOW_FOCUS_TIMEOUT", 2.0)
    monkeypatch.setattr(oscar_main.config, "FOCUS_SETTLE_DELAY", 0.0)
    monkeypatch.setattr(oscar_main, "validate_action", lambda action, screen_size=None: action)
    monkeypatch.setattr(oscar_main, "execute_action", lambda action: executed.append(action["action"]))
    monkeypatch.setattr(oscar_main, "focus_app_window", _focus_after_launch)
    monkeypatch.setattr(oscar_main, "app_window_exists", lambda _app_name: False)
    monkeypatch.setattr(
        oscar_main,
        "ask_gemini",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Gemini should not be called")),
    )
    monkeypatch.setattr(oscar_main.time, "sleep", lambda _seconds: None)

    def fake_write_run_log(**kwargs):
        logged.update(kwargs)
        path = tmp_path / "run.json"
        path.write_text("{}", encoding="utf-8")
        return path

    monkeypatch.setattr(oscar_main, "write_run_log", fake_write_run_log)

    log_path = oscar_main.run_oscar("open taskmanager")

    assert log_path == tmp_path / "run.json"
    assert executed == ["open_app"]
    assert logged["status"] == "completed"
    assert len(logged["history"]) == 2
    output = capsys.readouterr().out
    assert "Launch taskmanager directly" in output
    assert "Task completed!" in output


def test_run_oscar_bootstraps_browser_search_with_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path, capsys
) -> None:
    executed: list[str] = []
    logged: dict[str, object] = {}

    monkeypatch.setattr(oscar_main.config, "ACTION_DELAY", 0.0)
    monkeypatch.setattr(oscar_main.config, "APP_LAUNCH_DELAY", 1.5)
    monkeypatch.setattr(oscar_main.config, "WINDOW_FOCUS_TIMEOUT", 2.0)
    monkeypatch.setattr(oscar_main.config, "FOCUS_SETTLE_DELAY", 0.0)
    monkeypatch.setattr(oscar_main, "validate_action", lambda action, screen_size=None: action)
    monkeypatch.setattr(oscar_main, "execute_action", lambda action: executed.append(action["action"]))
    monkeypatch.setattr(oscar_main, "focus_app_window", _focus_after_launch)
    monkeypatch.setattr(oscar_main, "app_window_exists", lambda _app_name: False)
    monkeypatch.setattr(
        oscar_main,
        "ask_gemini",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Gemini should not be called")),
    )
    monkeypatch.setattr(oscar_main.time, "sleep", lambda _seconds: None)

    def fake_write_run_log(**kwargs):
        logged.update(kwargs)
        path = tmp_path / "run.json"
        path.write_text("{}", encoding="utf-8")
        return path

    monkeypatch.setattr(oscar_main, "write_run_log", fake_write_run_log)

    log_path = oscar_main.run_oscar("open chrome use Andrew profile and search google.com")

    assert log_path == tmp_path / "run.json"
    assert executed == ["open_app", "hotkey", "type", "press"]
    assert logged["status"] == "completed"
    assert len(logged["history"]) == 5
    output = capsys.readouterr().out
    assert "Launch chrome directly" in output
    assert "Type 'google.com'" in output


def test_run_oscar_bootstraps_browser_navigation(
    monkeypatch: pytest.MonkeyPatch, tmp_path, capsys
) -> None:
    executed: list[dict[str, object]] = []
    logged: dict[str, object] = {}

    monkeypatch.setattr(oscar_main.config, "ACTION_DELAY", 0.0)
    monkeypatch.setattr(oscar_main.config, "APP_LAUNCH_DELAY", 1.5)
    monkeypatch.setattr(oscar_main.config, "WINDOW_FOCUS_TIMEOUT", 2.0)
    monkeypatch.setattr(oscar_main.config, "FOCUS_SETTLE_DELAY", 0.0)
    monkeypatch.setattr(oscar_main, "validate_action", lambda action, screen_size=None: action)
    monkeypatch.setattr(oscar_main, "execute_action", lambda action: executed.append(action))
    monkeypatch.setattr(oscar_main, "focus_app_window", _focus_after_launch)
    monkeypatch.setattr(oscar_main, "app_window_exists", lambda _app_name: False)
    monkeypatch.setattr(
        oscar_main,
        "ask_gemini",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Gemini should not be called")),
    )
    monkeypatch.setattr(oscar_main.time, "sleep", lambda _seconds: None)

    def fake_write_run_log(**kwargs):
        logged.update(kwargs)
        path = tmp_path / "run.json"
        path.write_text("{}", encoding="utf-8")
        return path

    monkeypatch.setattr(oscar_main, "write_run_log", fake_write_run_log)

    log_path = oscar_main.run_oscar("open chrome and goto github.com")

    assert log_path == tmp_path / "run.json"
    assert [action["action"] for action in executed] == ["open_app"]
    assert executed[0]["url"] == "https://github.com"
    assert logged["status"] == "completed"
    assert "navigated to https://github.com" in capsys.readouterr().out


def test_run_oscar_bootstraps_multiple_apps_with_typo(
    monkeypatch: pytest.MonkeyPatch, tmp_path, capsys
) -> None:
    executed: list[str] = []
    logged: dict[str, object] = {}

    monkeypatch.setattr(oscar_main.config, "ACTION_DELAY", 0.0)
    monkeypatch.setattr(oscar_main.config, "APP_LAUNCH_DELAY", 1.5)
    monkeypatch.setattr(oscar_main.config, "WINDOW_FOCUS_TIMEOUT", 2.0)
    monkeypatch.setattr(oscar_main.config, "FOCUS_SETTLE_DELAY", 0.0)
    monkeypatch.setattr(oscar_main, "validate_action", lambda action, screen_size=None: action)
    monkeypatch.setattr(oscar_main, "execute_action", lambda action: executed.append(action["app_name"]))
    monkeypatch.setattr(oscar_main, "focus_app_window", _focus_after_launch)
    monkeypatch.setattr(oscar_main, "app_window_exists", lambda _app_name: False)
    monkeypatch.setattr(
        oscar_main,
        "ask_gemini",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Gemini should not be called")),
    )
    monkeypatch.setattr(oscar_main.time, "sleep", lambda _seconds: None)

    def fake_write_run_log(**kwargs):
        logged.update(kwargs)
        path = tmp_path / "run.json"
        path.write_text("{}", encoding="utf-8")
        return path

    monkeypatch.setattr(oscar_main, "write_run_log", fake_write_run_log)

    log_path = oscar_main.run_oscar("open notepad and file exploror")

    assert log_path == tmp_path / "run.json"
    assert executed == ["notepad", "file explorer"]
    assert logged["status"] == "completed"
    assert len(logged["history"]) == 3
    output = capsys.readouterr().out
    assert "Launch notepad directly" in output
    assert "Launch file explorer directly" in output


def test_run_oscar_bootstraps_open_type_and_save_notepad_tasks(
    monkeypatch: pytest.MonkeyPatch, tmp_path, capsys
) -> None:
    executed: list[dict[str, object]] = []
    logged: dict[str, object] = {}

    monkeypatch.setattr(oscar_main.config, "ACTION_DELAY", 0.0)
    monkeypatch.setattr(oscar_main.config, "APP_LAUNCH_DELAY", 1.5)
    monkeypatch.setattr(oscar_main.config, "WINDOW_FOCUS_TIMEOUT", 2.0)
    monkeypatch.setattr(oscar_main.config, "FOCUS_SETTLE_DELAY", 0.0)
    monkeypatch.setattr(oscar_main, "validate_action", lambda action, screen_size=None: action)
    monkeypatch.setattr(oscar_main, "execute_action", lambda action: executed.append(action))
    monkeypatch.setattr(oscar_main, "focus_app_window", _focus_after_launch)
    monkeypatch.setattr(oscar_main, "app_window_exists", lambda _app_name: False)
    monkeypatch.setattr(
        oscar_main,
        "ask_gemini",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Gemini should not be called")),
    )
    monkeypatch.setattr(oscar_main.time, "sleep", lambda _seconds: None)

    def fake_write_run_log(**kwargs):
        logged.update(kwargs)
        path = tmp_path / "run.json"
        path.write_text("{}", encoding="utf-8")
        return path

    monkeypatch.setattr(oscar_main, "write_run_log", fake_write_run_log)

    log_path = oscar_main.run_oscar("open notepad, type hello world and save it in Downloads folder")

    assert log_path == tmp_path / "run.json"
    assert [action["action"] for action in executed] == ["open_app", "type", "save_file"]
    assert logged["status"] == "completed"
    assert len(logged["history"]) == 4
    save_action = executed[-1]
    assert str(save_action["file_path"]).endswith(".txt")
    output = capsys.readouterr().out
    assert "Save the Notepad document to Downloads" in output


def test_run_oscar_bootstraps_open_type_and_save_to_desktop_with_typo(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    executed: list[dict[str, object]] = []

    monkeypatch.setattr(oscar_main.config, "ACTION_DELAY", 0.0)
    monkeypatch.setattr(oscar_main.config, "APP_LAUNCH_DELAY", 1.5)
    monkeypatch.setattr(oscar_main.config, "WINDOW_FOCUS_TIMEOUT", 2.0)
    monkeypatch.setattr(oscar_main.config, "FOCUS_SETTLE_DELAY", 0.0)
    monkeypatch.setattr(oscar_main, "validate_action", lambda action, screen_size=None: action)
    monkeypatch.setattr(oscar_main, "execute_action", lambda action: executed.append(action))
    monkeypatch.setattr(oscar_main, "focus_app_window", _focus_after_launch)
    monkeypatch.setattr(oscar_main, "app_window_exists", lambda _app_name: False)
    monkeypatch.setattr(
        oscar_main,
        "ask_gemini",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Gemini should not be called")),
    )
    monkeypatch.setattr(oscar_main.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        oscar_main,
        "write_run_log",
        lambda **_kwargs: tmp_path / "run.json",
    )

    oscar_main.run_oscar("open notepad and type 'Hello World By SMMSA' and save it in Dekstop Folder")

    assert [action["action"] for action in executed] == ["open_app", "type", "save_file"]
    assert "Desktop" in str(executed[-1]["file_path"])


def test_run_oscar_bootstraps_then_continues_for_multi_step_tasks(
    monkeypatch: pytest.MonkeyPatch, tmp_path, capsys
) -> None:
    actions = iter(
        [
            {
                "action": "done",
                "reasoning": "The follow-up work is complete.",
                "task_complete": True,
            }
        ]
    )
    executed: list[str] = []
    logged: dict[str, object] = {}
    prompts: list[dict[str, object]] = []

    monkeypatch.setattr(oscar_main.config, "MAX_STEPS", 5)
    monkeypatch.setattr(oscar_main.config, "ACTION_DELAY", 0.0)
    monkeypatch.setattr(oscar_main.config, "APP_LAUNCH_DELAY", 1.5)
    monkeypatch.setattr(oscar_main.config, "WINDOW_FOCUS_TIMEOUT", 2.0)
    monkeypatch.setattr(oscar_main.config, "FOCUS_SETTLE_DELAY", 0.0)
    monkeypatch.setattr(oscar_main.config, "SCREENSHOT_REGION", None)
    monkeypatch.setattr(oscar_main.config, "GEMINI_MODEL", "test-model")
    monkeypatch.setattr(oscar_main, "capture_screenshot", lambda _region=None: (object(), (800, 600)))
    monkeypatch.setattr(
        oscar_main,
        "get_active_window_info",
        lambda: {"title": "Untitled - Notepad", "process_name": "notepad.exe", "hwnd": 1},
    )
    monkeypatch.setattr(oscar_main, "get_cursor_position", lambda: (100, 200))
    monkeypatch.setattr(
        oscar_main,
        "build_prompt",
        lambda *args, **kwargs: prompts.append(kwargs) or "prompt",
    )
    monkeypatch.setattr(oscar_main, "ask_gemini", lambda *_args, **_kwargs: next(actions))
    monkeypatch.setattr(oscar_main, "validate_action", lambda action, screen_size=None: action)
    monkeypatch.setattr(oscar_main, "execute_action", lambda action: executed.append(action["action"]))
    monkeypatch.setattr(oscar_main, "focus_app_window", _focus_after_launch)
    monkeypatch.setattr(oscar_main, "app_window_exists", lambda _app_name: False)
    monkeypatch.setattr(oscar_main.time, "sleep", lambda _seconds: None)

    def fake_write_run_log(**kwargs):
        logged.update(kwargs)
        path = tmp_path / "run.json"
        path.write_text("{}", encoding="utf-8")
        return path

    monkeypatch.setattr(oscar_main, "write_run_log", fake_write_run_log)

    log_path = oscar_main.run_oscar("open notepad and save the file")

    assert log_path == tmp_path / "run.json"
    assert executed == ["open_app"]
    assert logged["status"] == "completed"
    assert len(logged["history"]) == 2
    assert prompts[0]["active_window_title"] == "Untitled - Notepad"
    assert prompts[0]["active_process_name"] == "notepad.exe"
    assert prompts[0]["cursor_position"] == (100, 200)
    output = capsys.readouterr().out
    assert "Launch notepad directly" in output
    assert "The follow-up work is complete." in output


def test_run_oscar_completes_and_logs(monkeypatch: pytest.MonkeyPatch, tmp_path, capsys) -> None:
    actions = iter(
        [
            {
                "action": "click",
                "x": 10,
                "y": 20,
                "reasoning": "Click the Start button.",
                "task_complete": False,
            },
            {
                "action": "done",
                "reasoning": "The task is complete.",
                "task_complete": True,
            },
        ]
    )
    executed: list[str] = []
    logged: dict[str, object] = {}

    monkeypatch.setattr(oscar_main.config, "MAX_STEPS", 5)
    monkeypatch.setattr(oscar_main.config, "ACTION_DELAY", 0.0)
    monkeypatch.setattr(oscar_main.config, "APP_LAUNCH_DELAY", 1.5)
    monkeypatch.setattr(oscar_main.config, "WINDOW_FOCUS_TIMEOUT", 2.0)
    monkeypatch.setattr(oscar_main.config, "FOCUS_SETTLE_DELAY", 0.0)
    monkeypatch.setattr(oscar_main.config, "SCREENSHOT_REGION", None)
    monkeypatch.setattr(oscar_main.config, "GEMINI_MODEL", "test-model")
    monkeypatch.setattr(oscar_main, "capture_screenshot", lambda _region=None: (object(), (800, 600)))
    monkeypatch.setattr(
        oscar_main,
        "get_active_window_info",
        lambda: {"title": "VS Code", "process_name": "code.exe", "hwnd": 1},
    )
    monkeypatch.setattr(oscar_main, "get_cursor_position", lambda: (10, 20))
    monkeypatch.setattr(oscar_main, "build_prompt", lambda *args, **kwargs: "prompt")
    monkeypatch.setattr(oscar_main, "ask_gemini", lambda *_args, **_kwargs: next(actions))
    monkeypatch.setattr(oscar_main, "validate_action", lambda action, screen_size=None: action)
    monkeypatch.setattr(oscar_main, "execute_action", lambda action: executed.append(action["action"]))
    monkeypatch.setattr(oscar_main, "focus_app_window", _focus_after_launch)
    monkeypatch.setattr(oscar_main, "app_window_exists", lambda _app_name: False)
    monkeypatch.setattr(oscar_main.time, "sleep", lambda _seconds: None)

    def fake_write_run_log(**kwargs):
        logged.update(kwargs)
        path = tmp_path / "run.json"
        path.write_text("{}", encoding="utf-8")
        return path

    monkeypatch.setattr(oscar_main, "write_run_log", fake_write_run_log)

    log_path = oscar_main.run_oscar("Click the Start button")

    assert log_path == tmp_path / "run.json"
    assert executed == ["click"]
    assert logged["status"] == "completed"
    assert len(logged["history"]) == 2
    output = capsys.readouterr().out
    assert "Step 1: Click the Start button." in output
    assert "Task completed!" in output


def test_run_oscar_logs_max_steps(monkeypatch: pytest.MonkeyPatch, tmp_path, capsys) -> None:
    logged: dict[str, object] = {}

    monkeypatch.setattr(oscar_main.config, "MAX_STEPS", 2)
    monkeypatch.setattr(oscar_main.config, "ACTION_DELAY", 0.0)
    monkeypatch.setattr(oscar_main.config, "APP_LAUNCH_DELAY", 1.5)
    monkeypatch.setattr(oscar_main.config, "WINDOW_FOCUS_TIMEOUT", 2.0)
    monkeypatch.setattr(oscar_main.config, "FOCUS_SETTLE_DELAY", 0.0)
    monkeypatch.setattr(oscar_main.config, "SCREENSHOT_REGION", None)
    monkeypatch.setattr(oscar_main, "capture_screenshot", lambda _region=None: (object(), (800, 600)))
    monkeypatch.setattr(
        oscar_main,
        "get_active_window_info",
        lambda: {"title": "VS Code", "process_name": "code.exe", "hwnd": 1},
    )
    monkeypatch.setattr(oscar_main, "get_cursor_position", lambda: (10, 20))
    monkeypatch.setattr(oscar_main, "build_prompt", lambda *args, **kwargs: "prompt")
    monkeypatch.setattr(
        oscar_main,
        "ask_gemini",
        lambda *_args, **_kwargs: {
            "action": "wait",
            "seconds": 1.0,
            "reasoning": "Keep waiting.",
            "task_complete": False,
        },
    )
    monkeypatch.setattr(oscar_main, "validate_action", lambda action, screen_size=None: action)
    monkeypatch.setattr(oscar_main, "execute_action", lambda action: None)
    monkeypatch.setattr(oscar_main, "focus_app_window", _focus_after_launch)
    monkeypatch.setattr(oscar_main, "app_window_exists", lambda _app_name: False)
    monkeypatch.setattr(oscar_main.time, "sleep", lambda _seconds: None)

    def fake_write_run_log(**kwargs):
        logged.update(kwargs)
        path = tmp_path / "max.json"
        path.write_text("{}", encoding="utf-8")
        return path

    monkeypatch.setattr(oscar_main, "write_run_log", fake_write_run_log)

    log_path = oscar_main.run_oscar("Wait forever")

    assert log_path == tmp_path / "max.json"
    assert logged["status"] == "max_steps_reached"
    assert len(logged["history"]) == 2
    assert "Reached the maximum number of steps (2)." in capsys.readouterr().out


def test_run_oscar_logs_failures_before_reraising(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    logged: dict[str, object] = {}

    monkeypatch.setattr(oscar_main.config, "MAX_STEPS", 3)
    monkeypatch.setattr(oscar_main.config, "ACTION_DELAY", 0.0)
    monkeypatch.setattr(oscar_main.config, "APP_LAUNCH_DELAY", 1.5)
    monkeypatch.setattr(oscar_main.config, "WINDOW_FOCUS_TIMEOUT", 2.0)
    monkeypatch.setattr(oscar_main.config, "FOCUS_SETTLE_DELAY", 0.0)
    monkeypatch.setattr(oscar_main.config, "SCREENSHOT_REGION", None)
    monkeypatch.setattr(oscar_main, "capture_screenshot", lambda _region=None: (object(), (800, 600)))
    monkeypatch.setattr(
        oscar_main,
        "get_active_window_info",
        lambda: {"title": "VS Code", "process_name": "code.exe", "hwnd": 1},
    )
    monkeypatch.setattr(oscar_main, "get_cursor_position", lambda: (10, 20))
    monkeypatch.setattr(oscar_main, "build_prompt", lambda *args, **kwargs: "prompt")
    monkeypatch.setattr(
        oscar_main,
        "ask_gemini",
        lambda *_args, **_kwargs: {
            "action": "click",
            "x": 10,
            "y": 20,
            "reasoning": "Click the button.",
            "task_complete": False,
        },
    )
    monkeypatch.setattr(oscar_main, "validate_action", lambda action, screen_size=None: action)

    def failing_execute(_action):
        raise RuntimeError("executor blew up")

    def fake_write_run_log(**kwargs):
        logged.update(kwargs)
        path = tmp_path / "failed.json"
        path.write_text("{}", encoding="utf-8")
        return path

    monkeypatch.setattr(oscar_main, "execute_action", failing_execute)
    monkeypatch.setattr(oscar_main, "focus_app_window", _focus_after_launch)
    monkeypatch.setattr(oscar_main, "app_window_exists", lambda _app_name: False)
    monkeypatch.setattr(oscar_main, "write_run_log", fake_write_run_log)

    with pytest.raises(RuntimeError, match="executor blew up"):
        oscar_main.run_oscar("Click the button")

    assert logged["status"] == "failed"
    assert logged["error"] == "executor blew up"
    assert len(logged["history"]) == 1


def test_cli_main_prompts_when_task_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(oscar_main, "run_oscar", lambda task: Path("logs/run.json"))
    monkeypatch.setattr("builtins.input", lambda _prompt: "Prompted task")

    assert oscar_main.main([]) == 0
