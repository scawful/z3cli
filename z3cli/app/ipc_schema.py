"""Typed JSON-RPC payload builders for the Ink frontend bridge."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, NotRequired, TypedDict, Union, get_args, get_origin, get_type_hints, is_typeddict


MessageRole = Literal["user", "assistant", "system", "tool"]


class JsonRpcError(TypedDict):
    code: int
    message: str


class JsonRpcRequest(TypedDict):
    jsonrpc: Literal["2.0"]
    id: int
    method: str
    params: NotRequired[dict[str, Any]]


class JsonRpcNotification(TypedDict):
    jsonrpc: Literal["2.0"]
    method: str
    params: NotRequired[dict[str, Any]]


class JsonRpcResponse(TypedDict):
    jsonrpc: Literal["2.0"]
    id: int
    result: NotRequired[Any]
    error: NotRequired[JsonRpcError]


class AttachmentMeta(TypedDict):
    path: str
    lines: int
    chars: int


class AttachmentReference(TypedDict):
    path: str


class ConstructRef(TypedDict):
    kind: str
    query: str
    token: NotRequired[str]
    id: NotRequired[str]
    label: NotRequired[str]


class ChatRequestParams(TypedDict):
    message: str
    model: NotRequired[str]
    attachments: NotRequired[list[AttachmentMeta]]
    construct_refs: NotRequired[list[ConstructRef]]


class CommandRequestParams(TypedDict):
    cmd: str
    args: list[str]


class TextParams(TypedDict):
    delta: str
    request_id: NotRequired[str]
    span_id: NotRequired[str]


class ToolCallParams(TypedDict):
    name: str
    server: str
    arguments: str
    call_id: NotRequired[str]
    tool_group: NotRequired[str]
    request_id: NotRequired[str]
    span_id: NotRequired[str]


class ToolResultParams(TypedDict):
    name: str
    result: str
    server: NotRequired[str]
    call_id: NotRequired[str]
    tool_group: NotRequired[str]
    request_id: NotRequired[str]
    span_id: NotRequired[str]


class ThinkingParams(TypedDict):
    delta: str
    request_id: NotRequired[str]
    span_id: NotRequired[str]


class ErrorParams(TypedDict):
    message: str
    request_id: NotRequired[str]
    span_id: NotRequired[str]


class MessageParams(TypedDict):
    id: str
    role: MessageRole
    content: str
    timestamp: int
    thinking: NotRequired[str | None]
    turn_id: NotRequired[str | None]
    model: NotRequired[str | None]
    tool_name: NotRequired[str | None]
    tool_server: NotRequired[str | None]
    tool_arguments: NotRequired[str | None]
    tool_group: NotRequired[str | None]
    attachments: NotRequired[list[AttachmentMeta] | None]
    construct_refs: NotRequired[list[ConstructRef] | None]
    request_id: NotRequired[str | None]
    span_id: NotRequired[str | None]


class DoneParams(TypedDict):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cache_creation_tokens: NotRequired[int]
    cache_read_tokens: NotRequired[int]
    request_id: NotRequired[str]
    end_status: NotRequired[str]


class ReadyModelInfo(TypedDict):
    name: str
    model_id: str
    role: str
    description: NotRequired[str]
    loaded: bool
    tools_enabled: bool
    provider: NotRequired[str]
    context_budget: NotRequired[int]


class ReadyParams(TypedDict):
    version: str
    backend: str
    active_model: str
    mode: str
    workspace: str
    rom_path: str
    tools_enabled: bool
    servers: list[str]
    tool_count: int
    warnings: list[str]
    models: list[ReadyModelInfo]
    session_path: str
    studio_model: NotRequired[str]
    tools_write: NotRequired[bool]
    verify_hooks: NotRequired[bool]
    focus_file: NotRequired[str]
    lsp_context_mode: NotRequired[str]
    registry_path: NotRequired[str]
    broadcast_models: NotRequired[list[str]]
    orchestrator_model: NotRequired[str]
    prompt_tokens: NotRequired[int]
    completion_tokens: NotRequired[int]
    cache_creation_tokens: NotRequired[int]
    cache_read_tokens: NotRequired[int]
    session_messages: NotRequired[int]
    session_tool_calls: NotRequired[int]
    last_active_at: NotRequired[str]
    last_active_model: NotRequired[str]
    permission_rules: NotRequired[dict[str, bool]]
    shell_active: NotRequired[bool]
    shell_cwd: NotRequired[str]
    cancel_count: NotRequired[int]
    backend_restart_count: NotRequired[int]
    tool_latency_ms: NotRequired[int]
    tool_latency_samples: NotRequired[int]
    review_wait_ms: NotRequired[int]
    permission_wait_ms: NotRequired[int]
    permission_timeout_count: NotRequired[int]
    review_timeout_count: NotRequired[int]
    model_retry_count: NotRequired[int]
    model_retry_backoff_ms: NotRequired[int]
    model_error_count: NotRequired[int]
    tool_timeout_count: NotRequired[int]
    model_backpressure_count: NotRequired[int]
    tool_backpressure_count: NotRequired[int]
    model_queue_highwater: NotRequired[int]
    tool_queue_highwater: NotRequired[int]
    model_inflight_highwater: NotRequired[int]
    tool_inflight_highwater: NotRequired[int]
    inflight_model_calls: NotRequired[int]
    queued_model_calls: NotRequired[int]
    inflight_tool_calls: NotRequired[int]
    queued_tool_calls: NotRequired[int]
    model_retry_max: NotRequired[int]
    model_retry_base_ms: NotRequired[int]
    tool_exec_timeout_s: NotRequired[float]
    max_inflight_model_calls: NotRequired[int]
    max_inflight_tools: NotRequired[int]
    exec_queue_depth: NotRequired[int]
    request_count: NotRequired[int]
    request_success_count: NotRequired[int]
    request_error_count: NotRequired[int]
    request_reject_count: NotRequired[int]
    request_cancel_count: NotRequired[int]
    model_alias_resolutions: NotRequired[int]
    model_lookup_failures: NotRequired[int]
    model_request_counts: NotRequired[dict[str, int]]
    span_count: NotRequired[int]
    last_request_id: NotRequired[str]
    last_span_id: NotRequired[str]
    last_tool_call_id: NotRequired[str]
    request_samples: NotRequired[int]
    queued_ms_p50: NotRequired[int]
    queued_ms_p95: NotRequired[int]
    model_ms_p50: NotRequired[int]
    model_ms_p95: NotRequired[int]
    tool_ms_p50: NotRequired[int]
    tool_ms_p95: NotRequired[int]
    total_ms_p50: NotRequired[int]
    total_ms_p95: NotRequired[int]
    last_request_status: NotRequired[str]
    last_request_queued_ms: NotRequired[int]
    last_request_model_ms: NotRequired[int]
    last_request_tool_ms: NotRequired[int]
    last_request_total_ms: NotRequired[int]


class ToolPermissionRequestParams(TypedDict):
    name: str
    server: str
    arguments: str
    reason: NotRequired[str]


class ToolReviewRequestParams(TypedDict):
    review_id: str
    name: str
    server: str
    summary: str
    paths: list[str]
    diff_lines: list[str]
    omitted: int
    verification_commands: NotRequired[list[str]]


class ContextCompactedParams(TypedDict):
    summary: str
    replaced: int
    tokens_before: int
    tokens_after: int
    model: str


class SubagentStartParams(TypedDict):
    id: str
    name: str
    model: str
    provider: str
    depth: int
    parent_id: NotRequired[str | None]


class SubagentTextParams(TypedDict):
    id: str
    delta: str


class SubagentThinkingParams(TypedDict):
    id: str
    delta: str


class SubagentToolCallParams(TypedDict):
    id: str
    name: str
    server: str
    arguments: str
    call_id: str


class SubagentToolResultParams(TypedDict):
    id: str
    name: str
    result: str
    call_id: str


class SubagentDoneParams(TypedDict):
    id: str
    name: str
    model: str
    text: str
    prompt_tokens: int
    completion_tokens: int
    tool_calls: int
    error: NotRequired[str]
    cancelled: NotRequired[bool]


class SubagentErrorParams(TypedDict):
    id: str
    message: str


NotificationParams = (
    TextParams
    | ToolCallParams
    | ToolResultParams
    | ThinkingParams
    | ErrorParams
    | MessageParams
    | DoneParams
    | ReadyParams
    | ToolPermissionRequestParams
    | ToolReviewRequestParams
    | ContextCompactedParams
    | SubagentStartParams
    | SubagentTextParams
    | SubagentThinkingParams
    | SubagentToolCallParams
    | SubagentToolResultParams
    | SubagentDoneParams
    | SubagentErrorParams
)


def make_notification(method: str, params: NotificationParams | None = None) -> JsonRpcNotification:
    payload: JsonRpcNotification = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        payload["params"] = params
    return payload


def make_response(req_id: int, result: Any = None, error: str | None = None) -> JsonRpcResponse:
    payload: JsonRpcResponse = {"jsonrpc": "2.0", "id": req_id}
    if error is not None:
        payload["error"] = {"code": -1, "message": error}
    else:
        payload["result"] = result
    return payload


def text_params(delta: str, request_id: str | None = None, span_id: str | None = None) -> TextParams:
    payload: TextParams = {"delta": delta}
    if request_id:
        payload["request_id"] = request_id
    if span_id:
        payload["span_id"] = span_id
    return payload


def thinking_params(delta: str, request_id: str | None = None, span_id: str | None = None) -> ThinkingParams:
    payload: ThinkingParams = {"delta": delta}
    if request_id:
        payload["request_id"] = request_id
    if span_id:
        payload["span_id"] = span_id
    return payload


def tool_call_params(
    name: str,
    server: str,
    arguments: str,
    *,
    call_id: str | None = None,
    tool_group: str | None = None,
    request_id: str | None = None,
    span_id: str | None = None,
) -> ToolCallParams:
    payload: ToolCallParams = {"name": name, "server": server, "arguments": arguments}
    if call_id:
        payload["call_id"] = call_id
    if tool_group:
        payload["tool_group"] = tool_group
    if request_id:
        payload["request_id"] = request_id
    if span_id:
        payload["span_id"] = span_id
    return payload


def tool_result_params(
    name: str,
    result: str,
    *,
    server: str | None = None,
    call_id: str | None = None,
    tool_group: str | None = None,
    request_id: str | None = None,
    span_id: str | None = None,
) -> ToolResultParams:
    payload: ToolResultParams = {"name": name, "result": result}
    if server:
        payload["server"] = server
    if call_id:
        payload["call_id"] = call_id
    if tool_group:
        payload["tool_group"] = tool_group
    if request_id:
        payload["request_id"] = request_id
    if span_id:
        payload["span_id"] = span_id
    return payload


def error_params(message: str, request_id: str | None = None, span_id: str | None = None) -> ErrorParams:
    payload: ErrorParams = {"message": message}
    if request_id:
        payload["request_id"] = request_id
    if span_id:
        payload["span_id"] = span_id
    return payload


def message_params(
    *,
    message_id: str,
    role: MessageRole,
    content: str,
    timestamp: int,
    thinking: str | None = None,
    turn_id: str | None = None,
    model: str | None = None,
    tool_name: str | None = None,
    tool_server: str | None = None,
    tool_arguments: str | None = None,
    tool_group: str | None = None,
    attachments: list[AttachmentMeta] | None = None,
    construct_refs: list[ConstructRef] | None = None,
    request_id: str | None = None,
    span_id: str | None = None,
) -> MessageParams:
    payload: MessageParams = {
        "id": message_id,
        "role": role,
        "content": content,
        "timestamp": timestamp,
    }
    if thinking is not None:
        payload["thinking"] = thinking
    if turn_id is not None:
        payload["turn_id"] = turn_id
    if model is not None:
        payload["model"] = model
    if tool_name is not None:
        payload["tool_name"] = tool_name
    if tool_server is not None:
        payload["tool_server"] = tool_server
    if tool_arguments is not None:
        payload["tool_arguments"] = tool_arguments
    if tool_group is not None:
        payload["tool_group"] = tool_group
    if attachments is not None:
        payload["attachments"] = attachments
    if construct_refs is not None:
        payload["construct_refs"] = construct_refs
    if request_id is not None:
        payload["request_id"] = request_id
    if span_id is not None:
        payload["span_id"] = span_id
    return payload


def done_params(
    *,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    cache_creation_tokens: int | None = None,
    cache_read_tokens: int | None = None,
    request_id: str | None = None,
    end_status: str | None = None,
) -> DoneParams:
    payload: DoneParams = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }
    if cache_creation_tokens is not None:
        payload["cache_creation_tokens"] = cache_creation_tokens
    if cache_read_tokens is not None:
        payload["cache_read_tokens"] = cache_read_tokens
    if request_id:
        payload["request_id"] = request_id
    if end_status:
        payload["end_status"] = end_status
    return payload


def tool_permission_request_params(
    name: str,
    server: str,
    arguments: str,
    *,
    reason: str | None = None,
) -> ToolPermissionRequestParams:
    payload: ToolPermissionRequestParams = {"name": name, "server": server, "arguments": arguments}
    if reason:
        payload["reason"] = reason
    return payload


def tool_review_request_params(
    *,
    review_id: str,
    name: str,
    server: str,
    summary: str,
    paths: list[str],
    diff_lines: list[str],
    omitted: int,
    verification_commands: list[str] | None = None,
) -> ToolReviewRequestParams:
    payload: ToolReviewRequestParams = {
        "review_id": review_id,
        "name": name,
        "server": server,
        "summary": summary,
        "paths": paths,
        "diff_lines": diff_lines,
        "omitted": omitted,
    }
    if verification_commands is not None:
        payload["verification_commands"] = verification_commands
    return payload


def context_compacted_params(
    *,
    summary: str,
    replaced: int,
    tokens_before: int,
    tokens_after: int,
    model: str,
) -> ContextCompactedParams:
    return {
        "summary": summary,
        "replaced": replaced,
        "tokens_before": tokens_before,
        "tokens_after": tokens_after,
        "model": model,
    }


def subagent_start_params(
    *,
    subagent_id: str,
    name: str,
    model: str,
    provider: str,
    depth: int,
    parent_id: str | None = None,
) -> SubagentStartParams:
    payload: SubagentStartParams = {
        "id": subagent_id,
        "name": name,
        "model": model,
        "provider": provider,
        "depth": depth,
    }
    if parent_id is not None:
        payload["parent_id"] = parent_id
    return payload


def subagent_text_params(subagent_id: str, delta: str) -> SubagentTextParams:
    return {"id": subagent_id, "delta": delta}


def subagent_thinking_params(subagent_id: str, delta: str) -> SubagentThinkingParams:
    return {"id": subagent_id, "delta": delta}


def subagent_tool_call_params(
    *,
    subagent_id: str,
    name: str,
    server: str,
    arguments: str,
    call_id: str,
) -> SubagentToolCallParams:
    return {
        "id": subagent_id,
        "name": name,
        "server": server,
        "arguments": arguments,
        "call_id": call_id,
    }


def subagent_tool_result_params(
    *,
    subagent_id: str,
    name: str,
    result: str,
    call_id: str,
) -> SubagentToolResultParams:
    return {"id": subagent_id, "name": name, "result": result, "call_id": call_id}


def subagent_done_params(
    *,
    subagent_id: str,
    name: str,
    model: str,
    text: str,
    prompt_tokens: int,
    completion_tokens: int,
    tool_calls: int,
    error: str | None = None,
    cancelled: bool = False,
) -> SubagentDoneParams:
    payload: SubagentDoneParams = {
        "id": subagent_id,
        "name": name,
        "model": model,
        "text": text,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "tool_calls": tool_calls,
    }
    if error:
        payload["error"] = error
    if cancelled:
        payload["cancelled"] = True
    return payload


def subagent_error_params(subagent_id: str, message: str) -> SubagentErrorParams:
    return {"id": subagent_id, "message": message}


REQUEST_METHOD_TYPES: dict[str, tuple[str, type[TypedDict] | None]] = {
    "chat": ("ChatRequest", ChatRequestParams),
    "command": ("CommandRequest", CommandRequestParams),
    "status": ("StatusRequest", None),
    "models": ("ModelsRequest", None),
}


NOTIFICATION_METHOD_TYPES: dict[str, tuple[str, type[TypedDict] | None]] = {
    "text": ("TextNotification", TextParams),
    "tool_call": ("ToolCallNotification", ToolCallParams),
    "tool_result": ("ToolResultNotification", ToolResultParams),
    "message": ("MessageNotification", MessageParams),
    "done": ("DoneNotification", DoneParams),
    "thinking": ("ThinkingNotification", ThinkingParams),
    "error": ("ErrorNotification", ErrorParams),
    "ready": ("ReadyNotification", ReadyParams),
    "tool/permission_request": ("ToolPermissionNotification", ToolPermissionRequestParams),
    "context/compacted": ("ContextCompactedNotification", ContextCompactedParams),
    "tool/review_request": ("ToolReviewNotification", ToolReviewRequestParams),
    "subagent/start": ("SubagentStartNotification", SubagentStartParams),
    "subagent/text": ("SubagentTextNotification", SubagentTextParams),
    "subagent/thinking": ("SubagentThinkingNotification", SubagentThinkingParams),
    "subagent/tool_call": ("SubagentToolCallNotification", SubagentToolCallParams),
    "subagent/tool_result": ("SubagentToolResultNotification", SubagentToolResultParams),
    "subagent/done": ("SubagentDoneNotification", SubagentDoneParams),
    "subagent/error": ("SubagentErrorNotification", SubagentErrorParams),
}


_TS_TYPE_ORDER: list[type[TypedDict] | object] = [
    JsonRpcError,
    JsonRpcRequest,
    JsonRpcNotification,
    JsonRpcResponse,
    AttachmentMeta,
    AttachmentReference,
    ConstructRef,
    ChatRequestParams,
    CommandRequestParams,
    TextParams,
    ToolCallParams,
    ToolResultParams,
    ThinkingParams,
    ErrorParams,
    MessageParams,
    DoneParams,
    ReadyModelInfo,
    ReadyParams,
    ToolPermissionRequestParams,
    ToolReviewRequestParams,
    ContextCompactedParams,
    SubagentStartParams,
    SubagentTextParams,
    SubagentThinkingParams,
    SubagentToolCallParams,
    SubagentToolResultParams,
    SubagentDoneParams,
    SubagentErrorParams,
]


def _unwrap_not_required(annotation: Any) -> tuple[bool, Any]:
    origin = get_origin(annotation)
    if origin is NotRequired:
        args = get_args(annotation)
        return True, args[0] if args else Any
    return False, annotation


def _ts_literal(value: Any) -> str:
    if isinstance(value, str):
        return f'"{value}"'
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _ts_type(annotation: Any) -> str:
    origin = get_origin(annotation)
    if origin is None:
        if annotation is Any:
            return "unknown"
        if annotation is str:
            return "string"
        if annotation is int or annotation is float:
            return "number"
        if annotation is bool:
            return "boolean"
        if annotation is type(None):
            return "null"
        if isinstance(annotation, type) and is_typeddict(annotation):
            return annotation.__name__
        return getattr(annotation, "__name__", "unknown")

    if origin is NotRequired:
        args = get_args(annotation)
        return _ts_type(args[0] if args else Any)

    if origin in {list, tuple}:
        args = get_args(annotation)
        inner = _ts_type(args[0] if args else Any)
        if "|" in inner:
            inner = f"({inner})"
        return f"{inner}[]"

    if origin is dict:
        key_type, value_type = get_args(annotation) or (str, Any)
        return f"Record<{_ts_type(key_type)}, {_ts_type(value_type)}>"

    if origin in {Union, getattr(__import__("types"), "UnionType", object())}:
        return " | ".join(_ts_type(arg) for arg in get_args(annotation))

    if origin is Literal:
        return " | ".join(_ts_literal(arg) for arg in get_args(annotation))

    return "unknown"


def _emit_ts_interface(cls: type[TypedDict]) -> str:
    lines = [f"export interface {cls.__name__} {{"]
    hints = get_type_hints(cls, include_extras=True)
    for field_name, annotation in hints.items():
        optional, inner = _unwrap_not_required(annotation)
        suffix = "?" if optional else ""
        ts_type = _ts_type(inner)
        if cls.__name__ in {"JsonRpcRequest", "JsonRpcNotification"} and field_name == "params":
            ts_type = "unknown"
        lines.append(f"  {field_name}{suffix}: {ts_type};")
    lines.append("}")
    return "\n".join(lines)


def generate_typescript_protocol() -> str:
    """Generate the frontend transport-layer TypeScript declarations."""
    sections: list[str] = [
        "// AUTO-GENERATED by scripts/generate_protocol_ts.py from z3cli.app.ipc_schema.",
        "// Do not edit this file directly.",
        "",
    ]

    for item in _TS_TYPE_ORDER:
        if isinstance(item, type) and is_typeddict(item):
            sections.append(_emit_ts_interface(item))
            sections.append("")

    sections.extend([
        "// Request wrappers",
        "",
    ])
    for method, (name, params_type) in REQUEST_METHOD_TYPES.items():
        if params_type is None:
            sections.append(
                f'export type {name} = JsonRpcRequest & {{\n'
                f'  method: "{method}";\n'
                f"}};"
            )
        else:
            sections.append(
                f'export type {name} = JsonRpcRequest & {{\n'
                f'  method: "{method}";\n'
                f"  params: {params_type.__name__};\n"
                f"}};"
            )
        sections.append("")

    sections.extend([
        "// Notification wrappers",
        "",
    ])
    notification_names: list[str] = []
    for method, (name, params_type) in NOTIFICATION_METHOD_TYPES.items():
        notification_names.append(name)
        if params_type is None:
            sections.append(
                f'export interface {name} extends JsonRpcNotification {{\n'
                f'  method: "{method}";\n'
                f"}}"
            )
        else:
            sections.append(
                f'export interface {name} extends JsonRpcNotification {{\n'
                f'  method: "{method}";\n'
                f"  params: {params_type.__name__};\n"
                f"}}"
            )
        sections.append("")

    sections.append("export type BackendEvent =")
    for index, name in enumerate(notification_names):
        prefix = "  | " if index > 0 else "  "
        sections.append(f"{prefix}{name}")
    sections.append(";")
    sections.append("")
    return "\n".join(sections)


def write_typescript_protocol(path: Path) -> None:
    """Write the generated frontend transport types to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(generate_typescript_protocol(), encoding="utf-8")
