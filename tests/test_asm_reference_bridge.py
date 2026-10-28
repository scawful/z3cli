"""AsmReferenceBridge: usdasm address/name lookup and ASM text search."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from protocol.asar_namespace import strip_namespace
from protocol.asm_reference_bridge import AsmReferenceBridge
from protocol.asm_symbol_bridge import AsmSymbolBridge

_BANK_07 = """\
; =========
TileDetect_MainHandler:
#_07D140: PHB
#_07D141: PHK

.try_overworld_warp
#_07D151: LDA.w $02DB
#_07D154: BNE .dont_attempt_to_warp
"""

_WRAM = """\
SCRAP0F         = $7E000F

; Game mode
; See $00:80B5
MODE            = $7E0010
SUBMODE         = $7E0011
"""


class AsmReferenceBridgeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.usdasm = root / "usdasm"
        self.usdasm.mkdir()
        (self.usdasm / "bank_07.asm").write_text(_BANK_07)
        (self.usdasm / "wram.asm").write_text(_WRAM)
        self.workspace = root / "oracle"
        (self.workspace / "Core").mkdir(parents=True)
        (self.workspace / "Core" / "hooks.asm").write_text(
            "org $07D151 ; TileDetect warp hook\n  JSL Oracle_WarpCheck\n"
        )
        (self.workspace / "main.asm").write_text(
            "namespace Oracle\nincsrc Core/follower.asm\nnamespace off\n"
        )
        (self.workspace / "Core" / "follower.asm").write_text("Follower_WatchLink:\n  RTL\n")
        self.bridge = AsmReferenceBridge(self.workspace, usdasm=self.usdasm)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    async def test_address_returns_instruction_routine_and_local(self) -> None:
        for query in ("$07:D151", "$07D151", "07D151"):
            out = await self.bridge.call_tool("vanilla_lookup", {"query": query})
            self.assertIn("LDA.w $02DB", out, query)
            self.assertIn("routine: TileDetect_MainHandler", out)
            self.assertIn("local .try_overworld_warp", out)
            self.assertIn("PC 0x03D151", out)

    async def test_mid_instruction_address_reports_nearest_line(self) -> None:
        out = await self.bridge.call_tool("vanilla_lookup", {"query": "$07:D152"})
        self.assertIn("not an instruction start", out)
        self.assertIn("LDA.w $02DB", out)

    async def test_wram_address_and_name_resolve_defines(self) -> None:
        by_address = await self.bridge.call_tool("vanilla_lookup", {"query": "$7E0010"})
        by_short = await self.bridge.call_tool("vanilla_lookup", {"query": "$0011"})
        by_name = await self.bridge.call_tool("vanilla_lookup", {"query": "TileDetect_MainHandler"})
        self.assertIn("MODE", by_address)
        self.assertIn("; See $00:80B5", by_address)
        self.assertIn("SUBMODE", by_short)
        self.assertIn("; Game mode", by_short)
        self.assertNotIn("SCRAP0F", by_short)
        self.assertIn(f"{self.usdasm.resolve()}/bank_07.asm:2", by_name)

    async def test_missing_bank_names_available_banks(self) -> None:
        out = await self.bridge.call_tool("vanilla_lookup", {"query": "$0D:8000"})
        self.assertIn("bank $0D", out)
        self.assertIn("07", out)

    async def test_asm_grep_scopes(self) -> None:
        both = await self.bridge.call_tool("asm_grep", {"query": "07D151"})
        oracle = await self.bridge.call_tool("asm_grep", {"query": "07D151", "scope": "oracle"})
        vanilla = await self.bridge.call_tool("asm_grep", {"query": "07D151", "scope": "vanilla"})
        usdasm = str(self.usdasm.resolve())
        self.assertIn("- Core/hooks.asm:1", both)
        self.assertIn(f"- {usdasm}/bank_07.asm", both)
        self.assertNotIn(usdasm, oracle)
        self.assertNotIn("- Core/", vanilla)

    async def test_namespaced_symbol_retries_without_prefix(self) -> None:
        self.assertEqual(strip_namespace("Oracle_Follower_WatchLink", self.workspace), "Follower_WatchLink")
        self.assertIsNone(strip_namespace("Follower_WatchLink", self.workspace))
        out = await self.bridge.call_tool("asm_grep", {"query": "Oracle_Follower_WatchLink"})
        self.assertIn("without the asar namespace prefix: Follower_WatchLink", out)
        self.assertIn("- Core/follower.asm:1", out)
        symbols = AsmSymbolBridge(self.workspace)
        found = await symbols.call_tool("z3lsp_symbols", {"query": "Oracle_Follower_WatchLink"})
        self.assertIn("Follower_WatchLink", found)
        self.assertIn("namespace prefix", found)

    async def test_no_usdasm_exposes_no_tools(self) -> None:
        bridge = AsmReferenceBridge(self.workspace, usdasm=self.workspace / "missing")
        self.assertEqual(bridge.tool_count, 0)
        self.assertEqual(bridge.get_openai_tools(), [])
        self.assertFalse(await bridge.call_tool("vanilla_lookup", {"query": "x"}) == "")


if __name__ == "__main__":
    unittest.main()
