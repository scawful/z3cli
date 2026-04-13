"""MCP server lifecycle management and tool dispatch.

Spawns MCP servers as child processes via stdio transport,
collects their tool schemas, and routes tool calls.
"""

from __future__ import annotations

import os
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from z3cli.core.config import MCPServerConfig


class MCPBridge:
    """Manages connections to multiple MCP servers."""

    def __init__(self):
        self._stack = AsyncExitStack()
        self._sessions: dict[str, ClientSession] = {}
        self._tool_server: dict[str, str] = {}  # tool_name -> server_name
        self._tool_actual: dict[str, str] = {}  # exposed_name -> actual tool name
        self._tools: list[dict] = []  # OpenAI function-calling format
        self._server_tool_counts: dict[str, int] = {}

    async def connect(self, servers: dict[str, MCPServerConfig]) -> list[str]:
        """Connect to MCP servers. Non-fatal if some fail.

        Returns list of errors (empty on full success).
        """
        errors = []
        for name, cfg in servers.items():
            try:
                # Merge current env with server-specific env vars
                env = {**os.environ, **cfg.env}
                params = StdioServerParameters(
                    command=cfg.command,
                    args=cfg.args,
                    env=env,
                )
                transport = await self._stack.enter_async_context(
                    stdio_client(params)
                )
                read_stream, write_stream = transport
                session = await self._stack.enter_async_context(
                    ClientSession(read_stream, write_stream)
                )
                await session.initialize()
                self._sessions[name] = session

                # Discover tools
                result = await session.list_tools()
                count = 0
                for tool in result.tools:
                    actual_name = tool.name
                    tool_name = actual_name
                    # Prefix on collision
                    if tool_name in self._tool_server:
                        tool_name = f"{name}_{tool_name}"
                    self._tool_server[tool_name] = name
                    self._tool_actual[tool_name] = actual_name
                    self._tools.append({
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "description": tool.description or "",
                            "parameters": tool.inputSchema or {
                                "type": "object",
                                "properties": {},
                            },
                        },
                    })
                    count += 1
                self._server_tool_counts[name] = count
            except Exception as e:
                errors.append(f"{name}: {e}")

        return errors

    async def call_tool(self, name: str, arguments: dict) -> str:
        """Call an MCP tool by name and return the text result."""
        server_name = self._tool_server.get(name)
        if not server_name:
            return f"Error: Unknown tool '{name}'"

        session = self._sessions.get(server_name)
        if not session:
            return f"Error: Server '{server_name}' not connected"

        actual_name = self._tool_actual.get(name, name)

        try:
            result = await session.call_tool(actual_name, arguments)
            if result.content:
                # MCP results can have multiple content blocks; join text ones
                parts = []
                for block in result.content:
                    text = getattr(block, "text", None)
                    if isinstance(text, str) and text:
                        parts.append(text)
                return "\n".join(parts) if parts else "(no output)"
            return "(no output)"
        except Exception as e:
            return f"Error calling {name}: {e}"

    def get_openai_tools(self) -> list[dict]:
        """Return tool schemas in OpenAI function-calling format."""
        return self._tools

    def get_tool_server(self, tool_name: str) -> str:
        """Which MCP server owns this tool."""
        return self._tool_server.get(tool_name, "unknown")

    @property
    def tool_count(self) -> int:
        return len(self._tools)

    @property
    def server_names(self) -> list[str]:
        return list(self._sessions.keys())

    @property
    def server_tool_counts(self) -> dict[str, int]:
        return dict(self._server_tool_counts)

    async def close(self):
        await self._stack.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()
