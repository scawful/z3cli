"""Chat engine: orchestrates streaming completions and tool-calling loops.

Provider-agnostic: delegates wire-format details to a Provider instance
while owning the tool-call → execute → re-query loop, thinking-block
parsing, cancellation, and history management.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
from dataclasses import dataclass, field
from typing import AsyncGenerator

import httpx

from z3cli.core.compaction import ConversationCompactor
from z3cli.core.provider import (
    CompletionRequest, CompletionChunk, LocalProvider, Provider, ProviderError,
)
from z3cli.core.tool_bridge import ToolBridge


# ---------------------------------------------------------------------------
# Events yielded by the chat generator
# ---------------------------------------------------------------------------

@dataclass
class TextEvent:
    """A chunk of streaming text content."""
    text: str

@dataclass
class ThinkingEvent:
    """A chunk of model thinking/reasoning content."""
    text: str

@dataclass
class ToolCallEvent:
    """The model is invoking a tool."""
    name: str
    arguments: str
    server: str = ""
    call_id: str = ""

@dataclass
class ToolResultEvent:
    """Result returned from a tool call."""
    name: str
    result: str
    server: str = ""
    call_id: str = ""

@dataclass
class ErrorEvent:
    """Something went wrong."""
    message: str

@dataclass
class DoneEvent:
    """Response complete."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0

@dataclass
class CompactionEvent:
    """History was compacted to fit the context budget."""
    summary: str
    replaced_count: int
    tokens_before: int
    tokens_after: int


ChatEvent = (
    TextEvent | ThinkingEvent | ToolCallEvent | ToolResultEvent
    | ErrorEvent | DoneEvent | CompactionEvent
)


@dataclass
class _ChatState:
    """Accumulator threaded through chat() helpers.

    * Token counters accrue across tool-calling rounds.
    * ``cancelled`` is set when the user aborts or the provider stream
      terminated while the cancel event was set.
    * ``done`` is set when a helper has yielded the terminal DoneEvent
      (or ErrorEvent+return) so the orchestrator should not continue.
    """

    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_cache_creation: int = 0
    total_cache_read: int = 0
    cancelled: bool = False
    done: bool = False


@dataclass
class _RoundOutput:
    """Per-round results populated by :meth:`ChatEngine._stream_round`."""

    content: str = ""
    thinking_content: str = ""
    tool_calls: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Thinking block parser (for local models that use XML <think> blocks)
# ---------------------------------------------------------------------------

class _ThinkingParser:
    """State machine that splits streaming content into thinking vs text.

    Handles ``<think>...</think>`` blocks that may arrive split across
    multiple SSE chunks.
    """

    _OPEN = "<think>"
    _CLOSE = "</think>"

    def __init__(self) -> None:
        self._in_thinking = False
        self._pending = ""  # buffered chars when a partial tag might be forming

    def feed(self, chunk: str) -> list[TextEvent | ThinkingEvent]:
        """Feed a content chunk and return events to yield."""
        events: list[TextEvent | ThinkingEvent] = []
        self._pending += chunk

        while self._pending:
            tag = self._CLOSE if self._in_thinking else self._OPEN

            idx = self._pending.find(tag)
            if idx >= 0:
                # Emit everything before the tag
                before = self._pending[:idx]
                if before:
                    events.append(
                        ThinkingEvent(before) if self._in_thinking else TextEvent(before)
                    )
                self._pending = self._pending[idx + len(tag) :]
                self._in_thinking = not self._in_thinking
                continue

            # Check if the end of _pending could be the start of a tag
            # (partial match). Buffer it for the next feed().
            partial_len = self._partial_match(self._pending, tag)
            if partial_len > 0:
                safe = self._pending[: -partial_len]
                if safe:
                    events.append(
                        ThinkingEvent(safe) if self._in_thinking else TextEvent(safe)
                    )
                self._pending = self._pending[-partial_len:]
                break  # wait for more data
            else:
                # No partial match — flush everything
                events.append(
                    ThinkingEvent(self._pending) if self._in_thinking else TextEvent(self._pending)
                )
                self._pending = ""

        return events

    def flush(self) -> list[TextEvent | ThinkingEvent]:
        """Flush any remaining buffered content."""
        events: list[TextEvent | ThinkingEvent] = []
        if self._pending:
            events.append(
                ThinkingEvent(self._pending) if self._in_thinking else TextEvent(self._pending)
            )
            self._pending = ""
        return events

    @staticmethod
    def _partial_match(text: str, tag: str) -> int:
        """Return the length of the longest suffix of *text* that is a prefix of *tag*."""
        for length in range(min(len(text), len(tag) - 1), 0, -1):
            if text[-length:] == tag[:length]:
                return length
        return 0


