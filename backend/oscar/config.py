"""Configuration helpers for OSCAR."""

from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - fallback for limited environments

    def load_dotenv(*_args, **_kwargs) -> bool:
        return False


ROOT_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = ROOT_DIR  # Portable alias for cross-machine path resolution
ENV_FILE = ROOT_DIR / ".env"
LOGS_DIR = Path(os.path.expandvars(os.getenv("OSCAR_LOGS_DIR", str(ROOT_DIR / "logs")))).expanduser()
PLAYWRIGHT_STATE_DIR = Path(
    os.path.expandvars(os.getenv("PLAYWRIGHT_STATE_DIR", str(ROOT_DIR / ".playwright")))
).expanduser()
STATE_DIR = Path(
    os.path.expandvars(os.getenv("OSCAR_STATE_DIR", str(ROOT_DIR / ".oscar")))
).expanduser()
SESSION_MEMORY_PATH = STATE_DIR / "session_memory.json"

load_dotenv(ENV_FILE)


def _parse_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value.strip() == "":
        return default
    return int(raw_value)


def _parse_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value.strip() == "":
        return default
    return float(raw_value)


def _parse_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value.strip() == "":
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_region(value: str | None) -> tuple[int, int, int, int] | None:
    if value is None or value.strip() == "":
        return None

    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 4:
        raise ValueError("SCREENSHOT_REGION must have four comma-separated integers.")

    left, top, width, height = (int(part) for part in parts)
    if width <= 0 or height <= 0:
        raise ValueError("SCREENSHOT_REGION width and height must be positive.")

    return left, top, width, height


def require_api_key() -> str:
    """Return the configured Gemini API key or raise a clear error."""

    if not GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is not configured. Add it to your environment or .env file."
        )
    return GEMINI_API_KEY


def enable_windows_dpi_awareness() -> None:
    if sys.platform != "win32":
        return

    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            return


def _enable_pyautogui_failsafe() -> None:
    try:
        import pyautogui
    except Exception:  # pragma: no cover - platform/import specific
        return

    pyautogui.FAILSAFE = True


GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = (
    os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
)
MAX_STEPS = _parse_int("MAX_STEPS", 25)
ACTION_DELAY = _parse_float("ACTION_DELAY", 0.5)
APP_LAUNCH_DELAY = _parse_float("APP_LAUNCH_DELAY", 1.5)
WINDOW_FOCUS_TIMEOUT = _parse_float("WINDOW_FOCUS_TIMEOUT", 2.0)
SAVE_DIALOG_DELAY = _parse_float("SAVE_DIALOG_DELAY", 0.75)
FOCUS_SETTLE_DELAY = _parse_float("FOCUS_SETTLE_DELAY", 0.35)
TYPEWRITE_INTERVAL = _parse_float("TYPEWRITE_INTERVAL", 0.07)
ENABLE_SCREENSHOT_GRID = _parse_bool("ENABLE_SCREENSHOT_GRID", True)
SCREENSHOT_GRID_INTERVAL = _parse_int("SCREENSHOT_GRID_INTERVAL", 100)
ENABLE_CLICK_REFINEMENT = _parse_bool("ENABLE_CLICK_REFINEMENT", True)
CLICK_REFINEMENT_RADIUS = _parse_int("CLICK_REFINEMENT_RADIUS", 220)
CLICK_REFINEMENT_MAX_SHIFT = _parse_int("CLICK_REFINEMENT_MAX_SHIFT", 90)
TERMINAL_TIMEOUT_SECONDS = _parse_float("TERMINAL_TIMEOUT_SECONDS", 20.0)
TERMINAL_OUTPUT_LIMIT = _parse_int("TERMINAL_OUTPUT_LIMIT", 4000)
SCREENSHOT_REGION = _parse_region(os.getenv("SCREENSHOT_REGION"))
PLAYWRIGHT_HEADLESS = _parse_bool("PLAYWRIGHT_HEADLESS", False)
PLAYWRIGHT_TIMEOUT_SECONDS = _parse_float("PLAYWRIGHT_TIMEOUT_SECONDS", 10.0)
LOG_LEVEL = (os.getenv("OSCAR_LOG_LEVEL", "INFO").strip() or "INFO").upper()
RETRY_INITIAL_INTERVAL_SECONDS = _parse_float("RETRY_INITIAL_INTERVAL_SECONDS", 0.05)
RETRY_MAX_INTERVAL_SECONDS = _parse_float("RETRY_MAX_INTERVAL_SECONDS", 0.5)
RETRY_BACKOFF_FACTOR = _parse_float("RETRY_BACKOFF_FACTOR", 1.6)
PLAYWRIGHT_MANAGED_PROFILE_DIR = Path(
    os.path.expandvars(
        os.getenv(
            "PLAYWRIGHT_MANAGED_PROFILE_DIR",
            str(PLAYWRIGHT_STATE_DIR / "managed-profile"),
        )
    )
).expanduser()
NATIVE_BROWSER_ENABLED = _parse_bool("NATIVE_BROWSER_ENABLED", True)
DEFAULT_DESKTOP_BROWSER = (
    os.getenv("DEFAULT_DESKTOP_BROWSER", "chrome").strip() or "chrome"
)
MAX_ROUTE_ATTEMPTS = _parse_int("MAX_ROUTE_ATTEMPTS", 4)
ROUTE_FAILURE_PENALTY = _parse_int("ROUTE_FAILURE_PENALTY", 40)

# Vision grid overlay dimensions (alphanumeric A1..J10 by default)
GRID_ROWS = _parse_int("GRID_ROWS", 10)
GRID_COLS = _parse_int("GRID_COLS", 10)

enable_windows_dpi_awareness()
_enable_pyautogui_failsafe()
