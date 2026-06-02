"""Locate package/project roots inside a workspace."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from collections.abc import Iterable

PROJECT_MARKERS = (
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "settings.gradle.kts",
)

IGNORED_DIRS = {".git", ".venv", "node_modules", "__pycache__", "dist", "build", "target"}


@dataclass(frozen=True)
class LocatedProject:
    root: Path
    marker: str
    score: int = 0


class ProjectLocator:
    """Finds a validation cwd without hardcoding generated project names."""

    def __init__(self, workspace_root: str | Path) -> None:
        self.workspace_root = Path(workspace_root).resolve()

    def nearest_project_root(self, path: str | Path) -> LocatedProject | None:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.workspace_root / candidate
        try:
            candidate = candidate.resolve()
            candidate.relative_to(self.workspace_root)
        except (OSError, ValueError):
            return None
        directory = candidate if candidate.is_dir() else candidate.parent
        for current in (directory, *directory.parents):
            try:
                current.relative_to(self.workspace_root)
            except ValueError:
                break
            marker = self._marker_for(current)
            if marker is not None:
                return LocatedProject(root=current, marker=marker, score=100)
        return None

    def validation_root(
        self,
        *,
        preferred: str | Path | None = None,
        changed_files: Iterable[str] = (),
    ) -> Path:
        for path in [preferred, *changed_files]:
            if path is None:
                continue
            nearest = self.nearest_project_root(path)
            if nearest is not None:
                return nearest.root
        workspace_marker = self._marker_for(self.workspace_root)
        if workspace_marker is not None:
            return self.workspace_root
        projects = self.discover_projects(limit=4)
        if len(projects) == 1:
            return projects[0].root
        return self.workspace_root

    def discover_projects(self, *, limit: int = 20) -> list[LocatedProject]:
        found: list[LocatedProject] = []
        if not self.workspace_root.exists():
            return found
        for path in self.workspace_root.rglob("*"):
            if len(found) >= limit:
                break
            if not path.is_file() or path.name not in PROJECT_MARKERS:
                continue
            if any(part in IGNORED_DIRS for part in path.relative_to(self.workspace_root).parts):
                continue
            found.append(LocatedProject(root=path.parent, marker=path.name, score=50))
        return sorted(found, key=lambda item: (len(item.root.parts), item.root.as_posix()))

    def _marker_for(self, directory: Path) -> str | None:
        for marker in PROJECT_MARKERS:
            if (directory / marker).exists():
                return marker
        return None