_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)
_TOOL_CALL_RE = re.compile(
    r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL,
)
_SHORTHAND_TOOL_CALL_RE = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_-]*)\s*(\(\s*\{.*\}\s*\)|\{.*\})\s*$",
    re.DOTALL,
)
_PROVIDER_STATUS_RE = re.compile(r"\b(?:API|Anthropic API)\s+(\d{3})\b")


def _strip_think_blocks(text: str) -> str:
    """Remove ``<think>...</think>`` blocks from text for history storage."""
    return _THINK_RE.sub("", text).lstrip()


def _extract_xml_tool_calls(text: str) -> list[dict]:
    """Parse ``<tool_call>`` XML blocks from text (Qwen3 reasoning path).

    Returns a list of dicts with 'name' and 'arguments' keys, or an
    empty list if no valid tool calls are found.
    """
    result = []
    for match in _TOOL_CALL_RE.finditer(text):
        try:
            call = json.loads(match.group(1))
            name = call.get("name", "")
            args = call.get("arguments", {})
            if name:
                result.append({
                    "id": f"xml_{len(result)}",
                    "name": name,
                    "arguments": json.dumps(args) if isinstance(args, dict) else str(args),
                })
        except json.JSONDecodeError:
            continue
    if result:
        return result

    shorthand = _SHORTHAND_TOOL_CALL_RE.match(text.strip())
    if shorthand is None:
        return result
    name = shorthand.group(1)
    raw_args = shorthand.group(2).strip()
    if raw_args.startswith("(") and raw_args.endswith(")"):
        raw_args = raw_args[1:-1].strip()
    try:
        args = json.loads(raw_args)
    except json.JSONDecodeError:
        return result
    return [{
        "id": "xml_0",
        "name": name,
        "arguments": json.dumps(args) if isinstance(args, dict) else str(args),
    }]
    return result


def _truncate_tool_result(result: str, max_chars: int) -> str:
    """Truncate a tool result if it exceeds *max_chars*.

    Preserves the first and last portions of the result so the model
    sees context from both ends, with a truncation marker in the middle.
    """
    if max_chars <= 0 or len(result) <= max_chars:
        return result
    keep = max_chars // 2
    lines = result.splitlines()
    total_lines = len(lines)
    return (
        result[:keep]
        + f"\n\n... [truncated {len(result) - max_chars} chars, {total_lines} total lines] ...\n\n"
        + result[-keep:]
    )


