"""Routing helper for generation workflow handoff."""

from __future__ import annotations

import re
from pathlib import Path

from allCode.agent.artifact_detection import prompt_requests_tests
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
    if routing.workflow_hint != "multi_file_generation":
        return False
    if routing.target_hint and Path(routing.target_hint).suffix:
        return _is_new_file_with_tests(prompt, routing.target_hint, workspace_root=workspace_root)
    if workspace_root is None:
        return True
    if not _workspace_has_non_placeholder_source_files(Path(workspace_root)):
        return True
    return _has_explicit_new_project_intent(prompt) or infer_generation_target_root(prompt) is not None


def workflow_target_root_from_routing(prompt: str, routing: RoutingDecision) -> str | None:
    if routing.target_hint and not Path(routing.target_hint).suffix:
        return routing.target_hint
    return infer_generation_target_root(prompt)


def infer_generation_target_root(prompt: str) -> str | None:
    """Infer an explicit directory target for a new multi-file artifact.

    This intentionally uses only structural directory/path signals, not scenario
    names or benchmark prompts. A file path such as ``src/app.py`` is not a
    generation root; a directory-like mention such as ``mini_api/`` is.
    """

    compact = " ".join(prompt.strip().split())
    if not compact:
        return None
    for pattern in (
        r"[`'\"](?P<path>[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)/[`'\"]",
        r"\b(?:in|under|inside|at)\s+[`'\"]?(?P<path>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)/?[`'\"]?\b",
        r"[`'\"](?P<path>[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)[`'\"]?\s*(?:아래|하위|내부)",
    ):
        match = re.search(pattern, compact, flags=re.IGNORECASE)
        if not match:
            continue
        value = _safe_directory_root(match.group("path"))
        if value is not None:
            return value
    return None


def _has_explicit_new_project_intent(prompt: str) -> bool:
    lowered = " ".join(prompt.lower().split())
    return any(marker in lowered for marker in NEW_PROJECT_MARKERS)


def _is_new_file_with_tests(prompt: str, target_hint: str, *, workspace_root: str | Path | None) -> bool:
    if not target_hint or not Path(target_hint).suffix or not prompt_requests_tests(prompt):
        return False
    if workspace_root is None:
        return True
    candidate = Path(target_hint)
    if not candidate.is_absolute():
        candidate = Path(workspace_root) / candidate
    try:
        return not candidate.expanduser().resolve().exists()
    except OSError:
        return False


def _workspace_has_non_placeholder_source_files(root: Path) -> bool:
    if not root.exists():
        return False
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in {".git", ".venv", "node_modules", "__pycache__", "dist", "build"} for part in path.parts):
            continue
        if path.suffix.lower() in SOURCE_SUFFIXES:
            if _is_placeholder_source(path):
                continue
            return True
    return False


def _is_placeholder_source(path: Path) -> bool:
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    stripped = "\n".join(line.strip() for line in content.splitlines() if line.strip())
    if not stripped:
        return True
    lowered = stripped.lower()
    placeholder_markers = (
        "pass",
        "todo",
        "placeholder",
        "notimplementederror",
        "raise not implemented",
        "implementation pending",
        "구현 예정",
    )
    meaningful_lines = [line for line in stripped.splitlines() if not line.lstrip().startswith(("#", "//", "/*", "*"))]
    return len(content) <= 240 and any(marker in lowered for marker in placeholder_markers) and len(meaningful_lines) <= 6


def _safe_directory_root(value: str) -> str | None:
    normalized = value.strip().strip("/").replace("\\", "/")
    if not normalized or normalized.startswith("/") or ".." in normalized.split("/"):
        return None
    if Path(normalized).suffix:
        return None
    if any(part in {".", ".git", ".venv", "node_modules"} for part in normalized.split("/")):
        return None
    return normalized
