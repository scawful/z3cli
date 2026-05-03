"""Lightweight file-backed symbol/reference bridge for Zelda ASM projects.

This is a fallback for environments where the z3lsp binary is not available
(such as a freshly-provisioned WSL training host). It exposes the same small
`z3lsp_*` tool names that Oracle adapters already call, but answers from local
ASM/symbol files with simple text search instead of a live LSP process.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


SERVER_NAME = "asm-symbols"
_SEARCH_EXTENSIONS = {".asm", ".inc", ".s", ".wla", ".mlb", ".sym", ".md", ".txt"}
_SKIP_DIRS = {".git", "build", "build_ai", "build_dbg", "build_rel", "node_modules", ".venv"}
_ADDRESS_RE = re.compile(r"^(?:\$|0x)?([0-9a-fA-F]{4,8})$")


def _normalise_query(value: object) -> str:
    return str(value or "").strip()


def _normalise_address(value: str) -> str:
    raw = value.strip()
    match = _ADDRESS_RE.match(raw)
    if match is None:
        return ""
    digits = match.group(1).upper()
    if len(digits) <= 4:
        return digits.lstrip("0") or "0"
    # Preserve bank/long-address leading zeroes.  Stripping "$00FFD5" to
    # "FFD5" made the fallback bridge match unrelated WRAM symbols such as
    # "$7FFD5C", which then encouraged the model to keep retrying.
    return digits


def _line_matches(line: str, query: str) -> bool:
    if not query:
        return False
    lowered = line.lower()
    q_lower = query.lower()
    if q_lower in lowered:
        return True
    address = _normalise_address(query)
    if address:
        compact = re.sub(r"[^0-9a-fA-F]", "", line).upper()
        if len(address) <= 4:
            return address in compact or address.zfill(4) in compact
        return address in compact
    return False


class AsmSymbolBridge:
    """Read-only grep-like bridge using local ASM and exported symbol files."""

    def __init__(self, workspace: Path, *, max_files: int = 4000) -> None:
        self.workspace = workspace.expanduser().resolve()
        self.max_files = max_files
        self._tools = {
            "z3lsp_symbols",
            "z3lsp_references",
        }

    def get_openai_tools(self) -> list[dict[str, Any]]:
        schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Symbol name, address, or text to search for."},
                "symbol": {"type": "string", "description": "Symbol/reference query alias."},
                "file_path": {"type": "string", "description": "Optional workspace-relative file to search."},
            },
        }
        return [
            {
                "type": "function",
                "function": {
                    "name": "z3lsp_symbols",
                    "description": "Fallback symbol lookup over local Zelda ASM and .mlb/.wla symbol files.",
                    "parameters": schema,
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "z3lsp_references",
                    "description": "Fallback reference search over local Zelda ASM and docs.",
                    "parameters": schema,
                },
            },
        ]

    async def call_tool(self, name: str, arguments: dict) -> str:
        if name not in self._tools:
            return f"Error: Unknown tool '{name}'"
        query = _normalise_query(arguments.get("query") or arguments.get("symbol") or arguments.get("target") or arguments.get("address"))
        if not query:
            return f"No query supplied to {name}."
        file_path = _normalise_query(arguments.get("file_path") or arguments.get("path"))
        hits = self._search(query, file_path=file_path)
        title = "Symbols" if name == "z3lsp_symbols" else "References"
        if not hits:
            return f"## {title}\nNo matches for {query!r} under {self.workspace}."
        lines = [f"## {title} for {query}"]
        lines.extend(hits)
        return "\n".join(lines)

    def _iter_files(self, file_path: str = ""):
        if file_path:
            path = (self.workspace / file_path).resolve()
            if self.workspace in path.parents or path == self.workspace:
                if path.is_file():
                    yield path
            return
        count = 0
        for path in self.workspace.rglob("*"):
            if count >= self.max_files:
                break
            if any(part in _SKIP_DIRS for part in path.parts):
                continue
            if path.is_file() and path.suffix.lower() in _SEARCH_EXTENSIONS:
                count += 1
                yield path

    def _search(self, query: str, *, file_path: str = "", limit: int = 24) -> list[str]:
        hits: list[str] = []
        for path in self._iter_files(file_path):
            try:
                with path.open("r", encoding="utf-8", errors="ignore") as handle:
                    for line_no, line in enumerate(handle, start=1):
                        if not _line_matches(line, query):
                            continue
                        rel = path.relative_to(self.workspace)
                        hits.append(f"- {rel}:{line_no}: {line.strip()}")
                        if len(hits) >= limit:
                            return hits
            except OSError:
                continue
        return hits

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
