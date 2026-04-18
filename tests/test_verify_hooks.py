import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from z3cli.app.verify import VerificationCommand, run_verification_hooks, select_verification_commands


class _FakeToolBridge:
    def __init__(self, tool_names: list[str], responses: dict[str, str] | None = None) -> None:
        self._tool_names = list(tool_names)
        self._responses = dict(responses or {})
        self.calls: list[tuple[str, dict]] = []

    def get_openai_tools(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": "",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
            for name in self._tool_names
        ]

    async def call_tool(self, name: str, arguments: dict) -> str:
        self.calls.append((name, dict(arguments)))
        return self._responses.get(name, "{}")

    def get_tool_server(self, tool_name: str) -> str:
        return "fake"

    @property
    def tool_count(self) -> int:
        return len(self._tool_names)

    @property
    def server_names(self) -> list[str]:
        return ["fake"]

    @property
    def server_tool_counts(self) -> dict[str, int]:
        return {"fake": len(self._tool_names)}

    async def close(self) -> None:
        return None


class VerifyHookTests(unittest.TestCase):
    def test_select_verification_commands_uses_repo_heuristics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "frontend").mkdir()
            (workspace / "frontend" / "package.json").write_text("{}", encoding="utf-8")
            (workspace / "pyproject.toml").write_text("[project]\nname='z3cli'\n", encoding="utf-8")
            (workspace / "tests").mkdir()
            serve_py = workspace / "z3cli" / "app" / "serve.py"
            serve_py.parent.mkdir(parents=True, exist_ok=True)
            serve_py.write_text("print('ok')\n", encoding="utf-8")

            commands = select_verification_commands(
                workspace,
                [
                    workspace / "frontend" / "src" / "App.tsx",
                    serve_py,
                ],
            )
            displays = [command.display for command in commands]

            self.assertIn("npm run test", displays)
            self.assertIn("npm run build", displays)
            self.assertTrue(any(display.startswith("python3 -m py_compile") for display in displays))
            self.assertIn("python3 -m unittest discover -s tests -p 'test_*.py'", displays)

    def test_select_verification_commands_skips_deleted_python_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "pyproject.toml").write_text("[project]\nname='z3cli'\n", encoding="utf-8")
            live = workspace / "z3cli" / "app" / "serve.py"
            live.parent.mkdir(parents=True, exist_ok=True)
            live.write_text("print('ok')\n", encoding="utf-8")

            commands = select_verification_commands(
                workspace,
                [
                    workspace / "z3cli" / "app" / "gone.py",
                    live,
                ],
            )
            compile_cmd = next(command for command in commands if command.display.startswith("python3 -m py_compile"))

            self.assertIn("z3cli/app/serve.py", compile_cmd.display)
            self.assertNotIn("z3cli/app/gone.py", compile_cmd.display)

    def test_select_verification_commands_adds_asm_lint_when_tool_is_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            patch = workspace / "src" / "main.asm"
            patch.parent.mkdir(parents=True, exist_ok=True)
            patch.write_text("lorom\n", encoding="utf-8")

            commands = select_verification_commands(
                workspace,
                [patch],
                bridge=_FakeToolBridge(["z3asm_lint"]),
            )

            displays = [command.display for command in commands]
            self.assertIn("z3asm_lint src/main.asm", displays)

    def test_select_verification_commands_uses_configured_patch_and_smoke_scenario(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            patch = workspace / "src" / "main.asm"
            include = workspace / "src" / "shared.inc"
            patch.parent.mkdir(parents=True, exist_ok=True)
            patch.write_text("lorom\n", encoding="utf-8")
            include.write_text("!foo = $01\n", encoding="utf-8")
            config_dir = workspace / "config"
            config_dir.mkdir()
            (config_dir / "asm_verify.toml").write_text(
                'patch_path = "src/main.asm"\n'
                'scenario = "sanctuary"\n'
                "frames = 24\n"
                'assertions = ["!crashed"]\n',
                encoding="utf-8",
            )

            commands = select_verification_commands(
                workspace,
                [include],
                bridge=_FakeToolBridge(["z3asm_lint", "asm_patch_test"]),
            )
            displays = [command.display for command in commands]

            self.assertIn("z3asm_lint src/main.asm", displays)
            smoke = next(display for display in displays if display.startswith("asm_patch_test "))
            self.assertIn("src/main.asm", smoke)
            self.assertIn("--scenario sanctuary", smoke)
            self.assertIn("--frames 24", smoke)
            self.assertNotIn("shared.inc", smoke)


class VerifyHookTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_verification_hooks_kills_timed_out_subprocesses(self) -> None:
        class FakeProcess:
            def __init__(self) -> None:
                self.killed = False
                self.returncode: int | None = None

            async def communicate(self) -> tuple[bytes, bytes]:
                if not self.killed:
                    await asyncio.sleep(3600)
                self.returncode = -9
                return (b"partial output\n", b"")

            def kill(self) -> None:
                self.killed = True

        fake_proc = FakeProcess()
        workspace = Path(tempfile.mkdtemp())

        async def fake_create_subprocess_exec(*args, **kwargs):  # type: ignore[no-untyped-def]
            return fake_proc

        with patch("z3cli.app.verify.select_verification_commands", return_value=[
            VerificationCommand(["python3", "-m", "py_compile", "main.py"], cwd=workspace, timeout_s=0.01),
        ]), patch("z3cli.app.verify.asyncio.create_subprocess_exec", side_effect=fake_create_subprocess_exec):
            summary = await run_verification_hooks(workspace, [workspace / "main.py"])

        self.assertTrue(fake_proc.killed)
        self.assertEqual(len(summary.results), 1)
        self.assertFalse(summary.results[0].ok)
        self.assertIn("Timed out after 0s", summary.results[0].output)
        self.assertIn("partial output", summary.results[0].output)

    async def test_run_verification_hooks_executes_asm_tool_verifiers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            patch = workspace / "src" / "main.asm"
            patch.parent.mkdir(parents=True, exist_ok=True)
            patch.write_text("lorom\n", encoding="utf-8")
            rom = workspace / "oracle.sfc"
            rom.write_bytes(b"\xAA" * 64)
            config_dir = workspace / "config"
            config_dir.mkdir()
            (config_dir / "asm_verify.toml").write_text(
                'scenario = "sanctuary"\n'
                "frames = 18\n"
                'assertions = ["LinkHealth > 0"]\n',
                encoding="utf-8",
            )
            bridge = _FakeToolBridge(
                ["z3asm_lint", "asm_patch_test"],
                responses={
                    "z3asm_lint": json.dumps({"lint.json": {"ok": True}}),
                    "asm_patch_test": json.dumps({"ok": True, "failure_stage": None}),
                },
            )

            summary = await run_verification_hooks(
                workspace,
                [patch],
                bridge=bridge,
                rom_path=rom,
            )

        self.assertEqual([result.command for result in summary.results], [
            "z3asm_lint src/main.asm",
            "asm_patch_test src/main.asm --scenario sanctuary --frames 18 --assert 'LinkHealth > 0'",
        ])
        self.assertTrue(all(result.ok for result in summary.results))
        self.assertEqual([name for name, _args in bridge.calls], ["z3asm_lint", "asm_patch_test"])
        self.assertEqual(bridge.calls[1][1]["rom_path_override"], str(rom))
        rendered = summary.render()
        self.assertIn("Verification:", rendered)
        self.assertIn("asm_patch_test src/main.asm", rendered)


if __name__ == "__main__":
    unittest.main()
