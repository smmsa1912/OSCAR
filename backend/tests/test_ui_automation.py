from __future__ import annotations

import pytest

from oscar.ui_automation import (
    capture_active_window_controls,
    click_active_window_control,
    get_last_ui_automation_error,
    resolve_active_window_control,
    uia_get_visible_elements,
)


class _Rect:
    def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom


class _ElementInfo:
    def __init__(
        self,
        *,
        control_type: str,
        automation_id: str = "",
        class_name: str = "",
        enabled: bool = True,
        keyboard_focusable: bool = False,
        handle: int | None = None,
    ) -> None:
        self.control_type = control_type
        self.automation_id = automation_id
        self.class_name = class_name
        self.enabled = enabled
        self.keyboard_focusable = keyboard_focusable
        self.handle = handle


class _Wrapper:
    def __init__(
        self,
        *,
        text: str = "",
        control_type: str = "Pane",
        automation_id: str = "",
        class_name: str = "",
        bounds: tuple[int, int, int, int] = (0, 0, 10, 10),
        children: list["_Wrapper"] | None = None,
        handle: int | None = None,
        visible: bool = True,
        focusable: bool = False,
    ) -> None:
        self._text = text
        self._visible = visible
        self._children = list(children or [])
        self._invoked = False
        self.element_info = _ElementInfo(
            control_type=control_type,
            automation_id=automation_id,
            class_name=class_name,
            enabled=True,
            keyboard_focusable=focusable,
            handle=handle,
        )
        self._rect = _Rect(*bounds)

    def children(self):
        return list(self._children)

    def rectangle(self):
        return self._rect

    def window_text(self):
        return self._text

    def is_visible(self):
        return self._visible

    def is_enabled(self):
        return True

    def set_focus(self):
        return None

    def invoke(self):
        self._invoked = True


class _Desktop:
    def __init__(self, active_wrapper: _Wrapper, windows: list[_Wrapper]) -> None:
        self._active_wrapper = active_wrapper
        self._windows = windows

    def window(self, *, handle: int):
        assert handle == 101
        return self._active_wrapper

    def windows(self):
        return list(self._windows)


def test_capture_active_window_controls_includes_context_menu_items(monkeypatch) -> None:
    main_button = _Wrapper(
        text="Rename",
        control_type="Button",
        bounds=(10, 10, 110, 40),
    )
    active_wrapper = _Wrapper(
        control_type="Window",
        bounds=(0, 0, 600, 400),
        children=[main_button],
        handle=101,
    )
    context_item = _Wrapper(
        text="Display settings",
        control_type="MenuItem",
        bounds=(20, 80, 220, 110),
    )
    context_menu = _Wrapper(
        control_type="Menu",
        class_name="#32768",
        bounds=(0, 60, 260, 320),
        children=[context_item],
        handle=202,
    )
    desktop = _Desktop(active_wrapper, [context_menu])

    monkeypatch.setattr(
        "oscar.ui_automation._load_desktop_backend",
        lambda: (lambda backend="uia": desktop),
    )
    monkeypatch.setattr(
        "oscar.window_control.get_active_window_info",
        lambda: {"hwnd": 101},
    )

    controls = capture_active_window_controls(limit=10)

    assert [control["text"] for control in controls] == ["Rename", "Display settings"]
    assert [control["element_id"] for control in controls] == [1, 2]


def test_click_active_window_control_can_target_context_menu_item(monkeypatch) -> None:
    context_item = _Wrapper(
        text="Refresh",
        control_type="MenuItem",
        bounds=(20, 80, 200, 110),
    )
    active_wrapper = _Wrapper(
        control_type="Window",
        bounds=(0, 0, 600, 400),
        children=[],
        handle=101,
    )
    context_menu = _Wrapper(
        control_type="Menu",
        class_name="#32768",
        bounds=(0, 60, 260, 320),
        children=[context_item],
        handle=202,
    )
    desktop = _Desktop(active_wrapper, [context_menu])

    monkeypatch.setattr(
        "oscar.ui_automation._load_desktop_backend",
        lambda: (lambda backend="uia": desktop),
    )
    monkeypatch.setattr(
        "oscar.window_control.get_active_window_info",
        lambda: {"hwnd": 101},
    )

    assert click_active_window_control(target_text="Refresh") is True
    assert context_item._invoked is True


def test_resolve_active_window_control_repools_until_element_appears(monkeypatch) -> None:
    snapshots = iter(
        [
            [],
            [
                {
                    "element_id": 1,
                    "text": "Continue",
                    "left": 10,
                    "top": 20,
                    "right": 110,
                    "bottom": 60,
                }
            ],
        ]
    )

    monkeypatch.setattr(
        "oscar.ui_automation.capture_active_window_controls",
        lambda limit=30: next(snapshots),
    )

    control = resolve_active_window_control(element_id=1, repoll_timeout_seconds=0.2)

    assert control is not None
    assert control["text"] == "Continue"


def test_click_active_window_control_records_error_when_no_match_is_found(monkeypatch) -> None:
    monkeypatch.setattr(
        "oscar.ui_automation._collect_visible_control_candidates",
        lambda **kwargs: [],
    )

    clicked = click_active_window_control(target_text="Refresh", repoll_timeout_seconds=0.0)

    assert clicked is False
    assert get_last_ui_automation_error() == "No visible UI Automation controls were available."


def test_click_active_window_control_allows_partial_text_and_looser_control_type(monkeypatch) -> None:
    sidebar_item = _Wrapper(
        text="Windows Update",
        control_type="NavigationViewItem",
        class_name="NavigationViewItem",
        bounds=(10, 10, 200, 40),
    )
    active_wrapper = _Wrapper(
        control_type="Window",
        bounds=(0, 0, 800, 600),
        children=[sidebar_item],
        handle=101,
    )
    desktop = _Desktop(active_wrapper, [])

    monkeypatch.setattr(
        "oscar.ui_automation._load_desktop_backend",
        lambda: (lambda backend="uia": desktop),
    )
    monkeypatch.setattr(
        "oscar.window_control.get_active_window_info",
        lambda: {"hwnd": 101},
    )

    clicked = click_active_window_control(
        target_text="Windows",
        control_type=["NavigationViewItem", "ListItem", "Button", "Hyperlink"],
    )

    assert clicked is True
    assert sidebar_item._invoked is True


def test_uia_get_visible_elements_returns_readable_summary(monkeypatch) -> None:
    search_box = _Wrapper(
        text="Find a setting",
        control_type="Edit",
        class_name="TextBox",
        bounds=(20, 20, 320, 56),
    )
    active_wrapper = _Wrapper(
        control_type="Window",
        bounds=(0, 0, 800, 600),
        children=[search_box],
        handle=101,
    )
    desktop = _Desktop(active_wrapper, [])

    monkeypatch.setattr(
        "oscar.ui_automation._load_desktop_backend",
        lambda: (lambda backend="uia": desktop),
    )
    monkeypatch.setattr(
        "oscar.window_control.get_active_window_info",
        lambda: {"hwnd": 101},
    )

    observed = uia_get_visible_elements(max_depth=3)

    assert observed["count"] == 1
    assert observed["elements"][0]["class_name"] == "TextBox"
    assert "#1 Edit Find a setting" in observed["summary"]
