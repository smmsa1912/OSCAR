"""Configuration helpers for OSCAR."""

from __future__ import annotations

import math
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

# Load .env before resolving path overrides so path settings behave like the
# other configuration values below. Real process environment values still win.
load_dotenv(ENV_FILE)

LOGS_DIR = Path(
    os.path.expandvars(os.getenv("OSCAR_LOGS_DIR", "").strip() or str(ROOT_DIR / "logs"))
).expanduser()
PLAYWRIGHT_STATE_DIR = Path(
    os.path.expandvars(os.getenv("PLAYWRIGHT_STATE_DIR", "").strip() or str(ROOT_DIR / ".playwright"))
).expanduser()
STATE_DIR = Path(
    os.path.expandvars(os.getenv("OSCAR_STATE_DIR", "").strip() or str(ROOT_DIR / ".oscar"))
).expanduser()
SESSION_MEMORY_PATH = STATE_DIR / "session_memory.json"


def _raw_value(name: str) -> str | None:
    raw_value = os.getenv(name)
    return raw_value.strip() if raw_value is not None else None


def _parse_int(
    name: str,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    raw_value = _raw_value(name)
    if not raw_value:
        value = default
    else:
        try:
            value = int(raw_value)
        except ValueError as exc:
            raise ValueError(f"{name} must be an integer; received {raw_value!r}.") from exc

    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum}; received {value}.")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be <= {maximum}; received {value}.")
    return value


def _parse_float(
    name: str,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    raw_value = _raw_value(name)
    if not raw_value:
        value = default
    else:
        try:
            value = float(raw_value)
        except ValueError as exc:
            raise ValueError(f"{name} must be a number; received {raw_value!r}.") from exc

    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number; received {value!r}.")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum}; received {value}.")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be <= {maximum}; received {value}.")
    return value


def _parse_bool(name: str, default: bool) -> bool:
    raw_value = _raw_value(name)
    if not raw_value:
        return default
    normalized = raw_value.lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(
        f"{name} must be a boolean (true/false, yes/no, on/off, or 1/0); "
        f"received {raw_value!r}."
    )


# When enabled, action executors report intended actions without performing them.
OSCAR_DRY_RUN = _parse_bool("OSCAR_DRY_RUN", False)


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


