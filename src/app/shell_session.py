"""Persistent PTY-backed shell session used by z3cli commands."""

from __future__ import annotations

import asyncio
import os
import re
import shlex
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path


ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


@dataclass
class ShellRunResult:
    command: str
    output: str
    exit_code: int
    cwd: str
    duration_ms: int


class PersistentShellSession:
    def __init__(
        self,
        cwd: Path,
        *,
        shell: str | None = None,
        scrollback_limit: int = 50,
    ) -> None:
        self.cwd = cwd.expanduser().resolve()
        self.shell = shell or os.environ.get("SHELL") or os.environ.get("COMSPEC") or "/bin/zsh"
        self._proc: asyncio.subprocess.Process | None = None
        self._master_fd: int | None = None
        self._lock = asyncio.Lock()
        self._scrollback: deque[ShellRunResult] = deque(maxlen=scrollback_limit)

    @property
    def active(self) -> bool:
        return self._proc is not None and self._proc.returncode is None and self._master_fd is not None

    @property
    def scrollback(self) -> list[ShellRunResult]:
        return list(self._scrollback)

    async def ensure_started(self) -> None:
        # Windows has no stdlib termios/PTY support. The JSON-RPC backend still
        # imports this module on Windows for model/eval runs, so keep import
        # side effects portable and use one-shot subprocesses for shell commands
        # there instead of failing at import time.
        if os.name == "nt":
            return
        if self.active:
            return
        if self._proc is not None or self._master_fd is not None:
            await self.close()

        import pty

        master_fd, slave_fd = pty.openpty()
        env = dict(os.environ)
        env["TERM"] = env.get("TERM", "dumb")
        self._proc = await asyncio.create_subprocess_exec(
            self.shell,
            "-i",
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=str(self.cwd),
            env=env,
        )
        os.close(slave_fd)
        os.set_blocking(master_fd, False)
        self._master_fd = master_fd

        await asyncio.sleep(0.05)
        await self._drain_output()
        await self._run_internal(
            "export PS1='' ; export PROMPT='' ; export RPROMPT='' ; stty -echo 2>/dev/null || true",
            timeout_s=5.0,
            record=False,
        )
        await self._drain_output()

    async def _drain_output(self) -> str:
        if self._master_fd is None:
            return ""
        chunks: list[str] = []
        while True:
            try:
                chunk = os.read(self._master_fd, 4096)
            except BlockingIOError:
                break
            if not chunk:
                break
            chunks.append(chunk.decode("utf-8", errors="replace"))
        return self._sanitize("".join(chunks))

    def _write(self, text: str) -> None:
        if self._master_fd is None:
            raise RuntimeError("shell session is not active")
        os.write(self._master_fd, text.encode("utf-8"))

    async def _read_until(self, marker: str, timeout_s: float) -> str:
        if self._master_fd is None:
            raise RuntimeError("shell session is not active")
        deadline = time.monotonic() + timeout_s
        chunks: list[str] = []
        while time.monotonic() < deadline:
            try:
                chunk = os.read(self._master_fd, 4096)
            except BlockingIOError:
                await asyncio.sleep(0.02)
                continue
            if not chunk:
                await asyncio.sleep(0.02)
                continue
            decoded = chunk.decode("utf-8", errors="replace")
            chunks.append(decoded)
            joined = "".join(chunks)
            if marker in joined:
                return self._sanitize(joined)
        raise TimeoutError(f"Timed out waiting for shell marker {marker}")

    def _sanitize(self, text: str) -> str:
        return ANSI_RE.sub("", text.replace("\r", ""))

    async def _run_internal(
        self,
        command: str,
        *,
        timeout_s: float,
        record: bool,
    ) -> ShellRunResult:
        if os.name == "nt":
            return await self._run_windows_internal(
                command,
                timeout_s=timeout_s,
                record=record,
            )
        await self.ensure_started()
        marker = f"__Z3CLI_SHELL_{uuid.uuid4().hex}__"
        wrapped = (
            f"{command}\n"
            f"printf '\\n{marker}:%s\\n' \"$?\"\n"
            "pwd\n"
            f"printf '{marker}_END\\n'\n"
        )
        started = time.perf_counter()
        self._write(wrapped)
        raw = await self._read_until(f"{marker}_END", timeout_s)
        before, sep, tail = raw.rpartition(f"{marker}:")
        if not sep:
            raise RuntimeError("shell marker missing from command output")
        exit_line, _, remainder = tail.partition("\n")
        try:
            exit_code = int(exit_line.strip() or "1")
        except ValueError:
            exit_code = 1
        cwd_block, _, _ = remainder.partition(f"{marker}_END")
        cwd_lines = [line.strip() for line in cwd_block.splitlines() if line.strip()]
        cwd = cwd_lines[-1] if cwd_lines else str(self.cwd)
        output = before.strip("\n")
        resolved_cwd = str(Path(cwd).expanduser().resolve())
        result = ShellRunResult(
            command=command,
            output=output,
            exit_code=exit_code,
            cwd=resolved_cwd,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        self.cwd = Path(resolved_cwd)
        if record:
            self._scrollback.append(result)
        await self._drain_output()
        return result

    async def _run_windows_internal(
        self,
        command: str,
        *,
        timeout_s: float,
        record: bool,
    ) -> ShellRunResult:
        started = time.perf_counter()
        builtin_result = self._run_windows_builtin(command, started_at=started)
        if builtin_result is not None:
            if record:
                self._scrollback.append(builtin_result)
            return builtin_result

        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(self.cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        except asyncio.TimeoutError:
            proc.kill()
            stdout, _ = await proc.communicate()
            output = stdout.decode("utf-8", errors="replace") if stdout else ""
            result = ShellRunResult(
                command=command,
                output=self._sanitize(output).strip(),
                exit_code=124,
                cwd=str(self.cwd),
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
            if record:
                self._scrollback.append(result)
            return result

        output = stdout.decode("utf-8", errors="replace") if stdout else ""
        result = ShellRunResult(
            command=command,
            output=self._sanitize(output).strip(),
            exit_code=int(proc.returncode or 0),
            cwd=str(self.cwd),
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        if record:
            self._scrollback.append(result)
        return result

    def _run_windows_builtin(self, command: str, *, started_at: float) -> ShellRunResult | None:
        stripped = command.strip()
        lowered = stripped.lower()
        if lowered in {"pwd", "cd"}:
            return ShellRunResult(
                command=command,
                output=str(self.cwd),
                exit_code=0,
                cwd=str(self.cwd),
                duration_ms=int((time.perf_counter() - started_at) * 1000),
            )
        if not (lowered.startswith("cd ") or lowered.startswith("chdir ")):
            return None

        try:
            parts = shlex.split(stripped)
        except ValueError:
            parts = stripped.split(maxsplit=1)
        if len(parts) < 2:
            return None
        args = parts[1:]
        if args and args[0].lower() == "/d":
            args = args[1:]
        if len(args) != 1:
            return None

        target = Path(args[0]).expanduser()
        if not target.is_absolute():
            target = self.cwd / target
        try:
            resolved = target.resolve()
        except OSError:
            resolved = target.absolute()
        if not resolved.exists() or not resolved.is_dir():
            return ShellRunResult(
                command=command,
                output=f"The system cannot find the path specified: {target}",
                exit_code=1,
                cwd=str(self.cwd),
                duration_ms=int((time.perf_counter() - started_at) * 1000),
            )

        self.cwd = resolved
        return ShellRunResult(
            command=command,
            output="",
            exit_code=0,
            cwd=str(self.cwd),
            duration_ms=int((time.perf_counter() - started_at) * 1000),
        )

    async def run(self, command: str, timeout_s: float = 30.0) -> ShellRunResult:
        async with self._lock:
            return await self._run_internal(command, timeout_s=timeout_s, record=True)

    async def chdir(self, path: Path) -> ShellRunResult:
        if os.name == "nt":
            started = time.perf_counter()
            resolved = path.expanduser().resolve()
            self.cwd = resolved
            result = ShellRunResult(
                command=f"cd {resolved}",
                output="",
                exit_code=0,
                cwd=str(resolved),
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
            self._scrollback.append(result)
            return result
        quoted = shlex.quote(str(path.expanduser().resolve()))
        return await self.run(f"cd {quoted}")

    async def close(self) -> None:
        if os.name == "nt":
            return
        proc = self._proc
        fd = self._master_fd
        self._proc = None
        self._master_fd = None
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if proc is not None and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
