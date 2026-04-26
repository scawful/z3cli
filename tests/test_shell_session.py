import tempfile
import unittest
from pathlib import Path
import shlex

from app.shell_session import PersistentShellSession


class ShellSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_shell_session_persists_cwd_between_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            nested = workspace / "frontend"
            nested.mkdir()

            shell = PersistentShellSession(workspace, shell="/bin/sh")
            try:
                await shell.run("pwd")
                await shell.run(f"cd {shlex.quote(str(nested))}")
                result = await shell.run("pwd")

                self.assertEqual(Path(result.cwd), nested.resolve())
                self.assertEqual(Path(result.output.strip()).resolve(), nested.resolve())
                self.assertGreaterEqual(len(shell.scrollback), 3)
            finally:
                await shell.close()


if __name__ == "__main__":
    unittest.main()
