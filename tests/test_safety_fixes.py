"""Regression tests for read-only and path-confinement safety fixes."""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

from core.rom_project import RomProject
from core.tool_bridge import ReadOnlyBridge
from protocol.z3asm_bridge import Z3asmBridge
from protocol.z3ed_bridge import Z3edBridge
from protocol.z3ed_schema import build_tool

# Mimics z3asm: on success, write the ROM argument (argv[2]).
_WRITING_ASM = """
import pathlib, sys
pathlib.Path(sys.argv[2]).write_bytes(b"\\xff" * 16)
print("ok")
"""


def _write_stub(target: Path, body: str) -> None:
    target.write_text(f"#!{sys.executable}\n{body}")
    target.chmod(target.stat().st_mode | stat.S_IEXEC)


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def get_openai_tools(self) -> list[dict]:
        return []

    def is_write_tool(self, name: str) -> bool:
        return False

    async def call_tool(self, name: str, arguments: dict) -> str:
        self.calls.append((name, arguments))
        return "ok"


class Z3asmSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.rom = self.tmp / "rom.sfc"
        self.rom.write_bytes(b"\x00" * 16)
        self.patch = self.tmp / "patch.asm"
        self.patch.write_text("lorom\n")
        fake = self.tmp / "z3asm"
        _write_stub(fake, _WRITING_ASM)
        fake_disasm = self.tmp / "z3disasm"
        _write_stub(fake_disasm, "import sys; sys.exit(0)")
        proj = RomProject.discover(workspace=self.tmp, rom_path=self.rom, env={})
        self.bridge = Z3asmBridge(proj, z3asm_bin=fake, z3disasm_bin=fake_disasm)
        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = ""
        try:
            await self.bridge.connect()
        finally:
            os.environ["PATH"] = old_path

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()

    async def test_lint_leaves_rom_untouched(self) -> None:
        result = await self.bridge.call_tool("z3asm_lint", {"patch_path": str(self.patch)})
        self.assertFalse(result.startswith("Error"), result)
        self.assertEqual(self.rom.read_bytes(), b"\x00" * 16)

    async def test_assemble_still_writes_rom(self) -> None:
        await self.bridge.call_tool("z3asm_assemble", {"patch_path": str(self.patch)})
        self.assertEqual(self.rom.read_bytes(), b"\xff" * 16)

    async def test_read_output_rejects_paths_outside_workspace(self) -> None:
        result = await self.bridge.call_tool("z3disasm_read_output", {"path": "/etc/hosts"})
        self.assertIn("outside the workspace", result)

    async def test_read_output_rejects_traversal(self) -> None:
        result = await self.bridge.call_tool(
            "z3disasm_read_output", {"path": "../../../../../../etc/hosts"},
        )
        self.assertIn("outside the workspace", result)

    async def test_read_output_allows_workspace_relative(self) -> None:
        result = await self.bridge.call_tool("z3disasm_read_output", {"path": "patch.asm"})
        self.assertIn("lorom", result)

    async def test_lint_rejects_emit_path_outside_workspace(self) -> None:
        result = await self.bridge.call_tool(
            "z3asm_lint",
            {"patch_path": str(self.patch), "emit_targets": ["diagnostics:/etc/z3cli-test.json"]},
        )
        self.assertIn("outside the workspace", result)


class ReadOnlyBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_dry_run_false_is_forced_true(self) -> None:
        inner = _Recorder()
        await ReadOnlyBridge(inner).call_tool("t", {"dry_run": False, "dryRun": False, "dry-run": 0})
        self.assertEqual(inner.calls[0][1], {"dry_run": True, "dryRun": True, "dry-run": True})

    async def test_write_flags_stripped_in_any_case(self) -> None:
        inner = _Recorder()
        await ReadOnlyBridge(inner).call_tool(
            "t", {"Write": True, "overwrite": True, "room": 3},
        )
        self.assertEqual(inner.calls[0][1], {"room": 3})


class Z3edArgvTests(unittest.TestCase):
    def test_undeclared_keys_are_not_forwarded(self) -> None:
        tool = build_tool({"name": "dungeon-list-sprites", "usage": "dungeon-list-sprites --room <id>"})
        self.assertIsNotNone(tool)
        with tempfile.TemporaryDirectory() as tmp:
            proj = RomProject.discover(workspace=Path(tmp), env={})
            bridge = Z3edBridge(proj, yaze_bin=Path(tmp) / "z3ed")
            argv = bridge._build_argv(
                tool, {"room": 5, "overwrite": True, "fix": True}, Path(tmp) / "z3ed",
            )
        self.assertIn("--room=0x5", argv)
        self.assertFalse(any(a.startswith(("--overwrite", "--fix")) for a in argv), argv)


if __name__ == "__main__":
    unittest.main()


class MesenGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_underscored_socket_key_counts_as_supplied(self) -> None:
        from z3ed_fakes import _write_fake_z3ed

        schemas = {"commands": [{
            "name": "mesen-memory-read",
            "category": "mesen2",
            "description": "",
            "usage": "mesen-memory-read --address <hex> [--mesen-socket <path>]",
            "available_to_agent": True,
            "requires_rom": False,
            "requires_grpc": False,
            "examples": [],
        }]}
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "z3ed"
            record = Path(tmp) / "record.txt"
            _write_fake_z3ed(fake, schemas=schemas, response='{"bytes":"ff"}')
            proj = RomProject.discover(workspace=Path(tmp), env={})
            bridge = Z3edBridge(proj, yaze_bin=fake, auto_bootstrap_mesen=False)
            await bridge.connect()
            os.environ["FAKE_Z3ED_RECORD"] = str(record)
            try:
                result = await bridge.call_tool(
                    "mesen_memory_read",
                    {"address": "0x7E0000", "_mesen_socket": "/tmp/mesen2-owned.sock"},
                )
            finally:
                os.environ.pop("FAKE_Z3ED_RECORD", None)
            argv = record.read_text()
        self.assertIn('"bytes":"ff"', result)
        self.assertIn("--mesen-socket=/tmp/mesen2-owned.sock", argv)


class GroundingEvidenceTests(unittest.TestCase):
    def test_mesen_fallback_unavailable_is_not_evidence(self) -> None:
        from core.engine import _GROUNDING_TOOL_NAMES, _tool_result_is_grounding_success

        self.assertIn("cpu_state", _GROUNDING_TOOL_NAMES)
        self.assertFalse(_tool_result_is_grounding_success(
            "cpu_state", "Mesen2 unavailable: CPU state requires a live Mesen2 socket. MESEN2_SOCKET_PATH=not detected.",
        ))
