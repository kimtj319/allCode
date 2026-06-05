"""Generation workflow planning contracts."""

from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import Field, field_validator

from allCode.core.models import CoreModel

TaskStatus = Literal["pending", "running", "succeeded", "failed", "skipped"]
GenerationStep = Literal["skeleton", "implementation", "tests", "validation", "repair", "final_report"]
PlannedFileStage = Literal["skeleton", "implementation", "tests"]


class TaskItem(CoreModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    description: str
    step: GenerationStep
    status: TaskStatus = "pending"
    evidence: list[str] = Field(default_factory=list)


class PlannedFile(CoreModel):
    path: str
    purpose: str
    stage: PlannedFileStage
    content: str
    required: bool = True

    @field_validator("path")
    @classmethod
    def require_relative_path(cls, value: str) -> str:
        normalized = value.strip().replace("\\", "/")
        if not normalized or normalized.startswith("/") or ".." in normalized.split("/"):
            raise ValueError("planned file paths must be relative to the target root")
        return normalized

    @field_validator("content")
    @classmethod
    def require_content(cls, value: str) -> str:
        if not value:
            raise ValueError("planned file content must not be empty")
        return value


class ValidationCommand(CoreModel):
    command: str
    cwd: str = "."
    timeout_seconds: int = 180
    environment: dict[str, str] = Field(default_factory=dict)

    @field_validator("command")
    @classmethod
    def require_command(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("validation command must not be empty")
        return stripped


class ApiObligation(CoreModel):
    path: str
    symbol: str
    reason: str = ""

    @field_validator("path")
    @classmethod
    def require_relative_path(cls, value: str) -> str:
        normalized = value.strip().replace("\\", "/")
        if not normalized or normalized.startswith("/") or ".." in normalized.split("/"):
            raise ValueError("api obligation paths must be relative to the target root")
        return normalized

    @field_validator("symbol")
    @classmethod
    def require_symbol(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("api obligation symbol must not be empty")
        return stripped


class ProjectPlan(CoreModel):
    target_root: str
    language: str
    files: list[PlannedFile] = Field(default_factory=list)
    validation_commands: list[ValidationCommand] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    forbidden_files: list[str] = Field(default_factory=list)
    tasks: list[TaskItem] = Field(default_factory=list)
    api_obligations: list[ApiObligation] = Field(default_factory=list)

    @field_validator("target_root")
    @classmethod
    def require_safe_target_root(cls, value: str) -> str:
        normalized = value.strip().strip("/").replace("\\", "/")
        if not normalized or ".." in normalized.split("/"):
            raise ValueError("target root must be a safe relative path")
        return normalized

    def files_for_step(self, step: PlannedFileStage) -> list[PlannedFile]:
        return [planned_file for planned_file in self.files if planned_file.stage == step]

    def required_paths(self) -> list[str]:
        return [planned_file.path for planned_file in self.files if planned_file.required]
