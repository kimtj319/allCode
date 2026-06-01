"""Completion checks for generation workflows."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from allCode.agent.task_plan import ProjectPlan
from allCode.agent.validation_runner import ValidationResult
from allCode.core.models import CoreModel
from allCode.core.result import CompletionEvidence
from allCode.workspace.path_resolver import safe_resolve_under_root


class CompletionCheck(CoreModel):
    ok: bool
    errors: list[str] = Field(default_factory=list)
    missing_files: list[str] = Field(default_factory=list)
    empty_files: list[str] = Field(default_factory=list)
    forbidden_files: list[str] = Field(default_factory=list)


class CompletionChecker:
    def check(
        self,
        *,
        workspace_root: str | Path,
        plan: ProjectPlan,
        completion_evidence: CompletionEvidence,
        validation_results: list[ValidationResult],
        final_report: str | None = None,
        validation_required: bool = True,
    ) -> CompletionCheck:
        errors: list[str] = []
        target_root = safe_resolve_under_root(workspace_root, plan.target_root)
        if not target_root.exists() or not target_root.is_dir():
            errors.append(f"target root does not exist: {plan.target_root}")

        missing_files: list[str] = []
        empty_files: list[str] = []
        for relative_path in plan.required_paths():
            path = target_root / relative_path
            if not path.exists():
                missing_files.append(relative_path)
                continue
            if not path.is_file() or path.stat().st_size == 0:
                empty_files.append(relative_path)

        forbidden_files = [path for path in plan.forbidden_files if (target_root / path).exists()]
        if missing_files:
            errors.append("required files are missing")
        if empty_files:
            errors.append("required files are empty")
        if forbidden_files:
            errors.append("forbidden files were created")
        if not completion_evidence.has_file_change():
            errors.append("no file-change evidence was produced")
        if validation_required:
            if not completion_evidence.validation_commands:
                errors.append("validation was not executed")
            elif completion_evidence.validation_passed is not True:
                errors.append("validation evidence did not succeed")
        if completion_evidence.validation_commands and not validation_results:
            errors.append("validation result details are missing")
        if final_report is not None:
            report_errors = self._check_final_report(final_report, plan, completion_evidence, validation_results)
            errors.extend(report_errors)

        return CompletionCheck(
            ok=not errors,
            errors=errors,
            missing_files=missing_files,
            empty_files=empty_files,
            forbidden_files=forbidden_files,
        )

    def _check_final_report(
        self,
        final_report: str,
        plan: ProjectPlan,
        completion_evidence: CompletionEvidence,
        validation_results: list[ValidationResult],
    ) -> list[str]:
        errors: list[str] = []
        lowered = final_report.lower()
        if plan.target_root.lower() not in lowered:
            errors.append("final report does not mention the target root")
        evidence_files = completion_evidence.created_files + completion_evidence.changed_files
        for changed_file in evidence_files:
            normalized = changed_file.replace("\\", "/")
            relative = normalized.split(plan.target_root.rstrip("/") + "/", 1)[-1]
            if relative not in final_report and normalized not in final_report:
                errors.append(f"final report omits changed file from evidence: {relative}")
                break
        for command in completion_evidence.validation_commands:
            if command not in final_report:
                errors.append("final report omits validation command from evidence")
                break
        expected_result = "succeeded" if completion_evidence.validation_passed is True else "failed"
        if completion_evidence.validation_passed is not None and expected_result not in lowered:
            errors.append("final report omits validation result from evidence")
        if "core functionality" not in lowered and "핵심 기능" not in lowered:
            errors.append("final report omits core functionality")
        if "remaining risks" not in lowered and "남은 리스크" not in lowered:
            errors.append("final report omits remaining risks")
        if validation_results and validation_results[-1].command not in final_report:
            errors.append("final report omits validation result detail")
        return errors
