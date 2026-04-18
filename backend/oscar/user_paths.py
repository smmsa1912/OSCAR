"""Helpers for resolving the current user's common filesystem paths."""

from __future__ import annotations

import os
import re
from pathlib import Path

_KNOWN_FOLDER_NAMES = {
    "desktop": "Desktop",
    "downloads": "Downloads",
    "documents": "Documents",
    "pictures": "Pictures",
    "music": "Music",
    "videos": "Videos",
}


def get_user_home_dir() -> Path:
    user_profile = os.getenv("USERPROFILE")
    if user_profile:
        return Path(user_profile)

    home_drive = os.getenv("HOMEDRIVE")
    home_path = os.getenv("HOMEPATH")
    if home_drive and home_path:
        return Path(f"{home_drive}{home_path}")

    return Path.home()


def get_known_user_paths() -> dict[str, Path]:
    home = get_user_home_dir()
    paths = {"home": home}
    for key, folder_name in _KNOWN_FOLDER_NAMES.items():
        paths[key] = home / folder_name
    return paths


def rewrite_known_user_paths(value: str) -> str:
    rewritten = os.path.expanduser(os.path.expandvars(value.strip()))
    if not rewritten:
        return rewritten

    known_paths = get_known_user_paths()
    for key, folder_path in known_paths.items():
        if key == "home":
            continue
        pattern = re.compile(
            rf"(?i)[a-z]:\\Users\\[^\\]+\\{re.escape(folder_path.name)}"
        )
        rewritten = pattern.sub(
            lambda _match, replacement=str(folder_path): replacement, rewritten
        )

    return rewritten


def generalize_known_user_paths(value: str) -> str:
    """Replace concrete user-home paths with runtime-safe environment forms."""

    generalized = value.strip()
    if not generalized:
        return generalized

    known_paths = get_known_user_paths()
    replacements: list[tuple[str, str]] = []
    for key, folder_path in known_paths.items():
        if key == "home":
            continue
        replacements.append(
            (str(folder_path), rf"$env:USERPROFILE\{folder_path.name}")
        )
    replacements.sort(key=lambda item: len(item[0]), reverse=True)

    for actual, replacement in replacements:
        generalized = re.sub(
            re.escape(actual),
            lambda _match, replacement=replacement: replacement,
            generalized,
            flags=re.IGNORECASE,
        )

    generalized = re.sub(
        re.escape(str(known_paths["home"])),
        lambda _match: "$env:USERPROFILE",
        generalized,
        flags=re.IGNORECASE,
    )
    return generalized


def render_known_path_strings() -> dict[str, str]:
    return {key: str(path) for key, path in get_known_user_paths().items()}
