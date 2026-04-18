"""Persistent short-term memory for recent apps, paths, and actions."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from oscar import config


def _dedupe_keep_latest(values: list[str], *, limit: int) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in reversed(values):
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
        if len(ordered) >= limit:
            break
    return list(reversed(ordered))


@dataclass
class PersistentMemoryStore:
    """Keep a compact JSON memory of recent system interactions across runs."""

    path: Path = field(default_factory=lambda: config.SESSION_MEMORY_PATH)
    recent_apps: list[str] = field(default_factory=list)
    recent_paths: list[str] = field(default_factory=list)
    recent_actions: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path | None = None) -> "PersistentMemoryStore":
        target = path or config.SESSION_MEMORY_PATH
        if not target.exists():
            return cls(path=target)
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except Exception:
            return cls(path=target)
        return cls(
            path=target,
            recent_apps=list(payload.get("recent_apps") or []),
            recent_paths=list(payload.get("recent_paths") or []),
            recent_actions=list(payload.get("recent_actions") or []),
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "recent_apps": list(self.recent_apps),
            "recent_paths": list(self.recent_paths),
            "recent_actions": list(self.recent_actions),
        }

    def record(self, action: dict[str, Any], result: Any) -> None:
        app_name = str(action.get("app_name") or action.get("browser_name") or "").strip()
        if app_name:
            self.recent_apps = _dedupe_keep_latest(
                [*self.recent_apps, app_name],
                limit=10,
            )

        for key in ("file_path", "working_directory"):
            value = str(action.get(key) or "").strip()
            if value:
                self.recent_paths = _dedupe_keep_latest(
                    [*self.recent_paths, value],
                    limit=12,
                )

        result_data = getattr(result, "data", None) or {}
        if isinstance(result_data, dict):
            for list_key in ("created_paths", "deleted_paths"):
                values = [
                    str(value).strip()
                    for value in result_data.get(list_key, [])
                    if str(value).strip()
                ]
                if values:
                    self.recent_paths = _dedupe_keep_latest(
                        [*self.recent_paths, *values],
                        limit=12,
                    )

        self.recent_actions.append(
            {
                "action": str(action.get("action") or ""),
                "route": str(getattr(result, "route", "") or ""),
                "success": bool(getattr(result, "success", False)),
            }
        )
        self.recent_actions = self.recent_actions[-20:]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.snapshot(), indent=2), encoding="utf-8")

