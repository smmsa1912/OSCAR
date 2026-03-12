from __future__ import annotations

from pathlib import Path

import pytest

from oscar import main as oscar_main


def _always_focus(*_args, **_kwargs) -> bool:
    return True


def test_run_oscar_bootstraps_simple_open_app_tasks(
    monkeypatch: pytest.MonkeyPatch, tmp_path, capsys
) -> None:
    executed: list[str] = []
    logged: dict[str, object] = {}

    monkeypatch.setattr(oscar_main.config, "ACTION_DELAY", 0.0)
    monkeypatch.setattr(oscar_main.config, "APP_LAUNCH_DELAY", 0.0)
    monkeypatch.setattr(oscar_main.config, "WINDOW_FOCUS_TIMEOUT", 0.0)
    monkeypatch.setattr(oscar_main.config, "FOCUS_SETTLE_DELAY", 0.0)
    monkeypatch.setattr(oscar_main, "validate_action", lambda action, screen_size=None: action)
    monkeypatch.setattr(oscar_main, "execute_action", lambda action: executed.append(action["action"]))
    monkeypatch.setattr(oscar_main, "focus_app_window", _always_focus)
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
    assert "taskmanager" in capsys.readouterr().out.lower()


def test_run_oscar_bootstraps_browser_search_to_direct_url_with_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    executed: list[dict[str, object]] = []

    monkeypatch.setattr(oscar_main.config, "ACTION_DELAY", 0.0)
    monkeypatch.setattr(oscar_main.config, "APP_LAUNCH_DELAY", 0.0)
    monkeypatch.setattr(oscar_main.config, "WINDOW_FOCUS_TIMEOUT", 0.0)
    monkeypatch.setattr(oscar_main.config, "FOCUS_SETTLE_DELAY", 0.0)
    monkeypatch.setattr(oscar_main, "validate_action", lambda action, screen_size=None: action)
    monkeypatch.setattr(oscar_main, "execute_action", lambda action: executed.append(action))
    monkeypatch.setattr(oscar_main, "focus_app_window", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(oscar_main, "app_window_exists", lambda _app_name: True)
    monkeypatch.setattr(
        oscar_main,
        "ask_gemini",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Gemini should not be called")),
    )
    monkeypatch.setattr(oscar_main.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(oscar_main, "write_run_log", lambda **_kwargs: tmp_path / "run.json")

    oscar_main.run_oscar("open chrome and use Andrew profile and search google.com")

    assert [action["action"] for action in executed] == ["open_app"]
    assert executed[0]["profile_name"] == "Andrew"
    assert executed[0]["url"] == "https://www.google.com/search?q=google.com"


def test_run_oscar_bootstraps_browser_image_search(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    executed: list[dict[str, object]] = []

    monkeypatch.setattr(oscar_main.config, "ACTION_DELAY", 0.0)
    monkeypatch.setattr(oscar_main.config, "APP_LAUNCH_DELAY", 0.0)
    monkeypatch.setattr(oscar_main.config, "WINDOW_FOCUS_TIMEOUT", 0.0)
    monkeypatch.setattr(oscar_main.config, "FOCUS_SETTLE_DELAY", 0.0)
    monkeypatch.setattr(oscar_main, "validate_action", lambda action, screen_size=None: action)
    monkeypatch.setattr(oscar_main, "execute_action", lambda action: executed.append(action))
    monkeypatch.setattr(oscar_main, "focus_app_window", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(oscar_main, "app_window_exists", lambda _app_name: True)
    monkeypatch.setattr(
        oscar_main,
        "ask_gemini",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Gemini should not be called")),
    )
    monkeypatch.setattr(oscar_main.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(oscar_main, "write_run_log", lambda **_kwargs: tmp_path / "run.json")

    oscar_main.run_oscar("open chrome and look for a dog image")

    assert [action["action"] for action in executed] == ["open_app"]
    assert "tbm=isch" in str(executed[0]["url"])
    assert "dog+image" in str(executed[0]["url"])


def test_run_oscar_bootstraps_browser_navigation_with_and_use_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    executed: list[dict[str, object]] = []

    monkeypatch.setattr(oscar_main.config, "ACTION_DELAY", 0.0)
    monkeypatch.setattr(oscar_main.config, "APP_LAUNCH_DELAY", 0.0)
    monkeypatch.setattr(oscar_main.config, "WINDOW_FOCUS_TIMEOUT", 0.0)
    monkeypatch.setattr(oscar_main.config, "FOCUS_SETTLE_DELAY", 0.0)
    monkeypatch.setattr(oscar_main, "validate_action", lambda action, screen_size=None: action)
    monkeypatch.setattr(oscar_main, "execute_action", lambda action: executed.append(action))
    monkeypatch.setattr(oscar_main, "focus_app_window", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(oscar_main, "app_window_exists", lambda _app_name: True)
    monkeypatch.setattr(
        oscar_main,
        "ask_gemini",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Gemini should not be called")),
    )
    monkeypatch.setattr(oscar_main.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(oscar_main, "write_run_log", lambda **_kwargs: tmp_path / "run.json")

    oscar_main.run_oscar("open chrome and use Salomi profile and goto google.com")

    assert [action["action"] for action in executed] == ["open_app"]
    assert executed[0]["profile_name"] == "Salomi"
    assert executed[0]["url"] == "https://google.com"


def test_run_oscar_bootstraps_multiple_apps_with_typo(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    executed: list[str] = []
    logged: dict[str, object] = {}

    monkeypatch.setattr(oscar_main.config, "ACTION_DELAY", 0.0)
    monkeypatch.setattr(oscar_main.config, "APP_LAUNCH_DELAY", 0.0)
    monkeypatch.setattr(oscar_main.config, "WINDOW_FOCUS_TIMEOUT", 0.0)
    monkeypatch.setattr(oscar_main.config, "FOCUS_SETTLE_DELAY", 0.0)
    monkeypatch.setattr(oscar_main, "validate_action", lambda action, screen_size=None: action)
    monkeypatch.setattr(oscar_main, "execute_action", lambda action: executed.append(action["app_name"]))
    monkeypatch.setattr(oscar_main, "focus_app_window", _always_focus)
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

    oscar_main.run_oscar("open notepad and file exploror")

    assert executed == ["notepad", "file explorer"]
    assert logged["status"] == "completed"


def test_run_oscar_bootstraps_write_task_to_custom_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path, capsys
) -> None:
    executed: list[dict[str, object]] = []
    logged: dict[str, object] = {}

    monkeypatch.setattr(oscar_main.config, "ACTION_DELAY", 0.0)
    monkeypatch.setattr(oscar_main.config, "APP_LAUNCH_DELAY", 0.0)
    monkeypatch.setattr(oscar_main.config, "WINDOW_FOCUS_TIMEOUT", 0.0)
    monkeypatch.setattr(oscar_main.config, "FOCUS_SETTLE_DELAY", 0.0)
    monkeypatch.setattr(oscar_main, "validate_action", lambda action, screen_size=None: action)
    monkeypatch.setattr(oscar_main, "execute_action", lambda action: executed.append(action))
    monkeypatch.setattr(oscar_main, "focus_app_window", _always_focus)
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

    log_path = oscar_main.run_oscar("open notepad and write 'Hello World By SMMSA' and save it in A:\\Andrew Folder")

    assert log_path == tmp_path / "run.json"
    assert [action["action"] for action in executed] == ["open_app", "type", "save_file"]
    assert executed[0]["new_instance"] is True
    assert executed[1]["text"] == "Hello World By SMMSA"
    assert str(executed[2]["file_path"]).endswith(r"A:\Andrew Folder\Hello World By SMMSA.txt")
    assert logged["status"] == "completed"
    assert "hello world by smmsa" in capsys.readouterr().out.lower()


def test_run_oscar_bootstraps_write_task_to_desktop(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    executed: list[dict[str, object]] = []

    monkeypatch.setattr(oscar_main.config, "ACTION_DELAY", 0.0)
    monkeypatch.setattr(oscar_main.config, "APP_LAUNCH_DELAY", 0.0)
    monkeypatch.setattr(oscar_main.config, "WINDOW_FOCUS_TIMEOUT", 0.0)
    monkeypatch.setattr(oscar_main.config, "FOCUS_SETTLE_DELAY", 0.0)
    monkeypatch.setattr(oscar_main, "validate_action", lambda action, screen_size=None: action)
    monkeypatch.setattr(oscar_main, "execute_action", lambda action: executed.append(action))
    monkeypatch.setattr(oscar_main, "focus_app_window", _always_focus)
    monkeypatch.setattr(oscar_main, "app_window_exists", lambda _app_name: False)
    monkeypatch.setattr(
        oscar_main,
        "ask_gemini",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Gemini should not be called")),
    )
    monkeypatch.setattr(oscar_main.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(oscar_main, "write_run_log", lambda **_kwargs: tmp_path / "run.json")

    oscar_main.run_oscar("open notepad type Hello World and save it in Desktop")

    assert [action["action"] for action in executed] == ["open_app", "type", "save_file"]
    assert "Desktop" in str(executed[-1]["file_path"])


def test_run_oscar_close_task_bootstraps_then_finishes(
    monkeypatch: pytest.MonkeyPatch, tmp_path, capsys
) -> None:
    executed: list[str] = []
    logged: dict[str, object] = {}

    monkeypatch.setattr(oscar_main.config, "MAX_STEPS", 4)
    monkeypatch.setattr(oscar_main.config, "ACTION_DELAY", 0.0)
    monkeypatch.setattr(oscar_main.config, "APP_LAUNCH_DELAY", 0.0)
    monkeypatch.setattr(oscar_main.config, "WINDOW_FOCUS_TIMEOUT", 0.0)
    monkeypatch.setattr(oscar_main.config, "FOCUS_SETTLE_DELAY", 0.0)
    monkeypatch.setattr(oscar_main.config, "SCREENSHOT_REGION", None)
    monkeypatch.setattr(oscar_main.config, "GEMINI_MODEL", "test-model")
    monkeypatch.setattr(oscar_main, "capture_screenshot", lambda _region=None: (object(), (800, 600)))
    monkeypatch.setattr(
        oscar_main,
        "get_active_window_info",
        lambda: {"title": None, "process_name": None, "hwnd": None},
    )
    monkeypatch.setattr(oscar_main, "get_cursor_position", lambda: (100, 200))
    monkeypatch.setattr(oscar_main, "build_prompt", lambda *args, **kwargs: "prompt")
    monkeypatch.setattr(
        oscar_main,
        "ask_gemini",
        lambda *_args, **_kwargs: {
            "action": "done",
            "reasoning": "The window is closed.",
            "task_complete": True,
        },
    )
    monkeypatch.setattr(oscar_main, "validate_action", lambda action, screen_size=None: action)
    monkeypatch.setattr(oscar_main, "execute_action", lambda action: executed.append(action["action"]))
    monkeypatch.setattr(oscar_main, "focus_app_window", _always_focus)
    state = {"calls": 0}

    def fake_app_window_exists(_app_name: str) -> bool:
        state["calls"] += 1
        return state["calls"] == 1

    monkeypatch.setattr(oscar_main, "app_window_exists", fake_app_window_exists)
    monkeypatch.setattr(oscar_main.time, "sleep", lambda _seconds: None)

    def fake_write_run_log(**kwargs):
        logged.update(kwargs)
        path = tmp_path / "run.json"
        path.write_text("{}", encoding="utf-8")
        return path

    monkeypatch.setattr(oscar_main, "write_run_log", fake_write_run_log)

    oscar_main.run_oscar("close notepad")

    assert executed == ["close_app"]
    assert logged["status"] == "completed"
    assert "focus notepad and close" in capsys.readouterr().out.lower()


def test_run_oscar_bootstraps_then_continues_for_multi_step_tasks(
    monkeypatch: pytest.MonkeyPatch, tmp_path
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
    prompts: list[dict[str, object]] = []

    monkeypatch.setattr(oscar_main.config, "MAX_STEPS", 5)
    monkeypatch.setattr(oscar_main.config, "ACTION_DELAY", 0.0)
    monkeypatch.setattr(oscar_main.config, "APP_LAUNCH_DELAY", 0.0)
    monkeypatch.setattr(oscar_main.config, "WINDOW_FOCUS_TIMEOUT", 0.0)
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
    monkeypatch.setattr(oscar_main, "focus_app_window", _always_focus)
    monkeypatch.setattr(oscar_main, "app_window_exists", lambda _app_name: False)
    monkeypatch.setattr(oscar_main.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(oscar_main, "write_run_log", lambda **_kwargs: tmp_path / "run.json")

    oscar_main.run_oscar("open notepad and save the file")

    assert executed == ["open_app"]
    assert prompts[0]["active_window_title"] == "Untitled - Notepad"
    assert prompts[0]["active_process_name"] == "notepad.exe"
    assert prompts[0]["cursor_position"] == (100, 200)


def test_run_oscar_logs_failures_before_reraising(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    logged: dict[str, object] = {}

    monkeypatch.setattr(oscar_main.config, "MAX_STEPS", 3)
    monkeypatch.setattr(oscar_main.config, "ACTION_DELAY", 0.0)
    monkeypatch.setattr(oscar_main.config, "APP_LAUNCH_DELAY", 0.0)
    monkeypatch.setattr(oscar_main.config, "WINDOW_FOCUS_TIMEOUT", 0.0)
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
    monkeypatch.setattr(oscar_main, "focus_app_window", _always_focus)
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
