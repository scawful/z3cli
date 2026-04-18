"""z3ed schema translator.

z3ed exports a JSON catalog of its commands via ``z3ed --export-schemas``.
That catalog contains usage strings (not JSON Schemas) and occasionally
malformed backslash escapes. This module turns one catalog into a list of
OpenAI-compatible tool schemas that z3cli bridges can serve directly.

Design decisions:

* Skip commands with ``available_to_agent: false``.
* Skip the yaze-gRPC-only families (``emulator-*``, ``gui-*``) because they
  do not work against a stand-alone mesen2-oos socket.
* Convert kebab-case command names to snake_case for the model-facing tool
  name; keep the original name as ``z3ed_name`` metadata for invocation.
* Parse usage strings into a flat parameter list; required flags become
  ``required`` in JSON Schema, optional flags are in ``properties`` only.
* Fold ``examples`` into the description so the model sees concrete call
  forms. Descriptions are length-capped to keep tool schemas small.
* Never raise on malformed input; return warnings the caller can surface.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


# --- JSON repair --------------------------------------------------------------

# A backslash followed by a character that is NOT a valid JSON escape
# sequence (", b, f, n, r, t, /, \, or u) is illegal in a JSON string.
# z3ed has been observed to emit ``Application\ Support`` literally —
# doubling the backslash preserves the intended text and lets json.loads
# succeed.
_BAD_ESCAPE = re.compile(r'\\(?![\"bfnrtu/\\])')


def repair_z3ed_json(raw: str) -> str:
    """Best-effort fix for known malformed backslash escapes."""
    return _BAD_ESCAPE.sub(r"\\\\", raw)


# --- Command filters ----------------------------------------------------------

# These command prefixes require yaze's internal gRPC server and are not
# relevant to a mesen2-oos-driven hacking workflow. Skip them entirely.
_SKIPPED_PREFIXES = ("emulator-", "gui-")


def _should_skip(cmd: dict[str, Any]) -> str | None:
    """Return a reason to skip the command, or None to keep it."""
    if not cmd.get("available_to_agent", True):
        return "available_to_agent=false"
    name = str(cmd.get("name", ""))
    if not name:
        return "empty name"
    for prefix in _SKIPPED_PREFIXES:
        if name.startswith(prefix):
            return f"gRPC-only family ({prefix}*)"
    if cmd.get("requires_grpc"):
        return "requires_grpc=true"
    return None


# --- Usage string parsing -----------------------------------------------------

@dataclass
class Parameter:
    name: str                           # internal flag, e.g. "room"
    flag: str                           # full CLI flag, e.g. "--room"
    required: bool
    kind: str = "string"                # string | integer | boolean | enum
    enum_values: list[str] = field(default_factory=list)
    description: str = ""

    def to_json_schema(self) -> dict[str, Any]:
        prop: dict[str, Any] = {}
        if self.kind == "boolean":
            prop["type"] = "boolean"
        elif self.kind == "integer":
            prop["type"] = "integer"
        elif self.kind == "enum":
            prop["type"] = "string"
            prop["enum"] = list(self.enum_values)
        else:
            prop["type"] = "string"
        if self.description:
            prop["description"] = self.description
        return prop


_FLAG_RE = re.compile(r"(--[a-zA-Z][a-zA-Z0-9_-]*)(?:\s+(<[^>]+>|[A-Za-z0-9,_|-]+))?")


def parse_usage(usage: str) -> list[Parameter]:
    """Extract parameters from a z3ed usage string.

    The grammar is simple in practice:
      name [--opt-flag [<value>]] --required-flag <value>
    We walk the bracket-depth stack to decide required vs optional and
    identify flags via ``--name`` tokens. Enum values (``json|text``) and
    alternatives (``<a|b|c>``) are detected for stronger schema hints.
    """
    params: list[Parameter] = []
    seen: set[str] = set()
    depth = 0
    i = 0
    # Skip the leading program name.
    first_space = usage.find(" ")
    if first_space == -1:
        return params
    segment = usage[first_space + 1 :]
    # Walk char-by-char tracking bracket depth.
    while i < len(segment):
        ch = segment[i]
        if ch == "[":
            depth += 1
            i += 1
            continue
        if ch == "]":
            depth = max(0, depth - 1)
            i += 1
            continue
        if ch != "-":
            i += 1
            continue
        m = _FLAG_RE.match(segment, i)
        if not m:
            i += 1
            continue
        flag = m.group(1)
        value_token = (m.group(2) or "").strip()
        i = m.end()
        name = flag.lstrip("-").replace("-", "_")
        if name in seen:
            continue
        seen.add(name)

        required = depth == 0
        kind = "boolean"
        enum_values: list[str] = []
        description = ""
        if value_token:
            inner = value_token
            if inner.startswith("<") and inner.endswith(">"):
                inner = inner[1:-1]
            inner = inner.strip()
            if "|" in inner:
                # enum or value alternative
                enum_values = [p.strip() for p in inner.split("|") if p.strip()]
                if enum_values:
                    kind = "enum"
                    description = f"one of: {', '.join(enum_values)}"
            else:
                lowered = inner.lower()
                if lowered in {"n", "count", "id", "room_id", "slot"}:
                    kind = "integer"
                elif lowered == "hex" or "hex" in lowered:
                    kind = "string"
                    description = "hex value (e.g., 0x7E0000)"
                elif lowered in {"path", "file"}:
                    kind = "string"
                    description = "filesystem path"
                else:
                    kind = "string"
                    description = inner
        params.append(
            Parameter(
                name=name,
                flag=flag,
                required=required,
                kind=kind,
                enum_values=enum_values,
                description=description,
            )
        )
    return params


# --- OpenAI tool schema -------------------------------------------------------

_DESCRIPTION_LIMIT = 600


def _openai_tool_name(kebab_name: str) -> str:
    """Convert kebab-case CLI name to snake_case tool name."""
    return kebab_name.replace("-", "_")


def _compose_description(cmd: dict[str, Any]) -> str:
    pieces: list[str] = []
    if cmd.get("description"):
        pieces.append(str(cmd["description"]).strip())
    examples = cmd.get("examples") or []
    if examples:
        sample = examples[0] if isinstance(examples[0], str) else ""
        if sample:
            pieces.append(f"Example: {sample}")
    pieces.append(f"z3ed command: {cmd.get('name', '')}")
    text = " | ".join(p for p in pieces if p)
    if len(text) > _DESCRIPTION_LIMIT:
        text = text[: _DESCRIPTION_LIMIT - 1] + "…"
    return text


@dataclass
class TranslatedTool:
    """One translated tool ready for inclusion in a ToolBridge."""
    tool_name: str                       # snake_case model-facing name
    z3ed_name: str                       # original kebab-case command name
    requires_rom: bool
    requires_grpc: bool
    params: list[Parameter]
    openai_schema: dict[str, Any]

    def is_write(self) -> bool:
        """True if any parameter is a --write / --dry-run flag or the name looks destructive."""
        lowered = self.z3ed_name.lower()
        # Explicit write flag → the command is dry-run by default but can mutate.
        for p in self.params:
            if p.name in {"write", "overwrite"}:
                return True
        # Always-writes commands.
        hits = ("-write", "-patch", "-import", "-hook", "rom-patch")
        return any(tok in lowered for tok in hits) or lowered.startswith("mesen-memory-write")


def build_tool(cmd: dict[str, Any]) -> TranslatedTool | None:
    """Convert one z3ed command record into a translated tool. Returns None to skip."""
    skip = _should_skip(cmd)
    if skip is not None:
        return None
    name = str(cmd.get("name", ""))
    usage = str(cmd.get("usage", ""))
    params = parse_usage(usage)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for p in params:
        properties[p.name] = p.to_json_schema()
        if p.required:
            required.append(p.name)
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        parameters_schema["required"] = required
    tool_name = _openai_tool_name(name)
    return TranslatedTool(
        tool_name=tool_name,
        z3ed_name=name,
        requires_rom=bool(cmd.get("requires_rom")),
        requires_grpc=bool(cmd.get("requires_grpc")),
        params=params,
        openai_schema={
            "type": "function",
            "function": {
                "name": tool_name,
                "description": _compose_description(cmd),
                "parameters": parameters_schema,
            },
        },
    )


def load_schemas(raw: str) -> tuple[list[TranslatedTool], list[str]]:
    """Parse a ``z3ed --export-schemas`` payload.

    Returns a list of translated tools plus a list of warnings (malformed
    commands, skipped commands, repair notifications).
    """
    warnings: list[str] = []
    repaired = repair_z3ed_json(raw)
    if repaired != raw:
        warnings.append("z3ed schema: repaired malformed JSON escape(s).")
    try:
        payload = json.loads(repaired)
    except json.JSONDecodeError as exc:
        return [], [f"z3ed schema: JSON parse failed: {exc}"]

    commands: list[dict[str, Any]]
    if isinstance(payload, dict) and isinstance(payload.get("commands"), list):
        commands = payload["commands"]
    elif isinstance(payload, list):
        commands = payload
    else:
        return [], ["z3ed schema: unexpected top-level shape"]

    tools: list[TranslatedTool] = []
    seen_tool_names: set[str] = set()
    for cmd in commands:
        if not isinstance(cmd, dict):
            warnings.append(f"z3ed schema: non-dict command entry skipped")
            continue
        try:
            tool = build_tool(cmd)
        except Exception as exc:
            warnings.append(f"z3ed schema: '{cmd.get('name', '?')}' failed: {exc}")
            continue
        if tool is None:
            continue
        if tool.tool_name in seen_tool_names:
            warnings.append(
                f"z3ed schema: duplicate translated tool name '{tool.tool_name}' skipped "
                f"(from '{tool.z3ed_name}')"
            )
            continue
        seen_tool_names.add(tool.tool_name)
        tools.append(tool)
    return tools, warnings
