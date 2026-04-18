import unittest
from pathlib import Path

from z3cli.app.shared_runtime import restore_runtime_state
from z3cli.core.config import ModelConfig


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
        self.llamacpp_model = "oracle-fast"
        self.orchestrator_model = "nayru"
        self.permission_rules: dict[str, bool] = {}
        self.models = {
            "nayru": _model("nayru"),
            "oracle": _model("oracle"),
        }
        self.model_alias_resolutions = 2
        self.model_lookup_failures = 1
        self.model_request_counts = {"oracle": 3}


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


if __name__ == "__main__":
    unittest.main()
