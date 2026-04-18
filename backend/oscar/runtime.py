"""Shared runtime models used by orchestrator, router, and agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ActionResult:
    """Structured outcome from a routed action execution."""

    success: bool
    route: str
    action: str
    confidence: float = 0.0
    data: dict[str, Any] = field(default_factory=dict)
    failure_reason: str | None = None
    retryable: bool = True
    attempts: int = 1
    fallback_chain: list[str] = field(default_factory=list)
    duration_ms: int = 0
    strategy: str | None = None
    context_updates: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "route": self.route,
            "action": self.action,
            "confidence": self.confidence,
            "data": self.data,
            "failure_reason": self.failure_reason,
            "retryable": self.retryable,
            "attempts": self.attempts,
            "fallback_chain": list(self.fallback_chain),
            "duration_ms": self.duration_ms,
            "strategy": self.strategy,
            "context_updates": self.context_updates,
        }


@dataclass(frozen=True)
class RouteCandidate:
    """A scored route option for a given action."""

    route: str
    score: int
    reason: str


@dataclass
class RetryDecision:
    """The next retry or fallback decision for an action."""

    action: dict[str, Any] | None = None
    forced_route: str | None = None
    resume_action: dict[str, Any] | None = None
    reason: str | None = None
    stop: bool = False
