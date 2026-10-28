"""Older z3ed rom-write/hex-write report success without saving; the bridge says so."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.rom_project import RomProject
from protocol.z3ed_bridge import Z3edBridge
from z3ed_fakes import _write_fake_z3ed


def _command(name: str) -> dict:
    return {
        "name": name, "category": "rom", "description": name,
        "usage": f"{name} --rom <sfc>", "requires_rom": True, "requires_grpc": False, "examples": [],
    }


class UnsavedWriteNoteTests(unittest.IsolatedAsyncioTestCase):
    async def _results(self, response: str) -> dict[str, str]:
        schemas = {"commands": [_command("rom-write"), _command("hex-write"), _command("rom-info")]}
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_z3ed = tmp_path / "z3ed"
            _write_fake_z3ed(fake_z3ed, schemas=schemas, response=response)
            rom = tmp_path / "rom.sfc"
            rom.write_bytes(b"\x00" * 32)
            bridge = Z3edBridge(RomProject.discover(workspace=tmp_path, rom_path=rom, env={}), yaze_bin=fake_z3ed)
            await bridge.connect()
            return {tool: await bridge.call_tool(tool, {}) for tool in ("rom_write", "hex_write", "rom_info")}

    async def test_note_on_unsaved_writer_output_only(self) -> None:
        results = await self._results('{"status":"success","bytes_written":1}')
        for tool in ("rom_write", "hex_write"):
            self.assertIn('"bytes_written":1', results[tool])
            self.assertIn("without saving the ROM", results[tool])
        self.assertNotIn("[z3cli]", results["rom_info"])

    async def test_no_note_when_z3ed_reports_the_save(self) -> None:
        results = await self._results('{"mode":"write","save_status":"saved","verified_reload":true}')
        for tool in ("rom_write", "hex_write"):
            self.assertNotIn("[z3cli]", results[tool])

if __name__ == "__main__":
    unittest.main()
