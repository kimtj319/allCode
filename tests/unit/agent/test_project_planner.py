from __future__ import annotations

import asyncio

from allCode.agent.project_planner import ModelProjectPlanner
from allCode.core.models import Message
from allCode.llm.settings import ModelSettings
from tests.helpers.fake_llm import FakeLLMClient


class CapturingFakeLLM(FakeLLMClient):
    def __init__(self, text: str) -> None:
        super().__init__([self.text_events(text)])
        self.messages: list[Message] = []

    async def complete(self, messages, tools, settings):
        self.messages = list(messages)
        return await super().complete(messages, tools, settings)


def test_model_project_planner_preserves_explicit_target_hint_over_model_root() -> None:
    llm = FakeLLMClient.text(
        """
        {
          "target_root": "generated_project",
          "language": "python",
          "files": [
            {
              "path": "generated_project/src/generated_project/main.py",
              "purpose": "entrypoint",
              "stage": "implementation",
              "content": "def main():\\n    return 'ok'\\n",
              "required": true
            }
          ],
          "validation_commands": [
            {"command": "python -m pytest", "cwd": "generated_project"}
          ],
          "tasks": []
        }
        """
    )

    async def scenario():
        return await ModelProjectPlanner(
            llm_client=llm,
            settings=ModelSettings(model_name="fake", api_key_env="FAKE_API_KEY"),
        ).create_plan("Create under ./output/phase41_sample_cli", target_hint="output/phase41_sample_cli")

    plan = asyncio.run(scenario())

    assert plan is not None
    assert plan.target_root == "output/phase41_sample_cli"
    assert plan.files[0].path == "src/generated_project/main.py"
    assert plan.validation_commands[0].cwd == "output/phase41_sample_cli"


def test_model_project_planner_includes_prompt_obligations_and_task_digest() -> None:
    llm = CapturingFakeLLM(
        """
        {
          "target_root": "ops_tool",
          "language": "python",
          "files": [
            {
              "path": "README.md",
              "purpose": "documentation",
              "stage": "implementation",
              "content": "usage\\n",
              "required": true
            }
          ],
          "validation_commands": [],
          "api_obligations": [
            {
              "path": "ops_tool/src/ops_tool/cli.py",
              "symbol": "main",
              "reason": "CLI entrypoint"
            }
          ],
          "tasks": []
        }
        """
    )

    async def scenario():
        return await ModelProjectPlanner(
            llm_client=llm,
            settings=ModelSettings(model_name="fake", api_key_env="FAKE_API_KEY"),
        ).create_plan(
            "표준 라이브러리만 사용해서 CLI, config, registry, retry, JSONL logger, tests, README를 생성해줘.",
            target_hint="ops_tool",
            task_digest="Task loop digest for this model round:\n- Required next action: plan files",
        )

    plan = asyncio.run(scenario())
    prompt = "\n\n".join(message.content for message in llm.messages)

    assert plan is not None
    assert "Prompt-derived artifact obligations" in prompt
    assert "CLI entrypoint" in prompt
    assert "configuration loader" in prompt
    assert "retry/backoff behavior" in prompt
    assert "structured audit logging" in prompt
    assert "Use only the language standard library" in prompt
    assert "Task loop digest for this model round" in prompt
    assert "api_obligations" in prompt
    assert "Tests must exercise requested behavior" in prompt
    assert plan is not None
    assert plan.api_obligations[0].path == "src/ops_tool/cli.py"


def test_model_project_planner_normalizes_api_obligation_paths() -> None:
    llm = FakeLLMClient.text(
        """
        {
          "target_root": "generated_project",
          "language": "python",
          "files": [
            {
              "path": "generated_project/src/generated_project/main.py",
              "purpose": "entrypoint",
              "stage": "implementation",
              "content": "def main():\\n    return 0\\n",
              "required": true
            },
            {
              "path": "generated_project/tests/test_main.py",
              "purpose": "behavior tests",
              "stage": "tests",
              "content": "from generated_project.main import main\\n\\ndef test_main():\\n    assert main() == 0\\n",
              "required": true
            }
          ],
          "validation_commands": [
            {"command": "python -m pytest", "cwd": "generated_project"}
          ],
          "api_obligations": [
            {
              "path": "generated_project/src/generated_project/main.py",
              "symbol": "main",
              "reason": "entrypoint imported by tests"
            }
          ],
          "tasks": []
        }
        """
    )

    async def scenario():
        return await ModelProjectPlanner(
            llm_client=llm,
            settings=ModelSettings(model_name="fake", api_key_env="FAKE_API_KEY"),
        ).create_plan("Create a Python package with tests.", target_hint="output/generated_project")

    plan = asyncio.run(scenario())

    assert plan is not None
    assert plan.target_root == "output/generated_project"
    assert plan.api_obligations[0].path == "src/generated_project/main.py"


