"""Structural prompt signals used by model routing post-processing."""

from __future__ import annotations

from allCode.agent.prompt_constraints import PromptConstraints


def answer_followup_request(constraints: PromptConstraints, prompt: str) -> bool:
    """Detect follow-ups that revise the prior answer rather than workspace files."""

    if not constraints.followup_requested or constraints.path_hints:
        return False
    if artifact_mutation_followup(prompt):
        return False
    if constraints.answer_followup_hint:
        return True
    lowered = " ".join(prompt.lower().split())
    compact = lowered.replace(" ", "")
    answer_markers = (
        "previous answer",
        "previous response",
        "last answer",
        "last response",
        "your answer",
        "이전 답변",
        "앞선 답변",
        "방금 답변",
        "이전답변",
        "앞선답변",
        "방금답변",
    )
    summary_markers = (
        "do not summarize again",
        "without re-summarizing",
        "don't re-summarize",
        "재요약하지",
        "다시전체재요약하지",
        "전체재요약하지",
    )
    return any(marker in lowered or marker in compact for marker in answer_markers + summary_markers)


def artifact_mutation_followup(prompt: str) -> bool:
    lowered = " ".join(prompt.lower().split())
    compact = lowered.replace(" ", "")
    artifact_markers = (
        "that file",
        "same file",
        "document",
        "report",
        "readme",
        "spec",
        "그파일",
        "해당파일",
        "문서",
        "보고서",
        "기획서",
        "시리즈바이블",
        "파일",
    )
    mutation_markers = ("add", "update", "modify", "edit", "fix", "append", "추가", "수정", "변경", "반영", "보강", "고쳐")
    answer_context_markers = ("대화", "답변", "논리", "주장", "반박", "재반박", "argument", "answer", "conversation")
    has_artifact = any(marker in lowered or marker in compact for marker in artifact_markers)
    has_mutation = any(marker in lowered or marker in compact for marker in mutation_markers)
    answer_context = any(marker in lowered or marker in compact for marker in answer_context_markers)
    return has_artifact and has_mutation and not answer_context


def local_workspace_request(constraints: PromptConstraints) -> bool:
    if constraints.no_external_network or constraints.path_hints:
        return True
    if constraints.external_knowledge_hint:
        explicit_workspace_terms = {
            "actual file search",
            "search files",
            "find in files",
            "read the file",
            "실제 파일 검색",
            "파일 검색",
            "파일을 검색",
            "파일을 읽",
            "directory structure",
            "file layout",
            "file list",
            "repo structure",
            "repository structure",
            "workspace structure",
            "디렉터리 구조",
            "디렉토리 구조",
            "파일 구조",
            "파일 목록",
            "저장소 구조",
            "워크스페이스 구조",
            "현재 디렉터리",
            "현재 디렉토리",
            "현재 폴더",
            "src 내",
            "src 안",
        }
        return any(term in constraints.matched_constraints for term in explicit_workspace_terms)
    return constraints.workspace_evidence_requested
