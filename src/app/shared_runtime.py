"""Shared runtime helpers for z3cli entrypoints."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import os
import re
import time
from typing import Any

from app.backends import LMStudioBackend, LlamaCppBackend
from app.shell_session import PersistentShellSession
from app.runtime import (
    blocked_model_reason,
    current_model_name,
    engine_key,
    load_focus_file,
    load_enriched_focus_file,
    normalize_lsp_context_mode,
    normalize_mode,
    resolve_existing_model_name,
    VALID_BACKENDS,
    VALID_MODES,
)
from core.config import (
    LlamaCppNodeConfig,
    StudioNodeConfig,
    UI_HIDDEN_ZELDA_MODEL_TAGS,
    direct_model_selection_error,
    is_advanced_model,
    is_hidden_model,
    is_spawn_only_model,
    is_zelda_model,
    is_z3ui_model_entry,
    z3ui_model_sort_key,
)
from core.engine import ChatEngine
from core.provider import CompletionRequest, create_provider
from protocol.lmstudio import (
    available_model_lookup,
    available_models,
    estimate_model_memory,
    ensure_server,
    loaded_model_lookup_keys,
    loaded_models,
    normalize_loaded_model_entry,
)

_LOCAL_MODEL_EXTENSIONS = (
    ".gguf",
    ".bin",
    ".safetensors",
    ".ggml",
)
_LOCAL_QUANT_SUFFIX_RE = re.compile(
    r"(?:[-_](?:q\d[a-z0-9_]*|iq\d[a-z0-9_]*|bf16|fp16|fp32|f16|f32|mlx))+$",
    re.IGNORECASE,
)


def _skip_model_memory_estimates() -> bool:
    return os.environ.get("Z3CLI_SKIP_MODEL_MEMORY_ESTIMATES", "").strip().lower() in {"1", "true", "yes", "on"}


_PRIMARY_MODEL_NAMES = ("oracle", "oracle-fast", "oracle-pro")
_USE_TARGET_ALIASES = {
    "oracle-pro-5090": "oracle-pro-home",
    "oracle-pro-local": "oracle-pro-home",
    "oracle-pro-studio": "oracle-pro-home",
    "pro": "oracle-pro-home",
    "home": "oracle-pro-home",
    "oracle-pro-ssh": "oracle-pro-home-ssh",
    "home-ssh": "oracle-pro-home-ssh",
    "vast": "oracle-pro-vast",
}
_CANONICAL_ROUTE_NAMES = {
    "oracle-pro-home": "oracle-pro-5090",
    "oracle-pro-5090": "oracle-pro-5090",
    "oracle-pro-local": "oracle-pro-5090",
    "oracle-pro-studio": "oracle-pro-5090",
    "pro": "oracle-pro-5090",
    "home": "oracle-pro-5090",
    "oracle-pro-home-ssh": "oracle-pro-ssh",
    "oracle-pro-ssh": "oracle-pro-ssh",
    "home-ssh": "oracle-pro-ssh",
    "oracle-pro-vast": "oracle-pro-vast",
    "vast": "oracle-pro-vast",
}
_ROUTE_TARGET_ORDER = (
    "oracle-pro-5090",
    "oracle-pro-ssh",
    "oracle-pro-vast",
)
_ROUTE_TARGET_ALIASES = {
    "oracle-pro-5090": (
        "home",
        "pro",
        "oracle-pro-local",
        "oracle-pro-studio",
    ),
    "oracle-pro-ssh": ("home-ssh",),
    "oracle-pro-vast": ("vast",),
}
_ROUTE_LIST_ADVANCED_ARGS = {
    "--all",
    "--advanced",
    "all",
    "advanced",
}
_TOPIC_SHIFT_STOPWORDS = {
    "about",
    "current",
    "explore",
    "files",
    "find",
    "help",
    "info",
    "information",
    "into",
    "look",
    "need",
    "oracle",
    "project",
    "secrets",
    "some",
    "state",
    "take",
    "that",
    "them",
    "this",
    "tools",
    "try",
    "what",
    "work",
}
_TOPIC_SHIFT_FOLLOWUPS = (
    "what are you talking about",
    "what's the current state",
    "whats the current state",
    "current state",
    "can you elaborate",
    "why",
    "what about",
)
DEFAULT_SMOKE_PROMPT = "/no_think\nReply exactly with: z3cli smoke ok"


def permission_rule_key(tool_name: str, server: str) -> str:
    return f"{server}:{tool_name}" if server else tool_name


def state_permission_rules(state: Any) -> dict[str, bool]:
    rules = getattr(state, "permission_rules", {})
    return dict(sorted(rules.items()))


def state_lsp_context_mode(state: Any) -> str:
    return normalize_lsp_context_mode(str(getattr(state, "lsp_context_mode", "auto") or "auto"))


def active_model_name(state: Any) -> str:
    return current_model_name(state.active_model, state.backend_name, state.llamacpp_model)


def get_llamacpp_nodes(state: Any) -> dict[str, LlamaCppNodeConfig]:
    raw_nodes = getattr(state, "llamacpp_nodes", {})
    return dict(raw_nodes) if isinstance(raw_nodes, dict) else {}


def get_studio_nodes(state: Any) -> dict[str, StudioNodeConfig]:
    raw_nodes = getattr(state, "studio_nodes", {})
    return dict(raw_nodes) if isinstance(raw_nodes, dict) else {}


def current_studio_node(state: Any) -> StudioNodeConfig | None:
    node_name = str(getattr(state, "studio_node", "") or "").strip().lower()
    if not node_name:
        return None
    return get_studio_nodes(state).get(node_name)


def current_llamacpp_node(state: Any) -> LlamaCppNodeConfig | None:
    node_name = str(getattr(state, "llamacpp_node", "") or "").strip().lower()
    if not node_name:
        return None
    return get_llamacpp_nodes(state).get(node_name)


def use_lean_llamacpp_prompt(state: Any) -> bool:
    if getattr(state, "backend_name", "") != "llamacpp":
        return False
    node = current_llamacpp_node(state)
    return bool(node and node.lean_prompt)


def _extract_topic_terms(text: str) -> set[str]:
    terms = {
        token
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_/-]{3,}", str(text or "").lower())
        if token not in _TOPIC_SHIFT_STOPWORDS
    }
    return terms


def maybe_reset_engine_for_topic_shift(engine: Any, prompt: str) -> bool:
    recent_prompts = list(getattr(engine, "_z3cli_recent_prompts", []) or [])
    normalized_prompt = str(prompt or "").strip()
    reset = False
    if recent_prompts:
        lowered = normalized_prompt.lower()
        current_terms = _extract_topic_terms(normalized_prompt)
        recent_terms: set[str] = set()
        for item in recent_prompts[-3:]:
            recent_terms.update(_extract_topic_terms(str(item)))
        if (
            len(getattr(engine, "messages", [])) >= 6
            and len(current_terms) >= 2
            and recent_terms
            and not (current_terms & recent_terms)
            and not any(phrase in lowered for phrase in _TOPIC_SHIFT_FOLLOWUPS)
        ):
            engine.reset()
            recent_prompts.clear()
            reset = True
    if normalized_prompt:
        recent_prompts.append(normalized_prompt)
        setattr(engine, "_z3cli_recent_prompts", recent_prompts[-4:])
    return reset


def apply_studio_node(state: Any, node: StudioNodeConfig) -> None:
    state.studio_node = node.name
    state.studio_api_base = node.api_base.rstrip("/")
    state.backend_name = "studio"
    state.api_base = state.studio_api_base
    if getattr(node, "hostd_url", ""):
        os.environ["Z3CLI_LMSTUDIO_HOSTD_URL"] = str(node.hostd_url).rstrip("/")
    else:
        os.environ.pop("Z3CLI_LMSTUDIO_HOSTD_URL", None)
    if getattr(node, "model", ""):
        try:
            resolved, _alias = resolve_existing_model_name(node.model, getattr(state, "models", {}))
        except RuntimeError:
            pass
        else:
            state.active_model = resolved


def select_studio_node(state: Any, node_name: str) -> tuple[StudioNodeConfig | None, str | None]:
    normalized = str(node_name or "").strip().lower()
    if not normalized:
        return None, "studio node name is required"
    nodes = get_studio_nodes(state)
    node = nodes.get(normalized)
    if node is None:
        return None, f"Unknown studio node: {node_name}"
    apply_studio_node(state, node)
    return node, None


def apply_llamacpp_node(state: Any, node: LlamaCppNodeConfig) -> None:
    state.llamacpp_node = node.name
    state.llamacpp_api_base = node.api_base.rstrip("/")
    state.llamacpp_model = node.model
    state.backend_name = "llamacpp"
    state.api_base = state.llamacpp_api_base


def select_llamacpp_node(state: Any, node_name: str) -> tuple[LlamaCppNodeConfig | None, str | None]:
    normalized = str(node_name or "").strip().lower()
    if not normalized:
        return None, "llama.cpp node name is required"
    nodes = get_llamacpp_nodes(state)
    node = nodes.get(normalized)
    if node is None:
        return None, f"Unknown llama.cpp node: {node_name}"
    apply_llamacpp_node(state, node)
    return node, None


def available_use_targets(state: Any) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(name: str, *, kind: str, backend: str, model: str = "", description: str = "") -> None:
        normalized = str(name or "").strip().lower()
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        entries.append({
            "name": normalized,
            "kind": kind,
            "backend": backend,
            "model": str(model or ""),
            "description": str(description or ""),
        })

    studio_nodes = get_studio_nodes(state)
    llamacpp_nodes = get_llamacpp_nodes(state)

    for alias, target in _USE_TARGET_ALIASES.items():
        if target in studio_nodes:
            node = studio_nodes[target]
            add(alias, kind="alias", backend="studio", model=node.model, description=f"{target} · {node.description}".strip(" ·"))
        elif target in llamacpp_nodes:
            node = llamacpp_nodes[target]
            add(alias, kind="alias", backend="llamacpp", model=node.model, description=f"{target} · {node.description}".strip(" ·"))

    for name, node in sorted(studio_nodes.items()):
        add(name, kind="studio-node", backend="studio", model=node.model, description=node.description)
    for name, node in sorted(llamacpp_nodes.items()):
        add(name, kind="llamacpp-node", backend="llamacpp", model=node.model, description=node.description)

    for name in _PRIMARY_MODEL_NAMES:
        if name in getattr(state, "models", {}):
            add(name, kind="model", backend="studio", model=name, description="model")

    return entries


def route_list_include_advanced(args: list[Any]) -> tuple[bool, str | None]:
    include_advanced = False
    for raw_arg in args:
        arg = str(raw_arg or "").strip().lower()
        if not arg:
            continue
        if arg not in _ROUTE_LIST_ADVANCED_ARGS:
            return False, f"Unknown route list option: {raw_arg}"
        include_advanced = True
    return include_advanced, None


def available_route_targets(state: Any, *, include_advanced: bool = False) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    seen: set[str] = set()
    resolved_names: set[str] = set()
    studio_nodes = get_studio_nodes(state)
    llamacpp_nodes = get_llamacpp_nodes(state)

    def add(entry: dict[str, object]) -> None:
        name = str(entry.get("name") or "").strip().lower()
        if not name or name in seen:
            return
        seen.add(name)
        entries.append(entry)

    for route_name in _ROUTE_TARGET_ORDER:
        resolved_name = _USE_TARGET_ALIASES.get(route_name, route_name)
        node = studio_nodes.get(resolved_name)
        if node is not None:
            resolved_names.add(node.name)
            add({
                "name": route_name,
                "kind": "route",
                "backend": "studio",
                "model": str(node.model or ""),
                "description": str(node.description or ""),
                "resolved": node.name,
                "aliases": list(_ROUTE_TARGET_ALIASES.get(route_name, ())),
            })
            continue

        llama_node = llamacpp_nodes.get(resolved_name)
        if llama_node is not None:
            resolved_names.add(llama_node.name)
            add({
                "name": route_name,
                "kind": "route",
                "backend": "llamacpp",
                "model": str(llama_node.model or ""),
                "description": str(llama_node.description or ""),
                "resolved": llama_node.name,
                "aliases": list(_ROUTE_TARGET_ALIASES.get(route_name, ())),
            })

    if not include_advanced:
        return entries

    for entry in available_use_targets(state):
        if entry.get("kind") == "alias":
            continue
        name = str(entry.get("name") or "").strip().lower()
        if not name or name in seen:
            continue
        advanced_entry: dict[str, object] = dict(entry)
        advanced_entry["advanced"] = True
        if name in resolved_names:
            advanced_entry["description"] = (
                f"{advanced_entry.get('description') or ''} (raw route target)"
            ).strip()
        add(advanced_entry)

    return entries


def canonical_route_name(target_name: str, resolved_name: str = "") -> str:
    requested = str(target_name or "").strip().lower()
    resolved = str(resolved_name or "").strip().lower()
    return _CANONICAL_ROUTE_NAMES.get(requested) or _CANONICAL_ROUTE_NAMES.get(resolved) or requested or resolved


def apply_use_target(state: Any, target_name: str) -> tuple[dict[str, str] | None, str | None]:
    requested = str(target_name or "").strip().lower()
    if not requested:
        return None, "use target is required"

    normalized = _USE_TARGET_ALIASES.get(requested, requested)
    studio_nodes = get_studio_nodes(state)
    llamacpp_nodes = get_llamacpp_nodes(state)

    if normalized in studio_nodes:
        node, error = select_studio_node(state, normalized)
        if node is None:
            return None, error or f"Unknown use target: {target_name}"
        return {
            "target": requested,
            "route": canonical_route_name(requested, node.name),
            "resolved": node.name,
            "backend": "studio",
            "model": getattr(state, "active_model", ""),
            "studio_node": node.name,
        }, None

    if normalized in llamacpp_nodes:
        node, error = select_llamacpp_node(state, normalized)
        if node is None:
            return None, error or f"Unknown use target: {target_name}"
        return {
            "target": requested,
            "route": canonical_route_name(requested, node.name),
            "resolved": node.name,
            "backend": "llamacpp",
            "model": node.model,
            "llamacpp_node": node.name,
        }, None

    try:
        resolved_model, _alias = resolve_existing_model_name(normalized, getattr(state, "models", {}))
    except RuntimeError:
        return None, f"Unknown use target: {target_name}"

    for name, node in sorted(studio_nodes.items()):
        if str(getattr(node, "model", "") or "").strip().lower() == resolved_model:
            select_studio_node(state, name)
            return {
                "target": requested,
                "route": canonical_route_name(requested, name),
                "resolved": name,
                "backend": "studio",
                "model": getattr(state, "active_model", resolved_model),
                "studio_node": name,
            }, None

    for name, node in sorted(llamacpp_nodes.items()):
        if str(getattr(node, "model", "") or "").strip().lower() == resolved_model:
            select_llamacpp_node(state, name)
            return {
                "target": requested,
                "route": canonical_route_name(requested, name),
                "resolved": name,
                "backend": "llamacpp",
                "model": node.model,
                "llamacpp_node": name,
            }, None

    set_backend(state, "studio")
    state.active_model = resolved_model
    return {
        "target": requested,
        "route": canonical_route_name(requested, resolved_model),
        "resolved": resolved_model,
        "backend": "studio",
        "model": resolved_model,
    }, None


def get_backend(state: Any) -> LMStudioBackend | LlamaCppBackend:
    if state.backend_name == "llamacpp":
        return LlamaCppBackend(api_base=state.llamacpp_api_base, model=state.llamacpp_model)
    return LMStudioBackend(api_base=state.studio_api_base, host=state.host, port=state.port)


def _smoke_provider_config(state: Any) -> tuple[str, str, str, str, str, bool]:
    target = getattr(state, "models", {}).get(getattr(state, "active_model", ""))
    if target is not None and getattr(target, "is_cloud", False):
        return (
            str(getattr(target, "provider", "") or "openai"),
            str(getattr(target, "api_base", "") or ""),
            str(getattr(target, "model_id", "") or getattr(target, "name", "")),
            str(getattr(target, "name", "") or ""),
            target.resolve_api_key(),
            bool(getattr(target, "disable_reasoning_prefill", False)),
        )

    if getattr(state, "backend_name", "") == "llamacpp":
        model_id = str(
            getattr(state, "llamacpp_model", "")
            or getattr(target, "model_id", "")
            or active_model_name(state)
        )
        return (
            "llamacpp",
            str(getattr(state, "llamacpp_api_base", "") or getattr(state, "api_base", "")),
            model_id,
            str(getattr(state, "llamacpp_node", "") or ""),
            "",
            bool(getattr(target, "disable_reasoning_prefill", False)) if target is not None else False,
        )

    if target is not None:
        model_id = resolve_request_model_name(state, target)
    else:
        model_id = active_model_name(state)
    return (
        "studio",
        str(getattr(state, "studio_api_base", "") or getattr(state, "api_base", "")),
        model_id,
        str(getattr(state, "studio_node", "") or ""),
        "",
        bool(getattr(target, "disable_reasoning_prefill", False)) if target is not None else False,
    )


async def smoke_current_route(
    state: Any,
    *,
    prompt: str = DEFAULT_SMOKE_PROMPT,
    max_tokens: int = 256,
    timeout_s: float = 30.0,
) -> dict[str, Any]:
    provider_name, api_base, model_id, node, api_key, disable_reasoning_prefill = _smoke_provider_config(state)
    result: dict[str, Any] = {
        "ok": False,
        "matched": False,
        "backend": provider_name,
        "api_base": api_base,
        "node": node,
        "model": model_id,
        "text": "",
        "thinking": "",
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "duration_ms": 0,
        "stop_reason": "",
        "error": "",
    }
    started = time.monotonic()
    provider = None
    try:
        provider = create_provider(
            provider_name,
            api_base=api_base,
            api_key=api_key,
            default_model=model_id,
            timeout=timeout_s,
        )
        async for chunk in provider.stream(
            CompletionRequest(
                model_id=model_id,
                messages=[{"role": "user", "content": prompt}],
                system="/no_think\nYou are a z3cli route smoke test. Reply only with: z3cli smoke ok",
                temperature=0.0,
                max_tokens=max_tokens,
                stream=False,
                prompt_cache=False,
                disable_reasoning_prefill=disable_reasoning_prefill,
            )
        ):
            if chunk.content is not None:
                result["text"] += chunk.content.text or ""
                result["thinking"] += chunk.content.thinking or chunk.content.reasoning or ""
            if chunk.usage is not None:
                result["prompt_tokens"] += int(chunk.usage.prompt_tokens or 0)
                result["completion_tokens"] += int(chunk.usage.completion_tokens or 0)
            if chunk.stop_reason:
                result["stop_reason"] = chunk.stop_reason
    except Exception as exc:
        result["error"] = str(exc)[:500]
        return result
    finally:
        result["duration_ms"] = int((time.monotonic() - started) * 1000)
        if provider is not None:
            try:
                await provider.close()
            except Exception:
                pass

    text = str(result["text"] or "").strip()
    result["ok"] = bool(text)
    result["matched"] = "z3cli smoke ok" in text.lower()
    return result


def set_backend(state: Any, backend_name: str) -> None:
    state.backend_name = backend_name
    if backend_name == "llamacpp":
        state.api_base = state.llamacpp_api_base
    else:
        state.api_base = state.studio_api_base


def render_focus_context(focus_path: Path, content: str) -> str:
    return f"# Focus: {focus_path.name}\n\n{content}"


def set_focus_context(state: Any, focus_path: Path, content: str) -> tuple[int, int]:
    state.focus_path = focus_path
    state.focus_context = render_focus_context(focus_path, content)
    return content.count("\n") + 1, len(content)


def clear_focus_context(state: Any) -> None:
    state.focus_path = None
    state.focus_context = ""


async def _load_focus_context_for_state(
    state: Any,
    model_name: str = "",
    query: str = "",
) -> tuple[Path | None, str]:
    focus_path = getattr(state, "focus_path", None)
    if focus_path is None:
        return None, ""
    models = getattr(state, "models", {})
    selected_name = model_name or getattr(state, "active_model", "")
    model = models.get(selected_name) if isinstance(models, dict) else None
    try:
        return await load_enriched_focus_file(
            getattr(state, "workspace"),
            focus_path,
            bridge=getattr(state, "bridge", None),
            model=model,
            lsp_context_mode=state_lsp_context_mode(state),
            prompt_query=query,
        )
    except Exception:
        return None, ""


async def resolve_focus_context(state: Any, model_name: str = "", query: str = "") -> str:
    path, content = await _load_focus_context_for_state(state, model_name, query)
    if path is None:
        return ""
    return render_focus_context(path, content)


async def refresh_focus_context(state: Any, model_name: str = "") -> None:
    path, content = await _load_focus_context_for_state(state, model_name)
    if path is None:
        clear_focus_context(state)
        return
    set_focus_context(state, path, content)


def mark_active(state: Any, model_name: str = "") -> None:
    state.last_active_at = datetime.now(timezone.utc).isoformat()
    state.last_active_model = model_name or state.last_active_model or state.active_model


def session_metrics_patch(state: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "prompt_tokens": state.prompt_tokens,
        "completion_tokens": state.completion_tokens,
        "tool_call_count": state.tool_call_count,
        "last_active_at": state.last_active_at,
        "last_active_model": state.last_active_model,
    }
    if hasattr(state, "cache_creation_tokens"):
        payload["cache_creation_tokens"] = state.cache_creation_tokens
    if hasattr(state, "cache_read_tokens"):
        payload["cache_read_tokens"] = state.cache_read_tokens
    if hasattr(state, "orchestrator_model"):
        payload["orchestrator_model"] = state.orchestrator_model
    if hasattr(state, "lsp_context_mode"):
        payload["lsp_context_mode"] = state_lsp_context_mode(state)
    if hasattr(state, "permission_rules"):
        payload["permission_rules"] = state_permission_rules(state)
    if hasattr(state, "cancel_count"):
        payload["cancel_count"] = state.cancel_count
    if hasattr(state, "backend_restart_count"):
        payload["backend_restart_count"] = state.backend_restart_count
    if hasattr(state, "tool_latency_ms_total"):
        payload["tool_latency_ms_total"] = state.tool_latency_ms_total
    if hasattr(state, "tool_latency_samples"):
        payload["tool_latency_samples"] = state.tool_latency_samples
    if hasattr(state, "review_wait_ms"):
        payload["review_wait_ms"] = state.review_wait_ms
    if hasattr(state, "permission_wait_ms"):
        payload["permission_wait_ms"] = state.permission_wait_ms
    if hasattr(state, "permission_timeout_count"):
        payload["permission_timeout_count"] = state.permission_timeout_count
    if hasattr(state, "review_timeout_count"):
        payload["review_timeout_count"] = state.review_timeout_count
    if hasattr(state, "model_retry_count"):
        payload["model_retry_count"] = state.model_retry_count
    if hasattr(state, "model_retry_backoff_ms"):
        payload["model_retry_backoff_ms"] = state.model_retry_backoff_ms
    if hasattr(state, "model_error_count"):
        payload["model_error_count"] = state.model_error_count
    if hasattr(state, "tool_timeout_count"):
        payload["tool_timeout_count"] = state.tool_timeout_count
    if hasattr(state, "model_backpressure_count"):
        payload["model_backpressure_count"] = state.model_backpressure_count
    if hasattr(state, "tool_backpressure_count"):
        payload["tool_backpressure_count"] = state.tool_backpressure_count
    if hasattr(state, "model_queue_highwater"):
        payload["model_queue_highwater"] = state.model_queue_highwater
    if hasattr(state, "tool_queue_highwater"):
        payload["tool_queue_highwater"] = state.tool_queue_highwater
    if hasattr(state, "model_inflight_highwater"):
        payload["model_inflight_highwater"] = state.model_inflight_highwater
    if hasattr(state, "tool_inflight_highwater"):
        payload["tool_inflight_highwater"] = state.tool_inflight_highwater
    if hasattr(state, "max_inflight_model_calls"):
        payload["max_inflight_model_calls"] = state.max_inflight_model_calls
    if hasattr(state, "max_inflight_tools"):
        payload["max_inflight_tools"] = state.max_inflight_tools
    if hasattr(state, "exec_queue_depth"):
        payload["exec_queue_depth"] = state.exec_queue_depth
    if hasattr(state, "request_index"):
        payload["request_index"] = state.request_index
    if hasattr(state, "request_count"):
        payload["request_count"] = state.request_count
    if hasattr(state, "request_success_count"):
        payload["request_success_count"] = state.request_success_count
    if hasattr(state, "request_error_count"):
        payload["request_error_count"] = state.request_error_count
    if hasattr(state, "request_reject_count"):
        payload["request_reject_count"] = state.request_reject_count
    if hasattr(state, "request_cancel_count"):
        payload["request_cancel_count"] = state.request_cancel_count
    if hasattr(state, "model_alias_resolutions"):
        payload["model_alias_resolutions"] = state.model_alias_resolutions
    if hasattr(state, "model_lookup_failures"):
        payload["model_lookup_failures"] = state.model_lookup_failures
    if hasattr(state, "model_request_counts"):
        payload["model_request_counts"] = dict(state.model_request_counts)
    if hasattr(state, "span_count"):
        payload["span_count"] = state.span_count
    if hasattr(state, "last_request_id"):
        payload["last_request_id"] = state.last_request_id
    if hasattr(state, "last_span_id"):
        payload["last_span_id"] = state.last_span_id
    if hasattr(state, "last_tool_call_id"):
        payload["last_tool_call_id"] = state.last_tool_call_id
    if hasattr(state, "request_queued_ms_samples"):
        payload["request_queued_ms_samples"] = list(state.request_queued_ms_samples)
    if hasattr(state, "request_model_ms_samples"):
        payload["request_model_ms_samples"] = list(state.request_model_ms_samples)
    if hasattr(state, "request_tool_ms_samples"):
        payload["request_tool_ms_samples"] = list(state.request_tool_ms_samples)
    if hasattr(state, "request_total_ms_samples"):
        payload["request_total_ms_samples"] = list(state.request_total_ms_samples)
    if hasattr(state, "last_request_status"):
        payload["last_request_status"] = state.last_request_status
    if hasattr(state, "last_request_total_ms"):
        payload["last_request_total_ms"] = state.last_request_total_ms
    if hasattr(state, "last_request_queued_ms"):
        payload["last_request_queued_ms"] = state.last_request_queued_ms
    if hasattr(state, "last_request_model_ms"):
        payload["last_request_model_ms"] = state.last_request_model_ms
    if hasattr(state, "last_request_tool_ms"):
        payload["last_request_tool_ms"] = state.last_request_tool_ms
    return payload


def persist_state(state: Any, changes: dict[str, Any] | None = None, model_name: str = "") -> None:
    session = getattr(state, "session", None)
    if session is None:
        return
    mark_active(state, model_name or state.active_model)
    payload = dict(changes or {})
    payload.update(session_metrics_patch(state))
    session.append_state_update(payload)


async def compact_session_history(state: Any, model_name: str, engine: Any | None = None) -> Any | None:
    """Compact a model history, persist the summary, and return the event."""
    if engine is None:
        get_engine = getattr(state, "get_engine", None)
        if get_engine is None:
            return None
        engine = get_engine(model_name)
    if engine.compactor is None:
        return None
    event = await engine.compact_now(force=True)
    if event is None:
        return None
    session = getattr(state, "session", None)
    if session is not None:
        session.save_compact(model_name, event.summary, event.replaced_count)
    persist_state(state, model_name=model_name)
    return event


def restore_runtime_state(state: Any, meta: dict[str, Any]) -> list[str]:
    warnings: list[str] = []

    if meta.get("active_model"):
        requested = str(meta["active_model"])
        try:
            state.active_model, _alias = resolve_existing_model_name(requested, state.models)
        except RuntimeError:
            warnings.append(f"Unknown model in session: {requested}")
    if meta.get("mode"):
        mode, _alias = normalize_mode(str(meta["mode"]))
        if mode in VALID_MODES:
            state.mode = mode
    if meta.get("backend") in VALID_BACKENDS:
        set_backend(state, str(meta["backend"]))
        if state.backend_name == "studio" and getattr(state, "auto_start_server", True):
            ensure_server(state.host, state.port)
    if meta.get("workspace"):
        state.workspace = Path(str(meta["workspace"])).expanduser().resolve()
    if "rom_path" in meta:
        rom_value = str(meta["rom_path"])
        state.rom_path = Path(rom_value).expanduser().resolve() if rom_value else None
    if "tools_enabled" in meta and hasattr(state, "tools_enabled"):
        state.tools_enabled = bool(meta["tools_enabled"])
    if "tools_write" in meta and hasattr(state, "tools_write"):
        state.tools_write = bool(meta["tools_write"])
    if "verify_hooks" in meta and hasattr(state, "verify_hooks"):
        state.verify_hooks = bool(meta["verify_hooks"])
    if "lsp_context_mode" in meta and hasattr(state, "lsp_context_mode"):
        state.lsp_context_mode = normalize_lsp_context_mode(str(meta["lsp_context_mode"]))
    if "prompt_tokens" in meta:
        state.prompt_tokens = int(meta["prompt_tokens"])
    if "completion_tokens" in meta:
        state.completion_tokens = int(meta["completion_tokens"])
    if "cache_creation_tokens" in meta and hasattr(state, "cache_creation_tokens"):
        state.cache_creation_tokens = int(meta["cache_creation_tokens"])
    if "cache_read_tokens" in meta and hasattr(state, "cache_read_tokens"):
        state.cache_read_tokens = int(meta["cache_read_tokens"])
    if "tool_call_count" in meta:
        state.tool_call_count = int(meta["tool_call_count"])
    if "cancel_count" in meta and hasattr(state, "cancel_count"):
        state.cancel_count = int(meta["cancel_count"])
    if "backend_restart_count" in meta and hasattr(state, "backend_restart_count"):
        state.backend_restart_count = int(meta["backend_restart_count"])
    if "tool_latency_ms_total" in meta and hasattr(state, "tool_latency_ms_total"):
        state.tool_latency_ms_total = int(meta["tool_latency_ms_total"])
    if "tool_latency_samples" in meta and hasattr(state, "tool_latency_samples"):
        state.tool_latency_samples = int(meta["tool_latency_samples"])
    if "review_wait_ms" in meta and hasattr(state, "review_wait_ms"):
        state.review_wait_ms = int(meta["review_wait_ms"])
    if "permission_wait_ms" in meta and hasattr(state, "permission_wait_ms"):
        state.permission_wait_ms = int(meta["permission_wait_ms"])
    if "permission_timeout_count" in meta and hasattr(state, "permission_timeout_count"):
        state.permission_timeout_count = int(meta["permission_timeout_count"])
    if "review_timeout_count" in meta and hasattr(state, "review_timeout_count"):
        state.review_timeout_count = int(meta["review_timeout_count"])
    if "model_retry_count" in meta and hasattr(state, "model_retry_count"):
        state.model_retry_count = int(meta["model_retry_count"])
    if "model_retry_backoff_ms" in meta and hasattr(state, "model_retry_backoff_ms"):
        state.model_retry_backoff_ms = int(meta["model_retry_backoff_ms"])
    if "model_error_count" in meta and hasattr(state, "model_error_count"):
        state.model_error_count = int(meta["model_error_count"])
    if "tool_timeout_count" in meta and hasattr(state, "tool_timeout_count"):
        state.tool_timeout_count = int(meta["tool_timeout_count"])
    if "model_backpressure_count" in meta and hasattr(state, "model_backpressure_count"):
        state.model_backpressure_count = int(meta["model_backpressure_count"])
    if "tool_backpressure_count" in meta and hasattr(state, "tool_backpressure_count"):
        state.tool_backpressure_count = int(meta["tool_backpressure_count"])
    if "model_queue_highwater" in meta and hasattr(state, "model_queue_highwater"):
        state.model_queue_highwater = int(meta["model_queue_highwater"])
    if "tool_queue_highwater" in meta and hasattr(state, "tool_queue_highwater"):
        state.tool_queue_highwater = int(meta["tool_queue_highwater"])
    if "model_inflight_highwater" in meta and hasattr(state, "model_inflight_highwater"):
        state.model_inflight_highwater = int(meta["model_inflight_highwater"])
    if "tool_inflight_highwater" in meta and hasattr(state, "tool_inflight_highwater"):
        state.tool_inflight_highwater = int(meta["tool_inflight_highwater"])
    budget_changed = False
    if "max_inflight_model_calls" in meta and hasattr(state, "max_inflight_model_calls"):
        state.max_inflight_model_calls = max(1, int(meta["max_inflight_model_calls"]))
        budget_changed = True
    if "max_inflight_tools" in meta and hasattr(state, "max_inflight_tools"):
        state.max_inflight_tools = max(1, int(meta["max_inflight_tools"]))
        budget_changed = True
    if "exec_queue_depth" in meta and hasattr(state, "exec_queue_depth"):
        state.exec_queue_depth = max(0, int(meta["exec_queue_depth"]))
        budget_changed = True
    if "request_index" in meta and hasattr(state, "request_index"):
        state.request_index = max(0, int(meta["request_index"]))
    if "request_count" in meta and hasattr(state, "request_count"):
        state.request_count = max(0, int(meta["request_count"]))
    if "request_success_count" in meta and hasattr(state, "request_success_count"):
        state.request_success_count = max(0, int(meta["request_success_count"]))
    if "request_error_count" in meta and hasattr(state, "request_error_count"):
        state.request_error_count = max(0, int(meta["request_error_count"]))
    if "request_reject_count" in meta and hasattr(state, "request_reject_count"):
        state.request_reject_count = max(0, int(meta["request_reject_count"]))
    if "request_cancel_count" in meta and hasattr(state, "request_cancel_count"):
        state.request_cancel_count = max(0, int(meta["request_cancel_count"]))
    if "model_alias_resolutions" in meta and hasattr(state, "model_alias_resolutions"):
        state.model_alias_resolutions = max(0, int(meta["model_alias_resolutions"]))
    if "model_lookup_failures" in meta and hasattr(state, "model_lookup_failures"):
        state.model_lookup_failures = max(0, int(meta["model_lookup_failures"]))
    if "model_request_counts" in meta and hasattr(state, "model_request_counts"):
        raw_counts = meta["model_request_counts"]
        if isinstance(raw_counts, dict):
            state.model_request_counts = {
                str(model_name): max(0, int(count))
                for model_name, count in raw_counts.items()
                if isinstance(count, (int, float))
            }
        else:
            state.model_request_counts = {}
    if "span_count" in meta and hasattr(state, "span_count"):
        state.span_count = max(0, int(meta["span_count"]))
    if "last_request_id" in meta and hasattr(state, "last_request_id"):
        state.last_request_id = str(meta["last_request_id"])
    if "last_span_id" in meta and hasattr(state, "last_span_id"):
        state.last_span_id = str(meta["last_span_id"])
    if "last_tool_call_id" in meta and hasattr(state, "last_tool_call_id"):
        state.last_tool_call_id = str(meta["last_tool_call_id"])
    if "request_queued_ms_samples" in meta and hasattr(state, "request_queued_ms_samples"):
        samples = meta["request_queued_ms_samples"]
        if isinstance(samples, list):
            state.request_queued_ms_samples = [max(0, int(item)) for item in samples if isinstance(item, (int, float))]
    if "request_model_ms_samples" in meta and hasattr(state, "request_model_ms_samples"):
        samples = meta["request_model_ms_samples"]
        if isinstance(samples, list):
            state.request_model_ms_samples = [max(0, int(item)) for item in samples if isinstance(item, (int, float))]
    if "request_tool_ms_samples" in meta and hasattr(state, "request_tool_ms_samples"):
        samples = meta["request_tool_ms_samples"]
        if isinstance(samples, list):
            state.request_tool_ms_samples = [max(0, int(item)) for item in samples if isinstance(item, (int, float))]
    if "request_total_ms_samples" in meta and hasattr(state, "request_total_ms_samples"):
        samples = meta["request_total_ms_samples"]
        if isinstance(samples, list):
            state.request_total_ms_samples = [max(0, int(item)) for item in samples if isinstance(item, (int, float))]
    if "last_request_status" in meta and hasattr(state, "last_request_status"):
        state.last_request_status = str(meta["last_request_status"])
    if "last_request_total_ms" in meta and hasattr(state, "last_request_total_ms"):
        state.last_request_total_ms = max(0, int(meta["last_request_total_ms"]))
    if "last_request_queued_ms" in meta and hasattr(state, "last_request_queued_ms"):
        state.last_request_queued_ms = max(0, int(meta["last_request_queued_ms"]))
    if "last_request_model_ms" in meta and hasattr(state, "last_request_model_ms"):
        state.last_request_model_ms = max(0, int(meta["last_request_model_ms"]))
    if "last_request_tool_ms" in meta and hasattr(state, "last_request_tool_ms"):
        state.last_request_tool_ms = max(0, int(meta["last_request_tool_ms"]))
    reconfigure = getattr(state, "reconfigure_execution_budget", None)
    if budget_changed and callable(reconfigure):
        reconfigure()
    if meta.get("last_active_at"):
        state.last_active_at = str(meta["last_active_at"])
    if meta.get("last_active_model"):
        state.last_active_model = str(meta["last_active_model"])
    if "broadcast_models" in meta and isinstance(meta["broadcast_models"], list):
        state.broadcast_models = [str(value).strip() for value in meta["broadcast_models"] if str(value).strip()]
    if meta.get("studio_api_base") and hasattr(state, "studio_api_base"):
        state.studio_api_base = str(meta["studio_api_base"]).rstrip("/")
    if "studio_node" in meta and hasattr(state, "studio_node"):
        requested_studio_node = str(meta["studio_node"] or "").strip().lower()
        if requested_studio_node:
            node, error = select_studio_node(state, requested_studio_node)
            if node is None and error:
                warnings.append(error)
        else:
            state.studio_node = ""
    if meta.get("llamacpp_api_base") and hasattr(state, "llamacpp_api_base"):
        state.llamacpp_api_base = str(meta["llamacpp_api_base"]).rstrip("/")
    if meta.get("llamacpp_model"):
        state.llamacpp_model = str(meta["llamacpp_model"])
    if "llamacpp_node" in meta and hasattr(state, "llamacpp_node"):
        requested_node = str(meta["llamacpp_node"] or "").strip().lower()
        if requested_node:
            node, error = select_llamacpp_node(state, requested_node)
            if node is None and error:
                warnings.append(error)
        else:
            state.llamacpp_node = ""
    if getattr(state, "backend_name", "") == "studio" and hasattr(state, "studio_api_base"):
        state.api_base = state.studio_api_base
    elif getattr(state, "backend_name", "") == "llamacpp" and hasattr(state, "llamacpp_api_base"):
        state.api_base = state.llamacpp_api_base
    if "orchestrator_model" in meta and hasattr(state, "orchestrator_model"):
        requested_orchestrator = str(meta["orchestrator_model"] or "")
        if not requested_orchestrator:
            state.orchestrator_model = ""
        else:
            try:
                state.orchestrator_model, _orchestrator_alias = resolve_existing_model_name(
                    requested_orchestrator,
                    state.models,
                )
            except RuntimeError:
                warnings.append(f"Unknown orchestrator model in session: {requested_orchestrator}")
    rules = meta.get("permission_rules")
    if isinstance(rules, dict) and hasattr(state, "permission_rules"):
        state.permission_rules = {
            str(key): bool(value)
            for key, value in rules.items()
        }
    elif hasattr(state, "permission_rules"):
        state.permission_rules = {}

    focus_value = str(meta.get("focus_path", "") or "").strip()
    if focus_value:
        try:
            focus_path, content = load_focus_file(state.workspace, focus_value)
        except FileNotFoundError:
            clear_focus_context(state)
            warnings.append(f"Focus file not found while resuming: {focus_value}")
        except Exception as exc:
            clear_focus_context(state)
            warnings.append(f"Failed to load focus file '{focus_value}': {exc}")
        else:
            state.focus_path = focus_path
            set_focus_context(state, focus_path, content)
    else:
        clear_focus_context(state)

    return warnings


def get_or_create_engine(
    state: Any,
    model_name: str,
    *,
    permission_hook=None,
    post_tool_hook=None,
    tool_invocation_hook=None,
    compactor_builder=None,
) -> ChatEngine:
    def apply_runtime_policy(engine: ChatEngine) -> None:
        # Keep retry/timeout guardrails centralized at runtime state.
        engine.provider_max_retries = max(0, int(getattr(state, "model_retry_max", engine.provider_max_retries)))
        engine.provider_retry_base_s = max(
            0.0,
            float(getattr(state, "model_retry_backoff_base_s", engine.provider_retry_base_s)),
        )
        engine.tool_timeout_s = max(0.0, float(getattr(state, "tool_exec_timeout_s", engine.tool_timeout_s)))
        if tool_invocation_hook is not None:
            engine.set_tool_invocation_hook(tool_invocation_hook)

    model_cfg = state.models.get(model_name)
    if model_cfg and model_cfg.is_cloud:
        key = engine_key(model_cfg.provider, model_name)
        engine = state.engines.get(key)
        if engine is None:
            provider = create_provider(
                provider_name=model_cfg.provider,
                api_base=model_cfg.api_base,
                api_key=model_cfg.resolve_api_key(),
                default_model=model_cfg.model_id,
            )
            engine = ChatEngine(
                bridge=state.bridge,
                permission_hook=permission_hook,
                post_tool_hook=post_tool_hook,
                tool_invocation_hook=tool_invocation_hook,
                provider=provider,
                compactor=compactor_builder(model_cfg, provider) if compactor_builder else None,
            )
            apply_runtime_policy(engine)
            state.engines[key] = engine
        else:
            apply_runtime_policy(engine)
        return engine

    key = engine_key(state.backend_name, model_name)
    engine = state.engines.get(key)
    if engine is None:
        engine = ChatEngine(
            api_base=state.api_base,
            bridge=state.bridge,
            permission_hook=permission_hook,
            post_tool_hook=post_tool_hook,
            tool_invocation_hook=tool_invocation_hook,
        )
        if compactor_builder and model_cfg is not None:
            engine.set_compactor(compactor_builder(model_cfg, engine.provider))
        apply_runtime_policy(engine)
        state.engines[key] = engine
    else:
        apply_runtime_policy(engine)
    return engine


def resolve_request_model_name(state: Any, target: Any) -> str:
    if getattr(target, "is_cloud", False):
        return target.model_id
    auto_load = getattr(state, "auto_load", True)
    return get_backend(state).resolve_request_model(target, auto_load)


def _studio_runtime_inventory(
    state: Any,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]], bool]:
    inventory_ok = False
    try:
        available_entries = available_models(state.host, state.port) if state.backend_name == "studio" else []
        loaded_entries = loaded_models(state.host, state.port) if state.backend_name == "studio" else []
        inventory_ok = state.backend_name == "studio"
    except Exception:
        available_entries = []
        loaded_entries = []

    available_lookup = available_model_lookup([
        entry for entry in available_entries if isinstance(entry, dict)
    ])
    runtime_infos: list[dict[str, Any]] = []
    loaded_lookup: dict[str, dict[str, Any]] = {}
    for entry in loaded_entries:
        if not isinstance(entry, dict):
            continue
        runtime_info = normalize_loaded_model_entry(entry, available_lookup=available_lookup)
        model_key = str(runtime_info.get("model_key", "") or runtime_info.get("identifier", ""))
        if model_key and not _skip_model_memory_estimates():
            try:
                runtime_info.update(estimate_model_memory(
                    state.host,
                    state.port,
                    model_key,
                    context_length=int(runtime_info.get("context_length", 0) or 0),
                ))
            except Exception:
                pass
        runtime_infos.append(runtime_info)
        for key in loaded_model_lookup_keys(entry):
            loaded_lookup.setdefault(key, runtime_info)
        identifier = runtime_info.get("identifier")
        model_key = runtime_info.get("model_key")
        if isinstance(identifier, str) and identifier:
            loaded_lookup.setdefault(identifier, runtime_info)
        if isinstance(model_key, str) and model_key:
            loaded_lookup.setdefault(model_key, runtime_info)
    return runtime_infos, loaded_lookup, available_lookup, inventory_ok


def _model_has_runtime_presence(
    model: Any,
    loaded_lookup: dict[str, dict[str, Any]],
    available_lookup: dict[str, dict[str, Any]],
    inventory_ok: bool,
) -> bool:
    if getattr(model, "is_cloud", False):
        return bool(model.resolve_api_key())
    if getattr(model, "provider", "") == "llamacpp":
        return True
    if not inventory_ok:
        return True
    if not bool(getattr(model, "hide_if_unavailable", False)):
        return True
    if not loaded_lookup and not available_lookup:
        return True
    runtime_keys = _model_runtime_keys(model)
    return (
        _lookup_runtime_entry(runtime_keys, loaded_lookup) is not None
        or _lookup_runtime_entry(runtime_keys, available_lookup) is not None
    )


def _normalized_runtime_lookup_keys(value: str) -> set[str]:
    raw = str(value or "").strip()
    if not raw:
        return set()
    slash_normalized = raw.replace("\\", "/").strip("/")
    candidates = {
        raw.lower(),
        slash_normalized.lower(),
    }
    basename = slash_normalized.rsplit("/", 1)[-1]
    if basename:
        candidates.add(basename.lower())
        stem = basename
        lowered_stem = stem.lower()
        for extension in _LOCAL_MODEL_EXTENSIONS:
            if lowered_stem.endswith(extension):
                stem = stem[: -len(extension)]
                lowered_stem = stem.lower()
                candidates.add(lowered_stem)
                break
        trimmed = _LOCAL_QUANT_SUFFIX_RE.sub("", stem)
        if trimmed:
            candidates.add(trimmed.lower())
    return {candidate for candidate in candidates if candidate}


def _model_runtime_keys(model: Any) -> tuple[str, ...]:
    aliases = getattr(model, "aliases", [])
    alias_values = aliases if isinstance(aliases, list) else []
    values = [
        str(getattr(model, "name", "") or "").strip(),
        str(getattr(model, "model_id", "") or "").strip(),
        *(str(alias or "").strip() for alias in alias_values),
    ]
    deduped: list[str] = []
    for value in values:
        if value and value not in deduped:
            deduped.append(value)
    return tuple(deduped)


def _lookup_runtime_entry(
    runtime_keys: tuple[str, ...],
    lookup: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    if not runtime_keys or not lookup:
        return None
    normalized_targets: set[str] = set()
    for value in runtime_keys:
        normalized_targets.update(_normalized_runtime_lookup_keys(value))
    if not normalized_targets:
        return None
    for key, entry in lookup.items():
        if normalized_targets & _normalized_runtime_lookup_keys(key):
            return entry
    return None


def _build_model_runtime_info(
    model: Any,
    loaded_lookup: dict[str, dict[str, Any]],
    available_lookup: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    runtime_keys = _model_runtime_keys(model)
    runtime_info = _lookup_runtime_entry(runtime_keys, loaded_lookup)
    available_info = _lookup_runtime_entry(runtime_keys, available_lookup)
    return {
        "name": model.name,
        "model_id": model.model_id,
        "role": model.role,
        "description": model.description,
        "loaded": True if model.is_cloud else runtime_info is not None,
        "available": True if model.is_cloud else available_info is not None,
        "tools_enabled": model.tools_enabled,
        "provider": model.provider,
        "selectable": direct_model_selection_error(model) is None,
        "loaded_identifier": runtime_info.get("identifier", "") if runtime_info else "",
        "size_bytes": runtime_info.get("size_bytes", 0) if runtime_info else 0,
        "status": runtime_info.get("status", "") if runtime_info else "",
        "parallel": runtime_info.get("parallel", 0) if runtime_info else 0,
        "context_length": runtime_info.get("context_length", 0) if runtime_info else 0,
        "max_context_length": runtime_info.get("max_context_length", 0) if runtime_info else 0,
        "architecture": runtime_info.get("architecture", "") if runtime_info else "",
        "quantization": runtime_info.get("quantization", "") if runtime_info else "",
        "queued": runtime_info.get("queued", 0) if runtime_info else 0,
        "estimated_gpu_bytes": runtime_info.get("estimated_gpu_bytes", 0) if runtime_info else 0,
        "estimated_total_bytes": runtime_info.get("estimated_total_bytes", 0) if runtime_info else 0,
    }


def loaded_model_runtime_infos(state: Any) -> list[dict[str, Any]]:
    if getattr(state, "backend_name", "") == "llamacpp":
        model_name = str(getattr(state, "llamacpp_model", "") or "")
        if model_name:
            return [{
                "identifier": model_name,
                "model_key": model_name,
                "display_name": model_name,
                "status": "pinned",
            }]
    runtime_infos, _loaded_lookup, _available_lookup, _inventory_ok = _studio_runtime_inventory(state)
    return runtime_infos


def visible_model_infos(state: Any) -> list[dict[str, Any]]:
    return model_catalog_infos(state, include_advanced=False)


def _is_catalog_visible_model(model: Any, *, include_advanced: bool) -> bool:
    if is_hidden_model(model) or is_spawn_only_model(model):
        return False
    if direct_model_selection_error(model) is not None:
        return False
    if is_advanced_model(model) and not include_advanced:
        return False
    tags_lower = {str(tag).lower() for tag in getattr(model, "tags", [])}
    if UI_HIDDEN_ZELDA_MODEL_TAGS & tags_lower:
        return False
    return True


def _sorted_model_infos(
    models: list[Any],
    loaded_lookup: dict[str, dict[str, Any]],
    available_lookup: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    infos: list[dict[str, Any]] = []
    for model in sorted(models, key=lambda item: z3ui_model_sort_key(item.name)):
        infos.append(_build_model_runtime_info(model, loaded_lookup, available_lookup))
    return infos


def _primary_catalog_models(
    state: Any,
    loaded_lookup: dict[str, dict[str, Any]],
    available_lookup: dict[str, dict[str, Any]],
    inventory_ok: bool,
) -> dict[str, Any]:
    visible: dict[str, Any] = {}
    for model in state.models.values():
        if not is_z3ui_model_entry(model):
            continue
        if blocked_model_reason(model):
            continue
        if direct_model_selection_error(model) is not None:
            continue
        if not _model_has_runtime_presence(model, loaded_lookup, available_lookup, inventory_ok):
            continue
        visible[model.name] = model

    return visible


def primary_model_infos(state: Any) -> list[dict[str, Any]]:
    return z3ui_model_infos(state)


def model_catalog_infos(state: Any, *, include_advanced: bool = False) -> list[dict[str, Any]]:
    _runtime_infos, loaded_lookup, available_lookup, inventory_ok = _studio_runtime_inventory(state)
    if not include_advanced:
        catalog = _primary_catalog_models(state, loaded_lookup, available_lookup, inventory_ok)
        return _sorted_model_infos(list(catalog.values()), loaded_lookup, available_lookup)

    catalog: dict[str, Any] = {}
    for model in state.models.values():
        if not _is_catalog_visible_model(model, include_advanced=True):
            continue
        if model.is_cloud:
            if _model_has_runtime_presence(model, loaded_lookup, available_lookup, inventory_ok):
                catalog[model.name] = model
            continue
        if not is_zelda_model(model):
            continue
        if not _model_has_runtime_presence(model, loaded_lookup, available_lookup, inventory_ok):
            continue
        catalog[model.name] = model

    active_model = state.models.get(getattr(state, "active_model", ""))
    if (
        active_model is not None
        and _is_catalog_visible_model(active_model, include_advanced=True)
        and (active_model.is_cloud or is_zelda_model(active_model))
        and _model_has_runtime_presence(active_model, loaded_lookup, available_lookup, inventory_ok)
    ):
        catalog[active_model.name] = active_model

    return _sorted_model_infos(list(catalog.values()), loaded_lookup, available_lookup)


def z3ui_model_infos(state: Any) -> list[dict[str, Any]]:
    _runtime_infos, loaded_lookup, available_lookup, inventory_ok = _studio_runtime_inventory(state)
    visible = _primary_catalog_models(state, loaded_lookup, available_lookup, inventory_ok)
    return _sorted_model_infos(list(visible.values()), loaded_lookup, available_lookup)


async def ensure_shell(state: Any) -> PersistentShellSession:
    if state.shell is None:
        state.shell = PersistentShellSession(state.workspace)
    await state.shell.ensure_started()
    return state.shell
