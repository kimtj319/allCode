"""Metadata helpers for bounded source overview results."""

from __future__ import annotations


def representative_read_limit(*, groups: list[dict[str, object]]) -> int:
    """Return an adaptive but bounded representative-read budget.

    Broad source inventory prompts need package coverage more than a tiny top-N
    ranking. The cap keeps observations compact and prevents full-repo dumps.
    """

    package_count = len(groups)
    if package_count >= 10:
        return 12
    if package_count >= 6:
        return 10
    return max(8, package_count)


def suggested_read_limit(*, groups: list[dict[str, object]], representative_count: int) -> int:
    package_count = len(groups)
    if package_count >= 10:
        return min(representative_count, 12)
    if package_count >= 6:
        return min(representative_count, 10)
    return min(representative_count, 8)


def package_representative_reads(
    *,
    groups: list[dict[str, object]],
    representative_reads: list[str],
) -> list[dict[str, str]]:
    representatives: list[dict[str, str]] = []
    for group in groups:
        group_path = str(group.get("path") or "").strip()
        if not group_path:
            continue
        representative = _first_representative_for_group(group_path, representative_reads)
        if representative:
            representatives.append({"path": group_path, "representative": representative})
    return representatives


def _first_representative_for_group(group_path: str, representative_reads: list[str]) -> str:
    for path in representative_reads:
        if path == group_path or path.startswith(f"{group_path}/"):
            return path
    return ""
