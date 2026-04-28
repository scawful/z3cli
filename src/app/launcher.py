"""Launcher policy for the user-facing z3cli command.

The Ink terminal UI is the canonical interactive surface.  The older Python
REPL remains available for scripted/control operations and as a legacy escape
hatch, but plain ``z3cli`` should land in the same experience as ``z3ui``.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


CONTROL_COMMANDS = {"route", "models"}
LEGACY_REPL_FLAGS = {"--legacy-repl", "--repl"}
BACKEND_ONLY_FLAGS = {
    "--list-loaded",
    "--list-models",
    "--prompt",
    "--route-only",
    "--smoke",
    "--status",
}
VALUE_FLAGS = {
    "--api-base",
    "--backend",
    "--broadcast-models",
    "--host",
    "--llamacpp-api-base",
    "--llamacpp-model",
    "--llamacpp-node",
    "--lsp-context",
    "--max-tokens",
    "--mcp-config",
    "--mode",
    "--model",
    "--port",
    "--prompt",
    "--registry",
    "--rom",
    "--smoke",
    "--studio-api-base",
    "--studio-node",
    "--temperature",
    "--workspace",
    # Frontend-owned, but it also takes an optional value and should not be
    # mistaken for a control command.
    "--resume",
}


HELP_TEXT = """z3cli launches the Ink z3ui terminal UI by default.

Usage:
  z3cli [ui/backend flags]
  z3ui [ui/backend flags]
  z3cli --serve [backend flags]
  z3cli --bridge [bridge flags] -- [backend flags]
  z3cli route|models ...
  z3cli --prompt "..."
  z3cli --legacy-repl

Interactive chat now goes through the Ink UI and its --serve backend. The
legacy Python REPL is kept only for debugging and compatibility.
"""


def strip_legacy_repl_flag(argv: list[str]) -> tuple[list[str], bool]:
    stripped: list[str] = []
    legacy = False
    for arg in argv:
        if arg in LEGACY_REPL_FLAGS:
            legacy = True
            continue
        stripped.append(arg)
    return stripped, legacy


def is_backend_only_invocation(argv: list[str]) -> bool:
    """Return true when argv should stay on the Python backend/control path."""

    for arg in argv:
        if arg in BACKEND_ONLY_FLAGS:
            return True
        if any(arg.startswith(f"{flag}=") for flag in BACKEND_ONLY_FLAGS):
            return True
    first = first_positional_arg(argv)
    return first in CONTROL_COMMANDS


def first_positional_arg(argv: list[str]) -> str:
    skip_next = False
    for arg in argv:
        if skip_next:
            skip_next = False
            continue
        if arg == "--":
            return ""
        if arg.startswith("--"):
            if "=" not in arg and arg in VALUE_FLAGS:
                skip_next = True
            continue
        if arg.startswith("-"):
            continue
        return arg.strip().lower()
    return ""


def _root_candidates(path: Path) -> list[Path]:
    return [path, *path.parents]


def _looks_like_repo_root(path: Path) -> bool:
    return (path / "frontend" / "package.json").exists()


def repo_root_from_app_file(app_file: str | Path) -> Path:
    env_root = os.environ.get("Z3CLI_REPO_ROOT")
    if env_root:
        root = Path(env_root).expanduser().resolve()
        if _looks_like_repo_root(root):
            return root

    app_path = Path(app_file).resolve()
    for candidate in _root_candidates(app_path):
        if _looks_like_repo_root(candidate):
            return candidate

    cwd = Path.cwd().resolve()
    for candidate in _root_candidates(cwd):
        if _looks_like_repo_root(candidate):
            return candidate

    return app_path.parents[2]


def build_ink_frontend_command(repo_root: Path, argv: list[str]) -> list[str]:
    frontend = repo_root / "frontend"
    dist = frontend / "dist" / "index.js"
    source = frontend / "src" / "index.tsx"
    tsx = frontend / "node_modules" / ".bin" / "tsx"

    if dist.exists():
        return ["node", str(dist), *argv]
    if tsx.exists() and source.exists():
        return [str(tsx), str(source), *argv]
    if (frontend / "package.json").exists() and shutil.which("npm"):
        return ["npm", "--prefix", str(frontend), "run", "dev", "--", *argv]
    raise FileNotFoundError(
        "Could not find the z3ui Ink frontend. Run `cd frontend && npm install`, "
        "or use `z3cli --legacy-repl` for the old Python REPL."
    )


def exec_ink_frontend(repo_root: Path, argv: list[str]) -> int:
    cmd = build_ink_frontend_command(repo_root, argv)
    env = os.environ.copy()
    env.setdefault("Z3CLI_PYTHON", sys.executable)
    try:
        os.execvpe(cmd[0], cmd, env)
    except FileNotFoundError as exc:
        print(f"z3cli: failed to launch Ink UI: {exc}", file=sys.stderr)
        return 127
    return 127
