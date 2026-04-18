"""Configuration loading for z3cli."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import os

import tomllib

from z3cli.core.provider import VALID_PROVIDERS


def _default_registry_path() -> Path:
    override = os.environ.get("Z3CLI_REGISTRY", "").strip()
    if override:
        return Path(override)
    # Check project config first, then legacy path
    project = Path(__file__).resolve().parents[2] / "config" / "chat_registry.toml"
    if project.exists():
        return project
    return Path.home() / "src/lab/afs-scawful/config/chat_registry.toml"


REGISTRY_PATH = _default_registry_path()
MCP_CONFIG_PATH = Path(os.environ.get("Z3CLI_MCP_CONFIG", str(Path.home() / ".lmstudio/mcp.json")))
API_BASE = os.environ.get("Z3CLI_API_BASE", "http://localhost:1234/v1")
SESSION_DIR = Path(os.environ.get("Z3CLI_SESSION_DIR", str(Path.home() / ".local/share/z3cli/sessions")))
HISTORY_FILE = Path(os.environ.get("Z3CLI_HISTORY_FILE", str(Path.home() / ".local/share/z3cli/history")))


def _normalize_domain_mode_name(value: str) -> str:
    return str(value or "").strip().lower()


@dataclass
class ProfileConfig:
    name: str
    keywords: list[str] = field(default_factory=list)
    system_prompt: str = ""


_DOMAIN_PROFILES: dict[str, ProfileConfig] = {}
_MODE_PROFILES: dict[str, ProfileConfig] = {}
_MODEL_ALIAS_MAP: dict[str, str] = {}
_PROFILE_DEFAULTS = {
    "domain": "adaptive",
    "mode": "adaptive",
}
def _default_rollout_gates_path() -> Path:
    override = os.environ.get("Z3CLI_ROLLOUT_GATES", "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "config" / "model_rollouts.toml"


ROLLOUT_GATES_PATH = _default_rollout_gates_path()

ZELDA_MCP_SERVERS = {
    "afs",
    "book-of-mudora",
    "hyrule-historian",
    "yaze-debugger",
    "yaze-editor",
}

SPECIALIST_MODEL_NAMES = {
    "din",
    "nayru",
    "farore",
    "veran",
    "majora",
    "hylia",
}

LEGACY_ZELDA_MODEL_NAMES = {
    "oracle-tools",
    "oracle-main",
    "oracle-main-plan",
    "oracle-main-act",
    "switchhook",
    "switchhook-plan",
    "switchhook-act",
}
_CANONICAL_ORACLE_MODELS = {"oracle", "oracle-fast", "oracle-pro"}
UI_HIDDEN_ZELDA_MODEL_TAGS = {
    "avatar",
    "persona",
}
Z3UI_MODEL_TAGS = {
    "z3ui",
}
Z3UI_MODEL_ORDER = (
    "oracle",
    "oracle-fast",
    "oracle-pro",
    "qwen3-oracle-8b",
    "din",
    "farore",
    "farore-q4km",
    "nayru",
    "majora",
    "veran",
    "hylia",
    "hylia-q4km",
)
_Z3UI_MODEL_ORDER_INDEX = {
    name: index for index, name in enumerate(Z3UI_MODEL_ORDER)
}

ZELDA_TAG_HINTS = {
    "oracle",
    "zelda",
    "rom",
    "rom-hack",
    "rom-hacking",
    "rom_hacking",
}

ZELDA_TEXT_HINTS = (
    "oracle",
    "zelda",
    "rom hack",
    "rom-hacking",
    "rom hacking",
    "65816",
    "asm",
    "hook",
)


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
    domain: str = ""
    mode: str = ""
    effort: str = ""
    tools_enabled: bool = False
    tool_profile: str = ""  # adapter profile name (e.g. "din", "farore") or "*" for full surface
    # Cloud provider fields
    api_base: str = ""      # override endpoint (e.g. custom Anthropic proxy)
    api_key_env: str = ""   # env var name for API key (e.g. "ANTHROPIC_API_KEY")
    # Prompt caching: cache system prompt + tool list on Anthropic. No-op for local models.
    prompt_cache: bool = True
    # Context compaction: target context window in tokens. 0 disables auto-compaction.
    context_budget: int = 0
    # Deferred tool schema loading: hide the tool surface behind tool_search.
    # Useful when a model uses tool_profile = "*" (full MCP surface).
    deferred_tools: bool = False
    # Some local models behave poorly when LM Studio receives native OpenAI
    # tool schemas. Those models can still use the engine's XML/manual tool loop
    # by setting native_tools = False while keeping tools_enabled = True.
    native_tools: bool = True
    # When deferred_tools is True, these tool names stay always-visible
    # without needing tool_search (e.g. high-frequency helpers).
    core_tools: list[str] = field(default_factory=list)
    # LM Studio load hints for large local models. Zero / empty means "use LM Studio defaults".
    lmstudio_context_length: int = 0
    lmstudio_parallel: int = 0
    lmstudio_gpu: str = ""
    lmstudio_ttl: int = 0
    allow_auto_load: bool = True
    rollout_block_reason: str = ""
    visibility: str = ""
    spawn_only: bool = False
    spawnable_by: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)

    @property
    def is_cloud(self) -> bool:
        return self.provider in ("anthropic", "openai")

    @property
    def is_local(self) -> bool:
        return self.provider in ("studio", "ollama", "llamacpp")

    def resolve_api_key(self) -> str:
        """Resolve the API key from environment variable."""
        if self.api_key_env:
            return os.environ.get(self.api_key_env, "")
        # Default env var names per provider
        if self.provider == "anthropic":
            return os.environ.get("ANTHROPIC_API_KEY", "")
        if self.provider == "openai":
            return os.environ.get("OPENAI_API_KEY", "")
        return ""


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


@dataclass
class RolloutGate:
    alias: str
    allowed_model_ids: list[str] = field(default_factory=list)
    required_checks: list[str] = field(default_factory=list)
    note: str = ""
    enforce: bool = True


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
        or lowered_name in _CANONICAL_ORACLE_MODELS
        or is_legacy_zelda_model(name)
    )


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def is_legacy_zelda_model(name: str) -> bool:
    """Return True for names that should be treated as legacy Zelda aliases."""
    normalized = _normalize_domain_mode_name(name)
    if not normalized:
        return False
    if normalized in LEGACY_ZELDA_MODEL_NAMES:
        return True
    canonical = _MODEL_ALIAS_MAP.get(normalized, "")
    return canonical in _CANONICAL_ORACLE_MODELS


def _normalize_profile_name(value: str) -> str:
    return _normalize_domain_mode_name(value)


def get_domain_profiles() -> dict[str, ProfileConfig]:
    return dict(_DOMAIN_PROFILES)


def get_mode_profiles() -> dict[str, ProfileConfig]:
    return dict(_MODE_PROFILES)


def get_profile_defaults() -> tuple[str, str]:
    return _PROFILE_DEFAULTS["domain"], _PROFILE_DEFAULTS["mode"]


def get_registry_aliases() -> dict[str, str]:
    """Return alias -> canonical model name mapping from the loaded registry."""
    return dict(_MODEL_ALIAS_MAP)


def model_visibility(model: ModelConfig | None) -> str:
    if model is None:
        return "public"
    visibility = _normalize_domain_mode_name(getattr(model, "visibility", ""))
    return visibility or "public"


def is_hidden_model(model: ModelConfig | None) -> bool:
    return model_visibility(model) in {"hidden", "internal"}


def is_spawn_only_model(model: ModelConfig | None) -> bool:
    if model is None:
        return False
    if bool(getattr(model, "spawn_only", False)):
        return True
    return model_visibility(model) == "spawn-only"


def direct_model_selection_error(model: ModelConfig | None) -> str | None:
    if model is None:
        return None
    if is_spawn_only_model(model):
        return f"Model '{model.name}' is internal-only and can only be invoked via delegation."
    return None


def can_spawn_model(parent_model: str, model: ModelConfig | None) -> bool:
    if model is None:
        return False
    normalized_parent = _normalize_domain_mode_name(parent_model)
    if is_spawn_only_model(model) and not normalized_parent:
        return False
    allowed_parents = {
        _normalize_domain_mode_name(name)
        for name in getattr(model, "spawnable_by", [])
        if _normalize_domain_mode_name(name)
    }
    if allowed_parents and normalized_parent not in allowed_parents:
        return False
    return True


def load_rollout_gates(path: Path | None = None) -> dict[str, RolloutGate]:
    path = path or _default_rollout_gates_path()
    if not path.exists():
        return {}

    with path.open("rb") as handle:
        loaded = tomllib.load(handle)
    data: dict[str, Any] = loaded if isinstance(loaded, dict) else {}

    settings_obj = data.get("settings")
    settings: dict[str, Any] = settings_obj if isinstance(settings_obj, dict) else {}
    default_enforce = bool(settings.get("enforce", True))
    aliases_obj = data.get("aliases")
    raw_aliases: dict[str, Any] = aliases_obj if isinstance(aliases_obj, dict) else {}

    gates: dict[str, RolloutGate] = {}
    for alias, raw_gate in raw_aliases.items():
        if not isinstance(raw_gate, dict):
            continue
        alias_name = str(alias).strip()
        if not alias_name:
            continue
        gates[alias_name] = RolloutGate(
            alias=alias_name,
            allowed_model_ids=_normalize_string_list(raw_gate.get("allowed_model_ids")),
            required_checks=_normalize_string_list(raw_gate.get("required_checks")),
            note=str(raw_gate.get("note", "") or "").strip(),
            enforce=bool(raw_gate.get("enforce", default_enforce)),
        )
    return gates


def _load_profile_sections(
    data: dict[str, Any],
    *,
    section_name: str,
) -> dict[str, ProfileConfig]:
    profiles: dict[str, ProfileConfig] = {}
    for raw_profile in data.get(section_name, []) or []:
        if not isinstance(raw_profile, dict):
            continue
        name = _normalize_profile_name(str(raw_profile.get("name", "")))
        if not name:
            continue
        profiles[name] = ProfileConfig(
            name=name,
            keywords=_normalize_string_list(raw_profile.get("keywords", [])),
            system_prompt=str(raw_profile.get("system_prompt", "") or "").strip(),
        )
    return profiles


def _load_profile_defaults(data: dict[str, Any]) -> None:
    global _PROFILE_DEFAULTS
    defaults_obj = data.get("profile_defaults")
    defaults: dict[str, Any] = defaults_obj if isinstance(defaults_obj, dict) else {}
    domain_default = defaults["domain"] if "domain" in defaults else "adaptive"
    mode_default = defaults["mode"] if "mode" in defaults else "adaptive"
    _PROFILE_DEFAULTS = {
        "domain": _normalize_profile_name(domain_default) or "adaptive",
        "mode": _normalize_profile_name(mode_default) or "adaptive",
    }


def apply_rollout_gates(models: dict[str, ModelConfig], gates: dict[str, RolloutGate]) -> None:
    for alias, gate in gates.items():
        canonical = alias
        if canonical not in models:
            canonical = _MODEL_ALIAS_MAP.get(alias, "")
        if not canonical:
            continue
        model = models.get(canonical)
        if model is None:
            continue
        if model.rollout_block_reason:
            continue
        if not gate.enforce:
            continue
        approved_ids = set(gate.allowed_model_ids)
        if model.model_id in approved_ids:
            continue
        checks = ", ".join(gate.required_checks) if gate.required_checks else "the rollout gate"
        approved_text = ", ".join(gate.allowed_model_ids) if gate.allowed_model_ids else "(none)"
        note = f" {gate.note}" if gate.note else ""
        model.rollout_block_reason = (
            f"Production alias '{alias}' is rollout-gated. "
            f"Registry points to '{model.model_id}', but approved model_ids are: {approved_text}. "
            f"Only update the approval manifest after {checks} pass.{note}"
        )


def rollout_warnings(models: dict[str, ModelConfig]) -> list[str]:
    warnings = {
        model.rollout_block_reason.strip()
        for model in models.values()
        if model.rollout_block_reason.strip()
    }
    return sorted(warnings)


def is_zelda_model(model: ModelConfig) -> bool:
    if not model.is_local:
        return False

    if model.name in SPECIALIST_MODEL_NAMES:
        return True

    if model.tool_profile:
        return True

    tags_lower = {tag.lower() for tag in model.tags}
    capabilities_lower = {cap.lower() for cap in model.capabilities}
    if tags_lower & ZELDA_TAG_HINTS or capabilities_lower & ZELDA_TAG_HINTS:
        return True

    searchable = " ".join(
        part.strip().lower()
        for part in (
            model.name,
            model.role,
            model.description,
            model.system_prompt,
        )
        if part and part.strip()
    )
    return any(hint in searchable for hint in ZELDA_TEXT_HINTS)


def list_zelda_models(models: dict[str, ModelConfig], *, include_legacy: bool = False) -> dict[str, ModelConfig]:
    return {
        name: model
        for name, model in models.items()
        if (
            is_zelda_model(model)
            and not is_hidden_model(model)
            and not is_spawn_only_model(model)
            and (include_legacy or not is_legacy_zelda_model(name))
        )
    }


def list_visible_zelda_models(
    models: dict[str, ModelConfig],
    *,
    include_legacy: bool = False,
) -> dict[str, ModelConfig]:
    visible: dict[str, ModelConfig] = {}
    for name, model in list_zelda_models(models, include_legacy=include_legacy).items():
        tags_lower = {tag.lower() for tag in model.tags}
        if UI_HIDDEN_ZELDA_MODEL_TAGS & tags_lower:
            continue
        visible[name] = model
    return visible


def z3ui_model_sort_key(name: str) -> tuple[int, str]:
    lowered = _normalize_domain_mode_name(name)
    return (_Z3UI_MODEL_ORDER_INDEX.get(lowered, len(_Z3UI_MODEL_ORDER_INDEX)), lowered)


def is_z3ui_model(name: str) -> bool:
    return _normalize_domain_mode_name(name) in _Z3UI_MODEL_ORDER_INDEX


def is_z3ui_model_entry(model: ModelConfig | None) -> bool:
    if model is None or not model.is_local:
        return False
    if is_hidden_model(model) or is_spawn_only_model(model):
        return False
    if is_z3ui_model(model.name):
        return True
    tags_lower = {tag.lower() for tag in model.tags}
    return bool(Z3UI_MODEL_TAGS & tags_lower)


def load_registry(
    path: Path | None = None,
    *,
    rollout_path: Path | None = None,
) -> tuple[dict[str, ModelConfig], dict[str, RouterConfig]]:
    """Load models and routers from chat_registry.toml."""
    path = path or REGISTRY_PATH
    models: dict[str, ModelConfig] = {}
    routers: dict[str, RouterConfig] = {}

    if not path.exists():
        return models, routers

    with path.open("rb") as handle:
        loaded = tomllib.load(handle)
    data: dict[str, Any] = loaded if isinstance(loaded, dict) else {}

    _load_profile_defaults(data)

    global _DOMAIN_PROFILES, _MODE_PROFILES, _MODEL_ALIAS_MAP
    _DOMAIN_PROFILES = _load_profile_sections(data, section_name="domain_profiles")
    _MODE_PROFILES = _load_profile_sections(data, section_name="mode_profiles")
    _MODEL_ALIAS_MAP = {}

    raw_models = data.get("models", [])
    if isinstance(raw_models, dict):
        raw_models = [dict(value, name=name) for name, value in raw_models.items()]
    for raw_model in raw_models:
        if not isinstance(raw_model, dict):
            continue
        name = str(raw_model.get("name", "")).strip()
        model_id = str(raw_model.get("model_id", name)).strip()
        provider = str(raw_model.get("provider", "studio")).strip()
        if not name or not model_id or provider not in VALID_PROVIDERS:
            continue
        options = raw_model.get("options") or raw_model.get("parameters") or {}
        if not isinstance(options, dict):
            options = {}
        lmstudio_load = raw_model.get("lmstudio_load") or {}
        if not isinstance(lmstudio_load, dict):
            lmstudio_load = {}
        tags = [str(tag) for tag in (raw_model.get("tags") or []) if str(tag).strip()]
        capabilities = [str(cap) for cap in (raw_model.get("capabilities") or []) if str(cap).strip()]
        role = str(raw_model.get("role", "") or "")
        tool_profile = str(raw_model.get("tool_profile", "") or "")
        domain = _normalize_profile_name(raw_model.get("domain", _PROFILE_DEFAULTS["domain"]))
        mode = _normalize_profile_name(raw_model.get("mode", _PROFILE_DEFAULTS["mode"]))
        effort = _normalize_profile_name(raw_model.get("effort", raw_model.get("thinking_tier", "")))
        if not domain:
            domain = _PROFILE_DEFAULTS["domain"]
        if not mode:
            mode = _PROFILE_DEFAULTS["mode"]
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
            domain=domain,
            mode=mode,
            effort=effort,
            tools_enabled=_tools_enabled(name, role, tags, capabilities) or bool(tool_profile),
            tool_profile=tool_profile,
            api_base=str(raw_model.get("api_base", "") or ""),
            api_key_env=str(raw_model.get("api_key_env", "") or ""),
            prompt_cache=bool(raw_model.get("prompt_cache", True)),
            context_budget=int(raw_model.get("context_budget", 0) or 0),
            deferred_tools=bool(raw_model.get("deferred_tools", False)),
            native_tools=bool(raw_model.get("native_tools", True)),
            core_tools=[
                str(name).strip()
                for name in (raw_model.get("core_tools") or [])
                if str(name).strip()
            ],
            lmstudio_context_length=int(lmstudio_load.get("context_length", 0) or 0),
            lmstudio_parallel=int(lmstudio_load.get("parallel", 0) or 0),
            lmstudio_gpu=str(lmstudio_load.get("gpu", "") or "").strip(),
            lmstudio_ttl=int(lmstudio_load.get("ttl", 0) or 0),
            allow_auto_load=bool(raw_model.get("allow_auto_load", raw_model.get("lmstudio_auto_load", True))),
            rollout_block_reason=str(raw_model.get("rollout_block_reason", "") or "").strip(),
            visibility=_normalize_domain_mode_name(raw_model.get("visibility", "")),
            spawn_only=bool(raw_model.get("spawn_only", False)),
            spawnable_by=[
                _normalize_profile_name(str(parent))
                for parent in (raw_model.get("spawnable_by") or [])
                if _normalize_profile_name(str(parent))
            ],
            aliases=[
                str(alias).strip().lower()
                for alias in (raw_model.get("aliases") or [])
                if isinstance(alias, str) and str(alias).strip()
            ],
        )
        for alias in models[name].aliases:
            alias_name = _normalize_profile_name(alias)
            if alias_name and alias_name != name and alias_name not in _MODEL_ALIAS_MAP:
                _MODEL_ALIAS_MAP[alias_name] = name

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

    apply_rollout_gates(models, load_rollout_gates(rollout_path))

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
        loaded = json.load(handle)
    data: dict[str, Any] = loaded if isinstance(loaded, dict) else {}

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
