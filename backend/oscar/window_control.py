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
from typing import Any

from oscar import config
from oscar.utils.retry import RetryPolicy, wait_for_condition


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
    shortcut_keys: tuple[str, ...] = ()
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
        canonical_name="brave",
        command=("brave.exe",),
        process_names=("brave.exe",),
        title_keywords=("brave",),
        aliases=("brave browser",),
        launch_candidates=(
            r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"%LocalAppData%\BraveSoftware\Brave-Browser\Application\brave.exe",
            "brave.exe",
        ),
        supports_url=True,
    ),
    AppSpec(
        canonical_name="firefox",
        command=("firefox.exe",),
        process_names=("firefox.exe",),
        title_keywords=("firefox",),
        aliases=("mozilla firefox",),
        launch_candidates=(
            r"%ProgramFiles%\Mozilla Firefox\firefox.exe",
            r"%ProgramFiles(x86)%\Mozilla Firefox\firefox.exe",
            "firefox.exe",
        ),
        supports_url=True,
    ),
    AppSpec(
        canonical_name="file explorer",
        command=("explorer.exe",),
        process_names=("explorer.exe",),
        title_keywords=("file explorer", "explorer"),
        aliases=(
            "explorer",
            "windows explorer",
            "file exploror",
            "exploror",
            "file manager",
        ),
        launch_candidates=(r"%SystemRoot%\explorer.exe", "explorer.exe"),
        shortcut_keys=("winleft", "e"),
    ),
    AppSpec(
        canonical_name="settings",
        command=("cmd.exe", "/c", "start", "", "ms-settings:"),
        process_names=("systemsettings.exe",),
        title_keywords=("settings",),
        aliases=("setting", "windows settings", "settings app"),
        launch_candidates=(r"%SystemRoot%\System32\cmd.exe", "cmd.exe"),
        shortcut_keys=("winleft", "i"),
    ),
    AppSpec(
        canonical_name="task manager",
        command=("taskmgr.exe",),
        process_names=("taskmgr.exe",),
        title_keywords=("task manager",),
        aliases=("taskmanager", "task manger", "taskmgr"),
        launch_candidates=(r"%SystemRoot%\System32\taskmgr.exe", "taskmgr.exe"),
        shortcut_keys=("ctrl", "shift", "esc"),
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
        launch_candidates=(
            r"%SystemRoot%\System32\SnippingTool.exe",
            "SnippingTool.exe",
        ),
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
GUEST_PROFILE_NAMES = {"guest", "guest mode"}
INCOGNITO_PROFILE_NAMES = {
    "incognito",
    "private",
    "private mode",
    "inprivate",
    "in private",
}
HOST_PROCESS_NAMES = {"pwsh.exe", "powershell.exe", "cmd.exe", "windowsterminal.exe"}
HOST_TITLE_MARKERS = ("oscar", "python main.py", "code\\oscar", "codex")
OSCAR_APP_PROCESS_NAMES = {"oscar.exe", "oscar_ag.exe"}
OSCAR_APP_NAME_TOKENS = {"oscar", "oscarapp", "oscardesktop"}


def normalize_app_name(app_name: str) -> str:
    """Normalize a free-form app name for matching."""

    return " ".join(app_name.strip().split()).strip(" .,\t").lower()


def _compact_name_token(value: str) -> str:
    return "".join(ch for ch in normalize_app_name(value) if ch.isalnum())


def is_oscar_app_name(app_name: str) -> bool:
    """Return whether a free-form app name refers to the OSCAR desktop app."""

    return _compact_name_token(app_name) in OSCAR_APP_NAME_TOKENS


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


def _load_json_file(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def resolve_default_chrome_profile_directory(
    *,
    local_state_data: dict[str, Any] | None = None,
    local_state_path: Path | None = None,
) -> str | None:
    """Return Chrome's most likely default profile directory."""

    data = local_state_data or _load_json_file(
        local_state_path or chrome_local_state_path()
    )
    if not data:
        return None

    profile_section = data.get("profile", {})
    last_used = profile_section.get("last_used")
    if isinstance(last_used, str) and last_used.strip():
        return last_used.strip()

    info_cache = profile_section.get("info_cache", {})
    if "Default" in info_cache:
        return "Default"
    if info_cache:
        return next(iter(info_cache))
    return None


def resolve_chrome_profile_directory(
    profile_name: str,
    *,
    local_state_data: dict[str, Any] | None = None,
    local_state_path: Path | None = None,
) -> str | None:
    """Resolve a Chrome display profile name to its profile directory."""

    wanted = normalize_app_name(profile_name)
    if not wanted:
        return None

    data = local_state_data or _load_json_file(
        local_state_path or chrome_local_state_path()
    )
    if not data:
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

    if spec.canonical_name == "chrome":
        command = [executable]
        normalized_profile = normalize_app_name(profile_name or "")
        if normalized_profile in GUEST_PROFILE_NAMES:
            command.append("--guest")
        elif normalized_profile in INCOGNITO_PROFILE_NAMES:
            command.append("--incognito")
        else:
            profile_directory = None
            if profile_name:
                profile_directory = (
                    resolve_chrome_profile_directory(profile_name)
                    or profile_name.strip()
                )
            else:
                profile_directory = resolve_default_chrome_profile_directory()
            if profile_directory:
                command.append(f"--profile-directory={profile_directory}")
        if url:
            command.append(url)
        return command, spec

    if spec.canonical_name == "microsoft edge":
        command = [executable]
        normalized_profile = normalize_app_name(profile_name or "")
        if normalized_profile in GUEST_PROFILE_NAMES:
            command.append("--guest")
        elif normalized_profile in INCOGNITO_PROFILE_NAMES:
            command.append("--inprivate")
        elif profile_name:
            command.append(f"--profile-directory={profile_name.strip()}")
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

    try:
        win32gui.EnumWindows(_callback, None)
    except Exception:
        return windows
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


def list_visible_windows(*, limit: int = 12) -> list[dict[str, int | str | None]]:
    """Return a compact snapshot of visible top-level windows for prompt context."""

    visible: list[dict[str, int | str | None]] = []
    seen: set[tuple[str, str]] = set()
    for window in _iter_visible_windows():
        title = str(window.get("title") or "").strip()
        process_name = str(window.get("process_name") or "").strip().lower()
        if not title and not process_name:
            continue
        key = (title.lower(), process_name)
        if key in seen:
            continue
        seen.add(key)
        visible.append(
            {
                "title": title or None,
                "process_name": process_name or None,
                "hwnd": window.get("hwnd"),
            }
        )
        if len(visible) >= limit:
            break
    return visible


def is_protected_host_window(window_info: dict[str, Any] | None = None) -> bool:
    """Return whether a window looks like the OSCAR host terminal/session."""

    info = window_info or get_active_window_info()
    title = str(info.get("title") or "").lower()
    process_name = str(info.get("process_name") or "").lower()
    if process_name not in HOST_PROCESS_NAMES:
        return False
    if not title:
        return True
    return any(marker in title for marker in HOST_TITLE_MARKERS) or any(
        generic in title
        for generic in ("powershell", "terminal", "command prompt", "cmd.exe")
    )


def is_oscar_app_window(window_info: dict[str, Any] | None = None) -> bool:
    """Return whether a window looks like the OSCAR desktop application."""

    info = window_info or get_active_window_info()
    process_name = str(info.get("process_name") or "").lower()
    if process_name:
        return process_name in OSCAR_APP_PROCESS_NAMES
    title = str(info.get("title") or "")
    return _compact_name_token(title) == "oscar"


def find_oscar_app_windows() -> list[dict[str, int | str | None]]:
    """Return currently visible windows that appear to belong to OSCAR."""

    matches: list[dict[str, int | str | None]] = []
    seen_hwnds: set[int] = set()

    active = get_active_window_info()
    active_hwnd = active.get("hwnd")
    if isinstance(active_hwnd, int) and is_oscar_app_window(active):
        seen_hwnds.add(active_hwnd)
        matches.append(active)

    for window in _iter_visible_windows():
        hwnd = window.get("hwnd")
        if not isinstance(hwnd, int) or hwnd in seen_hwnds:
            continue
        if is_oscar_app_window(window):
            seen_hwnds.add(hwnd)
            matches.append(window)

    return matches


def focus_oscar_app_window(
    *,
    timeout: float = 3.0,
    poll_interval: float = 0.1,
) -> bool:
    """Bring the OSCAR desktop application window to the foreground."""

    if not find_oscar_app_windows():
        return False

    policy = RetryPolicy(
        timeout_seconds=max(timeout, 0.0),
        initial_interval=max(poll_interval, config.RETRY_INITIAL_INTERVAL_SECONDS),
        max_interval=max(poll_interval, config.RETRY_MAX_INTERVAL_SECONDS),
        backoff=max(config.RETRY_BACKOFF_FACTOR, 1.0),
    )

    def _attempt_focus() -> bool:
        active = get_active_window_info()
        if is_oscar_app_window(active):
            return True

        for window in find_oscar_app_windows():
            hwnd = window.get("hwnd")
            if isinstance(hwnd, int):
                _activate_window(hwnd)
                break
        return is_oscar_app_window(get_active_window_info())

    focused = wait_for_condition(_attempt_focus, policy=policy)
    return bool(focused)


def is_protected_control_window(window_info: dict[str, Any] | None = None) -> bool:
    """Return whether a window is part of OSCAR's own control surface."""

    return is_protected_host_window(window_info) or is_oscar_app_window(window_info)


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


def _minimize_window(hwnd: int) -> None:
    try:
        import win32con
        import win32gui

        win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
    except Exception:
        try:
            import pygetwindow as gw

            window = gw.Win32Window(hwnd)
            window.minimize()
        except Exception:
            return


def focus_app_window(
    app_name: str,
    *,
    timeout: float = 3.0,
    poll_interval: float = 0.1,
) -> bool:
    """Bring a known application window to the foreground."""

    # This low-level helper may be reached outside the main action executor.
    # Never inspect or change desktop focus while dry-run is enabled.
    if config.OSCAR_DRY_RUN:
        return False

    spec = resolve_app_spec(app_name)
    policy = RetryPolicy(
        timeout_seconds=max(timeout, 0.0),
        initial_interval=max(poll_interval, config.RETRY_INITIAL_INTERVAL_SECONDS),
        max_interval=max(poll_interval, config.RETRY_MAX_INTERVAL_SECONDS),
        backoff=max(config.RETRY_BACKOFF_FACTOR, 1.0),
    )

    def _attempt_focus() -> bool:
        active = get_active_window_info()
        if _matches_spec(
            active.get("title"),  # type: ignore[arg-type]
            active.get("process_name"),  # type: ignore[arg-type]
            spec,
        ):
            return True

        if is_oscar_app_window(active) and not is_oscar_app_name(app_name):
            active_hwnd = active.get("hwnd")
            if isinstance(active_hwnd, int):
                _minimize_window(active_hwnd)
                time.sleep(0.05)

        for window in find_app_windows(app_name):
            hwnd = window.get("hwnd")
            if isinstance(hwnd, int):
                _activate_window(hwnd)
                break
        active = get_active_window_info()
        return _matches_spec(
            active.get("title"),  # type: ignore[arg-type]
            active.get("process_name"),  # type: ignore[arg-type]
            spec,
        )

    focused = wait_for_condition(_attempt_focus, policy=policy)
    return bool(focused)
