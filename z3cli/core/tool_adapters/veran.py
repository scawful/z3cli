"""Veran adapter — deep analysis tools.

Veran is the broadest specialist with the largest tool surface (~10).
She handles cross-cutting analysis across dungeon, overworld, ROM,
and debugging domains, including transactional patch-test workflows.
"""

from __future__ import annotations

from z3cli.core.tool_adapters.base import AdapterTool, ToolAdapter


class VeranAdapter(ToolAdapter):
    PROFILE_NAME = "veran"
    WRITE_TOOLS = frozenset({"asm_patch_test", "hook_try"})

    def _define_tools(self) -> list[AdapterTool]:
        return [
            AdapterTool(
                name="asm_patch_test",
                description="Run the full transactional patch-test loop: lint a patch, assemble it against a temp ROM, load an optional scenario, run assertions, and return structured results.",
                parameters={
                    "type": "object",
                    "properties": {
                        "patch_path": {"type": "string", "description": "Path to the ASM patch file."},
                        "rom_path_override": {
                            "type": "string",
                            "description": "Optional ROM path to use instead of the active session ROM.",
                        },
                        "scenario": {
                            "type": "string",
                            "description": "Optional named test state to load before execution.",
                        },
                        "frames": {"type": "integer", "default": 120},
                        "breakpoints": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional breakpoint addresses for the emulator run.",
                        },
                        "assertions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Assertion expressions to evaluate after execution.",
                        },
                        "capture_screenshot": {"type": "boolean", "default": False},
                        "restore_after": {"type": "boolean", "default": True},
                        "include": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional z3asm include directories.",
                        },
                        "define": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional z3asm defines such as FEATURE=1.",
                        },
                        "emit_targets": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional z3asm emit targets forwarded to lint and assemble.",
                        },
                    },
                    "required": ["patch_path"],
                },
            ),
            AdapterTool(
                name="hook_try",
                description="Validate a hook target when reference tooling is available, then assemble and run the hook against a temp ROM in one structured workflow.",
                parameters={
                    "type": "object",
                    "properties": {
                        "patch_path": {"type": "string", "description": "Path to the ASM hook patch file."},
                        "address": {
                            "type": "string",
                            "description": "Hook target address or symbol name to validate before assembly.",
                        },
                        "rom_path_override": {
                            "type": "string",
                            "description": "Optional ROM path to use instead of the active session ROM.",
                        },
                        "scenario": {
                            "type": "string",
                            "description": "Optional named test state to load before execution.",
                        },
                        "frames": {"type": "integer", "default": 120},
                        "breakpoints": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional breakpoint addresses for the emulator run.",
                        },
                        "assertions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Assertion expressions to evaluate after execution.",
                        },
                        "capture_screenshot": {"type": "boolean", "default": False},
                        "restore_after": {"type": "boolean", "default": True},
                        "include": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional z3asm include directories.",
                        },
                        "define": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional z3asm defines such as FEATURE=1.",
                        },
                        "emit_targets": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional z3asm emit targets forwarded to lint and assemble.",
                        },
                    },
                    "required": ["patch_path", "address"],
                },
            ),
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
        if name == "asm_patch_test":
            return await self._call_on("workflow", "asm_patch_test", dict(arguments))

        if name == "hook_try":
            return await self._call_on("workflow", "hook_try", dict(arguments))

        if name == "inspect_room":
            room = arguments["room"]
            desc, objects, sprites, chests, header = await self._call_many_on([
                ("rom", "dungeon_describe_room", {"room": room}),
                ("rom", "dungeon_list_objects", {"room": room}),
                ("rom", "dungeon_list_sprites", {"room": room}),
                ("rom", "dungeon_list_chests", {"room": room}),
                ("rom", "dungeon_room_header", {"room": room}),
            ])
            return (
                f"## Room {room}\n{desc}\n\n## Header\n{header}\n\n"
                f"## Objects\n{objects}\n\n## Sprites\n{sprites}\n\n## Chests\n{chests}"
            )

        if name == "inspect_overworld":
            map_id = arguments["map_id"]
            desc, sprites, warps = await self._call_many_on([
                ("rom", "overworld_describe_map", {"map_id": map_id}),
                ("rom", "overworld_list_sprites", {"map_id": map_id}),
                ("rom", "overworld_list_warps", {"map_id": map_id}),
            ])
            return f"## Overworld {map_id}\n{desc}\n\n## Sprites\n{sprites}\n\n## Warps\n{warps}"

        if name == "read_memory":
            return await self._call_on("emulator", "mesen_memory_read", {
                "address": arguments["address"],
                "length": arguments.get("length", 16),
            })

        if name == "disasm_at":
            return await self._call_on("emulator", "mesen_disasm", {
                "address": arguments["address"],
                "count": arguments.get("lines", 30),
            })

        if name == "lookup_symbol":
            return await self._call_on("symbols", "z3lsp_symbols", {"query": arguments["query"]})

        if name == "search_reference":
            query = arguments["query"]
            msg = await self._call_on("rom", "message_search", {"query": query})
            ref = await self._call_on("reference", "search", {"query": query})
            return f"## In-ROM messages\n{msg}\n\n## Reference / docs\n{ref}"

        if name == "check_diagnostics":
            return await self._call_on("symbols", "z3lsp_diagnostics", {"file": arguments["file"]})

        if name == "rom_doctor":
            return await self._call_on("rom", "rom_doctor", {})

        if name == "read_context":
            return await self._call_on("workspace", "workspace_read", {"path": arguments["path"]})

        if name == "validate_hook":
            # Prefer the z3asm lint path when available — the hook's ASM
            # source file is the canonical place to validate register
            # widths, bank safety, and ABI concerns. Fall back to the
            # reference bridge when only MCP semantics exist.
            file_arg = arguments.get("file")
            if file_arg:
                return await self._call_on("asm", "z3asm_lint", {"patch_path": file_arg})
            args = {"address": arguments["address"]}
            return await self._call_on("reference", "validate_hook", args)

        return await super()._dispatch(name, arguments)
