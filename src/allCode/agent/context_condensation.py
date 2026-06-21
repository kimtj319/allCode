"""Provider-facing context condensation for long model loops."""

from __future__ import annotations

from collections.abc import Sequence
import re

from pydantic import Field

from allCode.core.models import CoreModel, Message
from allCode.memory.redaction import redact_text

MAX_MODEL_CONTEXT_CHARS = 32000
MAX_SUMMARY_CHARS = 6000
MAX_RECENT_MESSAGE_CHARS = 1800
DEFAULT_RECENT_MESSAGES = 10

# Rough chars-per-token for budget estimation (English/code ~3.5-4).
_CHARS_PER_TOKEN = 4
# Fraction of the input window we actually fill, leaving slack for tokenizer
# variance and the model's own framing.
_WINDOW_SAFETY = 0.85


def window_aware_max_chars(
    *,
    context_window_tokens: int,
    max_output_tokens: int,
    default_chars: int = MAX_MODEL_CONTEXT_CHARS,
) -> int:
    """Total outgoing-message char budget derived from the model context window.

    ``condense_messages_for_model`` bounds the WHOLE message list (system prefix
    + body) against this value, so this returns the *total* input budget —
    window minus an output reserve and a safety margin — NOT a body-only budget.
    (A previous version subtracted the system prefix here and then handed the
    result to a consumer that re-counts the prefix, double-charging it and
    truncating the live workspace context far too aggressively.) When the window
    is unknown (``context_window_tokens <= 0``) the fixed legacy budget is used.
    """

    if context_window_tokens and context_window_tokens > 0:
        input_tokens = max(2000, int((context_window_tokens - max_output_tokens) * _WINDOW_SAFETY))
        return input_tokens * _CHARS_PER_TOKEN
    return default_chars

# Strips <think>…</think> reasoning blocks; compiled once since _clean_content
# runs several times per message during every round's context condensation.
_THINK_BLOCK = re.compile(r"(?is)<think\b[^>]*>.*?</think>")


class CondensedContext(CoreModel):
    preserved_constraints: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    tool_observations: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    omitted_message_count: int = 0

    def render(self) -> str:
        lines = ["Condensed prior context:"]
        _extend_section(lines, "Preserved constraints", self.preserved_constraints)
        _extend_section(lines, "Decisions and answers", self.decisions)
        _extend_section(lines, "Tool observations", self.tool_observations)
        _extend_section(lines, "Artifacts", self.artifacts)
        _extend_section(lines, "Failures", self.failures)
        _extend_section(lines, "Open questions", self.open_questions)
        lines.append(f"- Omitted raw message count: {self.omitted_message_count}")
        lines.append("Use this as observable history only. Do not expose hidden reasoning.")
        return "\n".join(lines)


def condense_messages_for_model(
    messages: Sequence[Message],
    *,
    max_chars: int = MAX_MODEL_CONTEXT_CHARS,
    recent_messages: int = DEFAULT_RECENT_MESSAGES,
) -> list[Message]:
    """Return a compact outgoing message view without mutating runtime history."""

    clean_messages = [message for message in messages if not message.metadata.get("context_condensed")]
    if _message_chars(clean_messages) <= max_chars:
        return list(clean_messages)

    system_prefix, body = _split_system_prefix(clean_messages)
    if not body:
        return _bound_message_contents(clean_messages, max_chars=max_chars)

    keep_indexes = _kept_body_indexes(body, recent_messages=recent_messages)
    omitted = [message for index, message in enumerate(body) if index not in keep_indexes]
    condensed = build_condensed_context(omitted)
    summary = Message(
        role="assistant",
        content=_bounded(condensed.render(), MAX_SUMMARY_CHARS),
        metadata={"context_condensed": True},
    )
    rebuilt: list[Message] = [*system_prefix]
    inserted = False
    if not any(message.role == "user" for message in body):
        rebuilt.append(summary)
        inserted = True
    for index, message in enumerate(body):
        if index in keep_indexes:
            rebuilt.append(_compact_recent_message(message))
            if not inserted and message.role == "user":
                rebuilt.append(summary)
                inserted = True
    if not inserted:
        rebuilt.append(summary)
    if _message_chars(rebuilt) > max_chars:
        return _bound_message_contents(rebuilt, max_chars=max_chars)
    return rebuilt


def build_condensed_context(messages: Sequence[Message]) -> CondensedContext:
    context = CondensedContext(omitted_message_count=len(messages))
    for message in messages:
        content = _clean_content(message.content)
        if not content and not message.tool_calls:
            continue
        if message.role == "user":
            _append_unique(context.preserved_constraints, _bounded(content, 700))
            continue
        if message.role == "tool":
            _collect_tool_summary(context, message, content)
            continue
        if message.role == "assistant":
            if message.tool_calls:
                calls = ", ".join(call.name for call in message.tool_calls[:6])
                _append_unique(context.decisions, f"assistant requested tools: {calls}")
            if content:
                target = context.failures if _looks_like_failure(content) else context.decisions
                _append_unique(target, _bounded(content, 700))
            continue
        if message.role == "system" and content:
            _append_unique(context.preserved_constraints, _bounded(content, 700))
    return _bounded_context(context)


def _split_system_prefix(messages: Sequence[Message]) -> tuple[list[Message], list[Message]]:
    index = 0
    while index < len(messages) and messages[index].role == "system":
        index += 1
    return list(messages[:index]), list(messages[index:])


