#!/usr/bin/env python3
"""Prepare selected Google HF datasets as local JSONL eval prompt packs."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


def raise_csv_field_limit() -> None:
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


raise_csv_field_limit()


GOOGLE_EVAL_SYSTEM_PROMPT = (
    "You are being evaluated. Follow the user request exactly, answer directly, "
    "and do not include hidden reasoning."
)

GROUNDED_SYSTEM_PROMPT = (
    "Answer only from the provided context. Do not use outside knowledge. "
    "If the context is insufficient, say that the answer is not supported by "
    "the provided context."
)

WEB_RAG_SYSTEM_PROMPT = (
    "You are a web-capable retrieval and reasoning agent. Use search or "
    "retrieval tools when available. Return only the final answer, not a chain "
    "of thought. If available evidence is insufficient, say you cannot verify "
    "the answer from the available evidence."
)

NO_TOOLS_FACTUALITY_SYSTEM_PROMPT = (
    "Answer from parametric knowledge only. Do not use search or retrieval "
    "tools. If you are not highly confident, say you cannot verify the answer."
)


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "unknown"


def truthy(value: str) -> bool:
    return value.strip().lower() in {"true", "1", "yes", "y"}


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def download_file(*, url: str, out_path: Path, force: bool = False, timeout: float = 120.0) -> Path:
    if out_path.exists() and not force:
        return out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=timeout) as response:
        out_path.write_bytes(response.read())
    return out_path


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [
            {str(key or "").strip(): clean_text(value) for key, value in row.items()}
            for row in csv.DictReader(handle)
        ]


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [
            {str(key or "").strip(): clean_text(value) for key, value in row.items()}
            for row in csv.DictReader(handle, delimiter="\t")
        ]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                rows.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def maybe_limit(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return rows[:limit] if limit > 0 else rows


def common_metadata(
    *,
    dataset_id: str,
    source_url: str,
    license_name: str,
    eval_family: str,
    tags: list[str],
    scoring: dict[str, str],
) -> dict[str, Any]:
    return {
        "source_dataset": dataset_id,
        "source_url": source_url,
        "license": license_name,
        "eval_family": eval_family,
        "tags": ["external", "google", *tags],
        "severity": "medium",
        "scoring": scoring,
    }


def prepare_facts_grounding(
    source_path: Path,
    *,
    out_path: Path,
    answers_out: Path | None,
    limit: int = 0,
) -> dict[str, Any]:
    del answers_out
    raw_rows = maybe_limit(read_csv(source_path), limit)
    prompt_rows: list[dict[str, Any]] = []
    for index, row in enumerate(raw_rows, start=1):
        user_request = clean_text(row.get("user_request"))
        context_document = clean_text(row.get("context_document"))
        if not user_request or not context_document:
            continue
        system_instruction = clean_text(row.get("system_instruction")) or GROUNDED_SYSTEM_PROMPT
        prompt_rows.append({
            "id": f"google_facts_grounding_eval_v1_{index:04d}",
            "messages": [
                {"role": "system", "content": system_instruction},
                {
                    "role": "user",
                    "content": f"Question:\n{user_request}\n\nContext:\n{context_document}",
                },
            ],
            "_metadata": {
                **common_metadata(
                    dataset_id="google/FACTS-grounding-public",
                    source_url="https://huggingface.co/datasets/google/FACTS-grounding-public",
                    license_name="cc-by-4.0",
                    eval_family="google_facts_grounding_eval_v1",
                    tags=["facts-grounding", "grounded-answering", "long-context"],
                    scoring={
                        "official": "FACTS Grounding judge prompts from Google's Kaggle starter.",
                        "local": "manual/LLM judge review; no gold answers are embedded in this prompt pack.",
                    },
                ),
                "context_chars": len(context_document),
                "user_request_chars": len(user_request),
            },
        })
    write_jsonl(out_path, prompt_rows)
    return {
        "dataset": "facts-grounding",
        "source": str(source_path),
        "out": str(out_path),
        "rows": len(prompt_rows),
        "answers_out": "",
    }


def prepare_frames(
    source_path: Path,
    *,
    out_path: Path,
    answers_out: Path | None,
    limit: int = 0,
) -> dict[str, Any]:
    raw_rows = maybe_limit(read_tsv(source_path), limit)
    prompt_rows: list[dict[str, Any]] = []
    answer_rows: list[dict[str, Any]] = []
    reasoning_counts: Counter[str] = Counter()
    for index, row in enumerate(raw_rows, start=1):
        prompt = clean_text(row.get("Prompt") or row.get("prompt"))
        answer = clean_text(row.get("Answer") or row.get("answer"))
        if not prompt:
            continue
        reasoning_types = clean_text(row.get("reasoning_types"))
        for piece in re.split(r"\s*\|\s*", reasoning_types):
            if piece:
                reasoning_counts[piece] += 1
        wiki_links = clean_text(row.get("wiki_links"))
        link_values = [
            clean_text(row.get(f"wikipedia_link_{n}"))
            for n in range(1, 12)
            if clean_text(row.get(f"wikipedia_link_{n}"))
        ]
        case_id = f"google_frames_eval_v1_{index:04d}"
        prompt_rows.append({
            "id": case_id,
            "messages": [
                {"role": "system", "content": WEB_RAG_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "_metadata": {
                **common_metadata(
                    dataset_id="google/frames-benchmark",
                    source_url="https://huggingface.co/datasets/google/frames-benchmark",
                    license_name="apache-2.0",
                    eval_family="google_frames_eval_v1",
                    tags=["frames", "rag", "multi-hop", "web-retrieval"],
                    scoring={
                        "official": "FRAMES benchmark scoring from the paper/release.",
                        "local": "rough answer containment only if paired with a local scorer.",
                    },
                ),
                "reasoning_types": reasoning_types,
                "wiki_links": wiki_links,
                "wikipedia_links": link_values,
            },
        })
        answer_rows.append({
            "id": case_id,
            "answer": answer,
            "reasoning_types": reasoning_types,
            "wiki_links": wiki_links,
            "wikipedia_links": link_values,
            "source_dataset": "google/frames-benchmark",
            "license": "apache-2.0",
        })
    write_jsonl(out_path, prompt_rows)
    if answers_out:
        write_jsonl(answers_out, answer_rows)
    return {
        "dataset": "frames",
        "source": str(source_path),
        "out": str(out_path),
        "answers_out": str(answers_out) if answers_out else "",
        "rows": len(prompt_rows),
        "reasoning_types": dict(sorted(reasoning_counts.items())),
    }


def prepare_ifeval(
    source_path: Path,
    *,
    out_path: Path,
    answers_out: Path | None,
    limit: int = 0,
) -> dict[str, Any]:
    raw_rows = maybe_limit(read_jsonl(source_path), limit)
    prompt_rows: list[dict[str, Any]] = []
    rule_rows: list[dict[str, Any]] = []
    instruction_counts: Counter[str] = Counter()
    for row in raw_rows:
        prompt = clean_text(row.get("prompt"))
        key = clean_text(row.get("key"))
        if not prompt or not key:
            continue
        instruction_ids = [
            str(item)
            for item in row.get("instruction_id_list", [])
            if str(item).strip()
        ]
        for instruction_id in instruction_ids:
            instruction_counts[instruction_id] += 1
        kwargs = row.get("kwargs", [])
        case_id = f"google_ifeval_eval_v1_{key}"
        prompt_rows.append({
            "id": case_id,
            "messages": [
                {"role": "system", "content": GOOGLE_EVAL_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "_metadata": {
                **common_metadata(
                    dataset_id="google/IFEval",
                    source_url="https://huggingface.co/datasets/google/IFEval",
                    license_name="apache-2.0",
                    eval_family="google_ifeval_eval_v1",
                    tags=["ifeval", "instruction-following", "format-discipline"],
                    scoring={
                        "official": "IFEval official instruction verifier.",
                        "local": "not implemented in z3cli; use as output capture or external verifier input.",
                    },
                ),
                "source_key": key,
                "instruction_id_list": instruction_ids,
                "kwargs": kwargs,
            },
        })
        rule_rows.append({
            "id": case_id,
            "source_key": key,
            "instruction_id_list": instruction_ids,
            "kwargs": kwargs,
            "source_dataset": "google/IFEval",
            "license": "apache-2.0",
        })
    write_jsonl(out_path, prompt_rows)
    if answers_out:
        write_jsonl(answers_out, rule_rows)
    return {
        "dataset": "ifeval",
        "source": str(source_path),
        "out": str(out_path),
        "answers_out": str(answers_out) if answers_out else "",
        "rows": len(prompt_rows),
        "instruction_ids": dict(sorted(instruction_counts.items())),
    }


def prepare_simpleqa_verified(
    source_path: Path,
    *,
    out_path: Path,
    answers_out: Path | None,
    limit: int = 0,
) -> dict[str, Any]:
    raw_rows = maybe_limit(read_csv(source_path), limit)
    prompt_rows: list[dict[str, Any]] = []
    answer_rows: list[dict[str, Any]] = []
    topic_counts: Counter[str] = Counter()
    answer_type_counts: Counter[str] = Counter()
    for index, row in enumerate(raw_rows, start=1):
        problem = clean_text(row.get("problem"))
        answer = clean_text(row.get("answer"))
        if not problem:
            continue
        topic = clean_text(row.get("topic")) or "unknown"
        answer_type = clean_text(row.get("answer_type")) or "unknown"
        topic_counts[topic] += 1
        answer_type_counts[answer_type] += 1
        case_id = f"google_simpleqa_verified_eval_v1_{index:04d}_{slugify(topic)}"
        prompt_rows.append({
            "id": case_id,
            "messages": [
                {"role": "system", "content": NO_TOOLS_FACTUALITY_SYSTEM_PROMPT},
                {"role": "user", "content": problem},
            ],
            "_metadata": {
                **common_metadata(
                    dataset_id="google/simpleqa-verified",
                    source_url="https://huggingface.co/datasets/google/simpleqa-verified",
                    license_name="mit",
                    eval_family="google_simpleqa_verified_eval_v1",
                    tags=["simpleqa-verified", "factuality", "no-tools"],
                    scoring={
                        "official": "SimpleQA Verified GPT-4.1 autorater from Google's Kaggle starter.",
                        "local": "rough answer containment only if paired with a local scorer.",
                    },
                ),
                "original_index": clean_text(row.get("original_index")),
                "topic": topic,
                "answer_type": answer_type,
                "multi_step": truthy(clean_text(row.get("multi_step"))),
                "requires_reasoning": truthy(clean_text(row.get("requires_reasoning"))),
            },
        })
        answer_rows.append({
            "id": case_id,
            "answer": answer,
            "original_index": clean_text(row.get("original_index")),
            "topic": topic,
            "answer_type": answer_type,
            "multi_step": truthy(clean_text(row.get("multi_step"))),
            "requires_reasoning": truthy(clean_text(row.get("requires_reasoning"))),
            "urls": clean_text(row.get("urls")),
            "source_dataset": "google/simpleqa-verified",
            "license": "mit",
        })
    write_jsonl(out_path, prompt_rows)
    if answers_out:
        write_jsonl(answers_out, answer_rows)
    return {
        "dataset": "simpleqa-verified",
        "source": str(source_path),
        "out": str(out_path),
        "answers_out": str(answers_out) if answers_out else "",
        "rows": len(prompt_rows),
        "topics": dict(sorted(topic_counts.items())),
        "answer_types": dict(sorted(answer_type_counts.items())),
    }


PrepareFn = Callable[[Path], dict[str, Any]]


@dataclass(frozen=True)
class DatasetSpec:
    name: str
    source_filename: str
    download_url: str
    eval_filename: str
    answers_filename: str
    prepare: Callable[..., dict[str, Any]]


SPECS: dict[str, DatasetSpec] = {
    "facts-grounding": DatasetSpec(
        name="facts-grounding",
        source_filename="google_facts_grounding_public/examples.csv",
        download_url="https://huggingface.co/datasets/google/FACTS-grounding-public/resolve/main/examples.csv",
        eval_filename="google_facts_grounding_eval_v1.jsonl",
        answers_filename="",
        prepare=prepare_facts_grounding,
    ),
    "frames": DatasetSpec(
        name="frames",
        source_filename="google_frames_benchmark/test.tsv",
        download_url="https://huggingface.co/datasets/google/frames-benchmark/resolve/main/test.tsv",
        eval_filename="google_frames_eval_v1.jsonl",
        answers_filename="google_frames_eval_answers_v1.jsonl",
        prepare=prepare_frames,
    ),
    "ifeval": DatasetSpec(
        name="ifeval",
        source_filename="google_ifeval/ifeval_input_data.jsonl",
        download_url="https://huggingface.co/datasets/google/IFEval/resolve/main/ifeval_input_data.jsonl",
        eval_filename="google_ifeval_eval_v1.jsonl",
        answers_filename="google_ifeval_rules_v1.jsonl",
        prepare=prepare_ifeval,
    ),
    "simpleqa-verified": DatasetSpec(
        name="simpleqa-verified",
        source_filename="google_simpleqa_verified/simpleqa_verified.csv",
        download_url="https://huggingface.co/datasets/google/simpleqa-verified/resolve/main/simpleqa_verified.csv",
        eval_filename="google_simpleqa_verified_eval_v1.jsonl",
        answers_filename="google_simpleqa_verified_eval_answers_v1.jsonl",
        prepare=prepare_simpleqa_verified,
    ),
}


def prepare_dataset(
    name: str,
    *,
    source_dir: Path,
    eval_dir: Path,
    answers_dir: Path,
    download: bool = False,
    force_download: bool = False,
    limit: int = 0,
) -> dict[str, Any]:
    spec = SPECS[name]
    source_path = source_dir / spec.source_filename
    if download:
        download_file(url=spec.download_url, out_path=source_path, force=force_download)
    elif not source_path.exists():
        raise FileNotFoundError(f"{source_path} does not exist. Use --download.")
    answers_out = answers_dir / spec.answers_filename if spec.answers_filename else None
    return spec.prepare(
        source_path,
        out_path=eval_dir / spec.eval_filename,
        answers_out=answers_out,
        limit=limit,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        action="append",
        choices=(*SPECS.keys(), "all"),
        default=[],
        help="Dataset to prepare. Repeat for multiple datasets, or use all.",
    )
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--eval-dir", type=Path, required=True)
    parser.add_argument("--answers-dir", type=Path, required=True)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--force-download", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args()


def selected_datasets(values: list[str]) -> list[str]:
    if not values or "all" in values:
        return list(SPECS.keys())
    seen: set[str] = set()
    selected: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            selected.append(value)
    return selected


def main() -> int:
    args = parse_args()
    summaries = [
        prepare_dataset(
            name,
            source_dir=args.source_dir,
            eval_dir=args.eval_dir,
            answers_dir=args.answers_dir,
            download=args.download,
            force_download=args.force_download,
            limit=args.limit,
        )
        for name in selected_datasets(args.dataset)
    ]
    print(json.dumps({"datasets": summaries}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
