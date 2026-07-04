import asyncio
import unittest
from typing import AsyncGenerator, Any, cast

import httpx

from core.engine import (
    ChatEngine,
    DoneEvent,
    ErrorEvent,
    TextEvent,
    ThinkingEvent,
    ToolResultEvent,
    ToolCallEvent,
    _extract_xml_tool_calls,
    _grounded_fallback_answer_from_history,
    _repair_grounding_tool_call_arguments,
    summarize_tool_result_for_history,
)
from app.runtime import (
    build_local_identity_prompt,
    build_oracle_answer_after_grounding_prompt,
    build_oracle_natural_chat_prompt,
    build_tool_bias_prompt,
    build_tool_use_prompt,
)
from core.config import ModelConfig
from core.provider import CompletionChunk, CompletionRequest, ContentDelta, ProviderError, ToolCallDelta, UsageInfo


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

    def test_oracle_tool_prompt_preserves_exact_symbol_arguments(self) -> None:
        prompt = build_tool_use_prompt(True, "oracle")
        self.assertIn("MDMAEN", prompt)
        self.assertIn("exact symbol", prompt)
        self.assertIn("requested byte/instruction count", prompt)

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

    def test_oracle_xml_tool_prompt_does_not_offer_missing_tool_search(self) -> None:
        prompt = build_tool_use_prompt(
            True,
            "oracle",
            deferred_tools=False,
            native_tools=False,
        )

        self.assertIn("compact Oracle tool catalog", prompt)
        self.assertIn("workspace_read", prompt)
        self.assertIn("Use only exact tool names", prompt)
        self.assertIn("Do not call unlisted aliases", prompt)
        self.assertNotIn("start with `tool_search`", prompt)

    def test_tool_bias_prompt_mentions_xml_tool_block_when_native_tools_disabled(self) -> None:
        prompt = build_tool_bias_prompt(
            "inspect this file",
            True,
            "",
            deferred_tools=True,
            native_tools=False,
        )
        self.assertIn("<tool_call>", prompt)

    def test_oracle_tool_bias_prompt_for_exact_compact_tool_request(self) -> None:
        prompt = build_tool_bias_prompt(
            "Use grep_disasm for Sprite_CheckIfActive before answering.",
            True,
            "oracle",
            deferred_tools=False,
            native_tools=False,
        )

        self.assertIn("explicitly named `grep_disasm`", prompt)
        self.assertIn("Do not substitute a similar tool", prompt)
        self.assertIn(
            '<tool_call>{"name":"grep_disasm","arguments":{"query":"Sprite_CheckIfActive"}}</tool_call>',
            prompt,
        )

    def test_oracle_tool_bias_prompt_triggers_on_exact_tool_without_other_keywords(self) -> None:
        prompt = build_tool_bias_prompt(
            "label_lookup $00FFD5",
            True,
            "oracle",
            deferred_tools=False,
            native_tools=False,
        )

        self.assertIn("explicitly named `label_lookup`", prompt)
        self.assertIn('<tool_call>{"name":"label_lookup","arguments":{"query":"$00FFD5"}}</tool_call>', prompt)

    def test_repair_grounding_tool_call_arguments_recovers_empty_args_from_prompt(self) -> None:
        self.assertEqual(
            _repair_grounding_tool_call_arguments(
                "label_lookup",
                "{}",
                "Call label_lookup for Underworld_LoadSongBankIfNeeded before answering.",
            ),
            '{"query":"Underworld_LoadSongBankIfNeeded"}',
        )
        self.assertEqual(
            _repair_grounding_tool_call_arguments(
                "rom_read",
                "{}",
                "Use rom_read to read 8 bytes at $7E0800 before discussing state.",
            ),
            '{"address":"$7E0800","length":8}',
        )
        self.assertEqual(
            _repair_grounding_tool_call_arguments(
                "disasm_at",
                "{}",
                "Use disasm_at at $02A3B0 for 12 instructions before commenting.",
            ),
            '{"address":"$02A3B0","count":12}',
        )

    def test_repair_grounding_tool_call_arguments_recovers_missing_address_from_partial_args(self) -> None:
        self.assertEqual(
            _repair_grounding_tool_call_arguments(
                "rom_read",
                '{"value":"6","length":6}',
                "Read 6 bytes at $02A3B0 with rom_read, then say whether the hook site bytes are available.",
            ),
            '{"value":"6","length":6,"address":"$02A3B0"}',
        )
        self.assertEqual(
            _repair_grounding_tool_call_arguments(
                "disasm_at",
                '{"value":"12","count":12}',
                "Use disasm_at at $02A3B0 for 12 instructions before commenting.",
            ),
            '{"value":"12","count":12,"address":"$02A3B0"}',
        )

    def test_grounded_fallback_answer_extracts_model_id_from_registry_result(self) -> None:
        answer = _grounded_fallback_answer_from_history(
            "Open config/chat_registry.toml with workspace_read and tell me which configured model id belongs to oracle-qwen35-9b.",
            [
                {
                    "role": "tool",
                    "content": "\n".join([
                        '119 | name = "oracle-qwen35-9b"',
                        '120 | provider = "studio"',
                        '121 | model_id = "gguf/zelda/oracle-qwen35-9b-v1-q4km.gguf"',
                        '122 | tool_profile = "oracle"',
                    ]),
                },
            ],
        )

        self.assertEqual(
            answer,
            "The configured model id for `oracle-qwen35-9b` is `gguf/zelda/oracle-qwen35-9b-v1-q4km.gguf`.",
        )

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


