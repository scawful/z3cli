"""Model-specific tool adapters for z3cli.

Each adapter exposes a compact, purpose-built tool interface for a
specific Oracle model. The full tool surface (z3ed + z3lsp + z3asm + MCP)
exists for SOTA cloud models; local 8B/14B models get small focused
interfaces they can master.

Adapters take a capability-keyed bridge dict: ``{"rom": ..., "emulator": ...,
"symbols": ..., "asm": ..., "workflow": ..., "workspace": ..., "reference": ...}`` plus a
``"*"`` catch-all.
The catch-all is used as a fallback when a specific capability isn't wired
(e.g. no MCP server running).
"""

from __future__ import annotations

from typing import Mapping

from core.tool_bridge import ToolBridge

from core.tool_adapters.base import ToolAdapter
from core.tool_adapters.din import DinAdapter
from core.tool_adapters.nayru import NayruAdapter
from core.tool_adapters.farore import FaroreAdapter
from core.tool_adapters.oracle import OracleAdapter


# Veran/Majora/Hylia adapter files remain in-tree as historical reference code,
# but the runtime registry exposes only the consolidated specialist family.
ADAPTER_REGISTRY: dict[str, type[ToolAdapter]] = {
    "din": DinAdapter,
    "nayru": NayruAdapter,
    "farore": FaroreAdapter,
    "oracle": OracleAdapter,
    "oracle-fast": OracleAdapter,
    "oracle-pro": OracleAdapter,
}


def get_adapter(
    profile: str,
    bridges: ToolBridge | Mapping[str, ToolBridge],
) -> ToolAdapter | None:
    """Look up and instantiate an adapter by profile name.

    ``bridges`` may be a single :class:`ToolBridge` (legacy: stored under
    the ``"*"`` key) or a capability-keyed mapping. Returns None if the
    profile is not recognized or is ``"*"`` (full surface requested).
    """
    if not profile or profile == "*":
        return None
    adapter_cls = ADAPTER_REGISTRY.get(profile)
    if adapter_cls is None:
        return None
    return adapter_cls(bridges)
