"""Safe path normalization and prompt target resolution."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from allCode.core.errors import PathPolicyDeniedError
from allCode.core.models import CoreModel
from allCode.core.path_patterns import extract_prompt_path, is_followup_reference
from allCode.workspace.roots import WorkspaceRoot, WorkspaceRoots


class PathResolution(CoreModel):
    query: str
    resolved_path: str | None = None
    root: str | None = None
    candidates: list[str] = Field(default_factory=list)
    ambiguous: bool = False
    denied_reason: str | None = None


def safe_resolve_under_root(root: str | Path, path: str | Path) -> Path:
    root_path = Path(root).expanduser().resolve()
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = root_path / candidate
    resolved = candidate.resolve()
    if resolved != root_path and root_path not in resolved.parents:
        raise PathPolicyDeniedError(f"path escapes workspace root: {path}")
    return resolved


class PathResolver:
    def __init__(self, roots: WorkspaceRoots) -> None:
        self.roots = roots

    def resolve_for_read(
        self,
        query: str,
        *,
        recent_paths: list[str] | None = None,
        workspace_candidates: list[str] | None = None,
    ) -> PathResolution:
        return self._resolve(query, require_writable=False, recent_paths=recent_paths, workspace_candidates=workspace_candidates)

    def resolve_for_write(self, query: str) -> PathResolution:
        return self._resolve(query, require_writable=True)

    def extract_prompt_path(self, prompt: str) -> str | None:
        return extract_prompt_path(prompt)

    def _resolve(
        self,
        query: str,
        *,
        require_writable: bool,
        recent_paths: list[str] | None = None,
        workspace_candidates: list[str] | None = None,
    ) -> PathResolution:
        explicit_target = self.extract_prompt_path(query)
        recent = recent_paths or []
        target = explicit_target or query
        if explicit_target is None and is_followup_reference(query) and recent:
            target = recent[0]
        recent_match = self._match_recent(target, recent)
        if recent_match is not None and not Path(target).is_absolute():
            target = recent_match
        roots = self.roots.writable_roots() if require_writable else self.roots.roots
        if not roots:
            return PathResolution(query=query, denied_reason="no workspace roots configured")
        direct = self._direct_candidates(target, roots)
        existing = [path for path in direct if path.exists()]
        if len(existing) == 1:
            return self._resolved(query, existing[0])
        if len(existing) > 1:
            return PathResolution(query=query, candidates=[str(path) for path in existing], ambiguous=True)
        named = self._candidate_name_matches(target, workspace_candidates or [], roots)
        if len(named) == 1:
            return self._resolved(query, named[0])
        if len(named) > 1:
            return PathResolution(query=query, candidates=[str(path) for path in named], ambiguous=True)
        if direct:
            return self._resolved(query, direct[0])
        return PathResolution(query=query, denied_reason=f"path is outside workspace roots: {target}")

    def _direct_candidates(self, target: str, roots: list[WorkspaceRoot]) -> list[Path]:
        candidates: list[Path] = []
        for root in roots:
            try:
                candidates.append(safe_resolve_under_root(root.resolved, target))
            except PathPolicyDeniedError:
                if Path(target).is_absolute():
                    continue
        return candidates

    def _candidate_name_matches(self, target: str, candidates: list[str], roots: list[WorkspaceRoot]) -> list[Path]:
        target_name = Path(target).name
        matches: list[Path] = []
        for candidate in candidates:
            if Path(candidate).name != target_name and candidate != target:
                continue
            for root in roots:
                try:
                    resolved = safe_resolve_under_root(root.resolved, candidate)
                except PathPolicyDeniedError:
                    continue
                if resolved.exists():
                    matches.append(resolved)
        return sorted(set(matches))

    def _match_recent(self, target: str, recent_paths: list[str]) -> str | None:
        target_name = Path(target).name
        for recent in recent_paths:
            if recent == target or Path(recent).name == target_name:
                return recent
        return None

    def _resolved(self, query: str, path: Path) -> PathResolution:
        root = self.roots.find(path)
        return PathResolution(
            query=query,
            resolved_path=str(path),
            root=str(root.resolved) if root is not None else None,
        )
