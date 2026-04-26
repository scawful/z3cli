"""Tests for Phase 4 capability-keyed adapter routing."""

from __future__ import annotations

import unittest
from typing import Any

from core.tool_adapters import get_adapter


class _TrackingBridge:
    """Minimal ToolBridge that records every call with a tag."""

    def __init__(self, tag: str, response: str | None = None):
        self.tag = tag
        self.calls: list[tuple[str, dict]] = []
        self._response = response or f"{tag} result"

    def get_openai_tools(self) -> list[dict]:
        return []

    async def call_tool(self, name: str, arguments: dict) -> str:
        self.calls.append((name, dict(arguments)))
        return f"[{self.tag}] {name}({arguments}) -> {self._response}"

    def get_tool_server(self, tool_name: str) -> str:
        return self.tag

    @property
    def tool_count(self) -> int:
        return 0

    @property
    def server_names(self) -> list[str]:
        return [self.tag]

    @property
    def server_tool_counts(self) -> dict[str, int]:
        return {self.tag: 0}

    async def close(self) -> None:
        return None


class CapabilityRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_farore_workflow_tools_route_to_workflow_bridge(self) -> None:
        workflow = _TrackingBridge("workflow")
        emulator = _TrackingBridge("emulator")
        adapter = get_adapter("farore", {"workflow": workflow, "emulator": emulator})
        assert adapter is not None

        await adapter.call_tool("scenario_run", {"scenario": "sanctuary", "frames": 30})
        await adapter.call_tool("emu_assert", {"assertions": ["LinkHealth > 0"]})

        self.assertEqual(
            [call[0] for call in workflow.calls],
            ["scenario_run", "emu_assert"],
        )
        self.assertEqual(emulator.calls, [])

    async def test_farore_dispatches_by_capability(self) -> None:
        rom = _TrackingBridge("rom")
        emulator = _TrackingBridge("emulator")
        symbols = _TrackingBridge("symbols")
        adapter = get_adapter("farore", {"rom": rom, "emulator": emulator, "symbols": symbols})
        assert adapter is not None

        # inspect_room should hit the "rom" bridge 4 times.
        await adapter.call_tool("inspect_room", {"room": "0x45"})
        rom_tools = [call[0] for call in rom.calls]
        self.assertEqual(
            rom_tools,
            [
                "dungeon_describe_room",
                "dungeon_list_objects",
                "dungeon_list_sprites",
                "dungeon_list_chests",
            ],
        )
        self.assertEqual(emulator.calls, [])

        # read_memory should hit the "emulator" bridge.
        emulator.calls.clear()
        await adapter.call_tool("read_memory", {"address": "0x7E0000"})
        self.assertEqual(len(emulator.calls), 1)
        self.assertEqual(emulator.calls[0][0], "mesen_memory_read")

        # check_diagnostics should hit the "symbols" bridge.
        await adapter.call_tool("check_diagnostics", {"file": "/a/b.asm"})
        self.assertEqual(symbols.calls[-1][0], "z3lsp_diagnostics")

    async def test_set_breakpoint_rewrites_arguments(self) -> None:
        emulator = _TrackingBridge("emulator")
        adapter = get_adapter("farore", {"emulator": emulator})
        assert adapter is not None
        await adapter.call_tool(
            "set_breakpoint", {"address": "0x02A3B0", "type": "write"},
        )
        name, args = emulator.calls[-1]
        self.assertEqual(name, "mesen_breakpoint")
        self.assertEqual(args["action"], "add")
        self.assertEqual(args["address"], "0x02A3B0")
        self.assertEqual(args["type"], "write")

    async def test_missing_capability_falls_back_to_star(self) -> None:
        fallback = _TrackingBridge("fallback")
        # Only the star key is wired — every capability call falls back.
        adapter = get_adapter("farore", {"*": fallback})
        assert adapter is not None
        await adapter.call_tool("read_memory", {"address": "0x7E0000"})
        self.assertEqual(len(fallback.calls), 1)
        self.assertEqual(fallback.calls[0][0], "mesen_memory_read")

    async def test_no_bridge_surfaces_actionable_error(self) -> None:
        # Empty dict — every capability should produce an error.
        adapter = get_adapter("farore", {})
        assert adapter is not None
        result = await adapter.call_tool("read_memory", {"address": "0x7E0000"})
        self.assertIn("Error", result)
        self.assertIn("farore", result)

    async def test_legacy_single_bridge_signature(self) -> None:
        # get_adapter used to take a single ToolBridge — must still work.
        bridge = _TrackingBridge("legacy")
        adapter = get_adapter("farore", bridge)
        assert adapter is not None
        await adapter.call_tool("read_memory", {"address": "0x7E0000"})
        self.assertEqual(len(bridge.calls), 1)

    def test_retired_profiles_do_not_bind_runtime_adapters(self) -> None:
        fallback = _TrackingBridge("fallback")

        for profile in ("veran", "majora", "hylia"):
            with self.subTest(profile=profile):
                self.assertIsNone(get_adapter(profile, {"*": fallback}))

    async def test_din_step_trace_loops_and_collects_state(self) -> None:
        emulator = _TrackingBridge("emulator")
        adapter = get_adapter("din", {"emulator": emulator})
        assert adapter is not None
        await adapter.call_tool("step_trace", {"count": 3})
        # Each step invokes mesen_control then mesen_cpu.
        tools = [c[0] for c in emulator.calls]
        self.assertEqual(tools.count("mesen_control"), 3)
        self.assertEqual(tools.count("mesen_cpu"), 3)

    async def test_din_file_and_diagnostics_tools_route_to_reference_and_symbols(self) -> None:
        workspace = _TrackingBridge("workspace")
        symbols = _TrackingBridge("symbols")
        adapter = get_adapter("din", {"workspace": workspace, "symbols": symbols})
        assert adapter is not None

        await adapter.call_tool("read_context", {"path": "src/main.asm"})
        await adapter.call_tool("check_diagnostics", {"file": "src/main.asm"})

        self.assertEqual(workspace.calls[-1][0], "workspace_read")
        self.assertEqual(symbols.calls[-1][0], "z3lsp_diagnostics")

    async def test_nayru_explain_routine_queries_symbols_and_reference(self) -> None:
        symbols = _TrackingBridge("symbols")
        reference = _TrackingBridge("reference")
        adapter = get_adapter("nayru", {"symbols": symbols, "reference": reference})
        assert adapter is not None
        await adapter.call_tool("explain_routine", {"query": "Link_Main"})
        self.assertEqual(symbols.calls[-1][0], "z3lsp_symbols")
        self.assertEqual(reference.calls[-1][0], "find_usages")


if __name__ == "__main__":
    unittest.main()
