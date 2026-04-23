import os
import unittest
from unittest.mock import patch
from pathlib import Path

from z3cli.app.shared_runtime import (
    apply_use_target,
    available_use_targets,
    maybe_reset_engine_for_topic_shift,
    restore_runtime_state,
    use_lean_llamacpp_prompt,
)
from z3cli.core.config import LlamaCppNodeConfig, ModelConfig, StudioNodeConfig


def _model(name: str) -> ModelConfig:
    return ModelConfig(name=name, model_id=name, role="")


class _State:
    def __init__(self) -> None:
        self.active_model = "nayru"
        self.mode = "manual"
        self.backend_name = "studio"
        self.auto_start_server = False
        self.host = "127.0.0.1"
        self.port = 1234
        self.workspace = Path("/tmp")
        self.rom_path = None
        self.tools_enabled = True
        self.tools_write = False
        self.verify_hooks = True
        self.broadcast_models: list[str] = []
        self.studio_api_base = "http://127.0.0.1:1234/v1"
        self.studio_node = ""
        self.studio_nodes = {
            "oracle-pro-home": StudioNodeConfig(
                name="oracle-pro-home",
                api_base="http://127.0.0.1:2234/v1",
                model="oracle",
                description="Windows tunnel",
                hostd_url="http://127.0.0.1:8766",
            ),
        }
        self.llamacpp_api_base = "http://127.0.0.1:8080/v1"
        self.llamacpp_model = "oracle-fast"
        self.llamacpp_node = ""
        self.llamacpp_nodes = {
            "oracle-pro-vast": LlamaCppNodeConfig(
                name="oracle-pro-vast",
                api_base="http://127.0.0.1:18080/v1",
                model="oracle-pro",
                description="SSH tunnel",
                lean_prompt=True,
            ),
        }
        self.orchestrator_model = "nayru"
        self.permission_rules: dict[str, bool] = {}
        self.models = {
            "nayru": _model("nayru"),
            "oracle": _model("oracle"),
            "oracle-pro": _model("oracle-pro"),
            "oracle-fast": _model("oracle-fast"),
        }
        self.model_alias_resolutions = 2
        self.model_lookup_failures = 1
        self.model_request_counts = {"oracle": 3}


class _Engine:
    def __init__(self, messages: list[dict] | None = None) -> None:
        self.messages = list(messages or [])
        self.reset_count = 0

    def reset(self) -> None:
        self.reset_count += 1
        self.messages.clear()


