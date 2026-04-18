"""Local workspace file-reading bridge for z3cli.

Provides a small, read-only tool for reading files or listing directories under
the active workspace root. This avoids coupling basic source inspection to AFS
allowed-root policy, which may point at a different repository tree.
"""

from __future__ import annotations

import re
from pathlib import Path


class WorkspaceContextBridge:
    """Expose a read-only workspace file/context tool."""

    SERVER_NAME = "workspace"
    DEFAULT_MAX_LINES = 240
    DEFAULT_MAX_CHARS = 24_000
    DEFAULT_MAX_ENTRIES = 120
    _SKIP_PARTS = {".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv"}

    def __init__(self, workspace: Path):
        self.workspace = workspace.expanduser().resolve()

    def get_openai_tools(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "workspace_read",
                    "description": "Read a workspace file or list a directory under the active project root.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Path relative to the active workspace root, or an absolute path within it.",
                            },
                            "max_lines": {
                                "type": "integer",
                                "description": "Maximum number of lines to include when reading a file.",
                                "default": self.DEFAULT_MAX_LINES,
                            },
                        },
                        "required": ["path"],
                    },
                },
            },
        ]

    async def call_tool(self, name: str, arguments: dict) -> str:
        if name != "workspace_read":
            return f"Error: Unknown tool '{name}'"

        raw_path = str(arguments.get("path", "") or "").strip()
        max_lines = int(arguments.get("max_lines", self.DEFAULT_MAX_LINES) or self.DEFAULT_MAX_LINES)

        try:
            target = self._resolve_path(raw_path)
        except ValueError as exc:
            return f"Error calling {name}: {exc}"

        if not target.exists():
            return self._render_missing(raw_path, target)
        if target.is_dir():
            return self._render_directory(target)
        return self._render_file(target, max_lines=max_lines)

    def get_tool_server(self, tool_name: str) -> str:
        return self.SERVER_NAME if tool_name == "workspace_read" else "unknown"

    @property
    def tool_count(self) -> int:
        return 1

    @property
    def server_names(self) -> list[str]:
        return [self.SERVER_NAME]

    @property
    def server_tool_counts(self) -> dict[str, int]:
        return {self.SERVER_NAME: 1}

    async def close(self) -> None:
        return None

    def _resolve_path(self, raw_path: str) -> Path:
        if not raw_path or raw_path in {".", "./"}:
            candidate = self.workspace
        else:
            candidate = Path(raw_path).expanduser()
            if not candidate.is_absolute():
                candidate = self.workspace / candidate
        resolved = candidate.resolve()
        if not resolved.is_relative_to(self.workspace):
            raise ValueError(
                f"path is outside the active workspace: {resolved} (workspace: {self.workspace})",
            )
        return resolved

    def _display_path(self, path: Path) -> str:
        try:
            rel = path.relative_to(self.workspace)
        except ValueError:
            return str(path)
        return "." if str(rel) == "." else str(rel)

    def _render_directory(self, path: Path) -> str:
        entries = sorted(
            path.iterdir(),
            key=lambda item: (item.is_file(), item.name.lower()),
        )
        lines = [f"Directory: {self._display_path(path)}"]
        for entry in entries[: self.DEFAULT_MAX_ENTRIES]:
            label = self._display_path(entry)
            if entry.is_dir():
                label += "/"
            lines.append(f"- {label}")
        remaining = len(entries) - self.DEFAULT_MAX_ENTRIES
        if remaining > 0:
            lines.append(f"... {remaining} more entries omitted")
        return "\n".join(lines)

    def _render_file(self, path: Path, *, max_lines: int) -> str:
        data = path.read_bytes()
        if b"\x00" in data[:4096]:
            return (
                f"Binary file: {self._display_path(path)}\n"
                f"Size: {len(data)} bytes"
            )

        text = data.decode("utf-8", errors="replace")
        lines = text.splitlines()
        rendered: list[str] = []
        char_count = 0
        line_limit = max(1, max_lines)
        width = len(str(min(len(lines), line_limit))) if lines else 1
        for idx, line in enumerate(lines[:line_limit], start=1):
            numbered = f"{idx:>{width}} | {line}"
            if rendered and char_count + len(numbered) + 1 > self.DEFAULT_MAX_CHARS:
                rendered.append("... output truncated")
                break
            rendered.append(numbered)
            char_count += len(numbered) + 1

        if len(lines) > line_limit and (not rendered or rendered[-1] != "... output truncated"):
            rendered.append(f"... {len(lines) - line_limit} more lines omitted")

        header = (
            f"File: {self._display_path(path)}\n"
            f"Lines: {len(lines)}\n"
        )
        return header + "\n".join(rendered)

    def _render_missing(self, raw_path: str, target: Path) -> str:
        lines = [
            f"Path not found in workspace: {raw_path or '.'}",
            f"Workspace root: {self.workspace}",
            f"Resolved path: {target}",
        ]
        suggestions = self._suggest_paths(raw_path)
        if suggestions:
            lines.append("Possible matches:")
            lines.extend(f"- {suggestion}" for suggestion in suggestions)
        return "\n".join(lines)

    def _suggest_paths(self, raw_path: str) -> list[str]:
        needle = Path(raw_path).name.strip()
        if not needle:
            return []
        matches: list[str] = []
        normalized_needle = re.sub(r"[^a-z0-9]+", "", needle.lower())
        for candidate in self.workspace.rglob("*"):
            if any(part in self._SKIP_PARTS for part in candidate.parts):
                continue
            if not candidate.is_file():
                continue
            candidate_name = candidate.name
            normalized_candidate = re.sub(r"[^a-z0-9]+", "", candidate_name.lower())
            if candidate_name != needle and normalized_candidate != normalized_needle:
                continue
            matches.append(self._display_path(candidate))
            if len(matches) >= 8:
                break
        return matches
