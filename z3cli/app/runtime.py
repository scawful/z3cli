"""Shared runtime helpers for z3cli app and serve mode."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from z3cli.core.config import ModelConfig, RouterConfig, load_project_context
from z3cli.core.router import route_message
from z3cli.core.tool_adapters import ADAPTER_REGISTRY


VALID_MODES = {"manual", "oracle", "switchhook", "broadcast"}
VALID_BACKENDS = {"studio", "llamacpp"}
DEFAULT_WORKSPACE = Path("/Users/scawful/src/hobby/oracle-of-secrets")
DEFAULT_ROM = Path("/Users/scawful/src/hobby/oracle-of-secrets/Roms/oos168.sfc")
DEFAULT_BROADCAST_MODELS = ["farore", "nayru", "veran"]
DEFAULT_LLAMACPP_MODEL = os.environ.get("LLAMACPP_MODEL", "oracle-fast")
ACTION_KEYWORDS = [
    "use", "run", "load", "breakpoint", "search", "lookup", "look up",
    "patch", "generate", "validate", "assemble", "test", "capture",
    "tool", "mcp", "mesen", "yaze", "z3ed", "write a hook", "apply",
]

# MCP server name hints — if the user mentions a server, prefer the model
# whose domain best matches it.
_SERVER_HINTS: dict[str, str] = {
    "yaze-debugger": "farore",
    "yaze-editor": "veran",
    "hyrule-historian": "hylia",
    "book-of-mudora": "nayru",
    "afs": "majora",
    "z3lsp": "majora",
    "mesen": "farore",
}


@lru_cache(maxsize=1)
def _build_tool_profile_map() -> dict[str, str]:
    """Build a mapping from adapter tool name → profile name.

    When a tool name appears in multiple profiles, the first profile
    alphabetically wins (the more specialized adapter should rename its
    tool to avoid collisions).  In practice, shared names like
    ``read_memory`` are deliberately in multiple profiles and won't
    be useful for routing — we skip names that appear in 3+ profiles.
    """
    name_to_profiles: dict[str, list[str]] = {}
    for profile, cls in ADAPTER_REGISTRY.items():
        adapter = cls.__new__(cls)
        adapter._bridge = None  # type: ignore[attr-defined]
        for tool in adapter._define_tools():
            name_to_profiles.setdefault(tool.name, []).append(profile)

    # Only keep names unique to 1-2 profiles (useful routing signal)
    result: dict[str, str] = {}
    for name, profiles in name_to_profiles.items():
        if len(profiles) <= 2:
            result[name] = profiles[0]
    return result


def _tool_hint(prompt: str, models: dict[str, ModelConfig]) -> str | None:
    """If the prompt mentions an adapter tool name or MCP server, return the profile name."""
    prompt_lower = prompt.lower()

    # Check MCP server name hints
    for server_name, profile in _SERVER_HINTS.items():
        if server_name in prompt_lower and profile in models:
            return profile

    # Check adapter tool names (underscore and hyphen forms)
    tool_map = _build_tool_profile_map()
    for tool_name, profile in tool_map.items():
        # Match both "inspect_room" and "inspect room" forms
        if tool_name in prompt_lower or tool_name.replace("_", " ") in prompt_lower:
            if profile in models:
                return profile

    return None


def merge_system_prompts(*parts: str) -> str:
    return "\n\n".join(part.strip() for part in parts if part and part.strip())


def build_harness_prompt(
    workspace: Path,
    rom_path: Path | None,
    focus_context: str = "",
) -> str:
    lines = [
        "You are operating inside z3cli, a local Zelda ROM-hacking CLI harness.",
        "Stay concrete, prefer practical hacking steps, and do not invent symbols, addresses, or tool names.",
        f"Primary workspace: {workspace}",
    ]
    if rom_path:
        lines.append(f"Primary ROM target: {rom_path}")
    lines.append("Relevant local tools may include z3ed, yaze, Mesen2, Hyrule Historian, Book of Mudora, and AFS.")
    project_ctx = load_project_context(workspace)
    if project_ctx:
        lines.append("\n--- Project Context ---\n" + project_ctx)
    if focus_context:
        lines.append("\n--- Focus Context ---\n" + focus_context)
    return "\n".join(lines)


def current_model_name(active_model: str, backend_name: str, llamacpp_model: str) -> str:
    if backend_name == "llamacpp":
        return llamacpp_model
    return active_model


def engine_key(backend_name: str, model_name: str) -> str:
    return f"{backend_name}:{model_name}"


def _oracle_route(
    prompt: str,
    models: dict[str, ModelConfig],
    routers: dict[str, RouterConfig],
) -> ModelConfig | None:
    """Resolve a model via oracle keyword routing + tool hints.

    Returns None if nothing matched (caller should use a default).
    """
    # Tool-aware hint takes priority — if the user mentions a specific
    # adapter tool or MCP server, route to the owning specialist.
    hint = _tool_hint(prompt, models)
    if hint and hint in models:
        return models[hint]

    # Fall back to keyword router
    router = routers.get("oracle")
    if router:
        model_name, _matched = route_message(prompt, router, models)
        if model_name:
            return models[model_name]
        if router.default and router.default in models:
            return models[router.default]

    return None


def resolve_targets(
    models: dict[str, ModelConfig],
    routers: dict[str, RouterConfig],
    active_model: str,
    mode: str,
    prompt: str,
    broadcast_models: list[str],
    backend_name: str,
    llamacpp_model: str,
    temperature: float,
    max_tokens: int,
) -> list[ModelConfig]:
    if backend_name == "llamacpp":
        return [
            ModelConfig(
                name=llamacpp_model,
                model_id=llamacpp_model,
                temperature=temperature,
                max_tokens=max_tokens,
                role="fast local main model",
                tools_enabled=True,
            )
        ]

    fallback = models.get(active_model, ModelConfig(name=active_model, model_id=active_model))

    if mode == "manual":
        return [fallback]

    if mode == "oracle":
        target = _oracle_route(prompt, models, routers)
        return [target] if target else [models.get("veran", fallback)]

    if mode == "switchhook":
        prompt_lower = prompt.lower()
        action_like = any(keyword in prompt_lower for keyword in ACTION_KEYWORDS)

        # Primary: use dedicated switchhook models if loaded
        preferred = "switchhook-act" if action_like else "switchhook-plan"
        if preferred in models:
            return [models[preferred]]

        # Fallback: use oracle domain routing to pick the right specialist.
        # Every specialist is now tool-capable, so we don't need to route
        # to oracle-tools specifically for action prompts.
        domain_target = _oracle_route(prompt, models, routers)
        if domain_target:
            return [domain_target]

        # Last resort
        return [models.get("farore" if action_like else "veran", fallback)]

    if mode == "broadcast":
        targets = [models[name] for name in broadcast_models if name in models]
        if targets:
            return targets
        return [fallback]

    raise RuntimeError(f"Unknown mode: {mode}")
