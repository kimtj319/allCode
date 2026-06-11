"""File-backed context section helpers for ``ContextBuilder``."""

from __future__ import annotations

from pathlib import Path

from allCode.agent.context_source_summary import source_skeleton_summary
from allCode.core.models import TurnInput
from allCode.memory.redaction import redact_text
from allCode.memory.schema import ContextSection, estimate_tokens
from allCode.workspace.indexer import WorkspaceIndex
from allCode.workspace.path_resolver import PathResolver


def recent_file_sections(
    turn_input: TurnInput,
    *,
    recent_paths: list[str],
) -> list[ContextSection]:
    workspace_root = Path(turn_input.workspace.root).expanduser().resolve()
    sections: list[ContextSection] = []
    total_bytes = 0
    seen: set[str] = set()
    for raw_path in recent_paths:
        path = resolve_recent_file(raw_path, workspace_root=workspace_root)
        if path is None:
            continue
        try:
            relative = path.relative_to(workspace_root).as_posix()
        except ValueError:
            continue
        if relative in seen:
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > 16_000 or total_bytes + size > 36_000:
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\0" in raw[:1024]:
            continue
        content = redact_text(raw.decode("utf-8", errors="replace"))
        section_content = f"path: {relative}\n```text\n{content}\n```"
        sections.append(
            ContextSection(
                name=f"recent_file:{relative}",
                priority=118,
                token_estimate=estimate_tokens(section_content),
                content=section_content,
                source=relative,
                section_type="recent_file",
            )
        )
        total_bytes += size
        seen.add(relative)
        if len(sections) >= 4:
            break
    return sections


def workspace_sections(
    turn_input: TurnInput,
    *,
    path_resolver: PathResolver,
    workspace_index: WorkspaceIndex,
    recent_paths: list[str],
    max_active_file_bytes: int,
) -> list[ContextSection]:
    resolution = path_resolver.resolve_for_read(
        turn_input.user_prompt,
        recent_paths=recent_paths,
        workspace_candidates=workspace_index.paths(),
    )
    if resolution.resolved_path is None:
        return []
    path = Path(resolution.resolved_path)
    if not path.exists() or not path.is_file():
        return []
    try:
        file_size = path.stat().st_size
        if file_size > 20_000:
            workspace_root = Path(turn_input.workspace.root).expanduser().resolve()
            section_content = source_skeleton_summary(
                path,
                workspace_root=workspace_root,
                reason="large active file suppressed",
            )
            return [
                ContextSection(
                    name=f"active_file:{path.name}",
                    priority=100,
                    token_estimate=estimate_tokens(section_content),
                    content=section_content,
                    source=str(path),
                    section_type="active_file_metadata",
                )
            ]
        with path.open("rb") as handle:
            raw = handle.read(max_active_file_bytes + 1)
    except OSError:
        return []
    if b"\0" in raw[:1024]:
        return []
    truncated = file_size > max_active_file_bytes or len(raw) > max_active_file_bytes
    if truncated:
        workspace_root = Path(turn_input.workspace.root).expanduser().resolve()
        section_content = source_skeleton_summary(
            path,
            workspace_root=workspace_root,
            reason="active file truncated",
        )
        return [
            ContextSection(
                name=f"active_file:{path.name}",
                priority=100,
                token_estimate=estimate_tokens(section_content),
                content=section_content,
                source=str(path),
                section_type="active_file_skeleton",
            )
        ]
    content = raw[:max_active_file_bytes].decode("utf-8", errors="replace")
    return [
        ContextSection(
            name=f"active_file:{path.name}",
            priority=100,
            token_estimate=estimate_tokens(content),
            content=content,
            source=str(path),
            section_type="active_file",
        )
    ]


def resolve_recent_file(raw_path: str, *, workspace_root: Path) -> Path | None:
    value = str(raw_path or "").strip()
    if not value:
        return None
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = workspace_root / candidate
    try:
        resolved = candidate.expanduser().resolve()
        resolved.relative_to(workspace_root)
    except (OSError, ValueError):
        return None
    if not resolved.exists() or not resolved.is_file():
        return None
    if any(part in {".git", ".venv", "node_modules", "__pycache__", "dist", "build"} for part in resolved.parts):
        return None
    return resolved

