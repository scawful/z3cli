"""Tests for the high-level ASM workflow bridge."""

from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path

from z3cli.core.rom_project import RomProject
from z3cli.protocol.asm_test_bridge import AsmTestBridge


class _FakeZ3asmBridge:
    def __init__(self, project: RomProject, *, lint_ok: bool = True):
        self.project = project
        self.lint_ok = lint_ok
        self.calls: list[tuple[str, dict]] = []

    async def connect(self) -> list[str]:
        return []

    def get_openai_tools(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "z3asm_lint",
                    "description": "",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "z3asm_assemble",
                    "description": "",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ]

    async def call_tool(self, name: str, arguments: dict) -> str:
        self.calls.append((name, dict(arguments)))
        if name == "z3asm_lint":
            return json.dumps({"lint.json": {"ok": self.lint_ok}}, indent=2)
        if name == "z3asm_assemble":
            return json.dumps({"diagnostics.json": {"ok": True}}, indent=2)
        return f"Error: unknown tool {name}"

    async def close(self) -> None:
        return None


class _FakeMCPBridge:
    def __init__(self, responses: dict[str, object]):
        normalized: dict[tuple[str, str], object] = {}
        for key, value in responses.items():
            if isinstance(key, tuple):
                server_name, tool_name = key
            else:
                server_name, tool_name = "yaze-debugger", key
            normalized[(str(server_name), str(tool_name))] = value
        self.responses = normalized
        self.calls: list[tuple[str, dict]] = []

    def find_exposed_tool(self, server_name: str, actual_name: str) -> str | None:
        return actual_name if (server_name, actual_name) in self.responses else None

    @property
    def server_names(self) -> list[str]:
        return sorted({server for server, _tool in self.responses})

    async def call_tool(self, name: str, arguments: dict) -> str:
        self.calls.append((name, dict(arguments)))
        response = None
        for (_server, tool_name), candidate in self.responses.items():
            if tool_name == name:
                response = candidate
                break
        if response is None:
            raise KeyError(name)
        if callable(response):
            return str(response(arguments))
        return str(response)


class AsmTestBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_connect_requires_debugger_minimum_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = RomProject.discover(workspace=Path(tmp), env={})
            instances: list[_FakeZ3asmBridge] = []

            def factory(proj: RomProject) -> _FakeZ3asmBridge:
                bridge = _FakeZ3asmBridge(proj)
                instances.append(bridge)
                return bridge

            bridge = AsmTestBridge(project, mcp_bridge=_FakeMCPBridge({}), z3asm_factory=factory)
            await bridge.connect()

        self.assertEqual(bridge.tool_count, 0)
        self.assertEqual(instances[0].project.workspace, project.workspace)

    async def test_connect_exposes_partial_tool_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            project = RomProject.discover(workspace=tmp_path, env={})

            def factory(proj: RomProject) -> _FakeZ3asmBridge:
                return _FakeZ3asmBridge(proj)

            bridge = AsmTestBridge(
                project,
                mcp_bridge=_FakeMCPBridge({
                    "emu_test_run": "{}",
                }),
                z3asm_factory=factory,
            )
            await bridge.connect()

        self.assertEqual(bridge.tool_count, 1)
        self.assertEqual(
            [tool["function"]["name"] for tool in bridge.get_openai_tools()],
            ["emu_assert"],
        )

    async def test_asm_patch_test_runs_transaction_and_restores_state(self) -> None:
        screenshot_bytes = b"\x89PNG\r\n\x1a\nfake"
        screenshot_path: Path | None = None
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            rom = tmp_path / "oracle.sfc"
            rom.write_bytes(b"\xAA" * 64)
            patch = tmp_path / "patch.asm"
            patch.write_text("lorom\n")
            project = RomProject.discover(workspace=tmp_path, rom_path=rom, env={})

            instances: list[_FakeZ3asmBridge] = []

            def factory(proj: RomProject) -> _FakeZ3asmBridge:
                bridge = _FakeZ3asmBridge(proj)
                instances.append(bridge)
                return bridge

            def save_state(arguments: dict) -> str:
                Path(arguments["filepath"]).write_bytes(b"state")
                return "State saved"

            responses = {
                "load_rom": "ROM loaded",
                "load_test_state": "Test state loaded",
                "save_emulator_state": save_state,
                "load_emulator_state": "State loaded",
                "emu_test_run": json.dumps({
                    "success": True,
                    "assertions": [{"expr": "LinkHealth > 0", "passed": True}],
                    "breakpoint_hit": True,
                    "final_state": {"cpu": {"pc": 0x8000}, "memory": {"LinkHealth": "03"}},
                }),
                "emu_screenshot": "Screenshot from yaze\n" + base64.b64encode(screenshot_bytes).decode(),
            }
            mcp = _FakeMCPBridge(responses)
            bridge = AsmTestBridge(project, mcp_bridge=mcp, z3asm_factory=factory)
            await bridge.connect()
            self.assertEqual(bridge.tool_count, 4)

            raw = await bridge.call_tool("asm_patch_test", {
                "patch_path": str(patch),
                "scenario": "sanctuary",
                "assertions": ["LinkHealth > 0"],
                "breakpoints": ["$008000"],
                "capture_screenshot": True,
                "restore_after": True,
            })
            payload = json.loads(raw)
            screenshot_path = Path(payload["screenshot_path"])

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["lint_ok"])
        self.assertTrue(payload["assemble_ok"])
        self.assertTrue(payload["emulator_ok"])
        self.assertTrue(payload["scenario_loaded"])
        self.assertEqual(payload["cpu"], {"pc": 0x8000})
        self.assertEqual(payload["memory"], {"LinkHealth": "03"})
        self.assertEqual(payload["assertions"][0]["ok"], True)
        self.assertEqual(payload["failure_stage"], None)
        self.assertFalse(next(a for a in payload["artifacts"] if a["kind"] == "temp_rom")["exists"])
        runtime_bridge = instances[-1]
        self.assertNotEqual(runtime_bridge.project.rom_path, rom.resolve())
        self.assertFalse(runtime_bridge.project.rom_path.exists())
        self.assertEqual(
            [name for name, _args in mcp.calls],
            [
                "save_emulator_state",
                "load_rom",
                "load_test_state",
                "emu_test_run",
                "emu_screenshot",
                "load_emulator_state",
            ],
        )
        self.assertTrue(screenshot_path.exists())
        self.assertEqual(screenshot_path.read_bytes(), screenshot_bytes)
        screenshot_path.unlink()

    async def test_scenario_run_uses_current_rom_and_loads_test_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            project = RomProject.discover(workspace=tmp_path, env={})

            def factory(proj: RomProject) -> _FakeZ3asmBridge:
                return _FakeZ3asmBridge(proj)

            mcp = _FakeMCPBridge({
                "load_test_state": "Test state loaded",
                "emu_test_run": json.dumps({
                    "success": True,
                    "final_state": {"cpu": {"pc": 0x8123}},
                }),
            })
            bridge = AsmTestBridge(project, mcp_bridge=mcp, z3asm_factory=factory)
            await bridge.connect()

            raw = await bridge.call_tool("scenario_run", {
                "scenario": "title_screen",
                "frames": 30,
                "restore_after": False,
            })
            payload = json.loads(raw)

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["lint_ok"])
        self.assertTrue(payload["assemble_ok"])
        self.assertTrue(payload["scenario_loaded"])
        self.assertEqual(payload["cpu"], {"pc": 0x8123})
        self.assertEqual(
            [name for name, _args in mcp.calls],
            ["load_test_state", "emu_test_run"],
        )

    async def test_emu_assert_uses_current_state_without_loading_rom(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            project = RomProject.discover(workspace=tmp_path, env={})

            def factory(proj: RomProject) -> _FakeZ3asmBridge:
                return _FakeZ3asmBridge(proj)

            mcp = _FakeMCPBridge({
                "emu_test_run": json.dumps({
                    "success": True,
                    "assertions": [{"expr": "LinkHealth > 0", "passed": True}],
                    "final_state": {"cpu": {"pc": 0x80F0}, "memory": {"LinkHealth": "04"}},
                }),
            })
            bridge = AsmTestBridge(project, mcp_bridge=mcp, z3asm_factory=factory)
            await bridge.connect()

            raw = await bridge.call_tool("emu_assert", {
                "frames": 15,
                "assertions": ["LinkHealth > 0"],
                "restore_after": False,
            })
            payload = json.loads(raw)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["cpu"], {"pc": 0x80F0})
        self.assertEqual(payload["memory"], {"LinkHealth": "04"})
        self.assertEqual([name for name, _args in mcp.calls], ["emu_test_run"])

    async def test_asm_patch_test_marks_assert_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            rom = tmp_path / "oracle.sfc"
            rom.write_bytes(b"\xAA" * 64)
            patch = tmp_path / "patch.asm"
            patch.write_text("lorom\n")
            project = RomProject.discover(workspace=tmp_path, rom_path=rom, env={})

            def factory(proj: RomProject) -> _FakeZ3asmBridge:
                return _FakeZ3asmBridge(proj)

            mcp = _FakeMCPBridge({
                "load_rom": "ROM loaded",
                "emu_test_run": json.dumps({
                    "success": True,
                    "assertions": [{"expr": "LinkHealth > 0", "passed": False, "error": "zero"}],
                    "final_state": {"cpu": {"pc": 0x8000}},
                }),
            })
            bridge = AsmTestBridge(project, mcp_bridge=mcp, z3asm_factory=factory)
            await bridge.connect()

            raw = await bridge.call_tool("asm_patch_test", {
                "patch_path": str(patch),
                "assertions": ["LinkHealth > 0"],
                "restore_after": False,
            })
            payload = json.loads(raw)

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["failure_stage"], "assert")
        self.assertTrue(payload["assemble_ok"])
        self.assertEqual(payload["assertions"][0]["detail"], "zero")

    async def test_hook_try_validates_target_before_assembly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            rom = tmp_path / "oracle.sfc"
            rom.write_bytes(b"\xAA" * 64)
            patch = tmp_path / "hook.asm"
            patch.write_text("org $028000\nrtl\n")
            project = RomProject.discover(workspace=tmp_path, rom_path=rom, env={})

            def factory(proj: RomProject) -> _FakeZ3asmBridge:
                return _FakeZ3asmBridge(proj)

            mcp = _FakeMCPBridge({
                ("hyrule-historian", "validate_hook"): "safe hook",
                "load_rom": "ROM loaded",
                "emu_test_run": json.dumps({
                    "success": True,
                    "final_state": {"cpu": {"pc": 0x8000}},
                }),
            })
            bridge = AsmTestBridge(project, mcp_bridge=mcp, z3asm_factory=factory)
            await bridge.connect()

            raw = await bridge.call_tool("hook_try", {
                "patch_path": str(patch),
                "address": "$028000",
                "restore_after": False,
            })
            payload = json.loads(raw)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["diagnostics"]["hook_address"], "$028000")
        self.assertEqual(payload["diagnostics"]["hook_validate"], "safe hook")
        self.assertEqual(
            [name for name, _args in mcp.calls],
            ["validate_hook", "load_rom", "emu_test_run"],
        )

    async def test_missing_patch_fails_before_invoking_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = RomProject.discover(workspace=Path(tmp), env={})
            instances: list[_FakeZ3asmBridge] = []

            def factory(proj: RomProject) -> _FakeZ3asmBridge:
                bridge = _FakeZ3asmBridge(proj)
                instances.append(bridge)
                return bridge

            mcp = _FakeMCPBridge({
                "load_rom": "ROM loaded",
                "emu_test_run": "{}",
            })
            bridge = AsmTestBridge(project, mcp_bridge=mcp, z3asm_factory=factory)
            await bridge.connect()

            raw = await bridge.call_tool("asm_patch_test", {"patch_path": str(Path(tmp) / "missing.asm")})
            payload = json.loads(raw)

        self.assertEqual(payload["failure_stage"], "setup")
        self.assertEqual(mcp.calls, [])
        # Only the connect-time probe should have been instantiated.
        self.assertEqual(len(instances), 1)


if __name__ == "__main__":
    unittest.main()
