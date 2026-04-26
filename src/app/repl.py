"""Interactive Zelda CLI harness for LM Studio models and MCP tools."""

from __future__ import annotations

import argparse
import asyncio
import os
import shlex
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.console import Console

from app.version import __version__
from app.backends import DEFAULT_LLAMACPP_API_BASE
from app.command_catalog import build_repl_help_text
from core.config import (
    API_BASE, HISTORY_FILE, MCP_CONFIG_PATH, REGISTRY_PATH, SESSION_DIR,
    ModelConfig, RouterConfig, load_llamacpp_nodes, load_registry, load_studio_nodes, rollout_warnings,
)
from app.display import (
    MarkdownStreamer, ThinkingStreamer, ToolPanel, build_bottom_toolbar,
    render_stats_table, render_welcome_banner,
)
from core.engine import (
    ChatEngine, DoneEvent, ErrorEvent, TextEvent, ThinkingEvent,
    ToolCallEvent, ToolResultEvent, summarize_tool_result_for_history,
)
from protocol.lmstudio import ensure_server, server_status, total_loaded_model_bytes
from app.runtime import (
    DEFAULT_ACTIVE_MODEL, DEFAULT_BROADCAST_MODELS, DEFAULT_LLAMACPP_MODEL, DEFAULT_ROM,
    DEFAULT_WORKSPACE, LSP_CONTEXT_MODES, SPECIALIST_NAMES, VALID_BACKENDS, VALID_MODES, build_harness_prompt,
    ORACLE_FAMILY_MODELS,
    add_attachment_context_packs,
    add_construct_context_packs,
    build_local_identity_prompt, build_oracle_answer_after_grounding_prompt, build_oracle_coder_prompt, build_oracle_hidden_routing_prompt, build_oracle_natural_chat_prompt, build_oracle_prefetch_forced_reply, build_oracle_prefetch_session_records, build_oracle_register_grounding_prompt, build_tool_bias_prompt, build_tool_use_prompt, build_unavailable_tool_forced_reply, collect_oracle_context_packs,
    choose_startup_model,
    default_orchestrator_model, engine_key, enrich_prompt_with_attachments, enrich_prompt_with_construct_refs, enrich_prompt_with_oracle_context,
    ensure_model_available, ensure_targets_available,
    load_enriched_focus_file, lsp_context_status_label, merge_system_prompts, mode_usage_text, normalize_lsp_context_mode, normalize_mode,
    oracle_prompting_tips_text,
    resolve_existing_model_name, resolve_message_attachments, resolve_message_construct_refs,
    resolve_oracle_profile_system_prompts, resolve_targets,
)
from app.shared_runtime import (
    active_model_name,
    available_route_targets,
    apply_use_target,
    compact_session_history,
    clear_focus_context as _clear_focus_context,
    ensure_shell,
    get_backend,
    get_or_create_engine,
    model_catalog_infos,
    permission_rule_key as _permission_rule_key,
    persist_state as _persist_state,
    refresh_focus_context as _refresh_focus_context,
    loaded_model_runtime_infos,
    maybe_reset_engine_for_topic_shift,
    resolve_focus_context as _resolve_focus_context,
    resolve_request_model_name as _resolve_request_model_name,
    restore_runtime_state as _restore_runtime_state,
    route_list_include_advanced,
    select_studio_node,
    select_llamacpp_node,
    set_backend,
    set_focus_context as _set_focus_context,
    smoke_current_route,
    state_permission_rules,
    primary_model_infos,
    use_lean_llamacpp_prompt,
    visible_model_infos,
)
from app.shell_session import PersistentShellSession
from core.session import (
    Session, export_training, find_session, list_sessions, load_session_bundle,
    load_session_bundle_without_thinking, load_tool_invocations,
)
from core.subagent import SubagentRunner
from core.subagent_bridge import SubagentBridge
from core.tool_bridge import CompositeBridge, ToolBridge
from app.tooling import connect_tool_bridge, wrap_bridge_for_model
from app.verify import run_verification_hooks
from app.write_review import ToolWriteContext, detect_changes, prepare_write_context

# Optional prompt_toolkit — degrade to input() if missing
try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.patch_stdout import patch_stdout as _patch_stdout
    HAS_PROMPT_TOOLKIT = True
except ImportError:
    PromptSession = None  # type: ignore[assignment]
    FileHistory = None  # type: ignore[assignment]
    HAS_PROMPT_TOOLKIT = False

class _AppStateSlice:
    """Base for read/write slice views over :class:`AppState`.

    Each slice exposes a narrow, semantically-grouped subset of AppState
    fields as attributes that delegate back to the owning state instance.
    This lets callers write ``state.routing.active_model = "nayru"`` while
    the underlying data still lives in one flat dataclass — no data
    duplication, no eager detachment. Slices are stateless proxies.
    """

    __slots__ = ("_state",)

    def __init__(self, state: "AppState") -> None:
        self._state = state


def _slice_property(field_name: str) -> property:
    def getter(self: _AppStateSlice):
        return getattr(self._state, field_name)

    def setter(self: _AppStateSlice, value) -> None:
        setattr(self._state, field_name, value)

    return property(getter, setter)


class _RoutingSlice(_AppStateSlice):
    """Model selection, mode, broadcast targets, orchestrator pinning."""

    active_model = _slice_property("active_model")
    mode = _slice_property("mode")
    broadcast_models = _slice_property("broadcast_models")
    orchestrator_model = _slice_property("orchestrator_model")
    last_active_model = _slice_property("last_active_model")


class _BackendSlice(_AppStateSlice):
    """Backend identity + endpoint wiring."""

    backend_name = _slice_property("backend_name")
    api_base = _slice_property("api_base")
    host = _slice_property("host")
    port = _slice_property("port")
    studio_api_base = _slice_property("studio_api_base")
    studio_node = _slice_property("studio_node")
    llamacpp_api_base = _slice_property("llamacpp_api_base")
    llamacpp_model = _slice_property("llamacpp_model")
    auto_load = _slice_property("auto_load")
    auto_start_server = _slice_property("auto_start_server")


class _MetricsSlice(_AppStateSlice):
    """Aggregated counters kept for display + session serialization."""

    message_count = _slice_property("message_count")
    tool_call_count = _slice_property("tool_call_count")
    prompt_tokens = _slice_property("prompt_tokens")
    completion_tokens = _slice_property("completion_tokens")
    last_active_at = _slice_property("last_active_at")


class _UiSlice(_AppStateSlice):
    """Console handle + focus context + surfaced warnings."""

    console = _slice_property("console")
    focus_context = _slice_property("focus_context")
    focus_path = _slice_property("focus_path")
    startup_warnings = _slice_property("startup_warnings")
    bridge_errors = _slice_property("bridge_errors")


class _PendingOpsSlice(_AppStateSlice):
    """Pending permission decisions and write-review contexts."""

    permission_rules = _slice_property("permission_rules")
    pending_write_contexts = _slice_property("pending_write_contexts")


@dataclass
class AppState:
    console: Console
    host: str
    port: int
    api_base: str
    backend_name: str
    studio_api_base: str
    llamacpp_api_base: str
    llamacpp_model: str
    registry_path: Path
    mcp_path: Path
    models: dict[str, ModelConfig]
    routers: dict[str, RouterConfig]
    active_model: str
    mode: str
    auto_load: bool
    auto_start_server: bool
    workspace: Path
    rom_path: Path | None
    temperature: float
    max_tokens: int
    broadcast_models: list[str]
    tools_enabled: bool
    studio_nodes: dict[str, Any] = field(default_factory=dict)
    studio_node: str = ""
    llamacpp_nodes: dict[str, Any] = field(default_factory=dict)
    llamacpp_node: str = ""
    tools_write: bool = False
    verify_hooks: bool = True
    bridge: ToolBridge | None = None
    bridge_errors: list[str] = field(default_factory=list)
    startup_warnings: list[str] = field(default_factory=list)
    engines: dict[str, ChatEngine] = field(default_factory=dict)
    shell: PersistentShellSession | None = None
    session: Session | None = None
    message_count: int = 0
    tool_call_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    focus_context: str = ""
    focus_path: Path | None = None
    last_active_at: str = ""
    last_active_model: str = ""
    orchestrator_model: str = ""
    lsp_context_mode: str = "auto"
    permission_rules: dict[str, bool] = field(default_factory=dict)
    pending_write_contexts: dict[str, ToolWriteContext] = field(default_factory=dict)
    subagent_tools_enabled: bool = True
    _subagent_runner: SubagentRunner | None = None
    _first_message_sent: bool = False

    def __post_init__(self) -> None:
        # Slice views expose semantically-grouped subsets of the fields
        # above. Existing flat access (``state.active_model``) still
        # works; new code can prefer ``state.routing.active_model``.
        self.routing = _RoutingSlice(self)
        self.backend_state = _BackendSlice(self)
        self.metrics = _MetricsSlice(self)
        self.ui = _UiSlice(self)
        self.pending_ops = _PendingOpsSlice(self)
async def replace_bridge(state: AppState, bridge: ToolBridge | None, warnings: list[str]) -> None:
    old_bridge = state.bridge
    state.bridge = bridge
    state.bridge_errors = warnings
    for engine in state.engines.values():
        engine.bridge = bridge
    if old_bridge is not None:
        await old_bridge.close()


async def refresh_tool_bridge(state: AppState) -> None:
    if not state.tools_enabled:
        await replace_bridge(state, None, [])
    else:
        bridge, warnings = await connect_tool_bridge(
            state.workspace,
            state.mcp_path,
            rom_path=getattr(state, "rom_path", None),
        )
        await replace_bridge(state, bridge, warnings)
    await _refresh_focus_context(state)


def build_system_prompt(state: AppState, focus_context: str | None = None) -> str:
    lean_prompt = use_lean_llamacpp_prompt(state)
    return build_harness_prompt(
        state.workspace,
        state.rom_path,
        state.focus_context if focus_context is None else focus_context,
        include_project_context=not lean_prompt,
    )


