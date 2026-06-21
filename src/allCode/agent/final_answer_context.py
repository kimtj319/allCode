"""Outgoing message compaction for final-answer synthesis calls."""

from __future__ import annotations

import re
from collections.abc import Sequence

from allCode.agent.final_answer_format import brevity_requested
from allCode.agent.language import ResponseLanguage, final_answer_request_text
from allCode.agent.web_formatter import (
    format_web_tool_observation,
    metadata_has_web_evidence,
    metadata_is_web_unavailable,
    web_citation_guard,
)
from allCode.core.models import Message

MAX_SYSTEM_CHARS = 5000
MAX_OBSERVATION_CHARS = 9000
MAX_SINGLE_OBSERVATION_CHARS = 900
MAX_TOOL_OBSERVATIONS = 16
MAX_EVIDENCE_BRIEF_CHARS = 3500
EVIDENCE_LIMITATION_MARKERS = (
    "남은 한계",
    "Limitations:",
    "관찰하지 못한",
    "관찰하지 않은",
    "확인하지 못한",
    "확인하지 않은",
    "한계",
    "Unobserved",
    "unobserved",
    "Coverage gaps",
    "coverage gaps",
    "Limitations",
    "limitations",
)


def final_answer_call_messages(
    messages: Sequence[Message],
    *,
    response_language: ResponseLanguage,
    evidence_brief: str = "",
) -> list[Message]:
    """Return provider-facing messages for final answer generation.

    Some OpenAI-compatible reasoning endpoints produce only reasoning deltas
    when native tool-role history is sent back for final synthesis. For the
    model call only, compact tool observations into assistant text while
    leaving the runtime transcript untouched for fallback summaries and logs.
    """

    if any(message.role == "tool" for message in messages):
        return _compacted_tool_history_messages(
            messages,
            response_language=response_language,
            evidence_brief=evidence_brief,
        )
    return _bridge_consecutive_user_messages(
        messages,
        response_language=response_language,
        evidence_brief=evidence_brief,
    )


def _compacted_tool_history_messages(
    messages: Sequence[Message],
    *,
    response_language: ResponseLanguage,
    evidence_brief: str = "",
) -> list[Message]:
    system = Message(
        role="system",
        content=_system_content(messages, response_language=response_language),
        metadata={"final_answer_compacted": True},
    )
    original_prompt = _first_user_content(messages)
    final_prompt = _last_user_content(messages) or final_answer_request_text(response_language)
    observation_summary = _tool_observation_summary(
        messages,
        response_language=response_language,
        evidence_brief=evidence_brief,
    )
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
    evidence_brief: str = "",
) -> list[Message]:
    outgoing = list(messages)
    if evidence_brief:
        outgoing.insert(_before_final_user_index(outgoing), _evidence_brief_message(evidence_brief, response_language))
    if not outgoing or outgoing[-1].role != "user":
        outgoing.append(
            Message(
                role="user",
                content=final_answer_request_text(response_language),
            )
        )
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
        "Start the visible assistant content immediately with the final answer. "
        "For source-analysis answers, prefer precise `path:Lx-Ly` or symbol anchors from the evidence brief "
        "for concrete architecture, flow, and module-role claims. If the evidence brief includes an answer synthesis "
        "outline, follow it as the answer plan unless the user requested a stricter output format. "
        "When Package/directory roles are present for a broad source-tree request, include those roles before representative file details. "
        "Report the FINAL verified outcome of the work: if your tests/validation ultimately passed, state plainly that the "
        "task is complete; do NOT describe earlier transient failures, or items you have already fixed, as unresolved, "
        "pending, or remaining work."
    )
    if response_language == "ko":
        guard = (
            "최종 답변 합성 모드: 아래 압축된 도구 관찰 결과만 근거로 사용하세요. "
            "숨겨진 reasoning/thinking 내용은 노출하지 마세요. 도구를 호출하지 말고, 비어 있거나 reasoning-only인 응답을 반환하지 마세요. "
            "사용자에게 보이는 assistant content의 첫 내용부터 최종 답변을 작성하세요. "
            "소스 분석 답변에서는 구체적인 구조, 흐름, 모듈 역할 주장에 대해 근거 brief의 `path:Lx-Ly` 또는 symbol anchor를 우선 사용하세요."
            "근거 brief에 답변 합성 outline이 있으면 사용자가 더 엄격한 출력 형식을 요청하지 않은 한 이를 답변 계획으로 따르세요. "
            "넓은 소스 트리 요청에서 디렉터리/패키지 역할이 제공되면 대표 파일 세부 설명보다 그 역할 요약을 먼저 포함하세요. "
            "최종 검증 상태를 보고하세요: 테스트/검증이 최종적으로 통과했다면 작업이 완료되었다고 분명히 보고하고, "
            "이미 수정한 항목이나 진행 중의 일시적 실패를 미해결·미결·잔여 작업으로 적지 마세요."
        )
    web_guidance = _web_unavailable_guidance(messages, response_language=response_language)
    if web_guidance:
        guard = f"{guard}\n{web_guidance}"
    citation_guidance = web_citation_guard(_has_web_evidence(messages), response_language=response_language)
    if citation_guidance:
        guard = f"{guard}\n{citation_guidance}"
    format_guidance = _output_format_guidance(messages, response_language=response_language)
    if format_guidance:
        guard = f"{guard}\n{format_guidance}"
    return f"{base}\n\n{guard}".strip()


