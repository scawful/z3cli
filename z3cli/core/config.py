"""Configuration loading for z3cli."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomllib


REGISTRY_PATH = Path.home() / "src/lab/afs-scawful/config/chat_registry.toml"
MCP_CONFIG_PATH = Path.home() / ".lmstudio/mcp.json"
API_BASE = "http://localhost:1234/v1"
SESSION_DIR = Path.home() / ".local/share/z3cli/sessions"
HISTORY_FILE = Path.home() / ".local/share/z3cli/history"

ZELDA_MCP_SERVERS = {
    "afs",
    "book-of-mudora",
    "hyrule-historian",
    "yaze-debugger",
    "yaze-editor",
}

KNOWN_ZELDA_MODEL_NAMES = {
    "din",
    "nayru",
    "farore",
    "veran",
    "majora",
    "hylia",
    "oracle-tools",
    "switchhook-plan",
    "switchhook-act",
}


@dataclass
class ModelConfig:
    name: str
    model_id: str
    provider: str = "studio"
    temperature: float = 0.3
    max_tokens: int = 2048
    system_prompt: str = ""
    role: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    thinking_tier: str = ""
    tools_enabled: bool = False
    tool_profile: str = ""  # adapter profile name (e.g. "din", "farore") or "*" for full surface


@dataclass
class RouterRule:
    keywords: list[str]
    model: str


@dataclass
class RouterConfig:
    name: str
    router_type: str
    default: str
    rules: list[RouterRule] = field(default_factory=list)


@dataclass
class MCPServerConfig:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


def _resolve_registry_relative_path(registry_path: Path, value: str) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = registry_path.parent / candidate
    return candidate.resolve()


def _load_system_prompt(model: dict[str, Any], registry_path: Path) -> str:
    parts: list[str] = []
    prompt_path_value = model.get("system_prompt_path")
    if isinstance(prompt_path_value, str) and prompt_path_value.strip():
        prompt_path = _resolve_registry_relative_path(registry_path, prompt_path_value)
        if prompt_path.exists():
            parts.append(prompt_path.read_text(encoding="utf-8"))

    inline_prompt = model.get("system_prompt")
    if isinstance(inline_prompt, str) and inline_prompt.strip():
        parts.append(inline_prompt)

    return "\n\n".join(part.strip() for part in parts if part.strip())


def _tools_enabled(name: str, role: str, tags: list[str], capabilities: list[str]) -> bool:
    lowered_name = name.lower()
    lowered_role = role.lower()
    lowered_tags = {tag.lower() for tag in tags}
    lowered_caps = {cap.lower() for cap in capabilities}
    return bool(
        {"tool_calling", "tool-calling", "tools"} & lowered_caps
        or "tools" in lowered_tags
        or "tool-calling" in lowered_role
        or lowered_name in {"oracle-tools", "switchhook-plan", "switchhook-act"}
    )


def is_zelda_model(model: ModelConfig) -> bool:
    return model.provider == "studio" and (
        model.name in KNOWN_ZELDA_MODEL_NAMES or "oracle" in {tag.lower() for tag in model.tags}
    )


def list_zelda_models(models: dict[str, ModelConfig]) -> dict[str, ModelConfig]:
    return {name: model for name, model in models.items() if is_zelda_model(model)}


def load_registry(
    path: Path | None = None,
) -> tuple[dict[str, ModelConfig], dict[str, RouterConfig]]:
    """Load models and routers from chat_registry.toml."""
    path = path or REGISTRY_PATH
    models: dict[str, ModelConfig] = {}
    routers: dict[str, RouterConfig] = {}

    if not path.exists():
        return models, routers

    with path.open("rb") as handle:
        data = tomllib.load(handle)

    raw_models = data.get("models", [])
    if isinstance(raw_models, dict):
        raw_models = [dict(value, name=name) for name, value in raw_models.items()]
    for raw_model in raw_models:
        if not isinstance(raw_model, dict):
            continue
        name = str(raw_model.get("name", "")).strip()
        model_id = str(raw_model.get("model_id", name)).strip()
        provider = str(raw_model.get("provider", "studio")).strip()
        if not name or not model_id or provider not in {"studio", "ollama"}:
            continue
        options = raw_model.get("options") or raw_model.get("parameters") or {}
        if not isinstance(options, dict):
            options = {}
        tags = [str(tag) for tag in (raw_model.get("tags") or []) if str(tag).strip()]
        capabilities = [str(cap) for cap in (raw_model.get("capabilities") or []) if str(cap).strip()]
        role = str(raw_model.get("role", "") or "")
        tool_profile = str(raw_model.get("tool_profile", "") or "")
        models[name] = ModelConfig(
            name=name,
            model_id=model_id,
            provider=provider,
            temperature=float(options.get("temperature", raw_model.get("temperature", 0.3)) or 0.3),
            max_tokens=int(options.get("max_tokens", raw_model.get("max_tokens", 2048)) or 2048),
            system_prompt=_load_system_prompt(raw_model, path),
            role=role,
            description=str(raw_model.get("description", "") or ""),
            tags=tags,
            capabilities=capabilities,
            thinking_tier=str(raw_model.get("thinking_tier", "") or ""),
            tools_enabled=_tools_enabled(name, role, tags, capabilities) or bool(tool_profile),
            tool_profile=tool_profile,
        )

    raw_routers = data.get("routers", [])
    if isinstance(raw_routers, dict):
        raw_routers = [dict(value, name=name) for name, value in raw_routers.items()]
    for raw_router in raw_routers:
        if not isinstance(raw_router, dict):
            continue
        name = str(raw_router.get("name", "")).strip()
        if not name:
            continue
        rules = []
        for rule in raw_router.get("rules", []) or []:
            if not isinstance(rule, dict):
                continue
            keywords = [str(keyword).strip() for keyword in (rule.get("keywords") or []) if str(keyword).strip()]
            model_name = str(rule.get("model", "")).strip()
            if keywords and model_name:
                rules.append(RouterRule(keywords=keywords, model=model_name))
        routers[name] = RouterConfig(
            name=name,
            router_type=str(raw_router.get("strategy", raw_router.get("type", "keyword")) or "keyword"),
            default=str(raw_router.get("default_model", raw_router.get("default", "")) or ""),
            rules=rules,
        )

    return models, routers


def load_mcp_servers(
    path: Path | None = None,
    filter_names: set[str] | None = None,
) -> dict[str, MCPServerConfig]:
    """Load MCP server configs from mcp.json."""
    path = path or MCP_CONFIG_PATH
    filter_names = filter_names if filter_names is not None else ZELDA_MCP_SERVERS
    servers: dict[str, MCPServerConfig] = {}

    if not path.exists():
        return servers

    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)

    for name, cfg in (data.get("mcpServers") or {}).items():
        if filter_names and name not in filter_names:
            continue
        if not isinstance(cfg, dict):
            continue
        servers[name] = MCPServerConfig(
            name=name,
            command=str(cfg.get("command", "")),
            args=[str(arg) for arg in (cfg.get("args") or [])],
            env={str(key): str(value) for key, value in (cfg.get("env") or {}).items()},
        )

    return servers


def load_project_context(workspace: Path) -> str:
    """Load Z3CLI.md from workspace directory if it exists."""
    for name in ("Z3CLI.md", "z3cli.md", ".z3cli.md"):
        path = workspace / name
        if path.is_file():
            return path.read_text(encoding="utf-8")
    return ""
