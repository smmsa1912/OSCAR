from __future__ import annotations

import pytest

from oscar.agents.browser_agent import BrowserAgent
from oscar.runtime import ActionResult


class FakeController:
    def __init__(self, *, search_results: list[ActionResult] | None = None) -> None:
        self.calls: list[tuple[str, object]] = []
        self.active = False
        self.page = None
        self.search_results = list(search_results or [])

    def is_active(self) -> bool:
        return self.active

    async def get_state(self):
        return {"url": "https://example.com", "title": "Example"}

    async def get_tabs(self):
        self.calls.append(("get_tabs", None))
        return ActionResult(
            success=True,
            route="browser",
            action="browser_get_tabs",
            data={
                "tabs": [
                    {
                        "id": 1,
                        "title": "Example",
                        "url": "https://example.com",
                        "active": True,
                    }
                ]
            },
            context_updates={
                "browser_tabs": [
                    {
                        "id": 1,
                        "title": "Example",
                        "url": "https://example.com",
                        "active": True,
                    }
                ]
            },
        )

    async def open_browser(self, **kwargs):
        self.calls.append(("open_browser", kwargs))
        self.active = True
        return ActionResult(success=True, route="browser", action="browser_open")

    async def search(self, query: str):
        self.calls.append(("search", query))
        if self.search_results:
            return self.search_results.pop(0)
        return ActionResult(
            success=True,
            route="browser",
            action="browser_search",
            data={"url": "https://www.google.com/search?q=red+pandas"},
            context_updates={"url": "https://www.google.com/search?q=red+pandas"},
        )

    async def click_tab(self, name: str, *, selector_strategy=None):
        self.calls.append(("click_tab", (name, selector_strategy)))
        return ActionResult(success=True, route="browser", action="browser_click")

    async def find_and_click(self, text: str, *, selector_strategy=None):
        self.calls.append(("find_and_click", (text, selector_strategy)))
        return ActionResult(success=True, route="browser", action="browser_find")

    async def find_and_type(self, text: str, type_text: str, *, selector_strategy=None):
        self.calls.append(("find_and_type", (text, type_text, selector_strategy)))
        return ActionResult(success=True, route="browser", action="browser_type")

    async def extract_main_content(self):
        self.calls.append(("extract_main_content", None))
        return ActionResult(success=True, route="browser", action="browser_extract")

    async def wait_for_text(self, text: str, *, selector_strategy=None):
        self.calls.append(("wait_for_text", (text, selector_strategy)))
        return ActionResult(success=True, route="browser", action="browser_wait_for")

    async def switch_tab(self, text: str | None = None, *, url=None, title_contains=None):
        self.calls.append(("switch_tab", (text, url, title_contains)))
        return ActionResult(success=True, route="browser", action="browser_switch_tab")

    async def navigate(
        self,
        url: str,
        *,
        reopen_session=False,
        reload=False,
        wait_timeout_seconds=None,
    ):
        self.calls.append(
            ("navigate", (url, reopen_session, reload, wait_timeout_seconds))
        )
        return ActionResult(success=True, route="browser", action="browser_navigate")


@pytest.mark.anyio
async def test_browser_agent_dispatches_high_level_actions() -> None:
    controller = FakeController()
    agent = BrowserAgent(controller=controller, native_browser_enabled=False)

    await agent.run({"action": "browser_search", "query": "red pandas"})
    await agent.run({"action": "browser_get_tabs"})
    await agent.run({"action": "browser_click", "text": "Images"})
    await agent.run({"action": "browser_switch_tab", "title_contains": "GitHub", "url": "https://github.com"})
    await agent.run(
        {"action": "browser_type", "target_text": "Search", "text": "red pandas"}
    )
    await agent.run({"action": "browser_extract"})

    assert controller.calls[0] == (
        "open_browser",
        {"session_mode": "managed", "profile_name": None, "browser_name": "chromium"},
    )
    assert controller.calls[1] == ("search", "red pandas")
    assert controller.calls[2][0] == "get_tabs"
    assert controller.calls[3][0] == "click_tab"
    assert controller.calls[4][0] == "switch_tab"
    assert controller.calls[5][0] == "find_and_type"
    assert controller.calls[-1][0] == "extract_main_content"
    assert [call[0] for call in controller.calls].count("open_browser") == 1


@pytest.mark.anyio
async def test_browser_agent_get_tabs_uses_controller_snapshot() -> None:
    controller = FakeController()
    controller.active = True
    agent = BrowserAgent(controller=controller, native_browser_enabled=False)

    result = await agent.get_tabs()

    assert result.success is True
    assert result.data["tabs"][0]["url"] == "https://example.com"
    assert controller.calls == [("get_tabs", None)]


