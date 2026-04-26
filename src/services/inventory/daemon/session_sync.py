"""Apply session/active context from a parent process (serve loop or router daemon)."""

from __future__ import annotations

from typing import Any


def apply_session_sync(state: Any, params: dict[str, object]) -> None:
    """Update inventory daemon state to mirror ServeState routing fields.

    Expected shape matches ``app.serve._route_list_payload`` ``active`` block plus optional
    ``activeRoute`` / ``active_route`` (canonical route name).
    """
    active = params.get("active")
    if isinstance(active, dict):
        if "backend" in active:
            raw = str(active.get("backend") or "").strip().lower()
            if raw:
                state.backend_name = raw
        if "model" in active:
            state.active_model = str(active.get("model") or "")
        if "studio_node" in active:
            state.studio_node = str(active.get("studio_node") or "")
        if "llamacpp_node" in active:
            state.llamacpp_node = str(active.get("llamacpp_node") or "")
