"""Base class for model-specific tool adapters.

A ToolAdapter wraps one or more underlying ToolBridges and exposes a
compact, purpose-built interface. The adapter implements the ToolBridge
protocol so it can be used as a drop-in replacement — the ChatEngine
never needs to know whether it's talking to the raw bridge or an adapter.

Capability-keyed routing
------------------------
Adapters accept a ``bridges: dict[str, ToolBridge]`` map. Keys identify
what the bridge provides; adapters dispatch via ``_call_on(capability,
tool, args)``. Conventional capability keys:

  ``"symbols"``    — z3lsp (hover, symbols, definition, references)
  ``"rom"``        — z3ed (dungeon/overworld/message/ROM inspection)
  ``"emulator"``   — z3ed mesen-* (memory, disasm, breakpoints, step)
  ``"asm"``        — z3asm / z3disasm
  ``"workflow"``   — high-level patch/run/assert workflows
  ``"workspace"``  — local workspace file reads
  ``"reference"``  — book-of-mudora, afs, or similar MCP servers
  ``"*"``          — full fallback / legacy catch-all

A missing capability is a first-class signal: :meth:`_call_on` returns a
clear error so the model knows the feature isn't available rather than
receiving a silent MCP-stub failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping
from core.tool_bridge import ToolBridge


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

    Constructors accept either ``ToolAdapter(bridges_dict)`` (new style,
    capability-keyed) or ``ToolAdapter(bridge)`` (legacy single-bridge,
    stored under the ``"*"`` key).
    """

    PROFILE_NAME: str = ""
    WRITE_TOOLS: frozenset[str] = frozenset()

    def __init__(self, bridges: ToolBridge | Mapping[str, ToolBridge]):
        if isinstance(bridges, Mapping):
            self._bridges: dict[str, ToolBridge] = dict(bridges)
        else:
            self._bridges = {"*": bridges}
        # Preserve legacy single-bridge attribute so code that hasn't been
        # migrated can still reach a fallback — the "*" key is the catch-all.
        self._bridge = self._bridges.get("*") or next(iter(self._bridges.values()), None)
        self._adapter_tools = self._define_tools()
        self._openai_tools = [self._to_openai(t) for t in self._adapter_tools]
        self._tool_names = {t.name for t in self._adapter_tools}

    def _define_tools(self) -> list[AdapterTool]:
        """Define the custom tool set. Override in subclasses."""
        return []

    async def _dispatch(self, name: str, arguments: dict) -> str:
        """Route a custom tool call to underlying bridge calls.

        Override in subclasses. Use ``_call_on(capability, tool, args)``
        for new code; ``_call(tool, args)`` is the legacy catch-all.
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

    def is_write_tool(self, tool_name: str) -> bool | None:
        if tool_name in self.WRITE_TOOLS:
            return True
        if tool_name in self._tool_names:
            return None
        return None

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
        # Close every distinct bridge we hold. The same bridge may appear
        # under multiple capability keys (e.g., z3ed under both "rom" and
        # "emulator"); close each exactly once.
        seen: set[int] = set()
        for bridge in self._bridges.values():
            if bridge is None or id(bridge) in seen:
                continue
            seen.add(id(bridge))
            await bridge.close()

    # -- Helpers for subclasses ------------------------------------------------

    async def _call(self, name: str, arguments: dict | None = None) -> str:
        """Legacy: call a tool on the ``"*"`` catch-all bridge."""
        bridge = self._bridges.get("*") or self._bridge
        if bridge is None:
            return f"Error: adapter '{self.PROFILE_NAME}' has no fallback bridge"
        return await bridge.call_tool(name, arguments or {})

    async def _call_on(
        self,
        capability: str,
        name: str,
        arguments: dict | None = None,
    ) -> str:
        """Call a tool via a specific capability bridge.

        If the capability isn't configured, falls back to the ``"*"`` bridge
        (so models still work in legacy single-bridge mode). If neither is
        available, returns an actionable error naming the missing piece.
        """
        bridge = self._bridges.get(capability) or self._bridges.get("*")
        if bridge is None:
            return (
                f"Error: adapter '{self.PROFILE_NAME}' is missing the "
                f"'{capability}' capability (no bridge wired)."
            )
        return await bridge.call_tool(name, arguments or {})

    async def _call_many(self, calls: list[tuple[str, dict]]) -> list[str]:
        """Call multiple tools sequentially via the ``"*"`` catch-all bridge."""
        results = []
        for name, args in calls:
            results.append(await self._call(name, args))
        return results

    async def _call_many_on(
        self,
        calls: list[tuple[str, str, dict]],
    ) -> list[str]:
        """Call multiple tools, each with its own capability, sequentially.

        Each entry is ``(capability, tool_name, arguments)``.
        """
        results: list[str] = []
        for capability, name, args in calls:
            results.append(await self._call_on(capability, name, args))
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
