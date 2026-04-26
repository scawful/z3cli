"""Shared tool bridge interfaces for z3cli."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Protocol


class ToolBridge(Protocol):
    def get_openai_tools(self) -> list[dict]:
        ...

    async def call_tool(self, name: str, arguments: dict) -> str:
        ...

    def get_tool_server(self, tool_name: str) -> str:
        ...

    @property
    def tool_count(self) -> int:
        ...

    @property
    def server_names(self) -> list[str]:
        ...

    @property
    def server_tool_counts(self) -> dict[str, int]:
        ...

    async def close(self) -> None:
        ...

    # Optional: bridges may override ``is_write_tool`` to authoritatively
    # declare whether a specific tool mutates state. ReadOnlyBridge prefers
    # this answer over pattern-matching. Return None to defer to the pattern
    # list. Implementations that never provide an authoritative answer can
    # omit this method entirely — call sites use ``getattr``.
    #
    #   def is_write_tool(self, tool_name: str) -> bool | None: ...


@dataclass
class _BridgeCollision:
    """Record of a tool-name collision resolved at bridge composition time."""

    tool: str                 # actual tool name that collided
    winner_server: str        # server that kept the unprefixed name
    loser_server: str         # server whose tool got prefixed
    loser_exposed: str        # final prefixed name the model sees for the loser

    def describe(self) -> str:
        return (
            f"tool name '{self.tool}' collided between '{self.winner_server}' (kept) "
            f"and '{self.loser_server}' (renamed to '{self.loser_exposed}')"
        )


class CompositeBridge:
    """Combine multiple tool bridges into one OpenAI tool surface.

    When two bridges expose the same tool name, the current owner keeps
    the unprefixed name and the newcomer's version is renamed
    ``<server>_<actual>``. Callers can supply ``priority`` on
    :meth:`add_bridge` to invert that default: a newcomer with strictly
    higher priority evicts the incumbent (the incumbent gets the prefix).

    Each collision is recorded in :attr:`collisions` so the tooling layer
    can surface a startup warning — renames are no longer silent.
    """

    def __init__(self, bridges: list[ToolBridge] | None = None):
        self._bridges: list[ToolBridge] = []
        self._tools: list[dict] = []
        self._tool_bridge: dict[str, ToolBridge] = {}
        self._tool_actual: dict[str, str] = {}
        self._tool_server: dict[str, str] = {}
        self._tool_priority: dict[str, int] = {}
        self._collisions: list[_BridgeCollision] = []
        if bridges:
            for bridge in bridges:
                self.add_bridge(bridge)

    @property
    def collisions(self) -> tuple[_BridgeCollision, ...]:
        """Tool-name collisions recorded so far (order of occurrence)."""
        return tuple(self._collisions)

    def add_bridge(self, bridge: ToolBridge, priority: int = 0) -> None:
        self._bridges.append(bridge)
        for tool in bridge.get_openai_tools():
            schema = deepcopy(tool)
            function = schema.get("function") or {}
            actual_name = function.get("name")
            if not isinstance(actual_name, str) or not actual_name:
                continue
            server_name = bridge.get_tool_server(actual_name)

            if actual_name in self._tool_bridge:
                incumbent_priority = self._tool_priority.get(actual_name, 0)
                if priority > incumbent_priority:
                    # Newcomer wins: evict the incumbent to a prefixed name.
                    incumbent_server = self._tool_server.get(actual_name, "tool")
                    incumbent_exposed = self._allocate_exposed_name(incumbent_server, actual_name)
                    self._rekey_entry(actual_name, incumbent_exposed)
                    self._collisions.append(_BridgeCollision(
                        tool=actual_name,
                        winner_server=server_name or "?",
                        loser_server=incumbent_server,
                        loser_exposed=incumbent_exposed,
                    ))
                    exposed_name = actual_name
                else:
                    # Incumbent wins: rename the newcomer.
                    exposed_name = self._allocate_exposed_name(server_name, actual_name)
                    function["name"] = exposed_name
                    self._collisions.append(_BridgeCollision(
                        tool=actual_name,
                        winner_server=self._tool_server.get(actual_name, "?"),
                        loser_server=server_name or "?",
                        loser_exposed=exposed_name,
                    ))
            else:
                exposed_name = actual_name

            self._tools.append(schema)
            self._tool_bridge[exposed_name] = bridge
            self._tool_actual[exposed_name] = actual_name
            self._tool_server[exposed_name] = server_name
            self._tool_priority[exposed_name] = priority

    @staticmethod
    def _prefix_name(server: str, actual: str) -> str:
        prefix = server.replace("-", "_") if server else "tool"
        return f"{prefix}_{actual}"

    def _allocate_exposed_name(self, server: str, actual: str) -> str:
        """Return a collision-free exposed name for a renamed tool."""
        base = self._prefix_name(server, actual)
        candidate = base
        suffix = 2
        while candidate in self._tool_bridge:
            candidate = f"{base}_{suffix}"
            suffix += 1
        return candidate

    def _rekey_entry(self, old_name: str, new_name: str) -> None:
        """Rewrite an existing entry to a new exposed name (collision eviction)."""
        bridge = self._tool_bridge.pop(old_name, None)
        actual = self._tool_actual.pop(old_name, old_name)
        server = self._tool_server.pop(old_name, "")
        priority = self._tool_priority.pop(old_name, 0)
        if bridge is None:
            return
        self._tool_bridge[new_name] = bridge
        self._tool_actual[new_name] = actual
        self._tool_server[new_name] = server
        self._tool_priority[new_name] = priority
        # Update the schema entry so the OpenAI tool list reflects the new name.
        for schema in self._tools:
            fn = schema.get("function") or {}
            if fn.get("name") == old_name:
                fn["name"] = new_name
                break

    @property
    def bridges(self) -> tuple[ToolBridge, ...]:
        """Underlying child bridges in insertion order."""
        return tuple(self._bridges)

    def get_openai_tools(self) -> list[dict]:
        return self._tools

    async def call_tool(self, name: str, arguments: dict) -> str:
        bridge = self._tool_bridge.get(name)
        if bridge is None:
            return f"Error: Unknown tool '{name}'"
        actual_name = self._tool_actual.get(name, name)
        return await bridge.call_tool(actual_name, arguments)

    def get_tool_server(self, tool_name: str) -> str:
        return self._tool_server.get(tool_name, "unknown")

    def is_write_tool(self, tool_name: str) -> bool | None:
        """Delegate to the underlying bridge that owns the tool."""
        bridge = self._tool_bridge.get(tool_name)
        if bridge is None:
            return None
        actual_name = self._tool_actual.get(tool_name, tool_name)
        inner = getattr(bridge, "is_write_tool", None)
        if inner is None:
            return None
        try:
            return inner(actual_name)
        except Exception:
            return None

    @property
    def tool_count(self) -> int:
        return len(self._tools)

    @property
    def server_names(self) -> list[str]:
        names: list[str] = []
        seen: set[str] = set()
        for bridge in self._bridges:
            for name in bridge.server_names:
                if name not in seen:
                    seen.add(name)
                    names.append(name)
        return names

    @property
    def server_tool_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for bridge in self._bridges:
            for name, count in bridge.server_tool_counts.items():
                counts[name] = counts.get(name, 0) + count
        return counts

    async def close(self) -> None:
        for bridge in reversed(self._bridges):
            await bridge.close()


# ---------------------------------------------------------------------------
# Write-operation patterns for dry-run enforcement
# ---------------------------------------------------------------------------

# Tool names that perform writes. Matched case-insensitively.
_WRITE_TOOL_PATTERNS = {
    "place", "remove", "delete", "set_collision", "write",
    "patch", "apply_patch", "save",
}

# Argument keys that enable writes (e.g., z3ed's --write flag).
_WRITE_ARG_KEYS = {"write", "dry_run", "dryRun"}


def _is_write_tool(name: str) -> bool:
    """Check if a tool name looks like a write operation."""
    lower = name.lower()
    return any(pattern in lower for pattern in _WRITE_TOOL_PATTERNS)


class ReadOnlyBridge:
    """Wraps a bridge and blocks write operations.

    When active, any tool call that matches a write pattern returns an
    error message instead of executing.  Arguments with write-enable
    keys are also stripped so even pass-through calls stay read-only.

    Use this as a safety layer for local models that shouldn't modify
    ROM data or project files without explicit user approval.
    """

    def __init__(self, bridge: ToolBridge):
        self._bridge = bridge

    def get_openai_tools(self) -> list[dict]:
        return self._bridge.get_openai_tools()

    def _looks_like_write(self, name: str) -> bool:
        """Authoritative answer from the bridge if available, else pattern match."""
        inner = getattr(self._bridge, "is_write_tool", None)
        if inner is not None:
            try:
                declared = inner(name)
            except Exception:
                declared = None
            if declared is not None:
                return bool(declared)
        return _is_write_tool(name)

    async def call_tool(self, name: str, arguments: dict) -> str:
        if self._looks_like_write(name):
            return f"Error: Write operation '{name}' is blocked in read-only mode. Use /tools-write on to enable."

        # Strip write-enable flags from arguments as a safety net
        safe_args = {
            k: v for k, v in arguments.items()
            if k.lower() not in _WRITE_ARG_KEYS
        }
        return await self._bridge.call_tool(name, safe_args)

    def get_tool_server(self, tool_name: str) -> str:
        return self._bridge.get_tool_server(tool_name)

    def is_write_tool(self, tool_name: str) -> bool | None:
        inner = getattr(self._bridge, "is_write_tool", None)
        if inner is None:
            return None
        try:
            return inner(tool_name)
        except Exception:
            return None

    @property
    def tool_count(self) -> int:
        return self._bridge.tool_count

    @property
    def server_names(self) -> list[str]:
        return self._bridge.server_names

    @property
    def server_tool_counts(self) -> dict[str, int]:
        return self._bridge.server_tool_counts

    async def close(self) -> None:
        await self._bridge.close()
