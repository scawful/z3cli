"""Chat engine: LM Studio API client with streaming and tool-calling loop.

Handles the OpenAI-compatible /v1/chat/completions endpoint,
accumulates streaming tool-call deltas, and iterates the
call-tool-feed-result loop until the model produces a final text response.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import AsyncGenerator

import httpx

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

@dataclass
class ToolResultEvent:
    """Result returned from a tool call."""
    name: str
    result: str

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


ChatEvent = TextEvent | ThinkingEvent | ToolCallEvent | ToolResultEvent | ErrorEvent | DoneEvent


# ---------------------------------------------------------------------------
# Thinking block parser
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


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class ChatEngine:
    def __init__(
        self,
        api_base: str,
        bridge: ToolBridge | None = None,
        permission_hook=None,
    ):
        """
        permission_hook: optional async callable(tool_name, arguments_json, server) -> bool.
        Called before each tool execution. Return False to deny.
        """
        self.api_base = api_base
        self.bridge = bridge
        self._permission_hook = permission_hook
        self.client = httpx.AsyncClient(base_url=api_base, timeout=300.0)
        self.messages: list[dict] = []
        self.connected = False
        self._cancel_event = asyncio.Event()
        self._active_response: httpx.Response | None = None

    def cancel(self) -> None:
        """Signal the engine to abort the current streaming response."""
        self._cancel_event.set()
        if self._active_response is not None:
            response = self._active_response
            self._active_response = None
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop is not None:
                loop.create_task(response.aclose())

    # -- connection helpers --------------------------------------------------

    async def check_connection(self) -> bool:
        try:
            resp = await self.client.get("/models", timeout=5.0)
            self.connected = resp.status_code == 200
        except Exception:
            self.connected = False
        return self.connected

    async def list_loaded_models(self) -> list[str]:
        try:
            resp = await self.client.get("/models", timeout=5.0)
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
        self.messages.append({"role": "user", "content": message})

        tools = (
            self.bridge.get_openai_tools()
            if use_tools and self.bridge and self.bridge.tool_count > 0
            else None
        )

        # Accumulate token usage across all tool-calling rounds
        total_prompt_tokens = 0
        total_completion_tokens = 0

        for round_idx in range(max_rounds + 1):
            payload: dict = {
                "model": model_id,
                "messages": self.messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True,
                "stream_options": {"include_usage": True},
            }
            if tools:
                payload["tools"] = tools
                payload["tool_choice"] = "auto"

            content = ""
            thinking_content = ""
            tool_calls: list[dict] = []
            parser = _ThinkingParser() if thinking else None

            cancelled = False
            try:
                async with self.client.stream(
                    "POST", "/chat/completions", json=payload
                ) as resp:
                    self._active_response = resp
                    if resp.status_code != 200:
                        body = (await resp.aread()).decode(errors="replace")[:300]
                        yield ErrorEvent(f"API {resp.status_code}: {body}")
                        return

                    async for line in resp.aiter_lines():
                        if self._cancel_event.is_set():
                            cancelled = True
                            break
                        if not line.startswith("data: "):
                            continue
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        # Extract usage if present (accumulate across rounds)
                        usage = chunk.get("usage")
                        if isinstance(usage, dict):
                            total_prompt_tokens += usage.get("prompt_tokens", 0)
                            total_completion_tokens += usage.get("completion_tokens", 0)

                        choices = chunk.get("choices", [])
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {})

                        # Streaming reasoning_content (Qwen3 thinking via LM Studio)
                        # LM Studio sends Qwen3 thinking+tool calls through
                        # delta.reasoning_content instead of delta.content
                        if delta.get("reasoning_content"):
                            raw = delta["reasoning_content"]
                            content += raw
                            if parser is not None:
                                for evt in parser.feed(raw):
                                    if isinstance(evt, ThinkingEvent):
                                        thinking_content += evt.text
                                    yield evt
                            else:
                                # Parse inline <tool_call> XML from reasoning
                                yield ThinkingEvent(raw) if thinking else TextEvent(raw)

                        # Streaming text — optionally parse thinking blocks
                        if delta.get("content"):
                            raw = delta["content"]
                            content += raw
                            if parser is not None:
                                for evt in parser.feed(raw):
                                    if isinstance(evt, ThinkingEvent):
                                        thinking_content += evt.text
                                    yield evt
                            else:
                                yield TextEvent(raw)

                        # Accumulate tool call deltas
                        if delta.get("tool_calls"):
                            for tc in delta["tool_calls"]:
                                idx = tc.get("index", 0)
                                while len(tool_calls) <= idx:
                                    tool_calls.append({
                                        "id": "", "name": "", "arguments": "",
                                    })
                                if tc.get("id"):
                                    tool_calls[idx]["id"] = tc["id"]
                                fn = tc.get("function", {})
                                if fn.get("name"):
                                    tool_calls[idx]["name"] = fn["name"]
                                if fn.get("arguments") is not None:
                                    tool_calls[idx]["arguments"] += fn["arguments"]

                    self._active_response = None

                    # Flush any remaining buffered thinking parser state
                    if parser is not None and not cancelled:
                        for evt in parser.flush():
                            if isinstance(evt, ThinkingEvent):
                                thinking_content += evt.text
                            yield evt

            except httpx.ConnectError:
                self._active_response = None
                yield ErrorEvent(
                    f"Cannot connect to model backend at {self.api_base}"
                )
                # Undo the user message so they can retry
                if self.messages and self.messages[-1]["role"] == "user":
                    self.messages.pop()
                return
            except (httpx.StreamClosed, httpx.StreamError, httpx.ReadError):
                # Raised when cancel() closes the active response mid-stream
                self._active_response = None
                cancelled = True
            except Exception as e:
                self._active_response = None
                yield ErrorEvent(str(e))
                return

            if cancelled:
                # Store whatever we got so far in history
                if content.strip():
                    history_content = content
                    if thinking and strip_thinking and thinking_content:
                        history_content = _strip_think_blocks(content)
                    self.messages.append({"role": "assistant", "content": history_content})
                yield DoneEvent(
                    prompt_tokens=total_prompt_tokens,
                    completion_tokens=total_completion_tokens,
                    total_tokens=total_prompt_tokens + total_completion_tokens,
                )
                return

            # Build the history content — optionally strip thinking blocks
            history_content = content
            if thinking and strip_thinking and thinking_content:
                history_content = _strip_think_blocks(content)

            # -- Check for XML tool calls in reasoning_content (Qwen3 path) --
            if not tool_calls and content:
                xml_calls = _extract_xml_tool_calls(content)
                if xml_calls:
                    tool_calls = xml_calls

            # -- No tool calls: final answer ---------------------------------
            if not tool_calls:
                self.messages.append({"role": "assistant", "content": history_content})
                yield DoneEvent(
                    prompt_tokens=total_prompt_tokens,
                    completion_tokens=total_completion_tokens,
                    total_tokens=total_prompt_tokens + total_completion_tokens,
                )
                return

            # -- Tool calls: execute and loop --------------------------------
            tc_list = []
            for i, tc in enumerate(tool_calls):
                tc_id = tc["id"] or f"call_{round_idx}_{i}"
                tc_list.append({
                    "id": tc_id,
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": tc["arguments"],
                    },
                })

            self.messages.append({
                "role": "assistant",
                "content": history_content or None,
                "tool_calls": tc_list,
            })

            bridge = self.bridge
            if bridge is None:
                yield ErrorEvent("Tool execution aborted: no tool bridge connected")
                return

            for i, tc in enumerate(tool_calls):
                if self._cancel_event.is_set():
                    cancelled = True
                    break

                tc_id = tc["id"] or f"call_{round_idx}_{i}"
                server = (
                    bridge.get_tool_server(tc["name"])
                    if bridge else "?"
                )
                yield ToolCallEvent(tc["name"], tc["arguments"], server)

                # Permission gate — caller can deny tool execution
                if self._permission_hook is not None:
                    allowed = await self._permission_hook(tc["name"], tc["arguments"], server)
                    if not allowed:
                        denial = "[Tool call denied by user]"
                        self.messages.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": denial,
                        })
                        yield ToolResultEvent(tc["name"], denial)
                        continue

                try:
                    args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                except json.JSONDecodeError:
                    args = {}

                tool_task = asyncio.create_task(bridge.call_tool(tc["name"], args))
                result = ""
                while True:
                    done, _ = await asyncio.wait({tool_task}, timeout=0.1)
                    if tool_task in done:
                        try:
                            result = tool_task.result()
                        except asyncio.CancelledError:
                            cancelled = True
                            break
                        except Exception as e:
                            yield ErrorEvent(str(e))
                            return
                        break
                    if self._cancel_event.is_set():
                        cancelled = True
                        tool_task.cancel()
                        await asyncio.gather(tool_task, return_exceptions=True)
                        break

                if cancelled:
                    break

                yield ToolResultEvent(tc["name"], result)

                # Truncate large results in history to save context window
                history_result = _truncate_tool_result(result, max_tool_result) if max_tool_result > 0 else result
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": history_result,
                })

            if cancelled:
                yield DoneEvent(
                    prompt_tokens=total_prompt_tokens,
                    completion_tokens=total_completion_tokens,
                    total_tokens=total_prompt_tokens + total_completion_tokens,
                )
                return

            # Loop continues — model will see tool results

        yield ErrorEvent(f"Exceeded {max_rounds} tool-calling rounds")
        yield DoneEvent(
            prompt_tokens=total_prompt_tokens,
            completion_tokens=total_completion_tokens,
            total_tokens=total_prompt_tokens + total_completion_tokens,
        )

    async def close(self):
        await self.client.aclose()
