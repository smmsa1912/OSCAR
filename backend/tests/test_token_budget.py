from __future__ import annotations

import pytest

from oscar.token_budget import (
    TokenBudgetExceeded,
    begin_task_budget,
    current_task_usage,
    end_task_budget,
    reserve_request,
    settle_request,
)


def test_task_budget_blocks_requests_before_the_limit_is_exceeded(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from oscar.token_budget import config as budget_config
    monkeypatch.setattr(budget_config, "STATE_DIR", tmp_path)
    monkeypatch.setattr(budget_config, "OMNIROUTE_MAX_DAILY_TOKENS", 1000)
    token = begin_task_budget(100)
    try:
        reservation = reserve_request(40, 20)
        assert current_task_usage() == {
            "estimated_units_used": 60,
            "budget_units": 100,
            "request_count": 1,
        }
        with pytest.raises(TokenBudgetExceeded, match="reached its configured token budget"):
            reserve_request(30, 20)
        settle_request(reservation, 25)
        assert current_task_usage()["estimated_units_used"] == 25
    finally:
        end_task_budget(token)


def test_budget_context_is_isolated_between_tasks(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from oscar.token_budget import config as budget_config
    monkeypatch.setattr(budget_config, "STATE_DIR", tmp_path)
    monkeypatch.setattr(budget_config, "OMNIROUTE_MAX_DAILY_TOKENS", 1000)
    first = begin_task_budget(100)
    try:
        reserve_request(20, 10)
        assert current_task_usage()["estimated_units_used"] == 30
        second = begin_task_budget(50)
        try:
            assert current_task_usage()["estimated_units_used"] == 0
            reserve_request(10, 10)
            assert current_task_usage()["estimated_units_used"] == 20
        finally:
            end_task_budget(second)
        assert current_task_usage()["estimated_units_used"] == 30
    finally:
        end_task_budget(first)



def test_daily_budget_persists_across_task_contexts(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from oscar.token_budget import config as budget_config

    monkeypatch.setattr(budget_config, "STATE_DIR", tmp_path)
    monkeypatch.setattr(budget_config, "OMNIROUTE_MAX_DAILY_TOKENS", 100)
    first = begin_task_budget(1000)
    try:
        reserve_request(40, 20)
    finally:
        end_task_budget(first)

    second = begin_task_budget(1000)
    try:
        with pytest.raises(TokenBudgetExceeded, match="today's configured OmniRoute token budget"):
            reserve_request(30, 20)
    finally:
        end_task_budget(second)
    usage_file = tmp_path / "omniroute_token_usage.json"
    assert usage_file.exists()
    assert '"estimated_tokens": 60' in usage_file.read_text(encoding="utf-8")
