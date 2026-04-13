"""Shared tool bridge interfaces for z3cli."""

from __future__ import annotations

from copy import deepcopy
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


class CompositeBridge:
    """Combine multiple tool bridges into one OpenAI tool surface."""

    def __init__(self, bridges: list[ToolBridge] | None = None):
        self._bridges: list[ToolBridge] = []
        self._tools: list[dict] = []
        self._tool_bridge: dict[str, ToolBridge] = {}
        self._tool_actual: dict[str, str] = {}
        self._tool_server: dict[str, str] = {}
        if bridges:
            for bridge in bridges:
                self.add_bridge(bridge)

    def add_bridge(self, bridge: ToolBridge) -> None:
        self._bridges.append(bridge)
        for tool in bridge.get_openai_tools():
            schema = deepcopy(tool)
            function = schema.get("function") or {}
            actual_name = function.get("name")
            if not isinstance(actual_name, str) or not actual_name:
                continue
            server_name = bridge.get_tool_server(actual_name)
            exposed_name = actual_name
            if exposed_name in self._tool_bridge:
                prefix = server_name.replace("-", "_") if server_name else "tool"
                exposed_name = f"{prefix}_{actual_name}"
                function["name"] = exposed_name
            self._tools.append(schema)
            self._tool_bridge[exposed_name] = bridge
            self._tool_actual[exposed_name] = actual_name
            self._tool_server[exposed_name] = server_name

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

    async def call_tool(self, name: str, arguments: dict) -> str:
        if _is_write_tool(name):
            return f"Error: Write operation '{name}' is blocked in read-only mode. Use /tools-write on to enable."

        # Strip write-enable flags from arguments as a safety net
        safe_args = {
            k: v for k, v in arguments.items()
            if k.lower() not in _WRITE_ARG_KEYS
        }
        return await self._bridge.call_tool(name, safe_args)

    def get_tool_server(self, tool_name: str) -> str:
        return self._bridge.get_tool_server(tool_name)

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
