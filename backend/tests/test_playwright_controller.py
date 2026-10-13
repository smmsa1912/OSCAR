from __future__ import annotations

import pytest

from oscar.browser.playwright_controller import PlaywrightController


class _ClosedContext:
    @property
    def pages(self):
        raise RuntimeError("Target page, context or browser has been closed")


class _FakePage:
    def __init__(self, url: str = "https://example.com") -> None:
        self.url = url

    async def title(self) -> str:
        return "Example"


class _HealthyContext:
    def __init__(self) -> None:
        self.pages = [_FakePage()]

    async def new_page(self):
        return _FakePage()


class _FakeBrowserType:
    def __init__(self, context: _HealthyContext) -> None:
        self.context = context
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def launch_persistent_context(self, user_data_dir: str, **kwargs):
        self.calls.append((user_data_dir, kwargs))
        return self.context


class _FakePlaywright:
    def __init__(self, context: _HealthyContext) -> None:
        self.chromium = _FakeBrowserType(context)

    async def stop(self) -> None:
        return None


class _FakeAsyncPlaywrightManager:
    def __init__(self, context: _HealthyContext) -> None:
        self.playwright = _FakePlaywright(context)

    async def start(self) -> _FakePlaywright:
        return self.playwright


@pytest.mark.anyio
async def test_controller_restarts_when_cached_context_is_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    healthy_context = _HealthyContext()
    controller = PlaywrightController()
    controller._context = _ClosedContext()
    controller._page = _FakePage()

    async def fake_load_playwright():
        return lambda: _FakeAsyncPlaywrightManager(healthy_context)

    monkeypatch.setattr(controller, "_load_playwright", fake_load_playwright)

    result = await controller.open_browser()

    assert result.success is True
    assert controller._context is healthy_context
    assert controller._page is healthy_context.pages[0]


def test_controller_is_active_clears_stale_context() -> None:
    controller = PlaywrightController()
    controller._context = _ClosedContext()
    controller._page = _FakePage()

    assert controller.is_active() is False
    assert controller._context is None
    assert controller._page is None


class _FakeLocatorInstance:
    def __init__(self) -> None:
        self.fill_calls: list[str] = []
        self.click_calls = 0
        self.wait_calls = 0

    @property
    def first(self):
        return self

    async def wait_for(self, *, state: str, timeout: int) -> None:
        assert state == "visible"
        assert timeout > 0
        self.wait_calls += 1

    async def click(self, *, timeout: int) -> None:
        assert timeout > 0
        self.click_calls += 1

    async def fill(self, value: str, *, timeout: int) -> None:
        assert timeout > 0
        self.fill_calls.append(value)


class _FakeFormPage(_FakePage):
    def __init__(self, locator: _FakeLocatorInstance) -> None:
        super().__init__("https://example.com/form")
        self._locator = locator

    def get_by_label(self, text: str, exact: bool = True):
        assert text == "Email"
        assert exact is True
        return self._locator


@pytest.mark.anyio
async def test_controller_find_and_type_fills_matching_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    locator = _FakeLocatorInstance()
    controller = PlaywrightController()
    controller._context = _HealthyContext()
    controller._page = _FakeFormPage(locator)

    captured_policies: list[object] = []

    async def fake_wait_for_condition(predicate, *, policy):
        captured_policies.append(policy)
        return await predicate()

    monkeypatch.setattr(
        "oscar.browser.playwright_controller.async_wait_for_condition",
        fake_wait_for_condition,
    )

    result = await controller.find_and_type("Email", "user@example.com")

    assert result.success is True
    assert locator.wait_calls == 1
    assert locator.click_calls == 1
    assert locator.fill_calls == ["user@example.com"]
    assert len(captured_policies) == 1
    assert result.data["matched_selector_strategy"] == "label"


class _FakeTabPage(_FakePage):
    def __init__(self, url: str, title: str) -> None:
        super().__init__(url)
        self._title = title
        self.brought_to_front = False

    async def title(self) -> str:
        return self._title

    async def bring_to_front(self) -> None:
        self.brought_to_front = True


@pytest.mark.anyio
async def test_controller_switch_tab_uses_existing_matching_page() -> None:
    current_page = _FakeTabPage("https://example.com", "Example")
    github_page = _FakeTabPage("https://web.whatsapp.com", "(24) WhatsApp")
    controller = PlaywrightController()
    controller._context = type("Context", (), {"pages": [current_page, github_page]})()
    controller._page = current_page

    result = await controller.switch_tab(
        title_contains="WhatsApp",
        url="https://web.whatsapp.com",
    )

    assert result.success is True
    assert controller.page is github_page
    assert github_page.brought_to_front is True
    assert result.data["matched_tab"] == "WhatsApp"


@pytest.mark.anyio
async def test_controller_switch_tab_reports_already_active_page() -> None:
    github_page = _FakeTabPage("https://github.com", "GitHub")
    controller = PlaywrightController()
    controller._context = type("Context", (), {"pages": [github_page]})()
    controller._page = github_page

    result = await controller.switch_tab("GitHub", url="https://github.com")

    assert result.success is True
    assert result.data["already_active"] is True
    assert result.data["matched_tab"] == "GitHub"


