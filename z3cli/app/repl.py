"""Interactive Zelda CLI harness for LM Studio models and MCP tools."""

from __future__ import annotations

import argparse
import asyncio
import os
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.console import Console

from z3cli import __version__
from z3cli.app.backends import (
    DEFAULT_LLAMACPP_API_BASE, LMStudioBackend, LlamaCppBackend,
)
from z3cli.core.config import (
    API_BASE, HISTORY_FILE, MCP_CONFIG_PATH, REGISTRY_PATH, SESSION_DIR,
    ModelConfig, RouterConfig, load_registry, list_zelda_models,
)
from z3cli.app.display import (
    MarkdownStreamer, ThinkingStreamer, ToolPanel, build_bottom_toolbar,
    render_stats_table, render_welcome_banner,
)
from z3cli.core.engine import (
    ChatEngine, DoneEvent, ErrorEvent, TextEvent, ThinkingEvent,
    ToolCallEvent, ToolResultEvent,
)
from z3cli.protocol.lmstudio import (
    available_models, ensure_model_loaded, ensure_server,
    loaded_models, server_status,
)
from z3cli.app.runtime import (
    DEFAULT_BROADCAST_MODELS, DEFAULT_LLAMACPP_MODEL, DEFAULT_ROM,
    DEFAULT_WORKSPACE, VALID_BACKENDS, VALID_MODES, build_harness_prompt,
    current_model_name, engine_key, merge_system_prompts, resolve_targets,
)
from z3cli.core.session import Session, export_training, list_sessions, load_session
from z3cli.core.tool_bridge import ToolBridge
from z3cli.app.tooling import connect_tool_bridge, wrap_bridge_for_model

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
    workspace: Path
    rom_path: Path | None
    temperature: float
    max_tokens: int
    broadcast_models: list[str]
    tools_enabled: bool
    tools_write: bool = False
    bridge: ToolBridge | None = None
    bridge_errors: list[str] = field(default_factory=list)
    engines: dict[str, ChatEngine] = field(default_factory=dict)
    session: Session | None = None
    message_count: int = 0
    tool_call_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    focus_context: str = ""
    _first_message_sent: bool = False


def get_backend(state: AppState) -> LMStudioBackend | LlamaCppBackend:
    if state.backend_name == "llamacpp":
        return LlamaCppBackend(api_base=state.llamacpp_api_base, model=state.llamacpp_model)
    return LMStudioBackend(api_base=state.studio_api_base, host=state.host, port=state.port)


def active_model_name(state: AppState) -> str:
    return current_model_name(state.active_model, state.backend_name, state.llamacpp_model)


def build_system_prompt(state: AppState) -> str:
    return build_harness_prompt(state.workspace, state.rom_path, state.focus_context)


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
        return
    bridge, warnings = await connect_tool_bridge(state.workspace, state.mcp_path)
    await replace_bridge(state, bridge, warnings)


def set_backend(state: AppState, backend_name: str) -> None:
    state.backend_name = backend_name
    if backend_name == "llamacpp":
        state.api_base = state.llamacpp_api_base
    else:
        state.api_base = state.studio_api_base


def get_engine(state: AppState, model_name: str) -> ChatEngine:
    key = engine_key(state.backend_name, model_name)
    engine = state.engines.get(key)
    if engine is None:
        engine = ChatEngine(api_base=state.api_base, bridge=state.bridge)
        state.engines[key] = engine
    return engine


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
    )


def render_model_table(state: AppState) -> None:
    from rich.table import Table
    try:
        avail = {
            entry.get("modelKey")
            for entry in available_models(state.host, state.port)
            if isinstance(entry.get("modelKey"), str)
        }
        loaded = loaded_models(state.host, state.port)
    except Exception:
        avail = set()
        loaded = []
    loaded_names = {
        value
        for entry in loaded
        for key in ("identifier", "modelKey", "modelPath", "name", "model", "id")
        for value in [entry.get(key)]
        if isinstance(value, str)
    }
    table = Table(title="Zelda Models")
    table.add_column("Active")
    table.add_column("Alias")
    table.add_column("Loaded")
    table.add_column("Available")
    table.add_column("Model ID")
    table.add_column("Role")
    for model in sorted(list_zelda_models(state.models).values(), key=lambda item: item.name):
        table.add_row(
            "*" if model.name == state.active_model else "",
            model.name,
            "yes" if model.name in loaded_names or model.model_id in loaded_names else "no",
            "yes" if model.model_id in avail else "no",
            model.model_id,
            model.role,
        )
    state.console.print(table)


