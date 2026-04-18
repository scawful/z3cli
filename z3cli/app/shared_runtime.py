"""Shared runtime helpers for z3cli entrypoints."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from z3cli.app.backends import LMStudioBackend, LlamaCppBackend
from z3cli.app.shell_session import PersistentShellSession
from z3cli.app.runtime import (
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
from z3cli.core.config import is_z3ui_model_entry, list_visible_zelda_models, z3ui_model_sort_key
from z3cli.core.engine import ChatEngine
from z3cli.core.provider import create_provider
from z3cli.protocol.lmstudio import (
    available_model_lookup,
    available_models,
    ensure_server,
    loaded_model_lookup_keys,
    loaded_models,
    normalize_loaded_model_entry,
)


def permission_rule_key(tool_name: str, server: str) -> str:
    return f"{server}:{tool_name}" if server else tool_name


def state_permission_rules(state: Any) -> dict[str, bool]:
    rules = getattr(state, "permission_rules", {})
    return dict(sorted(rules.items()))


def state_lsp_context_mode(state: Any) -> str:
    return normalize_lsp_context_mode(str(getattr(state, "lsp_context_mode", "auto") or "auto"))


def active_model_name(state: Any) -> str:
    return current_model_name(state.active_model, state.backend_name, state.llamacpp_model)


def get_backend(state: Any) -> LMStudioBackend | LlamaCppBackend:
    if state.backend_name == "llamacpp":
        return LlamaCppBackend(api_base=state.llamacpp_api_base, model=state.llamacpp_model)
    return LMStudioBackend(api_base=state.studio_api_base, host=state.host, port=state.port)


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
    if meta.get("llamacpp_model"):
        state.llamacpp_model = str(meta["llamacpp_model"])
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
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    try:
        available_entries = available_models(state.host, state.port) if state.backend_name == "studio" else []
        loaded_entries = loaded_models(state.host, state.port) if state.backend_name == "studio" else []
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
        runtime_infos.append(runtime_info)
        for key in loaded_model_lookup_keys(entry):
            loaded_lookup.setdefault(key, runtime_info)
        identifier = runtime_info.get("identifier")
        model_key = runtime_info.get("model_key")
        if isinstance(identifier, str) and identifier:
            loaded_lookup.setdefault(identifier, runtime_info)
        if isinstance(model_key, str) and model_key:
            loaded_lookup.setdefault(model_key, runtime_info)
    return runtime_infos, loaded_lookup, available_lookup


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
    runtime_infos, _loaded_lookup, _available_lookup = _studio_runtime_inventory(state)
    return runtime_infos


def visible_model_infos(state: Any) -> list[dict[str, Any]]:
    _runtime_infos, loaded_lookup, available_lookup = _studio_runtime_inventory(state)
    visible = {
        model.name: model
        for model in list_visible_zelda_models(state.models).values()
    }
    active_model = state.models.get(getattr(state, "active_model", ""))
    if active_model is not None:
        visible[active_model.name] = active_model
    for model in state.models.values():
        if model.is_cloud and model.resolve_api_key():
            visible[model.name] = model

    infos: list[dict[str, Any]] = []
    for model in sorted(visible.values(), key=lambda item: item.name):
        runtime_info = loaded_lookup.get(model.name) or loaded_lookup.get(model.model_id)
        available_info = available_lookup.get(model.model_id) or available_lookup.get(model.name)
        infos.append({
            "name": model.name,
            "model_id": model.model_id,
            "role": model.role,
            "description": model.description,
            "loaded": True if model.is_cloud else runtime_info is not None,
            "available": True if model.is_cloud else available_info is not None,
            "tools_enabled": model.tools_enabled,
            "provider": model.provider,
            "loaded_identifier": runtime_info.get("identifier", "") if runtime_info else "",
            "size_bytes": runtime_info.get("size_bytes", 0) if runtime_info else 0,
            "status": runtime_info.get("status", "") if runtime_info else "",
            "parallel": runtime_info.get("parallel", 0) if runtime_info else 0,
            "context_length": runtime_info.get("context_length", 0) if runtime_info else 0,
            "max_context_length": runtime_info.get("max_context_length", 0) if runtime_info else 0,
            "architecture": runtime_info.get("architecture", "") if runtime_info else "",
            "quantization": runtime_info.get("quantization", "") if runtime_info else "",
            "queued": runtime_info.get("queued", 0) if runtime_info else 0,
        })
    return infos


def z3ui_model_infos(state: Any) -> list[dict[str, Any]]:
    _runtime_infos, loaded_lookup, available_lookup = _studio_runtime_inventory(state)
    infos: list[dict[str, Any]] = []
    for model in sorted(
        (
            model
            for model in list_visible_zelda_models(state.models).values()
            if is_z3ui_model_entry(model) and not blocked_model_reason(model)
        ),
        key=lambda item: z3ui_model_sort_key(item.name),
    ):
        runtime_info = loaded_lookup.get(model.name) or loaded_lookup.get(model.model_id)
        available_info = available_lookup.get(model.model_id) or available_lookup.get(model.name)
        infos.append({
            "name": model.name,
            "model_id": model.model_id,
            "role": model.role,
            "description": model.description,
            "loaded": runtime_info is not None,
            "available": available_info is not None,
            "tools_enabled": model.tools_enabled,
            "provider": model.provider,
            "loaded_identifier": runtime_info.get("identifier", "") if runtime_info else "",
            "size_bytes": runtime_info.get("size_bytes", 0) if runtime_info else 0,
            "status": runtime_info.get("status", "") if runtime_info else "",
            "parallel": runtime_info.get("parallel", 0) if runtime_info else 0,
            "context_length": runtime_info.get("context_length", 0) if runtime_info else 0,
            "max_context_length": runtime_info.get("max_context_length", 0) if runtime_info else 0,
            "architecture": runtime_info.get("architecture", "") if runtime_info else "",
            "quantization": runtime_info.get("quantization", "") if runtime_info else "",
            "queued": runtime_info.get("queued", 0) if runtime_info else 0,
        })
    return infos


async def ensure_shell(state: Any) -> PersistentShellSession:
    if state.shell is None:
        state.shell = PersistentShellSession(state.workspace)
    await state.shell.ensure_started()
    return state.shell
