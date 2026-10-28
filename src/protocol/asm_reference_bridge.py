"""Read-only lookups over the vanilla ALTTP disassembly (usdasm) and the Oracle ASM tree.

z3lsp indexes only the active workspace, so vanilla routines such as
``TileDetect_MainHandler`` or an address like ``$07:D151`` were unreachable
from z3cli. usdasm lays code out as ``bank_BB.asm`` with one ``#_BBAAAA:`` line
per instruction, top-level ``Name:`` routines, local ``.name`` labels, and WRAM
names as ``NAME = $7E0010`` in ``wram.asm``.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
from pathlib import Path
from typing import Any

from protocol.asar_namespace import namespace_note, strip_namespace

SERVER_NAME = "asm-reference"
DEFAULT_USDASM = Path.home() / "src/hobby/usdasm"
_ROUTINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):")
_LOCAL_RE = re.compile(r"^(\.[A-Za-z0-9_]+)\b")
_ADDRESS_RE = re.compile(r"^(?:\$|0x)?([0-9A-Fa-f]{2}):?([0-9A-Fa-f]{4})$")
_SHORT_ADDRESS_RE = re.compile(r"^(?:\$|0x)?([0-9A-Fa-f]{4})$")
_DATA_FILES = ("wram.asm", "sram.asm", "registers.asm", "symbols_apu.asm")
_MAX_GREP_HITS = 40


def _usdasm_root() -> Path:
    return Path(os.environ.get("Z3CLI_USDASM", DEFAULT_USDASM)).expanduser()


def _read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def _block_start(lines: list[str], index: int, limit: int = 8) -> int:
    """First line of the blank-separated group holding ``index``; its comments describe the group."""
    start = index
    while start > 0 and index - start < limit and lines[start - 1].strip():
        start -= 1
    return start


class AsmReferenceBridge:
    """``vanilla_lookup`` and ``asm_grep``; never writes."""

    def __init__(self, workspace: Path, usdasm: Path | None = None) -> None:
        self.workspace = workspace.expanduser().resolve()
        self.usdasm = (usdasm or _usdasm_root()).expanduser().resolve()
        self._tools = {"vanilla_lookup", "asm_grep"} if self.usdasm.is_dir() else set()

    def get_openai_tools(self) -> list[dict[str, Any]]:
        tools = []
        if "vanilla_lookup" in self._tools:
            tools.append({"type": "function", "function": {
                "name": "vanilla_lookup",
                "description": (
                    "Look up a vanilla ALTTP address or name in the usdasm disassembly. "
                    "A ROM address ($07:D151, $07D151, 07D151) returns the instruction there, "
                    "its enclosing routine and local label, and nearby lines. A WRAM/SRAM "
                    "address ($7E0010) or a name (TileDetect_MainHandler, MODE) returns its "
                    "definition. Use for vanilla code a hook patches; Oracle symbols are in "
                    "z3lsp_symbols."),
                "parameters": {"type": "object", "properties": {
                    "query": {"type": "string", "description": "SNES address or label/define name."},
                    "context": {"type": "integer", "description": "Lines of context each side (default 6, max 30)."},
                }, "required": ["query"]},
            }})
        if "asm_grep" in self._tools:
            tools.append({"type": "function", "function": {
                "name": "asm_grep",
                "description": (
                    "Fixed-string search of ASM source: scope 'oracle' (this project, hooks are "
                    "`org $BBAAAA` lines), 'vanilla' (usdasm), or 'both'. Returns path:line: text."),
                "parameters": {"type": "object", "properties": {
                    "query": {"type": "string", "description": "Text to find (case-insensitive unless it has capitals)."},
                    "scope": {"type": "string", "enum": ["oracle", "vanilla", "both"], "default": "both"},
                }, "required": ["query"]},
            }})
        return tools

    def get_tool_server(self, tool_name: str) -> str:
        return SERVER_NAME if tool_name in self._tools else "unknown"

    def is_write_tool(self, tool_name: str) -> bool | None:
        return False if tool_name in self._tools else None

    @property
    def tool_count(self) -> int:
        return len(self._tools)

    @property
    def server_names(self) -> list[str]:
        return [SERVER_NAME] if self._tools else []

    @property
    def server_tool_counts(self) -> dict[str, int]:
        return {SERVER_NAME: len(self._tools)} if self._tools else {}

    async def close(self) -> None:
        return None

    async def call_tool(self, name: str, arguments: dict) -> str:
        if name not in self._tools:
            return f"Error: Unknown tool '{name}'"
        query = str(arguments.get("query") or arguments.get("address") or arguments.get("symbol") or "").strip()
        if not query:
            return f"Error: {name} requires a non-empty query."
        if name == "vanilla_lookup":
            try:
                context = max(0, min(30, int(arguments.get("context", 6))))
            except (TypeError, ValueError):
                context = 6
            return await asyncio.to_thread(self._lookup, query, context)
        scope = str(arguments.get("scope") or "both").lower()
        return await asyncio.to_thread(self._grep, query, scope)

    # -- vanilla_lookup ---------------------------------------------------

    def _lookup(self, query: str, context: int) -> str:
        match = _ADDRESS_RE.match(query)
        if match:
            bank, offset = match.group(1).upper(), match.group(2).upper()
            if bank in {"7E", "7F", "70"}:
                return self._lookup_define(f"${bank}{offset}", query)
            return self._lookup_code(bank, offset, context)
        short = _SHORT_ADDRESS_RE.match(query)
        if short:
            return self._lookup_define(f"$7E{short.group(1).upper()}", query)
        return self._lookup_name(query, context)

    def _lookup_code(self, bank: str, offset: str, context: int) -> str:
        path = self.usdasm / f"bank_{bank}.asm"
        lines = _read_lines(path)
        if not lines:
            return f"No usdasm file for bank ${bank} ({path.name} missing); vanilla code banks are {self._banks()}."
        marker = f"#_{bank}{offset}:"
        index = next((i for i, line in enumerate(lines) if line.startswith(marker)), None)
        if index is None:
            # Data blocks have no per-byte marker: report the nearest instruction before it.
            target = int(offset, 16)
            best = None
            for i, line in enumerate(lines):
                if line.startswith(f"#_{bank}"):
                    try:
                        here = int(line[4:8], 16)
                    except ValueError:
                        continue
                    if here <= target:
                        best = i
                    else:
                        break
            if best is None:
                return f"${bank}:{offset} is not an instruction start in {path.name}."
            index = best
            note = f"${bank}:{offset} is not an instruction start; nearest earlier line:"
        else:
            note = f"${bank}:{offset} (PC 0x{self._lorom_pc(bank, offset):06X}):"
        routine = local = ""
        for line in reversed(lines[: index + 1]):
            if not local and _LOCAL_RE.match(line):
                local = _LOCAL_RE.match(line).group(1)
            routine_match = _ROUTINE_RE.match(line)
            if routine_match:
                routine = routine_match.group(1)
                break
        start, end = max(0, index - context), min(len(lines), index + context + 1)
        body = "\n".join(f"{n + 1:6d}  {lines[n]}" for n in range(start, end))
        return (
            f"{note}\n- instruction: {lines[index].strip()}\n"
            f"- routine: {routine or '(none above)'}" + (f" (local {local})" if local else "")
            + f"\n- source: {path}:{index + 1}\n\n{body}"
        )

    def _lookup_define(self, address: str, query: str) -> str:
        pattern = re.compile(rf"=\s*\{address}\b", re.IGNORECASE)
        hits = []
        for name in _DATA_FILES:
            path = self.usdasm / name
            lines = _read_lines(path)
            for i, line in enumerate(lines):
                if not pattern.search(line):
                    continue
                comments = [
                    lines[n].strip() for n in range(_block_start(lines, i), i)
                    if lines[n].lstrip().startswith(";")
                ]
                hits.append(f"- {path}:{i + 1}: {line.strip()}")
                hits.extend(f"    {c}" for c in comments)
        if not hits:
            return f"No usdasm define for {query} ({address})."
        return f"Defines for {address} (indented lines are the comments above it):\n" + "\n".join(hits[:24])

    def _lookup_name(self, name: str, context: int) -> str:
        label = re.compile(rf"^{re.escape(name)}:")
        define = re.compile(rf"^{re.escape(name)}\s*=", re.IGNORECASE)
        for path in sorted(self.usdasm.glob("*.asm")):
            lines = _read_lines(path)
            for i, line in enumerate(lines):
                if label.match(line) or define.match(line):
                    end = min(len(lines), i + context + 1)
                    body = "\n".join(f"{n + 1:6d}  {lines[n]}" for n in range(_block_start(lines, i), end))
                    return f"{name} is defined at {path}:{i + 1}\n\n{body}"
        return f"No usdasm label or define named {name!r}. Try asm_grep with scope 'vanilla'."

    def _banks(self) -> str:
        return ", ".join(sorted(p.stem[5:] for p in self.usdasm.glob("bank_*.asm")))

    @staticmethod
    def _lorom_pc(bank: str, offset: str) -> int:
        return ((int(bank, 16) & 0x7F) << 15) | (int(offset, 16) & 0x7FFF)

    # -- asm_grep ---------------------------------------------------------

    def _grep(self, query: str, scope: str) -> str:
        # Oracle hits stay workspace-relative and usdasm hits absolute, so either opens with read_file.
        roots = []
        if scope in {"oracle", "both"}:
            roots.append(("", self.workspace))
        if scope in {"vanilla", "both"}:
            roots.append((f"{self.usdasm}/", self.usdasm))
        if not roots:
            return "Error: scope must be oracle, vanilla, or both."
        rg = shutil.which("rg")
        hits: list[str] = []
        for label, root in roots:
            if rg:
                hits.extend(self._rg(rg, query, label, root))
            else:
                hits.extend(self._py_grep(query, label, root))
            if len(hits) >= _MAX_GREP_HITS:
                break
        if not hits:
            stripped = strip_namespace(query, self.workspace) if scope != "vanilla" else None
            if stripped:
                return namespace_note(query, stripped) + "\n" + self._grep(stripped, scope)
            return f"No matches for {query!r} in {scope}."
        shown = hits[:_MAX_GREP_HITS]
        more = f"\n({len(hits) - len(shown)}+ more; refine the query)" if len(hits) > len(shown) else ""
        return f"Matches for {query!r} ({scope}):\n" + "\n".join(shown) + more

    @staticmethod
    def _rg(rg: str, query: str, label: str, root: Path) -> list[str]:
        import subprocess

        proc = subprocess.run(
            [rg, "-n", "-S", "-F", "--no-heading", "-g", "*.asm", "-g", "*.inc", "-m", "20", "--", query, "."],
            cwd=root, capture_output=True, text=True, timeout=30,
        )
        return [f"- {label}{line[2:] if line.startswith('./') else line}" for line in proc.stdout.splitlines()
                if line][: _MAX_GREP_HITS + 1]

    @staticmethod
    def _py_grep(query: str, label: str, root: Path) -> list[str]:
        sensitive = query != query.lower()
        needle = query if sensitive else query.lower()
        hits = []
        for path in root.rglob("*.asm"):
            if any(part.startswith(".") for part in path.relative_to(root).parts):
                continue
            for n, line in enumerate(_read_lines(path), start=1):
                if needle in (line if sensitive else line.lower()):
                    hits.append(f"- {label}{path.relative_to(root)}:{n}: {line.strip()}")
                    if len(hits) > _MAX_GREP_HITS:
                        return hits
        return hits