LLM_PROVIDER = (os.getenv("LLM_PROVIDER", "gemini").strip() or "gemini").lower()
if LLM_PROVIDER not in {"gemini", "omniroute", "freellmapi"}:
    raise ValueError("LLM_PROVIDER must be one of 'gemini', 'omniroute', or 'freellmapi'.")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = (
    os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
)
GEMINI_TIMEOUT_SECONDS = _parse_float(
    "GEMINI_TIMEOUT_SECONDS", 60.0, minimum=0.1, maximum=600
)
# Direct FreeLLMAPI OpenAI-compatible endpoint. This is independent of OmniRoute.
FREELLMAPI_BASE_URL = (
    os.getenv("FREELLMAPI_BASE_URL", "http://127.0.0.1:31415/v1").strip().rstrip("/")
    or "http://127.0.0.1:31415/v1"
)
FREELLMAPI_API_KEY = os.getenv("FREELLMAPI_API_KEY", "").strip()
FREELLMAPI_MODEL = os.getenv("FREELLMAPI_MODEL", "auto").strip() or "auto"
# FreeLLMAPI's own `auto` router chooses from its active chain, which includes vision models.
FREELLMAPI_VISION_MODEL = os.getenv("FREELLMAPI_VISION_MODEL", "auto").strip() or "auto"
FREELLMAPI_TIMEOUT_SECONDS = _parse_float(
    "FREELLMAPI_TIMEOUT_SECONDS", 45.0, minimum=0.1, maximum=600
)
# Keep FreeLLMAPI request sizing independent from the similarly named OmniRoute
# controls. The full shared system prompt is large, so its cap must account for
# system instructions, bounded task context, optional screenshot, and output.
FREELLMAPI_MAX_PROMPT_CHARS = _parse_int(
    "FREELLMAPI_MAX_PROMPT_CHARS", 5000, minimum=1000, maximum=100000
)
FREELLMAPI_MAX_OUTPUT_TOKENS = _parse_int(
    "FREELLMAPI_MAX_OUTPUT_TOKENS", 350, minimum=64, maximum=8192
)
FREELLMAPI_MAX_REQUEST_TOKENS = _parse_int(
    "FREELLMAPI_MAX_REQUEST_TOKENS", 8000, minimum=512, maximum=32000
)
FREELLMAPI_MAX_IMAGE_DIMENSION = _parse_int(
    "FREELLMAPI_MAX_IMAGE_DIMENSION", 1024, minimum=256, maximum=4096
)
OMNIROUTE_BASE_URL = (
    os.getenv("OMNIROUTE_BASE_URL", "").strip().rstrip("/")
    or "http://localhost:8080/v1"
)
OMNIROUTE_API_KEY = os.getenv("OMNIROUTE_API_KEY", "").strip()
# These gateway-specific presets may need changing to IDs exposed by /models.
# Gemini remains the global default; these only apply when OmniRoute is selected.
OMNIROUTE_MODEL = os.getenv("OMNIROUTE_MODEL", "auto/best-fast").strip() or "auto/best-fast"
OMNIROUTE_AUTO_ROUTING = _parse_bool("OMNIROUTE_AUTO_ROUTING", True)
OMNIROUTE_MODEL_FAST = os.getenv("OMNIROUTE_MODEL_FAST", "auto/best-fast").strip() or "auto/best-fast"
OMNIROUTE_MODEL_REASONING = os.getenv("OMNIROUTE_MODEL_REASONING", "auto/best-reasoning").strip() or "auto/best-reasoning"
OMNIROUTE_MODEL_VISION = os.getenv("OMNIROUTE_MODEL_VISION", "auto/best-vision").strip() or "auto/best-vision"
OMNIROUTE_MODEL_FALLBACK = os.getenv("OMNIROUTE_MODEL_FALLBACK", "auto/best-fast").strip() or "auto/best-fast"
OMNIROUTE_TIMEOUT_SECONDS = _parse_float(
    "OMNIROUTE_TIMEOUT_SECONDS", 45.0, minimum=0.1, maximum=600
)
# Cost controls: prompt truncation, response ceiling, per-request reservation,
# and a per-task budget. Estimates are conservative; provider usage wins if returned.
OMNIROUTE_MAX_PROMPT_CHARS = _parse_int(
    "OMNIROUTE_MAX_PROMPT_CHARS", 7000, minimum=1000, maximum=100000
)
OMNIROUTE_MAX_OUTPUT_TOKENS = _parse_int(
    "OMNIROUTE_MAX_OUTPUT_TOKENS", 350, minimum=64, maximum=8192
)
OMNIROUTE_MAX_REQUEST_TOKENS = _parse_int(
    "OMNIROUTE_MAX_REQUEST_TOKENS", 5000, minimum=512, maximum=32000
)
OMNIROUTE_MAX_TASK_TOKENS = _parse_int(
    "OMNIROUTE_MAX_TASK_TOKENS", 20000, minimum=1000, maximum=1_000_000
)
OMNIROUTE_MAX_DAILY_TOKENS = _parse_int(
    "OMNIROUTE_MAX_DAILY_TOKENS", 30000, minimum=1000, maximum=5_000_000
)
OMNIROUTE_MAX_IMAGE_DIMENSION = _parse_int(
    "OMNIROUTE_MAX_IMAGE_DIMENSION", 1024, minimum=256, maximum=4096
)
MAX_STEPS = _parse_int("MAX_STEPS", 25, minimum=1, maximum=500)
ACTION_DELAY = _parse_float("ACTION_DELAY", 0.5, minimum=0, maximum=300)
APP_LAUNCH_DELAY = _parse_float("APP_LAUNCH_DELAY", 1.5, minimum=0, maximum=300)
WINDOW_FOCUS_TIMEOUT = _parse_float("WINDOW_FOCUS_TIMEOUT", 2.0, minimum=0.1, maximum=300)
SAVE_DIALOG_DELAY = _parse_float("SAVE_DIALOG_DELAY", 0.75, minimum=0, maximum=300)
FOCUS_SETTLE_DELAY = _parse_float("FOCUS_SETTLE_DELAY", 0.35, minimum=0, maximum=300)
TYPEWRITE_INTERVAL = _parse_float("TYPEWRITE_INTERVAL", 0.07, minimum=0, maximum=10)
ENABLE_SCREENSHOT_GRID = _parse_bool("ENABLE_SCREENSHOT_GRID", True)
SCREENSHOT_GRID_INTERVAL = _parse_int("SCREENSHOT_GRID_INTERVAL", 100, minimum=1, maximum=1000)
ENABLE_CLICK_REFINEMENT = _parse_bool("ENABLE_CLICK_REFINEMENT", True)
CLICK_REFINEMENT_RADIUS = _parse_int("CLICK_REFINEMENT_RADIUS", 220, minimum=1, maximum=5000)
CLICK_REFINEMENT_MAX_SHIFT = _parse_int("CLICK_REFINEMENT_MAX_SHIFT", 90, minimum=0, maximum=2000)
TERMINAL_TIMEOUT_SECONDS = _parse_float("TERMINAL_TIMEOUT_SECONDS", 20.0, minimum=0.1, maximum=600)
TERMINAL_OUTPUT_LIMIT = _parse_int("TERMINAL_OUTPUT_LIMIT", 4000, minimum=128, maximum=1_000_000)
SCREENSHOT_REGION = _parse_region(os.getenv("SCREENSHOT_REGION"))
PLAYWRIGHT_HEADLESS = _parse_bool("PLAYWRIGHT_HEADLESS", False)
PLAYWRIGHT_TIMEOUT_SECONDS = _parse_float("PLAYWRIGHT_TIMEOUT_SECONDS", 10.0, minimum=0.1, maximum=600)
LOG_LEVEL = (os.getenv("OSCAR_LOG_LEVEL", "INFO").strip() or "INFO").upper()
if LOG_LEVEL not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
    raise ValueError(
        "OSCAR_LOG_LEVEL must be one of CRITICAL, ERROR, WARNING, INFO, DEBUG; "
        f"received {LOG_LEVEL!r}."
    )
