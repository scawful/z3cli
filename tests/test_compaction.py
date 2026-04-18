"""Tests for conversation compaction."""

from __future__ import annotations

import unittest
from typing import AsyncGenerator

from z3cli.core.compaction import (
    CompactionPolicy, ConversationCompactor, ProviderSummarizer,
    estimate_messages_tokens, estimate_tokens,
)
from z3cli.core.provider import (
    CompletionChunk, CompletionRequest, ContentDelta, UsageInfo,
)


# ---------------------------------------------------------------------------
# Mocks
# ---------------------------------------------------------------------------

class ScriptedProvider:
    """Provider that emits a fixed text response for any request."""

    def __init__(self, response: str):
        self._response = response
        self.calls: list[CompletionRequest] = []

    @property
    def name(self) -> str:
        return "mock"

    async def stream(
        self, request: CompletionRequest,
    ) -> AsyncGenerator[CompletionChunk, None]:
        self.calls.append(request)
        yield CompletionChunk(content=ContentDelta(text=self._response))
        yield CompletionChunk(usage=UsageInfo(prompt_tokens=10, completion_tokens=5))

    async def check_connection(self) -> bool:
        return True

    async def close(self) -> None:
        pass


class StaticSummarizer:
    """Summarizer that returns a fixed string, for deterministic tests."""

    def __init__(self, summary: str):
        self.summary = summary
        self.call_count = 0

    async def summarize(self, messages: list[dict], instruction: str = "") -> str:
        self.call_count += 1
        return self.summary


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------

class TokenEstimationTests(unittest.TestCase):
    def test_empty_string_returns_zero(self) -> None:
        self.assertEqual(estimate_tokens(""), 0)

    def test_scales_with_length(self) -> None:
        short = estimate_tokens("hello")
        long = estimate_tokens("hello " * 1000)
        self.assertLess(short, long)

    def test_message_includes_role_overhead(self) -> None:
        short_msg = [{"role": "user", "content": ""}]
        self.assertGreater(estimate_messages_tokens(short_msg), 0)

    def test_tool_call_message_counts_args(self) -> None:
        msg = {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "t1", "type": "function",
                "function": {"name": "echo", "arguments": '{"text": "hello world"}'},
            }],
        }
        # Tool call messages should have non-trivial token count
        self.assertGreater(estimate_messages_tokens([msg]), 5)


# ---------------------------------------------------------------------------
# Compactor policy / window selection
# ---------------------------------------------------------------------------

