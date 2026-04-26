import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.serve import (
    ServeState,
    _await_startup_tool_bridge,
    _run_startup_tool_bridge_warmup,
    _describe_permission_reason,
    _forward_subagent_event,
    build_ready_params,
    handle_chat,
    handle_command,
    handle_inventory_rpc,
    handle_route_rpc,
    init_state,
    run_budgeted_chat_request,
    serve_main,
)
from app.shared_runtime import model_catalog_infos
from core.config import LlamaCppNodeConfig, ModelConfig, StudioNodeConfig
from core.engine import CompactionEvent, DoneEvent, TextEvent, ThinkingEvent, ToolCallEvent, ToolResultEvent
from core.subagent import (
    SubagentContext,
    SubagentResult,
    SubagentRunner,
    SubagentStartEvent,
    _current_subagent,
)
from core.session import Session
from app.write_review import prepare_write_context
from protocol.z3lsp_bridge import Z3LspBridge


class FakeServeLoop:
    async def connect_read_pipe(self, protocol_factory, pipe):  # type: ignore[no-untyped-def]
        del protocol_factory, pipe
        return None, None


def _rpc_lines(*messages: dict) -> bytes:
    body = "".join(json.dumps(message) + "\n" for message in messages)
    return body.encode("utf-8")


class FakeBackend:
    def resolve_request_model(
        self,
        target: ModelConfig,
        auto_load: bool = True,
        *,
        manual_load: bool = False,
    ) -> str:
        del auto_load, manual_load
        return target.model_id


class CancelAwareEngine:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = False
        self.chat_calls = 0

    def cancel(self) -> None:
        self.cancelled = True
        self.release.set()

    async def chat(self, **kwargs):  # type: ignore[no-untyped-def]
        self.chat_calls += 1
        self.started.set()
        yield TextEvent("partial output")
        await self.release.wait()
        yield DoneEvent()


class CompactingEngine:
    def __init__(self) -> None:
        self.compactor = object()
        self.calls = 0

    async def compact_now(self, force: bool = False) -> CompactionEvent | None:
        self.calls += 1
        return CompactionEvent(
            summary="summary",
            replaced_count=5,
            tokens_before=2048,
            tokens_after=512,
        )


