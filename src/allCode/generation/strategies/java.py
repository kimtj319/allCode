"""Java generation strategy."""

from __future__ import annotations

from allCode.agent.task_plan import PlannedFile, ProjectPlan
from allCode.generation.strategy import GenerationRequest, infer_target_root, safe_name, validation_command


class JavaStrategy:
    language = "java"
    aliases = ("java", "javac", "gradle", "maven", ".java")

    def create_plan(self, request: GenerationRequest) -> ProjectPlan:
        target = safe_name(request.target_root or infer_target_root(request.prompt))
        return ProjectPlan(
            target_root=target,
            language=self.language,
            files=[
                PlannedFile(path="src/main/java/App.java", purpose="application skeleton", stage="skeleton", content=self._skeleton()),
                PlannedFile(path="src/main/java/App.java", purpose="application implementation", stage="implementation", content=self._implementation()),
                PlannedFile(path="src/test/java/AppTest.java", purpose="plain Java validation test", stage="tests", content=self._tests()),
            ],
            validation_commands=[
                validation_command("javac src/main/java/App.java src/test/java/AppTest.java", cwd=target),
                validation_command("java -cp src/main/java:src/test/java AppTest", cwd=target),
            ],
        )

    def repair_files(self, plan: ProjectPlan, failure_log: str) -> dict[str, str]:
        return {"src/main/java/App.java": self._implementation()}

    def _skeleton(self) -> str:
        return 'public class App {\n    public static String greet(String name) {\n        String cleaned = name == null || name.isBlank() ? "world" : name.trim();\n        return cleaned;\n    }\n}\n'

    def _implementation(self) -> str:
        return 'public class App {\n    public static String greet(String name) {\n        String cleaned = name == null || name.isBlank() ? "world" : name.trim();\n        return "Hello, " + cleaned + "!";\n    }\n}\n'

    def _tests(self) -> str:
        return 'public class AppTest {\n    public static void main(String[] args) {\n        if (!"Hello, User!".equals(App.greet("User"))) {\n            throw new IllegalStateException("unexpected greeting");\n        }\n    }\n}\n'
