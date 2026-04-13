"""Veran adapter — deep analysis tools.

Veran is the broadest specialist with the largest tool surface (~10).
She handles cross-cutting analysis across dungeon, overworld, ROM,
and debugging domains.
"""

from __future__ import annotations

from z3cli.core.tool_adapters.base import AdapterTool, ToolAdapter


class VeranAdapter(ToolAdapter):
    PROFILE_NAME = "veran"

    def _define_tools(self) -> list[AdapterTool]:
        return [
            AdapterTool(
                name="inspect_room",
                description="Full dungeon room inspection: description, objects, sprites, chests, and header.",
                parameters={
                    "type": "object",
                    "properties": {
                        "room": {"type": "string", "description": "Room ID (hex)"},
                    },
                    "required": ["room"],
                },
            ),
            AdapterTool(
                name="inspect_overworld",
                description="Describe an overworld map area including sprites and warps.",
                parameters={
                    "type": "object",
                    "properties": {
                        "map_id": {"type": "string", "description": "Overworld map ID (hex)"},
                    },
                    "required": ["map_id"],
                },
            ),
            AdapterTool(
                name="read_memory",
                description="Read bytes from emulator memory.",
                parameters={
                    "type": "object",
                    "properties": {
                        "address": {"type": "string"},
                        "length": {"type": "integer", "default": 16},
                    },
                    "required": ["address"],
                },
            ),
            AdapterTool(
                name="disasm_at",
                description="Disassemble code at an address.",
                parameters={
                    "type": "object",
                    "properties": {
                        "address": {"type": "string"},
                        "lines": {"type": "integer", "default": 30},
                    },
                    "required": ["address"],
                },
            ),
            AdapterTool(
                name="lookup_symbol",
                description="Look up a symbol, address, or label in the disassembly.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                    },
                    "required": ["query"],
                },
            ),
            AdapterTool(
                name="search_reference",
                description="Search across disassembly, Oracle ASM, and RAM docs.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                    },
                    "required": ["query"],
                },
            ),
            AdapterTool(
                name="check_diagnostics",
                description="Get assembler and lint diagnostics for a source file.",
                parameters={
                    "type": "object",
                    "properties": {
                        "file": {"type": "string"},
                    },
                    "required": ["file"],
                },
            ),
            AdapterTool(
                name="rom_doctor",
                description="Run comprehensive ROM health checks.",
                parameters={"type": "object", "properties": {}},
            ),
            AdapterTool(
                name="read_context",
                description="Read a file from the project context.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                    },
                    "required": ["path"],
                },
            ),
            AdapterTool(
                name="validate_hook",
                description="Validate an ASM hook for safety (address, registers, RTL).",
                parameters={
                    "type": "object",
                    "properties": {
                        "address": {"type": "string", "description": "Hook target address"},
                        "file": {"type": "string", "description": "ASM file containing the hook"},
                    },
                    "required": ["address"],
                },
            ),
        ]

    async def _dispatch(self, name: str, arguments: dict) -> str:
        if name == "inspect_room":
            room = arguments["room"]
            desc, objects, sprites, chests, header = await self._call_many([
                ("dungeon_describe_room", {"room": room}),
                ("dungeon_list_objects", {"room": room}),
                ("dungeon_list_sprites", {"room": room}),
                ("dungeon_list_chests", {"room": room}),
                ("dungeon_room_header", {"room": room}),
            ])
            return (
                f"## Room {room}\n{desc}\n\n## Header\n{header}\n\n"
                f"## Objects\n{objects}\n\n## Sprites\n{sprites}\n\n## Chests\n{chests}"
            )

        if name == "inspect_overworld":
            map_id = arguments["map_id"]
            desc, sprites, warps = await self._call_many([
                ("overworld_describe_map", {"map_id": map_id}),
                ("overworld_list_sprites", {"map_id": map_id}),
                ("overworld_list_warps", {"map_id": map_id}),
            ])
            return f"## Overworld {map_id}\n{desc}\n\n## Sprites\n{sprites}\n\n## Warps\n{warps}"

        if name == "read_memory":
            return await self._call("emu_read_memory", {
                "address": arguments["address"],
                "length": arguments.get("length", 16),
            })

        if name == "disasm_at":
            return await self._call("get_disassembly", {
                "address": arguments["address"],
                "lines": arguments.get("lines", 30),
            })

        if name == "lookup_symbol":
            return await self._call("lookup", {"query": arguments["query"]})

        if name == "search_reference":
            return await self._call("search", {"query": arguments["query"]})

        if name == "check_diagnostics":
            return await self._call("z3lsp_diagnostics", {"file": arguments["file"]})

        if name == "rom_doctor":
            return await self._call("rom_doctor", {})

        if name == "read_context":
            return await self._call("context.read", {"path": arguments["path"]})

        if name == "validate_hook":
            args = {"address": arguments["address"]}
            if "file" in arguments:
                args["file"] = arguments["file"]
            return await self._call("validate_hook", args)

        return await super()._dispatch(name, arguments)
