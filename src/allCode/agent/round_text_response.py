"""Text response gates for model rounds."""

from __future__ import annotations

from typing import Any

from allCode.agent.answer_scope_guard import (
    answer_scope_retry_messages,
    answer_scope_retry_used,
    answer_scope_violation,
)
from allCode.agent.dependency_answer_guard import (
    dependency_answer_blocked_message,
    dependency_answer_retry_messages,
    dependency_answer_retry_used,
    dependency_answer_sanitized_fallback,
    dependency_answer_violation,
)
from allCode.agent.finalization_helpers import blocked_summary
from allCode.agent.recovery import needs_validation_repair
from allCode.agent.round_runtime import RoundRuntime
from allCode.agent.round_runner_helpers import response_language, test_authoring_messages, validation_repair_messages
from allCode.agent.source_answer_fallback import safe_source_analysis_answer
from allCode.agent.source_answer_guard import (
    source_answer_retry_messages,
    source_answer_violation,
)
from allCode.agent.source_answer_retry_context import (
    repeated_source_answer_violation,
    source_answer_retry_count,
    source_answer_violation_error,
)
from allCode.agent.turn_completion import LoopOutcome
from allCode.agent.validation_repair import validation_repair_needed
from allCode.core.models import Message, TurnInput, TurnState
from allCode.core.result import CompletionEvidence


