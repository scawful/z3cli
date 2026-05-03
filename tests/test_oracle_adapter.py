"""Tests for the OracleAdapter — read-only grounding surface."""

from __future__ import annotations

import unittest
from pathlib import Path

from core import config as config_mod
from core.tool_adapters import ADAPTER_REGISTRY, get_adapter


class _TrackingBridge:
    def __init__(self, tag: str, response: str | None = None):
        self.tag = tag
        self.calls: list[tuple[str, dict]] = []
        self._response = response or f"{tag} result"

    def get_openai_tools(self) -> list[dict]:
        return []

    async def call_tool(self, name: str, arguments: dict) -> str:
        self.calls.append((name, dict(arguments)))
        return f"[{self.tag}] {name}({arguments}) -> {self._response}"

    def get_tool_server(self, tool_name: str) -> str:
        return self.tag

    @property
    def tool_count(self) -> int:
        return 0

    @property
    def server_names(self) -> list[str]:
        return [self.tag]

    @property
    def server_tool_counts(self) -> dict[str, int]:
        return {self.tag: 0}

    async def close(self) -> None:
        return None


class OracleAdapterRegistrationTests(unittest.TestCase):
    def test_oracle_profiles_registered(self) -> None:
        for profile in ("oracle", "oracle-fast", "oracle-pro"):
            self.assertIn(profile, ADAPTER_REGISTRY, msg=f"{profile} missing from ADAPTER_REGISTRY")

    def test_get_adapter_instantiates_oracle(self) -> None:
        adapter = get_adapter("oracle", {"symbols": _TrackingBridge("symbols")})
        self.assertIsNotNone(adapter)
        names = {tool.name for tool in adapter._adapter_tools}
        self.assertEqual(
            names,
            {
                "label_lookup",
                "grep_disasm",
                "rom_read",
                "disasm_at",
                "cpu_state",
                "register_doc",
                "workspace_read",
            },
        )


class OracleRegistryBindingTests(unittest.TestCase):
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

    def test_public_oracle_models_bind_oracle_tool_profiles(self) -> None:
        registry_path = Path(__file__).resolve().parents[1] / "config" / "chat_registry.toml"
        models, _routers = config_mod.load_registry(registry_path)

        self.assertEqual(models["oracle"].tool_profile, "oracle")
        self.assertEqual(models["oracle-qwen35-9b"].tool_profile, "oracle")
        self.assertEqual(models["oracle-fast"].tool_profile, "oracle-fast")
        self.assertEqual(models["oracle-pro"].tool_profile, "oracle-pro")
        self.assertEqual(models["oracle-pro"].model_id, "gguf/zelda/qwen3-oracle-14b-v8-q4km.gguf")
        self.assertIn("qwen3-oracle-14b-v8", models["oracle-pro"].aliases)
        self.assertFalse(models["oracle"].deferred_tools)


class OracleAdapterRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_label_lookup_routes_to_symbols_bridge(self) -> None:
        symbols = _TrackingBridge("symbols", response="symbol hit")
        emulator = _TrackingBridge("emulator")
        adapter = get_adapter("oracle", {"symbols": symbols, "emulator": emulator})
        assert adapter is not None

        await adapter.call_tool("label_lookup", {"query": "$0088EC"})

        self.assertEqual(symbols.calls, [("z3lsp_symbols", {"query": "$0088EC"})])
        self.assertEqual(emulator.calls, [])

    async def test_label_lookup_accepts_common_model_argument_aliases(self) -> None:
        symbols = _TrackingBridge("symbols", response="symbol hit")
        adapter = get_adapter("oracle", {"symbols": symbols})
        assert adapter is not None

        await adapter.call_tool("label_lookup", {"target": "Underworld_LoadSongBankIfNeeded"})
        await adapter.call_tool("label_lookup", {"address": "$00FFD5"})

        self.assertEqual(
            symbols.calls,
            [
                ("z3lsp_symbols", {"query": "Underworld_LoadSongBankIfNeeded"}),
                ("z3lsp_symbols", {"query": "$00FFD5"}),
            ],
        )

    async def test_grep_disasm_fans_out_to_two_symbols_calls(self) -> None:
        symbols = _TrackingBridge("symbols")
        adapter = get_adapter("oracle", {"symbols": symbols})
        assert adapter is not None

        await adapter.call_tool("grep_disasm", {"query": "MDMAEN"})

        self.assertEqual(
            [call[0] for call in symbols.calls],
            ["z3lsp_symbols", "z3lsp_references"],
        )

    async def test_grep_disasm_accepts_pattern_alias(self) -> None:
        symbols = _TrackingBridge("symbols")
        adapter = get_adapter("oracle", {"symbols": symbols})
        assert adapter is not None

        await adapter.call_tool("grep_disasm", {"pattern": "Sprite_CheckIfActive"})

        self.assertEqual(
            symbols.calls,
            [
                ("z3lsp_symbols", {"query": "Sprite_CheckIfActive"}),
                ("z3lsp_references", {"symbol": "Sprite_CheckIfActive"}),
            ],
        )

    async def test_rom_read_and_disasm_route_to_emulator(self) -> None:
        emulator = _TrackingBridge("emulator")
        adapter = get_adapter("oracle", {"emulator": emulator})
        assert adapter is not None

        await adapter.call_tool("rom_read", {"address": "$00A000", "length": 4})
        await adapter.call_tool("disasm_at", {"address": "$00A000", "count": 8})

        self.assertEqual(
            emulator.calls,
            [
                ("mesen_memory_read", {"address": "$00A000", "length": 4}),
                ("mesen_disasm", {"address": "$00A000", "count": 8}),
            ],
        )

    async def test_rom_read_and_disasm_accept_length_aliases(self) -> None:
        emulator = _TrackingBridge("emulator")
        adapter = get_adapter("oracle", {"emulator": emulator})
        assert adapter is not None

        await adapter.call_tool("rom_read", {"address": "$7E0800", "bytes": "8"})
        await adapter.call_tool("disasm_at", {"address": "$02A3B0", "size": "12"})
        await adapter.call_tool("disasm_at", {"addr": "$0088EC", "instruction_count": "10"})

        self.assertEqual(
            emulator.calls,
            [
                ("mesen_memory_read", {"address": "$7E0800", "length": 8}),
                ("mesen_disasm", {"address": "$02A3B0", "count": 12}),
                ("mesen_disasm", {"address": "$0088EC", "count": 10}),
            ],
        )

    async def test_common_value_aliases_route_for_salvaged_bare_calls(self) -> None:
        symbols = _TrackingBridge("symbols")
        workspace = _TrackingBridge("workspace")
        adapter = get_adapter("oracle", {"symbols": symbols, "workspace": workspace})
        assert adapter is not None

        await adapter.call_tool("label_lookup", {"value": "Underworld_LoadSongBankIfNeeded"})
        await adapter.call_tool("grep_disasm", {"value": "Sprite_CheckIfActive"})
        await adapter.call_tool("workspace_read", {"value": "docs/HANDOFF_ZELDA_MODEL_WORK_20260425.md"})

        self.assertEqual(
            symbols.calls,
            [
                ("z3lsp_symbols", {"query": "Underworld_LoadSongBankIfNeeded"}),
                ("z3lsp_symbols", {"query": "Sprite_CheckIfActive"}),
                ("z3lsp_references", {"symbol": "Sprite_CheckIfActive"}),
            ],
        )
        self.assertEqual(
            workspace.calls,
            [
                (
                    "workspace_read",
                    {"path": "docs/HANDOFF_ZELDA_MODEL_WORK_20260425.md"},
                ),
            ],
        )

    async def test_cpu_state_collects_cpu_and_gamestate(self) -> None:
        emulator = _TrackingBridge("emulator")
        adapter = get_adapter("oracle", {"emulator": emulator})
        assert adapter is not None

        out = await adapter.call_tool("cpu_state", {})

        self.assertEqual([call[0] for call in emulator.calls], ["mesen_cpu", "mesen_gamestate"])
        self.assertIn("CPU", out)
        self.assertIn("Game state", out)

    async def test_workspace_read_routes_to_workspace_bridge(self) -> None:
        workspace = _TrackingBridge("workspace", response="source contents")
        adapter = get_adapter("oracle", {"workspace": workspace})
        assert adapter is not None

        await adapter.call_tool("workspace_read", {"path": "Oracle_main.asm", "max_lines": 40})

        self.assertEqual(
            workspace.calls,
            [("workspace_read", {"path": "Oracle_main.asm", "max_lines": 40})],
        )


class OracleAdapterRegisterDocTests(unittest.IsolatedAsyncioTestCase):
    async def test_register_doc_resolves_address_and_name(self) -> None:
        adapter = get_adapter("oracle", {"symbols": _TrackingBridge("symbols")})
        assert adapter is not None

        by_address = await adapter.call_tool("register_doc", {"query": "$420B"})
        by_name = await adapter.call_tool("register_doc", {"query": "MDMAEN"})

        self.assertIn("MDMAEN", by_address)
        self.assertIn("MDMAEN", by_name)
        self.assertIn("DMA Enable", by_address)

    async def test_register_doc_handles_alttp_wram_mirror(self) -> None:
        adapter = get_adapter("oracle", {"symbols": _TrackingBridge("symbols")})
        assert adapter is not None

        out = await adapter.call_tool("register_doc", {"query": "$7E0013"})

        self.assertIn("INIDISPQ", out)

    async def test_register_doc_disambiguates_mdmaen_from_hdmaen(self) -> None:
        adapter = get_adapter("oracle", {"symbols": _TrackingBridge("symbols")})
        assert adapter is not None

        mdmaen = await adapter.call_tool("register_doc", {"query": "MDMAEN"})
        hdmaen = await adapter.call_tool("register_doc", {"query": "HDMAEN"})

        self.assertIn("$420B", mdmaen)
        self.assertIn("$420C", hdmaen)
        self.assertNotIn("$420C", mdmaen)
        self.assertNotIn("$420B", hdmaen)

    async def test_register_doc_unknown_query_explains(self) -> None:
        adapter = get_adapter("oracle", {"symbols": _TrackingBridge("symbols")})
        assert adapter is not None

        out = await adapter.call_tool("register_doc", {"query": "$1234"})

        self.assertIn("Unknown register", out)


if __name__ == "__main__":
    unittest.main()
