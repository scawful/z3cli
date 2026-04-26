"""High-level transactional bridge for 65816 patch test workflows."""

from __future__ import annotations

import base64
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable

from core.asm_workflow import AsmPatchInput, AsmPatchResult, AssertionOutcome, WorkflowArtifact
from core.rom_project import RomProject
from protocol.z3asm_bridge import Z3asmBridge


SERVER_NAME = "asm-workflow"
ASM_PATCH_TEST_TOOL = "asm_patch_test"
HOOK_TRY_TOOL = "hook_try"
EMU_ASSERT_TOOL = "emu_assert"
SCENARIO_RUN_TOOL = "scenario_run"

_TOOL_ORDER = [
    ASM_PATCH_TEST_TOOL,
    HOOK_TRY_TOOL,
    EMU_ASSERT_TOOL,
    SCENARIO_RUN_TOOL,
]


class _WorkflowAbort(Exception):
    """Internal control-flow signal for early workflow termination."""


def _tool_schema(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str],
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


_COMMON_RUN_PROPERTIES: dict[str, Any] = {
    "frames": {
        "type": "integer",
        "description": "Frames to execute after setup.",
        "default": 120,
    },
    "breakpoints": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Optional breakpoint addresses for the emulator run.",
    },
    "assertions": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Optional assertion expressions to evaluate after execution.",
    },
    "capture_screenshot": {
        "type": "boolean",
        "description": "Persist a PNG screenshot artifact after the run.",
        "default": False,
    },
    "restore_after": {
        "type": "boolean",
        "description": "Save and restore emulator state around the workflow when possible.",
        "default": True,
    },
    "preserve_artifacts": {
        "type": "boolean",
        "description": "Keep the workflow temp directory instead of cleaning it up.",
        "default": False,
    },
    "backend": {
        "type": "string",
        "description": "Debugger backend hint forwarded to yaze-debugger (default auto).",
        "default": "auto",
    },
}

_ASM_PROPERTIES: dict[str, Any] = {
    "patch_path": {
        "type": "string",
        "description": "Path to the .asm patch file to lint and assemble.",
    },
    "rom_path_override": {
        "type": "string",
        "description": "Optional ROM path to use instead of the session ROM.",
    },
    "scenario": {
        "type": "string",
        "description": "Optional named test state to load before execution.",
    },
    "include": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Optional z3asm include directories.",
    },
    "define": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Optional z3asm defines such as FEATURE=1.",
    },
    "emit_targets": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Optional z3asm emit targets forwarded to lint/assemble.",
    },
}

_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    ASM_PATCH_TEST_TOOL: _tool_schema(
        ASM_PATCH_TEST_TOOL,
        (
            "Transactional 65816 patch test loop: lint a patch, assemble it against a "
            "temporary ROM copy, load that ROM into the emulator, optionally load a "
            "named scenario, run frames/assertions, and return a structured JSON result."
        ),
        {
            **_ASM_PROPERTIES,
            **_COMMON_RUN_PROPERTIES,
        },
        ["patch_path"],
    ),
    HOOK_TRY_TOOL: _tool_schema(
        HOOK_TRY_TOOL,
        (
            "Address-targeted hook workflow: validate a hook target against reference tooling "
            "when available, then lint, assemble, load a temporary ROM, and run the emulator "
            "scenario/assertions in one structured pass."
        ),
        {
            **_ASM_PROPERTIES,
            "address": {
                "type": "string",
                "description": "Hook target address or symbol name to validate before assembly.",
            },
            **_COMMON_RUN_PROPERTIES,
        },
        ["patch_path", "address"],
    ),
    EMU_ASSERT_TOOL: _tool_schema(
        EMU_ASSERT_TOOL,
        (
            "Run the emulator from its current state for a number of frames and evaluate "
            "assertions against the resulting CPU/game state."
        ),
        dict(_COMMON_RUN_PROPERTIES),
        [],
    ),
    SCENARIO_RUN_TOOL: _tool_schema(
        SCENARIO_RUN_TOOL,
        (
            "Load a named test scenario, run the emulator for a number of frames, and "
            "return a structured state/screenshot result envelope."
        ),
        {
            "scenario": {
                "type": "string",
                "description": "Named test state to load before execution.",
            },
            "frames": _COMMON_RUN_PROPERTIES["frames"],
            "breakpoints": _COMMON_RUN_PROPERTIES["breakpoints"],
            "capture_screenshot": _COMMON_RUN_PROPERTIES["capture_screenshot"],
            "restore_after": _COMMON_RUN_PROPERTIES["restore_after"],
            "preserve_artifacts": _COMMON_RUN_PROPERTIES["preserve_artifacts"],
            "backend": _COMMON_RUN_PROPERTIES["backend"],
        },
        ["scenario"],
    ),
}


