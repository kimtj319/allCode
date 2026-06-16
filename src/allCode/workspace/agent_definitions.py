"""User-defined sub-agent definitions loaded from ``.allCode/agents/*.md``.

Each markdown file defines a specialized sub-agent (code reviewer, debugger,
…) with optional YAML frontmatter and an instruction body — the Claude
Code/Codex/Gemini ``/agents`` affordance:

    ---
    description: Reviews a diff for bugs and security issues
    model: wisenut/wise-lloa-max-v1.2.1
    tools: read_file, search_files, source_overview
    ---
    You are a meticulous reviewer. Focus on correctness and security...

The body is the sub-agent's system preamble; ``tools`` narrows its toolset.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    description: str
    instructions: str
    model: str | None = None
    tools: tuple[str, ...] = field(default_factory=tuple)


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text.strip()
    raw, body = match.group(1), match.group(2)
    meta: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip().lower()] = value.strip()
    return meta, body.strip()


def load_agent_definitions(project_root: str | Path) -> list[AgentDefinition]:
    agents_dir = Path(project_root).expanduser() / ".allCode" / "agents"
    if not agents_dir.is_dir():
        return []
    definitions: list[AgentDefinition] = []
    for path in sorted(agents_dir.glob("*.md")):
        stem = path.stem.strip().lower()
        if not _NAME_RE.match(stem):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if not text.strip():
            continue
        meta, body = _parse_frontmatter(text)
        tools = tuple(
            t.strip() for t in re.split(r"[,\s]+", meta.get("tools", "")) if t.strip()
        )
        definitions.append(
            AgentDefinition(
                name=stem,
                description=meta.get("description", "") or _first_line(body),
                instructions=body,
                model=meta.get("model") or None,
                tools=tools,
            )
        )
    return definitions


def _first_line(body: str) -> str:
    for line in body.splitlines():
        if line.strip():
            return line.strip()[:80]
    return "Custom sub-agent"
