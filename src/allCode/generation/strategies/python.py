"""Python skeleton-first generation strategy."""

from __future__ import annotations

from allCode.agent.task_plan import PlannedFile, ProjectPlan, TaskItem
from allCode.generation.strategy import GenerationRequest, infer_target_root, safe_name, validation_command


class PythonProjectStrategy:
    language = "python"
    aliases = ("python", "pytest", ".py", "파이썬")

    def create_plan(self, request: GenerationRequest) -> ProjectPlan:
        target = safe_name(request.target_root or infer_target_root(request.prompt))
        package = safe_name(target)
        return ProjectPlan(
            target_root=target,
            language=self.language,
            constraints=["Use a dependency-light src layout.", "Validate with pytest."],
            files=[
                PlannedFile(path="pyproject.toml", purpose="package metadata", stage="skeleton", content=self._pyproject(target)),
                PlannedFile(path=f"src/{package}/__init__.py", purpose="package marker", stage="skeleton", content='"""Generated package."""\n'),
                PlannedFile(path=f"src/{package}/main.py", purpose="public application API", stage="skeleton", content=self._main_skeleton()),
                PlannedFile(path=f"src/{package}/main.py", purpose="public application API", stage="implementation", content=self._main_implementation()),
                PlannedFile(path="tests/test_main.py", purpose="pytest coverage for public API", stage="tests", content=self._tests(package)),
            ],
            validation_commands=[
                validation_command("python -m pytest", cwd=target, environment={"PYTHONPATH": "src"}),
            ],
            tasks=[
                TaskItem(description="Create package skeleton and project metadata.", step="skeleton"),
                TaskItem(description="Implement the public application API.", step="implementation"),
                TaskItem(description="Add validation tests.", step="tests"),
                TaskItem(description="Run pytest validation.", step="validation"),
            ],
        )

    def repair_files(self, plan: ProjectPlan, failure_log: str) -> dict[str, str]:
        package = safe_name(plan.target_root)
        return {f"src/{package}/main.py": self._main_implementation()}

    def _pyproject(self, name: str) -> str:
        return "\n".join(
            [
                "[project]",
                f'name = "{name}"',
                'version = "0.1.0"',
                f'description = "Generated Python project {name}."',
                'requires-python = ">=3.11"',
                "",
                "[build-system]",
                'requires = ["hatchling"]',
                'build-backend = "hatchling.build"',
                "",
            ]
        )

    def _main_skeleton(self) -> str:
        return "\n".join(
            [
                '"""Application entry points."""',
                "",
                "",
                "def greet(name: str = \"world\") -> str:",
                "    \"\"\"Return a greeting for a caller.\"\"\"",
                "    cleaned = name.strip() or \"world\"",
                "    return cleaned",
                "",
            ]
        )

    def _main_implementation(self) -> str:
        return "\n".join(
            [
                '"""Application entry points."""',
                "",
                "",
                "def greet(name: str = \"world\") -> str:",
                "    \"\"\"Return a stable greeting for a caller.\"\"\"",
                "    cleaned = name.strip() or \"world\"",
                "    return f\"Hello, {cleaned}!\"",
                "",
            ]
        )

    def _tests(self, package: str) -> str:
        return "\n".join(
            [
                f"from {package}.main import greet",
                "",
                "",
                "def test_greet_uses_name() -> None:",
                "    assert greet(\"User\") == \"Hello, User!\"",
                "",
                "",
                "def test_greet_defaults_to_world() -> None:",
                "    assert greet(\"   \") == \"Hello, world!\"",
                "",
            ]
        )
