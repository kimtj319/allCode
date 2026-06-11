"""Safe path normalization and prompt target resolution."""

from __future__ import annotations

import re
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
    raw_path = str(path)
    if raw_path == "/workspace":
        candidate = root_path
    elif raw_path.startswith("/workspace/"):
        candidate = root_path / raw_path[len("/workspace/") :]
    else:
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
        roots = self.roots.writable_roots() if require_writable else self.roots.roots
        if not roots:
            return PathResolution(query=query, denied_reason="no workspace roots configured")
        if explicit_target is None and is_followup_reference(query) and recent:
            semantic_matches = self._semantic_recent_matches(query, recent)
            if len(semantic_matches) == 1:
                target = semantic_matches[0]
            elif len(semantic_matches) > 1:
                return self._ambiguous_recent(query, semantic_matches, roots)
            else:
                target = recent[0]
        recent_matches = self._recent_matches(target, recent)
        if len(recent_matches) == 1 and not Path(target).is_absolute():
            target = recent_matches[0]
        elif len(recent_matches) > 1 and not Path(target).is_absolute():
            return self._ambiguous_recent(query, recent_matches, roots)
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

    def _recent_matches(self, target: str, recent_paths: list[str]) -> list[str]:
        exact = [recent for recent in recent_paths if recent == target]
        if exact:
            return exact
        if not _basename_only(target):
            return []
        target_name = Path(target).name
        return [recent for recent in recent_paths if Path(recent).name == target_name]

    def _semantic_recent_matches(self, query: str, recent_paths: list[str]) -> list[str]:
        query_terms = _semantic_terms(query)
        if not query_terms:
            return []
        ranked: list[tuple[int, int, str]] = []
        for index, path in enumerate(recent_paths):
            path_terms = _path_terms(path)
            score = 0
            for term in query_terms:
                if term in path_terms:
                    score += 4
                elif any(term in path_term or path_term in term for path_term in path_terms if len(path_term) >= 3):
                    score += 2
            if score:
                ranked.append((score, -index, path))
        if not ranked:
            return []
        ranked.sort(reverse=True)
        top_score = ranked[0][0]
        return [path for score, _index, path in ranked if score == top_score]

    def _ambiguous_recent(self, query: str, matches: list[str], roots: list[WorkspaceRoot]) -> PathResolution:
        candidates = self._resolve_recent_candidates(matches, roots)
        return PathResolution(
            query=query,
            candidates=[str(path) for path in candidates] or matches,
            ambiguous=True,
        )

    def _resolve_recent_candidates(self, matches: list[str], roots: list[WorkspaceRoot]) -> list[Path]:
        candidates: list[Path] = []
        for match in matches:
            for root in roots:
                try:
                    resolved = safe_resolve_under_root(root.resolved, match)
                except PathPolicyDeniedError:
                    continue
                if resolved.exists():
                    candidates.append(resolved)
        return sorted(set(candidates))

    def _resolved(self, query: str, path: Path) -> PathResolution:
        root = self.roots.find(path)
        return PathResolution(
            query=query,
            resolved_path=str(path),
            root=str(root.resolved) if root is not None else None,
        )


ALIASES: dict[str, tuple[str, ...]] = {
    "config": ("config", "setting", "settings", "configuration", "설정", "환경"),
    "service": ("service", "services", "서비스"),
    "test": ("test", "tests", "spec", "테스트", "검증"),
    "util": ("util", "utils", "utility", "도구", "유틸"),
    "text": ("text", "string", "문자열", "텍스트"),
}


def _semantic_terms(text: str) -> set[str]:
    lowered = text.lower()
    tokens = {token for token in re.split(r"[^0-9a-zA-Z가-힣_]+", lowered) if len(token) >= 2}
    expanded = set(tokens)
    for canonical, aliases in ALIASES.items():
        if any(alias in lowered for alias in aliases):
            expanded.add(canonical)
            expanded.update(alias for alias in aliases if re.fullmatch(r"[0-9a-zA-Z_]+", alias))
    return expanded


def _path_terms(path: str) -> set[str]:
    parts: set[str] = set()
    for part in Path(path).parts:
        lowered = part.lower()
        parts.add(lowered)
        parts.add(Path(lowered).stem)
        parts.update(token for token in re.split(r"[^0-9a-zA-Z_]+", lowered) if len(token) >= 2)
    expanded = set(parts)
    for canonical, aliases in ALIASES.items():
        if any(alias in parts for alias in aliases):
            expanded.add(canonical)
            expanded.update(alias for alias in aliases if re.fullmatch(r"[0-9a-zA-Z_]+", alias))
    return expanded


def _basename_only(path: str) -> bool:
    cleaned = path.replace("\\", "/")
    return "/" not in cleaned