def get_engine(state: AppState, model_name: str) -> ChatEngine:
    return get_or_create_engine(
        state,
        model_name,
        permission_hook=lambda tool_name, arguments, server, call_id: _tool_permission_hook(
            state, tool_name, arguments, server, call_id,
        ),
        post_tool_hook=lambda tool_name, arguments, result, server, call_id: _post_tool_hook(
            state, tool_name, arguments, result, server, call_id,
        ),
        tool_invocation_hook=lambda payload: _tool_invocation_hook(state, model_name, payload),
    )


def _wrap_subagent_bridge_for_model(state: AppState, bridge: ToolBridge | None, model: ModelConfig) -> ToolBridge | None:
    return wrap_bridge_for_model(
        bridge,
        model.tool_profile,
        read_only=not state.tools_write,
        deferred_tools=model.deferred_tools,
        core_tools=model.core_tools,
    )


async def _build_subagent_system_context(state: AppState, model: ModelConfig, prompt: str) -> str:
    focus_context = await _resolve_focus_context(state, model.name, query=prompt)
    return build_system_prompt(state, focus_context)


def _get_subagent_runner(state: AppState) -> SubagentRunner:
    if state._subagent_runner is None:
        state._subagent_runner = SubagentRunner(
            bridge=state.bridge,
            permission_hook=lambda tool_name, arguments, server, call_id: _tool_permission_hook(
                state, tool_name, arguments, server, call_id,
            ),
            bridge_wrapper=lambda bridge, model: _wrap_subagent_bridge_for_model(state, bridge, model),
            models=state.models,
            system_context_resolver=lambda model, prompt: _build_subagent_system_context(state, model, prompt),
        )
    else:
        state._subagent_runner.set_bridge(state.bridge)
        state._subagent_runner.set_system_context_resolver(
            lambda model, prompt: _build_subagent_system_context(state, model, prompt),
        )
    return state._subagent_runner


def compose_repl_request_bridge(state: AppState, model: ModelConfig) -> ToolBridge | None:
    base_bridge = wrap_bridge_for_model(
        state.bridge,
        model.tool_profile,
        read_only=not state.tools_write,
        deferred_tools=model.deferred_tools,
        core_tools=model.core_tools,
    )
    if state.subagent_tools_enabled:
        subagent_bridge = SubagentBridge(
            runner=_get_subagent_runner(state),
            models=state.models,
            system_context_fn=lambda child_model, prompt: _build_subagent_system_context(state, child_model, prompt),
            parent_model=model.name,
        )
        if base_bridge is None:
            base_bridge = subagent_bridge
        else:
            base_bridge = CompositeBridge([base_bridge, subagent_bridge])
    return base_bridge


async def _tool_invocation_hook(state: AppState, model_name: str, payload: dict) -> None:
    session = getattr(state, "session", None)
    if session is None or session.path is None:
        return
    try:
        session.append_tool_invocation(
            tool=str(payload.get("tool", "")),
            server=str(payload.get("server", "")),
            duration_ms=float(payload.get("duration_ms", 0.0) or 0.0),
            status=str(payload.get("status", "")),
            model=model_name,
            call_id=str(payload.get("call_id", "")),
            error=str(payload.get("error", "")),
        )
    except Exception:
        pass


async def _tool_permission_hook(
    state: AppState,
    tool_name: str,
    arguments: str,
    server: str,
    call_id: str,
) -> bool:
    rule_key = _permission_rule_key(tool_name, server)
    write_context = prepare_write_context(state.workspace, tool_name, arguments, call_id)
    if write_context is not None:
        state.pending_write_contexts[call_id] = write_context
    cached = state.permission_rules.get(rule_key)
    if cached is not None:
        if not cached:
            state.pending_write_contexts.pop(call_id, None)
        return cached
    return True


async def _post_tool_hook(
    state: AppState,
    tool_name: str,
    arguments: str,
    result: str,
    server: str,
    call_id: str,
) -> str:
    del tool_name, arguments, server
    write_context = state.pending_write_contexts.pop(call_id, None)
    if write_context is None:
        return result

    changes = detect_changes(write_context)
    if not changes:
        return result

    accepted_note = "[Filesystem diff auto-accepted in REPL.]"
    if not state.verify_hooks:
        return result + "\n\n" + accepted_note

    try:
        verification = await run_verification_hooks(
            state.workspace,
            [change.path for change in changes],
            bridge=state.bridge,
            rom_path=state.rom_path,
        )
    except Exception as exc:
        return result + f"\n\n{accepted_note}\n\n[Verification failed to run: {exc}]"

    rendered = verification.render()
    if not rendered:
        return result + "\n\n" + accepted_note
    return result + f"\n\n{accepted_note}\n\n{rendered}"


def preview_targets(state: AppState, prompt: str) -> list[ModelConfig]:
    return resolve_targets(
        models=state.models,
        routers=state.routers,
        active_model=state.active_model,
        mode=state.mode,
        prompt=prompt,
        broadcast_models=state.broadcast_models,
        backend_name=state.backend_name,
        llamacpp_model=state.llamacpp_model,
        temperature=state.temperature,
        max_tokens=state.max_tokens,
        orchestrator_model=state.orchestrator_model,
    )


def render_model_table(state: AppState, models: list[dict[str, Any]] | None = None, *, title: str = "Zelda Models") -> None:
    from rich.table import Table
    table = Table(title=title, show_lines=False)
    table.add_column("", no_wrap=True)
    table.add_column("Model", no_wrap=True)
    table.add_column("Provider", no_wrap=True)
    table.add_column("Loaded", no_wrap=True)
    table.add_column("Use")
    table.add_column("Runtime")
    for model in models if models is not None else visible_model_infos(state):
        runtime = " · ".join(
            part
            for part in (
                _format_loaded_status(model),
                _format_loaded_estimate(model),
                _format_memory_bytes(int(model.get("size_bytes", 0) or 0)),
            )
            if part and part != "-"
        )
        table.add_row(
            "*" if model["name"] == state.active_model else "",
            str(model["name"]),
            str(model["provider"]),
            "yes" if model["loaded"] else "no",
            _compact_model_text(str(model.get("description") or model.get("role") or ""), 54),
            runtime or ("available" if model.get("available") else "unavailable"),
        )
    state.console.print(table)
    state.console.print(
        "Default list is intentionally small: Oracle lanes plus [bold]din[/bold], [bold]nayru[/bold], and [bold]navi[/bold]. "
        "Use [bold]models catalog advanced[/bold] for quants, raw fallbacks, and manual heavy lanes."
    )


def _compact_model_text(value: str, limit: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 1)].rstrip() + "…"


def _format_memory_bytes(size_bytes: int) -> str:
    if size_bytes <= 0:
        return "-"
    gib = size_bytes / (1024 ** 3)
    if gib >= 10:
        return f"{gib:.1f} GiB"
    return f"{gib:.2f} GiB"


def _format_context_length(context_length: int) -> str:
    if context_length <= 0:
        return ""
    if context_length >= 1000:
        return f"ctx {round(context_length / 1000)}k"
    return f"ctx {context_length}"


def _format_loaded_status(entry: dict[str, Any]) -> str:
    parts: list[str] = []
    status = str(entry.get("status", "") or "")
    if status:
        parts.append(status)
    parallel = int(entry.get("parallel", 0) or 0)
    if parallel > 0:
        parts.append(f"p{parallel}")
    queued = int(entry.get("queued", 0) or 0)
    if queued > 0:
        parts.append(f"q{queued}")
    context_length = int(entry.get("context_length", 0) or 0)
    context_text = _format_context_length(context_length)
    if context_text:
        parts.append(context_text)
    quantization = str(entry.get("quantization", "") or "")
    if quantization:
        parts.append(quantization)
    return " · ".join(parts) if parts else "-"


def _format_loaded_estimate(entry: dict[str, Any]) -> str:
    gpu = _format_memory_bytes(int(entry.get("estimated_gpu_bytes", 0) or 0))
    total = _format_memory_bytes(int(entry.get("estimated_total_bytes", 0) or 0))
    if gpu != "-" and total != "-":
        if gpu == total:
            return f"gpu/total {gpu}"
        return f"gpu {gpu} · total {total}"
    if gpu != "-":
        return f"gpu {gpu}"
    if total != "-":
        return f"total {total}"
    return "-"


def render_loaded_model_table(state: AppState, loaded: list[dict[str, Any]]) -> None:
    from rich.table import Table

    if not loaded:
        state.console.print("No loaded API models reported by the active backend.")
        return

    table = Table(title="Loaded Models")
    table.add_column("Identifier")
    table.add_column("Model")
    table.add_column("Mem")
    table.add_column("Estimate")
    table.add_column("Status")
    for entry in loaded:
        table.add_row(
            str(entry.get("identifier", "") or "?"),
            str(entry.get("display_name", "") or entry.get("model_key", "") or "?"),
            _format_memory_bytes(int(entry.get("size_bytes", 0) or 0)),
            _format_loaded_estimate(entry),
            _format_loaded_status(entry),
        )
    state.console.print(table)
    state.console.print(
        f"Concurrent loaded models: {len(loaded)} · total { _format_memory_bytes(total_loaded_model_bytes(loaded)) }",
    )


