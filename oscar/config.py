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
ENV_FILE = ROOT_DIR / ".env"
LOGS_DIR = ROOT_DIR / "logs"

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


def _enable_windows_dpi_awareness() -> None:
    if sys.platform != "win32":
        return

    try:
        import ctypes

        # Keep screenshot coordinates aligned with pointer coordinates on scaled displays.
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
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
MAX_STEPS = _parse_int("MAX_STEPS", 20)
ACTION_DELAY = _parse_float("ACTION_DELAY", 0.5)
APP_LAUNCH_DELAY = _parse_float("APP_LAUNCH_DELAY", 1.5)
SCREENSHOT_REGION = _parse_region(os.getenv("SCREENSHOT_REGION"))

_enable_windows_dpi_awareness()
_enable_pyautogui_failsafe()
