"""Window and application control helpers for OSCAR."""

from __future__ import annotations

import difflib
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppSpec:
    """Metadata used for deterministic launch and focus checks."""

    canonical_name: str
    command: tuple[str, ...]
    process_names: tuple[str, ...]
    title_keywords: tuple[str, ...]
    aliases: tuple[str, ...] = ()
    launch_candidates: tuple[str, ...] = ()
    supports_profile: bool = False
    supports_url: bool = False
    is_known: bool = True


_KNOWN_APP_SPECS = [
    AppSpec(
        canonical_name="notepad",
        command=("notepad.exe",),
        process_names=("notepad.exe",),
        title_keywords=("notepad",),
        aliases=("notepad app",),
        launch_candidates=(r"%SystemRoot%\System32\notepad.exe", "notepad.exe"),
    ),
    AppSpec(
        canonical_name="chrome",
        command=("chrome.exe",),
        process_names=("chrome.exe",),
        title_keywords=("chrome",),
        aliases=("google chrome", "chrome browser", "browser"),
        launch_candidates=(
            r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
            r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
            r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
            "chrome.exe",
        ),
        supports_profile=True,
        supports_url=True,
    ),
    AppSpec(
        canonical_name="microsoft edge",
        command=("msedge.exe",),
        process_names=("msedge.exe",),
        title_keywords=("microsoft edge", "edge"),
        aliases=("edge",),
        launch_candidates=(
            r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
            r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
            r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe",
            "msedge.exe",
        ),
        supports_profile=True,
        supports_url=True,
    ),
    AppSpec(
        canonical_name="file explorer",
        command=("explorer.exe",),
        process_names=("explorer.exe",),
        title_keywords=("file explorer", "explorer"),
        aliases=("explorer", "windows explorer", "file exploror", "exploror"),
        launch_candidates=(r"%SystemRoot%\explorer.exe", "explorer.exe"),
    ),
    AppSpec(
        canonical_name="task manager",
        command=("taskmgr.exe",),
        process_names=("taskmgr.exe",),
        title_keywords=("task manager",),
        aliases=("taskmanager", "task manger"),
        launch_candidates=(r"%SystemRoot%\System32\taskmgr.exe", "taskmgr.exe"),
    ),
    AppSpec(
        canonical_name="calculator",
        command=("calc.exe",),
        process_names=("calculatorapp.exe", "calculator.exe", "calc.exe"),
        title_keywords=("calculator",),
        aliases=("calc",),
        launch_candidates=(r"%SystemRoot%\System32\calc.exe", "calc.exe"),
    ),
    AppSpec(
        canonical_name="paint",
        command=("mspaint.exe",),
        process_names=("mspaint.exe",),
        title_keywords=("paint",),
        aliases=("ms paint",),
        launch_candidates=(r"%SystemRoot%\System32\mspaint.exe", "mspaint.exe"),
    ),
    AppSpec(
        canonical_name="snipping tool",
        command=("SnippingTool.exe",),
        process_names=("snippingtool.exe",),
        title_keywords=("snipping tool",),
        aliases=("snip", "snippingtool"),
        launch_candidates=(r"%SystemRoot%\System32\SnippingTool.exe", "SnippingTool.exe"),
    ),
    AppSpec(
        canonical_name="command prompt",
        command=("cmd.exe",),
        process_names=("cmd.exe",),
        title_keywords=("command prompt", "cmd.exe", "cmd"),
        aliases=("cmd",),
        launch_candidates=(r"%SystemRoot%\System32\cmd.exe", "cmd.exe"),
    ),
    AppSpec(
        canonical_name="powershell",
        command=("powershell.exe",),
        process_names=("powershell.exe", "pwsh.exe"),
        title_keywords=("powershell", "pwsh"),
        aliases=("windows powershell", "terminal"),
        launch_candidates=(
            r"%ProgramFiles%\PowerShell\7\pwsh.exe",
            r"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe",
            "pwsh.exe",
            "powershell.exe",
        ),
    ),
    AppSpec(
        canonical_name="visual studio code",
        command=("code.exe",),
        process_names=("code.exe",),
        title_keywords=("visual studio code", "vs code"),
        aliases=("vs code", "vscode", "code"),
        launch_candidates=(
            r"%LocalAppData%\Programs\Microsoft VS Code\Code.exe",
            r"%ProgramFiles%\Microsoft VS Code\Code.exe",
            "code.cmd",
            "code.exe",
            "code",
        ),
    ),
]

