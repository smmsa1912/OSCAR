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
    assert config.SCREENSHOT_REGION == (10, 20, 640, 480)


def test_require_api_key_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _reload_config(monkeypatch)

    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        config.require_api_key()
