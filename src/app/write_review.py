"""Helpers for post-write diff review and rollback."""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


WRITE_PATTERNS = (
    "write",
    "edit",
    "patch",
    "apply_patch",
    "create",
    "update",
    "save",
    "delete",
    "remove",
    "move",
)
PATH_KEYS = ("path", "filepath", "file_path", "reference_path", "destination", "source")
PATCH_PATH_RE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", re.MULTILINE)
PATCH_MOVE_RE = re.compile(r"^\*\*\* Move to: (.+)$", re.MULTILINE)
DIFF_LINE_LIMIT = 96


@dataclass
class FileSnapshot:
    path: Path
    existed: bool
    content: bytes | None


@dataclass
class ToolWriteContext:
    tool_name: str
    call_id: str
    files: list[FileSnapshot]


@dataclass
class ChangedFile:
    path: Path
    before: bytes | None
    after: bytes | None
    status: str


@dataclass
class ReviewPreview:
    review_id: str
    summary: str
    paths: list[str]
    diff_lines: list[str]
    omitted: int


def _resolve_path(workspace: Path, raw_value: str) -> Path:
    raw_path = Path(raw_value).expanduser()
    if raw_path.is_absolute():
        return raw_path.resolve()
    return (workspace / raw_path).resolve()


def _parse_arguments(arguments_json: str) -> dict[str, Any]:
    if not arguments_json.strip():
        return {}
    try:
        value = json.loads(arguments_json)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def looks_like_write_tool(tool_name: str, arguments_json: str) -> bool:
    args = _parse_arguments(arguments_json)
    lower = tool_name.lower()
    if any(pattern in lower for pattern in WRITE_PATTERNS):
        return True
    return (
        isinstance(args.get("content"), str)
        or isinstance(args.get("patch"), str)
        or isinstance(args.get("patch_content"), str)
        or isinstance(args.get("edits"), list)
    )


def _collect_patch_paths(args: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for key in ("patch", "patch_content"):
        patch_text = args.get(key)
        if not isinstance(patch_text, str) or not patch_text.strip():
            continue
        paths.extend(match.group(1).strip() for match in PATCH_PATH_RE.finditer(patch_text))
        paths.extend(match.group(1).strip() for match in PATCH_MOVE_RE.finditer(patch_text))
    return paths


def _collect_target_paths(args: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in PATH_KEYS:
        raw = args.get(key)
        if isinstance(raw, str) and raw.strip():
            values.append(raw.strip())
    paths_value = args.get("paths")
    if isinstance(paths_value, list):
        values.extend(str(item).strip() for item in paths_value if str(item).strip())
    values.extend(_collect_patch_paths(args))
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def prepare_write_context(
    workspace: Path,
    tool_name: str,
    arguments_json: str,
    call_id: str,
) -> ToolWriteContext | None:
    if not looks_like_write_tool(tool_name, arguments_json):
        return None
    args = _parse_arguments(arguments_json)
    raw_paths = _collect_target_paths(args)
    if not raw_paths:
        return None

    files: list[FileSnapshot] = []
    seen: set[Path] = set()
    for raw_path in raw_paths:
        try:
            path = _resolve_path(workspace, raw_path)
        except OSError:
            continue
        if path in seen:
            continue
        seen.add(path)
        if path.is_file():
            files.append(FileSnapshot(path=path, existed=True, content=path.read_bytes()))
        else:
            files.append(FileSnapshot(path=path, existed=False, content=None))
    if not files:
        return None
    return ToolWriteContext(tool_name=tool_name, call_id=call_id, files=files)


def detect_changes(context: ToolWriteContext) -> list[ChangedFile]:
    changes: list[ChangedFile] = []
    for snapshot in context.files:
        path = snapshot.path
        exists_now = path.is_file()
        if snapshot.existed and not exists_now:
            changes.append(ChangedFile(path=path, before=snapshot.content, after=None, status="deleted"))
            continue
        if not snapshot.existed and exists_now:
            changes.append(ChangedFile(path=path, before=None, after=path.read_bytes(), status="added"))
            continue
        if not snapshot.existed and not exists_now:
            continue
        current = path.read_bytes()
        if snapshot.content != current:
            changes.append(ChangedFile(path=path, before=snapshot.content, after=current, status="modified"))
    return changes


def _display_path(workspace: Path, path: Path) -> str:
    try:
        return str(path.relative_to(workspace))
    except ValueError:
        return str(path)


def _decode_text(data: bytes | None) -> str | None:
    if data is None:
        return ""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def build_review_preview(workspace: Path, review_id: str, changes: list[ChangedFile]) -> ReviewPreview | None:
    if not changes:
        return None

    diff_lines: list[str] = []
    omitted = 0
    display_paths = [_display_path(workspace, change.path) for change in changes]

    for change, display_path in zip(changes, display_paths, strict=False):
        before_text = _decode_text(change.before)
        after_text = _decode_text(change.after)
        if before_text is None or after_text is None:
            lines = [
                f"--- {display_path if change.before is not None else '/dev/null'}",
                f"+++ {display_path if change.after is not None else '/dev/null'}",
                "@@ binary @@",
                f"Binary file {change.status}",
            ]
        else:
            lines = list(difflib.unified_diff(
                before_text.splitlines(),
                after_text.splitlines(),
                fromfile=display_path if change.before is not None else "/dev/null",
                tofile=display_path if change.after is not None else "/dev/null",
                lineterm="",
            ))
            if not lines:
                lines = [
                    f"--- {display_path}",
                    f"+++ {display_path}",
                    "@@ no textual diff @@",
                ]
        room = max(0, DIFF_LINE_LIMIT - len(diff_lines))
        diff_lines.extend(lines[:room])
        if len(lines) > room:
            omitted += len(lines) - room
            break
    if len(changes) > len(display_paths):
        omitted += len(changes) - len(display_paths)

    listed = ", ".join(display_paths[:3])
    if len(display_paths) > 3:
        listed += f" (+{len(display_paths) - 3} more)"
    summary = f"{len(display_paths)} file change{'s' if len(display_paths) != 1 else ''} · {listed}"
    return ReviewPreview(
        review_id=review_id,
        summary=summary,
        paths=display_paths,
        diff_lines=diff_lines,
        omitted=omitted,
    )


def restore_write_context(context: ToolWriteContext) -> None:
    for snapshot in context.files:
        path = snapshot.path
        if snapshot.existed:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(snapshot.content or b"")
            continue
        if path.exists():
            try:
                path.unlink()
            except IsADirectoryError:
                continue
