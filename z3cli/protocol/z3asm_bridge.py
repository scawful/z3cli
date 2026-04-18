"""z3asm/z3disasm bridge — assemble, lint, and disassemble 65816 ASM.

Stateless subprocess per call, mirroring :class:`Z3edBridge`. Each tool is
surfaced only if the corresponding binary is discovered, so missing
toolchain pieces don't break the whole bridge.

Tools:
  * ``z3asm_assemble`` — runs z3asm against a patch + ROM, emitting
    diagnostics/sourcemaps (and optional structured outputs) into
    invocation-scoped temp files before returning their parsed contents.
  * ``z3asm_lint`` — z3asm with ``--emit=lint`` for fast iterative checks.
  * ``z3disasm_bank`` — runs z3disasm to emit bank_XX.asm files for a byte
    range; returns the list of generated paths plus a short preview.
  * ``z3disasm_read_output`` — reads a previously-generated .asm file with
    a line budget so agents don't have to shell out via ``cat``.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from z3cli.core.rom_project import RomProject


SERVER_NAME = "z3asm"
DEFAULT_TIMEOUT_S = 120.0
MAX_PREVIEW_LINES = 40
_DEFAULT_ASSEMBLE_EMITS = ("diagnostics", "sourcemap")
_DEFAULT_LINT_EMITS = ("lint",)
_JSON_ARTIFACT_BASENAMES = {
    "diagnostics.json",
    "sourcemap.json",
    "lint.json",
    "hooks.json",
    "annotations.json",
}
_SIMPLE_EMIT_TARGETS: dict[str, tuple[str, str]] = {
    "diagnostics": ("diagnostics", "diagnostics.json"),
    "diagnostics.json": ("diagnostics", "diagnostics.json"),
    "sourcemap": ("sourcemap", "sourcemap.json"),
    "source-map": ("sourcemap", "sourcemap.json"),
    "sourcemap.json": ("sourcemap", "sourcemap.json"),
    "lint": ("lint", "lint.json"),
    "lint.json": ("lint", "lint.json"),
    "hooks": ("hooks", "hooks.json"),
    "hooks.json": ("hooks", "hooks.json"),
    "annotations": ("annotations", "annotations.json"),
    "annotations.json": ("annotations", "annotations.json"),
    "symbols-mlb": ("symbols-mlb", "symbols.mlb"),
    "symbols.mlb": ("symbols-mlb", "symbols.mlb"),
    "symbols-wla": ("symbols-wla", "symbols.sym"),
    "symbols.sym": ("symbols-wla", "symbols.sym"),
}


class Z3asmBridge:
    """ToolBridge that shells out to z3asm / z3disasm per call."""

    def __init__(
        self,
        project: RomProject,
        *,
        z3asm_bin: Path | None = None,
        z3disasm_bin: Path | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self._project = project
        self._z3asm_bin = z3asm_bin or project.z3asm_bin
        self._z3disasm_bin = z3disasm_bin or project.z3disasm_bin
        self._timeout_s = timeout_s
        self._tool_names: list[str] = []
        self._warnings: list[str] = []

    # -- ToolBridge protocol -----------------------------------------------

    async def connect(self) -> list[str]:
        self._tool_names = []
        self._warnings = []
        if self._z3asm_bin is None:
            fallback = shutil.which("z3asm")
            if fallback:
                self._z3asm_bin = Path(fallback).resolve()
        if self._z3disasm_bin is None:
            fallback = shutil.which("z3disasm")
            if fallback:
                self._z3disasm_bin = Path(fallback).resolve()

        if self._z3asm_bin and self._z3asm_bin.exists():
            self._tool_names.extend(["z3asm_assemble", "z3asm_lint"])
        else:
            self._warnings.append("z3asm binary not found; assemble/lint tools disabled.")

        if self._z3disasm_bin and self._z3disasm_bin.exists():
            self._tool_names.extend(["z3disasm_bank", "z3disasm_read_output"])
        else:
            self._warnings.append("z3disasm binary not found; bank disassembly tool disabled.")

        return list(self._warnings)

    def get_openai_tools(self) -> list[dict]:
        schemas: list[dict] = []
        for name in self._tool_names:
            schemas.append(_TOOL_SCHEMAS[name])
        return schemas

    def get_tool_server(self, tool_name: str) -> str:
        return SERVER_NAME if tool_name in self._tool_names else "unknown"

    @property
    def tool_count(self) -> int:
        return len(self._tool_names)

    @property
    def server_names(self) -> list[str]:
        return [SERVER_NAME] if self._tool_names else []

    @property
    def server_tool_counts(self) -> dict[str, int]:
        return {SERVER_NAME: len(self._tool_names)} if self._tool_names else {}

    def is_write_tool(self, tool_name: str) -> bool | None:
        if tool_name not in self._tool_names:
            return None
        if tool_name == "z3asm_assemble":
            # Assembly mutates the target ROM on success. ReadOnlyBridge
            # should therefore gate it by default.
            return True
        return False

    async def close(self) -> None:
        return None

    async def call_tool(self, name: str, arguments: dict) -> str:
        if name not in self._tool_names:
            return f"Error: unknown z3asm tool '{name}'"
        if name == "z3asm_assemble":
            return await self._assemble(arguments, lint_only=False)
        if name == "z3asm_lint":
            return await self._assemble(arguments, lint_only=True)
        if name == "z3disasm_bank":
            return await self._disasm_bank(arguments)
        if name == "z3disasm_read_output":
            return await self._read_output(arguments)
        return f"Error: unhandled tool '{name}'"

    # -- implementations ---------------------------------------------------

    async def _assemble(self, arguments: dict, *, lint_only: bool) -> str:
        patch = arguments.get("patch_path") or arguments.get("patch")
        if not patch:
            return "Error: 'patch_path' is required"
        patch_p = Path(str(patch)).expanduser()
        if not patch_p.exists():
            return f"Error: patch file not found: {patch_p}"
        if self._z3asm_bin is None or not self._z3asm_bin.exists():
            return "Error: z3asm binary missing"
        rom_p = self._project.rom_path
        if rom_p is None or not rom_p.exists():
            return "Error: no ROM available; set a rom_path on the project"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            emit_flags, emitted_paths, emit_summary = _build_emit_flags(
                arguments, lint_only=lint_only, tmp_path=tmp_path,
            )
            if isinstance(emit_flags, str):
                return emit_flags
            argv = [
                str(self._z3asm_bin),
                str(patch_p),
                str(rom_p),
            ]
            argv.extend(emit_flags)
            # Forward whitelisted extra flags.
            for flag in ("include", "define"):
                vals = arguments.get(flag)
                if isinstance(vals, list):
                    for v in vals:
                        argv.append(f"--{flag}={v}")

            result = await _run_subprocess(argv, timeout=self._timeout_s)
            if result.startswith("Error"):
                return result

            report: dict[str, Any] = {"emit": emit_summary, "summary": result.strip()}
            for basename, emitted in emitted_paths.items():
                if not emitted.exists():
                    continue
                if basename in _JSON_ARTIFACT_BASENAMES:
                    try:
                        report[basename] = json.loads(emitted.read_text(encoding="utf-8"))
                    except Exception as exc:  # noqa: BLE001
                        report[basename] = f"(parse failed: {exc})"
                elif basename == "symbols.mlb":
                    report["symbols_path"] = str(emitted.resolve())
                    report["symbols_size_bytes"] = emitted.stat().st_size
                elif basename == "symbols.sym":
                    report["symbols_wla_path"] = str(emitted.resolve())
                    report["symbols_wla_size_bytes"] = emitted.stat().st_size
            return json.dumps(report, indent=2)

    async def _disasm_bank(self, arguments: dict) -> str:
        if self._z3disasm_bin is None or not self._z3disasm_bin.exists():
            return "Error: z3disasm binary missing"
        rom_p = self._project.rom_path
        if rom_p is None or not rom_p.exists():
            return "Error: no ROM available; set a rom_path on the project"
        bank_start = arguments.get("bank_start")
        bank_end = arguments.get("bank_end", bank_start)
        if bank_start is None:
            return "Error: 'bank_start' is required"
        out_dir = arguments.get("out_dir")
        if out_dir:
            out_path = Path(str(out_dir)).expanduser()
            out_path.mkdir(parents=True, exist_ok=True)
        else:
            # Persist outputs so subsequent z3disasm_read_output can see them.
            out_path = Path(tempfile.mkdtemp(prefix="z3disasm_"))

        # z3disasm uses space-separated flags (``--rom <path>``), not ``=``.
        argv = [
            str(self._z3disasm_bin),
            "--rom", str(rom_p),
            "--out", str(out_path),
            "--bank-start", str(bank_start),
            "--bank-end", str(bank_end),
        ]
        labels = arguments.get("labels") or (str(self._project.symbols_mlb) if self._project.symbols_mlb else "")
        if labels:
            argv.extend(["--labels", labels])
        hooks = arguments.get("hooks")
        if hooks:
            argv.extend(["--hooks", str(hooks)])
        result = await _run_subprocess(argv, timeout=self._timeout_s)
        if result.startswith("Error"):
            return result
        generated = sorted(out_path.glob("bank_*.asm"))
        if not generated:
            return json.dumps({
                "out_dir": str(out_path),
                "files": [],
                "note": "no bank_*.asm files emitted",
                "stderr": result.strip(),
            }, indent=2)
        previews = []
        for p in generated[:8]:
            head = _read_head(p, MAX_PREVIEW_LINES)
            previews.append({
                "path": str(p),
                "size_bytes": p.stat().st_size,
                "preview": head,
            })
        return json.dumps({
            "out_dir": str(out_path),
            "files_generated": len(generated),
            "files": previews,
        }, indent=2)

    async def _read_output(self, arguments: dict) -> str:
        path_arg = arguments.get("path")
        if not path_arg:
            return "Error: 'path' is required"
        p = Path(str(path_arg)).expanduser()
        if not p.exists():
            return f"Error: file not found: {p}"
        lines = int(arguments.get("lines", 200) or 200)
        return _read_head(p, lines)


def _build_emit_flags(
    arguments: dict[str, Any],
    *,
    lint_only: bool,
    tmp_path: Path,
) -> tuple[list[str] | str, dict[str, Path], list[str]]:
    raw_targets = arguments.get("emit_targets")
    if raw_targets is None:
        raw_targets = arguments.get("emit")
    if raw_targets is None:
        targets = list(_DEFAULT_LINT_EMITS if lint_only else _DEFAULT_ASSEMBLE_EMITS)
    elif isinstance(raw_targets, str):
        targets = [part.strip() for part in raw_targets.split(",") if part.strip()]
    elif isinstance(raw_targets, list):
        targets = []
        for value in raw_targets:
            text = str(value).strip()
            if text:
                targets.append(text)
    else:
        return "Error: 'emit_targets' must be a list of strings", {}, []

    if not targets:
        return "Error: at least one emit target is required", {}, []

    if not lint_only and not _targets_request_symbols(targets):
        targets.append("symbols.mlb")

    emit_flags: list[str] = []
    emitted_paths: dict[str, Path] = {}
    emit_summary: list[str] = []
    for target in targets:
        emit_arg, basename, path = _resolve_emit_target(target, tmp_path)
        emit_flags.append(f"--emit={emit_arg}")
        emit_summary.append(target)
        if basename and path is not None:
            emitted_paths[basename] = path
    return emit_flags, emitted_paths, emit_summary


def _resolve_emit_target(target: str, tmp_path: Path) -> tuple[str, str | None, Path | None]:
    text = target.strip()
    lower = text.lower()
    mapped = _SIMPLE_EMIT_TARGETS.get(lower)
    if mapped is not None:
        kind, basename = mapped
        path = tmp_path / basename
        return f"{kind}:{path}", basename, path
    if ":" in text:
        kind, raw_path = text.split(":", 1)
        path = Path(raw_path).expanduser()
        basename = path.name if path.name in _JSON_ARTIFACT_BASENAMES else None
        if path.name == "symbols.mlb":
            basename = "symbols.mlb"
        if path.name == "symbols.sym":
            basename = "symbols.sym"
        return f"{kind}:{path}", basename, path
    return text, None, None


def _targets_request_symbols(targets: list[str]) -> bool:
    for target in targets:
        lowered = target.strip().lower()
        if lowered.startswith("symbols"):
            return True
        if ":" in lowered:
            kind, _, path = lowered.partition(":")
            if kind.startswith("symbols") or path.endswith(".mlb") or path.endswith(".sym"):
                return True
    return False


def _read_head(path: Path, lines: int) -> str:
    """Read up to *lines* lines from *path*, returning the text."""
    result: list[str] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for _ in range(max(1, lines)):
                line = f.readline()
                if not line:
                    break
                result.append(line.rstrip("\n"))
    except OSError as exc:
        return f"Error: {exc}"
    return "\n".join(result)


async def _run_subprocess(argv: list[str], *, timeout: float) -> str:
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout,
        )
    except asyncio.TimeoutError:
        return f"Error: subprocess timed out after {timeout:.0f}s: {argv[0]}"
    except Exception as exc:  # noqa: BLE001
        return f"Error launching {argv[0]}: {exc}"
    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    if proc.returncode not in (0, None):
        body = stderr.strip() or stdout.strip() or "(no output)"
        return f"Error: {argv[0]} exit={proc.returncode}: {body}"
    return (stdout + ("\n" + stderr if stderr.strip() else "")).strip() or "(no output)"


_TOOL_SCHEMAS: dict[str, dict] = {
    "z3asm_assemble": {
        "type": "function",
        "function": {
            "name": "z3asm_assemble",
            "description": (
                "Assemble a z3asm patch against the active ROM. This is a WRITE tool "
                "(mutates ROM bytes on success); use z3asm_lint for read-only checks. "
                "Structured outputs are captured from per-invocation temp files and "
                "returned inline."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "patch_path": {"type": "string", "description": "Path to .asm patch file"},
                    "emit_targets": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Emit targets such as diagnostics, sourcemap, hooks, annotations, "
                            "symbols.mlb, or explicit kind:/path values. Defaults to "
                            "[diagnostics, sourcemap] plus symbols.mlb."
                        ),
                    },
                    "emit": {
                        "type": "string",
                        "description": "Deprecated string form of emit_targets; comma-separated targets are accepted for compatibility.",
                    },
                    "include": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Additional include dirs (-I)",
                    },
                    "define": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Additional defines (e.g., FEATURE_X=1)",
                    },
                },
                "required": ["patch_path"],
            },
        },
    },
    "z3asm_lint": {
        "type": "function",
        "function": {
            "name": "z3asm_lint",
            "description": "Run z3asm in lint mode (read-only) and return lint JSON.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patch_path": {"type": "string", "description": "Path to .asm patch file"},
                    "emit_targets": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional emit targets; defaults to [lint].",
                    },
                    "emit": {
                        "type": "string",
                        "description": "Deprecated string form of emit_targets.",
                    },
                    "include": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Additional include dirs (-I)",
                    },
                    "define": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Additional defines (e.g., FEATURE_X=1)",
                    },
                },
                "required": ["patch_path"],
            },
        },
    },
    "z3disasm_bank": {
        "type": "function",
        "function": {
            "name": "z3disasm_bank",
            "description": (
                "Run z3disasm to emit bank_XX.asm for a bank range from the active ROM. "
                "Returns the list of generated .asm paths and a short preview of each. "
                "Use z3disasm_read_output(path, lines=N) to read the full contents."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "bank_start": {"type": "string", "description": "First bank (e.g., 0, 0x02)"},
                    "bank_end": {"type": "string", "description": "Last bank (optional; defaults to bank_start)"},
                    "labels": {"type": "string", "description": "Optional label/symbol file path"},
                    "hooks": {"type": "string", "description": "Optional hooks.json path"},
                    "out_dir": {
                        "type": "string",
                        "description": "Output directory. If omitted a tempdir is used.",
                    },
                },
                "required": ["bank_start"],
            },
        },
    },
    "z3disasm_read_output": {
        "type": "function",
        "function": {
            "name": "z3disasm_read_output",
            "description": "Read a previously-generated bank_XX.asm file with a line budget.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to a bank_XX.asm file"},
                    "lines": {"type": "integer", "description": "Maximum lines to return (default 200)"},
                },
                "required": ["path"],
            },
        },
    },
}