_ALIASES: dict[str, AppSpec] = {}
for spec in _KNOWN_APP_SPECS:
    alias_variants = {
        spec.canonical_name,
        spec.canonical_name.replace(" ", ""),
        *spec.aliases,
    }
    for alias in alias_variants:
        normalized = " ".join(alias.strip().split()).lower()
        if normalized:
            _ALIASES[normalized] = spec
            _ALIASES[normalized.replace(" ", "")] = spec


KNOWN_APP_NAMES = sorted({spec.canonical_name for spec in _KNOWN_APP_SPECS})


def normalize_app_name(app_name: str) -> str:
    """Normalize a free-form app name for matching."""

    lowered = " ".join(app_name.strip().split()).strip(" .,\t").lower()
    return lowered


def _fuzzy_match_alias(app_name: str) -> AppSpec | None:
    normalized = normalize_app_name(app_name)
    if not normalized:
        return None

    alias_names = list(_ALIASES.keys())
    for candidate in (normalized, normalized.replace(" ", "")):
        matches = difflib.get_close_matches(candidate, alias_names, n=1, cutoff=0.84)
        if matches:
            return _ALIASES[matches[0]]
    return None


def resolve_app_spec(app_name: str) -> AppSpec:
    """Resolve a user/model app name to a known app spec when possible."""

    normalized = normalize_app_name(app_name)
    if normalized in _ALIASES:
        return _ALIASES[normalized]

    compact_name = normalized.replace(" ", "")
    if compact_name in _ALIASES:
        return _ALIASES[compact_name]

    fuzzy_spec = _fuzzy_match_alias(normalized)
    if fuzzy_spec is not None:
        return fuzzy_spec

    guessed_command = normalized if normalized.endswith(".exe") else f"{normalized}.exe"
    guessed_process = Path(guessed_command).name.lower()
    return AppSpec(
        canonical_name=normalized,
        command=(guessed_command,),
        process_names=(guessed_process,),
        title_keywords=(normalized,),
        launch_candidates=(guessed_command,),
        is_known=False,
    )


def chrome_local_state_path() -> Path:
    """Return the expected Chrome Local State path."""

    local_app_data = Path(os.getenv("LOCALAPPDATA", ""))
    return local_app_data / "Google" / "Chrome" / "User Data" / "Local State"


def resolve_chrome_profile_directory(
    profile_name: str,
    *,
    local_state_data: dict | None = None,
    local_state_path: Path | None = None,
) -> str | None:
    """Resolve a Chrome display profile name to its profile directory."""

    wanted = normalize_app_name(profile_name)
    if not wanted:
        return None

    data = local_state_data
    if data is None:
        path = local_state_path or chrome_local_state_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    info_cache = data.get("profile", {}).get("info_cache", {})
    exact_matches: list[str] = []
    partial_matches: list[str] = []

    for directory, info in info_cache.items():
        candidates = {
            normalize_app_name(directory),
            normalize_app_name(info.get("name", "")),
            normalize_app_name(info.get("shortcut_name", "")),
            normalize_app_name(info.get("gaia_given_name", "")),
            normalize_app_name(info.get("user_name", "")),
        }
        if wanted in candidates:
            exact_matches.append(directory)
            continue
        if any(wanted and wanted in candidate for candidate in candidates if candidate):
            partial_matches.append(directory)

    if exact_matches:
        return exact_matches[0]
    if len(partial_matches) == 1:
        return partial_matches[0]
    return None


def _resolve_launch_target(spec: AppSpec) -> str | None:
    candidates = spec.launch_candidates or spec.command
    for candidate in candidates:
        expanded = os.path.expandvars(candidate)
        path = Path(expanded)
        if path.is_absolute():
            if path.exists():
                return str(path)
            continue
        if path.exists():
            return str(path.resolve())
        resolved = shutil.which(expanded)
        if resolved:
            return resolved
    return None


def build_launch_command(
    app_name: str,
    *,
    profile_name: str | None = None,
    url: str | None = None,
) -> tuple[list[str], AppSpec]:
    """Build the command used to launch a known application."""

    spec = resolve_app_spec(app_name)
    executable = _resolve_launch_target(spec) or spec.command[0]

    if spec.canonical_name in {"chrome", "microsoft edge"}:
        command = [executable]
        if profile_name:
            profile_directory = profile_name.strip()
            if spec.canonical_name == "chrome":
                resolved_profile = resolve_chrome_profile_directory(profile_name)
                if resolved_profile is not None:
                    profile_directory = resolved_profile
            command.append(f"--profile-directory={profile_directory}")
        if url:
            command.append(url)
        return command, spec

    if spec.is_known:
        command = [executable, *spec.command[1:]]
        if url and spec.supports_url:
            command.append(url)
        return command, spec

    if sys.platform == "win32":
        return ["cmd", "/c", "start", "", app_name], spec

    return [app_name], spec


