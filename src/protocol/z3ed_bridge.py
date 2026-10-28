"""Direct bridge to the z3ed CLI (yaze).

Each ``call_tool`` spawns a fresh z3ed subprocess. This mirrors z3ed's
stateless-per-invocation design: simple to reason about, safe to cancel
(SIGTERM), and no persistent state to drift.

The bridge does three important things beyond "shell out":

1. Learns the tool surface once at :meth:`connect` time by translating
   ``z3ed --export-schemas`` into OpenAI-compatible tool schemas.
2. Auto-injects ``--rom`` for commands with ``requires_rom=true`` and
   ``--mesen-socket`` for ``mesen-*`` commands, sourced from a
   :class:`RomProject`. Callers need not thread these on every tool call.
3. Declares write-vs-read authoritatively via :meth:`is_write_tool` so
   ``ReadOnlyBridge`` can gate mutations without pattern-matching the
   command name.
"""

from __future__ import annotations

import asyncio
import copy
import os
import re
import shutil
from pathlib import Path
from typing import Any

from core.rom_project import RomProject
from protocol.z3ed_schema import TranslatedTool, load_schemas


SERVER_NAME = "z3ed"
DEFAULT_CONNECT_TIMEOUT_S = 30.0
DEFAULT_CALL_TIMEOUT_S = 120.0
DEFAULT_BOOTSTRAP_TIMEOUT_S = 60.0


_ANSI_ESCAPE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
_UNSAVED_WRITE_COMMANDS = frozenset({"rom-write", "hex-write"})
# z3ed reads these at PC file offsets, while rom-resolve-address takes SNES addresses.
_PC_OFFSET_COMMANDS = frozenset({"rom-read", "hex-read"})
_SYMBOL_COMMANDS = frozenset({"rom-resolve-address", "rom-find-symbol"})
_BANK_COLON_ADDRESS = re.compile(r"^\$?([0-9A-Fa-f]{1,2}):([0-9A-Fa-f]{4})$")
# The schema types these as integers, but z3ed parses the text as hex (--room=40 is room 0x40),
# so JSON integers must be sent 0x-prefixed.
_HEX_PARSED_INT_FLAGS = frozenset({"room"})
_PC_OFFSET_NOTE = (
    " `address` is a PC file offset (0x7FC0 is SNES $00:FFC0). For a 65816/SNES "
    "address pass `snes_address` instead ('$07:D151' or '$07D151'); it is mapped LoROM."
)


def lorom_snes_to_pc(text: str) -> int:
    """'$07:D151' / '$07D151' / '0x07D151' -> PC offset. Raises ValueError off-ROM."""
    cleaned = text.strip()
    match = _BANK_COLON_ADDRESS.match(cleaned)
    if match:
        value = (int(match.group(1), 16) << 16) | int(match.group(2), 16)
    else:
        value = int(re.sub(r"^(\$|0x)", "", cleaned, flags=re.IGNORECASE), 16)
    bank, offset = (value >> 16) & 0xFF, value & 0xFFFF
    if bank in (0x7E, 0x7F) or offset < 0x8000:
        raise ValueError(f"{text} is not a LoROM ROM address (WRAM/IO/low half of bank)")
    return ((bank & 0x7F) << 15) | (offset & 0x7FFF)


def _strip_ansi(text: str) -> str:
    return _ANSI_ESCAPE.sub("", text)


