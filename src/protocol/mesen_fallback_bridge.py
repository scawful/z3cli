"""Fallback Mesen-style tool bridge for hosts without z3ed/Mesen wiring."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.rom_project import RomProject


SERVER_NAME = "mesen-fallback"


def _parse_address(value: object) -> int | None:
    text = str(value or "").strip().lower().replace("$", "0x")
    if not text:
        return None
    try:
        return int(text, 16) if text.startswith("0x") else int(text, 16)
    except ValueError:
        return None


def _lorom_pc(address: int) -> int | None:
    bank = (address >> 16) & 0xFF
    offset = address & 0xFFFF
    if offset < 0x8000:
        return None
    return ((bank & 0x7F) * 0x8000) + (offset - 0x8000)


def _hex_address(address: int | None) -> str:
    return f"${address:06X}" if address is not None else "<invalid>"


class MesenFallbackBridge:
    """Expose Mesen-compatible read tools with clear degraded behavior.

    When a live Mesen2 socket is unavailable this bridge still prevents Oracle
    from seeing "unknown tool" and can read static ROM bytes for LoROM CPU
    addresses. WRAM/CPU-state requests report the missing emulator explicitly.
    """

    def __init__(self, project: RomProject) -> None:
        self.project = project
        self._tools = {"mesen_memory_read", "mesen_disasm", "mesen_cpu", "mesen_gamestate"}

    def get_openai_tools(self) -> list[dict[str, Any]]:
        return [
            self._tool("mesen_memory_read", {"address": "string", "length": "integer", "size": "integer"}),
            self._tool("mesen_disasm", {"address": "string", "count": "integer", "lines": "integer"}),
            self._tool("mesen_cpu", {}),
            self._tool("mesen_gamestate", {}),
        ]

    @staticmethod
    def _tool(name: str, props: dict[str, str]) -> dict[str, Any]:
        properties: dict[str, Any] = {}
        for key, kind in props.items():
            properties[key] = {"type": kind}
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": "Fallback Mesen2-compatible read-only diagnostic tool.",
                "parameters": {"type": "object", "properties": properties},
            },
        }

    async def call_tool(self, name: str, arguments: dict) -> str:
        if name not in self._tools:
            return f"Error: Unknown tool '{name}'"
        if name == "mesen_memory_read":
            return self._memory_read(arguments)
        if name == "mesen_disasm":
            return self._disasm(arguments)
        if name == "mesen_cpu":
            return self._unavailable("CPU state requires a live Mesen2 socket")
        if name == "mesen_gamestate":
            return self._unavailable("Game state requires a live Mesen2 socket")
        return f"Error: Unknown tool '{name}'"

    def _unavailable(self, reason: str) -> str:
        socket = self.project.mesen_socket or "not detected"
        return f"Mesen2 unavailable: {reason}. MESEN2_SOCKET_PATH={socket}."

    def _memory_read(self, arguments: dict) -> str:
        address = _parse_address(arguments.get("address"))
        length = int(arguments.get("length") or arguments.get("size") or 16)
        length = max(1, min(length, 256))
        if address is None:
            return "Mesen2 unavailable: invalid address for mesen_memory_read."
        if 0x7E0000 <= address <= 0x7FFFFF:
            return self._unavailable(f"WRAM read at {_hex_address(address)} length {length}")
        pc = _lorom_pc(address)
        rom = self.project.preferred_mesen_rom_path() or self.project.rom_path
        if pc is None or rom is None or not Path(rom).exists():
            return self._unavailable(f"live memory read at {_hex_address(address)} length {length}")
        try:
            data = Path(rom).read_bytes()[pc:pc + length]
        except OSError as exc:
            return f"Mesen2 unavailable: ROM byte fallback failed for {_hex_address(address)}: {exc}"
        hex_bytes = " ".join(f"{b:02X}" for b in data)
        return f"Static ROM bytes at {_hex_address(address)} (pc=0x{pc:06X}, length={len(data)}): {hex_bytes}"

    def _disasm(self, arguments: dict) -> str:
        address = _parse_address(arguments.get("address"))
        count = int(arguments.get("count") or arguments.get("lines") or 16)
        byte_result = self._memory_read({"address": arguments.get("address"), "length": max(1, min(count * 4, 64))})
        return (
            f"Disassembly unavailable without a live Mesen2 disassembler for {_hex_address(address)} "
            f"({count} instructions requested). Static byte evidence: {byte_result}"
        )

    def get_tool_server(self, tool_name: str) -> str:
        return SERVER_NAME if tool_name in self._tools else "unknown"

    @property
    def tool_count(self) -> int:
        return len(self._tools)

    @property
    def server_names(self) -> list[str]:
        return [SERVER_NAME]

    @property
    def server_tool_counts(self) -> dict[str, int]:
        return {SERVER_NAME: len(self._tools)}

    async def close(self) -> None:
        return None
