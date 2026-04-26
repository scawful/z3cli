"""Proto-JSON shaped route contract helpers.

The Python serve loop still owns the current route state. These helpers keep
the JSON payloads aligned with proto/routes.proto without requiring generated
protobuf bindings in the runtime path.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


_BACKEND_ENUMS = {
    "studio": "SERVING_BACKEND_STUDIO",
    "llamacpp": "SERVING_BACKEND_LLAMACPP",
    "openai": "SERVING_BACKEND_OPENAI",
    "ssh_openai": "SERVING_BACKEND_SSH_OPENAI",
    "vllm": "SERVING_BACKEND_VLLM",
}
_UNKNOWN_HEALTH = "HEALTH_STATE_UNKNOWN"


def serving_backend_enum(backend: str) -> str:
    return _BACKEND_ENUMS.get(str(backend or "").strip().lower(), "SERVING_BACKEND_UNSPECIFIED")


def model_ref(state: Any, model_name: str, *, backend: str = "") -> dict[str, str]:
    name = str(model_name or "").strip()
    models = getattr(state, "models", {})
    model = models.get(name) if isinstance(models, dict) else None
    if model is None and isinstance(models, dict):
        for candidate_name, candidate in models.items():
            candidate_id = str(getattr(candidate, "model_id", "") or "")
            aliases = getattr(candidate, "aliases", [])
            alias_set = {str(alias) for alias in aliases} if isinstance(aliases, list) else set()
            if name == candidate_id or name in alias_set:
                name = str(getattr(candidate, "name", "") or candidate_name)
                model = candidate
                break
    return {
        "name": name,
        "modelId": str(getattr(model, "model_id", "") or name),
        "provider": str(getattr(model, "provider", "") or backend or ""),
    }


def endpoint(uri: str = "", *, node_name: str = "", backend: str = "") -> dict[str, str]:
    parsed = urlparse(str(uri or ""))
    host_alias = parsed.hostname or ""
    return {
        "uri": str(uri or ""),
        "hostAlias": host_alias,
        "nodeName": str(node_name or ""),
        "backend": serving_backend_enum(backend),
    }


def _route_endpoint(state: Any, entry: dict[str, object]) -> dict[str, str]:
    backend = str(entry.get("backend") or "")
    resolved = str(entry.get("resolved") or entry.get("name") or "")
    if backend == "studio":
        node = getattr(state, "studio_nodes", {}).get(resolved)
        uri = str(getattr(node, "api_base", "") or getattr(state, "studio_api_base", ""))
        node_name = str(getattr(node, "name", "") or resolved)
        return endpoint(uri, node_name=node_name, backend=backend)
    if backend == "llamacpp":
        node = getattr(state, "llamacpp_nodes", {}).get(resolved)
        uri = str(getattr(node, "api_base", "") or getattr(state, "llamacpp_api_base", ""))
        node_name = str(getattr(node, "name", "") or resolved)
        return endpoint(uri, node_name=node_name, backend=backend)
    return endpoint(backend=backend)


def _control_endpoint(state: Any, entry: dict[str, object]) -> dict[str, str]:
    if str(entry.get("backend") or "") != "studio":
        return endpoint()
    resolved = str(entry.get("resolved") or entry.get("name") or "")
    node = getattr(state, "studio_nodes", {}).get(resolved)
    hostd_url = str(getattr(node, "hostd_url", "") or "")
    if not hostd_url:
        return endpoint()
    return endpoint(hostd_url, node_name=resolved, backend="studio")


def route_from_entry(state: Any, entry: dict[str, object]) -> dict[str, object]:
    backend = str(entry.get("backend") or "")
    model_name = str(entry.get("model") or "")
    description = str(entry.get("description") or "")
    name = str(entry.get("name") or "").strip()
    aliases = entry.get("aliases")
    return {
        "name": name,
        "displayName": description or name,
        "model": model_ref(state, model_name, backend=backend),
        "backend": serving_backend_enum(backend),
        "inferenceEndpoint": _route_endpoint(state, entry),
        "controlEndpoint": _control_endpoint(state, entry),
        "aliases": [str(alias) for alias in aliases] if isinstance(aliases, list) else [],
        "autoLoad": backend == "studio",
        "preferred": name == "oracle-pro-5090",
        "health": _UNKNOWN_HEALTH,
        "detail": description,
        "generation": 0,
    }


def active_route_name(state: Any, entries: list[dict[str, object]]) -> str:
    backend = str(getattr(state, "backend_name", "") or "")
    active_node = (
        str(getattr(state, "studio_node", "") or "")
        if backend == "studio"
        else str(getattr(state, "llamacpp_node", "") or "")
    )
    active_model = str(getattr(state, "active_model", "") or getattr(state, "llamacpp_model", "") or "")
    for entry in entries:
        if str(entry.get("backend") or "") != backend:
            continue
        resolved = str(entry.get("resolved") or "")
        if active_node and resolved == active_node:
            return str(entry.get("name") or "")
    for entry in entries:
        if str(entry.get("backend") or "") == backend and str(entry.get("model") or "") == active_model:
            return str(entry.get("name") or "")
    return active_node or active_model


def list_routes_response(state: Any, entries: list[dict[str, object]]) -> dict[str, object]:
    return {
        "activeRoute": active_route_name(state, entries),
        "routes": [route_from_entry(state, entry) for entry in entries],
    }


def select_route_response(
    state: Any,
    result: dict[str, str],
    *,
    previous_route: str = "",
    message: str = "",
) -> dict[str, object]:
    entry = {
        "name": result.get("route") or result.get("target") or "",
        "kind": "route",
        "backend": result.get("backend") or "",
        "model": result.get("model") or "",
        "description": "",
        "resolved": result.get("resolved") or "",
        "aliases": [],
    }
    return {
        "accepted": True,
        "previousRoute": previous_route,
        "route": route_from_entry(state, entry),
        "message": message or f"Route set to {entry['name']}",
    }


def route_probe_response(smoke: dict[str, Any], *, route_name: str = "") -> dict[str, object]:
    applied = smoke.get("applied") if isinstance(smoke.get("applied"), dict) else {}
    resolved_route = route_name or str(applied.get("route") or applied.get("target") or smoke.get("node") or "")
    return {
        "route": resolved_route,
        "ok": bool(smoke.get("ok")),
        "matched": bool(smoke.get("matched")),
        "text": str(smoke.get("text") or ""),
        "durationMs": int(smoke.get("duration_ms") or 0),
        "error": str(smoke.get("error") or ""),
    }
