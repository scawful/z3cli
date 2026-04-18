"""Tests for Phase 0 tool-invocation telemetry in ChatEngine."""

import asyncio
import json
import unittest
from pathlib import Path
from typing import AsyncGenerator

from z3cli.core.engine import ChatEngine, DoneEvent, ToolResultEvent
from z3cli.core.provider import (
    CompletionChunk,
    CompletionRequest,
    ContentDelta,
    ToolCallDelta,
    UsageInfo,
)
from z3cli.core.session import Session, load_tool_invocations


class StubProvider:
    """Yields one tool-call round then a final text reply."""

    def __init__(self, tool_name: str = "echo", tool_args: str = "{}"):
        self._tool_name = tool_name
        self._tool_args = tool_args
        self._round = 0

    @property
    def name(self) -> str:
        return "local"

    async def stream(
        self, request: CompletionRequest
    ) -> AsyncGenerator[CompletionChunk, None]:
        del request
        self._round += 1
        if self._round == 1:
            yield CompletionChunk(
                tool_calls=[
                    ToolCallDelta(
                        id="call_1",
                        name=self._tool_name,
                        arguments=self._tool_args,
                    )
                ],
                stop_reason="tool_calls",
            )
            yield CompletionChunk(usage=UsageInfo(prompt_tokens=1, completion_tokens=1))
        else:
            yield CompletionChunk(content=ContentDelta(text="done"))
            yield CompletionChunk(usage=UsageInfo(prompt_tokens=1, completion_tokens=1))

    async def check_connection(self) -> bool:
        return True

    async def close(self) -> None:
        pass


class StubBridge:
    """Minimal bridge returning a canned string (or raising)."""

    def __init__(self, response: str = "ok", raise_exc: Exception | None = None):
        self._response = response
        self._raise = raise_exc

    def get_openai_tools(self) -> list[dict]:
        return []

    async def call_tool(self, name: str, arguments: dict) -> str:
        if self._raise is not None:
            raise self._raise
        return self._response

    def get_tool_server(self, tool_name: str) -> str:
        return "stub"

    @property
    def tool_count(self) -> int:
        return 0

    @property
    def server_names(self) -> list[str]:
        return ["stub"]

    @property
    def server_tool_counts(self) -> dict[str, int]:
        return {"stub": 0}

    async def close(self) -> None:
        pass


class SlowBridge(StubBridge):
    async def call_tool(self, name: str, arguments: dict) -> str:
        await asyncio.sleep(10.0)
        return "never"


async def _collect(engine: ChatEngine, prompt: str) -> list:
    events = []
    async for ev in engine.chat(prompt, model_id="m"):
        events.append(ev)
    return events


class ToolInvocationHookTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_emits_one_invocation(self) -> None:
        payloads: list[dict] = []

        async def hook(payload: dict) -> None:
            payloads.append(payload)

        engine = ChatEngine(
            provider=StubProvider(),
            bridge=StubBridge(response="hello"),
            tool_invocation_hook=hook,
        )
        events = await _collect(engine, "go")
        self.assertTrue(any(isinstance(e, ToolResultEvent) for e in events))
        self.assertTrue(any(isinstance(e, DoneEvent) for e in events))
        self.assertEqual(len(payloads), 1)
        self.assertEqual(payloads[0]["tool"], "echo")
        self.assertEqual(payloads[0]["status"], "success")
        self.assertEqual(payloads[0]["server"], "stub")
        self.assertGreaterEqual(payloads[0]["duration_ms"], 0.0)
        self.assertEqual(payloads[0]["error"], "")

    async def test_error_emits_invocation_with_error_status(self) -> None:
        payloads: list[dict] = []

        async def hook(payload: dict) -> None:
            payloads.append(payload)

        engine = ChatEngine(
            provider=StubProvider(),
            bridge=StubBridge(raise_exc=RuntimeError("boom")),
            tool_invocation_hook=hook,
        )
        await _collect(engine, "go")
        self.assertEqual(len(payloads), 1)
        self.assertEqual(payloads[0]["status"], "error")
        self.assertIn("boom", payloads[0]["error"])

    async def test_timeout_emits_invocation_with_timeout_status(self) -> None:
        payloads: list[dict] = []

        async def hook(payload: dict) -> None:
            payloads.append(payload)

        engine = ChatEngine(
            provider=StubProvider(),
            bridge=SlowBridge(),
            tool_invocation_hook=hook,
            tool_timeout_s=0.2,
        )
        await _collect(engine, "go")
        self.assertEqual(len(payloads), 1)
        self.assertEqual(payloads[0]["status"], "timeout")
        self.assertGreaterEqual(payloads[0]["duration_ms"], 100.0)

    async def test_hook_exception_is_swallowed(self) -> None:
        async def hook(payload: dict) -> None:
            raise RuntimeError("hook failure")

        engine = ChatEngine(
            provider=StubProvider(),
            bridge=StubBridge(response="hello"),
            tool_invocation_hook=hook,
        )
        events = await _collect(engine, "go")
        # Chat loop must still reach DoneEvent despite hook crash.
        self.assertTrue(any(isinstance(e, DoneEvent) for e in events))


class CancellationLatencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_external_cancel_wakes_immediately(self) -> None:
        """External cancel via engine.cancel() must wake the tool loop promptly."""
        payloads: list[dict] = []

        async def hook(payload: dict) -> None:
            payloads.append(payload)

        engine = ChatEngine(
            provider=StubProvider(),
            bridge=SlowBridge(),  # sleeps 10s
            tool_invocation_hook=hook,
            tool_timeout_s=0,  # no timeout; rely on cancel
        )

        async def cancel_after(delay: float) -> None:
            await asyncio.sleep(delay)
            engine.cancel()

        loop = asyncio.get_running_loop()
        start = loop.time()
        cancel_task = asyncio.create_task(cancel_after(0.05))
        events = []
        async for ev in engine.chat("go", model_id="m"):
            events.append(ev)
        elapsed = loop.time() - start
        await cancel_task

        # Should wake within a reasonable window of the cancel signal, not
        # wait for the 10s sleep. Allow generous slack for CI noise.
        self.assertLess(elapsed, 1.0, f"cancel took too long: {elapsed}s")
        # Invocation should still be recorded as cancelled.
        self.assertEqual(len(payloads), 1)
        self.assertEqual(payloads[0]["status"], "cancelled")


class SessionPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_session_writes_and_reads_invocations(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            session = Session(session_dir=tmp_path)
            session.start(
                active_model="m",
                backend="studio",
                mode="manual",
                workspace=".",
                rom_path="",
                tools_enabled=False,
                broadcast_models=[],
            )
            session.append_tool_invocation(
                tool="echo",
                server="stub",
                duration_ms=12.3,
                status="success",
                model="m",
                call_id="call_1",
            )
            session.append_tool_invocation(
                tool="crash",
                server="stub",
                duration_ms=99.0,
                status="error",
                model="m",
                call_id="call_2",
                error="boom",
            )
            session.close()

            records = load_tool_invocations(session.path)  # type: ignore[arg-type]
            self.assertEqual(len(records), 2)
            self.assertEqual(records[0]["tool"], "echo")
            self.assertEqual(records[0]["status"], "success")
            self.assertEqual(records[0]["duration_ms"], 12.3)
            self.assertEqual(records[1]["status"], "error")
            self.assertEqual(records[1]["error"], "boom")


if __name__ == "__main__":
    unittest.main()
