"""Python skeleton-first generation strategy."""

from __future__ import annotations

from allCode.agent.task_plan import ApiObligation, PlannedFile, ProjectPlan, TaskItem
from pathlib import PurePosixPath

from allCode.generation.strategy import (
    GenerationRequest,
    explicit_module_names,
    infer_target_root,
    safe_name,
    safe_target_root,
    validation_command,
)


class PythonProjectStrategy:
    language = "python"
    aliases = ("python", "pytest", ".py", "파이썬")

    def create_plan(self, request: GenerationRequest) -> ProjectPlan:
        target = safe_target_root(request.target_root or infer_target_root(request.prompt))
        package = safe_name(PurePosixPath(target).name)
        # Honor an explicit module/test filename from the prompt (e.g. "파일명:
        # breaker.py") instead of the generic main.py/test_main.py scaffold names.
        module, explicit_test = explicit_module_names(request.prompt)
        module = module or "main"
        test_module = explicit_test or f"test_{module}"
        featureful_cli = _requests_featureful_cli(request.prompt)
        main_content = self._cli_main_implementation() if featureful_cli else self._main_implementation()
        readme_content = self._cli_readme(target, package, module) if featureful_cli else self._readme(target, package, module)
        test_content = self._cli_tests(package, module) if featureful_cli else self._tests(package, module)
        return ProjectPlan(
            target_root=target,
            language=self.language,
            constraints=["Use a dependency-light src layout.", "Validate with pytest."],
            files=[
                PlannedFile(path="pyproject.toml", purpose="package metadata", stage="skeleton", content=self._pyproject(target)),
                PlannedFile(path=f"src/{package}/__init__.py", purpose="package marker", stage="skeleton", content='"""Generated package."""\n'),
                PlannedFile(path=f"src/{package}/{module}.py", purpose="public application API", stage="skeleton", content=self._main_skeleton()),
                PlannedFile(path=f"src/{package}/{module}.py", purpose="public application API", stage="implementation", content=main_content),
                PlannedFile(path="README.md", purpose="project usage documentation", stage="implementation", content=readme_content),
                PlannedFile(path=f"tests/{test_module}.py", purpose="pytest coverage for public API", stage="tests", content=test_content),
            ],
            validation_commands=[
                validation_command("python -m pytest", cwd=target, environment={"PYTHONPATH": "src"}),
            ],
            api_obligations=self._cli_api_obligations(package, module) if featureful_cli else [],
            tasks=[
                TaskItem(description="Create package skeleton and project metadata.", step="skeleton"),
                TaskItem(description="Implement the public application API.", step="implementation"),
                TaskItem(description="Add validation tests.", step="tests"),
                TaskItem(description="Run pytest validation.", step="validation"),
            ],
        )

    def repair_files(self, plan: ProjectPlan, failure_log: str) -> dict[str, str]:
        package = safe_name(PurePosixPath(plan.target_root).name)
        module, test_module = _plan_module_names(plan, package)
        if any(obligation.symbol == "TaskStore" for obligation in plan.api_obligations):
            files = {f"src/{package}/{module}.py": self._cli_main_implementation()}
            if "test coverage " in failure_log:
                files[f"tests/{test_module}.py"] = self._cli_tests(package, module)
            if "documentation references " in failure_log:
                files["README.md"] = self._cli_readme(plan.target_root, package, module)
            return files
        return {f"src/{package}/{module}.py": self._main_implementation()}

    def _pyproject(self, name: str) -> str:
        distribution = safe_name(PurePosixPath(name).name).replace("_", "-")
        return "\n".join(
            [
                "[project]",
                f'name = "{distribution}"',
                'version = "0.1.0"',
                f'description = "Generated Python project {distribution}."',
                'requires-python = ">=3.11"',
                "",
                "[tool.pytest.ini_options]",
                'pythonpath = ["src"]',
                'testpaths = ["tests"]',
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

    def _readme(self, target: str, package: str, module: str = "main") -> str:
        return "\n".join(
            [
                f"# {PurePosixPath(target).name}",
                "",
                "Small Python CLI scaffold generated by allCode.",
                "",
                "## Usage",
                "",
                f"Run the package module with `python -m {package}.{module}` or import `greet` from `{package}.{module}`.",
                "",
                "## Validation",
                "",
                "```bash",
                "PYTHONPATH=src python -m pytest",
                "```",
                "",
            ]
        )

    def _tests(self, package: str, module: str = "main") -> str:
        return "\n".join(
            [
                f"from {package}.{module} import greet",
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

    def _cli_api_obligations(self, package: str, module: str = "main") -> list[ApiObligation]:
        path = f"src/{package}/{module}.py"
        symbols = (
            "retry",
            "TaskStore",
            "TaskStore.add",
            "TaskStore.list",
            "TaskStore.mark_done",
            "TaskStore.export",
            "CommandRegistry",
            "CommandRegistry.register",
            "CommandRegistry.dispatch",
            "build_parser",
            "main",
        )
        return [ApiObligation(path=path, symbol=symbol, reason="featureful CLI scaffold contract") for symbol in symbols]

    def _cli_main_implementation(self) -> str:
        return '''"""Standard-library task CLI implementation."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Callable


def retry(attempts: int = 3, delay: float = 0.0, exceptions: tuple[type[BaseException], ...] = (Exception,)):
    """Return a decorator that retries a callable for transient failures."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_error = exc
                    if attempt < attempts - 1 and delay:
                        time.sleep(delay)
            raise last_error
        return wrapper
    return decorator


class TaskStore:
    """JSON-backed task storage."""

    def __init__(self, path: str | Path = "tasks.json") -> None:
        self.path = Path(path)
        self._tasks: list[dict] = []
        self._load()

    @retry()
    def _load(self) -> None:
        if not self.path.exists():
            self._tasks = []
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self._tasks = data if isinstance(data, list) else []

    @retry()
    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._tasks, indent=2), encoding="utf-8")

    def add(self, title: str) -> dict:
        task = {"id": self._next_id(), "title": title, "done": False}
        self._tasks.append(task)
        self._save()
        return task

    def list(self, *, include_done: bool = False) -> list[dict]:
        if include_done:
            return list(self._tasks)
        return [task for task in self._tasks if not task.get("done")]

    def mark_done(self, task_id: int) -> dict | None:
        for task in self._tasks:
            if task.get("id") == task_id:
                task["done"] = True
                self._save()
                return task
        return None

    def export(self, destination: str | Path) -> Path:
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self._tasks, indent=2), encoding="utf-8")
        return target

    def _next_id(self) -> int:
        return max((int(task.get("id", 0)) for task in self._tasks), default=0) + 1


class CommandRegistry:
    """Map command names to handlers."""

    def __init__(self) -> None:
        self._commands: dict[str, Callable[[TaskStore, argparse.Namespace], int]] = {}

    def register(self, name: str, handler: Callable[[TaskStore, argparse.Namespace], int]) -> None:
        self._commands[name] = handler

    def dispatch(self, name: str, store: TaskStore, args: argparse.Namespace) -> int:
        return self._commands[name](store, args)


def _cmd_add(store: TaskStore, args: argparse.Namespace) -> int:
    task = store.add(args.title)
    print(f"added {task['id']}: {task['title']}")
    return 0


def _cmd_list(store: TaskStore, args: argparse.Namespace) -> int:
    for task in store.list(include_done=args.all):
        status = "done" if task.get("done") else "pending"
        print(f"{task['id']}\\t{status}\\t{task['title']}")
    return 0


def _cmd_done(store: TaskStore, args: argparse.Namespace) -> int:
    return 0 if store.mark_done(args.id) else 1


def _cmd_export(store: TaskStore, args: argparse.Namespace) -> int:
    store.export(args.output)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="taskhub")
    parser.add_argument("--store", default="tasks.json")
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add")
    add.add_argument("title")
    listing = sub.add_parser("list")
    listing.add_argument("--all", action="store_true")
    done = sub.add_parser("done")
    done.add_argument("id", type=int)
    export = sub.add_parser("export")
    export.add_argument("output")
    return parser


def _registry() -> CommandRegistry:
    registry = CommandRegistry()
    registry.register("add", _cmd_add)
    registry.register("list", _cmd_list)
    registry.register("done", _cmd_done)
    registry.register("export", _cmd_export)
    return registry


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    store = TaskStore(args.store)
    return _registry().dispatch(args.command, store, args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
'''

    def _cli_tests(self, package: str, module: str = "main") -> str:
        return f'''import pytest

from {package}.{module} import CommandRegistry, TaskStore, retry


def test_retry_retries_once() -> None:
    calls = {{"count": 0}}

    @retry(attempts=2, exceptions=(ValueError,))
    def flaky() -> str:
        calls["count"] += 1
        if calls["count"] == 1:
            raise ValueError("temporary")
        return "ok"

    assert flaky() == "ok"
    assert calls["count"] == 2


def test_task_store_add_list_done_and_export(tmp_path) -> None:
    store = TaskStore(tmp_path / "tasks.json")
    first = store.add("write tests")
    second = store.add("ship cli")

    assert [task["title"] for task in store.list()] == ["write tests", "ship cli"]
    assert store.mark_done(first["id"]) == {{"id": first["id"], "title": "write tests", "done": True}}
    assert [task["id"] for task in store.list()] == [second["id"]]

    exported = store.export(tmp_path / "export.json")
    assert exported.exists()
    assert "ship cli" in exported.read_text(encoding="utf-8")


def test_command_registry_dispatches_registered_handler(tmp_path) -> None:
    registry = CommandRegistry()
    store = TaskStore(tmp_path / "tasks.json")

    def handler(task_store, args):
        task_store.add(args.title)
        return 7

    registry.register("add", handler)
    assert registry.dispatch("add", store, type("Args", (), {{"title": "from registry"}})()) == 7
    assert store.list()[0]["title"] == "from registry"
'''

    def _cli_readme(self, target: str, package: str, module: str = "main") -> str:
        return "\n".join(
            [
                f"# {PurePosixPath(target).name}",
                "",
                "Standard-library task tracker CLI generated by allCode.",
                "",
                "## Project Structure",
                "",
                "```text",
                f"{PurePosixPath(target).name}/",
                "├─ pyproject.toml",
                "├─ README.md",
                "├─ src/",
                f"│  └─ {package}/",
                "│     ├─ __init__.py",
                f"│     └─ {module}.py",
                "└─ tests/",
                f"   └─ test_{module}.py",
                "```",
                "",
                "## Usage",
                "",
                f"Run `python -m {package}.{module} add \"Write tests\"` from an installed environment.",
                "",
                "## Validation",
                "",
                "```bash",
                "PYTHONPATH=src python -m pytest",
                "```",
                "",
            ]
        )


def _plan_module_names(plan: ProjectPlan, package: str) -> tuple[str, str]:
    """Recover the implementation module and test module stems from a plan.

    repair_files only sees the plan (not the original prompt), so honor whatever
    filenames the plan already settled on instead of re-hardcoding main.py.
    """
    module = "main"
    test_module = "test_main"
    src_prefix = f"src/{package}/"
    for planned_file in plan.files:
        path = planned_file.path.replace("\\", "/")
        name = path.rsplit("/", 1)[-1]
        if not name.endswith(".py"):
            continue
        stem = name[: -len(".py")]
        if path.startswith("tests/") or name.startswith("test_"):
            test_module = stem
        elif path.startswith(src_prefix) and stem != "__init__":
            module = stem
    return module, test_module


def _requests_featureful_cli(prompt: str) -> bool:
    lowered = prompt.lower()
    compact = lowered.replace(" ", "")
    cli = any(term in lowered for term in ("cli", "command", "entrypoint", "argparse")) or any(
        term in prompt for term in ("명령어", "커맨드", "진입점")
    )
    feature = any(term in lowered or term in compact for term in ("registry", "retry", "json", "task", "export", "pytest")) or any(
        term in prompt for term in ("레지스트리", "재시도", "저장소", "테스트", "검증")
    )
    return cli and feature
