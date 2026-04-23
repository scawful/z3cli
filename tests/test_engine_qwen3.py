import asyncio
import unittest
from typing import AsyncGenerator, Any, cast

import httpx

from z3cli.core.engine import (
    ChatEngine,
    DoneEvent,
    ErrorEvent,
    TextEvent,
    ThinkingEvent,
    ToolResultEvent,
    _extract_xml_tool_calls,
    summarize_tool_result_for_history,
)
from z3cli.app.runtime import (
    build_local_identity_prompt,
    build_oracle_answer_after_grounding_prompt,
    build_oracle_natural_chat_prompt,
    build_tool_bias_prompt,
    build_tool_use_prompt,
)
from z3cli.core.config import ModelConfig
from z3cli.core.provider import CompletionChunk, CompletionRequest, ContentDelta, ProviderError, ToolCallDelta, UsageInfo


class MockProvider:
    def __init__(self, scripts: list[list[CompletionChunk]]):
        self._scripts = list(scripts)

    @property
    def name(self) -> str:
        return "local"

    async def stream(
        self,
        request: CompletionRequest,
    ) -> AsyncGenerator[CompletionChunk, None]:
        if not self._scripts:
            return
        for chunk in self._scripts.pop(0):
            yield chunk

    async def check_connection(self) -> bool:
        return True

    async def close(self) -> None:
        pass


class ToolGuidancePromptTests(unittest.TestCase):
    def test_local_identity_prompt_blocks_vendor_claims_for_studio_models(self) -> None:
        prompt = build_local_identity_prompt(ModelConfig(
            name="farore",
            model_id="gguf/zelda/farore-9b-q8_0.gguf",
            provider="studio",
        ))
        self.assertIn("Do not claim to be Claude, Anthropic, OpenAI, or ChatGPT.", prompt)
        self.assertIn("farore", prompt)

    def test_local_identity_prompt_skips_cloud_models(self) -> None:
        prompt = build_local_identity_prompt(ModelConfig(
            name="claude-sonnet",
            model_id="claude-sonnet-4",
            provider="anthropic",
        ))
        self.assertEqual(prompt, "")

    def test_din_tool_prompt_forbids_pseudo_calls_and_mentions_file_reads(self) -> None:
        prompt = build_tool_use_prompt(True, "din")
        self.assertIn("Do not print JSON or pseudo-commands", prompt)
        self.assertIn("read_context", prompt)
        self.assertIn("check_diagnostics", prompt)

    def test_farore_tool_prompt_prefers_non_emulator_demo_tools(self) -> None:
        prompt = build_tool_use_prompt(True, "farore")
        self.assertIn("scenario_run", prompt)
        self.assertIn("inspect_room", prompt)
        self.assertIn("read_state", prompt)

    def test_tool_bias_prompt_pushes_tool_first_for_debug_requests(self) -> None:
        prompt = build_tool_bias_prompt(
            "inspect this asm file and check diagnostics",
            True,
            "din",
            deferred_tools=False,
        )
        self.assertIn("Lead with the tool call", prompt)
        self.assertIn("diagnostics", prompt)
        self.assertIn("path is known to be valid", prompt)

    def test_tool_bias_prompt_is_empty_for_non_tool_requests(self) -> None:
        prompt = build_tool_bias_prompt("say hello politely", True, "din")
        self.assertEqual(prompt, "")

    def test_disabled_tool_prompt_is_empty(self) -> None:
        self.assertEqual(build_tool_use_prompt(False, "din"), "")

    def test_tool_prompt_describes_xml_tool_mode_for_local_qwen3_lanes(self) -> None:
        prompt = build_tool_use_prompt(
            True,
            "",
            deferred_tools=True,
            native_tools=False,
        )
        self.assertIn("manual XML tool calls", prompt)
        self.assertIn("<tool_call>", prompt)
        self.assertIn("tool_search", prompt)
        self.assertIn("Do not invent tool names", prompt)
        self.assertIn("do not answer from memory", prompt.lower())

    def test_tool_bias_prompt_mentions_xml_tool_block_when_native_tools_disabled(self) -> None:
        prompt = build_tool_bias_prompt(
            "inspect this file",
            True,
            "",
            deferred_tools=True,
            native_tools=False,
        )
        self.assertIn("<tool_call>", prompt)

    def test_history_summary_compacts_list_subagents_blob(self) -> None:
        result = summarize_tool_result_for_history(
            "list_subagents",
            '{"specialists":[{"name":"din"},{"name":"farore"},{"name":"nayru"}]}',
            max_chars=4000,
        )

        self.assertEqual(result, "Available specialists (3): din, farore, nayru")

    def test_history_summary_reduces_workspace_symbol_dump(self) -> None:
        result = summarize_tool_result_for_history(
            "label_lookup",
            "\n".join([
                "Workspace symbols (4 of 4):",
                "- A",
                "- B",
                "- C",
                "- D",
            ]),
            max_chars=4000,
        )

        self.assertIn("Workspace symbols (4 of 4):", result)
        self.assertIn("... (+1 more matches)", result)

    def test_oracle_answer_after_grounding_prompt_skips_exhaustive_debug_turns(self) -> None:
        prompt = build_oracle_answer_after_grounding_prompt("Investigate why this minecart regression happens step by step.")

        self.assertEqual(prompt, "")

    def test_oracle_natural_chat_prompt_encourages_single_clarifier(self) -> None:
        prompt = build_oracle_natural_chat_prompt("minecart is weird")

        self.assertIn("casually, tersely, or by implication", prompt)
        self.assertIn("exactly one short clarifying question", prompt)
        self.assertIn("Do not lecture the user about prompting quality", prompt)


