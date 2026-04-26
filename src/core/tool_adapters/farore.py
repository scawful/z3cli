"""Farore adapter — fast debugging and surgical fix tools.

Farore specializes in quick triage: inspecting rooms, setting
breakpoints, reading state, and checking diagnostics.
"""

from __future__ import annotations

from core.tool_adapters.base import AdapterTool, ToolAdapter


class FaroreAdapter(ToolAdapter):
    PROFILE_NAME = "farore"

    def _define_tools(self) -> list[AdapterTool]:
        return [
            AdapterTool(
                name="scenario_run",
                description="Load a named test scenario, run a short repro loop, and return the structured emulator result envelope.",
                parameters={
                    "type": "object",
                    "properties": {
                        "scenario": {
                            "type": "string",
                            "description": "Named test state to load before running the repro.",
                        },
                        "frames": {
                            "type": "integer",
                            "description": "Frames to execute after loading the scenario.",
                            "default": 60,
                        },
                        "breakpoints": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional breakpoint addresses to watch during the repro.",
                        },
                        "capture_screenshot": {
                            "type": "boolean",
                            "description": "Persist a screenshot artifact after the run.",
                            "default": False,
                        },
                        "restore_after": {
                            "type": "boolean",
                            "description": "Restore emulator state after the repro when possible.",
                            "default": True,
                        },
                    },
                    "required": ["scenario"],
                },
            ),
            AdapterTool(
                name="emu_assert",
                description="Run the emulator from its current state and check bug-focused assertions without assembling a new ROM.",
                parameters={
                    "type": "object",
                    "properties": {
                        "assertions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Assertions to evaluate after the run.",
                        },
                        "frames": {
                            "type": "integer",
                            "description": "Frames to execute before checking assertions.",
                            "default": 30,
                        },
                        "breakpoints": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional breakpoint addresses to watch during the run.",
                        },
                        "capture_screenshot": {
                            "type": "boolean",
                            "description": "Persist a screenshot artifact after the run.",
                            "default": False,
                        },
                        "restore_after": {
                            "type": "boolean",
                            "description": "Restore emulator state after the run when possible.",
                            "default": True,
                        },
                    },
                },
            ),
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
        if name == "scenario_run":
            return await self._call_on("workflow", "scenario_run", dict(arguments))

        if name == "emu_assert":
            return await self._call_on("workflow", "emu_assert", dict(arguments))

        if name == "inspect_room":
            room = arguments["room"]
            desc, objects, sprites, chests = await self._call_many_on([
                ("rom", "dungeon_describe_room", {"room": room}),
                ("rom", "dungeon_list_objects", {"room": room}),
                ("rom", "dungeon_list_sprites", {"room": room}),
                ("rom", "dungeon_list_chests", {"room": room}),
            ])
            return (
                f"## Room {room}\n{desc}\n\n"
                f"## Objects\n{objects}\n\n"
                f"## Sprites\n{sprites}\n\n"
                f"## Chests\n{chests}"
            )

        if name == "set_breakpoint":
            # z3ed mesen-breakpoint takes an --action discriminator.
            bp_type_map = {"execute": "exec", "read": "read", "write": "write"}
            return await self._call_on("emulator", "mesen_breakpoint", {
                "action": "add",
                "address": arguments["address"],
                "type": bp_type_map.get(arguments.get("type", "execute"), "exec"),
            })

        if name == "read_state":
            # mesen-cpu gives registers; mesen-gamestate gives Link position, etc.
            cpu, game = await self._call_many_on([
                ("emulator", "mesen_cpu", {}),
                ("emulator", "mesen_gamestate", {}),
            ])
            return f"## CPU State\n{cpu}\n\n## Game State\n{game}"

        if name == "check_diagnostics":
            return await self._call_on("symbols", "z3lsp_diagnostics", {"file": arguments["file"]})

        if name == "goto_definition":
            return await self._call_on("symbols", "z3lsp_definition", {
                "file": arguments["file"],
                "line": arguments["line"],
                "column": arguments["column"],
            })

        if name == "list_sprites":
            return await self._call_on("rom", "dungeon_list_sprites", {"room": arguments["room"]})

        if name == "read_memory":
            return await self._call_on("emulator", "mesen_memory_read", {
                "address": arguments["address"],
                "length": arguments.get("length", 16),
            })

        return await super()._dispatch(name, arguments)
