"""Tests for the shared ASM workflow contracts."""

from __future__ import annotations

import unittest

from core.asm_workflow import AsmPatchInput, AsmPatchResult, AssertionOutcome


class AsmPatchInputTests(unittest.TestCase):
    def test_from_tool_arguments_normalizes_common_fields(self) -> None:
        payload = AsmPatchInput.from_tool_arguments({
            "patch_path": "patch.asm",
            "scenario": "sanctuary",
            "frames": "180",
            "breakpoints": "0x008000,$028000",
            "assertions": ["LinkHealth > 0"],
            "capture_screenshot": "true",
            "restore_after": "false",
            "preserve_artifacts": 1,
            "backend": "mesen2",
            "include": "src,include",
            "define": ["FEATURE_X=1"],
            "emit_targets": ["diagnostics", "sourcemap"],
        })

        self.assertEqual(payload.patch_path, "patch.asm")
        self.assertEqual(payload.scenario, "sanctuary")
        self.assertEqual(payload.frames, 180)
        self.assertEqual(payload.breakpoints, ["0x008000", "$028000"])
        self.assertEqual(payload.assertions, ["LinkHealth > 0"])
        self.assertTrue(payload.capture_screenshot)
        self.assertFalse(payload.restore_after)
        self.assertTrue(payload.preserve_artifacts)
        self.assertEqual(payload.backend, "mesen2")
        self.assertEqual(payload.include, ["src", "include"])
        self.assertEqual(payload.define, ["FEATURE_X=1"])
        self.assertEqual(payload.emit_targets, ["diagnostics", "sourcemap"])


class AsmPatchResultTests(unittest.TestCase):
    def test_to_dict_emits_canonical_top_level_keys(self) -> None:
        result = AsmPatchResult(
            ok=True,
            lint_ok=True,
            assemble_ok=True,
            emulator_ok=True,
            scenario_loaded=True,
            cpu={"pc": 0x8000},
            memory={"LinkHealth": "03"},
            breakpoint_hits=[{"hit": True}],
            screenshot_path="/tmp/x.png",
            failure_stage=None,
            warnings=["warn"],
        )
        result.assertions.append(AssertionOutcome(expr="LinkHealth > 0", ok=True, detail="passed"))
        result.diagnostics["lint"] = {"lint.json": {"ok": True}}
        result.add_artifact("temp_rom", "/tmp/rom.sfc", preserved=False, exists=False)

        payload = result.to_dict()

        self.assertEqual(
            list(payload.keys()),
            [
                "ok",
                "lint_ok",
                "assemble_ok",
                "emulator_ok",
                "scenario_loaded",
                "assertions",
                "diagnostics",
                "cpu",
                "memory",
                "breakpoint_hits",
                "screenshot_path",
                "artifacts",
                "failure_stage",
                "warnings",
            ],
        )
        self.assertEqual(payload["assertions"][0]["expr"], "LinkHealth > 0")
        self.assertEqual(payload["artifacts"][0]["kind"], "temp_rom")


if __name__ == "__main__":
    unittest.main()
