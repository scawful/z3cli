"""Inventory client seam for the serve loop.

Today the serve loop can host the inventory runtime in-process. Later this
module can swap to an out-of-process inventory daemon without changing request
handlers.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
from typing import Any

from app.shared_runtime import available_route_targets
from services.router.route.contract import active_route_name
from services.inventory.runtime import InventoryRuntime, refresh_inventory_snapshot, inventory_snapshot_for_entry


_SIDECAR_ENV = "Z3CLI_INVENTORY_TRANSPORT"
_SIDECAR_ENABLED_VALUES = {"sidecar", "daemon", "subprocess"}
_INPROCESS_VALUES = {"inprocess", "in-process", "local"}
_AUTO_VALUES = {"auto", ""}


def _source_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if parent.name == "src" and (parent / "app").is_dir():
            return parent
    return Path.cwd()


class _InventorySidecarClient:
    def __init__(self, *, registry_path: str = "", timeout_s: float = 6.0) -> None:
        self._registry_path = str(registry_path or "").strip()
        self._timeout_s = max(0.5, float(timeout_s))
        self._proc: asyncio.subprocess.Process | None = None
        self._reader: asyncio.StreamReader | None = None
        self._lock = asyncio.Lock()
        self._next_id = 1

    async def close(self) -> None:
        proc = self._proc
        self._proc = None
        self._reader = None
        if proc is None:
            return
        try:
            if proc.stdin is not None:
                proc.stdin.close()
                try:
                    await proc.stdin.wait_closed()
                except Exception:
                    pass
            if proc.returncode is None:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=1.0)
                return
        except Exception:
            pass
        try:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
        except Exception:
            pass

    async def _ensure_started(self) -> None:
        if self._proc is not None and self._proc.returncode is None and self._reader is not None:
            return

        await self.close()

        env = dict(os.environ)
        src_root = _source_root()
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{src_root}{os.pathsep}{existing}" if existing else str(src_root)

        argv: list[str] = [sys.executable, "-m", "services.inventory.daemon.main"]
        if self._registry_path:
            argv.extend(["--registry", self._registry_path])

        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        if proc.stdin is None or proc.stdout is None:
            raise RuntimeError("inventory sidecar failed to attach stdio")
        self._proc = proc
        self._reader = proc.stdout

    async def request(self, method: str, params: dict[str, object] | None = None) -> object:
        async with self._lock:
            await self._ensure_started()
            proc = self._proc
            reader = self._reader
            if proc is None or proc.stdin is None or reader is None:
                raise RuntimeError("inventory sidecar is not running")

            req_id = self._next_id
            self._next_id += 1
            payload: dict[str, object] = {"jsonrpc": "2.0", "id": req_id, "method": method}
            if params is not None:
                payload["params"] = params
            line = json.dumps(payload, ensure_ascii=False) + "\n"
            proc.stdin.write(line.encode("utf-8"))
            await proc.stdin.drain()

            deadline = self._timeout_s
            while True:
                if proc.returncode is not None:
                    raise RuntimeError(f"inventory sidecar exited (exit={proc.returncode})")
                raw = await asyncio.wait_for(reader.readline(), timeout=deadline)
                if not raw:
                    raise RuntimeError("inventory sidecar closed stdout")
                try:
                    msg = json.loads(raw.decode("utf-8"))
                except Exception:
                    continue
                if not isinstance(msg, dict):
                    continue
                if msg.get("id") != req_id:
                    continue
                if "error" in msg and isinstance(msg["error"], dict):
                    raise RuntimeError(str(msg["error"].get("message") or "inventory sidecar error"))
                return msg.get("result")


class InventoryClient:
    def __init__(self, state: Any):
        self._state = state
        self._transport = self._select_transport()

        runtime = getattr(state, "inventory_runtime", None)
        if runtime is None:
            ttl_ms = int(getattr(state, "inventory_ttl_ms", 5000) or 5000)
            existing_cache = getattr(state, "inventory_cache", None)
            if existing_cache is not None:
                runtime = InventoryRuntime(cache=existing_cache, poll_interval_s=max(0.5, ttl_ms / 1000.0))
            else:
                runtime = InventoryRuntime.from_ttl_ms(ttl_ms=ttl_ms)
            setattr(state, "inventory_runtime", runtime)
        self._runtime: InventoryRuntime = runtime
        setattr(state, "inventory_cache", self._runtime.cache)

    @property
    def cache(self):
        return self._runtime.cache

    async def refresh_entry(self, entry: dict[str, object]) -> dict[str, object]:
        if self._transport == "sidecar":
            return await self._sidecar_snapshot(entry, force_refresh=True)

        if self._is_active_entry(entry):
            from app import serve as serve_mod

            backend = serve_mod.get_backend(self._state)
            status_result, loaded_result = await backend.check_connection(), await backend.list_loaded_model_details()
            connected = bool(getattr(status_result, "connected", False))
            detail = str(getattr(status_result, "detail", "") or "")
            loaded = [item for item in loaded_result if isinstance(item, dict)]
            from services.inventory.contract import inventory_snapshot

            snapshot = inventory_snapshot(
                self._state,
                entry,
                loaded_models=loaded,
                connected=connected,
                detail=detail,
                ttl_ms=self._runtime.cache.ttl_ms,
                generation=self._runtime.cache.generation,
            )
            return self._runtime.cache.put(str(entry.get("name") or "active"), snapshot)
        return await refresh_inventory_snapshot(self._state, entry, cache=self._runtime.cache)

    async def snapshot_for_entry(
        self,
        entry: dict[str, object],
        *,
        force_refresh: bool = False,
    ) -> dict[str, object]:
        if self._transport == "sidecar":
            return await self._sidecar_snapshot(entry, force_refresh=force_refresh)

        if force_refresh and self._is_active_entry(entry):
            return await self.refresh_entry(entry)
        return await inventory_snapshot_for_entry(
            self._state,
            entry,
            cache=self._runtime.cache,
            force_refresh=force_refresh,
        )

    async def snapshots_for_entries(
        self,
        entries: list[dict[str, object]],
        *,
        force_refresh: bool = False,
    ) -> list[dict[str, object]]:
        if self._transport == "sidecar":
            return await self._sidecar_query(entries, force_refresh=force_refresh)

        if not force_refresh:
            return [await self.snapshot_for_entry(entry, force_refresh=False) for entry in entries]
        return [await self.snapshot_for_entry(entry, force_refresh=True) for entry in entries]

    def _select_transport(self) -> str:
        requested = str(getattr(self._state, "inventory_transport", "") or os.environ.get(_SIDECAR_ENV, "")).strip()
        lowered = requested.lower()
        if lowered in _AUTO_VALUES:
            # Prefer sidecar by default; fallback is handled per-request.
            return "sidecar"
        if lowered in _INPROCESS_VALUES:
            return "inprocess"
        if lowered in _SIDECAR_ENABLED_VALUES:
            return "sidecar"
        return "inprocess"

    def _sidecar(self) -> _InventorySidecarClient:
        client = getattr(self._state, "inventory_sidecar_client", None)
        if isinstance(client, _InventorySidecarClient):
            return client
        registry_path = getattr(self._state, "registry_path", "") or ""
        timeout_s = float(getattr(self._state, "inventory_sidecar_timeout_s", 6.0) or 6.0)
        client = _InventorySidecarClient(registry_path=str(registry_path), timeout_s=timeout_s)
        setattr(self._state, "inventory_sidecar_client", client)
        return client

    async def _sidecar_snapshot(self, entry: dict[str, object], *, force_refresh: bool) -> dict[str, object]:
        route_name = str(entry.get("name") or "").strip()
        method = "inventory/refresh" if force_refresh else "inventory/snapshot"
        params: dict[str, object] = {"route": route_name} if route_name else {}
        try:
            result = await self._sidecar().request(method, params)
        except Exception:
            # Deterministic fallback: sidecar is optional until router extraction.
            return await inventory_snapshot_for_entry(
                self._state,
                entry,
                cache=self._runtime.cache,
                force_refresh=force_refresh,
            )
        return result if isinstance(result, dict) else {}

    async def _sidecar_query(self, entries: list[dict[str, object]], *, force_refresh: bool) -> list[dict[str, object]]:
        route_names = [str(e.get("name") or "").strip() for e in entries if str(e.get("name") or "").strip()]
        params: dict[str, object] = {"routeNames": route_names} if route_names else {}
        if force_refresh:
            params["forceRefresh"] = True
        try:
            result = await self._sidecar().request("inventory/query", params)
        except Exception:
            # Fallback to local runtime; keep behavior consistent with earlier implementation.
            return [await self.snapshot_for_entry(entry, force_refresh=force_refresh) for entry in entries]
        if isinstance(result, dict):
            snapshots = result.get("snapshots")
            if isinstance(snapshots, list):
                return [item for item in snapshots if isinstance(item, dict)]
        return []

    def _is_active_entry(self, entry: dict[str, object]) -> bool:
        try:
            entries = available_route_targets(self._state, include_advanced=True)
            active = active_route_name(self._state, entries)
            return str(entry.get("name") or "") == str(active or "")
        except Exception:
            return False


async def close_inventory_sidecar(state: Any) -> None:
    client = getattr(state, "inventory_sidecar_client", None)
    if not isinstance(client, _InventorySidecarClient):
        return
    setattr(state, "inventory_sidecar_client", None)
    await client.close()
