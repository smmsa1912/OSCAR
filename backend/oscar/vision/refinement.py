"""Bounding-box refinement and coordinate normalization helpers."""

from __future__ import annotations

from typing import Any


def normalize_grid_coordinate(value: int | float, limit: int) -> int:
    if limit <= 0:
        return int(value)
    numeric = float(value)
    if numeric > 1000:
        return max(0, min(int(numeric), limit - 1))
    scaled = int((numeric / 1000.0) * limit)
    return max(0, min(scaled, limit - 1))


def refined_box_center(control: dict[str, Any]) -> tuple[int, int]:
    refined_left, refined_top, refined_right, refined_bottom = clickable_region(control)
    return ((refined_left + refined_right) // 2, (refined_top + refined_bottom) // 2)


def clickable_region(control: dict[str, Any]) -> tuple[int, int, int, int]:
    left = int(control.get("left", 0))
    top = int(control.get("top", 0))
    right = int(control.get("right", 0))
    bottom = int(control.get("bottom", 0))
    width = max(right - left, 1)
    height = max(bottom - top, 1)
    control_type = str(control.get("control_type") or "").lower()

    inset_x = max(int(width * 0.12), 1)
    inset_y = max(int(height * 0.18), 1)
    if control_type in {"tabitem", "menuitem", "treeitem", "listitem", "text"}:
        inset_x = max(int(width * 0.18), 1)
        inset_y = max(int(height * 0.22), 1)
    elif control_type in {"button", "splitbutton", "checkbox", "radiobutton"}:
        inset_x = max(int(width * 0.14), 1)
        inset_y = max(int(height * 0.2), 1)

    refined_left = left + inset_x
    refined_right = max(refined_left, right - inset_x)
    refined_top = top + inset_y
    refined_bottom = max(refined_top, bottom - inset_y)
    return refined_left, refined_top, refined_right, refined_bottom