def print_status(state: AppState) -> None:
    state.console.print(f"Backend: {state.backend_name}")
    if state.backend_name == "studio":
        status = server_status(state.host, state.port)
        state.console.print(f"LM Studio running: {status.get('running')} on port {status.get('port')}")
        state.console.print(f"API base: {state.studio_api_base}")
    else:
        state.console.print(f"llama.cpp API base: {state.llamacpp_api_base}")
        state.console.print(f"Pinned model: {state.llamacpp_model}")
    state.console.print(f"Mode: {state.mode}")
    state.console.print(f"Active model: {active_model_name(state)}")
    state.console.print(f"Workspace: {state.workspace}")
    state.console.print(f"ROM: {state.rom_path or '(none)'}")
    state.console.print(f"Tools enabled: {state.tools_enabled}")
    state.console.print(f"Tool write access: {state.tools_write}")
    if state.bridge:
        state.console.print(f"Connected tool servers: {', '.join(state.bridge.server_names) or '(none)'}")
        state.console.print(f"Tool count: {state.bridge.tool_count}")
    elif state.bridge_errors:
        state.console.print(f"Tool connection warnings: {'; '.join(state.bridge_errors)}")


async def list_loaded_api(state: AppState) -> None:
    loaded = await get_backend(state).list_loaded_models()
    if loaded:
        state.console.print("Loaded API models: " + ", ".join(loaded))
    else:
        state.console.print("No loaded API models reported by the active backend.")


# ---------------------------------------------------------------------------
# Streaming with Markdown rendering and tool panels
# ---------------------------------------------------------------------------

