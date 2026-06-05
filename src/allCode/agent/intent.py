"""Prompt signal extraction for routing."""

from __future__ import annotations

import re
from collections.abc import Sequence

from pydantic import Field

from allCode.core.models import CoreModel
from allCode.core.path_patterns import FOLLOWUP_TERMS, extract_prompt_path
from allCode.agent.prompt_safety import append_marker_if_matched, read_only_clause_matched, read_only_pattern_matched


class IntentSignals(CoreModel):
    read_only_requested: bool = False
    no_shell_requested: bool = False
    no_external_network: bool = False
    modify_action: bool = False
    explicit_change_request: bool = False
    conceptual_question: bool = False
    inspect_action: bool = False
    operate_action: bool = False
    validation_requested: bool = False
    external_knowledge_requested: bool = False
    followup_requested: bool = False
    target_hint: str | None = None
    matched_terms: list[str] = Field(default_factory=list)


class IntentExtractor:
    """Extracts generic prompt signals without project-specific hardcoding."""

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
    MODIFY_TERMS = (
        "implement",
        "create",
        "modify",
        "edit",
        "write",
        "fix",
        "add",
        "update",
        "delete",
        "generate",
        "scaffold",
        "refactor",
        "change",
        "구현",
        "생성",
        "수정",
        "고쳐",
        "추가",
        "작성",
        "삭제",
        "변경",
        "만들",
        "보강",
    )
    INSPECT_TERMS = (
        "inspect",
        "explain",
        "analyze",
        "review",
        "read",
        "find",
        "search",
        "describe",
        "분석",
        "설명",
        "검토",
        "찾아",
        "검색",
        "읽어",
    )
    OPERATE_TERMS = (
        "run",
        "test",
        "build",
        "compile",
        "install",
        "execute",
        "pytest",
        "npm",
        "cargo",
        "gradle",
        "mvn",
        "실행",
        "테스트",
        "빌드",
        "컴파일",
    )
    EXTERNAL_TERMS = (
        "latest",
        "current",
        "today",
        "search the web",
        "look up",
        "검색해서",
        "최신",
        "현재",
        "오늘",
        "공개 문서",
    )

    CONCEPTUAL_TERMS = (
        "why",
        "what",
        "how",
        "explain",
        "describe",
        "tell me",
        "reason",
        "benefit",
        "drawback",
        "difference",
        "compare",
        "concept",
        "왜",
        "이유",
        "무엇",
        "뭐",
        "어떤",
        "어떻게",
        "설명",
        "알려줘",
        "중요",
        "개념",
        "차이",
        "장점",
        "단점",
        "필요",
        "역할",
    )
    ENGLISH_CHANGE_COMMAND = re.compile(
        r"^\s*(?:please\s+)?"
        r"(?:implement|create|modify|edit|write|fix|add|update|delete|generate|scaffold|refactor|change)\b"
        r"|(?:can|could|would)\s+you\s+"
        r"(?:implement|create|modify|edit|write|fix|add|update|delete|generate|scaffold|refactor|change)\b",
        re.IGNORECASE,
    )
    KOREAN_CHANGE_COMMAND = re.compile(
        r"(?:구현|생성|수정|변경|추가|작성|삭제|보강|고쳐|만들)(?:해\s*줘|해줘|해주세요|하라|해라|하시오|하자|해야|어\s*줘|어줘|줘)"
    )
    KOREAN_CHANGE_CONNECTIVE = re.compile(
        r"(?:구현|생성|수정|변경|추가|작성|삭제|보강|고쳐|만들)(?:하고|해서|하여)"
    )
    KOREAN_TRAILING_COMMAND = re.compile(
        r"(?:실행|테스트|검증)(?:해\s*줘|해줘|해주세요|하라|해라|하시오)"
    )
    KOREAN_OPERATE_COMMAND = re.compile(
        r"(?:실행|테스트|검증|빌드|컴파일)(?:해\s*줘|해줘|해주세요|하라|해라|하시오)"
    )
    ENGLISH_OPERATE_COMMAND = re.compile(
        r"^\s*(?:please\s+)?(?:run|execute|rerun|build|compile|install)\b"
        r"|(?:can|could|would)\s+you\s+(?:run|execute|rerun|build|compile|install)\b"
        r"|\b(?:run|execute|rerun)\s+(?:the\s+)?(?:tests?|pytest|npm|cargo|gradle|mvn|build|compile)\b",
        re.IGNORECASE,
    )
    GENERATION_MARKERS = (
        "create a project",
        "generate project",
        "new project",
        "scaffold",
        "bootstrap",
        "프로젝트 생성",
        "새 프로젝트",
        "프로젝트를 생성",
        "프로젝트를 만들어",
    )

    def extract(self, prompt: str) -> IntentSignals:
        lowered = prompt.lower()
        matched: list[str] = []

        def has_any(terms: Sequence[str]) -> bool:
            found = [term for term in terms if term.lower() in lowered]
            matched.extend(found)
            return bool(found)

        target_hint = self._extract_target_hint(prompt)
        modify_term_found = has_any(self.MODIFY_TERMS)
        conceptual_question = self._has_conceptual_question(lowered)
        read_only_pattern = read_only_pattern_matched(prompt)
        read_only_clause = read_only_clause_matched(prompt)
        read_only_requested = has_any(self.READ_ONLY_TERMS) or read_only_pattern
        append_marker_if_matched(matched, "read_only_pattern", condition=read_only_pattern)
        append_marker_if_matched(matched, "read_only_clause", condition=read_only_clause)
        explicit_change_request = self._has_explicit_change_request(
            prompt=prompt,
            lowered=lowered,
            target_hint=target_hint,
            modify_term_found=modify_term_found,
        )
        if read_only_requested:
            explicit_change_request = False
        validation_requested = self._has_validation_request(prompt, lowered)
        return IntentSignals(
            read_only_requested=read_only_requested,
            no_shell_requested=has_any(self.NO_SHELL_TERMS),
            no_external_network=has_any(self.NO_NETWORK_TERMS),
            modify_action=explicit_change_request,
            explicit_change_request=explicit_change_request,
            conceptual_question=conceptual_question,
            inspect_action=has_any(self.INSPECT_TERMS),
            operate_action=self._has_operate_action(
                prompt=prompt,
                lowered=lowered,
                validation_requested=validation_requested,
            ),
            validation_requested=validation_requested,
            external_knowledge_requested=has_any(self.EXTERNAL_TERMS),
            followup_requested=has_any(FOLLOWUP_TERMS),
            target_hint=target_hint,
            matched_terms=matched,
        )

    def _extract_target_hint(self, prompt: str) -> str | None:
        return extract_prompt_path(prompt)

    def _has_conceptual_question(self, lowered: str) -> bool:
        return any(term in lowered for term in self.CONCEPTUAL_TERMS)

    def _has_validation_request(self, prompt: str, lowered: str) -> bool:
        if any(term in lowered for term in ("pytest", "validate", "validation", "run tests", "run the tests", "tests")):
            return True
        if re.search(r"\b(?:run|execute|rerun)\s+(?:the\s+)?tests?\b", lowered):
            return True
        compact_prompt = prompt.replace(" ", "")
        return any(term in compact_prompt for term in ("테스트", "테스트까지", "테스트실행", "테스트를실행", "검증", "재검증"))

    def _has_operate_action(self, *, prompt: str, lowered: str, validation_requested: bool) -> bool:
        if validation_requested:
            return True
        if self.ENGLISH_OPERATE_COMMAND.search(prompt):
            return True
        if re.search(r"\b(?:pytest|npm|cargo|gradle|mvn)\b", lowered):
            return True
        compact_prompt = prompt.replace(" ", "")
        return bool(self.KOREAN_OPERATE_COMMAND.search(compact_prompt))

    def _has_explicit_change_request(
        self,
        *,
        prompt: str,
        lowered: str,
        target_hint: str | None,
        modify_term_found: bool,
    ) -> bool:
        if not modify_term_found:
            return False
        if any(marker in lowered for marker in self.GENERATION_MARKERS):
            return True
        if self.ENGLISH_CHANGE_COMMAND.search(prompt):
            return True
        compact_prompt = prompt.replace(" ", "")
        if self.KOREAN_CHANGE_COMMAND.search(compact_prompt):
            return True
        if self.KOREAN_CHANGE_CONNECTIVE.search(compact_prompt) and self.KOREAN_TRAILING_COMMAND.search(compact_prompt):
            return True
        if target_hint and not self._has_conceptual_question(lowered):
            return True
        return False
