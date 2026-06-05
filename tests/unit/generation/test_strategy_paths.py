from __future__ import annotations

from allCode.generation.strategies.python import PythonProjectStrategy
from allCode.generation.strategy import GenerationRequest, safe_target_root


def test_safe_target_root_preserves_safe_directory_structure() -> None:
    assert safe_target_root("./output/phase41-sample-cli") == "output/phase41_sample_cli"


def test_python_strategy_uses_last_path_segment_as_package_name() -> None:
    plan = PythonProjectStrategy().create_plan(
        GenerationRequest(
            prompt="Python CLI 프로젝트를 만들어줘",
            workspace_root=".",
            target_root="./output/phase41-sample-cli",
        )
    )

    assert plan.target_root == "output/phase41_sample_cli"
    assert "src/phase41_sample_cli/main.py" in plan.required_paths()
    assert plan.validation_commands[0].cwd == "output/phase41_sample_cli"


def test_python_strategy_generates_kebab_case_argparse_cli_when_requested() -> None:
    plan = PythonProjectStrategy().create_plan(
        GenerationRequest(
            prompt="Python CLI로 입력 문자열을 kebab-case로 바꾸고 argparse 명령어와 pytest 테스트를 포함해줘",
            workspace_root=".",
            target_root="./output/phase41-sample-cli",
        )
    )
    files = {file.path: file.content for file in plan.files}

    assert 'name = "phase41-sample-cli"' in files["pyproject.toml"]
    assert "def to_kebab_case" in files["src/phase41_sample_cli/main.py"]
    assert "argparse.ArgumentParser" in files["src/phase41_sample_cli/main.py"]
    assert "test_main_prints_converted_text" in files["tests/test_main.py"]
