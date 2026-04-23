import tempfile
import unittest
from pathlib import Path

from z3cli.app.runtime import ensure_model_available, ensure_targets_available
from z3cli.core.config import load_registry, rollout_warnings


class RolloutGateTests(unittest.TestCase):
    def test_load_registry_blocks_unapproved_production_alias_swap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry_path = root / "chat_registry.toml"
            rollout_path = root / "model_rollouts.toml"
            registry_path.write_text(
                """
[[models]]
name = "oracle-main-plan"
model_id = "qwen3-oracle-8b-v1"
provider = "studio"
role = "planner"
""".strip(),
                encoding="utf-8",
            )
            rollout_path.write_text(
                """
[aliases.oracle-main-plan]
allowed_model_ids = ["oracle-main-plan"]
required_checks = ["ROM-hacking eval gate", "live tool smoke run"]
""".strip(),
                encoding="utf-8",
            )

            models, _routers = load_registry(registry_path, rollout_path=rollout_path)

            reason = models["oracle-main-plan"].rollout_block_reason
            self.assertIn("rollout-gated", reason)
            self.assertIn("qwen3-oracle-8b-v1", reason)
            self.assertEqual(len(rollout_warnings(models)), 1)

    def test_load_registry_allows_approved_model_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry_path = root / "chat_registry.toml"
            rollout_path = root / "model_rollouts.toml"
            registry_path.write_text(
                """
[[models]]
name = "oracle-main-plan"
model_id = "qwen3-oracle-8b-v1"
provider = "studio"
role = "planner"
""".strip(),
                encoding="utf-8",
            )
            rollout_path.write_text(
                """
[aliases.oracle-main-plan]
allowed_model_ids = ["qwen3-oracle-8b-v1"]
""".strip(),
                encoding="utf-8",
            )

            models, _routers = load_registry(registry_path, rollout_path=rollout_path)

            self.assertEqual(models["oracle-main-plan"].rollout_block_reason, "")

    def test_specialist_aliases_allow_current_artifact_model_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry_path = root / "chat_registry.toml"
            rollout_path = root / "model_rollouts.toml"
            registry_path.write_text(
                """
[[models]]
name = "din"
model_id = "gguf/zelda/din-7b-v4-q4km.gguf"
provider = "studio"
role = "author"

[[models]]
name = "nayru"
model_id = "gguf/zelda/nayru-v9-q8_0.gguf"
provider = "studio"
role = "analysis"

[[models]]
name = "farore"
model_id = "gguf/zelda/farore-7b-v5-q8.gguf"
provider = "studio"
role = "debugger"

[[models]]
name = "majora"
model_id = "gguf/zelda/majora-7b-v2-q8.gguf"
provider = "studio"
role = "context"

[[models]]
name = "veran"
model_id = "gguf/zelda/veran-7b-v4-q8.gguf"
provider = "studio"
role = "editor"

[[models]]
name = "hylia"
model_id = "gguf/zelda/hylia-v3-q8_0.gguf"
provider = "studio"
role = "historian"
""".strip(),
                encoding="utf-8",
            )
            rollout_path.write_text(
                """
[aliases.din]
allowed_model_ids = ["din", "gguf/zelda/din-7b-v4-q4km.gguf"]

[aliases.nayru]
allowed_model_ids = ["nayru", "gguf/zelda/nayru-v9-q8_0.gguf"]

[aliases.farore]
allowed_model_ids = ["farore", "gguf/zelda/farore-7b-v5-q8.gguf"]

[aliases.majora]
allowed_model_ids = ["majora", "gguf/zelda/majora-7b-v2-q8.gguf"]

[aliases.veran]
allowed_model_ids = ["veran", "gguf/zelda/veran-7b-v4-q8.gguf"]

[aliases.hylia]
allowed_model_ids = ["hylia", "gguf/zelda/hylia-v3-q8_0.gguf"]
""".strip(),
                encoding="utf-8",
            )

            models, _routers = load_registry(registry_path, rollout_path=rollout_path)

            for name in ("din", "nayru", "farore", "majora", "veran", "hylia"):
                self.assertEqual(models[name].rollout_block_reason, "", name)

    def test_oracle_fast_alias_allows_live_fast_lane(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry_path = root / "chat_registry.toml"
            rollout_path = root / "model_rollouts.toml"
            registry_path.write_text(
                """
[[models]]
name = "oracle-fast"
model_id = "oracle-fast"
provider = "studio"
role = "fast"
""".strip(),
                encoding="utf-8",
            )
            rollout_path.write_text(
                """
[aliases.oracle-fast]
allowed_model_ids = ["oracle-fast"]
""".strip(),
                encoding="utf-8",
            )

            models, _routers = load_registry(registry_path, rollout_path=rollout_path)

            self.assertEqual(models["oracle-fast"].rollout_block_reason, "")

    def test_oracle_pro_alias_can_preapprove_switchhook_transition_lane(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry_path = root / "chat_registry.toml"
            rollout_path = root / "model_rollouts.toml"
            registry_path.write_text(
                """
[[models]]
name = "oracle"
model_id = "gguf/zelda/qwen3-oracle-14b-v7-q4km.gguf"
provider = "studio"
aliases = ["oracle-pro"]
role = "planner"
""".strip(),
                encoding="utf-8",
            )
            rollout_path.write_text(
                """
[aliases.oracle-pro]
allowed_model_ids = ["oracle", "gguf/zelda/qwen3-oracle-14b-v7-q4km.gguf", "qwen3-oracle-14b-v7"]
required_checks = ["ROM-hacking eval gate", "live tool smoke run"]
""".strip(),
                encoding="utf-8",
            )

            models, _routers = load_registry(registry_path, rollout_path=rollout_path)

            self.assertEqual(models["oracle"].rollout_block_reason, "")

    def test_load_registry_preserves_inline_rollout_block_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry_path = root / "chat_registry.toml"
            registry_path.write_text(
                """
[[models]]
name = "nayru"
model_id = "nayru"
provider = "studio"
role = "analysis"
rollout_block_reason = "nayru is still gated"
""".strip(),
                encoding="utf-8",
            )

            models, _routers = load_registry(registry_path)

            self.assertEqual(models["nayru"].rollout_block_reason, "nayru is still gated")

    def test_ensure_model_available_raises_for_blocked_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry_path = root / "chat_registry.toml"
            rollout_path = root / "model_rollouts.toml"
            registry_path.write_text(
                """
[[models]]
name = "oracle-main-act"
model_id = "qwen3-oracle-8b-v1"
provider = "studio"
role = "act"
""".strip(),
                encoding="utf-8",
            )
            rollout_path.write_text(
                """
[aliases.oracle-main-act]
allowed_model_ids = ["oracle-main-act"]
""".strip(),
                encoding="utf-8",
            )

            models, _routers = load_registry(registry_path, rollout_path=rollout_path)

            with self.assertRaisesRegex(RuntimeError, "rollout-gated"):
                ensure_model_available(models["oracle-main-act"])
            with self.assertRaisesRegex(RuntimeError, "rollout-gated"):
                ensure_targets_available([models["oracle-main-act"]])

    def test_alias_gated_model_can_block_canonical_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry_path = root / "chat_registry.toml"
            rollout_path = root / "model_rollouts.toml"
            registry_path.write_text(
                """
[[models]]
name = "oracle"
model_id = "qwen3-oracle-8b-v1"
provider = "studio"
aliases = ["oracle-main-legacy"]
""".strip(),
                encoding="utf-8",
            )
            rollout_path.write_text(
                """
[aliases.oracle-main-legacy]
allowed_model_ids = ["oracle"]
required_checks = ["ROM-hacking eval gate", "live tool smoke run"]
""".strip(),
                encoding="utf-8",
            )

            models, _routers = load_registry(registry_path, rollout_path=rollout_path)

            reason = models["oracle"].rollout_block_reason
            self.assertIn("rollout-gated", reason)
            self.assertIn("oracle-main-legacy", reason)
            self.assertIn("qwen3-oracle-8b-v1", reason)

    def test_multiple_alias_gates_for_canonical_model_do_not_reset_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry_path = root / "chat_registry.toml"
            rollout_path = root / "model_rollouts.toml"
            registry_path.write_text(
                """
[[models]]
name = "oracle"
model_id = "qwen3-oracle-8b-v1"
provider = "studio"
aliases = ["oracle-main-legacy"]
""".strip(),
                encoding="utf-8",
            )
            rollout_path.write_text(
                """
[aliases.oracle]
allowed_model_ids = ["qwen3-oracle-8b-v1"]
required_checks = ["ROM-hacking eval gate", "live tool smoke run"]

[aliases.oracle-main-legacy]
allowed_model_ids = ["oracle"]
required_checks = ["ROM-hacking eval gate", "live tool smoke run"]
""".strip(),
                encoding="utf-8",
            )

            models, _routers = load_registry(registry_path, rollout_path=rollout_path)

            reason = models["oracle"].rollout_block_reason
            self.assertIn("rollout-gated", reason)
            self.assertIn("oracle-main-legacy", reason)


if __name__ == "__main__":
    unittest.main()
