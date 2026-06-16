"""Slash command execution for the TUI."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Protocol

from allCode.core.models import CoreModel
from allCode.tui.command_registry import CommandRegistry

if TYPE_CHECKING:
    from allCode.tui.custom_commands import CustomCommand


class MemoryCommandBackend(Protocol):
    async def handle(self, command: str) -> str:
        """Execute a memory command and return user-visible output."""


class StatusCommandBackend(Protocol):
    async def handle(self, command: str) -> str:
        """Execute model/tool/config status commands."""


class SlashCommandResult(CoreModel):
    message: str = ""
    clear_transcript: bool = False
    cancel_active: bool = False
    exit_requested: bool = False
    submit_prompt: str | None = None


class SlashCommandHandler:
    def __init__(
        self,
        *,
        registry: CommandRegistry | None = None,
        memory_backend: MemoryCommandBackend | None = None,
        status_backend: StatusCommandBackend | None = None,
        workspace_root: str | None = None,
        custom_commands: dict[str, "CustomCommand"] | None = None,
        compact_backend: Callable[[], str] | None = None,
    ) -> None:
        self.registry = registry or CommandRegistry()
        self.memory_backend = memory_backend
        self.status_backend = status_backend
        self.workspace_root = workspace_root
        self.custom_commands = custom_commands or {}
        self.compact_backend = compact_backend

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
        if normalized.split(maxsplit=1)[0] in {"/tools", "/model", "/approval", "/config", "/status", "/debug"}:
            if self.status_backend is None:
                return SlashCommandResult(message="상태 명령 백엔드가 설정되지 않았습니다.")
            return SlashCommandResult(message=await self.status_backend.handle(normalized))
        if normalized == "/undo":
            return SlashCommandResult(message=self._undo())
        if normalized == "/rewind":
            return SlashCommandResult(message=self._rewind())
        if normalized in {"/review", "/diff"}:
            from allCode.workspace.git_ops import working_tree_diff

            return SlashCommandResult(message=working_tree_diff(self.workspace_root or "."))
        if normalized == "/compact":
            if self.compact_backend is None:
                return SlashCommandResult(message="컨텍스트 압축 백엔드가 설정되지 않았습니다.")
            return SlashCommandResult(message=self.compact_backend())
        if normalized in {"/help", "/commands"}:
            return SlashCommandResult(message=self._help_text())
        custom_name = normalized.split(maxsplit=1)[0]
        if custom_name in self.custom_commands:
            from allCode.tui.custom_commands import expand_command

            args = normalized[len(custom_name) :].strip()
            template = self.custom_commands[custom_name].template
            return SlashCommandResult(submit_prompt=expand_command(template, args))
        return SlashCommandResult(message=f"알 수 없는 명령어입니다: {normalized}")

    def _undo(self) -> str:
        from allCode.workspace.git_ops import undo_last_allcode_commit

        root = self.workspace_root or "."
        return undo_last_allcode_commit(root).message

    def _rewind(self) -> str:
        from allCode.workspace.checkpoint_store import CheckpointStore

        return CheckpointStore(self.workspace_root or ".").restore_latest()

    def _help_text(self) -> str:
        return "\n".join(f"- {command.usage}: {command.description}" for command in self.registry.all())
