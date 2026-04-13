"""Helpers for connecting z3cli tool bridges."""

from __future__ import annotations

from pathlib import Path

from z3cli.core.config import load_mcp_servers
from z3cli.protocol.mcp_bridge import MCPBridge
from z3cli.core.tool_bridge import CompositeBridge, ReadOnlyBridge, ToolBridge
from z3cli.core.tool_adapters import get_adapter
from z3cli.protocol.z3lsp_bridge import Z3LspBridge, workspace_supports_z3lsp


async def connect_tool_bridge(
    workspace: Path,
    mcp_config: Path,
) -> tuple[ToolBridge | None, list[str]]:
    """Connect all tool sources and return a unified bridge."""
    bridges: list[ToolBridge] = []
    warnings: list[str] = []

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

    if len(bridges) == 1:
        return bridges[0], warnings
    if len(bridges) > 1:
        return CompositeBridge(bridges), warnings
    return None, warnings


def wrap_bridge_for_model(
    bridge: ToolBridge | None,
    tool_profile: str,
    read_only: bool = False,
) -> ToolBridge | None:
    """Wrap a bridge with a model-specific adapter if a profile is set.

    Returns the adapter (which implements ToolBridge) if a matching
    profile exists, otherwise returns the original bridge unchanged.

    When *read_only* is True, the result is further wrapped in a
    :class:`ReadOnlyBridge` that blocks write operations.
    """
    if bridge is None or not tool_profile:
        return bridge
    adapter = get_adapter(tool_profile, bridge)
    result: ToolBridge = adapter if adapter is not None else bridge
    if read_only:
        result = ReadOnlyBridge(result)
    return result
