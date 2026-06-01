"""Go generation strategy."""

from __future__ import annotations

from allCode.agent.task_plan import PlannedFile, ProjectPlan
from allCode.generation.strategy import GenerationRequest, infer_target_root, safe_name, validation_command


class GoStrategy:
    language = "go"
    aliases = ("go", "golang", ".go")

    def create_plan(self, request: GenerationRequest) -> ProjectPlan:
        target = safe_name(request.target_root or infer_target_root(request.prompt))
        module = target.replace("_", "")
        return ProjectPlan(
            target_root=target,
            language=self.language,
            files=[
                PlannedFile(path="go.mod", purpose="module declaration", stage="skeleton", content=f"module {module}\n\ngo 1.22\n"),
                PlannedFile(path="greet.go", purpose="public API skeleton", stage="skeleton", content=self._skeleton()),
                PlannedFile(path="greet.go", purpose="public API implementation", stage="implementation", content=self._implementation()),
                PlannedFile(path="greet_test.go", purpose="go test coverage", stage="tests", content=self._tests()),
            ],
            validation_commands=[validation_command("go test ./...", cwd=target)],
        )

    def repair_files(self, plan: ProjectPlan, failure_log: str) -> dict[str, str]:
        return {"greet.go": self._implementation()}

    def _skeleton(self) -> str:
        return 'package main\n\nfunc Greet(name string) string {\n\tif name == "" {\n\t\treturn "world"\n\t}\n\treturn name\n}\n'

    def _implementation(self) -> str:
        return 'package main\n\nfunc Greet(name string) string {\n\tif name == "" {\n\t\tname = "world"\n\t}\n\treturn "Hello, " + name + "!"\n}\n'

    def _tests(self) -> str:
        return 'package main\n\nimport "testing"\n\nfunc TestGreet(t *testing.T) {\n\tif Greet("User") != "Hello, User!" {\n\t\tt.Fatal("unexpected greeting")\n\t}\n}\n'
