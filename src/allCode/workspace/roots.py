"""Workspace root management."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from allCode.core.models import CoreModel, WorkspaceRef


class WorkspaceRoot(CoreModel):
    path: str
    writable: bool = True
    label: str | None = None

    @property
    def resolved(self) -> Path:
        return Path(self.path).expanduser().resolve()

    def to_ref(self) -> WorkspaceRef:
        return WorkspaceRef(root=str(self.resolved), writable=self.writable, label=self.label)


class WorkspaceRoots(CoreModel):
    roots: list[WorkspaceRoot] = Field(default_factory=list)

    @classmethod
    def from_root(cls, root: str | Path, *, writable: bool = True, label: str | None = None) -> "WorkspaceRoots":
        manager = cls()
        manager.add(root, writable=writable, label=label)
        return manager

    def add(self, root: str | Path, *, writable: bool = True, label: str | None = None) -> WorkspaceRoot:
        resolved = Path(root).expanduser().resolve()
        existing = self.find(resolved)
        if existing is not None:
            return existing
        workspace_root = WorkspaceRoot(path=str(resolved), writable=writable, label=label)
        self.roots.append(workspace_root)
        return workspace_root

    def find(self, path: str | Path) -> WorkspaceRoot | None:
        resolved = Path(path).expanduser().resolve()
        for root in self.roots:
            root_path = root.resolved
            if resolved == root_path or root_path in resolved.parents:
                return root
        return None

    def writable_roots(self) -> list[WorkspaceRoot]:
        return [root for root in self.roots if root.writable]

    def refs(self) -> list[WorkspaceRef]:
        return [root.to_ref() for root in self.roots]
