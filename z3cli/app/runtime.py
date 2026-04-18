"""Shared runtime helpers for z3cli app and serve mode."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from z3cli.core.config import (
    ModelConfig,
    RouterConfig,
    get_registry_aliases,
    LEGACY_ZELDA_MODEL_NAMES,
    list_zelda_models,
    get_domain_profiles,
    get_mode_profiles,
    get_profile_defaults,
    load_project_context,
)
from z3cli.core.router import route_message
from z3cli.core.tool_bridge import CompositeBridge, ToolBridge
from z3cli.core.tool_adapters import ADAPTER_REGISTRY
from z3cli.app.tooling import build_capability_bridges
from z3cli.protocol.z3lsp_bridge import Z3LspBridge


DEFAULT_ACTIVE_MODEL = "oracle"
DEFAULT_ORACLE_MAIN_MODEL = "oracle"
ORACLE_MAIN_MODE = "oracle"
ORCHESTRATOR_MODE = "orchestrator"
LEGACY_MODE_ALIASES = {"switchhook": ORACLE_MAIN_MODE, "oracle-main": ORACLE_MAIN_MODE}
VISIBLE_MODES = ("manual", ORACLE_MAIN_MODE, ORCHESTRATOR_MODE, "broadcast")
VALID_MODES = set(VISIBLE_MODES) | set(LEGACY_MODE_ALIASES)
# Preferred orchestrator models in priority order — first one available wins
DEFAULT_ORCHESTRATOR_CANDIDATES = ("claude-sonnet", "claude-opus", "gpt-4o", "orchestrator")
VALID_BACKENDS = {"studio", "llamacpp"}
DEFAULT_WORKSPACE = Path("/Users/scawful/src/hobby/oracle-of-secrets")
DEFAULT_ROM = Path("/Users/scawful/src/hobby/oracle-of-secrets/Roms/oos168.sfc")
DEFAULT_BROADCAST_MODELS = ["farore", "majora", "nayru"]
DEFAULT_LLAMACPP_MODEL = os.environ.get("LLAMACPP_MODEL", "oracle-fast")
DEFAULT_SAFE_STARTUP_MODELS = ("oracle-fast", "nayru", "majora", "din", "farore", "hylia", "veran")
DEFAULT_SAFE_ORACLE_MODELS = ("oracle", "oracle-fast", "nayru", "majora", "din", "farore", "hylia", "veran")
EFFORT_RANK = {
    "high": 0,
    "medium": 1,
    "low": 2,
}
LOW_EFFORT_KEYWORDS = (
    "quick",
    "faster",
    "speed",
    "quickly",
    "fast",
)
TOOL_FIRST_KEYWORDS = (
    "check",
    "debug",
    "definition",
    "demonstrate",
    "diagnose",
    "disasm",
    "inspect",
    "list",
    "look at",
    "memory",
    "open",
    "profile",
    "read",
    "review",
    "room",
    "show",
    "sprite",
    "state",
    "trace",
    "transcript",
    "tool",
    "verify",
    ".asm",
    "@",
)
HIGH_EFFORT_KEYWORDS = (
    "deep",
    "thorough",
    "investigate",
    "analyze",
    "analysis",
    "cause",
    "why",
)
_ORACLE_FAST_LEGACY_ALIASES = {
    "oracle-main-fast": "oracle-fast",
    "oracle-fast": "oracle-fast",
}
SPECIALIST_NAMES = tuple(sorted(ADAPTER_REGISTRY))
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


@dataclass(frozen=True)
class RoutingDecision:
    target: str
    reason: str
    requested_mode: str
    normalized_mode: str
    legacy_mode_alias: str | None
    profile_domain: str
    profile_mode: str
    profile_effort: str
    tool_hint: str | None = None
    router_keyword: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "target": self.target,
            "reason": self.reason,
            "requested_mode": self.requested_mode,
            "normalized_mode": self.normalized_mode,
            "legacy_mode_alias": self.legacy_mode_alias,
            "profile_domain": self.profile_domain,
            "profile_mode": self.profile_mode,
            "profile_effort": self.profile_effort,
            "tool_hint": self.tool_hint,
            "router_keyword": self.router_keyword,
        }

_ATTACHMENT_RE = re.compile(r"(?<!\S)@([^\s@]+)")
_CONSTRUCT_REF_RE = re.compile(r"(?<!\S)#([A-Za-z][A-Za-z0-9_-]*):([^\s#]+)")
_SYMBOL_QUERY_RE = re.compile(r"(?<![@/\\\\$])!?[A-Za-z_][A-Za-z0-9_]{2,}")
LSP_CONTEXT_MODES = ("auto", "off", "minimal", "balanced", "rich")
_RESOURCE_LABEL_FILES = (
    Path("Docs/Dev/Planning/oracle_resource_labels.json"),
    Path("Docs/Planning/oracle_resource_labels.json"),
)
_SPRITE_CATALOG_FILES = (
    Path("Docs/Technical/sprite_catalog.md"),
)
_OBJECT_METADATA_FILES = {
    "handler": Path("Dungeons/Objects/object_handler.asm"),
    "tracks": Path("Docs/World/Dungeons/GoronMines_Tracks.md"),
    "yaze": Path("Docs/Debugging/yaze_safe_edit_workflow.md"),
    "water": Path("Docs/Debugging/Issues/WaterCollision_Handoff.md"),
    "water_script": Path("scripts/Generate/generate_water_gate_runtime_tables.py"),
}
_SPRITE_CATALOG_SECTION_KINDS = {
    "Bosses": "sprite",
    "Enemies": "sprite",
    "NPCs": "sprite",
    "Objects": "object",
}
_CONSTRUCT_KIND_ALIASES = {
    "door": "entrance",
    "dungeon-room": "room",
    "ent": "entrance",
    "entity": "sprite",
    "entrance": "entrance",
    "item": "item",
    "map": "overworld",
    "message": "message",
    "msg": "message",
    "music": "music",
    "npc": "sprite",
    "obj": "object",
    "object": "object",
    "overworld": "overworld",
    "overworld_map": "overworld",
    "ow": "overworld",
    "room": "room",
    "song": "music",
    "sprite": "sprite",
    "track": "music",
}
_RESOURCE_LABEL_SECTION_KIND_MAP = {
    "entrance": "entrance",
    "item": "item",
    "music": "music",
    "overworld_map": "overworld",
    "room": "room",
    "sprite": "sprite",
}
_LSP_SYMBOL_STOPWORDS = {
    "about",
    "attached",
    "build",
    "check",
    "debug",
    "define",
    "definition",
    "file",
    "files",
    "focus",
    "inspect",
    "look",
    "please",
    "prompt",
    "review",
    "show",
    "symbol",
    "symbols",
    "this",
    "those",
    "trace",
    "use",
    "using",
    "with",
}


@dataclass(frozen=True)
class LspContextSettings:
    requested_mode: str
    resolved_mode: str
    max_chars: int
    diagnostic_limit: int
    symbol_limit: int
    symbol_query_limit: int
    symbol_detail_limit: int
    symbol_reference_limit: int
    include_clean_diagnostics: bool
    include_diagnostic_snippets: bool
    include_symbol_hover: bool

    @property
    def enabled(self) -> bool:
        return self.resolved_mode != "off"


def mode_usage_text() -> str:
    return "<manual|oracle|orchestrator|broadcast>"


def normalize_lsp_context_mode(mode: str) -> str:
    normalized = str(mode or "").strip().lower()
    return normalized if normalized in LSP_CONTEXT_MODES else "auto"


def normalize_mode(mode: str) -> tuple[str, str | None]:
    lowered = str(mode).strip().lower()
    canonical = LEGACY_MODE_ALIASES.get(lowered, lowered)
    alias = lowered if lowered != canonical else None
    return canonical, alias


def _looks_like_lsp_symbol_query(token: str) -> bool:
    if not token or len(token) < 3:
        return False
    if token.lower() in _LSP_SYMBOL_STOPWORDS:
        return False
    if token.lower().endswith((".asm", ".json", ".toml", ".py", ".md", ".txt")):
        return False
    if token.islower() and "_" not in token and not any(ch.isdigit() for ch in token):
        return False
    if token[0].isupper() and token[1:].islower():
        return False
    return (
        "_" in token
        or any(ch.isupper() for ch in token[1:])
        or any(ch.isdigit() for ch in token)
        or token.isupper()
    )


def extract_lsp_symbol_queries(prompt: str, *, limit: int = 0) -> list[str]:
    if limit <= 0:
        return []
    results: list[str] = []
    seen: set[str] = set()
    for match in _SYMBOL_QUERY_RE.finditer(str(prompt or "")):
        token = str(match.group(0) or "").lstrip("!").strip()
        if not _looks_like_lsp_symbol_query(token):
            continue
        lowered = token.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        results.append(token)
        if len(results) >= limit:
            break
    return results


def _normalize_profile_name(value: str) -> str:
    return str(value or "").strip().lower()


def _infer_prompt_profiles(prompt: str) -> tuple[str, str, str]:
    domain_profiles = get_domain_profiles()
    mode_profiles = get_mode_profiles()
    default_domain, default_mode = get_profile_defaults()

    normalized_prompt = prompt.lower()

    profile_domain = _profile_name_from_keywords(normalized_prompt, domain_profiles)
    if not profile_domain:
        profile_domain = default_domain
    if not profile_domain:
        profile_domain = "adaptive"

    profile_mode = _profile_name_from_keywords(normalized_prompt, mode_profiles)
    if not profile_mode:
        profile_mode = default_mode
    if not profile_mode:
        profile_mode = "adaptive"

    effort = "medium"
    if any(keyword in normalized_prompt for keyword in HIGH_EFFORT_KEYWORDS):
        effort = "high"
    elif any(keyword in normalized_prompt for keyword in LOW_EFFORT_KEYWORDS):
        effort = "low"

    return profile_domain, profile_mode, effort


def infer_prompt_profiles(prompt: str) -> tuple[str, str, str]:
    return _infer_prompt_profiles(prompt)


def _profile_name_from_keywords(prompt: str, profiles: dict[str, Any]) -> str:
    if not profiles:
        return ""
    for profile_name in profiles:
        profile = profiles[profile_name]
        for keyword in profile.keywords:
            if keyword and keyword.lower() in prompt:
                return profile_name
    return ""


def _resolve_effort(model: ModelConfig) -> str:
    effort = _normalize_profile_name(model.effort)
    if effort in EFFORT_RANK:
        return effort
    effort = _normalize_profile_name(model.thinking_tier)
    if effort in EFFORT_RANK:
        return effort
    return "medium"


def _profile_rank(value: str, requested: str) -> int:
    value = _normalize_profile_name(value)
    requested = _normalize_profile_name(requested)
    if not requested or requested == "adaptive":
        return 0 if value == "adaptive" else 1
    if value == requested:
        return 0
    if value == "adaptive" or not value:
        return 1
    return 2


def _is_canonical_oracle(name: str) -> int:
    return 0 if str(name).strip().lower() == DEFAULT_ORACLE_MAIN_MODEL else 1


def _legacy_oracle_alias_target(lowered_name: str) -> str:
    lowered = _normalize_profile_name(lowered_name)
    if lowered in _ORACLE_FAST_LEGACY_ALIASES:
        return _ORACLE_FAST_LEGACY_ALIASES[lowered]
    if lowered in LEGACY_ZELDA_MODEL_NAMES:
        return DEFAULT_ORACLE_MAIN_MODEL
    if lowered.startswith("oracle-main-"):
        return DEFAULT_ORACLE_MAIN_MODEL
    return lowered


def _oracle_candidate_names(models: dict[str, ModelConfig]) -> tuple[str, ...]:
    candidates = tuple(sorted(list_zelda_models(models).keys()))
    if candidates:
        return candidates
    return DEFAULT_SAFE_ORACLE_MODELS


def resolve_oracle_profile_context(prompt: str) -> tuple[str, str, str]:
    return _infer_prompt_profiles(prompt)


def resolve_oracle_profile_system_prompts(prompt: str) -> list[str]:
    domain_name, mode_name, _ = _infer_prompt_profiles(prompt)
    parts: list[str] = []

    domain_prompt = get_domain_profiles().get(domain_name)
    if domain_prompt is not None and domain_prompt.system_prompt.strip():
        parts.append(domain_prompt.system_prompt)

    mode_prompt = get_mode_profiles().get(mode_name)
    if mode_prompt is not None and mode_prompt.system_prompt.strip():
        parts.append(mode_prompt.system_prompt)

    return parts


def _pick_profiled_candidate(
    models: dict[str, ModelConfig],
    target_domain: str,
    target_mode: str,
    target_effort: str,
    *,
    candidate_names: tuple[str, ...] | None = None,
) -> ModelConfig | None:
    names = candidate_names if candidate_names is not None else tuple(sorted(models.keys()))
    options: list[tuple[tuple[int, int, int, int, str], str, ModelConfig]] = []

    for name in names:
        model = models.get(name)
        if model is None:
            continue
        reason = blocked_model_reason(model)
        if reason:
            continue

        domain = _normalize_profile_name(model.domain)
        mode = _normalize_profile_name(model.mode)
        effort = _resolve_effort(model)

        options.append((
            (
                _profile_rank(domain, target_domain),
                _profile_rank(mode, target_mode),
                _effort_rank(effort, target_effort),
                _is_canonical_oracle(name),
                name,
            ),
            name,
            model,
        ))

    if not options:
        return None
    return sorted(options, key=lambda item: item[0])[0][2]


def _pick_profiled_candidate_with_reason(
    models: dict[str, ModelConfig],
    target_domain: str,
    target_mode: str,
    target_effort: str,
    *,
    candidate_names: tuple[str, ...] | None = None,
) -> tuple[ModelConfig | None, str]:
    options: list[tuple[tuple[int, int, int, int, str], str, str, str, ModelConfig]] = []

    names = candidate_names if candidate_names is not None else tuple(sorted(models.keys()))
    for name in names:
        model = models.get(name)
        if model is None:
            continue
        reason = blocked_model_reason(model)
        if reason:
            continue

        domain = _normalize_profile_name(model.domain)
        mode = _normalize_profile_name(model.mode)
        effort = _resolve_effort(model)

        score = (
            _profile_rank(domain, target_domain),
            _profile_rank(mode, target_mode),
            _effort_rank(effort, target_effort),
            _is_canonical_oracle(name),
            name,
        )
        options.append((score, domain, mode, effort, model))

    if not options:
        return None, "profile-fallback: no candidates"

    score, domain, mode, effort, model = sorted(options, key=lambda item: item[0])[0]
    reason = (
        f"profile-match: requested domain={target_domain}, mode={target_mode}, effort={target_effort}; "
        f"selected={model.name} (model_domain={domain}, model_mode={mode}, model_effort={effort}, "
        f"ranks={score})"
    )
    return model, reason


def _effort_rank(effort: str, requested: str) -> int:
    requested = _normalize_profile_name(requested)
    effort = _normalize_profile_name(effort)
    if effort == requested:
        return 0
    if effort == "adaptive" or not effort:
        return 1
    if requested == "low" and effort == "medium":
        return 1
    if requested == "high" and effort == "medium":
        return 1
    return 2


def resolve_model_name(name: str, models: dict[str, ModelConfig]) -> tuple[str, str | None]:
    lowered = str(name).strip().lower()
    if lowered in models:
        return lowered, None
    alias_model = get_registry_aliases().get(lowered)
    if alias_model and alias_model in models:
        alias = lowered if lowered != alias_model else None
        return alias_model, alias
    canonical = _legacy_oracle_alias_target(lowered)
    alias = lowered if lowered != canonical else None
    if canonical in models:
        return canonical, alias
    return canonical, alias


def resolve_existing_model_name(name: str, models: dict[str, ModelConfig]) -> tuple[str, str | None]:
    """Resolve a requested model to an existing registry entry.

    The public registry supports legacy aliases and dynamic alias maps, but
    callers that require a concrete model must use this helper so unknown
    names fail fast instead of creating synthetic entries.
    """
    resolved_name, alias = resolve_model_name(name, models)
    if resolved_name in models:
        return resolved_name, alias
    raise RuntimeError(f"Unknown model: {name}")


def _model_role_bucket(name: str, model: ModelConfig | None) -> str:
    searchable = " ".join(
        part.strip().lower()
        for part in (
            name,
            model.role if model is not None else "",
        )
        if part and part.strip()
    )
    if re.search(r"(^|[-_ ])(plan|planner)([-_ ]|$)", searchable):
        return "plan"
    if re.search(r"(^|[-_ ])(act|action|executor)([-_ ]|$)", searchable):
        return "act"
    return "other"


def choose_startup_model(
    requested_name: str,
    models: dict[str, ModelConfig],
    *,
    explicit: bool,
    auto_load: bool = True,
) -> tuple[str, str | None]:
    resolved_name, _alias = resolve_model_name(requested_name, models)
    resolved_model = models.get(resolved_name)
    manual_only_reason = auto_load_blocked_reason(resolved_model, auto_load=auto_load)
    if not explicit and requested_name == DEFAULT_ACTIVE_MODEL and (
        resolved_model is None or blocked_model_reason(resolved_model) or manual_only_reason
    ):
        fallback = _preferred_startup_model(models, disallowed={resolved_name})
        if fallback is not None and fallback.name != resolved_name:
            if manual_only_reason:
                return (
                    fallback.name,
                    f"Default model '{resolved_name}' is configured for manual loads only; using '{fallback.name}' instead.",
                )
            return (
                fallback.name,
                f"Default model '{resolved_name}' is unavailable; using '{fallback.name}' instead.",
            )
    if manual_only_reason and not explicit:
        return resolved_name, manual_only_reason
    if explicit or not blocked_model_reason(resolved_model):
        return resolved_name, None
    if resolved_model is None:
        return resolved_name, None

    requested_bucket = _model_role_bucket(resolved_name, resolved_model)
    candidates = sorted(
        (
            candidate_name,
            candidate_model,
        )
        for candidate_name, candidate_model in models.items()
        if (
            candidate_name != resolved_name
            and candidate_model.model_id == resolved_model.model_id
            and not blocked_model_reason(candidate_model)
        )
    )
    candidates.sort(
        key=lambda item: (
            _model_role_bucket(item[0], item[1]) != requested_bucket,
            item[0],
        ),
    )
    if not candidates:
        return resolved_name, None

    fallback_name = candidates[0][0]
    return (
        fallback_name,
        f"Default model '{resolved_name}' is rollout-gated; using '{fallback_name}' instead.",
    )


def blocked_model_reason(model: ModelConfig | None) -> str | None:
    if model is None:
        return None
    reason = str(model.rollout_block_reason or "").strip()
    return reason or None


def auto_load_blocked_reason(model: ModelConfig | None, *, auto_load: bool) -> str | None:
    if model is None or not auto_load:
        return None
    if model.allow_auto_load:
        return None
    return f"Model '{model.name}' is configured for manual LM Studio loads only."


def _preferred_safe_model(
    models: dict[str, ModelConfig],
    *,
    candidates: tuple[str, ...],
    disallowed: set[str] | None = None,
) -> ModelConfig | None:
    blocked_names = disallowed or set()
    for name in candidates:
        if name in blocked_names:
            continue
        model = models.get(name)
        if model is not None and not blocked_model_reason(model):
            return model
    return None


def _preferred_startup_model(
    models: dict[str, ModelConfig],
    *,
    disallowed: set[str] | None = None,
) -> ModelConfig | None:
    blocked_names = disallowed or set()
    safe = _preferred_safe_model(models, candidates=DEFAULT_SAFE_ORACLE_MODELS, disallowed=blocked_names)
    if safe is not None:
        return safe
    for name in sorted(list_zelda_models(models)):
        if name in blocked_names:
            continue
        model = models.get(name)
        if model is not None and not blocked_model_reason(model):
            return model
    for name in sorted(models):
        if name in blocked_names:
            continue
        model = models.get(name)
        if model is not None and not blocked_model_reason(model):
            return model
    return None


def ensure_model_available(model: ModelConfig | None) -> None:
    if model is None:
        raise RuntimeError("Unknown model configuration")
    reason = blocked_model_reason(model)
    if reason:
        raise RuntimeError(reason)


def ensure_targets_available(targets: list[ModelConfig]) -> None:
    blocked = [reason for target in targets if (reason := blocked_model_reason(target))]
    if blocked:
        raise RuntimeError(blocked[0])


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


def build_tool_use_prompt(
    use_tools: bool,
    tool_profile: str = "",
    *,
    deferred_tools: bool = False,
    native_tools: bool = True,
) -> str:
    if not use_tools:
        return ""

    lines = [
        "When current files, symbols, addresses, ROM contents, or emulator state matter, use tools before answering.",
        "If a relevant tool can answer the request, make the tool call before explanatory prose.",
        "Keep any pre-tool preamble to at most one short sentence.",
        "Do not invent file contents, routine bodies, addresses, or tool output.",
        "Do not print JSON or pseudo-commands for the user to run when you can call the tool yourself.",
        "If the user is reporting a harness or tool bug, focus on reproducing the behavior and describing evidence instead of debating the premise.",
    ]

    if not native_tools:
        lines.extend([
            "This model uses manual XML tool calls instead of native API tool schemas.",
            "When you need a tool, emit exactly one XML block with no markdown fences: <tool_call>{\"name\":\"tool_name\",\"arguments\":{...}}</tool_call>",
            "Do not invent tool names. If you do not already know the exact tool name, start with `tool_search`.",
            "After a tool result returns, answer from that evidence or emit the next XML tool call.",
            "If a tool errors or `tool_search` returns no matches, do not answer from memory. Refine the query or say that the evidence could not be retrieved.",
        ])

    if deferred_tools:
        lines.append("If the needed tool is not visible yet, call `tool_search` first to reveal it.")

    if tool_profile == "din":
        lines.extend([
            "When the user asks you to inspect files or find an optimization yourself, start with `check_diagnostics`, `lookup_symbol`, or `profile_routine` instead of giving generic advice.",
            "Use `read_context` only when you already have a valid workspace-relative path that the harness can read.",
            "Only ask the user for an address after you have exhausted the file and symbol context you can gather yourself.",
        ])
    elif tool_profile == "farore":
        lines.extend([
            "For demonstrations and quick triage, prefer `inspect_room`, `list_sprites`, `check_diagnostics`, or `scenario_run` before raw live-emulator state calls.",
            "If a live emulator socket is unavailable, say that briefly and pivot to a ROM or workflow tool instead of repeatedly calling `read_state`.",
        ])

    return "\n".join(lines)


def build_tool_bias_prompt(
    prompt: str,
    use_tools: bool,
    tool_profile: str = "",
    *,
    deferred_tools: bool = False,
    native_tools: bool = True,
) -> str:
    """Return a per-request tool-first bias when the prompt strongly implies tools."""
    if not use_tools:
        return ""

    prompt_lower = prompt.lower()
    if not any(keyword in prompt_lower for keyword in TOOL_FIRST_KEYWORDS):
        return ""

    lines = [
        "This request likely requires tools.",
        "Lead with the tool call instead of a long explanation when a relevant tool exists.",
        "Do not narrate what you are about to inspect; inspect it first, then summarize the result.",
    ]

    if not native_tools:
        lines.append("Emit the tool call as a single <tool_call>{...}</tool_call> block instead of prose.")
        lines.append("If the exact tool name is not already known, start with `tool_search` rather than inventing one.")

    if deferred_tools:
        lines.append("If the relevant tool is hidden, call `tool_search` before any longer response.")

    if tool_profile == "din":
        lines.append("For optimization or review work, prefer diagnostics, symbol, or routine inspection first; use file reads only when the path is known to be valid.")
    elif tool_profile == "farore":
        lines.append("For demos, prefer one successful room, ROM, or workflow tool call over a speculative live-emulator call.")

    return "\n".join(lines)


def build_local_identity_prompt(model: ModelConfig) -> str:
    """Return an identity guardrail for locally hosted models."""
    if not model.is_local:
        return ""

    persona = model.name or model.model_id or "local model"
    return "\n".join([
        f"You are the locally hosted '{persona}' model inside z3cli.",
        "Do not claim to be Claude, Anthropic, OpenAI, or ChatGPT.",
        "If the user asks who you are, answer with this local model or persona name and the fact that you are running locally in z3cli.",
    ])


def load_focus_file(
    workspace: Path,
    raw_path: str,
    max_chars: int = 32_000,
) -> tuple[Path, str]:
    """Resolve and load a focus file relative to the workspace."""
    focus_path = workspace / raw_path
    if not focus_path.is_file():
        focus_path = Path(raw_path).expanduser().resolve()
    if not focus_path.is_file():
        raise FileNotFoundError(raw_path)
    content = focus_path.read_text(encoding="utf-8")
    if len(content) > max_chars:
        content = content[:max_chars] + f"\n\n... (truncated at {max_chars} chars)"
    return focus_path, content


def _attachment_label(workspace: Path, path: Path) -> str:
    try:
        return str(path.relative_to(workspace))
    except ValueError:
        return str(path)


def _extract_model_size_billions(model: ModelConfig | None) -> float:
    if model is None:
        return 0.0
    search_text = " ".join(
        value
        for value in (
            model.name,
            model.model_id,
            model.description,
            model.role,
        )
        if value
    )
    matches = re.findall(r"(?<!\d)(\d+(?:\.\d+)?)\s*[bB](?![a-zA-Z])", search_text)
    if not matches:
        return 0.0
    try:
        return max(float(match) for match in matches)
    except ValueError:
        return 0.0


def resolve_lsp_context_settings(
    mode: str,
    model: ModelConfig | None = None,
) -> LspContextSettings:
    requested = normalize_lsp_context_mode(mode)
    resolved = requested
    if resolved == "auto":
        size_b = _extract_model_size_billions(model)
        budget = int(getattr(model, "context_budget", 0) or 0) if model is not None else 0
        if model is not None and model.is_cloud:
            resolved = "rich"
        elif size_b >= 20.0 or budget >= 96_000:
            resolved = "rich"
        elif size_b >= 14.0 or budget >= 32_000:
            resolved = "balanced"
        elif size_b >= 8.0 or model is not None:
            resolved = "minimal"
        else:
            resolved = "balanced"

    profiles: dict[str, tuple[int, int, int, int, int, int, bool, bool, bool]] = {
        "off": (0, 0, 0, 0, 0, 0, False, False, False),
        "minimal": (420, 1, 4, 1, 0, 0, False, False, False),
        "balanced": (960, 2, 8, 1, 1, 2, True, False, False),
        "rich": (2200, 4, 14, 2, 2, 4, True, True, True),
    }
    (
        max_chars,
        diagnostic_limit,
        symbol_limit,
        symbol_query_limit,
        symbol_detail_limit,
        symbol_reference_limit,
        include_clean,
        include_snippets,
        include_symbol_hover,
    ) = profiles[resolved]
    return LspContextSettings(
        requested_mode=requested,
        resolved_mode=resolved,
        max_chars=max_chars,
        diagnostic_limit=diagnostic_limit,
        symbol_limit=symbol_limit,
        symbol_query_limit=symbol_query_limit,
        symbol_detail_limit=symbol_detail_limit,
        symbol_reference_limit=symbol_reference_limit,
        include_clean_diagnostics=include_clean,
        include_diagnostic_snippets=include_snippets,
        include_symbol_hover=include_symbol_hover,
    )


def lsp_context_status_label(mode: str, model: ModelConfig | None = None) -> str:
    settings = resolve_lsp_context_settings(mode, model)
    if settings.requested_mode == "auto":
        return f"auto -> {settings.resolved_mode}"
    return settings.resolved_mode


def find_z3lsp_bridge(bridge: ToolBridge | None) -> Z3LspBridge | None:
    """Find the underlying Z3LspBridge inside a possibly wrapped tool surface."""
    if bridge is None:
        return None
    if isinstance(bridge, Z3LspBridge):
        return bridge
    if isinstance(bridge, CompositeBridge):
        for child in bridge.bridges:
            resolved = find_z3lsp_bridge(child)
            if resolved is not None:
                return resolved
        return None

    inner = getattr(bridge, "_bridge", None)
    if inner is not None and inner is not bridge:
        return find_z3lsp_bridge(inner)
    return None


async def build_z3lsp_context_pack(
    bridge: ToolBridge | None,
    file_path: str | Path,
    *,
    model: ModelConfig | None = None,
    lsp_context_mode: str = "auto",
    query: str = "",
) -> str:
    """Build a compact z3lsp-derived context pack for one file path."""
    symbols_bridge = find_z3lsp_bridge(bridge)
    if symbols_bridge is None:
        return ""
    settings = resolve_lsp_context_settings(lsp_context_mode, model)
    if not settings.enabled:
        return ""
    symbol_queries = extract_lsp_symbol_queries(query, limit=settings.symbol_query_limit)
    outline_query = symbol_queries[0] if len(symbol_queries) == 1 else ""
    try:
        return await symbols_bridge.build_context_pack(
            str(file_path),
            query=outline_query,
            symbol_queries=symbol_queries,
            max_chars=settings.max_chars,
            diagnostic_limit=settings.diagnostic_limit,
            symbol_limit=settings.symbol_limit,
            symbol_detail_limit=settings.symbol_detail_limit,
            reference_limit=settings.symbol_reference_limit,
            include_clean_diagnostics=settings.include_clean_diagnostics,
            include_diagnostic_snippets=settings.include_diagnostic_snippets,
            include_symbol_hover=settings.include_symbol_hover,
        )
    except Exception:
        return ""


def normalize_construct_kind(kind: str) -> str:
    return _CONSTRUCT_KIND_ALIASES.get(str(kind or "").strip().lower(), "")


def _normalize_construct_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _parse_construct_int(value: str) -> int | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.lower().startswith("0x"):
        raw = raw[2:]
    elif raw.startswith("$"):
        raw = raw[1:]
    if not raw or not re.fullmatch(r"[0-9A-Fa-f]+", raw):
        return None
    try:
        return int(raw, 16)
    except ValueError:
        return None


def _format_construct_id(value: int) -> str:
    width = max(2, len(f"{value:X}"))
    return f"0x{value:0{width}X}"


def _construct_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return slug or _normalize_construct_key(value)


def _clean_markdown_cell(value: str) -> str:
    cleaned = str(value or "").strip()
    cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", cleaned)
    cleaned = cleaned.replace("`", "")
    cleaned = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", cleaned)
    return " ".join(cleaned.split())


def _parse_markdown_table_row(line: str) -> list[str]:
    stripped = str(line or "").strip()
    if not stripped.startswith("|") or stripped.count("|") < 2:
        return []
    return [_clean_markdown_cell(cell) for cell in stripped.strip("|").split("|")]


def _normalize_table_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _catalog_match_keys(entry: dict[str, str]) -> set[str]:
    keys = {
        _normalize_construct_key(entry.get("catalog_id", "")),
        _normalize_construct_key(entry.get("label", "")),
        _normalize_construct_key(entry.get("section", "")),
        _normalize_construct_key(f"{entry.get('section', '')}:{entry.get('label', '')}"),
    }
    if entry.get("id"):
        keys.add(_normalize_construct_key(entry["id"]))
        keys.add(_normalize_construct_key(f"{entry.get('section', '')}:{entry['id']}"))
    return {key for key in keys if key}


@lru_cache(maxsize=16)
def _load_workspace_sprite_catalog(workspace: str) -> dict[str, list[dict[str, str]]]:
    root = Path(workspace).expanduser().resolve()
    catalog_path: Path | None = None
    for rel_path in _SPRITE_CATALOG_FILES:
        candidate = root / rel_path
        if candidate.is_file():
            catalog_path = candidate
            break
    if catalog_path is None:
        return {}

    try:
        lines = catalog_path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return {}

    entries: dict[str, list[dict[str, str]]] = {"sprite": [], "object": []}
    current_section = ""
    current_kind = ""
    headers: list[str] | None = None
    sprite_labels = _load_workspace_resource_labels(str(root)).get("sprite", {})

    for line in lines:
        heading = re.match(r"^##\s+(.+?)(?:\s+\(|$)", line.strip())
        if heading:
            current_section = str(heading.group(1) or "").strip()
            current_kind = _SPRITE_CATALOG_SECTION_KINDS.get(current_section, "")
            headers = None
            continue
        if not current_kind:
            continue
        if not line.strip().startswith("|"):
            if headers is not None and line.strip():
                headers = None
            continue
        cells = _parse_markdown_table_row(line)
        if not cells:
            continue
        if all(not cell or set(cell) <= {"-", ":"} for cell in cells):
            continue
        if headers is None:
            headers = [_normalize_table_header(cell) for cell in cells]
            continue
        row = {
            headers[index]: cells[index]
            for index in range(min(len(headers), len(cells)))
            if headers[index]
        }
        label = row.get("sprite", "") or row.get("file", "")
        label = _clean_markdown_cell(label)
        if not label:
            continue
        entry: dict[str, str] = {
            "catalog_id": _construct_slug(label),
            "kind": current_kind,
            "label": label,
            "section": current_section,
            "status": row.get("status", ""),
            "location": row.get("location", ""),
            "notes": row.get("notes", ""),
        }
        for field_name in ("vanilla_base", "role", "service", "purpose"):
            value = row.get(field_name, "")
            if value:
                entry[field_name] = value
        if current_kind == "sprite":
            label_key = _normalize_construct_key(label)
            matches = [
                (entry_id, entry_label)
                for entry_id, entry_label in sprite_labels.items()
                if _normalize_construct_key(entry_label) == label_key
            ]
            if len(matches) == 1:
                entry["id"] = matches[0][0]
                entry["label"] = matches[0][1]
        entries[current_kind].append(entry)

    return {
        kind: values
        for kind, values in entries.items()
        if values
    }


def _match_construct_catalog_entry(
    workspace: Path,
    kind: str,
    query: str,
) -> dict[str, str] | None:
    entries = _load_workspace_sprite_catalog(str(workspace)).get(kind, [])
    normalized_query = _normalize_construct_key(query)
    if not normalized_query:
        return None

    exact: list[dict[str, str]] = []
    prefix: list[dict[str, str]] = []
    contains: list[dict[str, str]] = []
    for entry in entries:
        keys = _catalog_match_keys(entry)
        if normalized_query in keys:
            exact.append(entry)
            continue
        if any(key.startswith(normalized_query) for key in keys):
            prefix.append(entry)
            continue
        if any(normalized_query in key for key in keys):
            contains.append(entry)
    if len(exact) == 1:
        return exact[0]
    if len(prefix) == 1:
        return prefix[0]
    if len(contains) == 1:
        return contains[0]
    return None


def _humanize_construct_label(value: str) -> str:
    spaced = str(value or "").replace("_", " ")
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", spaced)
    return " ".join(spaced.split())


def _parse_object_handler_subtypes(text: str, handler_label: str) -> list[str]:
    match = re.search(rf"{handler_label}:\s*\{{(?P<body>.*?)^\}}", text, re.MULTILINE | re.DOTALL)
    if match is None:
        return []
    body = str(match.group("body") or "")
    collecting = False
    subtypes: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped == ".ObjOffset":
            collecting = True
            continue
        if stripped == ".ObjData":
            break
        if not collecting:
            continue
        entry_match = re.search(r"dw\s+\.([A-Za-z0-9_]+)-\.ObjData\s*;\s*(\d+)", stripped)
        if entry_match is None:
            continue
        name = _humanize_construct_label(str(entry_match.group(1) or ""))
        index = int(str(entry_match.group(2) or "0"), 10)
        subtypes.append(f"{index}: {name}")
    return subtypes


@lru_cache(maxsize=16)
def _load_workspace_object_id_metadata(workspace: str) -> dict[str, dict[str, Any]]:
    root = Path(workspace).expanduser().resolve()
    metadata: dict[str, dict[str, Any]] = {}

    def upsert(
        object_id: int,
        label: str,
        *,
        aliases: tuple[str, ...] = (),
        notes: tuple[str, ...] = (),
        subtypes: tuple[str, ...] = (),
        source: str = "",
    ) -> None:
        key = _format_construct_id(object_id)
        entry = metadata.setdefault(key, {
            "id": key,
            "label": label,
            "aliases": [],
            "notes": [],
            "subtypes": [],
            "sources": [],
        })
        if label and not entry.get("label"):
            entry["label"] = label
        for alias in aliases:
            alias_text = str(alias or "").strip()
            if alias_text and alias_text not in entry["aliases"]:
                entry["aliases"].append(alias_text)
        for note in notes:
            note_text = str(note or "").strip()
            if note_text and note_text not in entry["notes"]:
                entry["notes"].append(note_text)
        for subtype in subtypes:
            subtype_text = str(subtype or "").strip()
            if subtype_text and subtype_text not in entry["subtypes"]:
                entry["subtypes"].append(subtype_text)
        if source and source not in entry["sources"]:
            entry["sources"].append(source)

    handler_path = root / _OBJECT_METADATA_FILES["handler"]
    if handler_path.is_file():
        try:
            handler_text = handler_path.read_text(encoding="utf-8")
        except Exception:
            handler_text = ""
        if handler_text:
            source = str(handler_path.relative_to(root))
            upsert(
                0x31,
                "Custom track object",
                aliases=("track object", "custom object", "rail object"),
                notes=("Rendered at runtime by CustomObjectHandler.",),
                subtypes=tuple(_parse_object_handler_subtypes(handler_text, "CustomObjectHandler")),
                source=source,
            )
            upsert(
                0x32,
                "Custom decor object",
                aliases=("custom object 2", "decor object"),
                notes=("Rendered at runtime by CustomObjectHandler2.",),
                subtypes=tuple(_parse_object_handler_subtypes(handler_text, "CustomObjectHandler2")),
                source=source,
            )
            upsert(
                0x54,
                "Sprite body object",
                aliases=("boss body object",),
                notes=("Draws multi-tile sprite-body room objects.",),
                subtypes=tuple(_parse_object_handler_subtypes(handler_text, "SpriteObjectsDraw")),
                source=source,
            )
            upsert(
                0xE6,
                "Heavy pot object",
                aliases=("heavy pot",),
                notes=("Initializes the heavy gray pot draw routine.",),
                source=source,
            )

    tracks_path = root / _OBJECT_METADATA_FILES["tracks"]
    if tracks_path.is_file():
        upsert(
            0x31,
            "Custom track object",
            notes=("Subtype is encoded in the dungeon object size field for Goron Mines track authoring.",),
            source=str(tracks_path.relative_to(root)),
        )

    yaze_path = root / _OBJECT_METADATA_FILES["yaze"]
    if yaze_path.is_file():
        note = "Custom objects 0x31/0x32 do not render in Yaze and are drawn by runtime handlers instead."
        source = str(yaze_path.relative_to(root))
        upsert(0x31, "Custom track object", notes=(note,), source=source)
        upsert(0x32, "Custom decor object", notes=(note,), source=source)

    water_path = root / _OBJECT_METADATA_FILES["water"]
    water_source = str(water_path.relative_to(root)) if water_path.is_file() else ""
    water_script_path = root / _OBJECT_METADATA_FILES["water_script"]
    water_script_source = str(water_script_path.relative_to(root)) if water_script_path.is_file() else ""
    common_sources = tuple(source for source in (water_source, water_script_source) if source)
    if common_sources:
        upsert(
            0xC9,
            "Flood overlay object",
            aliases=("water overlay", "flood overlay"),
            notes=("Authoring object for generated water-gate flood overlay segments.",),
            source=common_sources[0],
        )
        for extra_source in common_sources[1:]:
            upsert(0xC9, "Flood overlay object", source=extra_source)
        upsert(
            0xD9,
            "Swim-mask overlay object",
            aliases=("swim mask object", "water overlay"),
            notes=("Authoring object for generated swim-mask overlay segments.",),
            source=common_sources[0],
        )
        for extra_source in common_sources[1:]:
            upsert(0xD9, "Swim-mask overlay object", source=extra_source)
        upsert(
            0x124,
            "Zora Baby target marker",
            aliases=("zora baby marker", "switch target marker"),
            notes=("Preferred room marker for post-switch Zora Baby walk targets.",),
            source=common_sources[0],
        )
        for extra_source in common_sources[1:]:
            upsert(0x124, "Zora Baby target marker", source=extra_source)
        upsert(
            0x137,
            "Zora Baby target marker fallback",
            aliases=("zora baby marker", "switch target marker"),
            notes=("Fallback room marker for post-switch Zora Baby walk targets.",),
            source=common_sources[0],
        )
        for extra_source in common_sources[1:]:
            upsert(0x137, "Zora Baby target marker fallback", source=extra_source)
        upsert(
            0x135,
            "Zora Baby target marker fallback",
            aliases=("zora baby marker", "switch target marker"),
            notes=("Fallback room marker for post-switch Zora Baby walk targets.",),
            source=common_sources[0],
        )
        for extra_source in common_sources[1:]:
            upsert(0x135, "Zora Baby target marker fallback", source=extra_source)

    for source, line in _iter_documented_object_lines(root):
        for match in re.finditer(r"(?P<label>[A-Za-z][A-Za-z0-9 /_\-]{1,80})\s*\((?P<content>[^)]*0x[0-9A-Fa-f][^)]*)\)", line):
            label = _humanize_construct_label(str(match.group("label") or ""))
            content = str(match.group("content") or "")
            ids = [int(raw_id, 16) for raw_id in re.findall(r"0x([0-9A-Fa-f]{1,4})", content)]
            if not label or not ids:
                continue
            note = line if len(line) <= 180 else line[:177].rstrip() + "..."
            for object_id in ids:
                upsert(
                    object_id,
                    label,
                    aliases=(label,),
                    notes=(note,),
                    source=source,
                )

    return metadata


def _match_object_id_metadata(workspace: Path, query: str) -> dict[str, Any] | None:
    metadata = _load_workspace_object_id_metadata(str(workspace))
    numeric_query = _parse_construct_int(query)
    if numeric_query is not None:
        return metadata.get(_format_construct_id(numeric_query))

    normalized_query = _normalize_construct_key(query)
    if not normalized_query:
        return None

    exact: list[dict[str, Any]] = []
    prefix: list[dict[str, Any]] = []
    contains: list[dict[str, Any]] = []
    for entry in metadata.values():
        keys = {
            _normalize_construct_key(str(entry.get("id", "") or "")),
            _normalize_construct_key(str(entry.get("label", "") or "")),
            *{
                _normalize_construct_key(str(alias or ""))
                for alias in entry.get("aliases", [])
                if str(alias or "").strip()
            },
        }
        keys = {key for key in keys if key}
        if normalized_query in keys:
            exact.append(entry)
            continue
        if any(key.startswith(normalized_query) for key in keys):
            prefix.append(entry)
            continue
        if any(normalized_query in key for key in keys):
            contains.append(entry)
    if len(exact) == 1:
        return exact[0]
    if len(prefix) == 1:
        return prefix[0]
    if len(contains) == 1:
        return contains[0]
    return None


def _iter_documented_object_lines(root: Path) -> list[tuple[str, str]]:
    docs_root = root / "Docs"
    if not docs_root.is_dir():
        return []
    lines: list[tuple[str, str]] = []
    for path in docs_root.rglob("*.md"):
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        rel_path = str(path.relative_to(root))
        for raw_line in text.splitlines():
            if "0x" not in raw_line.lower():
                continue
            normalized = _clean_markdown_cell(raw_line)
            if not normalized:
                continue
            table_cells = _parse_markdown_table_row(raw_line)
            key_objects_row = False
            if table_cells:
                first_cell = table_cells[0].strip().lower()
                if first_cell == "key objects" and len(table_cells) > 1:
                    key_objects_row = True
                    normalized = table_cells[1]
                elif any("object" in cell.lower() for cell in table_cells):
                    normalized = " ".join(cell for cell in table_cells if cell.strip())
                else:
                    continue
            lower = normalized.lower()
            if not key_objects_row and "object" not in lower and "objects" not in lower:
                continue
            lines.append((rel_path, normalized))
    return lines


@lru_cache(maxsize=16)
def _load_workspace_resource_labels(workspace: str) -> dict[str, dict[str, str]]:
    root = Path(workspace).expanduser().resolve()
    label_path: Path | None = None
    for rel_path in _RESOURCE_LABEL_FILES:
        candidate = root / rel_path
        if candidate.is_file():
            label_path = candidate
            break
    if label_path is None:
        for candidate in root.rglob("*resource_labels.json"):
            if candidate.is_file():
                label_path = candidate
                break
    if label_path is None:
        return {}
    try:
        payload = json.loads(label_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    labels: dict[str, dict[str, str]] = {}
    if not isinstance(payload, dict):
        return labels
    for section_name, section_data in payload.items():
        kind = _RESOURCE_LABEL_SECTION_KIND_MAP.get(str(section_name))
        if not kind or not isinstance(section_data, dict):
            continue
        entries: dict[str, str] = {}
        for raw_id, raw_label in section_data.items():
            if not isinstance(raw_id, str):
                continue
            label = str(raw_label or "").strip()
            entries[str(raw_id).strip()] = label
        if entries:
            labels[kind] = entries
    return labels


def _resolve_construct_entry(
    workspace: Path,
    kind: str,
    query: str,
) -> tuple[str | None, str | None]:
    labels = _load_workspace_resource_labels(str(workspace)).get(kind, {})
    numeric_query = _parse_construct_int(query)
    if numeric_query is not None:
        for entry_id, label in labels.items():
            if _parse_construct_int(entry_id) == numeric_query:
                return entry_id, label
        if kind == "object":
            object_meta = _match_object_id_metadata(workspace, query)
            if object_meta is not None:
                return str(object_meta.get("id") or ""), str(object_meta.get("label") or "") or None
        return _format_construct_id(numeric_query), None

    normalized_query = _normalize_construct_key(query)
    if not normalized_query:
        return None, None

    exact: list[tuple[str, str]] = []
    prefix: list[tuple[str, str]] = []
    contains: list[tuple[str, str]] = []
    for entry_id, label in labels.items():
        keys = {
            _normalize_construct_key(entry_id),
            _normalize_construct_key(label),
            _normalize_construct_key(f"{kind}:{entry_id}"),
            _normalize_construct_key(f"{kind}:{label}"),
        }
        if normalized_query in keys:
            exact.append((entry_id, label))
            continue
        if any(key.startswith(normalized_query) for key in keys if key):
            prefix.append((entry_id, label))
            continue
        if any(normalized_query in key for key in keys if key):
            contains.append((entry_id, label))

    if len(exact) == 1:
        return exact[0]
    if len(prefix) == 1:
        return prefix[0]
    if len(contains) == 1:
        return contains[0]

    catalog_entry = _match_construct_catalog_entry(workspace, kind, query)
    if catalog_entry is not None:
        return catalog_entry.get("id") or catalog_entry.get("catalog_id"), catalog_entry.get("label") or None
    if kind == "object":
        object_meta = _match_object_id_metadata(workspace, query)
        if object_meta is not None:
            return str(object_meta.get("id") or ""), str(object_meta.get("label") or "") or None
    return None, None


def _construct_token(kind: str, value: str) -> str:
    return f"#{kind}:{value}"


def _build_construct_summary(ref: dict[str, Any]) -> str:
    kind = str(ref.get("kind", "") or "").replace("_", " ").strip()
    entry_id = str(ref.get("id", "") or "").strip()
    label = str(ref.get("label", "") or "").strip()
    if entry_id and label and _normalize_construct_key(entry_id) == _normalize_construct_key(label):
        return f"{kind.title()}: {label}"
    if entry_id and label:
        return f"{kind.title()} {entry_id}: {label}"
    if label:
        return f"{kind.title()}: {label}"
    if entry_id:
        return f"{kind.title()} {entry_id}"
    return ""


def _coerce_requested_construct_ref(item: dict[str, Any]) -> tuple[str, str] | None:
    raw_kind = str(item.get("kind", "") or "").strip()
    raw_query = str(item.get("query", "") or item.get("id", "") or "").strip()
    if not raw_query:
        token = str(item.get("token", "") or "").strip()
        match = _CONSTRUCT_REF_RE.match(token)
        if match:
            raw_kind = raw_kind or str(match.group(1) or "")
            raw_query = str(match.group(2) or "").strip()
    kind = normalize_construct_kind(raw_kind)
    if not kind or not raw_query:
        return None
    return kind, raw_query.rstrip(".,:;!?)]}")


def resolve_message_construct_refs(
    workspace: Path,
    prompt: str,
    *,
    requested: list[dict[str, Any]] | None = None,
    max_refs: int = 8,
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_ref(kind: str, query: str) -> bool:
        query = str(query or "").strip().rstrip(".,:;!?)]}")
        if not kind or not query:
            return False
        entry_id, label = _resolve_construct_entry(workspace, kind, query)
        dedupe_value = str(entry_id or query).strip().lower()
        dedupe_key = f"{kind}:{dedupe_value}"
        if dedupe_key in seen:
            return False
        seen.add(dedupe_key)
        token_value = str(entry_id or query)
        ref: dict[str, Any] = {
            "kind": kind,
            "query": query,
            "token": _construct_token(kind, token_value),
        }
        if entry_id:
            ref["id"] = entry_id
        if label:
            ref["label"] = label
        summary = _build_construct_summary(ref)
        if summary:
            ref["summary"] = summary
        refs.append(ref)
        return len(refs) >= max_refs

    requested = requested or []
    for item in requested:
        if not isinstance(item, dict):
            continue
        coerced = _coerce_requested_construct_ref(item)
        if coerced is None:
            continue
        kind, query = coerced
        if add_ref(kind, query):
            return refs

    for match in _CONSTRUCT_REF_RE.finditer(prompt):
        kind = normalize_construct_kind(str(match.group(1) or ""))
        query = str(match.group(2) or "")
        if add_ref(kind, query):
            break

    return refs


def _truncate_construct_context(text: str, *, max_chars: int = 1800) -> str:
    compact = str(text or "").strip()
    if not compact:
        return ""
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."


async def _call_construct_context_tool(
    bridge: ToolBridge | None,
    name: str,
    arguments: dict[str, Any],
    *,
    max_chars: int = 900,
) -> str:
    if bridge is None:
        return ""
    try:
        result = await bridge.call_tool(name, arguments)
    except Exception:
        return ""
    text = str(result or "").strip()
    if not text or text.startswith("Error:"):
        return ""
    return _truncate_construct_context(text, max_chars=max_chars)


async def _build_room_context_pack(ref: dict[str, Any], bridge: ToolBridge | None) -> str:
    room_id = str(ref.get("id", "") or "").strip()
    if not room_id:
        return ""
    sections: list[str] = []
    tool_specs = [
        ("Room overview", "dungeon_describe_room", {"room": room_id}),
        ("Objects", "dungeon_list_objects", {"room": room_id}),
        ("Sprites", "dungeon_list_sprites", {"room": room_id}),
        ("Chests", "dungeon_list_chests", {"room": room_id}),
    ]
    for heading, tool_name, arguments in tool_specs:
        result = await _call_construct_context_tool(bridge, tool_name, arguments)
        if result:
            sections.append(f"{heading}:\n{result}")
    return _truncate_construct_context("\n\n".join(sections), max_chars=2200)


async def _build_overworld_context_pack(ref: dict[str, Any], bridge: ToolBridge | None) -> str:
    map_id = str(ref.get("id", "") or "").strip()
    if not map_id:
        return ""
    sections: list[str] = []
    tool_specs = [
        ("Map overview", "overworld_describe_map", {"map_id": map_id}),
        ("Sprites", "overworld_list_sprites", {"map_id": map_id}),
        ("Warps", "overworld_list_warps", {"map_id": map_id}),
    ]
    for heading, tool_name, arguments in tool_specs:
        result = await _call_construct_context_tool(bridge, tool_name, arguments)
        if result:
            sections.append(f"{heading}:\n{result}")
    return _truncate_construct_context("\n\n".join(sections), max_chars=2200)


async def _build_message_context_pack(ref: dict[str, Any], bridge: ToolBridge | None) -> str:
    message_id = str(ref.get("id", "") or "").strip()
    if not message_id:
        return ""
    return await _call_construct_context_tool(
        bridge,
        "message_read",
        {"id": message_id},
        max_chars=1200,
    )


def _find_construct_catalog_entry(workspace: Path, ref: dict[str, Any]) -> dict[str, str] | None:
    kind = str(ref.get("kind", "") or "")
    if kind not in {"sprite", "object"}:
        return None
    for value in (
        ref.get("id"),
        ref.get("label"),
        ref.get("query"),
    ):
        if not value:
            continue
        entry = _match_construct_catalog_entry(workspace, kind, str(value))
        if entry is not None:
            return entry
    return None


def _build_catalog_context_pack(workspace: Path, ref: dict[str, Any]) -> str:
    entry = _find_construct_catalog_entry(workspace, ref)
    if entry is None:
        return ""
    lines = [
        f"Catalog section: {entry.get('section', '')}",
    ]
    if entry.get("id"):
        lines.append(f"Registry ID: {entry['id']}")
    if entry.get("status"):
        lines.append(f"Status: {entry['status']}")
    if entry.get("location"):
        lines.append(f"Location: {entry['location']}")
    if entry.get("role"):
        lines.append(f"Role: {entry['role']}")
    if entry.get("service"):
        lines.append(f"Service: {entry['service']}")
    if entry.get("purpose"):
        lines.append(f"Purpose: {entry['purpose']}")
    if entry.get("vanilla_base"):
        lines.append(f"Vanilla base: {entry['vanilla_base']}")
    if entry.get("notes"):
        lines.append(f"Notes: {entry['notes']}")
    return _truncate_construct_context("\n".join(line for line in lines if line.strip()), max_chars=1200)


def _find_object_metadata_entry(workspace: Path, ref: dict[str, Any]) -> dict[str, Any] | None:
    if str(ref.get("kind", "") or "") != "object":
        return None
    for value in (
        ref.get("id"),
        ref.get("label"),
        ref.get("query"),
    ):
        if not value:
            continue
        entry = _match_object_id_metadata(workspace, str(value))
        if entry is not None:
            return entry
    return None


def _build_object_metadata_context_pack(workspace: Path, ref: dict[str, Any]) -> str:
    entry = _find_object_metadata_entry(workspace, ref)
    if entry is None:
        return ""
    lines = [f"Object ID: {entry.get('id', '')}"]
    aliases = [str(alias) for alias in entry.get("aliases", []) if str(alias or "").strip()]
    if aliases:
        lines.append(f"Aliases: {', '.join(aliases)}")
    sources = [str(source) for source in entry.get("sources", []) if str(source or "").strip()]
    if sources:
        lines.append(f"Sources: {', '.join(sources)}")
    notes = [str(note) for note in entry.get("notes", []) if str(note or "").strip()]
    for note in notes:
        lines.append(note)
    subtypes = [str(subtype) for subtype in entry.get("subtypes", []) if str(subtype or "").strip()]
    if subtypes:
        lines.append("Subtype map:")
        lines.extend(f"- {subtype}" for subtype in subtypes[:12])
        if len(subtypes) > 12:
            lines.append(f"- ... {len(subtypes) - 12} more")
    return _truncate_construct_context("\n".join(line for line in lines if line.strip()), max_chars=1400)


async def add_construct_context_packs(
    refs: list[dict[str, Any]],
    *,
    bridge: ToolBridge | None,
    workspace: Path | None = None,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    capability_bridges = build_capability_bridges(bridge) if bridge is not None else {}
    rom_bridge = capability_bridges.get("rom") or capability_bridges.get("*")
    for item in refs:
        ref = dict(item)
        summary = _build_construct_summary(ref)
        if summary:
            ref["summary"] = summary
        context_pack = ""
        kind = str(ref.get("kind", "") or "")
        if kind == "room":
            context_pack = await _build_room_context_pack(ref, rom_bridge)
        elif kind == "overworld":
            context_pack = await _build_overworld_context_pack(ref, rom_bridge)
        elif kind == "message":
            context_pack = await _build_message_context_pack(ref, rom_bridge)
        elif kind in {"sprite", "object"} and workspace is not None:
            context_pack = _build_catalog_context_pack(workspace, ref)
            if not context_pack and kind == "object":
                context_pack = _build_object_metadata_context_pack(workspace, ref)
        if context_pack:
            ref["context_pack"] = context_pack
        enriched.append(ref)
    return enriched


def enrich_prompt_with_construct_refs(prompt: str, refs: list[dict[str, Any]]) -> str:
    if not refs:
        return prompt

    sections = [prompt.rstrip(), "", "Referenced game context:"]
    appended = 0
    for ref in refs:
        body_parts: list[str] = []
        summary = str(ref.get("summary", "") or "").strip()
        context_pack = str(ref.get("context_pack", "") or "").strip()
        if summary:
            body_parts.append(summary)
        if context_pack:
            body_parts.append(context_pack)
        if not body_parts:
            continue
        token = str(ref.get("token", "") or _construct_token(
            str(ref.get("kind", "") or "construct"),
            str(ref.get("id") or ref.get("query") or "?"),
        )).strip()
        sections.extend([
            "",
            token,
            "```text",
            "\n\n".join(body_parts),
            "```",
        ])
        appended += 1
    if appended == 0:
        return prompt
    return "\n".join(sections).strip()


async def add_attachment_context_packs(
    attachments: list[dict[str, Any]],
    *,
    bridge: ToolBridge | None,
    model: ModelConfig | None = None,
    lsp_context_mode: str = "auto",
    prompt_query: str = "",
) -> list[dict[str, Any]]:
    """Attach compact z3lsp summaries to resolved message attachments."""
    enriched: list[dict[str, Any]] = []
    for item in attachments:
        attachment = dict(item)
        full_path = str(attachment.get("full_path", "")).strip()
        if full_path:
            pack = await build_z3lsp_context_pack(
                bridge,
                full_path,
                model=model,
                lsp_context_mode=lsp_context_mode,
                query=prompt_query,
            )
            if pack:
                attachment["context_pack"] = pack
        enriched.append(attachment)
    return enriched


async def build_focus_context_content(
    focus_path: Path,
    content: str,
    *,
    bridge: ToolBridge | None,
    model: ModelConfig | None = None,
    lsp_context_mode: str = "auto",
    prompt_query: str = "",
) -> str:
    """Combine a compact z3lsp pack with raw focus-file content."""
    pack = await build_z3lsp_context_pack(
        bridge,
        focus_path,
        model=model,
        lsp_context_mode=lsp_context_mode,
        query=prompt_query,
    )
    if not pack:
        return content
    return "\n".join([
        "--- z3lsp Context ---",
        pack,
        "",
        "--- File Content ---",
        content,
    ])


async def load_enriched_focus_file(
    workspace: Path,
    raw_path: str | Path,
    *,
    bridge: ToolBridge | None,
    model: ModelConfig | None = None,
    lsp_context_mode: str = "auto",
    prompt_query: str = "",
    file_max_chars: int = 32_000,
) -> tuple[Path, str]:
    """Load a focus file and prepend a compact z3lsp context pack when available."""
    focus_path, content = load_focus_file(workspace, str(raw_path), max_chars=file_max_chars)
    enriched = await build_focus_context_content(
        focus_path,
        content,
        bridge=bridge,
        model=model,
        lsp_context_mode=lsp_context_mode,
        prompt_query=prompt_query,
    )
    return focus_path, enriched


def resolve_message_attachments(
    workspace: Path,
    prompt: str,
    *,
    requested: list[dict[str, Any]] | None = None,
    max_files: int = 6,
    max_chars: int = 12_000,
) -> list[dict[str, Any]]:
    """Resolve structured and inline ``@path`` file references to attachments."""
    attachments: list[dict[str, Any]] = []
    seen: set[Path] = set()

    requested = requested or []
    for item in requested:
        if not isinstance(item, dict):
            continue
        raw_value = str(item.get("path", "") or "").strip().rstrip(".,:;!?)]}")
        if not raw_value:
            continue
        try:
            path, content = load_focus_file(workspace, raw_value, max_chars=max_chars)
        except FileNotFoundError:
            continue
        except Exception:
            continue
        if path in seen:
            continue
        seen.add(path)
        attachments.append({
            "path": _attachment_label(workspace, path),
            "full_path": str(path),
            "content": content,
            "lines": content.count("\n") + 1,
            "chars": len(content),
        })
        if len(attachments) >= max_files:
            return attachments

    for match in _ATTACHMENT_RE.finditer(prompt):
        raw_value = (match.group(1) or "").strip().rstrip(".,:;!?)]}")
        if not raw_value:
            continue
        try:
            path, content = load_focus_file(workspace, raw_value, max_chars=max_chars)
        except FileNotFoundError:
            continue
        except Exception:
            continue
        if path in seen:
            continue
        seen.add(path)
        attachments.append({
            "path": _attachment_label(workspace, path),
            "full_path": str(path),
            "content": content,
            "lines": content.count("\n") + 1,
            "chars": len(content),
        })
        if len(attachments) >= max_files:
            break

    return attachments


def enrich_prompt_with_attachments(prompt: str, attachments: list[dict[str, Any]]) -> str:
    """Append resolved attachment contents to the model-facing user message."""
    if not attachments:
        return prompt

    sections = [prompt.rstrip(), "", "Attached file context:"]
    for attachment in attachments:
        context_pack = str(attachment.get("context_pack", "") or "").strip()
        if context_pack:
            sections.extend([
                "",
                f"@{attachment['path']} z3lsp",
                "```text",
                context_pack,
                "```",
            ])
        sections.extend([
            "",
            f"@{attachment['path']}",
            "```",
            str(attachment["content"]),
            "```",
        ])
    return "\n".join(sections).strip()


def build_harness_prompt(
    workspace: Path,
    rom_path: Path | None,
    focus_context: str = "",
) -> str:
    lines = [
        "You are operating inside z3cli, a local Zelda ROM-hacking CLI harness.",
        "Stay concrete, prefer practical hacking steps, and do not invent symbols, addresses, or tool names.",
        "Treat this as a local project harness. Do not argue about model provenance, vendor identity, or who trained you unless the user explicitly asks for provenance debugging.",
        "When the user reports a z3cli or tool bug, stay focused on reproducing it, gathering evidence, and suggesting the next fix.",
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


def build_orchestrator_prompt(specialists: list[dict]) -> str:
    """System prompt that instructs a cloud planner to delegate via spawn_subagent.

    Args:
        specialists: List of specialist descriptors from list_subagents,
            used to build a compact catalog for the planner.
    """
    lines = [
        "You are operating in **orchestrator mode** — your job is to decompose the user's request and delegate execution to local specialist subagents.",
        "",
        "## How to work",
        "1. Use `list_subagents` once if you're unsure what specialists are available.",
        "2. For each concrete subtask, call `spawn_subagent` with the right specialist. Keep each delegated prompt self-contained — the subagent does not see this conversation.",
        "3. Prefer parallelizing independent subtasks by issuing multiple spawn_subagent calls in a single response.",
        "4. After specialists finish, synthesize their outputs into a coherent final answer. Do not just relay raw subagent text — integrate and summarize.",
        "5. Only do work yourself when it's pure reasoning or synthesis. For ROM/code/tool operations, delegate to the specialists who have the relevant tools.",
        "",
        "## Available specialists",
    ]
    if specialists:
        for spec in specialists:
            role = spec.get("role") or ""
            profile = spec.get("tool_profile") or ""
            provider = spec.get("provider") or ""
            parts = [f"- **{spec['name']}**"]
            if provider and provider != "studio":
                parts.append(f"({provider})")
            if role:
                parts.append(f"— {role}")
            if profile:
                parts.append(f"[tools: {profile}]")
            lines.append(" ".join(parts))
    else:
        lines.append("(No specialists configured. Tell the user to set up their chat_registry.toml.)")
    return "\n".join(lines)


def default_orchestrator_model(models: dict[str, ModelConfig]) -> str | None:
    """Pick the best available orchestrator model from the registry.

    Preference order:
    1. Any model tagged 'orchestrator' in its tags or role
    2. DEFAULT_ORCHESTRATOR_CANDIDATES in priority order, if present and keyed
    3. First cloud model with an API key available
    """
    # Check for explicit orchestrator tagging
    for name, model in models.items():
        if "orchestrator" in {tag.lower() for tag in model.tags}:
            if not model.is_cloud or model.resolve_api_key():
                return name
    # Check the candidate list
    for candidate in DEFAULT_ORCHESTRATOR_CANDIDATES:
        model = models.get(candidate)
        if model is None:
            continue
        if not model.is_cloud or model.resolve_api_key():
            return candidate
    # Fall back to first available cloud model with a key
    for name, model in models.items():
        if model.is_cloud and model.resolve_api_key():
            return name
    return None


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
    profile_domain: str,
    profile_mode: str,
    profile_effort: str,
) -> tuple[ModelConfig | None, str | None, str | None, str | None]:
    """Resolve a model via oracle keyword routing + tool hints.

    Returns a tuple of (model, reason, tool_hint, router_keyword).
    """
    # Tool-aware hint takes priority — if the user mentions a specific
    # adapter tool or MCP server, route to the owning specialist.
    hint = _tool_hint(prompt, models)
    if hint and hint in models:
        hinted = models[hint]
        if not blocked_model_reason(hinted):
            return hinted, "tool-hint", hint, None

    # Fall back to keyword router
    router = routers.get("oracle")
    if router:
        model_name, _matched = route_message(prompt, router, models)
        if model_name:
            model = models.get(model_name)
            if model is not None and not blocked_model_reason(model):
                return model, "router-rule", None, _matched

    # If no direct routing match, route through the internal profile contract.
    # The canonical oracle model remains stable while the prompt profile
    # changes behavior by changing the selected system prompt overlays.
    profile_target, profile_reason = _pick_profiled_candidate_with_reason(
        models,
        profile_domain,
        profile_mode,
        profile_effort,
        candidate_names=_oracle_candidate_names(models),
    )
    if profile_target is not None:
        return profile_target, profile_reason, None, None

    if router is not None and router.default and router.default in models:
        default_model = models[router.default]
        if not blocked_model_reason(default_model):
            return default_model, "router-default", None, None

    return None, "profile-fallback: no oracle candidates", None, None


def resolve_targets_with_reason(
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
    orchestrator_model: str = "",
) -> tuple[list[ModelConfig], list[RoutingDecision]]:
    fallback = models.get(active_model, ModelConfig(name=active_model, model_id=active_model))
    normalized_mode, legacy_mode_alias = normalize_mode(mode)
    profile_domain, profile_mode, profile_effort = _infer_prompt_profiles(prompt)

    if backend_name == "llamacpp":
        target = ModelConfig(
            name=llamacpp_model,
            model_id=llamacpp_model,
            temperature=temperature,
            max_tokens=max_tokens,
            role="fast local main model",
            tools_enabled=True,
        )
        return [target], [
            RoutingDecision(
                target=target.name,
                reason="llamacpp",
                requested_mode=mode,
                normalized_mode="llamacpp",
                legacy_mode_alias=None,
                profile_domain=profile_domain,
                profile_mode=profile_mode,
                profile_effort=profile_effort,
            )
        ]

    def decision_for(
        model: ModelConfig,
        reason: str,
        *,
        tool_hint: str | None = None,
        router_keyword: str | None = None,
    ) -> RoutingDecision:
        return RoutingDecision(
            target=model.name,
            reason=reason,
            requested_mode=mode,
            normalized_mode=normalized_mode,
            legacy_mode_alias=legacy_mode_alias,
            profile_domain=profile_domain,
            profile_mode=profile_mode,
            profile_effort=profile_effort,
            tool_hint=tool_hint,
            router_keyword=router_keyword,
        )

    if normalized_mode == "manual":
        return [fallback], [decision_for(fallback, reason="manual")]

    if normalized_mode == "oracle":
        model, reason, tool_hint, router_keyword = _oracle_route(
            prompt,
            models,
            routers,
            profile_domain=profile_domain,
            profile_mode=profile_mode,
            profile_effort=profile_effort,
        )
        if model is not None:
            return [model], [decision_for(model, reason=reason or "oracle-route", tool_hint=tool_hint, router_keyword=router_keyword)]

        safe_oracle, safe_reason = _pick_profiled_candidate_with_reason(
            models,
            profile_domain,
            profile_mode,
            profile_effort,
            candidate_names=_oracle_candidate_names(models),
        )
        if safe_oracle is not None:
            return [safe_oracle], [decision_for(safe_oracle, safe_reason)]

        safe_fallback = _preferred_safe_model(models, candidates=DEFAULT_SAFE_ORACLE_MODELS)
        if safe_fallback is not None:
            return [safe_fallback], [decision_for(safe_fallback, "oracle-fallback: safe-model")]
        return [fallback], [decision_for(fallback, "oracle-fallback: active-model")]

    if normalized_mode == ORCHESTRATOR_MODE:
        # Explicit orchestrator model override
        if orchestrator_model and orchestrator_model in models:
            orchestrator_target = models[orchestrator_model]
            return [orchestrator_target], [decision_for(orchestrator_target, "orchestrator-explicit")]

        # Auto-select best available
        auto = default_orchestrator_model(models)
        if auto and auto in models:
            orchestrator_target = models[auto]
            return [orchestrator_target], [decision_for(orchestrator_target, "orchestrator-auto")]

        # No cloud orchestrator configured — fall back to the active model
        # (which will still benefit from subagent tools being being enabled)
        return [fallback], [decision_for(fallback, "orchestrator-fallback")]

    if normalized_mode == "broadcast":
        targets = [models[name] for name in broadcast_models if name in models]
        if targets:
            return targets, [decision_for(target, "broadcast-primary") for target in targets]
        return [fallback], [decision_for(fallback, "broadcast-empty-fallback")]

    raise RuntimeError(f"Unknown mode: {mode}")


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
    orchestrator_model: str = "",
) -> list[ModelConfig]:
    targets, _decisions = resolve_targets_with_reason(
        models=models,
        routers=routers,
        active_model=active_model,
        mode=mode,
        prompt=prompt,
        broadcast_models=broadcast_models,
        backend_name=backend_name,
        llamacpp_model=llamacpp_model,
        temperature=temperature,
        max_tokens=max_tokens,
        orchestrator_model=orchestrator_model,
    )
    return targets
