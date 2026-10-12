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


def _default_daily_record(today: str) -> dict[str, object]:
    return {
        "date": today,
        # Effective budget units: provider-reported usage when available, otherwise
        # conservative reservations. This legacy key remains for backwards compatibility.
        "estimated_tokens": 0,
        "request_count": 0,
        "provider_reported_tokens": 0,
        "provider_reported_requests": 0,
        "estimated_only_requests": 0,
        "failed_or_unknown_requests": 0,
        "last_model": None,
        "last_usage_source": None,
    }


def _read_daily_record(path: Path, today: str) -> dict[str, object]:
    record = _default_daily_record(today)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("date") != today:
            return record
        record.update(data)
        # Ensure old ledgers get safe defaults for fields added in this version.
        for key, value in _default_daily_record(today).items():
            record.setdefault(key, value)
        record["estimated_tokens"] = max(0, int(record.get("estimated_tokens", 0)))
        return record
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return record


def _read_daily_usage(path: Path, today: str) -> int:
    return int(_read_daily_record(path, today)["estimated_tokens"])


def _write_daily_record(path: Path, record: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _write_daily_usage(path: Path, today: str, amount: int) -> None:
    record = _read_daily_record(path, today)
    record["estimated_tokens"] = max(0, amount)
    _write_daily_record(path, record)


def _reserve_daily_tokens(amount: int) -> None:
    today = date.today().isoformat()
    path = _daily_usage_path()
    with _daily_lock:
        record = _read_daily_record(path, today)
        used = int(record["estimated_tokens"])
        limit = config.OMNIROUTE_MAX_DAILY_TOKENS
        if used + amount > limit:
            raise TokenBudgetExceeded(
                "OSCAR blocked the cloud request because today's configured OmniRoute "
                f"token budget ({limit} estimated tokens) would be exceeded."
            )
        record["estimated_tokens"] = used + amount
        record["request_count"] = int(record.get("request_count", 0)) + 1
        _write_daily_record(path, record)


def _settle_daily_tokens(
    reserved: int,
    actual: int | None,
    *,
    model_name: str | None,
    outcome: str,
) -> None:
    today = date.today().isoformat()
    path = _daily_usage_path()
    with _daily_lock:
        record = _read_daily_record(path, today)
        used = int(record["estimated_tokens"])
        if actual is not None and actual > 0:
            record["estimated_tokens"] = max(0, used - reserved + actual)
            record["provider_reported_tokens"] = (
                int(record.get("provider_reported_tokens", 0)) + actual
            )
            record["provider_reported_requests"] = (
                int(record.get("provider_reported_requests", 0)) + 1
            )
            record["last_usage_source"] = "provider_reported"
        elif outcome == "success":
            # Keep the reservation as the budget charge, since no reliable usage
            # count was returned. Do not pretend the reservation is actual usage.
            record["estimated_only_requests"] = (
                int(record.get("estimated_only_requests", 0)) + 1
            )
            record["last_usage_source"] = "estimated_reservation_no_provider_usage"
        else:
            # Conservatively retain the reservation: some gateways bill failed calls.
            record["failed_or_unknown_requests"] = (
                int(record.get("failed_or_unknown_requests", 0)) + 1
            )
            record["last_usage_source"] = "estimated_reservation_failed_or_unknown"
        if model_name:
            record["last_model"] = model_name
        _write_daily_record(path, record)


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


def settle_request(
    reservation: TokenReservation,
    actual_tokens: int | None,
    *,
    model_name: str | None = None,
    outcome: str = "success",
) -> None:
    """Reconcile reservations with usage metadata, while recording estimate-only calls."""
    actual = actual_tokens if isinstance(actual_tokens, int) and actual_tokens > 0 else None
    if actual is not None and reservation.budget is not None:
        reservation.budget.reserved_or_used = max(
            0,
            reservation.budget.reserved_or_used
            - reservation.reserved_tokens
            + actual,
        )
    _settle_daily_tokens(
        reservation.daily_reserved_tokens,
        actual,
        model_name=model_name,
        outcome=outcome,
    )

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
