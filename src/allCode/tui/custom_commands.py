"""User-defined slash commands loaded from ``.allCode/commands/*.md``.

Each markdown file becomes a ``/<stem>`` command whose body is a prompt template.
``$ARGUMENTS`` (or ``{{args}}``) in the template is replaced with the text typed
after the command; if the template has no placeholder, the arguments are appended.
Templates may also inject context at expansion time:
- ``@{path}``       — insert the contents of a workspace file.
- ``!{command}``    — run a shell command and insert its stdout.
Invoking the command submits the expanded prompt as a normal turn.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_SHELL_RE = re.compile(r"!\{([^}]*)\}")
_FILE_RE = re.compile(r"@\{([^}]*)\}")
_INJECT_MAX_CHARS = 8000
_SHELL_TIMEOUT = 15


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


def _truncate(text: str) -> str:
    text = text.rstrip()
    if len(text) > _INJECT_MAX_CHARS:
        return text[:_INJECT_MAX_CHARS].rstrip() + "\n... (truncated) ..."
    return text


def _inject_files(template: str, cwd: Path) -> str:
    def repl(match: re.Match) -> str:
        rel = match.group(1).strip()
        if not rel:
            return match.group(0)
        path = Path(rel).expanduser()
        if not path.is_absolute():
            path = cwd / path
        try:
            return _truncate(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            return f"[파일을 읽을 수 없습니다: {rel}]"

    return _FILE_RE.sub(repl, template)


def _inject_shell(template: str, cwd: Path) -> str:
    def repl(match: re.Match) -> str:
        cmd = match.group(1).strip()
        if not cmd:
            return match.group(0)
        try:
            proc = subprocess.run(
                cmd, shell=True, cwd=str(cwd), capture_output=True, text=True, timeout=_SHELL_TIMEOUT
            )
            out = proc.stdout or proc.stderr
            return _truncate(out)
        except (OSError, subprocess.SubprocessError) as exc:
            return f"[명령 실행 실패: {cmd} — {exc}]"

    return _SHELL_RE.sub(repl, template)


def expand_command(template: str, args: str, *, cwd: Path | str | None = None) -> str:
    args = args.strip()
    if "$ARGUMENTS" in template:
        template = template.replace("$ARGUMENTS", args)
    elif "{{args}}" in template:
        template = template.replace("{{args}}", args)
    else:
        template = f"{template}\n\n{args}".rstrip() if args else template
    # File/shell injection runs after argument substitution so args can name a path.
    if cwd is not None and ("@{" in template or "!{" in template):
        base = Path(cwd).expanduser()
        template = _inject_files(template, base)
        template = _inject_shell(template, base)
    return template
