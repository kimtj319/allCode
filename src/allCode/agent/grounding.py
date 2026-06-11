"""Grounding requirements for search-first inspection answers."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from allCode.agent.source_inspection_budget import required_representative_probe_count
from allCode.core.models import ToolCall
from allCode.core.result import CompletionEvidence

GROUNDING_MARKERS = (
    "확인한 파일",
    "확인한",
    "문서에서",
    "근거",
    "없으면",
    "파일명",
    "actual file",
    "checked file",
    "cite checked",
    "grounded",
    "evidence",
    "if none",
)


def grounding_required(prompt: str, routing) -> bool:
    if getattr(routing, "requires_mutation", False):
        return False
    if getattr(routing, "requires_external_knowledge", False):
        return False
    if getattr(routing, "kind", "") not in {"inspect", "operate"}:
        return False
    lowered = prompt.lower()
    return any(marker in prompt or marker in lowered for marker in GROUNDING_MARKERS)


def needs_candidate_read(evidence: CompletionEvidence) -> bool:
    if not evidence.grounding_required:
        return False
    candidates = [_normalize(path) for path in evidence.search_candidate_paths]
    inspected = {_normalize(path) for path in evidence.inspected_paths}
    return bool(candidates) and not any(path in inspected for path in candidates)


def next_candidate_read_call(evidence: CompletionEvidence, *, workspace_root: str) -> ToolCall | None:
    inspected = {_normalize(path) for path in evidence.inspected_paths}
    representative = {_normalize(path) for path in evidence.source_representative_candidates}
    for candidate in evidence.search_candidate_paths:
        normalized = _normalize(candidate)
        if normalized in inspected:
            continue
        file_path = _relative_candidate(candidate, workspace_root=workspace_root)
        if file_path:
            if evidence.source_overview_paths and normalized in representative:
                return ToolCall(
                    id=f"grounding-{uuid4().hex}",
                    name="source_probe",
                    arguments={"path": file_path, "max_ranges": 4, "context_lines": 2, "include_imports": True},
                )
            return ToolCall(
                id=f"grounding-{uuid4().hex}",
                name="read_file",
                arguments={"file_path": file_path, "max_bytes": 12_000},
            )
    return None


def next_representative_source_probe_call(
    evidence: CompletionEvidence,
    *,
    workspace_root: str,
    remaining_budget: int | None = None,
) -> ToolCall | None:
    """Return the next unread source-overview representative probe.

    This is a deterministic safety net for read-only source analysis. The
    model still chooses normal tools first, but broad source overviews should
    not reach final synthesis with only package-level metadata when bounded
    representative candidates are already available.
    """

    if remaining_budget is not None and remaining_budget <= 0:
        return None
    if not evidence.source_overview_paths:
        return None
    candidates = [_normalize(path) for path in evidence.source_representative_candidates if _normalize(path)]
    if not candidates:
        return None
    observed = {_normalize(path) for path in [*evidence.inspected_paths, *evidence.representative_read_paths]}
    required = required_representative_probe_count(evidence, candidate_count=len(candidates))
    observed_count = sum(1 for candidate in candidates if candidate in observed)
    if required <= 0 or observed_count >= required:
        return None
    for candidate in _ranked_representative_candidates(evidence):
        normalized = _normalize(candidate)
        if not normalized or normalized in observed:
            continue
        file_path = _relative_candidate(candidate, workspace_root=workspace_root)
        if not file_path:
            continue
        return ToolCall(
            id=f"grounding-{uuid4().hex}",
            name="source_probe",
            arguments={"path": file_path, "max_ranges": 5, "context_lines": 2, "include_imports": True},
        )
    return None


def _ranked_representative_candidates(evidence: CompletionEvidence) -> list[str]:
    return list(dict.fromkeys(path for path in evidence.source_representative_candidates if str(path).strip()))


def _relative_candidate(path: str, *, workspace_root: str) -> str:
    if path.startswith("/workspace/"):
        return path[len("/workspace/") :]
    candidate = Path(path)
    if candidate.is_absolute():
        try:
            return candidate.resolve().relative_to(Path(workspace_root).resolve()).as_posix()
        except (OSError, ValueError):
            return ""
    return candidate.as_posix()


def _normalize(path: str) -> str:
    if path.startswith("/workspace/"):
        path = path[len("/workspace/") :]
    try:
        return Path(path).as_posix().lower()
    except TypeError:
        return str(path).lower()