def print_status(state: AppState) -> None:
    state.console.print(f"Backend: {state.backend_name}")
    if state.backend_name == "studio":
        status = server_status(state.host, state.port)
        loaded = loaded_model_runtime_infos(state)
        state.console.print(f"LM Studio running: {status.get('running')} on port {status.get('port')}")
        state.console.print(f"API base: {state.studio_api_base}")
        if state.studio_node:
            state.console.print(f"studio node: {state.studio_node}")
        state.console.print(
            f"Loaded models: {len(loaded)} · total {_format_memory_bytes(total_loaded_model_bytes(loaded))}",
        )
    else:
        state.console.print(f"llama.cpp API base: {state.llamacpp_api_base}")
        state.console.print(f"Pinned model: {state.llamacpp_model}")
        if state.llamacpp_node:
            state.console.print(f"llama.cpp node: {state.llamacpp_node}")
    state.console.print(f"Mode: {state.mode}")
    state.console.print(f"Active model: {active_model_name(state)}")
    state.console.print(f"Workspace: {state.workspace}")
    state.console.print(f"ROM: {state.rom_path or '(none)'}")
    state.console.print(f"Tools enabled: {state.tools_enabled}")
    state.console.print(f"Tool write access: {state.tools_write}")
    state.console.print(f"Verification hooks: {state.verify_hooks}")
    state.console.print(
        f"LSP context: {state.lsp_context_mode} ({lsp_context_status_label(state.lsp_context_mode, state.models.get(state.active_model))})"
    )
    if state.bridge:
        state.console.print(f"Connected tool servers: {', '.join(state.bridge.server_names) or '(none)'}")
        state.console.print(f"Tool count: {state.bridge.tool_count}")
    elif state.bridge_errors:
        state.console.print(f"Tool connection warnings: {'; '.join(state.bridge_errors)}")
    if state.startup_warnings:
        state.console.print(f"Startup warnings: {'; '.join(state.startup_warnings)}")
    rollout_notes = rollout_warnings(state.models)
    if rollout_notes:
        state.console.print(f"Rollout warnings: {'; '.join(rollout_notes)}")
    if state.permission_rules:
        allow = sorted(key for key, value in state.permission_rules.items() if value)
        deny = sorted(key for key, value in state.permission_rules.items() if not value)
        state.console.print(f"Permission allow rules: {', '.join(allow) if allow else '(none)'}")
        state.console.print(f"Permission deny rules: {', '.join(deny) if deny else '(none)'}")
    if state.shell is not None:
        state.console.print(f"Shell active: {state.shell.active}")
        state.console.print(f"Shell cwd: {state.shell.cwd}")


async def list_loaded_api(state: AppState) -> None:
    backend = get_backend(state)
    details_method = getattr(backend, "list_loaded_model_details", None)
    if callable(details_method):
        loaded = await details_method()  # type: ignore[misc]
    elif hasattr(backend, "list_loaded_models"):
        names = await backend.list_loaded_models()  # type: ignore[misc]
        loaded = [{"identifier": name, "model_key": name, "display_name": name} for name in names]
    else:
        loaded = []
    render_loaded_model_table(state, loaded)


# ---------------------------------------------------------------------------
# Streaming with Markdown rendering and tool panels
# ---------------------------------------------------------------------------

async def stream_response(
    state: AppState,
    target: ModelConfig,
    prompt: str,
    *,
    display_prompt: str = "",
    focus_context: str | None = None,
    target_count: int | None = None,
) -> None:
    ensure_model_available(target)
    route_prompt = display_prompt or prompt
    request_name = _resolve_request_model_name(state, target)
    engine = get_engine(state, target.name)
    maybe_reset_engine_for_topic_shift(engine, route_prompt)

    # Apply model-specific tools and compose REPL subagent delegation when enabled.
    effective_bridge = compose_repl_request_bridge(state, target)
    engine.bridge = effective_bridge
    tools_available = bool(effective_bridge and state.tools_enabled and target.tools_enabled)
    use_native_tools = bool(tools_available and target.native_tools)
    system_prompt = merge_system_prompts(
        build_system_prompt(state, focus_context),
        build_local_identity_prompt(target),
        build_oracle_natural_chat_prompt(route_prompt) if target.name in ORACLE_FAMILY_MODELS else "",
        build_oracle_hidden_routing_prompt(route_prompt),
        build_oracle_register_grounding_prompt(route_prompt),
        build_tool_use_prompt(
            tools_available,
            target.tool_profile,
            deferred_tools=target.deferred_tools,
            native_tools=target.native_tools,
        ),
        build_tool_bias_prompt(
            route_prompt,
            tools_available,
            target.tool_profile,
            deferred_tools=target.deferred_tools,
            native_tools=target.native_tools,
        ),
        build_oracle_coder_prompt(target, route_prompt, state.models),
        *resolve_oracle_profile_system_prompts(route_prompt),
        target.system_prompt,
    )

    # Enable thinking mode when the model has a thinking_tier configured
    use_thinking = bool(target.thinking_tier)

    visible_target_count = target_count if target_count is not None else len(preview_targets(state, route_prompt))
    prefix = f"[{target.name}] " if state.mode != "manual" or visible_target_count > 1 else ""
    if prefix:
        state.console.print(f"[bold cyan]{prefix}[/bold cyan]")

    streamer: MarkdownStreamer | None = None
    thinking_streamer: ThinkingStreamer | None = None

    def ensure_streamer() -> MarkdownStreamer:
        nonlocal streamer
        if streamer is None:
            streamer = MarkdownStreamer(state.console)
            streamer.start()
        return streamer

    def ensure_thinking() -> ThinkingStreamer:
        nonlocal thinking_streamer
        if thinking_streamer is None:
            thinking_streamer = ThinkingStreamer(state.console)
            thinking_streamer.start()
        return thinking_streamer

    def finish_thinking() -> None:
        nonlocal thinking_streamer
        if thinking_streamer is not None:
            thinking_streamer.finish()
            thinking_streamer = None

    # For local models with tool profiles, truncate large tool results
    # to avoid flooding the context window.  4000 chars ~= 1000 tokens.
    max_tool_result = 4000 if target.tool_profile and target.tool_profile != "*" else 0
    answer_after_grounding_system = (
        build_oracle_answer_after_grounding_prompt(route_prompt)
        if target.name in ORACLE_FAMILY_MODELS
        else ""
    )

    async for event in engine.chat(
        message=prompt,
        model_id=request_name,
        system=system_prompt,
        temperature=target.temperature or state.temperature,
        max_tokens=target.max_tokens or state.max_tokens,
        use_tools=use_native_tools,
        thinking=use_thinking,
        max_tool_result=max_tool_result,
        answer_after_first_grounding=bool(answer_after_grounding_system),
        answer_after_grounding_system=answer_after_grounding_system,
        allow_manual_tool_calls=tools_available,
    ):
        if isinstance(event, ThinkingEvent):
            ensure_thinking().feed(event.text)

        elif isinstance(event, TextEvent):
            # Transition from thinking to text — close thinking panel
            finish_thinking()
            ensure_streamer().feed(event.text)

        elif isinstance(event, ToolCallEvent):
            # Finish any in-progress panels before showing tool panel
            finish_thinking()
            if streamer is not None:
                streamer.finish()
                streamer = None
            state.console.print(ToolPanel.render_call(event.name, event.server, event.arguments))
            state.tool_call_count += 1
            # Record tool call in session
            if state.session:
                state.session.append_engine_msg(target.name, {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "name": event.name,
                        "arguments": event.arguments,
                        "server": event.server,
                        "tool_call_id": event.call_id,
                        "tool_group": event.call_id,
                    }],
                })
            _persist_state(state, model_name=target.name)

        elif isinstance(event, ToolResultEvent):
            state.console.print(ToolPanel.render_result(event.name, event.result))
            if state.session:
                history_result = summarize_tool_result_for_history(
                    event.name,
                    event.result,
                    max_chars=max_tool_result,
                )
                state.session.append_engine_msg(target.name, {
                    "role": "tool",
                    "name": event.name,
                    "server": event.server,
                    "tool_call_id": event.call_id,
                    "tool_group": event.call_id,
                    "content": history_result,
                })

        elif isinstance(event, ErrorEvent):
            finish_thinking()
            if streamer is not None:
                streamer.feed_error(event.message)
            else:
                state.console.print(f"[red]{event.message}[/red]")

        elif isinstance(event, DoneEvent):
            finish_thinking()
            full_text = ""
            if streamer is not None:
                full_text = streamer.finish()
                streamer = None
            state.message_count += 1
            state.prompt_tokens += event.prompt_tokens
            state.completion_tokens += event.completion_tokens
            _persist_state(state, model_name=target.name)
            # Record the final assistant message in session
            if state.session and full_text:
                state.session.append_engine_msg(target.name, {
                    "role": "assistant",
                    "content": full_text,
                })


