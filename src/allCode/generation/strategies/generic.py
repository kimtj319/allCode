"""Fallback strategy for unknown languages or simple file plans."""

from __future__ import annotations

from allCode.agent.task_plan import PlannedFile, ProjectPlan
from allCode.generation.strategy import GenerationRequest, infer_target_root, safe_name, validation_command


class GenericFileStrategy:
    language = "generic"
    aliases = ("",)

    def create_plan(self, request: GenerationRequest) -> ProjectPlan:
        target = safe_name(request.target_root or infer_target_root(request.prompt))
        return ProjectPlan(
            target_root=target,
            language=self.language,
            constraints=["Do not install dependencies for unknown languages."],
            files=[
                PlannedFile(path="README.md", purpose="project overview skeleton", stage="skeleton", content=f"# {target}\n\nGenerated project scaffold.\n"),
                PlannedFile(path="README.md", purpose="project overview implementation", stage="implementation", content=f"# {target}\n\nThis project was generated with a minimal, dependency-free scaffold.\n"),
            ],
            validation_commands=[
                validation_command(
                    "python -c \"from pathlib import Path; assert Path('README.md').read_text(encoding='utf-8').strip()\"",
                    cwd=target,
                )
            ],
        )

    def repair_files(self, plan: ProjectPlan, failure_log: str) -> dict[str, str]:
        return {"README.md": f"# {plan.target_root}\n\nThis project was repaired with a non-empty README.\n"}
