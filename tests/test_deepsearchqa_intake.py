import csv
import importlib.util
import json
import sys
from pathlib import Path


def load_script(name: str):
    script = Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, script)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_deepsearch_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["problem", "problem_category", "answer", "answer_type"],
        )
        writer.writeheader()
        writer.writerow({
            "problem": "Which file contains the SNES DMA register docs?",
            "problem_category": "Technology",
            "answer": "Docs/Technical/Registers.md",
            "answer_type": "Single Answer",
        })
        writer.writerow({
            "problem": "Name the Oracle files that mention MagicBeanProg.",
            "problem_category": "Technology",
            "answer": "Core/sram.asm, Sprites/NPCs/bean_vendor.asm",
            "answer_type": "Set Answer",
        })


def test_prepare_deepsearchqa_eval_writes_prompt_pack_and_answers(tmp_path: Path) -> None:
    prepare = load_script("prepare_deepsearchqa_eval")
    csv_path = tmp_path / "DSQA-full.csv"
    prompt_pack = tmp_path / "google_deepsearchqa_eval_v1.jsonl"
    answers = tmp_path / "google_deepsearchqa_eval_answers_v1.jsonl"
    write_deepsearch_csv(csv_path)

    summary = prepare.prepare_eval(
        csv_path=csv_path,
        out_path=prompt_pack,
        answers_out=answers,
        id_prefix="google_deepsearchqa_eval_v1",
        agent_mode="no-web",
    )

    rows = [json.loads(line) for line in prompt_pack.read_text(encoding="utf-8").splitlines()]
    answer_rows = [json.loads(line) for line in answers.read_text(encoding="utf-8").splitlines()]

    assert summary["rows"] == 2
    assert rows[0]["id"] == "google_deepsearchqa_eval_v1_0001_technology"
    assert rows[0]["messages"][0]["role"] == "system"
    assert "without browser or search tools" in rows[0]["messages"][0]["content"]
    assert rows[0]["messages"][1]["content"] == "Which file contains the SNES DMA register docs?"
    assert "expected" not in rows[0]
    assert rows[0]["_metadata"]["license"] == "apache-2.0"
    assert rows[0]["_metadata"]["answer_type"] == "Single Answer"
    assert "Docs/Technical/Registers.md" not in rows[0]["messages"][1]["content"]
    assert answer_rows[0]["answer"] == "Docs/Technical/Registers.md"
    assert answer_rows[1]["answer_type"] == "Set Answer"
    assert answer_rows[1]["answer"] == "Core/sram.asm, Sprites/NPCs/bean_vendor.asm"


def test_score_deepsearchqa_eval_handles_single_and_set_answers(tmp_path: Path) -> None:
    prepare = load_script("prepare_deepsearchqa_eval")
    scorer = load_script("score_deepsearchqa_eval")
    csv_path = tmp_path / "DSQA-full.csv"
    prompt_pack = tmp_path / "pack.jsonl"
    answers = tmp_path / "answers.jsonl"
    output = tmp_path / "output.jsonl"
    details = tmp_path / "details.jsonl"
    write_deepsearch_csv(csv_path)
    prepare.prepare_eval(
        csv_path=csv_path,
        out_path=prompt_pack,
        answers_out=answers,
        id_prefix="google_deepsearchqa_eval_v1",
    )
    output.write_text(
        "\n".join([
            json.dumps({
                "id": "google_deepsearchqa_eval_v1_0001_technology",
                "completion": "The register documentation lives in Docs/Technical/Registers.md.",
            }),
            json.dumps({
                "id": "google_deepsearchqa_eval_v1_0002_technology",
                "completion": "Core/sram.asm and Sprites/NPCs/bean_vendor.asm both mention it.",
            }),
        ])
        + "\n",
        encoding="utf-8",
    )

    summary = scorer.score_eval(eval_output=output, answers=answers, details_out=details)
    scored_rows = [json.loads(line) for line in details.read_text(encoding="utf-8").splitlines()]

    assert summary["total"] == 2
    assert summary["passed"] == 2
    assert summary["scoring"] == "rough_contains_v1"
    assert scored_rows[1]["hits"] == 2
    assert scored_rows[1]["total"] == 2
