"""Routing helper for generation workflow handoff."""

from __future__ import annotations

from pathlib import Path

from allCode.agent.router import RoutingDecision


SOURCE_SUFFIXES = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".java",
    ".go",
    ".rs",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".kt",
    ".rb",
    ".php",
}

NEW_PROJECT_MARKERS = (
    "new project",
    "create a project",
    "generate a project",
    "scaffold",
    "bootstrap",
    "project skeleton",
    "프로젝트 뼈대",
    "새 프로젝트",
    "프로젝트 생성",
    "프로젝트를 만들어",
    "프로젝트를 만들",
)


def should_use_generation_workflow(
    prompt: str,
    routing: RoutingDecision,
    *,
    workspace_root: str | Path | None = None,
) -> bool:
    if routing.kind != "modify" or routing.read_only_requested:
        return False
    if routing.target_hint and Path(routing.target_hint).suffix:
        return False
    if routing.workflow_hint != "multi_file_generation":
        return False
    if workspace_root is None:
        return True
    if not _workspace_has_source_files(Path(workspace_root)):
        return True
    return _has_explicit_new_project_intent(prompt)


def _has_explicit_new_project_intent(prompt: str) -> bool:
    lowered = " ".join(prompt.lower().split())
    return any(marker in lowered for marker in NEW_PROJECT_MARKERS)


def _workspace_has_source_files(root: Path) -> bool:
    if not root.exists():
        return False
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in {".git", ".venv", "node_modules", "__pycache__", "dist", "build"} for part in path.parts):
            continue
        if path.suffix.lower() in SOURCE_SUFFIXES:
            return True
    return False
