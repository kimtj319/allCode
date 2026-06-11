"""Prompt constraint extraction that does not decide the route kind."""

from __future__ import annotations

import re

from pydantic import Field

from allCode.agent.prompt_constraint_detection import (
    answer_only_artifact_hint,
    concrete_workspace_paths,
    direct_mutation_command,
    directory_output_hint,
    external_knowledge_suppressed,
    path_hints,
    path_mutation_hint,
)
from allCode.agent.prompt_constraint_terms import (
    ANSWER_REFERENCE_TERMS,
    ARGUMENTATION_FOLLOWUP_TERMS,
    CODE_ARTIFACT_TERMS,
    EXTERNAL_TERMS,
    FORMAT_FOLLOWUP_TERMS,
    MUTATION_TERMS,
    NO_NETWORK_TERMS,
    NO_SHELL_TERMS,
    PROJECT_GENERATION_TERMS,
    PROJECT_OUTPUT_TERMS,
    READ_ONLY_TERMS,
    STDLIB_ONLY_TERMS,
    UNSTABLE_KNOWLEDGE_TERMS,
    VALIDATION_TERMS,
    WORKSPACE_EVIDENCE_TERMS,
    MULTI_ARTIFACT_TERMS,
)
from allCode.agent.prompt_safety import (
    append_marker_if_matched,
    has_any_term,
    read_only_clause_matched,
    read_only_pattern_matched,
    scoped_output_mutation_allowed,
)
from allCode.core.models import CoreModel
from allCode.core.path_patterns import is_followup_reference


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
    directory_output_hint: bool = False
    multi_artifact_hint: bool = False
    project_output_hint: bool = False
    code_artifact_hint: bool = False
    answer_artifact_hint: bool = False
    stdlib_only_requested: bool = False
    unstable_knowledge_hint: bool = False
    path_hints: list[str] = Field(default_factory=list)
    matched_constraints: list[str] = Field(default_factory=list)

    @property
    def primary_target_hint(self) -> str | None:
        return self.path_hints[0] if self.path_hints else None


class PromptConstraintExtractor:
    """Extract safety and context hints without classifying user intent."""

    READ_ONLY_TERMS = READ_ONLY_TERMS
    NO_SHELL_TERMS = NO_SHELL_TERMS
    NO_NETWORK_TERMS = NO_NETWORK_TERMS
    VALIDATION_TERMS = VALIDATION_TERMS
    EXTERNAL_TERMS = EXTERNAL_TERMS
    WORKSPACE_EVIDENCE_TERMS = WORKSPACE_EVIDENCE_TERMS
    MUTATION_TERMS = MUTATION_TERMS
    PROJECT_GENERATION_TERMS = PROJECT_GENERATION_TERMS
    MULTI_ARTIFACT_TERMS = MULTI_ARTIFACT_TERMS
    PROJECT_OUTPUT_TERMS = PROJECT_OUTPUT_TERMS
    CODE_ARTIFACT_TERMS = CODE_ARTIFACT_TERMS
    STDLIB_ONLY_TERMS = STDLIB_ONLY_TERMS
    UNSTABLE_KNOWLEDGE_TERMS = UNSTABLE_KNOWLEDGE_TERMS
    ARGUMENTATION_FOLLOWUP_TERMS = ARGUMENTATION_FOLLOWUP_TERMS
    FORMAT_FOLLOWUP_TERMS = FORMAT_FOLLOWUP_TERMS
    ANSWER_REFERENCE_TERMS = ANSWER_REFERENCE_TERMS

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

        paths = path_hints(prompt)
        read_only_pattern = read_only_pattern_matched(prompt)
        read_only_clause = read_only_clause_matched(prompt)
        scoped_mutation_allowed = scoped_output_mutation_allowed(prompt)
        read_only_requested = (has_any(self.READ_ONLY_TERMS) or read_only_pattern) and not scoped_mutation_allowed
        append_marker_if_matched(matched, "read_only_pattern", condition=read_only_pattern)
        append_marker_if_matched(matched, "read_only_clause", condition=read_only_clause)
        append_marker_if_matched(matched, "scoped_output_mutation_allowed", condition=scoped_mutation_allowed)

        argumentation_followup = has_any(self.ARGUMENTATION_FOLLOWUP_TERMS, compact_match=True)
        format_followup = has_any(self.FORMAT_FOLLOWUP_TERMS, compact_match=True)
        answer_reference = has_any(self.ANSWER_REFERENCE_TERMS, compact_match=True)
        followup_requested = is_followup_reference(prompt)

        mutation_term_seen = has_any(self.MUTATION_TERMS, compact_match=True)
        direct_change = direct_mutation_command(prompt)
        mutation_requested = mutation_term_seen and (direct_change or path_mutation_hint(paths))
        directory_output = directory_output_hint(paths, prompt=prompt, mutation_requested=mutation_requested)
        multi_artifact = has_any(self.MULTI_ARTIFACT_TERMS, compact_match=True)
        project_output = directory_output and has_any(self.PROJECT_OUTPUT_TERMS, compact_match=True)
        code_artifact = has_any(self.CODE_ARTIFACT_TERMS, compact_match=True)
        stdlib_only = has_any(self.STDLIB_ONLY_TERMS, compact_match=True)
        answer_artifact = bool(read_only_requested and code_artifact and answer_only_artifact_hint(prompt))
        if answer_artifact:
            paths = concrete_workspace_paths(paths)
        append_marker_if_matched(matched, "answer_artifact_hint", condition=answer_artifact)
        project_generation = (
            has_any(self.PROJECT_GENERATION_TERMS, compact_match=True)
            or (project_output and multi_artifact and (mutation_requested or direct_change))
        )
        mutation_requested = mutation_requested or bool(project_generation and direct_change)
        unstable_knowledge = has_any(self.UNSTABLE_KNOWLEDGE_TERMS, compact_match=True)
        external_suppressed = external_knowledge_suppressed(prompt)
        append_marker_if_matched(matched, "external_knowledge_suppressed", condition=external_suppressed)
        external_knowledge = (has_any(self.EXTERNAL_TERMS) or unstable_knowledge) and not external_suppressed
        workspace_evidence = has_any(self.WORKSPACE_EVIDENCE_TERMS, compact_match=True)
        if answer_artifact and not paths:
            workspace_evidence = False

        return PromptConstraints(
            read_only_requested=read_only_requested,
            no_shell_requested=has_any(self.NO_SHELL_TERMS),
            no_external_network=has_any(self.NO_NETWORK_TERMS),
            mutation_requested_hint=False if read_only_requested else mutation_requested,
            project_generation_hint=False if read_only_requested else project_generation,
            validation_requested_hint=has_any(self.VALIDATION_TERMS, compact_match=True),
            external_knowledge_hint=external_knowledge,
            followup_requested=followup_requested,
            answer_followup_hint=bool((followup_requested or answer_reference) and (argumentation_followup or format_followup or answer_reference)),
            argumentation_followup_hint=argumentation_followup,
            format_conversion_followup_hint=format_followup,
            workspace_evidence_requested=workspace_evidence,
            directory_output_hint=False if read_only_requested else directory_output,
            multi_artifact_hint=False if read_only_requested else multi_artifact,
            project_output_hint=False if read_only_requested else project_output,
            code_artifact_hint=code_artifact,
            answer_artifact_hint=answer_artifact,
            stdlib_only_requested=stdlib_only,
            unstable_knowledge_hint=unstable_knowledge and not external_suppressed,
            path_hints=paths,
            matched_constraints=matched,
        )
