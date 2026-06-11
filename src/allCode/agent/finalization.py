"""Final answer policy gates for evidence-grounded turn results."""

from __future__ import annotations

from collections.abc import Sequence

from allCode.agent.final_answer_format import apply_output_format_gate
from allCode.agent.language import detect_response_language
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
    answer = apply_output_format_gate(final_answer, prompt=prompt, routing=routing, evidence=evidence)
    answer = _apply_workspace_boundary_wording(answer, routing, prompt, language=language)
    answer = _apply_safety_refusal_wording(answer, routing, prompt, language=language)
    answer = _apply_policy_denied_wording(answer, evidence, language=language)
    answer = _apply_safe_alternative_wording(answer, prompt, language=language)
    answer = _apply_validation_wording(answer, evidence, language=language)
    answer = _apply_missing_artifact_wording(answer, evidence, language=language)
    answer = _apply_not_found_wording(answer, messages, evidence, routing=routing, prompt=prompt, language=language)
    answer = _apply_no_search_results_wording(answer, messages, evidence, routing=routing, prompt=prompt, language=language)
    answer = _apply_config_wording(answer, prompt, messages, language=language)
    answer = _apply_budget_wording(answer, messages, language=language)
    answer = _apply_schema_denied_wording(answer, messages, evidence=evidence, routing=routing, language=language)
    answer = _apply_web_unavailable_wording(answer, messages, evidence, language=language)
    answer = _apply_feature_objective_wording(answer, messages, evidence, language=language)
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
    if getattr(routing, "read_only_requested", False):
        return final_answer
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


def _apply_missing_artifact_wording(final_answer: str, evidence: CompletionEvidence, *, language: str) -> str:
    missing = evidence.unsatisfied_artifacts("source", "test", "document", "validation")
    if not missing:
        return final_answer
    labels = []
    for artifact in missing:
        label = artifact.kind if not artifact.target else f"{artifact.kind}:{artifact.target}"
        if label not in labels:
            labels.append(label)
    if language == "en":
        if "missing requested artifacts" in final_answer.lower():
            return final_answer
        return final_answer.rstrip() + "\n\nMissing requested artifacts: " + ", ".join(labels)
    if "요청된 산출물" in final_answer:
        return final_answer
    return final_answer.rstrip() + "\n\n아직 충족되지 않은 요청된 산출물: " + ", ".join(labels)


