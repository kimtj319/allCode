"""Source-analysis staging for read-only inspect turns."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Literal

from pydantic import Field

from allCode.core.models import CoreModel
from allCode.core.result import CompletionEvidence

InspectStageName = Literal["none", "source_discovery", "targeted_read", "finalize"]

DISCOVERY_TOOLS = {"source_overview", "list_tree", "glob_files"}
TARGETED_READ_TOOLS = {"source_probe", "read_file", "search_files", "source_overview", "list_tree", "glob_files"}
REPRESENTATIVE_PROBE_TOOLS = {"source_probe"}


class InspectToolStage(CoreModel):
    stage: InspectStageName = "none"
    allowed_tool_names: set[str] = Field(default_factory=set)
    reason: str = ""
    target_paths: list[str] = Field(default_factory=list)
    evidence_complete: bool = False

    @property
    def active(self) -> bool:
        return self.stage != "none"


def decide_inspect_stage(
    *,
    prompt: str,
    routing,
    evidence: CompletionEvidence,
    round_index: int,
    inspect_round_budget: int,
    final_answer_requested: bool,
) -> InspectToolStage:
    if getattr(routing, "kind", "") != "inspect":
        return InspectToolStage()
    if getattr(routing, "requires_mutation", False):
        return InspectToolStage()
    if not getattr(routing, "read_only_requested", False) and not _source_inventory_request(prompt):
        return InspectToolStage()

    explicit_targets = _explicit_target_paths(prompt)
    target_hint = str(getattr(routing, "target_hint", "") or "").strip()
    if target_hint:
        explicit_targets.append(target_hint)
    explicit_targets = _dedupe(explicit_targets)

    if _evidence_complete(evidence=evidence, explicit_targets=explicit_targets):
        return InspectToolStage(
            stage="finalize",
            allowed_tool_names=set(),
            reason="Inspection evidence is sufficient for a grounded final answer.",
            target_paths=explicit_targets,
            evidence_complete=True,
        )

    if final_answer_requested:
        return InspectToolStage(
            stage="finalize",
            allowed_tool_names=set(),
            reason="A final-answer request is already pending.",
            target_paths=explicit_targets,
        )

    if explicit_targets and _has_file_target(explicit_targets) and round_index == 0:
        return InspectToolStage(
            stage="targeted_read",
            allowed_tool_names={"source_probe", "read_file", "search_files", "list_tree", "source_overview"},
            reason="Explicit file or path target was provided; allow direct read.",
            target_paths=explicit_targets,
        )

    if evidence.source_overview_paths or evidence.search_candidate_paths or evidence.inspected_paths:
        representative_targets = _representative_targets(evidence)
        if representative_targets:
            return InspectToolStage(
                stage="targeted_read",
                allowed_tool_names=REPRESENTATIVE_PROBE_TOOLS,
                reason="Source overview was broad or truncated; inspect representative files before final answer.",
                target_paths=representative_targets,
            )
        if round_index >= max(1, inspect_round_budget - 1):
            return InspectToolStage(
                stage="finalize",
                allowed_tool_names=set(),
                reason="Inspect budget is nearly exhausted; finalize from grounded observations.",
                target_paths=explicit_targets,
                evidence_complete=True,
            )
        return InspectToolStage(
            stage="targeted_read",
            allowed_tool_names=TARGETED_READ_TOOLS,
            reason="Discovery evidence exists; allow targeted content inspection.",
            target_paths=explicit_targets,
        )

    return InspectToolStage(
        stage="source_discovery",
        allowed_tool_names=_discovery_tools_for_prompt(prompt, explicit_targets),
        reason="Source tree analysis should start with bounded inventory tools.",
        target_paths=explicit_targets,
    )


def _evidence_complete(*, evidence: CompletionEvidence, explicit_targets: Sequence[str]) -> bool:
    inspected = set(evidence.inspected_paths)
    if explicit_targets and _has_file_target(explicit_targets) and any(
        _target_observed(target, inspected) for target in explicit_targets
    ):
        return True
    if evidence.source_overview_paths:
        return not _representative_targets(evidence)
    if explicit_targets and any(_target_observed(target, inspected) for target in explicit_targets):
        return True
    if evidence.search_candidate_paths and evidence.inspected_paths:
        return True
    if evidence.inspect_observation_count >= 2 and (evidence.search_candidate_paths or evidence.inspected_paths):
        return True
    return False


def _representative_targets(evidence: CompletionEvidence) -> list[str]:
    if not evidence.source_overview_paths:
        return []
    observed = {_normalize_path(path) for path in [*evidence.inspected_paths, *evidence.representative_read_paths]}
    candidates = [
        path
        for path in _dedupe(evidence.source_representative_candidates)
        if _normalize_path(path) not in observed
    ]
    all_candidates = _dedupe(evidence.source_representative_candidates)
    required_count = _required_representative_read_count(evidence, candidate_count=len(all_candidates))
    observed_count = _observed_representative_count(all_candidates, observed)
    if required_count <= 0 or observed_count >= required_count:
        return []
    if not candidates:
        return []
    remaining_needed = max(1, required_count - observed_count)
    return candidates[: min(3, remaining_needed)]


def _required_representative_read_count(evidence: CompletionEvidence, *, candidate_count: int) -> int:
    if candidate_count <= 0:
        return 0
    coverage = evidence.source_analysis_coverage or {}
    package_count = _int_value(coverage.get("package_count"), default=0)
    broad_or_truncated = _broad_or_truncated(evidence)
    if broad_or_truncated:
        coverage_cap = 8 if package_count >= 6 else 6 if package_count >= 4 else 4
        structural_need = package_count if package_count > 0 else candidate_count
        return min(candidate_count, coverage_cap, max(2, structural_need))
    if package_count <= 1 and candidate_count == 1:
        return 1
    return min(candidate_count, 2)


def _observed_representative_count(candidates: Sequence[str], observed: set[str]) -> int:
    return sum(1 for candidate in candidates if _normalize_path(candidate) in observed)


def _broad_or_truncated(evidence: CompletionEvidence) -> bool:
    coverage = evidence.source_analysis_coverage or {}
    coverage_ratio = _float_value(coverage.get("coverage_ratio"), default=1.0)
    package_count = _int_value(coverage.get("package_count"), default=0)
    return (
        evidence.source_overview_truncated
        or bool(coverage.get("truncated"))
        or coverage_ratio < 0.85
        or package_count > 1
    )


def _float_value(value, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int_value(value, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _target_observed(target: str, inspected: set[str]) -> bool:
    normalized = _normalize_path(target)
    if not normalized:
        return False
    return any(_paths_overlap(path, normalized) for path in inspected)


def _paths_overlap(path: str, target: str) -> bool:
    cleaned = _normalize_path(path)
    return bool(cleaned and target and (cleaned.endswith(target) or target.endswith(cleaned)))


def _has_file_target(targets: Sequence[str]) -> bool:
    return any(bool(re.search(r"\.[A-Za-z0-9]{1,8}$", target.strip())) for target in targets)


def _explicit_target_paths(prompt: str) -> list[str]:
    candidates: list[str] = []
    for quoted in re.findall(r"`([^`]+)`", prompt):
        if _looks_path_like(quoted):
            candidates.append(quoted)
    for token in re.findall(r"(?<!\w)(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+(?:\.[A-Za-z0-9]+)?", prompt):
        candidates.append(token)
    for token in re.findall(r"(?<!\w)[A-Za-z0-9_.-]+\.(?:py|js|ts|tsx|java|go|rs|md|toml|yaml|yml|json)(?!\w)", prompt):
        candidates.append(token)
    return _dedupe(candidates)


def _looks_path_like(value: str) -> bool:
    stripped = value.strip()
    return "/" in stripped or bool(re.search(r"\.[A-Za-z0-9]{1,8}$", stripped))


def _dedupe(values: Sequence[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        cleaned = value.strip().strip("`")
        if cleaned and cleaned not in seen:
            seen.append(cleaned)
    return seen[:8]


def _normalize_path(path: str) -> str:
    return path.strip().strip("`").replace("\\", "/")


def _source_inventory_request(prompt: str) -> bool:
    lowered = prompt.lower()
    english_markers = (
        "source tree",
        "directory structure",
        "module inventory",
        "package role",
        "package roles",
        "file layout",
        "src",
    )
    korean_markers = ("구조", "역할", "디렉터리", "소스", "코드들", "파일 목록")
    return any(marker in lowered for marker in english_markers) or any(marker in prompt for marker in korean_markers)


def _discovery_tools_for_prompt(prompt: str, explicit_targets: Sequence[str]) -> set[str]:
    if _source_inventory_request(prompt) or any(_looks_directory_target(target) for target in explicit_targets):
        return {"source_overview"}
    return DISCOVERY_TOOLS


def _looks_directory_target(target: str) -> bool:
    cleaned = target.strip().strip("`").replace("\\", "/")
    if not cleaned:
        return False
    if _has_file_target([cleaned]):
        return False
    return "/" in cleaned or cleaned in {"src", "tests", "test", "."}
