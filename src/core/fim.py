"""Fill-In-the-Middle prompt template helpers.

The vscode-z3cli extension builds these prompts client-side for the hot
path. The cold-path `complete` JSON-RPC handler uses these helpers when
the caller passed prefix+suffix instead of a fully-formed prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class FimTemplate:
    prefix_token: str
    suffix_token: str
    middle_token: str
    default_stops: tuple[str, ...]


QWEN_DEFAULT = FimTemplate(
    prefix_token="<|fim_prefix|>",
    suffix_token="<|fim_suffix|>",
    middle_token="<|fim_middle|>",
    default_stops=("<|endoftext|>", "<|fim_pad|>", "<|file_separator|>", "<|repo_name|>"),
)

QWEN_CODER = FimTemplate(
    prefix_token="<|fim_prefix|>",
    suffix_token="<|fim_suffix|>",
    middle_token="<|fim_middle|>",
    default_stops=("<|endoftext|>", "<|fim_pad|>", "<|file_separator|>"),
)

STARCODER = FimTemplate(
    prefix_token="<fim_prefix>",
    suffix_token="<fim_suffix>",
    middle_token="<fim_middle>",
    default_stops=("<file_sep>", "<|endoftext|>"),
)


_MODEL_TEMPLATE_PATTERNS: tuple[tuple[re.Pattern[str], FimTemplate], ...] = (
    (re.compile(r"navi|farore|nayru|qwen3?\.5", re.IGNORECASE), QWEN_DEFAULT),
    (re.compile(r"qwen3?-coder|oracle-coder", re.IGNORECASE), QWEN_CODER),
    (re.compile(r"oracle", re.IGNORECASE), QWEN_DEFAULT),
    (re.compile(r"starcoder|deepseek-coder", re.IGNORECASE), STARCODER),
)


def pick_template(model: str) -> FimTemplate:
    for pattern, template in _MODEL_TEMPLATE_PATTERNS:
        if pattern.search(model or ""):
            return template
    return QWEN_DEFAULT


def build_fim_prompt(prefix: str, suffix: str, model: str) -> str:
    template = pick_template(model)
    return f"{template.prefix_token}{prefix}{template.suffix_token}{suffix}{template.middle_token}"


def default_stops(model: str, extra: list[str] | tuple[str, ...] = ()) -> list[str]:
    template = pick_template(model)
    seen: list[str] = []
    for token in (*template.default_stops, *extra):
        if token and token not in seen:
            seen.append(token)
    return seen