def _is_retryable_provider_error(error: ProviderError) -> bool:
    """Return True when a provider error is likely transient."""
    match = _PROVIDER_STATUS_RE.search(str(error))
    if match is None:
        return False
    try:
        status = int(match.group(1))
    except ValueError:
        return False
    # 429, 5xx are usually transient overload/rate-limit failures.
    return status == 429 or status >= 500


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class ChatEngine:
    def __init__(
        self,
        api_base: str = "",
        bridge: ToolBridge | None = None,
        permission_hook=None,
        post_tool_hook=None,
        tool_invocation_hook=None,
        provider: Provider | None = None,
        compactor: ConversationCompactor | None = None,
        provider_max_retries: int = 0,
        provider_retry_base_s: float = 0.75,
        tool_timeout_s: float = 120.0,
        permission_hook_timeout_s: float = 0.0,
    ):
        """
        Args:
            api_base: Base URL for OpenAI-compatible API. Used to create a
                LocalProvider if *provider* is not given. Kept for backward
                compatibility.
            bridge: Tool bridge for tool execution.
            permission_hook: optional async callable(tool_name, arguments_json,
                server, call_id) -> bool. Called before each tool execution.
                Return False to deny.
            post_tool_hook: optional async callable(tool_name, arguments_json,
                result, server, call_id) -> str. Called after each tool
                execution and may rewrite the result.
            tool_invocation_hook: optional async callable(payload: dict) -> None
                called once per tool invocation with keys tool, arguments,
                server, call_id, duration_ms, status (success|timeout|
                cancelled|error|denied), error. Exceptions are swallowed so
                telemetry never breaks the chat loop.
            provider: A Provider instance. If given, *api_base* is ignored
                for completions (but kept as a reference attribute).
            provider_max_retries: Retry attempts for transient provider
                stream failures before surfacing an error.
            provider_retry_base_s: Base backoff duration in seconds.
                Retries use exponential backoff: base * 2^attempt.
            tool_timeout_s: Max wall-clock seconds for a single tool call.
                Set to 0 to disable.
            permission_hook_timeout_s: Max wait for the permission hook itself.
                Set to 0 to disable. Frontends that present approval UIs usually
                handle their own timeout and should leave this disabled.
        """
        self.api_base = api_base
        self.bridge = bridge
        self._permission_hook = permission_hook
        self._post_tool_hook = post_tool_hook
        self._tool_invocation_hook = tool_invocation_hook
        self._compactor = compactor

        # Provider: explicit or auto-created from api_base
        if provider is not None:
            self._provider = provider
            self._owns_provider = False
        else:
            self._provider = LocalProvider(api_base=api_base or "http://127.0.0.1:1234/v1")
            self._owns_provider = True

        self.messages: list[dict] = []
        self.connected = False
        self._cancel_event = asyncio.Event()
        self.provider_max_retries = max(0, int(provider_max_retries))
        self.provider_retry_base_s = max(0.0, float(provider_retry_base_s))
        self.tool_timeout_s = max(0.0, float(tool_timeout_s))
        self.provider_retry_count = 0
        self.provider_retry_backoff_ms = 0
        self.provider_error_count = 0
        self.tool_timeout_count = 0
        # Hook/compaction bounded-wait guardrails. Zero disables the timeout.
        self.permission_hook_timeout_s = max(0.0, float(permission_hook_timeout_s))
        self.post_tool_hook_timeout_s = 30.0
        self.compaction_timeout_s = 60.0
        self.hook_timeout_count = 0
        self.compaction_timeout_count = 0

    @property
    def provider(self) -> Provider:
        return self._provider

    @property
    def compactor(self) -> ConversationCompactor | None:
        return self._compactor

    def set_compactor(self, compactor: ConversationCompactor | None) -> None:
        """Attach or replace the conversation compactor."""
        self._compactor = compactor

    async def compact_now(self, force: bool = False) -> "CompactionEvent | None":
        """Run compaction immediately. Returns the event if messages changed."""
        if self._compactor is None:
            return None
        new_messages, result = await self._compactor.compact(
            self.messages, force=force,
        )
        if not result.compacted:
            return None
        self.messages = new_messages
        return CompactionEvent(
            summary=result.summary,
            replaced_count=result.replaced_count,
            tokens_before=result.tokens_before,
            tokens_after=result.tokens_after,
        )

    def cancel(self) -> None:
        """Signal the engine to abort the current streaming response."""
        self._cancel_event.set()

    def set_tool_invocation_hook(self, hook) -> None:
        """Attach or replace the tool-invocation telemetry hook."""
        self._tool_invocation_hook = hook

    async def _emit_tool_invocation(
        self,
        *,
        tool: str,
        arguments: str,
        server: str,
        call_id: str,
        duration_ms: float,
        status: str,
        error: str = "",
    ) -> None:
        if self._tool_invocation_hook is None:
            return
        try:
            await self._tool_invocation_hook({
                "tool": tool,
                "arguments": arguments,
                "server": server,
                "call_id": call_id,
                "duration_ms": duration_ms,
                "status": status,
                "error": error,
            })
        except Exception:
            # Telemetry must never break the chat loop.
            pass

    # -- connection helpers --------------------------------------------------

    async def check_connection(self) -> bool:
        self.connected = await self._provider.check_connection()
        return self.connected

    async def list_loaded_models(self) -> list[str]:
        # Only local providers support listing loaded models
        if isinstance(self._provider, LocalProvider):
            try:
                resp = await self._provider._client.get("/models", timeout=5.0)
                if resp.status_code == 200:
                    return [m["id"] for m in resp.json().get("data", [])]
            except Exception:
                pass
        return []

    # -- history management --------------------------------------------------

    def reset(self):
        self.messages.clear()

    def set_system(self, prompt: str):
        if not prompt:
            return
        if self.messages and self.messages[0]["role"] == "system":
            self.messages[0]["content"] = prompt
        else:
            self.messages.insert(0, {"role": "system", "content": prompt})

    # -- main chat method ----------------------------------------------------

    async def chat(
        self,
        message: str,
        model_id: str,
        system: str = "",
        temperature: float = 0.3,
        max_tokens: int = 2048,
        use_tools: bool = True,
        max_rounds: int = 8,
        thinking: bool = False,
        strip_thinking: bool = True,
        max_tool_result: int = 0,
        prompt_cache: bool = True,
    ) -> AsyncGenerator[ChatEvent, None]:
        """Send a user message and yield events as the response streams.

        Automatically executes tool calls and re-queries until the model
        produces a final text response or max_rounds is exhausted.

        When *thinking* is True, ``<think>...</think>`` blocks in the
        response are parsed and emitted as :class:`ThinkingEvent` instead
        of :class:`TextEvent`.  If *strip_thinking* is also True (the
        default), thinking content is removed from the message stored in
        conversation history to save context window.

        When *max_tool_result* > 0, tool results longer than that many
        characters are truncated before being stored in conversation
        history (the full result is still yielded in the event stream).
        """
        if system:
            self.set_system(system)

        self._cancel_event.clear()

        async for evt in self._maybe_compact():
            yield evt

        self.messages.append({"role": "user", "content": message})

        state = _ChatState()
        # Native thinking happens on the provider side for Anthropic;
        # local providers expose <think> blocks that the XML parser picks up.
        use_xml_thinking = thinking and self._provider.name not in ("anthropic",)

        for round_idx in range(max_rounds + 1):
            output = _RoundOutput()
            async for evt in self._stream_round(
                state=state,
                output=output,
                model_id=model_id,
                system=system,
                temperature=temperature,
                max_tokens=max_tokens,
                use_tools=use_tools,
                use_xml_thinking=use_xml_thinking,
                thinking=thinking,
                prompt_cache=prompt_cache,
            ):
                yield evt

            if state.done:
                return

            history_content = output.content
            if thinking and strip_thinking and output.thinking_content:
                history_content = _strip_think_blocks(output.content)

            if state.cancelled:
                if output.content.strip():
                    self.messages.append({"role": "assistant", "content": history_content})
                yield self._build_done_event(state)
                return

            # Fallback path: some local models emit tool calls as XML in
            # reasoning content rather than in the tool_calls delta.
            tool_calls = output.tool_calls
            if not tool_calls and output.content:
                xml_calls = _extract_xml_tool_calls(output.content)
                if xml_calls:
                    tool_calls = xml_calls

            if not tool_calls:
                self.messages.append({"role": "assistant", "content": history_content})
                yield self._build_done_event(state)
                return

            async for evt in self._execute_tool_calls(
                round_idx=round_idx,
                tool_calls=tool_calls,
                history_content=history_content,
                max_tool_result=max_tool_result,
                state=state,
            ):
                yield evt

            if state.done:
                return
            if state.cancelled:
                yield self._build_done_event(state)
                return

            # Loop continues — model will see tool results in the next round.

        yield ErrorEvent(f"Exceeded {max_rounds} tool-calling rounds")
        yield self._build_done_event(state)

    # -- orchestration helpers --------------------------------------------

    async def _maybe_compact(self) -> AsyncGenerator[ChatEvent, None]:
        """Pre-prompt compaction with bounded timeout.

        Auto-compacts *before* appending the new user message so the model
        sees a clean summary rather than fresh history mixed with stale.
        Yields :class:`CompactionEvent` on success, :class:`ErrorEvent` on
        timeout or failure; never raises — compaction failures must not
        kill the conversation.
        """
        if self._compactor is None or not self._compactor.should_compact(self.messages):
            return
        try:
            compact_awaitable = self._compactor.compact(self.messages)
            if self.compaction_timeout_s > 0:
                new_messages, result = await asyncio.wait_for(
                    compact_awaitable, timeout=self.compaction_timeout_s,
                )
            else:
                new_messages, result = await compact_awaitable
        except asyncio.TimeoutError:
            self.compaction_timeout_count += 1
            yield ErrorEvent(
                f"Compaction timed out after {self.compaction_timeout_s:.0f}s "
                "(continuing with uncompacted history)."
            )
            return
        except Exception as exc:
            yield ErrorEvent(f"Compaction failed (continuing): {exc}")
            return
        if result.compacted:
            self.messages = new_messages
            yield CompactionEvent(
                summary=result.summary,
                replaced_count=result.replaced_count,
                tokens_before=result.tokens_before,
                tokens_after=result.tokens_after,
            )

    async def _apply_retry_backoff(self, attempt_index: int) -> bool:
        """Sleep for exponential backoff between provider retries.

        Returns True on successful sleep (caller should retry). Returns
        False if the cancel event fires during the sleep (caller should
        abort).
        """
        delay_s = self.provider_retry_base_s * (2 ** attempt_index)
        self.provider_retry_count += 1
        self.provider_retry_backoff_ms += int(delay_s * 1000)
        if delay_s <= 0:
            await asyncio.sleep(0)
            return not self._cancel_event.is_set()
        try:
            await asyncio.wait_for(self._cancel_event.wait(), timeout=delay_s)
            return False
        except asyncio.TimeoutError:
            return True

    async def _stream_round(
        self,
        *,
        state: _ChatState,
        output: _RoundOutput,
        model_id: str,
        system: str,
        temperature: float,
        max_tokens: int,
        use_tools: bool,
        use_xml_thinking: bool,
        thinking: bool,
        prompt_cache: bool,
    ) -> AsyncGenerator[ChatEvent, None]:
        """Stream one provider completion with retry + cancellation.

        Populates ``output`` with accumulated content, thinking, and any
        tool_calls the model emitted. Sets ``state.cancelled`` on abort
        and ``state.done`` on a terminal error (caller must not continue).
        """
        # Re-fetch tool schemas each round. Most bridges return a static
        # list, but DeferredToolBridge reveals tools via tool_search and
        # expects to expose newly-available schemas on the next request.
        tools = (
            self.bridge.get_openai_tools()
            if use_tools and self.bridge and self.bridge.tool_count > 0
            else None
        )
        # Providers that use a separate system parameter (Anthropic) read
        # from request.system; pull it from history if not explicit.
        sys_prompt = system
        if not sys_prompt and self.messages and self.messages[0].get("role") == "system":
            sys_prompt = self.messages[0]["content"]

        request = CompletionRequest(
            model_id=model_id,
            messages=self.messages,
            system=sys_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice="auto" if tools else "",
            prompt_cache=prompt_cache,
        )

        attempt = 0
        while True:
            # Reset per-attempt state so a retry doesn't carry over stale
            # partial output from the failed attempt.
            output.content = ""
            output.thinking_content = ""
            output.tool_calls = []
            parser = _ThinkingParser() if use_xml_thinking else None
            local_cancelled = False
            saw_stream_output = False
            try:
                async for chunk in self._provider.stream(request):
                    saw_stream_output = True
                    if self._cancel_event.is_set():
                        local_cancelled = True
                        break

                    if chunk.usage:
                        state.total_prompt_tokens += chunk.usage.prompt_tokens
                        state.total_completion_tokens += chunk.usage.completion_tokens
                        state.total_cache_creation += chunk.usage.cache_creation_tokens
                        state.total_cache_read += chunk.usage.cache_read_tokens

                    if chunk.content:
                        # Native thinking (Anthropic)
                        if chunk.content.thinking:
                            output.thinking_content += chunk.content.thinking
                            yield ThinkingEvent(chunk.content.thinking)

                        # Reasoning content (Qwen3 via LM Studio)
                        if chunk.content.reasoning:
                            raw = chunk.content.reasoning
                            output.content += raw
                            if parser is not None:
                                for evt in parser.feed(raw):
                                    if isinstance(evt, ThinkingEvent):
                                        output.thinking_content += evt.text
                                    yield evt
                            else:
                                yield ThinkingEvent(raw) if thinking else TextEvent(raw)

                        # Regular text content
                        if chunk.content.text:
                            raw = chunk.content.text
                            output.content += raw
                            if parser is not None:
                                for evt in parser.feed(raw):
                                    if isinstance(evt, ThinkingEvent):
                                        output.thinking_content += evt.text
                                    yield evt
                            else:
                                yield TextEvent(raw)

                    # Tool calls stream as deltas but the engine consumes
                    # them as a final batch once the stream ends.
                    if chunk.tool_calls:
                        for tc in chunk.tool_calls:
                            output.tool_calls.append({
                                "id": tc.id,
                                "name": tc.name,
                                "arguments": tc.arguments,
                            })

                if parser is not None and not local_cancelled:
                    for evt in parser.flush():
                        if isinstance(evt, ThinkingEvent):
                            output.thinking_content += evt.text
                        yield evt

                if local_cancelled:
                    state.cancelled = True
                return

            except ProviderError as exc:
                can_retry = (
                    not saw_stream_output
                    and attempt < self.provider_max_retries
                    and _is_retryable_provider_error(exc)
                )
                if can_retry:
                    if not await self._apply_retry_backoff(attempt):
                        state.cancelled = True
                        return
                    attempt += 1
                    continue
                self.provider_error_count += 1
                state.done = True
                yield ErrorEvent(str(exc))
                return
            except (httpx.ConnectError, httpx.TimeoutException, ConnectionError):
                can_retry = (not saw_stream_output and attempt < self.provider_max_retries)
                if can_retry:
                    if not await self._apply_retry_backoff(attempt):
                        state.cancelled = True
                        return
                    attempt += 1
                    continue
                self.provider_error_count += 1
                state.done = True
                yield ErrorEvent(f"Cannot connect to model backend ({self._provider.name})")
                # Undo the user message so they can retry.
                if self.messages and self.messages[-1]["role"] == "user":
                    self.messages.pop()
                return
            except (httpx.StreamClosed, httpx.StreamError, httpx.ReadError):
                # Cancellation closes an active stream. A stream drop
                # before first bytes can still be retried.
                if self._cancel_event.is_set() or saw_stream_output:
                    state.cancelled = True
                    return
                can_retry = attempt < self.provider_max_retries
                if can_retry:
                    if not await self._apply_retry_backoff(attempt):
                        state.cancelled = True
                        return
                    attempt += 1
                    continue
                self.provider_error_count += 1
                state.done = True
                yield ErrorEvent(f"Model stream disconnected ({self._provider.name})")
                return
            except Exception as exc:
                self.provider_error_count += 1
                state.done = True
                yield ErrorEvent(str(exc))
                return

    async def _execute_tool_calls(
        self,
        *,
        round_idx: int,
        tool_calls: list[dict],
        history_content: str,
        max_tool_result: int,
        state: _ChatState,
    ) -> AsyncGenerator[ChatEvent, None]:
        """Append the assistant tool_calls record and execute each tool.

        Each tool call goes through: permission hook (with timeout) →
        bridge.call_tool (timeout + cancellation) → telemetry hook →
        post_tool_hook (with timeout) → append tool result message.

        Sets ``state.cancelled`` on user abort and ``state.done`` on a
        terminal error.
        """
        tc_list = []
        for i, tc in enumerate(tool_calls):
            tc_id = tc["id"] or f"call_{round_idx}_{i}"
            tc_list.append({
                "id": tc_id,
                "type": "function",
                "function": {"name": tc["name"], "arguments": tc["arguments"]},
            })

        self.messages.append({
            "role": "assistant",
            "content": history_content or None,
            "tool_calls": tc_list,
        })

        bridge = self.bridge
        if bridge is None:
            state.done = True
            yield ErrorEvent("Tool execution aborted: no tool bridge connected")
            return

        for i, tc in enumerate(tool_calls):
            if self._cancel_event.is_set():
                state.cancelled = True
                return

            tc_id = tc["id"] or f"call_{round_idx}_{i}"
            server = bridge.get_tool_server(tc["name"]) if bridge else "?"
            yield ToolCallEvent(tc["name"], tc["arguments"], server, tc_id)

            if not await self._gate_with_permission(tc, server, tc_id):
                # Permission hook denied (or timed out → default-deny).
                denial = "[Tool call denied by user]"
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": denial,
                })
                yield ToolResultEvent(tc["name"], denial, server, tc_id)
                await self._emit_tool_invocation(
                    tool=tc["name"],
                    arguments=tc["arguments"],
                    server=server,
                    call_id=tc_id,
                    duration_ms=0.0,
                    status="denied",
                )
                continue

            args: dict = {}
            try:
                arguments = tc["arguments"] or "{}"
                if not isinstance(arguments, str):
                    raise TypeError("Tool arguments must be a JSON string")
                parsed = json.loads(arguments)
                if not isinstance(parsed, dict):
                    raise TypeError("Tool arguments must be a JSON object")
                args = parsed
            except (json.JSONDecodeError, TypeError) as exc:
                yield_error = f"Invalid tool arguments for '{tc['name']}': {exc}"
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": f"[Tool execution error] {yield_error}",
                })
                yield ToolResultEvent(tc["name"], f"[Tool execution error] {yield_error}", server, tc_id)
                await self._emit_tool_invocation(
                    tool=tc["name"],
                    arguments=tc["arguments"],
                    server=server,
                    call_id=tc_id,
                    duration_ms=0.0,
                    status="error",
                    error=yield_error,
                )
                state.done = True
                yield ErrorEvent(yield_error)
                return

            result, tool_status, tool_exc, local_cancelled = await self._run_one_tool(
                bridge, tc["name"], args,
            )

            await self._emit_tool_invocation(
                tool=tc["name"],
                arguments=tc["arguments"],
                server=server,
                call_id=tc_id,
                duration_ms=result.duration_ms,
                status=tool_status,
                error=str(tool_exc) if tool_exc else "",
            )

            if tool_exc is not None:
                state.done = True
                yield ErrorEvent(str(tool_exc))
                return

            if local_cancelled:
                state.cancelled = True
                return

            post_result = result.output
            if self._post_tool_hook is not None:
                try:
                    post_coro = self._post_tool_hook(
                        tc["name"], tc["arguments"], post_result, server, tc_id,
                    )
                    if self.post_tool_hook_timeout_s > 0:
                        post_result = await asyncio.wait_for(
                            post_coro, timeout=self.post_tool_hook_timeout_s,
                        )
                    else:
                        post_result = await post_coro
                except asyncio.TimeoutError:
                    self.hook_timeout_count += 1
                    # Pass the original result through on timeout.
                except Exception:
                    # Post-tool hooks are advisory and must not fail the round.
                    pass

            yield ToolResultEvent(tc["name"], post_result, server, tc_id)

            # Truncate large results in history to save context window.
            history_result = (
                _truncate_tool_result(post_result, max_tool_result)
                if max_tool_result > 0 else post_result
            )
            self.messages.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "content": history_result,
            })

    async def _gate_with_permission(
        self, tc: dict, server: str, tc_id: str,
    ) -> bool:
        """Run the permission hook with a bounded timeout.

        Returns True if the tool call is allowed (no hook, or hook
        approved). Returns False if denied or the hook timed out
        (default-deny).
        """
        if self._permission_hook is None:
            return True
        try:
            perm_coro = self._permission_hook(tc["name"], tc["arguments"], server, tc_id)
            if self.permission_hook_timeout_s > 0:
                return bool(await asyncio.wait_for(
                    perm_coro, timeout=self.permission_hook_timeout_s,
                ))
            return bool(await perm_coro)
        except asyncio.TimeoutError:
            self.hook_timeout_count += 1
            return False
        except Exception:
            # Permission hooks default-deny on unexpected failures.
            return False

    async def _run_one_tool(
        self, bridge: ToolBridge, name: str, args: dict,
    ) -> tuple["_ToolRunResult", str, Exception | None, bool]:
        """Execute one tool with timeout + cancellation awareness.

        Returns a tuple of:
          * ``_ToolRunResult``: output string and measured duration_ms.
          * ``status``: one of ``success``, ``timeout``, ``cancelled``, ``error``.
          * ``exc``: exception instance if the tool raised, else ``None``.
          * ``cancelled``: True if the external cancel event fired.
        """
        tool_task = asyncio.create_task(bridge.call_tool(name, args))
        cancel_waiter = asyncio.create_task(self._cancel_event.wait())
        tool_loop = asyncio.get_running_loop()
        started = tool_loop.time()
        status = "success"
        exc: Exception | None = None
        output = ""
        local_cancelled = False
        timeout_s = self.tool_timeout_s if self.tool_timeout_s > 0 else None
        try:
            done, _ = await asyncio.wait(
                {tool_task, cancel_waiter},
                timeout=timeout_s,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if tool_task in done:
                try:
                    output = tool_task.result()
                except asyncio.CancelledError:
                    local_cancelled = True
                    status = "cancelled"
                except Exception as e:
                    exc = e
                    status = "error"
            elif cancel_waiter in done:
                local_cancelled = True
                status = "cancelled"
                tool_task.cancel()
            else:
                # Neither fired — asyncio.wait returned due to timeout.
                self.tool_timeout_count += 1
                tool_task.cancel()
                output = f"[Tool execution timed out after {self.tool_timeout_s:.0f}s]"
                status = "timeout"
        finally:
            cancel_waiter.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await cancel_waiter
            if not tool_task.done():
                tool_task.cancel()
                await asyncio.gather(tool_task, return_exceptions=True)
        duration_ms = (tool_loop.time() - started) * 1000.0
        return _ToolRunResult(output=output, duration_ms=duration_ms), status, exc, local_cancelled

    def _build_done_event(self, state: _ChatState) -> "DoneEvent":
        return DoneEvent(
            prompt_tokens=state.total_prompt_tokens,
            completion_tokens=state.total_completion_tokens,
            total_tokens=state.total_prompt_tokens + state.total_completion_tokens,
            cache_creation_tokens=state.total_cache_creation,
            cache_read_tokens=state.total_cache_read,
        )

    async def close(self):
        if self._owns_provider:
            await self._provider.close()


@dataclass
class _ToolRunResult:
    """Result from :meth:`ChatEngine._run_one_tool`."""
    output: str
    duration_ms: float