class FlakyProvider:
    def __init__(self) -> None:
        self.calls = 0

    @property
    def name(self) -> str:
        return "local"

    async def stream(
        self,
        request: CompletionRequest,
    ) -> AsyncGenerator[CompletionChunk, None]:
        del request
        self.calls += 1
        if self.calls == 1:
            raise httpx.ConnectError("temporary failure")
        yield CompletionChunk(content=ContentDelta(text="retry-ok"))
        yield CompletionChunk(usage=UsageInfo(prompt_tokens=3, completion_tokens=2))

    async def check_connection(self) -> bool:
        return True

    async def close(self) -> None:
        pass


class ToolTimeoutProvider:
    def __init__(self) -> None:
        self.calls = 0

    @property
    def name(self) -> str:
        return "local"

    async def stream(
        self,
        request: CompletionRequest,
    ) -> AsyncGenerator[CompletionChunk, None]:
        del request
        self.calls += 1
        if self.calls == 1:
            yield CompletionChunk(tool_calls=[ToolCallDelta(id="tc-1", name="sleep_tool", arguments="{}")])
            return
        yield CompletionChunk(content=ContentDelta(text="after-timeout"))
        yield CompletionChunk(usage=UsageInfo(prompt_tokens=2, completion_tokens=2))

    async def check_connection(self) -> bool:
        return True

    async def close(self) -> None:
        pass


class Burst429Provider:
    def __init__(self) -> None:
        self.calls = 0

    @property
    def name(self) -> str:
        return "local"

    async def stream(
        self,
        request: CompletionRequest,
    ) -> AsyncGenerator[CompletionChunk, None]:
        del request
        self.calls += 1
        raise ProviderError("API 429: rate limited")
        yield CompletionChunk()

    async def check_connection(self) -> bool:
        return True

    async def close(self) -> None:
        pass


