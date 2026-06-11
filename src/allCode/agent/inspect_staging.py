"""Source-analysis staging for read-only inspect turns."""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import Field

from allCode.agent.inspect_targets import (
    dedupe_targets,
    explicit_target_paths,
    looks_path_like,
    normalize_target,
    target_matches_path,
    target_observed,
)
from allCode.agent.source_inspection_budget import broad_source_scope, required_representative_probe_count
from allCode.core.models import CoreModel
from allCode.core.result import CompletionEvidence

InspectStageName = Literal["none", "source_discovery", "targeted_read", "finalize"]

DISCOVERY_TOOLS = {"source_overview", "list_tree", "glob_files"}
TARGETED_READ_TOOLS = {"source_probe", "read_file", "search_files", "source_overview", "list_tree", "glob_files"}
REPRESENTATIVE_PROBE_TOOLS = {"source_probe"}
WELL_KNOWN_EXTENSIONLESS_FILES = {
    "Dockerfile",
    "Containerfile",
    "Makefile",
    "Rakefile",
    "Gemfile",
    "Procfile",
    "Brewfile",
}


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

    explicit_targets = explicit_target_paths(prompt)
    target_hint = str(getattr(routing, "target_hint", "") or "").strip()
    if target_hint:
        explicit_targets.append(target_hint)
    explicit_targets = dedupe_targets(explicit_targets)

    if _evidence_complete(evidence=evidence, explicit_targets=explicit_targets):
        return InspectToolStage(
            stage="finalize",
            allowed_tool_names=set(),
            reason="Inspection evidence is sufficient for a grounded final answer.",
            target_paths=explicit_targets,
            evidence_complete=True,
        )

    missing_file_targets = _missing_explicit_file_targets(evidence, explicit_targets)
    if missing_file_targets:
        return InspectToolStage(
            stage="targeted_read",
            allowed_tool_names={"source_probe", "read_file"},
            reason="Explicit file targets must be observed before broad source-analysis finalization.",
            target_paths=missing_file_targets,
        )

    missing_overview_targets = _missing_explicit_overview_targets(evidence, explicit_targets)
    if missing_overview_targets and round_index < max(1, inspect_round_budget - 1):
        return InspectToolStage(
            stage="source_discovery",
            allowed_tool_names={"source_overview"},
            reason="Explicit source target still needs source overview before representative reads.",
            target_paths=missing_overview_targets,
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
            allowed_tool_names={"source_probe", "read_file"},
            reason="Explicit file or path target was provided; allow direct read.",
            target_paths=explicit_targets,
        )

    if evidence.source_overview_paths or evidence.search_candidate_paths or evidence.inspected_paths:
        representative_targets = _representative_targets(evidence, explicit_targets)
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
    if _missing_explicit_file_targets(evidence, explicit_targets):
        return False
    if _missing_explicit_overview_targets(evidence, explicit_targets):
        return False
    if _representative_evidence_missing(evidence, explicit_targets):
        return False
    inspected = set(evidence.inspected_paths)
    if explicit_targets and _has_file_target(explicit_targets) and all(
        target_observed(target, inspected) for target in explicit_targets
    ):
        return True
    if evidence.source_overview_paths:
        return not _representative_targets(evidence, explicit_targets)
    if explicit_targets and all(target_observed(target, inspected) for target in explicit_targets):
        return True
    if evidence.search_candidate_paths and evidence.inspected_paths:
        return True
    if evidence.inspect_observation_count >= 2 and (evidence.search_candidate_paths or evidence.inspected_paths):
        return True
    return False


def _representative_evidence_missing(evidence: CompletionEvidence, explicit_targets: Sequence[str]) -> bool:
    if not evidence.source_overview_paths:
        return False
    broad_scope = broad_source_scope(evidence) or any(_looks_directory_target(target) for target in explicit_targets)
    if not broad_scope:
        return False
    observed = {_normalize_path(path) for path in [*evidence.inspected_paths, *evidence.representative_read_paths]}
    candidates = _dedupe(evidence.source_representative_candidates)
    if candidates:
        required_count = _required_representative_read_count(evidence, candidate_count=len(candidates))
        return _observed_representative_count(candidates, observed) < required_count
    coverage = evidence.source_analysis_coverage or {}
    package_count = _int_value(coverage.get("package_count"), default=0)
    required_observed = min(4, max(2, package_count)) if package_count > 1 else 1
    if explicit_targets:
        directory_target_count = sum(1 for target in explicit_targets if _looks_directory_target(target))
        required_observed = max(required_observed, min(4, max(1, directory_target_count)))
    return len(observed) < required_observed


