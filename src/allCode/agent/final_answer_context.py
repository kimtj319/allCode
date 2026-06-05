"""Outgoing message compaction for final-answer synthesis calls."""

from __future__ import annotations

from collections.abc import Sequence

from allCode.agent.language import ResponseLanguage, final_answer_request_text
from allCode.core.models import Message

MAX_SYSTEM_CHARS = 5000
MAX_OBSERVATION_CHARS = 9000
MAX_SINGLE_OBSERVATION_CHARS = 900
MAX_TOOL_OBSERVATIONS = 16


def final_answer_call_messages(
    messages: Sequence[Message],
    *,
    response_language: ResponseLanguage,
) -> list[Message]:
    """Return provider-facing messages for final answer generation.

    Some OpenAI-compatible reasoning endpoints produce only reasoning deltas
    when native tool-role history is sent back for final synthesis. For the
    model call only, compact tool observations into assistant text while
    leaving the runtime transcript untouched for fallback summaries and logs.
    """

    if any(message.role == "tool" for message in messages):
        return _compacted_tool_history_messages(messages, response_language=response_language)
    return _bridge_consecutive_user_messages(messages, response_language=response_language)


def _compacted_tool_history_messages(
    messages: Sequence[Message],
    *,
    response_language: ResponseLanguage,
) -> list[Message]:
    system = Message(
        role="system",
        content=_system_content(messages, response_language=response_language),
        metadata={"final_answer_compacted": True},
    )
    original_prompt = _first_user_content(messages)
    final_prompt = _last_user_content(messages) or final_answer_request_text(response_language)
    observation_summary = _tool_observation_summary(messages, response_language=response_language)
    return [
        system,
        Message(role="user", content=original_prompt),
        Message(
            role="assistant",
            content=observation_summary,
            metadata={"final_answer_compacted_observations": True},
        ),
        Message(role="user", content=final_prompt),
    ]


def _bridge_consecutive_user_messages(
    messages: Sequence[Message],
    *,
    response_language: ResponseLanguage,
) -> list[Message]:
    outgoing = list(messages)
    if len(outgoing) >= 2 and outgoing[-1].role == "user" and outgoing[-2].role == "user":
        outgoing.insert(-1, Message(role="assistant", content=_bridge_text(response_language)))
    return outgoing


def _system_content(messages: Sequence[Message], *, response_language: ResponseLanguage) -> str:
    system_parts = [message.content for message in messages if message.role == "system" and message.content]
    base = "\n\n".join(system_parts).strip()
    if len(base) > MAX_SYSTEM_CHARS:
        base = base[:MAX_SYSTEM_CHARS].rstrip() + "\n[system context truncated]"
    guard = (
        "Final synthesis mode: use the compacted tool observations below as evidence. "
        "Do not expose hidden reasoning. Do not call tools. Do not return an empty or reasoning-only response. "
        "Start the visible assistant content immediately with the final answer."
    )
    if response_language == "ko":
        guard = (
            "최종 답변 합성 모드: 아래 압축된 도구 관찰 결과만 근거로 사용하세요. "
            "숨겨진 reasoning/thinking 내용은 노출하지 마세요. 도구를 호출하지 말고, 비어 있거나 reasoning-only인 응답을 반환하지 마세요. "
            "사용자에게 보이는 assistant content의 첫 내용부터 최종 답변을 작성하세요."
        )
    return f"{base}\n\n{guard}".strip()


def _tool_observation_summary(messages: Sequence[Message], *, response_language: ResponseLanguage) -> str:
    header = "Compacted tool observations for final answer:" if response_language == "en" else "최종 답변용 압축 도구 관찰 결과:"
    instruction = (
        "Use these observations as evidence and write a fresh final answer in the next user-requested language."
        if response_language == "en"
        else "이 관찰 결과를 근거로 사용하되, 다음 사용자 요청 언어로 새 최종 답변을 작성하세요."
    )
    lines = [header, instruction]
    used = 0
    count = 0
    for message in messages:
        if message.role != "tool":
            continue
        count += 1
        if count > MAX_TOOL_OBSERVATIONS:
            lines.append("- Additional tool observations were omitted to keep the final synthesis bounded.")
            break
        entry = _format_tool_message(message)
        if used + len(entry) > MAX_OBSERVATION_CHARS:
            lines.append("- Observation summary was truncated to stay within the final-answer context budget.")
            break
        lines.append(entry)
        used += len(entry)
    if count == 0:
        lines.append("- No tool observations were available.")
    return "\n".join(lines)


def _format_tool_message(message: Message) -> str:
    metadata = message.metadata
    tool_name = str(metadata.get("tool_name") or "tool")
    ok = bool(metadata.get("ok"))
    observation = metadata.get("observation")
    target = ""
    if isinstance(observation, dict):
        target = str(observation.get("target") or observation.get("summary") or "")
    if not target:
        target = str(metadata.get("target") or metadata.get("file_path") or "")
    status = "ok" if ok else f"failed:{metadata.get('error_type') or 'error'}"
    prefix = f"- {tool_name}"
    if target:
        prefix = f"{prefix} `{target}`"
    excerpt = _compact_text(message.content)
    if excerpt:
        return f"{prefix} -> {status}\n  {excerpt}"
    return f"{prefix} -> {status}"


def _compact_text(text: str) -> str:
    normalized = "\n".join(line.rstrip() for line in str(text or "").splitlines() if line.strip())
    if len(normalized) <= MAX_SINGLE_OBSERVATION_CHARS:
        return normalized
    return normalized[:MAX_SINGLE_OBSERVATION_CHARS].rstrip() + "\n  [observation truncated]"


def _first_user_content(messages: Sequence[Message]) -> str:
    for message in messages:
        if message.role == "user" and message.content:
            return message.content
    return ""


def _last_user_content(messages: Sequence[Message]) -> str:
    for message in reversed(messages):
        if message.role == "user" and message.content:
            return message.content
    return ""


def _bridge_text(response_language: ResponseLanguage) -> str:
    if response_language == "ko":
        return "확인한 근거를 바탕으로 사용자에게 보이는 최종 답변을 작성하겠습니다."
    return "I will now write the user-visible final answer based on the available evidence."
