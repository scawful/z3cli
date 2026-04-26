from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.config import MCPServerConfig
from protocol.mcp_bridge import MCPBridge


class _TaskBoundTransport:
    def __init__(self) -> None:
        self.enter_task = None

    async def __aenter__(self):
        self.enter_task = asyncio.current_task()
        return object(), object()

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if asyncio.current_task() is not self.enter_task:
            raise RuntimeError("transport exited in different task")


class _TaskBoundClientSession:
    tools = [
        SimpleNamespace(
            name="search",
            description="Search docs",
            inputSchema={"type": "object", "properties": {"query": {"type": "string"}}},
        ),
    ]

    def __init__(self, read_stream, write_stream):
        del read_stream, write_stream
        self.enter_task = None

    async def __aenter__(self):
        self.enter_task = asyncio.current_task()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if asyncio.current_task() is not self.enter_task:
            raise RuntimeError("session exited in different task")

    async def initialize(self) -> None:
        return None

    async def list_tools(self):
        return SimpleNamespace(tools=list(self.tools))

    async def call_tool(self, name: str, arguments: dict):
        return SimpleNamespace(content=[SimpleNamespace(text=f"{name}:{arguments.get('query', '')}")])


class MCPBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_close_keeps_task_bound_mcp_contexts_on_worker_task(self) -> None:
        bridge = MCPBridge()
        config = {
            "book-of-mudora": MCPServerConfig(
                name="book-of-mudora",
                command="/bin/echo",
                args=[],
                env={},
            ),
        }

        with (
            patch("protocol.mcp_bridge.stdio_client", side_effect=lambda params: _TaskBoundTransport()),
            patch("protocol.mcp_bridge.ClientSession", _TaskBoundClientSession),
        ):
            errors = await bridge.connect(config)
            self.assertEqual(errors, [])
            result = await bridge.call_tool("search", {"query": "mask"})
            self.assertEqual(result, "search:mask")
            await bridge.close()

        self.assertEqual(bridge.server_names, [])
