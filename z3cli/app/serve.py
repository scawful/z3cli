"""JSON-RPC stdio server mode for z3cli.

Reads JSON-RPC requests from stdin, streams events as JSON-RPC
notifications to stdout. This is the backend for the Ink frontend.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from z3cli import __version__
from z3cli.app.backends import (
    DEFAULT_LLAMACPP_API_BASE, LMStudioBackend, LlamaCppBackend,
)
from z3cli.core.config import (
    API_BASE, MCP_CONFIG_PATH, REGISTRY_PATH,
    load_registry, list_zelda_models,
)
from z3cli.core.engine import (
    ChatEngine, DoneEvent, ErrorEvent, TextEvent, ThinkingEvent,
    ToolCallEvent, ToolResultEvent,
)
from z3cli.protocol.lmstudio import (
    ensure_model_loaded, ensure_server, loaded_models, server_status,
)
from z3cli.app.runtime import (
    DEFAULT_BROADCAST_MODELS, DEFAULT_LLAMACPP_MODEL, DEFAULT_ROM,
    DEFAULT_WORKSPACE, VALID_BACKENDS, VALID_MODES, build_harness_prompt,
    current_model_name, engine_key, merge_system_prompts, resolve_targets,
)
from z3cli.core.session import Session, export_training, list_sessions, load_session
from z3cli.core.tool_bridge import ToolBridge
from z3cli.app.tooling import connect_tool_bridge, wrap_bridge_for_model


def _write(data: dict) -> None:
    """Write a JSON-RPC message to stdout."""
    sys.stdout.write(json.dumps(data, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _notify(method: str, params: dict | None = None) -> None:
    msg: dict = {"jsonrpc": "2.0", "method": method}
    if params:
        msg["params"] = params
    _write(msg)


def _respond(req_id: int, result: object = None, error: str | None = None) -> None:
    msg: dict = {"jsonrpc": "2.0", "id": req_id}
    if error:
        msg["error"] = {"code": -1, "message": error}
    else:
        msg["result"] = result
    _write(msg)


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
        self.active_model = "nayru"
        self.mode = "manual"
        self.workspace = DEFAULT_WORKSPACE
        self.rom_path: Path | None = DEFAULT_ROM
        self.tools_enabled = True
        self.tools_write = False
        self.broadcast_models = list(DEFAULT_BROADCAST_MODELS)
        self.focus_context: str = ""
        self.bridge: ToolBridge | None = None
        self.bridge_errors: list[str] = []
        self.engines: dict[str, ChatEngine] = {}
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.session = Session()
        self.cancel_requested = False

    def get_engine(self, model_name: str) -> ChatEngine:
        key = engine_key(self.backend_name, model_name)
        engine = self.engines.get(key)
        if engine is None:
            engine = ChatEngine(api_base=self.api_base, bridge=self.bridge)
            self.engines[key] = engine
        return engine


def active_model_name(state: ServeState) -> str:
    return current_model_name(state.active_model, state.backend_name, state.llamacpp_model)


def get_backend(state: ServeState) -> LMStudioBackend | LlamaCppBackend:
    if state.backend_name == "llamacpp":
        return LlamaCppBackend(api_base=state.llamacpp_api_base, model=state.llamacpp_model)
    return LMStudioBackend(api_base=state.studio_api_base, host=state.host, port=state.port)


def set_backend(state: ServeState, backend_name: str) -> None:
    state.backend_name = backend_name
    if backend_name == "llamacpp":
        state.api_base = state.llamacpp_api_base
    else:
        state.api_base = state.studio_api_base


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
        return
    bridge, warnings = await connect_tool_bridge(state.workspace, state.mcp_path)
    await replace_bridge(state, bridge, warnings)


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
    parser.add_argument("--model", default="nayru")
    parser.add_argument("--mode", default="manual")
    parser.add_argument("--broadcast-models", default=",".join(DEFAULT_BROADCAST_MODELS))
    parser.add_argument("--tools", action=argparse.BooleanOptionalAction, default=True)
    parsed, _ = parser.parse_known_args(args)
    return parsed


async def init_state(args: list[str]) -> ServeState:
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
    mode = str(parsed.mode).lower()
    if mode in VALID_MODES:
        state.mode = mode
    state.studio_api_base = parsed.studio_api_base.rstrip("/")
    state.llamacpp_api_base = parsed.llamacpp_api_base.rstrip("/")
    state.llamacpp_model = parsed.llamacpp_model
    state.workspace = Path(parsed.workspace).expanduser().resolve()
    state.rom_path = None if not parsed.rom else Path(parsed.rom).expanduser().resolve()
    state.tools_enabled = parsed.tools
    state.broadcast_models = [value.strip() for value in parsed.broadcast_models.split(",") if value.strip()]

    state.models, state.routers = load_registry(state.registry_path)
    set_backend(state, state.backend_name)
    if state.backend_name == "studio":
        ensure_server(state.host, state.port)

    if state.tools_enabled:
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
    )

    return state


def build_ready_params(state: ServeState) -> dict:
    """Build the ready notification payload."""
    try:
        loaded = loaded_models(state.host, state.port) if state.backend_name == "studio" else []
    except Exception:
        loaded = []
    loaded_names = {
        v
        for entry in loaded
        for k in ("identifier", "modelKey", "modelPath", "name", "model", "id")
        for v in [entry.get(k)]
        if isinstance(v, str)
    }
    zelda = list_zelda_models(state.models)
    models_info = []
    for m in sorted(zelda.values(), key=lambda x: x.name):
        models_info.append({
            "name": m.name,
            "model_id": m.model_id,
            "role": m.role,
            "loaded": m.name in loaded_names or m.model_id in loaded_names,
            "tools_enabled": m.tools_enabled,
        })

    return {
        "version": __version__,
        "backend": state.backend_name,
        "active_model": active_model_name(state),
        "studio_model": state.active_model,
        "mode": state.mode,
        "workspace": str(state.workspace),
        "rom_path": str(state.rom_path) if state.rom_path else "",
        "tools_enabled": state.tools_enabled,
        "tools_write": state.tools_write,
        "servers": state.bridge.server_names if state.bridge else [],
        "tool_count": state.bridge.tool_count if state.bridge else 0,
        "warnings": state.bridge_errors,
        "models": models_info,
        "session_path": str(state.session.path) if state.session.path else "",
    }


async def handle_chat(state: ServeState, req_id: int | None, params: dict) -> None:
    """Handle a chat request — stream events as notifications, respond when done."""
    message = str(params.get("message", ""))
    requested_model = params.get("model")
    active_model = str(requested_model) if isinstance(requested_model, str) and requested_model else state.active_model
    targets = resolve_targets(
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
    )

    backend = get_backend(state)
    multi_target = len(targets) > 1
    prompt_tokens = 0
    completion_tokens = 0

    # Record user message to session
    is_first_message = state.session.message_count == 0
    for target in targets:
        state.session.append_engine_msg(target.name, {"role": "user", "content": message})
    if is_first_message:
        state.session.rename_from_first_message(message)

    for target in targets:
        request_name = backend.resolve_request_model(target, auto_load=True)
        engine = state.get_engine(target.name)
        effective_bridge = wrap_bridge_for_model(
            state.bridge, target.tool_profile, read_only=not state.tools_write,
        )
        engine.bridge = effective_bridge
        use_tools = bool(effective_bridge and state.tools_enabled and target.tools_enabled)
        system = merge_system_prompts(
            build_harness_prompt(state.workspace, state.rom_path, state.focus_context),
            target.system_prompt,
        )
        if multi_target:
            _notify("text", {"delta": f"\n\n### {target.name}\n\n"})

        use_thinking = bool(target.thinking_tier)
        assistant_text = ""
        target_done = False
        async for event in engine.chat(
            message=message,
            model_id=request_name,
            system=system,
            temperature=target.temperature,
            max_tokens=target.max_tokens,
            use_tools=use_tools,
            thinking=use_thinking,
            max_tool_result=4000 if target.tool_profile and target.tool_profile != "*" else 0,
        ):
            if state.cancel_requested:
                engine.cancel()
                break
            if isinstance(event, ThinkingEvent):
                _notify("thinking", {"delta": event.text})
            elif isinstance(event, TextEvent):
                _notify("text", {"delta": event.text})
                assistant_text += event.text
            elif isinstance(event, ToolCallEvent):
                _notify("tool_call", {
                    "name": event.name,
                    "server": event.server,
                    "arguments": event.arguments,
                })
                state.session.append_engine_msg(target.name, {
                    "role": "assistant",
                    "content": assistant_text,
                    "tool_calls": [{"name": event.name, "arguments": event.arguments}],
                })
                assistant_text = ""
            elif isinstance(event, ToolResultEvent):
                _notify("tool_result", {
                    "name": event.name,
                    "result": event.result,
                })
                state.session.append_engine_msg(target.name, {
                    "role": "tool",
                    "name": event.name,
                    "content": event.result,
                })
            elif isinstance(event, ErrorEvent):
                _notify("error", {"message": event.message})
            elif isinstance(event, DoneEvent):
                state.prompt_tokens += event.prompt_tokens
                state.completion_tokens += event.completion_tokens
                prompt_tokens += event.prompt_tokens
                completion_tokens += event.completion_tokens
                target_done = True
                break

        # Record final assistant response to session
        if assistant_text.strip():
            state.session.append_engine_msg(target.name, {
                "role": "assistant",
                "content": assistant_text,
            })

        if state.cancel_requested:
            break
        if not target_done:
            break

    _notify("done", {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    })

    if req_id is not None:
        _respond(req_id, result={"ok": True})


async def run_chat_request(state: ServeState, req_id: int | None, params: dict) -> None:
    try:
        await handle_chat(state, req_id, params)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        _notify("error", {"message": str(exc)})
        if req_id is not None:
            _respond(req_id, error=str(exc))


async def handle_command(state: ServeState, req_id: int, params: dict) -> None:
    """Handle slash commands from the frontend."""
    cmd = str(params.get("cmd", ""))
    args = params.get("args", [])
    args = args if isinstance(args, list) else []

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
        set_backend(state, backend_name)
        if backend_name == "studio":
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

    if cmd == "/backend-status":
        backend = get_backend(state)
        status = await backend.check_connection()
        loaded = await backend.list_loaded_models()
        _respond(req_id, result={
            "backend": status.name,
            "connected": status.connected,
            "detail": status.detail,
            "loaded": loaded,
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
        state.active_model = str(args[0])
        state.session.append_model_switch(old_model, state.active_model, reason="user command")
        _notify("ready", build_ready_params(state))
        _respond(req_id, result={"active_model": state.active_model})
        return

    if cmd == "/mode":
        if not args:
            _respond(req_id, error="Usage: /mode <manual|oracle|switchhook|broadcast>")
            return
        mode = str(args[0]).strip().lower()
        if mode not in VALID_MODES:
            _respond(req_id, error="Usage: /mode <manual|oracle|switchhook|broadcast>")
            return
        state.mode = mode
        _notify("ready", build_ready_params(state))
        _respond(req_id, result={"mode": state.mode})
        return

    if cmd == "/route":
        prompt = " ".join(str(arg) for arg in args)
        targets = resolve_targets(
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
        )
        _respond(req_id, result={"targets": [target.name for target in targets]})
        return

    if cmd == "/broadcast":
        if not args:
            _respond(req_id, error="Usage: /broadcast <alias1,alias2,...>")
            return
        state.broadcast_models = [value.strip() for value in str(args[0]).split(",") if value.strip()]
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
        _respond(req_id, result={"loaded": await get_backend(state).list_loaded_models()})
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
        await refresh_tool_bridge(state)
        _notify("ready", build_ready_params(state))
        _respond(req_id, result={"tools_enabled": state.tools_enabled})
        return

    if cmd == "/tools-write":
        if not args or str(args[0]).lower() not in {"on", "off"}:
            _respond(req_id, error="Usage: /tools-write <on|off>")
            return
        state.tools_write = str(args[0]).lower() == "on"
        _respond(req_id, result={"tools_write": state.tools_write})
        return

    if cmd == "/workspace":
        if not args:
            _respond(req_id, error="Usage: /workspace <path>")
            return
        state.workspace = Path(str(args[0])).expanduser().resolve()
        await refresh_tool_bridge(state)
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
            state.focus_context = ""
            _respond(req_id, result={"cleared": True})
            return
        # Resolve path: try relative to workspace first, then absolute
        focus_path = state.workspace / arg
        if not focus_path.is_file():
            focus_path = Path(arg).expanduser().resolve()
        if not focus_path.is_file():
            _respond(req_id, error=f"File not found: {arg}")
            return
        try:
            content = focus_path.read_text(encoding="utf-8")
        except Exception as e:
            _respond(req_id, error=f"Error reading {focus_path}: {e}")
            return
        max_chars = 32_000
        if len(content) > max_chars:
            content = content[:max_chars] + f"\n\n... (truncated at {max_chars} chars)"
        state.focus_context = f"# Focus: {focus_path.name}\n\n{content}"
        lines = content.count("\n") + 1
        _respond(req_id, result={
            "loaded": focus_path.name,
            "lines": lines,
            "chars": len(content),
            "path": str(focus_path),
        })
        return

    if cmd == "/load":
        if state.backend_name != "studio":
            _respond(req_id, error="/load is only available on the studio backend")
            return
        target_name = str(args[0]) if args else state.active_model
        target = state.models.get(target_name)
        if target is None:
            _respond(req_id, error=f"Unknown model: {target_name}")
            return
        try:
            ensure_model_loaded(target.name, target.model_id, state.host, state.port, auto_load=True)
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
        _respond(req_id, result={
            "prompt_tokens": state.prompt_tokens,
            "completion_tokens": state.completion_tokens,
            "total_tokens": state.prompt_tokens + state.completion_tokens,
            "messages": user_msgs,
            "tool_calls": tool_calls,
            "engines": len(state.engines),
            "models_used": models_used,
            "session": str(state.session.path.name) if state.session.path else "",
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
        if not args:
            _respond(req_id, error="Usage: /resume <session-name>")
            return
        name = str(args[0])
        sessions = list_sessions()
        match = next((s for s in sessions if name in s["name"]), None)
        if not match:
            _respond(req_id, error=f"No session matching '{name}'")
            return
        try:
            meta, model_msgs = load_session(Path(match["path"]))
        except Exception as exc:
            _respond(req_id, error=f"Failed to load session: {exc}")
            return
        # Restore state from meta
        if meta.get("active_model"):
            state.active_model = meta["active_model"]
        if meta.get("mode") in VALID_MODES:
            state.mode = meta["mode"]
        if meta.get("backend") in VALID_BACKENDS:
            set_backend(state, meta["backend"])
            if state.backend_name == "studio":
                ensure_server(state.host, state.port)
        if meta.get("workspace"):
            state.workspace = Path(meta["workspace"]).expanduser().resolve()
        if "rom_path" in meta:
            rom_value = str(meta["rom_path"])
            state.rom_path = Path(rom_value).expanduser().resolve() if rom_value else None
        if "tools_enabled" in meta:
            state.tools_enabled = bool(meta["tools_enabled"])
        if "broadcast_models" in meta and isinstance(meta["broadcast_models"], list):
            state.broadcast_models = [
                str(value).strip() for value in meta["broadcast_models"] if str(value).strip()
            ]
        if meta.get("llamacpp_model"):
            state.llamacpp_model = str(meta["llamacpp_model"])
        await refresh_tool_bridge(state)
        # Restore engine histories
        restored_count = 0
        for engine in state.engines.values():
            engine.reset()
        for model_name, msgs in model_msgs.items():
            engine = state.get_engine(model_name)
            engine.messages = list(msgs)
            restored_count += len(msgs)
        _notify("ready", build_ready_params(state))
        _respond(req_id, result={
            "resumed": match["name"],
            "models": list(model_msgs.keys()),
            "messages_restored": restored_count,
        })
        return

    if cmd == "/export-training":
        if not state.session.path:
            _respond(req_id, error="No active session to export")
            return
        out_path = Path(str(args[0])) if args else state.session.path.with_suffix(".training.jsonl")
        model_filter = str(args[1]) if len(args) > 1 else None
        count = export_training(state.session.path, out_path, model_filter)
        _respond(req_id, result={"path": str(out_path), "samples": count})
        return

    if cmd == "/compact":
        target_name = str(args[0]) if args else active_model_name(state)
        ekey = engine_key(state.backend_name, target_name)
        engine = state.engines.get(ekey)
        if not engine or len(engine.messages) < 4:
            _respond(req_id, error=f"Not enough history to compact for {target_name}")
            return
        # Build a summarization prompt
        history_text = "\n".join(
            f"{m.get('role', '?')}: {str(m.get('content', ''))[:200]}"
            for m in engine.messages[-20:]
        )
        summary_prompt = (
            "Summarize the key points, decisions, and context from this conversation "
            "in 2-3 concise paragraphs. Preserve important technical details:\n\n"
            + history_text
        )
        # Resolve model for summarization
        target = state.models.get(target_name) or state.models.get(state.active_model)
        if not target:
            _respond(req_id, error=f"Cannot resolve model for compact: {target_name}")
            return
        backend = get_backend(state)
        try:
            request_name = backend.resolve_request_model(target, auto_load=True)
        except RuntimeError as exc:
            _respond(req_id, error=str(exc))
            return
        # Run summarization (non-streaming)
        summary_engine = ChatEngine(api_base=state.api_base)
        summary_text = ""
        async for event in summary_engine.chat(
            message=summary_prompt,
            model_id=request_name,
            system="You are a conversation summarizer. Be concise and preserve technical details.",
            temperature=0.3,
            max_tokens=512,
            use_tools=False,
        ):
            if isinstance(event, TextEvent):
                summary_text += event.text
        await summary_engine.close()
        if not summary_text.strip():
            _respond(req_id, error="Summarization produced empty result")
            return
        # Apply compaction
        replaced_count = len(engine.messages)
        engine.messages = [{"role": "assistant", "content": summary_text.strip()}]
        state.session.save_compact(target_name, summary_text.strip(), replaced_count)
        _respond(req_id, result={
            "model": target_name,
            "replaced": replaced_count,
            "summary_length": len(summary_text),
        })
        return

    _respond(req_id, error=f"Unknown command: {cmd}")


async def serve_main(extra_args: list[str]) -> None:
    """Main loop: read JSON-RPC from stdin, dispatch, write to stdout."""
    # Redirect logging to stderr so stdout is clean JSON
    import logging
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)

    state = await init_state(extra_args)
    _notify("ready", build_ready_params(state))

    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    active_chat: asyncio.Task | None = None

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
            if active_chat and not active_chat.done():
                state.cancel_requested = True
                active_chat.cancel()
            break
        elif method == "cancel":
            state.cancel_requested = True
            # Signal all engines to abort their active HTTP streams
            for engine in state.engines.values():
                engine.cancel()
            continue
        elif method == "chat":
            if active_chat and not active_chat.done():
                if req_id is not None:
                    _respond(req_id, error="Already processing a chat request")
                else:
                    _notify("error", {"message": "Already processing a chat request"})
                continue
            state.cancel_requested = False
            active_chat = asyncio.create_task(run_chat_request(state, req_id, params))
        elif method == "command" and req_id is not None:
            await handle_command(state, req_id, params)
        elif method == "status" and req_id is not None:
            _respond(req_id, result=build_ready_params(state))
        elif method == "models" and req_id is not None:
            _respond(req_id, result=build_ready_params(state)["models"])
        elif req_id is not None:
            _respond(req_id, error=f"Unknown method: {method}")

    # Wait for active chat to finish
    if active_chat and not active_chat.done():
        active_chat.cancel()
        try:
            await active_chat
        except asyncio.CancelledError:
            pass

    # Cleanup
    state.session.close()
    for engine in state.engines.values():
        await engine.close()
    if state.bridge:
        await state.bridge.close()
