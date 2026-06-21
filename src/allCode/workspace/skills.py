"""User-defined skills loaded from ``.allCode/skills/``.

A skill is a reusable capability package the model can pull in on demand
(Claude-Code-style progressive disclosure): its name + description are always
visible to the model (via the ``skill`` tool's description), and the full
instruction body is loaded only when the model calls ``skill(<name>)``.

Two layouts are supported:
    .allCode/skills/<name>/SKILL.md   (directory form; may ship companion files)
    .allCode/skills/<name>.md         (single-file form)

Each file may carry YAML-ish frontmatter with a ``description``; the body is the
instructions returned when the skill is loaded.

Only the user's own custom skills are listed. A skill that ships bundled with a
project as a template/example can opt out of the listing with frontmatter
``template: true`` (or ``hidden: true``); documentation files such as
``README.md`` dropped into the skills directory are ignored as well. This keeps
``/skills`` and the model's ``skill`` tool limited to genuine custom skills.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)

# Documentation / index files that may sit alongside skills but are not skills
# (e.g. a README shipped with a bundled example set).
_RESERVED_STEMS = {"readme", "index", "_index"}


def _is_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"true", "1", "yes", "on"}


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    description: str
    instructions: str
    path: str


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


def _first_line(body: str) -> str:
    for line in body.splitlines():
        if line.strip():
            return line.strip()[:100]
    return "Custom skill"


def _make(name: str, path: Path) -> SkillDefinition | None:
    name = name.strip().lower()
    if not _NAME_RE.match(name) or name in _RESERVED_STEMS:
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.strip():
        return None
    meta, body = _parse_frontmatter(text)
    # Bundled template/example skills opt out of the custom-skill listing.
    if _is_truthy(meta.get("template")) or _is_truthy(meta.get("hidden")):
        return None
    return SkillDefinition(
        name=name,
        description=meta.get("description", "") or _first_line(body),
        instructions=body,
        path=str(path),
    )


def load_skill_definitions(project_root: str | Path) -> list[SkillDefinition]:
    skills_dir = Path(project_root).expanduser() / ".allCode" / "skills"
    if not skills_dir.is_dir():
        return []
    definitions: list[SkillDefinition] = []
    seen: set[str] = set()
    # Directory form first (skills/<name>/SKILL.md), then single-file (skills/<name>.md).
    for sub in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        skill_md = sub / "SKILL.md"
        if skill_md.is_file():
            definition = _make(sub.name, skill_md)
            if definition is not None and definition.name not in seen:
                seen.add(definition.name)
                definitions.append(definition)
    for path in sorted(skills_dir.glob("*.md")):
        definition = _make(path.stem, path)
        if definition is not None and definition.name not in seen:
            seen.add(definition.name)
            definitions.append(definition)
    return definitions
