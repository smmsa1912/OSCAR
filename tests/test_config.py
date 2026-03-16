from __future__ import annotations

import importlib
import sys

import pytest


def _reload_config(monkeypatch: pytest.MonkeyPatch, **env: str):
    for key in [
        "GEMINI_API_KEY",
        "GEMINI_MODEL",
        "MAX_STEPS",
        "ACTION_DELAY",
        "APP_LAUNCH_DELAY",
        "WINDOW_FOCUS_TIMEOUT",
        "SAVE_DIALOG_DELAY",
        "FOCUS_SETTLE_DELAY",
        "TYPEWRITE_INTERVAL",
        "ENABLE_SCREENSHOT_GRID",
        "SCREENSHOT_GRID_INTERVAL",
        "ENABLE_CLICK_REFINEMENT",
        "CLICK_REFINEMENT_RADIUS",
        "CLICK_REFINEMENT_MAX_SHIFT",
        "TERMINAL_TIMEOUT_SECONDS",
        "TERMINAL_OUTPUT_LIMIT",
        "SCREENSHOT_REGION",
    ]:
        monkeypatch.setenv(key, "")

    for key, value in env.items():
        monkeypatch.setenv(key, value)

    sys.modules.pop("oscar.config", None)
    import oscar.config as config

    return importlib.reload(config)


def test_config_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _reload_config(monkeypatch)

    assert config.GEMINI_MODEL == "gemini-2.5-flash"
    assert config.MAX_STEPS == 20
    assert config.ACTION_DELAY == 0.5
    assert config.APP_LAUNCH_DELAY == 1.5
    assert config.WINDOW_FOCUS_TIMEOUT == 2.0
    assert config.SAVE_DIALOG_DELAY == 0.75
    assert config.FOCUS_SETTLE_DELAY == 0.35
    assert config.TYPEWRITE_INTERVAL == 0.07
    assert config.ENABLE_SCREENSHOT_GRID is True
    assert config.SCREENSHOT_GRID_INTERVAL == 100
    assert config.ENABLE_CLICK_REFINEMENT is True
    assert config.CLICK_REFINEMENT_RADIUS == 220
    assert config.CLICK_REFINEMENT_MAX_SHIFT == 90
    assert config.TERMINAL_TIMEOUT_SECONDS == 20.0
    assert config.TERMINAL_OUTPUT_LIMIT == 4000
    assert config.SCREENSHOT_REGION is None


def test_config_parses_values(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _reload_config(
        monkeypatch,
        GEMINI_API_KEY="secret-key",
        GEMINI_MODEL="custom-model",
        MAX_STEPS="5",
        ACTION_DELAY="1.25",
        APP_LAUNCH_DELAY="2.5",
        WINDOW_FOCUS_TIMEOUT="3.0",
        SAVE_DIALOG_DELAY="1.0",
        FOCUS_SETTLE_DELAY="0.4",
        TYPEWRITE_INTERVAL="0.12",
        ENABLE_SCREENSHOT_GRID="false",
        SCREENSHOT_GRID_INTERVAL="80",
        ENABLE_CLICK_REFINEMENT="no",
        CLICK_REFINEMENT_RADIUS="150",
        CLICK_REFINEMENT_MAX_SHIFT="45",
        TERMINAL_TIMEOUT_SECONDS="7.5",
        TERMINAL_OUTPUT_LIMIT="512",
        SCREENSHOT_REGION="10,20,640,480",
    )

    assert config.require_api_key() == "secret-key"
    assert config.GEMINI_MODEL == "custom-model"
    assert config.MAX_STEPS == 5
    assert config.ACTION_DELAY == 1.25
    assert config.APP_LAUNCH_DELAY == 2.5
    assert config.WINDOW_FOCUS_TIMEOUT == 3.0
    assert config.SAVE_DIALOG_DELAY == 1.0
    assert config.FOCUS_SETTLE_DELAY == 0.4
    assert config.TYPEWRITE_INTERVAL == 0.12
    assert config.ENABLE_SCREENSHOT_GRID is False
    assert config.SCREENSHOT_GRID_INTERVAL == 80
    assert config.ENABLE_CLICK_REFINEMENT is False
    assert config.CLICK_REFINEMENT_RADIUS == 150
    assert config.CLICK_REFINEMENT_MAX_SHIFT == 45
    assert config.TERMINAL_TIMEOUT_SECONDS == 7.5
    assert config.TERMINAL_OUTPUT_LIMIT == 512
    assert config.SCREENSHOT_REGION == (10, 20, 640, 480)


def test_require_api_key_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _reload_config(monkeypatch)

    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        config.require_api_key()




