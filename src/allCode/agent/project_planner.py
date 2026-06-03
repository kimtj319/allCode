"""Model-backed project planning for generation workflow."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence

from allCode.agent.task_plan import PlannedFile, ProjectPlan, ValidationCommand
from allCode.core.models import Message
from allCode.llm.client import LLMClient
from allCode.llm.settings import ModelSettings


class ModelProjectPlanner:
    """Ask the model for a compact, validated project plan.

    The planner is deliberately optional. Any invalid, unsafe, or non-JSON
    response falls back to the deterministic language strategy path.
    """

    def __init__(self, *, llm_client: LLMClient, settings: ModelSettings) -> None:
        self._llm_client = llm_client
        self._settings = settings

    async def create_plan(self, prompt: str, *, target_hint: str | None = None) -> ProjectPlan | None:
        planner_settings = self._settings.model_copy(
            update={
                "temperature": 0.0,
                "max_output_tokens": max(self._settings.max_output_tokens, 6000),
            }
        )
        response = await self._llm_client.complete(
            self._messages(prompt, target_hint=target_hint),
            tools=[],
            settings=planner_settings,
        )
        payload = _extract_json_object(response.final_text)
        if payload is None:
            return None
        try:
            plan = ProjectPlan.model_validate(payload)
        except Exception:
            return None
        return _sanitize_plan(plan)

    def _messages(self, prompt: str, *, target_hint: str | None) -> Sequence[Message]:
        target_line = f"Explicit target hint: {target_hint}" if target_hint else "Explicit target hint: none"
        return [
            Message(
                role="system",
                content=(
                    "You are a project planning component for allCode. "
                    "Return only one JSON object matching this schema: "
                    "{target_root, language, constraints, files, validation_commands, tasks}. "
                    "Each file item must have path, purpose, stage, content, required. "
                    "Allowed stages are skeleton, implementation, tests. "
                    "Use relative paths only, never absolute paths or '..'. "
                    "Make files complete and runnable. Do not include markdown fences. "
                    "Validation commands must be test/build commands only."
                ),
            ),
            Message(
                role="user",
                content=(
                    f"{target_line}\n"
                    "Create a skeleton-first implementation plan for this request. "
                    "If the request mentions a directory, either set target_root to that directory "
                    "and make file paths relative to it, or set target_root to '.' and include the directory in file paths. "
                    "The plan must include implementation files, tests when validation is requested or implied, "
                    "and validation commands that can run without installing external services.\n\n"
                    f"User request:\n{prompt}"
                ),
            ),
        ]


def _extract_json_object(text: str) -> dict | None:
    stripped = text.strip()
    if not stripped:
        return None
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        if not match:
            return None
        try:
            value = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return value if isinstance(value, dict) else None


def _sanitize_plan(plan: ProjectPlan) -> ProjectPlan | None:
    target_root = _safe_root(plan.target_root)
    if target_root is None:
        return None
    files: list[PlannedFile] = []
    for planned_file in plan.files:
        path = _safe_relative_path(planned_file.path)
        if path is None:
            return None
        if target_root != "." and path.startswith(f"{target_root}/"):
            path = path[len(target_root) + 1 :]
        files.append(planned_file.model_copy(update={"path": path}))
    if not files:
        return None
    commands: list[ValidationCommand] = []
    for command in plan.validation_commands:
        sanitized = _sanitize_validation_command(command, target_root=target_root)
        if sanitized is not None:
            commands.append(sanitized)
    return plan.model_copy(update={"target_root": target_root, "files": files, "validation_commands": commands})


def _safe_root(value: str) -> str | None:
    normalized = value.strip().strip("/").replace("\\", "/")
    if normalized == ".":
        return "."
    if not normalized or normalized.startswith("/") or ".." in normalized.split("/"):
        return None
    if any(part in {".git", ".venv", "node_modules"} for part in normalized.split("/")):
        return None
    return normalized


def _safe_relative_path(value: str) -> str | None:
    normalized = value.strip().replace("\\", "/")
    if not normalized or normalized.startswith("/") or ".." in normalized.split("/"):
        return None
    if any(part in {".git", ".venv", "node_modules"} for part in normalized.split("/")):
        return None
    return normalized


def _sanitize_validation_command(command: ValidationCommand, *, target_root: str) -> ValidationCommand | None:
    raw_command = command.command.strip()
    if not raw_command or any(token in raw_command for token in (";", "&&", "||", "|", "`", "$(")):
        return None
    lowered = raw_command.lower()
    allowed_markers = (
        "pytest",
        "python -m pytest",
        "python -m py_compile",
        "unittest",
        "node --test",
        "npm test",
        "npm run test",
        "go test",
        "cargo test",
        "gradle test",
        "./gradlew test",
        "mvn test",
        "javac",
    )
    if not any(marker in lowered for marker in allowed_markers):
        return None
    cwd = command.cwd.strip() or "."
    if target_root != "." and cwd == ".":
        cwd = target_root
    if _safe_relative_path(cwd) is None and cwd != ".":
        return None
    return command.model_copy(update={"command": raw_command, "cwd": cwd})
