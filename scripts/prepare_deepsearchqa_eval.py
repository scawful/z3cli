#!/usr/bin/env python3
"""Prepare google/deepsearchqa as a JSONL eval prompt pack."""

from __future__ import annotations

import argparse
import csv
import json
import re
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any


DATASET_ID = "google/deepsearchqa"
DATASET_URL = "https://huggingface.co/datasets/google/deepsearchqa"
RAW_CSV_URL = "https://huggingface.co/datasets/google/deepsearchqa/resolve/main/DSQA-full.csv"
EVAL_FAMILY = "google_deepsearchqa_eval_v1"

WEB_AGENT_SYSTEM_PROMPT = (
    "You are a web-capable research agent being evaluated on difficult "
    "multi-step factual retrieval. Use search or retrieval tools when your "
    "runtime provides them. Return only the final answer, not a chain of "
    "thought. If available evidence is insufficient, say you cannot verify "
    "the answer from the available evidence."
)

NO_WEB_SYSTEM_PROMPT = (
    "You are running this DeepSearchQA prompt without browser or search tools. "
    "Do not guess. Return only the final answer if you can answer from known "
    "facts with high confidence; otherwise say you cannot verify the answer "
    "from the available evidence."
)

REQUIRED_COLUMNS = ("problem", "problem_category", "answer", "answer_type")


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "unknown"


def normalize_answer_type(value: str) -> str:
    return slugify(value.replace("Answer", "").strip())


def download_csv(*, url: str, out_path: Path, force: bool = False, timeout: float = 60.0) -> Path:
    if out_path.exists() and not force:
        return out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=timeout) as response:
        payload = response.read()
    out_path.write_bytes(payload)
    return out_path


def read_deepsearchqa_csv(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = tuple(reader.fieldnames or ())
        missing = [column for column in REQUIRED_COLUMNS if column not in fieldnames]
        if missing:
            raise ValueError(f"{csv_path} missing required columns: {', '.join(missing)}")

        rows: list[dict[str, str]] = []
        for line_number, raw_row in enumerate(reader, start=2):
            row = {column: str(raw_row.get(column) or "").strip() for column in REQUIRED_COLUMNS}
            if not row["problem"]:
                continue
            if not row["answer"]:
                raise ValueError(f"{csv_path}:{line_number}: missing answer")
            rows.append(row)
    return rows


def build_prompt_row(
    source_row: dict[str, str],
    *,
    index: int,
    id_prefix: str,
    system_prompt: str,
    include_expected: bool = False,
) -> dict[str, Any]:
    category = source_row["problem_category"]
    answer_type = source_row["answer_type"]
    category_tag = slugify(category)
    answer_type_tag = normalize_answer_type(answer_type)
    case_id = f"{id_prefix}_{index:04d}_{category_tag}"
    prompt_row = {
        "id": case_id,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": source_row["problem"]},
        ],
        "_metadata": {
            "source_dataset": DATASET_ID,
            "source_url": DATASET_URL,
            "license": "apache-2.0",
            "eval_family": EVAL_FAMILY,
            "problem_category": category,
            "answer_type": answer_type,
            "tags": [
                "external",
                "google",
                "deepsearchqa",
                "web-retrieval",
                category_tag,
                f"answer-{answer_type_tag}",
            ],
            "severity": "medium",
            "scoring": {
                "official": "Gemini 2.5 Flash autorater from the DeepSearchQA Kaggle starter notebook.",
                "local": "scripts/score_deepsearchqa_eval.py is rough contains-based triage only.",
            },
        },
    }
    if include_expected:
        prompt_row["expected"] = source_row["answer"]
    return prompt_row


