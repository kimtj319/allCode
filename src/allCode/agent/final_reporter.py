"""Final report rendering for generation workflows."""

from __future__ import annotations

from allCode.agent.language import ResponseLanguage, generation_report_labels, normalize_response_language
from allCode.agent.obligation_matrix import build_obligation_matrix
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
        response_language: ResponseLanguage | None = None,
    ) -> str:
        language = normalize_response_language(response_language)
        labels = generation_report_labels(language)
        changed = self._relative_files(plan, completion_evidence.created_files + completion_evidence.changed_files)
        validation_lines = self._validation_lines(completion_evidence, validation_results, response_language=language)
        recovery_lines = [
            f"- {state.reason}: attempts={state.attempts}, blocked={state.blocked}"
            for state in recovery_states
        ]
        obligation_lines = build_obligation_matrix(
            plan=plan,
            completion_evidence=completion_evidence,
            validation_results=validation_results,
        ).render(language=language)
        risk_lines = risks or [labels.no_known_risk]
        next_command = completion_evidence.validation_commands[-1] if completion_evidence.validation_commands else ""

        sections = [
            f"# {labels.title}",
            "",
            f"{labels.implementation_location}: `{plan.target_root}`",
            "",
            f"{labels.files}:",
            *[f"- `{path}`" for path in changed],
            "",
            f"{labels.core_functionality}:",
            f"- Generated a {plan.language} scaffold using skeleton-first workflow.",
            "- Added implementation files and validation coverage.",
            "",
            *(obligation_lines + [""] if obligation_lines else []),
            f"{labels.validation}:",
            *(validation_lines or [f"- {labels.not_executed}"]),
            "",
            f"{labels.repair}:",
            f"- Repair attempts: {repair_attempts}",
            *(recovery_lines or [f"- {labels.no_repair}"]),
            "",
            f"{labels.remaining_risks}:",
            *[f"- {risk}" for risk in risk_lines],
            "",
            f"{labels.next_command}:",
            f"- `{next_command}`" if next_command else f"- {labels.no_validation_command}",
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

    def _validation_lines(
        self,
        completion_evidence: CompletionEvidence,
        validation_results: list[ValidationResult],
        *,
        response_language: ResponseLanguage,
    ) -> list[str]:
        labels = generation_report_labels(response_language)
        if not completion_evidence.validation_commands:
            return [f"- {labels.not_executed}"]
        result_by_command = {result.command: result for result in validation_results}
        outcome = labels.succeeded if completion_evidence.validation_passed is True else labels.failed
        lines = [f"- {labels.evidence_result}: {outcome}"]
        for command in completion_evidence.validation_commands:
            detail = result_by_command.get(command)
            if detail is None:
                lines.append(f"- `{command}`: {labels.recorded}")
                continue
            command_outcome = labels.succeeded if detail.ok else labels.failed
            lines.append(f"- `{detail.command}` in `{detail.cwd}`: {command_outcome}")
        return lines
