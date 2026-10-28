import asyncio
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from typing import AsyncGenerator
from unittest.mock import patch

import httpx
from rich.console import Console

from app.ipc_schema import done_params
from app.repl import AppState, _tool_permission_hook
from app.serve import ServeState
from app.shared_runtime import restore_runtime_state, session_metrics_patch
from core.config import ModelConfig, RouterConfig
from core.engine import (
    ChatEngine,
    DoneEvent,
    ErrorEvent,
    TextEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from core.provider import CompletionChunk, CompletionRequest, ContentDelta, ToolCallDelta


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_z3cli_oracle_promotion_eval.py"
SPEC = importlib.util.spec_from_file_location("run_z3cli_oracle_promotion_eval", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
promotion_eval = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = promotion_eval
SPEC.loader.exec_module(promotion_eval)


class ScriptedProvider:
    """Replays one chunk list per round; repeats the last when exhausted."""

    def __init__(self, scripts: list[list[CompletionChunk]]):
        self._scripts = scripts
        self.calls = 0

    @property
    def name(self) -> str:
        return "local"

    async def stream(self, request: CompletionRequest) -> AsyncGenerator[CompletionChunk, None]:
        del request
        script = self._scripts[min(self.calls, len(self._scripts) - 1)]
        self.calls += 1
        for chunk in script:
            yield chunk

    async def check_connection(self) -> bool:
        return True

    async def close(self) -> None:
        pass


class DroppingProvider(ScriptedProvider):
    async def stream(self, request: CompletionRequest) -> AsyncGenerator[CompletionChunk, None]:
        del request
        self.calls += 1
        yield CompletionChunk(content=ContentDelta(text="partial"))
        raise httpx.ReadError("connection reset")


class RecordingBridge:
    def __init__(self, write_tools: set[str] | None = None) -> None:
        self.calls: list[str] = []
        self._write_tools = write_tools or set()

    def get_openai_tools(self) -> list[dict]:
        return [{
            "type": "function",
            "function": {"name": "echo", "description": "", "parameters": {"type": "object", "properties": {}}},
        }]

    async def call_tool(self, name: str, arguments: dict) -> str:
        del arguments
        self.calls.append(name)
        return "tool-output"

    def get_tool_server(self, tool_name: str) -> str:
        del tool_name
        return "mock"

    def is_write_tool(self, tool_name: str) -> bool | None:
        return tool_name in self._write_tools

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


def _tool_round(name: str = "echo", arguments: str = "{}") -> list[CompletionChunk]:
    return [CompletionChunk(tool_calls=[ToolCallDelta(id="tc-1", name=name, arguments=arguments)])]


def _text_round(text: str, finish_reason: str = "stop") -> list[CompletionChunk]:
    return [CompletionChunk(content=ContentDelta(text=text), stop_reason=finish_reason)]


async def _run(engine: ChatEngine, **kwargs) -> list:
    return [event async for event in engine.chat("go", "model", **kwargs)]


def _done(events: list) -> DoneEvent:
    done = [event for event in events if isinstance(event, DoneEvent)]
    assert len(done) == 1, events
    return done[0]


class EngineStopReasonTests(unittest.IsolatedAsyncioTestCase):
    async def test_clean_answer_is_complete(self) -> None:
        engine = ChatEngine(provider=ScriptedProvider([_text_round("answer")]))

        done = _done(await _run(engine))

        self.assertEqual(done.stop_reason, "complete")
        self.assertTrue(done.ok)
        self.assertEqual(done.denied_tool_calls, 0)

    async def test_denied_tool_call_marks_done_event(self) -> None:
        async def deny(*_args) -> bool:
            return False

        bridge = RecordingBridge()
        engine = ChatEngine(
            provider=ScriptedProvider([_tool_round(), _text_round("could not run it")]),
            bridge=bridge,
            permission_hook=deny,
        )

        done = _done(await _run(engine))

        self.assertEqual(bridge.calls, [])
        self.assertEqual(done.stop_reason, "denied")
        self.assertFalse(done.ok)
        self.assertEqual(done.denied_tool_calls, 1)

    async def test_repeated_denied_call_ends_turn_without_reprompting(self) -> None:
        prompts: list[str] = []

        async def deny(name, *_args) -> bool:
            prompts.append(name)
            return False

        provider = ScriptedProvider([_tool_round()])
        engine = ChatEngine(provider=provider, bridge=RecordingBridge(), permission_hook=deny)

        events = await _run(engine, max_rounds=8)
        done = _done(events)

        self.assertEqual(prompts, ["echo"])
        self.assertEqual(provider.calls, 2)
        self.assertEqual(done.stop_reason, "denied")
        self.assertEqual(done.denied_tool_calls, 2)
        self.assertFalse(any(isinstance(event, ErrorEvent) for event in events))
        self.assertEqual(engine.messages[-1]["role"], "tool")

    async def test_different_arguments_after_denial_still_prompt(self) -> None:
        prompts: list[str] = []

        async def deny(name, arguments, *_args) -> bool:
            prompts.append(arguments)
            return False

        provider = ScriptedProvider([
            _tool_round(arguments='{"a": 1}'),
            _tool_round(arguments='{"a": 2}'),
            _text_round("done"),
        ])
        engine = ChatEngine(provider=provider, bridge=RecordingBridge(), permission_hook=deny)

        done = _done(await _run(engine))

        self.assertEqual(prompts, ['{"a": 1}', '{"a": 2}'])
        self.assertEqual(done.stop_reason, "denied")

    async def test_length_finish_reason_is_not_success(self) -> None:
        engine = ChatEngine(provider=ScriptedProvider([_text_round("truncated ans", "length")]))

        done = _done(await _run(engine))

        self.assertEqual(done.stop_reason, "length")
        self.assertFalse(done.ok)

    async def test_anthropic_max_tokens_is_length(self) -> None:
        engine = ChatEngine(provider=ScriptedProvider([_text_round("truncated", "max_tokens")]))

        self.assertEqual(_done(await _run(engine)).stop_reason, "length")

    async def test_empty_answer_is_not_success(self) -> None:
        engine = ChatEngine(provider=ScriptedProvider([[CompletionChunk(stop_reason="stop")]]))

        done = _done(await _run(engine))

        self.assertEqual(done.stop_reason, "empty")
        self.assertFalse(done.ok)

    async def test_think_only_answer_is_empty(self) -> None:
        engine = ChatEngine(provider=ScriptedProvider([_text_round("<think>hmm</think>")]))

        self.assertEqual(_done(await _run(engine, thinking=True)).stop_reason, "empty")

    async def test_mid_stream_disconnect_is_error_not_cancel(self) -> None:
        engine = ChatEngine(provider=DroppingProvider([[]]))

        events = await _run(engine)

        errors = [event for event in events if isinstance(event, ErrorEvent)]
        self.assertEqual(len(errors), 1)
        self.assertIn("disconnected", errors[0].message)
        self.assertFalse(any(isinstance(event, DoneEvent) for event in events))
        self.assertEqual(engine.provider_error_count, 1)

    async def test_cancel_still_reports_cancelled(self) -> None:
        engine_ref: list[ChatEngine] = []

        class CancelMidStream(ScriptedProvider):
            async def stream(self, request: CompletionRequest) -> AsyncGenerator[CompletionChunk, None]:
                del request
                yield CompletionChunk(content=ContentDelta(text="partial"))
                engine_ref[0].cancel()
                yield CompletionChunk(content=ContentDelta(text="more"))

        engine = ChatEngine(provider=CancelMidStream([[]]))
        engine_ref.append(engine)

        self.assertEqual(_done(await _run(engine)).stop_reason, "cancelled")

    async def test_max_rounds_reports_stop_reason(self) -> None:
        async def allow(*_args) -> bool:
            return True

        engine = ChatEngine(
            provider=ScriptedProvider([_tool_round()]),
            bridge=RecordingBridge(),
            permission_hook=allow,
        )

        done = _done(await _run(engine, max_rounds=1))

        self.assertEqual(done.stop_reason, "max_rounds")


class ThinkBlockToolParsingTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_call_inside_think_block_is_not_executed(self) -> None:
        bridge = RecordingBridge()
        content = (
            '<think>maybe <tool_call>{"name": "echo", "arguments": {}}</tool_call> no</think>'
            "Plain answer."
        )
        engine = ChatEngine(provider=ScriptedProvider([_text_round(content)]), bridge=bridge)

        events = await _run(engine, use_tools=False, allow_manual_tool_calls=True)

        self.assertEqual(bridge.calls, [])
        self.assertFalse(any(isinstance(event, ToolCallEvent) for event in events))
        self.assertEqual(_done(events).stop_reason, "complete")

    async def test_tool_call_in_unclosed_think_block_is_not_executed(self) -> None:
        bridge = RecordingBridge()
        content = '<think>try <tool_call>{"name": "echo", "arguments": {}}</tool_call>'
        engine = ChatEngine(provider=ScriptedProvider([_text_round(content)]), bridge=bridge)

        await _run(engine, use_tools=False, allow_manual_tool_calls=True)

        self.assertEqual(bridge.calls, [])

    async def test_tool_call_after_think_block_still_executes(self) -> None:
        bridge = RecordingBridge()
        content = '<think>plan</think><tool_call>{"name": "echo", "arguments": {}}</tool_call>'
        engine = ChatEngine(
            provider=ScriptedProvider([_text_round(content), _text_round("after")]),
            bridge=bridge,
        )

        events = await _run(engine, use_tools=False, allow_manual_tool_calls=True)

        self.assertEqual(bridge.calls, ["echo"])
        self.assertTrue(any(isinstance(event, ToolResultEvent) for event in events))
        self.assertTrue(any(isinstance(event, TextEvent) and event.text == "after" for event in events))


def _repl_state(workspace: Path) -> AppState:
    return AppState(
        console=Console(record=True, width=120),
        host="127.0.0.1",
        port=1234,
        api_base="http://localhost:1234/v1",
        backend_name="studio",
        studio_api_base="http://localhost:1234/v1",
        llamacpp_api_base="http://localhost:8080/v1",
        llamacpp_model="oracle-fast",
        registry_path=Path("/tmp/registry.toml"),
        mcp_path=Path("/tmp/mcp.json"),
        models={"farore": ModelConfig(name="farore", model_id="farore")},
        routers={"oracle": RouterConfig(name="oracle", router_type="keyword", default="farore")},
        active_model="farore",
        mode="manual",
        auto_load=False,
        auto_start_server=False,
        workspace=workspace,
        rom_path=None,
        temperature=0.2,
        max_tokens=1024,
        broadcast_models=[],
        tools_enabled=True,
    )


WRITE_ARGS = '{"path":"src/main.asm","content":"lda #$02\\n"}'


class ReplApprovalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name)
        (self.workspace / "src").mkdir()
        (self.workspace / "src" / "main.asm").write_text("lda #$01\n", encoding="utf-8")
        self.state = _repl_state(self.workspace)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    async def test_read_tool_is_allowed_without_prompt(self) -> None:
        with patch("app.repl._prompt_tool_approval") as prompt:
            allowed = await _tool_permission_hook(self.state, "read_file", '{"path":"src/main.asm"}', "afs", "c1")

        self.assertTrue(allowed)
        prompt.assert_not_called()

    async def test_write_tool_denied_when_not_interactive(self) -> None:
        with patch("app.repl._prompt_tool_approval") as prompt:
            allowed = await _tool_permission_hook(self.state, "write_file", WRITE_ARGS, "afs", "c1")

        self.assertFalse(allowed)
        prompt.assert_not_called()
        self.assertNotIn("c1", self.state.pending_write_contexts)
        self.assertIn("denied afs:write_file", self.state.console.export_text().lower())

    async def test_interactive_yes_approves_once(self) -> None:
        self.state.interactive_approvals = True
        with patch("app.repl._prompt_tool_approval", return_value="y") as prompt:
            first = await _tool_permission_hook(self.state, "write_file", WRITE_ARGS, "afs", "c1")
            second = await _tool_permission_hook(self.state, "write_file", WRITE_ARGS, "afs", "c2")

        self.assertTrue(first and second)
        self.assertEqual(prompt.call_count, 2)
        self.assertEqual(self.state.permission_rules, {})
        self.assertIn("c1", self.state.pending_write_contexts)

    async def test_interactive_no_denies_and_drops_write_context(self) -> None:
        self.state.interactive_approvals = True
        with patch("app.repl._prompt_tool_approval", return_value="n"):
            allowed = await _tool_permission_hook(self.state, "write_file", WRITE_ARGS, "afs", "c1")

        self.assertFalse(allowed)
        self.assertNotIn("c1", self.state.pending_write_contexts)

    async def test_interactive_always_caches_for_session(self) -> None:
        self.state.interactive_approvals = True
        with patch("app.repl._prompt_tool_approval", return_value="a") as prompt:
            first = await _tool_permission_hook(self.state, "write_file", WRITE_ARGS, "afs", "c1")
            second = await _tool_permission_hook(self.state, "write_file", WRITE_ARGS, "afs", "c2")

        self.assertTrue(first and second)
        self.assertEqual(prompt.call_count, 1)
        self.assertEqual(self.state.permission_rules, {"afs:write_file": True})

    async def test_bridge_declared_write_tool_requires_approval(self) -> None:
        self.state.bridge = RecordingBridge(write_tools={"echo"})

        allowed = await _tool_permission_hook(self.state, "echo", "{}", "mock", "c1")

        self.assertFalse(allowed)

    async def test_bridge_declared_read_tool_overrides_name_pattern(self) -> None:
        self.state.bridge = RecordingBridge(write_tools=set())

        allowed = await _tool_permission_hook(self.state, "save_state_info", "{}", "mock", "c1")

        self.assertTrue(allowed)


class SessionApprovalScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_serve_session_approval_is_not_persisted(self) -> None:
        state = ServeState()
        state.workspace = Path.cwd()
        persisted: list[dict] = []

        with patch("app.serve._notify"), patch(
            "app.serve._persist_state",
            side_effect=lambda _state, changes=None, **_kw: persisted.append(dict(changes or {})),
        ):
            pending = asyncio.create_task(state._tool_permission_hook("echo", "{}", "mock", "call-1"))
            for _ in range(50):
                if state.tool_decision is not None:
                    break
                await asyncio.sleep(0)
            assert state.tool_decision is not None
            state.tool_approved = True
            state.tool_decision_scope = "session"
            state.tool_decision.set()
            allowed = await asyncio.wait_for(pending, timeout=1)

        self.assertTrue(allowed)
        self.assertEqual(state.permission_rules, {"mock:echo": True})
        self.assertFalse(any("permission_rules" in changes for changes in persisted))
        self.assertNotIn("permission_rules", session_metrics_patch(state))

    def test_resume_does_not_restore_persisted_approvals(self) -> None:
        state = ServeState()
        state.permission_rules = {"mock:echo": True}

        restore_runtime_state(state, {"permission_rules": {"afs:write_file": True}})

        self.assertEqual(state.permission_rules, {})


class StopReasonPropagationTests(unittest.TestCase):
    def test_done_params_includes_stop_reason_only_when_set(self) -> None:
        clean = done_params(prompt_tokens=1, completion_tokens=1, total_tokens=2, end_status="success")
        denied = done_params(
            prompt_tokens=1, completion_tokens=1, total_tokens=2, end_status="success", stop_reason="denied",
        )

        self.assertNotIn("stop_reason", clean)
        self.assertEqual(denied["stop_reason"], "denied")

    def test_promotion_eval_fails_request_with_non_clean_stop(self) -> None:
        row = {"id": "r1", "prompt": "hi", "expect": {}}
        observed = promotion_eval.ObservedResponse(
            id="r1", prompt="hi", final_text="partial", end_status="success", stop_reason="length",
        )

        scored = promotion_eval.score_response(row, observed)

        check = next(check for check in scored["checks"] if check["name"] == "request_succeeded")
        self.assertFalse(check["passed"])
        self.assertFalse(scored["passed"])
        self.assertEqual(scored["stop_reason"], "length")


if __name__ == "__main__":
    unittest.main()
