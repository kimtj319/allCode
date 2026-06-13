"""Provider-neutral language strategy selection."""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from allCode.agent.task_plan import ProjectPlan, ValidationCommand
from allCode.core.models import CoreModel


class GenerationRequest(CoreModel):
    prompt: str
    workspace_root: str
    target_root: str | None = None
    language_hint: str | None = None


class LanguageStrategy(Protocol):
    language: str
    aliases: Sequence[str]

    def create_plan(self, request: GenerationRequest) -> ProjectPlan:
        raise NotImplementedError("language strategies must create a project plan")

    def repair_files(self, plan: ProjectPlan, failure_log: str) -> dict[str, str]:
        raise NotImplementedError("language strategies must return repair file contents")


class StrategyRegistry:
    def __init__(self, strategies: list[LanguageStrategy]) -> None:
        if not strategies:
            raise ValueError("at least one language strategy is required")
        self._strategies = strategies

    def select(self, request: GenerationRequest) -> LanguageStrategy:
        hint = (request.language_hint or request.prompt).lower()
        for strategy in self._strategies:
            if any(alias in hint for alias in strategy.aliases):
                return strategy
        return self._strategies[-1]


def infer_target_root(prompt: str) -> str:
    lowered = prompt.lower()
    patterns = (
        r"\bnamed\s+([A-Za-z0-9_.-]+)",
        r"\bcalled\s+([A-Za-z0-9_.-]+)",
        r"\bproject\s+([A-Za-z0-9_.-]+)",
        r"프로젝트\s+([A-Za-z0-9_.-]+)",
        r"이름은\s+([A-Za-z0-9_.-]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, prompt, flags=re.IGNORECASE)
        if match:
            return safe_name(match.group(1))
    path_match = re.search(r"(?:in|under|at)\s+([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)", lowered)
    if path_match:
        return safe_name(Path(path_match.group(1)).name)
    return "generated_project"


def safe_name(value: str) -> str:
    lowered = value.strip().lower().replace("-", "_")
    cleaned = re.sub(r"[^a-z0-9_]+", "_", lowered).strip("_")
    if not cleaned:
        return "generated_project"
    if cleaned[0].isdigit():
        cleaned = f"project_{cleaned}"
    return cleaned


# Python filenames the scaffold owns itself and must never be treated as the
# user's requested implementation module.
_RESERVED_PY_NAMES = {"setup.py", "__init__.py", "__main__.py", "conftest.py", "pyproject.py"}


def explicit_module_names(prompt: str) -> tuple[str | None, str | None]:
    """Extract an explicit implementation and test module name from the prompt.

    A request like "클래스명: CircuitBreaker (파일명: breaker.py)" and
    "테스트 파일(test_breaker.py)" should produce ``breaker.py`` / ``test_breaker.py``
    instead of the generic ``main.py`` / ``test_main.py`` scaffold names. Returns
    ``(module, test_module)`` stems (without ``.py``), each ``None`` when the
    prompt does not name one. The scaffold falls back to ``main`` / ``test_main``.
    """
    impl: str | None = None
    test: str | None = None
    for raw in re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\.py\b", prompt):
        filename = f"{raw}.py"
        if filename in _RESERVED_PY_NAMES:
            continue
        stem = raw.lower()
        if stem.startswith("test_") or stem.endswith("_test"):
            if test is None:
                test = safe_name(stem)
            continue
        if impl is None:
            impl = safe_name(stem)
    # If only a test file was named (e.g. test_breaker.py), derive the module
    # from it so imports stay consistent.
    if impl is None and test is not None and test.startswith("test_"):
        impl = test[len("test_") :] or None
    return impl, test


def safe_target_root(value: str) -> str:
    normalized = value.strip().strip("/").replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    parts = [part for part in normalized.split("/") if part]
    if not parts or any(part in {".", "..", ".git", ".venv", "node_modules"} for part in parts):
        return "generated_project"
    return "/".join(safe_name(part) for part in parts)


def validation_command(command: str, *, cwd: str = ".", timeout_seconds: int = 180, environment: dict[str, str] | None = None) -> ValidationCommand:
    return ValidationCommand(
        command=command,
        cwd=cwd,
        timeout_seconds=timeout_seconds,
        environment=environment or {},
    )
