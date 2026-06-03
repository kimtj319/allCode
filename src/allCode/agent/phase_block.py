"""Phase-block retry helpers for model/tool rounds."""

from __future__ import annotations

from collections.abc import Sequence

from allCode.agent.prompt_builder import PromptBuilder
from allCode.core.models import Message, ToolResult
from allCode.core.result import CompletionEvidence


class PhaseBlockHelper:
    """Builds corrective prompts and tracks bounded phase-block retries."""

    def __init__(self, prompt_builder: PromptBuilder) -> None:
        self._prompt_builder = prompt_builder

    def test_authoring_messages(
        self,
        messages: list[Message],
        evidence: CompletionEvidence,
        *,
        phase_gate,
        phase_block_reason: str = "",
    ) -> list[Message]:
        missing = list(phase_gate.missing_artifacts) if phase_gate is not None else []
        if not missing:
            missing = [
                artifact.kind if not artifact.target else f"{artifact.kind}:{artifact.target}"
                for artifact in evidence.unsatisfied_artifacts("source", "document", "test")
            ]
        return self._prompt_builder.test_authoring_request(
            messages,
            missing_artifacts=missing or ["test"],
            recent_source_paths=self.recent_source_paths(evidence),
            feature_objectives=evidence.feature_objectives,
            phase_block_reason=phase_block_reason or self.feedback(phase_gate, ()),
        )

    def validation_repair_messages(
        self,
        messages: list[Message],
        evidence: CompletionEvidence,
        *,
        phase_gate,
        phase_block_reason: str = "",
    ) -> list[Message]:
        repair_targets = (
            list(phase_gate.repair_targets)
            if phase_gate is not None and phase_gate.repair_targets
            else list(evidence.validation_failure_targets)
        )
        ambiguous = (
            list(phase_gate.patch_ambiguous_files)
            if phase_gate is not None and phase_gate.patch_ambiguous_files
            else list(evidence.patch_ambiguous_files)
        )
        preferred = list(phase_gate.preferred_next_tools) if phase_gate is not None else []
        return self._prompt_builder.validation_repair_request(
            messages,
            repair_targets=repair_targets[:3],
            patch_ambiguous_files=ambiguous[:3],
            preferred_next_tools=preferred[:3],
            failure_symbols=evidence.validation_failure_symbols[:3],
            api_expectations=evidence.public_api_expectations[:5],
            failure_excerpt=evidence.validation_failure_excerpt,
            phase_block_reason=phase_block_reason or self.feedback(phase_gate, ()),
        )

    @staticmethod
    def can_retry(
        counts: dict[tuple[str, str], int],
        *,
        phase_gate,
        reason: str,
        max_attempts: int = 2,
    ) -> bool:
        phase = str(getattr(phase_gate, "phase", "") or "normal")
        key = (phase, reason)
        count = counts.get(key, 0) + 1
        counts[key] = count
        return count <= max_attempts

    @staticmethod
    def feedback(phase_gate, results: Sequence[ToolResult]) -> str:
        if phase_gate is None or getattr(phase_gate, "phase", "normal") == "normal":
            return ""
        blocked_tools = [result.name for result in results if not result.ok]
        blocked = ", ".join(dict.fromkeys(blocked_tools)) if blocked_tools else "finalization"
        preferred = ", ".join(phase_gate.preferred_next_tools or sorted(phase_gate.allowed_tool_names))
        required = phase_gate.required_next_action or preferred
        reason = phase_gate.reason or "current phase requires a different next action"
        guidance = f"Required next tool family: {preferred or required}."
        if preferred == "write_file":
            guidance += " Retry with exactly one write_file call and include all required arguments, especially file_path and content."
        return f"Blocked {blocked}. Reason: {reason}. {guidance}"

    @staticmethod
    def recent_source_paths(evidence: CompletionEvidence) -> list[str]:
        seen: list[str] = []
        for path in [*evidence.created_files, *evidence.changed_files]:
            lowered = path.lower()
            if "/test" in lowered or lowered.startswith("test") or "tests/" in lowered:
                continue
            if path not in seen:
                seen.append(path)
        return seen[:5]
