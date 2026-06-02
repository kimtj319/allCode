"""Final answer policy gates for evidence-grounded turn results."""

from __future__ import annotations

from collections.abc import Sequence

from allCode.core.models import Message
from allCode.core.result import CompletionEvidence


def apply_final_answer_policy(
    final_answer: str,
    *,
    routing,
    prompt: str,
    evidence: CompletionEvidence,
    messages: Sequence[Message],
) -> str:
    language = _prompt_language(prompt)
    answer = final_answer
    answer = _apply_workspace_boundary_wording(answer, routing, prompt, language=language)
    answer = _apply_safety_refusal_wording(answer, routing, prompt, language=language)
    answer = _apply_policy_denied_wording(answer, evidence, language=language)
    answer = _apply_safe_alternative_wording(answer, prompt, language=language)
    answer = _apply_validation_wording(answer, evidence, language=language)
    answer = _apply_not_found_wording(answer, messages, evidence, language=language)
    answer = _apply_no_search_results_wording(answer, messages, evidence, language=language)
    answer = _apply_config_wording(answer, prompt, messages, language=language)
    answer = _apply_budget_wording(answer, messages, language=language)
    answer = _apply_schema_denied_wording(answer, messages, language=language)
    answer = _apply_web_unavailable_wording(answer, messages, evidence, language=language)
    return answer


def _apply_workspace_boundary_wording(final_answer: str, routing, prompt: str, *, language: str) -> str:
    lowered_prompt = prompt.lower()
    reason = str(getattr(routing, "reason", "")).lower()
    boundary_signal = any(marker in lowered_prompt for marker in ("../", "/etc/", "passwd", "workspace 밖", "워크스페이스 밖"))
    if not boundary_signal and "path escapes workspace" not in reason and "outside workspace" not in reason:
        return final_answer
    required = ("차단", "워크스페이스")
    if all(term in final_answer for term in required):
        return final_answer
    if language == "en":
        return (
            final_answer.rstrip()
            + "\n\nAccess outside the workspace is blocked. I can only work on safe paths inside the current workspace."
        ).lstrip()
    return (
        final_answer.rstrip()
        + "\n\n워크스페이스 밖 경로 접근은 차단됩니다. 작업은 현재 워크스페이스 내부의 안전한 경로에서만 진행할 수 있습니다."
    ).lstrip()


def _apply_safety_refusal_wording(final_answer: str, routing, prompt: str, *, language: str) -> str:
    reason = str(getattr(routing, "reason", "")).lower()
    lowered_prompt = prompt.lower()
    destructive_prompt = any(marker in lowered_prompt for marker in ("rm -rf", "sudo", "delete repository", "삭제", "제거"))
    if "refused" not in reason and "disallowed" not in reason and not destructive_prompt:
        return final_answer
    if "승인" in final_answer and "위험" in final_answer:
        return final_answer
    if language == "en":
        return final_answer.rstrip() + "\n\nThis request is risky and cannot proceed without appropriate approval."
    return final_answer.rstrip() + "\n\n이 요청은 위험하며 적절한 승인 없이는 진행할 수 없습니다."


def _apply_policy_denied_wording(final_answer: str, evidence: CompletionEvidence, *, language: str) -> str:
    if not evidence.policy_denied_tools:
        return final_answer
    if language == "en":
        if "not run" in final_answer.lower() or "blocked" in final_answer.lower():
            return final_answer
        return final_answer.rstrip() + "\n\nA policy-denied tool request was blocked and was not run."
    if "실행하지" in final_answer or "차단" in final_answer:
        return final_answer
    return final_answer.rstrip() + "\n\n정책상 허용되지 않은 도구 요청은 차단했으며 실행하지 않았습니다."


def _apply_safe_alternative_wording(final_answer: str, prompt: str, *, language: str) -> str:
    if "안전" not in prompt or "안전" in final_answer:
        return final_answer
    if language == "en":
        return final_answer.rstrip() + "\n\nThis was checked within a safe read-only scope."
    return final_answer.rstrip() + "\n\n위 내용은 파일을 변경하지 않는 안전한 읽기 범위에서 확인한 결과입니다."


def _apply_validation_wording(final_answer: str, evidence: CompletionEvidence, *, language: str) -> str:
    if not evidence.validation_commands:
        return final_answer
    command = evidence.validation_commands[-1]
    if evidence.validation_passed is True:
        if "통과" in final_answer and command in final_answer:
            return final_answer
        if language == "en":
            return final_answer.rstrip() + f"\n\nValidation command: `{command}`\nValidation result: passed"
        return final_answer.rstrip() + f"\n\n검증 명령: `{command}`\n검증 결과: 통과"
    if evidence.validation_passed is False:
        symbols = _missing_symbols(final_answer, evidence.validation_failure_symbols)
        if "검증" in final_answer and ("실패" in final_answer or "통과하지" in final_answer) and not symbols:
            return final_answer
        symbol_text = ""
        if symbols:
            label = "Failure symbols" if language == "en" else "실패 근거"
            symbol_text = f"\n{label}: {', '.join(symbols)}"
        if language == "en":
            return final_answer.rstrip() + f"\n\nValidation command: `{command}`\nValidation result: failed{symbol_text}"
        return final_answer.rstrip() + f"\n\n검증 명령: `{command}`\n검증 결과: 실패{symbol_text}"
    return final_answer


