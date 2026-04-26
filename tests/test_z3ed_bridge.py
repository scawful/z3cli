"""Tests for Z3edBridge — subprocess-per-call yaze integration."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import stat
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from core.rom_project import RomProject
from protocol.z3ed_bridge import Z3edBridge


def _write_fake_z3ed(
    target: Path,
    *,
    schemas: dict | None = None,
    response: str = '{"ok": true}',
    fail: bool = False,
) -> None:
    """Write a Python-based z3ed stand-in that records its invocation."""
    payload_json = json.dumps(schemas or {"commands": []})
    body = f"""#!{sys.executable}
import json, os, sys

if "--export-schemas" in sys.argv:
    sys.stdout.write({payload_json!r})
    sys.exit(0)

recorder = os.environ.get("FAKE_Z3ED_RECORD")
if recorder:
    with open(recorder, "a") as f:
        f.write(" ".join(sys.argv[1:]) + chr(10))

if {fail!r}:
    sys.stderr.write("simulated failure")
    sys.exit(2)

sys.stdout.write({response!r})
sys.exit(0)
"""
    target.write_text(body)
    target.chmod(target.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _write_fake_mesen_launcher(
    target: Path,
    *,
    socket_path: Path,
) -> None:
    body = f"""#!/bin/bash
set -euo pipefail
recorder="${{FAKE_MESEN_LAUNCH_RECORD:-}}"
if [[ -n "$recorder" ]]; then
  printf '%s\\n' "$*" >> "$recorder"
