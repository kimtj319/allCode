"""Web-evidence finalization controls for external-answer loops."""

from __future__ import annotations

from dataclasses import dataclass
from allCode.agent.language import ResponseLanguage
from allCode.agent.web_formatter import (
    WEB_TOOL_NAMES,
    format_web_references_for_answer,
    web_reference_dicts_from_metadata,
)
from allCode.core.models import Message
from allCode.core.result import CompletionEvidence


@dataclass(frozen=True)
class WebEvidenceSummary:
    successful_observations: int
    unavailable_observations: int
    evidence_items: list[dict[str, str]]

    @property
    def total_observations(self) -> int:
        return self.successful_observations + self.unavailable_observations

    @property
    def has_any_observation(self) -> bool:
        return self.total_observations > 0


def route_uses_web(routing) -> bool:
    return bool(
        getattr(routing, "requires_external_knowledge", False)
        or "web_search" in set(getattr(routing, "tool_capabilities", set()) or set())
        or getattr(routing, "workflow_hint", "") == "external_research"
    )


def summarize_web_observations(messages: list[Message] | tuple[Message, ...]) -> WebEvidenceSummary:
    successful = 0
    unavailable = 0
    evidence_items: list[dict[str, str]] = []
    for message in messages:
        if message.role != "tool":
            continue
        metadata = message.metadata
        tool_name = str(metadata.get("tool_name") or "")
        if tool_name not in WEB_TOOL_NAMES:
            continue
        evidence_kind = str(metadata.get("evidence_kind") or "")
        if evidence_kind == "web_evidence" and _metadata_evidence_count(metadata) > 0:
            successful += 1
            evidence_items.extend(web_reference_dicts_from_metadata(metadata, limit=max(0, 8 - len(evidence_items))))
        elif (
            metadata.get("error_type") in {"web_search_unavailable", "web_fetch_unavailable"}
            or evidence_kind in {"web_unavailable", "web_error", "web_no_results"}
        ):
            unavailable += 1
    return WebEvidenceSummary(
        successful_observations=successful,
        unavailable_observations=unavailable,
        evidence_items=evidence_items[:8],
    )


def should_request_web_final_answer(
    routing,
    evidence: CompletionEvidence,
    messages: list[Message] | tuple[Message, ...],
    *,
    already_requested: bool,
) -> bool:
    if not route_uses_web(routing):
        return False
    if already_requested:
        return True
    summary = summarize_web_observations(messages)
    if not summary.has_any_observation and not (evidence.web_evidence_queries or evidence.web_unavailable_queries):
        return False
    if summary.successful_observations >= 2:
        return True
    if summary.successful_observations >= 1 and summary.total_observations >= 3:
        return True
    if summary.successful_observations == 0 and (summary.unavailable_observations >= 1 or evidence.web_unavailable_queries):
        return True
    return False


def web_evidence_fallback_answer(
    *,
    prompt: str,
    messages: list[Message] | tuple[Message, ...],
    evidence: CompletionEvidence,
    reason: str,
    response_language: ResponseLanguage,
) -> str:
    summary = summarize_web_observations(messages)
    if response_language == "ko":
        return _korean_fallback(prompt=prompt, summary=summary, evidence=evidence, reason=reason)
    return _english_fallback(prompt=prompt, summary=summary, evidence=evidence, reason=reason)


def _korean_fallback(
    *,
    prompt: str,
    summary: WebEvidenceSummary,
    evidence: CompletionEvidence,
    reason: str,
) -> str:
    lines = [
        "수집한 웹 근거를 기준으로 정리합니다.",
        "",
        f"- 전환 사유: 모델이 최종 답변 대신 추가 도구 호출을 반복해 `{reason}`에서 중단했습니다.",
    ]
    if evidence.web_evidence_queries:
        lines.append("- 근거 수집 쿼리/URL: " + ", ".join(evidence.web_evidence_queries[:4]))
    if evidence.web_unavailable_queries:
        lines.append("- 사용 불가/실패한 쿼리/URL: " + ", ".join(evidence.web_unavailable_queries[:3]))
    if not summary.evidence_items:
        lines.extend(
            [
                "",
                "이번 요청에서 사용할 수 있는 웹 근거를 충분히 확보하지 못했습니다.",
                "현재/최신 정보는 웹 backend 상태를 확인한 뒤 다시 검증해야 합니다.",
            ]
        )
        return "\n".join(lines)
    lines.extend(["", "확인한 근거:"])
    lines.extend(format_web_references_for_answer(summary.evidence_items, response_language="ko", limit=6))
    lines.extend(
        [
            "",
            "요약:",
            "- 위 근거의 제목, URL, 발췌문에 명시된 내용만 확인된 사실로 볼 수 있습니다.",
            "- 최신성이나 세부 버전 정보는 각 공식 릴리즈 노트 또는 제공된 원문 URL에서 최종 확인해야 합니다.",
        ]
    )
    return "\n".join(lines)


def _english_fallback(
    *,
    prompt: str,
    summary: WebEvidenceSummary,
    evidence: CompletionEvidence,
    reason: str,
) -> str:
    lines = [
        "Summary from collected web evidence.",
        "",
        f"- Stop reason: the model kept requesting tools instead of writing the final answer at `{reason}`.",
    ]
    if evidence.web_evidence_queries:
        lines.append("- Evidence queries/URLs: " + ", ".join(evidence.web_evidence_queries[:4]))
    if evidence.web_unavailable_queries:
        lines.append("- Unavailable/failed queries/URLs: " + ", ".join(evidence.web_unavailable_queries[:3]))
    if not summary.evidence_items:
        lines.extend(
            [
                "",
                "No usable web evidence was collected for this request.",
                "Current facts should be verified after checking the web backend configuration.",
            ]
        )
        return "\n".join(lines)
    lines.extend(["", "Evidence observed:"])
    lines.extend(format_web_references_for_answer(summary.evidence_items, response_language="en", limit=6))
    lines.extend(
        [
            "",
            "Summary:",
            "- Treat only the observed titles, URLs, and excerpts above as grounded facts.",
            "- Verify latest or version-specific details against the linked release notes or source pages.",
        ]
    )
    return "\n".join(lines)


def _metadata_evidence_count(metadata: dict[str, object]) -> int:
    try:
        return int(metadata.get("evidence_count") or 0)
    except (TypeError, ValueError):
        return 0
