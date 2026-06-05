"""Helper formatting functions for prompt construction."""

from __future__ import annotations

from collections.abc import Sequence

from allCode.agent.language import ResponseLanguage
from allCode.core.models import Message, ToolResult


def content_with_evidence_bundle(content: str, result: ToolResult) -> str:
    bundle = result.metadata.get("evidence_bundle")
    if not isinstance(bundle, list) or not bundle:
        return content
    lines = [content, "Evidence bundle:"]
    for item in bundle[:10]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        url = str(item.get("url", "")).strip()
        snippet = str(item.get("snippet", "")).strip()
        lines.append(f"- title: {title}")
        if url:
            lines.append(f"  url: {url}")
        if snippet:
            lines.append(f"  snippet: {snippet}")
    return "\n".join(line for line in lines if line)


def tool_results_from_messages(messages: Sequence[Message]) -> list[ToolResult]:
    results: list[ToolResult] = []
    for message in messages:
        if message.role != "tool":
            continue
        results.append(
            ToolResult(
                call_id=message.tool_call_id or "unknown",
                name=str(message.metadata.get("tool_name") or "tool"),
                ok=bool(message.metadata.get("ok")),
                content=message.content,
                error=None if message.metadata.get("ok") else message.content,
                error_type=str(message.metadata.get("error_type") or "") or None,
                metadata=dict(message.metadata),
            )
        )
    return results


def blocked_reason_detail(
    reason: str,
    tool_results: Sequence[ToolResult],
    *,
    response_language: ResponseLanguage = "ko",
) -> str | None:
    if reason == "target_clarification_required" or "clarification" in reason:
        return "The file to modify could not be determined." if response_language == "en" else "수정 대상이 되는 어떤 파일인지 확정되지 않았습니다."
    if any(result.error_type == "not_found" for result in tool_results):
        return "The requested file or path was not found." if response_language == "en" else "요청한 파일이나 경로를 찾지 못했습니다."
    if any(result.error_type in {"approval_required", "policy_denied"} for result in tool_results):
        return "The action requires approval or is blocked by policy." if response_language == "en" else "위험하거나 권한이 필요한 작업이라 승인 없이 실행하지 않았습니다."
    if any(result.error_type in {"tool_loop_detected", "no_progress_detected"} for result in tool_results):
        return "The same tool calls repeated without producing new evidence." if response_language == "en" else "같은 도구 호출이 반복되어 더 진행해도 새 근거가 나오지 않는 상태입니다."
    if any(
        result.error_type in {"patch_ambiguous", "patch_not_found", "patch_invalid_request", "patch_strategy_required"}
        for result in tool_results
    ):
        if response_language == "en":
            return "The patch search block did not uniquely match current file content."
        return "patch_file 검색 블록이 현재 파일 내용과 정확히 일치하지 않아 수리 전에 파일을 다시 확인해야 합니다."
    if any(result.error_type == "invalid_query" for result in tool_results):
        return "The search query was empty, so no workspace search was run." if response_language == "en" else "검색어가 비어 있어 워크스페이스 검색을 실행하지 않았습니다."
    return None


def blocked_next_step(
    reason: str,
    tool_results: Sequence[ToolResult],
    *,
    response_language: ResponseLanguage = "ko",
) -> str:
    if reason == "target_clarification_required" or "clarification" in reason:
        return "Specify the target file or path." if response_language == "en" else "어떤 파일을 수정할지 파일명이나 경로를 지정해 주세요."
    if any(result.error_type == "not_found" for result in tool_results):
        return "Check the missing path or provide the correct file name." if response_language == "en" else "찾지 못한 경로를 확인하거나 올바른 파일명을 지정해 주세요."
    if any(result.error_type in {"approval_required", "policy_denied"} for result in tool_results):
        return "Adjust approval mode or ask for a safer action." if response_language == "en" else "승인이 필요한 작업이면 approval mode를 조정하거나 더 안전한 명령으로 다시 요청해 주세요."
    if any(result.error_type in {"tool_loop_detected", "no_progress_detected"} for result in tool_results):
        if response_language == "en":
            return "Provide a different file, search term, or validation condition."
        return "이미 확인한 결과와 다른 파일, 검색어, 또는 검증 조건을 지정해 주세요."
    if any(result.error_type == "patch_ambiguous" for result in tool_results):
        if response_language == "en":
            return "Read the relevant range again, then repair with a more specific patch_file or write_file."
        return "해당 파일의 관련 범위를 다시 읽은 뒤 더 구체적인 patch_file 또는 write_file로 수리해야 합니다."
    if any(result.error_type == "patch_strategy_required" for result in tool_results):
        if response_language == "en":
            return "Do not repeat the same patch; read the relevant range and switch to a more specific patch_file or write_file."
        return "같은 patch를 반복하지 말고 관련 범위를 read_file로 다시 확인한 뒤 더 구체적인 patch_file 또는 write_file로 전환해야 합니다."
    if any(result.error_type in {"patch_not_found", "patch_invalid_request"} for result in tool_results):
        if response_language == "en":
            return "Read the current file content and retry patch_file using text that actually exists."
        return "현재 파일 내용을 다시 읽은 뒤 실제 존재하는 텍스트를 기준으로 patch_file을 재시도해야 합니다."
    if any(result.error_type == "invalid_query" for result in tool_results):
        if response_language == "en":
            return "Use source_overview, list_tree, or glob_files for inventory, or provide a non-empty search query."
        return "구조 파악에는 source_overview, list_tree, glob_files를 사용하거나 비어 있지 않은 검색어를 지정해야 합니다."
    if response_language == "en":
        return "Provide the needed file name, approval, search term, or validation condition and retry."
    return "필요한 파일명, 승인, 또는 검색/검증 조건을 명확히 지정해 다시 요청해 주세요."