fi
touch {str(socket_path)!r}
echo '  export MESEN2_HOME="/tmp/mesen-home"'
echo '  export MESEN2_SOCKET_PATH="{str(socket_path)}"'
echo '  export MESEN2_INSTANCE="z3cli-test"'
"""
    target.write_text(body)
    target.chmod(target.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


class Z3edBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_connect_translates_tools(self) -> None:
        schemas = {
            "commands": [
                {
                    "name": "rom-info",
                    "category": "rom",
                    "description": "Show rom header info",
                    "usage": "rom-info --rom <path> [--format <json|text>]",
                    "available_to_agent": True,
                    "requires_rom": True,
                    "requires_grpc": False,
                    "examples": ["z3ed rom-info --rom=oos.sfc"],
                },
                {
                    "name": "emulator-read-memory",
                    "category": "emulator",
                    "description": "gRPC-only",
                    "usage": "emulator-read-memory --address <hex>",
                    "available_to_agent": True,
                    "requires_rom": False,
                    "requires_grpc": True,
                    "examples": [],
                },
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_z3ed = tmp_path / "z3ed"
            _write_fake_z3ed(fake_z3ed, schemas=schemas)
            proj = RomProject.discover(workspace=tmp_path, env={})
            bridge = Z3edBridge(proj, yaze_bin=fake_z3ed)
            warnings = await bridge.connect()
        self.assertEqual(warnings, [])
        tools = bridge.get_openai_tools()
        names = [t["function"]["name"] for t in tools]
        self.assertIn("rom_info", names)
        self.assertNotIn("emulator_read_memory", names)
        self.assertEqual(bridge.tool_count, 1)

    async def test_connect_is_idempotent(self) -> None:
        schemas = {
            "commands": [
                {
                    "name": "rom-info",
                    "category": "rom",
                    "description": "",
                    "usage": "rom-info --rom <path>",
                    "available_to_agent": True,
                    "requires_rom": True,
                    "requires_grpc": False,
                    "examples": [],
                },
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_z3ed = tmp_path / "z3ed"
            _write_fake_z3ed(fake_z3ed, schemas=schemas)
            proj = RomProject.discover(workspace=tmp_path, env={})
            bridge = Z3edBridge(proj, yaze_bin=fake_z3ed)
            await bridge.connect()
            warnings = await bridge.connect()
        self.assertEqual(warnings, [])
        self.assertEqual(bridge.tool_count, 1)
        names = [t["function"]["name"] for t in bridge.get_openai_tools()]
        self.assertEqual(names, ["rom_info"])

    async def test_connect_surfaces_duplicate_translated_tool_name_warning(self) -> None:
        schemas = {
            "commands": [
                {
                    "name": "room-info",
                    "category": "rom",
                    "description": "",
                    "usage": "room-info --room <id>",
                    "available_to_agent": True,
                    "requires_rom": False,
                    "requires_grpc": False,
                    "examples": [],
                },
                {
                    "name": "room_info",
                    "category": "rom",
                    "description": "",
                    "usage": "room_info --room <id>",
                    "available_to_agent": True,
                    "requires_rom": False,
                    "requires_grpc": False,
                    "examples": [],
                },
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_z3ed = tmp_path / "z3ed"
            _write_fake_z3ed(fake_z3ed, schemas=schemas)
            proj = RomProject.discover(workspace=tmp_path, env={})
            bridge = Z3edBridge(proj, yaze_bin=fake_z3ed)
            warnings = await bridge.connect()
        self.assertEqual(bridge.tool_count, 1)
        self.assertTrue(
            any("duplicate translated tool name 'room_info'" in warning for warning in warnings),
            warnings,
        )

    async def test_call_tool_auto_injects_rom_and_format(self) -> None:
        schemas = {
            "commands": [
                {
                    "name": "rom-info",
                    "category": "rom",
                    "description": "",
                    "usage": "rom-info --rom <path> [--format <json|text>]",
                    "available_to_agent": True,
                    "requires_rom": True,
                    "requires_grpc": False,
                    "examples": [],
                },
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_z3ed = tmp_path / "z3ed"
            recorder = tmp_path / "record.txt"
            _write_fake_z3ed(fake_z3ed, schemas=schemas, response='{"title":"X"}')
            rom = tmp_path / "rom.sfc"
            rom.write_bytes(b"\x00" * 32)
            proj = RomProject.discover(workspace=tmp_path, rom_path=rom, env={})
            bridge = Z3edBridge(proj, yaze_bin=fake_z3ed)
            await bridge.connect()

            os.environ["FAKE_Z3ED_RECORD"] = str(recorder)
            try:
                result = await bridge.call_tool("rom_info", {})
            finally:
                os.environ.pop("FAKE_Z3ED_RECORD", None)
            self.assertIn("title", result)
            captured = recorder.read_text().strip().splitlines()[-1]
            self.assertIn("rom-info", captured)
            self.assertIn(f"--rom={rom.resolve()}", captured)
            self.assertIn("--format=json", captured)

    async def test_call_tool_injects_mesen_socket(self) -> None:
        schemas = {
            "commands": [
                {
                    "name": "mesen-memory-read",
                    "category": "mesen2",
                    "description": "",
                    "usage": "mesen-memory-read --address <hex> [--length <n>] [--format <json|text>]",
                    "available_to_agent": True,
                    "requires_rom": False,
                    "requires_grpc": False,
                    "examples": [],
                },
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_z3ed = tmp_path / "z3ed"
            recorder = tmp_path / "record.txt"
            _write_fake_z3ed(fake_z3ed, schemas=schemas, response='{"bytes":"00 01"}')
            proj = RomProject.discover(
                workspace=tmp_path,
                env={"MESEN2_SOCKET_PATH": "/tmp/stub.sock"},
            )
            bridge = Z3edBridge(proj, yaze_bin=fake_z3ed)
            await bridge.connect()
            os.environ["FAKE_Z3ED_RECORD"] = str(recorder)
            try:
                await bridge.call_tool("mesen_memory_read", {"address": "0x7E0000"})
            finally:
                os.environ.pop("FAKE_Z3ED_RECORD", None)
            captured = recorder.read_text().strip().splitlines()[-1]
            self.assertIn("mesen-memory-read", captured)
            self.assertIn("--mesen-socket=/tmp/stub.sock", captured)
            self.assertIn("--address=0x7E0000", captured)

    async def test_bridge_reports_write_tools(self) -> None:
        schemas = {
            "commands": [
                {
                    "name": "mesen-memory-write",
                    "category": "mesen2",
                    "description": "",
                    "usage": "mesen-memory-write --address <hex> --data <hexbytes>",
                    "available_to_agent": True,
                    "requires_rom": False,
                    "requires_grpc": False,
                    "examples": [],
                },
                {
                    "name": "mesen-memory-read",
                    "category": "mesen2",
                    "description": "",
                    "usage": "mesen-memory-read --address <hex>",
                    "available_to_agent": True,
                    "requires_rom": False,
                    "requires_grpc": False,
                    "examples": [],
                },
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_z3ed = tmp_path / "z3ed"
            _write_fake_z3ed(fake_z3ed, schemas=schemas)
            proj = RomProject.discover(workspace=tmp_path, env={})
            bridge = Z3edBridge(proj, yaze_bin=fake_z3ed)
            await bridge.connect()
        self.assertTrue(bridge.is_write_tool("mesen_memory_write"))
        self.assertFalse(bridge.is_write_tool("mesen_memory_read"))
        self.assertIsNone(bridge.is_write_tool("unknown_tool"))

    async def test_non_zero_exit_surfaces_error(self) -> None:
        schemas = {
            "commands": [
                {
                    "name": "rom-info",
                    "category": "rom",
                    "description": "",
                    "usage": "rom-info --rom <path>",
                    "available_to_agent": True,
                    "requires_rom": True,
                    "requires_grpc": False,
                    "examples": [],
                },
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_z3ed = tmp_path / "z3ed"
            _write_fake_z3ed(fake_z3ed, schemas=schemas, fail=True)
            rom = tmp_path / "rom.sfc"
            rom.write_bytes(b"\x00")
            proj = RomProject.discover(workspace=tmp_path, rom_path=rom, env={})
            bridge = Z3edBridge(proj, yaze_bin=fake_z3ed)
            await bridge.connect()
            result = await bridge.call_tool("rom_info", {})
        self.assertIn("Error", result)
        self.assertIn("exit=2", result)
        self.assertIn("simulated failure", result)

    async def test_mesen_preflight_without_socket(self) -> None:
        schemas = {
            "commands": [
                {
                    "name": "mesen-memory-read",
                    "category": "mesen2",
                    "description": "",
                    "usage": "mesen-memory-read --address <hex> [--length <n>]",
                    "available_to_agent": True,
                    "requires_rom": False,
                    "requires_grpc": False,
                    "examples": [],
                },
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_z3ed = tmp_path / "z3ed"
            _write_fake_z3ed(fake_z3ed, schemas=schemas, response='{"bytes":"ff"}')
            proj = RomProject.discover(workspace=tmp_path, env={})
            # Sanity-check the precondition before invoking.
            self.assertIsNone(proj.mesen_socket)
            bridge = Z3edBridge(proj, yaze_bin=fake_z3ed, auto_bootstrap_mesen=False)
            await bridge.connect()
            with patch("core.rom_project._discover_mesen_socket", return_value=None):
                result = await bridge.call_tool("mesen_memory_read", {"address": "0x7E0000"})
        self.assertIn("Error", result)
        self.assertIn("Mesen2", result)
        self.assertIn("socket not detected", result)

    async def test_mesen_preflight_passes_with_socket(self) -> None:
        schemas = {
            "commands": [
                {
                    "name": "mesen-memory-read",
                    "category": "mesen2",
                    "description": "",
                    "usage": "mesen-memory-read --address <hex>",
                    "available_to_agent": True,
                    "requires_rom": False,
                    "requires_grpc": False,
                    "examples": [],
                },
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_z3ed = tmp_path / "z3ed"
            _write_fake_z3ed(fake_z3ed, schemas=schemas, response='{"ok":true}')
            proj = RomProject.discover(
                workspace=tmp_path,
                env={"MESEN2_SOCKET_PATH": "/tmp/stub.sock"},
            )
            bridge = Z3edBridge(proj, yaze_bin=fake_z3ed)
            await bridge.connect()
            result = await bridge.call_tool("mesen_memory_read", {"address": "0x7E0000"})
        self.assertIn("ok", result)

    async def test_mesen_preflight_auto_bootstraps_with_patched_rom(self) -> None:
        schemas = {
            "commands": [
                {
                    "name": "mesen-memory-read",
                    "category": "mesen2",
                    "description": "",
                    "usage": "mesen-memory-read --address <hex>",
                    "available_to_agent": True,
                    "requires_rom": False,
                    "requires_grpc": False,
                    "examples": [],
                },
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_z3ed = tmp_path / "z3ed"
            z3ed_record = tmp_path / "z3ed-record.txt"
            launch_record = tmp_path / "launch-record.txt"
            boot_socket = tmp_path / "mesen-boot.sock"
            _write_fake_z3ed(fake_z3ed, schemas=schemas, response='{"ok":true}')
            launcher = tmp_path / "Scripts" / "Mesen2" / "mesen2_launch_instance.sh"
            launcher.parent.mkdir(parents=True, exist_ok=True)
            _write_fake_mesen_launcher(launcher, socket_path=boot_socket)
            rom_dir = tmp_path / "Roms"
            rom_dir.mkdir()
            base_rom = rom_dir / "oos168.sfc"
            patched_rom = rom_dir / "oos168x.sfc"
            base_rom.write_bytes(b"\x00")
            patched_rom.write_bytes(b"\x01")
            proj = RomProject.discover(workspace=tmp_path, rom_path=base_rom, env={})
            bridge = Z3edBridge(proj, yaze_bin=fake_z3ed)
            await bridge.connect()

            os.environ["FAKE_Z3ED_RECORD"] = str(z3ed_record)
            os.environ["FAKE_MESEN_LAUNCH_RECORD"] = str(launch_record)
            try:
                with patch("core.rom_project._discover_mesen_socket", return_value=None):
                    result = await bridge.call_tool("mesen_memory_read", {"address": "0x7E0000"})
            finally:
                os.environ.pop("FAKE_Z3ED_RECORD", None)
                os.environ.pop("FAKE_MESEN_LAUNCH_RECORD", None)
                os.environ.pop("MESEN2_SOCKET_PATH", None)
                os.environ.pop("MESEN2_INSTANCE", None)

            self.assertIn("ok", result)
            launch_cmd = launch_record.read_text().strip().splitlines()[-1]
            self.assertIn(f"--rom {patched_rom.resolve()}", launch_cmd)
            captured = z3ed_record.read_text().strip().splitlines()[-1]
            self.assertIn(f"--mesen-socket={boot_socket}", captured)

    async def test_missing_binary_warns_not_crashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proj = RomProject.discover(workspace=Path(tmp), env={})
            # Absolute path that doesn't exist.
            missing = Path(tmp) / "nonexistent_z3ed"
            bridge = Z3edBridge(proj, yaze_bin=missing)
            # Override PATH lookup so the test doesn't pick up a real z3ed.
            old_path = os.environ.get("PATH", "")
            os.environ["PATH"] = ""
            try:
                warnings = await bridge.connect()
            finally:
                os.environ["PATH"] = old_path
        self.assertTrue(any("z3ed binary not found" in w for w in warnings))
        self.assertEqual(bridge.tool_count, 0)


if __name__ == "__main__":
    unittest.main()
