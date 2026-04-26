"""Proto-JSON shaped inventory contract helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services.router.route.contract import endpoint, model_ref, route_from_entry, serving_backend_enum


def timestamp_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def health_state(connected: bool | None, *, refreshing: bool = False) -> str:
    if refreshing:
        return "HEALTH_STATE_REFRESHING"
    if connected is True:
        return "HEALTH_STATE_HEALTHY"
    if connected is False:
        return "HEALTH_STATE_UNAVAILABLE"
    return "HEALTH_STATE_UNKNOWN"


def loaded_model_from_runtime(state: Any, item: dict[str, Any], *, backend: str) -> dict[str, Any]:
    identifier = str(item.get("identifier") or item.get("runtime_id") or "")
    model_key = str(item.get("model_key") or identifier)
    return {
        "ref": model_ref(state, model_key, backend=backend),
        "runtimeId": identifier,
        "displayName": str(item.get("display_name") or identifier or model_key),
        "backend": serving_backend_enum(backend),
        "health": "HEALTH_STATE_HEALTHY",
        "sizeBytes": int(item.get("size_bytes") or 0),
        "architecture": str(item.get("architecture") or ""),
        "quantization": str(item.get("quantization") or ""),
        "contextLength": int(item.get("context_length") or 0),
        "maxContextLength": int(item.get("max_context_length") or 0),
        "parallel": int(item.get("parallel") or 0),
        "queued": int(item.get("queued") or 0),
        "estimatedGpuBytes": int(item.get("estimated_gpu_bytes") or 0),
        "estimatedTotalBytes": int(item.get("estimated_total_bytes") or 0),
    }


def configured_model_from_route(state: Any, route_entry: dict[str, object]) -> dict[str, Any]:
    name = str(route_entry.get("model") or "")
    models = getattr(state, "models", {})
    model = models.get(name) if isinstance(models, dict) else None
    aliases = getattr(model, "aliases", []) if model is not None else []
    tags = getattr(model, "tags", []) if model is not None else []
    return {
        "ref": model_ref(state, name, backend=str(route_entry.get("backend") or "")),
        "displayName": str(getattr(model, "description", "") or name),
        "role": str(getattr(model, "role", "") or ""),
        "aliases": [str(alias) for alias in aliases] if isinstance(aliases, list) else [],
        "tags": [str(tag) for tag in tags] if isinstance(tags, list) else [],
        "local": bool(getattr(model, "is_local", True)),
        "hidden": bool(getattr(model, "spawn_only", False) or getattr(model, "visibility", "") == "hidden"),
        "selectable": True,
        "toolsEnabled": bool(getattr(model, "tools_enabled", False)),
        "contextTokens": int(getattr(model, "context_budget", 0) or 0),
        "maxTokens": int(getattr(model, "max_tokens", 0) or 0),
    }


def inventory_snapshot(
    state: Any,
    route_entry: dict[str, object],
    *,
    loaded_models: list[dict[str, Any]] | None = None,
    connected: bool | None = None,
    detail: str = "",
    ttl_ms: int = 5000,
    generation: int = 0,
) -> dict[str, Any]:
    backend = str(route_entry.get("backend") or getattr(state, "backend_name", ""))
    route = route_from_entry(state, route_entry)
    health = health_state(connected)
    detail_text = str(detail or "")
    route["health"] = health
    route["detail"] = detail_text or str(route.get("detail") or "")
    return {
        "source": str(route_entry.get("name") or "active"),
        "endpoint": route.get("inferenceEndpoint") or endpoint(backend=backend),
        "health": health,
        "detail": detail_text,
        "route": route,
        "routeEntry": dict(route_entry),
        "availableModels": [configured_model_from_route(state, route_entry)],
        "loadedModels": [
            loaded_model_from_runtime(state, item, backend=backend)
            for item in (loaded_models or [])
            if isinstance(item, dict)
        ],
        "observedAt": timestamp_now(),
        "ttlMs": int(ttl_ms),
        "generation": int(generation),
    }


def inventory_query_response(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    return {"snapshots": snapshots}