class StubbornToolCallerProvider:
    """Emits a tool call, then a tool-call-only answer round, then prose."""

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
        if self.calls == 2:
            # Tools are disabled in the answer round, but the model still
            # emits a manual XML tool call instead of answering.
            yield CompletionChunk(content=ContentDelta(text='<tool_call>{"name":"label_lookup","arguments":{"query":"Minecart"}}</tool_call>'))
            return
        yield CompletionChunk(content=ContentDelta(text="prose answer after retry"))
        yield CompletionChunk(usage=UsageInfo(prompt_tokens=2, completion_tokens=1))

    async def check_connection(self) -> bool:
        return True

    async def close(self) -> None:
        pass


class EmptyArgsGroundingProvider:
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
            yield CompletionChunk(tool_calls=[ToolCallDelta(id="tc-1", name="label_lookup", arguments="{}")])
            return
        yield CompletionChunk(content=ContentDelta(text="after repair"))

    async def check_connection(self) -> bool:
        return True

    async def close(self) -> None:
        pass


class ManualXmlToolProvider:
    def __init__(self) -> None:
        self.calls = 0

    @property
    def name(self) -> str:
        return "local"

    async def stream(
        self,
        request: CompletionRequest,
    ) -> AsyncGenerator[CompletionChunk, None]:
        self.calls += 1
        if self.calls == 1:
            self.first_request = request
            yield CompletionChunk(content=ContentDelta(text='<tool_call>{"name":"echo","arguments":{"text":"hi"}}</tool_call>'))
            return
        yield CompletionChunk(content=ContentDelta(text="after xml tool"))

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

    async def test_disable_reasoning_prefill_drops_stray_reasoning_from_text(self) -> None:
        provider = MockProvider([[
            CompletionChunk(content=ContentDelta(reasoning="hidden chain", text="Use DMA init.")),
            CompletionChunk(usage=UsageInfo(prompt_tokens=7, completion_tokens=3)),
        ]])
        engine = ChatEngine(provider=provider)

        events = [
            event
            async for event in engine.chat(
                "why?",
                "qwen3",
                disable_reasoning_prefill=True,
            )
        ]

        text = "".join(event.text for event in events if isinstance(event, TextEvent))
        thinking = "".join(event.text for event in events if isinstance(event, ThinkingEvent))

        self.assertEqual(text, "Use DMA init.")
        self.assertEqual(thinking, "")
        self.assertEqual(engine.messages[-1]["content"], "Use DMA init.")

    def test_extract_xml_tool_calls_parses_qwen3_tool_call_blocks(self) -> None:
        calls = _extract_xml_tool_calls(
            '<tool_call>{"name":"echo","arguments":{"text":"hi"}}</tool_call>'
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "echo")
        self.assertEqual(calls[0]["arguments"], '{"text": "hi"}')

    def test_extract_xml_tool_calls_repairs_unquoted_argument_keys(self) -> None:
        calls = _extract_xml_tool_calls(
            '<tool_call>{"name":"workspace_read","arguments":{ path: "config/chat_registry.toml" }}</tool_call>'
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "workspace_read")
        self.assertEqual(calls[0]["arguments"], '{"path": "config/chat_registry.toml"}')

    def test_extract_xml_tool_calls_repairs_args_equals_syntax(self) -> None:
        calls = _extract_xml_tool_calls(
            '<tool_call>{"name":"rom_read" args={"address":"$7E0800","bytes":8}}</tool_call>'
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "rom_read")
        self.assertEqual(calls[0]["arguments"], '{"address": "$7E0800", "bytes": 8}')

    def test_extract_xml_tool_calls_repairs_missing_comma_and_final_brace(self) -> None:
        calls = _extract_xml_tool_calls(
            '<tool_call>{"name":"rom_read" arguments={"address":"$7E0800","bytes":8}</tool_call>'
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "rom_read")
        self.assertEqual(calls[0]["arguments"], '{"address": "$7E0800", "bytes": 8}')

    def test_extract_xml_tool_calls_repairs_bare_equals_argument_pairs(self) -> None:
        calls = _extract_xml_tool_calls(
            '<tool_call>{"name":"label_lookup" arguments={ query="Underworld_LoadSongBankIfNeeded", }</tool_call>'
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "label_lookup")
        self.assertEqual(calls[0]["arguments"], '{"query": "Underworld_LoadSongBankIfNeeded"}')

    def test_extract_xml_tool_calls_accepts_tool_and_args_fields(self) -> None:
        calls = _extract_xml_tool_calls(
            '<tool_call>{"tool":"grep_disasm","args":{"query":"Sprite_CheckIfActive"}}</tool_call>'
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "grep_disasm")
        self.assertEqual(calls[0]["arguments"], '{"query": "Sprite_CheckIfActive"}')

    def test_extract_xml_tool_calls_parses_bare_grounding_call_prefix(self) -> None:
        calls = _extract_xml_tool_calls(
            "label_lookup(Underworld_LoadSongBankIfNeeded) reported no definition"
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "label_lookup")
        self.assertEqual(calls[0]["arguments"], '{"query": "Underworld_LoadSongBankIfNeeded"}')

    def test_extract_xml_tool_calls_keeps_disasm_instruction_count_alias(self) -> None:
        calls = _extract_xml_tool_calls(
            '<tool_call>{"name":"disasm_at" arguments={ address:"$0088EC", instruction_count:10 }</tool_call>'
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "disasm_at")
        self.assertEqual(calls[0]["arguments"], '{"address": "$0088EC", "instruction_count": 10}')

    def test_extract_xml_tool_calls_repairs_escaped_structural_argument_quotes(self) -> None:
        calls = _extract_xml_tool_calls(
            '<tool_call>{"name":"rom_read","arguments":{"address\\":\\"$7E0800\\",\\"size\\":8}}</tool_call>'
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "rom_read")
        self.assertEqual(calls[0]["arguments"], '{"address": "$7E0800", "size": 8}')

    def test_extract_xml_tool_calls_salvages_name_from_malformed_arguments(self) -> None:
        calls = _extract_xml_tool_calls(
            '<tool_call>{"name":"cpu_state","arguments":{"reason\\":\\"freeze\\"}}</tool_call>'
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "cpu_state")
        self.assertEqual(calls[0]["arguments"], '{"reason": "freeze"}')

    def test_extract_xml_tool_calls_accepts_inline_argument_keys(self) -> None:
        calls = _extract_xml_tool_calls(
            '<tool_call>{"name":"tool_name":"disasm_at", address="$008164", lines=3 }</tool_call>'
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "disasm_at")
        self.assertEqual(calls[0]["arguments"], '{"address": "$008164", "lines": 3}')

    def test_extract_xml_tool_calls_parses_function_style_label_lookup(self) -> None:
        calls = _extract_xml_tool_calls(
            "<tool_call><function=label_lookup><query>Underworld_LoadSongBankIfNeeded</query></function></tool_call>"
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "label_lookup")
        self.assertEqual(calls[0]["arguments"], '{"query": "Underworld_LoadSongBankIfNeeded"}')

    def test_extract_xml_tool_calls_parses_function_style_address_attrs(self) -> None:
        calls = _extract_xml_tool_calls(
            '<tool_call><function=rom_read><address="$02A3B0" length="6"></address></function></tool_call>'
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "rom_read")
        self.assertEqual(calls[0]["arguments"], '{"address": "$02A3B0", "length": "6"}')

    def test_extract_xml_tool_calls_parses_unclosed_function_style_disasm(self) -> None:
        calls = _extract_xml_tool_calls(
            "<tool_call><function=disasm_at><address>$02A3B0><instructions>12</instructions></address></tool_call>"
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "disasm_at")
        self.assertEqual(calls[0]["arguments"], '{"address": "$02A3B0", "count": "12"}')

    def test_extract_xml_tool_calls_salvages_unclosed_json_tool_call(self) -> None:
        calls = _extract_xml_tool_calls('<tool_call>{"name": "cpu_state"}{}</result>')

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "cpu_state")
        self.assertEqual(calls[0]["arguments"], "{}")

    def test_extract_xml_tool_calls_parses_json_name_with_xml_parameters(self) -> None:
        calls = _extract_xml_tool_calls(
            '<tool_call>{"name":"grep_disasm"} <parameters><pattern="MDMAEN"></parameters></tool_call>'
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "grep_disasm")
        self.assertEqual(calls[0]["arguments"], '{"pattern": "MDMAEN"}')

    def test_extract_xml_tool_calls_parses_parameter_value_tag(self) -> None:
        calls = _extract_xml_tool_calls(
            '<tool_call><function=workspace_read><parameter=path>config/chat_registry.toml</function></tool_call>'
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "workspace_read")
        self.assertEqual(calls[0]["arguments"], '{"path": "config/chat_registry.toml"}')

    def test_extract_xml_tool_calls_parses_arg_value_json_object(self) -> None:
        calls = _extract_xml_tool_calls(
            '<tool_call>{"name":"workspace_read"}<arg_value>{"path":"config/chat_registry.toml"}</arg_value></tool_call>'
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "workspace_read")
        self.assertEqual(calls[0]["arguments"], '{"path": "config/chat_registry.toml"}')

    def test_extract_xml_tool_calls_parses_self_closing_arg_json_object(self) -> None:
        calls = _extract_xml_tool_calls(
            '<tool_call>{tool="label_lookup"}<arg>{"query":"Underworld_LoadSongBankIfNeeded"}/></tool_call>'
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "label_lookup")
        self.assertEqual(calls[0]["arguments"], '{"query": "Underworld_LoadSongBankIfNeeded"}')

    def test_extract_xml_tool_calls_unwraps_argos_json_object(self) -> None:
        calls = _extract_xml_tool_calls(
            '<tool_call><function=grep_disasm><argos>{"pattern":"MDMAEN","limit":3}</argos></function></tool_call>'
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "grep_disasm")
        self.assertEqual(calls[0]["arguments"], '{"pattern": "MDMAEN", "limit": 3}')

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

    async def test_answer_round_tool_call_only_output_retries_once_with_prose_instruction(self) -> None:
        provider = StubbornToolCallerProvider()
        engine = ChatEngine(
            provider=provider,
            bridge=GroundingBridge(),
        )

        events = [
            event async for event in engine.chat(
                "Let's take a look at the Minecart sprite.",
                "oracle-9b-router",
                use_tools=True,
                answer_after_first_grounding=True,
                answer_after_grounding_system="Answer from the grounded evidence now.",
            )
        ]

        self.assertEqual(provider.calls, 3)
        self.assertIsNone(provider.requests[1].tools)
        self.assertIsNone(provider.requests[2].tools)
        self.assertIn("Tool calls are closed for this turn.", provider.requests[2].system)
        self.assertIn("Answer from the grounded evidence now.", provider.requests[2].system)
        self.assertTrue(any(isinstance(event, TextEvent) and event.text == "prose answer after retry" for event in events))
        self.assertTrue(any(isinstance(event, DoneEvent) for event in events))
        self.assertEqual(engine.messages[-1], {"role": "assistant", "content": "prose answer after retry"})

    async def test_empty_grounding_tool_arguments_are_repaired_before_execution(self) -> None:
        provider = EmptyArgsGroundingProvider()
        engine = ChatEngine(provider=provider, bridge=GroundingBridge())

        events = [
            event async for event in engine.chat(
                "Call label_lookup for Underworld_LoadSongBankIfNeeded before answering.",
                "oracle-9b-router",
                use_tools=True,
            )
        ]

        calls = [event for event in events if isinstance(event, ToolCallEvent)]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].arguments, '{"query":"Underworld_LoadSongBankIfNeeded"}')
        self.assertTrue(any(isinstance(event, TextEvent) and event.text == "after repair" for event in events))

    async def test_manual_xml_tool_calls_need_explicit_execution_gate(self) -> None:
        provider = ManualXmlToolProvider()
        engine = ChatEngine(provider=provider, bridge=EchoBridge())

        events = [
            event async for event in engine.chat(
                "run a manual tool",
                "qwen3",
                use_tools=False,
                allow_manual_tool_calls=False,
            )
        ]

        self.assertEqual(provider.calls, 1)
        self.assertIsNone(provider.first_request.tools)
        self.assertFalse(any(isinstance(event, ToolResultEvent) for event in events))
        self.assertTrue(any(
            isinstance(event, TextEvent) and "<tool_call>" in event.text
            for event in events
        ))

    async def test_manual_xml_tool_calls_can_execute_without_native_schemas(self) -> None:
        provider = ManualXmlToolProvider()
        engine = ChatEngine(provider=provider, bridge=EchoBridge())

        events = [
            event async for event in engine.chat(
                "run a manual tool",
                "qwen3",
                use_tools=False,
                allow_manual_tool_calls=True,
            )
        ]

        self.assertEqual(provider.calls, 2)
        self.assertIsNone(provider.first_request.tools)
        self.assertTrue(any(
            isinstance(event, ToolResultEvent) and event.result == "tool-output"
            for event in events
        ))
        self.assertTrue(any(
            isinstance(event, TextEvent) and event.text == "after xml tool"
            for event in events
        ))

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