class WindowSelectionTests(unittest.IsolatedAsyncioTestCase):
    def _build_long_conversation(self, turns: int = 10) -> list[dict]:
        """Build N user/assistant turn pairs plus a system prompt."""
        messages: list[dict] = [{"role": "system", "content": "You are a helper."}]
        for i in range(turns):
            messages.append({"role": "user", "content": f"question {i}"})
            messages.append({"role": "assistant", "content": f"answer {i}"})
        return messages

    async def test_below_threshold_no_compaction(self) -> None:
        summarizer = StaticSummarizer("summary")
        compactor = ConversationCompactor(
            policy=CompactionPolicy(context_budget=100000, keep_recent_turns=2),
            summarizer=summarizer,
        )
        messages = self._build_long_conversation(turns=2)
        new_messages, result = await compactor.compact(messages)
        self.assertFalse(result.compacted)
        self.assertEqual(new_messages, messages)
        self.assertEqual(summarizer.call_count, 0)

    async def test_preserves_system_and_recent_turns(self) -> None:
        summarizer = StaticSummarizer("condensed prior work")
        compactor = ConversationCompactor(
            policy=CompactionPolicy(
                context_budget=100, threshold_ratio=0.5, keep_recent_turns=2,
            ),
            summarizer=summarizer,
        )
        messages = self._build_long_conversation(turns=6)
        new_messages, result = await compactor.compact(messages)

        self.assertTrue(result.compacted)
        # Preserves system prompt
        self.assertEqual(new_messages[0]["role"], "system")
        # Compacted recap is second
        self.assertEqual(new_messages[1]["role"], "assistant")
        self.assertIn("condensed prior work", new_messages[1]["content"])
        # Final 2 turns (= 4 messages) preserved verbatim
        self.assertEqual(len(new_messages), 1 + 1 + 4)
        self.assertEqual(new_messages[-1]["content"], "answer 5")
        self.assertEqual(new_messages[-2]["content"], "question 5")
        self.assertEqual(new_messages[-4]["content"], "question 4")

    async def test_force_compaction(self) -> None:
        summarizer = StaticSummarizer("forced summary")
        compactor = ConversationCompactor(
            policy=CompactionPolicy(context_budget=1000000, keep_recent_turns=1),
            summarizer=summarizer,
        )
        messages = self._build_long_conversation(turns=4)
        new_messages, result = await compactor.compact(messages, force=True)
        self.assertTrue(result.compacted)
        self.assertEqual(summarizer.call_count, 1)
        # system + summary + 2 messages from last turn
        self.assertEqual(len(new_messages), 4)

    async def test_without_summarizer_skips_compaction(self) -> None:
        compactor = ConversationCompactor(
            policy=CompactionPolicy(context_budget=100, threshold_ratio=0.1),
            summarizer=None,
        )
        messages = self._build_long_conversation(turns=6)
        new_messages, result = await compactor.compact(messages)
        self.assertFalse(result.compacted)
        self.assertEqual(result.reason, "no summarizer configured")
        self.assertEqual(new_messages, messages)

    async def test_empty_summary_skips_compaction(self) -> None:
        summarizer = StaticSummarizer("   ")
        compactor = ConversationCompactor(
            policy=CompactionPolicy(context_budget=100, threshold_ratio=0.1, keep_recent_turns=1),
            summarizer=summarizer,
        )
        messages = self._build_long_conversation(turns=6)
        new_messages, result = await compactor.compact(messages)
        self.assertFalse(result.compacted)
        self.assertEqual(new_messages, messages)


# ---------------------------------------------------------------------------
# ProviderSummarizer integration
# ---------------------------------------------------------------------------

class ProviderSummarizerTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_provider_to_generate_summary(self) -> None:
        provider = ScriptedProvider("**Recap:** user asked about ASM hooks.")
        summarizer = ProviderSummarizer(provider=provider, model_id="test")

        messages = [
            {"role": "user", "content": "can you review this ASM hook?"},
            {"role": "assistant", "content": "yes, the hook looks fine"},
        ]
        summary = await summarizer.summarize(messages)
        self.assertIn("Recap", summary)
        self.assertEqual(len(provider.calls), 1)
        # The summarizer should NOT request tools (summaries don't need them)
        self.assertIsNone(provider.calls[0].tools)


# ---------------------------------------------------------------------------
# ChatEngine integration
# ---------------------------------------------------------------------------

class ChatEngineCompactionTests(unittest.IsolatedAsyncioTestCase):
    async def test_engine_compact_now_returns_event(self) -> None:
        from z3cli.core.engine import CompactionEvent, ChatEngine
        provider = ScriptedProvider("text")
        engine = ChatEngine(provider=provider)
        # Seed some history
        engine.messages = [
            {"role": "system", "content": "helper"},
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
            {"role": "user", "content": "c"},
            {"role": "assistant", "content": "d"},
        ]
        summarizer = StaticSummarizer("combined summary")
        engine.set_compactor(ConversationCompactor(
            policy=CompactionPolicy(context_budget=1000000, keep_recent_turns=1),
            summarizer=summarizer,
        ))
        event = await engine.compact_now(force=True)
        self.assertIsNotNone(event)
        self.assertIsInstance(event, CompactionEvent)
        self.assertGreater(event.replaced_count, 0)
        self.assertLess(len(engine.messages), 5)
        # Most recent user/assistant preserved
        self.assertEqual(engine.messages[-1]["content"], "d")

    async def test_engine_compact_now_no_compactor_returns_none(self) -> None:
        from z3cli.core.engine import ChatEngine
        engine = ChatEngine(provider=ScriptedProvider("text"))
        self.assertIsNone(await engine.compact_now(force=True))


if __name__ == "__main__":
    unittest.main()
