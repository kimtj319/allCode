"""Small helpers for final turn wording and metrics."""

from __future__ import annotations

from collections.abc import Sequence

from allCode.agent.prompt_builder import PromptBuilder
from allCode.core.models import Message, ToolResult


def final_answer_for_result(
    prompt_builder: PromptBuilder,
    *,
    finalized_status: str,
    evidence_ready: bool,
    outcome_answer: str,
    error_message: str | None,
    messages: Sequence[Message],
) -> str:
    if evidence_ready or finalized_status == "partial":
        return outcome_answer
    if finalized_status == "failed":
        if outcome_answer.strip():
            if error_message:
                return f"완료로 처리하지 않았습니다: {error_message}\n\n{outcome_answer}"
            return outcome_answer
        return blocked_summary(prompt_builder, messages, error_message or "turn_failed_without_completion_evidence")
    return ""


def blocked_summary(prompt_builder: PromptBuilder, messages: Sequence[Message], reason: str) -> str:
    return prompt_builder.summarize_blocked_turn(
        messages,
        reason=reason,
        last_tool_results=last_tool_results(messages),
    )


def last_tool_results(messages: Sequence[Message]) -> list[ToolResult]:
    results: list[ToolResult] = []
    for message in messages:
        if message.role != "tool":
            continue
        ok = bool(message.metadata.get("ok"))
        results.append(
            ToolResult(
                call_id=message.tool_call_id or "unknown",
                name=str(message.metadata.get("tool_name") or "tool"),
                ok=ok,
                content=message.content if ok else "",
                error=None if ok else message.content,
                error_type=str(message.metadata.get("error_type") or "") or None,
            )
        )
    return results


def message_chars(messages: Sequence[Message]) -> int:
    return sum(len(message.content or "") for message in messages)


def tool_observation_chars(messages: Sequence[Message]) -> int:
    return sum(len(message.content or "") for message in messages if message.role == "tool")


def has_blocking_tool_result(results: Sequence[ToolResult]) -> bool:
    return any(result.error_type in {"tool_loop_detected", "no_progress_detected"} for result in results)