class SharedRuntimeTests(unittest.TestCase):
    def test_restore_unknown_active_model_warns_and_preserves_current_model(self) -> None:
        state = _State()

        warnings = restore_runtime_state(state, {"active_model": "ghost"})

        self.assertEqual(state.active_model, "nayru")
        self.assertIn("Unknown model in session: ghost", warnings)

    def test_restore_unknown_orchestrator_model_warns_and_preserves_current_model(self) -> None:
        state = _State()

        warnings = restore_runtime_state(
            state,
            {
                "active_model": "nayru",
                "orchestrator_model": "bogus-orchestrator",
            },
        )

        self.assertEqual(state.orchestrator_model, "nayru")
        self.assertIn("Unknown orchestrator model in session: bogus-orchestrator", warnings)

    def test_restore_legacy_active_model_aliases_to_current_registry(self) -> None:
        state = _State()

        warnings = restore_runtime_state(state, {"active_model": "switchhook"})

        self.assertEqual(state.active_model, "oracle")
        self.assertEqual(warnings, [])

    def test_restore_restores_model_alias_telemetry(self) -> None:
        state = _State()

        warnings = restore_runtime_state(state, {
            "model_alias_resolutions": 5,
            "model_lookup_failures": 6,
            "model_request_counts": {"oracle": 7, "nayru": 2},
        })

        self.assertEqual(warnings, [])
        self.assertEqual(state.model_alias_resolutions, 5)
        self.assertEqual(state.model_lookup_failures, 6)
        self.assertEqual(state.model_request_counts, {"oracle": 7, "nayru": 2})

    def test_restore_invalid_model_request_counts_defaults_to_empty(self) -> None:
        state = _State()

        warnings = restore_runtime_state(state, {"model_request_counts": ["not", "a", "dict"]})

        self.assertEqual(warnings, [])
        self.assertEqual(state.model_request_counts, {})

    def test_restore_selects_named_llamacpp_node(self) -> None:
        state = _State()

        warnings = restore_runtime_state(state, {"llamacpp_node": "oracle-pro-vast"})

        self.assertEqual(warnings, [])
        self.assertEqual(state.llamacpp_node, "oracle-pro-vast")
        self.assertEqual(state.llamacpp_api_base, "http://127.0.0.1:18080/v1")
        self.assertEqual(state.llamacpp_model, "oracle-pro")

    def test_restore_selects_named_studio_node(self) -> None:
        state = _State()

        with patch.dict("os.environ", {}, clear=False):
            warnings = restore_runtime_state(state, {"studio_node": "oracle-pro-home"})
            self.assertEqual(os.environ.get("Z3CLI_LMSTUDIO_HOSTD_URL"), "http://127.0.0.1:8766")

        self.assertEqual(warnings, [])
        self.assertEqual(state.studio_node, "oracle-pro-home")
        self.assertEqual(state.studio_api_base, "http://127.0.0.1:2234/v1")
        self.assertEqual(state.backend_name, "studio")
        self.assertEqual(state.active_model, "oracle")

    def test_lean_prompt_enabled_only_for_llamacpp_nodes_that_request_it(self) -> None:
        state = _State()

        self.assertFalse(use_lean_llamacpp_prompt(state))
        state.backend_name = "llamacpp"
        restore_runtime_state(state, {"llamacpp_node": "oracle-pro-vast"})

        self.assertTrue(use_lean_llamacpp_prompt(state))

    def test_available_use_targets_lists_aliases_and_nodes(self) -> None:
        state = _State()

        entries = available_use_targets(state)
        names = [entry["name"] for entry in entries]

        self.assertIn("home", names)
        self.assertIn("vast", names)
        self.assertIn("oracle-pro-home", names)
        self.assertIn("oracle-pro-vast", names)

    def test_apply_use_target_home_alias_switches_to_studio_node(self) -> None:
        state = _State()

        with patch.dict("os.environ", {}, clear=False):
            result, error = apply_use_target(state, "home")

            self.assertIsNone(error)
            assert result is not None
            self.assertEqual(state.backend_name, "studio")
            self.assertEqual(state.studio_node, "oracle-pro-home")
            self.assertEqual(state.active_model, "oracle")
            self.assertEqual(result["resolved"], "oracle-pro-home")
            self.assertEqual(os.environ.get("Z3CLI_LMSTUDIO_HOSTD_URL"), "http://127.0.0.1:8766")

    def test_apply_use_target_prefers_named_node_for_model(self) -> None:
        state = _State()

        result, error = apply_use_target(state, "oracle-pro")

        self.assertIsNone(error)
        assert result is not None
        self.assertEqual(state.backend_name, "llamacpp")
        self.assertEqual(state.llamacpp_node, "oracle-pro-vast")
        self.assertEqual(result["resolved"], "oracle-pro-vast")

    def test_topic_shift_reset_triggers_for_new_subject(self) -> None:
        engine = _Engine(messages=[{"role": "user", "content": "old"}] * 6)
        engine._z3cli_recent_prompts = [  # type: ignore[attr-defined]
            "What tools do you have access to?",
            "What are some pending tasks in Oracle of Secrets I need to work on?",
        ]

        reset = maybe_reset_engine_for_topic_shift(engine, "Let's take a look at the Minecart sprite")

        self.assertTrue(reset)
        self.assertEqual(engine.reset_count, 1)

    def test_topic_shift_reset_skips_followup_prompt(self) -> None:
        engine = _Engine(messages=[{"role": "user", "content": "old"}] * 6)
        engine._z3cli_recent_prompts = [  # type: ignore[attr-defined]
            "Let's take a look at the Minecart sprite",
        ]

        reset = maybe_reset_engine_for_topic_shift(engine, "What are you talking about?")

        self.assertFalse(reset)
        self.assertEqual(engine.reset_count, 0)


if __name__ == "__main__":
    unittest.main()
