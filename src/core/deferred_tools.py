"""Deferred tool schema loading via a tool_search meta-tool.

By default, models receive every tool schema eagerly in every request.
For a large MCP surface (30+ tools, verbose JSON schemas), this costs
meaningful context on each request. DeferredToolBridge wraps an inner
bridge and exposes only a small "core" set plus a ``tool_search`` tool
that reveals matching tool schemas on demand.

Flow:
1. Initial request: ``tools = [tool_search] + core_tools``
2. Model calls ``tool_search(query="read memory")`` — response contains
   JSON schemas for matching tools, AND those tools get added to the
   revealed set.
3. Next request: ``tools = [tool_search] + core_tools + revealed_tools``
4. Model can now call the revealed tools by name directly.

Requires the engine to re-fetch ``get_openai_tools()`` each round so
freshly-revealed tools are visible to the model on subsequent requests.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Iterable

from core.tool_bridge import ToolBridge


TOOL_SEARCH_NAME = "tool_search"


def _tool_search_schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": TOOL_SEARCH_NAME,
            "description": (
                "Search available tools by keyword and reveal their JSON schemas. "
                "Call this before invoking a tool that is not already visible. "
                "Returns matching tool names, descriptions, and their full input "
                "schemas. Matched tools become directly callable in subsequent "
                "responses. Pass multiple space-separated keywords to narrow "
                "the search (e.g. 'read memory breakpoint')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Space-separated keywords. Matched against tool names and descriptions (case-insensitive).",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results (default 8).",
                        "minimum": 1,
                        "maximum": 32,
                    },
                },
                "required": ["query"],
            },
        },
    }


def _tool_matches(tool: dict, terms: list[str]) -> int:
    """Return a match score for how well *tool* matches any search term.

    Higher score = better match. 0 means no match.
    """
    fn = tool.get("function", {})
    name = str(fn.get("name", "")).lower()
    desc = str(fn.get("description", "")).lower()
    score = 0
    for term in terms:
        if not term:
            continue
        if term in name:
            score += 3
        if term in desc:
            score += 1
    return score


class DeferredToolBridge:
    """Wrap a ToolBridge so tool schemas are revealed on demand.

    Attributes:
        _inner: The wrapped bridge with the full tool surface.
        _core: Set of tool names always visible regardless of search.
        _revealed: Tool names revealed via tool_search during this session.
        _catalog_cache: Pre-built catalog of name+description for quick search.
    """

    SEARCH_TOOL_NAME = TOOL_SEARCH_NAME

    def __init__(
        self,
        inner: ToolBridge,
        core: Iterable[str] = (),
    ):
        """
        Args:
            inner: The underlying bridge to wrap.
            core: Tool names that should always be visible without search.
                Useful for high-frequency tools the model shouldn't have to
                rediscover each time (e.g. ``spawn_subagent``, ``read_file``).
        """
        self._inner = inner
        self._core: set[str] = {name for name in core if name}
        self._revealed: set[str] = set()
        self._inner_tools = inner.get_openai_tools()

    @property
    def revealed_tools(self) -> set[str]:
        """Set of tool names currently exposed in the tool list."""
        return self._core | self._revealed

    def reveal(self, names: Iterable[str]) -> list[str]:
        """Manually reveal tools by name. Returns the names that were added."""
        added: list[str] = []
        all_names = {t["function"]["name"] for t in self._inner_tools}
        for name in names:
            if name in all_names and name not in self._revealed and name not in self._core:
                self._revealed.add(name)
                added.append(name)
        return added

    # -- ToolBridge protocol -------------------------------------------------

    def get_openai_tools(self) -> list[dict]:
        """Return tool_search plus the currently-revealed subset."""
        exposed = [_tool_search_schema()]
        visible = self.revealed_tools
        if not visible:
            return exposed
        for tool in self._inner_tools:
            name = tool.get("function", {}).get("name", "")
            if name in visible:
                exposed.append(tool)
        return exposed

    async def call_tool(self, name: str, arguments: dict) -> str:
        if name == TOOL_SEARCH_NAME:
            return self._handle_search(arguments)

        # Only allow calling revealed or core tools
        if name not in self.revealed_tools:
            return (
                f"Error: Tool '{name}' has not been loaded. "
                f"Call `{TOOL_SEARCH_NAME}` with a query matching this tool "
                f"to reveal its schema first."
            )
        return await self._inner.call_tool(name, arguments)

    def get_tool_server(self, tool_name: str) -> str:
        if tool_name == TOOL_SEARCH_NAME:
            return "deferred"
        return self._inner.get_tool_server(tool_name)

    @property
    def tool_count(self) -> int:
        # Expose the full count so status reporting is accurate. The UI
        # should show both "X revealed / Y total" if it cares.
        return 1 + len(self._inner_tools)

    @property
    def server_names(self) -> list[str]:
        return ["deferred", *self._inner.server_names]

    @property
    def server_tool_counts(self) -> dict[str, int]:
        counts = {"deferred": 1}
        counts.update(self._inner.server_tool_counts)
        return counts

    async def close(self) -> None:
        await self._inner.close()

    # -- Search impl ---------------------------------------------------------

    def _handle_search(self, arguments: dict) -> str:
        query = str(arguments.get("query", "")).strip()
        limit = arguments.get("limit", 8)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 8
        limit = max(1, min(limit, 32))

        if not query:
            # Empty query → return the full catalog (names + short descriptions)
            catalog = [
                {
                    "name": tool["function"]["name"],
                    "description": (tool["function"].get("description", "") or "")[:120],
                    "server": self._inner.get_tool_server(tool["function"]["name"]),
                }
                for tool in self._inner_tools
            ]
            return json.dumps({
                "note": "Empty query — returning catalog. Call tool_search with keywords to reveal schemas.",
                "tools": catalog,
            }, indent=2)

        terms = [t.strip().lower() for t in query.split() if t.strip()]
        scored: list[tuple[int, dict]] = []
        for tool in self._inner_tools:
            score = _tool_matches(tool, terms)
            if score > 0:
                scored.append((score, tool))
        scored.sort(key=lambda x: x[0], reverse=True)
        top = [tool for _, tool in scored[:limit]]

        # Reveal matched tools so they become directly callable
        newly_revealed: list[str] = []
        for tool in top:
            name = tool.get("function", {}).get("name", "")
            if name and name not in self.revealed_tools:
                self._revealed.add(name)
                newly_revealed.append(name)

        # Return full schemas (deep-copied to avoid mutation)
        return json.dumps({
            "matched": len(top),
            "revealed": newly_revealed,
            "tools": [deepcopy(tool) for tool in top],
            "hint": (
                "Tools listed above are now callable directly in subsequent "
                "responses. You do not need to call tool_search again for them."
            ),
        }, indent=2)