def build_answer_row(prompt_row: dict[str, Any], source_row: dict[str, str]) -> dict[str, Any]:
    metadata = prompt_row.get("_metadata", {})
    return {
        "id": prompt_row["id"],
        "answer": source_row["answer"],
        "answer_type": metadata.get("answer_type", ""),
        "problem_category": metadata.get("problem_category", ""),
        "source_dataset": metadata.get("source_dataset", DATASET_ID),
        "license": metadata.get("license", "apache-2.0"),
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def select_system_prompt(agent_mode: str, override_path: Path | None = None) -> str:
    if override_path:
        return override_path.read_text(encoding="utf-8").strip()
    if agent_mode == "no-web":
        return NO_WEB_SYSTEM_PROMPT
    return WEB_AGENT_SYSTEM_PROMPT


def prepare_eval(
    *,
    csv_path: Path,
    out_path: Path,
    answers_out: Path | None,
    id_prefix: str = EVAL_FAMILY,
    agent_mode: str = "web-agent",
    system_prompt_file: Path | None = None,
    limit: int = 0,
    categories: list[str] | None = None,
    include_expected: bool = False,
) -> dict[str, Any]:
    source_rows = read_deepsearchqa_csv(csv_path)
    category_filter = {category.lower() for category in categories or []}
    if category_filter:
        source_rows = [
            row for row in source_rows if row["problem_category"].lower() in category_filter
        ]
    if limit > 0:
        source_rows = source_rows[:limit]
    if not source_rows:
        raise RuntimeError("No DeepSearchQA rows selected.")

    system_prompt = select_system_prompt(agent_mode, system_prompt_file)
    prompt_rows = [
        build_prompt_row(
            row,
            index=index,
            id_prefix=id_prefix,
            system_prompt=system_prompt,
            include_expected=include_expected,
        )
        for index, row in enumerate(source_rows, start=1)
    ]
    write_jsonl(out_path, prompt_rows)
    if answers_out:
        write_jsonl(answers_out, [
            build_answer_row(prompt_row, source_row)
            for prompt_row, source_row in zip(prompt_rows, source_rows, strict=True)
        ])

    category_counts = Counter(row["problem_category"] for row in source_rows)
    answer_type_counts = Counter(row["answer_type"] for row in source_rows)
    summary = {
        "source_dataset": DATASET_ID,
        "source_url": DATASET_URL,
        "csv": str(csv_path),
        "out": str(out_path),
        "answers_out": str(answers_out) if answers_out else "",
        "rows": len(prompt_rows),
        "agent_mode": agent_mode,
        "include_expected": include_expected,
        "categories": dict(sorted(category_counts.items())),
        "answer_types": dict(sorted(answer_type_counts.items())),
    }
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, required=True, help="Path to DSQA-full.csv.")
    parser.add_argument("--out", type=Path, required=True, help="Output prompt-pack JSONL.")
    parser.add_argument("--answers-out", type=Path, default=None, help="Optional answer companion JSONL.")
    parser.add_argument("--download", action="store_true", help="Download DSQA-full.csv to --csv first.")
    parser.add_argument("--download-url", default=RAW_CSV_URL)
    parser.add_argument("--force-download", action="store_true")
    parser.add_argument("--id-prefix", default=EVAL_FAMILY)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--category",
        action="append",
        default=[],
        help="Optional problem_category filter. Repeat for multiple categories.",
    )
    parser.add_argument(
        "--agent-mode",
        choices=("web-agent", "no-web"),
        default="web-agent",
        help="Prompt style. Use no-web for raw vLLM endpoints without search tools.",
    )
    parser.add_argument("--system-prompt-file", type=Path, default=None)
    parser.add_argument(
        "--include-expected",
        action="store_true",
        help="Embed gold answers in prompt-pack rows. Off by default to reduce leakage risk.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.download:
        download_csv(url=args.download_url, out_path=args.csv, force=args.force_download)
    elif not args.csv.exists():
        raise FileNotFoundError(f"{args.csv} does not exist. Use --download or provide a local CSV.")

    summary = prepare_eval(
        csv_path=args.csv,
        out_path=args.out,
        answers_out=args.answers_out,
        id_prefix=args.id_prefix,
        agent_mode=args.agent_mode,
        system_prompt_file=args.system_prompt_file,
        limit=args.limit,
        categories=args.category,
        include_expected=args.include_expected,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
