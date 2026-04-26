"""Tests for Anthropic prompt caching."""

from __future__ import annotations

import json
import unittest
from typing import AsyncGenerator

from core.engine import ChatEngine, DoneEvent
from core.provider import (
    AnthropicProvider, CompletionChunk, CompletionRequest, ContentDelta,
    UsageInfo,
)


# ---------------------------------------------------------------------------
# Static helpers (no network)
# ---------------------------------------------------------------------------

class BuildSystemTests(unittest.TestCase):
    def test_cache_enabled_wraps_in_content_block(self) -> None:
        result = AnthropicProvider._build_system("hello world", True)
        self.assertIsInstance(result, list)
        self.assertEqual(result, [{
            "type": "text",
            "text": "hello world",
            "cache_control": {"type": "ephemeral"},
        }])

    def test_cache_disabled_returns_plain_string(self) -> None:
        result = AnthropicProvider._build_system("hello", False)
        self.assertEqual(result, "hello")


class ConvertToolsTests(unittest.TestCase):
    def _tool(self, name: str) -> dict:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": f"describes {name}",
                "parameters": {"type": "object", "properties": {}},
            },
        }

    def test_cache_disabled_plain_tools(self) -> None:
        tools = [self._tool("a"), self._tool("b")]
        result = AnthropicProvider._convert_tools(tools, prompt_cache=False)
        self.assertEqual(len(result), 2)
        for entry in result:
            self.assertNotIn("cache_control", entry)

    def test_cache_enabled_marks_last_tool(self) -> None:
        tools = [self._tool("a"), self._tool("b"), self._tool("c")]
        result = AnthropicProvider._convert_tools(tools, prompt_cache=True)
        # Only the last tool has cache_control
        self.assertNotIn("cache_control", result[0])
        self.assertNotIn("cache_control", result[1])
        self.assertEqual(result[2]["cache_control"], {"type": "ephemeral"})

    def test_cache_enabled_but_empty_tools_returns_empty(self) -> None:
        result = AnthropicProvider._convert_tools([], prompt_cache=True)
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# Cache tokens flow through engine
# ---------------------------------------------------------------------------

class CacheProvider:
    """Scripted provider that reports cache tokens in its usage stream."""

    def __init__(
        self,
        text: str = "done",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0,
    ):
        self._text = text
        self._usage = UsageInfo(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cache_creation_tokens=cache_creation_tokens,
            cache_read_tokens=cache_read_tokens,
        )
        self.last_request: CompletionRequest | None = None

    @property
    def name(self) -> str:
        return "anthropic"

    async def stream(
        self, request: CompletionRequest,
    ) -> AsyncGenerator[CompletionChunk, None]:
        self.last_request = request
        yield CompletionChunk(content=ContentDelta(text=self._text))
        yield CompletionChunk(usage=self._usage)

    async def check_connection(self) -> bool:
        return True

    async def close(self) -> None:
        pass


class EnginePropagatesCacheTokensTests(unittest.IsolatedAsyncioTestCase):
    async def test_cache_tokens_in_done_event(self) -> None:
        provider = CacheProvider(
            text="hi",
            prompt_tokens=50,
            completion_tokens=10,
            cache_creation_tokens=200,
            cache_read_tokens=1500,
        )
        engine = ChatEngine(provider=provider)

        events: list = []
        async for event in engine.chat(
            message="hello",
            model_id="claude-sonnet-4-20250514",
            system="big system prompt",
        ):
            events.append(event)

        done = next((e for e in events if isinstance(e, DoneEvent)), None)
        self.assertIsNotNone(done)
        assert done is not None  # type narrowing
        self.assertEqual(done.prompt_tokens, 50)
        self.assertEqual(done.completion_tokens, 10)
        self.assertEqual(done.cache_creation_tokens, 200)
        self.assertEqual(done.cache_read_tokens, 1500)

    async def test_request_prompt_cache_flag_propagates_default_true(self) -> None:
        """ChatEngine.chat defaults prompt_cache=True, reaches provider."""
        provider = CacheProvider()
        engine = ChatEngine(provider=provider)
        async for _ in engine.chat(message="hi", model_id="x"):
            pass
        assert provider.last_request is not None
        self.assertTrue(provider.last_request.prompt_cache)

    async def test_request_prompt_cache_false_propagates(self) -> None:
        provider = CacheProvider()
        engine = ChatEngine(provider=provider)
        async for _ in engine.chat(message="hi", model_id="x", prompt_cache=False):
            pass
        assert provider.last_request is not None
        self.assertFalse(provider.last_request.prompt_cache)


class PayloadShapeTests(unittest.TestCase):
    """Verify the actual JSON payload that would be sent to Anthropic."""

    def test_system_and_tools_both_cacheable(self) -> None:
        # Re-use the static builders to confirm the combined payload
        system = AnthropicProvider._build_system("big prompt", True)
        tools = AnthropicProvider._convert_tools(
            [{
                "type": "function",
                "function": {
                    "name": "spawn_subagent",
                    "description": "delegate",
                    "parameters": {"type": "object"},
                },
            }],
            prompt_cache=True,
        )
        # Confirm both system and tools carry cache_control markers
        self.assertIsInstance(system, list)
        self.assertEqual(system[0]["cache_control"], {"type": "ephemeral"})  # type: ignore[index]
        self.assertEqual(tools[-1]["cache_control"], {"type": "ephemeral"})
        # Should be serializable
        json.dumps({"system": system, "tools": tools})


if __name__ == "__main__":
    unittest.main()
