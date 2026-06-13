"""Slash command registry consumed by the TUI palette."""

from __future__ import annotations

from allCode.core.models import CoreModel


class CommandSpec(CoreModel):
    name: str
    description: str
    usage: str


class CommandRegistry:
    def __init__(self, commands: list[CommandSpec] | None = None) -> None:
        self._commands: dict[str, CommandSpec] = {}
        for command in commands or default_commands():
            self.register(command)

    def register(self, command: CommandSpec) -> None:
        key = command.name.strip().lower()
        if not key.startswith("/"):
            raise ValueError("slash command names must start with /")
        if key in self._commands:
            raise ValueError(f"command already registered: {command.name}")
        self._commands[key] = command

    def all(self) -> list[CommandSpec]:
        return list(self._commands.values())

    def filter(self, query: str) -> list[CommandSpec]:
        normalized = query.lstrip("/").strip().lower()
        if not normalized:
            return self.all()
        return [
            command
            for command in self._commands.values()
            if normalized in command.name.lower() or normalized in command.description.lower()
        ]


def default_commands() -> list[CommandSpec]:
    return [
        CommandSpec(name="/memory show", description="Show active memory.", usage="/memory show"),
        CommandSpec(name="/memory add", description="Add project memory.", usage="/memory add <text>"),
        CommandSpec(name="/memory refresh", description="Reload active memory.", usage="/memory refresh"),
        CommandSpec(name="/tools", description="Show available tools.", usage="/tools"),
        CommandSpec(name="/model", description="Show active model configuration.", usage="/model"),
        CommandSpec(name="/config", description="Show active runtime configuration.", usage="/config"),
        CommandSpec(name="/status last", description="Show latest session diagnostics.", usage="/status last"),
        CommandSpec(name="/debug last", description="Show raw latest session diagnostics.", usage="/debug last"),
        CommandSpec(name="/stop", description="Cancel the active turn.", usage="/stop"),
        CommandSpec(name="/exit", description="Exit allCode.", usage="/exit"),
        CommandSpec(name="/undo", description="Undo allCode's last auto-commit.", usage="/undo"),
        CommandSpec(name="/clear", description="Clear transcript view.", usage="/clear"),
        CommandSpec(name="/help", description="Show slash commands.", usage="/help"),
    ]
