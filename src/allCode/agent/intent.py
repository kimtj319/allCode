"""Prompt signal extraction for routing."""

from __future__ import annotations

import re
from collections.abc import Sequence

from pydantic import Field

from allCode.core.models import CoreModel
from allCode.core.path_patterns import FOLLOWUP_TERMS, extract_prompt_path
from allCode.agent.prompt_safety import (
    append_marker_if_matched,
    read_only_clause_matched,
    read_only_pattern_matched,
    scoped_output_mutation_allowed,
)
from allCode.agent.prompt_constraint_detection import answer_only_artifact_hint, external_knowledge_suppressed
from allCode.agent import intent_terms


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
    directory_output_hint: bool = False
    multi_artifact_hint: bool = False
    project_output_hint: bool = False
    unstable_knowledge_hint: bool = False
    answer_artifact_requested: bool = False
    followup_requested: bool = False
    target_hint: str | None = None
    matched_terms: list[str] = Field(default_factory=list)


class IntentExtractor:
    """Extracts generic prompt signals without project-specific hardcoding."""

    READ_ONLY_TERMS = intent_terms.READ_ONLY_TERMS
    NO_SHELL_TERMS = intent_terms.NO_SHELL_TERMS
    NO_NETWORK_TERMS = intent_terms.NO_NETWORK_TERMS
    MODIFY_TERMS = intent_terms.MODIFY_TERMS
    INSPECT_TERMS = intent_terms.INSPECT_TERMS
    OPERATE_TERMS = intent_terms.OPERATE_TERMS
    EXTERNAL_TERMS = intent_terms.EXTERNAL_TERMS
    CONCEPTUAL_TERMS = intent_terms.CONCEPTUAL_TERMS
    ENGLISH_CHANGE_COMMAND = intent_terms.ENGLISH_CHANGE_COMMAND
    KOREAN_CHANGE_COMMAND = intent_terms.KOREAN_CHANGE_COMMAND
    KOREAN_CHANGE_CONNECTIVE = intent_terms.KOREAN_CHANGE_CONNECTIVE
    KOREAN_TRAILING_COMMAND = intent_terms.KOREAN_TRAILING_COMMAND
    KOREAN_OPERATE_COMMAND = intent_terms.KOREAN_OPERATE_COMMAND
    ENGLISH_OPERATE_COMMAND = intent_terms.ENGLISH_OPERATE_COMMAND
    GENERATION_MARKERS = intent_terms.GENERATION_MARKERS
    MULTI_ARTIFACT_TERMS = intent_terms.MULTI_ARTIFACT_TERMS
    PROJECT_OUTPUT_TERMS = intent_terms.PROJECT_OUTPUT_TERMS
    UNSTABLE_KNOWLEDGE_TERMS = intent_terms.UNSTABLE_KNOWLEDGE_TERMS

    def extract(self, prompt: str) -> IntentSignals:
        lowered = prompt.lower()
        matched: list[str] = []

        def has_any(terms: Sequence[str]) -> bool:
            found = [term for term in terms if term.lower() in lowered]
            matched.extend(found)
            return bool(found)

        target_hint = self._extract_target_hint(prompt)
        modify_term_found = has_any(self.MODIFY_TERMS)
        directory_output = self._directory_output_hint(target_hint, prompt=prompt, modify_term_found=modify_term_found)
        multi_artifact = has_any(self.MULTI_ARTIFACT_TERMS)
        project_output = directory_output and has_any(self.PROJECT_OUTPUT_TERMS)
        unstable_knowledge = has_any(self.UNSTABLE_KNOWLEDGE_TERMS)
        external_suppressed = external_knowledge_suppressed(prompt)
        append_marker_if_matched(matched, "external_knowledge_suppressed", condition=external_suppressed)
        conceptual_question = self._has_conceptual_question(lowered)
        read_only_pattern = read_only_pattern_matched(prompt)
        read_only_clause = read_only_clause_matched(prompt)
        scoped_mutation_allowed = scoped_output_mutation_allowed(prompt)
        read_only_requested = (has_any(self.READ_ONLY_TERMS) or read_only_pattern) and not scoped_mutation_allowed
        answer_artifact = bool(read_only_requested and answer_only_artifact_hint(prompt))
        if answer_artifact:
            target_hint = None
        append_marker_if_matched(matched, "read_only_pattern", condition=read_only_pattern)
        append_marker_if_matched(matched, "read_only_clause", condition=read_only_clause)
        append_marker_if_matched(matched, "scoped_output_mutation_allowed", condition=scoped_mutation_allowed)
        append_marker_if_matched(matched, "answer_artifact_hint", condition=answer_artifact)
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
            external_knowledge_requested=(has_any(self.EXTERNAL_TERMS) or unstable_knowledge) and not external_suppressed,
            directory_output_hint=False if read_only_requested else directory_output,
            multi_artifact_hint=False if read_only_requested else multi_artifact,
            project_output_hint=False if read_only_requested else project_output,
            unstable_knowledge_hint=unstable_knowledge and not external_suppressed,
            answer_artifact_requested=answer_artifact,
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
        if target_hint and self._directory_output_hint(target_hint, prompt=prompt, modify_term_found=modify_term_found):
            if self._has_multi_artifact_or_project_signal(prompt):
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

    def _directory_output_hint(self, target_hint: str | None, *, prompt: str, modify_term_found: bool) -> bool:
        if not modify_term_found or not target_hint:
            return False
        normalized = target_hint.strip().strip("`").replace("\\", "/")
        while normalized.startswith("./"):
            normalized = normalized[2:]
        if not normalized or normalized.startswith("../"):
            return False
        name = normalized.rsplit("/", 1)[-1]
        if "." in name:
            return False
        lowered = prompt.lower()
        output_context = any(term in lowered for term in ("output", "under", "inside", "directory", "folder")) or any(
            term in prompt for term in ("아래", "하위", "내부", "디렉터리", "디렉토리", "폴더", "경로")
        )
        return output_context and "/" in normalized

    def _has_multi_artifact_or_project_signal(self, prompt: str) -> bool:
        lowered = prompt.lower()
        return any(term in lowered for term in self.MULTI_ARTIFACT_TERMS) or any(
            term in lowered for term in self.PROJECT_OUTPUT_TERMS
        )
