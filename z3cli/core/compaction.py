"""Conversation compaction for managing small context windows.

When a conversation grows past a model's context budget, the engine
can compact older turns into a summary while preserving the system
prompt and the most recent turns verbatim. This keeps the active
context lean without forcing the user to manually /reset.

Compaction uses a model to summarize — typically the same model, but
a cloud provider can be used as the summarizer for higher quality.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Protocol

from z3cli.core.provider import CompletionRequest, Provider


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------

# Rough heuristic: ~4 chars per token for English prose. Tool JSON is
# denser (more structural chars), so we bias slightly upward. Good
# enough for budget checks without a real tokenizer dependency.
_CHARS_PER_TOKEN = 3.7


def estimate_tokens(text: str) -> int:
    """Approximate token count for a text blob."""
    if not text:
        return 0
    return max(1, int(len(text) / _CHARS_PER_TOKEN))


def estimate_message_tokens(message: dict) -> int:
    """Approximate token count for a single OpenAI-format message."""
    total = 0
    # Role and structural overhead (~4 tokens per message)
    total += 4
    content = message.get("content")
    if isinstance(content, str):
        total += estimate_tokens(content)
    elif isinstance(content, list):
        # Anthropic-style content blocks — sum each block's text
        for block in content:
            if isinstance(block, dict):
                text = block.get("text", "") or block.get("content", "")
                if isinstance(text, str):
                    total += estimate_tokens(text)
                # Tool input JSON
                input_data = block.get("input")
                if input_data is not None:
                    total += estimate_tokens(json.dumps(input_data))
    for tc in message.get("tool_calls", []) or []:
        fn = tc.get("function", {})
        total += estimate_tokens(fn.get("name", ""))
        total += estimate_tokens(fn.get("arguments", ""))
    return total


def estimate_messages_tokens(messages: list[dict]) -> int:
    """Total approximate token count for a message list."""
    return sum(estimate_message_tokens(m) for m in messages)


# ---------------------------------------------------------------------------
# Compaction configuration & result
# ---------------------------------------------------------------------------

@dataclass
class CompactionPolicy:
    """Rules for when and how to compact a conversation.

    Attributes:
        context_budget: Target maximum tokens for the conversation. When
            the running estimate exceeds `threshold_ratio * context_budget`,
            compaction triggers.
        threshold_ratio: Fraction of budget to trigger compaction at.
            Default 0.75 leaves room for the next response.
        keep_recent_turns: How many recent user/assistant turn pairs to
            preserve verbatim. Tool calls count toward their parent turn.
        keep_system: Whether to preserve the system message untouched.
        summarizer_temperature: Temperature for the summarization call.
        summarizer_max_tokens: Max tokens for the summary output.
    """
    context_budget: int = 16384
    threshold_ratio: float = 0.75
    keep_recent_turns: int = 3
    keep_system: bool = True
    summarizer_temperature: float = 0.2
    summarizer_max_tokens: int = 1024


@dataclass
class CompactionResult:
    """Outcome of a compaction pass."""
    compacted: bool = False
    summary: str = ""
    messages_before: int = 0
    messages_after: int = 0
    tokens_before: int = 0
    tokens_after: int = 0
    replaced_count: int = 0
    reason: str = ""


# ---------------------------------------------------------------------------
# Summarizer interface
# ---------------------------------------------------------------------------

class Summarizer(Protocol):
    """Callable that takes messages and returns a compact summary string."""

    async def summarize(self, messages: list[dict], instruction: str) -> str:
        ...


class ProviderSummarizer:
    """Summarize using any Provider (same model, a local lightweight one, or cloud).

    The default prompt asks for a structured recap so downstream tool
    calls retain context about prior state (files touched, decisions made,
    intermediate results) rather than just a narrative summary.
    """

    DEFAULT_INSTRUCTION = (
        "You are summarizing a prior conversation so it can be compressed. "
        "Produce a dense, structured recap that preserves:\n"
        "- Key decisions and conclusions reached\n"
        "- Files, symbols, or addresses that were inspected or modified\n"
        "- Tool results that informed later reasoning (cite tool name + outcome)\n"
        "- Open questions or TODOs the conversation left unresolved\n"
        "- User preferences or constraints stated during the conversation\n\n"
        "Do NOT include conversational filler. Write in compact Markdown. "
        "Aim for under 400 words unless the conversation was very long."
    )

    def __init__(
        self,
        provider: Provider,
        model_id: str,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ):
        self._provider = provider
        self._model_id = model_id
        self._max_tokens = max_tokens
        self._temperature = temperature

    async def summarize(
        self,
        messages: list[dict],
        instruction: str = "",
    ) -> str:
        """Run the summarizer over messages and return the summary text."""
        transcript = _render_transcript(messages)
        user_prompt = (
            "## Prior conversation\n\n"
            f"{transcript}\n\n"
            "## Task\n\nProduce the recap as instructed."
        )
        request = CompletionRequest(
            model_id=self._model_id,
            messages=[{"role": "user", "content": user_prompt}],
            system=instruction or self.DEFAULT_INSTRUCTION,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            tools=None,
            tool_choice="",
        )
        chunks: list[str] = []
        async for chunk in self._provider.stream(request):
            if chunk.content and chunk.content.text:
                chunks.append(chunk.content.text)
        return "".join(chunks).strip()


def _render_transcript(messages: list[dict]) -> str:
    """Render a message list as a human-readable transcript for summarization."""
    lines: list[str] = []
    for msg in messages:
        role = msg.get("role", "?")
        content = msg.get("content")
        header = f"### {role}"
        if role == "tool":
            tool_id = msg.get("tool_call_id", "")
            if tool_id:
                header = f"### tool result ({tool_id})"
        lines.append(header)
        if isinstance(content, str) and content.strip():
            lines.append(content.strip())
        for tc in msg.get("tool_calls", []) or []:
            fn = tc.get("function", {})
            name = fn.get("name", "?")
            args = fn.get("arguments", "")
            lines.append(f"[tool call: {name}({args})]")
        lines.append("")
    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# Compactor
# ---------------------------------------------------------------------------

class ConversationCompactor:
    """Decides when to compact and produces a reduced message list."""

    def __init__(
        self,
        policy: CompactionPolicy | None = None,
        summarizer: Summarizer | None = None,
    ):
        self._policy = policy or CompactionPolicy()
        self._summarizer = summarizer

    @property
    def policy(self) -> CompactionPolicy:
        return self._policy

    def set_policy(self, policy: CompactionPolicy) -> None:
        self._policy = policy

    def set_summarizer(self, summarizer: Summarizer) -> None:
        self._summarizer = summarizer

    def should_compact(self, messages: list[dict]) -> bool:
        """Return True if the message list exceeds the policy threshold."""
        budget = self._policy.context_budget
        if budget <= 0:
            return False
        threshold = int(budget * self._policy.threshold_ratio)
        return estimate_messages_tokens(messages) >= threshold

    def _split_window(
        self, messages: list[dict],
    ) -> tuple[list[dict], list[dict], list[dict]]:
        """Split messages into (system, to_compact, to_keep) segments."""
        system: list[dict] = []
        body = list(messages)
        if self._policy.keep_system and body and body[0].get("role") == "system":
            system.append(body.pop(0))

        # Walk from the end, counting user/assistant turns (turn = user → assistant,
        # with any tool calls/results attached to the assistant side).
        keep_turns = max(0, self._policy.keep_recent_turns)
        kept_tail: list[dict] = []
        turns_kept = 0
        i = len(body) - 1
        while i >= 0 and turns_kept < keep_turns:
            # Walk back over one turn: pull everything up to and including
            # the previous user message.
            segment: list[dict] = []
            # Collect trailing assistant / tool / system messages until we hit a user
            while i >= 0 and body[i].get("role") != "user":
                segment.insert(0, body[i])
                i -= 1
            # Include the user message itself if found
            if i >= 0 and body[i].get("role") == "user":
                segment.insert(0, body[i])
                i -= 1
                turns_kept += 1
            if not segment:
                break
            kept_tail = segment + kept_tail

        to_compact = body[: len(body) - len(kept_tail)]
        return system, to_compact, kept_tail

    async def compact(
        self,
        messages: list[dict],
        *,
        force: bool = False,
    ) -> tuple[list[dict], CompactionResult]:
        """Produce a compacted message list.

        If compaction is not needed (and not forced), returns the input
        unchanged with `compacted=False` in the result.
        """
        before_tokens = estimate_messages_tokens(messages)
        before_count = len(messages)

        if not force and not self.should_compact(messages):
            return messages, CompactionResult(
                compacted=False,
                messages_before=before_count,
                messages_after=before_count,
                tokens_before=before_tokens,
                tokens_after=before_tokens,
                reason="below threshold",
            )

        system, to_compact, to_keep = self._split_window(messages)

        if not to_compact:
            return messages, CompactionResult(
                compacted=False,
                messages_before=before_count,
                messages_after=before_count,
                tokens_before=before_tokens,
                tokens_after=before_tokens,
                reason="nothing to compact",
            )

        if self._summarizer is None:
            return messages, CompactionResult(
                compacted=False,
                messages_before=before_count,
                messages_after=before_count,
                tokens_before=before_tokens,
                tokens_after=before_tokens,
                reason="no summarizer configured",
            )

        summary = await self._summarizer.summarize(to_compact, instruction="")
        if not summary.strip():
            return messages, CompactionResult(
                compacted=False,
                messages_before=before_count,
                messages_after=before_count,
                tokens_before=before_tokens,
                tokens_after=before_tokens,
                reason="empty summary",
            )

        compact_msg = {
            "role": "assistant",
            "content": f"[Compacted recap of {len(to_compact)} earlier messages]\n\n{summary}",
        }
        new_messages = system + [compact_msg] + to_keep
        after_tokens = estimate_messages_tokens(new_messages)

        return new_messages, CompactionResult(
            compacted=True,
            summary=summary,
            messages_before=before_count,
            messages_after=len(new_messages),
            tokens_before=before_tokens,
            tokens_after=after_tokens,
            replaced_count=len(to_compact),
            reason="threshold exceeded" if not force else "manual compaction",
        )
