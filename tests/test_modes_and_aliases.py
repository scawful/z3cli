import unittest
import os
from pathlib import Path

from rich.console import Console

from z3cli.app.repl import (
    AppState,
    _resolve_request_model_name,
    current_mode_help,
    get_engine,
    handle_command,
    render_model_table,
)
from z3cli.app.runtime import (
    DEFAULT_ACTIVE_MODEL,
    DEFAULT_ORACLE_MAIN_MODEL,
    choose_startup_model,
    ensure_model_available,
    normalize_mode,
    resolve_existing_model_name,
    resolve_model_name,
    resolve_targets,
)
from z3cli.app.shared_runtime import visible_model_infos
from z3cli.core.config import ModelConfig, RouterConfig, RouterRule, list_visible_zelda_models, list_zelda_models


def _model(
    name: str,
    *,
    role: str = "",
    tool_profile: str = "",
    tags: list[str] | None = None,
    system_prompt: str = "",
    allow_auto_load: bool = True,
) -> ModelConfig:
    return ModelConfig(
        name=name,
        model_id=name,
        role=role,
        tools_enabled=True,
        tool_profile=tool_profile,
        tags=list(tags or []),
        system_prompt=system_prompt,
        allow_auto_load=allow_auto_load,
    )


def _cloud_model(name: str, *, model_id: str = "claude-sonnet-4", api_key_env: str = "ANTHROPIC_API_KEY") -> ModelConfig:
    return ModelConfig(
        name=name,
        model_id=model_id,
        provider="anthropic",
        role="cloud planner",
        tools_enabled=True,
        api_key_env=api_key_env,
        tags=["orchestrator"],
    )


def _state() -> AppState:
    models = {
        "oracle": _model("oracle", role="planner"),
        "oracle-main-plan": _model("oracle-main-plan", role="plan"),
        "oracle-main-act": _model("oracle-main-act", role="act"),
        "oracle-tools": _model("oracle-tools", role="legacy act"),
        "switchhook-plan": _model("switchhook-plan", role="legacy plan"),
        "switchhook-act": _model("switchhook-act", role="legacy act"),
        "farore": _model("farore", tool_profile="farore"),
        "veran": _model("veran", tool_profile="veran"),
        "nayru": _model("nayru", tool_profile="nayru"),
        "majora": _model("majora", tool_profile="majora"),
        "hylia": _model("hylia", tool_profile="hylia"),
        "din": _model("din", tool_profile="din"),
    }
    return AppState(
        console=Console(record=True, width=120),
        host="127.0.0.1",
        port=1234,
        api_base="http://localhost:1234/v1",
        backend_name="studio",
        studio_api_base="http://localhost:1234/v1",
        llamacpp_api_base="http://localhost:8080/v1",
        llamacpp_model="oracle-fast",
        registry_path=Path("/tmp/registry.toml"),
        mcp_path=Path("/tmp/mcp.json"),
        models=models,
        routers={"oracle": RouterConfig(name="oracle", router_type="keyword", default="veran")},
        active_model="oracle",
        mode="manual",
        auto_load=True,
        auto_start_server=True,
        workspace=Path("/tmp"),
        rom_path=None,
        temperature=0.2,
        max_tokens=1024,
        broadcast_models=["farore", "majora", "veran"],
        tools_enabled=True,
    )


