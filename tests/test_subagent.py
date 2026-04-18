"""Tests for the subagent runner and bridge.

Uses a mock provider to exercise the streaming/tool-loop contract
without requiring a running LM Studio or network access.
"""

from __future__ import annotations

import asyncio
import json
import unittest
from typing import AsyncGenerator

from z3cli.core.config import ModelConfig
from z3cli.core.provider import (
    CompletionChunk, CompletionRequest, ContentDelta, ToolCallDelta, UsageInfo,
)
from z3cli.core.subagent import (
    SubagentConfig, SubagentDoneEvent, SubagentResult, SubagentRunner,
    SubagentStartEvent, SubagentTextEvent, format_subagent_summary,
)
from z3cli.core.subagent_bridge import SPAWN_TOOL_NAME, SubagentBridge


# ---------------------------------------------------------------------------
# Mock provider / bridge
# ---------------------------------------------------------------------------

class MockProvider:
    """A scripted Provider that yields a fixed sequence of chunks."""

    def __init__(self, scripts: list[list[CompletionChunk]]):
        self._scripts = list(scripts)
        self.calls = 0
        self.requests: list[CompletionRequest] = []

    @property
    def name(self) -> str:
        return "mock"

    async def stream(
        self, request: CompletionRequest,
    ) -> AsyncGenerator[CompletionChunk, None]:
        self.calls += 1
        self.requests.append(request)
        if not self._scripts:
            return
        for chunk in self._scripts.pop(0):
            yield chunk

    async def check_connection(self) -> bool:
        return True

    async def close(self) -> None:
        pass


class MockBridge:
    """A tool bridge with one echo tool."""

    def __init__(self) -> None:
        self.calls = 0

    def get_openai_tools(self) -> list[dict]:
        return [{
            "type": "function",
            "function": {
                "name": "echo",
                "description": "Echoes input",
                "parameters": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                },
            },
        }]

    async def call_tool(self, name: str, arguments: dict) -> str:
        self.calls += 1
        return f"ECHO: {arguments.get('text', '')}"

    def get_tool_server(self, tool_name: str) -> str:
        return "mock"

    @property
    def tool_count(self) -> int:
        return 1

    @property
    def server_names(self) -> list[str]:
        return ["mock"]

    @property
    def server_tool_counts(self) -> dict[str, int]:
        return {"mock": 1}

    async def close(self) -> None:
        pass


def text_chunks(parts: list[str]) -> list[CompletionChunk]:
    """Build a list of text-only chunks ending with usage."""
    result = [CompletionChunk(content=ContentDelta(text=p)) for p in parts]
    result.append(CompletionChunk(usage=UsageInfo(prompt_tokens=10, completion_tokens=5)))
    return result


def make_model(name: str = "test-model") -> ModelConfig:
    return ModelConfig(
        name=name,
        model_id=f"{name}-id",
        provider="studio",
        temperature=0.3,
        max_tokens=256,
        role="test specialist",
        tools_enabled=True,
        tool_profile="",
    )


# ---------------------------------------------------------------------------
# Runner tests
# ---------------------------------------------------------------------------

class SubagentRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_spawn_text_only(self) -> None:
        provider = MockProvider([text_chunks(["Hello ", "world"])])
        runner = SubagentRunner()
        config = SubagentConfig(name="tester", model=make_model())

        result = await runner.spawn(
            config, "say hi", provider_override=provider,
        )

        self.assertEqual(result.text, "Hello world")
        self.assertEqual(result.prompt_tokens, 10)
        self.assertEqual(result.completion_tokens, 5)
        self.assertEqual(result.tool_calls, 0)
        self.assertEqual(result.error, "")
        self.assertEqual(result.name, "tester")
        self.assertEqual(result.model_name, "test-model")

    async def test_event_callback_order(self) -> None:
        provider = MockProvider([text_chunks(["A", "B", "C"])])
        runner = SubagentRunner()
        events: list = []

        async def on_event(evt) -> None:
            events.append(evt)

        await runner.spawn(
            SubagentConfig(name="order-test", model=make_model()),
            "test", provider_override=provider, on_event=on_event,
        )

        self.assertIsInstance(events[0], SubagentStartEvent)
        self.assertIsInstance(events[-1], SubagentDoneEvent)
        text_events = [e for e in events if isinstance(e, SubagentTextEvent)]
        self.assertEqual([e.delta for e in text_events], ["A", "B", "C"])

    async def test_default_event_hook_is_used_when_spawn_has_no_callback(self) -> None:
        provider = MockProvider([text_chunks(["nested"])])
        events: list = []

        async def on_event(evt) -> None:
            events.append(evt)

        runner = SubagentRunner(event_hook=on_event)
        await runner.spawn(
            SubagentConfig(name="hook-test", model=make_model("hook-test")),
            "test",
            provider_override=provider,
        )

        self.assertIsInstance(events[0], SubagentStartEvent)
        self.assertIsInstance(events[-1], SubagentDoneEvent)

    async def test_tool_call_round(self) -> None:
        tool_round = [
            CompletionChunk(
                tool_calls=[ToolCallDelta(id="t1", name="echo", arguments='{"text": "hi"}')],
                stop_reason="tool_use",
            ),
            CompletionChunk(usage=UsageInfo(prompt_tokens=5, completion_tokens=2)),
        ]
        final_round = text_chunks(["Done: hi"])

        provider = MockProvider([tool_round, final_round])
        bridge = MockBridge()
        runner = SubagentRunner(bridge=bridge)

        result = await runner.spawn(
            SubagentConfig(name="tool-test", model=make_model(), max_rounds=2),
            "use the echo tool",
            provider_override=provider,
            bridge_override=bridge,
        )

        self.assertEqual(result.tool_calls, 1)
        self.assertEqual(bridge.calls, 1)
        self.assertIn("Done: hi", result.text)
        self.assertEqual(result.prompt_tokens, 15)
        self.assertEqual(result.completion_tokens, 7)

    async def test_spawn_honors_native_tools_false_and_manual_tool_prompt(self) -> None:
        provider = MockProvider([text_chunks(["ok"])])
        bridge = MockBridge()
        model = make_model("qwen3-oracle-8b")
        model.native_tools = False
        model.deferred_tools = True
        runner = SubagentRunner(
            bridge=bridge,
            bridge_wrapper=lambda b, _model: b,
        )

        result = await runner.spawn(
            SubagentConfig(name="xml-tools", model=model),
            "inspect the workspace and use tools if needed",
            provider_override=provider,
        )

        self.assertEqual(result.text, "ok")
        self.assertEqual(len(provider.requests), 1)
        request = provider.requests[0]
        self.assertIsNone(request.tools)
        self.assertIn("manual XML tool calls", request.system)
        self.assertIn("<tool_call>{\"name\":\"tool_name\",\"arguments\":{...}}</tool_call>", request.system)
        self.assertIn("If the needed tool is not visible yet, call `tool_search` first", request.system)
        self.assertIn("Do not claim to be Claude, Anthropic, OpenAI, or ChatGPT.", request.system)

    async def test_bridge_wrapper_runs_for_full_surface_models_without_tool_profile(self) -> None:
        provider = MockProvider([text_chunks(["wrapped"])])
        bridge = MockBridge()
        wrapped: list[str] = []

        def wrapper(b, model):
            wrapped.append(model.name)
            return b

        model = make_model("full-surface")
        model.tool_profile = ""
        model.deferred_tools = True
        runner = SubagentRunner(bridge=bridge, bridge_wrapper=wrapper)

        result = await runner.spawn(
            SubagentConfig(name="full-surface", model=model),
            "read something",
            provider_override=provider,
        )

        self.assertEqual(result.text, "wrapped")
        self.assertEqual(wrapped, ["full-surface"])

    async def test_runs_in_parallel(self) -> None:
        provider1 = MockProvider([text_chunks(["A"])])
        provider2 = MockProvider([text_chunks(["B"])])
        runner = SubagentRunner()

        async def run_one(provider, name):
            return await runner.spawn(
                SubagentConfig(name=name, model=make_model(name)),
                "go", provider_override=provider,
            )

        r1, r2 = await asyncio.gather(
            run_one(provider1, "a"),
            run_one(provider2, "b"),
        )

        self.assertEqual(r1.text, "A")
        self.assertEqual(r2.text, "B")
        self.assertEqual(r1.name, "a")
        self.assertEqual(r2.name, "b")

    async def test_isolates_history(self) -> None:
        provider_1 = MockProvider([text_chunks(["first"])])
        provider_2 = MockProvider([text_chunks(["second"])])
        runner = SubagentRunner()

        r1 = await runner.spawn(
            SubagentConfig(name="one", model=make_model()),
            "prompt-1", provider_override=provider_1,
        )
        r2 = await runner.spawn(
            SubagentConfig(name="two", model=make_model()),
            "prompt-2", provider_override=provider_2,
        )

        self.assertEqual(r1.text, "first")
        self.assertEqual(r2.text, "second")
        self.assertEqual(provider_1.calls, 1)
        self.assertEqual(provider_2.calls, 1)

    async def test_timeout_cancels_inflight_tool_task(self) -> None:
        class SlowBridge(MockBridge):
            def __init__(self) -> None:
                super().__init__()
                self.started = asyncio.Event()
                self.was_cancelled = False

            async def call_tool(self, name: str, arguments: dict) -> str:  # type: ignore[override]
                self.calls += 1
                self.started.set()
                try:
                    await asyncio.sleep(5)
                except asyncio.CancelledError:
                    self.was_cancelled = True
                    raise
                return "unreachable"

        tool_round = [
            CompletionChunk(
                tool_calls=[ToolCallDelta(id="t1", name="echo", arguments='{"text": "slow"}')],
                stop_reason="tool_use",
            ),
            CompletionChunk(usage=UsageInfo(prompt_tokens=5, completion_tokens=2)),
        ]

        provider = MockProvider([tool_round])
        bridge = SlowBridge()
        runner = SubagentRunner(bridge=bridge)

        result = await runner.spawn(
            SubagentConfig(
                name="timeout-test",
                model=make_model(),
                timeout_seconds=0.05,
                max_rounds=2,
            ),
            "use the slow tool",
            provider_override=provider,
            bridge_override=bridge,
        )

        self.assertIn("timed out", result.error)
        await asyncio.wait_for(bridge.started.wait(), timeout=1)
        for _ in range(40):
            if bridge.was_cancelled:
                break
            await asyncio.sleep(0.01)
        self.assertTrue(bridge.was_cancelled)