def _is_error_output(text: str) -> bool:
    return text.lstrip().startswith("Error")


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


def _coerce_assertions(payload: dict[str, Any] | None) -> list[AssertionOutcome]:
    if payload is None:
        return []
    rows = payload.get("assertions")
    if not isinstance(rows, list):
        return []
    outcomes: list[AssertionOutcome] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        expr = str(row.get("expr") or row.get("expression") or "").strip()
        ok_value = row.get("ok")
        if ok_value is None:
            ok_value = row.get("passed")
        ok = bool(ok_value)
        detail = row.get("detail") or row.get("error")
        if detail is None and "actual" in row:
            detail = str(row["actual"])
        outcomes.append(AssertionOutcome(
            expr=expr,
            ok=ok,
            detail=None if detail is None else str(detail),
        ))
    return outcomes


def _extract_screenshot_bytes(output: str) -> bytes | None:
    payload = output.split("\n", 1)[1] if "\n" in output else output
    data = payload.strip()
    if not data:
        return None
    try:
        return base64.b64decode(data, validate=False)
    except Exception:  # noqa: BLE001
        return None


class AsmTestBridge:
    """Expose high-level author-test workflows as first-class tools."""

    def __init__(
        self,
        project: RomProject,
        *,
        mcp_bridge: Any | None = None,
        z3asm_factory: Callable[[RomProject], Any] | None = None,
    ) -> None:
        self._project = project
        self._mcp_bridge = mcp_bridge
        self._z3asm_factory = z3asm_factory or (lambda project: Z3asmBridge(project))
        self._available_tools: set[str] = set()

    async def connect(self) -> list[str]:
        asm_names = await self._probe_z3asm_tools()
        has_asm = {"z3asm_lint", "z3asm_assemble"}.issubset(asm_names)
        has_emu_test = self._has_debugger_tool("emu_test_run")
        has_load_rom = self._has_debugger_tool("load_rom")
        has_load_state = self._has_debugger_tool("load_test_state")

        available: set[str] = set()
        if has_emu_test:
            available.add(EMU_ASSERT_TOOL)
        if has_emu_test and has_load_state:
            available.add(SCENARIO_RUN_TOOL)
        if has_asm and has_load_rom and has_emu_test:
            available.add(ASM_PATCH_TEST_TOOL)
            available.add(HOOK_TRY_TOOL)

        self._available_tools = available
        return []

    def get_openai_tools(self) -> list[dict]:
        return [_TOOL_SCHEMAS[name] for name in _TOOL_ORDER if name in self._available_tools]

    async def call_tool(self, name: str, arguments: dict) -> str:
        if name == ASM_PATCH_TEST_TOOL:
            return await self._run_patch_workflow(arguments, tool_name=name)
        if name == HOOK_TRY_TOOL:
            return await self._run_patch_workflow(arguments, tool_name=name, hook_address=arguments.get("address"))
        if name == EMU_ASSERT_TOOL:
            return await self._run_emu_assert(arguments)
        if name == SCENARIO_RUN_TOOL:
            return await self._run_scenario_run(arguments)
        return f"Error: unknown asm workflow tool '{name}'"

    def get_tool_server(self, tool_name: str) -> str:
        return SERVER_NAME if tool_name in self._available_tools else "unknown"

    @property
    def tool_count(self) -> int:
        return len(self._available_tools)

    @property
    def server_names(self) -> list[str]:
        return [SERVER_NAME] if self._available_tools else []

    @property
    def server_tool_counts(self) -> dict[str, int]:
        return {SERVER_NAME: len(self._available_tools)} if self._available_tools else {}

    def is_write_tool(self, tool_name: str) -> bool | None:
        if tool_name not in self._available_tools:
            return None
        return tool_name in {ASM_PATCH_TEST_TOOL, HOOK_TRY_TOOL}

    async def close(self) -> None:
        return None

    async def _probe_z3asm_tools(self) -> set[str]:
        probe = self._z3asm_factory(self._project)
        try:
            await probe.connect()
            return {
                tool.get("function", {}).get("name", "")
                for tool in probe.get_openai_tools()
            }
        finally:
            close = getattr(probe, "close", None)
            if close is not None:
                await close()

    def _find_exposed_tool(
        self,
        actual_name: str,
        *,
        preferred_servers: tuple[str, ...] = (),
    ) -> str | None:
        if self._mcp_bridge is None:
            return None
        finder = getattr(self._mcp_bridge, "find_exposed_tool", None)
        if finder is None:
            return None
        seen: set[str] = set()
        for server in preferred_servers:
            seen.add(server)
            exposed = finder(server, actual_name)
            if exposed is not None:
                return exposed
        for server in getattr(self._mcp_bridge, "server_names", []):
            if server in seen:
                continue
            exposed = finder(server, actual_name)
            if exposed is not None:
                return exposed
        return None

    def _has_mcp_tool(self, actual_name: str, *, preferred_servers: tuple[str, ...] = ()) -> bool:
        return self._find_exposed_tool(actual_name, preferred_servers=preferred_servers) is not None

    def _has_debugger_tool(self, actual_name: str) -> bool:
        return self._has_mcp_tool(actual_name, preferred_servers=("yaze-debugger",))

    async def _call_mcp_tool(
        self,
        actual_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        preferred_servers: tuple[str, ...] = (),
    ) -> str:
        if self._mcp_bridge is None:
            server_text = ", ".join(preferred_servers) if preferred_servers else "MCP"
            return f"Error: {server_text} is not connected"
        exposed = self._find_exposed_tool(actual_name, preferred_servers=preferred_servers)
        if exposed is None:
            server_text = ", ".join(preferred_servers) if preferred_servers else "MCP"
            return f"Error: {server_text} tool '{actual_name}' is unavailable"
        return await self._mcp_bridge.call_tool(exposed, arguments or {})

    async def _call_debugger(self, actual_name: str, arguments: dict[str, Any] | None = None) -> str:
        return await self._call_mcp_tool(actual_name, arguments, preferred_servers=("yaze-debugger",))

    def _new_result(self, patch_input: AsmPatchInput, *, tool_name: str, asm_skipped: bool = False) -> AsmPatchResult:
        result = AsmPatchResult(
            lint_ok=asm_skipped,
            assemble_ok=asm_skipped,
        )
        result.diagnostics["tool"] = tool_name
        result.diagnostics["input"] = patch_input.to_dict()
        if asm_skipped:
            result.diagnostics["skipped_stages"] = ["lint", "assemble"]
        return result

    def _create_session_context(
        self,
        result: AsmPatchResult,
        *,
        prefix: str,
        preserve_artifacts: bool,
        artifact_kind: str = "session_dir",
    ) -> tuple[Path, WorkflowArtifact, Path, WorkflowArtifact]:
        session_dir = Path(tempfile.mkdtemp(prefix=prefix))
        session_artifact = result.add_artifact(
            artifact_kind,
            str(session_dir),
            preserved=preserve_artifacts,
            exists=True,
        )
        snapshot_path = session_dir / "pre_run.state"
        snapshot_artifact = result.add_artifact(
            "emulator_snapshot",
            str(snapshot_path),
            preserved=preserve_artifacts,
            exists=False,
        )
        return session_dir, session_artifact, snapshot_path, snapshot_artifact

    @staticmethod
    def _mark_artifact_exists(*pairs: tuple[WorkflowArtifact, Path]) -> None:
        for artifact, path in pairs:
            artifact.exists = path.exists()

    def _apply_emu_test_payload(self, result: AsmPatchResult, payload: dict[str, Any]) -> None:
        result.emulator_ok = bool(payload.get("success", False))
        result.assertions = _coerce_assertions(payload)
        final_state = payload.get("final_state")
        if isinstance(final_state, dict):
            if isinstance(final_state.get("cpu"), dict):
                result.cpu = final_state.get("cpu")
            else:
                result.cpu = final_state
            memory = final_state.get("memory")
            if isinstance(memory, (dict, str)):
                result.memory = memory
        breakpoint_hits = payload.get("breakpoint_hits")
        if isinstance(breakpoint_hits, list):
            result.breakpoint_hits = breakpoint_hits
        elif payload.get("breakpoint_hit"):
            result.breakpoint_hits = [{"hit": True}]

    async def _capture_screenshot(self, result: AsmPatchResult, backend: str) -> None:
        if not self._has_debugger_tool("emu_screenshot"):
            result.warnings.append("capture_screenshot requested but yaze-debugger emu_screenshot is unavailable")
            return
        screenshot_raw = await self._call_debugger("emu_screenshot", {"backend": backend})
        result.diagnostics["screenshot"] = screenshot_raw
        if _is_error_output(screenshot_raw):
            result.warnings.append(screenshot_raw)
            return
        png_bytes = _extract_screenshot_bytes(screenshot_raw)
        if not png_bytes:
            result.warnings.append("capture_screenshot requested but screenshot payload was not valid base64")
            return
        fd, screenshot_file = tempfile.mkstemp(prefix="z3cli_asm_patch_", suffix=".png")
        os.close(fd)
        Path(screenshot_file).write_bytes(png_bytes)
        Path(screenshot_file).chmod(0o644)
        result.screenshot_path = screenshot_file
        result.add_artifact(
            "screenshot",
            screenshot_file,
            preserved=True,
            exists=True,
        )

    async def _run_debugger_session(
        self,
        result: AsmPatchResult,
        patch_input: AsmPatchInput,
        *,
        session_dir: Path,
        session_artifact: WorkflowArtifact,
        snapshot_path: Path,
        snapshot_artifact: WorkflowArtifact,
        scenario: str | None,
        load_rom_path: Path | None,
        snapshot_label: str,
    ) -> None:
        restore_message: str | None = None
        try:
            if patch_input.restore_after and self._has_debugger_tool("save_emulator_state") and self._has_debugger_tool("load_emulator_state"):
                snapshot_raw = await self._call_debugger("save_emulator_state", {
                    "filepath": str(snapshot_path),
                    "description": snapshot_label,
                    "is_checkpoint": False,
                })
                result.diagnostics["snapshot_save"] = snapshot_raw
                if _is_error_output(snapshot_raw):
                    result.warnings.append(snapshot_raw)
                else:
                    snapshot_artifact.exists = snapshot_path.exists()
            elif patch_input.restore_after:
                result.warnings.append("restore_after requested but save/load emulator state tools are unavailable")

            if load_rom_path is not None:
                load_rom_raw = await self._call_debugger("load_rom", {"filepath": str(load_rom_path)})
                result.diagnostics["load_rom"] = load_rom_raw
                if _is_error_output(load_rom_raw):
                    result.mark_failure("setup", load_rom_raw)
                    raise _WorkflowAbort

            if scenario:
                if not self._has_debugger_tool("load_test_state"):
                    result.mark_failure("scenario", "scenario requested but yaze-debugger load_test_state is unavailable")
                    raise _WorkflowAbort
                scenario_raw = await self._call_debugger("load_test_state", {"state_id": scenario})
                result.diagnostics["scenario"] = scenario_raw
                if _is_error_output(scenario_raw):
                    result.mark_failure("scenario", scenario_raw)
                    raise _WorkflowAbort
                result.scenario_loaded = True

            emu_test_raw = await self._call_debugger("emu_test_run", {
                "frames": patch_input.frames,
                "assertions": list(patch_input.assertions),
                "breakpoints": list(patch_input.breakpoints),
                "backend": patch_input.backend,
            })
            emu_payload = _parse_json_output(emu_test_raw)
            result.diagnostics["emulator"] = emu_payload if emu_payload is not None else emu_test_raw
            if _is_error_output(emu_test_raw) or not isinstance(emu_payload, dict):
                result.mark_failure("runtime", emu_test_raw)
                raise _WorkflowAbort

            self._apply_emu_test_payload(result, emu_payload)
            if patch_input.capture_screenshot:
                await self._capture_screenshot(result, patch_input.backend)

            if result.assertions and not all(assertion.ok for assertion in result.assertions):
                result.mark_failure("assert", "one or more assertions failed")
            elif not result.emulator_ok:
                result.mark_failure("runtime", "emulator test run reported failure")
            else:
                result.ok = True
        except _WorkflowAbort:
            pass
        finally:
            if patch_input.restore_after and snapshot_path.exists():
                restore_raw = await self._call_debugger("load_emulator_state", {
                    "filepath": str(snapshot_path),
                    "verify_checksum": False,
                })
                result.diagnostics["snapshot_restore"] = restore_raw
                if _is_error_output(restore_raw):
                    restore_message = restore_raw

            if not patch_input.preserve_artifacts:
                shutil.rmtree(session_dir, ignore_errors=True)
                self._mark_artifact_exists(
                    (session_artifact, session_dir),
                    (snapshot_artifact, snapshot_path),
                )

            if restore_message is not None:
                result.warnings.append(restore_message)
                if result.failure_stage is None:
                    result.mark_failure("cleanup", restore_message)
                else:
                    result.ok = False

    async def _validate_hook_target(
        self,
        result: AsmPatchResult,
        *,
        address: str,
        patch_path: Path,
    ) -> None:
        result.diagnostics["hook_address"] = address
        if not self._has_mcp_tool("validate_hook", preferred_servers=("hyrule-historian",)):
            result.warnings.append("reference validate_hook tool is unavailable; proceeding with lint/assemble only")
            return
        hook_code = patch_path.read_text(encoding="utf-8", errors="replace")
        validate_raw = await self._call_mcp_tool(
            "validate_hook",
            {
                "target": address,
                "hook_code": hook_code,
            },
            preferred_servers=("hyrule-historian",),
        )
        result.diagnostics["hook_validate"] = validate_raw
        if _is_error_output(validate_raw):
            result.mark_failure("validate", validate_raw)
            raise _WorkflowAbort

    async def _run_patch_workflow(
        self,
        arguments: dict[str, Any],
        *,
        tool_name: str,
        hook_address: object | None = None,
    ) -> str:
        patch_input = AsmPatchInput.from_tool_arguments(arguments)
        result = self._new_result(patch_input, tool_name=tool_name)

        if not patch_input.patch_path:
            result.mark_failure("setup", "patch_path is required")
            return json.dumps(result.to_dict(), indent=2)

        patch_path = Path(patch_input.patch_path).expanduser()
        if not patch_path.exists():
            result.mark_failure("setup", f"patch file not found: {patch_path}")
            return json.dumps(result.to_dict(), indent=2)

        base_project = (
            self._project.with_rom_path(patch_input.rom_path_override)
            if patch_input.rom_path_override
            else self._project
        )
        result.diagnostics["project"] = base_project.diagnostics()
        if base_project.rom_path is None or not base_project.rom_path.exists():
            result.mark_failure("setup", f"no ROM available for {tool_name}")
            return json.dumps(result.to_dict(), indent=2)

        session_dir, session_artifact, snapshot_path, snapshot_artifact = self._create_session_context(
            result,
            prefix="z3cli_asm_patch_",
            preserve_artifacts=patch_input.preserve_artifacts,
            artifact_kind="transaction_dir",
        )
        temp_rom = session_dir / base_project.rom_path.name
        temp_rom_artifact = result.add_artifact(
            "temp_rom",
            str(temp_rom),
            preserved=patch_input.preserve_artifacts,
            exists=False,
        )

        z3asm: Any | None = None
        try:
            shutil.copy2(base_project.rom_path, temp_rom)
            temp_rom_artifact.exists = temp_rom.exists()
            txn_project = base_project.with_rom_path(temp_rom)

            if tool_name == HOOK_TRY_TOOL:
                hook_target = str(hook_address or "").strip()
                if not hook_target:
                    result.mark_failure("validate", "address is required for hook_try")
                    raise _WorkflowAbort
                await self._validate_hook_target(result, address=hook_target, patch_path=patch_path)

            z3asm = self._z3asm_factory(txn_project)
            await z3asm.connect()
            lint_args = {"patch_path": str(patch_path)}
            assemble_args = {"patch_path": str(patch_path)}
            if patch_input.emit_targets:
                lint_args["emit_targets"] = list(patch_input.emit_targets)
                assemble_args["emit_targets"] = list(patch_input.emit_targets)
            if patch_input.include:
                lint_args["include"] = list(patch_input.include)
                assemble_args["include"] = list(patch_input.include)
            if patch_input.define:
                lint_args["define"] = list(patch_input.define)
                assemble_args["define"] = list(patch_input.define)

            lint_raw = await z3asm.call_tool("z3asm_lint", lint_args)
            lint_payload = _parse_json_output(lint_raw)
            result.diagnostics["lint"] = lint_payload if lint_payload is not None else lint_raw
            lint_ok = not _is_error_output(lint_raw)
            explicit_lint_ok = _extract_bool(
                lint_payload if isinstance(lint_payload, dict) else None,
                ("lint.json", "ok"),
                ("success",),
            )
            if explicit_lint_ok is not None:
                lint_ok = explicit_lint_ok
            result.lint_ok = lint_ok
            if not result.lint_ok:
                result.mark_failure("lint", "z3asm lint failed")
                raise _WorkflowAbort

            assemble_raw = await z3asm.call_tool("z3asm_assemble", assemble_args)
            assemble_payload = _parse_json_output(assemble_raw)
            result.diagnostics["assemble"] = assemble_payload if assemble_payload is not None else assemble_raw
            result.assemble_ok = not _is_error_output(assemble_raw)
            if not result.assemble_ok:
                result.mark_failure("assemble", "z3asm assemble failed")
                raise _WorkflowAbort

            await self._run_debugger_session(
                result,
                patch_input,
                session_dir=session_dir,
                session_artifact=session_artifact,
                snapshot_path=snapshot_path,
                snapshot_artifact=snapshot_artifact,
                scenario=patch_input.scenario,
                load_rom_path=temp_rom,
                snapshot_label=f"{tool_name}:{patch_path.name}",
            )
        except _WorkflowAbort:
            pass
        except Exception as exc:  # noqa: BLE001
            result.mark_failure("runtime", f"unexpected asm workflow failure: {exc}")
        finally:
            if z3asm is not None:
                close = getattr(z3asm, "close", None)
                if close is not None:
                    await close()
            if not patch_input.preserve_artifacts:
                temp_rom_artifact.exists = temp_rom.exists()

        return json.dumps(result.to_dict(), indent=2)

    async def _run_emu_assert(self, arguments: dict[str, Any]) -> str:
        patch_input = AsmPatchInput.from_tool_arguments(arguments)
        result = self._new_result(patch_input, tool_name=EMU_ASSERT_TOOL, asm_skipped=True)
        session_dir, session_artifact, snapshot_path, snapshot_artifact = self._create_session_context(
            result,
            prefix="z3cli_emu_assert_",
            preserve_artifacts=patch_input.preserve_artifacts,
        )
        try:
            await self._run_debugger_session(
                result,
                patch_input,
                session_dir=session_dir,
                session_artifact=session_artifact,
                snapshot_path=snapshot_path,
                snapshot_artifact=snapshot_artifact,
                scenario=None,
                load_rom_path=None,
                snapshot_label=EMU_ASSERT_TOOL,
            )
        except Exception as exc:  # noqa: BLE001
            result.mark_failure("runtime", f"unexpected emu_assert failure: {exc}")
        return json.dumps(result.to_dict(), indent=2)

    async def _run_scenario_run(self, arguments: dict[str, Any]) -> str:
        patch_input = AsmPatchInput.from_tool_arguments(arguments)
        result = self._new_result(patch_input, tool_name=SCENARIO_RUN_TOOL, asm_skipped=True)
        if not patch_input.scenario:
            result.mark_failure("scenario", "scenario is required")
            return json.dumps(result.to_dict(), indent=2)
        patch_input.assertions = []
        session_dir, session_artifact, snapshot_path, snapshot_artifact = self._create_session_context(
            result,
            prefix="z3cli_scenario_run_",
            preserve_artifacts=patch_input.preserve_artifacts,
        )
        try:
            await self._run_debugger_session(
                result,
                patch_input,
                session_dir=session_dir,
                session_artifact=session_artifact,
                snapshot_path=snapshot_path,
                snapshot_artifact=snapshot_artifact,
                scenario=patch_input.scenario,
                load_rom_path=None,
                snapshot_label=f"{SCENARIO_RUN_TOOL}:{patch_input.scenario}",
            )
        except Exception as exc:  # noqa: BLE001
            result.mark_failure("runtime", f"unexpected scenario_run failure: {exc}")
        return json.dumps(result.to_dict(), indent=2)
