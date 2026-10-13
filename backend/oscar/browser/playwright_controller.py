"""Async Playwright browser controller."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from urllib.parse import quote_plus

from oscar import config
from oscar.browser.browser_session import BrowserSessionConfig
from oscar.browser.selector_resolver import SelectorResolver
from oscar.runtime import ActionResult
from oscar.utils.retry import RetryPolicy, async_wait_for_condition
from oscar.window_control import resolve_chrome_profile_directory


class PlaywrightController:
    """Owns a long-lived Playwright browser session."""

    def __init__(self, *, selector_resolver: SelectorResolver | None = None) -> None:
        self.selector_resolver = selector_resolver or SelectorResolver()
        self._playwright = None
        self._context = None
        self._page = None
        self._session_config: BrowserSessionConfig | None = None

    @staticmethod
    def _dry_run_result(action: str, **details) -> ActionResult:
        return ActionResult(
            success=True,
            route="browser",
            action=action,
            confidence=1.0,
            data={
                "dry_run": True,
                "execution_confirmed": False,
                "would_execute": action,
                "details": details,
                "message": "Dry-run enabled; no browser action was executed.",
            },
            retryable=False,
        )

    @property
    def page(self):
        return self._page

    def is_active(self) -> bool:
        """Return whether a usable page/context already exists."""

        if self._page is None or self._context is None:
            return False
        if not self._context_is_alive():
            self._context = None
            self._page = None
            return False
        return True

    async def open_browser(
        self,
        *,
        session_mode: str = "managed",
        profile_name: str | None = None,
        browser_name: str = "chromium",
    ) -> ActionResult:
        if config.OSCAR_DRY_RUN:
            return self._dry_run_result("browser_open", browser_name=browser_name)
        config_obj = BrowserSessionConfig(
            session_mode=session_mode,
            browser_name=browser_name,
            profile_name=profile_name,
        )
        try:
            await self._ensure_context(config_obj, restart=False)
        except Exception as exc:
            return ActionResult(
                success=False,
                route="browser",
                action="browser_open",
                failure_reason=str(exc),
                retryable=True,
            )
        state = await self.get_state()
        return ActionResult(
            success=True,
            route="browser",
            action="browser_open",
            confidence=0.9,
            data=state,
            context_updates=state,
        )

    async def navigate(
        self,
        url: str,
        *,
        reopen_session: bool = False,
        reload: bool = False,
        wait_timeout_seconds: float | None = None,
    ) -> ActionResult:
        if config.OSCAR_DRY_RUN:
            return self._dry_run_result("browser_navigate", url=url, reload=reload)
        try:
            await self._ensure_page(restart=reopen_session)
            existing_page = self._find_page_by_url(url)
            if existing_page is not None:
                self._page = existing_page
                try:
                    bring_to_front = getattr(existing_page, "bring_to_front", None)
                    if callable(bring_to_front):
                        await bring_to_front()
                except Exception:
                    pass
                if reload:
                    await self._page.reload(
                        wait_until="domcontentloaded",
                        timeout=int(
                            (wait_timeout_seconds or config.PLAYWRIGHT_TIMEOUT_SECONDS)
                            * 1000
                        ),
                    )
                state = await self.get_state()
                state["already_open"] = True
                return ActionResult(
                    success=True,
                    route="browser",
                    action="browser_navigate",
                    confidence=0.95,
                    data=state,
                    context_updates=state,
                    retryable=False,
                )
            timeout_ms = int(
                (wait_timeout_seconds or config.PLAYWRIGHT_TIMEOUT_SECONDS) * 1000
            )
            current_url = getattr(self._page, "url", None)
            if reload and current_url and current_url == url:
                await self._page.reload(
                    wait_until="domcontentloaded",
                    timeout=timeout_ms,
                )
            else:
                await self._page.goto(
                    url, wait_until="domcontentloaded", timeout=timeout_ms
                )
            state = await self.get_state()
            return ActionResult(
                success=True,
                route="browser",
                action="browser_navigate",
                confidence=0.9,
                data=state,
                context_updates=state,
            )
        except Exception as exc:
            return ActionResult(
                success=False,
                route="browser",
                action="browser_navigate",
                failure_reason=str(exc),
                retryable=True,
            )

    async def get_tabs(self) -> ActionResult:
        """Return a clean snapshot of currently open browser tabs."""

        if not self.is_active():
            return ActionResult(
                success=True,
                route="browser",
                action="browser_get_tabs",
                confidence=0.7,
                data={"tabs": []},
                context_updates={"browser_tabs": []},
                retryable=False,
            )

        tabs = await self._list_tabs()
        state = await self.get_state()
        state["tabs"] = tabs
        state["browser_tabs"] = tabs
        return ActionResult(
            success=True,
            route="browser",
            action="browser_get_tabs",
            confidence=0.95,
            data=state,
            context_updates={"browser_tabs": tabs, **state},
            retryable=False,
        )

    async def search(self, query: str) -> ActionResult:
        search_url = f"https://www.google.com/search?q={quote_plus(query)}"
        result = await self.navigate(search_url)
        result.action = "browser_search"
        if result.success:
            result.data["query"] = query
            result.context_updates["browser_url"] = result.data.get("url")
        return result

    async def click_tab(
        self,
        name: str,
        *,
        selector_strategy: str | None = None,
    ) -> ActionResult:
        if config.OSCAR_DRY_RUN:
            return self._dry_run_result("browser_click", target_text=name)
        try:
            await self._ensure_page()
            timeout_ms = int(config.PLAYWRIGHT_TIMEOUT_SECONDS * 1000)
            already_active, active_strategy = await self.selector_resolver.locator_looks_active(
                self._page,
                text=name,
                preferred=selector_strategy,
                timeout_ms=timeout_ms,
            )
            if already_active:
                state = await self.get_state()
                state["matched_selector_strategy"] = active_strategy
                state["already_active"] = True
                return ActionResult(
                    success=True,
                    route="browser",
                    action="browser_click",
                    confidence=0.98,
                    data=state,
                    context_updates=state,
                    strategy=active_strategy,
                    retryable=False,
                )
        except Exception:
            pass
        return await self.find_and_click(
            name,
            selector_strategy=selector_strategy,
            action_name="browser_click",
        )

    async def find_and_click(
        self,
        text: str,
        *,
        selector_strategy: str | None = None,
        action_name: str = "browser_find",
    ) -> ActionResult:
        if config.OSCAR_DRY_RUN:
            return self._dry_run_result(action_name, target_text=text)
        try:
            await self._ensure_page()
            timeout_ms = int(config.PLAYWRIGHT_TIMEOUT_SECONDS * 1000)
            previous_state = await self.get_state()
            clicked, strategy = await self.selector_resolver.click(
                self._page,
                text=text,
                preferred=selector_strategy,
                timeout_ms=timeout_ms,
            )
            if not clicked:
                return ActionResult(
                    success=False,
                    route="browser",
                    action=action_name,
                    confidence=0.2,
                    failure_reason=f"selector_not_found:{text}",
                    retryable=True,
                    data={"text": text},
                )
            state = await self._capture_state_after_interaction(
                previous_url=previous_state.get("url"),
                previous_title=previous_state.get("title"),
            )
            state["matched_selector_strategy"] = strategy
            return ActionResult(
                success=True,
                route="browser",
                action=action_name,
                confidence=0.95 if strategy in {"role", "label", "text"} else 0.7,
                data=state,
                context_updates=state,
                strategy=strategy,
            )
        except Exception as exc:
            return ActionResult(
                success=False,
                route="browser",
                action=action_name,
                failure_reason=str(exc),
                retryable=True,
            )

    async def find_and_type(
        self,
        text: str,
        type_text: str,
        *,
        selector_strategy: str | None = None,
        action_name: str = "browser_type",
    ) -> ActionResult:
        if config.OSCAR_DRY_RUN:
            return self._dry_run_result(action_name, target_text=text, text=type_text)
        try:
            await self._ensure_page()
            timeout_ms = int(config.PLAYWRIGHT_TIMEOUT_SECONDS * 1000)
            previous_state = await self.get_state()
            locator, strategy = self._resolve_input_locator(
                text=text,
                preferred=selector_strategy,
            )
            if locator is None:
                return ActionResult(
                    success=False,
                    route="browser",
                    action=action_name,
                    confidence=0.2,
                    failure_reason=f"selector_not_found:{text}",
                    retryable=True,
                    data={"target_text": text, "text": type_text},
                )
            try:
                await locator.first.wait_for(state="visible", timeout=timeout_ms)
                await locator.first.click(timeout=timeout_ms)
                await locator.first.fill(type_text, timeout=timeout_ms)
            except Exception:
                try:
                    await locator.first.wait_for(state="visible", timeout=timeout_ms)
                    await locator.first.click(timeout=timeout_ms)
                    await locator.first.type(type_text, timeout=timeout_ms)
                except Exception:
                    return ActionResult(
                        success=False,
                        route="browser",
                        action=action_name,
                        confidence=0.2,
                        failure_reason=f"selector_not_found:{text}",
                        retryable=True,
                        data={"target_text": text, "text": type_text},
                    )
            state = await self._capture_state_after_interaction(
                previous_url=previous_state.get("url"),
                previous_title=previous_state.get("title"),
            )
            state["matched_selector_strategy"] = strategy
            state["target_text"] = text
            state["typed_text"] = type_text
            return ActionResult(
                success=True,
                route="browser",
                action=action_name,
                confidence=0.95 if strategy in {"role", "label", "text"} else 0.75,
                data=state,
                context_updates=state,
                strategy=strategy,
            )
        except Exception as exc:
            return ActionResult(
                success=False,
                route="browser",
                action=action_name,
                failure_reason=str(exc),
                retryable=True,
            )

    async def switch_tab(
        self,
        text: str | None = None,
        *,
        url: str | None = None,
        title_contains: str | None = None,
    ) -> ActionResult:
        if config.OSCAR_DRY_RUN:
            return self._dry_run_result("browser_switch_tab", text=text, url=url)
        try:
            await self._ensure_page()
            pages = list(getattr(self._context, "pages", []) or [])
            if not pages and self._page is not None:
                pages = [self._page]

            title_filter = " ".join(str(title_contains or text or "").strip().split())
            current_state = await self.get_state()
            if self._page is not None and await self._page_matches(
                self._page,
                url=url,
                title_contains=title_filter,
            ):
                current_state["already_active"] = True
                current_state["matched_tab"] = title_filter or url
                return ActionResult(
                    success=True,
                    route="browser",
                    action="browser_switch_tab",
                    confidence=0.98,
                    data=current_state,
                    context_updates=current_state,
                    retryable=False,
                )

            for page in pages:
                if page is self._page:
                    continue
                if not await self._page_matches(
                    page,
                    url=url,
                    title_contains=title_filter,
                ):
                    continue
                self._page = page
                try:
                    bring_to_front = getattr(page, "bring_to_front", None)
                    if callable(bring_to_front):
                        await bring_to_front()
                except Exception:
                    pass
                state = await self.get_state()
                state["matched_tab"] = title_filter or url or text
                return ActionResult(
                    success=True,
                    route="browser",
                    action="browser_switch_tab",
                    confidence=0.95,
                    data=state,
                    context_updates=state,
                    retryable=False,
                )

            return ActionResult(
                success=False,
                route="browser",
                action="browser_switch_tab",
                confidence=0.2,
                failure_reason=f"tab_not_found:{title_filter or url or text or ''}",
                retryable=False,
                data={"title_contains": title_filter, "url": url},
            )
        except Exception as exc:
            return ActionResult(
                success=False,
                route="browser",
                action="browser_switch_tab",
                failure_reason=str(exc),
                retryable=True,
            )

    async def wait_for_text(
        self,
        text: str,
        *,
        selector_strategy: str | None = None,
    ) -> ActionResult:
        try:
            await self._ensure_page()
            timeout_ms = int(config.PLAYWRIGHT_TIMEOUT_SECONDS * 1000)
            found, strategy = await self.selector_resolver.wait_for_text(
                self._page,
                text=text,
                preferred=selector_strategy,
                timeout_ms=timeout_ms,
            )
            if not found:
                return ActionResult(
                    success=False,
                    route="browser",
                    action="browser_wait_for",
                    confidence=0.2,
                    failure_reason=f"text_not_found:{text}",
                    retryable=True,
                    data={"text": text},
                )
            state = await self.get_state()
            state["matched_selector_strategy"] = strategy
            return ActionResult(
                success=True,
                route="browser",
                action="browser_wait_for",
                confidence=0.9 if strategy in {"role", "label", "text"} else 0.7,
                data=state,
                context_updates=state,
                strategy=strategy,
            )
        except Exception as exc:
            return ActionResult(
                success=False,
                route="browser",
                action="browser_wait_for",
                failure_reason=str(exc),
                retryable=True,
            )

    async def extract_main_content(self) -> ActionResult:
        try:
            await self._ensure_page()
            text = ""
            if hasattr(self._page, "locator"):
                for selector in ("main", "article", "[role='main']", "body"):
                    try:
                        locator = self._page.locator(selector)
                        content = (
                            await locator.first.inner_text(
                                timeout=int(config.PLAYWRIGHT_TIMEOUT_SECONDS * 1000)
                            )
                        ).strip()
                    except Exception:
                        continue
                    if content:
                        text = content
                        break
            state = await self.get_state()
            state["content"] = text
            return ActionResult(
                success=bool(text),
                route="browser",
                action="browser_extract",
                confidence=0.9 if text else 0.2,
                data=state,
                failure_reason=None if text else "empty_content",
                retryable=not bool(text),
                context_updates=state,
            )
        except Exception as exc:
            return ActionResult(
                success=False,
                route="browser",
                action="browser_extract",
                failure_reason=str(exc),
                retryable=True,
            )

    async def reload(self) -> ActionResult:
        if config.OSCAR_DRY_RUN:
            return self._dry_run_result("browser_reload")
        try:
            await self._ensure_page()
            await self._page.reload(
                wait_until="domcontentloaded",
                timeout=int(config.PLAYWRIGHT_TIMEOUT_SECONDS * 1000),
            )
            state = await self.get_state()
            return ActionResult(
                success=True,
                route="browser",
                action="browser_reload",
                confidence=0.75,
                data=state,
                context_updates=state,
            )
        except Exception as exc:
            return ActionResult(
                success=False,
                route="browser",
                action="browser_reload",
                failure_reason=str(exc),
                retryable=True,
            )

    async def close(self) -> None:
        if config.OSCAR_DRY_RUN:
            return
        if self._context is not None:
            await self._context.close()
            self._context = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
        self._page = None

    async def get_state(self) -> dict[str, str | None]:
        if self._page is None:
            return {
                "browser_url": None,
                "browser_title": None,
                "url": None,
                "title": None,
            }
        try:
            title = await self._page.title()
        except Exception:
            title = None
        url = getattr(self._page, "url", None)
        return {
            "browser_url": url,
            "browser_title": title,
            "url": url,
            "title": title,
        }

    async def _capture_state_after_interaction(
        self,
        *,
        previous_url: str | None = None,
        previous_title: str | None = None,
    ) -> dict[str, str | None]:
        policy = RetryPolicy(
            timeout_seconds=config.PLAYWRIGHT_TIMEOUT_SECONDS,
            initial_interval=config.RETRY_INITIAL_INTERVAL_SECONDS,
            max_interval=config.RETRY_MAX_INTERVAL_SECONDS,
            backoff=max(config.RETRY_BACKOFF_FACTOR, 1.0),
        )

        async def _state_changed():
            state = await self.get_state()
            current_url = state.get("url")
            current_title = state.get("title")
            if current_url != previous_url or current_title != previous_title:
                return state
            return None

        return await async_wait_for_condition(_state_changed, policy=policy) or await self.get_state()

    async def _list_tabs(self) -> list[dict[str, object]]:
        pages = list(getattr(self._context, "pages", []) or [])
        tabs: list[dict[str, object]] = []
        active_page = self._page
        for index, page in enumerate(pages, start=1):
            try:
                title = await page.title()
            except Exception:
                title = None
            tabs.append(
                {
                    "id": index,
                    "title": title,
                    "url": getattr(page, "url", None),
                    "active": page is active_page,
                }
            )
        return tabs

    def _find_page_by_url(self, url: str):
        normalized_target = self._normalize_tab_url(url)
        if not normalized_target or self._context is None:
            return None
        for page in list(getattr(self._context, "pages", []) or []):
            page_url = self._normalize_tab_url(getattr(page, "url", None))
            if page_url and page_url == normalized_target:
                return page
        return None

    async def _page_matches(
        self,
        page,
        *,
        url: str | None = None,
        title_contains: str | None = None,
    ) -> bool:
        page_url = self._normalize_tab_url(getattr(page, "url", None))
        if url:
            lowered_url = self._normalize_tab_url(url)
            if lowered_url and lowered_url == page_url:
                return True
        try:
            title = str(await page.title() or "").strip().lower()
        except Exception:
            title = ""
        lowered_title = " ".join(str(title_contains or "").strip().lower().split())
        if lowered_title and lowered_title in title:
            return True
        return False

    def _normalize_tab_url(self, value: object) -> str:
        normalized = str(value or "").strip().lower()
        if not normalized:
            return ""
        if normalized.endswith("/"):
            normalized = normalized[:-1]
        return normalized

    async def _ensure_page(self, *, restart: bool = False) -> None:
        await self._ensure_context(
            self._session_config or BrowserSessionConfig(),
            restart=restart,
        )
        if self._page is None:
            pages = list(getattr(self._context, "pages", []) or [])
            self._page = pages[0] if pages else await self._context.new_page()

    async def _ensure_context(
        self,
        session_config: BrowserSessionConfig,
        *,
        restart: bool,
    ) -> None:
        if restart and self._context is not None:
            await self.close()
        if self._context is not None:
            if not self._context_is_alive():
                self._context = None
                self._page = None
            else:
                self._session_config = session_config
                return
        if self._context is not None:
            self._session_config = session_config
            return

        async_playwright = await self._load_playwright()
        self._playwright = await async_playwright().start()
        browser_type = getattr(self._playwright, "chromium")
        user_data_dir, launch_kwargs = self._build_launch_details(session_config)
        self._context = await browser_type.launch_persistent_context(
            str(user_data_dir),
            **launch_kwargs,
        )
        pages = list(getattr(self._context, "pages", []) or [])
        self._page = pages[0] if pages else await self._context.new_page()
        self._session_config = session_config

    def _resolve_input_locator(
        self,
        *,
        text: str,
        preferred: str | None = None,
    ):
        for strategy in self.selector_resolver.ordered_strategies(preferred):
            locator = self._build_input_locator(strategy, text)
            if locator is not None:
                return locator, strategy
        return None, None

    def _build_input_locator(self, strategy: str, text: str):
        if self._page is None:
            return None
        if strategy == "role" and hasattr(self._page, "get_by_role"):
            for role in ("textbox", "searchbox", "combobox", "spinbutton"):
                try:
                    return self._page.get_by_role(role, name=text, exact=True)
                except Exception:
                    continue
        if strategy == "label" and hasattr(self._page, "get_by_label"):
            return self._page.get_by_label(text, exact=True)
        if strategy == "text":
            if hasattr(self._page, "get_by_placeholder"):
                try:
                    return self._page.get_by_placeholder(text, exact=True)
                except Exception:
                    pass
            if hasattr(self._page, "get_by_text"):
                return self._page.get_by_text(text, exact=True)
        if strategy == "partial_text":
            if hasattr(self._page, "get_by_placeholder"):
                try:
                    return self._page.get_by_placeholder(text)
                except Exception:
                    pass
            if hasattr(self._page, "get_by_text"):
                return self._page.get_by_text(text)
        if strategy == "aria" and hasattr(self._page, "locator"):
            return self._page.locator(
                "input[aria-label=$label], textarea[aria-label=$label], [role='textbox'][aria-label=$label], input[placeholder=$label], textarea[placeholder=$label]",
                {"label": text},
            )
        if strategy == "test_id" and hasattr(self._page, "get_by_test_id"):
            return self._page.get_by_test_id(text)
        if strategy == "css" and hasattr(self._page, "locator"):
            return self._page.locator(
                "input, textarea, [contenteditable='true'], [role='textbox']"
            )
        return None

    async def _load_playwright(self):
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "Playwright is not installed. Install it with 'python -m pip install -r requirements.txt' "
                "and then run 'playwright install chromium'."
            ) from exc
        return async_playwright

    def _build_launch_details(
        self,
        session_config: BrowserSessionConfig,
    ) -> tuple[Path, dict[str, object]]:
        user_data_dir = session_config.managed_profile_dir
        launch_kwargs: dict[str, object] = {
            "headless": session_config.headless,
            "args": [],
        }

        if session_config.session_mode == "local_profile":
            if os.name != "nt":
                raise RuntimeError("Local browser profiles are only supported on Windows.")
            if session_config.browser_name not in {
                "chrome",
                "microsoft edge",
                "edge",
                "chromium",
            }:
                raise RuntimeError(
                    f"Unsupported browser for local profile mode: {session_config.browser_name}"
                )
            if session_config.browser_name in {"chrome", "chromium"}:
                local_app_data = Path(os.getenv("LOCALAPPDATA", Path.home()))
                user_data_dir = local_app_data / "Google" / "Chrome" / "User Data"
                profile_directory = (
                    resolve_chrome_profile_directory(session_config.profile_name)
                    if session_config.profile_name
                    else "Default"
                )
                launch_kwargs["channel"] = "chrome"
            else:
                local_app_data = Path(os.getenv("LOCALAPPDATA", Path.home()))
                user_data_dir = local_app_data / "Microsoft" / "Edge" / "User Data"
                profile_directory = session_config.profile_name or "Default"
                launch_kwargs["channel"] = "msedge"
            launch_kwargs["args"] = [f"--profile-directory={profile_directory}"]

        return user_data_dir, launch_kwargs

    def _context_is_alive(self) -> bool:
        if self._context is None:
            return False
        try:
            _ = list(getattr(self._context, "pages", []) or [])
            if self._page is not None:
                _ = getattr(self._page, "url", None)
            return True
        except Exception as exc:
            if self._looks_like_closed_target(exc):
                return False
            raise

    def _looks_like_closed_target(self, exc: Exception) -> bool:
        lowered = str(exc).lower()
        return any(
            token in lowered
            for token in (
                "target page, context or browser has been closed",
                "target closed",
                "browser has been closed",
                "context closed",
            )
        )
