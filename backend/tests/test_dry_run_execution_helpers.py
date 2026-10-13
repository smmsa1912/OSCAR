from __future__ import annotations

from pathlib import Path

import pytest

from oscar import config
from oscar.execution.files import execute_open_file, execute_save_file
from oscar.execution.windows import execute_focus_app, execute_open_app, execute_window_hotkey_action


def test_open_file_dry_run_does_not_launch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config, "OSCAR_DRY_RUN", True)
    launched: list[list[str]] = []
    result = execute_open_file(
        {"file_path": str(tmp_path / "notes.txt")},
        rewrite_known_user_paths=lambda value: value,
        build_launch_command=lambda *_args, **_kwargs: ([], object()),
        launch_process=lambda command, error_message: launched.append(command),
        wait_for_condition=lambda *_args, **_kwargs: True,
        default_retry_policy=lambda _timeout: object(),
        focus_app_window=lambda *_args, **_kwargs: True,
        app_window_exists=lambda _app: True,
        app_launch_delay=0.0,
        platform_name="win32",
    )
    assert result["dry_run"] is True
    assert result["execution_confirmed"] is False
    assert launched == []


def test_save_file_dry_run_does_not_create_directory_or_type(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config, "OSCAR_DRY_RUN", True)
    target = tmp_path / "not-created" / "notes.txt"
    result = execute_save_file(
        {"file_path": str(target)},
        error_cls=RuntimeError,
        rewrite_known_user_paths=lambda value: value,
        get_pyautogui=lambda: pytest.fail("pyautogui must not be loaded in dry-run"),
        get_active_window_info=lambda: pytest.fail("window inspection must not happen in dry-run"),
        wait_for_condition=lambda *_args, **_kwargs: pytest.fail("must not wait in dry-run"),
        default_retry_policy=lambda _timeout: object(),
        save_dialog_is_ready=lambda _window: False,
        type_interval=0.0,
        save_dialog_delay=0.0,
    )
    assert result["dry_run"] is True
    assert not target.parent.exists()


def test_focus_app_dry_run_does_not_inspect_or_focus(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "OSCAR_DRY_RUN", True)
    result = execute_focus_app(
        {"app_name": "notepad"},
        error_cls=RuntimeError,
        app_window_exists=lambda _app: pytest.fail("must not inspect windows in dry-run"),
        focus_app_window=lambda *_args, **_kwargs: pytest.fail("must not focus in dry-run"),
        get_active_window_info=lambda: pytest.fail("must not inspect active window in dry-run"),
        window_focus_timeout=1.0,
    )
    assert result["dry_run"] is True
    assert result["execution_confirmed"] is False


def test_open_app_dry_run_does_not_launch_or_focus(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "OSCAR_DRY_RUN", True)
    result = execute_open_app(
        {"app_name": "notepad"},
        error_cls=RuntimeError,
        app_window_exists=lambda _app: pytest.fail("must not inspect windows in dry-run"),
        focus_app_window=lambda *_args, **_kwargs: pytest.fail("must not focus in dry-run"),
        build_launch_command=lambda *_args, **_kwargs: pytest.fail("must not build launch command in dry-run"),
        wait_for_condition=lambda *_args, **_kwargs: pytest.fail("must not wait in dry-run"),
        default_retry_policy=lambda _timeout: object(),
        launch_process=lambda *_args, **_kwargs: pytest.fail("must not launch in dry-run"),
        app_launch_delay=0.0,
        window_focus_timeout=1.0,
        get_pyautogui=lambda: pytest.fail("must not load pyautogui in dry-run"),
    )
    assert result["dry_run"] is True
    assert result["execution_confirmed"] is False


def test_window_hotkey_dry_run_does_not_focus_or_send_hotkey(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "OSCAR_DRY_RUN", True)
    result = execute_window_hotkey_action(
        {"action": "close_app", "app_name": "notepad"},
        error_cls=RuntimeError,
        app_window_exists=lambda _app: pytest.fail("must not inspect windows in dry-run"),
        focus_app_window=lambda *_args, **_kwargs: pytest.fail("must not focus in dry-run"),
        get_active_window_info=lambda: pytest.fail("must not inspect active window in dry-run"),
        is_protected_control_window=lambda _window: False,
        is_oscar_app_name=lambda _app: False,
        get_pyautogui=lambda: pytest.fail("must not load pyautogui in dry-run"),
        window_focus_timeout=1.0,
    )
    assert result["dry_run"] is True
    assert result["execution_confirmed"] is False