@pytest.mark.anyio
async def test_browser_agent_switch_tab_falls_back_to_navigation_for_native_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = BrowserAgent(native_browser_enabled=True)
    calls: list[tuple[str | None, str | None]] = []

    async def fake_navigate(url: str, **_kwargs):
        calls.append((url, _kwargs.get("browser_name")))
        return ActionResult(success=True, route="browser", action="browser_navigate")

    monkeypatch.setattr(agent, "navigate", fake_navigate)

    result = await agent.switch_tab("GitHub", url="https://github.com")

    assert result.success is True
    assert calls == [("https://github.com", None)]


@pytest.mark.anyio
async def test_browser_agent_switch_tab_passes_partial_title_and_url_to_controller() -> None:
    controller = FakeController()
    controller.active = True
    agent = BrowserAgent(controller=controller, native_browser_enabled=False)

    result = await agent.switch_tab(title_contains="WhatsApp", url="https://web.whatsapp.com")

    assert result.success is True
    assert controller.calls == [
        ("switch_tab", (None, "https://web.whatsapp.com", "WhatsApp"))
    ]


@pytest.mark.anyio
async def test_browser_agent_browser_type_opens_managed_controller_even_when_native_enabled() -> None:
    controller = FakeController()
    agent = BrowserAgent(controller=controller, native_browser_enabled=True)

    result = await agent.run(
        {"action": "browser_type", "target_text": "Email", "text": "user@example.com"}
    )

    assert result.success is True
    assert controller.calls[0] == (
        "open_browser",
        {"session_mode": "managed", "browser_name": "chromium"},
    )
    assert controller.calls[1] == (
        "find_and_type",
        ("Email", "user@example.com", None),
    )


@pytest.mark.anyio
async def test_browser_agent_passes_reload_flag_for_navigation_retries() -> None:
    controller = FakeController()
    agent = BrowserAgent(controller=controller, native_browser_enabled=False)

    await agent.run(
        {
            "action": "browser_navigate",
            "url": "https://example.com",
            "reload": True,
            "wait_timeout_seconds": 12,
        }
    )

    assert controller.calls[1] == (
        "navigate",
        ("https://example.com", False, True, 12.0),
    )


@pytest.mark.anyio
async def test_browser_agent_marks_google_captcha_as_non_retryable_and_suggests_simpler_query() -> None:
    controller = FakeController(
        search_results=[
            ActionResult(
                success=True,
                route="browser",
                action="browser_search",
                data={"url": "https://www.google.com/sorry/index"},
                context_updates={"url": "https://www.google.com/sorry/index"},
            ),
            ActionResult(
                success=True,
                route="browser",
                action="browser_search",
                data={"url": "https://www.google.com/search?q=pomeranian+dog"},
                context_updates={"url": "https://www.google.com/search?q=pomeranian+dog"},
            ),
        ]
    )
    agent = BrowserAgent(controller=controller, native_browser_enabled=False)

    result = await agent.run(
        {
            "action": "browser_search",
            "query": "cute pomeranian dog images",
        }
    )

    assert result.success is False
    assert result.retryable is False
    assert result.failure_reason == "Blocked by Google CAPTCHA"
    assert result.data["blocked"] is True
    assert result.data["suggested_query"] == "pomeranian dog"
    assert controller.calls[1] == ("search", "cute pomeranian dog")
    assert len(controller.calls) == 2


@pytest.mark.anyio
async def test_browser_agent_marks_google_captcha_as_non_retryable_when_query_cannot_be_simplified() -> None:
    controller = FakeController(
        search_results=[
            ActionResult(
                success=True,
                route="browser",
                action="browser_search",
                data={"url": "https://www.google.com/sorry/index"},
                context_updates={"url": "https://www.google.com/sorry/index"},
            )
        ]
    )
    agent = BrowserAgent(controller=controller, native_browser_enabled=False)

    result = await agent.run(
        {
            "action": "browser_search",
            "query": "pomeranian dog",
        }
    )

    assert result.success is False
    assert result.retryable is False
    assert result.failure_reason == "Blocked by Google CAPTCHA"


@pytest.mark.anyio
async def test_browser_agent_native_search_uses_real_browser_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = BrowserAgent(native_browser_enabled=True)
    open_calls: list[tuple[str | None, str | None, str | None, str, str | None]] = []

    async def fake_open_native_browser(
        *,
        browser_name,
        profile_name,
        url=None,
        action_name="browser_open",
        query=None,
    ):
        open_calls.append((browser_name, profile_name, url, action_name, query))
        return ActionResult(
            success=True,
            route="browser",
            action=action_name,
            data={"url": url},
            context_updates={"url": url, "browser_url": url},
        )

    monkeypatch.setattr(agent, "_open_native_browser", fake_open_native_browser)

    result = await agent.run(
        {
            "action": "browser_search",
            "query": "pomerian dog",
            "browser_name": "chrome",
            "profile_name": "Andrew",
        }
    )

    assert result.success is True
    assert open_calls == [
        (
            "chrome",
            "Andrew",
            "https://www.google.com/search?q=pomeranian+dog",
            "browser_search",
            "pomeranian dog",
        )
    ]


