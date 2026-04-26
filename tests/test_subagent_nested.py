"""Tests for nested subagent spawning (depth limits + cycle detection).

Exercises the subagent-to-subagent delegation path built on top of the
existing SubagentRunner / SubagentBridge, using the MockProvider and
MockBridge patterns established in ``test_subagent.py``.
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from core.subagent import SubagentConfig, SubagentRunner
from core.subagent_bridge import SPAWN_TOOL_NAME, SubagentBridge
from core.tool_bridge import CompositeBridge

from tests.test_subagent import MockProvider, make_model, text_chunks


class CapturingEngine:
    """Minimal ChatEngine double that records the bridge passed to it."""

    last_bridge = None

    def __init__(self, bridge=None, permission_hook=None, provider=None):
        del permission_hook, provider
        self.bridge = bridge
        CapturingEngine.last_bridge = bridge

    async def chat(self, **kwargs):
        del kwargs
        if False:
            yield None
        return

    def cancel(self) -> None:
        pass

    async def close(self) -> None:
        pass


class NestedSubagentTests(unittest.IsolatedAsyncioTestCase):
    async def test_subagent_spawns_child_successfully(self) -> None:
        """Depth-1 bridge can spawn a depth-2 subagent under max_depth=2."""
        models = {
            "nayru": make_model("nayru"),
            "farore": make_model("farore"),
        }
        # Child runs at depth=2, returns text "CHILD".
        child_provider = MockProvider([text_chunks(["CHILD"])])
        runner = SubagentRunner(
            max_depth=2,
            models=models,
            # Disable the auto-composed nested bridge on the child so the
            # child engine doesn't try to do its own delegation here.
            expose_subagent_bridge_to_children=False,
        )

        # A bridge owned by a depth-1 agent ("nayru") spawns "farore".
        bridge = SubagentBridge(
            runner=runner,
            models=models,
            current_depth=1,
            parent_chain=(),
            parent_model="nayru",
        )

        # Monkey-patch the bridge's _spawn to use the mocked provider.
        original_spawn = runner.spawn

        async def spawn_with_mock(config, prompt, **kwargs):
            kwargs.setdefault("provider_override", child_provider)
            return await original_spawn(config, prompt, **kwargs)

        runner.spawn = spawn_with_mock  # type: ignore[assignment]

        raw = await bridge.call_tool(
            SPAWN_TOOL_NAME,
            {"model": "farore", "prompt": "hi"},
        )
        data = json.loads(raw)
        self.assertEqual(data["subagent"], "farore")
        self.assertEqual(data["text"], "CHILD")

    async def test_max_depth_rejects_too_deep_spawn(self) -> None:
        """A config at depth greater than max_depth is rejected."""
        runner = SubagentRunner(max_depth=2)
        config = SubagentConfig(
            name="too-deep",
            model=make_model("too-deep"),
            depth=3,
        )
        result = await runner.spawn(config, "go")
        self.assertIn("max subagent depth", result.error)
        self.assertEqual(result.text, "")

    async def test_cycle_detection_rejects_same_model_in_chain(self) -> None:
        """If the model name already appears in parent_chain, reject."""
        runner = SubagentRunner(max_depth=5)
        config = SubagentConfig(
            name="nayru",
            model=make_model("nayru"),
            depth=2,
            parent_chain=["orchestrator", "nayru"],
        )
        result = await runner.spawn(config, "go")
        self.assertIn("cycle detected", result.error)
        self.assertIn("nayru", result.error)

    async def test_depth_zero_spawn_still_works(self) -> None:
        """No regression: top-level spawns run as before."""
        provider = MockProvider([text_chunks(["OK"])])
        runner = SubagentRunner(max_depth=2)
        config = SubagentConfig(name="root", model=make_model())
        # Implicit depth=0 by default.
        result = await runner.spawn(config, "go", provider_override=provider)
        self.assertEqual(result.text, "OK")
        self.assertEqual(result.error, "")

    async def test_siblings_at_same_depth_do_not_interfere(self) -> None:
        """Two sequential spawns at depth=1 each succeed independently."""
        p1 = MockProvider([text_chunks(["A"])])
        p2 = MockProvider([text_chunks(["B"])])
        runner = SubagentRunner(max_depth=2)

        c1 = SubagentConfig(
            name="sib-a",
            model=make_model("sib-a"),
            depth=1,
            parent_chain=["orchestrator"],
        )
        c2 = SubagentConfig(
            name="sib-b",
            model=make_model("sib-b"),
            depth=1,
            parent_chain=["orchestrator"],
        )

        r1 = await runner.spawn(c1, "go", provider_override=p1)
        r2 = await runner.spawn(c2, "go", provider_override=p2)

        self.assertEqual(r1.text, "A")
        self.assertEqual(r1.error, "")
        self.assertEqual(r2.text, "B")
        self.assertEqual(r2.error, "")

    async def test_auto_composed_child_bridge_does_not_mutate_parent_composite(self) -> None:
        models = {
            "planner": make_model("planner"),
            "worker": make_model("worker"),
        }
        runner = SubagentRunner(max_depth=2, models=models)
        root = CompositeBridge([SubagentBridge(runner=runner, models=models)])
        runner.set_bridge(root)

        provider = MockProvider([text_chunks(["OK"])])
        await runner.spawn(
            SubagentConfig(name="worker", model=models["worker"], depth=1),
            "go",
            provider_override=provider,
        )

        self.assertEqual(
            [tool["function"]["name"] for tool in root.get_openai_tools()],
            ["spawn_subagent", "list_subagents"],
        )

    async def test_auto_composed_child_bridge_uses_correct_depth_and_chain(self) -> None:
        models = {
            "planner": make_model("planner"),
            "worker": make_model("worker"),
            "helper": make_model("helper"),
        }
        runner = SubagentRunner(max_depth=2, models=models)
        root = CompositeBridge([SubagentBridge(runner=runner, models=models)])
        runner.set_bridge(root)

        with patch("core.subagent.ChatEngine", CapturingEngine):
            await runner.spawn(
                SubagentConfig(name="worker", model=models["worker"], depth=1),
                "go",
                provider_override=MockProvider([]),
            )

        child_bridge = CapturingEngine.last_bridge
        assert child_bridge is not None
        tool_names = [tool["function"]["name"] for tool in child_bridge.get_openai_tools()]
        self.assertEqual(tool_names, ["spawn_subagent", "list_subagents"])

        captured: dict[str, object] = {}

        async def fake_spawn(config, prompt, **kwargs):
            del prompt, kwargs
            captured["depth"] = config.depth
            captured["parent_chain"] = list(config.parent_chain)
            captured["model_name"] = config.model.name
            from core.subagent import SubagentResult

            return SubagentResult(
                id="sub-test",
                name=config.name,
                model_name=config.model.name,
                text="ok",
            )

        runner.spawn = fake_spawn  # type: ignore[assignment]
        raw = await child_bridge.call_tool(
            SPAWN_TOOL_NAME,
            {"model": "helper", "prompt": "nested"},
        )
        data = json.loads(raw)
        self.assertEqual(data["subagent"], "helper")
        self.assertEqual(captured["depth"], 2)
        self.assertEqual(captured["parent_chain"], ["worker"])
        self.assertEqual(captured["model_name"], "helper")

    async def test_auto_composed_child_bridge_inherits_model_aware_system_context(self) -> None:
        models = {
            "planner": make_model("planner"),
            "worker": make_model("worker"),
            "helper": make_model("helper"),
        }

        async def system_context(model, prompt) -> str:  # type: ignore[no-untyped-def]
            return f"context:{model.name}:{prompt}"

        runner = SubagentRunner(
            max_depth=2,
            models=models,
            system_context_resolver=system_context,
        )
        root = CompositeBridge([
            SubagentBridge(
                runner=runner,
                models=models,
                system_context_fn=runner.resolve_system_context,
            ),
        ])
        runner.set_bridge(root)

        with patch("core.subagent.ChatEngine", CapturingEngine):
            await runner.spawn(
                SubagentConfig(name="worker", model=models["worker"], depth=1),
                "go",
                provider_override=MockProvider([]),
            )

        child_bridge = CapturingEngine.last_bridge
        assert child_bridge is not None
        captured: dict[str, str] = {}

        async def fake_spawn(config, prompt, **kwargs):  # type: ignore[no-untyped-def]
            del prompt
            captured["model_name"] = config.model.name
            captured["system_context"] = str(kwargs.get("system_context", ""))
            from core.subagent import SubagentResult

            return SubagentResult(
                id="sub-test",
                name=config.name,
                model_name=config.model.name,
                text="ok",
            )

        runner.spawn = fake_spawn  # type: ignore[assignment]
        raw = await child_bridge.call_tool(
            SPAWN_TOOL_NAME,
            {"model": "helper", "prompt": "nested"},
        )
        data = json.loads(raw)

        self.assertEqual(data["subagent"], "helper")
        self.assertEqual(captured["model_name"], "helper")
        self.assertEqual(captured["system_context"], "context:helper:nested")

    async def test_list_subagents_filters_cycles_for_nested_bridge(self) -> None:
        models = {
            "planner": make_model("planner"),
            "worker": make_model("worker"),
            "helper": make_model("helper"),
        }
        runner = SubagentRunner(max_depth=3, models=models)
        bridge = SubagentBridge(
            runner=runner,
            models=models,
            current_depth=1,
            parent_chain=("planner",),
            parent_model="worker",
        )

        raw = await bridge.call_tool("list_subagents", {})
        data = json.loads(raw)
        names = [item["name"] for item in data["specialists"]]

        self.assertEqual(names, ["helper"])
        self.assertEqual(data["filtered_models"], ["planner", "worker"])


if __name__ == "__main__":
    unittest.main()
