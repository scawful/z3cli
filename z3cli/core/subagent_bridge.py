"""Tool bridge that exposes subagent spawning as a tool call.

The SubagentBridge lets the main model delegate work to specialist
subagents by calling a `spawn_subagent` tool. This is the "orchestrator"
pattern: the main model (often a cloud planner like Claude) decides to
invoke a local specialist, gets the specialist's summarized output, and
incorporates it into its own reasoning.
"""

from __future__ import annotations

import inspect
import json
from typing import Awaitable, Callable

from z3cli.core.config import ModelConfig, can_spawn_model
from z3cli.core.subagent import SubagentConfig, SubagentRunner
from z3cli.core.tool_bridge import ToolBridge


SPAWN_TOOL_NAME = "spawn_subagent"
LIST_TOOL_NAME = "list_subagents"


class SubagentBridge:
    """ToolBridge that exposes subagent spawning tools.

    Tools exposed:
    - `spawn_subagent(model, prompt, tool_profile=?, max_rounds=?)` —
      runs a subagent and returns its final text plus metadata.
    - `list_subagents()` — returns the catalog of available specialist
      models with their roles and tool profiles.

    Typically composed with the main tool bridge via CompositeBridge
    so the main model sees MCP tools + subagent spawning side by side.
    """

    SERVER_NAME = "subagents"

    def __init__(
        self,
        runner: SubagentRunner,
        models: dict[str, ModelConfig],
        system_context_fn: Callable[[ModelConfig, str], str | Awaitable[str]] | None = None,
        *,
        current_depth: int = 0,
        parent_chain: tuple[str, ...] | list[str] = (),
        parent_model: str = "",
        parent_id: str = "",
    ):
        """
        Args:
            runner: The shared SubagentRunner instance.
            models: Registry of available models (for validation + listing).
            system_context_fn: Optional callable returning the harness context
                prepended to each subagent's system prompt for the child model.
            current_depth: Depth of the agent that owns this bridge. A spawn
                invoked through this bridge produces a child at
                ``current_depth + 1``. Top-level bridge uses 0.
            parent_chain: Ancestor model names leading to the agent that
                owns this bridge (not including that agent itself).
            parent_model: Model name of the agent that owns this bridge.
                Appended onto the child's parent_chain for cycle detection.
            parent_id: Subagent id of the agent that owns this bridge.
                Used by the frontend to render nested delegation as a tree.
        """
        self._runner = runner
        self._models = models
        self._system_context_fn = system_context_fn or (lambda _model, _prompt: "")
        self._current_depth = current_depth
        self._parent_chain = tuple(parent_chain)
        self._parent_model = parent_model
        self._parent_id = parent_id

    # -- ToolBridge protocol -------------------------------------------------

    def _available_models(self) -> list[tuple[str, ModelConfig]]:
        blocked = set(self._parent_chain)
        if self._parent_model:
            blocked.add(self._parent_model)
        if self._current_depth + 1 > self._runner.max_depth:
            return []
        entries: list[tuple[str, ModelConfig]] = []
        for name in sorted(self._models):
            model = self._models[name]
            if not (model.is_local or model.resolve_api_key()):
                continue
            if name in blocked:
                continue
            if not can_spawn_model(self._parent_model, model):
                continue
            entries.append((name, model))
        return entries

    def available_model_names(self) -> list[str]:
        return [name for name, _model in self._available_models()]

    def specialist_entries(self) -> list[dict[str, object]]:
        entries: list[dict[str, object]] = []
        for name, model in self._available_models():
            entries.append({
                "name": name,
                "provider": model.provider,
                "role": model.role,
                "description": model.description,
                "tool_profile": model.tool_profile,
                "thinking": bool(model.thinking_tier),
            })
        return entries

    def get_openai_tools(self) -> list[dict]:
        available = self.available_model_names()
        return [
            {
                "type": "function",
                "function": {
                    "name": SPAWN_TOOL_NAME,
                    "description": (
                        "Delegate a subtask to a specialist subagent. The subagent "
                        "runs in an isolated context with its own tool access and "
                        "returns a summary of its work. Use this to parallelize "
                        "independent work, tap domain specialists (ASM review, "
                        "debugging, lore lookup), or keep the main context lean."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "model": {
                                "type": "string",
                                "description": (
                                    "Name of the specialist model to spawn. "
                                    f"Available: {', '.join(available) if available else '(none configured)'}"
                                ),
                                "enum": available if available else None,
                            },
                            "prompt": {
                                "type": "string",
                                "description": (
                                    "Self-contained task briefing for the subagent. "
                                    "Include all context it needs — the subagent "
                                    "does not see the parent conversation."
                                ),
                            },
                            "tool_profile": {
                                "type": "string",
                                "description": (
                                    "Optional tool profile override (e.g. 'nayru', "
                                    "'farore', '*' for full surface). Defaults to "
                                    "the model's configured profile."
                                ),
                            },
                            "max_rounds": {
                                "type": "integer",
                                "description": "Max tool-calling rounds (default 4).",
                                "minimum": 1,
                                "maximum": 12,
                            },
                        },
                        "required": ["model", "prompt"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": LIST_TOOL_NAME,
                    "description": (
                        "List available specialist subagents with their roles "
                        "and domain focus. Call this first if unsure which "
                        "specialist fits the task."
                    ),
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ]

    async def call_tool(self, name: str, arguments: dict) -> str:
        if name == LIST_TOOL_NAME:
            return self._list_specialists()
        if name == SPAWN_TOOL_NAME:
            return await self._spawn(arguments)
        return f"Error: Unknown subagent tool '{name}'"

    def get_tool_server(self, tool_name: str) -> str:
        return self.SERVER_NAME

    @property
    def tool_count(self) -> int:
        return 2

    @property
    def server_names(self) -> list[str]:
        return [self.SERVER_NAME]

    @property
    def server_tool_counts(self) -> dict[str, int]:
        return {self.SERVER_NAME: 2}

    async def close(self) -> None:
        # Runner lifetime is owned elsewhere (usually ServeState)
        pass

    # -- Tool implementations ------------------------------------------------

    def _list_specialists(self) -> str:
        blocked = set(self._parent_chain)
        if self._parent_model:
            blocked.add(self._parent_model)
        depth_exhausted = self._current_depth + 1 > self._runner.max_depth
        entries = self.specialist_entries()
        payload: dict[str, object] = {"specialists": entries}
        if depth_exhausted:
            payload["note"] = (
                f"Subagent nesting limit reached at depth {self._current_depth}. "
                "Further delegation is disabled."
            )
        elif blocked:
            payload["filtered_models"] = sorted(blocked)
        return json.dumps(payload, indent=2)

    async def _resolve_system_context(self, model: ModelConfig, prompt: str) -> str:
        context = self._system_context_fn(model, prompt)
        if inspect.isawaitable(context):
            context = await context
        return str(context or "")

    async def _spawn(self, arguments: dict) -> str:
        model_name = str(arguments.get("model", "")).strip()
        prompt = str(arguments.get("prompt", "")).strip()
        tool_profile = str(arguments.get("tool_profile", "") or "")
        max_rounds = int(arguments.get("max_rounds", 4) or 4)
        max_rounds = max(1, min(max_rounds, 12))

        if not model_name:
            return "Error: 'model' is required"
        if not prompt:
            return "Error: 'prompt' is required"

        model_cfg = self._models.get(model_name)
        if model_cfg is None:
            available = ", ".join(sorted(self._models))
            return f"Error: Unknown model '{model_name}'. Available: {available}"
        if not can_spawn_model(self._parent_model, model_cfg):
            caller = f"'{self._parent_model}'" if self._parent_model else "this caller"
            return f"Error: Model '{model_name}' is not available to {caller}"
        if model_cfg.is_cloud and not model_cfg.resolve_api_key():
            return f"Error: Cloud model '{model_name}' has no API key configured"

        raw_prompt = prompt
        prompt = await self._runner.enrich_prompt(prompt, model_cfg)

        # Compute the child's depth and parent chain. The bridge owner's
        # own model name goes onto the chain so the child can detect cycles.
        child_depth = self._current_depth + 1
        if self._parent_model:
            child_chain = [*self._parent_chain, self._parent_model]
        else:
            child_chain = list(self._parent_chain)

        config = SubagentConfig(
            name=model_name,
            model=model_cfg,
            tool_profile=tool_profile or model_cfg.tool_profile,
            max_rounds=max_rounds,
            max_tokens=model_cfg.max_tokens,
            temperature=model_cfg.temperature,
            thinking=bool(model_cfg.thinking_tier),
            depth=child_depth,
            parent_chain=child_chain,
            parent_id=self._parent_id,
        )

        result = await self._runner.spawn(
            config,
            prompt,
            system_context=await self._resolve_system_context(model_cfg, raw_prompt),
        )

        if result.error:
            return f"Subagent '{model_name}' failed: {result.error}"

        summary: dict = {
            "subagent": model_name,
            "model": result.model_name,
            "text": result.text,
            "tool_calls": result.tool_calls,
            "tokens": {
                "prompt": result.prompt_tokens,
                "completion": result.completion_tokens,
            },
        }
        return json.dumps(summary, indent=2)
