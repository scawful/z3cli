"""Tests for the RomProject session-scoped coordinator."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from core.rom_project import RomProject


class DiscoveryTests(unittest.TestCase):
    def test_explicit_overrides_win(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ws = tmp_path / "ws"
            ws.mkdir()
            rom = tmp_path / "custom.sfc"
            rom.write_bytes(b"\x00" * 1024)
            proj = RomProject.discover(
                workspace=ws,
                rom_path=rom,
                env={},
            )
        self.assertEqual(proj.workspace, ws.resolve())
        self.assertEqual(proj.rom_path, rom.resolve())

    def test_env_var_sets_rom(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ws = tmp_path / "ws"
            ws.mkdir()
            rom = tmp_path / "envrom.sfc"
            rom.write_bytes(b"\x00")
            proj = RomProject.discover(
                workspace=ws,
                env={"Z3CLI_ROM": str(rom)},
            )
        self.assertEqual(proj.rom_path, rom.resolve())

    def test_workspace_z3dk_toml_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "z3dk.toml").write_text("[project]\nname='x'\n")
            proj = RomProject.discover(
                workspace=tmp_path,
                env={},
            )
        self.assertIsNotNone(proj.z3dk_toml)
        assert proj.z3dk_toml is not None
        self.assertEqual(proj.z3dk_toml.name, "z3dk.toml")

    def test_symbols_mlb_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            build = tmp_path / "build"
            build.mkdir()
            mlb = build / "symbols.mlb"
            mlb.write_text("; symbols\n")
            proj = RomProject.discover(workspace=tmp_path, env={})
        self.assertEqual(proj.symbols_mlb, mlb.resolve())

    def test_mesen_socket_from_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            fake_sock_path = "/tmp/fake-mesen.sock"
            proj = RomProject.discover(
                workspace=ws,
                env={"MESEN2_SOCKET_PATH": fake_sock_path},
            )
        self.assertEqual(proj.mesen_socket, fake_sock_path)

    def test_diagnostics_dict_is_serializable(self) -> None:
        import json as _json
        with tempfile.TemporaryDirectory() as tmp:
            proj = RomProject.discover(workspace=Path(tmp), env={})
            payload = _json.dumps(proj.diagnostics())
        self.assertIn("workspace", payload)


class ChecksumTests(unittest.TestCase):
    def test_sha256_matches_file_contents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            rom = tmp_path / "rom.sfc"
            data = b"zelda3" * 1024
            rom.write_bytes(data)
            proj = RomProject.discover(
                workspace=tmp_path, rom_path=rom, env={},
            )
            expected = hashlib.sha256(data).hexdigest()
            self.assertEqual(proj.compute_rom_sha256(), expected)

    def test_sha256_none_when_rom_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proj = RomProject.discover(
                workspace=Path(tmp),
                rom_path=Path(tmp) / "missing.sfc",
                env={},
            )
        self.assertIsNone(proj.compute_rom_sha256())


class CloneTests(unittest.TestCase):
    def test_with_rom_path_returns_updated_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            rom_a = tmp_path / "a.sfc"
            rom_b = tmp_path / "b.sfc"
            rom_a.write_bytes(b"\x00")
            rom_b.write_bytes(b"\x01")
            proj = RomProject.discover(
                workspace=tmp_path,
                rom_path=rom_a,
                env={},
            )
            swapped = proj.with_rom_path(rom_b)

        self.assertEqual(proj.rom_path, rom_a.resolve())
        self.assertEqual(swapped.rom_path, rom_b.resolve())
        self.assertEqual(swapped.workspace, proj.workspace)

    def test_preferred_mesen_rom_path_prefers_patched_sibling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            rom = tmp_path / "oos168.sfc"
            patched = tmp_path / "oos168x.sfc"
            rom.write_bytes(b"\x00")
            patched.write_bytes(b"\x01")
            proj = RomProject.discover(
                workspace=tmp_path,
                rom_path=rom,
                env={},
            )
            self.assertEqual(proj.preferred_mesen_rom_path(), patched.resolve())

    def test_with_mesen_socket_returns_updated_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            proj = RomProject.discover(
                workspace=tmp_path,
                env={},
            )
            updated = proj.with_mesen_socket("/tmp/mesen2-z3cli.sock")

        self.assertIsNone(proj.mesen_socket)
        self.assertEqual(updated.mesen_socket, "/tmp/mesen2-z3cli.sock")


if __name__ == "__main__":
    unittest.main()
