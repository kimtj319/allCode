"""Final report rendering for generation workflows."""

from __future__ import annotations

from allCode.agent.task_plan import ProjectPlan
from allCode.agent.validation_runner import ValidationResult
from allCode.core.result import CompletionEvidence, RecoveryState


class FinalReporter:
    def build(
        self,
        *,
        plan: ProjectPlan,
        completion_evidence: CompletionEvidence,
        validation_results: list[ValidationResult],
        recovery_states: list[RecoveryState],
        repair_attempts: int,
        risks: list[str] | None = None,
    ) -> str:
        changed = self._relative_files(plan, completion_evidence.created_files + completion_evidence.changed_files)
        validation_lines = self._validation_lines(completion_evidence, validation_results)
        recovery_lines = [
            f"- {state.reason}: attempts={state.attempts}, blocked={state.blocked}"
            for state in recovery_states
        ]
        risk_lines = risks or ["No known residual risk inside the generated scaffold."]
        next_command = completion_evidence.validation_commands[-1] if completion_evidence.validation_commands else ""

        sections = [
            "# Generation Report",
            "",
            f"Implementation location: `{plan.target_root}`",
            "",
            "Created/modified files:",
            *[f"- `{path}`" for path in changed],
            "",
            "Core functionality:",
            f"- Generated a {plan.language} scaffold using skeleton-first workflow.",
            "- Added implementation files and validation coverage.",
            "",
            "Validation:",
            *(validation_lines or ["- Not executed."]),
            "",
            "Repair:",
            f"- Repair attempts: {repair_attempts}",
            *(recovery_lines or ["- No repair was required."]),
            "",
            "Remaining risks:",
            *[f"- {risk}" for risk in risk_lines],
            "",
            "Next command:",
            f"- `{next_command}`" if next_command else "- No validation command is available.",
            "",
        ]
        return "\n".join(sections)

    def _relative_files(self, plan: ProjectPlan, files: list[str]) -> list[str]:
        seen: list[str] = []
        prefix = plan.target_root.rstrip("/") + "/"
        for path in files:
            normalized = path.replace("\\", "/")
            if prefix in normalized:
                normalized = normalized.split(prefix, 1)[1]
            if normalized not in seen:
                seen.append(normalized)
        return seen or ["No file changes recorded in completion evidence."]

    def _validation_lines(self, completion_evidence: CompletionEvidence, validation_results: list[ValidationResult]) -> list[str]:
        if not completion_evidence.validation_commands:
            return ["- Not executed."]
        result_by_command = {result.command: result for result in validation_results}
        outcome = "succeeded" if completion_evidence.validation_passed is True else "failed"
        lines = [f"- Evidence result: {outcome}"]
        for command in completion_evidence.validation_commands:
            detail = result_by_command.get(command)
            if detail is None:
                lines.append(f"- `{command}`: recorded in completion evidence")
                continue
            command_outcome = "succeeded" if detail.ok else "failed"
            lines.append(f"- `{detail.command}` in `{detail.cwd}`: {command_outcome}")
        return lines
