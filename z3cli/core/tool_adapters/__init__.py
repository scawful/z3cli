"""Model-specific tool adapters for z3cli.

Each adapter exposes a compact, purpose-built tool interface for a
specific Oracle model. The full MCP tool surface (136+ tools) exists
for SOTA cloud models; local 8B/14B models get small focused interfaces
they can master.
"""

from __future__ import annotations

from z3cli.core.tool_bridge import ToolBridge

from z3cli.core.tool_adapters.base import ToolAdapter
from z3cli.core.tool_adapters.din import DinAdapter
from z3cli.core.tool_adapters.nayru import NayruAdapter
from z3cli.core.tool_adapters.farore import FaroreAdapter
from z3cli.core.tool_adapters.veran import VeranAdapter
from z3cli.core.tool_adapters.majora import MajoraAdapter
from z3cli.core.tool_adapters.hylia import HyliaAdapter


ADAPTER_REGISTRY: dict[str, type[ToolAdapter]] = {
    "din": DinAdapter,
    "nayru": NayruAdapter,
    "farore": FaroreAdapter,
    "veran": VeranAdapter,
    "majora": MajoraAdapter,
    "hylia": HyliaAdapter,
}


def get_adapter(profile: str, bridge: ToolBridge) -> ToolAdapter | None:
    """Look up and instantiate an adapter by profile name.

    Returns None if the profile is not recognized or is '*' (full surface).
    """
    if not profile or profile == "*":
        return None
    adapter_cls = ADAPTER_REGISTRY.get(profile)
    if adapter_cls is None:
        return None
    return adapter_cls(bridge)
