"""Shared contracts for 65816 author-test workflow tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _coerce_bool(value: object, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _coerce_int(value: object, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return default
    try:
        return int(text, 10)
    except ValueError:
        return default


def _coerce_str_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item) for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in text.split(",") if part.strip()]


@dataclass(slots=True)
class AsmPatchInput:
    """Normalized input for transactional patch-test workflows."""

    patch_path: str
    rom_path_override: str | None = None
    scenario: str | None = None
    frames: int = 120
    breakpoints: list[str] = field(default_factory=list)
    assertions: list[str] = field(default_factory=list)
    capture_screenshot: bool = False
    restore_after: bool = True
    preserve_artifacts: bool = False
    backend: str = "auto"
    include: list[str] = field(default_factory=list)
    define: list[str] = field(default_factory=list)
    emit_targets: list[str] = field(default_factory=list)

    @classmethod
    def from_tool_arguments(cls, arguments: dict[str, Any]) -> "AsmPatchInput":
        patch_path = str(arguments.get("patch_path") or arguments.get("patch") or "").strip()
        return cls(
            patch_path=patch_path,
            rom_path_override=_optional_str(arguments.get("rom_path_override") or arguments.get("rom_path")),
            scenario=_optional_str(arguments.get("scenario") or arguments.get("test_state")),
            frames=_coerce_int(arguments.get("frames"), 120),
            breakpoints=_coerce_str_list(arguments.get("breakpoints")),
            assertions=_coerce_str_list(arguments.get("assertions")),
            capture_screenshot=_coerce_bool(arguments.get("capture_screenshot"), False),
            restore_after=_coerce_bool(arguments.get("restore_after"), True),
            preserve_artifacts=_coerce_bool(arguments.get("preserve_artifacts"), False),
            backend=_optional_str(arguments.get("backend")) or "auto",
            include=_coerce_str_list(arguments.get("include")),
            define=_coerce_str_list(arguments.get("define")),
            emit_targets=_coerce_str_list(arguments.get("emit_targets") or arguments.get("emit")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "patch_path": self.patch_path,
            "rom_path_override": self.rom_path_override,
            "scenario": self.scenario,
            "frames": self.frames,
            "breakpoints": list(self.breakpoints),
            "assertions": list(self.assertions),
            "capture_screenshot": self.capture_screenshot,
            "restore_after": self.restore_after,
            "preserve_artifacts": self.preserve_artifacts,
            "backend": self.backend,
            "include": list(self.include),
            "define": list(self.define),
            "emit_targets": list(self.emit_targets),
        }


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass(slots=True)
class WorkflowArtifact:
    kind: str
    path: str
    preserved: bool = False
    exists: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "path": self.path,
            "preserved": self.preserved,
            "exists": self.exists,
        }


@dataclass(slots=True)
class AssertionOutcome:
    expr: str
    ok: bool
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "expr": self.expr,
            "ok": self.ok,
            "detail": self.detail,
        }


@dataclass(slots=True)
class AsmPatchResult:
    """Canonical result envelope for high-level ASM workflow tools."""

    ok: bool = False
    lint_ok: bool = False
    assemble_ok: bool = False
    emulator_ok: bool = False
    scenario_loaded: bool = False
    assertions: list[AssertionOutcome] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    cpu: dict[str, Any] | str | None = None
    memory: dict[str, Any] | str | None = None
    breakpoint_hits: list[Any] = field(default_factory=list)
    screenshot_path: str | None = None
    artifacts: list[WorkflowArtifact] = field(default_factory=list)
    failure_stage: str | None = None
    warnings: list[str] = field(default_factory=list)

    def mark_failure(self, stage: str, message: str) -> None:
        self.failure_stage = stage
        self.ok = False
        self.diagnostics["error"] = message

    def add_artifact(
        self,
        kind: str,
        path: str,
        *,
        preserved: bool = False,
        exists: bool | None = None,
    ) -> WorkflowArtifact:
        artifact = WorkflowArtifact(
            kind=kind,
            path=path,
            preserved=preserved,
            exists=exists,
        )
        self.artifacts.append(artifact)
        return artifact

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "lint_ok": self.lint_ok,
            "assemble_ok": self.assemble_ok,
            "emulator_ok": self.emulator_ok,
            "scenario_loaded": self.scenario_loaded,
            "assertions": [assertion.to_dict() for assertion in self.assertions],
            "diagnostics": dict(self.diagnostics),
            "cpu": self.cpu,
            "memory": self.memory,
            "breakpoint_hits": list(self.breakpoint_hits),
            "screenshot_path": self.screenshot_path,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "failure_stage": self.failure_stage,
            "warnings": list(self.warnings),
        }
