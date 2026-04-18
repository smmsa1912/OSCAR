"""Selector resolution order for high-level browser actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


SELECTOR_STRATEGIES = (
    "role",
    "label",
    "text",
    "partial_text",
    "aria",
    "test_id",
    "css",
)


@dataclass(frozen=True)
class SelectorAttempt:
    """One concrete selector strategy attempt."""

    strategy: str
    value: str


class SelectorResolver:
    """Build and execute robust Playwright selector attempts."""

    @staticmethod
    def ordered_strategies(preferred: str | None = None) -> list[str]:
        if preferred and preferred in SELECTOR_STRATEGIES:
            return [preferred, *[item for item in SELECTOR_STRATEGIES if item != preferred]]
        return list(SELECTOR_STRATEGIES)

    def build_attempts(
        self,
        *,
        text: str,
        preferred: str | None = None,
    ) -> list[SelectorAttempt]:
        attempts: list[SelectorAttempt] = []
        for strategy in self.ordered_strategies(preferred):
            if strategy == "role":
                attempts.append(SelectorAttempt(strategy="role", value=text))
            elif strategy == "label":
                attempts.append(SelectorAttempt(strategy="label", value=text))
            elif strategy == "text":
                attempts.append(SelectorAttempt(strategy="text", value=text))
            elif strategy == "partial_text":
                attempts.append(SelectorAttempt(strategy="partial_text", value=text))
            elif strategy == "aria":
                attempts.append(SelectorAttempt(strategy="aria", value=text))
            elif strategy == "test_id":
                attempts.append(SelectorAttempt(strategy="test_id", value=text))
            elif strategy == "css":
                attempts.append(
                    SelectorAttempt(
                        strategy="css",
                        value=":is(a,button,[role=\"tab\"],[role=\"link\"],[role=\"button\"])",
                    )
                )
        return attempts

    async def click(
        self,
        page: Any,
        *,
        text: str,
        preferred: str | None = None,
        timeout_ms: int,
    ) -> tuple[bool, str | None]:
        locator, strategy = self.resolve_locator(
            page,
            text=text,
            preferred=preferred,
        )
        if locator is None:
            return False, None
        try:
            await locator.first.wait_for(state="visible", timeout=timeout_ms)
            await locator.first.click(timeout=timeout_ms)
            return True, strategy
        except Exception:
            return False, strategy

    def resolve_locator(
        self,
        page: Any,
        *,
        text: str,
        preferred: str | None = None,
    ) -> tuple[Any | None, str | None]:
        for attempt in self.build_attempts(text=text, preferred=preferred):
            locator = self._build_locator(page, attempt)
            if locator is None:
                continue
            return locator, attempt.strategy
        return None, None

    async def wait_for_text(
        self,
        page: Any,
        *,
        text: str,
        preferred: str | None = None,
        timeout_ms: int,
    ) -> tuple[bool, str | None]:
        locator, strategy = self.resolve_locator(
            page,
            text=text,
            preferred=preferred,
        )
        if locator is None:
            return False, None
        try:
            await locator.first.wait_for(state="visible", timeout=timeout_ms)
            return True, strategy
        except Exception:
            return False, strategy

    async def locator_looks_active(
        self,
        page: Any,
        *,
        text: str,
        preferred: str | None = None,
        timeout_ms: int,
    ) -> tuple[bool, str | None]:
        locator, strategy = self.resolve_locator(
            page,
            text=text,
            preferred=preferred,
        )
        if locator is None:
            return False, None
        try:
            await locator.first.wait_for(state="visible", timeout=timeout_ms)
            for attribute_name in ("aria-selected", "aria-current", "data-selected"):
                value = await locator.first.get_attribute(attribute_name)
                lowered = str(value or "").strip().lower()
                if lowered in {"true", "page", "step", "location"}:
                    return True, strategy
            class_name = str(
                await locator.first.get_attribute("class") or ""
            ).strip().lower()
            if "active" in class_name or "selected" in class_name or "current" in class_name:
                return True, strategy
        except Exception:
            return False, strategy
        return False, strategy

    def _build_locator(self, page: Any, attempt: SelectorAttempt):
        strategy = attempt.strategy
        value = attempt.value
        if strategy == "role" and hasattr(page, "get_by_role"):
            for role in ("link", "button", "tab", "menuitem"):
                try:
                    locator = page.get_by_role(role, name=value, exact=True)
                    return locator
                except Exception:
                    continue
        if strategy == "label" and hasattr(page, "get_by_label"):
            return page.get_by_label(value, exact=True)
        if strategy == "text" and hasattr(page, "get_by_text"):
            return page.get_by_text(value, exact=True)
        if strategy == "partial_text" and hasattr(page, "get_by_text"):
            return page.get_by_text(value)
        if strategy == "aria" and hasattr(page, "locator"):
            return page.locator(
                "[aria-label=$label], [aria-labelledby=$label]",
                {"label": value},
            )
        if strategy == "test_id" and hasattr(page, "get_by_test_id"):
            return page.get_by_test_id(value)
        if strategy == "css" and hasattr(page, "locator"):
            return page.locator(attempt.value).filter(has_text=value)
        return None
