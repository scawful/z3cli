"""Tests for MCP capability partitioning and fallback translation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from z3cli.app.tooling import _build_capability_bridges
from z3cli.core.rom_project import RomProject
from z3cli.core.tool_bridge import CompositeBridge
from z3cli.protocol.asm_test_bridge import AsmTestBridge
from z3cli.protocol.mcp_bridge import MCPBridge
from z3cli.protocol.workspace_context_bridge import WorkspaceContextBridge
from z3cli.protocol.z3ed_bridge import Z3edBridge


class _StubMCPBridge(MCPBridge):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, dict]] = []

    def seed_tool(self, server_name: str, tool_name: str, description: str = "") -> None:
        self._sessions[server_name] = object()  # type: ignore[assignment]
        self._tool_server[tool_name] = server_name
        self._tool_actual[tool_name] = tool_name
        self._tools.append({
            "type": "function",
            "function": {
                "name": tool_name,
                "description": description,
                "parameters": {"type": "object", "properties": {}},
            },
        })
        self._server_tool_counts[server_name] = self._server_tool_counts.get(server_name, 0) + 1

    async def call_tool(self, name: str, arguments: dict) -> str:
        self.calls.append((name, dict(arguments)))
        return f"OK:{name}"


class _StubZ3edBridge(Z3edBridge):
    def __init__(self) -> None:
        pass

    def get_openai_tools(self) -> list[dict]:
        return [{
            "type": "function",
            "function": {
                "name": "mesen_memory_read",
                "description": "",
                "parameters": {"type": "object", "properties": {}},
            },
        }]

    async def call_tool(self, name: str, arguments: dict) -> str:
        return f"z3ed:{name}"

    def get_tool_server(self, tool_name: str) -> str:
        return "z3ed"

    @property
    def tool_count(self) -> int:
        return 1

    @property
    def server_names(self) -> list[str]:
        return ["z3ed"]

    @property
    def server_tool_counts(self) -> dict[str, int]:
        return {"z3ed": 1}

    async def close(self) -> None:
        return None


class MCPRoutingSplitTests(unittest.IsolatedAsyncioTestCase):
    def test_capability_views_split_servers_cleanly(self) -> None:
        bridge = _StubMCPBridge()
        bridge.seed_tool("yaze-debugger", "read_memory")
        bridge.seed_tool("yaze-editor", "dungeon_describe_room")
        bridge.seed_tool("book-of-mudora", "search")
        bridge.seed_tool("afs", "context.read")

        caps = _build_capability_bridges(bridge)

        self.assertEqual(
            [tool["function"]["name"] for tool in caps["emulator"].get_openai_tools()],
            ["read_memory"],
        )
        self.assertEqual(
            [tool["function"]["name"] for tool in caps["rom"].get_openai_tools()],
            ["dungeon_describe_room"],
        )
        self.assertEqual(
            [tool["function"]["name"] for tool in caps["reference"].get_openai_tools()],
            ["search", "context.read"],
        )
        self.assertEqual(caps["reference"].server_names, ["book-of-mudora", "afs"])

    async def test_emulator_view_translates_adapter_calls_to_yaze_debugger(self) -> None:
        bridge = _StubMCPBridge()
        bridge.seed_tool("yaze-debugger", "read_memory")
        bridge.seed_tool("yaze-debugger", "add_breakpoint")
        bridge.seed_tool("yaze-debugger", "step_emulator")
        bridge.seed_tool("yaze-debugger", "get_disassembly")
        bridge.seed_tool("yaze-debugger", "get_debug_status")
        bridge.seed_tool("yaze-debugger", "get_game_state")

        emulator = _build_capability_bridges(bridge)["emulator"]

        await emulator.call_tool("mesen_memory_read", {"address": "0x7E0000", "length": 32})
        await emulator.call_tool(
            "mesen_breakpoint", {"action": "add", "address": "0x02A3B0", "type": "write"},
        )
        await emulator.call_tool("mesen_control", {"action": "step", "mode": "into"})
        await emulator.call_tool("mesen_disasm", {"address": "0x02A3B0", "count": 12})
        await emulator.call_tool("mesen_cpu", {})
        await emulator.call_tool("mesen_gamestate", {})

        self.assertEqual(
            bridge.calls,
            [
                ("read_memory", {"address": "0x7E0000", "size": 32}),
                ("add_breakpoint", {"address": "0x02A3B0", "bp_type": "WRITE"}),
                ("step_emulator", {"mode": "instruction"}),
                ("get_disassembly", {"address": "0x02A3B0", "count": 12}),
                ("get_debug_status", {}),
                ("get_game_state", {}),
            ],
        )

    async def test_rom_view_rewrites_room_args_for_yaze_editor(self) -> None:
        bridge = _StubMCPBridge()
        bridge.seed_tool("yaze-editor", "dungeon_describe_room")
        bridge.seed_tool("yaze-editor", "dungeon_place_sprite")
        bridge.seed_tool("yaze-editor", "overworld_describe_map")

        rom = _build_capability_bridges(bridge)["rom"]

        await rom.call_tool("dungeon_describe_room", {"room": "0x45"})
        await rom.call_tool(
            "dungeon_place_sprite",
            {"room": "0x45", "id": "0x80", "x": "0x03", "y": "0x04", "write": True},
        )
        await rom.call_tool("overworld_describe_map", {"map_id": "0x1A"})

        self.assertEqual(
            bridge.calls,
            [
                ("dungeon_describe_room", {"room_id": 0x45}),
                (
                    "dungeon_place_sprite",
                    {"room_id": 0x45, "sprite_id": 0x80, "x": 0x03, "y": 0x04, "write": True},
                ),
                ("overworld_describe_map", {"map_id": 0x1A}),
            ],
        )

    def test_direct_z3ed_bridge_stays_ahead_of_mcp_fallback(self) -> None:
        mcp = _StubMCPBridge()
        mcp.seed_tool("yaze-debugger", "read_memory")
        mcp.seed_tool("yaze-editor", "dungeon_describe_room")
        z3ed = _StubZ3edBridge()

        caps = _build_capability_bridges(CompositeBridge([mcp, z3ed]))

        self.assertIs(caps["emulator"], z3ed)
        self.assertIs(caps["rom"], z3ed)

    def test_workflow_bridge_gets_dedicated_capability_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = RomProject.discover(workspace=Path(tmp), env={})
            workflow = AsmTestBridge(project)
            workflow._available_tools = {"emu_assert"}

            caps = _build_capability_bridges(CompositeBridge([workflow]))

        self.assertIs(caps["workflow"], workflow)
        self.assertEqual(
            [tool["function"]["name"] for tool in caps["workflow"].get_openai_tools()],
            ["emu_assert"],
        )

    def test_workspace_bridge_gets_dedicated_capability_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = WorkspaceContextBridge(Path(tmp))
            caps = _build_capability_bridges(CompositeBridge([workspace]))

        self.assertIs(caps["workspace"], workspace)
        self.assertEqual(
            [tool["function"]["name"] for tool in caps["workspace"].get_openai_tools()],
            ["workspace_read"],
        )


if __name__ == "__main__":
    unittest.main()
