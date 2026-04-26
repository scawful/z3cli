"""Minimal JSON-RPC inventory sidecar.

This process owns inventory probes and serves cached snapshots over stdio.
It intentionally keeps the JSON-RPC surface aligned with the serve loop:
- inventory/query
- inventory/snapshot
- inventory/refresh
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from types import SimpleNamespace
from typing import Any

from core.config import (
    REGISTRY_PATH,
    load_llamacpp_nodes,
    load_registry,
    load_studio_nodes,
)
from services.inventory.contract import inventory_query_response
from services.inventory.runtime import InventoryRuntime
from app.shared_runtime import available_route_targets
from services.router.route.contract import active_route_name


DEFAULT_INVENTORY_TTL_MS = int(os.environ.get("Z3CLI_INVENTORY_TTL_MS", "5000"))


def _write(obj: object) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _response(req_id: object, *, result: object | None = None, error: str | None = None) -> None:
    if error:
        payload = {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": error}}
    else:
        payload = {"jsonrpc": "2.0", "id": req_id, "result": result}
    _write(payload)


def _route_names_from_params(params: dict[str, object]) -> list[str]:
    for key in ("routeNames", "route_names"):
        value = params.get(key)
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
    route = str(params.get("route") or "").strip()
    return [route] if route else []


def _match_route_entry(entries: list[dict[str, object]], route_name: str) -> dict[str, object] | None:
    target = str(route_name or "").strip().lower()
    if not target:
        return None
    for entry in entries:
        aliases = entry.get("aliases") if isinstance(entry.get("aliases"), list) else []
        names = {
            str(entry.get("name") or "").lower(),
            str(entry.get("resolved") or "").lower(),
            *[str(alias).lower() for alias in aliases],
        }
        if target in names:
            return entry
    return None


def _active_route_entry(state: Any, entries: list[dict[str, object]]) -> dict[str, object] | None:
    try:
        active = active_route_name(state, entries)
    except Exception:
        active = ""
    if not active:
        return None
    for entry in entries:
        if str(entry.get("name") or "") == str(active):
            return entry
    return None


def _bool_param(params: dict[str, object], *names: str) -> bool:
    for name in names:
        value = params.get(name)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


async def _handle_inventory(
    runtime: InventoryRuntime,
    state: Any,
    req_id: object,
    method: str,
    params: dict[str, object],
) -> bool:
    if method not in {"inventory/query", "inventory/snapshot", "inventory/refresh"}:
        return False

    all_entries = available_route_targets(state, include_advanced=True)
    route_names = _route_names_from_params(params)
    entries: list[dict[str, object]] = []
    if route_names:
        for name in route_names:
            entry = _match_route_entry(all_entries, name)
            if entry is None:
                _response(req_id, error=f"Unknown route target: {name}")
                return True
            entries.append(entry)
    else:
        # Default semantics:
        # - inventory/query: all canonical routes (non-advanced)
        # - inventory/snapshot + inventory/refresh: active route only
        if method in {"inventory/snapshot", "inventory/refresh"}:
            canonical = available_route_targets(state, include_advanced=True)
            active_entry = _active_route_entry(state, canonical)
            entries = [active_entry] if active_entry is not None else []
        else:
            entries = available_route_targets(state, include_advanced=False)

    force = method == "inventory/refresh" or _bool_param(params, "forceRefresh", "force_refresh")
    snapshots = await runtime.refresh_all(state, entries, force_refresh=force)
    payload = inventory_query_response(snapshots)

    if method in {"inventory/snapshot", "inventory/refresh"}:
        _response(req_id, result=(snapshots[0] if snapshots else {}))
        return True
    _response(req_id, result=payload)
    return True


async def _run(runtime: InventoryRuntime, state: Any) -> int:
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    while True:
        line = await reader.readline()
        if not line:
            return 0
        try:
            req = json.loads(line.decode("utf-8"))
        except Exception:
            continue
        if not isinstance(req, dict):
            continue
        if req.get("jsonrpc") != "2.0":
            continue
        req_id = req.get("id")
        method = str(req.get("method") or "")
        params = req.get("params")
        params_dict = params if isinstance(params, dict) else {}
        try:
            handled = await _handle_inventory(runtime, state, req_id, method, params_dict)
        except Exception as exc:
            _response(req_id, error=str(exc))
            handled = True
        if not handled:
            _response(req_id, error=f"Unknown method: {method}")


def _load_state(registry_path: str) -> SimpleNamespace:
    models = load_registry(registry_path)
    studio_nodes = load_studio_nodes()
    llamacpp_nodes = load_llamacpp_nodes()
    return SimpleNamespace(
        backend_name="studio",
        models=models,
        studio_nodes=studio_nodes,
        llamacpp_nodes=llamacpp_nodes,
        studio_api_base="",
        llamacpp_api_base="",
        active_model="",
        studio_node="",
        llamacpp_node="",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="z3cli-inventoryd")
    parser.add_argument("--registry", default=str(REGISTRY_PATH))
    args = parser.parse_args(argv)

    state = _load_state(args.registry)
    runtime = InventoryRuntime.from_ttl_ms(ttl_ms=DEFAULT_INVENTORY_TTL_MS)
    runtime.start(state, entries_provider=lambda: available_route_targets(state, include_advanced=True))
    try:
        return asyncio.run(_run(runtime, state))
    finally:
        try:
            asyncio.run(runtime.stop())
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
