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
import os
import re
import shutil
from pathlib import Path
from typing import Any

from z3cli.core.rom_project import RomProject
from z3cli.protocol.z3ed_schema import TranslatedTool, load_schemas


SERVER_NAME = "z3ed"
DEFAULT_CONNECT_TIMEOUT_S = 30.0
DEFAULT_CALL_TIMEOUT_S = 120.0
DEFAULT_BOOTSTRAP_TIMEOUT_S = 60.0


_ANSI_ESCAPE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


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
        return [tool.openai_schema for tool in self._tools.values()]

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
            supplied_socket = arguments.get("mesen_socket") or arguments.get("mesen-socket")
            if not supplied_socket:
                bootstrap_error = await self._ensure_mesen_socket()
                if bootstrap_error:
                    return bootstrap_error

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
        return out or "(no output)"

    def _build_argv(
        self,
        tool: TranslatedTool,
        arguments: dict[str, Any],
        executable: Path,
    ) -> list[str]:
        argv: list[str] = [str(executable), tool.z3ed_name]

        # Auto-inject --rom for rom-dependent commands if not user-specified.
        supplied_names = {self._to_snake(k) for k in arguments.keys()}
        has_rom_arg = "rom" in supplied_names
        has_socket_arg = "mesen_socket" in supplied_names
        has_format_arg = "format" in supplied_names

        if tool.requires_rom and not has_rom_arg and self._project.rom_path:
            argv.append(f"--rom={self._project.rom_path}")

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
