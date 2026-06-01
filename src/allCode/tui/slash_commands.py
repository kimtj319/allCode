"""Slash command execution for the TUI."""

from __future__ import annotations

from typing import Protocol

from allCode.core.models import CoreModel
from allCode.tui.command_registry import CommandRegistry


class MemoryCommandBackend(Protocol):
    async def handle(self, command: str) -> str:
        """Execute a memory command and return user-visible output."""


class SlashCommandResult(CoreModel):
    message: str = ""
    clear_transcript: bool = False
    cancel_active: bool = False
    exit_requested: bool = False


class SlashCommandHandler:
    def __init__(
        self,
        *,
        registry: CommandRegistry | None = None,
        memory_backend: MemoryCommandBackend | None = None,
    ) -> None:
        self.registry = registry or CommandRegistry()
        self.memory_backend = memory_backend

    async def handle(self, command: str) -> SlashCommandResult:
        normalized = " ".join(command.strip().split())
        if not normalized.startswith("/"):
            return SlashCommandResult(message="명령어는 /로 시작해야 합니다.")
        if normalized == "/clear":
            return SlashCommandResult(message="대화 화면을 비웠습니다.", clear_transcript=True)
        if normalized == "/stop":
            return SlashCommandResult(message="현재 작업을 중단합니다.", cancel_active=True)
        if normalized == "/exit":
            return SlashCommandResult(message="allCode를 종료합니다.", cancel_active=True, exit_requested=True)
        if normalized.startswith("/memory"):
            if self.memory_backend is None:
                return SlashCommandResult(message="메모리 명령 백엔드가 설정되지 않았습니다.")
            return SlashCommandResult(message=await self.memory_backend.handle(normalized))
        if normalized in {"/help", "/commands"}:
            return SlashCommandResult(message=self._help_text())
        return SlashCommandResult(message=f"알 수 없는 명령어입니다: {normalized}")

    def _help_text(self) -> str:
        return "\n".join(f"- {command.usage}: {command.description}" for command in self.registry.all())
