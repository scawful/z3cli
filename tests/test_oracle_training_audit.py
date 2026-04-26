import importlib.util
import json
import sys
from pathlib import Path


def load_audit_module():
    script = Path(__file__).resolve().parents[1] / "scripts" / "audit_oracle_training_data.py"
    spec = importlib.util.spec_from_file_location("audit_oracle_training_data", script)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_audit_dataset_counts_duplicates_tools_buckets_and_eval_overlap(tmp_path: Path) -> None:
    audit_mod = load_audit_module()
    training_root = tmp_path / "training"
    dataset = training_root / "datasets" / "oracle_demo"
    evals = training_root / "evals"
    row = {
        "id": "repair_1",
        "messages": [
            {"role": "system", "content": "You are Oracle."},
            {"role": "user", "content": "Why does STZ $7E2000,X fail?"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": "register_doc", "arguments": "{}"}}],
            },
            {"role": "tool", "content": "No long indexed STZ mode."},
            {"role": "assistant", "content": "Use DB=$7E plus STZ $2000,X, or LDA #$00 : STA $7E2000,X."},
        ],
        "_metadata": {
            "capability_bucket": "abi_and_width_contracts",
            "corrective_v6_role": "failure_target",
            "corrective_v6_style": "direct",
        },
    }
    write_jsonl(dataset / "train.jsonl", [row, row])
    write_jsonl(dataset / "val.jsonl", [{
        **row,
        "id": "repair_val",
        "messages": [
            {"role": "user", "content": "Why does STZ $7E2000,X fail?"},
            {"role": "assistant", "content": "Use DB=$7E plus STZ $2000,X."},
        ],
    }])
    write_jsonl(dataset / "test.jsonl", [])
    write_jsonl(evals / "oracle_demo_eval.jsonl", [{
        "id": "eval_1",
        "messages": [{"role": "user", "content": "Why does STZ $7E2000,X fail?"}],
        "response": "Use DB=$7E plus STZ $2000,X, or LDA #$00 : STA $7E2000,X.",
    }])

    eval_index = audit_mod.load_eval_index(training_root, ["evals/oracle*.jsonl"])
    audit = audit_mod.audit_dataset(training_root, "oracle_demo", eval_index)

    assert audit.split_counts["train"] == 2
    assert audit.content_duplicate_rows == 1
    assert audit.prompt_duplicate_rows == 2
    assert audit.tool_surfaces["tool-role-transcript"] == 2
    assert audit.bucket_counts["abi_and_width_contracts"] == 3
    assert audit.split_prompt_overlaps["train/val"] == 1
    assert sum(audit.eval_prompt_overlaps.values()) == 3
    assert sum(audit.eval_answer_overlaps.values()) == 2
    report = audit_mod.render_markdown(training_root, [audit], eval_index)
    assert "oracle_demo" in report
    assert "abi_and_width_contracts" in report


def test_audit_dataset_hashes_dpo_prompt_chosen_and_rejected_messages(tmp_path: Path) -> None:
    audit_mod = load_audit_module()
    training_root = tmp_path / "training"
    dataset = training_root / "datasets" / "oracle_dpo"
    first = {
        "prompt_messages": [{"role": "user", "content": "Use evidence A. What follows?"}],
        "chosen_messages": [{"role": "assistant", "content": "Grounded answer A."}],
        "rejected_messages": [{"role": "assistant", "content": "Ungrounded guess."}],
        "_metadata": {"section": "lost_middle"},
    }
    second = {
        "prompt_messages": [{"role": "user", "content": "Use evidence B. What follows?"}],
        "chosen_messages": [{"role": "assistant", "content": "Grounded answer B."}],
        "rejected_messages": [{"role": "assistant", "content": "Ungrounded guess."}],
        "_metadata": {"section": "lost_middle"},
    }
    write_jsonl(dataset / "train.jsonl", [first, second])
    write_jsonl(dataset / "val.jsonl", [])
    write_jsonl(dataset / "test.jsonl", [])

    eval_index = audit_mod.load_eval_index(training_root, ["evals/oracle*.jsonl"])
    audit = audit_mod.audit_dataset(training_root, "oracle_dpo", eval_index)

    assert audit.unique_content == 2
    assert audit.unique_prompts == 2
    assert audit.unique_answers == 2
    assert audit.bucket_counts["lost_middle"] == 2
