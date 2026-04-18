"""JSON-RPC stdio server mode for z3cli.

Reads JSON-RPC requests from stdin, streams events as JSON-RPC
notifications to stdout. This is the backend for the Ink frontend.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import re
import select
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from z3cli import __version__
from z3cli.app.backends import DEFAULT_LLAMACPP_API_BASE, LMStudioBackend, LlamaCppBackend
from z3cli.app.ipc_schema import (
    AttachmentMeta,
    ConstructRef,
    LoadedModelRuntimeInfo,
    MessageRole,
    NotificationParams,
    ReadyModelInfo,
    ReadyParams,
    context_compacted_params,
    done_params,
    error_params,
    make_notification,
    make_response,
    message_params,
    subagent_done_params,
    subagent_error_params,
    subagent_start_params,
    subagent_text_params,
    subagent_thinking_params,
    subagent_tool_call_params,
    subagent_tool_result_params,
    text_params,
    thinking_params,
    tool_call_params,
    tool_permission_request_params,
    tool_result_params,
    tool_review_request_params,
)
from z3cli.core.config import (
    API_BASE, MCP_CONFIG_PATH, REGISTRY_PATH, ModelConfig, Z3UI_MODEL_ORDER,
    is_z3ui_model, is_z3ui_model_entry, z3ui_model_sort_key,
    load_registry, list_zelda_models, rollout_warnings,
)
from z3cli.core.engine import (
    ChatEngine, CompactionEvent, DoneEvent, ErrorEvent, TextEvent, ThinkingEvent,
    ToolCallEvent, ToolResultEvent,
)
from z3cli.core.compaction import (
    CompactionPolicy, ConversationCompactor, ProviderSummarizer,
)
from z3cli.core.provider import Provider, create_provider
from z3cli.core.subagent import (
    SubagentConfig, SubagentContext, SubagentDoneEvent, SubagentErrorEvent,
    SubagentEvent, SubagentRunner, SubagentStartEvent, SubagentTextEvent,
    SubagentThinkingEvent, SubagentToolCallEvent, SubagentToolResultEvent,
    format_subagent_summary, get_current_subagent,
)
from z3cli.protocol.lmstudio import ensure_server, total_loaded_model_bytes
from z3cli.app.runtime import (
    DEFAULT_ACTIVE_MODEL, DEFAULT_BROADCAST_MODELS, DEFAULT_LLAMACPP_MODEL, DEFAULT_ROM,
    DEFAULT_WORKSPACE, LSP_CONTEXT_MODES, ORCHESTRATOR_MODE, SPECIALIST_NAMES, VALID_BACKENDS, VALID_MODES,
    add_attachment_context_packs,
    add_construct_context_packs,
    build_harness_prompt, build_local_identity_prompt, build_orchestrator_prompt, build_tool_bias_prompt, build_tool_use_prompt, current_model_name,
    blocked_model_reason,
    choose_startup_model,
    default_orchestrator_model, engine_key, enrich_prompt_with_attachments, enrich_prompt_with_construct_refs,
    ensure_model_available, ensure_targets_available,
    load_enriched_focus_file, lsp_context_status_label, merge_system_prompts, mode_usage_text, normalize_lsp_context_mode, normalize_mode,
    resolve_existing_model_name, resolve_message_attachments, resolve_message_construct_refs, resolve_oracle_profile_system_prompts,
    resolve_targets, resolve_targets_with_reason,
)
from z3cli.app.shared_runtime import (
    active_model_name,
    compact_session_history,
    clear_focus_context as _clear_focus_context,
    ensure_shell,
    get_backend,
    get_or_create_engine,
    permission_rule_key as _permission_rule_key,
    persist_state as _persist_state,
    refresh_focus_context as _refresh_focus_context,
    loaded_model_runtime_infos,
    resolve_focus_context as _resolve_focus_context,
    resolve_request_model_name,
    restore_runtime_state as _restore_runtime_state,
    set_backend,
    set_focus_context as _set_focus_context,
    state_permission_rules,
    visible_model_infos,
    z3ui_model_infos,
)
from z3cli.app.shell_session import PersistentShellSession
from z3cli.app.verify import run_verification_hooks, select_verification_commands
from z3cli.app.write_review import (
    ToolWriteContext, build_review_preview, detect_changes, prepare_write_context,
    restore_write_context,
)
from z3cli.core.session import (
    Session, export_training, find_session, list_sessions, load_session_bundle,
    load_session_bundle_without_thinking,
)
from z3cli.core.tool_bridge import CompositeBridge, ToolBridge
from z3cli.core.subagent_bridge import SubagentBridge
from z3cli.app.tooling import connect_tool_bridge, wrap_bridge_for_model

DEFAULT_PERMISSION_WAIT_TIMEOUT_S = float(os.environ.get("Z3CLI_TOOL_PERMISSION_TIMEOUT_S", "45"))
DEFAULT_REVIEW_WAIT_TIMEOUT_S = float(os.environ.get("Z3CLI_TOOL_REVIEW_TIMEOUT_S", "90"))
DEFAULT_MODEL_RETRY_MAX = int(os.environ.get("Z3CLI_MODEL_RETRY_MAX", "2"))
DEFAULT_MODEL_RETRY_BACKOFF_BASE_S = float(os.environ.get("Z3CLI_MODEL_RETRY_BACKOFF_BASE_S", "0.75"))
DEFAULT_TOOL_EXEC_TIMEOUT_S = float(os.environ.get("Z3CLI_TOOL_EXEC_TIMEOUT_S", "120"))
DEFAULT_MAX_INFLIGHT_MODEL_CALLS = int(os.environ.get("Z3CLI_MAX_INFLIGHT_MODEL_CALLS", "1"))
DEFAULT_MAX_INFLIGHT_TOOLS = int(os.environ.get("Z3CLI_MAX_INFLIGHT_TOOLS", "2"))
DEFAULT_EXEC_QUEUE_DEPTH = int(os.environ.get("Z3CLI_EXEC_QUEUE_DEPTH", "4"))
DEFAULT_REQUEST_METRIC_SAMPLE_LIMIT = int(os.environ.get("Z3CLI_REQUEST_METRIC_SAMPLE_LIMIT", "256"))
DEFAULT_REQUEST_TELEMETRY_STDERR = str(
    os.environ.get("Z3CLI_REQUEST_TELEMETRY_STDERR", "1"),
).strip().lower() not in {"0", "false", "off", "no"}
_COLLISION_WARNING_RE = re.compile(
    r"^tool collision: tool name '([^']+)' collided between '([^']+)' \(kept\) and '([^']+)' "
    r"\(renamed to '([^']+)'\)$",
)
_REASONING_PREFIX_RE = re.compile(
    r"^(the user\b|okay[, ]|alright[, ]|hmm[, ]|first[, ]|let me\b|i should\b|i need to\b|"
    r"wait[, ]|another thing\b|alternatively\b|since i can't\b|without knowing\b|"
    r"looking through\b|the primary workspace is\b|maybe\b|perhaps\b)",
    re.IGNORECASE,
)


def _allowed_z3ui_model_names(state: "ServeState") -> list[str]:
    return [
        model.name
        for model in sorted(
            (
                model
                for model in state.models.values()
                if is_z3ui_model_entry(model) and not blocked_model_reason(model)
            ),
            key=lambda item: z3ui_model_sort_key(item.name),
        )
    ]


def _z3ui_model_policy_error(state: "ServeState", model_name: str) -> str:
    allowed = _allowed_z3ui_model_names(state)
    if allowed:
        return f"Model '{model_name}' is not available in z3ui. Choose one of: {', '.join(allowed)}"
    fallback = ", ".join(Z3UI_MODEL_ORDER)
    return (
        f"Model '{model_name}' is not available in z3ui. "
        f"No supported z3ui models are currently unblocked. Preferred set: {fallback}"
    )


def _coerce_z3ui_active_model(state: "ServeState", requested_name: str) -> str | None:
    current_name = state.active_model
    current_model = state.models.get(state.active_model)
    if is_z3ui_model_entry(current_model) and not blocked_model_reason(current_model):
        return None
    allowed = _allowed_z3ui_model_names(state)
    if allowed:
        fallback_model = allowed[0]
        display_name = requested_name or current_name
        state.active_model = fallback_model
        if is_z3ui_model_entry(current_model):
            return (
                f"Model '{display_name}' is rollout-gated in z3ui. "
                f"Using '{fallback_model}' instead."
            )
        return (
            f"z3ui does not expose model '{display_name}'. "
            f"Using '{fallback_model}' instead."
        )
    return _z3ui_model_policy_error(state, requested_name or current_name)


def _percentile(values: list[int], percentile: int) -> int:
    if not values:
        return 0
    p = max(0, min(100, percentile))
    sorted_values = sorted(values)
    rank = math.ceil((p / 100) * len(sorted_values))
    idx = max(0, min(len(sorted_values) - 1, rank - 1))
    return int(sorted_values[idx])


def _write(data: object) -> None:
    """Write a JSON-RPC message to stdout."""
    payload = (json.dumps(data, ensure_ascii=False) + "\n").encode("utf-8")
    fd = sys.stdout.fileno()
    view = memoryview(payload)
    while view:
        try:
            written = os.write(fd, view)
        except BlockingIOError:
            select.select([], [fd], [])
            continue
        if written <= 0:
            raise BrokenPipeError("stdout closed while writing JSON-RPC message")
        view = view[written:]


def _notify(method: str, params: NotificationParams | None = None) -> None:
    _write(make_notification(method, params))


def _describe_permission_reason(
    write_context: ToolWriteContext | None,
    *,
    subagent: SubagentContext | None = None,
) -> str | None:
    """Derive a short human-readable reason for a pending permission prompt.

    Covers:
      - Write-tool context (files that would be modified).
      - Subagent attribution (which delegated agent requested the call).
    When both apply, the subagent prefix precedes the write-tool summary so
    the user sees the source before the effect. Returns ``None`` only when
    neither applies.
    """
    base: str | None = None
    if write_context is not None:
        paths = [snap.path.name for snap in write_context.files if snap.path.name]
        count = len(write_context.files)
        if count == 0:
            base = "write tool: will modify files in workspace"
        elif count == 1:
            base = f"write tool: will modify {paths[0]}"
        else:
            base = f"write tool: will modify {count} files ({paths[0]} +{count - 1} more)"

    if subagent is not None:
        prefix = f"subagent [{subagent.name}]"
        if base is None:
            return prefix
        return f"{prefix} · {base}"

    return base


def _compact_warning_list(warnings: list[str]) -> list[str]:
    grouped_collisions: dict[tuple[str, str], list[str]] = {}
    ordered: list[str] = []
    seen: set[str] = set()

    for warning in warnings:
        match = _COLLISION_WARNING_RE.match(warning)
        if match:
            tool_name, winner, loser, _renamed = match.groups()
            grouped_collisions.setdefault((winner, loser), []).append(tool_name)
            continue
        if warning not in seen:
            seen.add(warning)
            ordered.append(warning)

    for (winner, loser), tool_names in sorted(grouped_collisions.items()):
        unique_tools = sorted(set(tool_names))
        sample = ", ".join(unique_tools[:3])
        remainder = len(unique_tools) - min(len(unique_tools), 3)
        if remainder > 0:
            sample = f"{sample}; {remainder} more"
        ordered.append(
            f"{len(unique_tools)} tool collisions between '{winner}' and '{loser}'; "
            f"keeping '{winner}' names (e.g. {sample})",
        )

    return ordered


def _normalize_paragraph_key(text: str) -> str:
    return " ".join(text.split()).strip().lower()


def _is_hidden_reasoning_paragraph(text: str) -> bool:
    compact = " ".join(text.split()).strip()
    if not compact:
        return False
    lowered = compact.lower()
    if _REASONING_PREFIX_RE.match(compact):
        return True
    return (
        "the user " in lowered
        or "i should " in lowered
        or "i need to " in lowered
        or "let me " in lowered
    )


def _extract_tool_anchor(tool_name: str, result: str) -> str:
    for raw_line in result.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^#+\s*", "", line)
        if len(line) > 160:
            line = line[:157].rstrip() + "..."
        return line
    return tool_name


def _ensure_tool_evidence_anchor(content: str, tool_results: list[tuple[str, str]]) -> str:
    if not tool_results:
        return content
    tool_name, result = tool_results[-1]
    anchor = _extract_tool_anchor(tool_name, result)
    lowered = content.lower()
    if "evidence:" in lowered or f"`{tool_name}`" in content or anchor.lower() in lowered:
        return content
    prefix = f"Evidence: `{tool_name}` -> {anchor}"
    return f"{prefix}\n\n{content}" if content else prefix


def _sanitize_assistant_content(content: str, *, tool_results: list[tuple[str, str]] | None = None) -> str:
    tool_results = tool_results or []
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", content) if part.strip()]
    if not paragraphs:
        return content.strip()

    deduped: list[str] = []
    previous_key = ""
    for paragraph in paragraphs:
        key = _normalize_paragraph_key(paragraph)
        if key and key == previous_key:
            continue
        deduped.append(paragraph)
        previous_key = key

    while deduped and _is_hidden_reasoning_paragraph(deduped[0]):
        deduped.pop(0)

    cleaned = "\n\n".join(deduped).strip()
    if not cleaned:
        return cleaned
    if tool_results:
        cleaned = _ensure_tool_evidence_anchor(cleaned, tool_results)
    return cleaned


def _assistant_text_delta(
    raw_content: str,
    rendered_content: str,
    *,
    tool_results: list[tuple[str, str]] | None = None,
) -> tuple[str, str]:
    sanitized = _sanitize_assistant_content(raw_content, tool_results=tool_results)
    if not sanitized:
        return sanitized, ""
    if not rendered_content:
        return sanitized, sanitized
    if sanitized.startswith(rendered_content):
        return sanitized, sanitized[len(rendered_content):]
    if rendered_content.startswith(sanitized):
        return sanitized, ""
    return sanitized, ""


def _respond(req_id: int, result: object = None, error: str | None = None) -> None:
    _write(make_response(req_id, result=result, error=error))


def _orchestrator_routing_payload(state: ServeState) -> tuple[str, bool, list[dict[str, object]]]:
    targets, decisions = resolve_targets_with_reason(
        models=state.models,
        routers=state.routers,
        active_model=state.active_model,
        mode=ORCHESTRATOR_MODE,
        prompt="",
        broadcast_models=state.broadcast_models,
        backend_name=state.backend_name,
        llamacpp_model=state.llamacpp_model,
        temperature=0.2,
        max_tokens=1024,
        orchestrator_model=state.orchestrator_model,
    )

    resolved = targets[0].name if targets else state.active_model
    decision_reason = decisions[0].reason if decisions else ""
    auto_selected = decision_reason != "orchestrator-explicit"
    return resolved, auto_selected, [decision.to_dict() for decision in decisions]


def _emit_request_telemetry(
    state: "ServeState",
    *,
    request_id: str,
    end_status: str,
    queued_ms: int,
    model_ms: int,
    tool_ms: int,
    total_ms: int,
    routing: list[dict[str, object]] | None = None,
) -> None:
    """Emit one structured request lifecycle record for log ingestion."""
    if not state.request_telemetry_stderr:
        return
    payload = {
        "event": "request.lifecycle",
        "request_id": request_id,
        "status": end_status,
        "queued_ms": max(0, int(queued_ms)),
        "model_ms": max(0, int(model_ms)),
        "tool_ms": max(0, int(tool_ms)),
        "total_ms": max(0, int(total_ms)),
        "backend": state.backend_name,
        "mode": state.mode,
        "active_model": active_model_name(state),
        "inflight_model_calls": state.inflight_model_calls,
        "queued_model_calls": state.queued_model_calls,
        "routing": routing,
    }
    try:
        sys.stderr.write(json.dumps(payload, ensure_ascii=False) + "\n")
        sys.stderr.flush()
    except Exception:
        # Telemetry must not impact request handling.
        pass


def _record_subagent_event(state: "ServeState", event: SubagentEvent) -> None:
    """Persist a subagent lifecycle event into the session log."""
    if isinstance(event, SubagentStartEvent):
        state.session.append_subagent_event("start", {
            "id": event.id,
            "name": event.name,
            "model": event.model_name,
            "provider": event.provider,
            "depth": event.depth,
            "parent_id": event.parent_id,
        })
    elif isinstance(event, SubagentTextEvent):
        state.session.append_subagent_event("text", {"id": event.id, "delta": event.delta})
    elif isinstance(event, SubagentThinkingEvent):
        state.session.append_subagent_event("thinking", {"id": event.id, "delta": event.delta})
    elif isinstance(event, SubagentToolCallEvent):
        state.session.append_subagent_event("tool_call", {
            "id": event.id,
            "name": event.name,
            "server": event.server,
            "arguments": event.arguments,
            "call_id": event.call_id,
        })
    elif isinstance(event, SubagentToolResultEvent):
        state.session.append_subagent_event("tool_result", {
            "id": event.id,
            "name": event.name,
            "result": event.result,
            "call_id": event.call_id,
        })
    elif isinstance(event, SubagentDoneEvent):
        result = event.result
        state.session.append_subagent_event("done", {
            "id": event.id,
            "name": result.name,
            "model": result.model_name,
            "text": result.text,
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "tool_calls": result.tool_calls,
            "error": result.error,
            "cancelled": result.cancelled,
        })
    elif isinstance(event, SubagentErrorEvent):
        state.session.append_subagent_event("error", {
            "id": event.id,
            "message": event.message,
        })


async def _forward_subagent_event(state: "ServeState", event: SubagentEvent) -> None:
    """Translate a SubagentEvent into a JSON-RPC notification and session record."""
    _record_subagent_event(state, event)
    if isinstance(event, SubagentStartEvent):
        _notify("subagent/start", subagent_start_params(
            subagent_id=event.id,
            name=event.name,
            model=event.model_name,
            provider=event.provider,
            depth=event.depth,
            parent_id=event.parent_id or None,
        ))
    elif isinstance(event, SubagentTextEvent):
        _notify("subagent/text", subagent_text_params(event.id, event.delta))
    elif isinstance(event, SubagentThinkingEvent):
        _notify("subagent/thinking", subagent_thinking_params(event.id, event.delta))
    elif isinstance(event, SubagentToolCallEvent):
        _notify("subagent/tool_call", subagent_tool_call_params(
            subagent_id=event.id,
            name=event.name,
            server=event.server,
            arguments=event.arguments,
            call_id=event.call_id,
        ))
    elif isinstance(event, SubagentToolResultEvent):
        _notify("subagent/tool_result", subagent_tool_result_params(
            subagent_id=event.id,
            name=event.name,
            result=event.result,
            call_id=event.call_id,
        ))
    elif isinstance(event, SubagentDoneEvent):
        result = event.result
        _notify("subagent/done", subagent_done_params(
            subagent_id=event.id,
            name=result.name,
            model=result.model_name,
            text=result.text,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            tool_calls=result.tool_calls,
            error=result.error or None,
            cancelled=result.cancelled,
        ))
    elif isinstance(event, SubagentErrorEvent):
        _notify("subagent/error", subagent_error_params(event.id, event.message))

def _build_orchestrator_catalog(state: "ServeState") -> str:
    """Build the orchestrator system prompt using the current specialist registry."""
    specialists: list[dict] = []
    for name in sorted(state.models):
        model = state.models[name]
        # Only expose models the orchestrator can actually spawn
        if model.is_cloud and not model.resolve_api_key():
            continue
        specialists.append({
            "name": name,
            "provider": model.provider,
            "role": model.role,
            "description": model.description,
            "tool_profile": model.tool_profile,
        })
    return build_orchestrator_prompt(specialists)


class _ToolBudgetBridge:
    """Tool bridge wrapper that enforces global tool execution budgets."""

    def __init__(self, state: "ServeState", bridge: ToolBridge):
        self._state = state
        self._bridge = bridge

    def get_openai_tools(self) -> list[dict]:
        return self._bridge.get_openai_tools()

    async def call_tool(self, name: str, arguments: dict) -> str:
        server = self._bridge.get_tool_server(name)
        reserved, rejection = await self._state.reserve_tool_budget(server, name)
        if not reserved:
            return rejection
        entered = False
        try:
            await self._state.acquire_tool_budget()
            entered = True
            return await self._bridge.call_tool(name, arguments)
        finally:
            if entered:
                await self._state.release_tool_budget()
            else:
                await self._state.rollback_tool_budget()

    def get_tool_server(self, tool_name: str) -> str:
        return self._bridge.get_tool_server(tool_name)

    @property
    def tool_count(self) -> int:
        return self._bridge.tool_count

    @property
    def server_names(self) -> list[str]:
        return self._bridge.server_names

    @property
    def server_tool_counts(self) -> dict[str, int]:
        return self._bridge.server_tool_counts

    async def close(self) -> None:
        await self._bridge.close()
class ServeState:
    """Runtime state for the serve mode backend."""

    def __init__(self):
        self.host = "127.0.0.1"
        self.port = 1234
        self.api_base = API_BASE
        self.backend_name = "studio"
        self.studio_api_base = API_BASE
        self.llamacpp_api_base = DEFAULT_LLAMACPP_API_BASE
        self.llamacpp_model = DEFAULT_LLAMACPP_MODEL
        self.registry_path = REGISTRY_PATH
        self.mcp_path = MCP_CONFIG_PATH
        self.models, self.routers = {}, {}
        self.active_model = DEFAULT_ACTIVE_MODEL
        self.mode = "manual"
        self.workspace = DEFAULT_WORKSPACE
        self.rom_path: Path | None = DEFAULT_ROM
        self.auto_start_server = True
        self.tools_enabled = True
        self.auto_load = True
        self.tools_write = False
        self.verify_hooks = True
        # When True, compose the subagent bridge with the main tool
        # surface so models can call spawn_subagent / list_subagents.
        self.subagent_tools_enabled = True
        # Name of the model to use as the orchestrator planner, or ""
        # to auto-select the best available cloud model at dispatch time.
        self.orchestrator_model = ""
        self.broadcast_models = list(DEFAULT_BROADCAST_MODELS)
        self.focus_context: str = ""
        self.focus_path: Path | None = None
        self.lsp_context_mode = "auto"
        self.shell: PersistentShellSession | None = None
        self.bridge: ToolBridge | None = None
        self.bridge_errors: list[str] = []
        self.startup_warnings: list[str] = []
        self.engines: dict[str, ChatEngine] = {}
        self.turn_index = 0
        self.request_index = 0
        self.message_index = 0
        self.tool_call_count = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.cache_creation_tokens = 0
        self.cache_read_tokens = 0
        self.last_active_at = ""
        self.last_active_model = ""
        self.permission_rules: dict[str, bool] = {}
        self.session = Session()
        self.cancel_requested = False
        self.permission_wait_timeout_s = max(0.0, DEFAULT_PERMISSION_WAIT_TIMEOUT_S)
        self.review_wait_timeout_s = max(0.0, DEFAULT_REVIEW_WAIT_TIMEOUT_S)
        self.model_retry_max = max(0, DEFAULT_MODEL_RETRY_MAX)
        self.model_retry_backoff_base_s = max(0.0, DEFAULT_MODEL_RETRY_BACKOFF_BASE_S)
        self.tool_exec_timeout_s = max(0.0, DEFAULT_TOOL_EXEC_TIMEOUT_S)
        self.max_inflight_model_calls = max(1, DEFAULT_MAX_INFLIGHT_MODEL_CALLS)
        self.max_inflight_tools = max(1, DEFAULT_MAX_INFLIGHT_TOOLS)
        self.exec_queue_depth = max(0, DEFAULT_EXEC_QUEUE_DEPTH)
        self.cancel_count = 0
        self.backend_restart_count = 0
        self.tool_latency_ms_total = 0
        self.tool_latency_samples = 0
        self.review_wait_ms = 0
        self.permission_wait_ms = 0
        self.permission_timeout_count = 0
        self.review_timeout_count = 0
        self.model_retry_count = 0
        self.model_retry_backoff_ms = 0
        self.model_error_count = 0
        self.tool_timeout_count = 0
        self.model_backpressure_count = 0
        self.tool_backpressure_count = 0
        self.model_queue_highwater = 0
        self.tool_queue_highwater = 0
        self.model_inflight_highwater = 0
        self.tool_inflight_highwater = 0
        self.inflight_model_calls = 0
        self.queued_model_calls = 0
        self.inflight_tool_calls = 0
        self.queued_tool_calls = 0
        self.request_count = 0
        self.request_success_count = 0
        self.request_error_count = 0
        self.request_reject_count = 0
        self.request_cancel_count = 0
        self.model_alias_resolutions = 0
        self.model_lookup_failures = 0
        self.model_request_counts: dict[str, int] = {}
        self.span_count = 0
        self.last_request_id = ""
        self.last_span_id = ""
        self.last_tool_call_id = ""
        self.request_metric_sample_limit = max(16, DEFAULT_REQUEST_METRIC_SAMPLE_LIMIT)
        self.request_telemetry_stderr = DEFAULT_REQUEST_TELEMETRY_STDERR
        self.request_queued_ms_samples: list[int] = []
        self.request_model_ms_samples: list[int] = []
        self.request_tool_ms_samples: list[int] = []
        self.request_total_ms_samples: list[int] = []
        self.last_request_status = ""
        self.last_request_total_ms = 0
        self.last_request_queued_ms = 0
        self.last_request_model_ms = 0
        self.last_request_tool_ms = 0
        self.cancelled_request_ids: set[str] = set()
        self.request_engines: dict[str, set[ChatEngine]] = {}
        self.tool_call_request_ids: dict[str, str] = {}
        self.pending_permission_call_id = ""
        self.pending_permission_request_id = ""
        self.pending_review_request_id = ""
        self.request_routing_decisions: dict[str, list[dict[str, object]]] = {}
        self.tool_decision: asyncio.Event | None = None
        self.tool_approved: bool = True
        self.tool_decision_scope = "once"
        self.tool_review_decision: asyncio.Event | None = None
        self.tool_review_action = "accept"
        self.pending_review_id = ""
        self.pending_write_contexts: dict[str, ToolWriteContext] = {}
        self._budget_lock = asyncio.Lock()
        self._model_slots = asyncio.Semaphore(self.max_inflight_model_calls)
        self._tool_slots = asyncio.Semaphore(self.max_inflight_tools)
        self._subagent_runner: SubagentRunner | None = None
        self.startup_tool_bridge_warming = False
        self.startup_tool_bridge_task: asyncio.Task[None] | None = None

    @property
    def subagent_runner(self) -> SubagentRunner:
        """Lazy-initialized subagent runner.

        Created on first access so self-referential hooks
        (permission_hook, bridge_wrapper) see the fully-constructed state.
        """
        if self._subagent_runner is None:
            self._subagent_runner = SubagentRunner(
                bridge=self.bridge,
                permission_hook=self._tool_permission_hook,
                bridge_wrapper=lambda b, model: self.apply_tool_budget(
                    wrap_bridge_for_model(
                        b,
                        model.tool_profile,
                        read_only=not self.tools_write,
                        deferred_tools=model.deferred_tools,
                        core_tools=model.core_tools,
                    ),
                ),
                event_hook=self._subagent_event_hook,
                models=self.models,
                prompt_enricher=lambda prompt, model: _enrich_prompt_with_workspace_context(self, prompt, model=model),
                system_context_resolver=lambda model, prompt: _build_subagent_system_context(self, model, prompt),
            )
        else:
            # Keep the runner's bridge reference in sync with state
            self._subagent_runner.set_bridge(self.bridge)
            self._subagent_runner.set_event_hook(self._subagent_event_hook)
            self._subagent_runner.set_prompt_enricher(
                lambda prompt, model: _enrich_prompt_with_workspace_context(self, prompt, model=model),
            )
            self._subagent_runner.set_system_context_resolver(
                lambda model, prompt: _build_subagent_system_context(self, model, prompt),
            )
        return self._subagent_runner

    async def _subagent_event_hook(self, event: SubagentEvent) -> None:
        await _forward_subagent_event(self, event)

    def reconfigure_execution_budget(self) -> None:
        """Apply current policy values to execution budget semaphores."""
        self.max_inflight_model_calls = max(1, int(self.max_inflight_model_calls))
        self.max_inflight_tools = max(1, int(self.max_inflight_tools))
        self.exec_queue_depth = max(0, int(self.exec_queue_depth))
        self._model_slots = asyncio.Semaphore(self.max_inflight_model_calls)
        self._tool_slots = asyncio.Semaphore(self.max_inflight_tools)

    def apply_tool_budget(self, bridge: ToolBridge | None) -> ToolBridge | None:
        if bridge is None:
            return None
        if isinstance(bridge, _ToolBudgetBridge):
            return bridge
        return _ToolBudgetBridge(self, bridge)

    async def reserve_model_budget(self) -> tuple[bool, str]:
        """Reserve queue capacity for an incoming chat request."""
        async with self._budget_lock:
            capacity = self.max_inflight_model_calls + self.exec_queue_depth
            pending = self.inflight_model_calls + self.queued_model_calls
            if pending >= capacity:
                self.model_backpressure_count += 1
                return False, (
                    "Model execution backpressure: queue saturated "
                    f"(inflight={self.inflight_model_calls}, queued={self.queued_model_calls}, "
                    f"max_inflight={self.max_inflight_model_calls}, queue_depth={self.exec_queue_depth})"
                )
            self.queued_model_calls += 1
            if self.queued_model_calls > self.model_queue_highwater:
                self.model_queue_highwater = self.queued_model_calls
            return True, ""

    async def rollback_model_budget(self) -> None:
        """Rollback a queued model slot reservation before acquisition."""
        async with self._budget_lock:
            if self.queued_model_calls > 0:
                self.queued_model_calls -= 1

    async def acquire_model_budget(self, request_id: str = "") -> bool:
        while True:
            if request_id and self.is_request_cancelled(request_id):
                return False
            try:
                await asyncio.wait_for(self._model_slots.acquire(), timeout=0.1)
                break
            except asyncio.TimeoutError:
                continue
        async with self._budget_lock:
            if self.queued_model_calls > 0:
                self.queued_model_calls -= 1
            self.inflight_model_calls += 1
            if self.inflight_model_calls > self.model_inflight_highwater:
                self.model_inflight_highwater = self.inflight_model_calls
        return True

    async def release_model_budget(self) -> None:
        async with self._budget_lock:
            if self.inflight_model_calls > 0:
                self.inflight_model_calls -= 1
        self._model_slots.release()

    async def reserve_tool_budget(self, server: str, tool_name: str) -> tuple[bool, str]:
        """Reserve queue capacity for a tool call."""
        async with self._budget_lock:
            capacity = self.max_inflight_tools + self.exec_queue_depth
            pending = self.inflight_tool_calls + self.queued_tool_calls
            if pending >= capacity:
                self.tool_backpressure_count += 1
                return False, (
                    "[Tool execution backpressure: saturated "
                    f"({server}:{tool_name}, inflight={self.inflight_tool_calls}, "
                    f"queued={self.queued_tool_calls}, max_inflight={self.max_inflight_tools}, "
                    f"queue_depth={self.exec_queue_depth})]"
                )
            self.queued_tool_calls += 1
            if self.queued_tool_calls > self.tool_queue_highwater:
                self.tool_queue_highwater = self.queued_tool_calls
            return True, ""

    async def rollback_tool_budget(self) -> None:
        """Rollback a queued tool slot reservation before acquisition."""
        async with self._budget_lock:
            if self.queued_tool_calls > 0:
                self.queued_tool_calls -= 1

    async def acquire_tool_budget(self) -> None:
        await self._tool_slots.acquire()
        async with self._budget_lock:
            if self.queued_tool_calls > 0:
                self.queued_tool_calls -= 1
            self.inflight_tool_calls += 1
            if self.inflight_tool_calls > self.tool_inflight_highwater:
                self.tool_inflight_highwater = self.inflight_tool_calls

    async def release_tool_budget(self) -> None:
        async with self._budget_lock:
            if self.inflight_tool_calls > 0:
                self.inflight_tool_calls -= 1
        self._tool_slots.release()

    def is_request_cancelled(self, request_id: str) -> bool:
        if self.cancel_requested:
            return True
        if not request_id:
            return False
        return request_id in self.cancelled_request_ids

    def mark_request_cancelled(self, request_id: str) -> None:
        if not request_id:
            return
        self.cancelled_request_ids.add(request_id)
        self.tool_approved = False
        self.tool_decision_scope = "once"
        if (
            self.tool_decision
            and not self.tool_decision.is_set()
            and self.pending_permission_request_id == request_id
        ):
            self.tool_decision.set()
        self.tool_review_action = "reject"
        if (
            self.tool_review_decision
            and not self.tool_review_decision.is_set()
            and self.pending_review_request_id == request_id
        ):
            self.tool_review_decision.set()
        for engine in self.request_engines.get(request_id, set()):
            engine.cancel()

    def clear_request_cancelled(self, request_id: str) -> None:
        if not request_id:
            return
        self.cancelled_request_ids.discard(request_id)

    def bind_request_engine(self, request_id: str, engine: ChatEngine) -> None:
        if not request_id:
            return
        self.request_engines.setdefault(request_id, set()).add(engine)

    def unbind_request_engine(self, request_id: str, engine: ChatEngine) -> None:
        if not request_id:
            return
        engines = self.request_engines.get(request_id)
        if not engines:
            return
        engines.discard(engine)
        if not engines:
            self.request_engines.pop(request_id, None)

    def track_tool_call_request(self, call_id: str, request_id: str) -> None:
        if call_id and request_id:
            self.tool_call_request_ids[call_id] = request_id

    def clear_tool_call_request(self, call_id: str) -> None:
        if call_id:
            self.tool_call_request_ids.pop(call_id, None)

    def clear_request_runtime_refs(self, request_id: str) -> None:
        if not request_id:
            return
        self.clear_request_cancelled(request_id)
        self.request_engines.pop(request_id, None)
        self.request_routing_decisions.pop(request_id, None)
        stale_call_ids = [
            call_id
            for call_id, owner in self.tool_call_request_ids.items()
            if owner == request_id
        ]
        for call_id in stale_call_ids:
            self.tool_call_request_ids.pop(call_id, None)
            self.pending_write_contexts.pop(call_id, None)
        if self.pending_permission_request_id == request_id:
            self.pending_permission_call_id = ""
            self.pending_permission_request_id = ""
            self.tool_decision = None
        if self.pending_review_request_id == request_id:
            self.pending_review_request_id = ""
            self.pending_review_id = ""
            self.tool_review_decision = None

    @staticmethod
    def _append_sample(samples: list[int], value: int, limit: int) -> None:
        samples.append(max(0, int(value)))
        if len(samples) > limit:
            del samples[: len(samples) - limit]

    def record_request_metrics(
        self,
        *,
        end_status: str,
        queued_ms: int,
        model_ms: int,
        tool_ms: int,
        total_ms: int,
    ) -> None:
        limit = max(16, self.request_metric_sample_limit)
        self._append_sample(self.request_queued_ms_samples, queued_ms, limit)
        self._append_sample(self.request_model_ms_samples, model_ms, limit)
        self._append_sample(self.request_tool_ms_samples, tool_ms, limit)
        self._append_sample(self.request_total_ms_samples, total_ms, limit)
        self.last_request_status = end_status
        self.last_request_queued_ms = max(0, int(queued_ms))
        self.last_request_model_ms = max(0, int(model_ms))
        self.last_request_tool_ms = max(0, int(tool_ms))
        self.last_request_total_ms = max(0, int(total_ms))

    def request_latency_snapshot(self) -> dict[str, int | str]:
        return {
            "request_samples": len(self.request_total_ms_samples),
            "queued_ms_p50": _percentile(self.request_queued_ms_samples, 50),
            "queued_ms_p95": _percentile(self.request_queued_ms_samples, 95),
            "model_ms_p50": _percentile(self.request_model_ms_samples, 50),
            "model_ms_p95": _percentile(self.request_model_ms_samples, 95),
            "tool_ms_p50": _percentile(self.request_tool_ms_samples, 50),
            "tool_ms_p95": _percentile(self.request_tool_ms_samples, 95),
            "total_ms_p50": _percentile(self.request_total_ms_samples, 50),
            "total_ms_p95": _percentile(self.request_total_ms_samples, 95),
            "last_request_status": self.last_request_status,
            "last_request_queued_ms": self.last_request_queued_ms,
            "last_request_model_ms": self.last_request_model_ms,
            "last_request_tool_ms": self.last_request_tool_ms,
            "last_request_total_ms": self.last_request_total_ms,
        }

    def get_engine(self, model_name: str) -> ChatEngine:
        return get_or_create_engine(
            self,
            model_name,
            permission_hook=self._tool_permission_hook,
            post_tool_hook=self._post_tool_hook,
            tool_invocation_hook=lambda payload: self._tool_invocation_hook(model_name, payload),
            compactor_builder=self._build_compactor,
        )

    async def _tool_invocation_hook(self, model_name: str, payload: dict) -> None:
        session = getattr(self, "session", None)
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

    def cancel_pending_prompts(self) -> None:
        """Release pending tool permission/review waits during cancellation."""
        self.tool_approved = False
        self.tool_decision_scope = "once"
        if self.tool_decision and not self.tool_decision.is_set():
            self.tool_decision.set()
        self.tool_review_action = "reject"
        if self.tool_review_decision and not self.tool_review_decision.is_set():
            self.tool_review_decision.set()

    def _build_compactor(
        self, model_cfg: ModelConfig, provider: Provider,
    ) -> ConversationCompactor | None:
        """Create a compactor for the given model if a context_budget is set."""
        budget = model_cfg.context_budget
        if budget <= 0:
            return None
        summarizer = ProviderSummarizer(
            provider=provider,
            model_id=model_cfg.model_id,
            max_tokens=min(1024, max(256, budget // 16)),
        )
        return ConversationCompactor(
            policy=CompactionPolicy(context_budget=budget),
            summarizer=summarizer,
        )

    async def _tool_permission_hook(self, tool_name: str, arguments: str, server: str, call_id: str) -> bool:
        """Notify frontend and wait for approve/deny before executing a tool."""
        request_id = self.tool_call_request_ids.get(call_id, "")
        if self.is_request_cancelled(request_id):
            self.pending_write_contexts.pop(call_id, None)
            return False
        rule_key = _permission_rule_key(tool_name, server)
        write_context = prepare_write_context(self.workspace, tool_name, arguments, call_id)
        if write_context is not None:
            self.pending_write_contexts[call_id] = write_context
        cached = self.permission_rules.get(rule_key)
        if cached is not None:
            if not cached:
                self.pending_write_contexts.pop(call_id, None)
            return cached
        reason = _describe_permission_reason(
            write_context,
            subagent=get_current_subagent(),
        )
        _notify(
            "tool/permission_request",
            tool_permission_request_params(tool_name, server, arguments, reason=reason),
        )
        event = asyncio.Event()
        self.tool_decision = event
        self.tool_approved = False
        self.tool_decision_scope = "once"
        self.pending_permission_call_id = call_id
        self.pending_permission_request_id = request_id
        loop = asyncio.get_running_loop()
        started = loop.time()
        timed_out = False
        try:
            timeout = self.permission_wait_timeout_s if self.permission_wait_timeout_s > 0 else None
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            timed_out = True
            self.tool_approved = False
            self.tool_decision_scope = "once"
            self.permission_timeout_count += 1
            _notify("error", error_params(
                f"Tool permission timed out after {self.permission_wait_timeout_s:.0f}s ({server}:{tool_name}); denying call.",
            ))
        finally:
            if self.pending_permission_call_id == call_id:
                self.pending_permission_call_id = ""
                self.pending_permission_request_id = ""
                self.tool_decision = None
            self.permission_wait_ms += int((loop.time() - started) * 1000)

        if timed_out:
            self.pending_write_contexts.pop(call_id, None)
            return False
        if self.is_request_cancelled(request_id):
            self.pending_write_contexts.pop(call_id, None)
            return False
        if self.tool_decision_scope == "session":
            self.permission_rules[rule_key] = self.tool_approved
            _persist_state(self, {"permission_rules": state_permission_rules(self)})
        if not self.tool_approved:
            self.pending_write_contexts.pop(call_id, None)
        return self.tool_approved

    async def _post_tool_hook(
        self,
        tool_name: str,
        arguments: str,
        result: str,
        server: str,
        call_id: str,
    ) -> str:
        write_context = self.pending_write_contexts.pop(call_id, None)
        request_id = self.tool_call_request_ids.get(call_id, "")
        if self.is_request_cancelled(request_id):
            if write_context is not None:
                restore_write_context(write_context)
            return result + "\n\n[Tool run cancelled before filesystem review.]"
        if write_context is None:
            return result

        changes = detect_changes(write_context)
        if not changes:
            return result

        review_id = f"review-{call_id}"
        review = build_review_preview(self.workspace, review_id, changes)
        if review is None:
            return result
        verification_commands = (
            [
                command.display
                for command in select_verification_commands(
                    self.workspace,
                    [change.path for change in changes],
                    bridge=self.bridge,
                    rom_path=self.rom_path,
                )
            ]
            if self.verify_hooks
            else []
        )
        _notify("tool/review_request", tool_review_request_params(
            review_id=review.review_id,
            name=tool_name,
            server=server,
            summary=review.summary,
            paths=review.paths,
            diff_lines=review.diff_lines,
            omitted=review.omitted,
            verification_commands=verification_commands,
        ))
        event = asyncio.Event()
        self.tool_review_decision = event
        self.tool_review_action = "accept"
        self.pending_review_id = review.review_id
        self.pending_review_request_id = request_id
        loop = asyncio.get_running_loop()
        started = loop.time()
        review_timed_out = False
        try:
            timeout = self.review_wait_timeout_s if self.review_wait_timeout_s > 0 else None
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            review_timed_out = True
            self.tool_review_action = "reject"
            self.review_timeout_count += 1
            _notify("error", error_params(
                f"Tool review timed out after {self.review_wait_timeout_s:.0f}s ({server}:{tool_name}); reverting changes.",
            ))
        finally:
            if self.pending_review_id == review.review_id:
                self.tool_review_decision = None
                self.pending_review_id = ""
                self.pending_review_request_id = ""
            self.review_wait_ms += int((loop.time() - started) * 1000)

        if self.tool_review_action != "accept":
            restore_write_context(write_context)
            if review_timed_out:
                return result + "\n\n[Filesystem diff review timed out. Changes were reverted.]"
            return result + "\n\n[Filesystem diff rejected by user. Changes were reverted.]"

        if not self.verify_hooks:
            return result + "\n\n[Filesystem diff accepted by user.]"

        try:
            verification = await run_verification_hooks(
                self.workspace,
                [change.path for change in changes],
                bridge=self.bridge,
                rom_path=self.rom_path,
            )
        except Exception as exc:
            return result + f"\n\n[Filesystem diff accepted by user. Verification failed to run: {exc}]"

        rendered = verification.render()
        if not rendered:
            return result + "\n\n[Filesystem diff accepted by user.]"
        return result + "\n\n[Filesystem diff accepted by user.]\n\n" + rendered

async def replace_bridge(state: ServeState, bridge: ToolBridge | None, warnings: list[str]) -> None:
    old_bridge = state.bridge
    state.bridge = bridge
    state.bridge_errors = warnings
    for engine in state.engines.values():
        engine.bridge = bridge
    if old_bridge is not None:
        await old_bridge.close()


async def refresh_tool_bridge(state: ServeState) -> None:
    if not state.tools_enabled:
        await replace_bridge(state, None, [])
    else:
        bridge, warnings = await connect_tool_bridge(
            state.workspace,
            state.mcp_path,
            rom_path=getattr(state, "rom_path", None),
        )
        # Compose the subagent bridge alongside the main tool surface so
        # orchestrator models can delegate to specialist subagents. Always
        # enabled in orchestrator mode regardless of user preference.
        expose_subagents = state.subagent_tools_enabled or state.mode == ORCHESTRATOR_MODE
        if expose_subagents and state.models:
            subagent_bridge = SubagentBridge(
                runner=state.subagent_runner,
                models=state.models,
                system_context_fn=state.subagent_runner.resolve_system_context,
            )
            if bridge is None:
                bridge = subagent_bridge
            elif isinstance(bridge, CompositeBridge):
                bridge.add_bridge(subagent_bridge)
            else:
                bridge = CompositeBridge([bridge, subagent_bridge])
        await replace_bridge(state, bridge, warnings)
    await _refresh_focus_context(state)


async def _resolve_enriched_attachments(
    state: ServeState,
    message: str,
    *,
    requested_attachments: list[dict[str, Any]] | None = None,
    model: ModelConfig | None = None,
) -> list[dict[str, Any]]:
    attachments = resolve_message_attachments(
        state.workspace,
        message,
        requested=requested_attachments if isinstance(requested_attachments, list) else None,
    )
    return await add_attachment_context_packs(
        attachments,
        bridge=state.bridge,
        model=model or state.models.get(state.active_model),
        lsp_context_mode=state.lsp_context_mode,
        prompt_query=message,
    )


async def _resolve_enriched_construct_refs(
    state: ServeState,
    message: str,
    *,
    requested_construct_refs: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    refs = resolve_message_construct_refs(
        state.workspace,
        message,
        requested=requested_construct_refs if isinstance(requested_construct_refs, list) else None,
    )
    return await add_construct_context_packs(refs, bridge=state.bridge, workspace=state.workspace)


async def _build_subagent_system_context(
    state: ServeState,
    model: ModelConfig,
    prompt: str = "",
) -> str:
    focus_context = await _resolve_focus_context(state, model.name, query=prompt)
    return build_harness_prompt(state.workspace, state.rom_path, focus_context)


async def _enrich_prompt_with_workspace_context(
    state: ServeState,
    message: str,
    *,
    requested_attachments: list[dict[str, Any]] | None = None,
    requested_construct_refs: list[dict[str, Any]] | None = None,
    model: ModelConfig | None = None,
) -> str:
    refs = await _resolve_enriched_construct_refs(
        state,
        message,
        requested_construct_refs=requested_construct_refs,
    )
    attachments = await _resolve_enriched_attachments(
        state,
        message,
        requested_attachments=requested_attachments,
        model=model,
    )
    return enrich_prompt_with_attachments(
        enrich_prompt_with_construct_refs(message, refs),
        attachments,
    )

def _next_turn_id(state: ServeState) -> str:
    state.turn_index += 1
    return f"turn-{state.turn_index}"


def _next_request_id(state: ServeState) -> str:
    state.request_index += 1
    return f"req-{state.request_index}"


def _make_span_id(request_id: str, target_name: str, ordinal: int) -> str:
    base = request_id or "req-unknown"
    return f"{base}:{target_name}:{ordinal}"


def _emit_message(
    state: ServeState,
    *,
    role: MessageRole,
    content: str,
    turn_id: str,
    thinking: str = "",
    request_id: str = "",
    span_id: str = "",
    model: str = "",
    tool_name: str = "",
    tool_server: str = "",
    tool_arguments: str = "",
    tool_group: str = "",
    attachments: list[AttachmentMeta] | None = None,
    construct_refs: list[ConstructRef] | None = None,
) -> None:
    message_id = f"live-{state.message_index}"
    state.message_index += 1
    _notify("message", message_params(
        message_id=message_id,
        role=role,
        content=content,
        timestamp=int(datetime.now(timezone.utc).timestamp() * 1000),
        thinking=thinking or None,
        turn_id=turn_id,
        model=model or None,
        tool_name=tool_name or None,
        tool_server=tool_server or None,
        tool_arguments=tool_arguments or None,
        tool_group=tool_group or None,
        attachments=attachments or None,
        construct_refs=construct_refs or None,
        request_id=request_id or None,
        span_id=span_id or None,
    ))

def parse_serve_args(args: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--registry", default=str(REGISTRY_PATH))
    parser.add_argument("--mcp-config", default=str(MCP_CONFIG_PATH))
    parser.add_argument("--backend", default=os.environ.get("Z3CLI_BACKEND", "studio"))
    parser.add_argument("--host", default=os.environ.get("LMSTUDIO_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("LMSTUDIO_PORT", "1234")))
    parser.add_argument(
        "--api-base",
        "--studio-api-base",
        dest="studio_api_base",
        default=os.environ.get("LMSTUDIO_BASE_URL", API_BASE),
    )
    parser.add_argument(
        "--llamacpp-api-base",
        default=os.environ.get("LLAMACPP_BASE_URL", DEFAULT_LLAMACPP_API_BASE),
    )
    parser.add_argument("--llamacpp-model", default=DEFAULT_LLAMACPP_MODEL)
    parser.add_argument("--workspace", default=str(DEFAULT_WORKSPACE))
    parser.add_argument("--rom", default=str(DEFAULT_ROM))
    parser.add_argument("--model", default=DEFAULT_ACTIVE_MODEL)
    parser.add_argument("--mode", default="manual")
    parser.add_argument("--orchestrator", default="", help="Model to use as orchestrator planner (empty = auto-select)")
    parser.add_argument("--broadcast-models", default=",".join(DEFAULT_BROADCAST_MODELS))
    parser.add_argument("--tools", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--lsp-context", choices=LSP_CONTEXT_MODES, default="auto")
    parser.add_argument("--auto-load", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--auto-start-server", action=argparse.BooleanOptionalAction, default=True)
    parsed, _ = parser.parse_known_args(args)
    parsed.model_explicit = "--model" in args
    normalized_mode, _alias = normalize_mode(parsed.mode)
    if normalized_mode not in VALID_MODES:
        parser.error(f"--mode must be one of {mode_usage_text()} (legacy aliases: switchhook, oracle-main)")
    return parsed


async def init_state(args: list[str], *, defer_tool_bridge: bool = False) -> ServeState:
    """Initialize state from CLI args passed through from the frontend."""
    state = ServeState()

    parsed = parse_serve_args(args)
    state.registry_path = Path(parsed.registry).expanduser()
    state.mcp_path = Path(parsed.mcp_config).expanduser()
    backend_name = str(parsed.backend).lower()
    if backend_name in VALID_BACKENDS:
        state.backend_name = backend_name
    state.host = parsed.host
    state.port = parsed.port
    state.active_model = parsed.model
    mode, _alias = normalize_mode(str(parsed.mode))
    if mode in VALID_MODES:
        state.mode = mode
    state.studio_api_base = parsed.studio_api_base.rstrip("/")
    state.llamacpp_api_base = parsed.llamacpp_api_base.rstrip("/")
    state.llamacpp_model = parsed.llamacpp_model
    state.workspace = Path(parsed.workspace).expanduser().resolve()
    state.rom_path = None if not parsed.rom else Path(parsed.rom).expanduser().resolve()
    state.auto_start_server = parsed.auto_start_server
    state.tools_enabled = parsed.tools
    state.auto_load = parsed.auto_load
    state.broadcast_models = [value.strip() for value in parsed.broadcast_models.split(",") if value.strip()]
    state.orchestrator_model = str(parsed.orchestrator or "").strip()
    state.lsp_context_mode = normalize_lsp_context_mode(parsed.lsp_context)
    state.last_active_model = state.active_model
    state.last_active_at = datetime.now(timezone.utc).isoformat()

    state.models, state.routers = load_registry(state.registry_path)
    state.active_model, startup_warning = choose_startup_model(
        state.active_model,
        state.models,
        explicit=bool(getattr(parsed, "model_explicit", False)),
        auto_load=state.auto_load,
    )
    if startup_warning:
        state.startup_warnings.append(startup_warning)
    z3ui_model_warning = _coerce_z3ui_active_model(state, parsed.model)
    if z3ui_model_warning:
        state.startup_warnings.append(z3ui_model_warning)
    state.last_active_model = state.active_model
    set_backend(state, state.backend_name)
    if state.backend_name == "studio" and state.auto_start_server:
        ensure_server(state.host, state.port)

    if state.tools_enabled:
        if defer_tool_bridge:
            state.startup_tool_bridge_warming = True
        else:
            await refresh_tool_bridge(state)

    # Start session persistence
    state.session.start(
        active_model=state.active_model,
        backend=state.backend_name,
        mode=state.mode,
        workspace=str(state.workspace),
        rom_path=str(state.rom_path) if state.rom_path else "",
        tools_enabled=state.tools_enabled,
        broadcast_models=state.broadcast_models,
        llamacpp_model=state.llamacpp_model,
        tools_write=state.tools_write,
        verify_hooks=state.verify_hooks,
        focus_path=str(state.focus_path) if state.focus_path else "",
    )

    return state


async def _run_startup_tool_bridge_warmup(state: ServeState) -> None:
    """Finish deferred tool-bridge startup and refresh the frontend."""
    cancelled = False
    try:
        await refresh_tool_bridge(state)
    except asyncio.CancelledError:
        cancelled = True
        raise
    except Exception as exc:
        state.bridge_errors = [f"Tool bridge warmup failed: {exc}"]
    finally:
        state.startup_tool_bridge_warming = False
        state.startup_tool_bridge_task = None
        if not cancelled:
            _notify("ready", build_ready_params(state))


async def _await_startup_tool_bridge(state: ServeState) -> None:
    """Block request handling until deferred startup tool warmup finishes."""
    task = state.startup_tool_bridge_task
    if task is None:
        return
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        raise
    except Exception:
        return


async def _cancel_startup_tool_bridge_warmup(state: ServeState) -> None:
    """Stop the deferred warmup task before doing an explicit bridge refresh."""
    task = state.startup_tool_bridge_task
    state.startup_tool_bridge_task = None
    state.startup_tool_bridge_warming = False
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception:
        pass


async def _refresh_tool_bridge_immediately(state: ServeState) -> None:
    """Cancel deferred warmup, then refresh the tool bridge on demand."""
    await _cancel_startup_tool_bridge_warmup(state)
    if state.tools_enabled:
        await refresh_tool_bridge(state)
    else:
        await replace_bridge(state, None, [])
        await _refresh_focus_context(state)


def build_ready_params(state: ServeState) -> ReadyParams:
    """Build the ready notification payload."""
    avg_tool_latency_ms = (
        int(state.tool_latency_ms_total / state.tool_latency_samples)
        if state.tool_latency_samples > 0 else 0
    )
    latency = state.request_latency_snapshot()
    loaded_runtime_models = loaded_model_runtime_infos(state)
    loaded_runtime_payload: list[LoadedModelRuntimeInfo] = []
    for item in loaded_runtime_models:
        runtime_item: LoadedModelRuntimeInfo = {
            "identifier": str(item.get("identifier", "")),
            "model_key": str(item.get("model_key", "")),
        }
        if item.get("display_name"):
            runtime_item["display_name"] = str(item["display_name"])
        if int(item.get("size_bytes", 0) or 0) > 0:
            runtime_item["size_bytes"] = int(item["size_bytes"])
        if item.get("architecture"):
            runtime_item["architecture"] = str(item["architecture"])
        if item.get("quantization"):
            runtime_item["quantization"] = str(item["quantization"])
        if int(item.get("context_length", 0) or 0) > 0:
            runtime_item["context_length"] = int(item["context_length"])
        if int(item.get("max_context_length", 0) or 0) > 0:
            runtime_item["max_context_length"] = int(item["max_context_length"])
        if int(item.get("parallel", 0) or 0) > 0:
            runtime_item["parallel"] = int(item["parallel"])
        if item.get("status"):
            runtime_item["status"] = str(item["status"])
        if int(item.get("queued", 0) or 0) > 0:
            runtime_item["queued"] = int(item["queued"])
        if int(item.get("ttl_ms", 0) or 0) > 0:
            runtime_item["ttl_ms"] = int(item["ttl_ms"])
        loaded_runtime_payload.append(runtime_item)
    models_info: list[ReadyModelInfo] = []
    for model in z3ui_model_infos(state):
        cfg = state.models.get(str(model["name"]))
        payload: ReadyModelInfo = {
            "name": str(model["name"]),
            "model_id": str(model["model_id"]),
            "role": str(model["role"]),
            "loaded": bool(model["loaded"]),
            "tools_enabled": bool(model["tools_enabled"]),
            "context_budget": cfg.context_budget if cfg is not None else 0,
        }
        if model.get("description"):
            payload["description"] = str(model["description"])
        if model.get("provider"):
            payload["provider"] = str(model["provider"])
        if model.get("loaded_identifier"):
            payload["loaded_identifier"] = str(model["loaded_identifier"])
        if int(model.get("size_bytes", 0) or 0) > 0:
            payload["size_bytes"] = int(model["size_bytes"])
        if model.get("status"):
            payload["status"] = str(model["status"])
        if int(model.get("parallel", 0) or 0) > 0:
            payload["parallel"] = int(model["parallel"])
        if int(model.get("context_length", 0) or 0) > 0:
            payload["context_length"] = int(model["context_length"])
        if int(model.get("max_context_length", 0) or 0) > 0:
            payload["max_context_length"] = int(model["max_context_length"])
        if model.get("architecture"):
            payload["architecture"] = str(model["architecture"])
        if model.get("quantization"):
            payload["quantization"] = str(model["quantization"])
        if int(model.get("queued", 0) or 0) > 0:
            payload["queued"] = int(model["queued"])
        models_info.append(payload)

    warnings = list(state.startup_warnings)
    warnings.extend(state.bridge_errors)
    warnings.extend(rollout_warnings(state.models))
    if state.startup_tool_bridge_warming:
        warnings.append("Tool bridge warming up; tools and server list will populate shortly.")

    ready: ReadyParams = {
        "version": __version__,
        "backend": state.backend_name,
        "active_model": active_model_name(state),
        "studio_model": state.active_model,
        "mode": state.mode,
        "workspace": str(state.workspace),
        "rom_path": str(state.rom_path) if state.rom_path else "",
        "tools_enabled": state.tools_enabled,
        "tools_write": state.tools_write,
        "verify_hooks": state.verify_hooks,
        "registry_path": str(state.registry_path),
        "servers": state.bridge.server_names if state.bridge else [],
        "tool_count": state.bridge.tool_count if state.bridge else 0,
        "warnings": _compact_warning_list(warnings),
        "models": models_info,
        "loaded_models": loaded_runtime_payload,
        "loaded_model_count": len(loaded_runtime_payload),
        "loaded_model_memory_bytes": total_loaded_model_bytes(loaded_runtime_payload),
        "session_path": str(state.session.path) if state.session.path else "",
        "focus_file": str(state.focus_path) if state.focus_path else "",
        "lsp_context_mode": state.lsp_context_mode,
        "broadcast_models": state.broadcast_models,
        "orchestrator_model": state.orchestrator_model or default_orchestrator_model(state.models) or "",
        "prompt_tokens": state.prompt_tokens,
        "cache_creation_tokens": state.cache_creation_tokens,
        "cache_read_tokens": state.cache_read_tokens,
        "completion_tokens": state.completion_tokens,
        "session_messages": state.session.message_count,
        "session_tool_calls": state.tool_call_count,
        "last_active_at": state.last_active_at,
        "last_active_model": state.last_active_model,
        "permission_rules": state_permission_rules(state),
        "shell_active": bool(state.shell and state.shell.active),
        "shell_cwd": str(state.shell.cwd if state.shell else state.workspace),
        "cancel_count": state.cancel_count,
        "backend_restart_count": state.backend_restart_count,
        "tool_latency_ms": avg_tool_latency_ms,
        "tool_latency_samples": state.tool_latency_samples,
        "review_wait_ms": state.review_wait_ms,
        "permission_wait_ms": state.permission_wait_ms,
        "permission_timeout_count": state.permission_timeout_count,
        "review_timeout_count": state.review_timeout_count,
        "model_retry_count": state.model_retry_count,
        "model_retry_backoff_ms": state.model_retry_backoff_ms,
        "model_error_count": state.model_error_count,
        "tool_timeout_count": state.tool_timeout_count,
        "model_alias_resolutions": state.model_alias_resolutions,
        "model_lookup_failures": state.model_lookup_failures,
        "model_request_counts": dict(state.model_request_counts),
        "model_backpressure_count": state.model_backpressure_count,
        "tool_backpressure_count": state.tool_backpressure_count,
        "model_queue_highwater": state.model_queue_highwater,
        "tool_queue_highwater": state.tool_queue_highwater,
        "model_inflight_highwater": state.model_inflight_highwater,
        "tool_inflight_highwater": state.tool_inflight_highwater,
        "inflight_model_calls": state.inflight_model_calls,
        "queued_model_calls": state.queued_model_calls,
        "inflight_tool_calls": state.inflight_tool_calls,
        "queued_tool_calls": state.queued_tool_calls,
        "model_retry_max": state.model_retry_max,
        "model_retry_base_ms": int(state.model_retry_backoff_base_s * 1000),
        "tool_exec_timeout_s": state.tool_exec_timeout_s,
        "max_inflight_model_calls": state.max_inflight_model_calls,
        "max_inflight_tools": state.max_inflight_tools,
        "exec_queue_depth": state.exec_queue_depth,
        "request_count": state.request_count,
        "request_success_count": state.request_success_count,
        "request_error_count": state.request_error_count,
        "request_reject_count": state.request_reject_count,
        "request_cancel_count": state.request_cancel_count,
        "span_count": state.span_count,
        "last_request_id": state.last_request_id,
        "last_span_id": state.last_span_id,
        "last_tool_call_id": state.last_tool_call_id,
        "request_samples": int(latency["request_samples"]),
        "queued_ms_p50": int(latency["queued_ms_p50"]),
        "queued_ms_p95": int(latency["queued_ms_p95"]),
        "model_ms_p50": int(latency["model_ms_p50"]),
        "model_ms_p95": int(latency["model_ms_p95"]),
        "tool_ms_p50": int(latency["tool_ms_p50"]),
        "tool_ms_p95": int(latency["tool_ms_p95"]),
        "total_ms_p50": int(latency["total_ms_p50"]),
        "total_ms_p95": int(latency["total_ms_p95"]),
        "last_request_status": str(latency["last_request_status"]),
        "last_request_queued_ms": int(latency["last_request_queued_ms"]),
        "last_request_model_ms": int(latency["last_request_model_ms"]),
        "last_request_tool_ms": int(latency["last_request_tool_ms"]),
        "last_request_total_ms": int(latency["last_request_total_ms"]),
    }
    return ready
async def handle_chat(
    state: ServeState,
    req_id: int | None,
    params: dict,
    *,
    request_id: str = "",
) -> tuple[str, int]:
    """Handle a chat request — stream events as notifications, respond when done."""
    message = str(params.get("message", ""))
    requested_attachments = params.get("attachments")
    requested_construct_refs = params.get("construct_refs")
    requested_model = params.get("model")
    active_model = state.active_model
    _alias = ""
    if isinstance(requested_model, str) and requested_model:
        try:
            active_model, _alias = resolve_existing_model_name(str(requested_model), state.models)
        except RuntimeError:
            state.model_lookup_failures += 1
            raise
    if _alias:
        state.model_alias_resolutions += 1
    if state.startup_tool_bridge_warming:
        await _await_startup_tool_bridge(state)
    attachments = resolve_message_attachments(
        state.workspace,
        message,
        requested=requested_attachments if isinstance(requested_attachments, list) else None,
    )
    construct_refs = resolve_message_construct_refs(
        state.workspace,
        message,
        requested=requested_construct_refs if isinstance(requested_construct_refs, list) else None,
    )
    attachment_meta: list[AttachmentMeta] = [
        {
            "path": str(item["path"]),
            "lines": int(item["lines"]),
            "chars": int(item["chars"]),
        }
        for item in attachments
    ]
    construct_ref_meta: list[ConstructRef] = []
    for item in construct_refs:
        ref_entry: ConstructRef = {
            "kind": str(item["kind"]),
            "query": str(item["query"]),
        }
        if item.get("token"):
            ref_entry["token"] = str(item["token"])
        if item.get("id"):
            ref_entry["id"] = str(item["id"])
        if item.get("label"):
            ref_entry["label"] = str(item["label"])
        construct_ref_meta.append(ref_entry)

    targets, decisions = resolve_targets_with_reason(
        models=state.models,
        routers=state.routers,
        active_model=active_model,
        mode=state.mode,
        prompt=message,
        broadcast_models=state.broadcast_models,
        backend_name=state.backend_name,
        llamacpp_model=state.llamacpp_model,
        temperature=0.2,
        max_tokens=1024,
        orchestrator_model=state.orchestrator_model,
    )
    if request_id:
        state.request_routing_decisions[request_id] = [
            decision.to_dict() for decision in decisions
        ]
    ensure_targets_available(targets)

    multi_target = len(targets) > 1
    for target in targets:
        state.model_request_counts[target.name] = state.model_request_counts.get(target.name, 0) + 1
    target_turns: list[tuple[ModelConfig, str, str]] = []
    for target in targets:
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
            prompt_query=message,
        )
        target_engine_message = enrich_prompt_with_attachments(
            enrich_prompt_with_construct_refs(message, target_construct_refs),
            target_attachments,
        )
        target_focus_context = await _resolve_focus_context(state, target.name, query=message)
        target_turns.append((target, target_engine_message, target_focus_context))
    prompt_tokens = 0
    completion_tokens = 0
    cache_creation_tokens = 0
    cache_read_tokens = 0
    request_tool_ms = 0
    end_status = "success"
    turn_id = _next_turn_id(state)

    # Record user message to session
    is_first_message = state.session.message_count == 0
    for target, target_engine_message, _target_focus_context in target_turns:
        state.session.append_engine_msg(target.name, {
            "role": "user",
            "content": target_engine_message,
            "display_content": message,
            "attachments": attachment_meta,
            "construct_refs": construct_ref_meta,
            "turn_id": turn_id,
            "request_id": request_id,
        })
    if is_first_message:
        state.session.rename_from_first_message(message)
    _persist_state(state, model_name=active_model)
    _emit_message(
        state,
        role="user",
        content=message,
        turn_id=turn_id,
        request_id=request_id,
        attachments=attachment_meta,
        construct_refs=construct_ref_meta,
    )

    for target_index, (target, engine_message, focus_context) in enumerate(target_turns, start=1):
        loop = asyncio.get_running_loop()
        tool_started_at: dict[str, float] = {}
        tool_groups_by_call_id: dict[str, str] = {}
        pending_anon_tool_groups: list[str] = []
        span_id = _make_span_id(request_id, target.name, target_index) if request_id else ""
        if span_id:
            state.span_count += 1
            state.last_span_id = span_id
        request_name = resolve_request_model_name(state, target)
        engine = state.get_engine(target.name)
        state.bind_request_engine(request_id, engine)
        retry_count_start = int(getattr(engine, "provider_retry_count", 0))
        retry_backoff_start = int(getattr(engine, "provider_retry_backoff_ms", 0))
        provider_errors_start = int(getattr(engine, "provider_error_count", 0))
        tool_timeout_start = int(getattr(engine, "tool_timeout_count", 0))
        effective_bridge = wrap_bridge_for_model(
            state.bridge, target.tool_profile, read_only=not state.tools_write,
            deferred_tools=target.deferred_tools,
            core_tools=target.core_tools,
        )
        effective_bridge = state.apply_tool_budget(effective_bridge)
        engine.bridge = effective_bridge
        tools_available = bool(effective_bridge and state.tools_enabled and target.tools_enabled)
        use_native_tools = bool(tools_available and target.native_tools)
        # Compose the target's system prompt. In orchestrator mode, prepend
        # the planner-specific instructions with a catalog of specialists.
        system_parts = [
            build_harness_prompt(state.workspace, state.rom_path, focus_context),
            build_local_identity_prompt(target),
            build_tool_use_prompt(
                tools_available,
                target.tool_profile,
                deferred_tools=target.deferred_tools,
                native_tools=target.native_tools,
            ),
            build_tool_bias_prompt(
                message,
                tools_available,
                target.tool_profile,
                deferred_tools=target.deferred_tools,
                native_tools=target.native_tools,
            ),
        ]
        if state.mode == ORCHESTRATOR_MODE:
            system_parts.append(_build_orchestrator_catalog(state))
        system_parts.extend(resolve_oracle_profile_system_prompts(message))
        system_parts.append(target.system_prompt)
        system = merge_system_prompts(*system_parts)
        if multi_target:
            _notify("text", text_params(f"\n\n### {target.name}\n\n", request_id=request_id, span_id=span_id))

        use_thinking = bool(target.thinking_tier)
        assistant_text = ""
        rendered_assistant_text = ""
        assistant_thinking = ""
        assistant_tool_results: list[tuple[str, str]] = []
        target_done = False
        saw_error = False
        try:
            async for event in engine.chat(
                message=engine_message,
                model_id=request_name,
                system=system,
                temperature=target.temperature,
                max_tokens=target.max_tokens,
                use_tools=use_native_tools,
                thinking=use_thinking,
                max_tool_result=4000 if target.tool_profile and target.tool_profile != "*" else 0,
                prompt_cache=target.prompt_cache,
            ):
                if state.is_request_cancelled(request_id):
                    end_status = "cancelled"
                    engine.cancel()
                    break
                if isinstance(event, ThinkingEvent):
                    _notify("thinking", thinking_params(event.text, request_id=request_id, span_id=span_id))
                    assistant_thinking += event.text
                elif isinstance(event, CompactionEvent):
                    _notify("context/compacted", context_compacted_params(
                        summary=event.summary,
                        replaced=event.replaced_count,
                        tokens_before=event.tokens_before,
                        tokens_after=event.tokens_after,
                        model=target.name,
                    ))
                    _emit_message(
                        state,
                        role="system",
                        content=(
                            f"Compacted {event.replaced_count} earlier messages "
                            f"({event.tokens_before} → {event.tokens_after} tokens)."
                        ),
                        turn_id=turn_id,
                        request_id=request_id,
                        span_id=span_id,
                        model=target.name,
                    )
                elif isinstance(event, TextEvent):
                    assistant_text += event.text
                    rendered_assistant_text, delta = _assistant_text_delta(
                        assistant_text,
                        rendered_assistant_text,
                        tool_results=assistant_tool_results,
                    )
                    if delta:
                        _notify("text", text_params(delta, request_id=request_id, span_id=span_id))
                elif isinstance(event, ToolCallEvent):
                    call_id = event.call_id or ""
                    state.track_tool_call_request(call_id, request_id)
                    if call_id:
                        tool_group = f"{span_id}:{call_id}" if span_id else call_id
                        tool_groups_by_call_id[call_id] = tool_group
                    else:
                        tool_group = (
                            f"{span_id}:tool-{len(pending_anon_tool_groups) + 1}"
                            if span_id else f"tool-{len(pending_anon_tool_groups) + 1}"
                        )
                        pending_anon_tool_groups.append(tool_group)
                    if call_id:
                        state.last_tool_call_id = call_id
                    sanitized_assistant_text = _sanitize_assistant_content(
                        assistant_text,
                        tool_results=assistant_tool_results,
                    )
                    if sanitized_assistant_text or assistant_thinking.strip():
                        _emit_message(
                            state,
                            role="assistant",
                            content=sanitized_assistant_text,
                            turn_id=turn_id,
                            thinking=assistant_thinking,
                            request_id=request_id,
                            span_id=span_id,
                            model=target.name,
                        )
                    _notify("tool_call", tool_call_params(
                        event.name,
                        event.server,
                        event.arguments,
                        call_id=call_id or None,
                        tool_group=tool_group or None,
                        request_id=request_id or None,
                        span_id=span_id or None,
                    ))
                    state.session.append_engine_msg(target.name, {
                        "role": "assistant",
                        "content": sanitized_assistant_text,
                        "thinking": assistant_thinking,
                        "turn_id": turn_id,
                        "request_id": request_id,
                        "span_id": span_id,
                        "tool_calls": [{
                            "name": event.name,
                            "arguments": event.arguments,
                            "server": event.server,
                            "tool_call_id": call_id,
                            "tool_group": tool_group,
                            "request_id": request_id,
                            "span_id": span_id,
                        }],
                    })
                    _emit_message(
                        state,
                        role="tool",
                        content="",
                        turn_id=turn_id,
                        request_id=request_id,
                        span_id=span_id,
                        model=target.name,
                        tool_name=event.name,
                        tool_server=event.server,
                        tool_arguments=event.arguments,
                        tool_group=tool_group,
                    )
                    state.tool_call_count += 1
                    if call_id:
                        tool_started_at[call_id] = loop.time()
                    _persist_state(state, model_name=target.name)
                    assistant_text = ""
                    rendered_assistant_text = ""
                    assistant_thinking = ""
                elif isinstance(event, ToolResultEvent):
                    call_id = event.call_id or ""
                    if call_id:
                        tool_group = tool_groups_by_call_id.pop(
                            call_id,
                            f"{span_id}:{call_id}" if span_id else call_id,
                        )
                    elif pending_anon_tool_groups:
                        tool_group = pending_anon_tool_groups.pop(0)
                    else:
                        tool_group = f"{span_id}:tool-result" if span_id else "tool-result"
                    _notify("tool_result", tool_result_params(
                        event.name,
                        event.result,
                        server=event.server,
                        call_id=call_id or None,
                        tool_group=tool_group,
                        request_id=request_id or None,
                        span_id=span_id or None,
                    ))
                    state.session.append_engine_msg(target.name, {
                        "role": "tool",
                        "name": event.name,
                        "server": event.server,
                        "content": event.result,
                        "turn_id": turn_id,
                        "tool_call_id": call_id,
                        "tool_group": tool_group,
                        "request_id": request_id,
                        "span_id": span_id,
                    })
                    _emit_message(
                        state,
                        role="tool",
                        content=event.result,
                        turn_id=turn_id,
                        request_id=request_id,
                        span_id=span_id,
                        model=target.name,
                        tool_name=event.name,
                        tool_server=event.server,
                        tool_group=tool_group,
                    )
                    assistant_tool_results.append((event.name, event.result))
                    if call_id:
                        started = tool_started_at.pop(call_id, None)
                        if started is not None:
                            elapsed_ms = int((loop.time() - started) * 1000)
                            request_tool_ms += elapsed_ms
                            state.tool_latency_ms_total += elapsed_ms
                            state.tool_latency_samples += 1
                        state.clear_tool_call_request(call_id)
                elif isinstance(event, ErrorEvent):
                    saw_error = True
                    _notify("error", error_params(event.message, request_id=request_id, span_id=span_id))
                elif isinstance(event, DoneEvent):
                    state.prompt_tokens += event.prompt_tokens
                    state.completion_tokens += event.completion_tokens
                    state.cache_creation_tokens += event.cache_creation_tokens
                    state.cache_read_tokens += event.cache_read_tokens
                    prompt_tokens += event.prompt_tokens
                    completion_tokens += event.completion_tokens
                    cache_creation_tokens += event.cache_creation_tokens
                    cache_read_tokens += event.cache_read_tokens
                    _persist_state(state, model_name=target.name)
                    target_done = True
                    break
        finally:
            state.unbind_request_engine(request_id, engine)

        # Record final assistant response to session
        sanitized_assistant_text = _sanitize_assistant_content(
            assistant_text,
            tool_results=assistant_tool_results,
        )
        if sanitized_assistant_text or assistant_thinking.strip():
            state.session.append_engine_msg(target.name, {
                "role": "assistant",
                "content": sanitized_assistant_text,
                "thinking": assistant_thinking,
                "turn_id": turn_id,
                "request_id": request_id,
                "span_id": span_id,
            })
            _emit_message(
                state,
                role="assistant",
                content=sanitized_assistant_text,
                turn_id=turn_id,
                thinking=assistant_thinking,
                request_id=request_id,
                span_id=span_id,
                model=target.name,
            )

        state.model_retry_count += max(0, int(getattr(engine, "provider_retry_count", 0)) - retry_count_start)
        state.model_retry_backoff_ms += max(0, int(getattr(engine, "provider_retry_backoff_ms", 0)) - retry_backoff_start)
        state.model_error_count += max(0, int(getattr(engine, "provider_error_count", 0)) - provider_errors_start)
        state.tool_timeout_count += max(0, int(getattr(engine, "tool_timeout_count", 0)) - tool_timeout_start)

        if saw_error and end_status != "cancelled":
            end_status = "error"
        if state.is_request_cancelled(request_id):
            end_status = "cancelled"
            break
        if not target_done:
            if end_status == "success":
                end_status = "error"
            break

    _notify("done", done_params(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        cache_creation_tokens=cache_creation_tokens,
        cache_read_tokens=cache_read_tokens,
        request_id=request_id or None,
        end_status=end_status,
    ))

    if req_id is not None:
        _respond(req_id, result={"ok": True})
    return end_status, request_tool_ms


async def run_chat_request(
    state: ServeState,
    req_id: int | None,
    params: dict,
    *,
    request_id: str = "",
) -> tuple[str, int]:
    try:
        return await handle_chat(state, req_id, params, request_id=request_id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        _notify("error", error_params(str(exc), request_id=request_id or None))
        if req_id is not None:
            _respond(req_id, error=str(exc))
        _notify("done", done_params(
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            request_id=request_id or None,
            end_status="error",
        ))
        return "error", 0


class RequestLifecycle:
    """Tracks request queue/runtime timings and final accounting."""

    def __init__(self, state: ServeState, request_id: str):
        self.state = state
        self.request_id = request_id
        self.loop = asyncio.get_running_loop()
        self.lifecycle_started = self.loop.time()
        self.queued_started = self.lifecycle_started
        self.model_started = self.lifecycle_started
        self.queued_ms = 0
        self.model_ms = 0
        self.tool_ms = 0
        self.end_status = "error"
        self.routing: list[dict[str, object]] | None = None
        self._reserved = False
        self._entered = False

    async def reserve(self) -> tuple[bool, str]:
        self.state.request_count += 1
        self.state.last_request_id = self.request_id
        self._reserved, rejection = await self.state.reserve_model_budget()
        if not self._reserved:
            self.end_status = "rejected"
            return False, rejection
        return True, ""

    async def acquire(self) -> bool:
        acquired = await self.state.acquire_model_budget(request_id=self.request_id)
        if not acquired:
            self.end_status = "cancelled"
            return False
        self._entered = True
        self.queued_ms = int((self.loop.time() - self.queued_started) * 1000)
        self.model_started = self.loop.time()
        return True

    def complete_run(self, end_status: str, tool_ms: int) -> None:
        self.end_status = end_status
        self.tool_ms = max(0, int(tool_ms))
        running_ms = int((self.loop.time() - self.model_started) * 1000)
        self.model_ms = max(0, running_ms - self.tool_ms)

    async def finalize(self) -> None:
        if self._reserved:
            if self._entered:
                await self.state.release_model_budget()
            else:
                await self.state.rollback_model_budget()
        total_ms = int((self.loop.time() - self.lifecycle_started) * 1000)
        if self.end_status == "success":
            self.state.request_success_count += 1
        elif self.end_status == "cancelled":
            self.state.request_cancel_count += 1
        elif self.end_status == "rejected":
            self.state.request_reject_count += 1
        else:
            self.state.request_error_count += 1
        self.state.record_request_metrics(
            end_status=self.end_status,
            queued_ms=self.queued_ms,
            model_ms=self.model_ms,
            tool_ms=self.tool_ms,
            total_ms=total_ms,
        )
        if self.routing is None:
            self.routing = self.state.request_routing_decisions.get(self.request_id)
        _emit_request_telemetry(
            self.state,
            request_id=self.request_id,
            end_status=self.end_status,
            queued_ms=self.queued_ms,
            model_ms=self.model_ms,
            tool_ms=self.tool_ms,
            total_ms=total_ms,
            routing=self.routing,
        )
        self.state.clear_request_runtime_refs(self.request_id)
        _persist_state(self.state)


async def run_budgeted_chat_request(
    state: ServeState,
    params: dict,
    *,
    request_id: str,
    req_id: int | None = None,
) -> None:
    """Run a chat request under global execution budget limits."""
    lifecycle = RequestLifecycle(state, request_id)
    reserved, rejection = await lifecycle.reserve()
    if not reserved:
        if req_id is not None:
            _respond(req_id, error=f"[{request_id}] {rejection}")
        else:
            _notify("error", error_params(rejection, request_id=request_id))
        await lifecycle.finalize()
        return

    try:
        acquired = await lifecycle.acquire()
        if not acquired:
            _notify("done", done_params(
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                request_id=request_id or None,
                end_status=lifecycle.end_status,
            ))
            return
        end_status, tool_ms = await run_chat_request(state, req_id, params, request_id=request_id)
        lifecycle.complete_run(end_status, tool_ms)
    finally:
        await lifecycle.finalize()


async def handle_command(state: ServeState, req_id: int, params: dict) -> None:
    """Handle slash commands from the frontend."""
    cmd = str(params.get("cmd", ""))
    args = params.get("args", [])
    args = args if isinstance(args, list) else []

    if cmd == "tool/approve":
        state.tool_approved = True
        state.tool_decision_scope = "once"
        if state.tool_decision:
            state.tool_decision.set()
        _respond(req_id, result={"approved": True})
        return

    if cmd == "tool/deny":
        state.tool_approved = False
        state.tool_decision_scope = "once"
        if state.tool_decision:
            state.tool_decision.set()
        _respond(req_id, result={"approved": False})
        return

    if cmd == "tool/decision":
        choice = str(args[0]) if args else ""
        if choice not in {"allow-once", "allow-session", "deny-once", "deny-session"}:
            _respond(req_id, error="Usage: tool/decision <allow-once|allow-session|deny-once|deny-session>")
            return
        state.tool_approved = choice.startswith("allow")
        state.tool_decision_scope = "session" if choice.endswith("session") else "once"
        if state.tool_decision:
            state.tool_decision.set()
        _respond(req_id, result={"approved": state.tool_approved, "scope": state.tool_decision_scope})
        return

    if cmd == "tool/review":
        if len(args) < 2:
            _respond(req_id, error="Usage: tool/review <review-id> <accept|reject>")
            return
        review_id = str(args[0])
        action = str(args[1]).lower()
        if action not in {"accept", "reject"}:
            _respond(req_id, error="Usage: tool/review <review-id> <accept|reject>")
            return
        if not state.tool_review_decision or review_id != state.pending_review_id:
            _respond(req_id, error="No matching pending tool review")
            return
        state.tool_review_action = action
        state.tool_review_decision.set()
        _respond(req_id, result={"accepted": action == "accept"})
        return

    if cmd == "/status":
        _respond(req_id, result=build_ready_params(state))
        return

    if cmd == "/backend":
        if not args:
            _respond(req_id, result={"backend": state.backend_name, "model": active_model_name(state)})
            return
        backend_name = str(args[0]).lower()
        if backend_name not in VALID_BACKENDS:
            _respond(req_id, error="Usage: /backend <studio|llamacpp>")
            return
        old_backend = state.backend_name
        set_backend(state, backend_name)
        if old_backend != state.backend_name:
            state.backend_restart_count += 1
            state.session.append_backend_switch(old_backend, state.backend_name)
        _persist_state(state)
        if backend_name == "studio" and state.auto_start_server:
            ensure_server(state.host, state.port)
        _notify("ready", build_ready_params(state))
        _respond(req_id, result={"backend": state.backend_name, "active_model": active_model_name(state)})
        return

    if cmd == "/backends":
        _respond(req_id, result={
            "active": state.backend_name,
            "available": ["studio", "llamacpp"],
            "studio_api_base": state.studio_api_base,
            "llamacpp_api_base": state.llamacpp_api_base,
            "llamacpp_model": state.llamacpp_model,
        })
        return

    if cmd == "/lsp-context":
        if not args:
            label = lsp_context_status_label(state.lsp_context_mode, state.models.get(state.active_model))
            _respond(req_id, result={"mode": state.lsp_context_mode, "resolved": label})
            return
        raw_mode = str(args[0]).strip().lower()
        if raw_mode not in LSP_CONTEXT_MODES:
            _respond(req_id, error="Usage: /lsp-context <auto|off|minimal|balanced|rich>")
            return
        state.lsp_context_mode = normalize_lsp_context_mode(raw_mode)
        await _refresh_focus_context(state)
        _persist_state(
            state,
            {
                "lsp_context_mode": state.lsp_context_mode,
                "focus_path": str(state.focus_path) if state.focus_path else "",
            },
        )
        _notify("ready", build_ready_params(state))
        _respond(
            req_id,
            result={
                "mode": state.lsp_context_mode,
                "resolved": lsp_context_status_label(state.lsp_context_mode, state.models.get(state.active_model)),
            },
        )
        return

    if cmd == "/backend-status":
        backend = get_backend(state)
        status = await backend.check_connection()
        loaded = await backend.list_loaded_model_details()
        _respond(req_id, result={
            "backend": status.name,
            "connected": status.connected,
            "detail": status.detail,
            "loaded": [str(item.get("identifier", "")) for item in loaded if item.get("identifier")],
            "loaded_models": loaded,
            "loaded_model_count": len(loaded),
            "loaded_model_memory_bytes": total_loaded_model_bytes(loaded),
        })
        return

    if cmd == "/model":
        if state.backend_name != "studio":
            _respond(req_id, error=f"llama.cpp is pinned to {state.llamacpp_model}; switch to /backend studio first")
            return
        if not args:
            _respond(req_id, error="Usage: /model <name>")
            return
        old_model = state.active_model
        try:
            next_model, alias = resolve_existing_model_name(str(args[0]), state.models)
        except RuntimeError as exc:
            state.model_lookup_failures += 1
            _respond(req_id, error=str(exc))
            return
        if alias:
            state.model_alias_resolutions += 1
        if not is_z3ui_model_entry(state.models.get(next_model)):
            _respond(req_id, error=_z3ui_model_policy_error(state, next_model))
            return
        ensure_model_available(state.models.get(next_model))
        state.active_model = next_model
        await _refresh_focus_context(state)
        state.session.append_model_switch(old_model, state.active_model, reason="user command")
        _persist_state(state, model_name=state.active_model)
        _notify("ready", build_ready_params(state))
        result = {"active_model": state.active_model}
        if alias:
            result["warning"] = f"Legacy alias '{alias}' now resolves to '{state.active_model}'."
        _respond(req_id, result=result)
        return

    if cmd == "/specialist":
        if state.backend_name != "studio":
            _respond(req_id, error=f"llama.cpp is pinned to {state.llamacpp_model}; switch to /backend studio first")
            return
        if not args or str(args[0]).strip().lower() not in SPECIALIST_NAMES:
            _respond(req_id, error=f"Usage: /specialist <{'|'.join(SPECIALIST_NAMES)}>")
            return
        old_model = state.active_model
        next_model = str(args[0]).strip().lower()
        ensure_model_available(state.models.get(next_model))
        state.active_model = next_model
        state.mode = "manual"
        await _refresh_focus_context(state)
        state.session.append_model_switch(old_model, state.active_model, reason="user command")
        _persist_state(state, {"mode": state.mode}, model_name=state.active_model)
        _notify("ready", build_ready_params(state))
        _respond(req_id, result={"active_model": state.active_model, "mode": state.mode})
        return

    if cmd == "/mode":
        if not args:
            _respond(req_id, error=f"Usage: /mode {mode_usage_text()}")
            return
        mode, alias = normalize_mode(str(args[0]))
        if mode not in VALID_MODES:
            _respond(req_id, error=f"Usage: /mode {mode_usage_text()}")
            return
        previous_mode = state.mode
        state.mode = mode
        _persist_state(state, {"mode": state.mode})
        # Refresh the bridge if orchestrator affects tool exposure
        if (previous_mode == ORCHESTRATOR_MODE) != (mode == ORCHESTRATOR_MODE):
            await _refresh_tool_bridge_immediately(state)
        _notify("ready", build_ready_params(state))
        result = {"mode": state.mode}
        if alias:
            result["warning"] = f"Legacy mode '{alias}' now resolves to '{state.mode}'."
        _respond(req_id, result=result)
        return

    if cmd == "/route":
        prompt = " ".join(str(arg) for arg in args)
        targets, decisions = resolve_targets_with_reason(
            models=state.models,
            routers=state.routers,
            active_model=state.active_model,
            mode=state.mode,
            prompt=prompt,
            broadcast_models=state.broadcast_models,
            backend_name=state.backend_name,
            llamacpp_model=state.llamacpp_model,
            temperature=0.2,
            max_tokens=1024,
            orchestrator_model=state.orchestrator_model,
        )
        ensure_targets_available(targets)
        _respond(
            req_id,
            result={
                "targets": [target.name for target in targets],
                "routing": [decision.to_dict() for decision in decisions],
            },
        )
        return

    if cmd == "/broadcast":
        if not args:
            _respond(req_id, error="Usage: /broadcast <alias1,alias2,...>")
            return
        state.broadcast_models = [value.strip() for value in str(args[0]).split(",") if value.strip()]
        _persist_state(state, {"broadcast_models": state.broadcast_models})
        _notify("ready", build_ready_params(state))
        _respond(req_id, result={"broadcast_models": state.broadcast_models})
        return

    if cmd == "/servers":
        _respond(req_id, result={
            "servers": state.bridge.server_names if state.bridge else [],
            "tool_count": state.bridge.tool_count if state.bridge else 0,
            "warnings": state.bridge_errors,
        })
        return

    if cmd == "/loaded":
        loaded = await get_backend(state).list_loaded_model_details()
        _respond(req_id, result={
            "loaded": [str(item.get("identifier", "")) for item in loaded if item.get("identifier")],
            "loaded_models": loaded,
            "loaded_model_count": len(loaded),
            "loaded_model_memory_bytes": total_loaded_model_bytes(loaded),
        })
        return

    if cmd == "/unload":
        if state.backend_name != "studio":
            _respond(req_id, error="/unload is only available on the studio backend.")
            return
        target_name = str(args[0]).strip() if args else state.active_model
        unload_all = target_name.lower() == "all"
        alias = ""
        if not unload_all and target_name:
            try:
                resolved_name, alias = resolve_existing_model_name(target_name, state.models)
                target_cfg = state.models.get(resolved_name)
                if target_cfg is not None and target_cfg.is_cloud:
                    _respond(req_id, error="/unload only applies to LM Studio models.")
                    return
                target_name = resolved_name
            except RuntimeError:
                pass
        try:
            unload_result = await get_backend(state).unload_model(target_name, all_models=unload_all)
        except RuntimeError as exc:
            _respond(req_id, error=str(exc))
            return
        _notify("ready", build_ready_params(state))
        result = {
            "all": bool(unload_result.get("all")),
            "unloaded": unload_result.get("unloaded", []),
            "target": target_name,
        }
        if alias:
            result["warning"] = f"Legacy alias '{alias}' now resolves to '{target_name}'."
        _respond(req_id, result=result)
        return

    if cmd == "/reset":
        target = str(args[0]) if args else active_model_name(state)
        if target == "all":
            for engine in state.engines.values():
                engine.reset()
        else:
            engine = state.engines.get(engine_key(state.backend_name, target))
            if engine:
                engine.reset()
        _respond(req_id, result={"ok": True})
        return

    if cmd == "/tools":
        if not args or str(args[0]).lower() not in {"on", "off"}:
            _respond(req_id, error="Usage: /tools <on|off>")
            return
        state.tools_enabled = str(args[0]).lower() == "on"
        _persist_state(state, {"tools_enabled": state.tools_enabled})
        await _refresh_tool_bridge_immediately(state)
        _notify("ready", build_ready_params(state))
        _respond(req_id, result={"tools_enabled": state.tools_enabled})
        return

    if cmd == "/tools-write":
        if not args or str(args[0]).lower() not in {"on", "off"}:
            _respond(req_id, error="Usage: /tools-write <on|off>")
            return
        state.tools_write = str(args[0]).lower() == "on"
        _persist_state(state, {"tools_write": state.tools_write})
        _notify("ready", build_ready_params(state))
        _respond(req_id, result={"tools_write": state.tools_write})
        return

    if cmd == "/verify-hooks":
        if not args or str(args[0]).lower() not in {"on", "off"}:
            _respond(req_id, error="Usage: /verify-hooks <on|off>")
            return
        state.verify_hooks = str(args[0]).lower() == "on"
        _persist_state(state, {"verify_hooks": state.verify_hooks})
        _notify("ready", build_ready_params(state))
        _respond(req_id, result={"verify_hooks": state.verify_hooks})
        return

    if cmd == "/shell":
        if not args:
            _respond(req_id, result={
                "active": bool(state.shell and state.shell.active),
                "cwd": str(state.shell.cwd if state.shell else state.workspace),
                "entries": len(state.shell.scrollback) if state.shell else 0,
            })
            return
        command = " ".join(str(arg) for arg in args).strip()
        if not command:
            _respond(req_id, error="Usage: /shell <command>")
            return
        shell = await ensure_shell(state)
        try:
            shell_result = await shell.run(command)
        except Exception as exc:
            _respond(req_id, error=f"Shell command failed: {exc}")
            return
        _notify("ready", build_ready_params(state))
        _respond(req_id, result={
            "command": shell_result.command,
            "cwd": shell_result.cwd,
            "exit_code": shell_result.exit_code,
            "output": shell_result.output,
            "duration_ms": shell_result.duration_ms,
        })
        return

    if cmd == "/shell-reset":
        if state.shell is not None:
            await state.shell.close()
            state.shell = None
        _notify("ready", build_ready_params(state))
        _respond(req_id, result={"reset": True})
        return

    if cmd == "/shell-log":
        limit = int(args[0]) if args and str(args[0]).isdigit() else 10
        entries = [
            {
                "command": item.command,
                "cwd": item.cwd,
                "exit_code": item.exit_code,
                "output": item.output,
                "duration_ms": item.duration_ms,
            }
            for item in (state.shell.scrollback[-limit:] if state.shell else [])
        ]
        _respond(req_id, result={"entries": entries})
        return

    if cmd == "/workspace":
        if not args:
            _respond(req_id, error="Usage: /workspace <path>")
            return
        state.workspace = Path(str(args[0])).expanduser().resolve()
        _persist_state(state, {"workspace": str(state.workspace)})
        await _refresh_tool_bridge_immediately(state)
        if state.shell is not None and state.shell.active:
            try:
                await state.shell.chdir(state.workspace)
            except Exception:
                pass
        _notify("ready", build_ready_params(state))
        _respond(req_id, result={"workspace": str(state.workspace)})
        return

    if cmd == "/rom":
        if not args:
            _respond(req_id, error="Usage: /rom <path|none>")
            return
        if str(args[0]).lower() == "none":
            state.rom_path = None
        else:
            state.rom_path = Path(str(args[0])).expanduser().resolve()
        _persist_state(state, {"rom_path": str(state.rom_path) if state.rom_path else ""})
        await _refresh_tool_bridge_immediately(state)
        _notify("ready", build_ready_params(state))
        _respond(req_id, result={"rom_path": str(state.rom_path) if state.rom_path else ""})
        return

    if cmd == "/focus":
        if not args:
            if state.focus_context:
                lines = state.focus_context.count("\n") + 1
                chars = len(state.focus_context)
                _respond(req_id, result={"active": True, "lines": lines, "chars": chars})
            else:
                _respond(req_id, result={"active": False})
            return
        arg = str(args[0])
        if arg.lower() == "clear":
            _clear_focus_context(state)
            _persist_state(state, {"focus_path": ""})
            _notify("ready", build_ready_params(state))
            _respond(req_id, result={"cleared": True})
            return
        try:
            focus_path, content = await load_enriched_focus_file(
                state.workspace,
                arg,
                bridge=state.bridge,
                model=state.models.get(state.active_model),
                lsp_context_mode=state.lsp_context_mode,
            )
        except FileNotFoundError:
            _respond(req_id, error=f"File not found: {arg}")
            return
        except Exception as e:
            _respond(req_id, error=f"Error reading {arg}: {e}")
            return
        lines, chars = _set_focus_context(state, focus_path, content)
        _persist_state(state, {"focus_path": str(focus_path)})
        _notify("ready", build_ready_params(state))
        _respond(req_id, result={
            "loaded": focus_path.name,
            "lines": lines,
            "chars": chars,
            "path": str(focus_path),
        })
        return

    if cmd == "/permissions":
        if args and str(args[0]).lower() == "clear":
            state.permission_rules.clear()
            _persist_state(state, {"permission_rules": {}})
            _notify("ready", build_ready_params(state))
            _respond(req_id, result={"cleared": True})
            return
        allow = sorted(key for key, value in state.permission_rules.items() if value)
        deny = sorted(key for key, value in state.permission_rules.items() if not value)
        _respond(req_id, result={"allow": allow, "deny": deny})
        return

    if cmd == "/load":
        if state.backend_name != "studio":
            _respond(req_id, error="/load is only available on the studio backend")
            return
        target_name = str(args[0]) if args else state.active_model
        if args:
            try:
                target_name, _alias = resolve_existing_model_name(target_name, state.models)
            except RuntimeError as exc:
                state.model_lookup_failures += 1
                _respond(req_id, error=str(exc))
                return
            if _alias:
                state.model_alias_resolutions += 1
        else:
            if target_name not in state.models:
                _respond(req_id, error=f"Unknown model: {target_name}")
                return
        target = state.models[target_name]
        try:
            get_backend(state).resolve_request_model(target, auto_load=True, manual_load=True)
        except RuntimeError as exc:
            _respond(req_id, error=str(exc))
            return
        _notify("ready", build_ready_params(state))
        _respond(req_id, result={"loaded": target_name})
        return

    if cmd == "/stats":
        user_msgs = sum(
            1 for engine in state.engines.values()
            for msg in engine.messages if msg.get("role") == "user"
        )
        tool_calls = sum(
            1 for engine in state.engines.values()
            for msg in engine.messages if msg.get("role") == "tool"
        )
        models_used = sorted(state.engines.keys())
        avg_tool_latency_ms = (
            int(state.tool_latency_ms_total / state.tool_latency_samples)
            if state.tool_latency_samples > 0 else 0
        )
        latency = state.request_latency_snapshot()
        _respond(req_id, result={
            "prompt_tokens": state.prompt_tokens,
            "completion_tokens": state.completion_tokens,
            "total_tokens": state.prompt_tokens + state.completion_tokens,
            "messages": user_msgs,
            "tool_calls": tool_calls,
            "engines": len(state.engines),
            "models_used": models_used,
            "session": str(state.session.path.name) if state.session.path else "",
            "cancel_count": state.cancel_count,
            "backend_restart_count": state.backend_restart_count,
            "tool_latency_ms": avg_tool_latency_ms,
            "tool_latency_samples": state.tool_latency_samples,
            "review_wait_ms": state.review_wait_ms,
            "permission_wait_ms": state.permission_wait_ms,
            "permission_timeout_count": state.permission_timeout_count,
            "review_timeout_count": state.review_timeout_count,
            "model_retry_count": state.model_retry_count,
            "model_retry_backoff_ms": state.model_retry_backoff_ms,
            "model_error_count": state.model_error_count,
            "tool_timeout_count": state.tool_timeout_count,
            "model_alias_resolutions": state.model_alias_resolutions,
            "model_lookup_failures": state.model_lookup_failures,
            "model_request_counts": dict(state.model_request_counts),
            "model_backpressure_count": state.model_backpressure_count,
            "tool_backpressure_count": state.tool_backpressure_count,
            "model_queue_highwater": state.model_queue_highwater,
            "tool_queue_highwater": state.tool_queue_highwater,
            "model_inflight_highwater": state.model_inflight_highwater,
            "tool_inflight_highwater": state.tool_inflight_highwater,
            "inflight_model_calls": state.inflight_model_calls,
            "queued_model_calls": state.queued_model_calls,
            "inflight_tool_calls": state.inflight_tool_calls,
            "queued_tool_calls": state.queued_tool_calls,
            "model_retry_max": state.model_retry_max,
            "model_retry_base_ms": int(state.model_retry_backoff_base_s * 1000),
            "tool_exec_timeout_s": state.tool_exec_timeout_s,
            "max_inflight_model_calls": state.max_inflight_model_calls,
            "max_inflight_tools": state.max_inflight_tools,
            "exec_queue_depth": state.exec_queue_depth,
            "request_count": state.request_count,
            "request_success_count": state.request_success_count,
            "request_error_count": state.request_error_count,
            "request_reject_count": state.request_reject_count,
            "request_cancel_count": state.request_cancel_count,
            "span_count": state.span_count,
            "last_request_id": state.last_request_id,
            "last_span_id": state.last_span_id,
            "last_tool_call_id": state.last_tool_call_id,
            "request_samples": int(latency["request_samples"]),
            "queued_ms_p50": int(latency["queued_ms_p50"]),
            "queued_ms_p95": int(latency["queued_ms_p95"]),
            "model_ms_p50": int(latency["model_ms_p50"]),
            "model_ms_p95": int(latency["model_ms_p95"]),
            "tool_ms_p50": int(latency["tool_ms_p50"]),
            "tool_ms_p95": int(latency["tool_ms_p95"]),
            "total_ms_p50": int(latency["total_ms_p50"]),
            "total_ms_p95": int(latency["total_ms_p95"]),
            "last_request_status": str(latency["last_request_status"]),
            "last_request_queued_ms": int(latency["last_request_queued_ms"]),
            "last_request_model_ms": int(latency["last_request_model_ms"]),
            "last_request_tool_ms": int(latency["last_request_tool_ms"]),
            "last_request_total_ms": int(latency["last_request_total_ms"]),
        })
        return

    if cmd == "/save":
        _respond(req_id, result={
            "path": str(state.session.path) if state.session.path else "",
            "messages": state.session.message_count,
        })
        return

    if cmd == "/sessions":
        sessions = list_sessions()
        _respond(req_id, result={"sessions": sessions})
        return

    if cmd == "/resume":
        filtered_args = [str(arg) for arg in args if str(arg).strip()]
        strip_thinking = "--strip-thinking" in filtered_args
        positional = [arg for arg in filtered_args if arg != "--strip-thinking"]
        if not positional:
            sessions = list_sessions()
            _respond(req_id, result={"sessions": sessions})
            return
        name = positional[0]
        try:
            match = find_session(name)
            loader = load_session_bundle_without_thinking if strip_thinking else load_session_bundle
            loaded = loader(Path(match["path"]))
        except Exception as exc:
            _respond(req_id, error=f"Failed to load session: {exc}")
            return
        restore_warnings = _restore_runtime_state(state, loaded.meta)
        z3ui_model_warning = _coerce_z3ui_active_model(state, str(loaded.meta.get("active_model") or state.active_model))
        if z3ui_model_warning:
            restore_warnings.append(z3ui_model_warning)
        await _refresh_tool_bridge_immediately(state)
        restored_count = 0
        for engine in state.engines.values():
            engine.reset()
        for model_name, msgs in loaded.model_messages.items():
            engine = state.get_engine(model_name)
            engine.messages = list(msgs)
            restored_count += len(msgs)
        state.turn_index = sum(1 for msg in loaded.transcript if msg.get("role") == "user")
        state.message_index = len(loaded.transcript)
        state.session.resume(Path(match["path"]), loaded.message_count)
        _notify("ready", build_ready_params(state))
        _respond(req_id, result={
            "resumed": match["name"],
            "models": list(loaded.model_messages.keys()),
            "messages_restored": restored_count,
            "messages": loaded.transcript,
            "subagents": loaded.subagents,
            "warnings": restore_warnings,
            "thinking_stripped": strip_thinking,
        })
        return

    if cmd == "/export-training":
        if not state.session.path:
            _respond(req_id, error="No active session to export")
            return
        filtered_args = [str(arg) for arg in args if str(arg).strip()]
        include_thinking = "--include-thinking" in filtered_args
        positional = [arg for arg in filtered_args if arg != "--include-thinking"]
        out_path = Path(positional[0]) if positional else state.session.path.with_suffix(".training.jsonl")
        model_filter = positional[1] if len(positional) > 1 else None
        count = export_training(
            state.session.path,
            out_path,
            model_filter,
            include_thinking=include_thinking,
        )
        _respond(req_id, result={
            "path": str(out_path),
            "samples": count,
            "include_thinking": include_thinking,
        })
        return

    if cmd == "/compact":
        # Usage: /compact [model-name]  — defaults to active model
        model_name = str(args[0]).strip() if args else state.active_model
        model_cfg = state.models.get(model_name)
        if model_cfg is None:
            _respond(req_id, error=f"Unknown model: {model_name}")
            return
        engine = state.get_engine(model_name)
        if engine.compactor is None:
            _respond(req_id, error=(
                f"No compactor configured for '{model_name}'. "
                "Set context_budget in chat_registry.toml to enable."
            ))
            return
        compaction_event = await compact_session_history(state, model_name)
        if compaction_event is None:
            _respond(req_id, result={"compacted": False, "reason": "no messages to compact"})
            return
        _notify("context/compacted", context_compacted_params(
            summary=compaction_event.summary,
            replaced=compaction_event.replaced_count,
            tokens_before=compaction_event.tokens_before,
            tokens_after=compaction_event.tokens_after,
            model=model_name,
        ))
        _respond(req_id, result={
            "compacted": True,
            "model": model_name,
            "replaced": compaction_event.replaced_count,
            "tokens_before": compaction_event.tokens_before,
            "tokens_after": compaction_event.tokens_after,
        })
        return

    if cmd == "/orchestrator":
        if not args:
            resolved, auto_selected, routing = _orchestrator_routing_payload(state)
            _respond(req_id, result={
                "orchestrator": state.orchestrator_model,
                "resolved": resolved,
                "auto_selected": auto_selected,
                "routing": routing,
            })
            return
        choice = str(args[0]).strip()
        if choice in {"auto", "-", ""}:
            state.orchestrator_model = ""
            warning = ""
        else:
            try:
                resolved_choice, alias = resolve_existing_model_name(choice, state.models)
            except RuntimeError:
                state.model_lookup_failures += 1
                _respond(req_id, error=f"Unknown model: {choice}")
                return
            if alias:
                state.model_alias_resolutions += 1
            cfg = state.models[resolved_choice]
            if cfg.is_cloud and not cfg.resolve_api_key():
                _respond(req_id, error=f"Cloud model '{resolved_choice}' has no API key configured")
                return
            state.orchestrator_model = resolved_choice
            warning = f"Legacy alias '{alias}' now resolves to '{state.orchestrator_model}'." if alias else ""

        resolved, auto_selected, routing = _orchestrator_routing_payload(state)
        _persist_state(state, {"orchestrator_model": state.orchestrator_model})
        _notify("ready", build_ready_params(state))
        _respond(req_id, result={
            "orchestrator": state.orchestrator_model,
            "resolved": resolved,
            "auto_selected": auto_selected,
            "routing": routing,
            "warning": warning,
        })
        return

    if cmd == "/subagent-tools":
        if not args:
            _respond(req_id, result={"enabled": state.subagent_tools_enabled})
            return
        choice = str(args[0]).lower()
        if choice not in {"on", "off"}:
            _respond(req_id, error="Usage: /subagent-tools <on|off>")
            return
        state.subagent_tools_enabled = choice == "on"
        await _refresh_tool_bridge_immediately(state)
        _respond(req_id, result={"enabled": state.subagent_tools_enabled})
        return

    if cmd == "/subagent":
        if len(args) < 2:
            _respond(req_id, error="Usage: /subagent <model-name> <prompt> [--profile <name>] [--rounds N]")
            return
        model_name = str(args[0])
        # Collect the prompt from remaining args, stripping out any flags
        prompt_parts: list[str] = []
        tool_profile_override = ""
        max_rounds = 4
        i = 1
        while i < len(args):
            arg = str(args[i])
            if arg == "--profile" and i + 1 < len(args):
                tool_profile_override = str(args[i + 1])
                i += 2
                continue
            if arg == "--rounds" and i + 1 < len(args):
                try:
                    max_rounds = max(1, int(args[i + 1]))
                except (TypeError, ValueError):
                    pass
                i += 2
                continue
            prompt_parts.append(arg)
            i += 1
        prompt = " ".join(prompt_parts).strip()
        if not prompt:
            _respond(req_id, error="Subagent prompt is empty")
            return

        model_cfg = state.models.get(model_name)
        if model_cfg is None:
            _respond(req_id, error=f"Unknown model: {model_name}")
            return

        config = SubagentConfig(
            name=model_name,
            model=model_cfg,
            tool_profile=tool_profile_override or model_cfg.tool_profile,
            max_rounds=max_rounds,
            max_tokens=model_cfg.max_tokens,
            temperature=model_cfg.temperature,
            thinking=bool(model_cfg.thinking_tier),
        )
        try:
            raw_prompt = prompt
            prompt = await _enrich_prompt_with_workspace_context(state, prompt, model=model_cfg)
            system_context = await state.subagent_runner.resolve_system_context(model_cfg, raw_prompt)
            result = await state.subagent_runner.spawn(
                config,
                prompt,
                system_context=system_context,
                on_event=state._subagent_event_hook,
            )
        except Exception as exc:
            _respond(req_id, error=f"Subagent failed: {exc}")
            return

        _respond(req_id, result={
            "id": result.id,
            "name": result.name,
            "model": result.model_name,
            "text": result.text,
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "tool_calls": result.tool_calls,
            "error": result.error or None,
        })
        return

    _respond(req_id, error=f"Unknown command: {cmd}")


async def serve_main(extra_args: list[str]) -> None:
    """Main loop: read JSON-RPC from stdin, dispatch, write to stdout."""
    # Redirect logging to stderr so stdout is clean JSON
    import logging
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    for stream in (sys.stdout, sys.stderr):
        try:
            os.set_blocking(stream.fileno(), True)
        except (AttributeError, OSError, ValueError):
            pass

    defer_startup_tool_bridge = str(
        os.environ.get("Z3CLI_DEFER_STARTUP_TOOL_BRIDGE", "1"),
    ).strip().lower() not in {"0", "false", "off", "no"}
    state = await init_state(extra_args, defer_tool_bridge=defer_startup_tool_bridge)
    _notify("ready", build_ready_params(state))
    if state.startup_tool_bridge_warming and state.tools_enabled:
        state.startup_tool_bridge_task = asyncio.create_task(
            _run_startup_tool_bridge_warmup(state),
            name="serve:startup-tool-bridge",
        )

    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    active_chats: set[asyncio.Task[None]] = set()
    chat_tasks_by_request: dict[str, asyncio.Task[None]] = {}

    def _track_chat(request_id: str, task: asyncio.Task[None]) -> None:
        active_chats.add(task)
        chat_tasks_by_request[request_id] = task

        def _on_done(done: asyncio.Task[None]) -> None:
            active_chats.discard(done)
            current = chat_tasks_by_request.get(request_id)
            if current is done:
                chat_tasks_by_request.pop(request_id, None)

        task.add_done_callback(_on_done)

    while True:
        line_bytes = await reader.readline()
        if not line_bytes:
            break  # EOF — frontend closed
        line = line_bytes.decode("utf-8").strip()
        if not line:
            continue

        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = msg.get("method", "")
        req_id = msg.get("id")
        params = msg.get("params", {})

        if method == "shutdown":
            if active_chats:
                state.cancel_requested = True
                state.cancel_pending_prompts()
                for request_id in list(chat_tasks_by_request.keys()):
                    state.mark_request_cancelled(request_id)
                for task in list(active_chats):
                    task.cancel()
            break
        elif method == "cancel":
            cancel_request_id = ""
            if isinstance(params, dict):
                requested = params.get("request_id")
                if isinstance(requested, str) and requested.strip():
                    cancel_request_id = requested.strip()
            if not cancel_request_id:
                for request_id in reversed(list(chat_tasks_by_request.keys())):
                    task = chat_tasks_by_request.get(request_id)
                    if task is not None and not task.done():
                        cancel_request_id = request_id
                        break
            if not cancel_request_id:
                continue
            state.cancel_count += 1
            state.mark_request_cancelled(cancel_request_id)
            if cancel_request_id not in chat_tasks_by_request:
                state.clear_request_runtime_refs(cancel_request_id)
            _persist_state(state)
            continue
        elif method == "chat":
            state.cancel_requested = False
            request_id = _next_request_id(state)
            state.clear_request_cancelled(request_id)
            if req_id is not None:
                _respond(req_id, result={"accepted": True, "request_id": request_id})
            chat_task = asyncio.create_task(
                run_budgeted_chat_request(
                    state,
                    params,
                    request_id=request_id,
                ),
            )
            _track_chat(request_id, chat_task)
        elif method == "command" and req_id is not None:
            try:
                await handle_command(state, req_id, params)
            except Exception as exc:
                _respond(req_id, error=str(exc))
        elif method == "status" and req_id is not None:
            _respond(req_id, result=build_ready_params(state))
        elif method == "models" and req_id is not None:
            _respond(req_id, result=build_ready_params(state)["models"])
        elif req_id is not None:
            _respond(req_id, error=f"Unknown method: {method}")

    # Wait for active chats to finish
    if active_chats:
        state.cancel_requested = True
        state.cancel_pending_prompts()
        for request_id in list(chat_tasks_by_request.keys()):
            state.mark_request_cancelled(request_id)
        pending = list(active_chats)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    await _cancel_startup_tool_bridge_warmup(state)

    # Cleanup
    state.session.close()
    for engine in state.engines.values():
        await engine.close()
    if state.bridge:
        await state.bridge.close()
    if state.shell:
        await state.shell.close()