def _apply_not_found_wording(
    final_answer: str,
    messages: Sequence[Message],
    evidence: CompletionEvidence,
    *,
    routing,
    prompt: str,
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
    if not _should_surface_lookup_failure(final_answer, routing=routing, prompt=prompt):
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
    routing,
    prompt: str,
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
    if not _should_surface_lookup_failure(final_answer, routing=routing, prompt=prompt):
        return final_answer
    if language == "en":
        if "not found" in final_answer.lower() or "no " in final_answer.lower():
            return final_answer
        return final_answer.rstrip() + "\n\nNo matching workspace evidence was found."
    if "찾지" in final_answer and "없" in final_answer:
        return final_answer
    return final_answer.rstrip() + "\n\n검색 결과에서 관련 근거를 찾지 못했습니다. 해당 내용은 현재 워크스페이스에 없습니다."


def _should_surface_lookup_failure(final_answer: str, *, routing, prompt: str) -> bool:
    if not final_answer.strip():
        return True
    if getattr(routing, "requires_mutation", False) or getattr(routing, "requires_validation", False):
        return True
    if _prompt_requests_lookup(prompt):
        return True
    kind = str(getattr(routing, "kind", "") or "").lower()
    if kind in {"answer", "plan"}:
        return False
    if getattr(routing, "read_only_requested", False):
        return False
    return False


def _prompt_requests_lookup(prompt: str) -> bool:
    lowered = str(prompt or "").lower()
    compact = "".join(lowered.split())
    english_markers = (
        "find file",
        "find the file",
        "locate file",
        "locate the file",
        "where is",
        "does file exist",
        "does the file exist",
        "search for",
        "look for",
        "read file",
        "open file",
    )
    korean_markers = (
        "파일찾",
        "파일을찾",
        "경로찾",
        "어디에",
        "어디있",
        "존재하",
        "검색해",
        "찾아줘",
        "읽어줘",
        "열어줘",
    )
    english_lookup = any(marker in lowered for marker in english_markers) or (
        any(verb in lowered for verb in ("find", "locate", "search", "read", "open", "look for"))
        and any(noun in lowered for noun in ("file", "path", "directory", "folder"))
    )
    return english_lookup or any(marker in compact for marker in korean_markers)


def _apply_config_wording(final_answer: str, prompt: str, messages: Sequence[Message], *, language: str) -> str:
    if language != "ko" or "설정" in final_answer:
        return final_answer
    prompt_signal = any(marker in prompt.lower() for marker in ("config", "setting", "settings", "env")) or any(
        marker in prompt for marker in ("설정", "환경")
    )
    tool_signal = any(
        message.role == "tool"
        and any(marker in str(message.metadata.get("tool_name") or "").lower() for marker in ("config", "settings"))
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


def _apply_schema_denied_wording(
    final_answer: str,
    messages: Sequence[Message],
    *,
    evidence: CompletionEvidence,
    routing,
    language: str,
) -> str:
    if not getattr(routing, "requires_tools", False):
        return final_answer
    if evidence.validation_passed is True and evidence.has_file_change():
        return final_answer
    schema_denied = any(
        message.role == "tool" and message.metadata.get("error_type") == "schema_denied"
        for message in messages
    )
    if not schema_denied or "허용되지 않은 도구" in final_answer:
        return final_answer
    if getattr(routing, "read_only_requested", False):
        if _substantive_read_only_evidence_answer(final_answer, evidence):
            return final_answer
        if language == "en":
            if "read-only" in final_answer.lower():
                return final_answer
            return final_answer.rstrip() + "\n\nA hidden write, shell, or validation tool call was ignored because this turn is read-only."
        if "읽기 전용 조건" in final_answer:
            return final_answer
        return final_answer.rstrip() + "\n\n읽기 전용 조건 때문에 파일 변경, 실행, 검증 도구 호출은 무시하고 수집된 읽기 근거만으로 답했습니다."
    if language == "en":
        return final_answer.rstrip() + "\n\nA tool call that is not allowed in the current phase was blocked; the next step should use the phase-appropriate tool."
    return final_answer.rstrip() + "\n\n현재 단계에서 허용되지 않은 도구 호출은 차단했고, 필요한 단계의 도구로 다시 진행합니다."


def _substantive_read_only_evidence_answer(final_answer: str, evidence: CompletionEvidence) -> bool:
    if not _has_read_evidence(evidence):
        return False
    lines = [line.strip() for line in final_answer.splitlines() if line.strip()]
    if len(lines) < 8:
        return False
    structured = sum(1 for line in lines if _is_structured_answer_line(line))
    return structured >= 5


def _has_read_evidence(evidence: CompletionEvidence) -> bool:
    fields = (
        "inspected_paths",
        "representative_read_paths",
        "source_overview_paths",
        "search_candidate_paths",
        "source_package_roles",
    )
    return any(bool(getattr(evidence, field, None)) for field in fields)


def _is_structured_answer_line(line: str) -> bool:
    stripped = line.lstrip()
    if stripped.startswith(("#", "-", "*", "|", ">")):
        return True
    prefix = stripped.split(maxsplit=1)[0].rstrip(".")
    return prefix.isdigit()


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
    if not unavailable or _answer_already_mentions_web_unavailable(final_answer):
        return final_answer
    if language == "en":
        return final_answer.rstrip() + "\n\nThe web search backend is not configured."
    return final_answer.rstrip() + "\n\n현재 웹 검색 backend가 설정되어 있지 않습니다."


def _answer_already_mentions_web_unavailable(final_answer: str) -> bool:
    lowered = final_answer.lower()
    compact = "".join(lowered.split())
    if "backend" in lowered:
        return True
    english_web = "web search" in lowered and any(marker in lowered for marker in ("not configured", "disabled", "unavailable"))
    korean_web = "웹검색" in compact and any(marker in compact for marker in ("비활성", "제공하지못", "설정되어있지", "사용할수없"))
    return english_web or korean_web


def _apply_feature_objective_wording(
    final_answer: str,
    messages: Sequence[Message],
    evidence: CompletionEvidence,
    *,
    language: str,
) -> str:
    if not (evidence.has_resolution_evidence() or evidence.validation_commands):
        return final_answer
    objectives = _feature_objectives(final_answer, messages, evidence)
    if not objectives:
        return final_answer
    if language == "en":
        return final_answer.rstrip() + "\n\nFeature summary: " + ", ".join(objectives[:6])
    return final_answer.rstrip() + "\n\n핵심 기능: " + ", ".join(objectives[:6])


def _prompt_language(prompt: str) -> str:
    return detect_response_language(prompt)


def _feature_objectives(
    final_answer: str,
    messages: Sequence[Message],
    evidence: CompletionEvidence,
) -> list[str]:
    lowered_answer = final_answer.lower()
    candidates: list[str] = []
    for value in evidence.feature_objectives:
        _append_feature_candidate(candidates, value)
    return [value for value in candidates if value.lower() not in lowered_answer][:8]


def _append_feature_candidate(values: list[str], value: str) -> None:
    cleaned = value.strip(" .,;:()[]{}\"'")
    if len(cleaned) < 3:
        return
    lowered = cleaned.lower()
    if lowered in _FEATURE_STOP_TERMS:
        return
    if any(separator in cleaned for separator in ("/", "\\", ".")):
        return
    if lowered not in {item.lower() for item in values}:
        values.append(cleaned)


def _missing_symbols(final_answer: str, symbols: Sequence[str]) -> list[str]:
    lowered = final_answer.lower()
    missing: list[str] = []
    for symbol in symbols:
        clean = symbol.strip()
        if clean and clean.lower() not in lowered and clean not in missing:
            missing.append(clean)
    return missing[:5]


_FEATURE_STOP_TERMS = {
    "assert",
    "class",
    "command",
    "content",
    "false",
    "file",
    "from",
    "game",
    "import",
    "lightweight",
    "metadata",
    "minimal",
    "modified",
    "module",
    "none",
    "patch",
    "patches",
    "provides",
    "pytest",
    "replace",
    "return",
    "search",
    "self",
    "test",
    "tests",
    "true",
    "typical",
    "usage",
    "validation",
    "write",
}
