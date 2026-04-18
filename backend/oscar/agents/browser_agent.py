"""High-level browser agent with native desktop and Playwright backends."""

from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import parse_qs, quote_plus, urlencode, urlparse, urlunparse

import anyio

from oscar import config
from oscar.executor import execute_action, validate_action
from oscar.browser.query_utils import (
    is_browser_app_name,
    normalize_url,
    simplify_search_query,
)
from oscar.browser.playwright_controller import PlaywrightController
from oscar.runtime import ActionResult
from oscar.window_control import (
    app_window_exists,
    focus_app_window,
    get_active_window_info,
    normalize_app_name,
)


def _is_pyautogui_fail_safe_exception(exc: Exception) -> bool:
    return (
        exc.__class__.__name__ == "FailSafeException"
        and exc.__class__.__module__.startswith("pyautogui")
    )


def _raise_critical_exception(exc: Exception) -> None:
    if _is_pyautogui_fail_safe_exception(exc):
        raise exc


class BrowserAgent:
    """Intent-level browser automation that hides selector details from the planner."""

    def __init__(
        self,
        *,
        controller: PlaywrightController | None = None,
        native_browser_enabled: bool | None = None,
    ) -> None:
        self.controller = controller or PlaywrightController()
        self.native_browser_enabled = (
            config.NATIVE_BROWSER_ENABLED
            if native_browser_enabled is None
            else native_browser_enabled
        )
        self._last_search_query: str | None = None
        self._last_search_url: str | None = None
        self._native_browser_name: str | None = None
        self._native_profile_name: str | None = None
        self._native_current_url: str | None = None
        self._native_browser_title: str | None = None

    async def open_browser(
        self,
        *,
        session_mode: str = "managed",
        profile_name: str | None = None,
        browser_name: str = "chromium",
    ) -> ActionResult:
        if self._should_use_native_browser(
            browser_name=browser_name,
            profile_name=profile_name,
            session_mode=session_mode,
        ):
            return await self._open_native_browser(
                browser_name=browser_name,
                profile_name=profile_name,
            )
        # Reuse the existing controller whenever possible so browser flows do not
        # pay the startup cost for every single semantic action.
        if self.controller.is_active():
            state = await self.controller.get_state()
            return ActionResult(
                success=True,
                route="browser",
                action="browser_open",
                confidence=0.9,
                data=state,
                context_updates=state,
            )
        return await self.controller.open_browser(
            session_mode=session_mode,
            profile_name=profile_name,
            browser_name=browser_name,
        )

    async def search_and_open(
        self,
        query: str,
        *,
        browser_name: str | None = None,
        profile_name: str | None = None,
    ) -> ActionResult:
        normalized_query = simplify_search_query(query)
        if not normalized_query:
            normalized_query = " ".join(query.strip().split())
        if self._is_repeated_query(normalized_query):
            return ActionResult(
                success=False,
                route="browser",
                action="browser_search",
                confidence=0.2,
                failure_reason=f"repeated_query:{normalized_query}",
                retryable=False,
                data={"query": normalized_query},
            )
        if self._should_use_native_browser(
            browser_name=browser_name,
            profile_name=profile_name,
            session_mode=None,
        ):
            result = await self._open_native_browser(
                browser_name=browser_name,
                profile_name=profile_name,
                url=self._build_search_url(normalized_query),
                action_name="browser_search",
                query=normalized_query,
            )
            if result.success:
                self._remember_search(normalized_query, result)
            return result
        if not self.controller.is_active():
            opened = await self.open_browser()
            if not opened.success:
                return opened
        result = await self.controller.search(normalized_query)
        if not result.success:
            return result
        return await self._finalize_search_result(
            current_query=normalized_query,
            result=result,
        )

    async def navigate(
        self,
        url: str,
        *,
        reopen_session: bool = False,
        reload: bool = False,
        wait_timeout_seconds: float | None = None,
        browser_name: str | None = None,
        profile_name: str | None = None,
    ) -> ActionResult:
        normalized_url = normalize_url(url)
        if self._looks_like_browser_focus_request(normalized_url):
            return await self._open_native_browser(
                browser_name=browser_name or normalized_url,
                profile_name=profile_name,
                action_name="browser_open",
            )
        if not self._is_valid_navigation_target(normalized_url):
            return ActionResult(
                success=False,
                route="browser",
                action="browser_navigate",
                confidence=0.1,
                failure_reason=f"invalid_navigation_target:{url}",
                retryable=False,
                data={"url": url},
            )
        if self._should_use_native_browser(
            browser_name=browser_name,
            profile_name=profile_name,
            session_mode=None,
        ):
            return await self._open_native_browser(
                browser_name=browser_name,
                profile_name=profile_name,
                url=normalized_url,
                action_name="browser_navigate",
            )
        if not self.controller.is_active():
            opened = await self.open_browser()
            if not opened.success:
                return opened
        return await self.controller.navigate(
            normalized_url,
            reopen_session=reopen_session,
            reload=reload,
            wait_timeout_seconds=wait_timeout_seconds,
        )

    async def get_tabs(self) -> ActionResult:
        if self.controller.is_active():
            return await self.controller.get_tabs()

        active_window = await anyio.to_thread.run_sync(get_active_window_info)
        title = str(active_window.get("title") or "").strip() or self._native_browser_title
        if self._native_current_url:
            tabs = [
                {
                    "id": 1,
                    "title": title or None,
                    "url": self._native_current_url,
                    "active": True,
                }
            ]
        else:
            tabs = []
        return ActionResult(
            success=True,
            route="browser",
            action="browser_get_tabs",
            confidence=0.75,
            data={"tabs": tabs, "browser_tabs": tabs},
            context_updates={"browser_tabs": tabs},
            retryable=False,
        )

    async def click_tab(
        self,
        name: str,
        *,
        selector_strategy: str | None = None,
    ) -> ActionResult:
        if self.native_browser_enabled:
            native_result = await self._click_native_tab(name)
            if native_result is not None:
                return native_result
        if not self.controller.is_active():
            opened = await self.open_browser()
            if not opened.success:
                return opened
        return await self.controller.click_tab(
            name,
            selector_strategy=selector_strategy,
        )

    async def switch_tab(
        self,
        text: str | None = None,
        *,
        url: str | None = None,
        title_contains: str | None = None,
    ) -> ActionResult:
        title_filter = " ".join(str(title_contains or text or "").strip().split())
        if self.native_browser_enabled:
            current_title = self._native_browser_title or str(
                (await anyio.to_thread.run_sync(get_active_window_info)).get("title") or ""
            )
            if self._native_current_url and url and str(self._native_current_url).strip().lower() == str(url).strip().lower():
                return ActionResult(
                    success=True,
                    route="browser",
                    action="browser_switch_tab",
                    confidence=0.85,
                    data={
                        "native_browser": True,
                        "browser_url": self._native_current_url,
                        "url": self._native_current_url,
                        "matched_tab": url,
                        "already_active": True,
                    },
                    context_updates={
                        "browser_url": self._native_current_url,
                        "url": self._native_current_url,
                    },
                    retryable=False,
                )
            if title_filter and title_filter.lower() in str(current_title or "").lower():
                return ActionResult(
                    success=True,
                    route="browser",
                    action="browser_switch_tab",
                    confidence=0.8,
                    data={
                        "native_browser": True,
                        "browser_url": self._native_current_url,
                        "url": self._native_current_url,
                        "matched_tab": title_filter,
                        "already_active": True,
                    },
                    context_updates={
                        "browser_url": self._native_current_url,
                        "url": self._native_current_url,
                    },
                    retryable=False,
                )
            if url:
                return await self.navigate(
                    url,
                    browser_name=self._native_browser_name,
                    profile_name=self._native_profile_name,
                )
            return ActionResult(
                success=False,
                route="browser",
                action="browser_switch_tab",
                confidence=0.2,
                failure_reason=f"tab_not_found:{title_filter or url or ''}",
                retryable=False,
                data={"native_browser": True, "title_contains": title_filter, "url": url},
            )
        if not self.controller.is_active():
            opened = await self.open_browser()
            if not opened.success:
                return opened
        result = await self.controller.switch_tab(
            text=text,
            url=url,
            title_contains=title_filter or None,
        )
        if not result.success and url:
            return await self.navigate(url)
        return result

    async def find_and_click(
        self,
        text: str,
        *,
        selector_strategy: str | None = None,
    ) -> ActionResult:
        if self.native_browser_enabled:
            return ActionResult(
                success=False,
                route="browser",
                action="browser_find",
                confidence=0.2,
                failure_reason="Native browser semantic find requires keyboard/UI fallback.",
                retryable=True,
                data={"native_browser": True, "text": text},
            )
        if not self.controller.is_active():
            opened = await self.open_browser()
            if not opened.success:
                return opened
        return await self.controller.find_and_click(
            text,
            selector_strategy=selector_strategy,
        )

    async def type_text(
        self,
        target_text: str,
        type_text: str,
        *,
        selector_strategy: str | None = None,
    ) -> ActionResult:
        if not self.controller.is_active():
            opened = await self.controller.open_browser(
                session_mode="managed",
                browser_name="chromium",
            )
            if not opened.success:
                return opened
        return await self.controller.find_and_type(
            target_text,
            type_text,
            selector_strategy=selector_strategy,
        )

    async def extract_main_content(self) -> ActionResult:
        if self.native_browser_enabled:
            return ActionResult(
                success=False,
                route="browser",
                action="browser_extract",
                confidence=0.1,
                failure_reason="Native browser content extraction requires a browser automation backend.",
                retryable=False,
                data={"native_browser": True},
            )
        if not self.controller.is_active():
            opened = await self.open_browser()
            if not opened.success:
                return opened
        return await self.controller.extract_main_content()

    async def wait_for_text(
        self,
        text: str,
        *,
        selector_strategy: str | None = None,
    ) -> ActionResult:
        if self.native_browser_enabled:
            return ActionResult(
                success=False,
                route="browser",
                action="browser_wait_for",
                confidence=0.1,
                failure_reason="Native browser text waiting requires a browser automation backend.",
                retryable=False,
                data={"native_browser": True, "text": text},
            )
        if not self.controller.is_active():
            opened = await self.open_browser()
            if not opened.success:
                return opened
        return await self.controller.wait_for_text(
            text,
            selector_strategy=selector_strategy,
        )

    async def run(self, action: dict[str, Any]) -> ActionResult:
        action_name = action.get("action")
        if action_name == "browser_open":
            return await self.open_browser(
                session_mode=str(action.get("session_mode") or "managed"),
                profile_name=action.get("profile_name"),
                browser_name=str(
                    action.get("browser_name") or self._native_browser_name or "chromium"
                ),
            )
        if action_name == "browser_get_tabs":
            return await self.get_tabs()
        if action_name == "browser_search":
            return await self.search_and_open(
                str(action.get("query") or ""),
                browser_name=action.get("browser_name"),
                profile_name=action.get("profile_name"),
            )
        if action_name == "browser_navigate":
            return await self.navigate(
                str(action.get("url") or ""),
                reopen_session=bool(action.get("reopen_session")),
                reload=bool(action.get("reload")),
                wait_timeout_seconds=(
                    float(action["wait_timeout_seconds"])
                    if action.get("wait_timeout_seconds") is not None
                    else None
                ),
                browser_name=action.get("browser_name"),
                profile_name=action.get("profile_name"),
            )
        if action_name == "browser_click":
            text = str(action.get("text") or action.get("name") or "")
            return await self.click_tab(
                text,
                selector_strategy=action.get("selector_strategy"),
            )
        if action_name == "browser_switch_tab":
            return await self.switch_tab(
                str(action.get("text") or action.get("name") or "").strip() or None,
                url=str(action.get("url") or "").strip() or None,
                title_contains=str(action.get("title_contains") or "").strip() or None,
            )
        if action_name == "browser_find":
            return await self.find_and_click(
                str(action.get("text") or ""),
                selector_strategy=action.get("selector_strategy"),
            )
        if action_name == "browser_type":
            return await self.type_text(
                str(action.get("target_text") or ""),
                str(action.get("text") or ""),
                selector_strategy=action.get("selector_strategy"),
            )
        if action_name == "browser_wait_for":
            return await self.wait_for_text(
                str(action.get("text") or ""),
                selector_strategy=action.get("selector_strategy"),
            )
        if action_name == "browser_extract":
            return await self.extract_main_content()
        return ActionResult(
            success=False,
            route="browser",
            action=str(action_name or "browser"),
            failure_reason=f"Unsupported browser action '{action_name}'.",
            retryable=False,
        )

    async def _finalize_search_result(
        self,
        *,
        current_query: str,
        result: ActionResult,
    ) -> ActionResult:
        current_url = str(
            result.context_updates.get("browser_url")
            or result.context_updates.get("url")
            or result.data.get("browser_url")
            or result.data.get("url")
            or ""
        )
        current_title = str(
            result.context_updates.get("browser_title")
            or result.context_updates.get("title")
            or result.data.get("browser_title")
            or result.data.get("title")
            or ""
        )
        body_text = (await self._get_body_text_excerpt()).lower()

        if self._is_google_sorry(current_url, body_text):
            return ActionResult(
                success=False,
                route="browser",
                action="browser_search",
                confidence=0.1,
                failure_reason="Blocked by Google CAPTCHA",
                retryable=False,
                data={
                    "blocked": True,
                    "query": current_query,
                    "suggested_query": simplify_search_query(
                        current_query,
                        aggressive=True,
                    ),
                    "url": current_url,
                },
                context_updates=result.context_updates,
            )

        if await self._looks_like_empty_results(current_title, body_text):
            return ActionResult(
                success=False,
                route="browser",
                action="browser_search",
                confidence=0.2,
                failure_reason="empty_results",
                retryable=False,
                data={"query": current_query, "url": current_url},
                context_updates=result.context_updates,
            )

        if self._last_search_url and current_url and current_url == self._last_search_url:
            return ActionResult(
                success=False,
                route="browser",
                action="browser_search",
                confidence=0.2,
                failure_reason="repeated_redirect",
                retryable=False,
                data={"query": current_query, "url": current_url},
                context_updates=result.context_updates,
            )

        result.data["query"] = current_query
        self._remember_search(current_query, result)
        return result

    async def _get_body_text_excerpt(self) -> str:
        page = self.controller.page
        if page is None or not hasattr(page, "locator"):
            return ""
        try:
            locator = page.locator("body")
            return (
                await locator.first.inner_text(timeout=2_000)
            ).strip()[:1_000]
        except Exception:
            return ""

    def _is_google_sorry(self, url: str, body_text: str) -> bool:
        lowered_url = url.lower()
        return "google.com/sorry" in lowered_url or "unusual traffic" in body_text

    async def _looks_like_empty_results(self, title: str, body_text: str) -> bool:
        """Detect empty search results via DOM structure, not English strings.

        This avoids breaking on non-English OS locales where "no results"
        and "did not match" would never appear in the page text.
        """
        # Strategy 1: structural check — Google wraps results in #rso
        page = self.controller.page
        if page is not None and hasattr(page, "locator"):
            try:
                results_container = page.locator("#rso")
                count = await results_container.count()
                if count == 0:
                    return True
                inner = (await results_container.first.inner_text(timeout=2_000)).strip()
                if len(inner) < 20:
                    return True
            except Exception:
                pass
            # Google's empty-results page contains a #botstuff div with correction hints
            try:
                botstuff = page.locator("#botstuff")
                if await botstuff.count() > 0:
                    botstuff_text = (await botstuff.first.inner_text(timeout=2_000)).strip()
                    if botstuff_text and len(body_text) < 200:
                        return True
            except Exception:
                pass
        # Strategy 2: heuristic fallback — very short body on a search URL
        if len(body_text.strip()) < 80:
            return True
        return False

    def _is_repeated_query(self, query: str) -> bool:
        return bool(
            query
            and self._last_search_query == query
            and self._last_search_url
            and "google.com/search" in self._last_search_url
        )

    def _remember_search(self, query: str, result: ActionResult) -> None:
        self._last_search_query = query
        self._last_search_url = str(
            result.context_updates.get("browser_url")
            or result.context_updates.get("url")
            or result.data.get("browser_url")
            or result.data.get("url")
            or ""
        )

    def _should_use_native_browser(
        self,
        *,
        browser_name: str | None,
        profile_name: str | None,
        session_mode: str | None,
    ) -> bool:
        if session_mode == "managed" and not self.native_browser_enabled:
            return False
        if session_mode == "local_profile":
            return True
        if profile_name:
            return True
        normalized_browser = normalize_app_name(
            browser_name or self._native_browser_name or config.DEFAULT_DESKTOP_BROWSER
        )
        if normalized_browser and normalized_browser not in {"chromium"}:
            return self.native_browser_enabled
        return self.native_browser_enabled

    async def _open_native_browser(
        self,
        *,
        browser_name: str | None,
        profile_name: str | None,
        url: str | None = None,
        action_name: str = "browser_open",
        query: str | None = None,
    ) -> ActionResult:
        resolved_browser = self._resolve_native_browser_name(browser_name)
        resolved_profile = profile_name or self._native_profile_name
        if (
            url
            and self._native_browser_name == resolved_browser
            and self._native_profile_name == resolved_profile
            and app_window_exists(resolved_browser)
        ):
            return await self._navigate_existing_native_browser(
                browser_name=resolved_browser,
                profile_name=resolved_profile,
                url=url,
                action_name=action_name,
                query=query,
            )
        action = {
            "action": "open_app",
            "app_name": resolved_browser,
            "reasoning": (
                "Open the user's installed browser directly so OSCAR uses the real desktop profile."
            ),
            "task_complete": False,
        }
        if resolved_profile:
            action["profile_name"] = resolved_profile
        if url:
            action["url"] = url
        normalized_action = validate_action(action)
        try:
            await anyio.to_thread.run_sync(execute_action, normalized_action)
            verified = await anyio.to_thread.run_sync(
                lambda: focus_app_window(
                    resolved_browser,
                    timeout=config.APP_LAUNCH_DELAY,
                )
                or app_window_exists(resolved_browser)
            )
        except asyncio.CancelledError:
            return ActionResult(
                success=False,
                route="browser",
                action=action_name,
                confidence=0.1,
                failure_reason="Execution cancelled",
                retryable=True,
                data={"browser_name": resolved_browser, "profile_name": resolved_profile},
            )
        except Exception as exc:
            _raise_critical_exception(exc)
            return ActionResult(
                success=False,
                route="browser",
                action=action_name,
                confidence=0.2,
                failure_reason=str(exc),
                retryable=True,
                data={
                    "browser_name": resolved_browser,
                    "profile_name": resolved_profile,
                    "error_type": exc.__class__.__name__,
                },
            )

        if not verified:
            return ActionResult(
                success=False,
                route="browser",
                action=action_name,
                confidence=0.2,
                failure_reason=f"Failed to verify that {resolved_browser} opened in the foreground.",
                retryable=True,
                data={
                    "browser_name": resolved_browser,
                    "profile_name": resolved_profile,
                    "url": url,
                },
            )

        self._native_browser_name = resolved_browser
        self._native_profile_name = resolved_profile
        self._native_current_url = url or self._native_current_url
        if url:
            await anyio.sleep(3)  # Wait for heavy web apps to render
        active_window = await anyio.to_thread.run_sync(get_active_window_info)
        self._native_browser_title = str(active_window.get("title") or "").strip() or None
        payload = {
            "browser_name": resolved_browser,
            "profile_name": resolved_profile,
            "browser_url": url,
            "browser_title": self._native_browser_title,
            "url": url,
            "title": self._native_browser_title,
            "native_browser": True,
        }
        if query:
            payload["query"] = query
        return ActionResult(
            success=True,
            route="browser",
            action=action_name,
            confidence=0.9 if url else 0.85,
            data=payload,
            context_updates=payload,
            retryable=False,
        )

    async def _click_native_tab(self, name: str) -> ActionResult | None:
        if not self._native_current_url:
            return ActionResult(
                success=False,
                route="browser",
                action="browser_click",
                confidence=0.2,
                failure_reason="Native browser tab click requires an active native browser URL.",
                retryable=True,
                data={"native_browser": True, "text": name},
            )
        lowered = " ".join(name.strip().split()).lower()
        tab_code = {
            "images": "isch",
            "videos": "vid",
            "news": "nws",
        }.get(lowered)
        if not tab_code:
            return ActionResult(
                success=False,
                route="browser",
                action="browser_click",
                confidence=0.2,
                failure_reason="Native browser semantic click requires UI fallback.",
                retryable=True,
                data={"native_browser": True, "text": name},
            )

        parsed = urlparse(self._native_current_url)
        if "google." not in parsed.netloc or "/search" not in parsed.path:
            return ActionResult(
                success=False,
                route="browser",
                action="browser_click",
                confidence=0.2,
                failure_reason="Images/Videos/News tab navigation is only available for Google search URLs.",
                retryable=True,
                data={"native_browser": True, "text": name, "url": self._native_current_url},
            )

        query = parse_qs(parsed.query, keep_blank_values=True)
        query["tbm"] = [tab_code]
        updated_url = urlunparse(parsed._replace(query=urlencode(query, doseq=True)))
        return await self._navigate_existing_native_browser(
            browser_name=self._native_browser_name,
            profile_name=self._native_profile_name,
            url=updated_url,
            action_name="browser_click",
        )

    def _resolve_native_browser_name(self, browser_name: str | None) -> str:
        normalized = normalize_app_name(
            browser_name or self._native_browser_name or config.DEFAULT_DESKTOP_BROWSER
        )
        if normalized in {"chromium", "browser"}:
            return config.DEFAULT_DESKTOP_BROWSER
        return normalized or config.DEFAULT_DESKTOP_BROWSER

    def _build_search_url(self, query: str) -> str:
        return f"https://www.google.com/search?q={quote_plus(query)}"

    async def _navigate_existing_native_browser(
        self,
        *,
        browser_name: str,
        profile_name: str | None,
        url: str,
        action_name: str,
        query: str | None = None,
    ) -> ActionResult:
        action = {
            "action": "open_app",
            "app_name": browser_name,
            "reasoning": (
                "Ask the operating system to open the URL directly in the user's real browser profile."
            ),
            "task_complete": False,
            "url": url,
        }
        if profile_name:
            action["profile_name"] = profile_name
        try:
            await anyio.to_thread.run_sync(
                execute_action,
                validate_action(action),
            )
            verified = await anyio.to_thread.run_sync(
                lambda: focus_app_window(
                    browser_name,
                    timeout=config.APP_LAUNCH_DELAY,
                )
                or app_window_exists(browser_name)
            )
            if not verified:
                return ActionResult(
                    success=False,
                    route="browser",
                    action=action_name,
                    confidence=0.2,
                    failure_reason=(
                        f"Failed to verify that {browser_name} accepted the requested URL."
                    ),
                    retryable=True,
                    data={"browser_name": browser_name, "profile_name": profile_name, "url": url},
                )
        except asyncio.CancelledError:
            return ActionResult(
                success=False,
                route="browser",
                action=action_name,
                confidence=0.1,
                failure_reason="Execution cancelled",
                retryable=True,
                data={"browser_name": browser_name, "profile_name": profile_name, "url": url},
            )
        except Exception as exc:
            _raise_critical_exception(exc)
            return ActionResult(
                success=False,
                route="browser",
                action=action_name,
                confidence=0.2,
                failure_reason=str(exc),
                retryable=True,
                data={
                    "browser_name": browser_name,
                    "profile_name": profile_name,
                    "url": url,
                    "error_type": exc.__class__.__name__,
                },
            )

        self._native_browser_name = browser_name
        self._native_profile_name = profile_name
        self._native_current_url = url
        await anyio.sleep(3)  # Wait for heavy web apps to render
        active_window = await anyio.to_thread.run_sync(get_active_window_info)
        self._native_browser_title = str(active_window.get("title") or "").strip() or None
        payload = {
            "browser_name": browser_name,
            "profile_name": profile_name,
            "browser_url": url,
            "browser_title": self._native_browser_title,
            "url": url,
            "title": self._native_browser_title,
            "native_browser": True,
        }
        if query:
            payload["query"] = query
        return ActionResult(
            success=True,
            route="browser",
            action=action_name,
            confidence=0.88,
            data=payload,
            context_updates=payload,
            retryable=False,
        )

    def _looks_like_browser_focus_request(self, value: str) -> bool:
        return is_browser_app_name(value)

    def _is_valid_navigation_target(self, value: str) -> bool:
        if not value or is_browser_app_name(value):
            return False
        return bool(
            re.match(r"^[a-z][a-z0-9+\-.]*://", value, re.IGNORECASE)
            or "." in value
        )
