"""Repository verification hooks triggered after accepted writes."""

from __future__ import annotations

import asyncio
import json
import shlex
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from z3cli.core.tool_bridge import ToolBridge


OUTPUT_CHAR_LIMIT = 1200
DEFAULT_ASM_LINT_TIMEOUT_S = 45.0
DEFAULT_ASM_SMOKE_TIMEOUT_S = 60.0
DEFAULT_ASM_SMOKE_FRAMES = 30
_ASM_LINT_SUFFIXES = {".asm", ".inc", ".s"}
_ASM_RELATED_SUFFIXES = _ASM_LINT_SUFFIXES | {".cfg", ".ld", ".lds", ".link"}
_ASM_RELATED_FILENAMES = {"z3dk.toml", "build_rom.sh", "build-rom.sh"}
_ASM_VERIFY_CONFIG_CANDIDATES = (
    Path("config") / "asm_verify.toml",
    Path("asm_verify.toml"),
)


@dataclass
class VerificationCommand:
    argv: list[str]
    cwd: Path
    timeout_s: float = 30.0
    tool_name: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    label: str | None = None

    @property
    def display(self) -> str:
        if self.label:
            return self.label
        if self.tool_name:
            return self.tool_name
        return " ".join(shlex.quote(part) for part in self.argv)


@dataclass
class VerificationResult:
    command: str
    cwd: str
    ok: bool
    exit_code: int | None
    output: str
    duration_ms: int


@dataclass
class VerificationSummary:
    commands: list[str]
    results: list[VerificationResult]

    def render(self) -> str:
        if not self.results:
            return ""
        lines = ["Verification:"]
        for result in self.results:
            status = "ok" if result.ok else "failed"
            code = "" if result.exit_code is None else f" exit {result.exit_code}"
            lines.append(f"- {status} `{result.command}` ({result.duration_ms}ms{code})")
            if result.output:
                lines.append(_indent(_collapse_output(result.output)))
        return "\n".join(lines)


def _indent(text: str) -> str:
    return "\n".join(f"  {line}" for line in text.splitlines())


def _collapse_output(output: str) -> str:
    trimmed = output.strip()
    if len(trimmed) <= OUTPUT_CHAR_LIMIT:
        return trimmed
    keep = OUTPUT_CHAR_LIMIT // 2
    return (
        trimmed[:keep]
        + "\n...\n"
        + trimmed[-keep:]
    )


@dataclass(frozen=True)
class AsmVerificationConfig:
    patch_path: str | None = None
    scenario: str | None = None
    frames: int = DEFAULT_ASM_SMOKE_FRAMES
    breakpoints: tuple[str, ...] = ()
    assertions: tuple[str, ...] = ()
    capture_screenshot: bool = False
    restore_after: bool = True
    include: tuple[str, ...] = ()
    define: tuple[str, ...] = ()
    emit_targets: tuple[str, ...] = ()
    lint_timeout_s: float = DEFAULT_ASM_LINT_TIMEOUT_S
    smoke_timeout_s: float = DEFAULT_ASM_SMOKE_TIMEOUT_S


def _parse_json_output(text: str) -> dict[str, Any] | list[Any] | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _extract_bool(payload: dict[str, Any] | None, *paths: tuple[str, ...]) -> bool | None:
    if payload is None:
        return None
    for path in paths:
        cursor: Any = payload
        for key in path:
            if not isinstance(cursor, dict) or key not in cursor:
                cursor = None
                break
            cursor = cursor[key]
        if isinstance(cursor, bool):
            return cursor
    return None


def _tool_result_ok(tool_name: str, output: str) -> bool:
    if output.lstrip().startswith("Error"):
        return False
    payload = _parse_json_output(output)
    if not isinstance(payload, dict):
        return True
    if tool_name == "z3asm_lint":
        explicit = _extract_bool(payload, ("lint.json", "ok"), ("ok",), ("success",))
    else:
        explicit = _extract_bool(payload, ("ok",), ("success",))
    return True if explicit is None else explicit


def _coerce_str_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return default


def _coerce_int(value: Any, default: int) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


def _coerce_float(value: Any, default: float) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return default


