#!/usr/bin/env python3
"""Audit Oracle training datasets for overlap, weighting, and tool coverage.

The script is intentionally dependency-free so it can run from the z3cli repo
while reading the sibling training repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any


DEFAULT_DATASETS = (
    "qwen3_oracle_14b_v7",
    "oracle_repo_code_v3",
    "oracle_fast_4b_candidate_v1",
    "oracle_9b_candidate_v1",
    "oracle_longctx_v1",
    "oracle_longctx_dpo_v1",
)
SPLITS = ("train", "val", "test")
BUCKET_KEYS = (
    "capability_bucket",
    "corrective_v6_bucket",
    "corrective_v5_bucket",
    "corrective_v4_bucket",
    "corrective_v3_bucket",
    "corrective_v2_bucket",
    "corrective_v1_bucket",
    "section",
    "surface",
)
ROLE_KEYS = (
    "corrective_v6_role",
    "corrective_v5_role",
    "corrective_v4_role",
    "corrective_v3_role",
    "role",
)
STYLE_KEYS = (
    "corrective_v6_style",
    "corrective_v5_style",
    "corrective_v4_style",
    "corrective_v3_style",
    "corrective_v2_style",
    "style",
)
HEX_RE = re.compile(r"\$[0-9a-fA-F]+|0x[0-9a-fA-F]+")
WORD_RE = re.compile(r"[a-z0-9_.$/-]+")


@dataclass
class RowRecord:
    dataset: str
    split: str
    path: Path
    line_no: int
    row_id: str
    prompt: str
    answer: str
    metadata: dict[str, Any]
    content_hash: str
    prompt_hash: str
    answer_hash: str
    prompt_family_hash: str
    tool_surface: str
    bucket: str
    role: str
    style: str


@dataclass
class DatasetAudit:
    name: str
    path: Path
    rows: list[RowRecord] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)
    split_counts: Counter[str] = field(default_factory=Counter)
    unique_content: int = 0
    unique_prompts: int = 0
    unique_answers: int = 0
    content_duplicate_rows: int = 0
    prompt_duplicate_rows: int = 0
    tool_surfaces: Counter[str] = field(default_factory=Counter)
    bucket_counts: Counter[str] = field(default_factory=Counter)
    bucket_unique_counts: Counter[str] = field(default_factory=Counter)
    role_counts: Counter[str] = field(default_factory=Counter)
    style_counts: Counter[str] = field(default_factory=Counter)
    split_content_overlaps: dict[str, int] = field(default_factory=dict)
    split_prompt_overlaps: dict[str, int] = field(default_factory=dict)
    prompt_family_clusters: list[dict[str, Any]] = field(default_factory=list)
    eval_prompt_overlaps: Counter[str] = field(default_factory=Counter)
    eval_answer_overlaps: Counter[str] = field(default_factory=Counter)
    eval_examples: list[dict[str, str]] = field(default_factory=list)
    examples_by_bucket: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class EvalIndex:
    files: list[Path] = field(default_factory=list)
    prompt_to_files: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    answer_to_files: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _normalize(value: str) -> str:
    lowered = value.strip().lower()
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered


def _hash_text(value: str) -> str:
    return hashlib.sha256(_normalize(value).encode("utf-8")).hexdigest()[:16]


def _message_text(messages: Any, role: str) -> str:
    if not isinstance(messages, list):
        return ""
    parts = [
        _text(message.get("content"))
        for message in messages
        if isinstance(message, dict) and message.get("role") == role
    ]
    return "\n\n".join(part for part in parts if part.strip())


def _last_message_text(messages: Any, role: str) -> str:
    if not isinstance(messages, list):
        return ""
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") == role:
            return _text(message.get("content"))
    return ""


def extract_prompt(row: dict[str, Any]) -> str:
    prompt = _last_message_text(row.get("messages"), "user")
    if not prompt:
        prompt = _last_message_text(row.get("prompt_messages"), "user")
    return prompt or _text(row.get("prompt"))


def extract_answer(row: dict[str, Any]) -> str:
    answer = _text(row.get("response"))
    if answer:
        return answer
    answer = _last_message_text(row.get("messages"), "assistant")
    if answer:
        return answer
    chosen = _last_message_text(row.get("chosen_messages"), "assistant")
    rejected = _last_message_text(row.get("rejected_messages"), "assistant")
    if chosen or rejected:
        return f"CHOSEN:\n{chosen}\n\nREJECTED:\n{rejected}".strip()
    chosen = _text(row.get("chosen"))
    rejected = _text(row.get("rejected"))
    if chosen or rejected:
        return f"CHOSEN:\n{chosen}\n\nREJECTED:\n{rejected}".strip()
    return ""


def _canonical_prompt_for_family(prompt: str) -> str:
    text = prompt
    cut_markers = (
        "\n\nA previous answer",
        "\n\nRewrite the answer",
        "\n\nAnswer in ",
        "\n\nUse the exact",
        "\n\nDo not replace",
    )
    for marker in cut_markers:
        if marker in text:
            text = text.split(marker, 1)[0]
    text = re.sub(
        r"^\s*(use only the file map below|use the repository sketch below|repository sketch|use the repository context below)\.?:\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = HEX_RE.sub("<hex>", text)
    words = WORD_RE.findall(_normalize(text))
    if len(words) > 90:
        words = words[-90:]
    return " ".join(words)


def prompt_family_hash(prompt: str) -> str:
    return _hash_text(_canonical_prompt_for_family(prompt))


def _metadata_value(metadata: dict[str, Any], keys: tuple[str, ...], fallback: str) -> str:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def classify_tool_surface(row: dict[str, Any]) -> str:
    messages = row.get("messages")
    all_text = json.dumps(row, sort_keys=True, ensure_ascii=False).lower()
    if isinstance(messages, list):
        if any(isinstance(message, dict) and message.get("role") == "tool" for message in messages):
            return "tool-role-transcript"
        if any(isinstance(message, dict) and message.get("tool_calls") for message in messages):
            return "native-tool-calls"
    if any(token in all_text for token in ("<tool_call", "<tool>", "</tool>", "tool_call_id")):
        return "manual-tool-transcript"
    if any(token in all_text for token in ("tool result", "tool output", "oracle preloaded context")):
        return "prose-tool-context"
    return "prose-only"


def read_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    if not path.exists():
        return rows, errors
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                data = json.loads(stripped)
            except json.JSONDecodeError as exc:
                errors.append(f"{path}:{line_no}: {exc}")
                continue
            if isinstance(data, dict):
                data["_audit_line_no"] = line_no
                rows.append(data)
            else:
                errors.append(f"{path}:{line_no}: row is not an object")
    return rows, errors


def row_record(dataset: str, split: str, path: Path, row: dict[str, Any]) -> RowRecord:
    metadata = row.get("_metadata") if isinstance(row.get("_metadata"), dict) else {}
    prompt = extract_prompt(row)
    answer = extract_answer(row)
    row_id = str(
        row.get("id")
        or metadata.get("sample_id")
        or metadata.get("from_eval_id")
        or f"{path.name}:{row.get('_audit_line_no', 0)}"
    )
    content_payload = {
        "messages": row.get("messages"),
        "prompt_messages": row.get("prompt_messages"),
        "chosen_messages": row.get("chosen_messages"),
        "rejected_messages": row.get("rejected_messages"),
        "response": row.get("response"),
        "prompt": row.get("prompt"),
        "chosen": row.get("chosen"),
        "rejected": row.get("rejected"),
    }
    bucket = _metadata_value(metadata, BUCKET_KEYS, "unbucketed")
    role = _metadata_value(metadata, ROLE_KEYS, "unspecified")
    style = _metadata_value(metadata, STYLE_KEYS, "unspecified")
    return RowRecord(
        dataset=dataset,
        split=split,
        path=path,
        line_no=int(row.get("_audit_line_no", 0) or 0),
        row_id=row_id,
        prompt=prompt,
        answer=answer,
        metadata=metadata,
        content_hash=_hash_text(json.dumps(content_payload, sort_keys=True, ensure_ascii=False)),
        prompt_hash=_hash_text(prompt),
        answer_hash=_hash_text(answer),
        prompt_family_hash=prompt_family_hash(prompt),
        tool_surface=classify_tool_surface(row),
        bucket=bucket,
        role=role,
        style=style,
    )


def load_eval_index(training_root: Path, eval_globs: list[str]) -> EvalIndex:
    index = EvalIndex()
    for pattern in eval_globs:
        for path in sorted(training_root.glob(pattern)):
            if not path.is_file():
                continue
            rows, _errors = read_jsonl(path)
            if not rows:
                continue
            index.files.append(path)
            rel = str(path.relative_to(training_root))
            for row in rows:
                prompt = extract_prompt(row)
                answer = extract_answer(row)
                if prompt:
                    index.prompt_to_files[_hash_text(prompt)].add(rel)
                if answer:
                    index.answer_to_files[_hash_text(answer)].add(rel)
    return index


def audit_dataset(training_root: Path, dataset_name: str, eval_index: EvalIndex) -> DatasetAudit:
    dataset_path = training_root / "datasets" / dataset_name
    audit = DatasetAudit(name=dataset_name, path=dataset_path)
    rows_by_split: dict[str, list[RowRecord]] = {split: [] for split in SPLITS}
    for split in SPLITS:
        path = dataset_path / f"{split}.jsonl"
        raw_rows, errors = read_jsonl(path)
        audit.parse_errors.extend(errors)
        for raw in raw_rows:
            record = row_record(dataset_name, split, path, raw)
            audit.rows.append(record)
            rows_by_split[split].append(record)
            audit.split_counts[split] += 1
            audit.tool_surfaces[record.tool_surface] += 1
            audit.bucket_counts[record.bucket] += 1
            audit.role_counts[record.role] += 1
            audit.style_counts[record.style] += 1

    content_hashes = Counter(row.content_hash for row in audit.rows)
    prompt_hashes = Counter(row.prompt_hash for row in audit.rows)
    answer_hashes = Counter(row.answer_hash for row in audit.rows if row.answer.strip())
    audit.unique_content = len(content_hashes)
    audit.unique_prompts = len(prompt_hashes)
    audit.unique_answers = len(answer_hashes)
    audit.content_duplicate_rows = sum(count - 1 for count in content_hashes.values() if count > 1)
    audit.prompt_duplicate_rows = sum(count - 1 for count in prompt_hashes.values() if count > 1)

    bucket_uniques: dict[str, set[str]] = defaultdict(set)
    examples: dict[str, list[str]] = defaultdict(list)
    for row in audit.rows:
        bucket_uniques[row.bucket].add(row.content_hash)
        if len(examples[row.bucket]) < 4:
            examples[row.bucket].append(row.row_id)
        for eval_file in sorted(eval_index.prompt_to_files.get(row.prompt_hash, ())):
            audit.eval_prompt_overlaps[eval_file] += 1
            if len(audit.eval_examples) < 20:
                audit.eval_examples.append({"kind": "prompt", "eval_file": eval_file, "row_id": row.row_id})
        if row.answer_hash:
            for eval_file in sorted(eval_index.answer_to_files.get(row.answer_hash, ())):
                audit.eval_answer_overlaps[eval_file] += 1
                if len(audit.eval_examples) < 20:
                    audit.eval_examples.append({"kind": "answer", "eval_file": eval_file, "row_id": row.row_id})
    audit.bucket_unique_counts = Counter({bucket: len(values) for bucket, values in bucket_uniques.items()})
    audit.examples_by_bucket = dict(examples)

    for left, right in (("train", "val"), ("train", "test"), ("val", "test")):
        left_content = {row.content_hash for row in rows_by_split[left]}
        right_content = {row.content_hash for row in rows_by_split[right]}
        left_prompts = {row.prompt_hash for row in rows_by_split[left]}
        right_prompts = {row.prompt_hash for row in rows_by_split[right]}
        audit.split_content_overlaps[f"{left}/{right}"] = len(left_content & right_content)
        audit.split_prompt_overlaps[f"{left}/{right}"] = len(left_prompts & right_prompts)

    family_groups: dict[str, list[RowRecord]] = defaultdict(list)
    for row in audit.rows:
        family_groups[row.prompt_family_hash].append(row)
    clusters: list[dict[str, Any]] = []
    for cluster_rows in family_groups.values():
        if len(cluster_rows) < 2:
            continue
        clusters.append({
            "count": len(cluster_rows),
            "unique_prompts": len({row.prompt_hash for row in cluster_rows}),
            "splits": dict(Counter(row.split for row in cluster_rows)),
            "buckets": dict(Counter(row.bucket for row in cluster_rows).most_common(4)),
            "sample_ids": [row.row_id for row in cluster_rows[:5]],
            "prompt_preview": cluster_rows[0].prompt.strip().replace("\n", " ")[:180],
        })
    audit.prompt_family_clusters = sorted(
        clusters,
        key=lambda item: (int(item["count"]), int(item["unique_prompts"])),
        reverse=True,
    )[:12]
    return audit


def _pct(part: int, whole: int) -> str:
    if whole <= 0:
        return "0.0%"
    return f"{(part / whole) * 100:.1f}%"


def _counter_lines(counter: Counter[str], *, limit: int = 8) -> list[str]:
    if not counter:
        return ["- none"]
    return [f"- `{key}`: {value}" for key, value in counter.most_common(limit)]


def findings_for(audits: list[DatasetAudit]) -> list[str]:
    findings: list[str] = []
    for audit in audits:
        total = len(audit.rows)
        if total == 0:
            findings.append(f"`{audit.name}` has no readable rows.")
            continue
        duplicate_ratio = audit.content_duplicate_rows / total
        if duplicate_ratio >= 0.50:
            findings.append(
                f"`{audit.name}` is heavily weighted by duplication "
                f"({audit.content_duplicate_rows}/{total} duplicate rows, {_pct(audit.content_duplicate_rows, total)}). "
                "Keep this only when each weight maps to a measured failure bucket."
            )
        if audit.split_counts["val"] < 5 or audit.split_counts["test"] < 5:
            findings.append(
                f"`{audit.name}` has tiny validation/test splits "
                f"(val {audit.split_counts['val']}, test {audit.split_counts['test']}); treat them as smoke checks, not promotion gates."
            )
        transcript_rows = sum(
            count
            for surface, count in audit.tool_surfaces.items()
            if surface in {"native-tool-calls", "tool-role-transcript", "manual-tool-transcript"}
        )
        if transcript_rows == 0:
            findings.append(
                f"`{audit.name}` has no actual tool-call transcript rows. If this trains a tool-using Oracle lane, add deployed-format tool call/result/final-answer examples."
            )
        prompt_overlap = sum(audit.eval_prompt_overlaps.values())
        answer_overlap = sum(audit.eval_answer_overlaps.values())
        if prompt_overlap or answer_overlap:
            findings.append(
                f"`{audit.name}` overlaps Oracle eval material (prompt rows {prompt_overlap}, answer rows {answer_overlap}). "
                "Use those evals as regression checks and keep a fresh holdout for promotion."
            )
    return findings


def render_markdown(
    training_root: Path,
    audits: list[DatasetAudit],
    eval_index: EvalIndex,
    *,
    generated_date: str | None = None,
) -> str:
    generated_date = generated_date or date.today().isoformat()
    lines: list[str] = [
        "# Oracle Training Data Audit",
        "",
        f"Generated: {generated_date}",
        f"Training root: `{training_root}`",
        f"Eval files indexed: `{len(eval_index.files)}`",
        "",
        "## Executive Findings",
        "",
    ]
    findings = findings_for(audits)
    lines.extend(f"- {item}" for item in findings) if findings else lines.append("- No high-priority audit warnings.")
    lines.extend([
        "",
        "## Dataset Summary",
        "",
        "| Dataset | Rows | Train | Val | Test | Unique Rows | Duplicate Rows | Tool Transcript Rows | Prompt Eval Overlaps | Answer Eval Overlaps |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for audit in audits:
        total = len(audit.rows)
        transcript_rows = sum(
            count
            for surface, count in audit.tool_surfaces.items()
            if surface in {"native-tool-calls", "tool-role-transcript", "manual-tool-transcript"}
        )
        lines.append(
            f"| `{audit.name}` | {total} | {audit.split_counts['train']} | {audit.split_counts['val']} | {audit.split_counts['test']} "
            f"| {audit.unique_content} | {audit.content_duplicate_rows} | {transcript_rows} "
            f"| {sum(audit.eval_prompt_overlaps.values())} | {sum(audit.eval_answer_overlaps.values())} |"
        )
    lines.extend([
        "",
        "## Dataset Details",
        "",
    ])
    for audit in audits:
        total = len(audit.rows)
        lines.extend([
            f"### `{audit.name}`",
            "",
            f"- Path: `{audit.path}`",
            f"- Rows: `{total}`; unique row payloads: `{audit.unique_content}`; duplicate row pressure: `{_pct(audit.content_duplicate_rows, total)}`",
            f"- Unique prompts: `{audit.unique_prompts}`; prompt duplicate pressure: `{_pct(audit.prompt_duplicate_rows, total)}`",
            f"- Unique answers: `{audit.unique_answers}`",
            f"- Split content overlap: `{audit.split_content_overlaps}`",
            f"- Split prompt overlap: `{audit.split_prompt_overlaps}`",
            "",
            "Tool surface:",
            *_counter_lines(audit.tool_surfaces),
            "",
            "Bucket counts (expanded rows):",
            *_counter_lines(audit.bucket_counts),
            "",
            "Bucket unique row counts:",
            *_counter_lines(audit.bucket_unique_counts),
            "",
            "Role counts:",
            *_counter_lines(audit.role_counts, limit=6),
            "",
            "Style counts:",
            *_counter_lines(audit.style_counts, limit=6),
            "",
            "Examples by bucket:",
        ])
        for bucket, examples in sorted(audit.examples_by_bucket.items())[:10]:
            lines.append(f"- `{bucket}`: {', '.join(f'`{item}`' for item in examples)}")
        lines.extend(["", "Largest prompt-family clusters:"])
        if audit.prompt_family_clusters:
            for cluster in audit.prompt_family_clusters[:6]:
                lines.append(
                    f"- count `{cluster['count']}`, unique prompts `{cluster['unique_prompts']}`, "
                    f"splits `{cluster['splits']}`, buckets `{cluster['buckets']}`; samples "
                    f"{', '.join(f'`{item}`' for item in cluster['sample_ids'])}; preview: {cluster['prompt_preview']}"
                )
        else:
            lines.append("- none")
        lines.extend(["", "Top eval overlaps:"])
        overlap_lines = []
        for eval_file, count in audit.eval_prompt_overlaps.most_common(5):
            overlap_lines.append(f"- prompt `{eval_file}`: {count}")
        for eval_file, count in audit.eval_answer_overlaps.most_common(5):
            overlap_lines.append(f"- answer `{eval_file}`: {count}")
        lines.extend(overlap_lines or ["- none"])
        if audit.eval_examples:
            lines.append("")
            lines.append("Overlap examples:")
            for example in audit.eval_examples[:8]:
                lines.append(f"- `{example['kind']}` with `{example['eval_file']}` via row `{example['row_id']}`")
        if audit.parse_errors:
            lines.append("")
            lines.append("Parse errors:")
            lines.extend(f"- `{error}`" for error in audit.parse_errors[:10])
        lines.append("")

    lines.extend([
        "## Training And Prompt Implications",
        "",
        "- Treat eval-overlapping packs as regression suites. Promotion needs fresh prompts or adversarial variants that are not represented in train rows.",
        "- Where duplicate pressure is high, keep metadata-driven weights explicit and cap any bucket that starts regressing previously repaired surfaces.",
        "- Add real deployed-format tool transcripts for Oracle-family models that must learn chain continuation; prose-only rows teach facts but not agent behavior.",
        "- Keep `oracle-coder` rows code/retrieval/compile-focused. Do not blend broad Oracle explanation rows into that worker unless an eval proves it helps.",
        "- For system prompts, prefer short branch rules that mirror the data: ground first, preserve failed-grounding uncertainty, delegate authoring to `oracle-coder`, then verify.",
        "",
    ])
    return "\n".join(lines).rstrip() + "\n"


def audit_to_json(audit: DatasetAudit) -> dict[str, Any]:
    return {
        "name": audit.name,
        "path": str(audit.path),
        "rows": len(audit.rows),
        "split_counts": dict(audit.split_counts),
        "unique_content": audit.unique_content,
        "unique_prompts": audit.unique_prompts,
        "unique_answers": audit.unique_answers,
        "content_duplicate_rows": audit.content_duplicate_rows,
        "prompt_duplicate_rows": audit.prompt_duplicate_rows,
        "tool_surfaces": dict(audit.tool_surfaces),
        "bucket_counts": dict(audit.bucket_counts),
        "bucket_unique_counts": dict(audit.bucket_unique_counts),
        "role_counts": dict(audit.role_counts),
        "style_counts": dict(audit.style_counts),
        "split_content_overlaps": audit.split_content_overlaps,
        "split_prompt_overlaps": audit.split_prompt_overlaps,
        "eval_prompt_overlaps": dict(audit.eval_prompt_overlaps),
        "eval_answer_overlaps": dict(audit.eval_answer_overlaps),
        "prompt_family_clusters": audit.prompt_family_clusters,
        "examples_by_bucket": audit.examples_by_bucket,
        "parse_errors": audit.parse_errors,
    }


def default_training_root() -> Path:
    return (Path.home() / "src" / "training").resolve()


def existing_default_datasets(training_root: Path) -> list[str]:
    return [
        name for name in DEFAULT_DATASETS
        if (training_root / "datasets" / name).exists()
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit Oracle training datasets for overlap and coverage.")
    parser.add_argument("--training-root", type=Path, default=default_training_root())
    parser.add_argument("--dataset", action="append", default=[], help="Dataset directory name under training/datasets. Repeatable.")
    parser.add_argument("--all-oracle", action="store_true", help="Audit every dataset directory containing 'oracle'.")
    parser.add_argument("--eval-glob", action="append", default=["evals/oracle*.jsonl"], help="Training-root-relative eval glob. Repeatable.")
    parser.add_argument("--out", type=Path, default=None, help="Markdown output path.")
    parser.add_argument("--json-out", type=Path, default=None, help="Optional JSON summary output path.")
    parser.add_argument("--generated-date", default=None, help="Override report date (YYYY-MM-DD).")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    training_root = args.training_root.expanduser().resolve()
    if args.all_oracle:
        dataset_names = sorted(
            path.name
            for path in (training_root / "datasets").iterdir()
            if path.is_dir() and "oracle" in path.name
        )
    elif args.dataset:
        dataset_names = args.dataset
    else:
        dataset_names = existing_default_datasets(training_root)
    if not dataset_names:
        raise SystemExit(f"No datasets selected under {training_root / 'datasets'}")

    eval_index = load_eval_index(training_root, args.eval_glob)
    audits = [audit_dataset(training_root, name, eval_index) for name in dataset_names]
    markdown = render_markdown(training_root, audits, eval_index, generated_date=args.generated_date)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(markdown, encoding="utf-8")
    else:
        print(markdown, end="")

    if args.json_out:
        payload = {
            "training_root": str(training_root),
            "eval_files": [str(path.relative_to(training_root)) for path in eval_index.files],
            "datasets": [audit_to_json(audit) for audit in audits],
            "findings": findings_for(audits),
        }
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
