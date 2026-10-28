"""Reasoning streamed as untagged ``reasoning_content`` (LM Studio, llama-server).

The reasoning must stay out of visible text, history content and XML tool parsing, and is
sent back as ``reasoning_content`` so Qwen3.8's template renders it the way the agent is trained.
"""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from typing import AsyncGenerator

from core.compaction import estimate_message_tokens
from core.engine import ChatEngine, TextEvent, ThinkingEvent, ToolResultEvent
from core.provider import CompletionChunk, CompletionRequest, ContentDelta, OpenAICloudProvider, ToolCallDelta
from core.session import load_session_bundle, load_session_bundle_without_thinking
from test_engine_qwen3 import EchoBridge


class ScriptedProvider:
    def __init__(self, scripts: list[list[CompletionChunk]]) -> None:
        self._scripts = list(scripts)
        self.requests: list[list[dict]] = []

    @property
    def name(self) -> str:
        return "local"

    async def stream(self, request: CompletionRequest) -> AsyncGenerator[CompletionChunk, None]:
        self.requests.append(copy.deepcopy(request.messages))
        for chunk in self._scripts.pop(0) if self._scripts else []:
            yield chunk

    async def check_connection(self) -> bool:
        return True

    async def close(self) -> None:
        pass


def reasoning(text: str) -> CompletionChunk:
    return CompletionChunk(content=ContentDelta(reasoning=text))


def text(value: str) -> CompletionChunk:
    return CompletionChunk(content=ContentDelta(text=value))


class UntaggedReasoningTests(unittest.IsolatedAsyncioTestCase):
    async def test_untagged_reasoning_is_thinking_not_text(self) -> None:
        provider = ScriptedProvider([[reasoning("\nplan: check"), reasoning(" $420C\n"), text("Use DMA init.")]])
        engine = ChatEngine(provider=provider)

        events = [e async for e in engine.chat("why?", "qwen3", thinking=True)]

        self.assertEqual("".join(e.text for e in events if isinstance(e, TextEvent)), "Use DMA init.")
        self.assertEqual("".join(e.text for e in events if isinstance(e, ThinkingEvent)).strip(), "plan: check $420C")
        self.assertEqual(engine.messages[-1], {
            "role": "assistant", "content": "Use DMA init.", "reasoning_content": "plan: check $420C",
        })

    async def test_untagged_reasoning_hidden_when_thinking_display_off(self) -> None:
        provider = ScriptedProvider([[reasoning("plan"), text("answer")]])
        engine = ChatEngine(provider=provider)

        events = [e async for e in engine.chat("q", "qwen3", thinking=False)]

        self.assertEqual("".join(e.text for e in events if isinstance(e, TextEvent)), "answer")
        self.assertFalse(any(isinstance(e, ThinkingEvent) for e in events))
        self.assertEqual(engine.messages[-1]["content"], "answer")

    async def test_tool_call_only_in_reasoning_does_not_execute(self) -> None:
        provider = ScriptedProvider([[
            reasoning('maybe <tool_call>{"name":"echo","arguments":{}}</tool_call> but no'),
            text("No tool needed."),
        ]])
        engine = ChatEngine(provider=provider, bridge=EchoBridge())

        events = [e async for e in engine.chat("q", "qwen3", thinking=True, allow_manual_tool_calls=True)]

        self.assertFalse(any(isinstance(e, ToolResultEvent) for e in events))
        self.assertEqual(len(provider.requests), 1)

    async def test_reasoning_is_sent_back_on_tool_rounds(self) -> None:
        provider = ScriptedProvider([
            [reasoning("need the echo tool"), CompletionChunk(tool_calls=[ToolCallDelta(id="c1", name="echo", arguments="{}")])],
            [reasoning("tool said tool-output"), text("done")],
        ])
        engine = ChatEngine(provider=provider, bridge=EchoBridge())

        [e async for e in engine.chat("q", "qwen3", thinking=True)]

        second = provider.requests[1]
        call_turn = next(m for m in second if m.get("tool_calls"))
        self.assertEqual(call_turn["reasoning_content"], "need the echo tool")
        self.assertIsNone(call_turn["content"])
        self.assertEqual(engine.messages[-1]["reasoning_content"], "tool said tool-output")

    async def test_tagged_reasoning_stream_keeps_legacy_split(self) -> None:
        provider = ScriptedProvider([[reasoning("<thi"), reasoning("nk>inspect</think>Answer.")]])
        engine = ChatEngine(provider=provider)

        events = [e async for e in engine.chat("q", "qwen3", thinking=True)]

        self.assertEqual("".join(e.text for e in events if isinstance(e, TextEvent)), "Answer.")
        self.assertEqual(engine.messages[-1], {"role": "assistant", "content": "Answer.", "reasoning_content": "inspect"})

    async def test_keep_reasoning_false_and_no_think_lanes_store_none(self) -> None:
        for kwargs in ({"keep_reasoning": False}, {"disable_reasoning_prefill": True}):
            provider = ScriptedProvider([[reasoning("plan"), text("answer")]])
            engine = ChatEngine(provider=provider)
            [e async for e in engine.chat("q", "qwen3", thinking=True, **kwargs)]
            self.assertEqual(engine.messages[-1], {"role": "assistant", "content": "answer"}, kwargs)


class ReasoningPlumbingTests(unittest.IsolatedAsyncioTestCase):
    async def test_openai_cloud_provider_drops_reasoning_content(self) -> None:
        cloud = OpenAICloudProvider(api_key="test")
        seen: list[CompletionRequest] = []

        async def fake_stream(request: CompletionRequest) -> AsyncGenerator[CompletionChunk, None]:
            seen.append(request)
            yield text("ok")

        cloud._local.stream = fake_stream  # type: ignore[method-assign]
        messages = [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a", "reasoning_content": "r"}]
        [c async for c in cloud.stream(CompletionRequest(model_id="", messages=messages, prompt_cache=False))]

        self.assertEqual(seen[0].messages[1], {"role": "assistant", "content": "a"})
        self.assertEqual(messages[1]["reasoning_content"], "r")
        self.assertEqual(seen[0].model_id, cloud._default_model)
        self.assertFalse(seen[0].prompt_cache)

    def test_compaction_estimate_counts_reasoning(self) -> None:
        plain = {"role": "assistant", "content": "a"}
        self.assertGreater(estimate_message_tokens({**plain, "reasoning_content": "x" * 400}),
                           estimate_message_tokens(plain))

    def test_resume_restores_reasoning_unless_stripped(self) -> None:
        records = [
            {"type": "engine_msg", "model": "m", "msg": {"role": "user", "content": "q"}},
            {"type": "engine_msg", "model": "m", "msg": {"role": "assistant", "content": "a", "thinking": "plan"}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.jsonl"
            path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
            kept = load_session_bundle(path).model_messages["m"][-1]
            stripped = load_session_bundle_without_thinking(path).model_messages["m"][-1]

        self.assertEqual(kept, {"role": "assistant", "content": "a", "reasoning_content": "plan"})
        self.assertEqual(stripped, {"role": "assistant", "content": "a"})


if __name__ == "__main__":
    unittest.main()
