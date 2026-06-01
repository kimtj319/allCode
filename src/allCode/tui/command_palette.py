"""Slash command palette backend."""

from __future__ import annotations

from pydantic import Field

from allCode.core.models import CoreModel
from allCode.tui.command_registry import CommandRegistry, CommandSpec


class CommandPalette:
    def __init__(self, registry: CommandRegistry | None = None) -> None:
        self.registry = registry or CommandRegistry()

    def visible_for(self, text: str) -> bool:
        return text.startswith("/")

    def filter(self, text: str) -> list[CommandSpec]:
        return self.registry.filter(text)


class CommandPaletteState(CoreModel):
    visible: bool = False
    query: str = ""
    matches: list[CommandSpec] = Field(default_factory=list)

    def update(self, text: str, palette: CommandPalette) -> None:
        self.visible = palette.visible_for(text)
        self.query = text
        self.matches = palette.filter(text) if self.visible else []
