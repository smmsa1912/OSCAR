from __future__ import annotations

from oscar.user_paths import (
    generalize_known_user_paths,
    get_known_user_paths,
    rewrite_known_user_paths,
)


def test_get_known_user_paths_uses_userprofile(monkeypatch) -> None:
    monkeypatch.setenv("USERPROFILE", r"C:\Users\andre")

    paths = get_known_user_paths()

    assert str(paths["home"]) == r"C:\Users\andre"
    assert str(paths["downloads"]) == r"C:\Users\andre\Downloads"
    assert str(paths["desktop"]) == r"C:\Users\andre\Desktop"


def test_rewrite_known_user_paths_maps_other_user_folder_to_current_profile(
    monkeypatch,
) -> None:
    monkeypatch.setenv("USERPROFILE", r"C:\Users\andre")

    rewritten = rewrite_known_user_paths(
        r"Remove-Item 'C:\Users\Andrew\Downloads\Hello World.txt'"
    )

    assert rewritten == r"Remove-Item 'C:\Users\andre\Downloads\Hello World.txt'"


def test_generalize_known_user_paths_rewrites_literal_user_paths_to_env_forms(
    monkeypatch,
) -> None:
    monkeypatch.setenv("USERPROFILE", r"C:\Users\andre")

    generalized = generalize_known_user_paths(
        r"Set-Content -LiteralPath 'C:\Users\andre\Desktop\note.txt' -Value 'hello'"
    )

    assert generalized == (
        r"Set-Content -LiteralPath '$env:USERPROFILE\Desktop\note.txt' -Value 'hello'"
    )