def _load_asm_verification_config(workspace: Path) -> AsmVerificationConfig | None:
    for relative in _ASM_VERIFY_CONFIG_CANDIDATES:
        candidate = workspace / relative
        if not candidate.is_file():
            continue
        try:
            with candidate.open("rb") as handle:
                raw = tomllib.load(handle)
        except Exception:
            return None
        payload = raw
        for key in ("asm_verify", "verify", "asm"):
            nested = payload.get(key)
            if isinstance(nested, dict):
                payload = nested
                break
        if not isinstance(payload, dict):
            return None
        return AsmVerificationConfig(
            patch_path=str(payload.get("patch_path") or payload.get("patch") or "").strip() or None,
            scenario=str(payload.get("scenario") or "").strip() or None,
            frames=_coerce_int(payload.get("frames"), DEFAULT_ASM_SMOKE_FRAMES),
            breakpoints=_coerce_str_list(payload.get("breakpoints")),
            assertions=_coerce_str_list(payload.get("assertions")),
            capture_screenshot=_coerce_bool(payload.get("capture_screenshot"), False),
            restore_after=_coerce_bool(payload.get("restore_after"), True),
            include=_coerce_str_list(payload.get("include")),
            define=_coerce_str_list(payload.get("define")),
            emit_targets=_coerce_str_list(payload.get("emit_targets")),
            lint_timeout_s=_coerce_float(payload.get("lint_timeout_s"), DEFAULT_ASM_LINT_TIMEOUT_S),
            smoke_timeout_s=_coerce_float(payload.get("smoke_timeout_s"), DEFAULT_ASM_SMOKE_TIMEOUT_S),
        )
    return None


def _display_path(workspace: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(workspace.resolve()))
    except ValueError:
        return str(path)


def _resolve_workspace_path(workspace: Path, raw_path: str | None) -> Path | None:
    if not raw_path:
        return None
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = workspace / candidate
    return candidate.resolve()


