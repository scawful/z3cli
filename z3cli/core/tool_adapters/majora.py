"""Majora adapter — architecture and subsystem mapping tools.

Majora specializes in understanding how subsystems connect: finding
usages across files, searching symbols, analyzing ROM structure, and
cross-referencing code.
"""

from __future__ import annotations

from z3cli.core.tool_adapters.base import AdapterTool, ToolAdapter


class MajoraAdapter(ToolAdapter):
    PROFILE_NAME = "majora"

    def _define_tools(self) -> list[AdapterTool]:
        return [
            AdapterTool(
                name="find_usages",
                description="Find all usages of a symbol across Oracle ASM files.",
                parameters={
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "description": "Symbol to search for"},
                    },
                    "required": ["symbol"],
                },
            ),
            AdapterTool(
                name="search_symbols",
                description="Search workspace or document symbols via the language server.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Symbol search query"},
                    },
                    "required": ["query"],
                },
            ),
            AdapterTool(
                name="rom_analysis",
                description="Analyze ROM patches, hotspots, and conflicts.",
                parameters={
                    "type": "object",
                    "properties": {
                        "focus": {
                            "type": "string",
                            "description": "Analysis focus area (e.g. 'patches', 'hotspots', 'conflicts')",
                        },
                    },
                },
            ),
            AdapterTool(
                name="cross_reference",
                description="Look up a symbol and find all its references to map connections.",
                parameters={
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "description": "Symbol to cross-reference"},
                        "file": {"type": "string", "description": "Source file for context"},
                        "line": {"type": "integer", "description": "Line number"},
                        "column": {"type": "integer", "description": "Column number"},
                    },
                    "required": ["symbol"],
                },
            ),
            AdapterTool(
                name="map_subsystem",
                description="Describe a dungeon or overworld area to understand its structural composition.",
                parameters={
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["dungeon", "overworld"],
                            "description": "Area type",
                        },
                        "id": {"type": "string", "description": "Room or map ID (hex)"},
                    },
                    "required": ["type", "id"],
                },
            ),
        ]

    async def _dispatch(self, name: str, arguments: dict) -> str:
        if name == "find_usages":
            return await self._call("find_usages", {"symbol": arguments["symbol"]})

        if name == "search_symbols":
            return await self._call("z3lsp_symbols", {"query": arguments["query"]})

        if name == "rom_analysis":
            args = {}
            if "focus" in arguments:
                args["focus"] = arguments["focus"]
            return await self._call("rom_analysis", args)

        if name == "cross_reference":
            symbol = arguments["symbol"]
            lookup = await self._call("lookup", {"query": symbol})
            usages = await self._call("find_usages", {"symbol": symbol})

            parts = [f"## {symbol}\n{lookup}\n\n## Usages\n{usages}"]

            if "file" in arguments and "line" in arguments and "column" in arguments:
                refs = await self._call("z3lsp_references", {
                    "file": arguments["file"],
                    "line": arguments["line"],
                    "column": arguments["column"],
                })
                parts.append(f"\n\n## LSP References\n{refs}")

            return "".join(parts)

        if name == "map_subsystem":
            area_type = arguments["type"]
            area_id = arguments["id"]
            if area_type == "dungeon":
                desc, objects, sprites = await self._call_many([
                    ("dungeon_describe_room", {"room": area_id}),
                    ("dungeon_list_objects", {"room": area_id}),
                    ("dungeon_list_sprites", {"room": area_id}),
                ])
                return f"## Dungeon Room {area_id}\n{desc}\n\n## Objects\n{objects}\n\n## Sprites\n{sprites}"
            else:
                desc, sprites, warps = await self._call_many([
                    ("overworld_describe_map", {"map_id": area_id}),
                    ("overworld_list_sprites", {"map_id": area_id}),
                    ("overworld_list_warps", {"map_id": area_id}),
                ])
                return f"## Overworld {area_id}\n{desc}\n\n## Sprites\n{sprites}\n\n## Warps\n{warps}"

        return await super()._dispatch(name, arguments)