async def stream_response(state: AppState, target: ModelConfig, prompt: str) -> None:
    request_name = get_backend(state).resolve_request_model(target, state.auto_load)
    engine = get_engine(state, target.name)
    system_prompt = merge_system_prompts(build_system_prompt(state), target.system_prompt)

    # Apply model-specific tool adapter if the model has a tool_profile
    effective_bridge = wrap_bridge_for_model(
        state.bridge, target.tool_profile, read_only=not state.tools_write,
    )
    engine.bridge = effective_bridge
    use_tools = bool(effective_bridge and state.tools_enabled and target.tools_enabled)

    # Enable thinking mode when the model has a thinking_tier configured
    use_thinking = bool(target.thinking_tier)

    prefix = f"[{target.name}] " if state.mode != "manual" or len(preview_targets(state, prompt)) > 1 else ""
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

    async for event in engine.chat(
        message=prompt,
        model_id=request_name,
        system=system_prompt,
        temperature=target.temperature or state.temperature,
        max_tokens=target.max_tokens or state.max_tokens,
        use_tools=use_tools,
        thinking=use_thinking,
        max_tool_result=max_tool_result,
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
                    "tool_calls": [{"name": event.name, "arguments": event.arguments}],
                })

        elif isinstance(event, ToolResultEvent):
            state.console.print(ToolPanel.render_result(event.name, event.result))
            if state.session:
                state.session.append_engine_msg(target.name, {
                    "role": "tool",
                    "content": event.result,
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
            # Record the final assistant message in session
            if state.session and full_text:
                state.session.append_engine_msg(target.name, {
                    "role": "assistant",
                    "content": full_text,
                })


async def send_prompt(state: AppState, prompt: str) -> None:
    # Record user message in session
    targets = preview_targets(state, prompt)
    if state.session:
        for target in targets:
            state.session.append_engine_msg(target.name, {
                "role": "user",
                "content": prompt,
            })
        # Rename session file based on first message
        if not state._first_message_sent:
            state.session.rename_from_first_message(prompt)
            state._first_message_sent = True

    for target in targets:
        await stream_response(state, target, prompt)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def current_mode_help() -> str:
    return (
        "Modes: manual (active model only), oracle (keyword route), "
        "switchhook (plan vs act), broadcast (fan out to multiple models)"
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
        state.console.print(
            "Commands:\n"
            "  /help                   Show this help\n"
            "  /status                 Connection and state info\n"
            "  /backend [name]         Show or set backend (studio|llamacpp)\n"
            "  /backends               List available backends\n"
            "  /backend-status         Show active backend status\n"
            "  /models                 Show available Zelda models\n"
            "  /loaded                 List loaded API models\n"
            "  /servers                Tool server info\n"
            "  /model <name>           Switch active model\n"
            "  /mode <name>            Set routing mode (manual|oracle|switchhook|broadcast)\n"
            "  /modes                  List routing modes\n"
            "  /route <prompt>         Preview routing without sending\n"
            "  /broadcast <a,b,c>      Set broadcast model list\n"
            "  /load [name]            Load a model in LM Studio\n"
            "  /workspace <path>       Change workspace directory\n"
            "  /rom <path|none>        Change ROM target\n"
            "  /focus <path|clear>     Load file into system prompt (KV-cached)\n"
            "  /tools <on|off>         Toggle tool use\n"
            "  /tools-write <on|off>   Toggle write access (default: off)\n"
            "  /reset [model|all]      Clear conversation history\n"
            "  /stats                  Show session statistics\n"
            "  /save                   Show session file path\n"
            "  /sessions               List saved sessions\n"
            "  /resume <name>          Resume a previous session\n"
            "  /compact                Summarize and compress history (lossy)\n"
            "  /export-training [out]  Export session to training JSONL\n"
            "  /exit                   Quit"
        )
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
        state.console.print(f"Backend set to {state.backend_name} ({active_model_name(state)})")
        return True

    if command == "/backends":
        state.console.print(
            f"Backends: {'*' if state.backend_name == 'studio' else ' '} studio ({state.studio_api_base}) ; "
            f"{'*' if state.backend_name == 'llamacpp' else ' '} llamacpp ({state.llamacpp_api_base}, {state.llamacpp_model})"
        )
        return True

    if command == "/backend-status":
        backend = get_backend(state)
        status = await backend.check_connection()
        loaded = await backend.list_loaded_models()
        state.console.print(f"Backend: {status.name}")
        state.console.print(f"Connected: {status.connected}")
        if status.detail:
            state.console.print(f"Detail: {status.detail}")
        state.console.print("Loaded: " + (", ".join(loaded) if loaded else "(none)"))
        return True

    if command == "/models":
        render_model_table(state)
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
        state.active_model = parts[1]
        state.console.print(f"Active model set to {state.active_model}")
        if state.session and old_model != state.active_model:
            state.session.append_model_switch(old_model, state.active_model)
        return True

    if command == "/mode":
        if len(parts) < 2:
            state.console.print("Usage: /mode <manual|oracle|switchhook|broadcast>")
            return True
        mode = parts[1].strip().lower()
        if mode not in VALID_MODES:
            state.console.print("Usage: /mode <manual|oracle|switchhook|broadcast>")
            return True
        state.mode = mode
        state.console.print(f"Routing mode set to {state.mode}")
        return True

    if command == "/route":
        if len(parts) < 2:
            state.console.print("Usage: /route <prompt>")
            return True
        state.console.print(" -> ".join(target.name for target in preview_targets(state, " ".join(parts[1:]))))
        return True

    if command == "/broadcast":
        if len(parts) < 2:
            state.console.print("Usage: /broadcast <alias1,alias2,...>")
            return True
        state.broadcast_models = [v.strip() for v in parts[1].split(",") if v.strip()]
        state.console.print(f"Broadcast models: {', '.join(state.broadcast_models)}")
        return True

    if command == "/load":
        if state.backend_name != "studio":
            state.console.print("/load is only available on the studio backend.")
            return True
        target_name = parts[1] if len(parts) >= 2 else state.active_model
        target = state.models.get(target_name, ModelConfig(name=target_name, model_id=target_name))
        request_name = ensure_model_loaded(target.name, target.model_id, state.host, state.port, auto_load=True)
        state.console.print(f"Loaded {target.name} as {request_name}")
        return True

    if command == "/workspace":
        if len(parts) < 2:
            state.console.print("Usage: /workspace <path>")
            return True
        state.workspace = Path(parts[1]).expanduser().resolve()
        await refresh_tool_bridge(state)
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
            state.focus_context = ""
            state.console.print("Focus context cleared.")
            return True
        # Resolve path: try relative to workspace first, then absolute
        focus_path = state.workspace / arg
        if not focus_path.is_file():
            focus_path = Path(arg).expanduser().resolve()
        if not focus_path.is_file():
            state.console.print(f"[red]File not found: {arg}[/red]")
            return True
        try:
            content = focus_path.read_text(encoding="utf-8")
        except Exception as e:
            state.console.print(f"[red]Error reading {focus_path}: {e}[/red]")
            return True
        # Truncate very large files to avoid blowing context
        max_chars = 32_000
        if len(content) > max_chars:
            content = content[:max_chars] + f"\n\n... (truncated at {max_chars} chars)"
        state.focus_context = f"# Focus: {focus_path.name}\n\n{content}"
        lines = content.count("\n") + 1
        state.console.print(f"Loaded {focus_path.name} ({lines} lines) into focus context.")
        return True

    if command == "/tools":
        if len(parts) < 2 or parts[1].lower() not in {"on", "off"}:
            state.console.print("Usage: /tools <on|off>")
            return True
        state.tools_enabled = parts[1].lower() == "on"
        await refresh_tool_bridge(state)
        state.console.print(f"Tools enabled: {state.tools_enabled}")
        return True

    if command == "/tools-write":
        if len(parts) < 2 or parts[1].lower() not in {"on", "off"}:
            state.console.print("Usage: /tools-write <on|off>")
            return True
        state.tools_write = parts[1].lower() == "on"
        state.console.print(f"Tool write access: {state.tools_write}")
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
        if len(parts) < 2:
            state.console.print("Usage: /resume <session-name>")
            return True
        name = parts[1]
        sessions = list_sessions(SESSION_DIR)
        match = next((s for s in sessions if s["name"] == name), None)
        if not match:
            # Try partial match
            match = next((s for s in sessions if name in s["name"]), None)
        if not match:
            state.console.print(f"Session not found: {name}")
            return True
        meta, model_msgs = load_session(Path(match["path"]))
        # Restore AppState from meta
        if meta.get("active_model"):
            state.active_model = meta["active_model"]
        if meta.get("backend") in VALID_BACKENDS:
            set_backend(state, meta["backend"])
            if state.backend_name == "studio":
                ensure_server(state.host, state.port)
        if meta.get("mode") and meta["mode"] in VALID_MODES:
            state.mode = meta["mode"]
        if meta.get("workspace"):
            state.workspace = Path(meta["workspace"]).expanduser().resolve()
        if "rom_path" in meta:
            state.rom_path = Path(meta["rom_path"]).expanduser().resolve() if meta["rom_path"] else None
        if "tools_enabled" in meta:
            state.tools_enabled = bool(meta["tools_enabled"])
        if "broadcast_models" in meta and isinstance(meta["broadcast_models"], list):
            state.broadcast_models = [str(value).strip() for value in meta["broadcast_models"] if str(value).strip()]
        if meta.get("llamacpp_model"):
            state.llamacpp_model = meta["llamacpp_model"]
        await refresh_tool_bridge(state)
        # Restore per-model engine messages
        for engine in state.engines.values():
            engine.reset()
        for model_name, msgs in model_msgs.items():
            engine = get_engine(state, model_name)
            engine.messages = msgs
        state.console.print(f"Resumed session: {match['name']} ({len(model_msgs)} model(s), {sum(len(m) for m in model_msgs.values())} messages)")
        return True

    if command == "/compact":
        # Summarize current model's conversation via the model itself
        current_model = active_model_name(state)
        engine = state.engines.get(engine_key(state.backend_name, current_model))
        if not engine or len(engine.messages) < 3:
            state.console.print("Not enough history to compact.")
            return True
        state.console.print("[dim]Compacting conversation...[/dim]")
        targets = preview_targets(state, "")
        target = targets[0] if targets else ModelConfig(name=current_model, model_id=current_model)
        request_name = get_backend(state).resolve_request_model(target, state.auto_load)
        summary_parts: list[str] = []
        replaced_count = len(engine.messages)
        async for event in engine.chat(
            message="Summarize our conversation so far in 2-3 paragraphs, preserving key facts, decisions, and code references.",
            model_id=request_name,
            system="",
            use_tools=False,
        ):
            if isinstance(event, TextEvent):
                summary_parts.append(event.text)
        summary = "".join(summary_parts)
        if not summary.strip():
            state.console.print("[red]Compaction failed — no summary generated.[/red]")
            return True
        # Save compact record
        if state.session:
            state.session.save_compact(current_model, summary, replaced_count)
        # Replace engine history with system prompt + summary
        system_prompt = merge_system_prompts(build_system_prompt(state), target.system_prompt)
        engine.messages = [
            {"role": "system", "content": system_prompt},
            {"role": "assistant", "content": summary},
        ]
        state.console.print(f"Compacted {replaced_count} messages into summary.")
        return True

    if command == "/export-training":
        if not state.session or not state.session.path:
            state.console.print("No active session to export.")
            return True
        if len(parts) >= 2:
            out_path = Path(parts[1]).expanduser().resolve()
        else:
            out_path = state.session.path.with_suffix(".training.jsonl")
        count = export_training(state.session.path, out_path)
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

    # Start session
    state.session = Session(SESSION_DIR)
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
    parser.add_argument("--llamacpp-api-base", default=os.environ.get("LLAMACPP_BASE_URL", DEFAULT_LLAMACPP_API_BASE))
    parser.add_argument("--llamacpp-model", default=DEFAULT_LLAMACPP_MODEL)
    parser.add_argument("--workspace", default=str(DEFAULT_WORKSPACE))
    parser.add_argument("--rom", default=str(DEFAULT_ROM), help="Primary ROM path (use '' to disable)")
    parser.add_argument("--model", default="nayru")
    parser.add_argument("--mode", default="manual", choices=sorted(VALID_MODES))
    parser.add_argument("--broadcast-models", default=",".join(DEFAULT_BROADCAST_MODELS))
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--tools", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--auto-load", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--list-models", action="store_true")
    parser.add_argument("--list-loaded", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--route-only", action="store_true")
    parser.add_argument("--prompt", default="")
    return parser.parse_args()


async def build_state(args: argparse.Namespace) -> AppState:
    console = Console()
    models, routers = load_registry(Path(args.registry).expanduser())
    workspace = Path(args.workspace).expanduser().resolve()
    studio_api_base = args.studio_api_base.rstrip("/")
    llamacpp_api_base = args.llamacpp_api_base.rstrip("/")
    active_api_base = studio_api_base if args.backend == "studio" else llamacpp_api_base
    if args.backend == "studio":
        ensure_server(args.host, args.port)

    bridge = None
    bridge_errors: list[str] = []
    should_connect_tools = args.tools and not (
        args.list_models or args.list_loaded or args.status or args.route_only
    )
    if should_connect_tools:
        bridge, bridge_errors = await connect_tool_bridge(workspace, Path(args.mcp_config).expanduser())

    return AppState(
        console=console,
        host=args.host,
        port=args.port,
        api_base=active_api_base,
        backend_name=args.backend,
        studio_api_base=studio_api_base,
        llamacpp_api_base=llamacpp_api_base,
        llamacpp_model=args.llamacpp_model,
        registry_path=Path(args.registry).expanduser(),
        mcp_path=Path(args.mcp_config).expanduser(),
        models=models,
        routers=routers,
        active_model=args.model,
        mode=args.mode,
        auto_load=args.auto_load,
        workspace=workspace,
        rom_path=None if not args.rom else Path(args.rom).expanduser().resolve(),
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        broadcast_models=[v.strip() for v in args.broadcast_models.split(",") if v.strip()],
        tools_enabled=args.tools,
        bridge=bridge,
        bridge_errors=bridge_errors,
    )


async def main() -> int:
    args = parse_args()
    state = await build_state(args)
    try:
        if args.list_models:
            render_model_table(state)
            return 0
        if args.list_loaded:
            await list_loaded_api(state)
            return 0
        if args.status:
            print_status(state)
            return 0
        if args.prompt:
            if args.route_only:
                state.console.print(" -> ".join(target.name for target in preview_targets(state, args.prompt)))
                return 0
            await send_prompt(state, args.prompt)
            return 0
        return await run_repl(state)
    finally:
        for engine in state.engines.values():
            await engine.close()
        if state.bridge:
            await state.bridge.close()


def run() -> int:
    return asyncio.run(main())
