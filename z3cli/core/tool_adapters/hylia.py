"""Hylia adapter — lore, history, and reference lookup tools.

Hylia specializes in reading documentation, looking up references,
and retrieving context. All tools are read-only.
"""

from __future__ import annotations

from z3cli.core.tool_adapters.base import AdapterTool, ToolAdapter


class HyliaAdapter(ToolAdapter):
    PROFILE_NAME = "hylia"

    def _define_tools(self) -> list[AdapterTool]:
        return [
            AdapterTool(
                name="lookup_reference",
                description="Look up a symbol, address, or label in the ALTTP disassembly and find related documentation.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Symbol name, hex address, or keyword to look up",
                        },
                    },
                    "required": ["query"],
                },
            ),
            AdapterTool(
                name="search_history",
                description="Search across disassembly, Oracle ASM, and documentation for historical references.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query",
                        },
                    },
                    "required": ["query"],
                },
            ),
            AdapterTool(
                name="consult_docs",
                description="Read core SNES/ALTTP reference documentation.",
                parameters={
                    "type": "object",
                    "properties": {
                        "topic": {
                            "type": "string",
                            "enum": ["memory_map", "rom_map", "snes_hardware", "ram"],
                            "description": "Reference topic",
                        },
                    },
                    "required": ["topic"],
                },
            ),
            AdapterTool(
                name="read_context",
                description="Read a file from the project context or memory.",
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
        ]

    async def _dispatch(self, name: str, arguments: dict) -> str:
        if name == "lookup_reference":
            query = arguments["query"]
            lookup = await self._call("lookup", {"query": query})
            search = await self._call("search", {"query": query})
            return f"## Lookup: {query}\n{lookup}\n\n## Related\n{search}"

        if name == "search_history":
            return await self._call("search", {"query": arguments["query"]})

        if name == "consult_docs":
            return await self._call("consult_reference", {"topic": arguments["topic"]})

        if name == "read_context":
            return await self._call("context.read", {"path": arguments["path"]})

        return await super()._dispatch(name, arguments)
