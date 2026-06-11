"""Completion helpers for skeleton-first generation workflow."""

from __future__ import annotations

from allCode.agent.completion_checker import CompletionCheck
from allCode.agent.task_plan import ProjectPlan
from allCode.agent.validation_runner import ValidationResult
from allCode.core.result import CompletionEvidence, ProjectManifest


def build_project_manifest(*, plan: ProjectPlan, completion_evidence: CompletionEvidence) -> ProjectManifest:
    files = [planned_file.path for planned_file in plan.files]
    entrypoints = [
        f"{plan.target_root}/{path}"
        for path in files
        if path.endswith(("main.py", "cli.py", "__main__.py", "index.js", "main.go", "Main.java"))
        or "/cli" in path.lower()
    ]
    if not entrypoints:
        entrypoints = [
            f"{plan.target_root}/{path}"
            for path in files
            if path.endswith((".py", ".js", ".ts", ".go", ".rs", ".java")) and "test" not in path.lower()
        ][:3]
    test_paths = [f"{plan.target_root}/{path}" for path in files if "test" in path.lower() or "spec" in path.lower()]
    package_candidates = [f"{plan.target_root}/{path.rsplit('/', 1)[0]}" for path in files if "/" in path and "test" not in path.lower()]
    package_root = package_candidates[0] if package_candidates else plan.target_root
    validation_commands = completion_evidence.validation_commands or [command.command for command in plan.validation_commands]
    validation_cwd = plan.validation_commands[0].cwd if plan.validation_commands else plan.target_root
    last_modified = [
        path
        for path in [*completion_evidence.created_files, *completion_evidence.changed_files]
        if path not in completion_evidence.deleted_files
    ]
    return ProjectManifest(
        project_root=plan.target_root,
        package_root=package_root,
        entrypoints=entrypoints,
        test_paths=test_paths,
        validation_commands=validation_commands,
        validation_cwd=validation_cwd,
        last_modified_files=last_modified,
        language=plan.language,
        confidence=0.85 if last_modified else 0.5,
    )


def completion_check_repairable(
    check: CompletionCheck,
    completion_evidence: CompletionEvidence,
    validation_results: list[ValidationResult],
) -> bool:
    if check.ok or completion_evidence.validation_passed is not True:
        return False
    if not validation_results or validation_results[-1].ok is not True:
        return False
    return any(
        error.startswith("public API ")
        or error.startswith("python syntax error")
        or error.startswith("test coverage ")
        or error.startswith("documentation references ")
        for error in check.errors
    )
