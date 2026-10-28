"""``workbench/*`` RPCs backing the Oracle Agent Manager client.

Emulators come from Mesen2-OOS status files (``mesen2-*.status``), models from
``~/models/registry.json`` plus LM Studio hosts, training from
``training/scripts/live_training_status.py``. Every call is bounded by a
timeout so a slow host never stalls the serve loop.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib import error, request

DEFAULT_STATUS_DIR = Path(os.environ.get("MESEN2_STATUS_DIR", "/tmp"))
DEFAULT_REGISTRY = Path.home() / "models" / "registry.json"
DEFAULT_TRAINING_SCRIPT = Path.home() / "src" / "training" / "scripts" / "live_training_status.py"
DEFAULT_LMSTUDIO_HOSTS = {
    "local": "http://127.0.0.1:1234",
    "mm": "http://medical-mechanica:1234",  # Tailscale only; MM firewall blocks other sources
}

# Argument-free socket commands; SAVESTATE/LOADSTATE need path validation first.
EMULATOR_COMMANDS = frozenset(
    {"PING", "HEALTH", "STATE", "FRAME", "PAUSE", "RESUME", "RESET", "SYMBOLS_RELOAD"},
)
_STATUS_KEYS = (
    "emulatorRunning", "paused", "romHash", "frameCount", "registeredAgents", "lastSave", "lastLoad",
)
TRAINING_CACHE_TTL_S = 30.0


class WorkbenchError(Exception):
    pass


def _pid_alive(pid: Any) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def list_emulators(status_dir: Path = DEFAULT_STATUS_DIR) -> list[dict[str, Any]]:
    """Mesen2 instances, newest status first; sockets without a status file are reported too."""
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    status_files = sorted(
        status_dir.glob("mesen2-*.status"), key=lambda p: p.stat().st_mtime, reverse=True,
    )
    for status in status_files:
        try:
            data = json.loads(status.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        socket_path = str(data.get("socketPath") or status.with_suffix(".sock"))
        seen.add(socket_path)
        pid = data.get("pid")
        alive = _pid_alive(pid)
        entry = {
            "name": status.stem.removeprefix("mesen2-"),
            "pid": pid,
            "alive": alive,
            "socket": socket_path,
            "socket_exists": Path(socket_path).exists(),
            "status_path": str(status),
            "status_age_s": round(time.time() - status.stat().st_mtime, 1),
        }
        entry.update({k: data.get(k) for k in _STATUS_KEYS})
        entries.append(entry)
    for sock in sorted(status_dir.glob("mesen2-*.sock")):
        if str(sock) in seen:
            continue
        entries.append({
            "name": sock.stem.removeprefix("mesen2-"),
            "pid": None,
            "alive": None,
            "socket": str(sock),
            "socket_exists": True,
            "status_path": None,
        })
    return entries


async def emulator_command(
    socket_path: str,
    command: str,
    *,
    status_dir: Path = DEFAULT_STATUS_DIR,
    timeout_s: float = 3.0,
) -> dict[str, Any]:
    command = str(command).upper()
    if command not in EMULATOR_COMMANDS:
        raise WorkbenchError(f"command not allowed: {command}")
    known = {e["socket"] for e in list_emulators(status_dir) if e.get("alive") is not False}
    if socket_path not in known:
        raise WorkbenchError(f"not a live Mesen2 socket: {socket_path}")
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(socket_path), timeout=timeout_s,
        )
    except (OSError, asyncio.TimeoutError) as exc:
        raise WorkbenchError(f"connect failed: {exc or 'timeout'}") from exc
    try:
        writer.write(json.dumps({"type": command}).encode() + b"\n")
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=timeout_s)
    except asyncio.TimeoutError as exc:
        raise WorkbenchError(f"{command} timed out after {timeout_s:.0f}s") from exc
    finally:
        writer.close()
    try:
        reply = json.loads(line)
    except ValueError as exc:
        raise WorkbenchError(f"unparseable reply: {line[:200]!r}") from exc
    return reply if isinstance(reply, dict) else {"reply": reply}


def list_registry_models(registry_path: Path = DEFAULT_REGISTRY) -> dict[str, Any]:
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"path": str(registry_path), "error": str(exc), "models": []}
    models = []
    for row in data.get("models") or []:
        if not isinstance(row, dict) or not row.get("name"):
            continue
        gguf, mlx = row.get("gguf_path"), row.get("mlx_path")
        models.append({
            "name": row["name"],
            "gguf_path": gguf,
            "gguf_exists": bool(gguf) and Path(gguf).exists(),
            "mlx_path": mlx,
            "mlx_exists": bool(mlx) and Path(mlx).exists(),
        })
    return {"path": str(registry_path), "updated": data.get("updated"), "models": models}


def _fetch_json(url: str, timeout_s: float, api_key: str | None) -> Any:
    req = request.Request(url)
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")
    with request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310 — configured hosts only
        return json.loads(resp.read())


async def lmstudio_models(
    hosts: dict[str, str] | None = None, *, timeout_s: float = 5.0,
) -> list[dict[str, Any]]:
    """Query each LM Studio host's ``/api/v0/models``; keys come from ``<HOST>_LMSTUDIO_API_KEY`` env."""
    hosts = hosts or _hosts_from_env()

    async def one(name: str, base: str) -> dict[str, Any]:
        api_key = os.environ.get(f"{name.upper().replace('-', '_')}_LMSTUDIO_API_KEY")
        url = base.rstrip("/") + "/api/v0/models"
        try:
            payload = await asyncio.to_thread(_fetch_json, url, timeout_s, api_key)
        except (error.URLError, OSError, ValueError) as exc:
            return {"host": name, "base_url": base, "reachable": False, "error": str(exc), "models": []}
        rows = payload.get("data", []) if isinstance(payload, dict) else []
        return {
            "host": name,
            "base_url": base,
            "reachable": True,
            "models": [
                {
                    "id": r.get("id"),
                    "type": r.get("type"),
                    "state": r.get("state"),
                    "loaded_context_length": r.get("loaded_context_length"),
                    "max_context_length": r.get("max_context_length"),
                }
                for r in rows if isinstance(r, dict)
            ],
        }

    return list(await asyncio.gather(*(one(n, b) for n, b in hosts.items())))


