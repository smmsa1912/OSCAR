from __future__ import annotations

from pathlib import Path

import pytest

from oscar import main as oscar_main


def test_run_oscar_bootstraps_simple_open_app_tasks(
    monkeypatch: pytest.MonkeyPatch, tmp_path, capsys
) -> None:
    executed: list[str] = []
    logged: dict[str, object] = {}
    sleeps: list[float] = []

    monkeypatch.setattr(oscar_main.config, "ACTION_DELAY", 0.0)
    monkeypatch.setattr(oscar_main.config, "APP_LAUNCH_DELAY", 1.5)
    monkeypatch.setattr(oscar_main, "validate_action", lambda action, screen_size=None: action)
    monkeypatch.setattr(oscar_main, "execute_action", lambda action: executed.append(action["action"]))
    monkeypatch.setattr(
        oscar_main,
        "ask_gemini",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Gemini should not be called")),
    )
    monkeypatch.setattr(oscar_main.time, "sleep", lambda seconds: sleeps.append(seconds))

    def fake_write_run_log(**kwargs):
        logged.update(kwargs)
        path = tmp_path / "run.json"
        path.write_text("{}", encoding="utf-8")
        return path

    monkeypatch.setattr(oscar_main, "write_run_log", fake_write_run_log)

    log_path = oscar_main.run_oscar("open notepad")

    assert log_path == tmp_path / "run.json"
    assert executed == ["open_app"]
    assert sleeps == [1.5]
    assert logged["status"] == "completed"
    assert len(logged["history"]) == 2
    output = capsys.readouterr().out
    assert "Launch notepad directly" in output
    assert "Task completed!" in output


def test_run_oscar_bootstraps_open_and_type_tasks(
    monkeypatch: pytest.MonkeyPatch, tmp_path, capsys
) -> None:
    executed: list[str] = []
    logged: dict[str, object] = {}
    sleeps: list[float] = []

    monkeypatch.setattr(oscar_main.config, "ACTION_DELAY", 0.25)
    monkeypatch.setattr(oscar_main.config, "APP_LAUNCH_DELAY", 1.5)
    monkeypatch.setattr(oscar_main, "validate_action", lambda action, screen_size=None: action)
    monkeypatch.setattr(oscar_main, "execute_action", lambda action: executed.append(action["action"]))
    monkeypatch.setattr(
        oscar_main,
        "ask_gemini",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Gemini should not be called")),
    )
    monkeypatch.setattr(oscar_main.time, "sleep", lambda seconds: sleeps.append(seconds))

    def fake_write_run_log(**kwargs):
        logged.update(kwargs)
        path = tmp_path / "run.json"
        path.write_text("{}", encoding="utf-8")
        return path

    monkeypatch.setattr(oscar_main, "write_run_log", fake_write_run_log)

    log_path = oscar_main.run_oscar("open notepad and type Hello World")

    assert log_path == tmp_path / "run.json"
    assert executed == ["open_app", "type"]
    assert sleeps == [1.5, 0.25]
    assert logged["status"] == "completed"
    assert len(logged["history"]) == 3
    output = capsys.readouterr().out
    assert "Launch notepad directly" in output
    assert "Type the requested text into notepad" in output
    assert "Task completed!" in output


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
    prompts: list[str] = []

    monkeypatch.setattr(oscar_main.config, "MAX_STEPS", 5)
    monkeypatch.setattr(oscar_main.config, "ACTION_DELAY", 0.0)
    monkeypatch.setattr(oscar_main.config, "APP_LAUNCH_DELAY", 1.5)
    monkeypatch.setattr(oscar_main.config, "SCREENSHOT_REGION", None)
    monkeypatch.setattr(oscar_main.config, "GEMINI_MODEL", "test-model")
    monkeypatch.setattr(oscar_main, "capture_screenshot", lambda _region=None: (object(), (800, 600)))
    monkeypatch.setattr(
        oscar_main,
        "build_prompt",
        lambda *args, **kwargs: prompts.append("prompt") or "prompt",
    )
    monkeypatch.setattr(oscar_main, "ask_gemini", lambda *_args, **_kwargs: next(actions))
    monkeypatch.setattr(oscar_main, "validate_action", lambda action, screen_size=None: action)
    monkeypatch.setattr(oscar_main, "execute_action", lambda action: executed.append(action["action"]))
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
    assert prompts == ["prompt"]
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
    monkeypatch.setattr(oscar_main.config, "SCREENSHOT_REGION", None)
    monkeypatch.setattr(oscar_main.config, "GEMINI_MODEL", "test-model")
    monkeypatch.setattr(oscar_main, "capture_screenshot", lambda _region=None: (object(), (800, 600)))
    monkeypatch.setattr(oscar_main, "build_prompt", lambda *args, **kwargs: "prompt")
    monkeypatch.setattr(oscar_main, "ask_gemini", lambda *_args, **_kwargs: next(actions))
    monkeypatch.setattr(oscar_main, "validate_action", lambda action, screen_size=None: action)
    monkeypatch.setattr(oscar_main, "execute_action", lambda action: executed.append(action["action"]))
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
    monkeypatch.setattr(oscar_main.config, "SCREENSHOT_REGION", None)
    monkeypatch.setattr(oscar_main, "capture_screenshot", lambda _region=None: (object(), (800, 600)))
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
    monkeypatch.setattr(oscar_main.config, "SCREENSHOT_REGION", None)
    monkeypatch.setattr(oscar_main, "capture_screenshot", lambda _region=None: (object(), (800, 600)))
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
