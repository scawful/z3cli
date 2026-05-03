import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_z3cli_oracle_promotion_eval.py"
SPEC = importlib.util.spec_from_file_location("run_z3cli_oracle_promotion_eval", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
promotion_eval = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = promotion_eval
SPEC.loader.exec_module(promotion_eval)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


class Z3cliOraclePromotionEvalTests(unittest.TestCase):
    def test_score_response_checks_tool_args_and_final_text(self) -> None:
        row = {
            "id": "workspace_gate",
            "messages": [{"role": "user", "content": "Read docs/cli-current-state.md before answering."}],
            "expect": {
                "tool_required": True,
                "expected_tools_any": ["workspace_read"],
                "expected_args_contain": ["docs/cli-current-state.md"],
                "require_final_contains_any": ["z3cli"],
                "forbid_final_patterns": ["\\bi can't access\\b"],
            },
        }
        observed = promotion_eval.ObservedResponse(
            id="workspace_gate",
            prompt="Read docs/cli-current-state.md before answering.",
            tool_calls=[
                {
                    "name": "workspace_read",
                    "arguments": {"path": "docs/cli-current-state.md"},
                    "server": "workspace",
                }
            ],
            final_text="z3cli currently routes Oracle work through the local runtime.",
            end_status="success",
        )

        scored = promotion_eval.score_response(row, observed)

        self.assertTrue(scored["passed"])
        self.assertEqual(scored["tool_calls_observed"], ["workspace_read"])

    def test_score_response_treats_mdmaen_address_as_argument_alias(self) -> None:
        row = {
            "id": "dma_refs",
            "messages": [{"role": "user", "content": "Use grep_disasm for MDMAEN."}],
            "expect": {
                "tool_required": True,
                "expected_tools_any": ["grep_disasm"],
                "expected_args_contain": ["MDMAEN"],
            },
        }
        observed = promotion_eval.ObservedResponse(
            id="dma_refs",
            prompt="Use grep_disasm for MDMAEN.",
            tool_calls=[
                {
                    "name": "grep_disasm",
                    "arguments": {"query": r"^\s*LD\w*\s+\$420B"},
                    "server": "oracle",
                }
            ],
            final_text="MDMAEN maps to $420B.",
            end_status="success",
        )

        scored = promotion_eval.score_response(row, observed)

        self.assertTrue(scored["passed"])

    def test_score_response_checks_tool_result_patterns_and_asar_compile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_asar = Path(tmp) / "asar"
            fake_asar.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_asar.chmod(0o755)
            old_asar = os.environ.get("Z3CLI_ASAR_PATH")
            os.environ["Z3CLI_ASAR_PATH"] = str(fake_asar)
            try:
                row = {
                    "id": "asar_gate",
                    "messages": [{"role": "user", "content": "Return assembler-safe ASM only."}],
                    "expect": {
                        "compile_final_asar": True,
                        "require_final_contains_all": ["STA.l", "$7E0200"],
                        "require_tool_result_patterns": ["PC", "P"],
                        "forbid_tool_result_patterns": ["Mesen2 unavailable"],
                    },
                }
                observed = promotion_eval.ObservedResponse(
                    id="asar_gate",
                    prompt="Return assembler-safe ASM only.",
                    tool_results=[{"name": "cpu_state", "content": "PC=$0088EC P=34"}],
                    final_text="ClearOracleScratch:\n  LDA #$00\n  STA.l $7E0200\n  RTL\n",
                    end_status="success",
                )

                scored = promotion_eval.score_response(row, observed)
            finally:
                if old_asar is None:
                    os.environ.pop("Z3CLI_ASAR_PATH", None)
                else:
                    os.environ["Z3CLI_ASAR_PATH"] = old_asar

        self.assertTrue(scored["passed"])
        self.assertIn("compile_final_asar", [check["name"] for check in scored["checks"]])

    def test_score_session_excludes_oracle_prefetch_records_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp) / "session.jsonl"
            rows = [
                {
                    "type": "engine_msg",
                    "model": "oracle-qwen35-9b",
                    "msg": {
                        "role": "user",
                        "content": "Read docs/cli-current-state.md before answering.",
                        "display_content": "Read docs/cli-current-state.md before answering.",
                        "turn_id": "turn-1",
                        "request_id": "req-1",
                    },
                },
                {
                    "type": "engine_msg",
                    "model": "oracle-qwen35-9b",
                    "msg": {
                        "role": "assistant",
                        "turn_id": "turn-1",
                        "request_id": "req-1",
                        "tool_calls": [
                            {
                                "name": "register_doc",
                                "arguments": "{\"query\":\"$420B\"}",
                                "tool_call_id": "oracle-prefetch-register-1",
                            }
                        ],
                    },
                },
                {
                    "type": "engine_msg",
                    "model": "oracle-qwen35-9b",
                    "msg": {
                        "role": "tool",
                        "name": "register_doc",
                        "content": "### MDMAEN ($420B)",
                        "turn_id": "turn-1",
                        "request_id": "req-1",
                        "tool_call_id": "oracle-prefetch-register-1",
                    },
                },
                {
                    "type": "engine_msg",
                    "model": "oracle-qwen35-9b",
                    "msg": {
                        "role": "assistant",
                        "content": "",
                        "turn_id": "turn-1",
                        "request_id": "req-1",
                        "tool_calls": [
                            {
                                "name": "workspace_read",
                                "arguments": "{\"path\":\"docs/cli-current-state.md\"}",
                                "server": "workspace",
                                "tool_call_id": "call-1",
                            }
                        ],
                    },
                },
                {
                    "type": "engine_msg",
                    "model": "oracle-qwen35-9b",
                    "msg": {
                        "role": "tool",
                        "name": "workspace_read",
                        "content": "z3cli current state",
                        "turn_id": "turn-1",
                        "request_id": "req-1",
                        "tool_call_id": "call-1",
                    },
                },
                {
                    "type": "engine_msg",
                    "model": "oracle-qwen35-9b",
                    "msg": {
                        "role": "assistant",
                        "content": "z3cli current state is grounded by the file.",
                        "turn_id": "turn-1",
                        "request_id": "req-1",
                    },
                },
            ]
            _write_jsonl(session, rows)

            pack = [
                {
                    "id": "workspace_gate",
                    "messages": [
                        {"role": "user", "content": "Read docs/cli-current-state.md before answering."}
                    ],
                    "expect": {
                        "tool_required": True,
                        "expected_tools_any": ["workspace_read"],
                        "forbidden_tools": ["register_doc"],
                        "expected_args_contain": ["docs/cli-current-state.md"],
                    },
                }
            ]

            scored = promotion_eval.score_session_file(
                rows=pack,
                session_path=session,
                model="oracle-qwen35-9b",
                include_prefetch=False,
            )

        self.assertTrue(scored[0]["passed"])
        self.assertEqual(scored[0]["tool_calls_observed"], ["workspace_read"])
        self.assertEqual(scored[0]["observed"]["tool_results"][0]["name"], "workspace_read")

    def test_missing_session_prompt_fails_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp) / "session.jsonl"
            _write_jsonl(session, [])
            pack = [
                {
                    "id": "missing",
                    "messages": [{"role": "user", "content": "Use cpu_state first."}],
                    "expect": {"tool_required": True, "expected_tools_any": ["cpu_state"]},
                }
            ]

            scored = promotion_eval.score_session_file(rows=pack, session_path=session)

        self.assertFalse(scored[0]["passed"])
        self.assertEqual(scored[0]["end_status"], "missing")
        self.assertIn("prompt not found", scored[0]["observed"]["errors"][0])


if __name__ == "__main__":
    unittest.main()