class MultiToolTimeoutProvider:
    def __init__(self) -> None:
        self.calls = 0

    @property
    def name(self) -> str:
        return "local"

    async def stream(
        self,
        request: CompletionRequest,
    ) -> AsyncGenerator[CompletionChunk, None]:
        del request
        self.calls += 1
        if self.calls <= 2:
            yield CompletionChunk(tool_calls=[ToolCallDelta(id=f"tc-{self.calls}", name="sleep_tool", arguments="{}")])
            return
        yield CompletionChunk(content=ContentDelta(text="after-storm"))
        yield CompletionChunk(usage=UsageInfo(prompt_tokens=2, completion_tokens=1))

    async def check_connection(self) -> bool:
        return True

    async def close(self) -> None:
        pass


class ToolThenAnswerProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.requests: list[CompletionRequest] = []

    @property
    def name(self) -> str:
        return "local"

    async def stream(
        self,
        request: CompletionRequest,
    ) -> AsyncGenerator[CompletionChunk, None]:
        self.requests.append(request)
        self.calls += 1
        if self.calls == 1:
            yield CompletionChunk(tool_calls=[ToolCallDelta(id="tc-1", name="label_lookup", arguments='{"query":"Minecart"}')])
            return
        yield CompletionChunk(content=ContentDelta(text="grounded answer"))
        yield CompletionChunk(usage=UsageInfo(prompt_tokens=2, completion_tokens=1))

    async def check_connection(self) -> bool:
        return True

    async def close(self) -> None:
        pass


class HangingBridge:
    def get_openai_tools(self) -> list[dict]:
        return [{
            "type": "function",
            "function": {
                "name": "sleep_tool",
                "description": "hangs forever",
                "parameters": {"type": "object", "properties": {}},
            },
        }]

    async def call_tool(self, name: str, arguments: dict) -> str:
        del name, arguments
        await asyncio.sleep(1.0)
        return "never"

    def get_tool_server(self, tool_name: str) -> str:
        del tool_name
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
        return None


class EchoBridge:
    def get_openai_tools(self) -> list[dict]:
        return [{
            "type": "function",
            "function": {
                "name": "echo",
                "description": "echo tool",
                "parameters": {"type": "object", "properties": {}},
            },
        }]

    async def call_tool(self, name: str, arguments: dict) -> str:
        del name, arguments
        return "tool-output"

    def get_tool_server(self, tool_name: str) -> str:
        del tool_name
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
        return None


class GroundingBridge:
    def get_openai_tools(self) -> list[dict]:
        return [{
            "type": "function",
            "function": {
                "name": "label_lookup",
                "description": "resolve label",
                "parameters": {"type": "object", "properties": {}},
            },
        }]

    async def call_tool(self, name: str, arguments: dict) -> str:
        del name, arguments
        return "Sprite_Minecart @ /tmp/minecart.asm:1"

    def get_tool_server(self, tool_name: str) -> str:
        del tool_name
        return "oracle"

    @property
    def tool_count(self) -> int:
        return 1

    @property
    def server_names(self) -> list[str]:
        return ["oracle"]

    @property
    def server_tool_counts(self) -> dict[str, int]:
        return {"oracle": 1}

    async def close(self) -> None:
        return None


class BadArgumentsBridge:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def get_openai_tools(self) -> list[dict]:
        return [{
            "type": "function",
            "function": {
                "name": "echo",
                "description": "echo tool",
                "parameters": {"type": "object", "properties": {}},
            },
        }]

    async def call_tool(self, name: str, arguments: dict) -> str:
        self.calls.append((name, dict(arguments)))
        return "tool-output"

    def get_tool_server(self, tool_name: str) -> str:
        del tool_name
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
        return None


class MalformedToolArgumentProvider:
    @property
    def name(self) -> str:
        return "local"

    async def stream(
        self,
        request: CompletionRequest,
    ) -> AsyncGenerator[CompletionChunk, None]:
        del request
        yield CompletionChunk(
            tool_calls=[ToolCallDelta(id="bad-1", name="echo", arguments="{\"text\":\"oops\"" )]
        )
        return

    async def check_connection(self) -> bool:
        return True

    async def close(self) -> None:
        pass


