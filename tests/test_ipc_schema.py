import unittest
from pathlib import Path

from app.ipc_schema import (
    done_params,
    generate_typescript_protocol,
    make_notification,
    make_response,
    message_params,
    subagent_start_params,
)


class IpcSchemaTests(unittest.TestCase):
    def test_make_notification_wraps_params(self) -> None:
        payload = make_notification("text", {"delta": "hello"})
        self.assertEqual(payload, {
            "jsonrpc": "2.0",
            "method": "text",
            "params": {"delta": "hello"},
        })

    def test_make_response_builds_error_envelope(self) -> None:
        payload = make_response(7, error="boom")
        self.assertEqual(payload, {
            "jsonrpc": "2.0",
            "id": 7,
            "error": {"code": -1, "message": "boom"},
        })

    def test_message_params_omits_empty_optional_fields(self) -> None:
        payload = message_params(
            message_id="msg-1",
            role="assistant",
            content="hello",
            timestamp=123,
        )
        self.assertEqual(payload, {
            "id": "msg-1",
            "role": "assistant",
            "content": "hello",
            "timestamp": 123,
        })

    def test_message_params_preserve_reasoning_when_present(self) -> None:
        payload = message_params(
            message_id="msg-2",
            role="assistant",
            content="done",
            thinking="inspect $028000",
            timestamp=456,
        )
        self.assertEqual(payload["thinking"], "inspect $028000")

    def test_message_params_include_construct_refs_when_present(self) -> None:
        payload = message_params(
            message_id="msg-3",
            role="user",
            content="inspect room",
            timestamp=789,
            construct_refs=[{
                "kind": "room",
                "query": "0x45",
                "token": "#room:0x45",
                "id": "0x45",
                "label": "Glacia Estate (Jail Cells)",
            }],
        )
        self.assertEqual(payload["construct_refs"][0]["token"], "#room:0x45")

    def test_done_params_include_cache_counters_when_present(self) -> None:
        payload = done_params(
            prompt_tokens=100,
            completion_tokens=25,
            total_tokens=125,
            cache_creation_tokens=64,
            cache_read_tokens=32,
        )
        self.assertEqual(payload, {
            "prompt_tokens": 100,
            "completion_tokens": 25,
            "total_tokens": 125,
            "cache_creation_tokens": 64,
            "cache_read_tokens": 32,
        })

    def test_subagent_start_params_preserve_tree_fields(self) -> None:
        payload = subagent_start_params(
            subagent_id="sub-2-helper",
            name="helper",
            model="helper",
            provider="anthropic",
            depth=2,
            parent_id="sub-1-worker",
        )
        self.assertEqual(payload, {
            "id": "sub-2-helper",
            "name": "helper",
            "model": "helper",
            "provider": "anthropic",
            "depth": 2,
            "parent_id": "sub-1-worker",
        })

    def test_generated_typescript_protocol_is_committed(self) -> None:
        expected = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "ipc" / "protocol.generated.ts").read_text(encoding="utf-8")
        self.assertEqual(generate_typescript_protocol(), expected)


if __name__ == "__main__":
    unittest.main()
