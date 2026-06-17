"""Slash command registry consumed by the TUI palette."""

from __future__ import annotations

from pydantic import Field

from allCode.core.models import CoreModel


class CommandSpec(CoreModel):
    name: str
    description: str
    usage: str
    # Selectable sub-option tokens for commands that take an argument (e.g.
    # /theme -> ["dark", "light"]). Offered as arrow-navigable completions once
    # the command name and a space have been typed.
    options: list[str] = Field(default_factory=list)


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

    def get(self, name: str) -> CommandSpec | None:
        return self._commands.get(name.strip().lower())

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
        CommandSpec(name="/model", description="Show or change the model (writes .allCode/config.yaml).", usage="/model [<name>|impl <name>|base <url>]", options=["impl", "base"]),
        CommandSpec(name="/approval", description="Show or set approval mode: auto (no prompts) or ask.", usage="/approval [auto|ask]", options=["auto", "ask"]),
        CommandSpec(name="/config", description="Show active runtime configuration.", usage="/config"),
        CommandSpec(name="/init", description="Generate an AGENTS.md draft from the project.", usage="/init [force]", options=["force"]),
        CommandSpec(name="/doctor", description="Diagnose config, API key, and setup.", usage="/doctor"),
        CommandSpec(name="/export", description="Save the conversation transcript to a file.", usage="/export [path]"),
        CommandSpec(name="/theme", description="Switch the color theme (dark|light).", usage="/theme [dark|light]", options=["dark", "light"]),
        CommandSpec(name="/pr", description="Commit, push, and open a GitHub PR (gh).", usage="/pr [title]"),
        CommandSpec(name="/agents", description="List defined sub-agents (.allCode/agents).", usage="/agents"),
        CommandSpec(name="/status", description="Show usage gauges and session status (append 'last' for diagnostics).", usage="/status [last]", options=["last"]),
        CommandSpec(name="/stop", description="Cancel the active turn.", usage="/stop"),
        CommandSpec(name="/exit", description="Exit allCode.", usage="/exit"),
        CommandSpec(name="/undo", description="Undo allCode's last auto-commit.", usage="/undo"),
        CommandSpec(name="/rewind", description="Revert the last turn's file changes (checkpoint).", usage="/rewind"),
        CommandSpec(name="/review", description="Show uncommitted changes (git diff).", usage="/review"),
        CommandSpec(name="/compact", description="Summarize and compact the conversation context.", usage="/compact"),
        CommandSpec(name="/cost", description="Show this session's token and context-window usage.", usage="/cost"),
        CommandSpec(name="/clear", description="Clear transcript view.", usage="/clear"),
        CommandSpec(name="/help", description="Show slash commands.", usage="/help"),
    ]
