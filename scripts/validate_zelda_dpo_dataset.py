#!/usr/bin/env python3
"""Validate Zelda RLHF datasets against minimum coverage thresholds."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_THRESHOLDS = {
    "dpo": {
        "pilot": {
            "train_min": 250,
            "val_min": 10,
            "test_min": 10,
            "min_unique_ratio": 0.20,
            "max_duplicate": 16,
            "max_missing_metadata_pct": 0.02,
            "pair_source": {"nayru": 60, "farore": 40, "din": 25, "majora": 16},
            "domain": {"alttp-vanilla": 120, "oos": 70, "xref": 16},
            "mode": {"trace": 80, "debug": 20, "author": 20},
            "effort": {"high": 120, "medium": 80},
        },
        "production": {
            "train_min": 600,
            "val_min": 25,
            "test_min": 25,
            "min_unique_ratio": 0.30,
            "max_duplicate": 8,
            "max_missing_metadata_pct": 0.01,
            "pair_source": {"nayru": 150, "farore": 100, "din": 60, "majora": 40},
            "domain": {"alttp-vanilla": 300, "oos": 200, "xref": 80},
            "mode": {"trace": 220, "debug": 80, "author": 60},
            "effort": {"high": 280, "medium": 250},
        },
    },
    "ppo": {
        "pilot": {
            "train_min": 2000,
            "val_min": 200,
            "test_min": 200,
            "max_missing_metadata_pct": 0.03,
            "trajectory_min": 2000,
            "reward_non_null_ratio_min": 0.90,
            "mean_episode_len_min": 32,
            "max_trajectory_repeat": 10,
            "domain": {"alttp-vanilla": 600, "oos": 160, "xref": 60},
            "mode": {"trace": 140, "debug": 40, "author": 20},
            "effort": {"high": 600, "medium": 300, "low": 100},
        },
        "production": {
            "train_min": 8000,
            "val_min": 500,
            "test_min": 500,
            "max_missing_metadata_pct": 0.01,
            "trajectory_min": 8000,
            "reward_non_null_ratio_min": 0.97,
            "mean_episode_len_min": 48,
            "max_trajectory_repeat": 6,
            "domain": {"alttp-vanilla": 1400, "oos": 400, "xref": 150},
            "mode": {"trace": 260, "debug": 90, "author": 70},
            "effort": {"high": 900, "medium": 500, "low": 200},
        },
    },
}


TRAJECTORY_ID_FIELDS = ("trajectory_id", "trajectory", "trajectoryid", "traj_id", "traj")
REWARD_FIELDS = ("reward", "trajectory_reward", "reward_value", "final_reward")
EPISODE_LENGTH_FIELDS = ("trajectory_length", "episode_length", "episode_len", "num_steps", "steps")


@dataclass
class SplitReport:
    split: str
    total: int
    counts: dict[str, int] = field(default_factory=dict)
    missing_metadata: int = 0
    unique_repair_targets: int = 0
    max_repair_repeats: int = 0
    unique_ratio: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "split": self.split,
            "total": self.total,
            "counts": self.counts,
            "missing_metadata": self.missing_metadata,
            "unique_repair_targets": self.unique_repair_targets,
            "max_repair_repeats": self.max_repair_repeats,
            "unique_ratio": self.unique_ratio,
        }


@dataclass
class PPOReport:
    split: str
    total: int
    missing_metadata: int = 0
    missing_trajectory_id: int = 0
    unique_trajectories: int = 0
    max_trajectory_repeat: int = 0
    rewards_present: int = 0
    rewards_parsed: int = 0
    reward_min: float | None = None
    reward_max: float | None = None
    reward_sum: float = 0.0
    reward_count: int = 0
    episode_len_count: int = 0
    episode_len_sum: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        reward_ratio = self.rewards_present / self.total if self.total else 0.0
        mean_reward = self.reward_sum / self.reward_count if self.reward_count else 0.0
        mean_episode_len = self.episode_len_sum / self.episode_len_count if self.episode_len_count else 0.0
        return {
            "split": self.split,
            "total": self.total,
            "missing_metadata": self.missing_metadata,
            "missing_trajectory_id": self.missing_trajectory_id,
            "unique_trajectories": self.unique_trajectories,
            "max_trajectory_repeat": self.max_trajectory_repeat,
            "rewards_present": self.rewards_present,
            "rewards_parsed": self.rewards_parsed,
            "reward_non_null_ratio": reward_ratio,
            "reward_min": self.reward_min,
            "reward_max": self.reward_max,
            "mean_reward": mean_reward,
            "episode_len_count": self.episode_len_count,
            "mean_episode_len": mean_episode_len,
        }


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_num, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON in {path} line {line_num}: {exc}") from exc
    return rows


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        text = str(value).strip()
        if not text:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def _extract_field(metadata: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if name in metadata:
            return metadata[name]
    return None


def _summarize_split(rows: list[dict[str, Any]], split: str, bucket: str = "pair_source") -> SplitReport:
    report = SplitReport(split=split, total=len(rows))
    if not rows:
        return report

    profile_counts: Counter[str] = Counter()
    repair_ids: Counter[str] = Counter()

    for row in rows:
        metadata = row.get("_metadata", {})
        if not isinstance(metadata, dict) or not metadata:
            report.missing_metadata += 1
            continue

        value = metadata.get(bucket)
        if value:
            profile_counts[str(value)] += 1

        repair_id = metadata.get("repair_target_id")
        if repair_id:
            repair_ids[str(repair_id)] += 1

    report.counts = dict(profile_counts)
    if repair_ids:
        total_ids = sum(repair_ids.values())
        report.unique_repair_targets = len(repair_ids)
        report.max_repair_repeats = max(repair_ids.values())
        report.unique_ratio = report.unique_repair_targets / total_ids

    return report


def _summarize_bucket(rows: list[dict[str, Any]], field_name: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        metadata = row.get("_metadata", {})
        if not isinstance(metadata, dict):
            continue
        value = metadata.get(field_name)
        if isinstance(value, str) and value.strip():
            counts[value] += 1
    return dict(counts)


def _summarize_ppo_split(rows: list[dict[str, Any]], split: str) -> PPOReport:
    report = PPOReport(split=split, total=len(rows))
    if not rows:
        return report

    trajectory_counts: Counter[str] = Counter()

    for row in rows:
        metadata = row.get("_metadata", {})
        if not isinstance(metadata, dict) or not metadata:
            report.missing_metadata += 1
            continue

        trajectory_id = _extract_field(metadata, TRAJECTORY_ID_FIELDS)
        if trajectory_id:
            trajectory_counts[str(trajectory_id)] += 1
        else:
            report.missing_trajectory_id += 1

        reward = _extract_field(metadata, REWARD_FIELDS)
        if reward is not None:
            report.rewards_present += 1
            parsed_reward = _coerce_float(reward)
            if parsed_reward is not None:
                report.rewards_parsed += 1
                report.reward_sum += parsed_reward
                report.reward_count += 1
                if report.reward_min is None or parsed_reward < report.reward_min:
                    report.reward_min = parsed_reward
                if report.reward_max is None or parsed_reward > report.reward_max:
                    report.reward_max = parsed_reward

        episode_len = _extract_field(metadata, EPISODE_LENGTH_FIELDS)
        parsed_len = _coerce_float(episode_len)
        if parsed_len is not None:
            report.episode_len_sum += parsed_len
            report.episode_len_count += 1

    report.unique_trajectories = len(trajectory_counts)
    report.max_trajectory_repeat = max(trajectory_counts.values(), default=0)
    return report


def _collect_rows(dataset_dir: Path) -> dict[str, list[dict[str, Any]]]:
    splits = {}
    for split in ("train", "val", "test"):
        path = dataset_dir / f"{split}.jsonl"
        if not path.exists():
            raise FileNotFoundError(f"missing split file: {path}")
        splits[split] = _load_jsonl(path)
    return splits


def _check_thresholds(
    split: str,
    bucket_counts: dict[str, int],
    profile: str,
    threshold: dict[str, int],
    errors: list[str],
) -> None:
    minimum = threshold.get(profile)
    if minimum is None:
        return
    have = bucket_counts.get(profile, 0)
    if have < minimum:
        errors.append(f"{split}: {profile} has {have} < {minimum} required ({profile} bucket)")


def _check_ppo(
    train_rows: list[dict[str, Any]],
    thresholds: dict[str, Any],
    errors: list[str],
    warnings: list[str],
) -> tuple[PPOReport, dict[str, dict[str, int]]]:
    report = _summarize_ppo_split(train_rows, "train")

    if report.unique_trajectories < thresholds["trajectory_min"]:
        errors.append(
            f"train: unique trajectory_id count {report.unique_trajectories} < "
            f"{thresholds['trajectory_min']} required"
        )

    reward_ratio = report.rewards_present / report.total if report.total else 0.0
    if reward_ratio < thresholds["reward_non_null_ratio_min"]:
        errors.append(
            f"train: reward coverage ratio {reward_ratio:.1%} < "
            f"{thresholds['reward_non_null_ratio_min']:.1%}"
        )
    if report.rewards_present > report.rewards_parsed:
        warnings.append(
            f"train: rewards present but not all numeric; parsed "
            f"{report.rewards_parsed}/{report.rewards_present}"
        )

    if report.max_trajectory_repeat > thresholds["max_trajectory_repeat"]:
        warnings.append(
            f"train: trajectory_id max repeat {report.max_trajectory_repeat} > "
            f"{thresholds['max_trajectory_repeat']} (watch over-reliance on repeats)"
        )

    if report.episode_len_count > 0:
        mean_episode_len = report.episode_len_sum / report.episode_len_count
        if mean_episode_len < thresholds["mean_episode_len_min"]:
            warnings.append(
                f"train: mean episode length {mean_episode_len:.1f} < "
                f"target {thresholds['mean_episode_len_min']} for long-context repair traces"
            )
    else:
        warnings.append("train: episode length metadata unavailable; cannot check long-context minimum")

    domain_counts = _summarize_bucket(train_rows, "domain")
    mode_counts = _summarize_bucket(train_rows, "mode")
    effort_counts = _summarize_bucket(train_rows, "effort")

    bucket_counts = {
        "domain": domain_counts,
        "mode": mode_counts,
        "effort": effort_counts,
    }

    for value in thresholds["domain"]:
        _check_thresholds("train", domain_counts, value, thresholds["domain"], errors)
    for value in thresholds["mode"]:
        _check_thresholds("train", mode_counts, value, thresholds["mode"], errors)
    for value in thresholds["effort"]:
        _check_thresholds("train", effort_counts, value, thresholds["effort"], errors)

    return report, bucket_counts


def check_dataset(
    dataset_dir: Path,
    algorithm: str,
    phase: str,
) -> tuple[bool, list[str], list[str], dict[str, Any]]:
    if algorithm not in DEFAULT_THRESHOLDS:
        raise ValueError(f"unknown algorithm '{algorithm}'")
    if phase not in DEFAULT_THRESHOLDS[algorithm]:
        raise ValueError(f"unknown phase '{phase}' for algorithm '{algorithm}'")

    thresholds = DEFAULT_THRESHOLDS[algorithm][phase]
    splits = _collect_rows(dataset_dir)
    all_errors: list[str] = []
    all_warnings: list[str] = []

    train_rows = splits["train"]
    val_rows = splits["val"]
    test_rows = splits["test"]

    if len(train_rows) < thresholds["train_min"]:
        all_errors.append(f"train rows {len(train_rows)} below minimum {thresholds['train_min']}")
    if len(val_rows) < thresholds["val_min"]:
        all_errors.append(f"val rows {len(val_rows)} below minimum {thresholds['val_min']}")
    if len(test_rows) < thresholds["test_min"]:
        all_errors.append(f"test rows {len(test_rows)} below minimum {thresholds['test_min']}")

    report = {
        "dataset_dir": str(dataset_dir),
        "algorithm": algorithm,
        "phase": phase,
        "thresholds": thresholds,
        "splits": {},
        "bucket_counts": {},
    }

    if algorithm == "dpo":
        pair_report = _summarize_split(train_rows, "train", "pair_source")
        val_report = _summarize_split(val_rows, "val", "pair_source")
        test_report = _summarize_split(test_rows, "test", "pair_source")
        report["splits"]["train"] = pair_report.to_dict()
        report["splits"]["val"] = val_report.to_dict()
        report["splits"]["test"] = test_report.to_dict()

        pair_counts = _summarize_bucket(train_rows, "pair_source")
        domain_counts = _summarize_bucket(train_rows, "domain")
        mode_counts = _summarize_bucket(train_rows, "mode")
        effort_counts = _summarize_bucket(train_rows, "effort")
        report["bucket_counts"] = {
            "pair_source": pair_counts,
            "domain": domain_counts,
            "mode": mode_counts,
            "effort": effort_counts,
        }

        for split_name, rows in (("train", train_rows), ("val", val_rows), ("test", test_rows)):
            if split_name == "train":
                split_report = pair_report
            elif split_name == "val":
                split_report = val_report
            else:
                split_report = test_report
            missing_pct = split_report.missing_metadata / len(rows) if rows else 1.0
            if missing_pct > thresholds["max_missing_metadata_pct"]:
                all_errors.append(
                    f"{split_name}: missing _metadata ratio {missing_pct:.1%} "
                    f"above max {thresholds['max_missing_metadata_pct']:.1%}"
                )

        if pair_report.total:
            if pair_report.unique_ratio < thresholds["min_unique_ratio"]:
                all_warnings.append(
                    f"train unique repair_target_id ratio {pair_report.unique_ratio:.1%} "
                    f"below target {thresholds['min_unique_ratio']:.1%}; may over-represent repeats"
                )
            if pair_report.max_repair_repeats > thresholds["max_duplicate"]:
                all_warnings.append(
                    f"train repair_target_id max repeat {pair_report.max_repair_repeats} "
                    f"above target {thresholds['max_duplicate']} (dedupe or rebalance required)"
                )

        for source in thresholds["pair_source"]:
            _check_thresholds("train", pair_counts, source, thresholds["pair_source"], all_errors)
        for source in thresholds["domain"]:
            _check_thresholds("train", domain_counts, source, thresholds["domain"], all_errors)
        for source in thresholds["mode"]:
            _check_thresholds("train", mode_counts, source, thresholds["mode"], all_errors)
        for source in thresholds["effort"]:
            _check_thresholds("train", effort_counts, source, thresholds["effort"], all_errors)
    else:
        ppo_report, bucket_counts = _check_ppo(train_rows, thresholds, all_errors, all_warnings)
        report["splits"]["train"] = ppo_report.to_dict()
        report["splits"]["val"] = _summarize_ppo_split(val_rows, "val").to_dict()
        report["splits"]["test"] = _summarize_ppo_split(test_rows, "test").to_dict()
        report["bucket_counts"] = bucket_counts

        for split_name, rows in (("train", train_rows), ("val", val_rows), ("test", test_rows)):
            split_dict = report["splits"][split_name]
            missing_pct = split_dict["missing_metadata"] / len(rows) if rows else 1.0
            if missing_pct > thresholds["max_missing_metadata_pct"]:
                all_errors.append(
                    f"{split_name}: missing _metadata ratio {missing_pct:.1%} "
                    f"above max {thresholds['max_missing_metadata_pct']:.1%}"
                )

    if not all_errors:
        return True, all_errors, all_warnings, report
    return False, all_errors, all_warnings, report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate Zelda RLHF dataset against policy thresholds.")
    parser.add_argument("dataset_dir", type=Path, help="Directory containing train.jsonl, val.jsonl, test.jsonl")
    parser.add_argument(
        "--algorithm",
        choices=("dpo", "ppo"),
        default="dpo",
        help="Validation family: dpo pairs or ppo trajectories",
    )
    parser.add_argument(
        "--phase",
        choices=("pilot", "production"),
        default="pilot",
        help="Validation phase threshold set (default: pilot)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON report and exit status only.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as failures (defaults to warnings allowed).",
    )
    return parser.parse_args()


def _print_report_text(
    dataset_dir: Path,
    phase: str,
    algorithm: str,
    ok: bool,
    errors: list[str],
    warnings: list[str],
    report: dict[str, Any],
) -> None:
    print(f"dataset: {dataset_dir}")
    print(f"algorithm: {algorithm}")
    print(f"phase: {phase}")
    print(f"result: {'PASS' if ok else 'FAIL'}")
    print("\ncounts:")
    print(f"  train={report['splits']['train']['total']} val={report['splits']['val']['total']} test={report['splits']['test']['total']}")
    print(f"  missing_metadata: train={report['splits']['train']['missing_metadata']}")
    if algorithm == "dpo":
        print(f"  unique_train_repair_targets: {report['splits']['train']['unique_repair_targets']}")
        print(f"  train_repair_target_repeat_max: {report['splits']['train']['max_repair_repeats']}")
        print(f"  train_unique_ratio: {report['splits']['train']['unique_ratio']:.1%}")
    else:
        print(f"  unique_train_trajectories: {report['splits']['train']['unique_trajectories']}")
        print(f"  train_reward_non_null_ratio: {report['splits']['train']['reward_non_null_ratio']:.1%}")
        if report["splits"]["train"]["mean_reward"] is not None:
            print(f"  train_mean_reward: {report['splits']['train']['mean_reward']:.3f}")
        if report["splits"]["train"]["reward_min"] is not None and report["splits"]["train"]["reward_max"] is not None:
            print(f"  reward_range: {report['splits']['train']['reward_min']} -> {report['splits']['train']['reward_max']}")
        if report["splits"]["train"]["mean_episode_len"]:
            print(f"  train_mean_episode_len: {report['splits']['train']['mean_episode_len']:.1f}")
    print("\nbucket minima:")
    for name, values in report["bucket_counts"].items():
        if values:
            print(f"  {name}: {values}")
    if warnings:
        print("\nWARNINGS:")
        for warning in warnings:
            print(f"  - {warning}")
    if errors:
        print("\nFAILURES:")
        for err in errors:
            print(f"  - {err}")


def main() -> int:
    args = parse_args()
    ok, errors, warnings, report = check_dataset(
        args.dataset_dir.expanduser().resolve(),
        args.algorithm,
        args.phase,
    )
    if args.strict and warnings:
        errors.extend(warnings)
        warnings = []

    passed = ok and not warnings if args.strict else ok
    if args.json:
        payload = {
            "pass": passed,
            "errors": errors,
            "warnings": warnings,
            "report": report,
        }
        print(json.dumps(payload, indent=2))
    else:
        _print_report_text(
            args.dataset_dir,
            args.phase,
            args.algorithm,
            passed,
            errors,
            warnings,
            report,
        )

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
