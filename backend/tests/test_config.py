from __future__ import annotations

import importlib
import sys

import pytest


def _reload_config(monkeypatch: pytest.MonkeyPatch, **env: str):
    for key in [
        "GEMINI_API_KEY",
        "GEMINI_MODEL",
        "LLM_PROVIDER",
        "GEMINI_TIMEOUT_SECONDS",
        "OMNIROUTE_BASE_URL",
        "OMNIROUTE_API_KEY",
        "OMNIROUTE_MODEL",
        "OMNIROUTE_TIMEOUT_SECONDS",
        "OMNIROUTE_MAX_PROMPT_CHARS",
        "OMNIROUTE_MAX_OUTPUT_TOKENS",
        "OMNIROUTE_MAX_REQUEST_TOKENS",
        "OMNIROUTE_MAX_TASK_TOKENS",
        "OMNIROUTE_MAX_DAILY_TOKENS",
        "OMNIROUTE_MAX_IMAGE_DIMENSION",
        "OMNIROUTE_AUTO_ROUTING",
        "OMNIROUTE_MODEL_FAST",
        "OMNIROUTE_MODEL_REASONING",
        "OMNIROUTE_MODEL_VISION",
        "OMNIROUTE_MODEL_FALLBACK",
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
        "PLAYWRIGHT_HEADLESS",
        "PLAYWRIGHT_TIMEOUT_SECONDS",
        "PLAYWRIGHT_MANAGED_PROFILE_DIR",
        "OSCAR_LOG_LEVEL",
        "RETRY_INITIAL_INTERVAL_SECONDS",
        "RETRY_MAX_INTERVAL_SECONDS",
        "RETRY_BACKOFF_FACTOR",
        "NATIVE_BROWSER_ENABLED",
        "DEFAULT_DESKTOP_BROWSER",
        "MAX_ROUTE_ATTEMPTS",
        "ROUTE_FAILURE_PENALTY",
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
    assert config.LLM_PROVIDER == "gemini"
    assert config.GEMINI_TIMEOUT_SECONDS == 60.0
    assert config.OMNIROUTE_BASE_URL == "http://localhost:8080/v1"
    assert config.OMNIROUTE_API_KEY == ""
    assert config.OMNIROUTE_MODEL == "auto/best-fast"
    assert config.OMNIROUTE_MODEL_FAST == "auto/best-fast"
    assert config.OMNIROUTE_MODEL_REASONING == "auto/best-reasoning"
    assert config.OMNIROUTE_MODEL_VISION == "auto/best-vision"
    assert config.OMNIROUTE_MODEL_FALLBACK == "auto/best-fast"
    assert config.OMNIROUTE_TIMEOUT_SECONDS == 45.0
    assert config.OMNIROUTE_MAX_PROMPT_CHARS == 7000
    assert config.OMNIROUTE_MAX_OUTPUT_TOKENS == 350
    assert config.OMNIROUTE_MAX_REQUEST_TOKENS == 5000
    assert config.OMNIROUTE_MAX_TASK_TOKENS == 20000
    assert config.OMNIROUTE_MAX_DAILY_TOKENS == 30000
    assert config.OMNIROUTE_MAX_IMAGE_DIMENSION == 1024
    assert config.MAX_STEPS == 25
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
    assert config.PLAYWRIGHT_HEADLESS is False
    assert config.PLAYWRIGHT_TIMEOUT_SECONDS == 10.0
    assert config.LOG_LEVEL == "INFO"
    assert config.RETRY_INITIAL_INTERVAL_SECONDS == 0.05
    assert config.RETRY_MAX_INTERVAL_SECONDS == 0.5
    assert config.RETRY_BACKOFF_FACTOR == 1.6
    assert config.NATIVE_BROWSER_ENABLED is True
    assert config.DEFAULT_DESKTOP_BROWSER == "chrome"
    assert config.MAX_ROUTE_ATTEMPTS == 4
    assert config.ROUTE_FAILURE_PENALTY == 40


def test_config_parses_values(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _reload_config(
        monkeypatch,
        GEMINI_API_KEY="secret-key",
        GEMINI_MODEL="custom-model",
        LLM_PROVIDER="omniroute",
        GEMINI_TIMEOUT_SECONDS="12.5",
        OMNIROUTE_BASE_URL="http://127.0.0.1:8080/v1/",
        OMNIROUTE_API_KEY="route-secret",
        OMNIROUTE_MODEL="test-model",
        OMNIROUTE_TIMEOUT_SECONDS="25",
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
        PLAYWRIGHT_HEADLESS="true",
        PLAYWRIGHT_TIMEOUT_SECONDS="12.5",
        OSCAR_LOG_LEVEL="debug",
        RETRY_INITIAL_INTERVAL_SECONDS="0.1",
        RETRY_MAX_INTERVAL_SECONDS="0.9",
        RETRY_BACKOFF_FACTOR="2.0",
        NATIVE_BROWSER_ENABLED="false",
        DEFAULT_DESKTOP_BROWSER="microsoft edge",
        MAX_ROUTE_ATTEMPTS="6",
        ROUTE_FAILURE_PENALTY="55",
    )

    assert config.require_api_key() == "secret-key"
    assert config.GEMINI_MODEL == "custom-model"
    assert config.LLM_PROVIDER == "omniroute"
    assert config.GEMINI_TIMEOUT_SECONDS == 12.5
    assert config.OMNIROUTE_BASE_URL == "http://127.0.0.1:8080/v1"
    assert config.OMNIROUTE_API_KEY == "route-secret"
    assert config.OMNIROUTE_MODEL == "test-model"
    assert config.OMNIROUTE_TIMEOUT_SECONDS == 25.0
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
    assert config.PLAYWRIGHT_HEADLESS is True
    assert config.PLAYWRIGHT_TIMEOUT_SECONDS == 12.5
    assert config.LOG_LEVEL == "DEBUG"
    assert config.RETRY_INITIAL_INTERVAL_SECONDS == 0.1
    assert config.RETRY_MAX_INTERVAL_SECONDS == 0.9
    assert config.RETRY_BACKOFF_FACTOR == 2.0
    assert config.NATIVE_BROWSER_ENABLED is False
    assert config.DEFAULT_DESKTOP_BROWSER == "microsoft edge"
    assert config.MAX_ROUTE_ATTEMPTS == 6
    assert config.ROUTE_FAILURE_PENALTY == 55


def test_require_api_key_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _reload_config(monkeypatch)

    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        config.require_api_key()


@pytest.mark.parametrize(
    ("setting", "value", "message"),
    [
        ("MAX_STEPS", "0", "MAX_STEPS must be >= 1"),
        ("MAX_STEPS", "many", "MAX_STEPS must be an integer"),
        ("TERMINAL_TIMEOUT_SECONDS", "-1", "TERMINAL_TIMEOUT_SECONDS must be >= 0.1"),
        ("TERMINAL_OUTPUT_LIMIT", "999999999", "TERMINAL_OUTPUT_LIMIT must be <= 1000000"),
        ("RETRY_BACKOFF_FACTOR", "0.5", "RETRY_BACKOFF_FACTOR must be >= 1.0"),
        ("PLAYWRIGHT_TIMEOUT_SECONDS", "nan", "must be a finite number"),
        ("GEMINI_TIMEOUT_SECONDS", "0", "GEMINI_TIMEOUT_SECONDS must be >= 0.1"),
        ("OMNIROUTE_TIMEOUT_SECONDS", "700", "OMNIROUTE_TIMEOUT_SECONDS must be <= 600"),
    ],
)
def test_config_rejects_invalid_numeric_ranges(
    monkeypatch: pytest.MonkeyPatch, setting: str, value: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _reload_config(monkeypatch, **{setting: value})


def test_config_rejects_invalid_boolean(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="ENABLE_SCREENSHOT_GRID must be a boolean"):
        _reload_config(monkeypatch, ENABLE_SCREENSHOT_GRID="sometimes")


def test_config_rejects_unknown_log_level(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="OSCAR_LOG_LEVEL must be one of"):
        _reload_config(monkeypatch, OSCAR_LOG_LEVEL="TRACEISH")


def test_config_rejects_retry_max_below_initial(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="RETRY_MAX_INTERVAL_SECONDS must be greater than or equal"):
        _reload_config(
            monkeypatch,
            RETRY_INITIAL_INTERVAL_SECONDS="2",
            RETRY_MAX_INTERVAL_SECONDS="1",
        )


def test_config_rejects_unknown_llm_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="LLM_PROVIDER must be either"):
        _reload_config(monkeypatch, LLM_PROVIDER="unknown-provider")
