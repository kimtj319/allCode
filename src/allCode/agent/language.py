"""Shared response-language detection and localized agent wording."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from allCode.core.models import Message

ResponseLanguage = Literal["ko", "en"]


@dataclass(frozen=True)
class BlockedSummaryLabels:
    title: str
    reason: str
    details: str
    evidence: str
    next_step: str
    success: str
    failure: str


@dataclass(frozen=True)
class GenerationReportLabels:
    title: str
    implementation_location: str
    files: str
    core_functionality: str
    validation: str
    repair: str
    remaining_risks: str
    next_command: str
    no_validation_command: str
    not_executed: str
    no_repair: str
    no_known_risk: str
    evidence_result: str
    succeeded: str
    failed: str
    recorded: str


def detect_response_language(prompt: str) -> ResponseLanguage:
    """Return the user-facing language for final prose.

    Paths, code identifiers, commands, and symbols should stay as written by
    callers. This only controls explanatory prose.
    """

    text = prompt or ""
    hangul = sum(1 for char in text if "\uac00" <= char <= "\ud7a3")
    if hangul:
        # Korean prompts often include ASCII paths and identifiers. One Hangul
        # phrase is enough to keep user-facing prose Korean.
        return "ko"
    return "en"


def response_language_from_messages(messages: Sequence[Message]) -> ResponseLanguage:
    for message in reversed(messages):
        if message.role == "user" and message.content:
            return detect_response_language(message.content)
    return "en"


def normalize_response_language(language: str | None) -> ResponseLanguage:
    return "ko" if language == "ko" else "en"


def language_instruction(language: ResponseLanguage) -> str:
    if language == "ko":
        return (
            "Write the final user-facing explanation in Korean even when tool observations are English. Preserve paths, "
            "commands, code identifiers, symbols, and error names exactly."
        )
    return (
        "Write the final user-facing explanation in English. Preserve paths, "
        "commands, code identifiers, symbols, and error names exactly."
    )


def final_answer_request_text(language: ResponseLanguage) -> str:
    if language == "ko":
        return (
            "최종 답변은 반드시 한국어로만 작성하세요. 섹션 제목과 설명 문장도 한국어로 작성하세요. "
            "관찰한 도구 결과에 근거해서 사용자에게 보이는 assistant content 본문에 최종 답변을 작성하세요. "
            "reasoning, thinking, 분석 채널에만 쓰고 끝내지 마세요. "
            "확인한 근거와 추론한 내용을 구분하고, 완료할 수 없으면 무엇을 확인했는지, "
            "왜 막혔는지, 안전한 다음 단계가 무엇인지 명시하세요. "
            "소스 구조 분석에서는 source_overview의 주요 package role을 누락하지 말고, "
            "probe/read로 확인한 항목과 overview 기반 추론 항목을 구분하세요. "
            "파일 경로, 명령어, 코드 식별자는 원문 그대로 유지하세요."
        )
    return (
        "Write the final answer as user-visible assistant content, grounded in the observed tool results. "
        "Do not stop after writing only to a reasoning, thinking, or analysis channel. "
        "Separate confirmed evidence from inferred roles. If the task cannot be completed, "
        "explicitly say what was checked, why it is blocked, and what safe next step is available. "
        "For source-structure analysis, do not omit major package roles from source_overview; "
        "distinguish probe/read observations from overview-based inferences. "
        "Preserve file paths, commands, and code identifiers exactly."
    )


def blocked_summary_labels(language: ResponseLanguage) -> BlockedSummaryLabels:
    if language == "ko":
        return BlockedSummaryLabels(
            title="요청을 완료하지 못했습니다.",
            reason="차단 사유",
            details="세부 내용",
            evidence="확인한 근거",
            next_step="다음 단계",
            success="성공",
            failure="실패",
        )
    return BlockedSummaryLabels(
        title="The request could not be completed.",
        reason="Block reason",
        details="Details",
        evidence="Evidence checked",
        next_step="Next step",
        success="success",
        failure="failed",
    )


def generation_report_labels(language: ResponseLanguage) -> GenerationReportLabels:
    if language == "ko":
        return GenerationReportLabels(
            title="생성 보고서",
            implementation_location="구현 위치",
            files="생성/수정 파일",
            core_functionality="핵심 기능",
            validation="검증",
            repair="수리",
            remaining_risks="남은 리스크",
            next_command="다음 명령",
            no_validation_command="사용 가능한 검증 명령이 없습니다.",
            not_executed="실행하지 않음.",
            no_repair="수리가 필요하지 않았습니다.",
            no_known_risk="생성된 스캐폴드 내부에서 알려진 잔여 리스크는 없습니다.",
            evidence_result="근거 결과",
            succeeded="성공",
            failed="실패",
            recorded="완료 근거에 기록됨",
        )
    return GenerationReportLabels(
        title="Generation Report",
        implementation_location="Implementation location",
        files="Created/modified files",
        core_functionality="Core functionality",
        validation="Validation",
        repair="Repair",
        remaining_risks="Remaining risks",
        next_command="Next command",
        no_validation_command="No validation command is available.",
        not_executed="Not executed.",
        no_repair="No repair was required.",
        no_known_risk="No known residual risk inside the generated scaffold.",
        evidence_result="Evidence result",
        succeeded="succeeded",
        failed="failed",
        recorded="recorded in completion evidence",
    )