def _is_asm_related(path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix in _ASM_RELATED_SUFFIXES:
        return True
    return path.name.lower() in _ASM_RELATED_FILENAMES


def _bridge_tool_names(bridge: ToolBridge | None) -> set[str]:
    if bridge is None:
        return set()
    names: set[str] = set()
    for schema in bridge.get_openai_tools():
        function = schema.get("function") if isinstance(schema, dict) else None
        name = function.get("name") if isinstance(function, dict) else None
        if isinstance(name, str) and name:
            names.add(name)
    return names


def _build_lint_label(workspace: Path, patch_path: Path) -> str:
    return f"z3asm_lint {shlex.quote(_display_path(workspace, patch_path))}"


def _build_smoke_label(workspace: Path, patch_path: Path, config: AsmVerificationConfig) -> str:
    parts = [
        "asm_patch_test",
        shlex.quote(_display_path(workspace, patch_path)),
        "--scenario",
        shlex.quote(config.scenario or ""),
        "--frames",
        str(config.frames),
    ]
    for assertion in config.assertions:
        parts.extend(["--assert", shlex.quote(assertion)])
    return " ".join(parts)


def _select_asm_verification_commands(
    workspace: Path,
    changed_files: list[Path],
    *,
    bridge: ToolBridge | None,
    rom_path: Path | None,
) -> list[VerificationCommand]:
    if not any(_is_asm_related(path) for path in changed_files):
        return []
    tool_names = _bridge_tool_names(bridge)
    if not tool_names:
        return []

    config = _load_asm_verification_config(workspace) or AsmVerificationConfig()
    configured_patch = _resolve_workspace_path(workspace, config.patch_path)
    direct_targets = [
        path.resolve()
        for path in changed_files
        if path.is_file() and path.suffix.lower() in _ASM_LINT_SUFFIXES
    ]

    lint_targets: list[Path] = []
    if configured_patch is not None and configured_patch.is_file():
        lint_targets.append(configured_patch)
    else:
        lint_targets.extend(direct_targets)

    commands: list[VerificationCommand] = []
    seen_targets: set[Path] = set()
    if "z3asm_lint" in tool_names:
        for target in lint_targets:
            if target in seen_targets or not target.is_file():
                continue
            seen_targets.add(target)
            arguments: dict[str, Any] = {"patch_path": str(target)}
            if config.include:
                arguments["include"] = list(config.include)
            if config.define:
                arguments["define"] = list(config.define)
            if config.emit_targets:
                arguments["emit_targets"] = list(config.emit_targets)
            commands.append(VerificationCommand(
                argv=[],
                cwd=workspace,
                timeout_s=config.lint_timeout_s,
                tool_name="z3asm_lint",
                arguments=arguments,
                label=_build_lint_label(workspace, target),
            ))

    smoke_target: Path | None = None
    if config.scenario:
        if configured_patch is not None and configured_patch.is_file():
            smoke_target = configured_patch
        elif len(direct_targets) == 1:
            smoke_target = direct_targets[0]
    if smoke_target is not None and "asm_patch_test" in tool_names:
        arguments = {
            "patch_path": str(smoke_target),
            "scenario": config.scenario,
            "frames": config.frames,
            "breakpoints": list(config.breakpoints),
            "assertions": list(config.assertions),
            "capture_screenshot": config.capture_screenshot,
            "restore_after": config.restore_after,
        }
        if rom_path is not None:
            arguments["rom_path_override"] = str(rom_path)
        if config.include:
            arguments["include"] = list(config.include)
        if config.define:
            arguments["define"] = list(config.define)
        if config.emit_targets:
            arguments["emit_targets"] = list(config.emit_targets)
        commands.append(VerificationCommand(
            argv=[],
            cwd=workspace,
            timeout_s=config.smoke_timeout_s,
            tool_name="asm_patch_test",
            arguments=arguments,
            label=_build_smoke_label(workspace, smoke_target, config),
        ))
    return commands


def select_verification_commands(
    workspace: Path,
    changed_files: list[Path],
    *,
    bridge: ToolBridge | None = None,
    rom_path: Path | None = None,
) -> list[VerificationCommand]:
    commands: list[VerificationCommand] = []
    frontend_changed = False
    python_changed: list[str] = []
    workspace_root = workspace.resolve()

    for path in changed_files:
        try:
            rel = path.resolve().relative_to(workspace_root)
            rel_text = str(rel)
        except ValueError:
            rel_text = str(path)
        if rel_text == "frontend/package.json" or rel_text.startswith("frontend/"):
            frontend_changed = True
        if rel_text.endswith(".py") and path.is_file():
            python_changed.append(rel_text)

    if frontend_changed and (workspace / "frontend" / "package.json").is_file():
        commands.append(VerificationCommand(["npm", "run", "test"], cwd=workspace / "frontend", timeout_s=45.0))
        commands.append(VerificationCommand(["npm", "run", "build"], cwd=workspace / "frontend", timeout_s=45.0))

    if python_changed and (workspace / "pyproject.toml").is_file():
        commands.append(VerificationCommand(["python3", "-m", "py_compile", *python_changed], cwd=workspace))
        if (workspace / "tests").is_dir():
            commands.append(VerificationCommand(
                ["python3", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
                cwd=workspace,
                timeout_s=45.0,
            ))

    commands.extend(_select_asm_verification_commands(
        workspace,
        changed_files,
        bridge=bridge,
        rom_path=rom_path,
    ))

    deduped: list[VerificationCommand] = []
    seen: set[tuple[str, str]] = set()
    for command in commands:
        key = (str(command.cwd), command.display)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(command)
    return deduped


async def run_verification_hooks(
    workspace: Path,
    changed_files: list[Path],
    *,
    bridge: ToolBridge | None = None,
    rom_path: Path | None = None,
) -> VerificationSummary:
    commands = select_verification_commands(
        workspace,
        changed_files,
        bridge=bridge,
        rom_path=rom_path,
    )
    results: list[VerificationResult] = []

    for command in commands:
        started = time.perf_counter()
        output = ""
        exit_code: int | None = None
        ok = False
        if command.tool_name is not None:
            try:
                if bridge is None:
                    output = f"Error: verification tool '{command.tool_name}' is unavailable"
                else:
                    output = await asyncio.wait_for(
                        bridge.call_tool(command.tool_name, dict(command.arguments)),
                        timeout=command.timeout_s,
                    )
                ok = _tool_result_ok(command.tool_name, output)
            except asyncio.TimeoutError:
                output = f"Timed out after {command.timeout_s:.0f}s"
                ok = False
            except Exception as exc:
                output = f"Error: verification tool '{command.tool_name}' failed: {exc}"
                ok = False
        else:
            proc: asyncio.subprocess.Process | None = None
            try:
                proc = await asyncio.create_subprocess_exec(
                    *command.argv,
                    cwd=str(command.cwd),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=command.timeout_s)
                output = stdout.decode("utf-8", errors="replace")
                exit_code = proc.returncode
                ok = proc.returncode == 0
            except asyncio.TimeoutError:
                if proc is not None:
                    proc.kill()
                try:
                    stdout, _ = await proc.communicate() if proc is not None else (b"", b"")
                except ProcessLookupError:
                    stdout = b""
                output = f"Timed out after {command.timeout_s:.0f}s"
                timeout_output = stdout.decode("utf-8", errors="replace").strip()
                if timeout_output:
                    output += "\n" + timeout_output
                exit_code = None if proc is None else proc.returncode
                ok = False
        duration_ms = int((time.perf_counter() - started) * 1000)
        results.append(VerificationResult(
            command=command.display,
            cwd=str(command.cwd),
            ok=ok,
            exit_code=exit_code,
            output=output,
            duration_ms=duration_ms,
        ))

    return VerificationSummary(
        commands=[command.display for command in commands],
        results=results,
    )
