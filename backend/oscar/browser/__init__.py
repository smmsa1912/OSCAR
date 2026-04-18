"""Browser automation helpers for OSCAR."""

from oscar.browser.browser_session import BrowserSessionConfig
from oscar.browser.playwright_controller import PlaywrightController
from oscar.browser.selector_resolver import SelectorResolver

__all__ = ["BrowserSessionConfig", "PlaywrightController", "SelectorResolver"]