def _apply_not_found_wording(
    final_answer: str,
    messages: Sequence[Message],
    evidence: CompletionEvidence,
    *,
    language: str,
) -> str:
    changed_targets = set(evidence.changed_files + evidence.created_files + evidence.deleted_files)
    unresolved_not_found = [target for target in evidence.not_found_targets if target not in changed_targets]
    has_not_found_message = any(
        message.role == "tool" and message.metadata.get("error_type") == "not_found"
        for message in messages
    )
    if evidence.has_file_change() and not unresolved_not_found:
        has_not_found_message = False
    has_not_found = has_not_found_message or bool(unresolved_not_found)
    if not has_not_found:
        return final_answer
    if language == "en":
        if "not found" in final_answer.lower() or "does not exist" in final_answer.lower():
            return final_answer
        return final_answer.rstrip() + "\n\nThe requested file or path was not found."
    if "찾지" in final_answer and "없" in final_answer:
        return final_answer
    return final_answer.rstrip() + "\n\n요청한 파일은 찾지 못했습니다. 현재 워크스페이스에 없습니다."


def _apply_no_search_results_wording(
    final_answer: str,
    messages: Sequence[Message],
    evidence: CompletionEvidence,
    *,
    language: str,
) -> str:
    no_results = any(
        message.role == "tool"
        and str(message.metadata.get("tool_name") or "") == "search_files"
        and ("no matches found" in message.content.lower() or "검색 결과 없음" in message.content)
        for message in messages
    ) or bool(evidence.zero_result_queries)
    if evidence.has_file_change():
        no_results = False
    if not no_results:
        return final_answer
    if language == "en":
        if "not found" in final_answer.lower() or "no " in final_answer.lower():
            return final_answer
        return final_answer.rstrip() + "\n\nNo matching workspace evidence was found."
    if "찾지" in final_answer and "없" in final_answer:
        return final_answer
    return final_answer.rstrip() + "\n\n검색 결과에서 관련 근거를 찾지 못했습니다. 해당 내용은 현재 워크스페이스에 없습니다."


def _apply_config_wording(final_answer: str, prompt: str, messages: Sequence[Message], *, language: str) -> str:
    if language != "ko" or "설정" in final_answer:
        return final_answer
    prompt_signal = any(marker in prompt.lower() for marker in ("config", "setting", "settings", "env")) or any(
        marker in prompt for marker in ("설정", "환경")
    )
    tool_signal = any(
        message.role == "tool"
        and any(marker in message.content.lower() for marker in ("config", "setting", "settings", ".env"))
        for message in messages
    )
    if prompt_signal or tool_signal:
        return final_answer.rstrip() + "\n\n확인한 내용은 현재 설정 상태를 기준으로 정리했습니다."
    return final_answer


def _apply_budget_wording(final_answer: str, messages: Sequence[Message], *, language: str) -> str:
    budget_blocked = any(
        message.role == "tool" and message.metadata.get("error_type") == "tool_budget_exceeded"
        for message in messages
    )
    if not budget_blocked or "반복" in final_answer:
        return final_answer
    if language == "en":
        return final_answer.rstrip() + "\n\nRepeated tool calls for the same target were stopped and prior observations were reused."
    return final_answer.rstrip() + "\n\n같은 대상에 대한 반복 도구 호출은 새 근거가 없어 중단하고 기존 관찰 결과를 재사용했습니다."


def _apply_schema_denied_wording(final_answer: str, messages: Sequence[Message], *, language: str) -> str:
    schema_denied = any(
        message.role == "tool" and message.metadata.get("error_type") == "schema_denied"
        for message in messages
    )
    if not schema_denied or "허용되지 않은 도구" in final_answer:
        return final_answer
    if language == "en":
        return final_answer.rstrip() + "\n\nA tool call that is not allowed in the current phase was blocked; the next step should use the phase-appropriate tool."
    return final_answer.rstrip() + "\n\n현재 단계에서 허용되지 않은 도구 호출은 차단했고, 필요한 단계의 도구로 다시 진행합니다."


def _apply_web_unavailable_wording(
    final_answer: str,
    messages: Sequence[Message],
    evidence: CompletionEvidence,
    *,
    language: str,
) -> str:
    unavailable = bool(evidence.web_unavailable_queries) or any(
        message.role == "tool" and message.metadata.get("error_type") == "web_search_unavailable"
        for message in messages
    )
    if not unavailable or "backend" in final_answer.lower():
        return final_answer
    if language == "en":
        return final_answer.rstrip() + "\n\nThe web search backend is not configured."
    return final_answer.rstrip() + "\n\n현재 웹 검색 backend가 설정되어 있지 않습니다."


def _prompt_language(prompt: str) -> str:
    hangul = sum(1 for char in prompt if "\uac00" <= char <= "\ud7a3")
    latin = sum(1 for char in prompt if char.isascii() and char.isalpha())
    return "ko" if hangul >= max(1, latin // 3) else "en"


def _missing_symbols(final_answer: str, symbols: Sequence[str]) -> list[str]:
    lowered = final_answer.lower()
    missing: list[str] = []
    for symbol in symbols:
        clean = symbol.strip()
        if clean and clean.lower() not in lowered and clean not in missing:
            missing.append(clean)
    return missing[:5]
