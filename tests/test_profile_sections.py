import tempfile
import unittest
from pathlib import Path

from z3cli.app.runtime import (
    resolve_model_name,
    resolve_oracle_profile_system_prompts,
    resolve_targets_with_reason,
    resolve_targets,
)
from z3cli.core import config as config_mod


class ProfileSectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved_defaults = config_mod.get_profile_defaults()
        self._saved_domain_profiles = dict(config_mod.get_domain_profiles())
        self._saved_mode_profiles = dict(config_mod.get_mode_profiles())
        self._saved_aliases = config_mod.get_registry_aliases()

    def tearDown(self) -> None:
        config_mod._PROFILE_DEFAULTS = {
            "domain": self._saved_defaults[0],
            "mode": self._saved_defaults[1],
        }
        config_mod._DOMAIN_PROFILES = dict(self._saved_domain_profiles)
        config_mod._MODE_PROFILES = dict(self._saved_mode_profiles)
        config_mod._MODEL_ALIAS_MAP = dict(self._saved_aliases)

    def _write_registry(self, tmp: str, content: str) -> Path:
        path = Path(tmp) / "chat_registry.toml"
        path.write_text(content.strip(), encoding="utf-8")
        return path

    def _write_empty_rollout(self, tmp: str) -> Path:
        path = Path(tmp) / "model_rollouts.toml"
        path.write_text("[settings]\nenforce = false\n", encoding="utf-8")
        return path

    def test_load_registry_populates_profile_sections_and_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry_path = self._write_registry(
                tmp,
                """
[profile_defaults]
domain = "adaptive"
mode = "author"

[[domain_profiles]]
name = "adaptive"

[[domain_profiles]]
name = "alttp-vanilla"
keywords = ["alttp", "usdasm"]
system_prompt = "Use vanilla conventions."

[[mode_profiles]]
name = "adaptive"

[[mode_profiles]]
name = "trace"
keywords = ["trace", "walk"]
system_prompt = "Explain rather than patch."

[[models]]
name = "oracle"
provider = "studio"
model_id = "gguf/zelda/main-1"

[[models]]
name = "din"
provider = "studio"
model_id = "gguf/zelda/din-7b"
domain = "adaptive"
mode = "author"
effort = "low"
                """.strip(),
            )
            models, _routers = config_mod.load_registry(
                registry_path,
                rollout_path=self._write_empty_rollout(tmp),
            )

            self.assertEqual(config_mod.get_profile_defaults(), ("adaptive", "author"))
            self.assertEqual(models["oracle"].domain, "adaptive")
            self.assertEqual(models["oracle"].mode, "author")
            self.assertEqual(models["din"].effort, "low")
            self.assertIn("alttp-vanilla", config_mod.get_domain_profiles())
            self.assertIn("trace", config_mod.get_mode_profiles())
            self.assertEqual(len(models), 2)

    def test_oracle_profile_routing_prefers_profile_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry_path = self._write_registry(
                tmp,
                """
[profile_defaults]
domain = "adaptive"
mode = "adaptive"

[[domain_profiles]]
name = "adaptive"

[[domain_profiles]]
name = "oos"
keywords = ["oos", "oracle of secrets"]
system_prompt = "Use Oracle of Secrets conventions."

[[mode_profiles]]
name = "adaptive"

[[mode_profiles]]
name = "trace"
keywords = ["trace", "inspect"]
system_prompt = "Trace before patching."

[[models]]
name = "oracle"
provider = "studio"
model_id = "gguf/zelda/main-1"
domain = "adaptive"
mode = "adaptive"
effort = "high"

[[models]]
name = "nayru"
provider = "studio"
model_id = "gguf/zelda/nayru"
domain = "oos"
mode = "trace"
effort = "high"
                """.strip(),
            )
            models, routers = config_mod.load_registry(
                registry_path,
                rollout_path=self._write_empty_rollout(tmp),
            )
            self.assertIn("oracle", models)
            self.assertIn("nayru", models)

            target = resolve_targets(
                models=models,
                routers=routers,
                active_model="oracle",
                mode="oracle",
                prompt="trace this oos routine and inspect the bug",
                broadcast_models=["farore", "majora", "veran"],
                backend_name="studio",
                llamacpp_model="oracle-fast",
                temperature=0.2,
                max_tokens=1024,
            )

            self.assertEqual([item.name for item in target], ["nayru"])

    def test_profile_system_prompts_appear_for_inferred_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry_path = self._write_registry(
                tmp,
                """
[profile_defaults]
domain = "adaptive"
mode = "adaptive"

[[domain_profiles]]
name = "adaptive"

[[domain_profiles]]
name = "alttp-vanilla"
keywords = ["alttp disassembly", "usdasm"]
system_prompt = "Use vanilla conventions."

[[mode_profiles]]
name = "trace"
keywords = ["trace", "inspect"]
system_prompt = "Trace first, patch second."

[[models]]
name = "oracle"
provider = "studio"
model_id = "gguf/zelda/main-1"
                """.strip(),
            )
            config_mod.load_registry(
                registry_path,
                rollout_path=self._write_empty_rollout(tmp),
            )
            prompts = resolve_oracle_profile_system_prompts("please trace an usdasm flow in the alttp disassembly")

            self.assertIn("Use vanilla conventions.", prompts)
            self.assertIn("Trace first, patch second.", prompts)

    def test_resolve_targets_with_reason_includes_profile_axis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry_path = self._write_registry(
                tmp,
                """
[profile_defaults]
domain = "adaptive"
mode = "author"

[[domain_profiles]]
name = "adaptive"

[[domain_profiles]]
name = "oos"
keywords = ["oos", "oracle of secrets"]
system_prompt = "Use Oracle of Secrets conventions."

[[mode_profiles]]
name = "author"

[[mode_profiles]]
name = "trace"
keywords = ["trace", "inspect"]
system_prompt = "Inspect before patching."

[[models]]
name = "oracle"
provider = "studio"
model_id = "gguf/zelda/main-1"
domain = "adaptive"
mode = "author"
effort = "medium"

[[models]]
name = "nayru"
provider = "studio"
model_id = "gguf/zelda/nayru"
domain = "oos"
mode = "trace"
effort = "high"
                """.strip(),
            )
            models, routers = config_mod.load_registry(
                registry_path,
                rollout_path=self._write_empty_rollout(tmp),
            )
            targets, decisions = resolve_targets_with_reason(
                models=models,
                routers=routers,
                active_model="oracle",
                mode="oracle",
                prompt="trace this oos routine and inspect memory",
                broadcast_models=["farore", "majora", "veran"],
                backend_name="studio",
                llamacpp_model="oracle-fast",
                temperature=0.2,
                max_tokens=1024,
            )

            self.assertEqual([item.name for item in targets], ["nayru"])
            self.assertEqual(len(decisions), 1)
            decision = decisions[0]
            self.assertEqual(decision.target, "nayru")
            self.assertEqual(decision.profile_domain, "oos")
            self.assertEqual(decision.profile_mode, "trace")
            self.assertEqual(decision.requested_mode, "oracle")
            self.assertEqual(decision.normalized_mode, "oracle")
            self.assertIn("selected=nayru", decision.reason)

    def test_registry_aliases_resolve_to_canonical_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry_path = self._write_registry(
                tmp,
                """
[profile_defaults]
domain = "adaptive"
mode = "adaptive"

[[models]]
name = "oracle"
provider = "studio"
model_id = "gguf/zelda/main-1"
aliases = ["oracle-main-legacy", "switchhook", "oracle-tools"]
                """.strip(),
            )
            models, _routers = config_mod.load_registry(
                registry_path,
                rollout_path=self._write_empty_rollout(tmp),
            )

            self.assertEqual(resolve_model_name("switchhook", models), ("oracle", "switchhook"))
            self.assertEqual(resolve_model_name("oracle-main-legacy", models), ("oracle", "oracle-main-legacy"))
            self.assertNotIn("switchhook", models)

    def test_alias_mapped_oracle_models_stay_hidden_in_zelda_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry_path = self._write_registry(
                tmp,
                """
[profile_defaults]
domain = "adaptive"
mode = "adaptive"

[[models]]
name = "oracle"
provider = "studio"
model_id = "gguf/zelda/main-1"
aliases = ["legacy-oracle-view"]

[[models]]
name = "legacy-oracle-view"
provider = "studio"
model_id = "gguf/zelda/legacy-v1"
role = "legacy oracled view model"
                """.strip(),
            )
            models, _ = config_mod.load_registry(
                registry_path,
                rollout_path=self._write_empty_rollout(tmp),
            )

            visible = config_mod.list_zelda_models(models)
            visible_with_legacy = config_mod.list_zelda_models(models, include_legacy=True)

            self.assertIn("oracle", visible)
            self.assertIn("oracle", visible_with_legacy)
            self.assertNotIn("legacy-oracle-view", visible)
            self.assertIn("legacy-oracle-view", visible_with_legacy)
