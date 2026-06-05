"""Prompt constraint extraction that does not decide the route kind."""

from __future__ import annotations

import re

from pydantic import Field

from allCode.core.models import CoreModel
from allCode.core.path_patterns import PATH_PATTERN, extract_prompt_path, is_followup_reference
from allCode.agent.prompt_safety import (
    append_marker_if_matched,
    has_any_term,
    read_only_clause_matched,
    read_only_pattern_matched,
)


class PromptConstraints(CoreModel):
    read_only_requested: bool = False
    no_shell_requested: bool = False
    no_external_network: bool = False
    mutation_requested_hint: bool = False
    project_generation_hint: bool = False
    validation_requested_hint: bool = False
    external_knowledge_hint: bool = False
    followup_requested: bool = False
    answer_followup_hint: bool = False
    argumentation_followup_hint: bool = False
    format_conversion_followup_hint: bool = False
    workspace_evidence_requested: bool = False
    path_hints: list[str] = Field(default_factory=list)
    matched_constraints: list[str] = Field(default_factory=list)

    @property
    def primary_target_hint(self) -> str | None:
        return self.path_hints[0] if self.path_hints else None


class PromptConstraintExtractor:
    """Extract safety and context hints without classifying user intent."""

    READ_ONLY_TERMS = (
        "read-only",
        "read only",
        "do not edit",
        "don't edit",
        "no changes",
        "no file changes",
        "수정 금지",
        "변경 금지",
        "파일 변경 금지",
        "수정하지",
        "수정하지 마",
        "수정하지마",
        "변경하지",
        "파일 수정은 하지",
        "파일은 수정하지",
        "절대 수정",
        "읽기만",
        "분석만",
    )
    NO_SHELL_TERMS = (
        "no shell",
        "don't run commands",
        "do not run commands",
        "명령 실행 금지",
        "셸 실행 금지",
        "쉘 실행 금지",
    )
    NO_NETWORK_TERMS = (
        "no network",
        "offline",
        "검색 금지",
        "외부 검색 금지",
        "네트워크 금지",
    )
    VALIDATION_TERMS = (
        "pytest",
        "validate",
        "validation",
        "run tests",
        "run the tests",
        "테스트까지",
        "테스트",
        "tests",
        "test coverage",
        "테스트도",
        "테스트 추가",
        "테스트를 추가",
        "테스트 포함",
        "테스트 실행",
        "테스트를 실행",
        "검증",
        "재검증",
    )
    EXTERNAL_TERMS = (
        "latest",
        "current",
        "today",
        "search the web",
        "look up",
        "공개 문서",
        "최신",
        "현재",
        "오늘",
    )
    WORKSPACE_EVIDENCE_TERMS = (
        "actual file search",
        "search files",
        "find in files",
        "read the file",
        "실제 파일 검색",
        "파일 검색",
        "파일을 검색",
        "파일을 읽",
        "찾아줘",
        "검색으로 찾아",
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
    )
    MUTATION_TERMS = (
        "implement",
        "create",
        "generate",
        "scaffold",
        "write",
        "add",
        "modify",
        "edit",
        "fix",
        "update",
        "refactor",
        "구현",
        "생성",
        "작성",
        "추가",
        "수정",
        "변경",
        "보강",
        "고쳐",
        "만들",
    )
    PROJECT_GENERATION_TERMS = (
        "new project",
        "create a project",
        "generate a project",
        "project skeleton",
        "scaffold project",
        "bootstrap project",
        "새 프로젝트",
        "프로젝트 생성",
        "프로젝트 뼈대",
        "프로젝트를 만들어",
        "프로젝트를 만들",
        "프로젝트를 생성",
    )
    ARGUMENTATION_FOLLOWUP_TERMS = (
        "counterargument",
        "rebuttal",
        "refute",
        "critique",
        "challenge the argument",
        "반박",
        "재반박",
        "반론",
        "비판",
        "논리를 만들",
        "논리를 제시",
        "주장을 검토",
    )
    FORMAT_FOLLOWUP_TERMS = (
        "summarize the conversation",
        "summarize our discussion",
        "turn this into",
        "rewrite as",
        "blog post",
        "article",
        "대화를 요약",
        "전체 대화",
        "요약해",
        "정리해",
        "형태로",
        "기고문",
        "블로그",
        "토론 수업용",
        "체크리스트로",
    )
    ANSWER_REFERENCE_TERMS = (
        "previous answer",
        "previous response",
        "last answer",
        "last response",
        "your answer",
        "앞 답변",
        "앞선 답변",
        "이전 답변",
        "방금 답변",
        "방금 제시",
        "앞서 제시",
        "방금 설명",
    )
    COMMON_WORKSPACE_DIRS = (
        "src",
        "lib",
        "app",
        "apps",
        "packages",
        "tests",
        "test",
        "docs",
        "examples",
    )

    def extract(self, prompt: str) -> PromptConstraints:
        lowered = prompt.lower()
        compact = re.sub(r"\s+", "", prompt)
        matched: list[str] = []

        def has_any(terms, *, compact_match: bool = False) -> bool:
            return has_any_term(
                terms,
                prompt=prompt,
                lowered=lowered,
                compact=compact,
                compact_match=compact_match,
                matched=matched,
            )

        paths = self._path_hints(prompt)
        read_only_pattern = read_only_pattern_matched(prompt)
        read_only_clause = read_only_clause_matched(prompt)
        read_only_requested = has_any(self.READ_ONLY_TERMS) or read_only_pattern
        append_marker_if_matched(matched, "read_only_pattern", condition=read_only_pattern)
        append_marker_if_matched(matched, "read_only_clause", condition=read_only_clause)
        argumentation_followup = has_any(self.ARGUMENTATION_FOLLOWUP_TERMS, compact_match=True)
        format_followup = has_any(self.FORMAT_FOLLOWUP_TERMS, compact_match=True)
        answer_reference = has_any(self.ANSWER_REFERENCE_TERMS, compact_match=True)
        followup_requested = is_followup_reference(prompt)
        mutation_requested = has_any(self.MUTATION_TERMS, compact_match=True)
        project_generation = has_any(self.PROJECT_GENERATION_TERMS, compact_match=True)
        return PromptConstraints(
            read_only_requested=read_only_requested,
            no_shell_requested=has_any(self.NO_SHELL_TERMS),
            no_external_network=has_any(self.NO_NETWORK_TERMS),
            mutation_requested_hint=False if read_only_requested else mutation_requested,
            project_generation_hint=False if read_only_requested else project_generation,
            validation_requested_hint=has_any(self.VALIDATION_TERMS, compact_match=True),
            external_knowledge_hint=has_any(self.EXTERNAL_TERMS),
            followup_requested=followup_requested,
            answer_followup_hint=bool((followup_requested or answer_reference) and (argumentation_followup or format_followup or answer_reference)),
            argumentation_followup_hint=argumentation_followup,
            format_conversion_followup_hint=format_followup,
            workspace_evidence_requested=has_any(self.WORKSPACE_EVIDENCE_TERMS, compact_match=True),
            path_hints=paths,
            matched_constraints=matched,
        )

    def _path_hints(self, prompt: str) -> list[str]:
        paths: list[str] = []
        for match in PATH_PATTERN.finditer(prompt):
            value = match.group("path").lstrip("@")
            if value not in paths:
                paths.append(value)
        first = extract_prompt_path(prompt)
        if first and first not in paths:
            paths.insert(0, first)
        lowered = prompt.lower()
        for directory in self.COMMON_WORKSPACE_DIRS:
            if directory in paths:
                continue
            if re.search(rf"(?<![A-Za-z0-9_.-]){re.escape(directory)}(?![A-Za-z0-9_.-])", lowered):
                paths.append(directory)
        return paths