class ToolArgumentTypeProvider:
    @property
    def name(self) -> str:
        return "local"

    async def stream(
        self,
        request: CompletionRequest,
    ) -> AsyncGenerator[CompletionChunk, None]:
        del request
        yield CompletionChunk(
            tool_calls=[ToolCallDelta(id="bad-type-1", name="echo", arguments='"oops"')]
        )
        return

    async def check_connection(self) -> bool:
        return True

    async def close(self) -> None:
        pass


class ToolArgumentListProvider:
    @property
    def name(self) -> str:
        return "local"

    async def stream(
        self,
        request: CompletionRequest,
    ) -> AsyncGenerator[CompletionChunk, None]:
        del request
        yield CompletionChunk(
            tool_calls=[ToolCallDelta(id="bad-list-1", name="echo", arguments="[]")]
        )
        return

    async def check_connection(self) -> bool:
        return True

    async def close(self) -> None:
        pass


class ToolArgumentNumberProvider:
    @property
    def name(self) -> str:
        return "local"

    async def stream(
        self,
        request: CompletionRequest,
    ) -> AsyncGenerator[CompletionChunk, None]:
        del request
        yield CompletionChunk(
            tool_calls=[ToolCallDelta(id="bad-number-1", name="echo", arguments="123")]
        )
        return

    async def check_connection(self) -> bool:
        return True

    async def close(self) -> None:
        pass


class ToolArgumentDictProvider:
    @property
    def name(self) -> str:
        return "local"

    async def stream(
        self,
        request: CompletionRequest,
    ) -> AsyncGenerator[CompletionChunk, None]:
        del request
        yield CompletionChunk(
            tool_calls=[ToolCallDelta(
                id="bad-dict-1",
                name="echo",
                arguments=cast(Any, {"text": "oops"}),
            )]
        )
        return

    async def check_connection(self) -> bool:
        return True

    async def close(self) -> None:
        pass


class TwoRoundToolProvider:
    def __init__(self) -> None:
        self.calls = 0

    @property
    def name(self) -> str:
        return "local"

    async def stream(
        self,
        request: CompletionRequest,
    ) -> AsyncGenerator[CompletionChunk, None]:
        del request
        self.calls += 1
        if self.calls == 1:
            yield CompletionChunk(tool_calls=[ToolCallDelta(id="tc-1", name="echo", arguments="{}")])
            return
        yield CompletionChunk(content=ContentDelta(text="after-tool"))
        yield CompletionChunk(usage=UsageInfo(prompt_tokens=2, completion_tokens=1))

    async def check_connection(self) -> bool:
        return True

    async def close(self) -> None:
        pass


