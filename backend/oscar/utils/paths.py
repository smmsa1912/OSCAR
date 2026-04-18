"""Compatibility wrappers for runtime path resolution."""

from __future__ import annotations

from oscar.user_paths import (
    generalize_known_user_paths,
    get_known_user_paths,
    get_user_home_dir,
    render_known_path_strings,
    rewrite_known_user_paths,
)

__all__ = [
    "get_known_user_paths",
    "get_user_home_dir",
    "generalize_known_user_paths",
    "render_known_path_strings",
    "rewrite_known_user_paths",
]
