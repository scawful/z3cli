"""Oracle adapter — read-only grounding tools for the local Oracle 8B/14B models.

The canonical Oracle models repeatedly fail the capability eval on questions
that are one lookup away from a correct answer (specific MMIO register, exact
disassembly symbol, current emulator state). This adapter exposes a small,
purpose-built tool surface so the model reaches for a primitive instead of
hallucinating an address.

All tools here are read-only — write paths stay with the SOTA / full-surface
profiles. The static SNES register table at ``data/snes_registers.json``
covers the registers the r3 grounded eval missed plus a wider set drawn from
``.context/knowledge/snes``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from threading import Lock

from z3cli.core.tool_adapters.base import AdapterTool, ToolAdapter


_REGISTER_DATA_PATH = Path(__file__).parent / "data" / "snes_registers.json"
_HEX_ADDRESS_RE = re.compile(r"^[0-9a-f]{2,8}$")
_ADDRESS_PREFIX_RE = re.compile(r"^(?:\$|0x)", re.IGNORECASE)

_register_cache: dict[str, dict] | None = None
_register_lock = Lock()


def _load_register_table() -> dict[str, dict]:
    """Index the SNES register JSON by both address (hex) and name (uppercase)."""
    global _register_cache
    if _register_cache is not None:
        return _register_cache
    with _register_lock:
        if _register_cache is not None:
            return _register_cache
        raw = json.loads(_REGISTER_DATA_PATH.read_text(encoding="utf-8"))
        index: dict[str, dict] = {}
        for entry in raw.get("registers", []):
            addr = (entry.get("address") or "").upper()
            name = (entry.get("name") or "").upper()
            normalised = {
                "address": f"${addr}" if addr else "",
                "name": name,
                "category": entry.get("category", ""),
                "description": entry.get("description", ""),
                "see_also": entry.get("see_also") or [],
            }
            if addr:
                index[addr] = normalised
            if name:
                index[name] = normalised
        for entry in raw.get("wram_quick_refs", []):
            addr = (entry.get("address") or "").upper()
            name = (entry.get("name") or "").upper()
            normalised = {
                "address": f"${addr}" if addr else "",
                "name": name,
                "category": "wram_mirror",
                "description": entry.get("description", ""),
                "see_also": [],
            }
            if addr:
                index[addr] = normalised
            if name:
                index[name] = normalised
        _register_cache = index
        return _register_cache


def _normalise_register_query(query: str) -> str:
    cleaned = (query or "").strip()
    cleaned = _ADDRESS_PREFIX_RE.sub("", cleaned)
    cleaned = cleaned.lstrip("#")
    return cleaned.upper()


def _format_register_entry(entry: dict) -> str:
    parts = [f"### {entry['name']} ({entry['address']})"]
    if entry.get("category"):
        parts.append(f"- category: {entry['category']}")
    if entry.get("description"):
        parts.append("")
        parts.append(entry["description"])
    if entry.get("see_also"):
        parts.append("")
        parts.append(f"See also: {', '.join(entry['see_also'])}")
    return "\n".join(parts)


class OracleAdapter(ToolAdapter):
    """Compact read-only tool surface for the local Oracle profile."""

    PROFILE_NAME = "oracle"
    WRITE_TOOLS = frozenset()

    def _define_tools(self) -> list[AdapterTool]:
        return [
            AdapterTool(
                name="label_lookup",
                description=(
                    "Look up an ALTTP / Oracle of Secrets symbol or address via the "
                    "language server. Use when the user mentions a hex address (e.g. "
                    "$0088EC) or a symbol name and you need its definition site."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Symbol name or hex address (e.g. 'Underworld_LoadSongBankIfNeeded' or '$0088EC').",
                        },
                    },
                    "required": ["query"],
                },
            ),
            AdapterTool(
                name="grep_disasm",
                description=(
                    "Find every site in the disassembly that defines or references a "
                    "symbol. Use when you need the call sites of a routine or every "
                    "writer to a register."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Symbol or hex pattern to search for.",
                        },
                    },
                    "required": ["query"],
                },
            ),
            AdapterTool(
                name="rom_read",
                description=(
                    "Read raw bytes from the running Mesen process at a CPU address. "
                    "Use when you need to confirm the exact byte sequence at a hook "
                    "site, or what value a WRAM mirror currently holds."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "address": {
                            "type": "string",
                            "description": "CPU address as hex (e.g. '$00A000' or '0x7E0013').",
                        },
                        "length": {
                            "type": "integer",
                            "description": "Number of bytes to read (1-256).",
                            "default": 16,
                            "minimum": 1,
                            "maximum": 256,
                        },
                    },
                    "required": ["address"],
                },
            ),
            AdapterTool(
                name="disasm_at",
                description=(
                    "Disassemble bytes at a CPU address into 65816 mnemonics via "
                    "Mesen. Use when reasoning about width contracts, REP/SEP state, "
                    "or JSR/JSL pairing."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "address": {
                            "type": "string",
                            "description": "Hex CPU address.",
                        },
                        "count": {
                            "type": "integer",
                            "description": "Number of instructions to disassemble (1-64).",
                            "default": 16,
                            "minimum": 1,
                            "maximum": 64,
                        },
                    },
                    "required": ["address"],
                },
            ),
            AdapterTool(
                name="cpu_state",
                description=(
                    "Snapshot the running CPU registers and game state via Mesen. "
                    "Use when triaging a crash, blackout, or width-mismatch — never "
                    "guess A/X/Y widths from prose, ask the emulator."
                ),
                parameters={
                    "type": "object",
                    "properties": {},
                },
            ),
            AdapterTool(
                name="register_doc",
                description=(
                    "Look up an SNES MMIO register by hex address or shorthand name "
                    "(e.g. '$420B', '420B', or 'MDMAEN'). Returns category, purpose, "
                    "and bit fields where known. Use this BEFORE answering any "
                    "question about a $21xx, $42xx, or $43xx address."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Register address or name.",
                        },
                    },
                    "required": ["query"],
                },
            ),
        ]

    async def _dispatch(self, name: str, arguments: dict) -> str:
        if name == "label_lookup":
            return await self._call_on(
                "symbols", "z3lsp_symbols", {"query": arguments["query"]}
            )

        if name == "grep_disasm":
            query = arguments["query"]
            symbols, references = await self._call_many_on([
                ("symbols", "z3lsp_symbols", {"query": query}),
                ("symbols", "z3lsp_references", {"symbol": query}),
            ])
            return f"## Symbols\n{symbols}\n\n## References\n{references}"

        if name == "rom_read":
            length = int(arguments.get("length") or 16)
            return await self._call_on(
                "emulator",
                "mesen_memory_read",
                {"address": arguments["address"], "length": length},
            )

        if name == "disasm_at":
            count = int(arguments.get("count") or 16)
            return await self._call_on(
                "emulator",
                "mesen_disasm",
                {"address": arguments["address"], "count": count},
            )

        if name == "cpu_state":
            cpu, gamestate = await self._call_many_on([
                ("emulator", "mesen_cpu", {}),
                ("emulator", "mesen_gamestate", {}),
            ])
            return f"## CPU\n{cpu}\n\n## Game state\n{gamestate}"

        if name == "register_doc":
            return self._lookup_register(arguments.get("query") or "")

        return await super()._dispatch(name, arguments)

    @staticmethod
    def _lookup_register(query: str) -> str:
        normalised = _normalise_register_query(query)
        if not normalised:
            return "Error: register_doc requires a non-empty query."
        table = _load_register_table()
        entry = table.get(normalised)
        if entry is None:
            return (
                f"Unknown register '{query}'. Try a hex address like '$420B' or a "
                f"shorthand name like 'MDMAEN'. Coverage focuses on $21xx PPU, "
                f"$42xx CPU control, and $43xx DMA per-channel registers."
            )
        return _format_register_entry(entry)