RETRY_INITIAL_INTERVAL_SECONDS = _parse_float("RETRY_INITIAL_INTERVAL_SECONDS", 0.05, minimum=0.001, maximum=60)
RETRY_MAX_INTERVAL_SECONDS = _parse_float("RETRY_MAX_INTERVAL_SECONDS", 0.5, minimum=0.001, maximum=300)
RETRY_BACKOFF_FACTOR = _parse_float("RETRY_BACKOFF_FACTOR", 1.6, minimum=1.0, maximum=10)
if RETRY_MAX_INTERVAL_SECONDS < RETRY_INITIAL_INTERVAL_SECONDS:
    raise ValueError(
        "RETRY_MAX_INTERVAL_SECONDS must be greater than or equal to "
        "RETRY_INITIAL_INTERVAL_SECONDS."
    )
PLAYWRIGHT_MANAGED_PROFILE_DIR = Path(
    os.path.expandvars(
        os.getenv("PLAYWRIGHT_MANAGED_PROFILE_DIR", "").strip()
        or str(PLAYWRIGHT_STATE_DIR / "managed-profile")
    )
).expanduser()
NATIVE_BROWSER_ENABLED = _parse_bool("NATIVE_BROWSER_ENABLED", True)
DEFAULT_DESKTOP_BROWSER = (
    os.getenv("DEFAULT_DESKTOP_BROWSER", "chrome").strip() or "chrome"
)
MAX_ROUTE_ATTEMPTS = _parse_int("MAX_ROUTE_ATTEMPTS", 4, minimum=1, maximum=50)
ROUTE_FAILURE_PENALTY = _parse_int("ROUTE_FAILURE_PENALTY", 40, minimum=0, maximum=1000)

# Vision grid overlay dimensions (alphanumeric A1..J10 by default)
GRID_ROWS = _parse_int("GRID_ROWS", 10, minimum=1, maximum=50)
GRID_COLS = _parse_int("GRID_COLS", 10, minimum=1, maximum=50)

enable_windows_dpi_awareness()
_enable_pyautogui_failsafe()
