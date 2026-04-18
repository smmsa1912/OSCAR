"""Dynamic tool registry for O.S.C.A.R. agent capabilities.

This is an internal abstraction layer that wraps existing agents behind a
unified interface.  When the core architecture is stable, a true MCP JSON-RPC
transport can be layered on top without changing any consumer code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


@dataclass(frozen=True)
class ToolSpec:
    """A single registered tool capability.

    Attributes
    ----------
    name:
        Unique name used by the planner and router to reference this tool.
    description:
        Short, LLM-readable description of what this tool does.
    handler:
        Async callable implementing the tool logic.
    parameter_schema:
        JSON Schema fragment describing the accepted parameters.
    route:
        Route label to tag dispatched actions (e.g., "browser", "terminal").
    tags:
        Optional categories for filtering (e.g., ("browser", "navigation")).
    """

    name: str
    description: str
    handler: Callable[..., Awaitable[Any]]
    parameter_schema: dict[str, Any] = field(default_factory=dict)
    route: str = "dynamic"
    tags: tuple[str, ...] = ()


class ToolRegistry:
    """Central registry for all available agent tools.

    Tools can be registered at startup or discovered dynamically.
    The registry provides prompt-generation helpers so the planner always
    has an up-to-date view of available capabilities.
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    # ── Mutation ──────────────────────────────────────────────────────

    def register(self, spec: ToolSpec) -> None:
        """Register a tool (overwrites any existing tool with the same name)."""
        self._tools[spec.name] = spec

    def register_many(self, *specs: ToolSpec) -> None:
        """Register multiple tools at once."""
        for spec in specs:
            self.register(spec)

    def unregister(self, name: str) -> None:
        """Remove a tool by name (no-op if not present)."""
        self._tools.pop(name, None)

    def clear(self) -> None:
        """Remove all registered tools."""
        self._tools.clear()

    # ── Lookup ────────────────────────────────────────────────────────

    def get(self, name: str) -> ToolSpec | None:
        """Return a tool by name, or ``None`` if not found."""
        return self._tools.get(name)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def list_tools(self, *, tags: set[str] | None = None) -> list[ToolSpec]:
        """Return all registered tools, optionally filtered by tags."""
        if tags is None:
            return list(self._tools.values())
        return [t for t in self._tools.values() if tags & set(t.tags)]

    def list_names(self) -> list[str]:
        """Return sorted names of all registered tools."""
        return sorted(self._tools)

    # ── Prompt helpers ────────────────────────────────────────────────

    def describe_for_prompt(self) -> str:
        """Generate a compact tool listing for the LLM system prompt.

        Returns a newline-separated list of ``- name: description`` entries
        that can be injected directly into the SYSTEM_PROMPT template.
        """
        lines: list[str] = []
        for tool in sorted(self._tools.values(), key=lambda t: t.name):
            lines.append(f"- {tool.name}: {tool.description}")
        return "\n".join(lines)

    def describe_tool(self, name: str) -> str | None:
        """Return the full description for a single tool, or None."""
        spec = self._tools.get(name)
        return spec.description if spec else None

    # ── Dispatch ──────────────────────────────────────────────────────

    async def invoke(self, name: str, **kwargs: Any) -> Any:
        """Invoke a registered tool by name.

        Raises
        ------
        KeyError
            If no tool with the given name is registered.
        """
        spec = self._tools.get(name)
        if spec is None:
            raise KeyError(f"Unknown tool: {name!r}")
        return await spec.handler(**kwargs)


# Module-level singleton — importable by any subsystem.
_default_registry: ToolRegistry | None = None


def get_default_registry() -> ToolRegistry:
    """Return (or lazily create) the process-wide default :class:`ToolRegistry`."""
    global _default_registry
    if _default_registry is None:
        _default_registry = ToolRegistry()
    return _default_registry