def test_model_project_planner_adds_missing_documentation_obligation() -> None:
    llm = FakeLLMClient.text(
        """
        {
          "target_root": "sample_tool",
          "language": "python",
          "files": [
            {
              "path": "src/sample_tool/main.py",
              "purpose": "entrypoint",
              "stage": "implementation",
              "content": "def main():\\n    return 0\\n",
              "required": true
            }
          ],
          "validation_commands": [],
          "tasks": []
        }
        """
    )

    async def scenario():
        return await ModelProjectPlanner(
            llm_client=llm,
            settings=ModelSettings(model_name="fake", api_key_env="FAKE_API_KEY"),
        ).create_plan("README와 실행 방법 문서가 포함된 작은 CLI 프로젝트를 생성해줘.", target_hint="sample_tool")

    plan = asyncio.run(scenario())

    assert plan is not None
    paths = {file.path for file in plan.files}
    assert "README.md" in paths
    readme = next(file for file in plan.files if file.path == "README.md")
    assert readme.required is True
    assert "Usage" in readme.content


def test_model_project_planner_adds_report_artifact_only_when_explicitly_requested() -> None:
    llm = FakeLLMClient.text(
        """
        {
          "target_root": "sample_tool",
          "language": "python",
          "files": [
            {
              "path": "src/sample_tool/main.py",
              "purpose": "entrypoint",
              "stage": "implementation",
              "content": "def main():\\n    return 0\\n",
              "required": true
            }
          ],
          "validation_commands": [],
          "tasks": []
        }
        """
    )

    async def scenario():
        return await ModelProjectPlanner(
            llm_client=llm,
            settings=ModelSettings(model_name="fake", api_key_env="FAKE_API_KEY"),
        ).create_plan("결과 보고서 파일을 포함한 작은 CLI 프로젝트를 생성해줘.", target_hint="sample_tool")

    plan = asyncio.run(scenario())

    assert plan is not None
    assert "REPORT.md" in {file.path for file in plan.files}


def test_model_project_planner_normalizes_flat_python_package_layout() -> None:
    llm = FakeLLMClient.text(
        """
        {
          "target_root": "output/flat-cli",
          "language": "python",
          "files": [
            {
              "path": "__init__.py",
              "purpose": "package init",
              "stage": "skeleton",
              "content": "from . import cli\\n",
              "required": true
            },
            {
              "path": "cli.py",
              "purpose": "CLI entrypoint",
              "stage": "implementation",
              "content": "def main():\\n    return 0\\n",
              "required": true
            },
            {
              "path": "tests/test_cli.py",
              "purpose": "tests",
              "stage": "tests",
              "content": "from flat_cli import cli\\n\\ndef test_main():\\n    assert cli.main() == 0\\n",
              "required": true
            }
          ],
          "validation_commands": [
            {"command": "python -m pytest", "cwd": "."}
          ],
          "tasks": []
        }
        """
    )

    async def scenario():
        return await ModelProjectPlanner(
            llm_client=llm,
            settings=ModelSettings(model_name="fake", api_key_env="FAKE_API_KEY"),
        ).create_plan(
            "표준 라이브러리만 사용하는 Python 패키지형 CLI 프로젝트를 생성해줘.",
            target_hint="output/flat-cli",
        )

    plan = asyncio.run(scenario())

    assert plan is not None
    paths = {file.path for file in plan.files}
    assert "flat_cli/__init__.py" in paths
    assert "flat_cli/cli.py" in paths
    assert "tests/test_cli.py" in paths
    assert "pyproject.toml" in paths
    assert "__init__.py" not in paths
    assert "cli.py" not in paths
    assert plan.validation_commands[0].cwd == "output/flat-cli"
