"""Named shortcut executor for fast OS and browser flows."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import anyio

from oscar import config
from oscar.runtime import ActionResult
from oscar.user_paths import get_known_user_paths
from oscar.window_control import focus_app_window


class ShortcutHandler:
    """Execute named shortcuts instead of planner-authored raw key lists."""

    SHORTCUTS: dict[str, tuple[str, ...]] = {
        "os.open_explorer": ("winleft", "e"),
        "os.open_settings": ("winleft", "i"),
        "os.open_task_manager": ("ctrl", "shift", "esc"),
        "os.search": ("winleft", "s"),
        "os.run": ("winleft", "r"),
        "os.show_desktop": ("winleft", "d"),
        "os.lock_screen": ("winleft", "l"),
        "os.snap_left": ("winleft", "left"),
        "os.snap_right": ("winleft", "right"),
        "os.snap_up": ("winleft", "up"),
        "os.snap_down": ("winleft", "down"),
        "os.take_screenshot": (),
        "app.close_current": ("alt", "f4"),
        "app.task_manager": ("ctrl", "shift", "esc"),
        "browser.focus_address_bar": ("ctrl", "l"),
        "browser.new_tab": ("ctrl", "t"),
        "browser.close_tab": ("ctrl", "w"),
        "browser.find": ("ctrl", "f"),
        "browser.history": ("ctrl", "h"),
        "browser.downloads": ("ctrl", "j"),
    }

    def _get_pyautogui(self):
        try:
            import pyautogui
        except Exception as exc:  # pragma: no cover - dependency/platform specific
            raise RuntimeError("pyautogui is required for shortcut execution.") from exc
        return pyautogui

    async def run(self, action: dict[str, Any]) -> ActionResult:
        shortcut_name = str(action.get("shortcut_name") or "")
        if config.OSCAR_DRY_RUN:
            return ActionResult(
                success=True,
                route="shortcut",
                action="shortcut",
                confidence=1.0,
                data={
                    "dry_run": True,
                    "execution_confirmed": False,
                    "would_execute": shortcut_name,
                    "message": "Dry-run enabled; no shortcut or screenshot was executed.",
                },
                retryable=False,
            )
        keys = self.SHORTCUTS.get(shortcut_name)
        if keys is None:
            return ActionResult(
                success=False,
                route="shortcut",
                action="shortcut",
                confidence=0.1,
                failure_reason=f"Unknown shortcut '{shortcut_name}'.",
                retryable=False,
            )
        if shortcut_name == "os.take_screenshot":
            return await self._take_screenshot(shortcut_name)
        target_app = action.get("target_app")
        if target_app and action.get("ensure_focus"):
            await anyio.to_thread.run_sync(focus_app_window, str(target_app))
        pyautogui = self._get_pyautogui()
        try:
            await anyio.to_thread.run_sync(lambda: pyautogui.hotkey(*keys))
            if shortcut_name == "browser.find" and action.get("text"):
                await anyio.sleep(0)
                await anyio.to_thread.run_sync(
                    lambda: pyautogui.typewrite(str(action["text"]))
                )
                await anyio.to_thread.run_sync(lambda: pyautogui.press("enter"))
        except Exception as exc:
            return ActionResult(
                success=False,
                route="shortcut",
                action="shortcut",
                confidence=0.2,
                failure_reason=str(exc),
                retryable=True,
                data={"shortcut_name": shortcut_name},
            )
        return ActionResult(
            success=True,
            route="shortcut",
            action="shortcut",
            confidence=0.85,
            data={"shortcut_name": shortcut_name, "keys": list(keys)},
            context_updates={},
        )

    async def _take_screenshot(self, shortcut_name: str) -> ActionResult:
        pyautogui = self._get_pyautogui()
        pictures_dir = get_known_user_paths()["pictures"]
        pictures_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = pictures_dir / f"screenshot_{timestamp}.png"
        try:
            image = await anyio.to_thread.run_sync(pyautogui.screenshot)
            # Save to OSCAR's resolved Pictures directory and verify the resulting file
            # on disk so screenshot tasks never depend on unverifiable hotkeys.
            await anyio.to_thread.run_sync(lambda: image.save(str(path)))
        except Exception as exc:
            return ActionResult(
                success=False,
                route="shortcut",
                action="shortcut",
                confidence=0.1,
                failure_reason=str(exc),
                retryable=True,
                data={"shortcut_name": shortcut_name, "file_path": str(path)},
            )
        if not path.exists():
            return ActionResult(
                success=False,
                route="shortcut",
                action="shortcut",
                confidence=0.1,
                failure_reason="Screenshot file was not created.",
                retryable=True,
                data={"shortcut_name": shortcut_name, "file_path": str(path)},
            )
        return ActionResult(
            success=True,
            route="shortcut",
            action="shortcut",
            confidence=0.95,
            data={
                "shortcut_name": shortcut_name,
                "file_path": str(path),
                "verified": True,
            },
            context_updates={},
        )
