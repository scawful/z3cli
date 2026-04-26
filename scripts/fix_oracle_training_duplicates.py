#!/usr/bin/env python3
"""Create capped or collapsed Oracle dataset variants from duplicate-expanded JSONL.

The current Zelda trainers consume plain JSONL and do not consistently honor a
per-row sample weight. Many Oracle builders therefore repeat rows physically to
weight known failure buckets. This tool preserves that intent in metadata while
producing safer variants:

- ``cap``: emit up to N copies per exact row payload, compatible with existing
  JSONL loaders while reducing overfit pressure.
- ``collapse``: emit one row per exact row payload with the original duplicate
  count stored as metadata for future weight-aware loaders.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any


SPLITS = ("train", "val", "test")
WEIGHT_META_KEY = "duplicate_fix_original_weight"
EFFECTIVE_WEIGHT_META_KEY = "duplicate_fix_effective_weight"
REPEAT_META_KEY = "duplicate_fix_repeat_index"
SOURCE_IDS_META_KEY = "duplicate_fix_source_ids"
SOURCE_REPEAT_KEYS = (
    "repeat_index",
    "oracle_14b_v7_repeat_index",
    "oracle_14b_v6_repeat_index",
    "oracle_14b_v5_repeat_index",
    "oracle_14b_v4_repeat_index",
    "oracle_14b_v3_repeat_index",
    "oracle_14b_repeat_index",
    "oracle_slot_repeat_index",
    "corrective3_repeat_index",
    "skill_coverage_repeat_index",
)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_no}: expected JSON object")
            rows.append(row)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=False) + "\n")


def canonical_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "messages": row.get("messages"),
        "prompt_messages": row.get("prompt_messages"),
        "chosen_messages": row.get("chosen_messages"),
        "rejected_messages": row.get("rejected_messages"),
        "prompt": row.get("prompt"),
        "response": row.get("response"),
        "chosen": row.get("chosen"),
        "rejected": row.get("rejected"),
    }


def payload_hash(row: dict[str, Any]) -> str:
    payload = canonical_payload(row)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def row_id(row: dict[str, Any], fallback: str) -> str:
    metadata = row.get("_metadata") if isinstance(row.get("_metadata"), dict) else {}
    return str(
        row.get("id")
        or metadata.get("sample_id")
        or metadata.get("pair_id")
        or metadata.get("from_eval_id")
        or fallback
    )


def annotate_row(
    row: dict[str, Any],
    *,
    original_weight: int,
    effective_weight: int,
    repeat_index: int,
    source_ids: list[str],
    output_dataset: str,
    mode: str,
) -> dict[str, Any]:
    cloned = copy.deepcopy(row)
    metadata = dict(cloned.get("_metadata", {}) or {})
    for key in SOURCE_REPEAT_KEYS:
        metadata.pop(key, None)
    metadata["duplicate_fix_dataset"] = output_dataset
    metadata["duplicate_fix_mode"] = mode
    metadata[WEIGHT_META_KEY] = original_weight
    metadata[EFFECTIVE_WEIGHT_META_KEY] = effective_weight
    metadata[REPEAT_META_KEY] = repeat_index
    metadata[SOURCE_IDS_META_KEY] = source_ids[:20]
    cloned["_metadata"] = metadata
    return cloned


def grouped_rows(rows: list[dict[str, Any]], split: str) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index, row in enumerate(rows, start=1):
        groups[payload_hash(row)].append(row)
    return groups


def fixed_split_rows(
    rows: list[dict[str, Any]],
    *,
    split: str,
    output_dataset: str,
    mode: str,
    max_repeat: int,
    rng: random.Random,
    excluded_hashes: set[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    groups = grouped_rows(rows, split)
    excluded_hashes = excluded_hashes or set()
    output: list[dict[str, Any]] = []
    group_sizes = Counter(len(group) for group in groups.values())
    reduced_rows = 0
    protected_holdout_rows = 0
    for group_index, (group_hash, group) in enumerate(sorted(groups.items()), start=1):
        if group_hash in excluded_hashes:
            protected_holdout_rows += len(group)
            reduced_rows += len(group)
            continue
        original_weight = len(group)
        effective_weight = 1 if mode == "collapse" else min(original_weight, max_repeat)
        reduced_rows += original_weight - effective_weight
        source_ids = [row_id(row, f"{split}:{group_index}:{idx}") for idx, row in enumerate(group, start=1)]
        base_row = group[0]
        for repeat_index in range(effective_weight):
            output.append(
                annotate_row(
                    base_row,
                    original_weight=original_weight,
                    effective_weight=effective_weight,
                    repeat_index=repeat_index,
                    source_ids=source_ids,
                    output_dataset=output_dataset,
                    mode=mode,
                )
            )
    rng.shuffle(output)
    return output, {
        "input_rows": len(rows),
        "unique_payloads": len(groups),
        "output_rows": len(output),
        "reduced_rows": reduced_rows,
        "protected_holdout_rows": protected_holdout_rows,
        "duplicate_rows_before": len(rows) - len(groups),
        "duplicate_rows_after": len(output) - len(groups),
        "group_size_histogram": dict(sorted(group_sizes.items())),
    }


def exact_overlap_count(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> int:
    left_hashes = {payload_hash(row) for row in left}
    right_hashes = {payload_hash(row) for row in right}
    return len(left_hashes & right_hashes)


def load_metadata(input_dir: Path) -> dict[str, Any]:
    path = input_dir / "metadata.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"unparsed_metadata_path": str(path)}
    return data if isinstance(data, dict) else {}


def fix_dataset(
    input_dir: Path,
    output_dir: Path,
    *,
    mode: str,
    max_repeat: int,
    seed: int,
    protect_holdouts: bool = True,
    generated_date: str | None = None,
) -> dict[str, Any]:
    if mode not in {"cap", "collapse"}:
        raise ValueError(f"Unsupported mode: {mode}")
    if max_repeat < 1:
        raise ValueError("--max-repeat must be at least 1")
    rng = random.Random(seed)
    input_rows = {split: load_jsonl(input_dir / f"{split}.jsonl") for split in SPLITS}
    holdout_hashes = (
        {payload_hash(row) for row in input_rows["val"] + input_rows["test"]}
        if protect_holdouts
        else set()
    )
    output_dataset = output_dir.name
    output_rows: dict[str, list[dict[str, Any]]] = {}
    split_reports: dict[str, dict[str, Any]] = {}
    for split in SPLITS:
        fixed_rows, report = fixed_split_rows(
            input_rows[split],
            split=split,
            output_dataset=output_dataset,
            mode=mode,
            max_repeat=max_repeat,
            rng=rng,
            excluded_hashes=holdout_hashes if split == "train" else set(),
        )
        output_rows[split] = fixed_rows
        split_reports[split] = report

    output_dir.mkdir(parents=True, exist_ok=True)
    for split in SPLITS:
        write_jsonl(output_dir / f"{split}.jsonl", output_rows[split])

    source_metadata = load_metadata(input_dir)
    overlap_before = {
        "train/val": exact_overlap_count(input_rows["train"], input_rows["val"]),
        "train/test": exact_overlap_count(input_rows["train"], input_rows["test"]),
        "val/test": exact_overlap_count(input_rows["val"], input_rows["test"]),
    }
    overlap_after = {
        "train/val": exact_overlap_count(output_rows["train"], output_rows["val"]),
        "train/test": exact_overlap_count(output_rows["train"], output_rows["test"]),
        "val/test": exact_overlap_count(output_rows["val"], output_rows["test"]),
    }
    metadata: dict[str, Any] = {
        "dataset": str(output_dir),
        "source_dataset": str(input_dir),
        "generated": generated_date or date.today().isoformat(),
        "mode": mode,
        "max_repeat": max_repeat if mode == "cap" else 1,
        "seed": seed,
        "protect_holdouts": protect_holdouts,
        "split_reports": split_reports,
        "exact_split_overlap_before": overlap_before,
        "exact_split_overlap_after": overlap_after,
        "source_metadata": source_metadata,
        "notes": [
            "This is a duplicate-normalized derivative. It does not overwrite the source dataset.",
            "Rows keep duplicate_fix_original_weight metadata so the original training emphasis is recoverable.",
            "Use cap mode for current plain-JSONL trainers; use collapse mode only when the loader honors per-row weights.",
        ],
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return metadata


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create duplicate-capped or collapsed Oracle dataset variants.")
    parser.add_argument("input_dir", type=Path, help="Input dataset directory with train/val/test JSONL files.")
    parser.add_argument("output_dir", type=Path, help="Output dataset directory.")
    parser.add_argument("--mode", choices=("cap", "collapse"), default="cap")
    parser.add_argument("--max-repeat", type=int, default=3, help="Maximum copies per exact payload in cap mode.")
    parser.add_argument("--seed", type=int, default=20260425)
    parser.add_argument("--generated-date", default=None, help="Override metadata date (YYYY-MM-DD).")
    parser.add_argument(
        "--no-protect-holdouts",
        action="store_true",
        help="Keep train rows even if their trainable content exactly overlaps val/test.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    metadata = fix_dataset(
        args.input_dir.expanduser().resolve(),
        args.output_dir.expanduser().resolve(),
        mode=args.mode,
        max_repeat=args.max_repeat,
        seed=args.seed,
        protect_holdouts=not args.no_protect_holdouts,
        generated_date=args.generated_date,
    )
    print(json.dumps(metadata, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
