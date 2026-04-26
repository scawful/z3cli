"""MCP server lifecycle management and tool dispatch.

Spawns MCP servers as child processes via stdio transport,
collects their tool schemas, and routes tool calls.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from core.config import MCPServerConfig
from core.tool_bridge import ToolBridge


MCP_CONNECT_PARALLELISM = 4
MCP_CONNECT_TIMEOUT_S = 30.0

MCP_SERVER_CAPABILITY_OVERRIDES = {
    "yaze-debugger": "emulator",
    "yaze-editor": "rom",
}

_ROM_NUMERIC_ARGS = {
    "room_id",
    "map_id",
    "dungeon_id",
    "sprite_id",
    "obj_id",
    "x",
    "y",
    "index",
    "subtype",
    "layer",
    "size",
    "palette_id",
    "message_id",
}


def infer_server_capability(server_name: str) -> str:
    """Return the logical adapter capability for an MCP server."""
    return MCP_SERVER_CAPABILITY_OVERRIDES.get(server_name, "reference")


def _maybe_parse_int(value: object) -> object:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    try:
        if text.lower().startswith("0x"):
            return int(text, 16)
        if text.startswith("$"):
            return int(text[1:], 16)
        return int(text, 10)
    except ValueError:
        return value


@dataclass
class _WorkerCall:
    tool_name: str
    arguments: dict[str, Any]
    future: asyncio.Future[Any]


class _StopWorker:
    pass


_STOP_WORKER = _StopWorker()


class _MCPServerWorker:
    """Own one MCP stdio/session lifecycle inside a single worker task."""

    CLOSE_TIMEOUT_S = 3.0

    def __init__(self, name: str, cfg: MCPServerConfig):
        self._name = name
        self._cfg = cfg
        self._queue: asyncio.Queue[_WorkerCall | _StopWorker] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._ready: asyncio.Future[list[Any]] | None = None
        self._error: Exception | None = None

    async def start(self) -> list[Any]:
        if self._task is not None:
            if self._ready is not None:
                return await self._ready
            if not self._task.done():
                return []
            raise RuntimeError(f"MCP worker '{self._name}' is not running")

        loop = asyncio.get_running_loop()
        self._ready = loop.create_future()
        self._task = loop.create_task(self._run(), name=f"mcp:{self._name}")
        try:
            return await asyncio.wait_for(self._ready, timeout=MCP_CONNECT_TIMEOUT_S)
        except Exception:
            await self.close(cancel=True)
            raise

    async def call_tool(self, name: str, arguments: dict) -> Any:
        if self._task is None or self._task.done():
            if self._error is not None:
                raise RuntimeError(f"{self._name}: {self._error}")
            raise RuntimeError(f"Server '{self._name}' not connected")

        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
        await self._queue.put(_WorkerCall(name, dict(arguments), future))
        return await future

    async def close(self, *, cancel: bool = False) -> None:
        task = self._task
        self._task = None
        if task is None:
            return

        if not task.done():
            if cancel:
                task.cancel()
            else:
                await self._queue.put(_STOP_WORKER)
            try:
                await asyncio.wait_for(task, timeout=self.CLOSE_TIMEOUT_S)
            except asyncio.TimeoutError:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        else:
            with suppress(asyncio.CancelledError):
                await task

    async def _run(self) -> None:
        try:
            env = {**os.environ, **self._cfg.env}
            params = StdioServerParameters(
                command=self._cfg.command,
                args=self._cfg.args,
                env=env,
            )
            async with stdio_client(params) as transport:
                read_stream, write_stream = transport
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    ready = self._ready
                    if ready is not None and not ready.done():
                        ready.set_result(list(result.tools))
                    await self._serve_requests(session)
        except asyncio.CancelledError:
            ready = self._ready
            if ready is not None and not ready.done():
                ready.set_exception(asyncio.TimeoutError())
            self._reject_pending(RuntimeError(f"{self._name}: worker cancelled"))
            raise
        except Exception as exc:
            self._error = exc
            ready = self._ready
            if ready is not None and not ready.done():
                ready.set_exception(exc)
            self._reject_pending(exc)
        else:
            self._reject_pending(RuntimeError(f"{self._name}: server closed"))
        finally:
            self._ready = None

    async def _serve_requests(self, session: ClientSession) -> None:
        while True:
            item = await self._queue.get()
            if item is _STOP_WORKER:
                return
            assert isinstance(item, _WorkerCall)
            try:
                result = await session.call_tool(item.tool_name, item.arguments)
            except Exception as exc:
                if not item.future.done():
                    item.future.set_exception(exc)
            else:
                if not item.future.done():
                    item.future.set_result(result)

    def _reject_pending(self, error: Exception) -> None:
        while not self._queue.empty():
            item = self._queue.get_nowait()
            if isinstance(item, _WorkerCall) and not item.future.done():
                item.future.set_exception(error)


class MCPCapabilityBridge:
    """Filtered view over an MCPBridge for a single logical capability.

    This is an internal adapter-facing wrapper. It exposes only tools owned by
    servers in one capability bucket and translates the current adapter-facing
    z3ed-style calls onto the yaze MCP server contracts where needed.
    """

    def __init__(self, inner: "MCPBridge", capability: str):
        self._inner = inner
        self._capability = capability

    def _server_names(self) -> list[str]:
        return [
            name for name in self._inner.server_names
            if infer_server_capability(name) == self._capability
        ]

    def _tool_names(self) -> set[str]:
        return {
            tool["function"]["name"]
            for tool in self.get_openai_tools()
        }

    def _resolve_exposed_tool_name(self, name: str) -> str | None:
        if name in self._tool_names():
            return name
        for server_name in self._server_names():
            exposed = self._inner.find_exposed_tool(server_name, name)
            if exposed is not None:
                return exposed
        return None

    @staticmethod
    def _translate_breakpoint_type(value: object) -> str:
        lowered = str(value or "exec").strip().lower()
        return {
            "exec": "EXECUTE",
            "execute": "EXECUTE",
            "read": "READ",
            "write": "WRITE",
            "access": "ACCESS",
        }.get(lowered, "EXECUTE")

    @staticmethod
    def _translate_step_mode(value: object) -> str:
        lowered = str(value or "instruction").strip().lower()
        return {
            "into": "instruction",
            "instruction": "instruction",
            "over": "over",
            "out": "out",
        }.get(lowered, "instruction")

    def _translate_emulator_call(self, name: str, arguments: dict) -> tuple[str, dict]:
        args = dict(arguments)
        if name == "mesen_memory_read":
            return "read_memory", {
                "address": args.get("address"),
                "size": args.get("length", args.get("size", 16)),
            }
        if name == "mesen_memory_write":
            return "write_memory", {
                "address": args.get("address"),
                "values": args.get("values", args.get("data")),
            }
        if name == "mesen_disasm":
            return "get_disassembly", {
                "address": args.get("address"),
                "count": args.get("count", args.get("lines", 20)),
            }
        if name == "mesen_gamestate":
            return "get_game_state", {}
        if name == "mesen_cpu":
            return "get_debug_status", {}
        if name == "mesen_control":
            action = str(args.get("action", "")).strip().lower()
            if action == "step":
                return "step_emulator", {
                    "mode": self._translate_step_mode(args.get("mode")),
                }
            if action in {"run", "continue"}:
                return "control_emulator", {"action": "resume"}
            if action in {"pause", "resume", "reset", "start", "stop"}:
                return "control_emulator", {"action": action}
        if name == "mesen_breakpoint":
            action = str(args.get("action", "add")).strip().lower()
            if action == "add":
                payload = {
                    "address": args.get("address"),
                    "bp_type": self._translate_breakpoint_type(args.get("type")),
                }
                description = args.get("description")
                if description:
                    payload["description"] = description
                return "add_breakpoint", payload
            if action == "remove":
                return "remove_breakpoint", {"bp_id": args.get("bp_id")}
            if action == "list":
                return "list_breakpoints", {}
        return name, args

    def _translate_rom_call(self, name: str, arguments: dict) -> tuple[str, dict]:
        args = dict(arguments)
        if name.startswith("dungeon_") and "room" in args and "room_id" not in args:
            args["room_id"] = args.pop("room")
        if name == "dungeon_place_sprite" and "id" in args and "sprite_id" not in args:
            args["sprite_id"] = args.pop("id")
        if name == "dungeon_place_object" and "id" in args and "obj_id" not in args:
            args["obj_id"] = args.pop("id")
        if name == "dungeon_graph" and "dungeon" in args and "dungeon_id" not in args:
            args["dungeon_id"] = args.pop("dungeon")
        if name == "message_read" and "id" in args and "message_id" not in args:
            args["message_id"] = args.pop("id")

        for key in _ROM_NUMERIC_ARGS:
            if key in args:
                args[key] = _maybe_parse_int(args[key])
        return name, args

    def _translate_call(self, name: str, arguments: dict) -> tuple[str, dict]:
        if self._capability == "emulator":
            return self._translate_emulator_call(name, arguments)
        if self._capability == "rom":
            return self._translate_rom_call(name, arguments)
        return name, dict(arguments)

    def get_openai_tools(self) -> list[dict]:
        tools: list[dict] = []
        for tool in self._inner.get_openai_tools():
            name = tool.get("function", {}).get("name", "")
            if self._inner.tool_capability(name) != self._capability:
                continue
            tools.append(deepcopy(tool))
        return tools

    async def call_tool(self, name: str, arguments: dict) -> str:
        translated_name, translated_args = self._translate_call(name, arguments)
        exposed_name = self._resolve_exposed_tool_name(translated_name)
        if exposed_name is None:
            return (
                f"Error: MCP capability '{self._capability}' does not expose "
                f"tool '{name}'."
            )
        return await self._inner.call_tool(exposed_name, translated_args)

    def get_tool_server(self, tool_name: str) -> str:
        translated_name, _ = self._translate_call(tool_name, {})
        exposed_name = self._resolve_exposed_tool_name(translated_name)
        if exposed_name is None:
            return "unknown"
        return self._inner.get_tool_server(exposed_name)

    @property
    def tool_count(self) -> int:
        return len(self.get_openai_tools())

    @property
    def server_names(self) -> list[str]:
        return self._server_names()

    @property
    def server_tool_counts(self) -> dict[str, int]:
        return {
            name: count
            for name, count in self._inner.server_tool_counts.items()
            if infer_server_capability(name) == self._capability
        }

    async def close(self) -> None:
        # The owning MCPBridge is also present under the "*" fallback bridge.
        # Keep this wrapper close as a no-op so adapters do not double-close the
        # shared underlying sessions.
        return None


class MCPBridge:
    """Manages connections to multiple MCP servers."""

    def __init__(self):
        self._sessions: dict[str, _MCPServerWorker] = {}
        self._tool_server: dict[str, str] = {}  # tool_name -> server_name
        self._tool_actual: dict[str, str] = {}  # exposed_name -> actual tool name
        self._tools: list[dict] = []  # OpenAI function-calling format
        self._server_tool_counts: dict[str, int] = {}

    async def connect(self, servers: dict[str, MCPServerConfig]) -> list[str]:
        """Connect to MCP servers in parallel. Non-fatal if some fail.

        Returns list of errors (empty on full success). Each server owns a
        dedicated worker task that enters and exits the stdio transport +
        ClientSession in the same task, which avoids anyio task-bound cancel
        scope errors during shutdown.
        """
        if not servers:
            return []

        pending_servers = {
            name: cfg
            for name, cfg in servers.items()
            if name not in self._sessions
        }
        if not pending_servers:
            return []

        semaphore = asyncio.Semaphore(MCP_CONNECT_PARALLELISM)

        async def connect_one(name: str, cfg: MCPServerConfig):
            async with semaphore:
                worker = _MCPServerWorker(name, cfg)
                try:
                    tools = await worker.start()
                    return name, worker, tools, None
                except asyncio.TimeoutError:
                    return name, None, None, f"{name}: connect timed out after {MCP_CONNECT_TIMEOUT_S:.0f}s"
                except Exception as e:
                    return name, None, None, f"{name}: {e}"

        gathered = await asyncio.gather(
            *(connect_one(n, c) for n, c in pending_servers.items()),
        )

        errors: list[str] = []
        # Deterministic ordering for collision renaming so tool names are
        # stable across runs regardless of which server connected first.
        for name, worker, tools, error in sorted(gathered, key=lambda r: r[0]):
            if error is not None:
                errors.append(error)
                continue
            assert worker is not None
            self._sessions[name] = worker
            count = 0
            for tool in tools or []:
                actual_name = tool.name
                tool_name = actual_name
                if tool_name in self._tool_server:
                    tool_name = f"{name}_{tool_name}"
                self._tool_server[tool_name] = name
                self._tool_actual[tool_name] = actual_name
                self._tools.append({
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": tool.description or "",
                        "parameters": tool.inputSchema or {
                            "type": "object",
                            "properties": {},
                        },
                    },
                })
                count += 1
            self._server_tool_counts[name] = count

        return errors

    async def call_tool(self, name: str, arguments: dict) -> str:
        """Call an MCP tool by name and return the text result."""
        server_name = self._tool_server.get(name)
        if not server_name:
            return f"Error: Unknown tool '{name}'"

        session = self._sessions.get(server_name)
        if not session:
            return f"Error: Server '{server_name}' not connected"

        actual_name = self._tool_actual.get(name, name)

        try:
            result = await session.call_tool(actual_name, arguments)
            if result.content:
                # MCP results can have multiple content blocks; join text ones
                parts = []
                for block in result.content:
                    text = getattr(block, "text", None)
                    if isinstance(text, str) and text:
                        parts.append(text)
                return "\n".join(parts) if parts else "(no output)"
            return "(no output)"
        except Exception as e:
            return f"Error calling {name}: {e}"

    def get_openai_tools(self) -> list[dict]:
        """Return tool schemas in OpenAI function-calling format."""
        return self._tools

    def get_tool_server(self, tool_name: str) -> str:
        """Which MCP server owns this tool."""
        return self._tool_server.get(tool_name, "unknown")

    def tool_capability(self, tool_name: str) -> str:
        """Return the logical capability bucket for an exposed tool name."""
        return infer_server_capability(self.get_tool_server(tool_name))

    def find_exposed_tool(self, server_name: str, actual_name: str) -> str | None:
        """Return the exposed tool name for a server+actual-tool pair."""
        for exposed_name, owner in self._tool_server.items():
            if owner != server_name:
                continue
            if self._tool_actual.get(exposed_name, exposed_name) == actual_name:
                return exposed_name
        return None

    def capability_view(self, capability: str) -> ToolBridge | None:
        """Return a filtered ToolBridge for one logical capability."""
        view = MCPCapabilityBridge(self, capability)
        return view if view.tool_count > 0 else None

    @property
    def tool_count(self) -> int:
        return len(self._tools)

    @property
    def server_names(self) -> list[str]:
        return list(self._sessions.keys())

    @property
    def server_tool_counts(self) -> dict[str, int]:
        return dict(self._server_tool_counts)

    async def close(self):
        workers = list(self._sessions.values())
        self._sessions = {}
        self._tool_server = {}
        self._tool_actual = {}
        self._tools = []
        self._server_tool_counts = {}
        for worker in reversed(workers):
            with suppress(Exception):
                await worker.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()
