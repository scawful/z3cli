"""Tests for orchestrator mode routing and prompt generation."""

from __future__ import annotations

import os
import unittest

from z3cli.core.config import ModelConfig
from z3cli.app.runtime import (
    ORCHESTRATOR_MODE, VALID_MODES, VISIBLE_MODES,
    build_orchestrator_prompt, default_orchestrator_model, resolve_targets,
)


def studio_model(name: str) -> ModelConfig:
    return ModelConfig(
        name=name, model_id=name, provider="studio",
        role=f"{name} specialist", tools_enabled=True, tool_profile=name,
    )


def anthropic_model(name: str, api_key_env: str = "") -> ModelConfig:
    return ModelConfig(
        name=name, model_id="claude-sonnet-4", provider="anthropic",
        role="cloud planner", tools_enabled=True,
        api_key_env=api_key_env,
        tags=["cloud", "orchestrator"] if name == "orchestrator" else [],
    )


class OrchestratorModeTests(unittest.TestCase):
    def test_orchestrator_in_visible_modes(self) -> None:
        self.assertIn(ORCHESTRATOR_MODE, VISIBLE_MODES)
        self.assertIn(ORCHESTRATOR_MODE, VALID_MODES)

    def test_default_orchestrator_prefers_tagged_model(self) -> None:
        models = {
            "nayru": studio_model("nayru"),
            "custom-planner": ModelConfig(
                name="custom-planner", model_id="foo", provider="studio",
                tags=["orchestrator"],
            ),
        }
        self.assertEqual(default_orchestrator_model(models), "custom-planner")

    def test_default_orchestrator_falls_back_to_candidate_list(self) -> None:
        # claude-sonnet is in DEFAULT_ORCHESTRATOR_CANDIDATES. Make sure
        # env is set so the key resolves.
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        try:
            models = {
                "nayru": studio_model("nayru"),
                "claude-sonnet": anthropic_model("claude-sonnet"),
            }
            self.assertEqual(default_orchestrator_model(models), "claude-sonnet")
        finally:
            del os.environ["ANTHROPIC_API_KEY"]

    def test_default_orchestrator_skips_cloud_without_key(self) -> None:
        # Cloud model without an API key should not be selected
        os.environ.pop("ANTHROPIC_API_KEY", None)
        models = {
            "claude-sonnet": anthropic_model("claude-sonnet"),
        }
        self.assertIsNone(default_orchestrator_model(models))

    def test_default_orchestrator_handles_empty_registry(self) -> None:
        self.assertIsNone(default_orchestrator_model({}))

    def test_build_orchestrator_prompt_includes_specialists(self) -> None:
        specialists = [
            {"name": "nayru", "provider": "studio", "role": "ASM expert", "tool_profile": "nayru"},
            {"name": "farore", "provider": "studio", "role": "debugger", "tool_profile": "farore"},
        ]
        prompt = build_orchestrator_prompt(specialists)
        self.assertIn("orchestrator mode", prompt)
        self.assertIn("spawn_subagent", prompt)
        self.assertIn("list_subagents", prompt)
        self.assertIn("nayru", prompt)
        self.assertIn("farore", prompt)
        self.assertIn("ASM expert", prompt)
        self.assertIn("[tools: nayru]", prompt)

    def test_build_orchestrator_prompt_handles_no_specialists(self) -> None:
        prompt = build_orchestrator_prompt([])
        self.assertIn("No specialists configured", prompt)


class OrchestratorRoutingTests(unittest.TestCase):
    def test_routes_to_explicit_orchestrator(self) -> None:
        models = {
            "nayru": studio_model("nayru"),
            "custom-planner": studio_model("custom-planner"),
        }
        targets = resolve_targets(
            models=models, routers={}, active_model="nayru",
            mode=ORCHESTRATOR_MODE, prompt="hello",
            broadcast_models=[], backend_name="studio",
            llamacpp_model="", temperature=0.3, max_tokens=1024,
            orchestrator_model="custom-planner",
        )
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].name, "custom-planner")

    def test_auto_selects_orchestrator_when_unspecified(self) -> None:
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        try:
            models = {
                "nayru": studio_model("nayru"),
                "claude-sonnet": anthropic_model("claude-sonnet"),
            }
            targets = resolve_targets(
                models=models, routers={}, active_model="nayru",
                mode=ORCHESTRATOR_MODE, prompt="hello",
                broadcast_models=[], backend_name="studio",
                llamacpp_model="", temperature=0.3, max_tokens=1024,
                orchestrator_model="",
            )
            self.assertEqual(len(targets), 1)
            self.assertEqual(targets[0].name, "claude-sonnet")
        finally:
            del os.environ["ANTHROPIC_API_KEY"]

    def test_falls_back_to_active_model_when_no_orchestrator(self) -> None:
        """Without a cloud orchestrator, uses the active model (still gets subagent tools)."""
        os.environ.pop("ANTHROPIC_API_KEY", None)
        models = {"nayru": studio_model("nayru")}
        targets = resolve_targets(
            models=models, routers={}, active_model="nayru",
            mode=ORCHESTRATOR_MODE, prompt="hello",
            broadcast_models=[], backend_name="studio",
            llamacpp_model="", temperature=0.3, max_tokens=1024,
            orchestrator_model="",
        )
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].name, "nayru")

    def test_ignores_unknown_orchestrator_and_falls_back(self) -> None:
        models = {"nayru": studio_model("nayru")}
        targets = resolve_targets(
            models=models, routers={}, active_model="nayru",
            mode=ORCHESTRATOR_MODE, prompt="hello",
            broadcast_models=[], backend_name="studio",
            llamacpp_model="", temperature=0.3, max_tokens=1024,
            orchestrator_model="does-not-exist",
        )
        # Falls back to active model since orchestrator is invalid
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].name, "nayru")


if __name__ == "__main__":
    unittest.main()