def _hosts_from_env() -> dict[str, str]:
    """``Z3CLI_LMSTUDIO_HOSTS="local=http://127.0.0.1:1234,mm=http://127.0.0.1:2234"``."""
    raw = os.environ.get("Z3CLI_LMSTUDIO_HOSTS", "")
    hosts = dict(
        part.split("=", 1) for part in raw.split(",") if "=" in part
    )
    return {k.strip(): v.strip() for k, v in hosts.items()} or dict(DEFAULT_LMSTUDIO_HOSTS)


class TrainingStatus:
    """Cached runner for ``live_training_status.py`` (it fans out over ssh/vastai)."""

    def __init__(self, script: Path = DEFAULT_TRAINING_SCRIPT, *, timeout_s: float = 45.0) -> None:
        self.script = script
        self.timeout_s = timeout_s
        self._cached: tuple[float, dict[str, Any]] | None = None
        self._lock = asyncio.Lock()

    async def get(self, *, refresh: bool = False) -> dict[str, Any]:
        async with self._lock:
            if not refresh and self._cached and time.monotonic() - self._cached[0] < TRAINING_CACHE_TTL_S:
                return {**self._cached[1], "cached": True}
            result = await self._run()
            self._cached = (time.monotonic(), result)
            return {**result, "cached": False}

    async def _run(self) -> dict[str, Any]:
        if not self.script.exists():
            return {"error": f"missing {self.script}", "runs": []}
        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(self.script),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=self.timeout_s)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {"error": f"timed out after {self.timeout_s:.0f}s", "runs": []}
        if proc.returncode != 0:
            return {"error": err.decode(errors="replace").strip()[-500:] or f"exit {proc.returncode}", "runs": []}
        try:
            return json.loads(out)
        except ValueError:
            return {"error": "unparseable output", "runs": []}


_training = TrainingStatus()


async def dispatch(method: str, params: dict[str, Any] | None) -> Any:
    """Handle one ``workbench/<name>`` request; raises WorkbenchError on bad input."""
    params = params if isinstance(params, dict) else {}
    name = method.removeprefix("workbench/")
    if name == "emulators":
        return list_emulators()
    if name == "emulator_command":
        return await emulator_command(str(params.get("socket", "")), str(params.get("command", "")))
    if name == "models":
        local, hosts = list_registry_models(), await lmstudio_models()
        return {"registry": local, "lmstudio": hosts}
    if name == "training":
        return await _training.get(refresh=bool(params.get("refresh")))
    raise WorkbenchError(f"Unknown method: {method}")
