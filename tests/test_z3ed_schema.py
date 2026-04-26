"""Tests for the z3ed schema translator."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from protocol.z3ed_schema import (
    Parameter,
    build_tool,
    load_schemas,
    parse_usage,
    repair_z3ed_json,
)


class RepairJsonTests(unittest.TestCase):
    def test_repairs_application_support_escape(self) -> None:
        raw = r'{"ex": "~/Library/Application\ Support/Mesen2"}'
        repaired = repair_z3ed_json(raw)
        data = json.loads(repaired)
        self.assertIn("Application\\ Support", data["ex"])

    def test_leaves_valid_escapes_untouched(self) -> None:
        raw = r'{"tab": "a\tb", "quote": "\"hi\"", "unicode": "\u00e9"}'
        repaired = repair_z3ed_json(raw)
        data = json.loads(repaired)
        self.assertEqual(data["tab"], "a\tb")
        self.assertEqual(data["quote"], '"hi"')
        self.assertEqual(data["unicode"], "é")


class ParseUsageTests(unittest.TestCase):
    def test_required_flag(self) -> None:
        params = parse_usage("dialogue-read --id <message_id> [--format <json|text>]")
        self.assertEqual({p.name for p in params}, {"id", "format"})
        id_param = next(p for p in params if p.name == "id")
        fmt_param = next(p for p in params if p.name == "format")
        self.assertTrue(id_param.required)
        self.assertFalse(fmt_param.required)
        self.assertEqual(fmt_param.kind, "enum")
        self.assertEqual(fmt_param.enum_values, ["json", "text"])

    def test_optional_boolean(self) -> None:
        params = parse_usage("dungeon-doctor --rom <path> [--all] [--verbose]")
        all_p = next(p for p in params if p.name == "all")
        self.assertFalse(all_p.required)
        self.assertEqual(all_p.kind, "boolean")

    def test_write_flag_detected(self) -> None:
        usage = "dungeon-generate-track-collision --room <room_id> [--write]"
        params = parse_usage(usage)
        write_p = next(p for p in params if p.name == "write")
        self.assertFalse(write_p.required)
        self.assertEqual(write_p.kind, "boolean")

    def test_mutually_exclusive_group_flattens(self) -> None:
        usage = "dungeon-export-custom-collision-json --out <path> [--room <room_id> | --rooms <hex,hex,...> | --all]"
        params = parse_usage(usage)
        names = {p.name for p in params}
        self.assertEqual(names, {"out", "room", "rooms", "all"})
        # All bracketed alternatives should be optional.
        for p in params:
            if p.name == "out":
                self.assertTrue(p.required)
            else:
                self.assertFalse(p.required)

    def test_hex_hint(self) -> None:
        params = parse_usage("mesen-memory-read --address <hex> [--length <n>]")
        addr = next(p for p in params if p.name == "address")
        length = next(p for p in params if p.name == "length")
        self.assertTrue(addr.required)
        self.assertEqual(addr.kind, "string")
        self.assertIn("hex", addr.description)
        self.assertFalse(length.required)
        self.assertEqual(length.kind, "integer")


class BuildToolTests(unittest.TestCase):
    def test_skips_grpc_emulator_family(self) -> None:
        cmd = {
            "name": "emulator-read-memory",
            "category": "emulator",
            "description": "read ram",
            "usage": "emulator-read-memory --address <hex>",
            "available_to_agent": True,
            "requires_rom": False,
            "requires_grpc": True,
            "examples": [],
        }
        self.assertIsNone(build_tool(cmd))

    def test_skips_gui_family(self) -> None:
        cmd = {
            "name": "gui-click",
            "category": "gui",
            "description": "",
            "usage": "gui-click --x <n>",
            "available_to_agent": True,
            "requires_rom": False,
            "requires_grpc": True,
            "examples": [],
        }
        self.assertIsNone(build_tool(cmd))

    def test_skips_when_not_agent_visible(self) -> None:
        cmd = {
            "name": "rom-patch",
            "category": "rom",
            "description": "",
            "usage": "rom-patch --rom <path>",
            "available_to_agent": False,
            "requires_rom": True,
            "requires_grpc": False,
            "examples": [],
        }
        self.assertIsNone(build_tool(cmd))

    def test_mesen_memory_read_translates_cleanly(self) -> None:
        cmd = {
            "name": "mesen-memory-read",
            "category": "mesen2",
            "description": "Read bytes via mesen2 socket",
            "usage": "mesen-memory-read --address <hex> [--length <n>] [--format <json|text>]",
            "available_to_agent": True,
            "requires_rom": False,
            "requires_grpc": False,
            "examples": ["z3ed mesen-memory-read --address=0x7E0000 --length=16"],
        }
        tool = build_tool(cmd)
        self.assertIsNotNone(tool)
        assert tool is not None
        self.assertEqual(tool.tool_name, "mesen_memory_read")
        self.assertEqual(tool.z3ed_name, "mesen-memory-read")
        self.assertFalse(tool.requires_grpc)
        # Schema shape
        schema = tool.openai_schema
        self.assertEqual(schema["type"], "function")
        self.assertEqual(schema["function"]["name"], "mesen_memory_read")
        params = schema["function"]["parameters"]
        self.assertEqual(params["type"], "object")
        self.assertIn("address", params["properties"])
        self.assertEqual(params["required"], ["address"])
        # Description folds in example + z3ed name
        desc = schema["function"]["description"]
        self.assertIn("mesen-memory-read", desc)

    def test_write_classification(self) -> None:
        write_cmd = {
            "name": "mesen-memory-write",
            "category": "mesen2",
            "description": "",
            "usage": "mesen-memory-write --address <hex> --data <hexbytes>",
            "available_to_agent": True,
            "requires_rom": False,
            "requires_grpc": False,
            "examples": [],
        }
        tool = build_tool(write_cmd)
        assert tool is not None
        self.assertTrue(tool.is_write())

        read_cmd = dict(write_cmd)
        read_cmd["name"] = "mesen-memory-read"
        read_cmd["usage"] = "mesen-memory-read --address <hex>"
        read_tool = build_tool(read_cmd)
        assert read_tool is not None
        self.assertFalse(read_tool.is_write())

    def test_duplicate_translated_tool_names_warn_and_skip_later_entry(self) -> None:
        raw = json.dumps(
            {
                "commands": [
                    {
                        "name": "room-info",
                        "category": "rom",
                        "description": "",
                        "usage": "room-info --room <id>",
                        "available_to_agent": True,
                        "requires_rom": False,
                        "requires_grpc": False,
                        "examples": [],
                    },
                    {
                        "name": "room_info",
                        "category": "rom",
                        "description": "",
                        "usage": "room_info --room <id>",
                        "available_to_agent": True,
                        "requires_rom": False,
                        "requires_grpc": False,
                        "examples": [],
                    },
                ]
            }
        )
        tools, warnings = load_schemas(raw)
        self.assertEqual([tool.tool_name for tool in tools], ["room_info"])
        self.assertTrue(
            any("duplicate translated tool name 'room_info'" in warning for warning in warnings),
            warnings,
        )


class LiveFixtureTests(unittest.TestCase):
    """End-to-end tests against the real z3ed --export-schemas payload."""

    FIXTURE = Path("/tmp/z3ed_schemas.json")

    def _load_raw(self) -> str:
        if not self.FIXTURE.exists():
            self.skipTest(f"fixture {self.FIXTURE} not present")
        return self.FIXTURE.read_text(encoding="utf-8")

    def test_repair_yields_valid_json(self) -> None:
        raw = self._load_raw()
        repaired = repair_z3ed_json(raw)
        payload = json.loads(repaired)
        self.assertIn("commands", payload)
        self.assertIsInstance(payload["commands"], list)
        self.assertGreater(len(payload["commands"]), 100)

    def test_load_schemas_produces_tools(self) -> None:
        raw = self._load_raw()
        tools, warnings = load_schemas(raw)
        # Expect repair warning
        self.assertTrue(any("repaired" in w for w in warnings), warnings)
        # Should produce >50 tools after skipping gRPC/gui
        self.assertGreater(len(tools), 50)
        # All mesen-* commands should translate
        mesen = [t for t in tools if t.z3ed_name.startswith("mesen-")]
        self.assertGreaterEqual(len(mesen), 10)
        # No emulator-* or gui-* should be present
        for t in tools:
            self.assertFalse(t.z3ed_name.startswith("emulator-"), t.z3ed_name)
            self.assertFalse(t.z3ed_name.startswith("gui-"), t.z3ed_name)
        # All tools must have unique names
        names = [t.tool_name for t in tools]
        self.assertEqual(len(names), len(set(names)))
        # All tool_names should pass OpenAI's regex (^[a-zA-Z0-9_-]+$)
        import re as _re
        for name in names:
            self.assertTrue(_re.match(r"^[a-zA-Z0-9_-]+$", name), name)


if __name__ == "__main__":
    unittest.main()
