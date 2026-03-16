"""Optional Windows UI Automation helpers for OSCAR."""

from __future__ import annotations

from typing import Any


def _load_desktop_backend():
    try:
        from pywinauto import Desktop
    except Exception:
        return None
    return Desktop


def _active_window_wrapper():
    Desktop = _load_desktop_backend()
    if Desktop is None:
        return None

    try:
        from oscar.window_control import get_active_window_info

        active = get_active_window_info()
        hwnd = active.get("hwnd")
        if not isinstance(hwnd, int) or hwnd <= 0:
            return None
        return Desktop(backend="uia").window(handle=hwnd)
    except Exception:
        return None


def capture_active_window_controls(*, limit: int = 30) -> list[dict[str, Any]]:
    wrapper = _active_window_wrapper()
    if wrapper is None:
        return []

    try:
        descendants = wrapper.descendants()
    except Exception:
        return []

    controls: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, int, int, int, int]] = set()
    for child in descendants:
        try:
            if hasattr(child, "is_visible") and not child.is_visible():
                continue
            text = (child.window_text() or "").strip()
            element_info = getattr(child, "element_info", None)
            automation_id = (getattr(element_info, "automation_id", "") or "").strip()
            control_type = (
                (getattr(element_info, "control_type", "") or "").strip()
                or (child.friendly_class_name() if hasattr(child, "friendly_class_name") else "")
            )
            if not text and not automation_id:
                continue
            rect = child.rectangle()
            item = {
                "text": text,
                "automation_id": automation_id,
                "control_type": control_type,
                "left": int(rect.left),
                "top": int(rect.top),
                "right": int(rect.right),
                "bottom": int(rect.bottom),
            }
            key = (
                item["text"],
                item["automation_id"],
                item["control_type"],
                item["left"],
                item["top"],
                item["right"],
                item["bottom"],
            )
            if key in seen:
                continue
            seen.add(key)
            controls.append(item)
            if len(controls) >= limit:
                break
        except Exception:
            continue

    return controls


def click_active_window_control(
    *,
    target_text: str | None = None,
    control_type: str | None = None,
    automation_id: str | None = None,
) -> bool:
    wrapper = _active_window_wrapper()
    if wrapper is None:
        return False

    target_text_normalized = (target_text or "").strip().lower()
    control_type_normalized = (control_type or "").strip().lower()
    automation_id_normalized = (automation_id or "").strip().lower()

    try:
        descendants = wrapper.descendants()
    except Exception:
        return False

    scored_matches: list[tuple[tuple[int, int, int], Any]] = []
    for child in descendants:
        try:
            if hasattr(child, "is_visible") and not child.is_visible():
                continue
            text = (child.window_text() or "").strip()
            element_info = getattr(child, "element_info", None)
            child_automation_id = (getattr(element_info, "automation_id", "") or "").strip()
            child_control_type = (
                (getattr(element_info, "control_type", "") or "").strip()
                or (child.friendly_class_name() if hasattr(child, "friendly_class_name") else "")
            )

            if automation_id_normalized and child_automation_id.lower() != automation_id_normalized:
                continue
            if control_type_normalized and child_control_type.lower() != control_type_normalized:
                continue
            if target_text_normalized:
                lowered_text = text.lower()
                if target_text_normalized != lowered_text and target_text_normalized not in lowered_text:
                    continue

            exact_text = int(bool(target_text_normalized and text.lower() == target_text_normalized))
            exact_automation = int(bool(automation_id_normalized and child_automation_id.lower() == automation_id_normalized))
            exact_control_type = int(bool(control_type_normalized and child_control_type.lower() == control_type_normalized))
            scored_matches.append(((exact_automation, exact_text, exact_control_type), child))
        except Exception:
            continue

    for _score, child in sorted(scored_matches, key=lambda item: item[0], reverse=True):
        try:
            if hasattr(child, "set_focus"):
                child.set_focus()
            if hasattr(child, "invoke"):
                child.invoke()
                return True
            if hasattr(child, "click_input"):
                child.click_input()
                return True
            if hasattr(child, "click"):
                child.click()
                return True
        except Exception:
            continue

    return False