class Qwen3ParsingTests(unittest.IsolatedAsyncioTestCase):
    async def test_reasoning_content_splits_thinking_and_text(self) -> None:
        provider = MockProvider([[
            CompletionChunk(content=ContentDelta(reasoning="<thi")),
            CompletionChunk(content=ContentDelta(reasoning="nk>inspect")),
            CompletionChunk(content=ContentDelta(reasoning=" $420C</think>Use DMA init.")),
            CompletionChunk(usage=UsageInfo(prompt_tokens=7, completion_tokens=3)),
        ]])
        engine = ChatEngine(provider=provider)

        events = [event async for event in engine.chat("why?", "qwen3", thinking=True)]

        thinking = "".join(event.text for event in events if isinstance(event, ThinkingEvent))
        text = "".join(event.text for event in events if isinstance(event, TextEvent))
        done = [event for event in events if isinstance(event, DoneEvent)]

        self.assertEqual(thinking, "inspect $420C")
        self.assertEqual(text, "Use DMA init.")
        self.assertEqual(len(done), 1)
        self.assertEqual(engine.messages[-1]["content"], "Use DMA init.")

    def test_extract_xml_tool_calls_parses_qwen3_tool_call_blocks(self) -> None:
        calls = _extract_xml_tool_calls(
            '<tool_call>{"name":"echo","arguments":{"text":"hi"}}</tool_call>'
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "echo")
        self.assertEqual(calls[0]["arguments"], '{"text": "hi"}')

    def test_extract_xml_tool_calls_parses_shorthand_tool_call_blocks(self) -> None:
        calls = _extract_xml_tool_calls('tool_search{"query":"read context"}')

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "tool_search")
        self.assertEqual(calls[0]["arguments"], '{"query": "read context"}')

    async def test_retry_transient_provider_connect_error_once(self) -> None:
        provider = FlakyProvider()
        engine = ChatEngine(
            provider=provider,
            provider_max_retries=1,
            provider_retry_base_s=0.0,
        )

        events = [event async for event in engine.chat("ping", "nayru")]

        self.assertEqual(provider.calls, 2)
        self.assertEqual(engine.provider_retry_count, 1)
        self.assertGreaterEqual(engine.provider_retry_backoff_ms, 0)
        self.assertTrue(any(isinstance(event, TextEvent) and event.text == "retry-ok" for event in events))
        self.assertTrue(any(isinstance(event, DoneEvent) for event in events))

    async def test_tool_timeout_yields_result_and_tracks_counter(self) -> None:
        provider = ToolTimeoutProvider()
        bridge = HangingBridge()
        engine = ChatEngine(
            provider=provider,
            bridge=bridge,
            tool_timeout_s=0.01,
        )

        events = [event async for event in engine.chat("run tool", "nayru", use_tools=True)]

        timeout_results = [
            event.result
            for event in events
            if isinstance(event, ToolResultEvent) and "timed out" in event.result
        ]
        self.assertEqual(len(timeout_results), 1)
        self.assertEqual(engine.tool_timeout_count, 1)
        self.assertTrue(any(isinstance(event, DoneEvent) for event in events))

    async def test_answer_after_first_grounding_disables_extra_tool_rounds(self) -> None:
        provider = ToolThenAnswerProvider()
        engine = ChatEngine(
            provider=provider,
            bridge=GroundingBridge(),
        )

        events = [
            event async for event in engine.chat(
                "Let's take a look at the Minecart sprite.",
                "oracle-pro",
                use_tools=True,
                answer_after_first_grounding=True,
                answer_after_grounding_system="Answer from the grounded evidence now.",
            )
        ]

        self.assertEqual(provider.calls, 2)
        self.assertEqual(len(provider.requests), 2)
        self.assertIsNotNone(provider.requests[0].tools)
        self.assertIsNone(provider.requests[1].tools)
        self.assertIn("Answer from the grounded evidence now.", provider.requests[1].system)
        self.assertTrue(any(isinstance(event, TextEvent) and event.text == "grounded answer" for event in events))
        self.assertTrue(any(isinstance(event, DoneEvent) for event in events))

    async def test_retry_burst_429_counts_error_after_retry_budget_exhausted(self) -> None:
        provider = Burst429Provider()
        engine = ChatEngine(
            provider=provider,
            provider_max_retries=2,
            provider_retry_base_s=0.0,
        )

        events = [event async for event in engine.chat("ping", "nayru")]

        self.assertEqual(provider.calls, 3)
        self.assertEqual(engine.provider_retry_count, 2)
        self.assertEqual(engine.provider_error_count, 1)
        self.assertTrue(any(isinstance(event, ErrorEvent) and "429" in event.message for event in events))
        self.assertFalse(any(isinstance(event, DoneEvent) for event in events))

    async def test_tool_timeout_storm_counts_each_timeout(self) -> None:
        provider = MultiToolTimeoutProvider()
        bridge = HangingBridge()
        engine = ChatEngine(
            provider=provider,
            bridge=bridge,
            tool_timeout_s=0.01,
        )

        events = [event async for event in engine.chat("run tools", "nayru", use_tools=True)]
        timeout_results = [
            event
            for event in events
            if isinstance(event, ToolResultEvent) and "timed out" in event.result
        ]
        self.assertEqual(len(timeout_results), 2)
        self.assertEqual(engine.tool_timeout_count, 2)
        self.assertTrue(any(isinstance(event, DoneEvent) for event in events))

    async def test_permission_hook_exception_defaults_to_denied_without_crashing(self) -> None:
        async def broken_permission(*_args) -> bool:
            raise RuntimeError("permission hook boom")

        provider = TwoRoundToolProvider()
        engine = ChatEngine(
            provider=provider,
            bridge=EchoBridge(),
            permission_hook=broken_permission,
        )

        events = [event async for event in engine.chat("run tool", "nayru", use_tools=True)]

        tool_results = [event for event in events if isinstance(event, ToolResultEvent)]
        self.assertEqual(len(tool_results), 1)
        self.assertIn("denied by user", tool_results[0].result)
        self.assertTrue(any(isinstance(event, TextEvent) and event.text == "after-tool" for event in events))
        self.assertFalse(any(isinstance(event, ErrorEvent) for event in events))
        self.assertTrue(any(isinstance(event, DoneEvent) for event in events))

    async def test_permission_hook_does_not_time_out_by_default(self) -> None:
        async def delayed_permission(*_args) -> bool:
            await asyncio.sleep(0.02)
            return True

        provider = TwoRoundToolProvider()
        engine = ChatEngine(
            provider=provider,
            bridge=EchoBridge(),
            permission_hook=delayed_permission,
        )

        events = [event async for event in engine.chat("run tool", "nayru", use_tools=True)]

        tool_results = [event for event in events if isinstance(event, ToolResultEvent)]
        self.assertEqual(len(tool_results), 1)
        self.assertEqual(tool_results[0].result, "tool-output")
        self.assertEqual(engine.hook_timeout_count, 0)
        self.assertTrue(any(isinstance(event, DoneEvent) for event in events))

    async def test_permission_hook_timeout_still_denies_when_explicitly_enabled(self) -> None:
        async def delayed_permission(*_args) -> bool:
            await asyncio.sleep(0.02)
            return True

        provider = TwoRoundToolProvider()
        engine = ChatEngine(
            provider=provider,
            bridge=EchoBridge(),
            permission_hook=delayed_permission,
            permission_hook_timeout_s=0.01,
        )

        events = [event async for event in engine.chat("run tool", "nayru", use_tools=True)]

        tool_results = [event for event in events if isinstance(event, ToolResultEvent)]
        self.assertEqual(len(tool_results), 1)
        self.assertIn("denied by user", tool_results[0].result)
        self.assertEqual(engine.hook_timeout_count, 1)
        self.assertTrue(any(isinstance(event, DoneEvent) for event in events))

    async def test_post_tool_hook_exception_falls_back_to_original_result(self) -> None:
        async def broken_post_hook(*_args) -> str:
            raise RuntimeError("post hook boom")

        provider = TwoRoundToolProvider()
        engine = ChatEngine(
            provider=provider,
            bridge=EchoBridge(),
            post_tool_hook=broken_post_hook,
        )

        events = [event async for event in engine.chat("run tool", "nayru", use_tools=True)]

        tool_results = [event for event in events if isinstance(event, ToolResultEvent)]
        self.assertEqual(len(tool_results), 1)
        self.assertEqual(tool_results[0].result, "tool-output")
        self.assertFalse(any(isinstance(event, ErrorEvent) for event in events))
        self.assertTrue(any(isinstance(event, DoneEvent) for event in events))

    async def test_malformed_tool_arguments_are_reported_as_tool_error(self) -> None:
        provider = MalformedToolArgumentProvider()
        bridge = BadArgumentsBridge()
        engine = ChatEngine(
            provider=provider,
            bridge=bridge,
            tool_timeout_s=0.01,
        )

        events = [event async for event in engine.chat("run tool", "nayru", use_tools=True)]

        tool_results = [event for event in events if isinstance(event, ToolResultEvent)]
        self.assertEqual(len(tool_results), 1)
        self.assertIn("Invalid tool arguments", tool_results[0].result)
        self.assertIn("Tool execution error", tool_results[0].result)
        self.assertEqual(bridge.calls, [])
        self.assertTrue(any(isinstance(event, ErrorEvent) for event in events))
        self.assertFalse(any(isinstance(event, DoneEvent) for event in events))

    async def test_nondict_tool_arguments_are_reported_as_tool_error(self) -> None:
        provider = ToolArgumentTypeProvider()
        bridge = BadArgumentsBridge()
        engine = ChatEngine(
            provider=provider,
            bridge=bridge,
            tool_timeout_s=0.01,
        )

        events = [event async for event in engine.chat("run tool", "nayru", use_tools=True)]

        tool_results = [event for event in events if isinstance(event, ToolResultEvent)]
        self.assertEqual(len(tool_results), 1)
        self.assertIn("Invalid tool arguments", tool_results[0].result)
        self.assertIn("Tool execution error", tool_results[0].result)
        self.assertEqual(bridge.calls, [])
        self.assertTrue(any(isinstance(event, ErrorEvent) for event in events))
        self.assertFalse(any(isinstance(event, DoneEvent) for event in events))

    async def test_list_tool_arguments_are_reported_as_tool_error(self) -> None:
        provider = ToolArgumentListProvider()
        bridge = BadArgumentsBridge()
        engine = ChatEngine(
            provider=provider,
            bridge=bridge,
            tool_timeout_s=0.01,
        )

        events = [event async for event in engine.chat("run tool", "nayru", use_tools=True)]

        tool_results = [event for event in events if isinstance(event, ToolResultEvent)]
        self.assertEqual(len(tool_results), 1)
        self.assertIn("Invalid tool arguments", tool_results[0].result)
        self.assertIn("Tool execution error", tool_results[0].result)
        self.assertEqual(bridge.calls, [])
        self.assertTrue(any(isinstance(event, ErrorEvent) for event in events))
        self.assertFalse(any(isinstance(event, DoneEvent) for event in events))

    async def test_numeric_tool_arguments_are_reported_as_tool_error(self) -> None:
        provider = ToolArgumentNumberProvider()
        bridge = BadArgumentsBridge()
        engine = ChatEngine(
            provider=provider,
            bridge=bridge,
            tool_timeout_s=0.01,
        )

        events = [event async for event in engine.chat("run tool", "nayru", use_tools=True)]

        tool_results = [event for event in events if isinstance(event, ToolResultEvent)]
        self.assertEqual(len(tool_results), 1)
        self.assertIn("Invalid tool arguments", tool_results[0].result)
        self.assertIn("Tool execution error", tool_results[0].result)
        self.assertEqual(bridge.calls, [])
        self.assertTrue(any(isinstance(event, ErrorEvent) for event in events))
        self.assertFalse(any(isinstance(event, DoneEvent) for event in events))

    async def test_dict_tool_arguments_are_reported_as_tool_error(self) -> None:
        provider = ToolArgumentDictProvider()
        bridge = BadArgumentsBridge()
        engine = ChatEngine(
            provider=provider,
            bridge=bridge,
            tool_timeout_s=0.01,
        )

        events = [event async for event in engine.chat("run tool", "nayru", use_tools=True)]

        tool_results = [event for event in events if isinstance(event, ToolResultEvent)]
        self.assertEqual(len(tool_results), 1)
        self.assertIn("Invalid tool arguments", tool_results[0].result)
        self.assertIn("Tool execution error", tool_results[0].result)
        self.assertEqual(bridge.calls, [])
        self.assertTrue(any(isinstance(event, ErrorEvent) for event in events))
        self.assertFalse(any(isinstance(event, DoneEvent) for event in events))


if __name__ == "__main__":
    unittest.main()
