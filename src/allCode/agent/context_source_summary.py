"""Source-aware context snippets for active and recent files."""

from __future__ import annotations

from pathlib import Path

from allCode.memory.redaction import redact_text
from allCode.workspace.source_intelligence import SourceIntelligenceService


def source_skeleton_summary(
    path: Path,
    *,
    workspace_root: Path,
    reason: str,
) -> str:
    relative = _relative(path, workspace_root)
    size = _size(path)
    line_count = _line_count(path)
    analysis = SourceIntelligenceService().analyze_file(path, workspace_root=workspace_root)
    lines = [
        f"[source skeleton: {path.name}]",
        f"- path: {relative}",
        f"- reason: {reason}",
        f"- size_bytes: {size}",
        f"- line_count: {line_count}",
        f"- backend: {analysis.backend}",
    ]
    definitions = analysis.compact_definitions()[:18]
    imports = analysis.compact_imports()[:12]
    if definitions:
        lines.append("- definitions:")
        lines.extend(f"  - {item}" for item in definitions)
    if imports:
        lines.append("- imports:")
        lines.extend(f"  - {item}" for item in imports)
    if analysis.diagnostics:
        lines.append("- diagnostics:")
        for item in analysis.diagnostics[:4]:
            message = str(item.get("message") or item.get("kind") or item)
            lines.append(f"  - {message}")
    lines.append("- recommended_action: use source_probe or read_file with start_line/end_line for implementation details")
    return redact_text("\n".join(lines))


def _relative(path: Path, root: Path) -> str:
    try:
        return path.expanduser().resolve().relative_to(root.expanduser().resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _line_count(path: Path) -> int:
    try:
        with path.open("rb") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return 0