@pytest.mark.anyio
async def test_browser_agent_native_click_images_rewrites_google_search_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = BrowserAgent(native_browser_enabled=True)
    agent._native_browser_name = "chrome"
    agent._native_profile_name = "Andrew"
    agent._native_current_url = "https://www.google.com/search?q=pomeranian+dog"

    calls: list[str] = []

    async def fake_navigate_existing_native_browser(
        *,
        browser_name,
        profile_name,
        url=None,
        action_name="browser_navigate",
        query=None,
    ):
        calls.append(str(url))
        return ActionResult(success=True, route="browser", action=action_name)

    monkeypatch.setattr(
        agent,
        "_navigate_existing_native_browser",
        fake_navigate_existing_native_browser,
    )

    result = await agent.click_tab("Images")

    assert result.success is True
    assert calls == ["https://www.google.com/search?q=pomeranian+dog&tbm=isch"]


@pytest.mark.anyio
async def test_browser_agent_navigate_treats_browser_name_as_focus_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = BrowserAgent(native_browser_enabled=True)
    calls: list[tuple[str | None, str | None, str | None, str]] = []

    async def fake_open_native_browser(
        *,
        browser_name,
        profile_name,
        url=None,
        action_name="browser_open",
        query=None,
    ):
        calls.append((browser_name, profile_name, url, action_name))
        return ActionResult(success=True, route="browser", action=action_name)

    monkeypatch.setattr(agent, "_open_native_browser", fake_open_native_browser)

    result = await agent.navigate("chrome", browser_name="chrome", profile_name="Andrew")

    assert result.success is True
    assert calls == [("chrome", "Andrew", None, "browser_open")]


@pytest.mark.anyio
async def test_browser_agent_existing_native_navigation_uses_os_launch_instead_of_address_bar_typing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = BrowserAgent(native_browser_enabled=True)
    calls: list[dict[str, object]] = []

    async def fake_run_sync(func, *args):
        return func(*args)

    monkeypatch.setattr("oscar.agents.browser_agent.anyio.to_thread.run_sync", fake_run_sync)
    monkeypatch.setattr(
        "oscar.agents.browser_agent.validate_action",
        lambda action: dict(action),
    )
    monkeypatch.setattr(
        "oscar.agents.browser_agent.execute_action",
        lambda action: calls.append(dict(action)) or None,
    )
    monkeypatch.setattr("oscar.agents.browser_agent.focus_app_window", lambda *args, **kwargs: True)
    monkeypatch.setattr("oscar.agents.browser_agent.app_window_exists", lambda *_args, **_kwargs: True)

    result = await agent._navigate_existing_native_browser(
        browser_name="chrome",
        profile_name="Andrew",
        url="https://github.com",
        action_name="browser_navigate",
    )

    assert result.success is True
    assert calls == [
        {
            "action": "open_app",
            "app_name": "chrome",
            "reasoning": "Ask the operating system to open the URL directly in the user's real browser profile.",
            "task_complete": False,
            "url": "https://github.com",
            "profile_name": "Andrew",
        }
    ]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("method_name", "args", "kwargs", "expected_action"),
    [
        ("open_browser", (), {}, "browser_open"),
        ("search_and_open", ("red pandas",), {}, "browser_search"),
        ("navigate", ("https://example.com",), {}, "browser_navigate"),
        ("get_tabs", (), {}, "browser_get_tabs"),
        ("click_tab", ("Settings",), {}, "browser_click"),
        ("switch_tab", (), {"url": "https://example.com"}, "browser_switch_tab"),
        ("find_and_click", ("Submit",), {}, "browser_find"),
        ("type_text", ("Search", "secret text"), {}, "browser_type"),
        ("extract_main_content", (), {}, "browser_extract"),
        ("wait_for_text", ("Ready",), {}, "browser_wait_for"),
    ],
)
async def test_direct_browser_methods_are_side_effect_free_in_dry_run(
    monkeypatch, method_name, args, kwargs, expected_action
) -> None:
    from oscar import config

    monkeypatch.setattr(config, "OSCAR_DRY_RUN", True)
    controller = FakeController()
    agent = BrowserAgent(controller=controller, native_browser_enabled=False)

    method = getattr(agent, method_name)
    result = await method(*args, **kwargs)

    assert result.success is True
    assert result.action == expected_action
    assert result.data["dry_run"] is True
    assert result.data["execution_confirmed"] is False
    assert result.data["would_execute"] == expected_action
    assert controller.calls == []
