"""Tests for the AppState slice views introduced in Phase 6.3."""

from __future__ import annotations

import unittest
from pathlib import Path

from rich.console import Console

from z3cli.app.repl import AppState


def _make_state() -> AppState:
    return AppState(
        console=Console(quiet=True),
        host="127.0.0.1",
        port=1234,
        api_base="http://127.0.0.1:1234/v1",
        backend_name="studio",
        studio_api_base="http://127.0.0.1:1234/v1",
        llamacpp_api_base="http://127.0.0.1:8080/v1",
        llamacpp_model="",
        registry_path=Path("/tmp/registry.toml"),
        mcp_path=Path("/tmp/mcp.json"),
        models={},
        routers={},
        active_model="nayru",
        mode="oracle",
        auto_load=True,
        auto_start_server=True,
        workspace=Path("/tmp"),
        rom_path=None,
        temperature=0.3,
        max_tokens=2048,
        broadcast_models=["farore", "majora"],
        tools_enabled=False,
    )


class SliceReadWriteTests(unittest.TestCase):
    def test_routing_slice_reads_fields(self) -> None:
        s = _make_state()
        self.assertEqual(s.routing.active_model, "nayru")
        self.assertEqual(s.routing.mode, "oracle")
        self.assertEqual(s.routing.broadcast_models, ["farore", "majora"])

    def test_routing_slice_writes_propagate(self) -> None:
        s = _make_state()
        s.routing.active_model = "oracle"
        self.assertEqual(s.active_model, "oracle")
        s.routing.mode = "manual"
        self.assertEqual(s.mode, "manual")

    def test_backend_slice_reads_and_writes(self) -> None:
        s = _make_state()
        self.assertEqual(s.backend_state.backend_name, "studio")
        s.backend_state.backend_name = "llamacpp"
        self.assertEqual(s.backend_name, "llamacpp")
        s.backend_state.api_base = "http://localhost:9999/v1"
        self.assertEqual(s.api_base, "http://localhost:9999/v1")

    def test_metrics_slice_reads_and_writes(self) -> None:
        s = _make_state()
        s.metrics.prompt_tokens = 123
        s.metrics.completion_tokens = 45
        self.assertEqual(s.prompt_tokens, 123)
        self.assertEqual(s.completion_tokens, 45)
        self.assertEqual(s.metrics.message_count, 0)

    def test_ui_slice_reads_and_writes(self) -> None:
        s = _make_state()
        self.assertIs(s.ui.console, s.console)
        s.ui.focus_context = "hello"
        self.assertEqual(s.focus_context, "hello")
        s.ui.startup_warnings.append("warn")
        self.assertEqual(s.startup_warnings, ["warn"])

    def test_pending_ops_slice(self) -> None:
        s = _make_state()
        s.pending_ops.permission_rules["tool:yaze"] = True
        self.assertEqual(s.permission_rules, {"tool:yaze": True})
        self.assertIs(
            s.pending_ops.pending_write_contexts,
            s.pending_write_contexts,
        )

    def test_slice_objects_are_stable_across_access(self) -> None:
        # Although slices are lightweight proxies, they should be the same
        # instance across repeated `.routing` accesses so any per-slice
        # state (future caches) is preserved.
        s = _make_state()
        self.assertIs(s.routing, s.routing)
        self.assertIs(s.backend_state, s.backend_state)


if __name__ == "__main__":
    unittest.main()
