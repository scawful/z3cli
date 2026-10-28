"""rom-read/hex-read take PC offsets; symbol commands need the project's .mlb."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.rom_project import RomProject
from protocol.z3ed_bridge import Z3edBridge, lorom_snes_to_pc
from z3ed_fakes import _write_fake_z3ed


def _command(name: str, usage: str) -> dict:
    return {
        "name": name,
        "category": "rom",
        "description": "ROM inspection and validation",
        "usage": usage,
        "available_to_agent": True,
        "requires_rom": True,
        "requires_grpc": False,
        "examples": [],
    }


_SCHEMAS = {
    "commands": [
        _command("rom-read", "rom-read --address <hex> [--length <bytes>]"),
        _command("rom-resolve-address", "rom-resolve-address --address <hex>"),
        _command("dungeon-room-header", "dungeon-room-header --room <room_id> [--format <json|text>]"),
    ]
}


class LoromMappingTests(unittest.TestCase):
    def test_bank_colon_and_flat_forms(self) -> None:
        self.assertEqual(lorom_snes_to_pc("$07:D151"), 0x03D151)
        self.assertEqual(lorom_snes_to_pc("$07D151"), 0x03D151)
        self.assertEqual(lorom_snes_to_pc("0x00FFC0"), 0x007FC0)
        self.assertEqual(lorom_snes_to_pc("$87:D151"), 0x03D151)

    def test_rejects_wram_and_low_half(self) -> None:
        for text in ("$7E0010", "$07:1234"):
            with self.assertRaises(ValueError):
                lorom_snes_to_pc(text)


class Z3edAddressingTests(unittest.IsolatedAsyncioTestCase):
    async def _bridge(self, tmp_path: Path, *, toml: str = "") -> tuple[Z3edBridge, Path]:
        fake = tmp_path / "z3ed"
        _write_fake_z3ed(fake, schemas=_SCHEMAS)
        (tmp_path / "Roms").mkdir(exist_ok=True)
        rom = tmp_path / "Roms" / "oos.sfc"
        rom.write_bytes(b"\0" * 16)
        if toml:
            (tmp_path / "z3dk.toml").write_text(toml)
        proj = RomProject.discover(workspace=tmp_path, rom_path=rom, env={})
        bridge = Z3edBridge(proj, yaze_bin=fake)
        await bridge.connect()
        return bridge, tmp_path / "record.txt"

    async def test_rom_read_schema_explains_pc_offset_and_offers_snes_address(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bridge, _ = await self._bridge(Path(tmp))
            schema = next(t for t in bridge.get_openai_tools() if t["function"]["name"] == "rom_read")
        self.assertIn("PC file offset", schema["function"]["description"])
        self.assertIn("snes_address", schema["function"]["parameters"]["properties"])
        self.assertNotIn("address", schema["function"]["parameters"].get("required", []))

    async def test_snes_address_is_converted_and_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bridge, record = await self._bridge(Path(tmp))
            with patch.dict(os.environ, {"FAKE_Z3ED_RECORD": str(record)}):
                out = await bridge.call_tool("rom_read", {"snes_address": "$07:D151", "length": 4})
                await bridge.call_tool("rom_read", {"address": "07:D151"})
                await bridge.call_tool("rom_read", {"address": "0x7FC0"})
            lines = record.read_text().splitlines()
        self.assertIn("SNES $07:D151 -> PC 0x03D151", out)
        self.assertIn("--address=0x03D151", lines[0])
        self.assertIn("--address=0x03D151", lines[1])
        self.assertIn("--address=0x7FC0", lines[2])

    async def test_off_rom_snes_address_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bridge, _ = await self._bridge(Path(tmp))
            out = await bridge.call_tool("rom_read", {"snes_address": "$7E0010"})
        self.assertTrue(out.startswith("Error:"), out)

    async def test_resolve_address_gets_symbols_from_z3dk_emit(self) -> None:
        toml = '[emit]\nsymbols_mlb = "Roms/oos.mlb"\n'
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "Roms").mkdir()
            (tmp_path / "Roms" / "oos.mlb").write_text("PRG:3d151:Foo\n")
            bridge, record = await self._bridge(tmp_path, toml=toml)
            with patch.dict(os.environ, {"FAKE_Z3ED_RECORD": str(record)}):
                await bridge.call_tool("rom_resolve_address", {"address": "$07D151"})
                await bridge.call_tool("rom_read", {"address": "0x10"})
            lines = record.read_text().splitlines()
            mlb = (tmp_path / "Roms" / "oos.mlb").resolve()
        self.assertIn(f"--symbols={mlb}", lines[0])
        self.assertNotIn("--symbols", lines[1])

    async def test_integer_room_is_sent_as_hex(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bridge, record = await self._bridge(Path(tmp))
            schema = next(
                t for t in bridge.get_openai_tools() if t["function"]["name"] == "dungeon_room_header"
            )
            with patch.dict(os.environ, {"FAKE_Z3ED_RECORD": str(record)}):
                await bridge.call_tool("dungeon_room_header", {"room": 40})
                await bridge.call_tool("dungeon_room_header", {"room": "28"})
                await bridge.call_tool("dungeon_room_header", {"room": "$28"})
            lines = record.read_text().splitlines()
        self.assertIn("decimal", schema["function"]["parameters"]["properties"]["room"]["description"])
        self.assertIn("--room=0x28", lines[0])
        self.assertIn("--room=28", lines[1])
        # z3ed reads "$28" as hex too, so either the raw or the 0x form reaches room 0x28.
        self.assertTrue(any(form in lines[2] for form in ("--room=0x28", "--room=$28")), lines[2])


if __name__ == "__main__":
    unittest.main()
