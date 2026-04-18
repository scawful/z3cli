"""Provider abstraction for LLM completion backends.

A Provider handles the wire-format details of streaming chat completions
from a specific LLM backend (local OpenAI-compatible, Anthropic, etc.).
The ChatEngine uses providers to decouple its tool-loop orchestration
from the specifics of any single API.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from typing import AsyncGenerator, Protocol

import httpx


# ---------------------------------------------------------------------------
# Completion primitives shared across all providers
# ---------------------------------------------------------------------------

@dataclass
class ContentDelta:
    """A chunk of streaming content from the model."""
    text: str = ""
    thinking: str = ""
    reasoning: str = ""


@dataclass
class ToolCallDelta:
    """Accumulated tool call from the model's response."""
    id: str = ""
    name: str = ""
    arguments: str = ""


@dataclass
class CompletionChunk:
    """A single streaming chunk from a provider.

    Providers yield these; the engine interprets them.
    """
    content: ContentDelta | None = None
    tool_calls: list[ToolCallDelta] | None = None
    usage: "UsageInfo | None" = None
    stop_reason: str | None = None  # "end_turn", "tool_use", "max_tokens", etc.


@dataclass
class UsageInfo:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0


@dataclass
class CompletionRequest:
    """Provider-agnostic request for a streaming completion."""
    model_id: str
    messages: list[dict]
    system: str = ""
    temperature: float = 0.3
    max_tokens: int = 2048
    tools: list[dict] | None = None
    tool_choice: str = "auto"
    stream: bool = True
    # Provider-specific hint: enable prompt caching (Anthropic) for
    # system prompt + tool list. No-op for other providers.
    prompt_cache: bool = True


@dataclass
class CompletionResult:
    """Final accumulated result after streaming completes."""
    content: str = ""
    thinking: str = ""
    tool_calls: list[ToolCallDelta] = field(default_factory=list)
    usage: UsageInfo = field(default_factory=UsageInfo)
    stop_reason: str = ""


# ---------------------------------------------------------------------------
# Provider protocol
# ---------------------------------------------------------------------------

class Provider(Protocol):
    """Backend-agnostic interface for streaming LLM completions."""

    @property
    def name(self) -> str:
        """Short identifier: 'local', 'anthropic', 'openai'."""
        ...

    async def stream(
        self,
        request: CompletionRequest,
    ) -> AsyncGenerator[CompletionChunk, None]:
        """Stream completion chunks from the backend."""
        ...
        yield  # type: ignore[misc]

    async def check_connection(self) -> bool:
        """Return True if the backend is reachable."""
        ...

    async def close(self) -> None:
        """Release underlying resources."""
        ...


# ---------------------------------------------------------------------------
# LocalProvider — OpenAI-compatible (LM Studio, llama.cpp, Ollama)
# ---------------------------------------------------------------------------

