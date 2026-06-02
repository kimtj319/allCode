"""Standard turn result model."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import Field, model_validator

from allCode.core.models import CoreModel, TokenUsage, ToolCall

CompletionStatus = Literal[
    "not_started",
    "changed",
    "validated",
    "reported",
    "blocked",
]
RecoveryReason = Literal[
    "empty_response",
    "reasoning_only",
    "length_cutoff",
    "tool_loop",
    "slow_stream",
    "stream_timeout",
    "validation_failed",
    "external_tool_failed",
    "no_progress",
]


class ProjectManifest(CoreModel):
    """Session-scoped summary of a generated or discovered project layout."""

    project_root: str = ""
    package_root: str = ""
    entrypoints: list[str] = Field(default_factory=list)
    test_paths: list[str] = Field(default_factory=list)
    validation_commands: list[str] = Field(default_factory=list)
    validation_cwd: str = ""
    last_modified_files: list[str] = Field(default_factory=list)
    language: str = ""
    confidence: float = 0.0

    def candidate_targets(self) -> list[str]:
        seen: list[str] = []
        for value in [
            *self.entrypoints,
            *self.test_paths,
            *self.last_modified_files,
            self.package_root,
            self.project_root,
        ]:
            if value and value not in seen:
                seen.append(value)
        return seen


class DocumentManifest(CoreModel):
    """Session-scoped summary of a generated or edited document artifact."""

    path: str = ""
    title: str = ""
    artifact_kind: str = ""
    section_headings: list[str] = Field(default_factory=list)
    last_requested_changes: list[str] = Field(default_factory=list)
    updated_at_turn_id: str = ""

    def candidate_targets(self) -> list[str]:
        return [self.path] if self.path else []


class CompletionEvidence(CoreModel):
    """Evidence required before reporting a turn as complete."""

    status: CompletionStatus = "not_started"
    changed_files: list[str] = Field(default_factory=list)
    created_files: list[str] = Field(default_factory=list)
    deleted_files: list[str] = Field(default_factory=list)
    noop_targets: list[str] = Field(default_factory=list)
    noop_reason: str | None = None
    safe_noop: bool = False
    validation_commands: list[str] = Field(default_factory=list)
    validation_passed: bool | None = None
    final_answer_ready: bool = False
    grounding_required: bool = False
    search_candidate_paths: list[str] = Field(default_factory=list)
    inspected_paths: list[str] = Field(default_factory=list)
    zero_result_queries: list[str] = Field(default_factory=list)
    not_found_targets: list[str] = Field(default_factory=list)
    validation_failure_symbols: list[str] = Field(default_factory=list)
    policy_denied_tools: list[str] = Field(default_factory=list)
    web_unavailable_queries: list[str] = Field(default_factory=list)
    project_manifest: ProjectManifest | None = None
    document_manifest: DocumentManifest | None = None

    def has_file_change(self) -> bool:
        return bool(self.changed_files or self.created_files or self.deleted_files)

    def has_resolution_evidence(self) -> bool:
        return self.has_file_change() or self.safe_noop


class RecoveryState(CoreModel):
    """Recovery state for empty, slow, truncated, or looping model behavior."""

    reason: RecoveryReason
    attempts: int = 0
    last_error: str | None = None
    blocked: bool = False


class ToolLoopSignature(CoreModel):
    """Canonical signature for repeated tool-call detection."""

    tool_name: str
    arguments_hash: str
    count: int = 1

    @classmethod
    def from_tool_call(cls, tool_call: ToolCall, *, count: int = 1) -> "ToolLoopSignature":
        encoded = json.dumps(
            tool_call.arguments,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return cls(
            tool_name=tool_call.name,
            arguments_hash=hashlib.sha256(encoded).hexdigest(),
            count=count,
        )


class TurnResult(CoreModel):
    """Single-turn outcome consumed by headless mode and later by the TUI."""

    turn_id: str
    status: Literal["success", "partial", "failed", "cancelled"]
    final_answer: str = ""
    created_files: list[str] = Field(default_factory=list)
    modified_files: list[str] = Field(default_factory=list)
    deleted_files: list[str] = Field(default_factory=list)
    validation_passed: bool | None = None
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    error_message: str | None = None
    completion_evidence: CompletionEvidence = Field(default_factory=CompletionEvidence)
    recovery_states: list[RecoveryState] = Field(default_factory=list)
    tool_loop_signatures: list[ToolLoopSignature] = Field(default_factory=list)
    requires_change_evidence: bool = False
    validation_required: bool = False

    @model_validator(mode="after")
    def validate_success_has_evidence(self) -> "TurnResult":
        if self.status != "success":
            return self
        if not self.final_answer.strip():
            raise ValueError("successful turn results must include a final answer")
        if not self.completion_evidence.final_answer_ready:
            raise ValueError("successful turn results require completion evidence")
        if self.requires_change_evidence and not self._has_change_evidence():
            raise ValueError("change requests cannot succeed without file-change evidence")
        if self.validation_required and self.completion_evidence.validation_passed is not True:
            raise ValueError("validation-required turn results cannot succeed without passing validation")
        return self

    def _has_change_evidence(self) -> bool:
        return bool(
            self.created_files
            or self.modified_files
            or self.deleted_files
            or self.completion_evidence.created_files
            or self.completion_evidence.changed_files
            or self.completion_evidence.deleted_files
            or self.completion_evidence.safe_noop
        )
