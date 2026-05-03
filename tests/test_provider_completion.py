"""Tests for LocalProvider.complete() — the FIM cold-path entry point."""

from __future__ import annotations

import json
import unittest

import httpx

from core.fim import build_fim_prompt
from core.provider import CompletionRequest, LocalProvider, ProviderError


def _mock_transport(responder):
    return httpx.MockTransport(responder)


def _attach_mock(provider: LocalProvider, transport: httpx.MockTransport) -> None:
    provider._client = httpx.AsyncClient(
        base_url=provider._api_base,
        transport=transport,
        timeout=5.0,
    )


class LocalProviderCompleteTests(unittest.IsolatedAsyncioTestCase):
    def test_build_messages_can_append_qwen_non_thinking_prefill(self) -> None:
        request = CompletionRequest(
            model_id="oracle-9b-router",
            messages=[{"role": "user", "content": "Reply exactly: z3cli smoke ok"}],
            system="You are concise.",
            disable_reasoning_prefill=True,
        )

        messages = LocalProvider._build_messages(request)

        self.assertEqual(messages[0], {"role": "system", "content": "You are concise."})
        self.assertEqual(messages[1], {"role": "user", "content": "Reply exactly: z3cli smoke ok"})
        self.assertEqual(messages[2], {"role": "assistant", "content": "<think>\n\n</think>\n\n"})

    async def test_complete_posts_to_completions_endpoint(self) -> None:
        captured: dict[str, object] = {}

        def respond(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["body"] = json.loads(request.content.decode())
            payload = {
                "choices": [{"text": "lda #$01", "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 4},
            }
            return httpx.Response(200, json=payload)

        provider = LocalProvider("http://127.0.0.1:1234/v1")
        _attach_mock(provider, _mock_transport(respond))

        try:
            result = await provider.complete(
                model_id="farore",
                prompt="<|fim_prefix|>x<|fim_suffix|>y<|fim_middle|>",
                max_tokens=24,
                temperature=0.05,
                stop=["<|endoftext|>"],
            )
        finally:
            await provider.close()

        self.assertEqual(result.text, "lda #$01")
        self.assertEqual(result.finish_reason, "stop")
        self.assertEqual(result.usage.prompt_tokens, 11)
        self.assertEqual(result.usage.completion_tokens, 4)
        self.assertEqual(captured["url"], "http://127.0.0.1:1234/v1/completions")
        body = captured["body"]
        assert isinstance(body, dict)
        self.assertEqual(body["model"], "farore")
        self.assertEqual(body["max_tokens"], 24)
        self.assertEqual(body["temperature"], 0.05)
        self.assertEqual(body["stream"], False)
        self.assertEqual(body["stop"], ["<|endoftext|>"])
        self.assertIn("<|fim_prefix|>", body["prompt"])

    async def test_complete_raises_on_http_error(self) -> None:
        def respond(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="server overloaded")

        provider = LocalProvider("http://127.0.0.1:1234/v1")
        _attach_mock(provider, _mock_transport(respond))

        try:
            with self.assertRaises(ProviderError) as cm:
                await provider.complete(
                    model_id="farore",
                    prompt="x",
                    max_tokens=4,
                )
            self.assertIn("503", str(cm.exception))
        finally:
            await provider.close()

    async def test_complete_handles_missing_usage(self) -> None:
        def respond(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"choices": [{"text": "ok"}]})

        provider = LocalProvider("http://127.0.0.1:1234/v1")
        _attach_mock(provider, _mock_transport(respond))

        try:
            result = await provider.complete(model_id="farore", prompt="x")
        finally:
            await provider.close()

        self.assertEqual(result.text, "ok")
        self.assertEqual(result.usage.prompt_tokens, 0)
        self.assertEqual(result.usage.completion_tokens, 0)


class FimPromptTests(unittest.TestCase):
    def test_build_fim_prompt_uses_qwen_tokens_for_farore(self) -> None:
        prompt = build_fim_prompt("PRE", "SUF", "farore")
        self.assertIn("<|fim_prefix|>PRE", prompt)
        self.assertIn("<|fim_suffix|>SUF", prompt)
        self.assertTrue(prompt.endswith("<|fim_middle|>"))

    def test_build_fim_prompt_falls_back_for_unknown_model(self) -> None:
        prompt = build_fim_prompt("a", "b", "mystery-model")
        self.assertIn("<|fim_prefix|>a", prompt)
        self.assertIn("<|fim_suffix|>b", prompt)


if __name__ == "__main__":
    unittest.main()
