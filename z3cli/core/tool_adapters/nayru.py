"""Nayru adapter — explanation, teaching, and reference tools.

Nayru specializes in explaining code, looking up references, and
describing ROM structures. All tools are read-only.
"""

from __future__ import annotations

from z3cli.core.tool_adapters.base import AdapterTool, ToolAdapter


class NayruAdapter(ToolAdapter):
    PROFILE_NAME = "nayru"

    def _define_tools(self) -> list[AdapterTool]:
        return [
            AdapterTool(
                name="explain_routine",
                description="Look up a symbol or address and return detailed reference information including disassembly context.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Symbol name, hex address, or RAM label to explain",
                        },
                    },
                    "required": ["query"],
                },
            ),
            AdapterTool(
                name="search_reference",
                description="Search across the ALTTP disassembly, Oracle ASM, and RAM documentation.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query (symbol, keyword, or pattern)",
                        },
                    },
                    "required": ["query"],
                },
            ),
            AdapterTool(
                name="describe_room",
                description="Get a detailed description of a dungeon room including objects, sprites, and layout.",
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
                name="read_context",
                description="Read a file from the project context.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "File path relative to context root",
                        },
                    },
                    "required": ["path"],
                },
            ),
            AdapterTool(
                name="search_memory",
                description="Search durable memory entries by keyword.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Keyword to search for in memory",
                        },
                    },
                    "required": ["query"],
                },
            ),
            AdapterTool(
                name="consult_docs",
                description="Read core reference documentation (memory map, ROM map, SNES hardware, RAM layout).",
                parameters={
                    "type": "object",
                    "properties": {
                        "topic": {
                            "type": "string",
                            "enum": ["memory_map", "rom_map", "snes_hardware", "ram"],
                            "description": "Reference topic to consult",
                        },
                    },
                    "required": ["topic"],
                },
            ),
        ]

    async def _dispatch(self, name: str, arguments: dict) -> str:
        if name == "explain_routine":
            query = arguments["query"]
            lookup_result = await self._call("lookup", {"query": query})
            usages = await self._call("find_usages", {"symbol": query})
            return f"## Reference: {query}\n{lookup_result}\n\n## Usages\n{usages}"

        if name == "search_reference":
            return await self._call("search", {"query": arguments["query"]})

        if name == "describe_room":
            room = arguments["room"]
            desc, objects, sprites = await self._call_many([
                ("dungeon_describe_room", {"room": room}),
                ("dungeon_list_objects", {"room": room}),
                ("dungeon_list_sprites", {"room": room}),
            ])
            return f"## Room {room}\n{desc}\n\n## Objects\n{objects}\n\n## Sprites\n{sprites}"

        if name == "read_context":
            return await self._call("context.read", {"path": arguments["path"]})

        if name == "search_memory":
            return await self._call("memory.search", {"query": arguments["query"]})

        if name == "consult_docs":
            return await self._call("consult_reference", {"topic": arguments["topic"]})

        return await super()._dispatch(name, arguments)