# ---------------------------------------------------------------------------
# Subagent bridge tests
# ---------------------------------------------------------------------------

class SubagentBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_lists_specialists(self) -> None:
        models = {
            "nayru": make_model("nayru"),
            "farore": make_model("farore"),
        }
        runner = SubagentRunner()
        bridge = SubagentBridge(runner=runner, models=models)

        raw = await bridge.call_tool("list_subagents", {})
        data = json.loads(raw)
        self.assertIn("specialists", data)
        names = [s["name"] for s in data["specialists"]]
        self.assertIn("nayru", names)
        self.assertIn("farore", names)

    async def test_lists_specialists_exposes_spawn_only_worker_to_allowed_parent(self) -> None:
        models = {
            "oracle": make_model("oracle"),
            "oracle-coder": make_model("oracle-coder"),
        }
        models["oracle-coder"].visibility = "hidden"
        models["oracle-coder"].spawn_only = True
        models["oracle-coder"].spawnable_by = ["oracle", "oracle-fast"]
        runner = SubagentRunner()
        bridge = SubagentBridge(runner=runner, models=models, parent_model="oracle")

        raw = await bridge.call_tool("list_subagents", {})
        data = json.loads(raw)

        self.assertEqual([entry["name"] for entry in data["specialists"]], ["oracle-coder"])

    async def test_lists_specialists_hide_spawn_only_worker_from_disallowed_parent(self) -> None:
        models = {
            "claude-sonnet": make_model("claude-sonnet"),
            "oracle-coder": make_model("oracle-coder"),
        }
        models["oracle-coder"].visibility = "hidden"
        models["oracle-coder"].spawn_only = True
        models["oracle-coder"].spawnable_by = ["oracle", "oracle-fast"]
        runner = SubagentRunner()
        bridge = SubagentBridge(runner=runner, models=models, parent_model="claude-sonnet")

        raw = await bridge.call_tool("list_subagents", {})
        data = json.loads(raw)

        self.assertEqual(data["specialists"], [])

    async def test_rejects_unknown_model(self) -> None:
        runner = SubagentRunner()
        bridge = SubagentBridge(runner=runner, models={})

        result = await bridge.call_tool(
            SPAWN_TOOL_NAME,
            {"model": "does-not-exist", "prompt": "test"},
        )
        self.assertIn("Unknown model", result)

    async def test_rejects_empty_prompt(self) -> None:
        runner = SubagentRunner()
        bridge = SubagentBridge(runner=runner, models={"x": make_model("x")})

        result = await bridge.call_tool(
            SPAWN_TOOL_NAME,
            {"model": "x", "prompt": ""},
        )
        self.assertIn("required", result)

    async def test_spawn_uses_runner_prompt_enricher(self) -> None:
        models = {"nayru": make_model("nayru")}

        async def enrich(prompt: str, model: ModelConfig) -> str:
            self.assertEqual(model.name, "nayru")
            return prompt + "\n\nAttached file context:\n@src/main.asm"

        runner = SubagentRunner(prompt_enricher=enrich)
        captured: dict[str, str] = {}

        async def fake_spawn(config, prompt, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            captured["model"] = config.model.name
            captured["prompt"] = prompt
            return SubagentResult(
                id="sub-1-nayru",
                name=config.name,
                model_name=config.model.name,
                text="ok",
            )

        runner.spawn = fake_spawn  # type: ignore[assignment]
        bridge = SubagentBridge(runner=runner, models=models)

        raw = await bridge.call_tool(
            SPAWN_TOOL_NAME,
            {"model": "nayru", "prompt": "inspect @src/main.asm"},
        )

        self.assertEqual(captured["model"], "nayru")
        self.assertIn("Attached file context:", captured["prompt"])
        self.assertIn("@src/main.asm", captured["prompt"])
        self.assertEqual(json.loads(raw)["text"], "ok")

    async def test_spawn_uses_async_model_aware_system_context(self) -> None:
        models = {"nayru": make_model("nayru")}

        async def system_context(model: ModelConfig, prompt: str) -> str:
            self.assertEqual(model.name, "nayru")
            self.assertEqual(prompt, "inspect this")
            return f"context:{model.name}:{prompt}"

        runner = SubagentRunner(system_context_resolver=system_context)
        captured: dict[str, str] = {}

        async def fake_spawn(config, prompt, **kwargs):  # type: ignore[no-untyped-def]
            del prompt
            captured["model"] = config.model.name
            captured["system_context"] = str(kwargs.get("system_context", ""))
            return SubagentResult(
                id="sub-1-nayru",
                name=config.name,
                model_name=config.model.name,
                text="ok",
            )

        runner.spawn = fake_spawn  # type: ignore[assignment]
        bridge = SubagentBridge(
            runner=runner,
            models=models,
            system_context_fn=runner.resolve_system_context,
        )

        raw = await bridge.call_tool(
            SPAWN_TOOL_NAME,
            {"model": "nayru", "prompt": "inspect this"},
        )

        self.assertEqual(captured["model"], "nayru")
        self.assertEqual(captured["system_context"], "context:nayru:inspect this")
        self.assertEqual(json.loads(raw)["text"], "ok")

    async def test_rejects_spawn_only_worker_for_disallowed_parent(self) -> None:
        models = {"oracle-coder": make_model("oracle-coder")}
        models["oracle-coder"].visibility = "hidden"
        models["oracle-coder"].spawn_only = True
        models["oracle-coder"].spawnable_by = ["oracle", "oracle-fast"]
        runner = SubagentRunner()
        bridge = SubagentBridge(runner=runner, models=models, parent_model="claude-sonnet")

        result = await bridge.call_tool(
            SPAWN_TOOL_NAME,
            {"model": "oracle-coder", "prompt": "repair this hook"},
        )

        self.assertIn("not available", result)

    def test_exposes_two_tools(self) -> None:
        runner = SubagentRunner()
        bridge = SubagentBridge(runner=runner, models={"x": make_model("x")})
        tools = bridge.get_openai_tools()
        names = [t["function"]["name"] for t in tools]
        self.assertIn("spawn_subagent", names)
        self.assertIn("list_subagents", names)
        self.assertEqual(bridge.tool_count, 2)


# ---------------------------------------------------------------------------
# Summary formatter
# ---------------------------------------------------------------------------

class SummaryFormatterTests(unittest.TestCase):
    def test_format_includes_text_and_stats(self) -> None:
        results = [
            SubagentResult(
                id="s1", name="nayru", model_name="nayru",
                text="Reviewed the hook.",
                prompt_tokens=100, completion_tokens=50, tool_calls=2,
            ),
            SubagentResult(
                id="s2", name="farore", model_name="farore",
                text="", error="bridge not connected",
            ),
        ]
        out = format_subagent_summary(results)
        self.assertIn("nayru", out)
        self.assertIn("Reviewed the hook.", out)
        self.assertIn("tokens: 100/50", out)
        self.assertIn("tools: 2", out)
        self.assertIn("Error:", out)
        self.assertIn("bridge not connected", out)


if __name__ == "__main__":
    unittest.main()
