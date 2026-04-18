"""Browser session configuration for Playwright-backed automation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from oscar import config


@dataclass(frozen=True)
class BrowserSessionConfig:
    """Launch configuration for a browser session."""

    session_mode: str = "managed"
    browser_name: str = "chromium"
    profile_name: str | None = None
    headless: bool = config.PLAYWRIGHT_HEADLESS
    timeout_seconds: float = config.PLAYWRIGHT_TIMEOUT_SECONDS
    managed_profile_dir: Path = config.PLAYWRIGHT_MANAGED_PROFILE_DIR
