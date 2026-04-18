"""Tests for deferred tool schema loading."""

from __future__ import annotations

import json
import unittest

from z3cli.core.deferred_tools import DeferredToolBridge, TOOL_SEARCH_NAME


class MockFullBridge:
    """Bridge with a broad, varied tool catalog for search testing."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self._tools = [
            self._tool("read_memory", "Read bytes from ROM or RAM address"),
            self._tool("write_memory", "Write bytes to RAM (disabled in read-only mode)"),
            self._tool("set_breakpoint", "Set a Mesen2 emulator breakpoint"),
            self._tool("search_reference", "Search vanilla ALttP disassembly"),
            self._tool("describe_room", "Describe a dungeon room by ID"),
            self._tool("consult_docs", "Consult project docs for a symbol"),
            self._tool("place_sprite", "Place a sprite in a room"),
            self._tool("read_file", "Read a file from the workspace"),
        ]
        # Map tool name to synthetic server for get_tool_server()
        self._servers = {
            "read_memory": "yaze-debugger",
            "write_memory": "yaze-debugger",
            "set_breakpoint": "mesen2-oos",
            "search_reference": "book-of-mudora",
            "describe_room": "yaze-editor",
            "consult_docs": "hyrule-historian",
            "place_sprite": "yaze-editor",
            "read_file": "afs",
        }

    @staticmethod
    def _tool(name: str, description: str) -> dict:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {"type": "object", "properties": {}},
            },
        }

    def get_openai_tools(self) -> list[dict]:
        return list(self._tools)

    async def call_tool(self, name: str, arguments: dict) -> str:
        self.calls.append((name, arguments))
        return f"OK:{name}"

    def get_tool_server(self, tool_name: str) -> str:
        return self._servers.get(tool_name, "unknown")

    @property
    def tool_count(self) -> int:
        return len(self._tools)

    @property
    def server_names(self) -> list[str]:
        return sorted(set(self._servers.values()))

    @property
    def server_tool_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for server in self._servers.values():
            counts[server] = counts.get(server, 0) + 1
        return counts

    async def close(self) -> None:
        pass


class DeferredToolBridgeTests(unittest.IsolatedAsyncioTestCase):
    def test_exposes_only_search_and_core_by_default(self) -> None:
        inner = MockFullBridge()
        bridge = DeferredToolBridge(inner, core=["read_file"])
        tools = bridge.get_openai_tools()
        names = [t["function"]["name"] for t in tools]
        self.assertIn(TOOL_SEARCH_NAME, names)
        self.assertIn("read_file", names)
        # Other tools are hidden until search reveals them
        self.assertNotIn("read_memory", names)
        self.assertNotIn("set_breakpoint", names)

    def test_empty_core_exposes_only_search(self) -> None:
        bridge = DeferredToolBridge(MockFullBridge())
        tools = bridge.get_openai_tools()
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["function"]["name"], TOOL_SEARCH_NAME)

    async def test_search_finds_by_name(self) -> None:
        bridge = DeferredToolBridge(MockFullBridge())
        raw = await bridge.call_tool(TOOL_SEARCH_NAME, {"query": "memory"})
        result = json.loads(raw)
        revealed_names = {t["function"]["name"] for t in result["tools"]}
        self.assertIn("read_memory", revealed_names)
        self.assertIn("write_memory", revealed_names)

    async def test_search_finds_by_description(self) -> None:
        bridge = DeferredToolBridge(MockFullBridge())
        raw = await bridge.call_tool(TOOL_SEARCH_NAME, {"query": "emulator"})
        result = json.loads(raw)
        revealed_names = {t["function"]["name"] for t in result["tools"]}
        self.assertIn("set_breakpoint", revealed_names)

    async def test_search_reveals_tools_for_next_round(self) -> None:
        bridge = DeferredToolBridge(MockFullBridge())
        # Before search: not visible
        before = [t["function"]["name"] for t in bridge.get_openai_tools()]
        self.assertNotIn("set_breakpoint", before)
        # Search reveals it
        await bridge.call_tool(TOOL_SEARCH_NAME, {"query": "breakpoint"})
        after = [t["function"]["name"] for t in bridge.get_openai_tools()]
        self.assertIn("set_breakpoint", after)
        # Search tool itself is still visible
        self.assertIn(TOOL_SEARCH_NAME, after)

    async def test_revealed_tool_delegates_to_inner(self) -> None:
        inner = MockFullBridge()
        bridge = DeferredToolBridge(inner)
        # Reveal the tool via search
        await bridge.call_tool(TOOL_SEARCH_NAME, {"query": "read_memory"})
        # Now callable directly
        result = await bridge.call_tool("read_memory", {"address": "0x7E0000"})
        self.assertEqual(result, "OK:read_memory")
        self.assertEqual(inner.calls, [("read_memory", {"address": "0x7E0000"})])

    async def test_unrevealed_tool_rejected_with_helpful_error(self) -> None:
        inner = MockFullBridge()
        bridge = DeferredToolBridge(inner)
        result = await bridge.call_tool("read_memory", {})
        self.assertIn("has not been loaded", result)
        self.assertIn(TOOL_SEARCH_NAME, result)
        # Inner bridge should NOT have been called
        self.assertEqual(inner.calls, [])

    async def test_core_tools_callable_without_search(self) -> None:
        inner = MockFullBridge()
        bridge = DeferredToolBridge(inner, core=["read_file"])
        result = await bridge.call_tool("read_file", {"path": "README.md"})
        self.assertEqual(result, "OK:read_file")

    async def test_empty_query_returns_catalog(self) -> None:
        bridge = DeferredToolBridge(MockFullBridge())
        raw = await bridge.call_tool(TOOL_SEARCH_NAME, {"query": ""})
        result = json.loads(raw)
        self.assertIn("tools", result)
        # Catalog includes all 8 inner tools as name/description/server
        self.assertEqual(len(result["tools"]), 8)
        # Catalog entries do NOT have full schema, just metadata
        entry = result["tools"][0]
        self.assertIn("name", entry)
        self.assertIn("description", entry)
        self.assertNotIn("parameters", entry)

    async def test_search_ranks_name_matches_higher(self) -> None:
        bridge = DeferredToolBridge(MockFullBridge())
        raw = await bridge.call_tool(TOOL_SEARCH_NAME, {"query": "memory"})
        result = json.loads(raw)
        # Name matches for 'memory' should come before description-only matches
        # read_memory and write_memory both have 'memory' in name → tied at top
        top_names = [t["function"]["name"] for t in result["tools"][:2]]
        self.assertIn("read_memory", top_names)
        self.assertIn("write_memory", top_names)

    async def test_search_limit_caps_results(self) -> None:
        bridge = DeferredToolBridge(MockFullBridge())
        raw = await bridge.call_tool(
            TOOL_SEARCH_NAME, {"query": "memory file room breakpoint reference docs sprite", "limit": 2},
        )
        result = json.loads(raw)
        self.assertLessEqual(len(result["tools"]), 2)

    async def test_manual_reveal_via_api(self) -> None:
        bridge = DeferredToolBridge(MockFullBridge())
        added = bridge.reveal(["read_memory", "nonexistent"])
        self.assertEqual(added, ["read_memory"])
        names = [t["function"]["name"] for t in bridge.get_openai_tools()]
        self.assertIn("read_memory", names)

    def test_server_metadata_includes_deferred(self) -> None:
        bridge = DeferredToolBridge(MockFullBridge())
        self.assertIn("deferred", bridge.server_names)
        self.assertEqual(bridge.get_tool_server(TOOL_SEARCH_NAME), "deferred")
        self.assertEqual(bridge.get_tool_server("read_memory"), "yaze-debugger")

    def test_tool_count_reflects_full_surface(self) -> None:
        bridge = DeferredToolBridge(MockFullBridge())
        # Expose the full count so status reporting is accurate
        self.assertEqual(bridge.tool_count, 1 + 8)


class IntegrationWithEngineTests(unittest.IsolatedAsyncioTestCase):
    """Smoke-test that re-fetching tools per round picks up newly-revealed tools."""

    async def test_engine_sees_revealed_tools_across_rounds(self) -> None:
        # Verify that ChatEngine calls get_openai_tools() inside the loop
        # by asserting the bridge gets called more than once across rounds.
        from z3cli.core.engine import ChatEngine
        from z3cli.core.provider import (
            CompletionChunk, CompletionRequest, ContentDelta, ToolCallDelta,
            UsageInfo,
        )

        class CountingBridge:
            def __init__(self, inner):
                self._inner = inner
                self.get_calls = 0

            def get_openai_tools(self) -> list[dict]:
                self.get_calls += 1
                return self._inner.get_openai_tools()

            async def call_tool(self, name: str, arguments: dict) -> str:
                return await self._inner.call_tool(name, arguments)

            def get_tool_server(self, tool_name: str) -> str:
                return self._inner.get_tool_server(tool_name)

            @property
            def tool_count(self) -> int:
                return self._inner.tool_count

            @property
            def server_names(self) -> list[str]:
                return self._inner.server_names

            @property
            def server_tool_counts(self) -> dict[str, int]:
                return self._inner.server_tool_counts

            async def close(self) -> None:
                await self._inner.close()

        # Mock provider: round 1 calls a tool, round 2 returns text
        from typing import AsyncGenerator

        class TwoRoundProvider:
            def __init__(self):
                self._round = 0

            @property
            def name(self) -> str:
                return "mock"

            async def stream(
                self, request: CompletionRequest,
            ) -> AsyncGenerator[CompletionChunk, None]:
                self._round += 1
                if self._round == 1:
                    yield CompletionChunk(
                        tool_calls=[ToolCallDelta(
                            id="t1", name="read_file", arguments='{"path":"x"}',
                        )],
                    )
                    yield CompletionChunk(usage=UsageInfo(prompt_tokens=1, completion_tokens=1))
                else:
                    yield CompletionChunk(content=ContentDelta(text="done"))
                    yield CompletionChunk(usage=UsageInfo(prompt_tokens=1, completion_tokens=1))

            async def check_connection(self) -> bool:
                return True

            async def close(self) -> None:
                pass

        inner = DeferredToolBridge(MockFullBridge(), core=["read_file"])
        counting = CountingBridge(inner)
        engine = ChatEngine(provider=TwoRoundProvider(), bridge=counting)

        async for _ in engine.chat(message="hi", model_id="m", max_rounds=2):
            pass

        # Should have been called at least twice (once per round), proving
        # the fix that moves tool retrieval into the round loop
        self.assertGreaterEqual(counting.get_calls, 2)


if __name__ == "__main__":
    unittest.main()
