from __future__ import annotations

from oscar.window_control import (
    build_launch_command,
    resolve_app_spec,
    resolve_chrome_profile_directory,
)


def test_resolve_app_spec_maps_known_aliases() -> None:
    spec = resolve_app_spec("taskmanager")

    assert spec.canonical_name == "task manager"
    assert spec.command == ("taskmgr.exe",)


def test_resolve_app_spec_fuzzy_matches_common_typo() -> None:
    spec = resolve_app_spec("file exploror")

    assert spec.canonical_name == "file explorer"


def test_build_launch_command_uses_resolved_known_executable(monkeypatch) -> None:
    monkeypatch.setattr(
        "oscar.window_control._resolve_launch_target",
        lambda spec: r"C:\Windows\explorer.exe",
    )

    command, spec = build_launch_command("file explorer")

    assert spec.canonical_name == "file explorer"
    assert command == [r"C:\Windows\explorer.exe"]


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


def test_build_launch_command_includes_chrome_profile_when_available(monkeypatch) -> None:
    monkeypatch.setattr(
        "oscar.window_control.resolve_chrome_profile_directory",
        lambda profile_name, **kwargs: "Default",
    )
    monkeypatch.setattr(
        "oscar.window_control._resolve_launch_target",
        lambda spec: r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    )

    command, spec = build_launch_command("chrome", profile_name="Andrew", url="https://google.com")

    assert spec.canonical_name == "chrome"
    assert command == [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "--profile-directory=Default",
        "https://google.com",
    ]
