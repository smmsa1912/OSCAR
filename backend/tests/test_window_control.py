from __future__ import annotations

import sys

from oscar.window_control import (
    _iter_visible_windows,
    build_launch_command,
    focus_app_window,
    is_oscar_app_name,
    is_oscar_app_window,
    resolve_app_spec,
    resolve_chrome_profile_directory,
    resolve_default_chrome_profile_directory,
)


def test_resolve_app_spec_maps_known_aliases() -> None:
    spec = resolve_app_spec("taskmanager")

    assert spec.canonical_name == "task manager"
    assert spec.command == ("taskmgr.exe",)


def test_resolve_app_spec_fuzzy_matches_common_typo() -> None:
    spec = resolve_app_spec("file exploror")

    assert spec.canonical_name == "file explorer"


def test_resolve_app_spec_maps_settings_alias() -> None:
    spec = resolve_app_spec("windows settings")

    assert spec.canonical_name == "settings"
    assert spec.shortcut_keys == ("winleft", "i")


def test_is_oscar_app_name_matches_common_variants() -> None:
    assert is_oscar_app_name("OSCAR")
    assert is_oscar_app_name("O.S.C.A.R.")
    assert is_oscar_app_name("oscar app")
    assert not is_oscar_app_name("Visual Studio Code")


def test_is_oscar_app_window_prefers_process_identity() -> None:
    assert is_oscar_app_window({"title": "Anything", "process_name": "OSCAR.exe"})
    assert is_oscar_app_window({"title": "OSCAR", "process_name": "oscar_ag.exe"})
    assert not is_oscar_app_window({"title": "OSCAR", "process_name": "explorer.exe"})


def test_resolve_default_chrome_profile_directory_prefers_last_used() -> None:
    profile_directory = resolve_default_chrome_profile_directory(
        local_state_data={
            "profile": {
                "last_used": "Profile 3",
                "info_cache": {
                    "Default": {"name": "Andrew"},
                },
            }
        }
    )

    assert profile_directory == "Profile 3"


def test_build_launch_command_uses_resolved_known_executable(monkeypatch) -> None:
    monkeypatch.setattr(
        "oscar.window_control._resolve_launch_target",
        lambda spec: r"C:\Windows\explorer.exe",
    )

    command, spec = build_launch_command("file explorer")

    assert spec.canonical_name == "file explorer"
    assert command == [r"C:\Windows\explorer.exe"]


def test_build_launch_command_supports_settings_uri(monkeypatch) -> None:
    monkeypatch.setattr(
        "oscar.window_control._resolve_launch_target",
        lambda spec: r"C:\Windows\System32\cmd.exe",
    )

    command, spec = build_launch_command("settings")

    assert spec.canonical_name == "settings"
    assert spec.shortcut_keys == ("winleft", "i")
    assert command == [
        r"C:\Windows\System32\cmd.exe",
        "/c",
        "start",
        "",
        "ms-settings:",
    ]


def test_resolve_chrome_profile_directory_matches_display_name() -> None:
    local_state_data = {
        "profile": {
            "info_cache": {
                "Default": {
                    "name": "Andrew",
                    "shortcut_name": "Andrew",
                    "gaia_given_name": "Andrew",
                },
                "Profile 1": {
                    "name": "Salomi",
                    "shortcut_name": "Salomi",
                    "gaia_given_name": "Salomi",
                },
            }
        }
    }

    profile_directory = resolve_chrome_profile_directory(
        "Andrew",
        local_state_data=local_state_data,
    )

    assert profile_directory == "Default"


def test_build_launch_command_includes_default_chrome_profile(monkeypatch) -> None:
    monkeypatch.setattr(
        "oscar.window_control._resolve_launch_target",
        lambda spec: r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    )
    monkeypatch.setattr(
        "oscar.window_control.resolve_default_chrome_profile_directory",
        lambda **kwargs: "Default",
    )

    command, spec = build_launch_command("chrome", url="https://github.com")

    assert spec.canonical_name == "chrome"
    assert command == [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "--profile-directory=Default",
        "https://github.com",
    ]


def test_build_launch_command_includes_chrome_profile_when_available(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "oscar.window_control.resolve_chrome_profile_directory",
        lambda profile_name, **kwargs: "Default",
    )
    monkeypatch.setattr(
        "oscar.window_control._resolve_launch_target",
        lambda spec: r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    )

    command, spec = build_launch_command(
        "chrome", profile_name="Andrew", url="https://google.com"
    )

    assert spec.canonical_name == "chrome"
    assert command == [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "--profile-directory=Default",
        "https://google.com",
    ]


def test_build_launch_command_uses_chrome_guest_mode(monkeypatch) -> None:
    monkeypatch.setattr(
        "oscar.window_control._resolve_launch_target",
        lambda spec: r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    )

    command, spec = build_launch_command("chrome", profile_name="Guest Mode")

    assert spec.canonical_name == "chrome"
    assert command == [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "--guest",
    ]


def test_iter_visible_windows_handles_enumwindows_failure(monkeypatch) -> None:
    class FakeWin32Gui:
        @staticmethod
        def EnumWindows(_callback, _extra):
            raise RuntimeError("boom")

    class FakeWin32Process:
        pass

    monkeypatch.setitem(sys.modules, "win32gui", FakeWin32Gui)
    monkeypatch.setitem(sys.modules, "win32process", FakeWin32Process)

    assert _iter_visible_windows() == []


def test_focus_app_window_minimizes_oscar_before_focusing_other_app(monkeypatch) -> None:
    active_windows = iter(
        [
            {"title": "OSCAR", "process_name": "oscar.exe", "hwnd": 1},
            {"title": "New Tab - Google Chrome", "process_name": "chrome.exe", "hwnd": 2},
        ]
    )
    calls: list[tuple[str, int]] = []

    monkeypatch.setattr(
        "oscar.window_control.get_active_window_info",
        lambda: next(active_windows),
    )
    monkeypatch.setattr(
        "oscar.window_control.find_app_windows",
        lambda app_name: [{"title": "New Tab - Google Chrome", "process_name": "chrome.exe", "hwnd": 2}],
    )
    monkeypatch.setattr(
        "oscar.window_control._minimize_window",
        lambda hwnd: calls.append(("minimize", hwnd)),
    )
    monkeypatch.setattr(
        "oscar.window_control._activate_window",
        lambda hwnd: calls.append(("activate", hwnd)),
    )
    monkeypatch.setattr(
        "oscar.window_control.wait_for_condition",
        lambda predicate, policy: predicate(),
    )

    assert focus_app_window("chrome", timeout=0.0)
    assert calls == [("minimize", 1), ("activate", 2)]
