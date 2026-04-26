import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "eval_openai_prompt_pack.py"
SPEC = importlib.util.spec_from_file_location("eval_openai_prompt_pack", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
eval_runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(eval_runner)


class EvalOpenAIPromptPackTests(unittest.TestCase):
    def test_load_prompt_pack_supports_messages_and_system_user_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pack.jsonl"
            rows = [
                {
                    "id": "with_messages",
                    "messages": [
                        {"role": "system", "content": "sys"},
                        {"role": "user", "content": "user"},
                    ],
                },
                {"id": "legacy", "system": "sys2", "user": "user2"},
            ]
            path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

            loaded = eval_runner.load_prompt_pack(path)

        self.assertEqual([row["id"] for row in loaded], ["with_messages", "legacy"])
        self.assertEqual(loaded[1]["_messages"], [
            {"role": "system", "content": "sys2"},
            {"role": "user", "content": "user2"},
        ])

    def test_run_eval_writes_scoring_compatible_jsonl(self) -> None:
        calls = []

        def fake_post(url, payload, timeout):  # type: ignore[no-untyped-def]
            calls.append((url, payload, timeout))
            return {"choices": [{"message": {"content": "```asm\nrtl\n```"}}]}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pack = root / "pack.jsonl"
            out = root / "out.jsonl"
            pack.write_text(
                json.dumps({
                    "id": "case_1",
                    "messages": [{"role": "user", "content": "Return ASM."}],
                    "_metadata": {"tags": ["asm"], "severity": "high"},
                })
                + "\n",
                encoding="utf-8",
            )

            count = eval_runner.run_eval(
                prompt_pack=pack,
                out_path=out,
                api_base="http://127.0.0.1:18081/v1",
                model="oracle-coder-pro",
                max_tokens=128,
                temperature=0.0,
                top_p=0.9,
                post_fn=fake_post,
            )

            records = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(count, 1)
        self.assertEqual(calls[0][0], "http://127.0.0.1:18081/v1/chat/completions")
        self.assertEqual(calls[0][1]["model"], "oracle-coder-pro")
        self.assertEqual(records[0]["id"], "case_1")
        self.assertEqual(records[0]["completion"], "```asm\nrtl\n```")
        self.assertEqual(records[0]["tags"], ["asm"])
        self.assertEqual(records[0]["meta"]["model"], "oracle-coder-pro")

    def test_extra_body_is_merged_into_payload(self) -> None:
        payload = eval_runner.build_payload(
            model="oracle-reasoner-27b",
            messages=[{"role": "user", "content": "x"}],
            max_tokens=64,
            temperature=0.7,
            top_p=0.8,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )

        self.assertEqual(payload["chat_template_kwargs"], {"enable_thinking": False})


if __name__ == "__main__":
    unittest.main()
