"""Artifact-obligation helpers for phase gating."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from allCode.agent.artifact_detection import (
    looks_like_test_artifact,
    prompt_requests_documents as _prompt_requests_documents,
    prompt_requests_tests as _prompt_requests_tests,
)
from allCode.core.path_patterns import extract_prompt_paths
from allCode.core.result import CompletionEvidence, RequestedArtifact


def ensure_requested_artifacts(
    prompt: str,
    evidence: CompletionEvidence,
    *,
    workspace_root: str,
    routing=None,
) -> None:
    """Populate prompt-derived artifact obligations without benchmark-specific rules."""

    if routing is not None and (
        getattr(routing, "read_only_requested", False)
        or getattr(routing, "kind", "") in {"answer", "inspect"}
    ):
        satisfy_requested_artifacts(evidence, workspace_root=workspace_root)
        return
    mutation_route = routing is not None and getattr(routing, "requires_mutation", False)
    if mutation_route:
        for path in extract_prompt_paths(prompt):
            kind = _artifact_kind_for_path(path, workspace_root=workspace_root)
            _add_requested_artifact(
                evidence,
                RequestedArtifact(
                    kind=kind,
                    target=path,
                    reason="explicit path mentioned in mutation prompt",
                ),
            )
    if mutation_route and _prompt_requests_tests(prompt):
        _add_requested_artifact(
            evidence,
            RequestedArtifact(
                kind="test",
                reason="prompt requests test artifacts",
            ),
        )
    if mutation_route and _prompt_requests_documents(prompt):
        _add_requested_artifact(
            evidence,
            RequestedArtifact(
                kind="document",
                reason="prompt requests documentation artifacts",
            ),
        )
    if mutation_route and routing is not None and getattr(routing, "requires_validation", False):
        _add_requested_artifact(
            evidence,
            RequestedArtifact(
                kind="validation",
                reason="route requires validation",
            ),
        )
    satisfy_requested_artifacts(evidence, workspace_root=workspace_root)


def seed_known_artifact_targets(
    prompt: str,
    evidence: CompletionEvidence,
    *,
    workspace_root: str,
    source_files: Sequence[str] = (),
    test_files: Sequence[str] = (),
) -> None:
    """Promote session-known artifacts into current-turn obligations."""

    if _prompt_requests_tests(prompt):
        for path in _existing_targets(test_files, workspace_root=workspace_root)[:3]:
            _add_requested_artifact(
                evidence,
                RequestedArtifact(
                    kind="test",
                    target=path,
                    reason="session test artifact should be updated for requested test work",
                ),
            )
    if source_files and not any(artifact.kind == "source" for artifact in evidence.requested_artifacts):
        for path in _existing_targets(source_files, workspace_root=workspace_root)[:3]:
            _add_requested_artifact(
                evidence,
                RequestedArtifact(
                    kind="source",
                    target=path,
                    reason="session source artifact provides project context",
                    satisfied=True,
                    evidence_paths=[path],
                ),
            )


def satisfy_requested_artifacts(evidence: CompletionEvidence, *, workspace_root: str) -> None:
    changed = [*evidence.created_files, *evidence.changed_files, *evidence.deleted_files]
    for artifact in evidence.requested_artifacts:
        evidence_paths = list(artifact.evidence_paths)
        satisfied = artifact.satisfied
        if artifact.kind == "validation":
            satisfied = evidence.validation_passed is True
            if satisfied:
                evidence_paths = list(evidence.validation_commands)
        elif artifact.target:
            matches = _matching_artifact_paths(changed, artifact, workspace_root=workspace_root)
            if matches:
                satisfied = True
                evidence_paths = _merge_unique(evidence_paths, matches)
        elif artifact.kind == "test":
            matches = [path for path in changed if looks_like_test_artifact(path, workspace_root=workspace_root)]
            if matches:
                satisfied = True
                evidence_paths = _merge_unique(evidence_paths, matches)
        elif artifact.kind == "document":
            matches = [path for path in changed if _artifact_kind_for_path(path, workspace_root=workspace_root) == "document"]
            if matches:
                satisfied = True
                evidence_paths = _merge_unique(evidence_paths, matches)
        elif artifact.kind == "source":
            matches = [
                path
                for path in changed
                if _artifact_kind_for_path(path, workspace_root=workspace_root) == "source"
                and not looks_like_test_artifact(path, workspace_root=workspace_root)
            ]
            if matches:
                satisfied = True
                evidence_paths = _merge_unique(evidence_paths, matches)
        artifact.satisfied = satisfied
        artifact.evidence_paths = evidence_paths


def unsatisfied_artifact_kinds(evidence: CompletionEvidence, *kinds: str) -> list[str]:
    seen: list[str] = []
    for artifact in evidence.unsatisfied_artifacts(*kinds):
        if artifact.kind not in seen:
            seen.append(artifact.kind)
    return seen


def unsatisfied_artifact_labels(evidence: CompletionEvidence, *kinds: str) -> list[str]:
    labels: list[str] = []
    for artifact in evidence.unsatisfied_artifacts(*kinds):
        label = artifact.kind if not artifact.target else f"{artifact.kind}:{artifact.target}"
        if label not in labels:
            labels.append(label)
    return labels


def mutation_artifact_required(
    prompt: str,
    evidence: CompletionEvidence,
    *,
    workspace_root: str,
    routing=None,
) -> bool:
    if routing is not None and (
        getattr(routing, "read_only_requested", False)
        or getattr(routing, "kind", "") in {"answer", "inspect"}
    ):
        return False
    ensure_requested_artifacts(prompt, evidence, workspace_root=workspace_root, routing=routing)
    return evidence.has_unsatisfied_artifacts("source", "document", "test")


def test_artifact_required(
    prompt: str,
    evidence: CompletionEvidence,
    *,
    workspace_root: str,
    routing=None,
) -> bool:
    if routing is not None and (
        getattr(routing, "read_only_requested", False)
        or getattr(routing, "kind", "") in {"answer", "inspect"}
    ):
        return False
    ensure_requested_artifacts(prompt, evidence, workspace_root=workspace_root, routing=routing)
    if evidence.has_unsatisfied_artifacts("test"):
        return True
    if not _prompt_requests_tests(prompt):
        return False
    changed = [*evidence.changed_files, *evidence.created_files]
    return not any(looks_like_test_artifact(path, workspace_root=workspace_root) for path in changed)


def target_matches_any(path: str, targets: Sequence[str], *, workspace_root: str) -> bool:
    """Return whether a tool target satisfies one of the required artifact paths."""

    if not targets:
        return True
    return any(_same_artifact_target(path, target, workspace_root=workspace_root) for target in targets)


def _add_requested_artifact(evidence: CompletionEvidence, artifact: RequestedArtifact) -> None:
    key = (artifact.kind, artifact.target)
    for existing in evidence.requested_artifacts:
        if (existing.kind, existing.target) == key:
            if artifact.reason and artifact.reason not in existing.reason:
                existing.reason = artifact.reason if not existing.reason else existing.reason
            return
    evidence.requested_artifacts.append(artifact)


def _artifact_kind_for_path(path: str, *, workspace_root: str) -> str:
    suffix = Path(path).suffix.lower()
    if looks_like_test_artifact(path, workspace_root=workspace_root):
        return "test"
    if suffix in {".md", ".txt", ".rst"}:
        return "document"
    return "source"


def _same_artifact_target(path: str, target: str, *, workspace_root: str) -> bool:
    normalized_path = _normalize_target(path, workspace_root=workspace_root)
    normalized_target = _normalize_target(target, workspace_root=workspace_root)
    if normalized_path == normalized_target:
        return True
    if _looks_directory_artifact_target(normalized_target) and normalized_path.startswith(f"{normalized_target}/"):
        return True
    if normalized_path.endswith(f"/{normalized_target}"):
        return True
    if "/" not in normalized_target and Path(normalized_path).name == normalized_target:
        return True
    return False


def _matching_artifact_paths(changed: Sequence[str], artifact: RequestedArtifact, *, workspace_root: str) -> list[str]:
    matches = [path for path in changed if _same_artifact_target(path, artifact.target, workspace_root=workspace_root)]
    if not matches:
        return []
    normalized_target = _normalize_target(artifact.target, workspace_root=workspace_root)
    if not _looks_directory_artifact_target(normalized_target):
        return matches
    if artifact.kind == "source":
        return [
            path
            for path in matches
            if _artifact_kind_for_path(path, workspace_root=workspace_root) == "source"
            and not looks_like_test_artifact(path, workspace_root=workspace_root)
        ]
    if artifact.kind == "test":
        return [path for path in matches if looks_like_test_artifact(path, workspace_root=workspace_root)]
    if artifact.kind == "document":
        return [path for path in matches if _artifact_kind_for_path(path, workspace_root=workspace_root) == "document"]
    return matches


def _looks_directory_artifact_target(target: str) -> bool:
    normalized = target.strip().strip("/").replace("\\", "/")
    if not normalized or normalized in {".", ".."}:
        return False
    if Path(normalized).suffix:
        return False
    return "/" in normalized or normalized.split("/", 1)[0] in {"output", "dist", "build", "apps", "packages"}


def _normalize_target(path: str, *, workspace_root: str) -> str:
    candidate = Path(path)
    try:
        if candidate.is_absolute():
            return candidate.expanduser().resolve().relative_to(Path(workspace_root).expanduser().resolve()).as_posix()
    except (OSError, ValueError):
        return candidate.as_posix()
    return candidate.as_posix()


def _target_exists(path: str, *, workspace_root: str) -> bool:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = Path(workspace_root) / candidate
    try:
        return candidate.expanduser().resolve().exists()
    except OSError:
        return False


def _existing_targets(paths: Sequence[str], *, workspace_root: str) -> list[str]:
    existing: list[str] = []
    for path in paths:
        if not path:
            continue
        if _target_exists(path, workspace_root=workspace_root) and path not in existing:
            existing.append(_normalize_target(path, workspace_root=workspace_root))
    return existing


def _merge_unique(left: list[str], right: list[str]) -> list[str]:
    merged = list(left)
    for item in right:
        if item not in merged:
            merged.append(item)
    return merged
