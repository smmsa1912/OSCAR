from __future__ import annotations

import pytest

from oscar.utils.retry import RetryPolicy, async_wait_for_condition, wait_for_condition


def test_wait_for_condition_polls_until_truthy(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = {"count": 0}
    sleep_calls: list[float] = []

    def fake_condition():
        attempts["count"] += 1
        return attempts["count"] >= 3

    monkeypatch.setattr("oscar.utils.retry.time.sleep", lambda seconds: sleep_calls.append(seconds))

    result = wait_for_condition(
        fake_condition,
        policy=RetryPolicy(timeout_seconds=0.2, initial_interval=0.01, max_interval=0.02, backoff=2.0),
    )

    assert result is True
    assert attempts["count"] == 3
    assert sleep_calls


@pytest.mark.anyio
async def test_async_wait_for_condition_stops_after_max_attempts() -> None:
    attempts = {"count": 0}

    async def fake_condition():
        attempts["count"] += 1
        return None

    result = await async_wait_for_condition(
        fake_condition,
        policy=RetryPolicy(
            timeout_seconds=1.0,
            initial_interval=0.0,
            max_interval=0.0,
            backoff=1.0,
            max_attempts=4,
        ),
    )

    assert result is None
    assert attempts["count"] == 4
