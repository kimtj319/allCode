"""Rust generation strategy."""

from __future__ import annotations

from allCode.agent.task_plan import PlannedFile, ProjectPlan
from allCode.generation.strategy import GenerationRequest, infer_target_root, safe_name, validation_command


class RustStrategy:
    language = "rust"
    aliases = ("rust", "cargo", ".rs")

    def create_plan(self, request: GenerationRequest) -> ProjectPlan:
        target = safe_name(request.target_root or infer_target_root(request.prompt))
        return ProjectPlan(
            target_root=target,
            language=self.language,
            files=[
                PlannedFile(path="Cargo.toml", purpose="cargo metadata", stage="skeleton", content=f'[package]\nname = "{target}"\nversion = "0.1.0"\nedition = "2021"\n'),
                PlannedFile(path="src/lib.rs", purpose="public API skeleton", stage="skeleton", content=self._skeleton()),
                PlannedFile(path="src/lib.rs", purpose="public API implementation", stage="implementation", content=self._implementation()),
                PlannedFile(path="tests/greet_test.rs", purpose="cargo integration test", stage="tests", content=self._tests(target)),
            ],
            validation_commands=[validation_command("cargo test", cwd=target)],
        )

    def repair_files(self, plan: ProjectPlan, failure_log: str) -> dict[str, str]:
        return {"src/lib.rs": self._implementation()}

    def _skeleton(self) -> str:
        return 'pub fn greet(name: &str) -> String {\n    let cleaned = if name.trim().is_empty() { "world" } else { name.trim() };\n    cleaned.to_string()\n}\n'

    def _implementation(self) -> str:
        return 'pub fn greet(name: &str) -> String {\n    let cleaned = if name.trim().is_empty() { "world" } else { name.trim() };\n    format!("Hello, {}!", cleaned)\n}\n'

    def _tests(self, crate_name: str) -> str:
        return f'use {crate_name}::greet;\n\n#[test]\nfn greet_uses_name() {{\n    assert_eq!(greet("User"), "Hello, User!");\n}}\n'
