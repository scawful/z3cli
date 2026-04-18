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
from typing import NamedTuple


ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
OSC_RE = re.compile(r"\x1B\][^\x07]*(?:\x07|\x1B\\)")

REVIEW_DIALOG_HEADER_PATTERNS = (
    "review the master's work",
    "review applied changes",
    "review tool output",
)
REVIEW_DIALOG_KEEP_PROMPT = ("Y/Enter keep changes",)

PERMISSION_DIALOG_HEADER_PATTERNS = (
    "the oracle requests action",
    "the oracle requests permission",
)
PERMISSION_DIALOG_ACTION_PROMPTS = (
    "y/enter allow once",
    "a allow for session",
    "n/esc deny once",
    "d deny for session",
)
PERMISSION_DECISION_ALLOW_ONCE = "permission decision: allow-once"
PERMISSION_DECISION_ALLOW_SESSION = "permission decision: allow-session"
PERMISSION_DECISION_DENY_ONCE = "permission decision: deny-once"
PERMISSION_DECISION_DENY_SESSION = "permission decision: deny-session"


class DialogContract(NamedTuple):
    required_patterns: tuple[str, ...] = ()
    any_patterns: tuple[str, ...] = ()


REVIEW_DIALOG_CONTRACT = DialogContract(
    required_patterns=REVIEW_DIALOG_KEEP_PROMPT,
    any_patterns=REVIEW_DIALOG_HEADER_PATTERNS,
)

PERMISSION_DIALOG_CONTRACT = DialogContract(
    required_patterns=PERMISSION_DIALOG_ACTION_PROMPTS,
    any_patterns=PERMISSION_DIALOG_HEADER_PATTERNS + PERMISSION_DIALOG_ACTION_PROMPTS,
)


def strip_ansi(text: str) -> str:
    text = OSC_RE.sub("", text)
    text = ANSI_RE.sub("", text)
    return text.replace("\r", "")


def normalize_for_match(text: str) -> str:
    normalized = strip_ansi(text).lower()
    return normalized.replace("\u2019", "'")


def has_any_pattern(text: str, patterns: tuple[str, ...] | list[str]) -> bool:
    normalized_text = normalize_for_match(text)
    normalized_patterns = [pattern.lower() for pattern in patterns]
    return any(pattern in normalized_text for pattern in normalized_patterns)


def has_all_patterns(text: str, patterns: tuple[str, ...] | list[str]) -> bool:
    normalized_text = normalize_for_match(text)
    normalized_patterns = [pattern.lower() for pattern in patterns]
    return all(pattern in normalized_text for pattern in normalized_patterns)


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
        normalized_pattern = normalize_for_match(pattern)
        while time.time() < deadline:
            select.select([self.master_fd], [], [], 0.1)
            self._read_once()
            raw_output = strip_ansi(self.buffer)
            if normalized_pattern in normalize_for_match(raw_output):
                return raw_output
            if self.proc.poll() is not None:
                break
        raw_output = strip_ansi(self.buffer)
        raise AssertionError(f"Pattern not found: {pattern!r}\n--- output ---\n{raw_output}")

    def wait_for_any(self, patterns: list[str], timeout: float = 6.0) -> str:
        """Wait for any one of several output patterns to appear."""
        return self.wait_for_dialog(any_patterns=tuple(patterns), timeout=timeout)

    def wait_for_dialog(
        self,
        required_patterns: tuple[str, ...] | list[str] = (),
        any_patterns: tuple[str, ...] | list[str] = (),
        timeout: float = 6.0,
    ) -> str:
        """Wait for a dialog state by required and alternative patterns."""
        if not required_patterns and not any_patterns:
            raise ValueError("wait_for_dialog requires at least one pattern")

        deadline = time.time() + timeout
        while time.time() < deadline:
            select.select([self.master_fd], [], [], 0.1)
            self._read_once()
            raw_output = strip_ansi(self.buffer)
            if required_patterns and not has_all_patterns(raw_output, required_patterns):
                continue
            if any_patterns and not has_any_pattern(raw_output, any_patterns):
                continue
            if self.proc.poll() is not None:
                break
            return raw_output
        raw_output = strip_ansi(self.buffer)
        raise AssertionError(
            f"Dialog wait failed. Required: {required_patterns!r}, any-of: {any_patterns!r}\n--- output ---\n{raw_output}"
        )

    def wait_for_dialog_contract(self, contract: DialogContract, timeout: float = 6.0) -> str:
        """Wait for a dialog state using a named contract."""
        return self.wait_for_dialog(
            required_patterns=contract.required_patterns,
            any_patterns=contract.any_patterns,
            timeout=timeout,
        )

    def wait_for_review_dialog(self, timeout: float = 8.0) -> str:
        """Wait for the review dialog state (header + affordance text)."""
        return self.wait_for_dialog_contract(REVIEW_DIALOG_CONTRACT, timeout=timeout)

    def wait_for_permission_dialog(self, timeout: float = 8.0) -> str:
        """Wait for the permission dialog state (header + action hints)."""
        return self.wait_for_dialog_contract(PERMISSION_DIALOG_CONTRACT, timeout=timeout)

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
        self.app.wait_for_review_dialog()
        self.app.send("n")
        self.app.wait_for("review decision: reject", timeout=8)

    def test_auto_permission_dialog_can_be_denied(self) -> None:
        self.restart_app({"Z3CLI_TEST_AUTO_PERMISSION": "1"})
        self.app.wait_for("Ctrl+P", timeout=8)
        dialog_output = self.app.wait_for_permission_dialog()
        assert has_all_patterns(dialog_output, PERMISSION_DIALOG_ACTION_PROMPTS)
        assert has_any_pattern(dialog_output, PERMISSION_DIALOG_HEADER_PATTERNS)
        self.app.send("n")
        self.app.wait_for("permission decision: deny-once", timeout=8)

    def test_auto_permission_dialog_can_allow_once(self) -> None:
        self.restart_app({"Z3CLI_TEST_AUTO_PERMISSION": "1"})
        self.app.wait_for("Ctrl+P", timeout=8)
        self.app.wait_for_permission_dialog()
        self.app.send("y")
        self.app.wait_for(PERMISSION_DECISION_ALLOW_ONCE, timeout=8)

    def test_auto_permission_dialog_can_allow_for_session(self) -> None:
        self.restart_app({"Z3CLI_TEST_AUTO_PERMISSION": "1"})
        self.app.wait_for("Ctrl+P", timeout=8)
        self.app.wait_for_dialog(
            required_patterns=("a allow for session",),
            any_patterns=PERMISSION_DIALOG_HEADER_PATTERNS + PERMISSION_DIALOG_ACTION_PROMPTS,
        )
        self.app.send("a")
        self.app.wait_for(PERMISSION_DECISION_ALLOW_SESSION, timeout=8)

    def test_auto_permission_dialog_can_deny_for_session(self) -> None:
        self.restart_app({"Z3CLI_TEST_AUTO_PERMISSION": "1"})
        self.app.wait_for("Ctrl+P", timeout=8)
        self.app.wait_for_dialog(
            required_patterns=("d deny for session",),
            any_patterns=PERMISSION_DIALOG_HEADER_PATTERNS + PERMISSION_DIALOG_ACTION_PROMPTS,
        )
        self.app.send("d")
        self.app.wait_for(PERMISSION_DECISION_DENY_SESSION, timeout=8)


if __name__ == "__main__":
    unittest.main()
