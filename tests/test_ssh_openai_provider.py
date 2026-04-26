import unittest
from unittest.mock import patch

from app.backends import LlamaCppBackend
from core.provider import (
    CompletionRequest,
    SSHOpenAIProvider,
    ToolCallDelta,
    create_provider,
)


class StubSSHOpenAIProvider(SSHOpenAIProvider):
    def __init__(self, response: dict):
        super().__init__("ssh://medical-mechanica/127.0.0.1:1234/v1")
        self.response = response
        self.last_payload: dict | None = None

    async def _post_json(self, path: str, payload: dict) -> dict:
        self.last_payload = {"path": path, "payload": payload}
        return self.response


class StubSSHModelsProvider(SSHOpenAIProvider):
    def __init__(self, response: dict):
        super().__init__("ssh://medical-mechanica/127.0.0.1:1234/v1")
        self.response = response

    async def _get_json(self, path: str, *, timeout: float | None = None) -> dict:
        del timeout
        if path != "/models":
            raise AssertionError(path)
        return self.response


class SSHOpenAIProviderTests(unittest.IsolatedAsyncioTestCase):
    def test_create_provider_uses_ssh_provider_for_ssh_api_base(self) -> None:
        provider = create_provider(
            "llamacpp",
            api_base="ssh://medical-mechanica/127.0.0.1:1234/v1",
        )

        self.assertIsInstance(provider, SSHOpenAIProvider)

    def test_parse_ssh_api_base(self) -> None:
        provider = SSHOpenAIProvider("ssh://medical-mechanica/127.0.0.1:1234/v1")

        self.assertEqual(provider._ssh_host, "medical-mechanica")
        self.assertEqual(provider._remote_api_base, "http://127.0.0.1:1234/v1")

    def test_build_post_command_inlines_small_payload_without_stdin(self) -> None:
        provider = SSHOpenAIProvider("ssh://medical-mechanica/127.0.0.1:1234/v1")

        command, stdin = provider._build_remote_curl_command(
            "POST",
            "http://127.0.0.1:1234/v1/chat/completions",
            {"model": "oracle-pro", "messages": [{"role": "user", "content": "ping"}]},
            20,
        )

        self.assertIsNone(stdin)
        self.assertIn("powershell -NoProfile -Command", command)
        self.assertIn("curl.exe", command)
        self.assertIn("FromBase64String", command)
        self.assertNotIn("\"messages\"", command)

    def test_build_post_command_uses_stdin_for_large_payload(self) -> None:
        provider = SSHOpenAIProvider("ssh://medical-mechanica/127.0.0.1:1234/v1")

        command, stdin = provider._build_remote_curl_command(
            "POST",
            "http://127.0.0.1:1234/v1/chat/completions",
            {"model": "oracle-pro", "messages": [{"role": "user", "content": "x" * 5000}]},
            20,
        )

        assert stdin is not None
        self.assertIn(b'"content":"', stdin)
        self.assertIn("cmd /c curl.exe", command)
        self.assertIn("--data-binary @-", command)

    async def test_list_model_ids_parses_openai_models_payload(self) -> None:
        provider = StubSSHModelsProvider({
            "data": [
                {"id": "gguf/zelda/qwen3-oracle-14b-v8-q4km.gguf"},
                {"id": "other"},
                {"bad": "entry"},
            ],
        })

        self.assertEqual(
            await provider.list_model_ids(),
            ["gguf/zelda/qwen3-oracle-14b-v8-q4km.gguf", "other"],
        )

    async def test_llamacpp_backend_uses_ssh_provider_for_status_and_models(self) -> None:
        provider = StubSSHModelsProvider({
            "data": [{"id": "gguf/zelda/qwen3-oracle-14b-v8-q4km.gguf"}],
        })
        backend = LlamaCppBackend(
            api_base="ssh://medical-mechanica/127.0.0.1:1234/v1",
            model="gguf/zelda/qwen3-oracle-14b-v8-q4km.gguf",
        )

        with patch("app.backends.create_provider", return_value=provider):
            status = await backend.check_connection()
            models = await backend.list_loaded_models()

        self.assertTrue(status.connected)
        self.assertEqual(status.detail, "ssh://medical-mechanica/127.0.0.1:1234/v1")
        self.assertEqual(models, ["gguf/zelda/qwen3-oracle-14b-v8-q4km.gguf"])

    async def test_stream_emits_text_reasoning_usage_and_payload(self) -> None:
        provider = StubSSHOpenAIProvider({
            "choices": [{
                "message": {
                    "content": "Oracle Pro V8 Online",
                    "reasoning_content": "\n",
                },
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4},
        })

        chunks = [
            chunk
            async for chunk in provider.stream(
                CompletionRequest(
                    model_id="gguf/zelda/qwen3-oracle-14b-v8-q4km.gguf",
                    messages=[{"role": "user", "content": "ping"}],
                    system="You are Oracle-Pro.",
                    temperature=0.0,
                    max_tokens=16,
                    stream=True,
                )
            )
        ]

        assert provider.last_payload is not None
        payload = provider.last_payload["payload"]
        self.assertEqual(provider.last_payload["path"], "/chat/completions")
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["model"], "gguf/zelda/qwen3-oracle-14b-v8-q4km.gguf")
        self.assertEqual(payload["messages"][0]["role"], "system")
        self.assertEqual(chunks[0].content.text, "Oracle Pro V8 Online")
        self.assertEqual(chunks[-1].usage.prompt_tokens, 3)
        self.assertEqual(chunks[-1].usage.completion_tokens, 4)

    async def test_stream_emits_tool_calls(self) -> None:
        provider = StubSSHOpenAIProvider({
            "choices": [{
                "message": {
                    "content": "",
                    "tool_calls": [{
                        "id": "call_1",
                        "function": {
                            "name": "label_lookup",
                            "arguments": "{\"query\":\"NMI\"}",
                        },
                    }],
                },
                "finish_reason": "tool_calls",
            }],
        })

        chunks = [
            chunk
            async for chunk in provider.stream(
                CompletionRequest(
                    model_id="oracle-pro",
                    messages=[{"role": "user", "content": "lookup NMI"}],
                    tools=[{"type": "function", "function": {"name": "label_lookup"}}],
                )
            )
        ]

        tool_chunks = [chunk for chunk in chunks if chunk.tool_calls]
        self.assertEqual(len(tool_chunks), 1)
        tool_call = tool_chunks[0].tool_calls[0]
        self.assertIsInstance(tool_call, ToolCallDelta)
        self.assertEqual(tool_call.id, "call_1")
        self.assertEqual(tool_call.name, "label_lookup")
        self.assertEqual(tool_call.arguments, "{\"query\":\"NMI\"}")


if __name__ == "__main__":
    unittest.main()