def _safe_process_name(pid: int) -> str | None:
    try:
        import psutil

        return psutil.Process(pid).name().lower()
    except Exception:
        return None


def get_active_window_info() -> dict[str, int | str | None]:
    """Return the current foreground window title and process when available."""

    try:
        import win32gui
        import win32process

        hwnd = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(hwnd) or None
        _thread_id, pid = win32process.GetWindowThreadProcessId(hwnd)
        return {
            "hwnd": hwnd,
            "title": title,
            "process_name": _safe_process_name(pid),
        }
    except Exception:
        return {
            "hwnd": None,
            "title": None,
            "process_name": None,
        }


def get_active_window_title() -> str | None:
    """Return the current foreground window title when available."""

    return get_active_window_info()["title"]  # type: ignore[return-value]


def get_cursor_position() -> tuple[int, int] | None:
    """Return the current cursor position."""

    try:
        import pyautogui

        position = pyautogui.position()
        return int(position.x), int(position.y)
    except Exception:
        try:
            import win32gui

            x, y = win32gui.GetCursorPos()
            return int(x), int(y)
        except Exception:
            return None


def _matches_spec(title: str | None, process_name: str | None, spec: AppSpec) -> bool:
    lowered_title = (title or "").lower()
    lowered_process = (process_name or "").lower()

    if lowered_process and lowered_process in spec.process_names:
        return True
    return any(keyword in lowered_title for keyword in spec.title_keywords)


def _iter_visible_windows() -> list[dict[str, int | str | None]]:
    windows: list[dict[str, int | str | None]] = []

    try:
        import win32gui
        import win32process
    except Exception:
        return windows

    def _callback(hwnd: int, _extra: object) -> None:
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd) or None
            _thread_id, pid = win32process.GetWindowThreadProcessId(hwnd)
            windows.append(
                {
                    "hwnd": hwnd,
                    "title": title,
                    "process_name": _safe_process_name(pid),
                }
            )
        except Exception:
            return

    win32gui.EnumWindows(_callback, None)
    return windows


def find_app_windows(app_name: str) -> list[dict[str, int | str | None]]:
    """Return currently visible windows that appear to belong to the app."""

    spec = resolve_app_spec(app_name)
    matches: list[dict[str, int | str | None]] = []
    seen_hwnds: set[int] = set()

    active = get_active_window_info()
    active_hwnd = active.get("hwnd")
    if isinstance(active_hwnd, int) and _matches_spec(
        active.get("title"),  # type: ignore[arg-type]
        active.get("process_name"),  # type: ignore[arg-type]
        spec,
    ):
        seen_hwnds.add(active_hwnd)
        matches.append(active)

    for window in _iter_visible_windows():
        hwnd = window.get("hwnd")
        if not isinstance(hwnd, int) or hwnd in seen_hwnds:
            continue
        if _matches_spec(
            window.get("title"),  # type: ignore[arg-type]
            window.get("process_name"),  # type: ignore[arg-type]
            spec,
        ):
            seen_hwnds.add(hwnd)
            matches.append(window)

    return matches


def app_window_exists(app_name: str) -> bool:
    """Return whether a matching app window is currently visible."""

    return bool(find_app_windows(app_name))


def _activate_window(hwnd: int) -> None:
    try:
        import win32con
        import win32gui

        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.BringWindowToTop(hwnd)
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        try:
            import pygetwindow as gw

            window = gw.Win32Window(hwnd)
            window.restore()
            window.activate()
        except Exception:
            return


def focus_app_window(
    app_name: str,
    *,
    timeout: float = 3.0,
    poll_interval: float = 0.1,
) -> bool:
    """Bring a known application window to the foreground."""

    spec = resolve_app_spec(app_name)
    deadline = time.monotonic() + max(timeout, 0.0)

    while time.monotonic() <= deadline:
        active = get_active_window_info()
        if _matches_spec(
            active.get("title"),  # type: ignore[arg-type]
            active.get("process_name"),  # type: ignore[arg-type]
            spec,
        ):
            return True

        for window in find_app_windows(app_name):
            hwnd = window.get("hwnd")
            if isinstance(hwnd, int):
                _activate_window(hwnd)
                break
        time.sleep(poll_interval)

    active = get_active_window_info()
    return _matches_spec(
        active.get("title"),  # type: ignore[arg-type]
        active.get("process_name"),  # type: ignore[arg-type]
        spec,
    )
