import errno
import fcntl
import os
import pty
import re
import select
import signal
import shutil
import struct
import subprocess
import tempfile
import termios
import time
import unittest
from pathlib import Path


ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
OSC_RE = re.compile(r"\x1B\][^\x07]*(?:\x07|\x1B\\)")


def strip_ansi(text: str) -> str:
    text = OSC_RE.sub("", text)
    text = ANSI_RE.sub("", text)
    return text.replace("\r", "")


class PtyApp:
    def __init__(self, workspace: Path, extra_env: dict[str, str] | None = None):
        repo_root = Path(__file__).resolve().parents[1]
        frontend_dir = repo_root / "frontend"
        tsx_bin = frontend_dir / "node_modules" / ".bin" / "tsx"
        fixture = repo_root / "tests" / "fixtures" / "fake_ui_backend.py"

        if not tsx_bin.exists():
            raise RuntimeError(f"tsx not found at {tsx_bin}")

        self.tmpdir = tempfile.TemporaryDirectory()
        self.master_fd, slave_fd = pty.openpty()
        fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 120, 0, 0))
        flags = fcntl.fcntl(self.master_fd, fcntl.F_GETFL)
        fcntl.fcntl(self.master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        wrapper = Path(self.tmpdir.name) / "fake-python"
        wrapper.write_text(
            "#!/bin/sh\n"
            f"exec python3 {fixture} \"$@\"\n",
            encoding="utf-8",
        )
        wrapper.chmod(0o755)

        env = os.environ.copy()
        env["Z3CLI_PYTHON"] = str(wrapper)
        env["Z3CLI_TEST_WORKSPACE"] = str(workspace)
        if extra_env:
            env.update(extra_env)

        self.proc = subprocess.Popen(
            [str(tsx_bin), str(frontend_dir / "src" / "index.tsx")],
            cwd=frontend_dir,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=env,
            close_fds=True,
        )
        os.close(slave_fd)
        self.buffer = ""

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=3)
        os.close(self.master_fd)
        self.tmpdir.cleanup()

    def send(self, data: str) -> None:
        for char in data:
            os.write(self.master_fd, char.encode("utf-8"))
            time.sleep(0.01)

    def resize(self, rows: int, cols: int) -> None:
        fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        self.proc.send_signal(signal.SIGWINCH)

    def _read_once(self) -> None:
        try:
            chunk = os.read(self.master_fd, 8192)
        except BlockingIOError:
            return
        except OSError as exc:
            if exc.errno == errno.EIO:
                return
            raise
        if chunk:
            self.buffer += chunk.decode("utf-8", errors="ignore")

    def wait_for(self, pattern: str, timeout: float = 6.0) -> str:
        deadline = time.time() + timeout
        while time.time() < deadline:
            select.select([self.master_fd], [], [], 0.1)
            self._read_once()
            cleaned = strip_ansi(self.buffer)
            if pattern in cleaned:
                return cleaned
            if self.proc.poll() is not None:
                break
        cleaned = strip_ansi(self.buffer)
        raise AssertionError(f"Pattern not found: {pattern!r}\n--- output ---\n{cleaned}")

    def wait_for_any(self, patterns: list[str], timeout: float = 6.0) -> str:
        """Wait for any one of several output patterns to appear."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            select.select([self.master_fd], [], [], 0.1)
            self._read_once()
            cleaned = strip_ansi(self.buffer)
            for pattern in patterns:
                if pattern in cleaned:
                    return cleaned
            if self.proc.poll() is not None:
                break
        cleaned = strip_ansi(self.buffer)
        raise AssertionError(f"No match for patterns: {patterns!r}\n--- output ---\n{cleaned}")

    def wait_for_exit(self, timeout: float = 4.0) -> int:
        return self.proc.wait(timeout=timeout)


@unittest.skipUnless(shutil.which("python3"), "python3 required")
class FrontendPtyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.workspace_dir.name)
        (self.workspace / "src").mkdir(parents=True, exist_ok=True)
        (self.workspace / "src" / "room.asm").write_text("lda #$01\nsta $7E0010\n", encoding="utf-8")
        self.app = PtyApp(self.workspace)

    def tearDown(self) -> None:
        self.app.close()
        self.workspace_dir.cleanup()

    def restart_app(self, extra_env: dict[str, str] | None = None) -> None:
        self.app.close()
        self.app = PtyApp(self.workspace, extra_env=extra_env)

    def test_ctrl_p_opens_command_palette(self) -> None:
        self.app.wait_for("Ctrl+P", timeout=8)
        self.app.send("\x10")
        self.app.wait_for("Command palette", timeout=8)

    def test_file_reference_picker_opens_for_workspace_match(self) -> None:
        self.app.wait_for("Ctrl+P", timeout=8)
        self.app.send("@room")
        self.app.wait_for("File reference", timeout=8)
        self.app.wait_for("src/room.asm", timeout=8)

    def test_prompt_typing_echoes_into_the_input_line(self) -> None:
        self.app.wait_for("Ctrl+P", timeout=8)
        self.app.send("status")
        self.app.wait_for("❯ status", timeout=8)

    def test_resize_smoke_keeps_input_alive(self) -> None:
        self.app.wait_for("Ctrl+P", timeout=8)
        self.app.resize(30, 180)
        self.app.send("\x10")
        self.app.wait_for("Command palette", timeout=8)

    def test_backend_crash_during_pending_command_surfaces_error(self) -> None:
        self.restart_app({
            "Z3CLI_TEST_CRASH_AFTER_READY_MS": "250",
            "Z3CLI_TEST_CRASH_EXIT_CODE": "23",
        })
        self.app.wait_for("Backend exited with code 23", timeout=8)

    def test_cancel_during_review_wait_returns_to_prompt(self) -> None:
        self.restart_app({"Z3CLI_TEST_AUTO_REVIEW": "1"})
        self.app.wait_for("Ctrl+P", timeout=8)
        self.app.wait_for_any(["REVIEW THE MASTER'S WORK", "Review applied changes"], timeout=8)
        self.app.send("n")
        self.app.wait_for("review decision: reject", timeout=8)


if __name__ == "__main__":
    unittest.main()
