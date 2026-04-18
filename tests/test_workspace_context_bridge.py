from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from z3cli.protocol.workspace_context_bridge import WorkspaceContextBridge


class WorkspaceContextBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_workspace_relative_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = workspace / "Oracle_main.asm"
            target.write_text("lda #$01\nsta $7E0010\n", encoding="utf-8")

            bridge = WorkspaceContextBridge(workspace)
            result = await bridge.call_tool("workspace_read", {"path": "Oracle_main.asm"})

        self.assertIn("File: Oracle_main.asm", result)
        self.assertIn("1 | lda #$01", result)
        self.assertIn("2 | sta $7E0010", result)

    async def test_lists_workspace_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "src").mkdir()
            (workspace / "src" / "main.asm").write_text("rtl\n", encoding="utf-8")

            bridge = WorkspaceContextBridge(workspace)
            result = await bridge.call_tool("workspace_read", {"path": "."})

        self.assertIn("Directory: .", result)
        self.assertIn("- src/", result)

    async def test_missing_path_suggests_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "src").mkdir()
            (workspace / "src" / "Oracle_main.asm").write_text("rtl\n", encoding="utf-8")

            bridge = WorkspaceContextBridge(workspace)
            result = await bridge.call_tool("workspace_read", {"path": "OracleMain.asm"})

        self.assertIn("Path not found in workspace: OracleMain.asm", result)
        self.assertIn("Possible matches", result)
        self.assertIn("src/Oracle_main.asm", result)

    async def test_blocks_paths_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            outside = Path(tmp).parent / "other.asm"
            outside.write_text("rtl\n", encoding="utf-8")
            try:
                bridge = WorkspaceContextBridge(workspace)
                result = await bridge.call_tool("workspace_read", {"path": str(outside)})
            finally:
                outside.unlink(missing_ok=True)

        self.assertIn("outside the active workspace", result)
