"""Optional Windows UI Automation helpers for OSCAR.

These helpers bias toward resilient, state-driven UI targeting:
- gather only a bounded slice of the UIA tree with wall-clock limits
- expose visible controls to the planner for observation before action
- match controls by partial text, type families, automation id, and class name
- retry looser targeting inside the UI action itself before giving up
"""

from __future__ import annotations

from collections import deque
import time
from typing import Any, Iterable

ACTIONABLE_CONTROL_TYPES = {
    "Button",
    "CheckBox",
    "ComboBox",
    "DataItem",
    "Edit",
    "Hyperlink",
    "Image",
    "ListItem",
    "MenuItem",
    "RadioButton",
    "SplitButton",
    "TabItem",
    "Text",
    "TreeItem",
}
GENERIC_CONTROL_TYPES = {"Document", "Group", "Pane", "Window", "Custom"}
DEFAULT_UIA_DEPTH = 8
DEFAULT_UIA_NODE_LIMIT = 400
DEFAULT_UIA_WALK_TIMEOUT_SECONDS = 1.0
DEFAULT_UIA_REPOLL_TIMEOUT_SECONDS = 1.5

_LAST_UI_AUTOMATION_ERROR: str | None = None


def _set_last_ui_automation_error(message: str | None) -> None:
    global _LAST_UI_AUTOMATION_ERROR
    _LAST_UI_AUTOMATION_ERROR = message.strip() if isinstance(message, str) and message.strip() else None


def get_last_ui_automation_error() -> str | None:
    return _LAST_UI_AUTOMATION_ERROR


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


def _safe_rectangle(child: Any):
    try:
        return child.rectangle()
    except Exception:
        return None


def _rect_metrics(rect: Any) -> tuple[int, int, int, int, int, int]:
    left = int(rect.left)
    top = int(rect.top)
    right = int(rect.right)
    bottom = int(rect.bottom)
    width = max(right - left, 0)
    height = max(bottom - top, 0)
    return left, top, right, bottom, width, height


def _safe_window_text(child: Any) -> str:
    try:
        return (child.window_text() or "").strip()
    except Exception:
        return ""


def _safe_element_info(child: Any) -> Any:
    return getattr(child, "element_info", None)


def _safe_control_type(child: Any, element_info: Any) -> str:
    control_type = (getattr(element_info, "control_type", "") or "").strip()
    if control_type:
        return control_type
    if hasattr(child, "friendly_class_name"):
        try:
            return str(child.friendly_class_name() or "").strip()
        except Exception:
            return ""
    return ""


def _safe_automation_id(element_info: Any) -> str:
    return (getattr(element_info, "automation_id", "") or "").strip()


def _safe_class_name(element_info: Any) -> str:
    return (getattr(element_info, "class_name", "") or "").strip()


