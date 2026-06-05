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
