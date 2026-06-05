from __future__ import annotations

import asyncio

from allCode.agent.project_planner import ModelProjectPlanner
from allCode.llm.settings import ModelSettings
from tests.helpers.fake_llm import FakeLLMClient


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
