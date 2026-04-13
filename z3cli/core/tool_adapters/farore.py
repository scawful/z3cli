"""Farore adapter — fast debugging and surgical fix tools.

Farore specializes in quick triage: inspecting rooms, setting
breakpoints, reading state, and checking diagnostics.
"""

from __future__ import annotations

from z3cli.core.tool_adapters.base import AdapterTool, ToolAdapter


class FaroreAdapter(ToolAdapter):
    PROFILE_NAME = "farore"

    def _define_tools(self) -> list[AdapterTool]:
        return [
            AdapterTool(
                name="inspect_room",
                description="Inspect a dungeon room: description, objects, sprites, and chests in one call.",
                parameters={
                    "type": "object",
                    "properties": {
                        "room": {
                            "type": "string",
                            "description": "Room ID (hex, e.g. '0x45')",
                        },
                    },
                    "required": ["room"],
                },
            ),
            AdapterTool(
                name="set_breakpoint",
                description="Set a breakpoint at an address.",
                parameters={
                    "type": "object",
                    "properties": {
                        "address": {
                            "type": "string",
                            "description": "Address to break at",
                        },
                        "type": {
                            "type": "string",
                            "enum": ["execute", "read", "write"],
                            "default": "execute",
                        },
                    },
                    "required": ["address"],
                },
            ),
            AdapterTool(
                name="read_state",
                description="Get current CPU registers, game state (Link position, health, mode), and debug status.",
                parameters={"type": "object", "properties": {}},
            ),
            AdapterTool(
                name="check_diagnostics",
                description="Get assembler and lint diagnostics for an ASM source file.",
                parameters={
                    "type": "object",
                    "properties": {
                        "file": {
                            "type": "string",
                            "description": "Path to the ASM file to check",
                        },
                    },
                    "required": ["file"],
                },
            ),
            AdapterTool(
                name="goto_definition",
                description="Jump to the definition of a symbol in the ASM source.",
                parameters={
                    "type": "object",
                    "properties": {
                        "file": {"type": "string", "description": "Source file path"},
                        "line": {"type": "integer", "description": "Line number (1-based)"},
                        "column": {"type": "integer", "description": "Column number (1-based)"},
                    },
                    "required": ["file", "line", "column"],
                },
            ),
            AdapterTool(
                name="list_sprites",
                description="List all sprites in a dungeon room.",
                parameters={
                    "type": "object",
                    "properties": {
                        "room": {
                            "type": "string",
                            "description": "Room ID (hex, e.g. '0x45')",
                        },
                    },
                    "required": ["room"],
                },
            ),
            AdapterTool(
                name="read_memory",
                description="Read bytes from emulator memory.",
                parameters={
                    "type": "object",
                    "properties": {
                        "address": {"type": "string", "description": "Memory address"},
                        "length": {"type": "integer", "default": 16},
                    },
                    "required": ["address"],
                },
            ),
        ]

    async def _dispatch(self, name: str, arguments: dict) -> str:
        if name == "inspect_room":
            room = arguments["room"]
            desc, objects, sprites, chests = await self._call_many([
                ("dungeon_describe_room", {"room": room}),
                ("dungeon_list_objects", {"room": room}),
                ("dungeon_list_sprites", {"room": room}),
                ("dungeon_list_chests", {"room": room}),
            ])
            return (
                f"## Room {room}\n{desc}\n\n"
                f"## Objects\n{objects}\n\n"
                f"## Sprites\n{sprites}\n\n"
                f"## Chests\n{chests}"
            )

        if name == "set_breakpoint":
            return await self._call("add_breakpoint", {
                "address": arguments["address"],
                "type": arguments.get("type", "execute"),
            })

        if name == "read_state":
            state, game = await self._call_many([
                ("emu_get_state", {}),
                ("get_game_state", {}),
            ])
            return f"## CPU State\n{state}\n\n## Game State\n{game}"

        if name == "check_diagnostics":
            return await self._call("z3lsp_diagnostics", {"file": arguments["file"]})

        if name == "goto_definition":
            return await self._call("z3lsp_definition", {
                "file": arguments["file"],
                "line": arguments["line"],
                "column": arguments["column"],
            })

        if name == "list_sprites":
            return await self._call("dungeon_list_sprites", {"room": arguments["room"]})

        if name == "read_memory":
            return await self._call("emu_read_memory", {
                "address": arguments["address"],
                "length": arguments.get("length", 16),
            })

        return await super()._dispatch(name, arguments)
