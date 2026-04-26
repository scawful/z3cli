import importlib.util
import json
import sys
from pathlib import Path


def load_fix_module():
    script = Path(__file__).resolve().parents[1] / "scripts" / "fix_oracle_training_duplicates.py"
    spec = importlib.util.spec_from_file_location("fix_oracle_training_duplicates", script)
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


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def row(sample_id: str, repeat_index: int, content: str = "answer") -> dict:
    return {
        "id": sample_id,
        "messages": [
            {"role": "user", "content": "Prompt"},
            {"role": "assistant", "content": content},
        ],
        "_metadata": {
            "sample_id": sample_id,
            "repeat_index": repeat_index,
            "section": "repo_retrieval",
        },
    }


def test_fix_dataset_cap_mode_reduces_exact_duplicates_and_preserves_weight_metadata(tmp_path: Path) -> None:
    fix_mod = load_fix_module()
    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    write_jsonl(input_dir / "train.jsonl", [row("same", 0), row("same", 1), row("same", 2), row("other", 0, "other")])
    write_jsonl(input_dir / "val.jsonl", [row("val", 0, "val")])
    write_jsonl(input_dir / "test.jsonl", [])

    report = fix_mod.fix_dataset(input_dir, output_dir, mode="cap", max_repeat=2, seed=1)
    train = read_jsonl(output_dir / "train.jsonl")

    assert report["split_reports"]["train"]["input_rows"] == 4
    assert report["split_reports"]["train"]["output_rows"] == 3
    weights = sorted(item["_metadata"]["duplicate_fix_original_weight"] for item in train)
    assert weights == [1, 3, 3]
    assert all("repeat_index" not in item["_metadata"] for item in train)
    capped = [item for item in train if item["_metadata"]["duplicate_fix_original_weight"] == 3]
    assert sorted(item["_metadata"]["duplicate_fix_repeat_index"] for item in capped) == [0, 1]


def test_fix_dataset_collapse_mode_emits_one_row_per_payload(tmp_path: Path) -> None:
    fix_mod = load_fix_module()
    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    write_jsonl(input_dir / "train.jsonl", [row("same", 0), row("same", 1), row("same", 2)])
    write_jsonl(input_dir / "val.jsonl", [])
    write_jsonl(input_dir / "test.jsonl", [])

    report = fix_mod.fix_dataset(input_dir, output_dir, mode="collapse", max_repeat=3, seed=1)
    train = read_jsonl(output_dir / "train.jsonl")

    assert report["split_reports"]["train"]["output_rows"] == 1
    assert train[0]["_metadata"]["duplicate_fix_original_weight"] == 3
    assert train[0]["_metadata"]["duplicate_fix_effective_weight"] == 1
    assert train[0]["_metadata"]["duplicate_fix_mode"] == "collapse"
