"""Conservative per-task and per-day token budgeting for cloud model calls.

Token counts are estimates unless the gateway returns usage metadata. Request
ceilings are reserved before sending so a gateway that omits usage cannot let
repeated calls silently exceed the configured budgets.
"""
from __future__ import annotations

import json
import os
import threading
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from oscar import config


class TokenBudgetExceeded(RuntimeError):
    """Raised before a cloud request when its estimated cost exceeds a cap."""


@dataclass
class TaskTokenBudget:
    limit: int
    reserved_or_used: int = 0
    requests: int = 0


@dataclass(frozen=True)
class TokenReservation:
    budget: TaskTokenBudget | None
    reserved_tokens: int
    daily_reserved_tokens: int


_current_budget: ContextVar[TaskTokenBudget | None] = ContextVar(
    "oscar_task_token_budget", default=None
)
_daily_lock = threading.Lock()


def begin_task_budget(limit: int) -> Token[TaskTokenBudget | None]:
    """Start a task-scoped budget; return its context token for cleanup."""
    return _current_budget.set(TaskTokenBudget(limit=limit))


def end_task_budget(token: Token[TaskTokenBudget | None]) -> None:
    """Restore the previous budget context."""
    _current_budget.reset(token)


def estimate_text_tokens(text: str) -> int:
    """Conservative English/code estimate; not a provider billing tokenizer."""
    return max(1, (len(text) + 2) // 3)


def _daily_usage_path() -> Path:
    return Path(config.STATE_DIR) / "omniroute_token_usage.json"


def _read_daily_usage(path: Path, today: str) -> int:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return 0
        if data.get("date") == today:
            value = data.get("estimated_tokens", 0)
            return max(0, int(value))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    return 0


def _write_daily_usage(path: Path, today: str, amount: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"date": today, "estimated_tokens": max(0, amount)}, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _reserve_daily_tokens(amount: int) -> None:
    today = date.today().isoformat()
    path = _daily_usage_path()
    with _daily_lock:
        used = _read_daily_usage(path, today)
        limit = config.OMNIROUTE_MAX_DAILY_TOKENS
        if used + amount > limit:
            raise TokenBudgetExceeded(
                "OSCAR blocked the cloud request because today's configured OmniRoute "
                f"token budget ({limit} estimated tokens) would be exceeded."
            )
        _write_daily_usage(path, today, used + amount)


def _settle_daily_tokens(reserved: int, actual: int) -> None:
    today = date.today().isoformat()
    path = _daily_usage_path()
    with _daily_lock:
        used = _read_daily_usage(path, today)
        _write_daily_usage(path, today, max(0, used - reserved + actual))


def reserve_request(input_tokens: int, output_tokens: int) -> TokenReservation:
    """Reserve worst-case request tokens before sending a model request."""
    budget = _current_budget.get()
    reserved = max(1, input_tokens) + max(1, output_tokens)
    if budget is not None and budget.reserved_or_used + reserved > budget.limit:
        raise TokenBudgetExceeded(
            "OSCAR stopped before the model request because this task reached its "
            f"configured token budget ({budget.limit} estimated tokens)."
        )
    # Daily guard is persisted across OSCAR restarts; count failed requests too,
    # since providers can bill requests that end in an HTTP/model error.
    _reserve_daily_tokens(reserved)
    if budget is not None:
        budget.reserved_or_used += reserved
        budget.requests += 1
    return TokenReservation(
        budget=budget,
        reserved_tokens=reserved,
        daily_reserved_tokens=reserved,
    )


def settle_request(reservation: TokenReservation, actual_tokens: int | None) -> None:
    """Replace a worst-case reservation with provider-reported usage when available."""
    if actual_tokens is None or actual_tokens <= 0:
        return
    if reservation.budget is not None:
        reservation.budget.reserved_or_used = max(
            0,
            reservation.budget.reserved_or_used
            - reservation.reserved_tokens
            + actual_tokens,
        )
    _settle_daily_tokens(reservation.daily_reserved_tokens, actual_tokens)


def current_task_usage() -> dict[str, int] | None:
    """Return non-sensitive budget telemetry for UI/log summaries."""
    budget = _current_budget.get()
    if budget is None:
        return None
    return {
        "estimated_units_used": budget.reserved_or_used,
        "budget_units": budget.limit,
        "request_count": budget.requests,
    }
