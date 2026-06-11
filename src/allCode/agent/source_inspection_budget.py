"""Shared representative coverage budgets for read-only source inspection."""

from __future__ import annotations

from allCode.core.result import CompletionEvidence


def broad_source_scope(evidence: CompletionEvidence) -> bool:
    coverage = evidence.source_analysis_coverage or {}
    coverage_ratio = _float_value(coverage.get("coverage_ratio"), default=1.0)
    package_count = _int_value(coverage.get("package_count"), default=0)
    return (
        evidence.source_overview_truncated
        or bool(coverage.get("truncated"))
        or coverage_ratio < 0.85
        or package_count > 1
    )


def required_representative_probe_count(
    evidence: CompletionEvidence,
    *,
    candidate_count: int | None = None,
) -> int:
    candidates = candidate_count
    if candidates is None:
        candidates = len([path for path in evidence.source_representative_candidates if str(path).strip()])
    if candidates <= 0:
        return 2 if evidence.source_overview_paths else 0
    coverage = evidence.source_analysis_coverage or {}
    package_count = _int_value(coverage.get("package_count"), default=0)
    coverage_ratio = _float_value(coverage.get("coverage_ratio"), default=1.0)
    if not broad_source_scope(evidence) and candidates < 5:
        if package_count <= 1 and candidates == 1:
            return 1
        return min(candidates, 2)
    return min(
        candidates,
        _coverage_cap(package_count=package_count, candidate_count=candidates),
        _structural_need(
            package_count=package_count,
            candidate_count=candidates,
            coverage_ratio=coverage_ratio,
        ),
    )


def _coverage_cap(*, package_count: int, candidate_count: int) -> int:
    if package_count >= 6 or candidate_count >= 10:
        return 8
    if package_count >= 4 or candidate_count >= 8:
        return 6
    return 4


def _structural_need(*, package_count: int, candidate_count: int, coverage_ratio: float) -> int:
    if package_count > 1:
        return max(2, package_count)
    if candidate_count >= 8:
        return 5
    if candidate_count >= 5:
        return 4
    if coverage_ratio < 0.85:
        return 2
    return 2


def _float_value(value: object, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int_value(value: object, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
