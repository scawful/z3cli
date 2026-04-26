import csv
import importlib.util
import json
import sys
from pathlib import Path


def load_prepare_module():
    script = Path(__file__).resolve().parents[1] / "scripts" / "prepare_google_eval_datasets.py"
    spec = importlib.util.spec_from_file_location("prepare_google_eval_datasets", script)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_prepare_facts_grounding_writes_context_prompt_without_answers(tmp_path: Path) -> None:
    prepare = load_prepare_module()
    source = tmp_path / "examples.csv"
    out = tmp_path / "facts.jsonl"
    with source.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["system_instruction", "user_request", "context_document", "full_prompt"],
        )
        writer.writeheader()
        writer.writerow({
            "system_instruction": "Only use context.",
            "user_request": "What does $420B do?",
            "context_document": "$420B starts DMA on selected channels.",
            "full_prompt": "ignored",
        })

    summary = prepare.prepare_facts_grounding(source, out_path=out, answers_out=None)
    rows = read_jsonl(out)

    assert summary["rows"] == 1
    assert rows[0]["id"] == "google_facts_grounding_eval_v1_0001"
    assert rows[0]["messages"][0]["content"] == "Only use context."
    assert "Context:\n$420B starts DMA" in rows[0]["messages"][1]["content"]
    assert "expected" not in rows[0]
    assert rows[0]["_metadata"]["license"] == "cc-by-4.0"
    assert rows[0]["_metadata"]["context_chars"] > 0


def test_prepare_frames_writes_prompt_pack_and_answer_companion(tmp_path: Path) -> None:
    prepare = load_prepare_module()
    source = tmp_path / "test.tsv"
    out = tmp_path / "frames.jsonl"
    answers = tmp_path / "frames_answers.jsonl"
    with source.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "Prompt",
                "Answer",
                "wikipedia_link_1",
                "wikipedia_link_2",
                "reasoning_types",
                "wiki_links",
            ],
            delimiter="\t",
        )
        writer.writeheader()
        writer.writerow({
            "Prompt": "Which file should be inspected first?",
            "Answer": "src/app/runtime.py",
            "wikipedia_link_1": "https://en.wikipedia.org/wiki/Test",
            "wikipedia_link_2": "",
            "reasoning_types": "Multiple constraints | Temporal reasoning",
            "wiki_links": "['https://en.wikipedia.org/wiki/Test']",
        })

    summary = prepare.prepare_frames(source, out_path=out, answers_out=answers)
    rows = read_jsonl(out)
    answer_rows = read_jsonl(answers)

    assert summary["rows"] == 1
    assert rows[0]["messages"][1]["content"] == "Which file should be inspected first?"
    assert "expected" not in rows[0]
    assert rows[0]["_metadata"]["wikipedia_links"] == ["https://en.wikipedia.org/wiki/Test"]
    assert answer_rows[0]["answer"] == "src/app/runtime.py"
    assert answer_rows[0]["license"] == "apache-2.0"


def test_prepare_ifeval_writes_rule_companion(tmp_path: Path) -> None:
    prepare = load_prepare_module()
    source = tmp_path / "ifeval_input_data.jsonl"
    out = tmp_path / "ifeval.jsonl"
    rules = tmp_path / "rules.jsonl"
    source.write_text(
        json.dumps({
            "key": 1000,
            "prompt": "Write exactly two bullet points.",
            "instruction_id_list": ["detectable_format:number_bullet_lists"],
            "kwargs": [{"num_bullets": 2}],
        })
        + "\n",
        encoding="utf-8",
    )

    summary = prepare.prepare_ifeval(source, out_path=out, answers_out=rules)
    rows = read_jsonl(out)
    rule_rows = read_jsonl(rules)

    assert summary["rows"] == 1
    assert rows[0]["id"] == "google_ifeval_eval_v1_1000"
    assert rows[0]["messages"][1]["content"] == "Write exactly two bullet points."
    assert rows[0]["_metadata"]["instruction_id_list"] == ["detectable_format:number_bullet_lists"]
    assert rule_rows[0]["kwargs"] == [{"num_bullets": 2}]


def test_prepare_simpleqa_verified_writes_answer_companion_without_leakage(tmp_path: Path) -> None:
    prepare = load_prepare_module()
    source = tmp_path / "simpleqa_verified.csv"
    out = tmp_path / "simpleqa.jsonl"
    answers = tmp_path / "simpleqa_answers.jsonl"
    with source.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "original_index",
                "problem",
                "answer",
                "topic",
                "answer_type",
                "multi_step",
                "requires_reasoning",
                "urls",
            ],
        )
        writer.writeheader()
        writer.writerow({
            "original_index": "5",
            "problem": "Who discovered the bug?",
            "answer": "Nayru",
            "topic": "Technology",
            "answer_type": "Person",
            "multi_step": "True",
            "requires_reasoning": "False",
            "urls": "https://example.com/a,https://example.com/b",
        })

    summary = prepare.prepare_simpleqa_verified(source, out_path=out, answers_out=answers)
    rows = read_jsonl(out)
    answer_rows = read_jsonl(answers)

    assert summary["rows"] == 1
    assert rows[0]["id"] == "google_simpleqa_verified_eval_v1_0001_technology"
    assert rows[0]["messages"][1]["content"] == "Who discovered the bug?"
    assert "expected" not in rows[0]
    assert "Nayru" not in json.dumps(rows[0])
    assert rows[0]["_metadata"]["multi_step"] is True
    assert answer_rows[0]["answer"] == "Nayru"
    assert answer_rows[0]["license"] == "mit"
