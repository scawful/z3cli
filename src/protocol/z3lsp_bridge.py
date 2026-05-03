"""Direct stdio bridge for z3lsp agent tools."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse


DEFAULT_Z3DK_ROOT = Path.home() / "src/hobby/z3dk"


@dataclass
class OpenDocument:
    uri: str
    text: str
    version: int = 1
    diagnostics: list[dict[str, Any]] = field(default_factory=list)


def workspace_supports_z3lsp(workspace: Path) -> bool:
    if (workspace / "z3dk.toml").is_file():
        return True
    for pattern in ("Main.asm", "*_main.asm", "*-main.asm"):
        if any(workspace.glob(pattern)):
            return True
    return False


class Z3LspBridge:
    """Expose a small, read-only z3lsp tool surface to models."""

    SERVER_NAME = "z3lsp"
    REQUEST_TIMEOUT = 8.0
    DIAGNOSTIC_TIMEOUT = 8.0
    CONTEXT_PACK_SYMBOL_LIMIT = 12
    CONTEXT_PACK_DIAGNOSTIC_LIMIT = 3

    def __init__(
        self,
        workspace: Path,
        z3dk_root: Path | None = None,
        executable: Path | None = None,
    ):
        self.workspace = workspace.expanduser().resolve()
        self.z3dk_root = (z3dk_root or DEFAULT_Z3DK_ROOT).expanduser().resolve()
        self.executable = executable.expanduser().resolve() if executable else None
        self.proc: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._stderr_tail: list[str] = []
        self._buffer = bytearray()
        self._lock = asyncio.Lock()
        self._next_id = 1
        self._docs: dict[Path, OpenDocument] = {}
        self._tool_names = {
            "z3lsp_diagnostics",
            "z3lsp_hover",
            "z3lsp_definition",
            "z3lsp_symbols",
            "z3lsp_references",
        }

    async def connect(self) -> list[str]:
        try:
            executable = self._locate_executable()
            self.proc = await asyncio.create_subprocess_exec(
                str(executable),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._stderr_task = asyncio.create_task(self._drain_stderr())
            await self._request(
                "initialize",
                {
                    "rootUri": self.workspace.as_uri(),
                    "capabilities": {},
                },
            )
            await self._notify("initialized", {})
            return []
        except Exception as exc:
            await self.close()
            return [f"z3lsp: {exc}"]

    def _locate_executable(self) -> Path:
        if self.executable and self.executable.exists():
            return self.executable
        env_path = os.environ.get("Z3LSP_PATH")
        if env_path:
            candidate = Path(env_path).expanduser()
            if candidate.exists():
                return candidate.resolve()
        candidates = [
            self.z3dk_root / "build" / "z3lsp" / "z3lsp",
            self.z3dk_root / "build" / "src" / "z3lsp" / "z3lsp",
            self.z3dk_root / "build-z3dk-foundation" / "z3lsp" / "z3lsp",
            self.z3dk_root / "build-z3dk-foundation" / "src" / "z3lsp" / "z3lsp",
            self.z3dk_root / "build-z3dk-asan" / "z3lsp" / "z3lsp",
            self.z3dk_root / "build-z3dk-asan" / "src" / "z3lsp" / "z3lsp",
            self.z3dk_root / "build" / "bin" / "z3lsp",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate.resolve()
        found = shutil.which("z3lsp")
        if found:
            return Path(found).resolve()
        raise FileNotFoundError(f"z3lsp binary not found under {self.z3dk_root} or in PATH")

    async def _drain_stderr(self) -> None:
        if self.proc is None or self.proc.stderr is None:
            return
        while True:
            chunk = await self.proc.stderr.readline()
            if not chunk:
                return
            line = chunk.decode("utf-8", errors="replace").rstrip()
            if line:
                self._stderr_tail.append(line)
                if len(self._stderr_tail) > 20:
                    self._stderr_tail.pop(0)

    async def _send_locked(self, payload: dict[str, Any]) -> None:
        if self.proc is None or self.proc.stdin is None:
            raise RuntimeError("z3lsp is not running")
        body = json.dumps(payload).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        self.proc.stdin.write(header + body)
        await self.proc.stdin.drain()

    async def _read_message_locked(self, timeout: float) -> dict[str, Any]:
        if self.proc is None or self.proc.stdout is None:
            raise RuntimeError("z3lsp is not running")
        while True:
            marker = self._buffer.find(b"\r\n\r\n")
            if marker == -1:
                chunk = await asyncio.wait_for(self.proc.stdout.read(4096), timeout=timeout)
                if not chunk:
                    raise RuntimeError(self._exit_message("z3lsp closed stdout"))
                self._buffer.extend(chunk)
                continue

            header = bytes(self._buffer[:marker])
            content_length = 0
            for line in header.split(b"\r\n"):
                if line.lower().startswith(b"content-length:"):
                    content_length = int(line.split(b":", 1)[1].strip())
                    break
            body_start = marker + 4
            if len(self._buffer) < body_start + content_length:
                chunk = await asyncio.wait_for(self.proc.stdout.read(4096), timeout=timeout)
                if not chunk:
                    raise RuntimeError(self._exit_message("z3lsp closed stdout"))
                self._buffer.extend(chunk)
                continue

            body = bytes(self._buffer[body_start : body_start + content_length])
            del self._buffer[: body_start + content_length]
            return json.loads(body.decode("utf-8"))

    async def _request(self, method: str, params: dict[str, Any], timeout: float | None = None) -> Any:
        async with self._lock:
            request_id = self._next_id
            self._next_id += 1
            await self._send_locked(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params,
                }
            )
            wait_timeout = timeout or self.REQUEST_TIMEOUT
            while True:
                message = await self._read_message_locked(wait_timeout)
                if message.get("method") == "textDocument/publishDiagnostics":
                    self._handle_diagnostics(message)
                    continue
                if message.get("id") != request_id:
                    continue
                if "error" in message:
                    raise RuntimeError(f"{method} failed: {message['error']}")
                return message.get("result")

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        async with self._lock:
            await self._send_locked(
                {
                    "jsonrpc": "2.0",
                    "method": method,
                    "params": params,
                }
            )

    def _handle_diagnostics(self, message: dict[str, Any]) -> None:
        params = message.get("params") or {}
        uri = params.get("uri")
        if not isinstance(uri, str):
            return
        path = self._uri_to_path(uri)
        doc = self._docs.get(path)
        if doc is None:
            return
        diagnostics = params.get("diagnostics")
        if isinstance(diagnostics, list):
            doc.diagnostics = diagnostics

    async def _wait_for_diagnostics_locked(self, uri: str, timeout: float | None = None) -> list[dict[str, Any]]:
        wait_timeout = timeout or self.DIAGNOSTIC_TIMEOUT
        while True:
            message = await self._read_message_locked(wait_timeout)
            if message.get("method") != "textDocument/publishDiagnostics":
                continue
            self._handle_diagnostics(message)
            params = message.get("params") or {}
            if params.get("uri") == uri:
                diagnostics = params.get("diagnostics")
                return diagnostics if isinstance(diagnostics, list) else []

    async def _ensure_document(self, file_path: str) -> tuple[Path, OpenDocument]:
        path = self._resolve_file_path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"File not found: {path}")
        text = path.read_text(encoding="utf-8", errors="replace")
        existing = self._docs.get(path)
        if existing is not None and existing.text == text:
            return path, existing

        uri = path.as_uri()
        version = 1 if existing is None else existing.version + 1
        document = OpenDocument(uri=uri, text=text, version=version)

        async with self._lock:
            if existing is not None:
                await self._send_locked(
                    {
                        "jsonrpc": "2.0",
                        "method": "textDocument/didClose",
                        "params": {"textDocument": {"uri": uri}},
                    }
                )
                try:
                    await self._wait_for_diagnostics_locked(uri, timeout=2.0)
                except Exception:
                    pass
            self._docs[path] = document
            await self._send_locked(
                {
                    "jsonrpc": "2.0",
                    "method": "textDocument/didOpen",
                    "params": {
                        "textDocument": {
                            "uri": uri,
                            "languageId": "asar",
                            "version": version,
                            "text": text,
                        }
                    },
                }
            )
            document.diagnostics = await self._wait_for_diagnostics_locked(uri)
        return path, document

    def _resolve_file_path(self, value: str) -> Path:
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = self.workspace / candidate
        return candidate.resolve()

    def _uri_to_path(self, uri: str) -> Path:
        parsed = urlparse(uri)
        if parsed.scheme == "file":
            raw_path = unquote(parsed.path)
            if os.name == "nt":
                if parsed.netloc and parsed.netloc.lower() not in {"", "localhost"}:
                    return Path(f"//{parsed.netloc}{raw_path}").resolve()
                if len(raw_path) >= 3 and raw_path[0] == "/" and raw_path[2] == ":":
                    raw_path = raw_path[1:]
            return Path(raw_path).resolve()
        return Path(uri).expanduser().resolve()

    def _exit_message(self, prefix: str) -> str:
        if self.proc is not None and self.proc.returncode is not None:
            prefix = f"{prefix} (exit={self.proc.returncode})"
        if self._stderr_tail:
            prefix = f"{prefix}; stderr: {self._stderr_tail[-1]}"
        return prefix

    def _position(self, arguments: dict[str, Any]) -> tuple[int, int, int, int]:
        line = max(1, int(arguments.get("line", 1)))
        column = max(1, int(arguments.get("column", 1)))
        return line, column, line - 1, column - 1

    def _location_to_ref(self, location: dict[str, Any]) -> str:
        path = self._uri_to_path(str(location.get("uri", "")))
        start = ((location.get("range") or {}).get("start") or {})
        line = int(start.get("line", 0)) + 1
        column = int(start.get("character", 0)) + 1
        snippet = self._line_snippet(path, line)
        return f"{path}:{line}:{column}" + (f" - {snippet}" if snippet else "")

    def _line_snippet(self, path: Path, line_number: int) -> str:
        document = self._docs.get(path)
        if document is not None:
            lines = document.text.splitlines()
        else:
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except Exception:
                return ""
        if 1 <= line_number <= len(lines):
            return lines[line_number - 1].strip()[:160]
        return ""

    def _format_diagnostics(self, path: Path, diagnostics: list[dict[str, Any]]) -> str:
        if not diagnostics:
            return f"No diagnostics for {path}"
        lines = [f"Diagnostics for {path}:"]
        for diagnostic in diagnostics[:50]:
            severity = {1: "error", 2: "warning", 3: "info", 4: "hint"}.get(
                diagnostic.get("severity"), "info"
            )
            start = ((diagnostic.get("range") or {}).get("start") or {})
            line = int(start.get("line", 0)) + 1
            column = int(start.get("character", 0)) + 1
            message = str(diagnostic.get("message", "")).strip()
            lines.append(f"- {severity} {path}:{line}:{column} {message}")
            snippet = self._line_snippet(path, line)
            if snippet:
                lines.append(f"  {snippet}")
        return "\n".join(lines)

    def _extract_hover_text(self, result: Any) -> str:
        if not result:
            return "No hover information available."
        contents = result.get("contents") if isinstance(result, dict) else result
        if isinstance(contents, dict):
            value = contents.get("value")
            if isinstance(value, str) and value.strip():
                return value.strip()
        if isinstance(contents, list):
            parts: list[str] = []
            for item in contents:
                if isinstance(item, dict):
                    value = item.get("value")
                    if isinstance(value, str) and value.strip():
                        parts.append(value.strip())
                elif isinstance(item, str) and item.strip():
                    parts.append(item.strip())
            if parts:
                return "\n\n".join(parts)
        if isinstance(contents, str) and contents.strip():
            return contents.strip()
        return str(contents)

    def _format_locations(self, title: str, locations: list[dict[str, Any]], limit: int = 50) -> str:
        if not locations:
            return f"{title}: none"
        lines = [f"{title} ({min(len(locations), limit)} of {len(locations)}):"]
        for location in locations[:limit]:
            lines.append(f"- {self._location_to_ref(location)}")
        return "\n".join(lines)

    def _format_workspace_symbols(self, symbols: list[dict[str, Any]]) -> str:
        if not symbols:
            return "No matching workspace symbols."
        lines = [f"Workspace symbols ({min(len(symbols), 50)} of {len(symbols)}):"]
        for symbol in symbols[:50]:
            name = symbol.get("name", "?")
            location = symbol.get("location") or {}
            lines.append(f"- {name} @ {self._location_to_ref(location)}")
        return "\n".join(lines)

    def _format_document_symbols(self, path: Path, symbols: list[dict[str, Any]], query: str) -> str:
        query_lower = query.lower().strip()
        lines = [f"Document symbols for {path}:"]

        def walk(items: list[dict[str, Any]], prefix: str = "") -> None:
            for item in items:
                name = str(item.get("name", "?")).strip()
                if query_lower and query_lower not in name.lower():
                    walk(item.get("children") or [], prefix + "  ")
                    continue
                start = ((item.get("range") or {}).get("start") or {})
                line = int(start.get("line", 0)) + 1
                lines.append(f"- {path}:{line} {prefix}{name}")
                walk(item.get("children") or [], prefix + "  ")

        walk(symbols)
        return "\n".join(lines) if len(lines) > 1 else f"No matching document symbols for {path}."

    @staticmethod
    def _relative_label(path: Path, workspace: Path) -> str:
        try:
            return path.relative_to(workspace).as_posix()
        except ValueError:
            return path.as_posix()

    @staticmethod
    def _truncate_inline(text: str, max_chars: int = 160) -> str:
        value = " ".join(str(text or "").split())
        if len(value) <= max_chars:
            return value
        return value[: max_chars - 3].rstrip() + "..."

    @staticmethod
    def _truncate_block(text: str, max_chars: int) -> str:
        if max_chars <= 0 or len(text) <= max_chars:
            return text
        suffix = "\n... [truncated]"
        keep = max(0, max_chars - len(suffix))
        return text[:keep].rstrip() + suffix

    def _collect_symbol_outline(
        self,
        symbols: list[dict[str, Any]],
        *,
        query: str = "",
        limit: int | None = None,
    ) -> list[str]:
        query_lower = query.lower().strip()
        max_items = limit or self.CONTEXT_PACK_SYMBOL_LIMIT
        lines: list[str] = []

        def walk(items: list[dict[str, Any]], depth: int = 0) -> None:
            for item in items:
                if len(lines) >= max_items:
                    return
                name = str(item.get("name", "?")).strip() or "?"
                children = item.get("children") or []
                matches = not query_lower or query_lower in name.lower()
                if matches:
                    start = ((item.get("range") or {}).get("start") or {})
                    line = int(start.get("line", 0)) + 1
                    indent = "  " * min(depth, 3)
                    lines.append(f"- L{line} {indent}{name}")
                walk(children, depth + 1)

        walk(symbols)
        return lines

    @staticmethod
    def _normalize_locations(result: Any) -> list[dict[str, Any]]:
        if isinstance(result, list):
            return [item for item in result if isinstance(item, dict)]
        if isinstance(result, dict):
            return [result]
        return []

    @staticmethod
    def _symbol_start(item: dict[str, Any]) -> tuple[int, int]:
        range_data = item.get("selectionRange") or item.get("range") or {}
        start = (range_data.get("start") or {}) if isinstance(range_data, dict) else {}
        return int(start.get("line", 0)), int(start.get("character", 0))

    def _iter_document_symbols(self, symbols: list[dict[str, Any]]) -> list[dict[str, Any]]:
        flattened: list[dict[str, Any]] = []

        def walk(items: list[dict[str, Any]]) -> None:
            for item in items:
                if not isinstance(item, dict):
                    continue
                flattened.append(item)
                children = item.get("children") or []
                if isinstance(children, list):
                    walk(children)

        walk(symbols)
        return flattened

    def _select_symbol_candidates(
        self,
        symbols: list[dict[str, Any]],
        symbol_queries: list[str],
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        if limit <= 0 or not symbol_queries:
            return []
        flattened = self._iter_document_symbols(symbols)
        if not flattened:
            return []

        candidates: list[dict[str, Any]] = []
        seen: set[tuple[str, int, int]] = set()

        def append_matches(query: str, *, exact_only: bool) -> None:
            query_lower = query.lower().strip()
            if not query_lower:
                return
            for item in flattened:
                if len(candidates) >= limit:
                    return
                name = str(item.get("name", "") or "").strip()
                if not name:
                    continue
                name_lower = name.lower()
                if exact_only:
                    if name_lower != query_lower:
                        continue
                elif query_lower not in name_lower:
                    continue
                line, column = self._symbol_start(item)
                key = (name_lower, line, column)
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(item)

        for query in symbol_queries:
            append_matches(query, exact_only=True)
        for query in symbol_queries:
            append_matches(query, exact_only=False)
        return candidates[:limit]

    @staticmethod
    def _query_matches_name(query: str, name: str) -> bool:
        query_lower = query.lower().strip()
        name_lower = name.lower().strip()
        if not query_lower or not name_lower:
            return False
        return name_lower == query_lower or query_lower in name_lower

    async def _build_symbol_detail_lines(
        self,
        path: Path,
        document: OpenDocument,
        symbols: list[dict[str, Any]],
        *,
        symbol_queries: list[str],
        detail_limit: int,
        reference_limit: int,
        include_hover: bool,
    ) -> list[str]:
        candidates = self._select_symbol_candidates(symbols, symbol_queries, limit=detail_limit)
        if not candidates:
            return []

        lines: list[str] = []
        for item in candidates:
            name = str(item.get("name", "?") or "?").strip()
            zero_line, zero_column = self._symbol_start(item)
            line = zero_line + 1
            column = zero_column + 1
            lines.append(f"- {name} @ {path.name}:{line}:{column}")

            position = {"line": zero_line, "character": zero_column}
            if include_hover:
                try:
                    hover = await self._request(
                        "textDocument/hover",
                        {
                            "textDocument": {"uri": document.uri},
                            "position": position,
                        },
                    )
                except Exception:
                    hover = None
                hover_text = self._extract_hover_text(hover)
                if hover_text and hover_text != "No hover information available.":
                    lines.append(f"  hover: {self._truncate_inline(hover_text, max_chars=140)}")

            try:
                definitions = self._normalize_locations(await self._request(
                    "textDocument/definition",
                    {
                        "textDocument": {"uri": document.uri},
                        "position": position,
                    },
                ))
            except Exception:
                definitions = []
            if definitions:
                lines.append(
                    f"  def: {self._truncate_inline(self._location_to_ref(definitions[0]), max_chars=140)}"
                )

            if reference_limit > 0:
                try:
                    references = self._normalize_locations(await self._request(
                        "textDocument/references",
                        {
                            "textDocument": {"uri": document.uri},
                            "position": position,
                            "context": {"includeDeclaration": False},
                        },
                    ))
                except Exception:
                    references = []
                if references:
                    preview = [
                        self._truncate_inline(self._location_to_ref(location), max_chars=120)
                        for location in references[:reference_limit]
                    ]
                    suffix = f" (+{len(references) - len(preview)} more)" if len(references) > len(preview) else ""
                    lines.append(f"  refs: {' ; '.join(preview)}{suffix}")

        return lines

    async def _workspace_symbol_candidates(
        self,
        symbol_queries: list[str],
        *,
        limit: int,
    ) -> list[tuple[str, dict[str, Any]]]:
        if limit <= 0:
            return []

        collected: list[tuple[str, dict[str, Any]]] = []
        seen: set[tuple[str, str]] = set()
        for query in symbol_queries:
            if len(collected) >= limit:
                break
            try:
                result = await self._request("workspace/symbol", {"query": query})
            except Exception:
                continue
            symbols = result if isinstance(result, list) else []
            exact: list[dict[str, Any]] = []
            fuzzy: list[dict[str, Any]] = []
            for item in symbols:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", "") or "").strip()
                location = item.get("location") or {}
                if not isinstance(location, dict):
                    continue
                uri = str(location.get("uri", "") or "")
                if not uri:
                    continue
                key = (name.lower(), uri)
                if key in seen or not self._query_matches_name(query, name):
                    continue
                if name.lower() == query.lower():
                    exact.append(item)
                else:
                    fuzzy.append(item)
            for item in [*exact, *fuzzy]:
                if len(collected) >= limit:
                    break
                name = str(item.get("name", "") or "").strip()
                uri = str(((item.get("location") or {}).get("uri", "") or ""))
                seen.add((name.lower(), uri))
                collected.append((query, item))
        return collected

    async def _hover_for_location(self, location: dict[str, Any]) -> str:
        try:
            path = self._uri_to_path(str(location.get("uri", "")))
            _path, document = await self._ensure_document(str(path))
            start = ((location.get("range") or {}).get("start") or {})
            result = await self._request(
                "textDocument/hover",
                {
                    "textDocument": {"uri": document.uri},
                    "position": {
                        "line": int(start.get("line", 0)),
                        "character": int(start.get("character", 0)),
                    },
                },
            )
        except Exception:
            return ""
        hover_text = self._extract_hover_text(result)
        if hover_text == "No hover information available.":
            return ""
        return hover_text

    async def _build_workspace_symbol_fallback_lines(
        self,
        symbol_queries: list[str],
        *,
        detail_limit: int,
        include_hover: bool,
    ) -> list[str]:
        candidates = await self._workspace_symbol_candidates(symbol_queries, limit=detail_limit)
        if not candidates:
            return []

        lines: list[str] = []
        for query, item in candidates:
            name = str(item.get("name", "?") or "?").strip()
            location = item.get("location") or {}
            ref = self._truncate_inline(self._location_to_ref(location), max_chars=140)
            prefix = f"{name} (query: {query})" if name.lower() != query.lower() else name
            lines.append(f"- {prefix} @ {ref}")
            if include_hover:
                hover_text = await self._hover_for_location(location)
                if hover_text:
                    lines.append(f"  hover: {self._truncate_inline(hover_text, max_chars=140)}")
        return lines

    async def build_context_pack(
        self,
        file_path: str,
        *,
        query: str = "",
        symbol_queries: list[str] | None = None,
        max_chars: int = 1600,
        diagnostic_limit: int | None = None,
        symbol_limit: int | None = None,
        symbol_detail_limit: int = 0,
        reference_limit: int = 0,
        include_clean_diagnostics: bool = True,
        include_diagnostic_snippets: bool = False,
        include_symbol_hover: bool = False,
    ) -> str:
        """Return a compact diagnostics + symbol summary for one file."""
        if self.proc is None:
            return ""

        path, document = await self._ensure_document(file_path)
        result = await self._request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": document.uri}},
        )
        symbols = result if isinstance(result, list) else []
        label = self._relative_label(path, self.workspace)
        lines = [f"z3lsp summary for {label}:"]
        diag_limit = self.CONTEXT_PACK_DIAGNOSTIC_LIMIT if diagnostic_limit is None else max(0, diagnostic_limit)
        symbol_cap = self.CONTEXT_PACK_SYMBOL_LIMIT if symbol_limit is None else max(0, symbol_limit)

        if document.diagnostics:
            lines.append("Diagnostics:")
            for diagnostic in document.diagnostics[:diag_limit]:
                severity = {1: "error", 2: "warning", 3: "info", 4: "hint"}.get(
                    diagnostic.get("severity"), "info",
                )
                start = ((diagnostic.get("range") or {}).get("start") or {})
                line = int(start.get("line", 0)) + 1
                column = int(start.get("character", 0)) + 1
                message = self._truncate_inline(diagnostic.get("message", ""))
                lines.append(f"- {severity} L{line}:C{column} {message}")
                if include_diagnostic_snippets:
                    snippet = self._line_snippet(path, line)
                    if snippet:
                        lines.append(f"  {self._truncate_inline(snippet)}")
        elif include_clean_diagnostics:
            lines.append("Diagnostics: clean")

        outline_query = query
        detail_queries = [str(value).strip() for value in (symbol_queries or []) if str(value).strip()]
        if not outline_query and len(detail_queries) == 1:
            outline_query = detail_queries[0]
        symbol_lines = self._collect_symbol_outline(symbols, query=outline_query, limit=symbol_cap)
        if symbol_lines:
            lines.append("Symbols:")
            lines.extend(symbol_lines)
        elif symbol_cap > 0:
            lines.append("Symbols: none")

        if detail_queries and symbol_detail_limit > 0:
            local_candidates = self._select_symbol_candidates(
                symbols,
                detail_queries,
                limit=symbol_detail_limit,
            )
            detail_lines = await self._build_symbol_detail_lines(
                path,
                document,
                symbols,
                symbol_queries=detail_queries,
                detail_limit=symbol_detail_limit,
                reference_limit=reference_limit,
                include_hover=include_symbol_hover,
            )
            if detail_lines:
                lines.append("Symbol details:")
                lines.extend(detail_lines)
            matched_names = {
                str(item.get("name", "") or "").strip().lower()
                for item in local_candidates
                if isinstance(item, dict)
            }
            unresolved_queries = [
                query
                for query in detail_queries
                if not any(self._query_matches_name(query, name) for name in matched_names)
            ]
            fallback_lines = await self._build_workspace_symbol_fallback_lines(
                unresolved_queries,
                detail_limit=max(0, symbol_detail_limit - len(local_candidates)),
                include_hover=include_symbol_hover,
            )
            if fallback_lines:
                lines.append("Workspace symbol matches:")
                lines.extend(fallback_lines)

        return self._truncate_block("\n".join(lines), max_chars)

    def get_openai_tools(self) -> list[dict]:
        if self.proc is None:
            return []
        return [
            {
                "type": "function",
                "function": {
                    "name": "z3lsp_diagnostics",
                    "description": "Read z3lsp assembler and lint diagnostics for one source file.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string", "description": "ASM file path, absolute or workspace-relative."},
                        },
                        "required": ["file_path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "z3lsp_hover",
                    "description": "Get z3lsp hover info for an opcode, symbol, define, or SNES register at a 1-based line and column.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string"},
                            "line": {"type": "integer", "minimum": 1},
                            "column": {"type": "integer", "minimum": 1},
                        },
                        "required": ["file_path", "line", "column"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "z3lsp_definition",
                    "description": "Go to the definition for the token at a 1-based line and column.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string"},
                            "line": {"type": "integer", "minimum": 1},
                            "column": {"type": "integer", "minimum": 1},
                        },
                        "required": ["file_path", "line", "column"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "z3lsp_symbols",
                    "description": "Search workspace symbols, or list document symbols when file_path is provided.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Optional substring filter."},
                            "file_path": {"type": "string", "description": "Optional ASM file path for document-local symbols."},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "z3lsp_references",
                    "description": "Find references to the token at a 1-based line and column.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string"},
                            "line": {"type": "integer", "minimum": 1},
                            "column": {"type": "integer", "minimum": 1},
                        },
                        "required": ["file_path", "line", "column"],
                    },
                },
            },
        ]

    async def call_tool(self, name: str, arguments: dict) -> str:
        if self.proc is None:
            return "Error: z3lsp is not connected"
        try:
            if name == "z3lsp_diagnostics":
                path, document = await self._ensure_document(str(arguments["file_path"]))
                return self._format_diagnostics(path, document.diagnostics)

            if name == "z3lsp_hover":
                path, document = await self._ensure_document(str(arguments["file_path"]))
                line, column, zero_line, zero_column = self._position(arguments)
                result = await self._request(
                    "textDocument/hover",
                    {
                        "textDocument": {"uri": document.uri},
                        "position": {"line": zero_line, "character": zero_column},
                    },
                )
                return f"Hover at {path}:{line}:{column}\n\n{self._extract_hover_text(result)}"

            if name == "z3lsp_definition":
                path, document = await self._ensure_document(str(arguments["file_path"]))
                line, column, zero_line, zero_column = self._position(arguments)
                result = await self._request(
                    "textDocument/definition",
                    {
                        "textDocument": {"uri": document.uri},
                        "position": {"line": zero_line, "character": zero_column},
                    },
                )
                locations = result if isinstance(result, list) else []
                return self._format_locations(f"Definitions for {path}:{line}:{column}", locations)

            if name == "z3lsp_symbols":
                file_path = str(arguments.get("file_path", "")).strip()
                query = str(arguments.get("query", "")).strip()
                if file_path:
                    path, document = await self._ensure_document(file_path)
                    result = await self._request(
                        "textDocument/documentSymbol",
                        {"textDocument": {"uri": document.uri}},
                    )
                    symbols = result if isinstance(result, list) else []
                    return self._format_document_symbols(path, symbols, query)
                result = await self._request("workspace/symbol", {"query": query})
                symbols = result if isinstance(result, list) else []
                return self._format_workspace_symbols(symbols)

            if name == "z3lsp_references":
                path, document = await self._ensure_document(str(arguments["file_path"]))
                line, column, zero_line, zero_column = self._position(arguments)
                result = await self._request(
                    "textDocument/references",
                    {
                        "textDocument": {"uri": document.uri},
                        "position": {"line": zero_line, "character": zero_column},
                        "context": {"includeDeclaration": True},
                    },
                )
                locations = result if isinstance(result, list) else []
                return self._format_locations(f"References for {path}:{line}:{column}", locations)

            return f"Error: Unknown tool '{name}'"
        except Exception as exc:
            return f"Error calling {name}: {exc}"

    def get_tool_server(self, tool_name: str) -> str:
        return self.SERVER_NAME if tool_name in self._tool_names else "unknown"

    @property
    def tool_count(self) -> int:
        return len(self.get_openai_tools())

    @property
    def server_names(self) -> list[str]:
        return [self.SERVER_NAME] if self.proc is not None else []

    @property
    def server_tool_counts(self) -> dict[str, int]:
        return {self.SERVER_NAME: self.tool_count} if self.proc is not None else {}

    async def close(self) -> None:
        if self.proc is None:
            return
        try:
            if self.proc.returncode is None:
                try:
                    await self._request("shutdown", {}, timeout=2.0)
                except Exception:
                    pass
                try:
                    await self._notify("exit", {})
                except Exception:
                    pass
                try:
                    await asyncio.wait_for(self.proc.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    self.proc.terminate()
                    await asyncio.wait_for(self.proc.wait(), timeout=2.0)
        finally:
            if self._stderr_task is not None:
                self._stderr_task.cancel()
                try:
                    await self._stderr_task
                except asyncio.CancelledError:
                    pass
            self.proc = None