def _tool_observation_summary(
    messages: Sequence[Message],
    *,
    response_language: ResponseLanguage,
    evidence_brief: str = "",
) -> str:
    header = "Compacted tool observations for final answer:" if response_language == "en" else "최종 답변용 압축 도구 관찰 결과:"
    instruction = (
        "Use these observations as evidence and write a fresh final answer in the next user-requested language."
        if response_language == "en"
        else "이 관찰 결과를 근거로 사용하되, 다음 사용자 요청 언어로 새 최종 답변을 작성하세요."
    )
    lines = [header, instruction]
    if evidence_brief:
        lines.extend(["", _evidence_brief_text(evidence_brief, response_language=response_language)])
    used = 0
    count = 0
    for message in messages:
        if message.role != "tool":
            continue
        count += 1
        if count > MAX_TOOL_OBSERVATIONS:
            lines.append("- Additional tool observations were omitted to keep the final synthesis bounded.")
            break
        entry = _format_tool_message(message, response_language=response_language)
        if used + len(entry) > MAX_OBSERVATION_CHARS:
            lines.append("- Observation summary was truncated to stay within the final-answer context budget.")
            break
        lines.append(entry)
        used += len(entry)
    if count == 0:
        lines.append("- No tool observations were available.")
    return "\n".join(lines)


def _evidence_brief_text(evidence_brief: str, *, response_language: ResponseLanguage) -> str:
    header = "Required source-analysis evidence brief:" if response_language == "en" else "반드시 반영할 소스 분석 근거 brief:"
    compacted = _compact_evidence_brief(evidence_brief)
    return f"{header}\n{compacted}".strip()


def _evidence_brief_message(evidence_brief: str, response_language: ResponseLanguage) -> Message:
    return Message(
        role="assistant",
        content=_evidence_brief_text(evidence_brief, response_language=response_language),
        metadata={"final_answer_evidence_brief": True},
    )


def _before_final_user_index(messages: Sequence[Message]) -> int:
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].role == "user":
            return index
    return len(messages)


def _compact_evidence_brief(text: str) -> str:
    normalized = "\n".join(line.rstrip() for line in str(text or "").splitlines() if line.strip())
    if len(normalized) <= MAX_EVIDENCE_BRIEF_CHARS:
        return normalized
    important_tail = _important_evidence_tail(normalized)
    if not important_tail:
        return normalized[:MAX_EVIDENCE_BRIEF_CHARS].rstrip() + "\n[brief truncated]"
    marker = "\n[brief middle truncated]\n"
    important_tail = _compact_important_tail(important_tail, reserved_head_chars=600, marker=marker)
    head_budget = MAX_EVIDENCE_BRIEF_CHARS - len(marker) - len(important_tail)
    return normalized[:head_budget].rstrip() + marker + important_tail.strip()


def _important_evidence_tail(text: str) -> str:
    positions = [text.find(marker) for marker in EVIDENCE_LIMITATION_MARKERS if marker in text]
    positions = [position for position in positions if position >= 0]
    if not positions:
        return ""
    return text[min(positions) :]


def _compact_important_tail(text: str, *, reserved_head_chars: int, marker: str) -> str:
    tail_budget = MAX_EVIDENCE_BRIEF_CHARS - len(marker) - reserved_head_chars
    if len(text) <= tail_budget:
        return text
    tail_marker = "\n[limitation details truncated]\n"
    if tail_budget <= len(tail_marker) + 80:
        return text[:tail_budget].rstrip()
    front_budget = max(120, tail_budget // 2)
    back_budget = tail_budget - front_budget - len(tail_marker)
    if back_budget <= 0:
        return text[:tail_budget].rstrip()
    return text[:front_budget].rstrip() + tail_marker + text[-back_budget:].strip()


def _format_tool_message(message: Message, *, response_language: ResponseLanguage) -> str:
    metadata = message.metadata
    tool_name = str(metadata.get("tool_name") or "tool")
    if metadata_has_web_evidence(metadata) or metadata_is_web_unavailable(metadata):
        return format_web_tool_observation(metadata, response_language=response_language)
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


def _web_unavailable_guidance(messages: Sequence[Message], *, response_language: ResponseLanguage) -> str:
    unavailable = any(
        message.role == "tool"
        and (
            message.metadata.get("error_type") in {"web_search_unavailable", "ExternalSearchNoResults"}
            or message.metadata.get("evidence_kind") in {"web_unavailable", "web_no_results", "web_error"}
        )
        for message in messages
    )
    if not unavailable:
        return ""
    if response_language == "ko":
        return (
            "웹 검색 근거를 확보하지 못한 경우, 현재/최신 수치, 법률, 가격, 시장 데이터는 확정하지 마세요. "
            "확인 가능한 일반 원칙과 추가 검증이 필요한 항목을 분리하고, 웹 검색 backend 미설정 또는 검색 결과 없음의 한계를 명시하세요."
        )
    return (
        "If web evidence was unavailable, do not assert current metrics, legal facts, prices, or market data as verified. "
        "Separate stable general principles from items that need verification, and state the web-backend/no-results limitation."
    )


def _has_web_evidence(messages: Sequence[Message]) -> bool:
    return any(message.role == "tool" and metadata_has_web_evidence(message.metadata) for message in messages)


def _output_format_guidance(messages: Sequence[Message], *, response_language: ResponseLanguage) -> str:
    prompt = _first_user_content(messages)
    sentence_count = _requested_count(prompt, unit_patterns=(r"문장", r"sentence(?:s)?"))
    if sentence_count is not None:
        if response_language == "ko":
            return (
                f"사용자가 정확히 {sentence_count}문장으로 답변하라고 요청했습니다. "
                "제목, bullet, 번호 목록, 추가 섹션을 만들지 말고 사용자에게 보이는 최종 답변을 정확히 그 문장 수로만 작성하세요."
            )
        return (
            f"The user requested exactly {sentence_count} sentence(s). "
            "Do not add headings, bullets, numbered lists, or extra sections; write only that many final-answer sentences."
        )
    line_count = _requested_count(prompt, unit_patterns=(r"줄", r"line(?:s)?"))
    if line_count is not None:
        if response_language == "ko":
            return f"사용자가 정확히 {line_count}줄로 답변하라고 요청했습니다. 제목이나 추가 섹션 없이 정확히 {line_count}줄만 작성하세요."
        return f"The user requested exactly {line_count} line(s). Do not add headings or extra sections; write exactly {line_count} line(s)."
    if brevity_requested(prompt):
        if response_language == "ko":
            return (
                "사용자가 짧고 간결한 답변을 요청했습니다. "
                "필요한 근거만 남기고 최대 3개의 짧은 문장 또는 최대 4개의 짧은 줄로 답하세요. "
                "사용자가 명시적으로 요청하지 않은 추가 섹션, 긴 배경 설명, 마무리 문구는 생략하세요."
            )
        return (
            "The user requested a brief, concise answer. "
            "Keep only necessary evidence and answer in at most 3 short sentences or 4 short lines. "
            "Omit extra sections, long background, and closing filler unless explicitly requested."
        )
    return ""


def _requested_count(prompt: str, *, unit_patterns: tuple[str, ...]) -> int | None:
    text = str(prompt or "")
    for unit in unit_patterns:
        match = re.search(rf"(?P<count>\d+)\s*{unit}", text, flags=re.IGNORECASE)
        if match:
            try:
                return int(match.group("count"))
            except ValueError:
                return None
    if any(re.search(rf"한\s*{unit}", text, flags=re.IGNORECASE) for unit in unit_patterns):
        return 1
    return None


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
