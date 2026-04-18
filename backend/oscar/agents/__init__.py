"""Route executors for OSCAR."""

from oscar.agents.browser_agent import BrowserAgent
from oscar.agents.shortcut_handler import ShortcutHandler
from oscar.agents.terminal_agent import TerminalAgent
from oscar.agents.ui_agent import UIAgent

__all__ = ["BrowserAgent", "ShortcutHandler", "TerminalAgent", "UIAgent"]
