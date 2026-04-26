"""Subagent runner: spawn ephemeral ChatEngine instances for delegated work.

A subagent is a fresh conversation with its own context window, system
prompt, tool profile, and bounded tool-round budget. It runs to
completion and returns a structured result to the caller — useful for
parallelizing specialist work (e.g., ASM review, debugging, lore
lookup) or for a cloud planner to delegate to local specialists.

Subagents share the parent's tool bridge by default (to avoid spinning
up duplicate MCP servers) but get their own ChatEngine and message
history, so their work doesn't pollute the parent's context.
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field
from inspect import isawaitable
from typing import Awaitable, Callable

from app.runtime import (
    build_local_identity_prompt,
    build_tool_bias_prompt,
    build_tool_use_prompt,
    merge_system_prompts,
    resolve_oracle_profile_system_prompts,
)
from core.config import ModelConfig
from core.engine import (
    ChatEngine, ChatEvent, DoneEvent, ErrorEvent, TextEvent, ThinkingEvent,
    ToolCallEvent, ToolResultEvent,
)
from core.provider import Provider, create_provider
from core.tool_bridge import CompositeBridge, ToolBridge


# ---------------------------------------------------------------------------
# Active-subagent context (for hooks that need to know who initiated a call)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SubagentContext:
    """Identifying metadata for a currently-running subagent invocation.

    Exposed to hooks (e.g. permission gates) via the module-level ContextVar
    so they can attribute tool calls back to the subagent that triggered
    them without needing the subagent id threaded through every signature.
    """

    id: str
    name: str
    model_name: str
    depth: int = 0


_current_subagent: ContextVar[SubagentContext | None] = ContextVar(
    "z3cli_current_subagent", default=None,
)


def get_current_subagent() -> SubagentContext | None:
    """Return the SubagentContext for the currently-running subagent, if any."""
    return _current_subagent.get()


# ---------------------------------------------------------------------------
# Configuration & result
# ---------------------------------------------------------------------------

@dataclass
class SubagentConfig:
    """Configuration for a subagent invocation."""

    name: str                          # label for this subagent instance
    model: ModelConfig                 # which model to use
    task_prompt: str = ""              # task-specific briefing appended to system
    tool_profile: str = ""             # override model's profile ("" uses model default)
    max_rounds: int = 4                # tool-calling rounds budget
    max_tokens: int = 2048
    temperature: float = 0.3
    thinking: bool = False
    strip_thinking: bool = True
    max_tool_result: int = 4000        # truncate large tool results
    parent_turn_id: str = ""           # which parent turn spawned this
    depth: int = 0                     # 0=top-level, 1=spawned by top-level, etc.
    parent_chain: list[str] = field(default_factory=list)  # ancestor model names
    parent_id: str = ""                # parent subagent id for UI treeing
    timeout_seconds: float = 300.0     # wall-clock limit for the entire run (0 = no limit)


@dataclass
class SubagentResult:
    """Outcome of a subagent run."""

    id: str
    name: str
    model_name: str
    text: str = ""                     # final assistant text
    thinking: str = ""                 # collected thinking content
    tool_calls: int = 0                # count of tool calls executed
    prompt_tokens: int = 0
    completion_tokens: int = 0
    error: str = ""                    # non-empty on failure
    cancelled: bool = False


# ---------------------------------------------------------------------------
# Events (re-emitted with subagent id attached)
# ---------------------------------------------------------------------------

@dataclass
class SubagentStartEvent:
    id: str
    name: str
    model_name: str
    provider: str
    depth: int = 0
    parent_id: str = ""


@dataclass
class SubagentTextEvent:
    id: str
    delta: str


@dataclass
class SubagentThinkingEvent:
    id: str
    delta: str


@dataclass
class SubagentToolCallEvent:
    id: str
    name: str
    server: str
    arguments: str
    call_id: str


@dataclass
class SubagentToolResultEvent:
    id: str
    name: str
    result: str
    call_id: str


@dataclass
class SubagentDoneEvent:
    id: str
    result: SubagentResult


@dataclass
class SubagentErrorEvent:
    id: str
    message: str


SubagentEvent = (
    SubagentStartEvent | SubagentTextEvent | SubagentThinkingEvent
    | SubagentToolCallEvent | SubagentToolResultEvent
    | SubagentDoneEvent | SubagentErrorEvent
)

SubagentEventCallback = Callable[[SubagentEvent], Awaitable[None]]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

class SubagentRunner:
    """Spawns and manages subagent invocations.

    Each spawn creates a fresh ChatEngine with the appropriate provider
    and tool bridge. Multiple subagents can run concurrently — just await
    their tasks in parallel with asyncio.gather.
    """

    def __init__(
        self,
        bridge: ToolBridge | None = None,
        permission_hook=None,
        bridge_wrapper: Callable[[ToolBridge | None, ModelConfig], ToolBridge | None] | None = None,
        event_hook: SubagentEventCallback | None = None,
        prompt_enricher: Callable[[str, ModelConfig], Awaitable[str]] | None = None,
        system_context_resolver: Callable[[ModelConfig, str], str | Awaitable[str]] | None = None,
        max_depth: int = 2,
        models: dict[str, ModelConfig] | None = None,
        expose_subagent_bridge_to_children: bool = True,
    ):
        """
        Args:
            bridge: Shared tool bridge. Subagents use this (wrapped by their
                tool_profile if set) unless the caller overrides per-spawn.
            permission_hook: Optional permission gate, same signature as
                ChatEngine's. Applied to subagent tool calls.
            bridge_wrapper: Optional callable(bridge, model) -> bridge
                for applying model-specific bridge wrappers. This is where
                callers inject tool adapters, deferred-tool search, and
                read-only wrappers. If None, the bridge is used as-is.
            max_depth: Maximum nesting depth for subagent delegation. A
                subagent whose ``config.depth`` exceeds this cap is rejected
                without running. Default 2 allows 3 levels total (0, 1, 2).
            models: Optional registry of available models. Required to let
                subagents themselves delegate via a nested SubagentBridge.
            expose_subagent_bridge_to_children: When True (and ``models`` is
                provided), spawned subagents get a SubagentBridge of their
                own so they can delegate further (subject to ``max_depth``).
        """
        self._bridge = bridge
        self._permission_hook = permission_hook
        self._bridge_wrapper = bridge_wrapper
        self._event_hook = event_hook
        self._prompt_enricher = prompt_enricher
        self._system_context_resolver = system_context_resolver
        self._max_depth = max_depth
        self._models = models
        self._expose_subagent_bridge_to_children = expose_subagent_bridge_to_children
        self._counter = 0
        self._active: dict[str, asyncio.Task] = {}

    @property
    def max_depth(self) -> int:
        return self._max_depth

    def set_bridge(self, bridge: ToolBridge | None) -> None:
        """Update the shared bridge (e.g. after re-connecting MCP servers)."""
        self._bridge = bridge

    def set_event_hook(self, event_hook: SubagentEventCallback | None) -> None:
        """Update the default event callback used for nested subagent runs."""
        self._event_hook = event_hook

    def set_prompt_enricher(self, prompt_enricher: Callable[[str, ModelConfig], Awaitable[str]] | None) -> None:
        """Update the prompt enricher used before spawning child subagents."""
        self._prompt_enricher = prompt_enricher

    def set_system_context_resolver(
        self,
        system_context_resolver: Callable[[ModelConfig, str], str | Awaitable[str]] | None,
    ) -> None:
        """Update the model-aware system context resolver for child subagents."""
        self._system_context_resolver = system_context_resolver

    async def enrich_prompt(self, prompt: str, model: ModelConfig) -> str:
        """Apply the configured prompt enricher when present."""
        if self._prompt_enricher is None:
            return prompt
        return await self._prompt_enricher(prompt, model)

    async def resolve_system_context(self, model: ModelConfig, prompt: str = "") -> str:
        """Resolve harness/system context for a child model when configured."""
        if self._system_context_resolver is None:
            return ""
        context = self._system_context_resolver(model, prompt)
        if isawaitable(context):
            context = await context
        return str(context or "")

    def _next_id(self, name: str) -> str:
        self._counter += 1
        return f"sub-{self._counter}-{name}"

    def _build_provider(self, model: ModelConfig) -> tuple[Provider, bool]:
        """Create a provider for the subagent. Returns (provider, owns_it)."""
        if model.is_cloud:
            return (
                create_provider(
                    provider_name=model.provider,
                    api_base=model.api_base,
                    api_key=model.resolve_api_key(),
                    default_model=model.model_id,
                ),
                True,
            )
        # Local models need an api_base — caller supplies via model.api_base
        # or falls back to the default LM Studio URL
        api_base = model.api_base or "http://127.0.0.1:1234/v1"
        return (
            create_provider(provider_name="studio", api_base=api_base),
            True,
        )

    @staticmethod
    def _strip_subagent_bridges(bridge: ToolBridge | None) -> ToolBridge | None:
        """Remove inherited SubagentBridge layers from a base tool surface."""
        if bridge is None:
            return None
        from core.subagent_bridge import SubagentBridge

        if isinstance(bridge, SubagentBridge):
            return None
        if isinstance(bridge, CompositeBridge):
            children = [
                child
                for child in bridge.bridges
                if not isinstance(child, SubagentBridge)
            ]
            if not children:
                return None
            if len(children) == 1:
                return children[0]
            return CompositeBridge(list(children))
        return bridge

    async def spawn(
        self,
        config: SubagentConfig,
        prompt: str,
        *,
        system_context: str = "",
        on_event: SubagentEventCallback | None = None,
        bridge_override: ToolBridge | None = None,
        provider_override: Provider | None = None,
    ) -> SubagentResult:
        """Run a subagent to completion and return the result.

        Args:
            config: Subagent configuration.
            prompt: The user-level prompt to send to the subagent.
            system_context: Additional harness context prepended to the
                subagent's system prompt (e.g. workspace/ROM info).
            on_event: Optional callback invoked for each streaming event.
                Useful for forwarding to an IPC layer.
            bridge_override: Use this bridge instead of the runner's default.
            provider_override: Use this provider instead of building one
                from the model config.
        """
        sub_id = self._next_id(config.name)
        event_callback = on_event or self._event_hook

        # Enforce depth cap and cycle detection BEFORE spawning anything.
        if config.depth > self._max_depth:
            result = SubagentResult(
                id=sub_id,
                name=config.name,
                model_name=config.model.name,
                error=f"max subagent depth ({self._max_depth}) exceeded",
            )
            if event_callback is not None:
                await event_callback(SubagentErrorEvent(id=sub_id, message=result.error))
                await event_callback(SubagentDoneEvent(id=sub_id, result=result))
            return result

        if config.model.name in config.parent_chain:
            chain = " -> ".join([*config.parent_chain, config.model.name])
            result = SubagentResult(
                id=sub_id,
                name=config.name,
                model_name=config.model.name,
                error=f"cycle detected in subagent chain: {chain}",
            )
            if event_callback is not None:
                await event_callback(SubagentErrorEvent(id=sub_id, message=result.error))
                await event_callback(SubagentDoneEvent(id=sub_id, result=result))
            return result

        # Build provider
        if provider_override is not None:
            provider = provider_override
            owns_provider = False
        else:
            provider, owns_provider = self._build_provider(config.model)

        # Build bridge (model-specific wrappers such as adapters, deferred
        # tool search, and read-only guards are delegated to bridge_wrapper).
        base_bridge = bridge_override if bridge_override is not None else self._bridge
        base_bridge = self._strip_subagent_bridges(base_bridge)
        active_profile = config.tool_profile or config.model.tool_profile
        if base_bridge is not None and self._bridge_wrapper is not None:
            effective_bridge = self._bridge_wrapper(base_bridge, config.model)
        else:
            effective_bridge = base_bridge

        # Expose a nested SubagentBridge so the child can itself delegate
        # (bounded by max_depth / cycle detection). Only compose when we
        # have a models registry and the feature hasn't been disabled.
        if (
            self._expose_subagent_bridge_to_children
            and self._models is not None
            and config.depth <= self._max_depth
        ):
            # Import here to avoid a circular import at module load time.
            from core.subagent_bridge import SubagentBridge
            from core.tool_bridge import CompositeBridge

            child_depth = config.depth + 1
            if child_depth <= self._max_depth:
                nested = SubagentBridge(
                    runner=self,
                    models=self._models,
                    system_context_fn=self.resolve_system_context,
                    current_depth=config.depth,
                    parent_chain=tuple(config.parent_chain),
                    parent_model=config.model.name,
                    parent_id=sub_id,
                )
                if effective_bridge is None:
                    effective_bridge = nested
                else:
                    effective_bridge = CompositeBridge([effective_bridge, nested])

        tools_available = bool(effective_bridge and config.model.tools_enabled)
        use_native_tools = bool(tools_available and config.model.native_tools)

        # Mirror the top-level chat path so delegated runs inherit the same
        # local identity guardrails and manual/deferred tool guidance.
        system = merge_system_prompts(
            system_context,
            build_local_identity_prompt(config.model),
            build_tool_use_prompt(
                tools_available,
                active_profile,
                deferred_tools=config.model.deferred_tools,
                native_tools=config.model.native_tools,
            ),
            build_tool_bias_prompt(
                prompt,
                tools_available,
                active_profile,
                deferred_tools=config.model.deferred_tools,
                native_tools=config.model.native_tools,
            ),
            *resolve_oracle_profile_system_prompts(prompt),
            config.model.system_prompt,
            config.task_prompt,
        )

        # Create engine
        engine = ChatEngine(
            bridge=effective_bridge,
            permission_hook=self._permission_hook,
            provider=provider,
        )

        result = SubagentResult(
            id=sub_id,
            name=config.name,
            model_name=config.model.name,
        )

        # Emit start event
        if event_callback is not None:
            await event_callback(SubagentStartEvent(
                id=sub_id,
                name=config.name,
                model_name=config.model.name,
                provider=provider.name,
                depth=config.depth,
                parent_id=config.parent_id,
            ))

        # Expose the subagent identity to hooks running inside this task via
        # a ContextVar. Token is captured inside the try so a raise *at* the
        # set-call has no window to leak state before finally can reset it.
        ctx_token = None
        try:
            ctx_token = _current_subagent.set(SubagentContext(
                id=sub_id,
                name=config.name,
                model_name=config.model.name,
                depth=config.depth,
            ))
            timeout_ctx = (
                asyncio.timeout(config.timeout_seconds)
                if config.timeout_seconds > 0
                else asyncio.timeout(None)
            )
            async with timeout_ctx:
                async for event in engine.chat(
                    message=prompt,
                    model_id=config.model.model_id,
                    system=system,
                    temperature=config.temperature,
                    max_tokens=config.max_tokens,
                    use_tools=use_native_tools,
                    max_rounds=config.max_rounds,
                    thinking=config.thinking,
                    strip_thinking=config.strip_thinking,
                    max_tool_result=config.max_tool_result,
                ):
                    await self._forward_event(sub_id, event, result, event_callback)

        except asyncio.TimeoutError:
            result.error = f"subagent timed out after {config.timeout_seconds:.0f}s"
            engine.cancel()
            if event_callback is not None:
                await event_callback(SubagentErrorEvent(id=sub_id, message=result.error))
        except asyncio.CancelledError:
            result.cancelled = True
            engine.cancel()
            if event_callback is not None:
                await event_callback(SubagentErrorEvent(id=sub_id, message="cancelled"))
            raise
        except Exception as exc:
            result.error = str(exc)
            if event_callback is not None:
                await event_callback(SubagentErrorEvent(id=sub_id, message=result.error))
        finally:
            if ctx_token is not None:
                _current_subagent.reset(ctx_token)
            if owns_provider:
                try:
                    await engine.close()
                except Exception:
                    pass

        # Emit done event
        if event_callback is not None:
            await event_callback(SubagentDoneEvent(id=sub_id, result=result))

        return result

    async def _forward_event(
        self,
        sub_id: str,
        event: ChatEvent,
        result: SubagentResult,
        on_event: SubagentEventCallback | None,
    ) -> None:
        """Translate ChatEngine events into subagent events and update result."""
        if isinstance(event, TextEvent):
            result.text += event.text
            if on_event is not None:
                await on_event(SubagentTextEvent(id=sub_id, delta=event.text))
        elif isinstance(event, ThinkingEvent):
            result.thinking += event.text
            if on_event is not None:
                await on_event(SubagentThinkingEvent(id=sub_id, delta=event.text))
        elif isinstance(event, ToolCallEvent):
            result.tool_calls += 1
            if on_event is not None:
                await on_event(SubagentToolCallEvent(
                    id=sub_id,
                    name=event.name,
                    server=event.server,
                    arguments=event.arguments,
                    call_id=event.call_id,
                ))
        elif isinstance(event, ToolResultEvent):
            if on_event is not None:
                await on_event(SubagentToolResultEvent(
                    id=sub_id,
                    name=event.name,
                    result=event.result,
                    call_id=event.call_id,
                ))
        elif isinstance(event, DoneEvent):
            result.prompt_tokens = event.prompt_tokens
            result.completion_tokens = event.completion_tokens
        elif isinstance(event, ErrorEvent):
            result.error = event.message
            if on_event is not None:
                await on_event(SubagentErrorEvent(id=sub_id, message=event.message))

    async def spawn_many(
        self,
        invocations: list[tuple[SubagentConfig, str]],
        *,
        system_context: str = "",
        on_event: SubagentEventCallback | None = None,
    ) -> list[SubagentResult]:
        """Run multiple subagents in parallel, collect all results.

        Useful when the main model (or user) wants several specialists
        to work on related subtasks concurrently.
        """
        tasks = [
            asyncio.create_task(
                self.spawn(
                    config,
                    prompt,
                    system_context=system_context,
                    on_event=on_event,
                )
            )
            for config, prompt in invocations
        ]
        try:
            return await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise


def format_subagent_summary(results: list[SubagentResult]) -> str:
    """Format a compact summary of subagent results for injection into
    the parent conversation."""
    lines = [f"# Subagent Results ({len(results)} agents)", ""]
    for result in results:
        header = f"## {result.name} ({result.model_name})"
        if result.error:
            lines.extend([header, f"**Error:** {result.error}", ""])
            continue
        if result.cancelled:
            lines.extend([header, "**Status:** cancelled", ""])
            continue
        stats = f"tokens: {result.prompt_tokens}/{result.completion_tokens}"
        if result.tool_calls:
            stats += f"  •  tools: {result.tool_calls}"
        lines.extend([
            header,
            f"_{stats}_",
            "",
            result.text.strip() or "_(no output)_",
            "",
        ])
    return "\n".join(lines)