class ModeAndAliasTests(unittest.IsolatedAsyncioTestCase):
    def test_normalize_mode_maps_switchhook_alias(self) -> None:
        self.assertEqual(normalize_mode("switchhook"), ("oracle", "switchhook"))

    def test_current_mode_help_mentions_oracle(self) -> None:
        self.assertIn("oracle", current_mode_help())
        self.assertIn("orchestrator", current_mode_help())
        self.assertNotIn("switchhook (plan vs act)", current_mode_help())

    def test_list_zelda_models_hides_legacy_aliases(self) -> None:
        visible = list_zelda_models(_state().models)
        self.assertIn("oracle", visible)
        self.assertNotIn("oracle-main-plan", visible)
        self.assertNotIn("oracle-main-act", visible)
        self.assertNotIn("oracle-tools", visible)
        self.assertNotIn("switchhook-plan", visible)
        self.assertNotIn("switchhook-act", visible)

    def test_list_zelda_models_includes_qwen3_oracle_model_without_legacy_alias(self) -> None:
        models = _state().models
        models["qwen3-oracle-8b-v1"] = _model("qwen3-oracle-8b-v1", role="oracle main planner")

        visible = list_zelda_models(models)

        self.assertIn("qwen3-oracle-8b-v1", visible)

    def test_list_zelda_models_includes_tool_profile_models_without_name_allowlist(self) -> None:
        models = _state().models
        models["qwen3-debug-specialist"] = _model("qwen3-debug-specialist", tool_profile="farore")

        visible = list_zelda_models(models)

        self.assertIn("qwen3-debug-specialist", visible)

    def test_visible_zelda_models_hide_persona_and_avatar_entries(self) -> None:
        models = _state().models
        models["claudia"] = _model(
            "claudia",
            role="oracle witness persona",
            tags=["avatar", "daily"],
        )
        models["glados"] = _model(
            "glados",
            role="oracle code review persona",
            tags=["persona", "experimental"],
        )
        models["oracle-mythic"] = _model(
            "oracle-mythic",
            role="experimental mythic Zelda register",
            tags=["persona", "zelda"],
        )
        models["oracle-avatar-debugger"] = _model(
            "oracle-avatar-debugger",
            role="oracle debugger witness",
            tool_profile="farore",
            tags=["avatar", "oracle"],
        )

        visible = list_visible_zelda_models(models)

        self.assertIn("oracle", visible)
        self.assertNotIn("claudia", visible)
        self.assertNotIn("glados", visible)
        self.assertNotIn("oracle-mythic", visible)
        self.assertNotIn("oracle-avatar-debugger", visible)

    def test_list_zelda_models_hide_spawn_only_internal_entries(self) -> None:
        models = _state().models
        models["oracle-coder"] = _model(
            "oracle-coder",
            role="internal coding worker",
            tags=["oracle"],
        )
        models["oracle-coder"].visibility = "hidden"
        models["oracle-coder"].spawn_only = True
        models["oracle-coder"].spawnable_by = ["oracle", "oracle-fast"]

        visible = list_zelda_models(models)

        self.assertNotIn("oracle-coder", visible)

    def test_ensure_model_available_rejects_spawn_only_internal_model(self) -> None:
        model = _model("oracle-coder", role="internal coding worker", tags=["oracle"])
        model.visibility = "hidden"
        model.spawn_only = True

        with self.assertRaisesRegex(RuntimeError, "internal-only"):
            ensure_model_available(model)

    def test_visible_model_infos_use_filtered_operational_model_list(self) -> None:
        state = _state()
        state.models["scawfulbot"] = _model(
            "scawfulbot",
            role="oracle-adjacent direct coding partner",
            tags=["avatar", "primary"],
            system_prompt="Oracle continuity and Zelda workflow notes.",
        )

        names = [str(item["name"]) for item in visible_model_infos(state)]

        self.assertIn("oracle", names)
        self.assertNotIn("scawfulbot", names)

    def test_resolve_model_name_prefers_exact_registry_entries_over_legacy_alias_map(self) -> None:
        models = _state().models
        self.assertEqual(resolve_model_name("oracle-main-27b-v1", models), (DEFAULT_ORACLE_MAIN_MODEL, "oracle-main-27b-v1"))
        self.assertEqual(resolve_model_name("oracle-main-fast", models), ("oracle-fast", "oracle-main-fast"))
        self.assertEqual(resolve_model_name("oracle-tools", models), ("oracle-tools", None))
        self.assertEqual(resolve_model_name("switchhook-plan", models), ("switchhook-plan", None))
        self.assertEqual(resolve_model_name("switchhook", models), (DEFAULT_ORACLE_MAIN_MODEL, "switchhook"))

    def test_resolve_existing_model_name_rejects_unknown_entries(self) -> None:
        models = _state().models

        with self.assertRaisesRegex(RuntimeError, "Unknown model"):
            resolve_existing_model_name("bogus-model", models)

    def test_choose_startup_model_uses_safe_fallback_when_default_missing(self) -> None:
        models = {
            "farore": _model("farore", tool_profile="farore"),
            "veran": _model("veran", tool_profile="veran"),
        }

        selected, warning = choose_startup_model(DEFAULT_ACTIVE_MODEL, models, explicit=False)

        self.assertEqual(selected, "farore")
        self.assertIn("using 'farore' instead", warning or "")

    def test_choose_startup_model_prefers_fallback_zelda_model_over_avatar_when_oracle_is_rollout_gated(self) -> None:
        models = {
            "oracle": _model("oracle", role="planner"),
            "nayru": _model("nayru", tool_profile="nayru"),
            "farore": _model("farore", tool_profile="farore"),
            "veran": _model("veran", tool_profile="veran"),
            "avatar": _model("avatar", role="avatar alias", tags=["avatar", "daily"]),
        }
        models["oracle"].rollout_block_reason = "rollout-gated candidate"
        for name in ("nayru", "veran"):
            models[name].rollout_block_reason = "rollout-gated candidate"

        selected, warning = choose_startup_model(DEFAULT_ACTIVE_MODEL, models, explicit=False)

        self.assertEqual(selected, "farore")
        self.assertIn("using 'farore' instead", warning or "")

    def test_choose_startup_model_prefers_oracle_fast_when_default_oracle_skips_auto_load(self) -> None:
        models = {
            "oracle": _model("oracle", role="planner", allow_auto_load=False),
            "oracle-fast": _model("oracle-fast", role="fast"),
            "farore": _model("farore", tool_profile="farore"),
        }

        selected, warning = choose_startup_model(DEFAULT_ACTIVE_MODEL, models, explicit=False, auto_load=True)

        self.assertEqual(selected, "oracle-fast")
        self.assertIn("manual loads only", warning or "")

    def test_choose_startup_model_falls_back_to_unblocked_same_artifact_model(self) -> None:
        models = _state().models
        models["oracle-main-plan"].model_id = "switchhook-27b-v1"
        models["oracle-main-plan"].rollout_block_reason = "rollout-gated candidate"
        models["switchhook-plan"].model_id = "switchhook-27b-v1"

        selected, warning = choose_startup_model("oracle-main-plan", models, explicit=False)

        self.assertEqual(selected, "switchhook-plan")
        self.assertIn("using 'switchhook-plan' instead", warning or "")

    def test_choose_startup_model_keeps_explicit_rollout_gated_request(self) -> None:
        models = _state().models
        models["oracle-main-plan"].model_id = "switchhook-27b-v1"
        models["oracle-main-plan"].rollout_block_reason = "rollout-gated candidate"

        selected, warning = choose_startup_model("oracle-main-plan", models, explicit=True)

        self.assertEqual(selected, "oracle-main-plan")
        self.assertIsNone(warning)

    def test_oracle_main_mode_uses_oracle(self) -> None:
        models = _state().models
        routers: dict[str, RouterConfig] = {}

        action_target = resolve_targets(
            models=models,
            routers=routers,
            active_model="oracle-main-plan",
            mode="oracle-main",
            prompt="set a breakpoint and validate the hook",
            broadcast_models=["farore", "majora", "veran"],
            backend_name="studio",
            llamacpp_model="oracle-fast",
            temperature=0.2,
            max_tokens=1024,
        )
        plan_target = resolve_targets(
            models=models,
            routers=routers,
            active_model="oracle-main-plan",
            mode="oracle-main",
            prompt="explain the transition flow before proposing a fix",
            broadcast_models=["farore", "majora", "veran"],
            backend_name="studio",
            llamacpp_model="oracle-fast",
            temperature=0.2,
            max_tokens=1024,
        )

        self.assertEqual([item.name for item in action_target], ["oracle"])
        self.assertEqual([item.name for item in plan_target], ["oracle"])

    def test_oracle_mode_falls_back_to_safe_specialist(self) -> None:
        target = resolve_targets(
            models=_state().models,
            routers={},
            active_model="farore",
            mode="oracle",
            prompt="something broad with no special keywords",
            broadcast_models=["farore", "majora", "veran"],
            backend_name="studio",
            llamacpp_model="oracle-fast",
            temperature=0.2,
            max_tokens=1024,
        )

        self.assertEqual([item.name for item in target], ["oracle"])

    def test_oracle_mode_profiles_include_new_zelda_models_when_oracle_is_blocked(self) -> None:
        models = _state().models
        models["oracle"].rollout_block_reason = "rollout-gated candidate"
        models["oracle-main-plan"].rollout_block_reason = "rollout-gated candidate"
        qwen_model = _model(
            "qwen3-oracle-8b-v1",
            role="oracle analysis specialist",
        )
        qwen_model.domain = "adaptive"
        models["qwen3-oracle-8b-v1"] = qwen_model
        target = resolve_targets(
            models=models,
            routers={},
            active_model="oracle",
            mode="oracle",
            prompt="inspect the stack and registers",
            broadcast_models=["farore", "majora", "veran"],
            backend_name="studio",
            llamacpp_model="oracle-fast",
            temperature=0.2,
            max_tokens=1024,
        )

        self.assertEqual([item.name for item in target], ["qwen3-oracle-8b-v1"])

    def test_oracle_mode_skips_blocked_router_match(self) -> None:
        models = _state().models
        models["oracle-main-plan"].model_id = "qwen3-oracle-8b-v1"
        models["oracle-main-plan"].rollout_block_reason = "rollout-gated candidate"
        qwen_model = _model(
            "qwen3-oracle-8b-v1",
            role="oracle analysis specialist",
        )
        qwen_model.domain = "adaptive"
        qwen_model.mode = "adaptive"
        models["qwen3-oracle-8b-v1"] = qwen_model
        routers = {
            "oracle": RouterConfig(
                name="oracle",
                router_type="keyword",
                default="veran",
                rules=[RouterRule(keywords=["trace"], model="oracle-main-plan")],
            ),
        }

        target = resolve_targets(
            models=models,
            routers=routers,
            active_model="oracle",
            mode="oracle",
            prompt="trace this stack with the router keyword",
            broadcast_models=["farore", "majora", "veran"],
            backend_name="studio",
            llamacpp_model="oracle-fast",
            temperature=0.2,
            max_tokens=1024,
        )

        self.assertEqual([item.name for item in target], ["qwen3-oracle-8b-v1"])

    def test_oracle_route_with_no_router_keeps_fallback_when_candidates_blocked(self) -> None:
        models = _state().models
        models["oracle"].rollout_block_reason = "rollout-gated candidate"
        models["oracle-main-plan"].rollout_block_reason = "rollout-gated candidate"
        models["oracle-main-act"].rollout_block_reason = "rollout-gated candidate"
        models["oracle-tools"].rollout_block_reason = "rollout-gated candidate"
        models["switchhook-act"].rollout_block_reason = "rollout-gated candidate"
        models["switchhook-plan"].rollout_block_reason = "rollout-gated candidate"
        models["veran"].domain = "adaptive"
        models["veran"].mode = "adaptive"

        target = resolve_targets(
            models=models,
            routers={},
            active_model="oracle",
            mode="oracle",
            prompt="any request, no router configured",
            broadcast_models=["farore", "majora", "veran"],
            backend_name="studio",
            llamacpp_model="oracle-fast",
            temperature=0.2,
            max_tokens=1024,
        )

        self.assertEqual([item.name for item in target], ["veran"])

    def test_oracle_main_mode_uses_profile_fallback_when_main_aliases_blocked(self) -> None:
        models = _state().models
        blocked_names = [
            "oracle",
            "oracle-main-act",
            "oracle-main-plan",
            "oracle-tools",
            "switchhook-act",
            "switchhook-plan",
        ]
        for name in blocked_names:
            models[name].rollout_block_reason = "rollout-gated candidate"

        qwen_model = _model(
            "qwen3-oracle-8b-v1",
            role="oracle analysis specialist",
        )
        qwen_model.domain = "adaptive"
        qwen_model.mode = "adaptive"
        models["qwen3-oracle-8b-v1"] = qwen_model
        routers = {
            "oracle": RouterConfig(
                name="oracle",
                router_type="keyword",
                default="oracle",
                rules=[RouterRule(keywords=["trace"], model="oracle")],
            ),
        }

        target = resolve_targets(
            models=models,
            routers=routers,
            active_model="oracle-main-plan",
            mode="oracle-main",
            prompt="trace this stack and inspect timing",
            broadcast_models=["farore", "majora", "veran"],
            backend_name="studio",
            llamacpp_model="oracle-fast",
            temperature=0.2,
            max_tokens=1024,
        )

        self.assertEqual([item.name for item in target], ["qwen3-oracle-8b-v1"])

    async def test_model_command_selects_exact_legacy_named_entry_when_present(self) -> None:
        state = _state()

        await handle_command(state, "/model oracle-tools")

        self.assertEqual(state.active_model, "oracle-tools")
        self.assertNotIn("legacy alias", state.console.export_text().lower())

    async def test_model_command_rejects_rollout_blocked_alias(self) -> None:
        state = _state()
        state.models["oracle-main-plan"].model_id = "qwen3-oracle-8b-v1"
        state.models["oracle-main-plan"].rollout_block_reason = "rollout-gated candidate"

        with self.assertRaisesRegex(RuntimeError, "rollout-gated"):
            await handle_command(state, "/model oracle-main-plan")

    async def test_specialist_command_switches_to_manual_specialist(self) -> None:
        state = _state()
        state.mode = "oracle-main"

        await handle_command(state, "/specialist farore")

        self.assertEqual(state.active_model, "farore")
        self.assertEqual(state.mode, "manual")

    async def test_mode_command_normalizes_legacy_alias(self) -> None:
        state = _state()

        await handle_command(state, "/mode switchhook")

        self.assertEqual(state.mode, "oracle")
        self.assertIn("legacy mode 'switchhook' now resolves to 'oracle'.", state.console.export_text().lower())

    async def test_orchestrator_command_sets_cloud_planner(self) -> None:
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        try:
            state = _state()
            state.models["claude-sonnet"] = _cloud_model("claude-sonnet")

            await handle_command(state, "/orchestrator claude-sonnet")

            self.assertEqual(state.orchestrator_model, "claude-sonnet")
            self.assertIn("resolved planner: claude-sonnet", state.console.export_text().lower())
        finally:
            del os.environ["ANTHROPIC_API_KEY"]

    def test_cloud_models_show_up_in_render_model_table(self) -> None:
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        try:
            state = _state()
            state.models["claude-sonnet"] = _cloud_model("claude-sonnet")

            render_model_table(state)

            output = state.console.export_text().lower()
            self.assertIn("claude-so", output)
            self.assertIn("anthropic", output)
        finally:
            del os.environ["ANTHROPIC_API_KEY"]

    def test_render_model_table_mentions_oracle_pro_manual_alias(self) -> None:
        state = _state()

        render_model_table(state)

        output = state.console.export_text().lower()
        self.assertIn("oracle-pro", output)
        self.assertIn("manual-only heavy model", output)

    def test_get_engine_uses_cloud_provider_for_cloud_models(self) -> None:
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        try:
            state = _state()
            state.models["claude-sonnet"] = _cloud_model("claude-sonnet")

            engine = get_engine(state, "claude-sonnet")

            self.assertEqual(engine.provider.name, "anthropic")
        finally:
            del os.environ["ANTHROPIC_API_KEY"]

    def test_resolve_request_model_name_uses_model_id_for_cloud_models(self) -> None:
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        try:
            state = _state()
            target = _cloud_model("claude-sonnet", model_id="claude-sonnet-4-20250514")
            state.models["claude-sonnet"] = target

            self.assertEqual(
                _resolve_request_model_name(state, target),
                "claude-sonnet-4-20250514",
            )
        finally:
            del os.environ["ANTHROPIC_API_KEY"]


if __name__ == "__main__":
    unittest.main()