class LocalProvider:
    """Provider for local OpenAI-compatible endpoints.

    Handles the SSE streaming format used by LM Studio, llama.cpp,
    and Ollama's OpenAI-compatible API.
    """

    def __init__(self, api_base: str, timeout: float = 300.0):
        self._api_base = api_base.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._api_base, timeout=timeout,
        )

    @property
    def name(self) -> str:
        return "local"

    async def stream(
        self,
        request: CompletionRequest,
    ) -> AsyncGenerator[CompletionChunk, None]:
        payload: dict = {
            "model": request.model_id,
            "messages": self._build_messages(request),
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if request.tools:
            payload["tools"] = request.tools
            payload["tool_choice"] = request.tool_choice

        async with self._client.stream(
            "POST", "/chat/completions", json=payload,
        ) as resp:
            if resp.status_code != 200:
                body = (await resp.aread()).decode(errors="replace")[:300]
                raise ProviderError(f"API {resp.status_code}: {body}")

            # Accumulate tool call deltas across SSE chunks
            tool_calls: dict[int, ToolCallDelta] = {}

            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break

                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                # Parse usage
                usage_info = None
                raw_usage = chunk.get("usage")
                if isinstance(raw_usage, dict):
                    usage_info = UsageInfo(
                        prompt_tokens=raw_usage.get("prompt_tokens", 0),
                        completion_tokens=raw_usage.get("completion_tokens", 0),
                    )

                choices = chunk.get("choices", [])
                if not choices:
                    if usage_info:
                        yield CompletionChunk(usage=usage_info)
                    continue

                delta = choices[0].get("delta", {})
                finish_reason = choices[0].get("finish_reason")

                # Content deltas
                content_delta = None
                text = delta.get("content", "")
                reasoning = delta.get("reasoning_content", "")
                if text or reasoning:
                    content_delta = ContentDelta(
                        text=text or "",
                        reasoning=reasoning or "",
                    )

                # Tool call deltas — accumulate across chunks
                tc_deltas = None
                if delta.get("tool_calls"):
                    for tc in delta["tool_calls"]:
                        idx = tc.get("index", 0)
                        if idx not in tool_calls:
                            tool_calls[idx] = ToolCallDelta()
                        entry = tool_calls[idx]
                        if tc.get("id"):
                            entry.id = tc["id"]
                        fn = tc.get("function", {})
                        if fn.get("name"):
                            entry.name = fn["name"]
                        if fn.get("arguments") is not None:
                            entry.arguments += fn["arguments"]

                # Yield chunk
                yield CompletionChunk(
                    content=content_delta,
                    tool_calls=None,  # accumulated, emitted at end
                    usage=usage_info,
                    stop_reason=finish_reason,
                )

            # Emit accumulated tool calls at stream end
            if tool_calls:
                yield CompletionChunk(
                    tool_calls=[tool_calls[i] for i in sorted(tool_calls)],
                    stop_reason="tool_use",
                )

    async def check_connection(self) -> bool:
        try:
            resp = await self._client.get("/models", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False

    async def close(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _build_messages(request: CompletionRequest) -> list[dict]:
        """Build the messages list, injecting system as first message."""
        msgs = list(request.messages)
        if request.system:
            if msgs and msgs[0].get("role") == "system":
                msgs[0] = {**msgs[0], "content": request.system}
            else:
                msgs.insert(0, {"role": "system", "content": request.system})
        return msgs


# ---------------------------------------------------------------------------
# AnthropicProvider — Claude API (/v1/messages)
# ---------------------------------------------------------------------------

class AnthropicProvider:
    """Provider for the Anthropic Messages API.

    Uses the Anthropic Python SDK if available, otherwise falls back
    to raw httpx against the REST API.

    Handles:
    - Native thinking blocks (extended thinking)
    - tool_use content blocks (no XML parsing needed)
    - Prompt caching via cache_control headers
    - Streaming server-sent events
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str = "https://api.anthropic.com",
        timeout: float = 300.0,
        default_model: str = "claude-sonnet-4-20250514",
    ):
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._api_base = api_base.rstrip("/")
        self._default_model = default_model
        self._client = httpx.AsyncClient(
            base_url=self._api_base,
            timeout=timeout,
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )

    @property
    def name(self) -> str:
        return "anthropic"

    async def stream(
        self,
        request: CompletionRequest,
    ) -> AsyncGenerator[CompletionChunk, None]:
        model = request.model_id or self._default_model
        payload: dict = {
            "model": model,
            "messages": self._convert_messages(request.messages),
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "stream": True,
        }
        if request.system:
            payload["system"] = self._build_system(request.system, request.prompt_cache)
        if request.tools:
            payload["tools"] = self._convert_tools(request.tools, request.prompt_cache)
            payload["tool_choice"] = {"type": request.tool_choice}

        # Accumulate tool calls from content_block events
        active_tool: ToolCallDelta | None = None
        pending_tools: list[ToolCallDelta] = []

        async with self._client.stream(
            "POST", "/v1/messages", json=payload,
        ) as resp:
            if resp.status_code != 200:
                body = (await resp.aread()).decode(errors="replace")[:500]
                raise ProviderError(f"Anthropic API {resp.status_code}: {body}")

            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:].strip()
                if not data_str:
                    continue

                try:
                    event = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                event_type = event.get("type", "")

                # --- content_block_start: new text or tool_use block ---
                if event_type == "content_block_start":
                    block = event.get("content_block", {})
                    if block.get("type") == "tool_use":
                        active_tool = ToolCallDelta(
                            id=block.get("id", ""),
                            name=block.get("name", ""),
                            arguments="",
                        )

                # --- content_block_delta: streaming content ---
                elif event_type == "content_block_delta":
                    delta = event.get("delta", {})
                    delta_type = delta.get("type", "")

                    if delta_type == "text_delta":
                        yield CompletionChunk(
                            content=ContentDelta(text=delta.get("text", "")),
                        )

                    elif delta_type == "thinking_delta":
                        yield CompletionChunk(
                            content=ContentDelta(thinking=delta.get("thinking", "")),
                        )

                    elif delta_type == "input_json_delta" and active_tool:
                        active_tool.arguments += delta.get("partial_json", "")

                # --- content_block_stop: finalize tool call ---
                elif event_type == "content_block_stop":
                    if active_tool:
                        pending_tools.append(active_tool)
                        active_tool = None

                # --- message_delta: stop reason + output tokens ---
                elif event_type == "message_delta":
                    delta = event.get("delta", {})
                    usage_data = event.get("usage", {})
                    yield CompletionChunk(
                        stop_reason=delta.get("stop_reason"),
                        usage=UsageInfo(
                            completion_tokens=usage_data.get("output_tokens", 0),
                        ),
                    )

                # --- message_start: input token count ---
                elif event_type == "message_start":
                    msg = event.get("message", {})
                    usage_data = msg.get("usage", {})
                    if usage_data:
                        yield CompletionChunk(
                            usage=UsageInfo(
                                prompt_tokens=usage_data.get("input_tokens", 0),
                                cache_creation_tokens=usage_data.get(
                                    "cache_creation_input_tokens", 0,
                                ),
                                cache_read_tokens=usage_data.get(
                                    "cache_read_input_tokens", 0,
                                ),
                            ),
                        )

        # Emit accumulated tool calls
        if pending_tools:
            yield CompletionChunk(
                tool_calls=pending_tools,
                stop_reason="tool_use",
            )

    async def check_connection(self) -> bool:
        if not self._api_key:
            return False
        try:
            # Anthropic doesn't have a /models endpoint; use a minimal
            # messages request to validate the key.
            resp = await self._client.post(
                "/v1/messages",
                json={
                    "model": self._default_model,
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "ping"}],
                },
                timeout=10.0,
            )
            return resp.status_code == 200
        except Exception:
            return False

    async def close(self) -> None:
        await self._client.aclose()

    # -- Message format conversion -------------------------------------------

    @staticmethod
    def _convert_messages(messages: list[dict]) -> list[dict]:
        """Convert OpenAI-format messages to Anthropic format.

        Anthropic messages API:
        - No 'system' role in messages (handled via top-level 'system' param)
        - tool results use role='user' with tool_result content blocks
        - assistant tool_calls become tool_use content blocks
        """
        result: list[dict] = []
        for msg in messages:
            role = msg.get("role", "")

            # Skip system messages (handled separately)
            if role == "system":
                continue

            # Tool results → user message with tool_result content block
            if role == "tool":
                result.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.get("tool_call_id", ""),
                        "content": msg.get("content", ""),
                    }],
                })
                continue

            # Assistant messages with tool_calls → tool_use content blocks
            if role == "assistant" and msg.get("tool_calls"):
                content_blocks: list[dict] = []
                text = msg.get("content")
                if text:
                    content_blocks.append({"type": "text", "text": text})
                for tc in msg["tool_calls"]:
                    fn = tc.get("function", {})
                    args_str = fn.get("arguments", "{}")
                    try:
                        args = json.loads(args_str) if isinstance(args_str, str) else args_str
                    except json.JSONDecodeError:
                        args = {}
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": fn.get("name", ""),
                        "input": args,
                    })
                result.append({"role": "assistant", "content": content_blocks})
                continue

            # Regular user/assistant messages
            result.append({
                "role": role,
                "content": msg.get("content", ""),
            })

        return result

    @staticmethod
    def _build_system(system: str, prompt_cache: bool) -> str | list[dict]:
        """Build the system parameter. When prompt_cache is True, wrap as a
        content block with ``cache_control`` so the whole system prompt
        becomes a cacheable prefix.

        Subsequent requests with the same system prompt read from cache
        at ~10% of the original token cost.
        """
        if not prompt_cache:
            return system
        return [
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }
        ]

    @staticmethod
    def _convert_tools(openai_tools: list[dict], prompt_cache: bool = False) -> list[dict]:
        """Convert OpenAI function-calling tool schemas to Anthropic format.

        When ``prompt_cache`` is True, attaches ``cache_control`` to the
        final tool. Anthropic caches everything *up to and including* the
        marked block, so marking the last tool caches the entire tool list
        as a prefix alongside the system prompt.
        """
        anthropic_tools: list[dict] = []
        for tool in openai_tools:
            fn = tool.get("function", {})
            anthropic_tools.append({
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters", {"type": "object"}),
            })
        if prompt_cache and anthropic_tools:
            last = anthropic_tools[-1]
            anthropic_tools[-1] = {**last, "cache_control": {"type": "ephemeral"}}
        return anthropic_tools


# ---------------------------------------------------------------------------
# OpenAI Cloud Provider — for GPT-4o, o3, etc.
# ---------------------------------------------------------------------------

class OpenAICloudProvider:
    """Provider for the OpenAI Chat Completions API (cloud).

    Same SSE format as LocalProvider but pointed at api.openai.com
    with API key auth. Kept separate so we can add OpenAI-specific
    features (structured outputs, reasoning tokens) later.
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str = "https://api.openai.com/v1",
        timeout: float = 300.0,
        default_model: str = "gpt-4o",
    ):
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._api_base = api_base.rstrip("/")
        self._default_model = default_model
        self._local = LocalProvider(api_base=self._api_base, timeout=timeout)
        # Patch in auth header
        self._local._client = httpx.AsyncClient(
            base_url=self._api_base,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )

    @property
    def name(self) -> str:
        return "openai"

    async def stream(
        self,
        request: CompletionRequest,
    ) -> AsyncGenerator[CompletionChunk, None]:
        if not request.model_id:
            request = CompletionRequest(
                model_id=self._default_model,
                messages=request.messages,
                system=request.system,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                tools=request.tools,
                tool_choice=request.tool_choice,
                stream=request.stream,
            )
        async for chunk in self._local.stream(request):
            yield chunk

    async def check_connection(self) -> bool:
        if not self._api_key:
            return False
        return await self._local.check_connection()

    async def close(self) -> None:
        await self._local.close()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

class ProviderError(Exception):
    """Raised when a provider encounters an unrecoverable error."""


# Valid provider names for config validation
VALID_PROVIDERS = {"studio", "ollama", "llamacpp", "anthropic", "openai"}


def create_provider(
    provider_name: str,
    api_base: str = "",
    api_key: str = "",
    default_model: str = "",
    timeout: float = 300.0,
) -> Provider:
    """Create a Provider instance from a provider name and config.

    Args:
        provider_name: One of 'studio', 'ollama', 'llamacpp', 'anthropic', 'openai'.
        api_base: Base URL for the API endpoint.
        api_key: API key for cloud providers.
        default_model: Default model ID if not specified per-request.
        timeout: HTTP timeout in seconds.
    """
    if provider_name in ("studio", "ollama", "llamacpp"):
        if not api_base:
            api_base = "http://127.0.0.1:1234/v1"
        return LocalProvider(api_base=api_base, timeout=timeout)

    if provider_name == "anthropic":
        return AnthropicProvider(
            api_key=api_key,
            api_base=api_base or "https://api.anthropic.com",
            timeout=timeout,
            default_model=default_model or "claude-sonnet-4-20250514",
        )

    if provider_name == "openai":
        return OpenAICloudProvider(
            api_key=api_key,
            api_base=api_base or "https://api.openai.com/v1",
            timeout=timeout,
            default_model=default_model or "gpt-4o",
        )

    raise ValueError(f"Unknown provider: {provider_name!r} (valid: {VALID_PROVIDERS})")
