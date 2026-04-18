"""Polling and retry helpers for reliable state-based automation."""

from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass
from collections.abc import Awaitable
from typing import Callable, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    """Shared retry configuration for sync and async polling loops."""

    timeout_seconds: float
    initial_interval: float = 0.05
    max_interval: float = 0.5
    backoff: float = 1.6
    max_attempts: int = 25


def wait_for_condition(
    condition: Callable[[], T | bool | None],
    *,
    policy: RetryPolicy,
    retry_exceptions: tuple[type[Exception], ...] = (Exception,),
) -> T | bool | None:
    """Poll until a condition produces a truthy result or the timeout expires."""

    deadline = time.monotonic() + max(policy.timeout_seconds, 0.0)
    interval = max(policy.initial_interval, 0.0)
    last_value: T | bool | None = None
    attempts = 0

    while True:
        if policy.max_attempts > 0 and attempts >= policy.max_attempts:
            return last_value
        try:
            last_value = condition()
        except retry_exceptions:
            last_value = None
        attempts += 1
        if last_value:
            return last_value
        if time.monotonic() >= deadline:
            return last_value
        sleep_for = min(max(interval, 0.0), max(deadline - time.monotonic(), 0.0))
        if sleep_for > 0:
            time.sleep(sleep_for)
        interval = min(max(interval * policy.backoff, policy.initial_interval), policy.max_interval)


async def async_wait_for_condition(
    condition: Callable[[], Awaitable[T | bool | None] | T | bool | None],
    *,
    policy: RetryPolicy,
    retry_exceptions: tuple[type[Exception], ...] = (Exception,),
) -> T | bool | None:
    """Async variant of :func:`wait_for_condition` with adaptive backoff."""

    deadline = time.monotonic() + max(policy.timeout_seconds, 0.0)
    interval = max(policy.initial_interval, 0.0)
    last_value: T | bool | None = None
    attempts = 0

    while True:
        if policy.max_attempts > 0 and attempts >= policy.max_attempts:
            return last_value
        try:
            maybe_result = condition()
            last_value = await maybe_result if inspect.isawaitable(maybe_result) else maybe_result
        except retry_exceptions:
            last_value = None
        attempts += 1
        if last_value:
            return last_value
        if time.monotonic() >= deadline:
            return last_value
        sleep_for = min(max(interval, 0.0), max(deadline - time.monotonic(), 0.0))
        if sleep_for > 0:
            await asyncio.sleep(sleep_for)
        interval = min(max(interval * policy.backoff, policy.initial_interval), policy.max_interval)