def _normalize_filter_strings(value: str | Iterable[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        normalized = " ".join(value.strip().lower().split())
        return [normalized] if normalized else []

    normalized_values: list[str] = []
    for item in value:
        normalized = " ".join(str(item or "").strip().lower().split())
        if normalized:
            normalized_values.append(normalized)
    return normalized_values


def _safe_is_visible(child: Any) -> bool:
    try:
        if hasattr(child, "is_visible"):
            return bool(child.is_visible())
    except Exception:
        return True
    return True


def _safe_is_enabled(child: Any, element_info: Any) -> bool:
    try:
        if hasattr(child, "is_enabled"):
            return bool(child.is_enabled())
    except Exception:
        pass
    enabled = getattr(element_info, "enabled", None)
    if isinstance(enabled, bool):
        return enabled
    return True


def _safe_is_keyboard_focusable(child: Any, element_info: Any) -> bool:
    focusable = getattr(element_info, "keyboard_focusable", None)
    if isinstance(focusable, bool):
        return focusable
    try:
        iface_element = getattr(child, "iface_element", None)
        if iface_element is not None:
            return bool(getattr(iface_element, "CurrentIsKeyboardFocusable", False))
    except Exception:
        return False
    return False


def _is_actionable_control(
    *,
    text: str,
    automation_id: str,
    control_type: str,
    rect: Any,
    is_enabled: bool,
    is_keyboard_focusable: bool,
) -> bool:
    _left, _top, _right, _bottom, width, height = _rect_metrics(rect)
    if width <= 0 or height <= 0 or not is_enabled:
        return False

    normalized_type = control_type.strip()
    normalized_text = text.strip()
    normalized_id = automation_id.strip()

    if normalized_type in ACTIONABLE_CONTROL_TYPES:
        return True
    if is_keyboard_focusable and (
        normalized_type not in GENERIC_CONTROL_TYPES or normalized_text or normalized_id
    ):
        return True
    if normalized_type in GENERIC_CONTROL_TYPES:
        return False
    return bool(normalized_text or normalized_id)


def _should_expand_control(control_type: str) -> bool:
    normalized = control_type.strip()
    return not normalized or normalized in GENERIC_CONTROL_TYPES


def _iter_limited_descendants(
    wrapper: Any,
    *,
    max_depth: int,
    max_nodes: int,
    deadline_monotonic: float | None = None,
):
    if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
        return
    try:
        initial_children = list(wrapper.children())
    except Exception:
        return

    queue: deque[tuple[Any, int]] = deque((child, 1) for child in initial_children)
    visited = 0
    while queue and visited < max_nodes:
        if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
            break
        child, depth = queue.popleft()
        visited += 1
        yield child

        if depth >= max_depth:
            continue

        control_type = _safe_control_type(child, _safe_element_info(child))
        if not _should_expand_control(control_type):
            continue

        try:
            grandchildren = list(child.children())
        except Exception:
            continue

        for grandchild in grandchildren:
            if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
                break
            queue.append((grandchild, depth + 1))


def _control_sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        int(item.get("top", 0)),
        int(item.get("left", 0)),
        int(item.get("bottom", 0)) - int(item.get("top", 0)),
        int(item.get("right", 0)) - int(item.get("left", 0)),
        str(item.get("text") or "").lower(),
        str(item.get("automation_id") or "").lower(),
        str(item.get("class_name") or "").lower(),
        str(item.get("control_type") or "").lower(),
    )


def _dedupe_and_finalize_controls(
    controls: list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, int, int, int, int]] = set()

    for control in sorted(controls, key=_control_sort_key):
        key = (
            str(control.get("text") or ""),
            str(control.get("automation_id") or ""),
            str(control.get("class_name") or ""),
            str(control.get("control_type") or ""),
            int(control.get("left", 0)),
            int(control.get("top", 0)),
            int(control.get("right", 0)),
            int(control.get("bottom", 0)),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(control)
        if len(deduped) >= limit:
            break

    for index, item in enumerate(deduped, start=1):
        item["element_id"] = index
    return deduped


def _collect_control_candidates(
    wrapper: Any,
    *,
    limit: int,
    max_depth: int = DEFAULT_UIA_DEPTH,
    max_nodes: int = DEFAULT_UIA_NODE_LIMIT,
    include_wrappers: bool = False,
    deadline_monotonic: float | None = None,
) -> list[dict[str, Any]]:
    controls: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, int, int, int, int]] = set()

    for child in _iter_limited_descendants(
        wrapper,
        max_depth=max_depth,
        max_nodes=max(max_nodes, limit * 4),
        deadline_monotonic=deadline_monotonic,
    ):
        if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
            break
        try:
            if not _safe_is_visible(child):
                continue

            element_info = _safe_element_info(child)
            text = _safe_window_text(child)
            automation_id = _safe_automation_id(element_info)
            control_type = _safe_control_type(child, element_info)
            class_name = _safe_class_name(element_info)
            rect = _safe_rectangle(child)
            if rect is None:
                continue

            actionable = _is_actionable_control(
                text=text,
                automation_id=automation_id,
                control_type=control_type,
                rect=rect,
                is_enabled=_safe_is_enabled(child, element_info),
                is_keyboard_focusable=_safe_is_keyboard_focusable(child, element_info),
            )
            if not actionable:
                continue

            left, top, right, bottom, _width, _height = _rect_metrics(rect)
            item = {
                "text": text,
                "automation_id": automation_id,
                "control_type": control_type,
                "class_name": class_name,
                "left": left,
                "top": top,
                "right": right,
                "bottom": bottom,
                "actionable": True,
            }
            if include_wrappers:
                item["_wrapper"] = child

            key = (
                item["text"],
                item["automation_id"],
                item["class_name"],
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
        except Exception:
            continue

    controls.sort(key=_control_sort_key)
    return controls[:limit]


def _context_menu_wrappers() -> list[Any]:
    Desktop = _load_desktop_backend()
    if Desktop is None:
        return []

    try:
        top_level = list(Desktop(backend="uia").windows())
    except Exception:
        return []

    wrappers: list[Any] = []
    seen_handles: set[int] = set()
    for wrapper in top_level:
        try:
            if not _safe_is_visible(wrapper):
                continue
            element_info = _safe_element_info(wrapper)
            class_name = _safe_class_name(element_info)
            control_type = _safe_control_type(wrapper, element_info)
            if class_name != "#32768" and control_type.lower() != "menu":
                continue
            handle = getattr(element_info, "handle", None)
            if isinstance(handle, int) and handle in seen_handles:
                continue
            if isinstance(handle, int):
                seen_handles.add(handle)
            wrappers.append(wrapper)
        except Exception:
            continue
    return wrappers


def _collect_visible_control_candidates(
    *,
    limit: int,
    include_wrappers: bool = False,
    max_depth: int = DEFAULT_UIA_DEPTH,
    deadline_monotonic: float | None = None,
) -> list[dict[str, Any]]:
    wrappers: list[Any] = []
    active_wrapper = _active_window_wrapper()
    if active_wrapper is not None:
        wrappers.append(active_wrapper)
    wrappers.extend(_context_menu_wrappers())
    if not wrappers:
        _set_last_ui_automation_error(
            "No active UI Automation window or floating context menu was available."
        )
        return []

    combined: list[dict[str, Any]] = []
    per_wrapper_limit = max(limit, 40)
    for wrapper in wrappers:
        if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
            break
        try:
            combined.extend(
                _collect_control_candidates(
                    wrapper,
                    limit=per_wrapper_limit,
                    max_depth=max_depth,
                    include_wrappers=include_wrappers,
                    deadline_monotonic=deadline_monotonic,
                )
            )
        except Exception:
            continue
    return _dedupe_and_finalize_controls(combined, limit=limit)


def capture_active_window_controls(
    *,
    limit: int = 30,
    max_depth: int = DEFAULT_UIA_DEPTH,
) -> list[dict[str, Any]]:
    _set_last_ui_automation_error(None)
    deadline_monotonic = time.monotonic() + DEFAULT_UIA_WALK_TIMEOUT_SECONDS
    controls = _collect_visible_control_candidates(
        limit=limit,
        max_depth=max_depth,
        deadline_monotonic=deadline_monotonic,
    )

    return [
        {key: value for key, value in control.items() if key != "_wrapper"}
        for control in controls
    ]


def uia_get_visible_elements(
    *,
    max_depth: int = 3,
    limit: int = 40,
) -> dict[str, Any]:
    """Return a readable snapshot of currently visible UIA elements.

    The planner uses this to observe the real desktop state before attempting
    semantic UI actions. The returned structure is intentionally compact and
    stable so it can be fed back into the LLM prompt or execution logs.
    """

    controls = capture_active_window_controls(limit=limit, max_depth=max_depth)
    simplified: list[dict[str, Any]] = []
    summary_lines: list[str] = []
    for control in controls:
        entry = {
            "element_id": control.get("element_id"),
            "text": control.get("text"),
            "control_type": control.get("control_type"),
            "automation_id": control.get("automation_id"),
            "class_name": control.get("class_name"),
            "actionable": control.get("actionable", True),
            "left": control.get("left"),
            "top": control.get("top"),
            "right": control.get("right"),
            "bottom": control.get("bottom"),
            "bounds": {
                "left": control.get("left"),
                "top": control.get("top"),
                "right": control.get("right"),
                "bottom": control.get("bottom"),
            },
        }
        simplified.append(entry)
        label = str(control.get("text") or control.get("automation_id") or control.get("class_name") or "").strip()
        summary_lines.append(
            f"#{control.get('element_id')} {control.get('control_type') or 'Control'} {label}".strip()
        )
    return {
        "elements": simplified,
        "summary": "\n".join(summary_lines),
        "count": len(simplified),
    }


def _matches_partial_text(value: str, expected: str) -> bool:
    normalized_value = " ".join(value.strip().lower().split())
    normalized_expected = " ".join(expected.strip().lower().split())
    if not normalized_expected:
        return True
    return normalized_expected in normalized_value


def _control_matches_filters(
    control: dict[str, Any],
    *,
    target_text: str | None,
    automation_id: str | None,
    class_name: str | None,
    control_types: list[str],
) -> bool:
    control_text = str(control.get("text") or "")
    control_id = " ".join(str(control.get("automation_id") or "").strip().lower().split())
    control_class = " ".join(str(control.get("class_name") or "").strip().lower().split())
    control_type = " ".join(str(control.get("control_type") or "").strip().lower().split())

    if target_text and not _matches_partial_text(control_text, target_text):
        return False
    if automation_id and automation_id != control_id:
        return False
    if class_name and class_name != control_class:
        return False
    if control_types and control_type not in control_types:
        return False
    return True


def resolve_active_window_control(
    *,
    element_id: int,
    limit: int = 60,
    repoll_timeout_seconds: float = DEFAULT_UIA_REPOLL_TIMEOUT_SECONDS,
) -> dict[str, Any] | None:
    if int(element_id) <= 0:
        _set_last_ui_automation_error(
            f"element_id must be positive, received {element_id!r}."
        )
        return None
    _set_last_ui_automation_error(None)
    deadline_monotonic = time.monotonic() + max(repoll_timeout_seconds, 0.0)
    requested_limit = max(limit, int(element_id))
    while True:
        controls = capture_active_window_controls(limit=requested_limit)
        for control in controls:
            if int(control.get("element_id", 0)) == int(element_id):
                _set_last_ui_automation_error(None)
                return control
        if time.monotonic() >= deadline_monotonic:
            break
    _set_last_ui_automation_error(
        f"Could not find visible element_id={element_id} before the UI snapshot changed or timed out."
    )
    return None


def _invoke_wrapper(child: Any) -> bool:
    try:
        if hasattr(child, "set_focus"):
            child.set_focus()
    except Exception:
        pass

    for method_name in ("invoke", "click_input", "click"):
        try:
            method = getattr(child, method_name, None)
            if callable(method):
                method()
                return True
        except Exception:
            continue
    return False


def click_active_window_control(
    *,
    target_text: str | None = None,
    control_type: str | list[str] | None = None,
    automation_id: str | None = None,
    class_name: str | None = None,
    element_id: int | None = None,
    repoll_timeout_seconds: float = DEFAULT_UIA_REPOLL_TIMEOUT_SECONDS,
) -> bool:
    return (
        invoke_active_window_control(
            target_text=target_text,
            control_type=control_type,
            automation_id=automation_id,
            class_name=class_name,
            element_id=element_id,
            repoll_timeout_seconds=repoll_timeout_seconds,
        )
        is not None
    )


def invoke_active_window_control(
    *,
    target_text: str | None = None,
    control_type: str | list[str] | None = None,
    automation_id: str | None = None,
    class_name: str | None = None,
    element_id: int | None = None,
    repoll_timeout_seconds: float = DEFAULT_UIA_REPOLL_TIMEOUT_SECONDS,
) -> dict[str, Any] | None:
    _set_last_ui_automation_error(None)
    target_text_normalized = (target_text or "").strip().lower()
    automation_id_normalized = (automation_id or "").strip().lower()
    class_name_normalized = (class_name or "").strip().lower()
    control_types_normalized = _normalize_filter_strings(control_type)
    deadline_monotonic = time.monotonic() + max(repoll_timeout_seconds, 0.0)
    last_error = "No visible UI Automation controls were available."
    while True:
        controls = _collect_visible_control_candidates(
            limit=max(int(element_id or 0), 40),
            include_wrappers=True,
            max_depth=DEFAULT_UIA_DEPTH,
            deadline_monotonic=deadline_monotonic,
        )
        if not controls:
            last_error = get_last_ui_automation_error() or last_error
        elif element_id is not None:
            matched_control = None
            for control in controls:
                if int(control.get("element_id", 0)) != int(element_id):
                    continue
                matched_control = control
                child = control.get("_wrapper")
                if child is None:
                    last_error = f"element_id={element_id} no longer has a live UI wrapper."
                    break
                if _invoke_wrapper(child):
                    _set_last_ui_automation_error(None)
                    return {
                        key: value
                        for key, value in control.items()
                        if key != "_wrapper"
                    }
                last_error = f"Matched element_id={element_id}, but UI Automation could not invoke it."
                break
            if matched_control is None:
                last_error = (
                    f"element_id={element_id} was not present in the latest UI snapshot."
                )
        else:
            match_variants = [
                {
                    "target_text": target_text_normalized or None,
                    "automation_id": automation_id_normalized or None,
                    "class_name": class_name_normalized or None,
                    "control_types": control_types_normalized,
                },
                {
                    "target_text": target_text_normalized or None,
                    "automation_id": automation_id_normalized or None,
                    "class_name": class_name_normalized or None,
                    "control_types": [],
                },
                {
                    "target_text": target_text_normalized or None,
                    "automation_id": None,
                    "class_name": class_name_normalized or None,
                    "control_types": [],
                },
                {
                    "target_text": target_text_normalized or None,
                    "automation_id": None,
                    "class_name": None,
                    "control_types": [],
                },
            ]
            deduped_variants: list[dict[str, Any]] = []
            seen_variants: set[tuple[str | None, str | None, str | None, tuple[str, ...]]] = set()
            for variant in match_variants:
                signature = (
                    variant["target_text"],
                    variant["automation_id"],
                    variant["class_name"],
                    tuple(variant["control_types"]),
                )
                if signature in seen_variants:
                    continue
                seen_variants.add(signature)
                deduped_variants.append(variant)

            matched_control: dict[str, Any] | None = None
            for variant in deduped_variants:
                scored_matches: list[tuple[tuple[int, int, int, int, int], dict[str, Any], Any]] = []
                for control in controls:
                    try:
                        child = control.get("_wrapper")
                        if child is None:
                            continue
                        if not _control_matches_filters(
                            control,
                            target_text=variant["target_text"],
                            automation_id=variant["automation_id"],
                            class_name=variant["class_name"],
                            control_types=list(variant["control_types"]),
                        ):
                            continue

                        text_value = " ".join(str(control.get("text") or "").strip().lower().split())
                        automation_value = " ".join(str(control.get("automation_id") or "").strip().lower().split())
                        class_value = " ".join(str(control.get("class_name") or "").strip().lower().split())
                        control_value = " ".join(str(control.get("control_type") or "").strip().lower().split())

                        exact_text = int(bool(variant["target_text"] and text_value == variant["target_text"]))
                        exact_automation = int(bool(variant["automation_id"] and automation_value == variant["automation_id"]))
                        exact_class_name = int(bool(variant["class_name"] and class_value == variant["class_name"]))
                        typed_match = int(bool(variant["control_types"] and control_value in variant["control_types"]))
                        actionable_bonus = int(bool(control.get("actionable")))
                        scored_matches.append(
                            (
                                (
                                    exact_automation,
                                    exact_text,
                                    exact_class_name,
                                    typed_match,
                                    actionable_bonus,
                                ),
                                control,
                                child,
                            )
                        )
                    except Exception:
                        continue

                for _score, control, child in sorted(
                    scored_matches,
                    key=lambda item: item[0],
                    reverse=True,
                ):
                    if not _invoke_wrapper(child):
                        continue
                    _set_last_ui_automation_error(None)
                    matched_control = control
                    break
                if matched_control is not None:
                    break

            if matched_control is not None:
                return {
                    key: value
                    for key, value in matched_control.items()
                    if key != "_wrapper"
                }

            if target_text_normalized or automation_id_normalized or class_name_normalized or control_types_normalized:
                last_error = (
                    "No visible UI Automation control matched the requested text, automation id, class name, or control type."
                )
            else:
                last_error = "No visible UI Automation controls could be invoked."

        if time.monotonic() >= deadline_monotonic:
            break

    _set_last_ui_automation_error(last_error)
    return None


def focus_visible_search_input(
    *,
    limit: int = 40,
    max_depth: int = DEFAULT_UIA_DEPTH,
) -> dict[str, Any] | None:
    """Focus the best visible search/edit control for fallback text search.

    This is used as a last resort for apps like Windows Settings where a search
    box can deterministically navigate to a target page more reliably than
    repeated sidebar clicks.
    """

    _set_last_ui_automation_error(None)
    controls = _collect_visible_control_candidates(
        limit=limit,
        include_wrappers=True,
        max_depth=max_depth,
        deadline_monotonic=time.monotonic() + DEFAULT_UIA_REPOLL_TIMEOUT_SECONDS,
    )
    ranked: list[tuple[tuple[int, int, int], dict[str, Any], Any]] = []
    for control in controls:
        child = control.get("_wrapper")
        if child is None:
            continue
        control_type = " ".join(str(control.get("control_type") or "").strip().lower().split())
        if control_type not in {"edit", "combobox", "searchbox"}:
            continue
        text_value = " ".join(str(control.get("text") or "").strip().lower().split())
        automation_value = " ".join(str(control.get("automation_id") or "").strip().lower().split())
        class_value = " ".join(str(control.get("class_name") or "").strip().lower().split())
        search_signal = int(
            any(token in text_value for token in ("search", "find", "setting"))
            or any(token in automation_value for token in ("search", "find"))
            or "search" in class_value
        )
        ranked.append(((search_signal, int(bool(control.get("actionable"))), int(bool(text_value))), control, child))

    for _score, control, child in sorted(ranked, key=lambda item: item[0], reverse=True):
        if not _invoke_wrapper(child):
            continue
        _set_last_ui_automation_error(None)
        return {key: value for key, value in control.items() if key != "_wrapper"}

    _set_last_ui_automation_error("No visible searchable input control could be focused.")
    return None