async def send_prompt(state: AppState, prompt: str) -> None:
    _ensure_session_started(state)
    # Record user message in session
    targets = preview_targets(state, prompt)
    ensure_targets_available(targets)
    attachments = resolve_message_attachments(state.workspace, prompt)
    construct_refs = resolve_message_construct_refs(state.workspace, prompt)
    attachment_meta = [
        {
            "path": str(item["path"]),
            "lines": int(item["lines"]),
            "chars": int(item["chars"]),
        }
        for item in attachments
    ]
    construct_ref_meta = [
        {
            "kind": str(item["kind"]),
            "query": str(item["query"]),
            **({"token": str(item["token"])} if item.get("token") else {}),
            **({"id": str(item["id"])} if item.get("id") else {}),
            **({"label": str(item["label"])} if item.get("label") else {}),
        }
        for item in construct_refs
    ]
    target_turns: list[tuple[ModelConfig, str, str, list[dict[str, Any]], str]] = []
    for target in targets:
        target_prefetch_bridge = None
        if state.tools_enabled and bool(getattr(target, "tools_enabled", False)):
            target_prefetch_bridge = wrap_bridge_for_model(
                state.bridge,
                getattr(target, "tool_profile", ""),
                read_only=not state.tools_write,
                deferred_tools=bool(getattr(target, "deferred_tools", False)),
                core_tools=list(getattr(target, "core_tools", [])),
            )
        target_construct_refs = await add_construct_context_packs(
            construct_refs,
            bridge=state.bridge,
            workspace=state.workspace,
        )
        target_attachments = await add_attachment_context_packs(
            attachments,
            bridge=state.bridge,
            model=target,
            lsp_context_mode=state.lsp_context_mode,
            prompt_query=prompt,
        )
        lean_prompt = use_lean_llamacpp_prompt(state)
        oracle_context = await collect_oracle_context_packs(
            prompt,
            bridge=target_prefetch_bridge,
            model=target,
            max_chars=1200 if lean_prompt else 2400,
            max_calls=2 if lean_prompt else 4,
        )
        target_engine_prompt = enrich_prompt_with_attachments(
            enrich_prompt_with_construct_refs(prompt, target_construct_refs),
            target_attachments,
        )
        target_engine_prompt = enrich_prompt_with_oracle_context(target_engine_prompt, oracle_context)
        target_focus_context = await _resolve_focus_context(state, target.name, query=prompt)
        forced_reply = (
            build_oracle_prefetch_forced_reply(prompt, oracle_context)
            or build_unavailable_tool_forced_reply(prompt, target_prefetch_bridge)
        )
        target_turns.append((target, target_engine_prompt, target_focus_context, oracle_context, forced_reply))
    if state.session:
        for target, target_engine_prompt, _target_focus_context, oracle_context, _forced_reply in target_turns:
            state.session.append_engine_msg(target.name, {
                "role": "user",
                "content": target_engine_prompt,
                "display_content": prompt,
                "attachments": attachment_meta,
                "construct_refs": construct_ref_meta,
            })
            for record in build_oracle_prefetch_session_records(prompt, oracle_context):
                state.session.append_engine_msg(target.name, {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "name": record["tool_name"],
                        "arguments": record["arguments_json"],
                        "server": record["server"],
                        "tool_call_id": record["tool_call_id"],
                        "tool_group": record["tool_group"],
                    }],
                })
                state.session.append_engine_msg(target.name, {
                    "role": "tool",
                    "name": record["tool_name"],
                    "server": record["server"],
                    "tool_call_id": record["tool_call_id"],
                    "tool_group": record["tool_group"],
                    "content": record["content"],
                })
                state.tool_call_count += 1
        # Rename session file based on first message
        if not state._first_message_sent:
            state.session.rename_from_first_message(prompt)
            state._first_message_sent = True
    _persist_state(state)

    for target, target_engine_prompt, target_focus_context, _oracle_context, forced_reply in target_turns:
        if forced_reply:
            visible_target_count = len(target_turns)
            prefix = f"[{target.name}] " if state.mode != "manual" or visible_target_count > 1 else ""
            if prefix:
                state.console.print(f"[bold cyan]{prefix}[/bold cyan]")
            state.console.print(forced_reply)
            state.message_count += 1
            if state.session:
                state.session.append_engine_msg(target.name, {
                    "role": "assistant",
                    "content": forced_reply,
                })
            _persist_state(state, model_name=target.name)
            continue
        await stream_response(
            state,
            target,
            target_engine_prompt,
            display_prompt=prompt,
            focus_context=target_focus_context,
            target_count=len(target_turns),
        )


def _ensure_session_started(state: AppState) -> None:
    if state.session is not None and state.session.path is not None:
        return
    state.last_active_model = state.active_model
    state.last_active_at = datetime.now(timezone.utc).isoformat()
    state.session = Session(SESSION_DIR)
    state.session.start(
        active_model=state.active_model,
        backend=state.backend_name,
        mode=state.mode,
        workspace=str(state.workspace),
        rom_path=str(state.rom_path) if state.rom_path else "",
        tools_enabled=state.tools_enabled,
        broadcast_models=state.broadcast_models,
        studio_api_base=state.studio_api_base,
        studio_node=state.studio_node,
        llamacpp_model=state.llamacpp_model,
        llamacpp_api_base=state.llamacpp_api_base,
        llamacpp_node=state.llamacpp_node,
        tools_write=state.tools_write,
        verify_hooks=state.verify_hooks,
        focus_path=str(state.focus_path) if state.focus_path else "",
    )


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def current_mode_help() -> str:
    return (
        "Modes: manual (active model only), oracle (portfolio router), "
        "orchestrator (delegate via planner), "
        "broadcast (fan out to multiple models)"
    )


def _smoke_failure_result(state: AppState, error: str) -> dict[str, Any]:
    return {
        "ok": False,
        "matched": False,
        "backend": state.backend_name,
        "api_base": state.llamacpp_api_base if state.backend_name == "llamacpp" else state.studio_api_base,
        "node": state.llamacpp_node if state.backend_name == "llamacpp" else state.studio_node,
        "model": active_model_name(state),
        "text": "",
        "thinking": "",
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "duration_ms": 0,
        "stop_reason": "",
        "error": error,
    }


def print_route_targets(state: AppState, *, title: str = "routes", include_advanced: bool = False) -> None:
    state.console.print(
        f"Current: backend={state.backend_name}, model={active_model_name(state)}, "
        f"studio_node={state.studio_node or '-'}, llamacpp_node={state.llamacpp_node or '-'}",
    )
    entries = available_route_targets(state, include_advanced=include_advanced)
    if not entries:
        state.console.print(f"No named {title} available.")
        return
    state.console.print(f"{title}:")
    for entry in entries:
        desc = f" · {entry['description']}" if entry.get("description") else ""
        model = f" ({entry['model']})" if entry.get("model") else ""
        aliases = entry.get("aliases")
        alias_text = ""
        if isinstance(aliases, list) and aliases:
            alias_text = " · aliases: " + ", ".join(str(alias) for alias in aliases)
        advanced = " · advanced" if entry.get("advanced") else ""
        state.console.print(f"  {entry['name']:<20} {entry['backend']}{model}{desc}{alias_text}{advanced}")


async def apply_route_target_for_state(
    state: AppState,
    target_name: str,
    *,
    reason: str,
) -> tuple[dict[str, str] | None, str | None]:
    old_backend = state.backend_name
    old_model = state.active_model
    result, error = apply_use_target(state, target_name)
    if result is None:
        return None, error or "Unknown route target"
    if state.backend_name == "studio":
        ensure_model_available(state.models.get(state.active_model))
        await _refresh_focus_context(state)
    if state.session:
        if old_backend != state.backend_name:
            state.session.append_backend_switch(old_backend, state.backend_name)
        if old_model != state.active_model:
            state.session.append_model_switch(old_model, state.active_model, reason=reason)
    _persist_state(
        state,
        {
            "studio_node": state.studio_node,
            "studio_api_base": state.studio_api_base,
            "llamacpp_node": state.llamacpp_node,
            "llamacpp_api_base": state.llamacpp_api_base,
            "llamacpp_model": state.llamacpp_model,
        },
        model_name=state.active_model,
    )
    return result, None


async def run_smoke_probe_for_state(state: AppState, target_name: str = "") -> dict[str, Any]:
    applied: dict[str, str] | None = None
    requested = str(target_name or "").strip()
    if requested:
        result, error = await apply_route_target_for_state(state, requested, reason="smoke command")
        if result is None:
            return _smoke_failure_result(state, error or "Unknown use target")
        applied = result

    smoke = await smoke_current_route(state)
    if applied:
        smoke["applied"] = applied
    return smoke


def print_smoke_result(state: AppState, smoke: dict[str, Any]) -> None:
    applied = smoke.get("applied") if isinstance(smoke.get("applied"), dict) else None
    if applied:
        state.console.print(
            f"Smoking {applied['backend']} ({applied.get('resolved') or applied.get('target')}) "
            f"as {applied.get('model') or active_model_name(state)}",
        )
    label = smoke.get("node") or smoke.get("api_base") or smoke.get("backend")
    if smoke.get("ok"):
        matched = " · matched expected reply" if smoke.get("matched") else ""
        state.console.print(
            f"Smoke OK: {smoke.get('backend')} {label} [{smoke.get('model')}] "
            f"in {smoke.get('duration_ms')}ms{matched}",
        )
        if not smoke.get("matched"):
            state.console.print(f"Reply: {str(smoke.get('text') or '').strip()[:240]}")
    else:
        state.console.print(
            f"[red]Smoke failed:[/red] {smoke.get('backend')} {label} [{smoke.get('model')}] "
            f"{smoke.get('error') or 'empty response'}",
        )


