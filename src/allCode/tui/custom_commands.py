"""User-defined slash commands loaded from ``.allCode/commands/*.md``.

Each markdown file becomes a ``/<stem>`` command whose body is a prompt template.
``$ARGUMENTS`` (or ``{{args}}``) in the template is replaced with the text typed
after the command; if the template has no placeholder, the arguments are appended.
Invoking the command submits the expanded prompt as a normal turn.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


@dataclass(frozen=True)
class CustomCommand:
    name: str  # includes leading slash, e.g. "/review"
    description: str
    template: str


def load_custom_commands(project_root: str | Path) -> list[CustomCommand]:
    commands_dir = Path(project_root).expanduser() / ".allCode" / "commands"
    if not commands_dir.is_dir():
        return []
    commands: list[CustomCommand] = []
    for path in sorted(commands_dir.glob("*.md")):
        stem = path.stem.strip().lower()
        if not _NAME_RE.match(stem):
            continue
        try:
            body = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if not body.strip():
            continue
        commands.append(CustomCommand(name=f"/{stem}", description=_description(body), template=body.strip()))
    return commands


def _description(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped[:80]
    return "Custom command"


def expand_command(template: str, args: str) -> str:
    args = args.strip()
    if "$ARGUMENTS" in template:
        return template.replace("$ARGUMENTS", args)
    if "{{args}}" in template:
        return template.replace("{{args}}", args)
    return f"{template}\n\n{args}".rstrip() if args else template