class TraceToolEngine:
    def cancel(self) -> None:
        return None

    async def chat(self, **kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        yield TextEvent("Tracing.")
        yield ToolCallEvent("echo", '{"text":"hi"}', "mock", "call-9")
        yield ToolResultEvent("echo", "ok", "mock", "call-9")
        yield DoneEvent(prompt_tokens=2, completion_tokens=2)


class ThinkingEngine:
    def cancel(self) -> None:
        return None

    async def chat(self, **kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        yield ThinkingEvent("Inspecting the room header.")
        yield TextEvent("Patched the room script.")
        yield DoneEvent(prompt_tokens=1, completion_tokens=1)


class SanitizingToolEngine:
    def cancel(self) -> None:
        return None

    async def chat(self, **kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        yield TextEvent("The user is wrong about the file contents.\n\n")
        yield ToolCallEvent("inspect_room", '{"room":"0x45"}', "mock", "call-45")
        yield ToolResultEvent("inspect_room", "## Room 0x45\nSprites: 3", "mock", "call-45")
        yield TextEvent("Okay, I checked the room.\n\nThe room has 3 sprites.")
        yield DoneEvent(prompt_tokens=3, completion_tokens=4)


class BlockingToolBridge:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    def get_openai_tools(self) -> list[dict]:
        return []

    async def call_tool(self, name: str, arguments: dict) -> str:
        del name, arguments
        self.started.set()
        await self.release.wait()
        return "ok"

    def get_tool_server(self, tool_name: str) -> str:
        del tool_name
        return "mock"

    @property
    def tool_count(self) -> int:
        return 1

    @property
    def server_names(self) -> list[str]:
        return ["mock"]

    @property
    def server_tool_counts(self) -> dict[str, int]:
        return {"mock": 1}

    async def close(self) -> None:
        return None


class FakeZ3LspBridge(Z3LspBridge):
    def __init__(self, prefix: str = "serve pack") -> None:
        self.prefix = prefix

    async def build_context_pack(  # type: ignore[override]
        self,
        file_path: str,
        *,
        query: str = "",
        symbol_queries: list[str] | None = None,
        max_chars: int = 1600,
        diagnostic_limit: int | None = None,
        symbol_limit: int | None = None,
        symbol_detail_limit: int = 0,
        reference_limit: int = 0,
        include_clean_diagnostics: bool = True,
        include_diagnostic_snippets: bool = False,
        include_symbol_hover: bool = False,
    ) -> str:
        del (
            query,
            symbol_queries,
            diagnostic_limit,
            symbol_limit,
            symbol_detail_limit,
            reference_limit,
            include_clean_diagnostics,
            include_diagnostic_snippets,
            include_symbol_hover,
        )
        pack = f"{self.prefix} for {Path(file_path).name}"
        return pack[:max_chars]


class ServeFlowTests(unittest.IsolatedAsyncioTestCase):
    def test_build_ready_params_uses_configured_z3ui_bench(self) -> None:
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        try:
            state = ServeState()
            state.models = {
                "veran": ModelConfig(name="veran", model_id="veran", role="editor", tool_profile="veran"),
                "oracle-fast": ModelConfig(name="oracle-fast", model_id="oracle-fast", role="fast", tools_enabled=True),
                "claude-sonnet": ModelConfig(
                    name="claude-sonnet",
                    model_id="claude-sonnet-4",
                    provider="anthropic",
                    role="cloud planner",
                    tools_enabled=True,
                    api_key_env="ANTHROPIC_API_KEY",
                ),
                "navi": ModelConfig(name="navi", model_id="navi", role="autocomplete/debug", tool_profile="farore"),
                "farore": ModelConfig(name="farore", model_id="farore", role="legacy debugger", tool_profile="farore"),
                "hylia": ModelConfig(name="hylia", model_id="hylia", role="historian", tool_profile="hylia"),
                "majora": ModelConfig(name="majora", model_id="majora", role="context", tool_profile="majora"),
                "nayru": ModelConfig(name="nayru", model_id="nayru", role="analysis", tool_profile="nayru"),
                "din": ModelConfig(name="din", model_id="din", role="author", tool_profile="din"),
                "oracle": ModelConfig(name="oracle", model_id="oracle", role="planner", tools_enabled=True),
                "qwen3-oracle-8b-v1": ModelConfig(
                    name="qwen3-oracle-8b-v1",
                    model_id="qwen3-oracle-8b-v1",
                    role="experimental oracle candidate",
                    tags=["oracle"],
                ),
                "avatar-debugger": ModelConfig(
                    name="avatar-debugger",
                    model_id="avatar-debugger",
                    role="oracle debugger witness",
                    tool_profile="farore",
                    tags=["avatar", "oracle"],
                ),
            }

            with patch("app.shared_runtime.available_models", return_value=[]), patch(
                "app.shared_runtime.loaded_models",
                return_value=[],
            ):
                params = build_ready_params(state)
            names = [str(item["name"]) for item in params["models"]]

            self.assertEqual(
                names,
                ["oracle-fast", "oracle", "din", "nayru", "navi"],
            )
            self.assertNotIn("avatar-debugger", names)
            self.assertNotIn("claude-sonnet", names)
            self.assertNotIn("qwen3-oracle-8b-v1", names)
        finally:
            del os.environ["ANTHROPIC_API_KEY"]

    def test_build_ready_params_hides_rollout_gated_z3ui_models(self) -> None:
        state = ServeState()
        state.models = {
            "oracle": ModelConfig(name="oracle", model_id="oracle", role="planner", tools_enabled=True),
            "oracle-fast": ModelConfig(
                name="oracle-fast",
                model_id="oracle-fast",
                role="fast",
                tools_enabled=True,
                rollout_block_reason="oracle-fast is still gated",
            ),
            "nayru": ModelConfig(
                name="nayru",
                model_id="nayru",
                role="analysis",
                tool_profile="nayru",
                rollout_block_reason="nayru is still gated",
            ),
            "avatar": ModelConfig(
                name="avatar",
                model_id="avatar",
                role="avatar alias",
            ),
        }

        with patch("app.shared_runtime.available_models", return_value=[]), patch(
            "app.shared_runtime.loaded_models",
            return_value=[],
        ):
            params = build_ready_params(state)

        self.assertEqual([str(item["name"]) for item in params["models"]], ["oracle"])

    def test_build_ready_params_hides_spawn_only_internal_worker(self) -> None:
        state = ServeState()
        state.models = {
            "oracle": ModelConfig(name="oracle", model_id="oracle", role="planner", tools_enabled=True),
            "oracle-fast": ModelConfig(name="oracle-fast", model_id="oracle-fast", role="fast", tools_enabled=True),
            "oracle-pro": ModelConfig(name="oracle-pro", model_id="oracle-pro", role="pro", tools_enabled=True),
            "oracle-coder": ModelConfig(
                name="oracle-coder",
                model_id="qwen25-oracle-coder-7b-v1",
                role="internal coding worker",
                tags=["oracle", "z3ui"],
                visibility="hidden",
                spawn_only=True,
                spawnable_by=["oracle", "oracle-fast"],
                tools_enabled=True,
            ),
        }

        with patch("app.shared_runtime.available_models", return_value=[]), patch(
            "app.shared_runtime.loaded_models",
            return_value=[],
        ):
            params = build_ready_params(state)

        self.assertEqual([str(item["name"]) for item in params["models"]], ["oracle-fast", "oracle", "oracle-pro"])

    def test_build_ready_params_hides_unavailable_local_models(self) -> None:
        state = ServeState()
        state.models = {
            "oracle": ModelConfig(name="oracle", model_id="oracle", role="planner", tools_enabled=True),
            "oracle-fast": ModelConfig(name="oracle-fast", model_id="oracle-fast", role="fast", tools_enabled=True),
            "oracle-pro": ModelConfig(name="oracle-pro", model_id="oracle-pro", role="pro", tools_enabled=True),
            "oracle-coder-preview": ModelConfig(
                name="oracle-coder-preview",
                model_id="qwen25-oracle-coder-14b-v1",
                role="future coder preview",
                tags=["oracle", "z3ui"],
                hide_if_unavailable=True,
                tools_enabled=True,
            ),
        }

        with patch("app.shared_runtime.available_models", return_value=[
            {"id": "oracle", "path": "oracle"},
            {"id": "oracle-fast", "path": "oracle-fast"},
            {"id": "oracle-pro", "path": "oracle-pro"},
        ]), patch("app.shared_runtime.loaded_models", return_value=[]):
            params = build_ready_params(state)

        self.assertEqual([str(item["name"]) for item in params["models"]], ["oracle-fast", "oracle", "oracle-pro"])

    def test_build_ready_params_keeps_active_specialist_visible_in_primary_picker(self) -> None:
        state = ServeState()
        state.active_model = "nayru"
        state.models = {
            "oracle": ModelConfig(name="oracle", model_id="oracle", role="planner", tools_enabled=True),
            "oracle-fast": ModelConfig(name="oracle-fast", model_id="oracle-fast", role="fast", tools_enabled=True),
            "nayru": ModelConfig(name="nayru", model_id="nayru", role="analysis", tool_profile="nayru"),
        }

        with patch("app.shared_runtime.available_models", return_value=[]), patch(
            "app.shared_runtime.loaded_models",
            return_value=[],
        ):
            params = build_ready_params(state)

        self.assertEqual([str(item["name"]) for item in params["models"]], ["oracle-fast", "oracle", "nayru"])

    def test_build_ready_params_surfaces_hidden_14b_slot_from_quantized_available_key(self) -> None:
        state = ServeState()
        state.models = {
            "oracle": ModelConfig(name="oracle", model_id="oracle", role="planner", tools_enabled=True),
            "qwen3-oracle-14b": ModelConfig(
                name="qwen3-oracle-14b",
                model_id="qwen3-oracle-14b-v7",
                role="reserved local oracle main",
                tags=["oracle"],
                aliases=["oracle-main-14b", "oracle-main-14b-v7", "oracle-14b"],
                hide_if_unavailable=True,
                tools_enabled=True,
            ),
        }

        with patch("app.shared_runtime.available_models", return_value=[
            {"id": "oracle", "path": "oracle"},
            {
                "id": "gguf/zelda/qwen3-oracle-14b-v7-q4km.gguf",
                "path": "gguf/zelda/qwen3-oracle-14b-v7-q4km.gguf",
            },
        ]), patch("app.shared_runtime.loaded_models", return_value=[]):
            params = build_ready_params(state)

        self.assertEqual(
            [str(item["name"]) for item in params["model_catalog"]],
            ["oracle"],
        )
        self.assertEqual(
            [str(item["name"]) for item in model_catalog_infos(state, include_advanced=True)],
            ["oracle", "qwen3-oracle-14b"],
        )
        self.assertEqual([str(item["name"]) for item in params["models"]], ["oracle"])

    def test_build_ready_params_hides_internal_spawn_only_entries_from_catalog(self) -> None:
        state = ServeState()
        state.models = {
            "oracle": ModelConfig(name="oracle", model_id="oracle", role="planner", tools_enabled=True),
            "oracle-pro": ModelConfig(
                name="oracle-pro",
                model_id="gguf/zelda/qwen3-oracle-14b-v7-q4km.gguf",
                role="14b oracle pro",
                tags=["oracle"],
                hide_if_unavailable=True,
                tools_enabled=True,
            ),
            "oracle-coder": ModelConfig(
                name="oracle-coder",
                model_id="qwen25-oracle-coder-7b-v1",
                role="internal coder",
                tags=["oracle"],
                visibility="hidden",
                spawn_only=True,
                spawnable_by=["oracle"],
                hide_if_unavailable=True,
                tools_enabled=True,
            ),
        }

        with patch("app.shared_runtime.available_models", return_value=[
            {"id": "oracle", "path": "oracle"},
            {"id": "gguf/zelda/qwen3-oracle-14b-v7-q4km.gguf", "path": "gguf/zelda/qwen3-oracle-14b-v7-q4km.gguf"},
            {"id": "qwen25-oracle-coder-7b-v1", "path": "qwen25-oracle-coder-7b-v1"},
        ]), patch("app.shared_runtime.loaded_models", return_value=[]):
            params = build_ready_params(state)
        catalog = params.get("model_catalog", [])

        self.assertEqual([str(item["name"]) for item in params["models"]], ["oracle", "oracle-pro"])
        self.assertEqual(
            [str(item["name"]) for item in catalog],
            ["oracle", "oracle-pro"],
        )
        oracle_pro_entry = next(item for item in catalog if str(item["name"]) == "oracle-pro")
        self.assertEqual(oracle_pro_entry.get("selectable"), True)

    def test_build_ready_params_includes_tagged_local_z3ui_models(self) -> None:
        state = ServeState()
        state.models = {
            "oracle": ModelConfig(name="oracle", model_id="oracle", role="planner", tools_enabled=True),
            "qwen3-local-8b": ModelConfig(
                name="qwen3-local-8b",
                model_id="qwen/qwen3-8b",
                role="general local qwen3 model",
                tags=["oracle", "z3ui"],
                tools_enabled=True,
            ),
        }

        with patch("app.shared_runtime.available_models", return_value=[]), patch(
            "app.shared_runtime.loaded_models",
            return_value=[],
        ):
            params = build_ready_params(state)

        self.assertEqual(
            [str(item["name"]) for item in params["models"]],
            ["oracle", "qwen3-local-8b"],
        )

    def test_build_ready_params_includes_loaded_model_memory_details(self) -> None:
        state = ServeState()
        state.models = {
            "nayru": ModelConfig(name="nayru", model_id="gguf/zelda/nayru-9b-q8_0.gguf", role="analysis"),
        }

        with patch("app.serve.primary_model_infos", return_value=[{
            "name": "nayru",
            "model_id": "gguf/zelda/nayru-9b-q8_0.gguf",
            "role": "analysis",
            "description": "9B explainer",
            "loaded": True,
            "available": True,
            "tools_enabled": True,
            "provider": "studio",
            "loaded_identifier": "nayru",
            "size_bytes": 9_527_501_152,
            "status": "idle",
            "parallel": 4,
            "context_length": 262144,
            "max_context_length": 262144,
            "architecture": "qwen35",
            "quantization": "Q8_0",
            "queued": 0,
            "estimated_gpu_bytes": int(9.95 * 1024 ** 3),
            "estimated_total_bytes": int(9.95 * 1024 ** 3),
        }]), patch("app.serve.loaded_model_runtime_infos", return_value=[{
            "identifier": "nayru",
            "model_key": "gguf/zelda/nayru-9b-q8_0.gguf",
            "display_name": "Nayru 9B",
            "size_bytes": 9_527_501_152,
            "status": "idle",
            "parallel": 4,
            "context_length": 262144,
            "max_context_length": 262144,
            "architecture": "qwen35",
            "quantization": "Q8_0",
            "estimated_gpu_bytes": int(9.95 * 1024 ** 3),
            "estimated_total_bytes": int(9.95 * 1024 ** 3),
        }]):
            params = build_ready_params(state)

        self.assertEqual(params.get("loaded_model_count"), 1)
        self.assertEqual(params.get("loaded_model_memory_bytes"), 9_527_501_152)
        self.assertEqual(params["models"][0].get("size_bytes"), 9_527_501_152)
        self.assertEqual(params["models"][0].get("estimated_gpu_bytes"), int(9.95 * 1024 ** 3))
        self.assertEqual((params.get("loaded_models") or [])[0].get("identifier"), "nayru")

    def test_build_ready_params_compacts_collision_warning_bursts(self) -> None:
        state = ServeState()
        state.models = {
            "oracle": ModelConfig(name="oracle", model_id="oracle", role="planner", tools_enabled=True),
        }
        state.startup_warnings = ["No veran GGUF is currently installed in LM Studio."]
        state.bridge_errors = [
            "tool collision: tool name 'rom_diff' collided between 'yaze-editor' (kept) and 'z3ed' (renamed to 'z3ed_rom_diff')",
            "tool collision: tool name 'rom_info' collided between 'yaze-editor' (kept) and 'z3ed' (renamed to 'z3ed_rom_info')",
            "tool collision: tool name 'rom_read' collided between 'yaze-editor' (kept) and 'z3ed' (renamed to 'z3ed_rom_read')",
        ]

        params = build_ready_params(state)
        warnings = [str(item) for item in params["warnings"]]

        self.assertIn("No veran GGUF is currently installed in LM Studio.", warnings)
        self.assertIn(
            "3 tool collisions between 'yaze-editor' and 'z3ed'; keeping 'yaze-editor' names (e.g. rom_diff, rom_info, rom_read)",
            warnings,
        )
        self.assertFalse(any(warning.startswith("tool collision:") for warning in warnings))

    def test_build_ready_params_includes_tool_warmup_warning(self) -> None:
        state = ServeState()
        state.models = {
            "oracle": ModelConfig(name="oracle", model_id="oracle", role="planner", tools_enabled=True),
        }
        state.startup_tool_bridge_warming = True

        params = build_ready_params(state)
        warnings = [str(item) for item in params["warnings"]]

        self.assertIn(
            "Tool bridge warming up; tools and server list will populate shortly.",
            warnings,
        )

    async def test_init_state_honors_no_auto_start_server(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry_path = root / "chat_registry.toml"
            registry_path.write_text(
                """
[[models]]
name = "oracle-main-plan"
model_id = "gguf/zelda/qwen3-oracle-14b-v7-q4km.gguf"
provider = "studio"
role = "planner"
""".strip(),
                encoding="utf-8",
            )

            with patch("app.serve.ensure_server") as ensure, patch(
                "core.session.DEFAULT_SESSION_DIR",
                root / "sessions",
            ):
                state = await init_state([
                    "--registry", str(registry_path),
                    "--mcp-config", str(root / "mcp.json"),
                    "--no-tools",
                    "--no-auto-start-server",
                ])

            self.assertTrue(state.auto_start_server is False)
            ensure.assert_not_called()
            state.session.close()

    async def test_run_startup_tool_bridge_warmup_clears_flag_and_notifies_ready(self) -> None:
        state = ServeState()
        state.models = {
            "oracle": ModelConfig(name="oracle", model_id="oracle", role="planner", tools_enabled=True),
        }
        state.startup_tool_bridge_warming = True
        notifications: list[tuple[str, dict | None]] = []

        with patch("app.serve.refresh_tool_bridge", new=AsyncMock()), patch(
            "app.serve._notify",
            side_effect=lambda method, params=None: notifications.append((method, params)),
        ):
            await _run_startup_tool_bridge_warmup(state)

        self.assertFalse(state.startup_tool_bridge_warming)
        self.assertIsNone(state.startup_tool_bridge_task)
        self.assertTrue(notifications)
        self.assertEqual(notifications[-1][0], "ready")

    async def test_await_startup_tool_bridge_waits_for_background_task(self) -> None:
        state = ServeState()

        async def delayed() -> None:
            await asyncio.sleep(0.01)

        state.startup_tool_bridge_task = asyncio.create_task(delayed())
        await _await_startup_tool_bridge(state)
        self.assertTrue(state.startup_tool_bridge_task.done())

    async def test_init_state_defaults_to_oracle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry_path = root / "chat_registry.toml"
            registry_path.write_text(
                """
[[models]]
name = "oracle"
model_id = "oracle"
provider = "studio"
role = "planner"
""".strip(),
                encoding="utf-8",
            )

            with patch("app.serve.ensure_server"), patch(
                "core.session.DEFAULT_SESSION_DIR",
                root / "sessions",
            ):
                state = await init_state([
                    "--registry", str(registry_path),
                    "--mcp-config", str(root / "mcp.json"),
                    "--no-tools",
                ])

            self.assertEqual(state.active_model, "oracle")
            state.session.close()

    async def test_init_state_coerces_explicit_hidden_model_to_oracle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry_path = root / "chat_registry.toml"
            registry_path.write_text(
                """
[[models]]
name = "oracle"
model_id = "oracle"
provider = "studio"
role = "planner"

[[models]]
name = "avatar"
model_id = "avatar"
provider = "studio"
role = "avatar alias"
""".strip(),
                encoding="utf-8",
            )

            with patch("app.shared_runtime.available_models", return_value=[]), patch(
                "app.shared_runtime.loaded_models",
                return_value=[],
            ), patch("app.serve.ensure_server"), patch(
                "core.session.DEFAULT_SESSION_DIR",
                root / "sessions",
            ):
                state = await init_state([
                    "--registry", str(registry_path),
                    "--mcp-config", str(root / "mcp.json"),
                    "--no-tools",
                    "--model", "avatar",
                ])

            self.assertEqual(state.active_model, "oracle")
            self.assertTrue(any("does not expose model 'avatar'" in warning for warning in state.startup_warnings))
            state.session.close()

    async def test_init_state_coerces_explicit_rollout_gated_z3ui_model_to_oracle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry_path = root / "chat_registry.toml"
            registry_path.write_text(
                """
[[models]]
name = "oracle"
model_id = "oracle"
provider = "studio"
role = "planner"

[[models]]
name = "nayru"
model_id = "nayru"
provider = "studio"
role = "analysis"
rollout_block_reason = "nayru is still gated"
""".strip(),
                encoding="utf-8",
            )

            with patch("app.shared_runtime.available_models", return_value=[]), patch(
                "app.shared_runtime.loaded_models",
                return_value=[],
            ), patch("app.serve.ensure_server"), patch(
                "core.session.DEFAULT_SESSION_DIR",
                root / "sessions",
            ):
                state = await init_state([
                    "--registry", str(registry_path),
                    "--mcp-config", str(root / "mcp.json"),
                    "--no-tools",
                    "--model", "nayru",
                ])

            self.assertEqual(state.active_model, "oracle")
            self.assertTrue(any("rollout-gated in z3ui" in warning for warning in state.startup_warnings))
            state.session.close()

    async def test_init_state_honors_no_auto_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry_path = root / "chat_registry.toml"
            registry_path.write_text(
                """
[[models]]
name = "oracle-main-plan"
model_id = "gguf/zelda/qwen3-oracle-14b-v7-q4km.gguf"
provider = "studio"
role = "planner"
""".strip(),
                encoding="utf-8",
            )

            with patch("app.serve.ensure_server"), patch(
                "core.session.DEFAULT_SESSION_DIR",
                root / "sessions",
            ):
                state = await init_state([
                    "--registry", str(registry_path),
                    "--mcp-config", str(root / "mcp.json"),
                    "--no-tools",
                    "--no-auto-load",
                ])

            self.assertFalse(state.auto_load)
            state.session.close()

    async def test_handle_command_model_unknown_reports_error(self) -> None:
        state = ServeState()
        state.models = {
            "nayru": ModelConfig(name="nayru", model_id="nayru", role="analysis"),
        }

        responses: list[tuple[int, object, str | None]] = []
        with patch("app.serve._respond", side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error))):
            await handle_command(state, 101, {"cmd": "/model", "args": ["ghost"]})

        self.assertEqual(responses[-1], (101, None, "Unknown model: ghost"))
        self.assertEqual(state.model_lookup_failures, 1)
        self.assertEqual(state.model_alias_resolutions, 0)

    async def test_handle_command_model_rejects_hidden_avatar_entries(self) -> None:
        state = ServeState()
        state.active_model = "oracle"
        state.models = {
            "oracle": ModelConfig(name="oracle", model_id="oracle", role="planner"),
            "avatar": ModelConfig(name="avatar", model_id="avatar", role="avatar alias"),
        }

        responses: list[tuple[int, object, str | None]] = []
        with patch("app.serve._respond", side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error))):
            await handle_command(state, 102, {"cmd": "/model", "args": ["avatar"]})

        self.assertEqual(
            responses[-1],
            (102, None, "Model 'avatar' is not available in z3ui. Choose one of: oracle"),
        )
        self.assertEqual(state.active_model, "oracle")

    async def test_handle_command_model_rejects_unavailable_local_entries(self) -> None:
        state = ServeState()
        state.active_model = "oracle"
        state.models = {
            "oracle": ModelConfig(name="oracle", model_id="oracle", role="planner"),
            "oracle-coder-preview": ModelConfig(
                name="oracle-coder-preview",
                model_id="qwen25-oracle-coder-14b-v1",
                role="future coder preview",
                tags=["oracle", "z3ui"],
                hide_if_unavailable=True,
            ),
        }

        responses: list[tuple[int, object, str | None]] = []
        with patch("app.shared_runtime.available_models", return_value=[
            {"id": "oracle", "path": "oracle"},
        ]), patch("app.shared_runtime.loaded_models", return_value=[]), patch(
            "app.serve._respond",
            side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
        ):
            await handle_command(state, 103, {"cmd": "/model", "args": ["oracle-coder-preview"]})

        self.assertEqual(
            responses[-1],
            (103, None, "Model 'oracle-coder-preview' is not available in z3ui. Choose one of: oracle"),
        )
        self.assertEqual(state.active_model, "oracle")

    async def test_handle_command_model_accepts_oracle_pro_when_available(self) -> None:
        state = ServeState()
        state.active_model = "oracle"
        state.models = {
            "oracle": ModelConfig(name="oracle", model_id="oracle", role="planner"),
            "oracle-fast": ModelConfig(
                name="oracle-fast",
                model_id="gguf/zelda/qwen3-oracle-8b-v1-corrective2-q4km.gguf",
                role="fast oracle",
            ),
            "oracle-pro": ModelConfig(
                name="oracle-pro",
                model_id="gguf/zelda/qwen3-oracle-14b-v7-q4km.gguf",
                role="14b oracle pro",
            ),
        }

        responses: list[tuple[int, object, str | None]] = []
        with patch("app.shared_runtime.available_models", return_value=[
            {"id": "gguf/zelda/qwen3-oracle-8b-v1-corrective2-q4km.gguf", "path": "gguf/zelda/qwen3-oracle-8b-v1-corrective2-q4km.gguf"},
            {"id": "gguf/zelda/qwen3-oracle-14b-v7-q4km.gguf", "path": "gguf/zelda/qwen3-oracle-14b-v7-q4km.gguf"},
        ]), patch("app.shared_runtime.loaded_models", return_value=[]), patch(
            "app.serve.ensure_model_available"
        ), patch(
            "app.serve._refresh_focus_context"
        ), patch(
            "app.serve._persist_state"
        ), patch(
            "app.serve._notify"
        ), patch(
            "app.serve._respond",
            side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
        ):
            await handle_command(state, 104, {"cmd": "/model", "args": ["oracle-pro"]})

        self.assertEqual(responses[-1], (104, {"active_model": "oracle-pro"}, None))
        self.assertEqual(state.active_model, "oracle-pro")

    async def test_handle_command_model_accepts_visible_advanced_model_by_name(self) -> None:
        state = ServeState()
        state.active_model = "oracle"
        navi_model_id = "gguf/zelda/farore-9b-q4km.gguf"
        state.models = {
            "oracle": ModelConfig(name="oracle", model_id="oracle", role="planner"),
            "navi-q4km": ModelConfig(
                name="navi-q4km",
                model_id=navi_model_id,
                role="lighter navi quant",
                tags=["oracle", "local", "qwen35"],
                tool_profile="farore",
                visibility="advanced",
                hide_if_unavailable=True,
            ),
        }

        responses: list[tuple[int, object, str | None]] = []
        with patch("app.shared_runtime.available_models", return_value=[
            {"id": "oracle", "path": "oracle"},
            {"id": navi_model_id, "path": navi_model_id},
        ]), patch("app.shared_runtime.loaded_models", return_value=[]), patch(
            "app.serve._refresh_focus_context"
        ), patch(
            "app.serve._persist_state"
        ), patch(
            "app.serve._schedule_ready_notification"
        ), patch(
            "app.serve._respond",
            side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
        ):
            default_names = [str(item["name"]) for item in model_catalog_infos(state)]
            advanced_names = [str(item["name"]) for item in model_catalog_infos(state, include_advanced=True)]
            await handle_command(state, 105, {"cmd": "/model", "args": ["navi-q4km"]})

        self.assertNotIn("navi-q4km", default_names)
        self.assertIn("navi-q4km", advanced_names)
        self.assertEqual(responses[-1], (105, {"active_model": "navi-q4km"}, None))
        self.assertEqual(state.active_model, "navi-q4km")

    async def test_handle_command_orchestrator_resolves_legacy_alias(self) -> None:
        state = ServeState()
        state.models = {
            "oracle": ModelConfig(name="oracle", model_id="oracle", role="planner"),
            "nayru": ModelConfig(name="nayru", model_id="nayru", role="analysis"),
        }
        responses: list[tuple[int, object, str | None]] = []
        with patch("app.serve._respond", side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error))):
            await handle_command(state, 212, {"cmd": "/orchestrator", "args": ["oracle-main"]})

        self.assertEqual(state.orchestrator_model, "oracle")
        self.assertEqual(state.model_alias_resolutions, 1)
        result = responses[-1][1]
        self.assertIsInstance(result, dict)
        self.assertEqual(responses[-1], (212, result, None))
        self.assertEqual(result["orchestrator"], "oracle")
        self.assertEqual(result["resolved"], "oracle")
        self.assertFalse(result["auto_selected"])
        self.assertEqual(len(result["routing"]), 1)
        decision = result["routing"][0]
        self.assertEqual(decision["target"], "oracle")
        self.assertEqual(decision["reason"], "orchestrator-explicit")
        self.assertEqual(decision["requested_mode"], "orchestrator")
        self.assertEqual(decision["normalized_mode"], "orchestrator")
        self.assertIsNone(decision["legacy_mode_alias"])
        self.assertEqual(result["warning"], "Legacy alias 'oracle-main' now resolves to 'oracle'.")

    async def test_handle_command_orchestrator_unknown_name_reports_error(self) -> None:
        state = ServeState()
        state.models = {
            "nayru": ModelConfig(name="nayru", model_id="nayru", role="analysis"),
        }
        responses: list[tuple[int, object, str | None]] = []
        with patch("app.serve._respond", side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error))):
            await handle_command(state, 213, {"cmd": "/orchestrator", "args": ["ghost"]})

        self.assertEqual(responses[-1], (213, None, "Unknown model: ghost"))
        self.assertEqual(state.model_lookup_failures, 1)
        self.assertEqual(state.model_alias_resolutions, 0)

    async def test_handle_command_orchestrator_status_returns_routing(self) -> None:
        state = ServeState()
        state.models = {
            "nayru": ModelConfig(name="nayru", model_id="nayru", role="analysis"),
        }
        state.orchestrator_model = ""
        state.active_model = "nayru"
        responses: list[tuple[int, object, str | None]] = []
        with patch("app.serve._respond", side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error))):
            await handle_command(state, 214, {"cmd": "/orchestrator", "args": []})

        result = responses[-1][1]
        self.assertIsInstance(result, dict)
        self.assertEqual(responses[-1], (214, result, None))
        self.assertEqual(result["orchestrator"], "")
        self.assertEqual(result["resolved"], "nayru")
        self.assertTrue(result["auto_selected"])
        self.assertEqual(len(result["routing"]), 1)
        decision = result["routing"][0]
        self.assertEqual(decision["target"], "nayru")
        self.assertEqual(decision["reason"], "orchestrator-fallback")
        self.assertEqual(decision["requested_mode"], "orchestrator")
        self.assertEqual(decision["normalized_mode"], "orchestrator")

    async def test_resume_coerces_hidden_active_model_back_to_oracle(self) -> None:
        state = ServeState()
        state.models = {
            "oracle": ModelConfig(name="oracle", model_id="oracle", role="planner"),
            "avatar": ModelConfig(name="avatar", model_id="avatar", role="avatar alias"),
        }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            saved_path = root / "saved-session.jsonl"
            saved_path.write_text("", encoding="utf-8")
            placeholder_dir = root / "active"
            state.session = Session(placeholder_dir)
            state.session.start(
                active_model="oracle",
                backend=state.backend_name,
                mode=state.mode,
                workspace=str(root),
                rom_path="",
                tools_enabled=state.tools_enabled,
                broadcast_models=state.broadcast_models,
                llamacpp_model=state.llamacpp_model,
                tools_write=state.tools_write,
                verify_hooks=state.verify_hooks,
                focus_path="",
            )

            responses: list[tuple[int, object, str | None]] = []
            with patch("app.serve.find_session", return_value={"name": "saved", "path": str(saved_path)}), patch(
                "app.serve.load_session_bundle",
                return_value=SimpleNamespace(
                    meta={"active_model": "avatar"},
                    model_messages={},
                    transcript=[],
                    message_count=0,
                    subagents=[],
                ),
            ), patch("app.serve.refresh_tool_bridge", new=AsyncMock()), patch(
                "app.serve._respond",
                side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
            ):
                await handle_command(state, 215, {"cmd": "/resume", "args": ["saved"]})

        result = responses[-1][1]
        self.assertIsInstance(result, dict)
        self.assertEqual(state.active_model, "oracle")
        self.assertIn("does not expose model 'avatar'", " ".join(result["warnings"]))

    async def test_llamacpp_node_command_switches_named_endpoint(self) -> None:
        state = ServeState()
        state.llamacpp_nodes = {
            "oracle-pro-vast": LlamaCppNodeConfig(
                name="oracle-pro-vast",
                api_base="http://127.0.0.1:18080/v1",
                model="oracle-pro",
                description="SSH tunnel",
            ),
        }
        responses: list[tuple[int, object, str | None]] = []

        with patch(
            "app.serve._respond",
            side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
        ), patch(
            "app.serve._notify",
        ):
            await handle_command(state, 216, {"cmd": "/llamacpp-node", "args": ["oracle-pro-vast"]})

        self.assertEqual(state.llamacpp_node, "oracle-pro-vast")
        self.assertEqual(state.llamacpp_api_base, "http://127.0.0.1:18080/v1")
        self.assertEqual(state.llamacpp_model, "oracle-pro")
        self.assertEqual(responses[-1][2], None)
        self.assertEqual(responses[-1][1]["active"], "oracle-pro-vast")

    async def test_studio_node_command_switches_named_endpoint(self) -> None:
        state = ServeState()
        state.models = {
            "oracle-pro": ModelConfig(name="oracle-pro", model_id="oracle-pro", role="pro"),
        }
        state.studio_nodes = {
            "oracle-pro-home": StudioNodeConfig(
                name="oracle-pro-home",
                api_base="http://127.0.0.1:2234/v1",
                model="oracle-pro",
                description="Windows tunnel",
            ),
        }
        responses: list[tuple[int, object, str | None]] = []

        with patch(
            "app.serve._respond",
            side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
        ), patch(
            "app.serve._notify",
        ):
            await handle_command(state, 217, {"cmd": "/studio-node", "args": ["oracle-pro-home"]})

        self.assertEqual(state.studio_node, "oracle-pro-home")
        self.assertEqual(state.studio_api_base, "http://127.0.0.1:2234/v1")
        self.assertEqual(state.backend_name, "studio")
        self.assertEqual(state.active_model, "oracle-pro")
        self.assertEqual(responses[-1][2], None)
        self.assertEqual(responses[-1][1]["active"], "oracle-pro-home")

    async def test_use_command_switches_to_home_alias(self) -> None:
        state = ServeState()
        state.models = {
            "oracle-pro": ModelConfig(name="oracle-pro", model_id="oracle-pro", role="pro"),
        }
        state.active_model = "oracle-pro"
        state.studio_nodes = {
            "oracle-pro-home": StudioNodeConfig(
                name="oracle-pro-home",
                api_base="http://127.0.0.1:2234/v1",
                model="oracle-pro",
                description="Windows tunnel",
            ),
        }
        responses: list[tuple[int, object, str | None]] = []

        with patch(
            "app.serve._respond",
            side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
        ), patch(
            "app.serve._notify",
        ):
            await handle_command(state, 218, {"cmd": "/use", "args": ["home"]})

        self.assertEqual(state.backend_name, "studio")
        self.assertEqual(state.studio_node, "oracle-pro-home")
        self.assertEqual(state.active_model, "oracle-pro")
        self.assertEqual(responses[-1][2], None)
        self.assertEqual(responses[-1][1]["resolved"], "oracle-pro-home")

    async def test_route_command_switches_to_canonical_5090_alias(self) -> None:
        state = ServeState()
        state.models = {
            "oracle-pro": ModelConfig(name="oracle-pro", model_id="oracle-pro", role="pro"),
        }
        state.active_model = "oracle-pro"
        state.studio_nodes = {
            "oracle-pro-home": StudioNodeConfig(
                name="oracle-pro-home",
                api_base="http://127.0.0.1:2234/v1",
                model="oracle-pro",
                description="Windows tunnel",
            ),
        }
        responses: list[tuple[int, object, str | None]] = []

        with patch(
            "app.serve._respond",
            side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
        ), patch(
            "app.serve._notify",
        ):
            await handle_command(state, 222, {"cmd": "/route", "args": ["oracle-pro-5090"]})

        self.assertEqual(state.backend_name, "studio")
        self.assertEqual(state.studio_node, "oracle-pro-home")
        self.assertEqual(state.active_model, "oracle-pro")
        self.assertEqual(responses[-1][2], None)
        self.assertEqual(responses[-1][1]["route"], "oracle-pro-5090")
        self.assertEqual(responses[-1][1]["resolved"], "oracle-pro-home")
        if state.focus_refresh_task is not None:
            state.focus_refresh_task.cancel()
            await asyncio.gather(state.focus_refresh_task, return_exceptions=True)

    async def test_route_list_returns_route_targets(self) -> None:
        state = ServeState()
        state.models = {
            "oracle-pro": ModelConfig(name="oracle-pro", model_id="oracle-pro", role="pro"),
        }
        state.active_model = "oracle-pro"
        state.studio_nodes = {
            "oracle-pro-home": StudioNodeConfig(
                name="oracle-pro-home",
                api_base="http://127.0.0.1:2234/v1",
                model="oracle-pro",
                description="Windows tunnel",
            ),
        }
        responses: list[tuple[int, object, str | None]] = []

        with patch(
            "app.serve._respond",
            side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
        ):
            await handle_command(state, 223, {"cmd": "/route", "args": ["list"]})

        payload = responses[-1][1]
        self.assertEqual(responses[-1][2], None)
        self.assertEqual(payload["active"]["model"], "oracle-pro")
        names = [entry["name"] for entry in payload["entries"]]
        self.assertEqual(names, ["oracle-pro-5090"])
        self.assertNotIn("oracle-pro-home", names)
        self.assertEqual(payload["active_route"], "oracle-pro-5090")
        self.assertEqual(payload["routes"][0]["name"], "oracle-pro-5090")
        self.assertEqual(payload["routes"][0]["backend"], "SERVING_BACKEND_STUDIO")

    async def test_route_list_rpc_returns_proto_json_routes(self) -> None:
        state = ServeState()
        state.models = {
            "oracle-pro": ModelConfig(name="oracle-pro", model_id="oracle-pro", role="pro"),
        }
        state.active_model = "oracle-pro"
        state.studio_nodes = {
            "oracle-pro-home": StudioNodeConfig(
                name="oracle-pro-home",
                api_base="http://127.0.0.1:2234/v1",
                model="oracle-pro",
                description="Windows tunnel",
                hostd_url="http://127.0.0.1:8766",
            ),
        }
        responses: list[tuple[int, object, str | None]] = []

        with patch(
            "app.serve._respond",
            side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
        ):
            handled = await handle_route_rpc(state, 229, "route/list", {"includeHidden": False})

        self.assertTrue(handled)
        self.assertEqual(responses[-1][2], None)
        payload = responses[-1][1]
        self.assertEqual(payload["activeRoute"], "oracle-pro-5090")
        self.assertEqual(payload["routes"][0]["name"], "oracle-pro-5090")
        self.assertEqual(payload["routes"][0]["inferenceEndpoint"]["uri"], "http://127.0.0.1:2234/v1")
        self.assertEqual(payload["routes"][0]["controlEndpoint"]["uri"], "http://127.0.0.1:8766")

    async def test_inventory_query_rpc_refreshes_active_route_snapshot(self) -> None:
        state = ServeState()
        state.models = {
            "oracle-pro": ModelConfig(name="oracle-pro", model_id="oracle-pro", role="pro"),
        }
        state.active_model = "oracle-pro"
        state.studio_node = "oracle-pro-home"
        state.studio_nodes = {
            "oracle-pro-home": StudioNodeConfig(
                name="oracle-pro-home",
                api_base="http://127.0.0.1:2234/v1",
                model="oracle-pro",
                description="Windows tunnel",
            ),
        }
        backend = SimpleNamespace(
            check_connection=AsyncMock(return_value=SimpleNamespace(connected=True, detail="port=1234")),
            list_loaded_model_details=AsyncMock(return_value=[{
                "identifier": "oracle-pro",
                "model_key": "oracle-pro",
                "display_name": "Oracle Pro",
                "size_bytes": 123,
            }]),
        )
        responses: list[tuple[int, object, str | None]] = []

        with patch("app.serve.get_backend", return_value=backend), patch(
            "app.serve._respond",
            side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
        ):
            handled = await handle_inventory_rpc(state, 232, "inventory/query", {"forceRefresh": True})

        self.assertTrue(handled)
        self.assertEqual(responses[-1][2], None)
        payload = responses[-1][1]
        snapshot = payload["snapshots"][0]
        self.assertEqual(snapshot["source"], "oracle-pro-5090")
        self.assertEqual(snapshot["health"], "HEALTH_STATE_HEALTHY")
        self.assertEqual(snapshot["loadedModels"][0]["runtimeId"], "oracle-pro")
        self.assertEqual(snapshot["loadedModels"][0]["sizeBytes"], 123)
        self.assertIsNotNone(state.inventory_cache.get("oracle-pro-5090"))

    async def test_inventory_snapshot_rpc_uses_cache_without_backend_probe(self) -> None:
        state = ServeState()
        state.models = {
            "oracle-pro": ModelConfig(name="oracle-pro", model_id="oracle-pro", role="pro"),
        }
        state.active_model = "oracle-pro"
        state.studio_node = "oracle-pro-home"
        state.studio_nodes = {
            "oracle-pro-home": StudioNodeConfig(
                name="oracle-pro-home",
                api_base="http://127.0.0.1:2234/v1",
                model="oracle-pro",
                description="Windows tunnel",
            ),
        }
        state.inventory_cache.put("oracle-pro-5090", {
            "source": "oracle-pro-5090",
            "health": "HEALTH_STATE_HEALTHY",
            "loadedModels": [],
            "ttlMs": 5000,
        })
        responses: list[tuple[int, object, str | None]] = []

        with patch("app.serve.get_backend", side_effect=AssertionError("should not probe backend")), patch(
            "app.serve._respond",
            side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
        ):
            handled = await handle_inventory_rpc(state, 233, "inventory/snapshot", {})

        self.assertTrue(handled)
        self.assertEqual(responses[-1][2], None)
        self.assertEqual(responses[-1][1]["source"], "oracle-pro-5090")

    def test_build_ready_params_uses_cached_inventory_loaded_models(self) -> None:
        state = ServeState()
        state.models = {
            "oracle-pro": ModelConfig(name="oracle-pro", model_id="oracle-pro", role="pro"),
        }
        state.active_model = "oracle-pro"
        state.studio_node = "oracle-pro-home"
        state.studio_nodes = {
            "oracle-pro-home": StudioNodeConfig(
                name="oracle-pro-home",
                api_base="http://127.0.0.1:2234/v1",
                model="oracle-pro",
                description="Windows tunnel",
            ),
        }
        state.inventory_cache.put("oracle-pro-5090", {
            "source": "oracle-pro-5090",
            "loadedModels": [{
                "ref": {"name": "oracle-pro", "modelId": "oracle-pro", "provider": "studio"},
                "runtimeId": "oracle-pro",
                "displayName": "Oracle Pro",
                "sizeBytes": 123,
            }],
            "ttlMs": 5000,
        })

        with patch("app.serve.loaded_model_runtime_infos", side_effect=AssertionError("cache miss")), patch(
            "app.serve.primary_model_infos",
            return_value=[],
        ), patch("app.serve.model_catalog_infos", return_value=[]):
            params = build_ready_params(state)

        self.assertEqual(params["loaded_model_count"], 1)
        self.assertEqual(params["loaded_model_memory_bytes"], 123)
        self.assertEqual(params["loaded_models"][0]["identifier"], "oracle-pro")

    async def test_models_routes_returns_route_targets(self) -> None:
        state = ServeState()
        state.models = {
            "oracle-pro": ModelConfig(name="oracle-pro", model_id="oracle-pro", role="pro"),
        }
        state.active_model = "oracle-pro"
        state.studio_nodes = {
            "oracle-pro-home": StudioNodeConfig(
                name="oracle-pro-home",
                api_base="http://127.0.0.1:2234/v1",
                model="oracle-pro",
                description="Windows tunnel",
            ),
        }
        responses: list[tuple[int, object, str | None]] = []

        with patch(
            "app.serve._respond",
            side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
        ):
            await handle_command(state, 225, {"cmd": "/models", "args": ["routes"]})

        payload = responses[-1][1]
        self.assertEqual(responses[-1][2], None)
        self.assertEqual(payload["active"]["model"], "oracle-pro")
        self.assertIn("oracle-pro-5090", [entry["name"] for entry in payload["entries"]])

    async def test_route_list_advanced_returns_raw_route_targets(self) -> None:
        state = ServeState()
        state.models = {
            "oracle-pro": ModelConfig(name="oracle-pro", model_id="oracle-pro", role="pro"),
        }
        state.active_model = "oracle-pro"
        state.studio_nodes = {
            "oracle-pro-home": StudioNodeConfig(
                name="oracle-pro-home",
                api_base="http://127.0.0.1:2234/v1",
                model="oracle-pro",
                description="Windows tunnel",
            ),
        }
        responses: list[tuple[int, object, str | None]] = []

        with patch(
            "app.serve._respond",
            side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
        ):
            await handle_command(state, 227, {"cmd": "/route", "args": ["list", "advanced"]})

        payload = responses[-1][1]
        self.assertEqual(responses[-1][2], None)
        names = [entry["name"] for entry in payload["entries"]]
        self.assertIn("oracle-pro-5090", names)
        self.assertIn("oracle-pro-home", names)

    async def test_models_catalog_returns_model_payloads(self) -> None:
        state = ServeState()
        state.models = {
            "oracle-pro": ModelConfig(name="oracle-pro", model_id="oracle-pro", role="pro"),
        }
        state.active_model = "oracle-pro"
        responses: list[tuple[int, object, str | None]] = []

        with patch(
            "app.serve._respond",
            side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
        ):
            await handle_command(state, 226, {"cmd": "/models", "args": ["catalog"]})

        payload = responses[-1][1]
        self.assertEqual(responses[-1][2], None)
        self.assertTrue(payload["catalog"])
        self.assertIn("oracle-pro", [entry["name"] for entry in payload["models"]])

    async def test_use_command_responds_before_ready_refresh_builds(self) -> None:
        state = ServeState()
        state.models = {
            "oracle-pro": ModelConfig(name="oracle-pro", model_id="oracle-pro", role="pro"),
        }
        state.active_model = "oracle-pro"
        state.studio_nodes = {
            "oracle-pro-home": StudioNodeConfig(
                name="oracle-pro-home",
                api_base="http://127.0.0.1:2234/v1",
                model="oracle-pro",
                description="Windows tunnel",
            ),
        }
        order: list[str] = []
        responses: list[tuple[int, object, str | None]] = []

        def capture_response(req_id: int, result: object = None, error: str | None = None) -> None:
            responses.append((req_id, result, error))
            order.append("respond")

        def capture_ready_build(_state: ServeState) -> dict[str, object]:
            order.append("ready-build")
            return {"models": [], "model_catalog": []}

        with patch("app.serve.build_ready_params", side_effect=capture_ready_build), patch(
            "app.serve._respond",
            side_effect=capture_response,
        ), patch("app.serve._notify"):
            await handle_command(state, 221, {"cmd": "/use", "args": ["home"]})

        self.assertEqual(responses[-1][2], None)
        self.assertEqual(order, ["respond"])
        if state.focus_refresh_task is not None:
            state.focus_refresh_task.cancel()
            await asyncio.gather(state.focus_refresh_task, return_exceptions=True)
        if state.ready_refresh_task is not None:
            state.ready_refresh_task.cancel()
            await asyncio.gather(state.ready_refresh_task, return_exceptions=True)

    async def test_route_select_rpc_responds_before_ready_refresh_builds(self) -> None:
        state = ServeState()
        state.models = {
            "oracle-pro": ModelConfig(name="oracle-pro", model_id="oracle-pro", role="pro"),
        }
        state.active_model = "oracle-pro"
        state.studio_nodes = {
            "oracle-pro-home": StudioNodeConfig(
                name="oracle-pro-home",
                api_base="http://127.0.0.1:2234/v1",
                model="oracle-pro",
                description="Windows tunnel",
            ),
        }
        order: list[str] = []
        responses: list[tuple[int, object, str | None]] = []

        def capture_response(req_id: int, result: object = None, error: str | None = None) -> None:
            responses.append((req_id, result, error))
            order.append("respond")

        def capture_ready_build(_state: ServeState) -> dict[str, object]:
            order.append("ready-build")
            return {"models": [], "model_catalog": []}

        with patch("app.serve.build_ready_params", side_effect=capture_ready_build), patch(
            "app.serve._respond",
            side_effect=capture_response,
        ), patch("app.serve._notify"):
            handled = await handle_route_rpc(state, 230, "route/select", {"route": "oracle-pro-5090"})

        self.assertTrue(handled)
        self.assertEqual(responses[-1][2], None)
        self.assertEqual(order, ["respond"])
        payload = responses[-1][1]
        self.assertTrue(payload["accepted"])
        self.assertEqual(payload["route"]["name"], "oracle-pro-5090")
        self.assertEqual(payload["route"]["backend"], "SERVING_BACKEND_STUDIO")
        if state.focus_refresh_task is not None:
            state.focus_refresh_task.cancel()
            await asyncio.gather(state.focus_refresh_task, return_exceptions=True)
        if state.ready_refresh_task is not None:
            state.ready_refresh_task.cancel()
            await asyncio.gather(state.ready_refresh_task, return_exceptions=True)

    async def test_smoke_command_switches_target_and_returns_probe_result(self) -> None:
        state = ServeState()
        state.models = {
            "oracle-pro": ModelConfig(name="oracle-pro", model_id="oracle-pro", role="pro"),
        }
        state.active_model = "oracle-pro"
        state.llamacpp_nodes = {
            "oracle-pro-home-ssh": LlamaCppNodeConfig(
                name="oracle-pro-home-ssh",
                api_base="ssh://medical-mechanica/127.0.0.1:1234/v1",
                model="gguf/zelda/qwen3-oracle-14b-v8-q4km.gguf",
                description="SSH command proxy",
                lean_prompt=True,
            ),
        }
        responses: list[tuple[int, object, str | None]] = []

        with patch(
            "app.serve.smoke_current_route",
            new=AsyncMock(return_value={
                "ok": True,
                "matched": True,
                "backend": "llamacpp",
                "node": "oracle-pro-home-ssh",
                "api_base": "ssh://medical-mechanica/127.0.0.1:1234/v1",
                "model": "gguf/zelda/qwen3-oracle-14b-v8-q4km.gguf",
                "duration_ms": 42,
                "text": "z3cli smoke ok",
            }),
        ), patch(
            "app.serve._respond",
            side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
        ), patch(
            "app.serve._notify",
        ):
            await handle_command(state, 220, {"cmd": "/smoke", "args": ["home-ssh"]})

        self.assertEqual(state.backend_name, "llamacpp")
        self.assertEqual(state.llamacpp_node, "oracle-pro-home-ssh")
        self.assertEqual(responses[-1][2], None)
        payload = responses[-1][1]
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["applied"]["resolved"], "oracle-pro-home-ssh")

    async def test_route_smoke_uses_canonical_ssh_route(self) -> None:
        state = ServeState()
        state.models = {
            "oracle-pro": ModelConfig(name="oracle-pro", model_id="oracle-pro", role="pro"),
        }
        state.active_model = "oracle-pro"
        state.llamacpp_nodes = {
            "oracle-pro-home-ssh": LlamaCppNodeConfig(
                name="oracle-pro-home-ssh",
                api_base="ssh://medical-mechanica/127.0.0.1:1234/v1",
                model="gguf/zelda/qwen3-oracle-14b-v8-q4km.gguf",
                description="SSH command proxy",
                lean_prompt=True,
            ),
        }
        responses: list[tuple[int, object, str | None]] = []

        with patch(
            "app.serve.smoke_current_route",
            new=AsyncMock(return_value={
                "ok": True,
                "matched": True,
                "backend": "llamacpp",
                "node": "oracle-pro-home-ssh",
                "api_base": "ssh://medical-mechanica/127.0.0.1:1234/v1",
                "model": "gguf/zelda/qwen3-oracle-14b-v8-q4km.gguf",
                "duration_ms": 42,
                "text": "z3cli smoke ok",
            }),
        ), patch(
            "app.serve._respond",
            side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
        ), patch(
            "app.serve._notify",
        ):
            await handle_command(state, 224, {"cmd": "/route", "args": ["smoke", "oracle-pro-ssh"]})

        self.assertEqual(state.backend_name, "llamacpp")
        self.assertEqual(state.llamacpp_node, "oracle-pro-home-ssh")
        self.assertEqual(responses[-1][2], None)
        payload = responses[-1][1]
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["applied"]["route"], "oracle-pro-ssh")

    async def test_route_probe_rpc_returns_proto_json_probe_response(self) -> None:
        state = ServeState()
        state.models = {
            "oracle-pro": ModelConfig(name="oracle-pro", model_id="oracle-pro", role="pro"),
        }
        state.active_model = "oracle-pro"
        state.llamacpp_nodes = {
            "oracle-pro-home-ssh": LlamaCppNodeConfig(
                name="oracle-pro-home-ssh",
                api_base="ssh://medical-mechanica/127.0.0.1:1234/v1",
                model="gguf/zelda/qwen3-oracle-14b-v8-q4km.gguf",
                description="SSH command proxy",
                lean_prompt=True,
            ),
        }
        responses: list[tuple[int, object, str | None]] = []

        with patch(
            "app.serve.smoke_current_route",
            new=AsyncMock(return_value={
                "ok": True,
                "matched": True,
                "duration_ms": 42,
                "text": "z3cli smoke ok",
                "error": "",
            }),
        ), patch(
            "app.serve._respond",
            side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
        ), patch(
            "app.serve._notify",
        ):
            handled = await handle_route_rpc(state, 231, "route/probe", {"route": "oracle-pro-ssh", "timeoutMs": 1000})

        self.assertTrue(handled)
        self.assertEqual(responses[-1][2], None)
        payload = responses[-1][1]
        self.assertEqual(payload, {
            "route": "oracle-pro-ssh",
            "ok": True,
            "matched": True,
            "text": "z3cli smoke ok",
            "durationMs": 42,
            "error": "",
        })
        if state.ready_refresh_task is not None:
            state.ready_refresh_task.cancel()
            await asyncio.gather(state.ready_refresh_task, return_exceptions=True)

    async def test_oracle_tips_command_returns_cheat_sheet(self) -> None:
        state = ServeState()
        responses: list[tuple[int, object, str | None]] = []

        with patch(
            "app.serve._respond",
            side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
        ):
            await handle_command(state, 219, {"cmd": "/oracle-tips", "args": []})

        self.assertTrue(responses)
        req_id, result, error = responses[-1]
        self.assertEqual(req_id, 219)
        self.assertIsNone(error)
        payload = result if isinstance(result, dict) else {}
        self.assertEqual(payload.get("title"), "Oracle Prompt Tips")
        self.assertIn("symptom + anchor + intent", str(payload.get("text", "")))

    async def test_resume_can_strip_transcript_reasoning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            saved_path = root / "saved-session.jsonl"
            saved_path.write_text("", encoding="utf-8")
            state = ServeState()
            state.workspace = root
            state.models = {
                "oracle": ModelConfig(name="oracle", model_id="oracle", role="analysis"),
            }
            state.active_model = "oracle"
            state.session = Session(root / "sessions")
            state.session.start(
                active_model="oracle",
                backend=state.backend_name,
                mode=state.mode,
                workspace=str(root),
                rom_path="",
                tools_enabled=state.tools_enabled,
                broadcast_models=state.broadcast_models,
                llamacpp_model=state.llamacpp_model,
                tools_write=state.tools_write,
                verify_hooks=state.verify_hooks,
                focus_path="",
            )

            responses: list[tuple[int, object, str | None]] = []
            with patch("app.serve.find_session", return_value={"name": "saved", "path": str(saved_path)}), patch(
                "app.serve.load_session_bundle_without_thinking",
                return_value=SimpleNamespace(
                    meta={"active_model": "oracle"},
                    model_messages={},
                    transcript=[],
                    message_count=0,
                    subagents=[],
                ),
            ) as stripped_loader, patch("app.serve.refresh_tool_bridge", new=AsyncMock()), patch(
                "app.serve._respond",
                side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
            ):
                await handle_command(state, 216, {"cmd": "/resume", "args": ["saved", "--strip-thinking"]})

        stripped_loader.assert_called_once()
        result = responses[-1][1]
        self.assertTrue(result["thinking_stripped"])

    async def test_resume_without_name_returns_saved_sessions(self) -> None:
        state = ServeState()
        responses: list[tuple[int, object, str | None]] = []

        with patch(
            "app.serve.list_sessions",
            return_value=[{"name": "saved", "active_model": "oracle", "mode": "manual", "messages": 4}],
        ), patch(
            "app.serve._respond",
            side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
        ):
            await handle_command(state, 217, {"cmd": "/resume", "args": []})

        self.assertEqual(responses[-1], (217, {"sessions": [{"name": "saved", "active_model": "oracle", "mode": "manual", "messages": 4}]}, None))

    async def test_handle_chat_rejects_unknown_requested_model(self) -> None:
        state = ServeState()
        state.models = {
            "nayru": ModelConfig(name="nayru", model_id="nayru", role="analysis"),
        }
        state.active_model = "nayru"
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            session_dir = workspace / "sessions"
            state.workspace = workspace
            state.session = Session(session_dir)
            state.session.start(
                active_model=state.active_model,
                backend=state.backend_name,
                mode=state.mode,
                workspace=str(state.workspace),
                rom_path="",
                tools_enabled=state.tools_enabled,
                broadcast_models=state.broadcast_models,
            )

        with self.assertRaisesRegex(RuntimeError, "Unknown model"):
            await handle_chat(state, 202, {"message": "hello", "model": "ghost"}, request_id="req-202")
        self.assertEqual(state.model_lookup_failures, 1)
        self.assertEqual(state.model_alias_resolutions, 0)
        state.session.close()

    async def test_handle_chat_alias_model_and_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            session_dir = workspace / "sessions"
            state = ServeState()
            state.workspace = workspace
            state.models = {
                "oracle": ModelConfig(name="oracle", model_id="oracle", role="analysis"),
                "nayru": ModelConfig(name="nayru", model_id="nayru", role="analysis"),
            }
            state.active_model = "nayru"
            state.session = Session(session_dir)
            state.session.start(
                active_model=state.active_model,
                backend=state.backend_name,
                mode=state.mode,
                workspace=str(state.workspace),
                rom_path="",
                tools_enabled=state.tools_enabled,
                broadcast_models=state.broadcast_models,
            )
            state.get_engine = lambda _name: TraceToolEngine()  # type: ignore[method-assign]

            responses: list[tuple[int, object, str | None]] = []
            with patch("app.serve._respond", side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error))), patch(
                "app.serve._notify",
                side_effect=lambda method, params=None: None,
            ), patch("app.serve.resolve_request_model_name", return_value="oracle"):
                await handle_chat(state, 204, {"message": "hello", "model": "oracle-main"}, request_id="req-204")

            self.assertEqual(state.model_alias_resolutions, 1)
            self.assertEqual(state.model_lookup_failures, 0)
            self.assertEqual(state.model_request_counts.get("oracle"), 1)
            self.assertEqual(responses[-1], (204, {"ok": True}, None))
            state.session.close()

    async def test_init_state_falls_back_to_safe_startup_model_when_default_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry_path = root / "chat_registry.toml"
            registry_path.write_text(
                """
[[models]]
name = "farore"
model_id = "farore"
provider = "studio"
role = "quick specialist"

[[models]]
name = "veran"
model_id = "veran"
provider = "studio"
role = "context specialist"
""".strip(),
                encoding="utf-8",
            )

            with patch("app.serve.ensure_server"), patch(
                "core.session.DEFAULT_SESSION_DIR",
                root / "sessions",
            ):
                state = await init_state([
                    "--registry", str(registry_path),
                    "--mcp-config", str(root / "mcp.json"),
                    "--no-tools",
                ])

            self.assertEqual(state.active_model, "farore")
            self.assertTrue(any("farore" in warning for warning in state.startup_warnings))
            state.session.close()

    async def test_forward_subagent_start_includes_tree_metadata(self) -> None:
        notifications: list[tuple[str, dict | None]] = []
        state = ServeState()

        with patch(
            "app.serve._notify",
            side_effect=lambda method, params=None: notifications.append((method, params)),
        ):
            await _forward_subagent_event(state, SubagentStartEvent(
                id="sub-7-worker",
                name="worker",
                model_name="worker",
                provider="anthropic",
                depth=2,
                parent_id="sub-3-planner",
            ))

        self.assertEqual(len(notifications), 1)
        method, params = notifications[0]
        self.assertEqual(method, "subagent/start")
        self.assertEqual(params, {
            "id": "sub-7-worker",
            "name": "worker",
            "model": "worker",
            "provider": "anthropic",
            "depth": 2,
            "parent_id": "sub-3-planner",
        })

    async def test_cancel_pending_prompts_releases_decision_events(self) -> None:
        state = ServeState()
        state.tool_decision = asyncio.Event()
        state.tool_review_decision = asyncio.Event()
        state.tool_approved = True
        state.tool_decision_scope = "session"
        state.tool_review_action = "accept"

        state.cancel_pending_prompts()

        self.assertFalse(state.tool_approved)
        self.assertEqual(state.tool_decision_scope, "once")
        self.assertEqual(state.tool_review_action, "reject")
        self.assertTrue(state.tool_decision.is_set())
        self.assertTrue(state.tool_review_decision.is_set())

    async def test_tool_permission_hook_unblocks_on_cancel(self) -> None:
        state = ServeState()
        state.workspace = Path.cwd()

        with patch("app.serve._notify"):
            pending = asyncio.create_task(
                state._tool_permission_hook(
                    "edit_file",
                    '{"path":"src/main.asm","edits":[]}',
                    "afs",
                    "call-1",
                ),
            )
            for _ in range(20):
                if state.tool_decision is not None:
                    break
                await asyncio.sleep(0)
            self.assertIsNotNone(state.tool_decision)

            state.cancel_requested = True
            state.cancel_pending_prompts()
            allowed = await asyncio.wait_for(pending, timeout=1)

        self.assertFalse(allowed)
        self.assertNotIn("call-1", state.pending_write_contexts)

    async def test_tool_permission_hook_emits_write_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = workspace / "src" / "main.asm"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("lda #$01\n", encoding="utf-8")

            state = ServeState()
            state.workspace = workspace
            notifications: list[tuple[str, dict | None]] = []

            def capture(method: str, params: dict | None = None) -> None:
                notifications.append((method, params))

            with patch("app.serve._notify", side_effect=capture):
                pending = asyncio.create_task(
                    state._tool_permission_hook(
                        "edit_file",
                        '{"path":"src/main.asm","edits":[{"oldText":"lda #$01\\n","newText":"lda #$02\\n"}]}',
                        "afs",
                        "call-1",
                    ),
                )
                for _ in range(20):
                    if notifications:
                        break
                    await asyncio.sleep(0)

                self.assertTrue(notifications)
                method, params = notifications[0]
                assert params is not None
                self.assertEqual(method, "tool/permission_request")
                self.assertEqual(params["name"], "edit_file")
                self.assertEqual(params["server"], "afs")
                self.assertEqual(params["reason"], "write tool: will modify main.asm")

                state.cancel_requested = True
                state.cancel_pending_prompts()
                allowed = await asyncio.wait_for(pending, timeout=1)

        self.assertFalse(allowed)
        self.assertNotIn("call-1", state.pending_write_contexts)

    def test_describe_permission_reason_returns_none_without_context_or_subagent(self) -> None:
        self.assertIsNone(_describe_permission_reason(None))

    def test_describe_permission_reason_labels_subagent_without_write_context(self) -> None:
        sub = SubagentContext(id="sub-1-nayru", name="nayru", model_name="nayru-1", depth=0)
        self.assertEqual(_describe_permission_reason(None, subagent=sub), "subagent [nayru]")

    def test_describe_permission_reason_prefixes_subagent_before_write_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = workspace / "src" / "main.asm"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("lda #$01\n", encoding="utf-8")
            wc = prepare_write_context(
                workspace,
                "edit_file",
                '{"path":"src/main.asm","edits":[{"oldText":"lda #$01\\n","newText":"lda #$02\\n"}]}',
                "call-42",
            )

        self.assertIsNotNone(wc)
        sub = SubagentContext(id="sub-2-din", name="din", model_name="din-1", depth=1)
        reason = _describe_permission_reason(wc, subagent=sub)
        assert reason is not None
        self.assertTrue(reason.startswith("subagent [din]"))
        self.assertIn("main.asm", reason)

    async def test_tool_permission_hook_attributes_reason_to_active_subagent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            state = ServeState()
            state.workspace = workspace
            notifications: list[tuple[str, dict | None]] = []

            def capture(method: str, params: dict | None = None) -> None:
                notifications.append((method, params))

            sub = SubagentContext(id="sub-3-nayru", name="nayru", model_name="nayru-1", depth=0)
            token = _current_subagent.set(sub)
            try:
                with patch("app.serve._notify", side_effect=capture):
                    pending = asyncio.create_task(
                        state._tool_permission_hook(
                            "read_file",
                            '{"path":"src/main.asm"}',
                            "afs",
                            "call-sub",
                        ),
                    )
                    for _ in range(20):
                        if notifications:
                            break
                        await asyncio.sleep(0)

                    self.assertTrue(notifications)
                    method, params = notifications[0]
                    assert params is not None
                    self.assertEqual(method, "tool/permission_request")
                    self.assertEqual(params.get("reason"), "subagent [nayru]")

                    state.cancel_requested = True
                    state.cancel_pending_prompts()
                    await asyncio.wait_for(pending, timeout=1)
            finally:
                _current_subagent.reset(token)

    async def test_handle_chat_respects_cancel_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            session_dir = workspace / "sessions"
            state = ServeState()
            state.workspace = workspace
            state.models = {
                "nayru": ModelConfig(name="nayru", model_id="nayru", role="analysis")
            }
            state.active_model = "nayru"
            state.session = Session(session_dir)
            state.session.start(
                active_model=state.active_model,
                backend=state.backend_name,
                mode=state.mode,
                workspace=str(state.workspace),
                rom_path="",
                tools_enabled=state.tools_enabled,
                broadcast_models=state.broadcast_models,
            )
            engine = CancelAwareEngine()
            state.get_engine = lambda _name: engine  # type: ignore[method-assign]

            notifications: list[tuple[str, dict | None]] = []
            responses: list[tuple[int, object, str | None]] = []

            with patch("app.serve._notify", side_effect=lambda method, params=None: notifications.append((method, params))), patch(
                "app.serve._respond",
                side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
            ), patch("app.serve.resolve_request_model_name", return_value="nayru"):
                task = asyncio.create_task(handle_chat(state, 7, {"message": "hello"}))
                await asyncio.wait_for(engine.started.wait(), timeout=1)
                for _ in range(20):
                    if any(method == "text" for method, _params in notifications):
                        break
                    await asyncio.sleep(0)
                state.cancel_requested = True
                engine.release.set()
                await asyncio.wait_for(task, timeout=1)

            self.assertTrue(engine.cancelled)
            self.assertTrue(any(method == "done" for method, _params in notifications))
            self.assertEqual(responses[-1], (7, {"ok": True}, None))
            self.assertEqual(state.session.message_count, 2)
            state.session.close()

    async def test_handle_chat_emits_reasoning_on_final_assistant_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            session_dir = workspace / "sessions"
            state = ServeState()
            state.workspace = workspace
            state.models = {
                "nayru": ModelConfig(name="nayru", model_id="nayru", role="analysis", thinking_tier="medium")
            }
            state.active_model = "nayru"
            state.session = Session(session_dir)
            state.session.start(
                active_model=state.active_model,
                backend=state.backend_name,
                mode=state.mode,
                workspace=str(state.workspace),
                rom_path="",
                tools_enabled=state.tools_enabled,
                broadcast_models=state.broadcast_models,
            )
            engine = ThinkingEngine()
            state.get_engine = lambda _name: engine  # type: ignore[method-assign]

            notifications: list[tuple[str, dict | None]] = []
            with patch("app.serve._notify", side_effect=lambda method, params=None: notifications.append((method, params))), patch(
                "app.serve.resolve_request_model_name",
                return_value="nayru",
            ):
                await handle_chat(state, 11, {"message": "patch it"})

            assistant_messages = [
                params for method, params in notifications
                if method == "message" and isinstance(params, dict) and params.get("role") == "assistant"
            ]
            self.assertEqual(len(assistant_messages), 1)
            self.assertEqual(assistant_messages[0]["thinking"], "Inspecting the room header.")
            self.assertEqual(assistant_messages[0]["content"], "Patched the room script.")
            state.session.close()

    async def test_handle_chat_disables_native_tool_schemas_for_xml_tool_lanes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            session_dir = workspace / "sessions"
            state = ServeState()
            state.workspace = workspace
            state.bridge = BlockingToolBridge()
            state.models = {
                "qwen3-oracle-8b": ModelConfig(
                    name="qwen3-oracle-8b",
                    model_id="gguf/zelda/qwen3-oracle-8b-v1-corrective2-q8_0.gguf",
                    role="shared oracle qwen3 model",
                    tools_enabled=True,
                    deferred_tools=True,
                    native_tools=False,
                )
            }
            state.active_model = "qwen3-oracle-8b"
            state.session = Session(session_dir)
            state.session.start(
                active_model=state.active_model,
                backend=state.backend_name,
                mode=state.mode,
                workspace=str(state.workspace),
                rom_path="",
                tools_enabled=state.tools_enabled,
                broadcast_models=state.broadcast_models,
            )

            class FakeEngine:
                def __init__(self) -> None:
                    self.bridge = None
                    self.chat_kwargs: dict | None = None

                def cancel(self) -> None:
                    return None

                async def chat(self, **kwargs):  # type: ignore[no-untyped-def]
                    self.chat_kwargs = dict(kwargs)
                    yield DoneEvent()

            engine = FakeEngine()
            state.get_engine = lambda _name: engine  # type: ignore[method-assign]

            with patch("app.serve.resolve_request_model_name", return_value="qwen3-oracle-8b"), patch(
                "app.serve._notify",
                side_effect=lambda method, params=None: None,
            ):
                await handle_chat(state, 15, {"message": "inspect this file"}, request_id="req-15")

            self.assertIsNotNone(engine.chat_kwargs)
            assert engine.chat_kwargs is not None
            self.assertFalse(engine.chat_kwargs["use_tools"])
            self.assertTrue(engine.chat_kwargs["allow_manual_tool_calls"])
            state.session.close()

    async def test_handle_chat_disables_manual_xml_execution_when_tools_are_off(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            session_dir = workspace / "sessions"
            state = ServeState()
            state.workspace = workspace
            state.bridge = BlockingToolBridge()
            state.tools_enabled = False
            state.subagent_tools_enabled = False
            state.models = {
                "qwen3-oracle-8b": ModelConfig(
                    name="qwen3-oracle-8b",
                    model_id="gguf/zelda/qwen3-oracle-8b-v1-corrective2-q8_0.gguf",
                    role="shared oracle qwen3 model",
                    tools_enabled=True,
                    deferred_tools=True,
                    native_tools=False,
                )
            }
            state.active_model = "qwen3-oracle-8b"
            state.session = Session(session_dir)
            state.session.start(
                active_model=state.active_model,
                backend=state.backend_name,
                mode=state.mode,
                workspace=str(state.workspace),
                rom_path="",
                tools_enabled=state.tools_enabled,
                broadcast_models=state.broadcast_models,
            )

            class FakeEngine:
                def __init__(self) -> None:
                    self.bridge = None
                    self.chat_kwargs: dict | None = None

                def cancel(self) -> None:
                    return None

                async def chat(self, **kwargs):  # type: ignore[no-untyped-def]
                    self.chat_kwargs = dict(kwargs)
                    yield DoneEvent()

            engine = FakeEngine()
            state.get_engine = lambda _name: engine  # type: ignore[method-assign]

            with patch("app.serve.resolve_request_model_name", return_value="qwen3-oracle-8b"), patch(
                "app.serve._notify",
                side_effect=lambda method, params=None: None,
            ):
                await handle_chat(state, 18, {"message": "inspect this file"}, request_id="req-18")

            self.assertIsNotNone(engine.chat_kwargs)
            assert engine.chat_kwargs is not None
            self.assertFalse(engine.chat_kwargs["use_tools"])
            self.assertFalse(engine.chat_kwargs["allow_manual_tool_calls"])
            self.assertNotIn("manual XML tool calls", engine.chat_kwargs["system"])
            state.session.close()

    async def test_handle_chat_exposes_oracle_coder_to_oracle_fast_and_injects_quality_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            session_dir = workspace / "sessions"
            state = ServeState()
            state.workspace = workspace
            state.models = {
                "oracle-fast": ModelConfig(
                    name="oracle-fast",
                    model_id="oracle-fast",
                    role="fast local model",
                    tools_enabled=True,
                ),
                "oracle-coder": ModelConfig(
                    name="oracle-coder",
                    model_id="qwen25-oracle-coder-7b-v1",
                    role="internal coding worker",
                    tags=["oracle"],
                    visibility="hidden",
                    spawn_only=True,
                    spawnable_by=["oracle", "oracle-fast"],
                    tools_enabled=True,
                ),
            }
            state.active_model = "oracle-fast"
            state.session = Session(session_dir)
            state.session.start(
                active_model=state.active_model,
                backend=state.backend_name,
                mode=state.mode,
                workspace=str(state.workspace),
                rom_path="",
                tools_enabled=state.tools_enabled,
                broadcast_models=state.broadcast_models,
            )

            class FakeEngine:
                def __init__(self) -> None:
                    self.bridge = None
                    self.chat_kwargs: dict | None = None

                def cancel(self) -> None:
                    return None

                async def chat(self, **kwargs):  # type: ignore[no-untyped-def]
                    self.chat_kwargs = dict(kwargs)
                    yield DoneEvent()

            engine = FakeEngine()
            state.get_engine = lambda _name: engine  # type: ignore[method-assign]

            with patch("app.serve.resolve_request_model_name", return_value="oracle-fast"), patch(
                "app.serve._notify",
                side_effect=lambda method, params=None: None,
            ):
                await handle_chat(state, 16, {"message": "repair this asm hook"}, request_id="req-16")

            self.assertIsNotNone(engine.chat_kwargs)
            assert engine.chat_kwargs is not None
            self.assertIn("Delegate the code-writing pass to `spawn_subagent` with model `oracle-coder`", engine.chat_kwargs["system"])
            self.assertIn("Quality-first policy", engine.chat_kwargs["system"])
            assert engine.bridge is not None
            tool_names = [tool["function"]["name"] for tool in engine.bridge.get_openai_tools()]
            self.assertIn("spawn_subagent", tool_names)
            spawn_tool = next(tool for tool in engine.bridge.get_openai_tools() if tool["function"]["name"] == "spawn_subagent")
            self.assertEqual(spawn_tool["function"]["parameters"]["properties"]["model"]["enum"], ["oracle-coder"])
            state.session.close()

    async def test_handle_chat_sanitizes_tool_backed_answer_and_anchors_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            session_dir = workspace / "sessions"
            state = ServeState()
            state.workspace = workspace
            state.models = {
                "farore": ModelConfig(name="farore", model_id="farore", role="debugger", tool_profile="farore")
            }
            state.active_model = "farore"
            state.session = Session(session_dir)
            state.session.start(
                active_model=state.active_model,
                backend=state.backend_name,
                mode=state.mode,
                workspace=str(state.workspace),
                rom_path="",
                tools_enabled=state.tools_enabled,
                broadcast_models=state.broadcast_models,
            )
            engine = SanitizingToolEngine()
            state.get_engine = lambda _name: engine  # type: ignore[method-assign]

            notifications: list[tuple[str, dict | None]] = []
            with patch("app.serve._notify", side_effect=lambda method, params=None: notifications.append((method, params))), patch(
                "app.serve.resolve_request_model_name",
                return_value="farore",
            ):
                await handle_chat(state, 17, {"message": "inspect room 0x45"}, request_id="req-17")

            text_deltas = [
                str(params["delta"])
                for method, params in notifications
                if method == "text" and isinstance(params, dict)
            ]
            streamed = "".join(text_deltas)
            self.assertNotIn("The user is wrong", streamed)
            self.assertNotIn("Okay, I checked the room.", streamed)
            self.assertIn("Evidence: `inspect_room` -> Room 0x45", streamed)
            self.assertIn("The room has 3 sprites.", streamed)

            assistant_messages = [
                params for method, params in notifications
                if method == "message" and isinstance(params, dict) and params.get("role") == "assistant"
            ]
            self.assertEqual(len(assistant_messages), 1)
            self.assertEqual(
                assistant_messages[0]["content"],
                "Evidence: `inspect_room` -> Room 0x45\n\nThe room has 3 sprites.",
            )
            state.session.close()

    async def test_handle_chat_builds_per_target_attachment_and_focus_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target_file = workspace / "src" / "main.asm"
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_text("lda #$01\n", encoding="utf-8")

            session_dir = workspace / "sessions"
            state = ServeState()
            state.workspace = workspace
            state.mode = "broadcast"
            small = ModelConfig(name="qwen3-oracle-8b", model_id="qwen3-oracle-8b")
            large = ModelConfig(name="oracle-pro", model_id="oracle-pro")
            state.models = {
                small.name: small,
                large.name: large,
            }
            state.active_model = small.name
            state.broadcast_models = [small.name, large.name]
            state.session = Session(session_dir)
            state.session.start(
                active_model=state.active_model,
                backend=state.backend_name,
                mode=state.mode,
                workspace=str(state.workspace),
                rom_path="",
                tools_enabled=state.tools_enabled,
                broadcast_models=state.broadcast_models,
            )

            class FakeEngine:
                def __init__(self) -> None:
                    self.bridge = None
                    self.chat_kwargs: dict | None = None

                def cancel(self) -> None:
                    return None

                async def chat(self, **kwargs):  # type: ignore[no-untyped-def]
                    self.chat_kwargs = dict(kwargs)
                    yield DoneEvent()

            engines = {
                small.name: FakeEngine(),
                large.name: FakeEngine(),
            }
            state.get_engine = lambda name: engines[name]  # type: ignore[method-assign]

            async def fake_add_context(
                attachments,  # type: ignore[no-untyped-def]
                *,
                bridge,
                model=None,
                lsp_context_mode="auto",
                prompt_query="",
            ):
                del bridge, lsp_context_mode, prompt_query
                assert model is not None
                return [
                    {
                        **item,
                        "context_pack": f"pack:{model.name}",
                    }
                    for item in attachments
                ]

            async def fake_add_construct_context(
                refs,  # type: ignore[no-untyped-def]
                *,
                bridge,
                workspace=None,
            ):
                del bridge, workspace
                return [
                    {
                        **item,
                        "context_pack": "room-pack",
                        "summary": "Room 0x45: Glacia Estate (Jail Cells)",
                    }
                    for item in refs
                ]

            with patch(
                "app.serve.resolve_targets_with_reason",
                return_value=([small, large], []),
            ), patch(
                "app.serve.ensure_targets_available",
            ), patch(
                "app.serve.resolve_request_model_name",
                side_effect=lambda _state, target: target.model_id,
            ), patch(
                "app.serve.add_attachment_context_packs",
                new=AsyncMock(side_effect=fake_add_context),
            ), patch(
                "app.serve.add_construct_context_packs",
                new=AsyncMock(side_effect=fake_add_construct_context),
            ), patch(
                "app.serve._resolve_focus_context",
                new=AsyncMock(side_effect=lambda _state, name, query="": f"# Focus: main.asm\n\nfocus:{name}"),
            ), patch(
                "app.serve._notify",
                side_effect=lambda method, params=None: None,
            ):
                await handle_chat(
                    state,
                    23,
                    {
                        "message": "Inspect @src/main.asm",
                        "construct_refs": [{"kind": "room", "query": "0x45"}],
                    },
                    request_id="req-23",
                )

            self.assertIsNotNone(engines[small.name].chat_kwargs)
            self.assertIsNotNone(engines[large.name].chat_kwargs)
            assert engines[small.name].chat_kwargs is not None
            assert engines[large.name].chat_kwargs is not None
            self.assertIn("Referenced game context:", engines[small.name].chat_kwargs["message"])
            self.assertIn("room-pack", engines[small.name].chat_kwargs["message"])
            self.assertIn("pack:qwen3-oracle-8b", engines[small.name].chat_kwargs["message"])
            self.assertIn("pack:oracle-pro", engines[large.name].chat_kwargs["message"])
            self.assertIn("focus:qwen3-oracle-8b", engines[small.name].chat_kwargs["system"])
            self.assertIn("focus:oracle-pro", engines[large.name].chat_kwargs["system"])

            assert state.session.path is not None
            data = state.session.path.read_text(encoding="utf-8")
            self.assertIn('"construct_refs"', data)
            self.assertIn("room-pack", data)
            self.assertIn("pack:qwen3-oracle-8b", data)
            self.assertIn("pack:oracle-pro", data)
            state.session.close()

    async def test_run_budgeted_chat_request_backpressures_when_saturated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            session_dir = workspace / "sessions"
            state = ServeState()
            state.workspace = workspace
            state.models = {
                "nayru": ModelConfig(name="nayru", model_id="nayru", role="analysis")
            }
            state.active_model = "nayru"
            state.session = Session(session_dir)
            state.session.start(
                active_model=state.active_model,
                backend=state.backend_name,
                mode=state.mode,
                workspace=str(state.workspace),
                rom_path="",
                tools_enabled=state.tools_enabled,
                broadcast_models=state.broadcast_models,
            )
            state.max_inflight_model_calls = 1
            state.exec_queue_depth = 0
            state.reconfigure_execution_budget()
            engine = CancelAwareEngine()
            state.get_engine = lambda _name: engine  # type: ignore[method-assign]

            responses: list[tuple[int, object, str | None]] = []
            with patch(
                "app.serve._respond",
                side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
            ), patch("app.serve.resolve_request_model_name", return_value="nayru"):
                first = asyncio.create_task(
                    run_budgeted_chat_request(state, {"message": "first"}, request_id="req_31", req_id=31)
                )
                await asyncio.wait_for(engine.started.wait(), timeout=1)
                await run_budgeted_chat_request(state, {"message": "second"}, request_id="req_32", req_id=32)
                engine.release.set()
                await asyncio.wait_for(first, timeout=1)

            self.assertTrue(any(req_id == 32 and error and "backpressure" in error.lower() for req_id, _result, error in responses))
            self.assertEqual(state.model_backpressure_count, 1)
            self.assertEqual(state.request_count, 2)
            self.assertEqual(state.request_success_count, 1)
            self.assertEqual(state.request_reject_count, 1)
            self.assertEqual(state.inflight_model_calls, 0)
            self.assertEqual(state.queued_model_calls, 0)
            state.session.close()

    async def test_run_budgeted_chat_request_cancels_specific_queued_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            session_dir = workspace / "sessions"
            state = ServeState()
            state.workspace = workspace
            state.models = {
                "nayru": ModelConfig(name="nayru", model_id="nayru", role="analysis")
            }
            state.active_model = "nayru"
            state.session = Session(session_dir)
            state.session.start(
                active_model=state.active_model,
                backend=state.backend_name,
                mode=state.mode,
                workspace=str(state.workspace),
                rom_path="",
                tools_enabled=state.tools_enabled,
                broadcast_models=state.broadcast_models,
            )
            state.max_inflight_model_calls = 1
            state.exec_queue_depth = 1
            state.reconfigure_execution_budget()
            engine = CancelAwareEngine()
            state.get_engine = lambda _name: engine  # type: ignore[method-assign]

            notifications: list[tuple[str, dict | None]] = []
            with patch("app.serve._notify", side_effect=lambda method, params=None: notifications.append((method, params))), patch(
                "app.serve.resolve_request_model_name",
                return_value="nayru",
            ):
                first = asyncio.create_task(
                    run_budgeted_chat_request(state, {"message": "first"}, request_id="req_41"),
                )
                await asyncio.wait_for(engine.started.wait(), timeout=1)

                second = asyncio.create_task(
                    run_budgeted_chat_request(state, {"message": "second"}, request_id="req_42"),
                )
                for _ in range(20):
                    if state.queued_model_calls >= 1:
                        break
                    await asyncio.sleep(0)
                self.assertGreaterEqual(state.queued_model_calls, 1)

                state.mark_request_cancelled("req_42")
                await asyncio.wait_for(second, timeout=2)

                engine.release.set()
                await asyncio.wait_for(first, timeout=2)

            cancelled_done = next(
                (
                    params
                    for method, params in notifications
                    if method == "done"
                    and isinstance(params, dict)
                    and params.get("request_id") == "req_42"
                ),
                None,
            )
            self.assertIsNotNone(cancelled_done)
            assert cancelled_done is not None
            self.assertEqual(cancelled_done.get("end_status"), "cancelled")
            self.assertEqual(engine.chat_calls, 1)
            self.assertEqual(state.request_count, 2)
            self.assertEqual(state.request_success_count, 1)
            self.assertEqual(state.request_cancel_count, 1)
            self.assertEqual(state.request_error_count, 0)
            self.assertEqual(state.request_reject_count, 0)
            self.assertEqual(state.inflight_model_calls, 0)
            self.assertEqual(state.queued_model_calls, 0)
            state.session.close()

    async def test_run_budgeted_chat_request_emits_structured_request_telemetry(self) -> None:
        state = ServeState()

        async def fake_run_chat(
            _state: ServeState,
            _req_id: int | None,
            _params: dict,
            *,
            request_id: str = "",
        ) -> tuple[str, int]:
            del _state, _req_id, _params, request_id
            await asyncio.sleep(0)
            return "success", 12

        with patch("app.serve.run_chat_request", side_effect=fake_run_chat), patch(
            "app.serve._emit_request_telemetry",
        ) as emit_telemetry:
            await run_budgeted_chat_request(
                state,
                {"message": "telemetry"},
                request_id="req-telemetry",
                req_id=91,
            )

        self.assertEqual(state.request_count, 1)
        self.assertEqual(state.request_success_count, 1)
        self.assertEqual(state.request_error_count, 0)
        self.assertEqual(state.request_reject_count, 0)
        self.assertEqual(state.request_cancel_count, 0)
        self.assertEqual(emit_telemetry.call_count, 1)
        kwargs = emit_telemetry.call_args.kwargs
        self.assertEqual(kwargs.get("request_id"), "req-telemetry")
        self.assertEqual(kwargs.get("end_status"), "success")
        self.assertGreaterEqual(int(kwargs.get("tool_ms", 0)), 0)
        self.assertGreaterEqual(int(kwargs.get("model_ms", 0)), 0)
        self.assertGreaterEqual(int(kwargs.get("total_ms", 0)), 0)

    async def test_tool_budget_backpressure_returns_inline_result(self) -> None:
        state = ServeState()
        state.max_inflight_tools = 1
        state.exec_queue_depth = 0
        state.reconfigure_execution_budget()

        base = BlockingToolBridge()
        bridge = state.apply_tool_budget(base)
        self.assertIsNotNone(bridge)
        assert bridge is not None

        first = asyncio.create_task(bridge.call_tool("sleep_tool", {}))
        await asyncio.wait_for(base.started.wait(), timeout=1)
        saturated = await bridge.call_tool("sleep_tool", {})
        self.assertIn("backpressure", saturated.lower())
        self.assertEqual(state.tool_backpressure_count, 1)

        base.release.set()
        done = await asyncio.wait_for(first, timeout=1)
        self.assertEqual(done, "ok")
        self.assertEqual(state.inflight_tool_calls, 0)
        self.assertEqual(state.queued_tool_calls, 0)

    async def test_handle_chat_emits_request_and_span_tracing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            session_dir = workspace / "sessions"
            state = ServeState()
            state.workspace = workspace
            state.models = {
                "nayru": ModelConfig(name="nayru", model_id="nayru", role="analysis")
            }
            state.active_model = "nayru"
            state.session = Session(session_dir)
            state.session.start(
                active_model=state.active_model,
                backend=state.backend_name,
                mode=state.mode,
                workspace=str(state.workspace),
                rom_path="",
                tools_enabled=state.tools_enabled,
                broadcast_models=state.broadcast_models,
            )
            state.get_engine = lambda _name: TraceToolEngine()  # type: ignore[method-assign]

            notifications: list[tuple[str, dict | None]] = []
            responses: list[tuple[int, object, str | None]] = []
            with patch("app.serve._notify", side_effect=lambda method, params=None: notifications.append((method, params))), patch(
                "app.serve._respond",
                side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
            ), patch("app.serve.resolve_request_model_name", return_value="nayru"):
                await handle_chat(state, 41, {"message": "trace this"}, request_id="req-41")

            tool_call = next(params for method, params in notifications if method == "tool_call")
            assert tool_call is not None
            self.assertEqual(tool_call.get("request_id"), "req-41")
            self.assertEqual(tool_call.get("span_id"), "req-41:nayru:1")
            self.assertEqual(tool_call.get("call_id"), "call-9")
            self.assertEqual(tool_call.get("tool_group"), "req-41:nayru:1:call-9")

            tool_result = next(params for method, params in notifications if method == "tool_result")
            assert tool_result is not None
            self.assertEqual(tool_result.get("request_id"), "req-41")
            self.assertEqual(tool_result.get("span_id"), "req-41:nayru:1")
            self.assertEqual(tool_result.get("tool_group"), "req-41:nayru:1:call-9")

            message = next(
                params for method, params in notifications
                if method == "message" and isinstance(params, dict) and params.get("role") == "assistant"
            )
            assert message is not None
            self.assertEqual(message.get("request_id"), "req-41")
            self.assertEqual(message.get("span_id"), "req-41:nayru:1")
            self.assertEqual(responses[-1], (41, {"ok": True}, None))
            state.session.close()

    async def test_tool_review_request_lists_asm_verification_plan(self) -> None:
        class FakeBridge:
            def get_openai_tools(self) -> list[dict]:
                return [
                    {
                        "type": "function",
                        "function": {
                            "name": "z3asm_lint",
                            "description": "",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    },
                    {
                        "type": "function",
                        "function": {
                            "name": "asm_patch_test",
                            "description": "",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    },
                ]

            async def call_tool(self, name: str, arguments: dict) -> str:
                del name, arguments
                return "{}"

            def get_tool_server(self, tool_name: str) -> str:
                del tool_name
                return "fake"

            @property
            def tool_count(self) -> int:
                return 2

            @property
            def server_names(self) -> list[str]:
                return ["fake"]

            @property
            def server_tool_counts(self) -> dict[str, int]:
                return {"fake": 2}

            async def close(self) -> None:
                return None

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = workspace / "src" / "main.asm"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("lda #$01\n", encoding="utf-8")
            config_dir = workspace / "config"
            config_dir.mkdir()
            (config_dir / "asm_verify.toml").write_text(
                'scenario = "sanctuary"\n'
                "frames = 16\n",
                encoding="utf-8",
            )

            state = ServeState()
            state.workspace = workspace
            state.bridge = FakeBridge()
            state.verify_hooks = True

            arguments = '{"path":"src/main.asm","edits":[{"oldText":"lda #$01\\n","newText":"lda #$02\\n"}]}'
            context = prepare_write_context(workspace, "edit_file", arguments, "call-verify")
            self.assertIsNotNone(context)
            assert context is not None
            state.pending_write_contexts["call-verify"] = context
            target.write_text("lda #$02\n", encoding="utf-8")

            notifications: list[tuple[str, dict | None]] = []
            responses: list[tuple[int, object, str | None]] = []
            with patch("app.serve._notify", side_effect=lambda method, params=None: notifications.append((method, params))), patch(
                "app.serve._respond",
                side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
            ):
                hook_task = asyncio.create_task(
                    state._post_tool_hook("edit_file", arguments, "tool wrote file", "afs", "call-verify")
                )

                review_params: dict | None = None
                for _ in range(20):
                    review_params = next(
                        (
                            params for method, params in notifications
                            if method == "tool/review_request" and isinstance(params, dict)
                        ),
                        None,
                    )
                    if review_params is not None:
                        break
                    await asyncio.sleep(0)

                self.assertIsNotNone(review_params)
                assert review_params is not None
                self.assertEqual(
                    review_params.get("verification_commands"),
                    [
                        "z3asm_lint src/main.asm",
                        "asm_patch_test src/main.asm --scenario sanctuary --frames 16",
                    ],
                )

                await handle_command(state, 77, {
                    "cmd": "tool/review",
                    "args": [state.pending_review_id, "reject"],
                })
                result = await asyncio.wait_for(hook_task, timeout=1)

            self.assertIn("rejected by user", result)
            self.assertEqual(target.read_text(encoding="utf-8"), "lda #$01\n")
            self.assertEqual(responses[-1], (77, {"accepted": False}, None))

    async def test_tool_review_reject_restores_files_and_unblocks_hook(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = workspace / "src" / "main.asm"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("lda #$01\n", encoding="utf-8")

            state = ServeState()
            state.workspace = workspace
            state.verify_hooks = False

            arguments = '{"path":"src/main.asm","edits":[{"oldText":"lda #$01\\n","newText":"lda #$02\\n"}]}'
            context = prepare_write_context(workspace, "edit_file", arguments, "call-1")
            self.assertIsNotNone(context)
            assert context is not None
            state.pending_write_contexts["call-1"] = context
            target.write_text("lda #$02\n", encoding="utf-8")

            notifications: list[tuple[str, dict | None]] = []
            responses: list[tuple[int, object, str | None]] = []

            with patch("app.serve._notify", side_effect=lambda method, params=None: notifications.append((method, params))), patch(
                "app.serve._respond",
                side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
            ):
                hook_task = asyncio.create_task(
                    state._post_tool_hook("edit_file", arguments, "tool wrote file", "afs", "call-1")
                )

                for _ in range(20):
                    if state.pending_review_id:
                        break
                    await asyncio.sleep(0)

                self.assertTrue(state.pending_review_id)
                await handle_command(state, 11, {
                    "cmd": "tool/review",
                    "args": [state.pending_review_id, "reject"],
                })
                result = await asyncio.wait_for(hook_task, timeout=1)

            self.assertEqual(target.read_text(encoding="utf-8"), "lda #$01\n")
            self.assertIn("rejected by user", result)
            self.assertTrue(any(method == "tool/review_request" for method, _params in notifications))
            self.assertEqual(responses[-1], (11, {"accepted": False}, None))

    async def test_export_training_can_opt_in_to_thinking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            session_dir = workspace / "sessions"
            state = ServeState()
            state.workspace = workspace
            state.session = Session(session_dir)
            state.session.start(
                active_model=state.active_model,
                backend=state.backend_name,
                mode=state.mode,
                workspace=str(workspace),
                rom_path="",
                tools_enabled=state.tools_enabled,
                broadcast_models=state.broadcast_models,
            )

            responses: list[tuple[int, object, str | None]] = []
            with patch("app.serve.export_training", return_value=1) as export_mock, patch(
                "app.serve._respond",
                side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
            ):
                await handle_command(state, 19, {
                    "cmd": "/export-training",
                    "args": ["out.jsonl", "--include-thinking"],
                })

            export_mock.assert_called_once()
            self.assertTrue(export_mock.call_args.kwargs["include_thinking"])
            result = responses[-1][1]
            self.assertTrue(result["include_thinking"])
            state.session.close()

    async def test_manual_subagent_command_enriches_prompt_with_z3lsp_attachment_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = workspace / "src" / "main.asm"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("lda #$01\nsta $7E0010\n", encoding="utf-8")

            state = ServeState()
            state.workspace = workspace
            state.bridge = FakeZ3LspBridge()
            state.models = {
                "nayru": ModelConfig(
                    name="nayru",
                    model_id="nayru",
                    provider="studio",
                    role="analysis",
                ),
            }

            runner = SubagentRunner()
            captured: dict[str, str] = {}

            async def fake_spawn(config, prompt, **kwargs):  # type: ignore[no-untyped-def]
                captured["model"] = config.model.name
                captured["prompt"] = prompt
                captured["system_context"] = str(kwargs.get("system_context", ""))
                return SubagentResult(
                    id="sub-1-nayru",
                    name=config.name,
                    model_name=config.model.name,
                    text="ok",
                )

            runner.spawn = fake_spawn  # type: ignore[assignment]
            state._subagent_runner = runner
            responses: list[tuple[int, object, str | None]] = []

            with patch(
                "app.serve._respond",
                side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
            ):
                await handle_command(state, 21, {
                    "cmd": "/subagent",
                    "args": ["nayru", "inspect", "@src/main.asm"],
                })

            self.assertEqual(captured["model"], "nayru")
            self.assertIn("@src/main.asm z3lsp", captured["prompt"])
            self.assertIn("serve pack for main.asm", captured["prompt"])
            self.assertIn("sta $7E0010", captured["prompt"])
            self.assertIn("Primary workspace:", captured["system_context"])
            self.assertEqual(responses[-1][2], None)
            self.assertEqual(responses[-1][1]["text"], "ok")

    async def test_manual_subagent_command_builds_model_aware_focus_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = workspace / "src" / "main.asm"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("lda #$01\n", encoding="utf-8")

            state = ServeState()
            state.workspace = workspace
            state.models = {
                "nayru": ModelConfig(
                    name="nayru",
                    model_id="nayru",
                    provider="studio",
                    role="analysis",
                ),
            }

            runner = SubagentRunner()
            captured: dict[str, str] = {}

            async def fake_spawn(config, prompt, **kwargs):  # type: ignore[no-untyped-def]
                del prompt
                captured["model"] = config.model.name
                captured["system_context"] = str(kwargs.get("system_context", ""))
                return SubagentResult(
                    id="sub-1-nayru",
                    name=config.name,
                    model_name=config.model.name,
                    text="ok",
                )

            runner.spawn = fake_spawn  # type: ignore[assignment]
            state._subagent_runner = runner
            state.focus_path = target
            state.focus_context = "# Focus: main.asm\n\nstale-focus"

            responses: list[tuple[int, object, str | None]] = []
            resolve_focus = AsyncMock(return_value="# Focus: main.asm\n\nfocus:nayru")
            with patch(
                "app.serve._resolve_focus_context",
                new=resolve_focus,
            ), patch(
                "app.serve._respond",
                side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
            ):
                await handle_command(state, 22, {
                    "cmd": "/subagent",
                    "args": ["nayru", "inspect", "Link_Main"],
                })

            self.assertEqual(captured["model"], "nayru")
            self.assertIn("focus:nayru", captured["system_context"])
            self.assertNotIn("stale-focus", captured["system_context"])
            resolve_focus.assert_awaited_once_with(state, "nayru", query="inspect Link_Main")
            self.assertEqual(responses[-1][2], None)
            self.assertEqual(responses[-1][1]["text"], "ok")

    async def test_lsp_context_command_updates_ready_payload(self) -> None:
        state = ServeState()
        state.models = {
            "oracle": ModelConfig(name="oracle", model_id="oracle", role="planner"),
        }

        responses: list[tuple[int, object, str | None]] = []
        notifications: list[tuple[str, dict | None]] = []
        with patch(
            "app.serve._respond",
            side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
        ), patch(
            "app.serve._notify",
            side_effect=lambda method, params=None: notifications.append((method, params)),
        ):
            await handle_command(state, 31, {"cmd": "/lsp-context", "args": ["off"]})
            if state.ready_refresh_task is not None:
                await state.ready_refresh_task

        self.assertEqual(state.lsp_context_mode, "off")
        self.assertEqual(responses[-1][1]["mode"], "off")
        ready = notifications[-1][1]
        assert isinstance(ready, dict)
        self.assertEqual(ready.get("lsp_context_mode"), "off")

    async def test_tool_review_wait_unblocks_on_cancel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = workspace / "src" / "main.asm"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("lda #$01\n", encoding="utf-8")

            state = ServeState()
            state.workspace = workspace
            state.verify_hooks = False

            arguments = '{"path":"src/main.asm","edits":[{"oldText":"lda #$01\\n","newText":"lda #$02\\n"}]}'
            context = prepare_write_context(workspace, "edit_file", arguments, "call-2")
            self.assertIsNotNone(context)
            assert context is not None
            state.pending_write_contexts["call-2"] = context
            target.write_text("lda #$02\n", encoding="utf-8")

            notifications: list[tuple[str, dict | None]] = []
            with patch("app.serve._notify", side_effect=lambda method, params=None: notifications.append((method, params))):
                hook_task = asyncio.create_task(
                    state._post_tool_hook("edit_file", arguments, "tool wrote file", "afs", "call-2")
                )

                for _ in range(20):
                    if state.pending_review_id:
                        break
                    await asyncio.sleep(0)

                self.assertTrue(state.pending_review_id)
                state.cancel_requested = True
                state.cancel_pending_prompts()
                result = await asyncio.wait_for(hook_task, timeout=1)

            self.assertEqual(target.read_text(encoding="utf-8"), "lda #$01\n")
            self.assertIn("rejected by user", result)
            self.assertTrue(any(method == "tool/review_request" for method, _params in notifications))

    async def test_compact_command_uses_engine_compactor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            session_dir = workspace / "sessions"
            state = ServeState()
            state.workspace = workspace
            state.models = {
                "nayru": ModelConfig(name="nayru", model_id="nayru", role="analysis")
            }
            state.active_model = "nayru"
            state.session = Session(session_dir)
            state.session.start(
                active_model=state.active_model,
                backend=state.backend_name,
                mode=state.mode,
                workspace=str(state.workspace),
                rom_path="",
                tools_enabled=state.tools_enabled,
                broadcast_models=state.broadcast_models,
            )
            engine = CompactingEngine()
            state.get_engine = lambda _name: engine  # type: ignore[method-assign]

            notifications: list[tuple[str, dict | None]] = []
            responses: list[tuple[int, object, str | None]] = []

            with patch("app.serve._notify", side_effect=lambda method, params=None: notifications.append((method, params))), patch(
                "app.serve._respond",
                side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
            ):
                await handle_command(state, 17, {"cmd": "/compact", "args": []})

            self.assertEqual(engine.calls, 1)
            self.assertTrue(any(method == "context/compacted" for method, _params in notifications))
            self.assertEqual(
                responses[-1],
                (17, {"compacted": True, "model": "nayru", "replaced": 5, "tokens_before": 2048, "tokens_after": 512}, None),
            )
            state.session.close()

    async def test_serve_main_chat_ack_returns_request_id_before_task_dispatch(self) -> None:
        state = ServeState()
        reader = asyncio.StreamReader()
        reader.feed_data(_rpc_lines(
            {"jsonrpc": "2.0", "id": 11, "method": "chat", "params": {"message": "hello"}},
            {"jsonrpc": "2.0", "method": "shutdown"},
        ))
        reader.feed_eof()
        loop = FakeServeLoop()
        order: list[str] = []
        responses: list[tuple[int, object, str | None]] = []

        async def fake_init(_args: list[str], **_kwargs) -> ServeState:
            return state

        async def fake_run_budgeted(
            _state: ServeState,
            _params: dict,
            *,
            request_id: str,
            req_id: int | None = None,
        ) -> None:
            del _state, _params, req_id, request_id
            return None

        real_create_task = asyncio.create_task

        def traced_create_task(coro):  # type: ignore[no-untyped-def]
            order.append("create_task")
            return real_create_task(coro)

        def traced_respond(req_id: int, result=None, error=None):  # type: ignore[no-untyped-def]
            order.append("respond")
            responses.append((req_id, result, error))

        with patch("app.serve.init_state", side_effect=fake_init), patch(
            "app.serve.run_budgeted_chat_request",
            side_effect=fake_run_budgeted,
        ), patch("app.serve._notify"), patch(
            "app.serve._respond",
            side_effect=traced_respond,
        ), patch("app.serve.asyncio.StreamReader", return_value=reader), patch(
            "app.serve.asyncio.StreamReaderProtocol",
            side_effect=lambda _reader: object(),
        ), patch("app.serve.asyncio.get_event_loop", return_value=loop), patch(
            "app.serve.asyncio.create_task",
            side_effect=traced_create_task,
        ):
            await serve_main([])

        self.assertTrue(responses)
        self.assertEqual(responses[0], (11, {"accepted": True, "request_id": "req-1"}, None))
        self.assertGreaterEqual(len(order), 2)
        self.assertEqual(order[0], "respond")
        self.assertEqual(order[1], "create_task")

    async def test_serve_main_cancel_with_request_id_targets_requested_chat(self) -> None:
        state = ServeState()
        reader = asyncio.StreamReader()
        reader.feed_data(_rpc_lines(
            {"jsonrpc": "2.0", "id": 21, "method": "chat", "params": {"message": "first"}},
            {"jsonrpc": "2.0", "id": 22, "method": "chat", "params": {"message": "second"}},
            {"jsonrpc": "2.0", "method": "cancel", "params": {"request_id": "req-1"}},
            {"jsonrpc": "2.0", "method": "shutdown"},
        ))
        reader.feed_eof()
        loop = FakeServeLoop()
        responses: list[tuple[int, object, str | None]] = []

        async def fake_init(_args: list[str], **_kwargs) -> ServeState:
            return state

        async def fake_run_budgeted(
            running_state: ServeState,
            _params: dict,
            *,
            request_id: str,
            req_id: int | None = None,
        ) -> None:
            del _params, req_id
            while not running_state.is_request_cancelled(request_id):
                await asyncio.sleep(0)

        with patch("app.serve.init_state", side_effect=fake_init), patch(
            "app.serve.run_budgeted_chat_request",
            side_effect=fake_run_budgeted,
        ), patch("app.serve._notify"), patch(
            "app.serve._respond",
            side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
        ), patch("app.serve.asyncio.StreamReader", return_value=reader), patch(
            "app.serve.asyncio.StreamReaderProtocol",
            side_effect=lambda _reader: object(),
        ), patch("app.serve.asyncio.get_event_loop", return_value=loop), patch.object(
            state,
            "mark_request_cancelled",
            wraps=state.mark_request_cancelled,
        ) as mark_cancelled:
            await serve_main([])

        self.assertEqual(
            responses[:2],
            [
                (21, {"accepted": True, "request_id": "req-1"}, None),
                (22, {"accepted": True, "request_id": "req-2"}, None),
            ],
        )
        cancel_calls = [call.args[0] for call in mark_cancelled.call_args_list]
        self.assertTrue(cancel_calls)
        self.assertEqual(cancel_calls[0], "req-1")

    async def test_serve_main_cancel_without_request_id_targets_latest_active(self) -> None:
        state = ServeState()
        reader = asyncio.StreamReader()
        reader.feed_data(_rpc_lines(
            {"jsonrpc": "2.0", "id": 31, "method": "chat", "params": {"message": "first"}},
            {"jsonrpc": "2.0", "id": 32, "method": "chat", "params": {"message": "second"}},
            {"jsonrpc": "2.0", "method": "cancel"},
            {"jsonrpc": "2.0", "method": "shutdown"},
        ))
        reader.feed_eof()
        loop = FakeServeLoop()

        async def fake_init(_args: list[str], **_kwargs) -> ServeState:
            return state

        async def fake_run_budgeted(
            running_state: ServeState,
            _params: dict,
            *,
            request_id: str,
            req_id: int | None = None,
        ) -> None:
            del _params, req_id
            while not running_state.is_request_cancelled(request_id):
                await asyncio.sleep(0)

        with patch("app.serve.init_state", side_effect=fake_init), patch(
            "app.serve.run_budgeted_chat_request",
            side_effect=fake_run_budgeted,
        ), patch("app.serve._notify"), patch(
            "app.serve._respond",
        ), patch("app.serve.asyncio.StreamReader", return_value=reader), patch(
            "app.serve.asyncio.StreamReaderProtocol",
            side_effect=lambda _reader: object(),
        ), patch("app.serve.asyncio.get_event_loop", return_value=loop), patch.object(
            state,
            "mark_request_cancelled",
            wraps=state.mark_request_cancelled,
        ) as mark_cancelled:
            await serve_main([])

        cancel_calls = [call.args[0] for call in mark_cancelled.call_args_list]
        self.assertTrue(cancel_calls)
        self.assertEqual(cancel_calls[0], "req-2")

    async def test_stats_reports_retry_and_tool_timeout_metrics(self) -> None:
        state = ServeState()
        state.model_retry_count = 4
        state.model_retry_backoff_ms = 2750
        state.model_error_count = 2
        state.tool_timeout_count = 3
        state.model_backpressure_count = 1
        state.tool_backpressure_count = 2
        state.max_inflight_model_calls = 2
        state.max_inflight_tools = 3
        state.exec_queue_depth = 5
        state.inflight_model_calls = 1
        state.queued_model_calls = 2
        state.inflight_tool_calls = 1
        state.queued_tool_calls = 1
        state.request_count = 10
        state.request_success_count = 8
        state.request_error_count = 1
        state.request_reject_count = 1
        state.request_cancel_count = 1
        state.span_count = 13
        state.last_request_id = "req-10"
        state.last_span_id = "req-10:nayru:1"
        state.last_tool_call_id = "call-200"
        state.request_queued_ms_samples = [10, 20, 30, 40]
        state.request_model_ms_samples = [50, 60, 70, 80]
        state.request_tool_ms_samples = [5, 15, 25, 35]
        state.request_total_ms_samples = [60, 80, 110, 130]
        state.last_request_status = "cancelled"
        state.last_request_queued_ms = 40
        state.last_request_model_ms = 80
        state.last_request_tool_ms = 35
        state.last_request_total_ms = 130
        state.model_retry_max = 5
        state.model_retry_backoff_base_s = 0.5
        state.tool_exec_timeout_s = 90.0

        responses: list[tuple[int, object, str | None]] = []
        with patch(
            "app.serve._respond",
            side_effect=lambda req_id, result=None, error=None: responses.append((req_id, result, error)),
        ):
            await handle_command(state, 23, {"cmd": "/stats", "args": []})

        self.assertTrue(responses)
        req_id, result, error = responses[-1]
        self.assertEqual(req_id, 23)
        self.assertIsNone(error)
        payload = result if isinstance(result, dict) else {}
        self.assertEqual(payload.get("model_retry_count"), 4)
        self.assertEqual(payload.get("model_retry_backoff_ms"), 2750)
        self.assertEqual(payload.get("model_error_count"), 2)
        self.assertEqual(payload.get("model_alias_resolutions"), 0)
        self.assertEqual(payload.get("model_lookup_failures"), 0)
        self.assertEqual(payload.get("model_request_counts"), {})
        self.assertEqual(payload.get("tool_timeout_count"), 3)
        self.assertEqual(payload.get("model_backpressure_count"), 1)
        self.assertEqual(payload.get("tool_backpressure_count"), 2)
        self.assertEqual(payload.get("max_inflight_model_calls"), 2)
        self.assertEqual(payload.get("max_inflight_tools"), 3)
        self.assertEqual(payload.get("exec_queue_depth"), 5)
        self.assertEqual(payload.get("inflight_model_calls"), 1)
        self.assertEqual(payload.get("queued_model_calls"), 2)
        self.assertEqual(payload.get("inflight_tool_calls"), 1)
        self.assertEqual(payload.get("queued_tool_calls"), 1)
        self.assertEqual(payload.get("request_count"), 10)
        self.assertEqual(payload.get("request_success_count"), 8)
        self.assertEqual(payload.get("request_error_count"), 1)
        self.assertEqual(payload.get("request_reject_count"), 1)
        self.assertEqual(payload.get("request_cancel_count"), 1)
        self.assertEqual(payload.get("span_count"), 13)
        self.assertEqual(payload.get("last_request_id"), "req-10")
        self.assertEqual(payload.get("last_span_id"), "req-10:nayru:1")
        self.assertEqual(payload.get("last_tool_call_id"), "call-200")
        self.assertEqual(payload.get("request_samples"), 4)
        self.assertEqual(payload.get("queued_ms_p50"), 20)
        self.assertEqual(payload.get("queued_ms_p95"), 40)
        self.assertEqual(payload.get("model_ms_p50"), 60)
        self.assertEqual(payload.get("model_ms_p95"), 80)
        self.assertEqual(payload.get("tool_ms_p50"), 15)
        self.assertEqual(payload.get("tool_ms_p95"), 35)
        self.assertEqual(payload.get("total_ms_p50"), 80)
        self.assertEqual(payload.get("total_ms_p95"), 130)
        self.assertEqual(payload.get("last_request_status"), "cancelled")
        self.assertEqual(payload.get("last_request_queued_ms"), 40)
        self.assertEqual(payload.get("last_request_model_ms"), 80)
        self.assertEqual(payload.get("last_request_tool_ms"), 35)
        self.assertEqual(payload.get("last_request_total_ms"), 130)
        self.assertEqual(payload.get("model_retry_max"), 5)
        self.assertEqual(payload.get("model_retry_base_ms"), 500)
        self.assertEqual(payload.get("tool_exec_timeout_s"), 90.0)


if __name__ == "__main__":
    unittest.main()
