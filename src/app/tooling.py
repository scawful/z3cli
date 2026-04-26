"""Helpers for connecting z3cli tool bridges."""

from __future__ import annotations

from pathlib import Path

from collections.abc import Iterable

from core.config import load_mcp_servers
from core.deferred_tools import DeferredToolBridge
from core.rom_project import RomProject
from protocol.mcp_bridge import MCPBridge
from core.tool_bridge import CompositeBridge, ReadOnlyBridge, ToolBridge
from core.tool_adapters import get_adapter
from protocol.asm_test_bridge import AsmTestBridge
from protocol.z3asm_bridge import Z3asmBridge
from protocol.z3ed_bridge import Z3edBridge
from protocol.z3lsp_bridge import Z3LspBridge, workspace_supports_z3lsp
from protocol.workspace_context_bridge import WorkspaceContextBridge


async def connect_tool_bridge(
    workspace: Path,
    mcp_config: Path,
    *,
    rom_path: Path | None = None,
    enable_z3ed: bool = True,
) -> tuple[ToolBridge | None, list[str]]:
    """Connect all tool sources and return a unified bridge.

    The caller passes an optional ``rom_path`` (typically from AppState). A
    ``RomProject`` is discovered from workspace + rom_path and shared with
    bridges that need it (currently just ``Z3edBridge``).
    """
    bridges: list[ToolBridge] = []
    warnings: list[str] = []

    project = RomProject.discover(workspace=workspace, rom_path=rom_path)
    mcp_bridge: MCPBridge | None = None
    workspace_bridge = WorkspaceContextBridge(workspace)
    bridges.append(workspace_bridge)

    servers = load_mcp_servers(mcp_config)
    if servers:
        mcp_bridge = MCPBridge()
        warnings.extend(await mcp_bridge.connect(servers))
        if mcp_bridge.tool_count > 0:
            bridges.append(mcp_bridge)

    if workspace_supports_z3lsp(workspace):
        z3lsp_bridge = Z3LspBridge(workspace=workspace)
        warnings.extend(await z3lsp_bridge.connect())
        if z3lsp_bridge.tool_count > 0:
            bridges.append(z3lsp_bridge)

    if enable_z3ed:
        z3ed_bridge = Z3edBridge(project)
        z3ed_warnings = await z3ed_bridge.connect()
        warnings.extend(z3ed_warnings)
        if z3ed_bridge.tool_count > 0:
            bridges.append(z3ed_bridge)

    # z3asm + z3disasm — surfaced only when the corresponding binaries are
    # discovered; each missing tool is noted in warnings.
    z3asm_bridge = Z3asmBridge(project)
    z3asm_warnings = await z3asm_bridge.connect()
    warnings.extend(z3asm_warnings)
    if z3asm_bridge.tool_count > 0:
        bridges.append(z3asm_bridge)

    asm_workflow_bridge = AsmTestBridge(project, mcp_bridge=mcp_bridge)
    await asm_workflow_bridge.connect()
    if asm_workflow_bridge.tool_count > 0:
        bridges.append(asm_workflow_bridge)

    if len(bridges) == 1:
        return bridges[0], warnings
    if len(bridges) > 1:
        composite = CompositeBridge(bridges)
        for collision in composite.collisions:
            warnings.append(f"tool collision: {collision.describe()}")
        return composite, warnings
    return None, warnings