def _kept_body_indexes(body: Sequence[Message], *, recent_messages: int) -> set[int]:
    keep: set[int] = set()
    blocks = _message_blocks(body)
    first_user = next((index for index, message in enumerate(body) if message.role == "user"), None)
    if first_user is not None:
        keep.update(_block_containing(blocks, first_user))
    last_user = next((index for index in range(len(body) - 1, -1, -1) if body[index].role == "user"), None)
    if last_user is not None:
        keep.update(_block_containing(blocks, last_user))
    kept_recent = 0
    for block in reversed(blocks):
        if kept_recent >= max(1, recent_messages):
            break
        keep.update(block)
        kept_recent += len(block)
    return keep


def _message_blocks(body: Sequence[Message]) -> list[list[int]]:
    blocks: list[list[int]] = []
    index = 0
    while index < len(body):
        message = body[index]
        block = [index]
        if message.role == "assistant" and message.tool_calls:
            next_index = index + 1
            while next_index < len(body) and body[next_index].role == "tool":
                block.append(next_index)
                next_index += 1
            blocks.append(block)
            index = next_index
            continue
        blocks.append(block)
        index += 1
    return blocks


def _block_containing(blocks: Sequence[Sequence[int]], target: int) -> list[int]:
    for block in blocks:
        if target in block:
            return list(block)
    return [target]


def _collect_tool_summary(context: CondensedContext, message: Message, content: str) -> None:
    metadata = message.metadata
    name = str(metadata.get("tool_name") or "tool")
    ok = bool(metadata.get("ok"))
    target = _tool_target(metadata)
    status = "ok" if ok else f"failed:{metadata.get('error_type') or 'error'}"
    line = f"{name}"
    if target:
        line += f" {target}"
    if content:
        line += f" -> {status}: {_bounded(content, 450)}"
    else:
        line += f" -> {status}"
    destination = context.failures if not ok or _looks_like_failure(content) else context.tool_observations
    _append_unique(destination, line)
    for field, label in (("created_files", "created"), ("changed_files", "changed"), ("deleted_files", "deleted")):
        for value in metadata.get(field, []):
            _append_unique(context.artifacts, f"{label}: {redact_text(str(value))}")


def _tool_target(metadata: dict[str, object]) -> str:
    observation = metadata.get("observation")
    if isinstance(observation, dict):
        for key in ("target", "summary", "path"):
            value = observation.get(key)
            if value:
                return redact_text(str(value))
    for key in ("target", "file_path"):
        value = metadata.get(key)
        if value:
            return redact_text(str(value))
    return ""


def _compact_recent_message(message: Message) -> Message:
    if message.role == "user":
        return message
    content = _clean_content(message.content) if message.role in {"assistant", "tool"} else message.content
    if len(content) <= MAX_RECENT_MESSAGE_CHARS and content == message.content:
        return message
    return message.model_copy(
        update={
            "content": _bounded(content, MAX_RECENT_MESSAGE_CHARS),
            "metadata": {**message.metadata, "context_recent_truncated": True},
        }
    )


def _bound_message_contents(messages: Sequence[Message], *, max_chars: int) -> list[Message]:
    bounded = list(messages)
    # The first system message is the authoritative system prompt (tool-use
    # constraints, routing/answer guidance). Preserve it from truncation while
    # any other non-user message can still be shrunk; only gut it as a last
    # resort when nothing else is left to cut.
    first_system = next((i for i, m in enumerate(bounded) if m.role == "system"), None)

    def _shrink_one(*, protect_system: bool) -> bool:
        for index, message in enumerate(bounded):
            if message.role == "user":
                continue
            if protect_system and index == first_system:
                continue
            if len(message.content) > 800:
                bounded[index] = message.model_copy(
                    update={
                        "content": _bounded(_clean_content(message.content), 800),
                        "metadata": {**message.metadata, "context_hard_truncated": True},
                    }
                )
                return True
        return False

    while _message_chars(bounded) > max_chars and len(bounded) > 3:
        if _shrink_one(protect_system=True):
            continue
        if _shrink_one(protect_system=False):
            continue
        break
    return bounded


def _bounded_context(context: CondensedContext) -> CondensedContext:
    return context.model_copy(
        update={
            "preserved_constraints": context.preserved_constraints[:8],
            "decisions": context.decisions[:10],
            "tool_observations": context.tool_observations[:14],
            "artifacts": context.artifacts[:12],
            "failures": context.failures[-6:],
            "open_questions": context.open_questions[:6],
        }
    )


def _clean_content(text: str) -> str:
    stripped_blocks = _THINK_BLOCK.sub("", str(text or ""))
    clean_lines: list[str] = []
    for line in stripped_blocks.splitlines():
        lowered = line.strip().lower()
        if not lowered:
            continue
        if lowered.startswith(("reasoning:", "reasoning_delta:", "chain-of-thought:", "<think", "</think")):
            continue
        clean_lines.append(line.rstrip())
    return redact_text("\n".join(clean_lines))


def _looks_like_failure(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in ("traceback", "syntaxerror", "assertionerror", "error:", "failed"))


def _append_unique(items: list[str], value: str) -> None:
    value = value.strip()
    if value and value not in items:
        items.append(value)


def _extend_section(lines: list[str], title: str, items: Sequence[str]) -> None:
    if not items:
        return
    lines.append(f"- {title}:")
    lines.extend(f"  - {item}" for item in items)


def _bounded(text: str, limit: int) -> str:
    compact = "\n".join(line.rstrip() for line in str(text or "").splitlines() if line.strip())
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "\n[truncated]"


def _message_chars(messages: Sequence[Message]) -> int:
    return sum(len(message.content) for message in messages)
