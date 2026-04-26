"""Tests for the `complete` JSON-RPC handler used by vscode-z3cli FIM cold path."""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from unittest.mock import patch

from app.serve import ServeState, handle_complete
from core.config import ModelConfig
from core.provider import CompletionResponse, UsageInfo


@dataclass
class _FakeResponse:
    response: CompletionResponse
    closed: bool = False


def _make_state(active: str = "farore") -> ServeState:
    state = ServeState()
    state.models = {
        active: ModelConfig(name=active, model_id=f"id::{active}", role="fim"),
    }
    state.active_model = active
    state.studio_api_base = "http://127.0.0.1:1234/v1"
    state.llamacpp_api_base = "http://127.0.0.1:8080/v1"
    return state


class _FakeProvider:
    instances: list["_FakeProvider"] = []

    def __init__(self, api_base: str):
        self.api_base = api_base
        self.calls: list[dict[str, object]] = []
        self.closed = False
        _FakeProvider.instances.append(self)

    async def complete(self, **kwargs):
        self.calls.append(kwargs)
        return CompletionResponse(
            text="lda #$01",
            finish_reason="stop",
            usage=UsageInfo(prompt_tokens=12, completion_tokens=4),
        )

    async def close(self) -> None:
        self.closed = True


class HandleCompleteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _FakeProvider.instances = []

    async def test_handle_complete_returns_text_and_usage(self) -> None:
        state = _make_state("farore")
        responses: list[tuple[int, object, str | None]] = []

        with patch(
            "app.serve.LocalProvider",
            side_effect=lambda api_base: _FakeProvider(api_base),
        ), patch(
            "app.serve.resolve_request_model_name",
            return_value="resolved::farore",
        ), patch(
            "app.serve._respond",
            side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
        ):
            await handle_complete(state, 7, {
                "prefix": "lda ",
                "suffix": "\nrts",
                "max_tokens": 32,
                "temperature": 0.05,
                "stop": ["<|endoftext|>"],
            })

        self.assertEqual(len(responses), 1)
        req_id, result, error = responses[0]
        self.assertEqual(req_id, 7)
        self.assertIsNone(error)
        assert isinstance(result, dict)
        self.assertEqual(result["text"], "lda #$01")
        self.assertEqual(result["finish_reason"], "stop")
        self.assertEqual(result["prompt_tokens"], 12)
        self.assertEqual(result["completion_tokens"], 4)
        self.assertEqual(result["model"], "farore")

        self.assertEqual(len(_FakeProvider.instances), 1)
        provider = _FakeProvider.instances[0]
        self.assertEqual(provider.api_base, "http://127.0.0.1:1234/v1")
        self.assertTrue(provider.closed)
        call = provider.calls[0]
        self.assertEqual(call["model_id"], "resolved::farore")
        self.assertEqual(call["max_tokens"], 32)
        self.assertEqual(call["temperature"], 0.05)
        self.assertEqual(call["stop"], ["<|endoftext|>"])
        self.assertIn("<|fim_prefix|>lda ", call["prompt"])
        self.assertIn("<|fim_suffix|>\nrts", call["prompt"])

    async def test_handle_complete_uses_llamacpp_api_base_when_active(self) -> None:
        state = _make_state("farore")
        state.backend_name = "llamacpp"
        responses: list[tuple[int, object, str | None]] = []

        with patch(
            "app.serve.LocalProvider",
            side_effect=lambda api_base: _FakeProvider(api_base),
        ), patch(
            "app.serve.resolve_request_model_name",
            return_value="resolved::farore",
        ), patch(
            "app.serve._respond",
            side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
        ):
            await handle_complete(state, 8, {"model": "farore", "prompt": "raw-prompt"})

        provider = _FakeProvider.instances[0]
        self.assertEqual(provider.api_base, "http://127.0.0.1:8080/v1")
        self.assertEqual(provider.calls[0]["prompt"], "raw-prompt")

    async def test_handle_complete_resolves_case_insensitive_alias(self) -> None:
        state = _make_state("farore")
        responses: list[tuple[int, object, str | None]] = []

        with patch(
            "app.serve.LocalProvider",
            side_effect=lambda api_base: _FakeProvider(api_base),
        ), patch(
            "app.serve.resolve_request_model_name",
            return_value="resolved::farore",
        ), patch(
            "app.serve._respond",
            side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
        ):
            await handle_complete(state, 11, {"model": "FARORE", "prefix": "x", "suffix": "y"})

        req_id, result, error = responses[0]
        self.assertIsNone(error)
        assert isinstance(result, dict)
        self.assertEqual(result["model"], "farore")

    async def test_handle_complete_rejects_unknown_alias(self) -> None:
        state = _make_state("farore")
        responses: list[tuple[int, object, str | None]] = []

        with patch(
            "app.serve._respond",
            side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
        ):
            await handle_complete(state, 9, {"model": "ghost", "prefix": "x", "suffix": "y"})

        req_id, result, error = responses[0]
        self.assertEqual(req_id, 9)
        self.assertIsNone(result)
        assert isinstance(error, str)
        self.assertIn("ghost", error)


if __name__ == "__main__":
    unittest.main()
