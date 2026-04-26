#!/usr/bin/env python3
"""Rough local triage scorer for DeepSearchQA eval outputs."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                rows.append(json.loads(stripped))
    return rows


def normalize_text(value: str) -> str:
    value = value.lower().replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def extract_completion(row: dict[str, Any]) -> str:
    for key in ("completion", "response", "answer", "content", "assistant_content"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value
    messages = row.get("messages")
    if isinstance(messages, list):
        for message in reversed(messages):
            if isinstance(message, dict) and message.get("role") == "assistant":
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    return content
    return ""


def split_set_answer(answer: str) -> list[str]:
    bullet_lines = [
        line.strip(" -*\t")
        for line in answer.splitlines()
        if line.strip().startswith(("-", "*"))
    ]
    if bullet_lines:
        return [line for line in bullet_lines if line]

    pieces = re.split(r"\s*(?:;|\n|,\s+and\s+|\band\b)\s*", answer)
    if len(pieces) <= 1:
        pieces = re.split(r",\s*", answer)
    return [piece.strip(" .") for piece in pieces if piece.strip(" .")]


def score_single_answer(expected: str, completion: str) -> dict[str, Any]:
    expected_norm = normalize_text(expected)
    completion_norm = normalize_text(completion)
    passed = bool(expected_norm and expected_norm in completion_norm)
    return {
        "passed": passed,
        "score": 1.0 if passed else 0.0,
        "hits": 1 if passed else 0,
        "total": 1,
        "missing": [] if passed else [expected],
    }


def score_set_answer(expected: str, completion: str) -> dict[str, Any]:
    expected_items = split_set_answer(expected)
    completion_norm = normalize_text(completion)
    missing = [
        item for item in expected_items if normalize_text(item) not in completion_norm
    ]
    total = len(expected_items)
    hits = total - len(missing)
    score = round(hits / total, 4) if total else 0.0
    return {
        "passed": total > 0 and hits == total,
        "score": score,
        "hits": hits,
        "total": total,
        "missing": missing,
    }


def score_row(row: dict[str, Any], answer_row: dict[str, Any] | None = None) -> dict[str, Any]:
    expected = ""
    answer_type = ""
    category = ""
    if answer_row:
        expected = str(answer_row.get("answer") or "")
        answer_type = str(answer_row.get("answer_type") or "")
        category = str(answer_row.get("problem_category") or "")
    expected = expected or str(row.get("expected") or row.get("answer") or "")
    metadata = row.get("_metadata", {}) if isinstance(row.get("_metadata"), dict) else {}
    answer_type = answer_type or str(row.get("answer_type") or metadata.get("answer_type") or "")
    category = category or str(row.get("problem_category") or metadata.get("problem_category") or "")

    completion = extract_completion(row)
    if "set" in answer_type.lower():
        result = score_set_answer(expected, completion)
    else:
        result = score_single_answer(expected, completion)

    return {
        "id": row.get("id"),
        "answer_type": answer_type,
        "problem_category": category,
        "expected": expected,
        "completion": completion,
        **result,
    }


def summarize(rows: list[dict[str, Any]], *, eval_output: Path, answers: Path | None) -> dict[str, Any]:
    total = len(rows)
    passed = sum(1 for row in rows if row["passed"])
    mean_score = round(sum(float(row["score"]) for row in rows) / total, 4) if total else 0.0
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_answer_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_category[str(row.get("problem_category") or "unknown")].append(row)
        by_answer_type[str(row.get("answer_type") or "unknown")].append(row)

    def group_summary(group: list[dict[str, Any]]) -> dict[str, Any]:
        group_total = len(group)
        group_passed = sum(1 for item in group if item["passed"])
        return {
            "total": group_total,
            "passed": group_passed,
            "pass_rate": round(group_passed / group_total, 4) if group_total else 0.0,
            "mean_score": round(sum(float(item["score"]) for item in group) / group_total, 4)
            if group_total
            else 0.0,
        }

    return {
        "eval_output": str(eval_output),
        "answers": str(answers) if answers else "",
        "scoring": "rough_contains_v1",
        "official_scoring_note": (
            "DeepSearchQA recommends the Gemini 2.5 Flash autorater from the Kaggle starter; "
            "this scorer is for local triage only."
        ),
        "total": total,
        "passed": passed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "mean_score": mean_score,
        "by_category": {key: group_summary(value) for key, value in sorted(by_category.items())},
        "by_answer_type": {
            key: group_summary(value) for key, value in sorted(by_answer_type.items())
        },
        "failing_ids": [str(row["id"]) for row in rows if not row["passed"]],
    }


def score_eval(
    *,
    eval_output: Path,
    answers: Path | None = None,
    summary_out: Path | None = None,
    details_out: Path | None = None,
) -> dict[str, Any]:
    answer_rows = {
        str(row.get("id")): row
        for row in load_jsonl(answers)
    } if answers else {}
    scored_rows = [
        score_row(row, answer_rows.get(str(row.get("id"))))
        for row in load_jsonl(eval_output)
    ]
    summary = summarize(scored_rows, eval_output=eval_output, answers=answers)
    if summary_out:
        summary_out.parent.mkdir(parents=True, exist_ok=True)
        summary_out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if details_out:
        details_out.parent.mkdir(parents=True, exist_ok=True)
        with details_out.open("w", encoding="utf-8") as handle:
            for row in scored_rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-output", type=Path, required=True)
    parser.add_argument("--answers", type=Path, default=None)
    parser.add_argument("--summary-out", type=Path, default=None)
    parser.add_argument("--details-out", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = score_eval(
        eval_output=args.eval_output,
        answers=args.answers,
        summary_out=args.summary_out,
        details_out=args.details_out,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
