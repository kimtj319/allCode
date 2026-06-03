"""Validation fallback and evidence-grounded final reporting helpers."""

from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

from allCode.agent.recovery import RecoveryTracker, ToolLoopGuard
from allCode.core.models import ToolCall, ToolResult, TurnInput, TurnState
from allCode.core.result import CompletionEvidence


class RevalidationOrchestrator:
    """Injects validation actions when the model stalls after mutation."""

    def __init__(self, *, tool_call_processor, max_rounds: int) -> None:
        self._tool_call_processor = tool_call_processor
        self._max_rounds = max_rounds

    def should_inject(
        self,
        round_index: int,
        routing,
        evidence: CompletionEvidence,
        recovery: RecoveryTracker,
        *,
        validation_action_pending: bool,
        awaiting_revalidation_after_mutation: bool,
    ) -> bool:
        if not (validation_action_pending or awaiting_revalidation_after_mutation):
            return False
        if not getattr(routing, "requires_validation", False) or evidence.validation_passed is True:
            return False
        if not evidence.has_file_change():
            return False
        if evidence.validation_passed is False and not awaiting_revalidation_after_mutation:
            return False
        return recovery.validation_action_requested or round_index >= self._max_rounds - 2

    async def execute(
        self,
        turn_input: TurnInput,
        state: TurnState,
        loop_guard: ToolLoopGuard,
        recovery: RecoveryTracker,
        completion_evidence: CompletionEvidence,
        routing,
        *,
        phase_gate,
    ) -> list[ToolResult]:
        call = ToolCall(id=f"validation-{uuid4().hex}", name="run_tests", arguments={})
        return await self._tool_call_processor.execute(
            turn_input,
            state,
            [call],
            loop_guard,
            recovery,
            completion_evidence,
            routing,
            allowed_tool_names={"run_tests"},
            phase_gate=phase_gate,
        )


def validated_change_complete(routing, evidence: CompletionEvidence) -> bool:
    return (
        getattr(routing, "requires_mutation", False)
        and getattr(routing, "requires_validation", False)
        and evidence.has_file_change()
        and evidence.validation_passed is True
        and not evidence.has_unsatisfied_artifacts("source", "test", "document", "validation")
    )


def mutation_change_complete(routing, evidence: CompletionEvidence) -> bool:
    return (
        getattr(routing, "requires_mutation", False)
        and not getattr(routing, "requires_validation", False)
        and evidence.has_file_change()
        and not evidence.has_unsatisfied_artifacts("source", "test", "document", "validation")
    )


def evidence_final_answer(prompt: str, evidence: CompletionEvidence, workspace_root: str) -> str:
    changed = _relative_unique_files(
        [*evidence.created_files, *evidence.changed_files, *evidence.deleted_files],
        workspace_root,
    )
    terms = _prompt_reference_terms(prompt)
    lines = ["작업을 완료했습니다."]
    if changed:
        lines.append("- 생성/수정 파일:")
        lines.extend(f"  - `{path}`" for path in changed[:12])
    if terms:
        lines.append("- 요청 기준: " + ", ".join(f"`{term}`" for term in terms[:8]))
    if evidence.validation_commands:
        lines.append(f"- 검증 명령: `{evidence.validation_commands[-1]}`")
    if evidence.validation_passed is True:
        lines.append("- 검증 결과: 통과")
    elif evidence.validation_passed is False:
        lines.append("- 검증 결과: 실패")
    else:
        lines.append("- 검증 결과: 요청되지 않음")
    lines.append("- 남은 리스크: 현재 검증 범위 밖의 런타임 환경 차이는 추가 확인이 필요합니다.")
    return "\n".join(lines)


def _relative_unique_files(paths: list[str], workspace_root: str) -> list[str]:
    seen: list[str] = []
    root = Path(workspace_root).expanduser().resolve()
    for raw_path in paths:
        if not raw_path:
            continue
        path = Path(raw_path)
        try:
            resolved = path.expanduser().resolve()
            relative = str(resolved.relative_to(root))
        except (OSError, ValueError):
            relative = str(path)
        if relative not in seen:
            seen.append(relative)
    return seen


def _prompt_reference_terms(prompt: str) -> list[str]:
    terms: list[str] = []
    for term in re.findall(r"--[A-Za-z0-9][A-Za-z0-9_-]*", prompt):
        if term not in terms:
            terms.append(term)
    common = {"python", "pytest", "test", "tests", "file", "files", "cli", "project"}
    for term in re.findall(r"(?<![A-Za-z0-9_])[A-Za-z_][A-Za-z0-9_]{2,}(?![A-Za-z0-9_])", prompt):
        lowered = term.lower()
        if "_" not in term and lowered in common:
            continue
        if term not in terms:
            terms.append(term)
    return terms