class RoundTextResponseHandler:
    """Handles visible model text that might arrive before required gates."""

    def __init__(self, runner: Any) -> None:
        self._runner = runner

    async def handle(
        self,
        *,
        parsed,
        turn_input: TurnInput,
        state: TurnState,
        runtime: RoundRuntime,
        recovery,
        evidence: CompletionEvidence,
        routing,
        phase_gate,
        inspect_stage,
        more_mutation_before_validation: bool,
    ) -> LoopOutcome | None:
        if routing.requires_mutation and not evidence.has_resolution_evidence() and recovery.can_request_mutation_action():
            state.phase = "recovery"
            await self._runner._record_recovery(state, recovery, "no_progress", attempts=1, last_error="model answered before file mutation")
            runtime.messages.append(Message(role="assistant", content=parsed.text.rstrip()))
            runtime.messages = self._runner._prompt_builder.mutation_action_request(runtime.messages)
            runtime.mutation_action_pending = True
            return None
        if more_mutation_before_validation:
            if recovery.can_request_mutation_action(max_attempts=6):
                state.phase = "recovery"
                await self._runner._record_recovery(
                    state,
                    recovery,
                    "no_progress",
                    attempts=recovery.mutation_action_requests,
                    last_error="model answered before required test artifact was written",
                )
                runtime.messages.append(Message(role="assistant", content=parsed.text.rstrip()))
                runtime.messages = test_authoring_messages(self._runner._phase_block, runtime.messages, evidence, phase_gate=phase_gate)
                runtime.mutation_action_pending = True
                return None
            return LoopOutcome(
                status="partial",
                answer=blocked_summary(self._runner._prompt_builder, runtime.messages, "test_artifact_required_before_validation"),
                error="A requested test artifact is required before validation and final answer.",
            )
        if getattr(phase_gate, "phase", "") == "related_test_discovery_required":
            state.phase = "recovery"
            await self._runner._record_recovery(
                state,
                recovery,
                "no_progress",
                attempts=1,
                last_error="model answered before related test discovery",
            )
            runtime.messages.append(Message(role="assistant", content=parsed.text.rstrip()))
            runtime.messages = self._runner._phase_block.related_test_discovery_messages(runtime.messages, evidence, phase_gate=phase_gate)
            return None
        if runtime.validation_action_pending and evidence.validation_passed is not True:
            if recovery.can_request_validation_action():
                state.phase = "recovery"
                await self._runner._record_recovery(state, recovery, "validation_failed", attempts=1, last_error="model answered before required validation")
                runtime.messages.append(Message(role="assistant", content=parsed.text.rstrip()))
                runtime.messages = self._runner._prompt_builder.validation_action_request(runtime.messages)
                return None
            return LoopOutcome(
                status="partial",
                answer=blocked_summary(
                    self._runner._prompt_builder,
                    runtime.messages,
                    "validation_required_but_model_answered_without_run_tests",
                ),
                error="Validation is required but the model answered before run_tests.",
            )
        if needs_validation_repair(routing, evidence) or validation_repair_needed(routing, evidence):
            if recovery.can_request_validation_repair():
                state.phase = "recovery"
                await self._runner._record_recovery(
                    state,
                    recovery,
                    "validation_failed",
                    attempts=recovery.validation_repair_requests,
                    last_error="model answered before validation passed",
                )
                runtime.messages.append(Message(role="assistant", content=parsed.text.rstrip()))
                runtime.messages = validation_repair_messages(self._runner._phase_block, runtime.messages, evidence, phase_gate=phase_gate)
                runtime.validation_repair_pending = True
                runtime.mutation_action_pending = True
                return None
        if self._inspect_answer_is_premature(routing, runtime, evidence, inspect_stage):
            state.phase = "recovery"
            await self._runner._record_recovery(
                state,
                recovery,
                "no_progress",
                attempts=1,
                last_error="model answered before required source inspection evidence was collected",
            )
            runtime.messages = self._runner._prompt_builder.inspect_stage_request(
                runtime.messages,
                stage=inspect_stage.stage,
                target_paths=inspect_stage.target_paths,
                reason=inspect_stage.reason,
            )
            return None
        source_violation = source_answer_violation(
            answer=parsed.text,
            routing=routing,
            messages=runtime.messages,
            user_prompt=turn_input.user_prompt,
        )
        if source_violation is not None:
            retry_count = source_answer_retry_count(recovery)
            repeated_violation = repeated_source_answer_violation(
                recovery,
                reason=source_violation.reason,
                excerpt=source_violation.excerpt,
            )
            if retry_count < 2 and not repeated_violation:
                state.phase = "recovery"
                await self._runner._record_recovery(
                    state,
                    recovery,
                    "no_progress",
                    attempts=retry_count + 1,
                    last_error=source_answer_violation_error(source_violation.reason, source_violation.excerpt),
                )
                runtime.messages = source_answer_retry_messages(
                    current_messages=runtime.messages,
                    previous_answer=parsed.text,
                    violation=source_violation,
                    language=response_language(turn_input.user_prompt),
                )
                return None
            language = response_language(turn_input.user_prompt)
            return LoopOutcome(
                status="success",
                answer=safe_source_analysis_answer(
                    messages=runtime.messages,
                    evidence=evidence,
                    user_prompt=turn_input.user_prompt,
                    language=language,
                ),
            )
        dependency_violation = dependency_answer_violation(answer=parsed.text, routing=routing)
        if dependency_violation is not None:
            language = response_language(turn_input.user_prompt)
            if not dependency_answer_retry_used(recovery):
                state.phase = "recovery"
                await self._runner._record_recovery(
                    state,
                    recovery,
                    "dependency_constraint_violation",
                    attempts=1,
                    last_error=f"{dependency_violation.reason}: {dependency_violation.excerpt}",
                )
                runtime.messages = dependency_answer_retry_messages(
                    current_messages=runtime.messages,
                    previous_answer=parsed.text,
                    violation=dependency_violation,
                    language=language,
                )
                return None
            sanitized = dependency_answer_sanitized_fallback(
                messages=runtime.messages,
                current_answer=parsed.text,
                routing=routing,
                language=language,
            )
            if sanitized:
                return LoopOutcome(status="success", answer=sanitized)
            return LoopOutcome(
                status="partial",
                answer=dependency_answer_blocked_message(violation=dependency_violation, language=language),
                error=dependency_violation.reason,
            )
        scope_violation = answer_scope_violation(
            prompt=turn_input.user_prompt,
            answer=parsed.text,
            routing=routing,
        )
        if scope_violation is not None and not answer_scope_retry_used(recovery, max_attempts=2):
            state.phase = "recovery"
            await self._runner._record_recovery(
                state,
                recovery,
                "answer_scope_violation",
                attempts=1,
                last_error=scope_violation.reason,
            )
            runtime.messages = answer_scope_retry_messages(
                current_messages=runtime.messages,
                previous_answer=parsed.text,
                violation=scope_violation,
                language=response_language(turn_input.user_prompt),
            )
            return None
        return LoopOutcome(status="success", answer=parsed.text.rstrip())

    @staticmethod
    def _inspect_answer_is_premature(
        routing,
        runtime: RoundRuntime,
        evidence: CompletionEvidence,
        inspect_stage,
    ) -> bool:
        if getattr(routing, "kind", "") != "inspect":
            return False
        if runtime.inspect_final_answer_requested:
            return False
        if not (
            evidence.source_overview_paths
            or evidence.search_candidate_paths
            or evidence.inspected_paths
            or evidence.representative_read_paths
        ):
            return False
        if not getattr(inspect_stage, "active", False):
            return False
        if getattr(inspect_stage, "stage", "") not in {"source_discovery", "targeted_read"}:
            return False
        return not bool(getattr(inspect_stage, "evidence_complete", False))