def _build_capability_bridges(bridge: ToolBridge) -> dict[str, ToolBridge]:
    """Introspect a (possibly composite) bridge into a capability-keyed dict.

    Keys:
      * ``"symbols"``  — Z3LspBridge
      * ``"rom"``      — Z3edBridge (dungeon/overworld/message/rom inspection)
      * ``"emulator"`` — Z3edBridge (mesen-* family lives here too)
      * ``"asm"``      — Z3asmBridge
      * ``"workflow"`` — AsmTestBridge (transactional patch/run/assert tools)
      * ``"workspace"``— local workspace file reads rooted at the active project
      * ``"reference"``— MCPBridge
      * ``"*"``        — the original bridge, used as a fallback

    Unknown children are ignored; the ``"*"`` fallback still works because
    the composite bridge delegates to whichever child owns a given tool.
    """
    caps: dict[str, ToolBridge] = {"*": bridge}
    children: list[ToolBridge]
    if isinstance(bridge, CompositeBridge):
        children = list(bridge.bridges)
    else:
        children = [bridge]

    symbols_bridge: ToolBridge | None = None
    asm_bridge: ToolBridge | None = None
    workflow_bridge: ToolBridge | None = None
    workspace_bridge: ToolBridge | None = None
    rom_bridge: ToolBridge | None = None
    emulator_bridge: ToolBridge | None = None
    reference_bridge: ToolBridge | None = None
    mcp_rom_fallback: ToolBridge | None = None
    mcp_emulator_fallback: ToolBridge | None = None
    mcp_reference_bridge: ToolBridge | None = None

    for child in children:
        if isinstance(child, Z3LspBridge):
            symbols_bridge = child
        elif isinstance(child, Z3edBridge):
            rom_bridge = child
            emulator_bridge = child
        elif isinstance(child, Z3asmBridge):
            asm_bridge = child
        elif isinstance(child, AsmTestBridge):
            workflow_bridge = child
        elif isinstance(child, WorkspaceContextBridge):
            workspace_bridge = child
        elif isinstance(child, MCPBridge):
            mcp_emulator_fallback = mcp_emulator_fallback or child.capability_view("emulator")
            mcp_rom_fallback = mcp_rom_fallback or child.capability_view("rom")
            mcp_reference_bridge = mcp_reference_bridge or child.capability_view("reference")

    if symbols_bridge is not None:
        caps["symbols"] = symbols_bridge
    if asm_bridge is not None:
        caps["asm"] = asm_bridge
    if workflow_bridge is not None:
        caps["workflow"] = workflow_bridge
    if workspace_bridge is not None:
        caps["workspace"] = workspace_bridge

    reference_bridge = mcp_reference_bridge
    if reference_bridge is not None:
        caps["reference"] = reference_bridge
    if rom_bridge is not None:
        caps["rom"] = rom_bridge
    elif mcp_rom_fallback is not None:
        caps["rom"] = mcp_rom_fallback
    if emulator_bridge is not None:
        caps["emulator"] = emulator_bridge
    elif mcp_emulator_fallback is not None:
        caps["emulator"] = mcp_emulator_fallback
    return caps


def build_capability_bridges(bridge: ToolBridge) -> dict[str, ToolBridge]:
    """Public wrapper for capability-keyed bridge views."""
    return _build_capability_bridges(bridge)


def wrap_bridge_for_model(
    bridge: ToolBridge | None,
    tool_profile: str,
    read_only: bool = False,
    *,
    deferred_tools: bool = False,
    core_tools: Iterable[str] = (),
) -> ToolBridge | None:
    """Wrap a bridge with model-specific adapters.

    Layering (innermost first):
    1. ``tool_profile`` — swap the bridge for a model-specific adapter
       (``din``, ``nayru``, etc.). ``"*"`` keeps the full surface.
       Adapters receive a capability-keyed bridge dict so they can route
       requests to the right sub-bridge (z3ed, z3lsp, z3asm, MCP).
    2. ``deferred_tools`` — hide tool schemas behind a ``tool_search``
       meta-tool. Always-visible tool names go in ``core_tools``.
    3. ``read_only`` — block any tool whose name looks like a write op.

    Returns None if *bridge* is None and no wrapping is requested.
    """
    if bridge is None:
        return bridge

    result: ToolBridge = bridge
    if tool_profile:
        capability_bridges = _build_capability_bridges(bridge)
        adapter = get_adapter(tool_profile, capability_bridges)
        if adapter is not None:
            result = adapter

    if deferred_tools:
        result = DeferredToolBridge(result, core=core_tools)

    if read_only:
        result = ReadOnlyBridge(result)

    return result
