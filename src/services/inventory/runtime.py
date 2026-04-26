"""Inventory polling runtime.

This module is the service-owned home for probing configured routes and producing
proto-JSON shaped `InventorySnapshot` payloads. The serve loop may host this
in-process today, and later replace the caller with an out-of-process daemon.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Callable
from urllib.parse import urlparse

from app.backends import LMStudioBackend, LlamaCppBackend
from services.inventory.cache import InventoryCache
from services.inventory.contract import inventory_snapshot


def _parse_host_port(api_base: str) -> tuple[str, int]:
    parsed = urlparse(str(api_base or ""))
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 1234
    return host, int(port)


def backend_for_route_entry(state: Any, entry: dict[str, object]) -> LMStudioBackend | LlamaCppBackend:
    backend = str(entry.get("backend") or "").strip().lower()
    resolved = str(entry.get("resolved") or entry.get("name") or "").strip()

    if backend == "llamacpp":
        nodes = getattr(state, "llamacpp_nodes", {}) or {}
        node = nodes.get(resolved) if isinstance(nodes, dict) else None
        api_base = str(getattr(node, "api_base", "") or getattr(state, "llamacpp_api_base", "") or "")
        model = str(getattr(node, "model", "") or entry.get("model") or "")
        return LlamaCppBackend(api_base=api_base, model=model)

    nodes = getattr(state, "studio_nodes", {}) or {}
    node = nodes.get(resolved) if isinstance(nodes, dict) else None
    api_base = str(getattr(node, "api_base", "") or getattr(state, "studio_api_base", "") or "")
    host, port = _parse_host_port(api_base)
    return LMStudioBackend(api_base=api_base, host=host, port=port)


async def refresh_inventory_snapshot(
    state: Any,
    entry: dict[str, object],
    *,
    cache: InventoryCache,
) -> dict[str, object]:
    source = str(entry.get("name") or "active")
    backend = backend_for_route_entry(state, entry)
    status_result, loaded_result = await asyncio.gather(
        backend.check_connection(),
        backend.list_loaded_model_details(),
        return_exceptions=True,
    )
    connected: bool | None = None
    detail = ""
    if isinstance(status_result, Exception):
        connected = False
        detail = str(status_result)[:200]
    else:
        connected = bool(getattr(status_result, "connected", False))
        detail = str(getattr(status_result, "detail", "") or "")

    loaded: list[dict[str, Any]] = []
    if isinstance(loaded_result, Exception):
        detail = (detail + f"; loaded model probe failed: {loaded_result}").strip("; ")
    else:
        loaded = [item for item in loaded_result if isinstance(item, dict)]

    snapshot = inventory_snapshot(
        state,
        entry,
        loaded_models=loaded,
        connected=connected,
        detail=detail,
        ttl_ms=cache.ttl_ms,
        generation=cache.generation,
    )
    return cache.put(source, snapshot)


async def inventory_snapshot_for_entry(
    state: Any,
    entry: dict[str, object],
    *,
    cache: InventoryCache,
    force_refresh: bool = False,
) -> dict[str, object]:
    source = str(entry.get("name") or "active")
    cached = None if force_refresh else cache.get(source)
    if cached is not None:
        return cached
    if force_refresh:
        return await refresh_inventory_snapshot(state, entry, cache=cache)
    stale = cache.get(source, allow_stale=True)
    if stale is not None:
        return stale
    return inventory_snapshot(
        state,
        entry,
        connected=None,
        detail="route is configured but has no cached inventory snapshot",
        ttl_ms=cache.ttl_ms,
        generation=cache.generation,
    )


@dataclass
class InventoryRuntime:
    """Polls configured route inventory into an `InventoryCache`."""

    cache: InventoryCache
    poll_interval_s: float = 5.0
    _task: asyncio.Task[None] | None = None
    _stop: asyncio.Event | None = None

    @classmethod
    def from_ttl_ms(cls, *, ttl_ms: int, poll_interval_ms: int | None = None) -> "InventoryRuntime":
        interval_s = float(poll_interval_ms) / 1000.0 if poll_interval_ms is not None else max(1.0, ttl_ms / 1000.0)
        return cls(cache=InventoryCache(ttl_ms=ttl_ms), poll_interval_s=max(0.5, interval_s))

    async def refresh_all(
        self,
        state: Any,
        entries: list[dict[str, object]],
        *,
        force_refresh: bool = False,
    ) -> list[dict[str, object]]:
        snapshots: list[dict[str, object]] = []
        for entry in entries:
            snapshots.append(
                await inventory_snapshot_for_entry(
                    state,
                    entry,
                    cache=self.cache,
                    force_refresh=force_refresh,
                )
            )
        return snapshots

    def start(
        self,
        state: Any,
        *,
        entries_provider: Callable[[], list[dict[str, object]]],
    ) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(self._run_loop(state, entries_provider=entries_provider))

    async def stop(self) -> None:
        task = self._task
        if task is None:
            return
        if self._stop is not None:
            self._stop.set()
        await asyncio.gather(task, return_exceptions=True)
        self._task = None
        self._stop = None

    async def _run_loop(
        self,
        state: Any,
        *,
        entries_provider: Callable[[], list[dict[str, object]]],
    ) -> None:
        stop = self._stop or asyncio.Event()
        while not stop.is_set():
            try:
                entries = entries_provider()
                if not isinstance(entries, list):
                    entries = []
                await self.refresh_all(state, entries, force_refresh=True)
            except Exception:
                # Best-effort background loop: callers surface health via the cache.
                pass
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.poll_interval_s)
            except asyncio.TimeoutError:
                continue


def minimal_inventory_state(
    *,
    models: dict[str, object],
    studio_nodes: dict[str, object],
    llamacpp_nodes: dict[str, object],
    studio_api_base: str = "",
    llamacpp_api_base: str = "",
) -> SimpleNamespace:
    """Create a minimal state object expected by contract helpers."""

    return SimpleNamespace(
        backend_name="studio",
        models=models,
        studio_nodes=studio_nodes,
        llamacpp_nodes=llamacpp_nodes,
        studio_api_base=studio_api_base,
        llamacpp_api_base=llamacpp_api_base,
    )
