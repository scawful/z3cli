"""Tests for CompositeBridge collision detection and priority eviction."""

from __future__ import annotations

import unittest

from z3cli.core.tool_bridge import CompositeBridge


class _StubBridge:
    def __init__(self, server: str, tools: list[str]):
        self._server = server
        self._tool_names = tools
        self.calls: list[tuple[str, dict]] = []

    def get_openai_tools(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": f"{self._server}::{name}",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
            for name in self._tool_names
        ]

    async def call_tool(self, name: str, arguments: dict) -> str:
        self.calls.append((name, dict(arguments)))
        return f"{self._server}/{name}"

    def get_tool_server(self, tool_name: str) -> str:
        return self._server

    @property
    def tool_count(self) -> int:
        return len(self._tool_names)

    @property
    def server_names(self) -> list[str]:
        return [self._server]

    @property
    def server_tool_counts(self) -> dict[str, int]:
        return {self._server: len(self._tool_names)}

    async def close(self) -> None:
        return None


class CollisionPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_collisions_emitted_when_tools_unique(self) -> None:
        a = _StubBridge("a", ["alpha", "beta"])
        b = _StubBridge("b", ["gamma"])
        comp = CompositeBridge([a, b])
        self.assertEqual(comp.collisions, ())
        self.assertEqual(comp.tool_count, 3)

    async def test_incumbent_wins_by_default(self) -> None:
        mcp = _StubBridge("book-of-mudora", ["rom_doctor"])
        z3ed = _StubBridge("z3ed", ["rom_doctor"])
        comp = CompositeBridge()
        comp.add_bridge(mcp)
        comp.add_bridge(z3ed)
        collisions = comp.collisions
        self.assertEqual(len(collisions), 1)
        self.assertEqual(collisions[0].tool, "rom_doctor")
        self.assertEqual(collisions[0].winner_server, "book-of-mudora")
        self.assertEqual(collisions[0].loser_server, "z3ed")
        self.assertEqual(collisions[0].loser_exposed, "z3ed_rom_doctor")
        # Dispatch still works under both names.
        await comp.call_tool("rom_doctor", {})
        self.assertEqual(mcp.calls[-1][0], "rom_doctor")
        await comp.call_tool("z3ed_rom_doctor", {})
        self.assertEqual(z3ed.calls[-1][0], "rom_doctor")

    async def test_newcomer_evicts_on_higher_priority(self) -> None:
        mcp = _StubBridge("book-of-mudora", ["rom_doctor"])
        z3ed = _StubBridge("z3ed", ["rom_doctor"])
        comp = CompositeBridge()
        comp.add_bridge(mcp, priority=0)
        comp.add_bridge(z3ed, priority=10)  # z3ed wins
        collisions = comp.collisions
        self.assertEqual(len(collisions), 1)
        self.assertEqual(collisions[0].winner_server, "z3ed")
        self.assertEqual(collisions[0].loser_server, "book-of-mudora")
        self.assertEqual(collisions[0].loser_exposed, "book_of_mudora_rom_doctor")
        # The unprefixed name now routes to the new owner (z3ed).
        await comp.call_tool("rom_doctor", {})
        self.assertEqual(z3ed.calls[-1], ("rom_doctor", {}))
        self.assertEqual(mcp.calls, [])
        # The evicted incumbent is still reachable under the prefixed name.
        await comp.call_tool("book_of_mudora_rom_doctor", {})
        self.assertEqual(mcp.calls[-1], ("rom_doctor", {}))

    async def test_describe_collision_is_human_readable(self) -> None:
        a = _StubBridge("alpha", ["shared"])
        b = _StubBridge("beta", ["shared"])
        comp = CompositeBridge([a, b])
        msg = comp.collisions[0].describe()
        self.assertIn("'shared'", msg)
        self.assertIn("alpha", msg)
        self.assertIn("beta", msg)
        self.assertIn("renamed", msg)

    async def test_prefixed_newcomer_name_does_not_overwrite_existing_tool(self) -> None:
        alpha = _StubBridge("alpha", ["shared", "beta_shared"])
        beta = _StubBridge("beta", ["shared"])
        comp = CompositeBridge([alpha, beta])

        collisions = comp.collisions
        self.assertEqual(len(collisions), 1)
        self.assertEqual(collisions[0].loser_exposed, "beta_shared_2")

        await comp.call_tool("shared", {})
        await comp.call_tool("beta_shared", {})
        await comp.call_tool("beta_shared_2", {})

        self.assertEqual(alpha.calls[0], ("shared", {}))
        self.assertEqual(alpha.calls[1], ("beta_shared", {}))
        self.assertEqual(beta.calls[0], ("shared", {}))

    async def test_prefixed_eviction_name_does_not_overwrite_existing_tool(self) -> None:
        incumbent = _StubBridge("book-of-mudora", ["shared", "book_of_mudora_shared"])
        newcomer = _StubBridge("z3ed", ["shared"])
        comp = CompositeBridge()
        comp.add_bridge(incumbent, priority=0)
        comp.add_bridge(newcomer, priority=10)

        collisions = comp.collisions
        self.assertEqual(len(collisions), 1)
        self.assertEqual(collisions[0].loser_exposed, "book_of_mudora_shared_2")

        await comp.call_tool("shared", {})
        await comp.call_tool("book_of_mudora_shared", {})
        await comp.call_tool("book_of_mudora_shared_2", {})

        self.assertEqual(newcomer.calls[0], ("shared", {}))
        self.assertEqual(incumbent.calls[0], ("book_of_mudora_shared", {}))
        self.assertEqual(incumbent.calls[1], ("shared", {}))


if __name__ == "__main__":
    unittest.main()
