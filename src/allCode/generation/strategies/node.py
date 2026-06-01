"""Dependency-light Node/TypeScript generation strategy."""

from __future__ import annotations

from allCode.agent.task_plan import PlannedFile, ProjectPlan
from allCode.generation.strategy import GenerationRequest, infer_target_root, safe_name, validation_command


class NodeTypeScriptStrategy:
    language = "node"
    aliases = ("node", "javascript", "typescript", "npm", ".js", ".ts")

    def create_plan(self, request: GenerationRequest) -> ProjectPlan:
        target = safe_name(request.target_root or infer_target_root(request.prompt))
        return ProjectPlan(
            target_root=target,
            language=self.language,
            constraints=["Use built-in Node test runner without installing dependencies."],
            files=[
                PlannedFile(path="package.json", purpose="node metadata", stage="skeleton", content=self._package(target)),
                PlannedFile(path="src/index.js", purpose="public API skeleton", stage="skeleton", content=self._skeleton()),
                PlannedFile(path="src/index.js", purpose="public API implementation", stage="implementation", content=self._implementation()),
                PlannedFile(path="test/index.test.js", purpose="node test coverage", stage="tests", content=self._tests()),
            ],
            validation_commands=[validation_command("node --test", cwd=target)],
        )

    def repair_files(self, plan: ProjectPlan, failure_log: str) -> dict[str, str]:
        return {"src/index.js": self._implementation()}

    def _package(self, name: str) -> str:
        return f'{{\n  "name": "{name}",\n  "version": "0.1.0",\n  "type": "module",\n  "scripts": {{"test": "node --test"}}\n}}\n'

    def _skeleton(self) -> str:
        return "export function greet(name = 'world') {\n  const cleaned = name.trim() || 'world';\n  return cleaned;\n}\n"

    def _implementation(self) -> str:
        return "export function greet(name = 'world') {\n  const cleaned = name.trim() || 'world';\n  return `Hello, ${cleaned}!`;\n}\n"

    def _tests(self) -> str:
        return "import test from 'node:test';\nimport assert from 'node:assert/strict';\nimport { greet } from '../src/index.js';\n\ntest('greet uses a name', () => {\n  assert.equal(greet('User'), 'Hello, User!');\n});\n"