class Z3edBridge:
    """ToolBridge that shells out to z3ed per call."""

    def __init__(
        self,
        project: RomProject,
        *,
        yaze_bin: Path | None = None,
        connect_timeout_s: float = DEFAULT_CONNECT_TIMEOUT_S,
        call_timeout_s: float = DEFAULT_CALL_TIMEOUT_S,
        bootstrap_timeout_s: float = DEFAULT_BOOTSTRAP_TIMEOUT_S,
        auto_bootstrap_mesen: bool | None = None,
    ) -> None:
        self._project = project
        self._yaze_bin: Path | None = yaze_bin or project.yaze_bin
        self._connect_timeout_s = connect_timeout_s
        self._call_timeout_s = call_timeout_s
        self._bootstrap_timeout_s = bootstrap_timeout_s
        if auto_bootstrap_mesen is None:
            auto_bootstrap_mesen = os.environ.get("Z3CLI_MESEN_AUTO_BOOTSTRAP", "1").lower() not in {
                "0", "false", "no", "off",
            }
        self._auto_bootstrap_mesen = bool(auto_bootstrap_mesen)
        self._tools: dict[str, TranslatedTool] = {}
        self._warnings: list[str] = []

    # -- discovery ----------------------------------------------------------

    def _locate_executable(self) -> Path:
        if self._yaze_bin and self._yaze_bin.exists():
            return self._yaze_bin
        found = shutil.which("z3ed")
        if found:
            return Path(found).resolve()
        raise FileNotFoundError("z3ed binary not found; set YAZE_BIN or add z3ed to PATH")

    # -- ToolBridge protocol -----------------------------------------------

    async def connect(self) -> list[str]:
        """Run ``z3ed --export-schemas`` and translate. Returns any warnings."""
        self._tools = {}
        self._warnings = []
        try:
            executable = self._locate_executable()
        except FileNotFoundError as exc:
            self._warnings.append(str(exc))
            return list(self._warnings)

        try:
            proc = await asyncio.create_subprocess_exec(
                str(executable),
                "--export-schemas",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=self._connect_timeout_s,
            )
        except asyncio.TimeoutError:
            self._warnings.append(
                f"z3ed --export-schemas timed out after {self._connect_timeout_s:.0f}s"
            )
            return list(self._warnings)
        except FileNotFoundError as exc:
            self._warnings.append(f"z3ed invocation failed: {exc}")
            return list(self._warnings)

        if proc.returncode not in (0, None):
            detail = _strip_ansi(stderr_bytes.decode("utf-8", errors="replace")).strip()
            self._warnings.append(
                f"z3ed --export-schemas exit={proc.returncode}: {detail or '(no detail)'}"
            )
            return list(self._warnings)

        raw = stdout_bytes.decode("utf-8", errors="replace")
        tools, schema_warnings = load_schemas(raw)
        self._warnings.extend(schema_warnings)
        for tool in tools:
            self._tools[tool.tool_name] = tool
        return list(self._warnings)

    def get_openai_tools(self) -> list[dict]:
        schemas = []
        for tool in self._tools.values():
            schema = tool.openai_schema
            if tool.z3ed_name in _PC_OFFSET_COMMANDS:
                schema = copy.deepcopy(schema)
                function = schema["function"]
                function["description"] = function.get("description", "") + _PC_OFFSET_NOTE
                params = function.setdefault("parameters", {"type": "object", "properties": {}})
                params.setdefault("properties", {})["snes_address"] = {
                    "type": "string",
                    "description": "SNES CPU address in a ROM bank; converted to the PC offset.",
                }
                params["required"] = [r for r in params.get("required", []) if r != "address"]
            hex_ints = _HEX_PARSED_INT_FLAGS & {p.name for p in tool.params}
            if hex_ints:
                schema = copy.deepcopy(schema)
                props = schema["function"].get("parameters", {}).get("properties", {})
                for name in hex_ints:
                    if name in props:
                        props[name]["description"] = (
                            "Integer (decimal, e.g. 40) or hex string (\"0x28\", \"$28\"); "
                            "a bare string like \"28\" is read as hex."
                        )
            schemas.append(schema)
        return schemas

    def get_tool_server(self, tool_name: str) -> str:
        return SERVER_NAME if tool_name in self._tools else "unknown"

    @property
    def tool_count(self) -> int:
        return len(self._tools)

    @property
    def server_names(self) -> list[str]:
        return [SERVER_NAME] if self._tools else []

    @property
    def server_tool_counts(self) -> dict[str, int]:
        return {SERVER_NAME: len(self._tools)} if self._tools else {}

    def is_write_tool(self, tool_name: str) -> bool | None:
        tool = self._tools.get(tool_name)
        if tool is None:
            return None
        return tool.is_write()

    async def close(self) -> None:  # noqa: D401 — matches protocol
        """No persistent state to close."""
        return None

    # -- call execution ----------------------------------------------------

    async def call_tool(self, name: str, arguments: dict) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return f"Error: unknown z3ed tool '{name}'"
        try:
            executable = self._locate_executable()
        except FileNotFoundError as exc:
            return f"Error: {exc}"

        # Pre-flight: mesen-* commands need a live mesen2-oos socket. If the
        # user supplied one explicitly via arguments we defer to that; else we
        # require RomProject to have found one. Returning a clear error here
        # beats letting z3ed exit with an opaque "socket failed" message.
        if tool.z3ed_name.startswith("mesen-"):
            # Match keys the way _build_argv renders them, so "_mesen_socket" can't dodge the guard.
            supplied_socket = next(
                (v for k, v in arguments.items() if self._to_snake(k) == "mesen_socket" and v),
                None,
            )
            if not supplied_socket:
                bootstrap_error = await self._ensure_mesen_socket()
                if bootstrap_error:
                    return bootstrap_error

        note = ""
        if tool.z3ed_name in _PC_OFFSET_COMMANDS:
            arguments, note = self._map_snes_address(arguments)
            if note.startswith("Error"):
                return note

        argv = self._build_argv(tool, arguments, executable)
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=self._call_timeout_s,
            )
        except asyncio.TimeoutError:
            return f"Error: z3ed {tool.z3ed_name} timed out after {self._call_timeout_s:.0f}s"
        except Exception as exc:  # noqa: BLE001 — surface any subprocess error
            return f"Error launching z3ed {tool.z3ed_name}: {exc}"

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = _strip_ansi(stderr_bytes.decode("utf-8", errors="replace")).strip()
        if proc.returncode not in (0, None):
            body = stderr or _strip_ansi(stdout).strip() or "(no output)"
            return f"Error: z3ed {tool.z3ed_name} exit={proc.returncode}: {body}"
        # Prefer stdout (JSON/text payload). Fold any stderr warning lines in.
        out = stdout.strip()
        if stderr:
            out = f"{out}\n[stderr] {stderr}" if out else f"[stderr] {stderr}"
        out = out or "(no output)"
        # Builds with the guarded writer report save_status; the unsaved ones only bytes_written.
        if (
            tool.z3ed_name in _UNSAVED_WRITE_COMMANDS
            and '"bytes_written"' in out
            and '"save_status"' not in out
        ):
            out += (
                f"\n[z3cli] z3ed {tool.z3ed_name} has reported success without saving the ROM "
                "(yaze 0.8.0). Re-read the bytes (hex-read) or compare file hashes before "
                "claiming the write landed."
            )
        if tool.z3ed_name == "rom-find-symbol" and '"not_found"' in out:
            name = str(arguments.get("name", ""))
            if name and not name.startswith("Oracle_"):
                out += (
                    "\n[z3cli] Symbols from asar namespaces carry their prefix in the .mlb; "
                    f"try name=Oracle_{name}."
                )
        return f"{note}\n{out}" if note else out

    @staticmethod
    def _map_snes_address(arguments: dict[str, Any]) -> tuple[dict[str, Any], str]:
        """Turn ``snes_address`` (or a ``BB:AAAA`` address) into a PC ``address``."""
        arguments = dict(arguments)
        snes = arguments.pop("snes_address", None)
        address = arguments.get("address")
        if snes is None and isinstance(address, str) and _BANK_COLON_ADDRESS.match(address.strip()):
            snes = address
        if snes is None:
            return arguments, ""
        try:
            pc = lorom_snes_to_pc(str(snes))
        except ValueError as exc:
            return arguments, f"Error: {exc}"
        arguments["address"] = f"0x{pc:06X}"
        return arguments, f"[z3cli] SNES {snes} -> PC 0x{pc:06X} (LoROM)"

    def _build_argv(
        self,
        tool: TranslatedTool,
        arguments: dict[str, Any],
        executable: Path,
    ) -> list[str]:
        argv: list[str] = [str(executable), tool.z3ed_name]

        # Only flags the command declares; anything else could smuggle in
        # undeclared mutators (--overwrite, --fix) past the write classification.
        declared = {self._to_snake(p.name) for p in tool.params}
        arguments = {k: v for k, v in arguments.items() if self._to_snake(k) in declared}

        # Auto-inject --rom for rom-dependent commands if not user-specified.
        supplied_names = {self._to_snake(k) for k in arguments.keys()}
        has_rom_arg = "rom" in supplied_names
        has_socket_arg = "mesen_socket" in supplied_names
        has_format_arg = "format" in supplied_names

        if tool.requires_rom and not has_rom_arg and self._project.rom_path:
            argv.append(f"--rom={self._project.rom_path}")

        # --symbols is a z3ed global flag, so it never appears in the declared params.
        if tool.z3ed_name in _SYMBOL_COMMANDS and self._project.symbols_mlb:
            argv.append(f"--symbols={self._project.symbols_mlb}")

        if (
            tool.z3ed_name.startswith("mesen-")
            and not has_socket_arg
            and self._project.mesen_socket
        ):
            argv.append(f"--mesen-socket={self._project.mesen_socket}")

        # Default --format=json when the tool accepts it.
        if not has_format_arg and any(p.name == "format" for p in tool.params):
            argv.append("--format=json")

        # Render user-supplied arguments.
        for key, value in arguments.items():
            snake = self._to_snake(key)
            # Skip already-injected keys.
            if snake == "rom" and has_rom_arg is False and tool.requires_rom:
                # User may supply 'rom' via auto-inject; keep user value if given.
                pass
            flag = f"--{snake.replace('_', '-')}"
            if isinstance(value, bool):
                if value:
                    argv.append(flag)
                # False-flags are simply omitted.
                continue
            if value is None:
                continue
            if snake in _HEX_PARSED_INT_FLAGS and isinstance(value, int):
                value = f"0x{value:X}"
            argv.append(f"{flag}={self._format_value(value)}")
        return argv

    async def _ensure_mesen_socket(self) -> str | None:
        """Ensure a Mesen2 socket exists, auto-bootstrapping when enabled.

        Returns an error string when no socket could be established.
        """
        current_socket = self._project.mesen_socket
        if current_socket:
            os.environ["MESEN2_SOCKET_PATH"] = current_socket
            return None

        self._project = self._project.refresh_mesen_socket()
        refreshed_socket = self._project.mesen_socket
        if refreshed_socket:
            os.environ["MESEN2_SOCKET_PATH"] = refreshed_socket
            return None

        if not self._auto_bootstrap_mesen:
            return (
                "Error: Mesen2 emulator socket not detected. Start Mesen2 "
                "(or mesen2-oos) first, or set MESEN2_SOCKET_PATH, then retry."
            )

        launch_script = self._project.mesen_launch_script()
        launch_rom = self._project.preferred_mesen_rom_path()
        if launch_script is None:
            return (
                "Error: Mesen2 emulator socket not detected and no launch script was found. "
                "Start Mesen2 (or mesen2-oos) first, or set MESEN2_SOCKET_PATH, then retry."
            )
        if launch_rom is None:
            return (
                "Error: Mesen2 emulator socket not detected and no ROM was available for auto-launch. "
                "Set --rom or Z3CLI_ROM, or start Mesen2 manually."
            )

        instance = os.environ.get("Z3CLI_MESEN_INSTANCE", f"z3cli-{self._project.workspace.name}")
        owner = os.environ.get("USER", "agent")
        source = os.environ.get("Z3CLI_MESEN_SOURCE", "z3cli")
        argv = [
            "bash",
            str(launch_script),
            "--instance", instance,
            "--owner", owner,
            "--source", source,
            "--rom", str(launch_rom),
            "--reuse",
        ]
        if os.environ.get("Z3CLI_MESEN_HEADLESS", "").lower() in {"1", "true", "yes", "on"}:
            argv.append("--headless")

        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=self._bootstrap_timeout_s,
            )
        except asyncio.TimeoutError:
            return (
                f"Error: Mesen2 auto-bootstrap timed out after {self._bootstrap_timeout_s:.0f}s. "
                "Start Mesen2 manually or set MESEN2_SOCKET_PATH."
            )
        except Exception as exc:  # noqa: BLE001
            return f"Error: Mesen2 auto-bootstrap failed to launch: {exc}"

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = _strip_ansi(stderr_bytes.decode("utf-8", errors="replace")).strip()
        if proc.returncode not in (0, None):
            detail = stderr or _strip_ansi(stdout).strip() or "(no output)"
            return f"Error: Mesen2 auto-bootstrap failed: {detail}"

        exported_socket = self._parse_export(stdout, "MESEN2_SOCKET_PATH")
        exported_home = self._parse_export(stdout, "MESEN2_HOME")
        exported_instance = self._parse_export(stdout, "MESEN2_INSTANCE")
        if exported_home:
            os.environ["MESEN2_HOME"] = exported_home
        if exported_instance:
            os.environ["MESEN2_INSTANCE"] = exported_instance
        if exported_socket:
            os.environ["MESEN2_SOCKET_PATH"] = exported_socket
            self._project = self._project.with_mesen_socket(exported_socket)
            return None

        self._project = self._project.refresh_mesen_socket()
        if self._project.mesen_socket:
            os.environ["MESEN2_SOCKET_PATH"] = self._project.mesen_socket
            return None

        return (
            "Error: Mesen2 auto-bootstrap did not yield a socket path. "
            "Start Mesen2 manually or set MESEN2_SOCKET_PATH."
        )

    @staticmethod
    def _parse_export(output: str, name: str) -> str:
        match = re.search(rf'export {re.escape(name)}="([^"]+)"', output)
        if match is None:
            return ""
        return match.group(1).strip()

    @staticmethod
    def _to_snake(name: str) -> str:
        return name.replace("-", "_").strip("_")

    @staticmethod
    def _format_value(value: Any) -> str:
        if isinstance(value, (list, tuple)):
            return ",".join(str(v) for v in value)
        return str(value)
