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


def test_python_strategy_repair_uses_last_path_segment_as_package_name() -> None:
    plan = PythonProjectStrategy().create_plan(
        GenerationRequest(
            prompt="Python CLI 프로젝트를 만들어줘",
            workspace_root=".",
            target_root="./output/phase41-sample-cli",
        )
    )

    repaired = PythonProjectStrategy().repair_files(plan, "validation failed")

    assert set(repaired) == {"src/phase41_sample_cli/main.py"}


def test_python_strategy_generates_generic_structure_for_kebab_case_request() -> None:
    plan = PythonProjectStrategy().create_plan(
        GenerationRequest(
            prompt="Python CLI로 입력 문자열을 kebab-case로 바꾸고 argparse 명령어와 pytest 테스트를 포함해줘",
            workspace_root=".",
            target_root="./output/phase41-sample-cli",
        )
    )
    files = {file.path: file.content for file in plan.files}

    assert 'name = "phase41-sample-cli"' in files["pyproject.toml"]
    assert 'pythonpath = ["src"]' in files["pyproject.toml"]
    assert 'testpaths = ["tests"]' in files["pyproject.toml"]
    assert "src/phase41_sample_cli/main.py" in files
    assert "tests/test_main.py" in files
    assert "README.md" in files


def test_python_strategy_generates_generic_structure_for_ops_platform_request() -> None:
    plan = PythonProjectStrategy().create_plan(
        GenerationRequest(
            prompt=(
                "Python 표준 라이브러리로 CLI entrypoint, config loader, task registry, "
                "job runner with retry/backoff, JSONL audit logger, plugin modules, pytest tests, README를 생성해줘"
            ),
            workspace_root=".",
            target_root="./output/complex-ops-platform",
        )
    )
    paths = set(plan.required_paths())

    assert plan.target_root == "output/complex_ops_platform"
    assert "src/complex_ops_platform/main.py" in paths
    assert "tests/test_main.py" in paths
    assert "README.md" in paths


def test_python_strategy_generates_featureful_cli_contract_for_registry_retry_json_request() -> None:
    plan = PythonProjectStrategy().create_plan(
        GenerationRequest(
            prompt=(
                "표준 라이브러리 Python CLI로 command registry, add/list/done/export, "
                "JSON storage, retry helper, pytest tests, README를 포함한 도구를 생성해줘"
            ),
            workspace_root=".",
            target_root="./output/task-hub",
        )
    )
    files = {file.path: file.content for file in plan.files}
    symbols = {(obligation.path, obligation.symbol) for obligation in plan.api_obligations}

    assert ("src/task_hub/main.py", "TaskStore.add") in symbols
    assert ("src/task_hub/main.py", "CommandRegistry.dispatch") in symbols
    assert "class TaskStore" in files["src/task_hub/main.py"]
    assert "class CommandRegistry" in files["src/task_hub/main.py"]
    assert "test_task_store_add_list_done_and_export" in files["tests/test_main.py"]
    assert "TaskStore" in files["tests/test_main.py"]
    assert "_storage.py" not in files["README.md"]