def _missing_explicit_overview_targets(evidence: CompletionEvidence, explicit_targets: Sequence[str]) -> list[str]:
    directory_targets = [target for target in explicit_targets if not _is_file_target(target)]
    if not directory_targets:
        return []
    coverage_paths = _overview_coverage_paths(evidence)
    if not coverage_paths:
        return directory_targets
    return [target for target in directory_targets if not target_observed(target, coverage_paths)]


def _missing_explicit_file_targets(evidence: CompletionEvidence, explicit_targets: Sequence[str]) -> list[str]:
    file_targets = [target for target in explicit_targets if _is_file_target(target)]
    if not file_targets:
        return []
    observed = {
        _normalize_path(path)
        for path in [*evidence.inspected_paths, *evidence.representative_read_paths]
        if _normalize_path(path)
    }
    not_found = {_normalize_path(path) for path in evidence.not_found_targets if _normalize_path(path)}
    return [
        target
        for target in file_targets
        if _normalize_path(target) not in not_found and not target_observed(target, observed)
    ]


def _overview_coverage_paths(evidence: CompletionEvidence) -> set[str]:
    overview_targets = {_normalize_path(path) for path in evidence.source_overview_targets if path}
    if overview_targets:
        return overview_targets
    return {_normalize_path(path) for path in evidence.source_overview_paths if path}


def _representative_targets(evidence: CompletionEvidence, explicit_targets: Sequence[str] = ()) -> list[str]:
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

    groups = _candidate_groups(candidates, explicit_targets)

    balanced_selection: list[str] = []
    group_keys = sorted(groups.keys())

    while len(balanced_selection) < remaining_needed:
        added_any = False
        for key in group_keys:
            if groups[key]:
                balanced_selection.append(groups[key].pop(0))
                added_any = True
                if len(balanced_selection) >= remaining_needed:
                    break
        if not added_any:
            break

    return balanced_selection


def _candidate_groups(candidates: Sequence[str], explicit_targets: Sequence[str]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    normalized_targets = [normalize_target(target) for target in explicit_targets if normalize_target(target)]
    if normalized_targets:
        for candidate in candidates:
            bucket = _matching_explicit_target(candidate, normalized_targets) or "__unmatched__"
            groups.setdefault(bucket, []).append(candidate)
        if any(key != "__unmatched__" for key in groups):
            return groups
    return _package_candidate_groups(candidates)


def _matching_explicit_target(candidate: str, targets: Sequence[str]) -> str:
    for target in targets:
        if target_matches_path(target, candidate):
            return target
    return ""


def _package_candidate_groups(candidates: Sequence[str]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for candidate in candidates:
        group = Path(candidate).parent.as_posix()
        groups.setdefault(group, []).append(candidate)
    return groups


def _required_representative_read_count(evidence: CompletionEvidence, *, candidate_count: int) -> int:
    return required_representative_probe_count(evidence, candidate_count=candidate_count)


def _observed_representative_count(candidates: Sequence[str], observed: set[str]) -> int:
    return sum(1 for candidate in candidates if _normalize_path(candidate) in observed)


def _int_value(value, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _target_observed(target: str, inspected: set[str]) -> bool:
    return target_observed(target, inspected)


def _paths_overlap(path: str, target: str) -> bool:
    return target_matches_path(target, path)


def _has_file_target(targets: Sequence[str]) -> bool:
    return any(_is_file_target(target) for target in targets)


def _is_file_target(target: str) -> bool:
    cleaned = target.strip().strip("`").replace("\\", "/")
    name = Path(cleaned).name
    return name in WELL_KNOWN_EXTENSIONLESS_FILES or bool(re.search(r"\.[A-Za-z0-9]{1,16}$", cleaned))


def _explicit_target_paths(prompt: str) -> list[str]:
    return explicit_target_paths(prompt)


def _looks_path_like(value: str) -> bool:
    return looks_path_like(value)


def _dedupe(values: Sequence[str]) -> list[str]:
    return dedupe_targets(values)


def _normalize_path(path: str) -> str:
    return normalize_target(path)


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