@pytest.mark.anyio
async def test_controller_get_tabs_returns_clean_tab_snapshot() -> None:
    first_page = _FakeTabPage("https://example.com", "Example")
    second_page = _FakeTabPage("https://web.whatsapp.com", "WhatsApp")
    controller = PlaywrightController()
    controller._context = type("Context", (), {"pages": [first_page, second_page]})()
    controller._page = second_page

    result = await controller.get_tabs()

    assert result.success is True
    assert result.data["tabs"] == [
        {"id": 1, "title": "Example", "url": "https://example.com", "active": False},
        {"id": 2, "title": "WhatsApp", "url": "https://web.whatsapp.com", "active": True},
    ]


@pytest.mark.anyio
async def test_controller_navigate_reuses_existing_tab_for_matching_url() -> None:
    first_page = _FakeTabPage("https://example.com", "Example")
    second_page = _FakeTabPage("https://web.whatsapp.com", "WhatsApp")
    controller = PlaywrightController()
    controller._context = type("Context", (), {"pages": [first_page, second_page]})()
    controller._page = first_page

    result = await controller.navigate("https://web.whatsapp.com")

    assert result.success is True
    assert controller.page is second_page
    assert second_page.brought_to_front is True
    assert result.data["already_open"] is True


@pytest.mark.anyio
async def test_playwright_controller_navigation_dry_run_never_opens_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from oscar import config

    monkeypatch.setattr(config, "OSCAR_DRY_RUN", True)
    monkeypatch.setattr(
        "oscar.browser.playwright_controller.config.OSCAR_DRY_RUN", True
    )
    controller = PlaywrightController()

    async def forbidden_ensure_page(*args, **kwargs):
        raise AssertionError("browser must not be started in dry-run mode")

    monkeypatch.setattr(controller, "_ensure_page", forbidden_ensure_page)
    result = await controller.navigate("https://example.com")

    assert result.success is True
    assert result.data["dry_run"] is True
    assert result.data["execution_confirmed"] is False


@pytest.mark.anyio
async def test_playwright_controller_close_dry_run_preserves_browser_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from oscar import config

    monkeypatch.setattr(config, "OSCAR_DRY_RUN", True)
    monkeypatch.setattr(
        "oscar.browser.playwright_controller.config.OSCAR_DRY_RUN", True
    )
    controller = PlaywrightController()

    class FakeContext:
        closed = False

        async def close(self):
            self.closed = True

    context = FakeContext()
    controller._context = context
    await controller.close()

    assert context.closed is False
    assert controller._context is context


@pytest.mark.anyio
async def test_playwright_controller_get_tabs_dry_run_never_inspects_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from oscar import config

    monkeypatch.setattr(config, "OSCAR_DRY_RUN", True)
    monkeypatch.setattr(
        "oscar.browser.playwright_controller.config.OSCAR_DRY_RUN", True
    )
    controller = PlaywrightController()

    def forbidden_is_active():
        raise AssertionError("browser state must not be inspected in dry-run mode")

    monkeypatch.setattr(controller, "is_active", forbidden_is_active)
    result = await controller.get_tabs()

    assert result.success is True
    assert result.action == "browser_get_tabs"
    assert result.data["dry_run"] is True
    assert result.data["execution_confirmed"] is False


@pytest.mark.anyio
async def test_playwright_controller_wait_for_text_dry_run_never_touches_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from oscar import config

    monkeypatch.setattr(config, "OSCAR_DRY_RUN", True)
    monkeypatch.setattr(
        "oscar.browser.playwright_controller.config.OSCAR_DRY_RUN", True
    )
    controller = PlaywrightController()

    async def forbidden_ensure_page(*args, **kwargs):
        raise AssertionError("page must not be accessed in dry-run mode")

    monkeypatch.setattr(controller, "_ensure_page", forbidden_ensure_page)
    result = await controller.wait_for_text("Ready")

    assert result.success is True
    assert result.action == "browser_wait_for"
    assert result.data["dry_run"] is True
    assert result.data["execution_confirmed"] is False


@pytest.mark.anyio
async def test_playwright_controller_extract_dry_run_never_reads_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from oscar import config

    monkeypatch.setattr(config, "OSCAR_DRY_RUN", True)
    monkeypatch.setattr(
        "oscar.browser.playwright_controller.config.OSCAR_DRY_RUN", True
    )
    controller = PlaywrightController()

    async def forbidden_ensure_page(*args, **kwargs):
        raise AssertionError("page must not be accessed in dry-run mode")

    monkeypatch.setattr(controller, "_ensure_page", forbidden_ensure_page)
    result = await controller.extract_main_content()

    assert result.success is True
    assert result.action == "browser_extract"
    assert result.data["dry_run"] is True
    assert result.data["execution_confirmed"] is False