async def handle_command(state: AppState, line: str) -> bool:
    """Dispatch a slash command. Returns False to exit the REPL."""
    parts = shlex.split(line)
    if not parts:
        return True
    command = parts[0].lower()

    if command in {"/exit", "/quit", "/bye"}:
        return False

    if command == "/help":
        state.console.print(build_repl_help_text(), markup=False)
        return True

    if command == "/oracle-tips":
        state.console.print(oracle_prompting_tips_text(), markup=False)
        return True

    if command == "/status":
        print_status(state)
        return True

    if command == "/backend":
        if len(parts) < 2:
            state.console.print(f"Backend: {state.backend_name} ({active_model_name(state)})")
            return True
        backend_name = parts[1].strip().lower()
        if backend_name not in VALID_BACKENDS:
            state.console.print("Usage: /backend <studio|llamacpp>")
            return True
        if backend_name == state.backend_name:
            state.console.print(f"Backend already set to {state.backend_name}")
            return True
        old_backend = state.backend_name
        set_backend(state, backend_name)
        if state.session:
            state.session.append_backend_switch(old_backend, backend_name)
        _persist_state(state)
        state.console.print(f"Backend set to {state.backend_name} ({active_model_name(state)})")
        return True

    if command == "/backends":
        state.console.print(
            f"Backends: {'*' if state.backend_name == 'studio' else ' '} studio ({state.studio_api_base}, node={state.studio_node or '-'}) ; "
            f"{'*' if state.backend_name == 'llamacpp' else ' '} llamacpp ({state.llamacpp_api_base}, {state.llamacpp_model}, node={state.llamacpp_node or '-'})"
        )
        return True

    if command == "/use":
        if len(parts) < 2:
            print_route_targets(state, title="route targets")
            return True
        result, error = await apply_route_target_for_state(state, parts[1], reason="user command")
        if result is None:
            state.console.print(error or "Unknown use target")
            return True
        state.console.print(
            f"Using {result['backend']} ({result.get('resolved') or result.get('target')}) as {result.get('model') or active_model_name(state)}",
        )
        return True

    if command == "/studio-nodes":
        if not state.studio_nodes:
            state.console.print("No studio nodes configured in the registry.")
            return True
        state.console.print("studio nodes:")
        for name, node in sorted(state.studio_nodes.items()):
            marker = "*" if name == state.studio_node else " "
            desc = f" · {node.description}" if node.description else ""
            state.console.print(f"{marker} {name:<18} {node.api_base}{desc}")
        return True

    if command == "/studio-node":
        if len(parts) < 2:
            label = state.studio_node or "(custom)"
            state.console.print(f"studio node: {label} ({state.studio_api_base})")
            return True
        node, error = select_studio_node(state, parts[1])
        if node is None:
            state.console.print(error or "Unknown studio node")
            return True
        _persist_state(
            state,
            {
                "studio_node": state.studio_node,
                "studio_api_base": state.studio_api_base,
            },
        )
        state.console.print(f"studio node set to {state.studio_node} ({state.studio_api_base})")
        return True

    if command == "/llamacpp-nodes":
        if not state.llamacpp_nodes:
            state.console.print("No llama.cpp nodes configured in the registry.")
            return True
        state.console.print("llama.cpp nodes:")
        for name, node in sorted(state.llamacpp_nodes.items()):
            marker = "*" if name == state.llamacpp_node else " "
            desc = f" · {node.description}" if node.description else ""
            state.console.print(f"{marker} {name:<18} {node.api_base} [{node.model}]{desc}")
        return True

    if command == "/llamacpp-node":
        if len(parts) < 2:
            label = state.llamacpp_node or "(custom)"
            state.console.print(f"llama.cpp node: {label} ({state.llamacpp_api_base}, {state.llamacpp_model})")
            return True
        node, error = select_llamacpp_node(state, parts[1])
        if node is None:
            state.console.print(error or "Unknown llama.cpp node")
            return True
        _persist_state(
            state,
            {
                "llamacpp_node": state.llamacpp_node,
                "llamacpp_api_base": state.llamacpp_api_base,
                "llamacpp_model": state.llamacpp_model,
            },
        )
        state.console.print(f"llama.cpp node set to {state.llamacpp_node} ({state.llamacpp_api_base}, {state.llamacpp_model})")
        return True

    if command == "/lsp-context":
        if len(parts) < 2:
            label = lsp_context_status_label(state.lsp_context_mode, state.models.get(state.active_model))
            state.console.print(f"LSP context: {state.lsp_context_mode} ({label})")
            return True
        raw_mode = parts[1].strip().lower()
        if raw_mode not in LSP_CONTEXT_MODES:
            state.console.print("Usage: /lsp-context <auto|off|minimal|balanced|rich>")
            return True
        state.lsp_context_mode = normalize_lsp_context_mode(raw_mode)
        await _refresh_focus_context(state)
        _persist_state(
            state,
            {
                "lsp_context_mode": state.lsp_context_mode,
                "focus_path": str(state.focus_path) if state.focus_path else "",
            },
        )
        label = lsp_context_status_label(state.lsp_context_mode, state.models.get(state.active_model))
        state.console.print(f"LSP context set to {state.lsp_context_mode} ({label})")
        return True

    if command == "/backend-status":
        backend = get_backend(state)
        status = await backend.check_connection()
        details_method = getattr(backend, "list_loaded_model_details", None)
        if callable(details_method):
            loaded = await details_method()  # type: ignore[misc]
        elif hasattr(backend, "list_loaded_models"):
            names = await backend.list_loaded_models()  # type: ignore[misc]
            loaded = [{"identifier": name, "model_key": name, "display_name": name} for name in names]
        else:
            loaded = []
        state.console.print(f"Backend: {status.name}")
        state.console.print(f"Connected: {status.connected}")
        if status.detail:
            state.console.print(f"Detail: {status.detail}")
        state.console.print(
            f"Loaded: {len(loaded)} · total {_format_memory_bytes(total_loaded_model_bytes(loaded))}",
        )
        render_loaded_model_table(state, loaded)
        return True

    if command in {"/smoke", "/doctor"}:
        if len(parts) > 2:
            state.console.print("Usage: /smoke [target]")
            return True
        smoke = await run_smoke_probe_for_state(state, parts[1] if len(parts) == 2 else "")
        print_smoke_result(state, smoke)
        return True

    if command == "/models":
        subcommand = parts[1].strip().lower() if len(parts) >= 2 else ""
        if subcommand in {"", "list"}:
            render_model_table(state)
            return True
        if subcommand == "catalog":
            include_advanced, error = route_list_include_advanced(parts[2:])
            if error:
                state.console.print("Usage: /models catalog [advanced|--all]", markup=False)
                return True
            title = "Advanced Model Catalog" if include_advanced else "Model Catalog"
            render_model_table(state, model_catalog_infos(state, include_advanced=include_advanced), title=title)
            return True
        if subcommand == "loaded":
            await list_loaded_api(state)
            return True
        if subcommand in {"routes", "route"}:
            include_advanced, error = route_list_include_advanced(parts[2:])
            if error:
                state.console.print("Usage: /models routes [advanced|--all]", markup=False)
                return True
            print_route_targets(state, include_advanced=include_advanced)
            return True
        state.console.print("Usage: /models [list|catalog [advanced|--all]|loaded|routes [advanced|--all]]", markup=False)
        return True

    if command == "/loaded":
        await list_loaded_api(state)
        return True

    if command == "/servers":
        if state.bridge:
            state.console.print("Tool servers: " + ", ".join(state.bridge.server_names))
            state.console.print("Tool count: " + str(state.bridge.tool_count))
        elif state.bridge_errors:
            state.console.print("Tool warnings: " + "; ".join(state.bridge_errors))
        else:
            state.console.print("No tool servers configured.")
        return True

    if command == "/modes":
        state.console.print(current_mode_help())
        return True

    if command == "/model":
        if state.backend_name != "studio":
            state.console.print(
                f"llama.cpp is pinned to {state.llamacpp_model}. Use /backend studio to switch LM Studio models."
            )
            return True
        if len(parts) < 2:
            state.console.print("Usage: /model <name>")
            return True
        old_model = state.active_model
        resolved_model, alias = resolve_existing_model_name(parts[1], state.models)
        ensure_model_available(state.models.get(resolved_model))
        state.active_model = resolved_model
        await _refresh_focus_context(state)
        state.console.print(f"Active model set to {state.active_model}")
        if alias:
            state.console.print(f"[yellow]Legacy alias '{alias}' now resolves to '{state.active_model}'.[/yellow]")
        if state.session and old_model != state.active_model:
            state.session.append_model_switch(old_model, state.active_model)
        _persist_state(state, model_name=state.active_model)
        return True

    if command == "/specialist":
        if state.backend_name != "studio":
            state.console.print(
                f"llama.cpp is pinned to {state.llamacpp_model}. Use /backend studio to switch LM Studio models."
            )
            return True
        requested_specialist = parts[1].strip().lower() if len(parts) >= 2 else ""
        try:
            next_model, alias = resolve_existing_model_name(requested_specialist, state.models)
        except RuntimeError:
            state.console.print(f"Usage: /specialist <{'|'.join(SPECIALIST_NAMES)}>")
            return True
        if next_model not in SPECIALIST_NAMES:
            state.console.print(f"Usage: /specialist <{'|'.join(SPECIALIST_NAMES)}>")
            return True
        old_model = state.active_model
        ensure_model_available(state.models.get(next_model))
        state.active_model = next_model
        state.mode = "manual"
        await _refresh_focus_context(state)
        state.console.print(f"Specialist set to {state.active_model} (mode: manual)")
        if alias:
            state.console.print(f"[yellow]Specialist alias '{alias}' now resolves to '{state.active_model}'.[/yellow]")
        if state.session and old_model != state.active_model:
            state.session.append_model_switch(old_model, state.active_model)
        _persist_state(state, {"mode": state.mode}, model_name=state.active_model)
        return True

    if command == "/mode":
        if len(parts) < 2:
            state.console.print(f"Usage: /mode {mode_usage_text()}")
            return True
        mode, alias = normalize_mode(parts[1])
        if mode not in VALID_MODES:
            state.console.print(f"Usage: /mode {mode_usage_text()}")
            return True
        state.mode = mode
        _persist_state(state, {"mode": state.mode})
        state.console.print(f"Routing mode set to {state.mode}")
        if alias:
            state.console.print(f"[yellow]Legacy mode '{alias}' now resolves to '{state.mode}'.[/yellow]")
        return True

    if command == "/orchestrator":
        if len(parts) < 2:
            resolved = state.orchestrator_model or default_orchestrator_model(state.models) or ""
            auto_selected = not state.orchestrator_model
            state.console.print(f"Orchestrator: {state.orchestrator_model or '(auto)'}")
            state.console.print(f"Resolved planner: {resolved or '(none)'}")
            state.console.print(f"Auto-selected: {auto_selected}")
            return True
        choice = parts[1].strip()
        if choice in {"auto", "-", ""}:
            state.orchestrator_model = ""
        else:
            try:
                resolved_choice, alias = resolve_existing_model_name(choice, state.models)
            except RuntimeError:
                state.console.print(f"[red]Unknown model: {choice}[/red]")
                return True
            cfg = state.models[resolved_choice]
            if cfg.is_cloud and not cfg.resolve_api_key():
                state.console.print(f"[red]Cloud model '{choice}' has no API key configured.[/red]")
                return True
            state.orchestrator_model = resolved_choice
            if alias:
                state.console.print(f"[yellow]Legacy alias '{alias}' now resolves to '{state.orchestrator_model}'.[/yellow]")
        _persist_state(state, {"orchestrator_model": state.orchestrator_model})
        resolved = state.orchestrator_model or default_orchestrator_model(state.models) or ""
        state.console.print(f"Orchestrator planner: {state.orchestrator_model or '(auto)'}")
        state.console.print(f"Resolved planner: {resolved or '(none)'}")
        return True

    if command == "/route":
        subcommand = parts[1].strip().lower() if len(parts) >= 2 else ""
        if len(parts) < 2 or subcommand in {"list", "ls"}:
            include_advanced, error = route_list_include_advanced(parts[2:])
            if error:
                state.console.print("Usage: /route list [advanced|--all]", markup=False)
                return True
            print_route_targets(state, include_advanced=include_advanced)
            return True
        if subcommand in {"current", "status"}:
            state.console.print(
                f"Current route: backend={state.backend_name}, model={active_model_name(state)}, "
                f"studio_node={state.studio_node or '-'}, llamacpp_node={state.llamacpp_node or '-'}",
            )
            return True
        if subcommand == "preview":
            if len(parts) < 3:
                state.console.print("Usage: /route preview <prompt>")
                return True
            targets = preview_targets(state, " ".join(parts[2:]))
            ensure_targets_available(targets)
            state.console.print(" -> ".join(target.name for target in targets))
            return True
        if subcommand in {"smoke", "doctor", "health"}:
            if len(parts) > 3:
                state.console.print(f"Usage: /route {subcommand} [target]")
                return True
            smoke = await run_smoke_probe_for_state(state, parts[2] if len(parts) == 3 else "")
            print_smoke_result(state, smoke)
            return True
        result, error = await apply_route_target_for_state(state, parts[1], reason="route command")
        if result is None:
            state.console.print(error or "Unknown route target")
            return True
        state.console.print(
            f"Route set to {result.get('route') or result.get('target')} via {result['backend']} "
            f"({result.get('resolved') or result.get('target')}) as {result.get('model') or active_model_name(state)}",
        )
        return True

    if command == "/broadcast":
        if len(parts) < 2:
            state.console.print("Usage: /broadcast <alias1,alias2,...>")
            return True
        state.broadcast_models = [v.strip() for v in parts[1].split(",") if v.strip()]
        _persist_state(state, {"broadcast_models": state.broadcast_models})
        state.console.print(f"Broadcast models: {', '.join(state.broadcast_models)}")
        return True

    if command == "/load":
        if state.backend_name != "studio":
            state.console.print("/load is only available on the studio backend.")
            return True
        target_name = parts[1] if len(parts) >= 2 else state.active_model
        if len(parts) >= 2:
            target_name, _alias = resolve_existing_model_name(target_name, state.models)
        else:
            target_name = str(target_name)
            if target_name not in state.models:
                state.console.print(f"[red]Unknown model: {target_name}[/red]")
                return True
            _alias = None
        target = state.models[target_name]
        if target.is_cloud:
            state.console.print("/load only applies to LM Studio models.")
            return True
        if _alias:
            state.console.print(f"[yellow]Legacy alias '{_alias}' now resolves to '{target_name}'.[/yellow]")
        request_name = get_backend(state).resolve_request_model(target, auto_load=True, manual_load=True)
        state.console.print(f"Loaded {target.name} as {request_name}")
        await list_loaded_api(state)
        return True

    if command == "/unload":
        if state.backend_name != "studio":
            state.console.print("/unload is only available on the studio backend.")
            return True
        target_name = parts[1] if len(parts) >= 2 else state.active_model
        unload_all = target_name.strip().lower() == "all"
        _alias = None
        if not unload_all:
            try:
                target_name, _alias = resolve_existing_model_name(target_name, state.models)
            except RuntimeError:
                target_name = target_name.strip()
        if _alias:
            state.console.print(f"[yellow]Legacy alias '{_alias}' now resolves to '{target_name}'.[/yellow]")
        try:
            result = await get_backend(state).unload_model(target_name, all_models=unload_all)
        except RuntimeError as exc:
            state.console.print(f"[red]{exc}[/red]")
            return True
        unloaded = [str(item) for item in result.get("unloaded", []) if item]
        if unload_all:
            state.console.print(f"Unloaded all LM Studio models ({len(unloaded)}).")
        else:
            state.console.print(f"Unloaded {', '.join(unloaded) if unloaded else target_name}.")
        await list_loaded_api(state)
        return True

    if command == "/workspace":
        if len(parts) < 2:
            state.console.print("Usage: /workspace <path>")
            return True
        state.workspace = Path(parts[1]).expanduser().resolve()
        _persist_state(state, {"workspace": str(state.workspace)})
        await refresh_tool_bridge(state)
        if state.shell is not None and state.shell.active:
            try:
                await state.shell.chdir(state.workspace)
            except Exception:
                pass
        state.console.print(f"Workspace set to {state.workspace}")
        return True

    if command == "/rom":
        if len(parts) < 2:
            state.console.print("Usage: /rom <path|none>")
            return True
        if parts[1].lower() == "none":
            state.rom_path = None
        else:
            state.rom_path = Path(parts[1]).expanduser().resolve()
        _persist_state(state, {"rom_path": str(state.rom_path) if state.rom_path else ""})
        await refresh_tool_bridge(state)
        state.console.print(f"ROM set to {state.rom_path or '(none)'}")
        return True

    if command == "/focus":
        if len(parts) < 2:
            if state.focus_context:
                lines = state.focus_context.count("\n") + 1
                chars = len(state.focus_context)
                state.console.print(f"[dim]Focus active ({lines} lines, {chars} chars). Use /focus clear to remove.[/dim]")
            else:
                state.console.print(
                    "Usage: /focus <path|clear>\n"
                    "  /focus Core/sprites.asm    Load a file relative to workspace\n"
                    "  /focus ~/path/to/file.asm  Load an absolute path\n"
                    "  /focus clear               Clear focus context"
                )
            return True
        arg = parts[1]
        if arg.lower() == "clear":
            _clear_focus_context(state)
            _persist_state(state, {"focus_path": ""})
            state.console.print("Focus context cleared.")
            return True
        try:
            focus_path, content = await load_enriched_focus_file(
                state.workspace,
                arg,
                bridge=state.bridge,
                model=state.models.get(state.active_model),
                lsp_context_mode=state.lsp_context_mode,
            )
        except FileNotFoundError:
            state.console.print(f"[red]File not found: {arg}[/red]")
            return True
        except Exception as e:
            state.console.print(f"[red]Error reading {arg}: {e}[/red]")
            return True
        lines, _chars = _set_focus_context(state, focus_path, content)
        _persist_state(state, {"focus_path": str(focus_path)})
        state.console.print(f"Loaded {focus_path.name} ({lines} lines) into focus context.")
        return True

    if command == "/tools":
        if len(parts) < 2 or parts[1].lower() not in {"on", "off"}:
            state.console.print("Usage: /tools <on|off>")
            return True
        state.tools_enabled = parts[1].lower() == "on"
        _persist_state(state, {"tools_enabled": state.tools_enabled})
        await refresh_tool_bridge(state)
        state.console.print(f"Tools enabled: {state.tools_enabled}")
        return True

    if command == "/tools-write":
        if len(parts) < 2 or parts[1].lower() not in {"on", "off"}:
            state.console.print("Usage: /tools-write <on|off>")
            return True
        state.tools_write = parts[1].lower() == "on"
        _persist_state(state, {"tools_write": state.tools_write})
        state.console.print(f"Tool write access: {state.tools_write}")
        return True

    if command == "/verify-hooks":
        if len(parts) < 2 or parts[1].lower() not in {"on", "off"}:
            state.console.print("Usage: /verify-hooks <on|off>")
            return True
        state.verify_hooks = parts[1].lower() == "on"
        _persist_state(state, {"verify_hooks": state.verify_hooks})
        state.console.print(f"Verification hooks: {state.verify_hooks}")
        return True

    if command == "/permissions":
        if len(parts) >= 2 and parts[1].lower() == "clear":
            state.permission_rules.clear()
            _persist_state(state, {"permission_rules": {}})
            state.console.print("Permission rules cleared.")
            return True
        allow = sorted(key for key, value in state.permission_rules.items() if value)
        deny = sorted(key for key, value in state.permission_rules.items() if not value)
        if not allow and not deny:
            state.console.print("No saved permission rules.")
            return True
        state.console.print("Allow: " + (", ".join(allow) if allow else "(none)"))
        state.console.print("Deny: " + (", ".join(deny) if deny else "(none)"))
        return True

    if command == "/shell":
        if len(parts) < 2:
            entries = len(state.shell.scrollback) if state.shell else 0
            cwd = state.shell.cwd if state.shell else state.workspace
            state.console.print(f"Shell active: {bool(state.shell and state.shell.active)}")
            state.console.print(f"Shell cwd: {cwd}")
            state.console.print(f"Shell history entries: {entries}")
            return True
        command_text = line.split(" ", 1)[1].strip()
        if not command_text:
            state.console.print("Usage: /shell <command>")
            return True
        shell = await ensure_shell(state)
        try:
            shell_result = await shell.run(command_text)
        except Exception as exc:
            state.console.print(f"[red]Shell command failed:[/red] {exc}")
            return True
        state.console.print(
            f"[dim]{shell_result.cwd}[/dim] "
            f"[{'green' if shell_result.exit_code == 0 else 'red'}]{shell_result.exit_code}[/] "
            f"({shell_result.duration_ms}ms)",
        )
        if shell_result.output.strip():
            state.console.print(shell_result.output)
        return True

    if command == "/shell-reset":
        if state.shell is not None:
            await state.shell.close()
            state.shell = None
        state.console.print("Shell reset.")
        return True

    if command == "/shell-log":
        limit = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else 10
        entries = state.shell.scrollback[-limit:] if state.shell else []
        if not entries:
            state.console.print("No shell history.")
            return True
        for entry in entries:
            state.console.print(
                f"$ {entry.command} "
                f"[dim]({entry.cwd}, exit {entry.exit_code}, {entry.duration_ms}ms)[/dim]",
            )
            if entry.output.strip():
                state.console.print(entry.output)
        return True

    if command == "/reset":
        if len(parts) >= 2 and parts[1].lower() == "all":
            for engine in state.engines.values():
                engine.reset()
            state.console.print("Cleared history for all models.")
            return True
        target_name = parts[1] if len(parts) >= 2 else active_model_name(state)
        engine = state.engines.get(engine_key(state.backend_name, target_name))
        if engine:
            engine.reset()
        state.console.print(f"Cleared history for {target_name}.")
        return True

    if command == "/stats":
        state.console.print(render_stats_table(
            messages=state.message_count,
            tool_calls=state.tool_call_count,
            prompt_tokens=state.prompt_tokens,
            completion_tokens=state.completion_tokens,
        ))
        return True

    if command == "/tool-timings":
        limit = 100
        if len(parts) >= 2:
            try:
                limit = max(1, int(parts[1]))
            except ValueError:
                state.console.print("Usage: /tool-timings [n]")
                return True
        if state.session is None or state.session.path is None:
            state.console.print("No active session — start a turn before checking timings.")
            return True
        records = load_tool_invocations(state.session.path, limit=limit)
        if not records:
            state.console.print("No tool invocations recorded yet.")
            return True
        from collections import defaultdict
        by_tool: dict[str, list[float]] = defaultdict(list)
        by_status: dict[str, int] = defaultdict(int)
        for rec in records:
            tool = str(rec.get("tool", "?"))
            dur = float(rec.get("duration_ms", 0.0) or 0.0)
            status = str(rec.get("status", ""))
            by_tool[tool].append(dur)
            by_status[status] += 1
        from rich.table import Table
        table = Table(title=f"Tool timings (last {len(records)} invocations)")
        table.add_column("Tool")
        table.add_column("Server")
        table.add_column("N", justify="right")
        table.add_column("p50 ms", justify="right")
        table.add_column("p95 ms", justify="right")
        table.add_column("max ms", justify="right")
        server_by_tool: dict[str, str] = {}
        for rec in records:
            server_by_tool.setdefault(str(rec.get("tool", "?")), str(rec.get("server", "")))
        for tool, durations in sorted(by_tool.items(), key=lambda kv: -sum(kv[1])):
            sd = sorted(durations)
            n = len(sd)
            p50 = sd[n // 2]
            p95 = sd[min(n - 1, int(n * 0.95))]
            mx = sd[-1]
            table.add_row(
                tool,
                server_by_tool.get(tool, ""),
                str(n),
                f"{p50:.0f}",
                f"{p95:.0f}",
                f"{mx:.0f}",
            )
        state.console.print(table)
        summary = ", ".join(f"{k}={v}" for k, v in sorted(by_status.items()))
        state.console.print(f"Status breakdown: {summary}")
        return True

    if command == "/save":
        if state.session and state.session.path:
            state.console.print(f"Session file: {state.session.path}")
        else:
            state.console.print("No active session.")
        return True

    if command == "/sessions":
        sessions = list_sessions(SESSION_DIR)
        if not sessions:
            state.console.print("No saved sessions.")
            return True
        from rich.table import Table
        table = Table(title="Sessions")
        table.add_column("Name")
        table.add_column("Backend")
        table.add_column("Model")
        table.add_column("Mode")
        table.add_column("Messages")
        table.add_column("Started")
        for s in sessions[:20]:
            table.add_row(s["name"], s.get("backend", "studio"), s["active_model"], s["mode"], str(s["messages"]), s["started"][:19])
        state.console.print(table)
        return True

    if command == "/resume":
        filtered_parts = [part for part in parts[1:] if part.strip()]
        strip_thinking = "--strip-thinking" in filtered_parts
        positional = [part for part in filtered_parts if part != "--strip-thinking"]
        if not positional:
            sessions = list_sessions(SESSION_DIR)
            if not sessions:
                state.console.print("No saved sessions.")
                return True

            from rich.table import Table
            table = Table(title="Sessions")
            table.add_column("Name", style="cyan")
            table.add_column("Backend")
            table.add_column("Model")
            table.add_column("Mode")
            table.add_column("Msgs", justify="right")
            table.add_column("Started")
            for s in sessions[:20]:
                table.add_row(
                    s["name"],
                    s.get("backend", "studio"),
                    s["active_model"],
                    s["mode"],
                    str(s["messages"]),
                    s["started"][:19],
                )
            state.console.print(table)
            return True
        name = positional[0]
        try:
            match = find_session(name, SESSION_DIR)
            loader = load_session_bundle_without_thinking if strip_thinking else load_session_bundle
            loaded = loader(Path(match["path"]))
        except Exception as exc:
            state.console.print(f"Session not found: {exc}")
            return True
        restore_warnings = _restore_runtime_state(state, loaded.meta)
        await refresh_tool_bridge(state)
        if state.shell is not None and state.shell.active:
            try:
                await state.shell.chdir(state.workspace)
            except Exception:
                pass
        for engine in state.engines.values():
            engine.reset()
        for model_name, msgs in loaded.model_messages.items():
            engine = get_engine(state, model_name)
            engine.messages = msgs
        if state.session:
            state.session.resume(Path(match["path"]), loaded.message_count)
        state.message_count = sum(1 for msg in loaded.transcript if msg.get("role") == "assistant")
        state._first_message_sent = loaded.message_count > 0
        state.console.print(
            f"Resumed session: {match['name']} "
            f"({len(loaded.model_messages)} model(s), {sum(len(m) for m in loaded.model_messages.values())} messages)"
        )
        for warning in restore_warnings:
            state.console.print(f"[yellow]{warning}[/yellow]")
        return True

    if command == "/compact":
        model_name = parts[1].strip() if len(parts) >= 2 else state.active_model
        model_cfg = state.models.get(model_name)
        if model_cfg is None:
            state.console.print(f"[red]Unknown model: {model_name}[/red]")
            return True
        engine = get_engine(state, model_name)
        if engine.compactor is None:
            state.console.print(
                f"[red]No compactor configured for '{model_name}'. "
                "Set context_budget in chat_registry.toml to enable.[/red]"
            )
            return True
        compaction_event = await compact_session_history(state, model_name, engine)
        if compaction_event is None:
            state.console.print("No messages to compact.")
            return True
        state.console.print(
            f"Compacted {compaction_event.replaced_count} messages "
            f"({compaction_event.tokens_before} -> {compaction_event.tokens_after} tokens)."
        )
        return True

    if command == "/export-training":
        if not state.session or not state.session.path:
            state.console.print("No active session to export.")
            return True
        filtered_parts = [part for part in parts[1:] if part.strip()]
        include_thinking = "--include-thinking" in filtered_parts
        positional = [part for part in filtered_parts if part != "--include-thinking"]
        out_path = Path(positional[0]).expanduser().resolve() if positional else state.session.path.with_suffix(".training.jsonl")
        model_filter = positional[1] if len(positional) > 1 else None
        count = export_training(
            state.session.path,
            out_path,
            model_filter,
            include_thinking=include_thinking,
        )
        state.console.print(f"Exported {count} training sample(s) to {out_path}")
        return True

    state.console.print(f"Unknown command: {command}")
    return True


# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------

async def run_repl(state: AppState) -> int:
    # Print welcome banner
    state.console.print(render_welcome_banner(
        version=__version__,
        model=active_model_name(state),
        mode=f"{state.mode} [{state.backend_name}]",
        servers=state.bridge.server_names if state.bridge else [],
        tool_count=state.bridge.tool_count if state.bridge else 0,
        workspace=str(state.workspace),
    ))
    state.last_active_model = state.active_model
    state.last_active_at = datetime.now(timezone.utc).isoformat()

    _ensure_session_started(state)

    # Set up prompt input
    if HAS_PROMPT_TOOLKIT:
        assert PromptSession is not None and FileHistory is not None
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        prompt_session: Any = PromptSession(
            history=FileHistory(str(HISTORY_FILE)),
        )
    else:
        prompt_session = None

    async def get_input(label: str) -> str:
        if prompt_session is not None:
            toolbar = build_bottom_toolbar(
                model=active_model_name(state),
                mode=f"{state.backend_name}:{state.mode}",
                server_count=len(state.bridge.server_names) if state.bridge else 0,
                tool_count=state.bridge.tool_count if state.bridge else 0,
                msg_count=state.message_count,
            )
            return await prompt_session.prompt_async(
                label,
                bottom_toolbar=toolbar,
            )
        return input(label)

    try:
        while True:
            label = f"[{state.backend_name}:{state.mode}:{active_model_name(state)}]> "
            try:
                line = await get_input(label)
            except (EOFError, KeyboardInterrupt):
                state.console.print()
                return 0
            line = line.strip()
            if not line:
                continue
            if line.startswith("/"):
                try:
                    if not await handle_command(state, line):
                        return 0
                except Exception as exc:
                    state.console.print(f"[red]Command failed:[/red] {exc}")
                continue
            try:
                await send_prompt(state, line)
            except Exception as exc:
                state.console.print(f"[red]Request failed:[/red] {exc}\n")
    finally:
        if state.session:
            state.session.close()


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", default=str(REGISTRY_PATH), help="Path to chat_registry.toml")
    parser.add_argument("--mcp-config", default=str(MCP_CONFIG_PATH), help="Path to LM Studio mcp.json")
    parser.add_argument("--backend", default=os.environ.get("Z3CLI_BACKEND", "studio"), choices=sorted(VALID_BACKENDS))
    parser.add_argument("--host", default=os.environ.get("LMSTUDIO_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("LMSTUDIO_PORT", "1234")))
    parser.add_argument("--api-base", "--studio-api-base", dest="studio_api_base", default=os.environ.get("LMSTUDIO_BASE_URL", API_BASE))
    parser.add_argument("--studio-node", default=os.environ.get("Z3CLI_STUDIO_NODE", ""))
    parser.add_argument("--llamacpp-api-base", default=os.environ.get("LLAMACPP_BASE_URL", DEFAULT_LLAMACPP_API_BASE))
    parser.add_argument("--llamacpp-model", default=DEFAULT_LLAMACPP_MODEL)
    parser.add_argument("--llamacpp-node", default=os.environ.get("Z3CLI_LLAMACPP_NODE", ""))
    parser.add_argument("--workspace", default=str(DEFAULT_WORKSPACE))
    parser.add_argument("--rom", default=str(DEFAULT_ROM), help="Primary ROM path (use '' to disable)")
    parser.add_argument("--model", default=DEFAULT_ACTIVE_MODEL)
    parser.add_argument(
        "--mode",
        default="manual",
        help=f"Routing mode {mode_usage_text()}",
    )
    parser.add_argument("--broadcast-models", default=",".join(DEFAULT_BROADCAST_MODELS))
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--tools", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--lsp-context", choices=LSP_CONTEXT_MODES, default="auto")
    parser.add_argument("--auto-load", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--auto-start-server", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--list-models", action="store_true")
    parser.add_argument("--list-loaded", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument(
        "--smoke",
        nargs="?",
        const="",
        default=None,
        metavar="TARGET",
        help="Probe the active or named model route with a tiny completion",
    )
    parser.add_argument("--route-only", action="store_true")
    parser.add_argument("--prompt", default="")
    parser.add_argument("command_args", nargs="*", help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.model_explicit = "--model" in os.sys.argv[1:]
    normalized_mode, _alias = normalize_mode(args.mode)
    if normalized_mode not in VALID_MODES:
        parser.error(f"--mode must be one of {mode_usage_text()}")
    return args


def _cli_command_kind(args: argparse.Namespace) -> str:
    command_args = getattr(args, "command_args", []) or []
    if not command_args:
        return ""
    command = str(command_args[0]).strip().lower()
    return command if command in {"route", "models"} else ""


async def build_state(args: argparse.Namespace) -> AppState:
    console = Console()
    models, routers = load_registry(Path(args.registry).expanduser())
    studio_nodes = load_studio_nodes(Path(args.registry).expanduser())
    llamacpp_nodes = load_llamacpp_nodes(Path(args.registry).expanduser())
    workspace = Path(args.workspace).expanduser().resolve()
    studio_api_base = args.studio_api_base.rstrip("/")
    llamacpp_api_base = args.llamacpp_api_base.rstrip("/")
    is_smoke_run = getattr(args, "smoke", None) is not None
    is_control_command = bool(_cli_command_kind(args))
    if args.backend == "studio" and args.auto_start_server and not is_smoke_run and not is_control_command:
        ensure_server(args.host, args.port)

    bridge = None
    bridge_errors: list[str] = []
    should_connect_tools = args.tools and not (
        args.list_models or args.list_loaded or args.status or args.route_only or is_smoke_run or is_control_command
    )
    if should_connect_tools:
        rom_arg = getattr(args, "rom", None)
        rom_path = Path(rom_arg).expanduser().resolve() if rom_arg else None
        bridge, bridge_errors = await connect_tool_bridge(
            workspace,
            Path(args.mcp_config).expanduser(),
            rom_path=rom_path,
        )

    active_model, startup_warning = choose_startup_model(
        args.model,
        models,
        explicit=bool(getattr(args, "model_explicit", False)),
        auto_load=args.auto_load,
    )

    selected_studio_node = ""
    if args.studio_node:
        node = studio_nodes.get(str(args.studio_node).strip().lower())
        if node is not None:
            studio_api_base = node.api_base
            selected_studio_node = node.name

    selected_llamacpp_node = ""
    if args.llamacpp_node:
        node = llamacpp_nodes.get(str(args.llamacpp_node).strip().lower())
        if node is not None:
            llamacpp_api_base = node.api_base
            args.llamacpp_model = node.model
            selected_llamacpp_node = node.name

    state = AppState(
        console=console,
        host=args.host,
        port=args.port,
        api_base=studio_api_base if args.backend == "studio" else llamacpp_api_base,
        backend_name=args.backend,
        studio_api_base=studio_api_base,
        studio_nodes=studio_nodes,
        studio_node=selected_studio_node,
        llamacpp_api_base=llamacpp_api_base,
        llamacpp_model=args.llamacpp_model,
        llamacpp_nodes=llamacpp_nodes,
        llamacpp_node=selected_llamacpp_node,
        registry_path=Path(args.registry).expanduser(),
        mcp_path=Path(args.mcp_config).expanduser(),
        models=models,
        routers=routers,
        active_model=active_model,
        mode=normalize_mode(args.mode)[0],
        auto_load=args.auto_load,
        auto_start_server=args.auto_start_server,
        workspace=workspace,
        rom_path=None if not args.rom else Path(args.rom).expanduser().resolve(),
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        broadcast_models=[v.strip() for v in args.broadcast_models.split(",") if v.strip()],
        tools_enabled=args.tools,
        lsp_context_mode=args.lsp_context,
        bridge=bridge,
        bridge_errors=bridge_errors,
        startup_warnings=[startup_warning] if startup_warning else [],
    )
    if args.studio_node and not selected_studio_node:
        state.startup_warnings.append(f"Unknown studio node: {args.studio_node}")
    elif selected_studio_node:
        _node, error = select_studio_node(state, selected_studio_node)
        if error:
            state.startup_warnings.append(error)
    if args.llamacpp_node and not selected_llamacpp_node:
        state.startup_warnings.append(f"Unknown llama.cpp node: {args.llamacpp_node}")
    elif selected_llamacpp_node:
        _node, error = select_llamacpp_node(state, selected_llamacpp_node)
        if error:
            state.startup_warnings.append(error)
    return state


async def run_control_cli_command(state: AppState, command_args: list[str]) -> int | None:
    if not command_args:
        return None
    command = str(command_args[0]).strip().lower()
    args = [str(arg) for arg in command_args[1:]]

    if command == "route":
        subcommand = args[0].strip().lower() if args else "list"
        if subcommand in {"list", "ls"}:
            include_advanced, error = route_list_include_advanced(args[1:])
            if error:
                state.console.print("Usage: z3cli route list [advanced|--all]", markup=False)
                return 2
            print_route_targets(state, include_advanced=include_advanced)
            return 0
        if subcommand in {"current", "status"}:
            state.console.print(
                f"Current route: backend={state.backend_name}, model={active_model_name(state)}, "
                f"studio_node={state.studio_node or '-'}, llamacpp_node={state.llamacpp_node or '-'}",
            )
            return 0
        if subcommand == "preview":
            if len(args) < 2:
                state.console.print("Usage: z3cli route preview <prompt>")
                return 2
            targets = preview_targets(state, " ".join(args[1:]))
            ensure_targets_available(targets)
            state.console.print(" -> ".join(target.name for target in targets))
            return 0
        if subcommand in {"smoke", "doctor", "health"}:
            if len(args) > 2:
                state.console.print(f"Usage: z3cli route {subcommand} [target]")
                return 2
            smoke = await run_smoke_probe_for_state(state, args[1] if len(args) == 2 else "")
            print_smoke_result(state, smoke)
            return 0 if smoke.get("ok") else 1
        if len(args) != 1:
            state.console.print(
                "Usage: z3cli route [list [advanced|--all]|current|<target>|smoke [target]|health [target]|preview <prompt>]",
                markup=False,
            )
            return 2
        result, error = await apply_route_target_for_state(state, args[0], reason="route cli command")
        if result is None:
            state.console.print(error or "Unknown route target")
            return 1
        state.console.print(
            f"Route set to {result.get('route') or result.get('target')} via {result['backend']} "
            f"({result.get('resolved') or result.get('target')}) as {result.get('model') or active_model_name(state)}",
        )
        return 0

    if command == "models":
        subcommand = args[0].strip().lower() if args else "list"
        if subcommand in {"list", ""}:
            render_model_table(state)
            return 0
        if subcommand == "catalog":
            include_advanced, error = route_list_include_advanced(args[1:])
            if error:
                state.console.print("Usage: z3cli models catalog [advanced|--all]", markup=False)
                return 2
            title = "Advanced Model Catalog" if include_advanced else "Model Catalog"
            render_model_table(state, model_catalog_infos(state, include_advanced=include_advanced), title=title)
            return 0
        if subcommand == "loaded":
            await list_loaded_api(state)
            return 0
        if subcommand in {"routes", "route"}:
            include_advanced, error = route_list_include_advanced(args[1:])
            if error:
                state.console.print("Usage: z3cli models routes [advanced|--all]", markup=False)
                return 2
            print_route_targets(state, include_advanced=include_advanced)
            return 0
        state.console.print("Usage: z3cli models [list|catalog [advanced|--all]|loaded|routes [advanced|--all]]", markup=False)
        return 2

    return None


async def main() -> int:
    args = parse_args()
    state = await build_state(args)
    try:
        command_result = await run_control_cli_command(state, list(getattr(args, "command_args", []) or []))
        if command_result is not None:
            return command_result
        if args.list_models:
            render_model_table(state)
            return 0
        if args.list_loaded:
            await list_loaded_api(state)
            return 0
        if args.status:
            print_status(state)
            return 0
        if args.smoke is not None:
            smoke = await run_smoke_probe_for_state(state, args.smoke)
            print_smoke_result(state, smoke)
            return 0 if smoke.get("ok") else 1
        if args.prompt:
            if args.route_only:
                targets = preview_targets(state, args.prompt)
                ensure_targets_available(targets)
                state.console.print(" -> ".join(target.name for target in targets))
                return 0
            await send_prompt(state, args.prompt)
            return 0
        return await run_repl(state)
    finally:
        if state.session:
            state.session.close()
        for engine in state.engines.values():
            await engine.close()
        if state.shell is not None:
            await state.shell.close()
        if state.bridge:
            await state.bridge.close()


def run() -> int:
    return asyncio.run(main())
