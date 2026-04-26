"""Tests for the inventory/resolve JSON-RPC method."""

from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from unittest.mock import patch

from app.serve import ServeState, handle_inventory_rpc
from core.config import ModelConfig


@dataclass
class _FakeBackend:
    name: str = "studio"
    runtime_id: str = "publisher/qwen-3.5-coder@q4"
    raises: BaseException | None = None
    calls: list[tuple[str, bool]] = field(default_factory=list)

    def resolve_request_model(self, target: ModelConfig, auto_load: bool) -> str:
        self.calls.append((target.name, auto_load))
        if self.raises is not None:
            raise self.raises
        return self.runtime_id


def _make_state(active: str = "farore", backend: str = "studio") -> ServeState:
    state = ServeState()
    state.models = {
        active: ModelConfig(name=active, model_id=f"id::{active}", role="fim"),
    }
    state.active_model = active
    state.backend_name = backend
    state.studio_api_base = "http://127.0.0.1:1234/v1"
    state.llamacpp_api_base = "http://127.0.0.1:8080/v1"
    return state


class InventoryResolveTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_runtime_id_and_studio_endpoint(self) -> None:
        state = _make_state()
        backend = _FakeBackend(name="studio", runtime_id="publisher/qwen-fim@q4")
        responses: list[tuple[int, object, str | None]] = []

        with patch("app.serve.get_backend", return_value=backend), patch(
            "app.serve._respond",
            side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
        ):
            handled = await handle_inventory_rpc(state, 1, "inventory/resolve", {"alias": "farore"})

        self.assertTrue(handled)
        req_id, result, error = responses[0]
        self.assertIsNone(error)
        assert isinstance(result, dict)
        self.assertEqual(result["alias"], "farore")
        self.assertEqual(result["canonical_name"], "farore")
        self.assertEqual(result["model_id"], "publisher/qwen-fim@q4")
        self.assertEqual(result["backend"], "studio")
        self.assertEqual(result["api_base"], "http://127.0.0.1:1234/v1")

    async def test_uses_llamacpp_api_base_when_active(self) -> None:
        state = _make_state(backend="llamacpp")
        backend = _FakeBackend(name="llamacpp")
        responses: list[tuple[int, object, str | None]] = []

        with patch("app.serve.get_backend", return_value=backend), patch(
            "app.serve._respond",
            side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
        ):
            await handle_inventory_rpc(state, 2, "inventory/resolve", {"alias": "farore"})

        result = responses[0][1]
        assert isinstance(result, dict)
        self.assertEqual(result["backend"], "llamacpp")
        self.assertEqual(result["api_base"], "http://127.0.0.1:8080/v1")

    async def test_resolves_case_insensitive_alias(self) -> None:
        state = _make_state()
        backend = _FakeBackend()
        responses: list[tuple[int, object, str | None]] = []

        with patch("app.serve.get_backend", return_value=backend), patch(
            "app.serve._respond",
            side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
        ):
            await handle_inventory_rpc(state, 3, "inventory/resolve", {"model": "FARORE"})

        result = responses[0][1]
        assert isinstance(result, dict)
        self.assertEqual(result["canonical_name"], "farore")

    async def test_falls_back_to_active_model_when_alias_missing(self) -> None:
        state = _make_state()
        backend = _FakeBackend()
        responses: list[tuple[int, object, str | None]] = []

        with patch("app.serve.get_backend", return_value=backend), patch(
            "app.serve._respond",
            side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
        ):
            await handle_inventory_rpc(state, 4, "inventory/resolve", {})

        result = responses[0][1]
        assert isinstance(result, dict)
        self.assertEqual(result["canonical_name"], "farore")

    async def test_rejects_unknown_alias(self) -> None:
        state = _make_state()
        backend = _FakeBackend()
        responses: list[tuple[int, object, str | None]] = []

        with patch("app.serve.get_backend", return_value=backend), patch(
            "app.serve._respond",
            side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
        ):
            await handle_inventory_rpc(state, 5, "inventory/resolve", {"alias": "ghost"})

        req_id, result, error = responses[0]
        self.assertIsNone(result)
        assert isinstance(error, str)
        self.assertIn("ghost", error)

    async def test_passes_auto_load_flag_through_to_backend(self) -> None:
        state = _make_state()
        backend = _FakeBackend()
        responses: list[tuple[int, object, str | None]] = []

        with patch("app.serve.get_backend", return_value=backend), patch(
            "app.serve._respond",
            side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
        ):
            await handle_inventory_rpc(state, 6, "inventory/resolve", {"alias": "farore", "autoLoad": True})

        self.assertEqual(backend.calls[0], ("farore", True))

    async def test_default_auto_load_is_false(self) -> None:
        state = _make_state()
        backend = _FakeBackend()
        responses: list[tuple[int, object, str | None]] = []

        with patch("app.serve.get_backend", return_value=backend), patch(
            "app.serve._respond",
            side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
        ):
            await handle_inventory_rpc(state, 7, "inventory/resolve", {"alias": "farore"})

        self.assertEqual(backend.calls[0], ("farore", False))

    async def test_string_false_auto_load_is_treated_as_false(self) -> None:
        state = _make_state()
        backend = _FakeBackend()
        responses: list[tuple[int, object, str | None]] = []

        with patch("app.serve.get_backend", return_value=backend), patch(
            "app.serve._respond",
            side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
        ):
            await handle_inventory_rpc(state, 8, "inventory/resolve", {"alias": "farore", "autoLoad": "false"})

        self.assertEqual(backend.calls[0], ("farore", False))

    async def test_string_true_auto_load_is_treated_as_true(self) -> None:
        state = _make_state()
        backend = _FakeBackend()
        responses: list[tuple[int, object, str | None]] = []

        with patch("app.serve.get_backend", return_value=backend), patch(
            "app.serve._respond",
            side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
        ):
            await handle_inventory_rpc(state, 9, "inventory/resolve", {"alias": "farore", "autoLoad": "true"})

        self.assertEqual(backend.calls[0], ("farore", True))


if __name__ == "__main__":
    unittest.main()
