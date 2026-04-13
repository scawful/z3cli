"""Base class for model-specific tool adapters.

A ToolAdapter wraps an underlying ToolBridge (the full MCP surface) and
exposes a compact, purpose-built interface. The adapter implements the
ToolBridge protocol so it can be used as a drop-in replacement — the
ChatEngine never needs to know whether it's talking to the raw bridge
or an adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from z3cli.core.tool_bridge import ToolBridge


@dataclass
class AdapterTool:
    """Definition of a single adapter tool."""

    name: str
    description: str
    parameters: dict  # JSON Schema for the tool's parameters


class ToolAdapter:
    """Base class for model-specific tool adapters.

    Subclasses must:
    1. Set PROFILE_NAME to the adapter's profile identifier.
    2. Override _define_tools() to return the custom tool definitions.
    3. Override _dispatch() to handle tool calls.
    """

    PROFILE_NAME: str = ""

    def __init__(self, bridge: ToolBridge):
        self._bridge = bridge
        self._adapter_tools = self._define_tools()
        self._openai_tools = [self._to_openai(t) for t in self._adapter_tools]
        self._tool_names = {t.name for t in self._adapter_tools}

    def _define_tools(self) -> list[AdapterTool]:
        """Define the custom tool set. Override in subclasses."""
        return []

    async def _dispatch(self, name: str, arguments: dict) -> str:
        """Route a custom tool call to underlying bridge calls.

        Override in subclasses. Use self._call() to invoke underlying tools.
        """
        return f"Error: tool '{name}' not implemented in {self.PROFILE_NAME} adapter"

    # -- ToolBridge protocol ---------------------------------------------------

    def get_openai_tools(self) -> list[dict]:
        return self._openai_tools

    async def call_tool(self, name: str, arguments: dict) -> str:
        if name not in self._tool_names:
            return f"Error: unknown tool '{name}' (available: {', '.join(sorted(self._tool_names))})"
        return await self._dispatch(name, arguments)

    def get_tool_server(self, tool_name: str) -> str:
        return self.PROFILE_NAME

    @property
    def tool_count(self) -> int:
        return len(self._openai_tools)

    @property
    def server_names(self) -> list[str]:
        return [self.PROFILE_NAME]

    @property
    def server_tool_counts(self) -> dict[str, int]:
        return {self.PROFILE_NAME: len(self._openai_tools)}

    async def close(self) -> None:
        await self._bridge.close()

    # -- Helpers for subclasses ------------------------------------------------

    async def _call(self, name: str, arguments: dict | None = None) -> str:
        """Call a tool on the underlying bridge."""
        return await self._bridge.call_tool(name, arguments or {})

    async def _call_many(self, calls: list[tuple[str, dict]]) -> list[str]:
        """Call multiple underlying tools sequentially, return all results."""
        results = []
        for name, args in calls:
            results.append(await self._call(name, args))
        return results

    @staticmethod
    def _to_openai(tool: AdapterTool) -> dict:
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }
