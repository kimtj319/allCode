"""Slash and path completion for the terminal composer."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from allCode.tui.command_registry import CommandRegistry


@dataclass(frozen=True)
class CompletionCandidate:
    replacement: str
    label: str
    description: str = ""


@dataclass
class CompletionState:
    start: int
    end: int
    candidates: list[CompletionCandidate]
    selected: int = 0

    def current(self) -> CompletionCandidate:
        return self.candidates[self.selected]

    def advance(self) -> CompletionCandidate:
        self.selected = (self.selected + 1) % len(self.candidates)
        return self.current()


class TerminalCompleter:
    """Build completion candidates without owning the editor state."""

    def __init__(self, *, registry: CommandRegistry, cwd: Path) -> None:
        self.registry = registry
        self.cwd = cwd

    def complete(self, text: str, cursor: int) -> CompletionState | None:
        slash = self._slash_completion(text, cursor)
        if slash is not None:
            return slash
        return self._path_completion(text, cursor)

    def _slash_completion(self, text: str, cursor: int) -> CompletionState | None:
        before = text[:cursor]
        if "\n" in before or not before.startswith("/"):
            return None
        query = before.lower()
        commands = self.registry.all()
        matches = [command for command in commands if command.name.lower().startswith(query)]
        if not matches:
            matches = [command for command in commands if command.usage.lower().startswith(query)]
        if not matches:
            matches = self.registry.filter(before)
        if not matches:
            return None
        candidates = [
            CompletionCandidate(
                replacement=command.name,
                label=command.usage,
                description=command.description,
            )
            for command in matches
        ]
        return CompletionState(start=0, end=cursor, candidates=candidates)

    def _path_completion(self, text: str, cursor: int) -> CompletionState | None:
        before = text[:cursor]
        marker = before.rfind("@")
        if marker == -1:
            return None
        token = before[marker + 1 :]
        if any(char.isspace() for char in token):
            return None
        base_dir, prefix = self._path_base(token)
        if not base_dir.exists() or not base_dir.is_dir():
            return None
        candidates: list[CompletionCandidate] = []
        for child in sorted(base_dir.iterdir(), key=lambda path: (not path.is_dir(), path.name.lower())):
            if not child.name.startswith(prefix):
                continue
            relative = child.relative_to(self.cwd) if self._is_relative_to(child, self.cwd) else child
            replacement = "@" + str(relative)
            if child.is_dir():
                replacement += "/"
            candidates.append(
                CompletionCandidate(
                    replacement=replacement,
                    label=replacement,
                    description="directory" if child.is_dir() else "file",
                )
            )
            if len(candidates) >= 8:
                break
        if not candidates:
            return None
        return CompletionState(start=marker, end=cursor, candidates=candidates)

    def _path_base(self, token: str) -> tuple[Path, str]:
        token_path = Path(token).expanduser()
        if token.endswith("/"):
            return self._resolve_token_path(token_path), ""
        parent = token_path.parent
        prefix = token_path.name
        if str(parent) in {"", "."}:
            return self.cwd, prefix
        return self._resolve_token_path(parent), prefix

    def _resolve_token_path(self, path: Path) -> Path:
        if path.is_absolute():
            return path
        return (self.cwd / path).resolve()

    @staticmethod
    def _is_relative_to(path: Path, parent: Path) -> bool:
        try:
            path.resolve().relative_to(parent.resolve())
            return True
        except ValueError:
            return False
