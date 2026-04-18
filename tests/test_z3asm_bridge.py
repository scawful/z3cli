"""Tests for Z3asmBridge — assembler/disassembler subprocess bridge."""

from __future__ import annotations

import asyncio
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

from z3cli.core.rom_project import RomProject
from z3cli.protocol.z3asm_bridge import Z3asmBridge


def _write_stub(target: Path, body: str) -> None:
    target.write_text(f"#!{sys.executable}\n{body}")
    target.chmod(target.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


class Z3asmBridgeDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_binaries_surfaces_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proj = RomProject.discover(workspace=Path(tmp), env={})
            bridge = Z3asmBridge(
                proj,
                z3asm_bin=Path(tmp) / "missing_z3asm",
                z3disasm_bin=Path(tmp) / "missing_z3disasm",
            )
            # Clear PATH so fallback can't find real binaries.
            old_path = os.environ.get("PATH", "")
            os.environ["PATH"] = ""
            try:
                warnings = await bridge.connect()
            finally:
                os.environ["PATH"] = old_path
        self.assertEqual(bridge.tool_count, 0)
        self.assertTrue(any("z3asm binary not found" in w for w in warnings))
        self.assertTrue(any("z3disasm binary not found" in w for w in warnings))

    async def test_only_z3disasm_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_disasm = tmp_path / "z3disasm"
            _write_stub(fake_disasm, "import sys; sys.exit(0)")
            proj = RomProject.discover(workspace=tmp_path, env={})
            bridge = Z3asmBridge(
                proj,
                z3asm_bin=tmp_path / "missing_z3asm",
                z3disasm_bin=fake_disasm,
            )
            old_path = os.environ.get("PATH", "")
            os.environ["PATH"] = ""
            try:
                warnings = await bridge.connect()
            finally:
                os.environ["PATH"] = old_path
        names = [t["function"]["name"] for t in bridge.get_openai_tools()]
        self.assertIn("z3disasm_bank", names)
        self.assertIn("z3disasm_read_output", names)
        self.assertNotIn("z3asm_assemble", names)
        self.assertTrue(any("z3asm binary not found" in w for w in warnings))

    async def test_connect_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_asm = tmp_path / "z3asm"
            fake_disasm = tmp_path / "z3disasm"
            _write_stub(fake_asm, "import sys; sys.exit(0)")
            _write_stub(fake_disasm, "import sys; sys.exit(0)")
            proj = RomProject.discover(workspace=tmp_path, env={})
            bridge = Z3asmBridge(proj, z3asm_bin=fake_asm, z3disasm_bin=fake_disasm)
            old_path = os.environ.get("PATH", "")
            os.environ["PATH"] = ""
            try:
                await bridge.connect()
                warnings = await bridge.connect()
            finally:
                os.environ["PATH"] = old_path
        self.assertEqual(warnings, [])
        self.assertEqual(bridge.tool_count, 4)
        names = [t["function"]["name"] for t in bridge.get_openai_tools()]
        self.assertEqual(
            names,
            ["z3asm_assemble", "z3asm_lint", "z3disasm_bank", "z3disasm_read_output"],
        )


class Z3asmBridgeInvocationTests(unittest.IsolatedAsyncioTestCase):
    async def test_assemble_uses_invocation_scoped_emit_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            rom = tmp_path / "rom.sfc"
            rom.write_bytes(b"\x00" * 1024)
            patch = tmp_path / "patch.asm"
            patch.write_text("lorom\n")
            fake_asm = tmp_path / "z3asm"
            stub = """
import json
import os
import pathlib
import sys

argv = sys.argv[1:]
legacy_symbols = [a for a in argv if a.startswith('--symbols=')]
if legacy_symbols:
    sys.stderr.write('unexpected legacy symbols flag')
    sys.exit(2)

pathlib.Path('diagnostics.json').write_text(json.dumps({'source': 'cwd'}))

for arg in argv:
    if not arg.startswith('--emit='):
        continue
    value = arg.split('=', 1)[1]
    if ':' in value:
        kind, path = value.split(':', 1)
    else:
        kind, path = value, value
    target = pathlib.Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if kind == 'diagnostics':
        target.write_text(json.dumps({'source': 'emit'}))
    elif kind == 'sourcemap':
        target.write_text(json.dumps({'bank': '02'}))
    elif kind == 'lint':
        target.write_text(json.dumps({'ok': True}))
    elif kind == 'symbols-mlb':
        target.write_text('; symbols\\n')
    else:
        target.write_text(json.dumps({'kind': kind}))

sys.stdout.write('assemble ok\\n')
sys.exit(0)
"""
            _write_stub(fake_asm, stub)
            proj = RomProject.discover(workspace=tmp_path, rom_path=rom, env={})
            bridge = Z3asmBridge(
                proj,
                z3asm_bin=fake_asm,
                z3disasm_bin=tmp_path / "missing",
            )
            old_path = os.environ.get("PATH", "")
            old_cwd = os.getcwd()
            cwd = tmp_path / "cwd"
            cwd.mkdir()
            os.environ["PATH"] = ""
            os.chdir(cwd)
            try:
                await bridge.connect()
                result = await bridge.call_tool("z3asm_assemble", {"patch_path": str(patch)})
            finally:
                os.chdir(old_cwd)
                os.environ["PATH"] = old_path

        payload = json.loads(result)
        self.assertEqual(payload["emit"], ["diagnostics", "sourcemap", "symbols.mlb"])
        self.assertEqual(payload["diagnostics.json"]["source"], "emit")
        self.assertEqual(payload["sourcemap.json"]["bank"], "02")
        self.assertNotEqual(payload["diagnostics.json"]["source"], "cwd")
        self.assertTrue(payload["symbols_path"].endswith("symbols.mlb"))

    async def test_disasm_bank_returns_previews(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            rom = tmp_path / "rom.sfc"
            rom.write_bytes(b"\x00" * 1024)
            fake_disasm = tmp_path / "z3disasm"
            stub = """
import os, sys
# Parse --out (space-separated) from argv.
argv = sys.argv[1:]
out_dir = None
for i, a in enumerate(argv):
    if a == '--out' and i + 1 < len(argv):
        out_dir = argv[i + 1]
        break
    if a.startswith('--out='):
        out_dir = a.split('=', 1)[1]
        break
if out_dir:
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, 'bank_02.asm'), 'w') as f:
        f.write('; generated\\nLABEL_FOO:\\n    LDA #$00\\n    RTS\\n')
sys.stdout.write('disasm ok\\n')
sys.exit(0)
"""
            _write_stub(fake_disasm, stub)
            proj = RomProject.discover(workspace=tmp_path, rom_path=rom, env={})
            bridge = Z3asmBridge(
                proj,
                z3asm_bin=tmp_path / "missing",
                z3disasm_bin=fake_disasm,
            )
            old_path = os.environ.get("PATH", "")
            os.environ["PATH"] = ""
            try:
                await bridge.connect()
                result = await bridge.call_tool(
                    "z3disasm_bank", {"bank_start": "0x02", "bank_end": "0x02"},
                )
            finally:
                os.environ["PATH"] = old_path

        payload = json.loads(result)
        self.assertEqual(payload["files_generated"], 1)
        self.assertEqual(len(payload["files"]), 1)
        self.assertIn("LABEL_FOO", payload["files"][0]["preview"])
        # Round-trip via z3disasm_read_output
        bank_path = payload["files"][0]["path"]
        read_result = await bridge.call_tool("z3disasm_read_output", {"path": bank_path, "lines": 10})
        self.assertIn("LABEL_FOO", read_result)

    async def test_disasm_bank_requires_rom(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_disasm = tmp_path / "z3disasm"
            _write_stub(fake_disasm, "import sys; sys.exit(0)")
            # No rom_path on project.
            proj = RomProject.discover(workspace=tmp_path, env={})
            bridge = Z3asmBridge(proj, z3asm_bin=tmp_path / "missing", z3disasm_bin=fake_disasm)
            old_path = os.environ.get("PATH", "")
            os.environ["PATH"] = ""
            try:
                await bridge.connect()
                result = await bridge.call_tool("z3disasm_bank", {"bank_start": "0x02"})
            finally:
                os.environ["PATH"] = old_path
        self.assertIn("Error", result)
        self.assertIn("no ROM available", result)

    async def test_write_classification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_asm = tmp_path / "z3asm"
            fake_disasm = tmp_path / "z3disasm"
            _write_stub(fake_asm, "import sys; sys.exit(0)")
            _write_stub(fake_disasm, "import sys; sys.exit(0)")
            proj = RomProject.discover(workspace=tmp_path, env={})
            bridge = Z3asmBridge(proj, z3asm_bin=fake_asm, z3disasm_bin=fake_disasm)
            old_path = os.environ.get("PATH", "")
            os.environ["PATH"] = ""
            try:
                await bridge.connect()
            finally:
                os.environ["PATH"] = old_path
        self.assertTrue(bridge.is_write_tool("z3asm_assemble"))
        self.assertFalse(bridge.is_write_tool("z3asm_lint"))
        self.assertFalse(bridge.is_write_tool("z3disasm_bank"))
        self.assertFalse(bridge.is_write_tool("z3disasm_read_output"))
        self.assertIsNone(bridge.is_write_tool("unknown"))


if __name__ == "__main__":
    unittest.main()
