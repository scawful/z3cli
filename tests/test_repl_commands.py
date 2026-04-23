import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from rich.console import Console

from z3cli.app.repl import AppState, _post_tool_hook, build_state, handle_command, send_prompt, stream_response
from z3cli.app.shell_session import PersistentShellSession
from z3cli.app.write_review import prepare_write_context
from z3cli.core.config import LlamaCppNodeConfig, ModelConfig, RouterConfig, StudioNodeConfig
from z3cli.core.engine import CompactionEvent, DoneEvent


def _model(name: str, *, role: str = "", tool_profile: str = "") -> ModelConfig:
    return ModelConfig(
        name=name,
        model_id=name,
        role=role,
        tools_enabled=True,
        tool_profile=tool_profile,
    )


def _state() -> AppState:
    models = {
        "oracle-main-plan": _model("oracle-main-plan", role="plan"),
        "oracle-main-act": _model("oracle-main-act", role="act"),
        "farore": _model("farore", tool_profile="farore"),
        "oracle": _model("oracle", role="planner"),
        "oracle-pro": _model("oracle-pro", role="pro"),
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
        routers={"oracle": RouterConfig(name="oracle", router_type="keyword", default="farore")},
        active_model="oracle-main-plan",
        mode="manual",
        auto_load=True,
        auto_start_server=True,
        workspace=Path("/tmp"),
        rom_path=None,
        temperature=0.2,
        max_tokens=1024,
        broadcast_models=["farore"],
        tools_enabled=True,
    )


class ReplCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_state_applies_studio_node_model_on_startup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = root / "chat_registry.toml"
            mcp = root / "mcp.json"
            workspace = root / "workspace"
            workspace.mkdir()
            registry.write_text(
                """
[[models]]
name = "oracle"
provider = "studio"
model_id = "qwen3-oracle-14b-v1"

[[models]]
name = "oracle-pro"
provider = "studio"
model_id = "gguf/zelda/qwen3-oracle-14b-v7-q4km.gguf"

[[studio_nodes]]
                name = "oracle-pro-home"
                api_base = "http://127.0.0.1:2234/v1"
                model = "oracle-pro"
                description = "Windows tunnel"
                hostd_url = "http://127.0.0.1:8766"
""".strip(),
                encoding="utf-8",
            )
            mcp.write_text("{}", encoding="utf-8")
            args = SimpleNamespace(
                registry=str(registry),
                mcp_config=str(mcp),
                backend="studio",
                host="127.0.0.1",
                port=1234,
                studio_api_base="http://127.0.0.1:1234/v1",
                studio_node="oracle-pro-home",
                llamacpp_api_base="http://127.0.0.1:8080/v1",
                llamacpp_model="oracle-fast",
                llamacpp_node="",
                workspace=str(workspace),
                rom="",
                model="oracle",
                model_explicit=False,
                mode="manual",
                broadcast_models="",
                temperature=0.2,
                max_tokens=256,
                tools=False,
                lsp_context="auto",
                auto_load=True,
                auto_start_server=False,
                list_models=False,
                list_loaded=False,
                status=False,
                route_only=False,
                prompt="",
            )

            state = await build_state(args)

        self.assertEqual(state.studio_node, "oracle-pro-home")
        self.assertEqual(state.backend_name, "studio")
        self.assertEqual(state.studio_api_base, "http://127.0.0.1:2234/v1")
        self.assertEqual(state.active_model, "oracle-pro")

    async def test_studio_node_command_switches_named_endpoint(self) -> None:
        state = _state()
        state.studio_nodes = {
            "oracle-pro-home": StudioNodeConfig(
                name="oracle-pro-home",
                api_base="http://127.0.0.1:2234/v1",
                model="oracle-pro",
                description="Windows tunnel",
                hostd_url="http://127.0.0.1:8766",
            ),
        }

        with patch.dict("os.environ", {}, clear=False):
            handled = await handle_command(state, "/studio-node oracle-pro-home")

            self.assertTrue(handled)
            self.assertEqual(state.studio_node, "oracle-pro-home")
            self.assertEqual(state.studio_api_base, "http://127.0.0.1:2234/v1")
            self.assertEqual(state.backend_name, "studio")
            self.assertEqual(state.active_model, "oracle-pro")
            self.assertEqual(os.environ.get("Z3CLI_LMSTUDIO_HOSTD_URL"), "http://127.0.0.1:8766")
            self.assertIn("studio node set to oracle-pro-home", state.console.export_text())

    async def test_use_command_switches_to_home_alias(self) -> None:
        state = _state()
        state.studio_nodes = {
            "oracle-pro-home": StudioNodeConfig(
                name="oracle-pro-home",
                api_base="http://127.0.0.1:2234/v1",
                model="oracle-pro",
                description="Windows tunnel",
                hostd_url="http://127.0.0.1:8766",
            ),
        }

        with patch.dict("os.environ", {}, clear=False):
            handled = await handle_command(state, "/use home")

            self.assertTrue(handled)
            self.assertEqual(state.backend_name, "studio")
            self.assertEqual(state.studio_node, "oracle-pro-home")
            self.assertEqual(state.active_model, "oracle-pro")
            self.assertEqual(os.environ.get("Z3CLI_LMSTUDIO_HOSTD_URL"), "http://127.0.0.1:8766")
            self.assertIn("Using studio (oracle-pro-home) as oracle-pro", state.console.export_text())

    async def test_llamacpp_node_command_switches_named_endpoint(self) -> None:
        state = _state()
        state.llamacpp_nodes = {
            "oracle-pro-vast": LlamaCppNodeConfig(
                name="oracle-pro-vast",
                api_base="http://127.0.0.1:18080/v1",
                model="oracle-pro",
                description="SSH tunnel",
            ),
        }

        handled = await handle_command(state, "/llamacpp-node oracle-pro-vast")

        self.assertTrue(handled)
        self.assertEqual(state.llamacpp_node, "oracle-pro-vast")
        self.assertEqual(state.llamacpp_api_base, "http://127.0.0.1:18080/v1")
        self.assertEqual(state.llamacpp_model, "oracle-pro")
        self.assertEqual(state.backend_name, "llamacpp")
        self.assertIn("llama.cpp node set to oracle-pro-vast", state.console.export_text())

    async def test_lsp_context_command_updates_mode(self) -> None:
        state = _state()

        handled = await handle_command(state, "/lsp-context rich")

        self.assertTrue(handled)
        self.assertEqual(state.lsp_context_mode, "rich")
        self.assertIn("LSP context set to rich", state.console.export_text())

    async def test_send_prompt_starts_session_for_one_shot_mode(self) -> None:
        state = _state()

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp)
            with (
                patch("z3cli.app.repl.SESSION_DIR", session_dir),
                patch("z3cli.app.repl.preview_targets", return_value=[SimpleNamespace(name="farore")]),
                patch("z3cli.app.repl.ensure_targets_available"),
                patch("z3cli.app.repl.stream_response", new=AsyncMock()),
            ):
                await send_prompt(state, "Inspect the workspace.")
                self.assertIsNotNone(state.session)
                assert state.session is not None
                self.assertIsNotNone(state.session.path)
                assert state.session.path is not None
                self.assertTrue(state.session.path.exists())
                data = state.session.path.read_text(encoding="utf-8")
                self.assertIn('"content": "Inspect the workspace."', data)
                self.assertIn('"display_content": "Inspect the workspace."', data)
                state.session.close()

    async def test_send_prompt_builds_per_target_attachment_and_focus_context(self) -> None:
        state = _state()
        state.mode = "broadcast"

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target_file = workspace / "src" / "main.asm"
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_text("lda #$01\n", encoding="utf-8")
            state.workspace = workspace

            session_dir = workspace / "sessions"
            small = ModelConfig(name="qwen3-oracle-8b", model_id="qwen3-oracle-8b")
            large = ModelConfig(name="oracle-pro", model_id="oracle-pro")
            state.models[small.name] = small
            state.models[large.name] = large

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

            with (
                patch("z3cli.app.repl.SESSION_DIR", session_dir),
                patch("z3cli.app.repl.preview_targets", return_value=[small, large]),
                patch("z3cli.app.repl.ensure_targets_available"),
                patch("z3cli.app.repl.add_attachment_context_packs", new=AsyncMock(side_effect=fake_add_context)),
                patch(
                    "z3cli.app.repl._resolve_focus_context",
                    new=AsyncMock(side_effect=lambda _state, name, query="": f"# Focus: main.asm\n\nfocus:{name}"),
                ),
                patch("z3cli.app.repl.stream_response", new=AsyncMock()) as stream_mock,
            ):
                await send_prompt(state, "Inspect @src/main.asm")

            self.assertEqual(stream_mock.await_count, 2)
            first_call = stream_mock.await_args_list[0]
            second_call = stream_mock.await_args_list[1]
            self.assertIn("pack:qwen3-oracle-8b", first_call.args[2])
            self.assertIn("pack:oracle-pro", second_call.args[2])
            self.assertEqual(first_call.kwargs["focus_context"], "# Focus: main.asm\n\nfocus:qwen3-oracle-8b")
            self.assertEqual(second_call.kwargs["focus_context"], "# Focus: main.asm\n\nfocus:oracle-pro")

            assert state.session is not None
            assert state.session.path is not None
            data = state.session.path.read_text(encoding="utf-8")
            self.assertIn("pack:qwen3-oracle-8b", data)
            self.assertIn("pack:oracle-pro", data)
            state.session.close()

    async def test_resume_without_name_lists_saved_sessions(self) -> None:
        state = _state()

        with patch(
            "z3cli.app.repl.list_sessions",
            return_value=[
                {
                    "name": "saved",
                    "backend": "studio",
                    "active_model": "oracle",
                    "mode": "manual",
                    "messages": 4,
                    "started": "2026-04-17T12:34:56+00:00",
                },
            ],
        ):
            handled = await handle_command(state, "/resume")

        self.assertTrue(handled)
        output = state.console.export_text()
        self.assertIn("Sessions", output)
        self.assertIn("saved", output)

    async def test_stream_response_honors_deferred_tool_config(self) -> None:
        state = _state()
        target = ModelConfig(
            name="qwen3-oracle-8b",
            model_id="gguf/zelda/qwen3-oracle-8b-v1-corrective2-q8_0.gguf",
            role="shared oracle qwen3 model",
            tools_enabled=True,
            deferred_tools=True,
            native_tools=False,
            core_tools=["read_context"],
            max_tokens=256,
        )

        class FakeEngine:
            def __init__(self) -> None:
                self.bridge = None
                self.chat_kwargs: dict | None = None

            async def chat(self, **kwargs):  # type: ignore[no-untyped-def]
                self.chat_kwargs = dict(kwargs)
                yield DoneEvent()

        fake_engine = FakeEngine()
        wrapped_bridge = object()

        with patch("z3cli.app.repl._resolve_request_model_name", return_value=target.model_id), patch(
            "z3cli.app.repl.get_engine",
            return_value=fake_engine,
        ), patch(
            "z3cli.app.repl.wrap_bridge_for_model",
            return_value=wrapped_bridge,
        ) as wrap_bridge:
            await stream_response(state, target, "Reply READY.")

        wrap_bridge.assert_called_once_with(
            state.bridge,
            target.tool_profile,
            read_only=True,
            deferred_tools=True,
            core_tools=["read_context"],
        )
        self.assertIs(fake_engine.bridge, wrapped_bridge)
        self.assertIsNotNone(fake_engine.chat_kwargs)
        assert fake_engine.chat_kwargs is not None
        self.assertFalse(fake_engine.chat_kwargs["use_tools"])

    async def test_stream_response_injects_oracle_coder_prompt_for_oracle_fast(self) -> None:
        state = _state()
        state.models["oracle-fast"] = ModelConfig(
            name="oracle-fast",
            model_id="oracle-fast",
            role="fast local model",
            tools_enabled=True,
        )
        state.models["oracle-coder"] = ModelConfig(
            name="oracle-coder",
            model_id="qwen25-oracle-coder-7b-v1",
            role="internal coding worker",
            tags=["oracle"],
            visibility="hidden",
            spawn_only=True,
            spawnable_by=["oracle", "oracle-fast"],
            tools_enabled=True,
        )
        target = state.models["oracle-fast"]

        class FakeEngine:
            def __init__(self) -> None:
                self.bridge = None
                self.chat_kwargs: dict | None = None

            async def chat(self, **kwargs):  # type: ignore[no-untyped-def]
                self.chat_kwargs = dict(kwargs)
                yield DoneEvent()

        fake_engine = FakeEngine()

        with patch("z3cli.app.repl._resolve_request_model_name", return_value=target.model_id), patch(
            "z3cli.app.repl.get_engine",
            return_value=fake_engine,
        ):
            await stream_response(state, target, "repair this asm hook", target_count=1)

        self.assertIsNotNone(fake_engine.chat_kwargs)
        assert fake_engine.chat_kwargs is not None
        self.assertIn(
            "Delegate the code-writing pass to `spawn_subagent` with model `oracle-coder`",
            fake_engine.chat_kwargs["system"],
        )
        self.assertIn("Quality-first policy", fake_engine.chat_kwargs["system"])

    async def test_stream_response_injects_oracle_natural_chat_prompt_for_oracle_pro(self) -> None:
        state = _state()
        target = state.models["oracle-pro"]

        class FakeEngine:
            def __init__(self) -> None:
                self.bridge = None
                self.chat_kwargs: dict | None = None

            async def chat(self, **kwargs):  # type: ignore[no-untyped-def]
                self.chat_kwargs = dict(kwargs)
                yield DoneEvent()

        fake_engine = FakeEngine()

        with patch("z3cli.app.repl._resolve_request_model_name", return_value=target.model_id), patch(
            "z3cli.app.repl.get_engine",
            return_value=fake_engine,
        ):
            await stream_response(state, target, "minecart is weird", target_count=1)

        self.assertIsNotNone(fake_engine.chat_kwargs)
        assert fake_engine.chat_kwargs is not None
        self.assertIn("The user may speak casually, tersely, or by implication.", fake_engine.chat_kwargs["system"])
        self.assertIn("exactly one short clarifying question", fake_engine.chat_kwargs["system"])

    async def test_post_tool_hook_appends_asm_verification_results(self) -> None:
        class FakeBridge:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict]] = []

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
                self.calls.append((name, dict(arguments)))
                if name == "z3asm_lint":
                    return json.dumps({"lint.json": {"ok": True}})
                if name == "asm_patch_test":
                    return json.dumps({"ok": True, "failure_stage": None})
                return "{}"

            def get_tool_server(self, tool_name: str) -> str:
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

        state = _state()
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            patch_path = workspace / "src" / "main.asm"
            patch_path.parent.mkdir(parents=True, exist_ok=True)
            patch_path.write_text("lda #$01\n", encoding="utf-8")
            rom_path = workspace / "oracle.sfc"
            rom_path.write_bytes(b"\xAA" * 64)
            config_dir = workspace / "config"
            config_dir.mkdir()
            (config_dir / "asm_verify.toml").write_text(
                'scenario = "sanctuary"\n'
                "frames = 12\n",
                encoding="utf-8",
            )

            arguments = '{"path":"src/main.asm","edits":[{"oldText":"lda #$01\\n","newText":"lda #$02\\n"}]}'
            context = prepare_write_context(workspace, "edit_file", arguments, "call-1")
            self.assertIsNotNone(context)
            assert context is not None

            state.workspace = workspace
            state.rom_path = rom_path
            state.bridge = FakeBridge()
            state.pending_write_contexts["call-1"] = context
            patch_path.write_text("lda #$02\n", encoding="utf-8")

            result = await _post_tool_hook(state, "edit_file", arguments, "tool wrote file", "afs", "call-1")

        self.assertIn("Filesystem diff auto-accepted in REPL.", result)
        self.assertIn("Verification:", result)
        self.assertIn("z3asm_lint src/main.asm", result)
        self.assertIn("asm_patch_test src/main.asm --scenario sanctuary --frames 12", result)

    async def test_verify_hooks_command_toggles_state(self) -> None:
        state = _state()

        await handle_command(state, "/verify-hooks off")

        self.assertFalse(state.verify_hooks)
        self.assertIn("verification hooks: false", state.console.export_text().lower())

    async def test_permissions_command_lists_and_clears_rules(self) -> None:
        state = _state()
        state.permission_rules = {
            "filesystem:write_file": True,
            "network:fetch": False,
        }

        await handle_command(state, "/permissions")
        output = state.console.export_text().lower()
        self.assertIn("allow: filesystem:write_file", output)
        self.assertIn("deny: network:fetch", output)

        await handle_command(state, "/permissions clear")
        self.assertEqual(state.permission_rules, {})
        self.assertIn("permission rules cleared", state.console.export_text().lower())

    async def test_shell_commands_work_in_repl(self) -> None:
        state = _state()
        state.shell = PersistentShellSession(state.workspace, shell="/bin/sh")
        try:
            await handle_command(state, "/shell pwd")
            await handle_command(state, "/shell-log 1")
            text = state.console.export_text().lower()
            self.assertIn("/tmp", text)
            self.assertIn("$ pwd", text)

            await handle_command(state, "/shell-reset")
            self.assertIsNone(state.shell)
        finally:
            if state.shell is not None:
                await state.shell.close()

    async def test_compact_uses_configured_compactor(self) -> None:
        state = _state()

        class CompactingEngine:
            def __init__(self) -> None:
                self.compactor = object()
                self.calls = 0

            async def compact_now(self, force: bool = False) -> CompactionEvent | None:
                self.calls += 1
                return CompactionEvent(
                    summary="summary",
                    replaced_count=4,
                    tokens_before=1200,
                    tokens_after=300,
                )

        engine = CompactingEngine()
        with patch("z3cli.app.repl.get_engine", return_value=engine):
            await handle_command(state, "/compact farore")

        self.assertEqual(engine.calls, 1)
        self.assertIn("Compacted 4 messages (1200 -> 300 tokens).", state.console.export_text())

    async def test_load_command_uses_backend_resolution(self) -> None:
        state = _state()

        class FakeBackend:
            def __init__(self) -> None:
                self.calls: list[tuple[str, bool, bool]] = []

            def resolve_request_model(
                self,
                target: ModelConfig,
                auto_load: bool = True,
                *,
                manual_load: bool = False,
            ) -> str:
                self.calls.append((target.name, auto_load, manual_load))
                return target.name

        backend = FakeBackend()
        with patch("z3cli.app.repl.get_backend", return_value=backend):
            await handle_command(state, "/load oracle-main-plan")

        self.assertEqual(backend.calls, [("oracle-main-plan", True, True)])
        self.assertIn("Loaded oracle-main-plan as oracle-main-plan", state.console.export_text())

    async def test_help_mentions_oracle_pro_manual_heavy_model(self) -> None:
        state = _state()

        await handle_command(state, "/help")

        output = state.console.export_text().lower()
        self.assertIn("quest & navigation", output)
        self.assertIn("#kind:query", output)
        self.assertIn("/lsp-context [mode]", output)
        self.assertIn("/unload [name|all]", output)
        self.assertIn("oracle-pro", output)
        self.assertIn("manual-heavy model", output)

    async def test_oracle_tips_command_prints_local_oracle_cheat_sheet(self) -> None:
        state = _state()

        await handle_command(state, "/oracle-tips")

        output = state.console.export_text().lower()
        self.assertIn("oracle prompt tips", output)
        self.assertIn("symptom + anchor + intent", output)
        self.assertIn("one symptom", output)
        self.assertIn("what should we look at first", output)

    async def test_unload_command_uses_backend_identifier_resolution(self) -> None:
        state = _state()

        class FakeBackend:
            async def unload_model(self, target: str = "", *, all_models: bool = False) -> dict[str, object]:
                self.last_target = target
                self.last_all = all_models
                return {"all": all_models, "unloaded": [target]}

            async def list_loaded_model_details(self) -> list[dict[str, object]]:
                return []

        backend = FakeBackend()
        with patch("z3cli.app.repl.get_backend", return_value=backend):
            await handle_command(state, "/unload oracle-main-plan")

        self.assertEqual(backend.last_target, "oracle-main-plan")
        self.assertFalse(backend.last_all)
        self.assertIn("Unloaded oracle-main-plan.", state.console.export_text())

    async def test_model_command_rejects_unknown_name(self) -> None:
        state = _state()

        with self.assertRaisesRegex(RuntimeError, "Unknown model"):
            await handle_command(state, "/model ghost")

    async def test_load_command_rejects_unknown_name(self) -> None:
        state = _state()

        with self.assertRaisesRegex(RuntimeError, "Unknown model"):
            await handle_command(state, "/load ghost")

    async def test_orchestrator_command_resolves_legacy_alias(self) -> None:
        state = _state()

        await handle_command(state, "/orchestrator oracle-main")

        self.assertEqual(state.orchestrator_model, "oracle")
        self.assertIn("Legacy alias 'oracle-main' now resolves to 'oracle'.", state.console.export_text())

    async def test_orchestrator_command_reports_unknown_name(self) -> None:
        state = _state()

        await handle_command(state, "/orchestrator ghost")

        self.assertIn("Unknown model: ghost", state.console.export_text())


if __name__ == "__main__":
    unittest.main()
