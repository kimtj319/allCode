"""Shared target extraction and matching helpers for read-only source inspection."""

from __future__ import annotations

import re
from collections.abc import Sequence


def explicit_target_paths(prompt: str) -> list[str]:
    candidates: list[str] = []
    for quoted in re.findall(r"`([^`]+)`", prompt):
        if looks_path_like(quoted):
            candidates.append(quoted)
    for token in re.findall(r"(?<!\w)(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+(?:\.[A-Za-z0-9]+)?", prompt):
        candidates.append(token)
    for token in re.findall(r"(?<!\w)[A-Za-z0-9_.-]+\.(?:py|js|ts|tsx|java|go|rs|md|toml|yaml|yml|json)(?!\w)", prompt):
        candidates.append(token)
    return dedupe_targets(candidates)


def looks_path_like(value: str) -> bool:
    stripped = value.strip()
    return "/" in stripped or bool(re.search(r"\.[A-Za-z0-9]{1,8}$", stripped))


def dedupe_targets(values: Sequence[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        cleaned = normalize_target(value)
        if cleaned and cleaned not in seen:
            seen.append(cleaned)
    return seen[:8]


def normalize_target(path: str) -> str:
    return str(path or "").strip().strip("`").replace("\\", "/").strip("/")


def target_observed(target: str, inspected: set[str]) -> bool:
    normalized = normalize_target(target)
    if not normalized:
        return False
    return any(paths_overlap(path, normalized) for path in inspected)


def target_matches_path(target: str, path: str) -> bool:
    normalized_target = normalize_target(target)
    normalized_path = normalize_target(path)
    if not normalized_target or not normalized_path:
        return False
    if paths_overlap(normalized_path, normalized_target):
        return True
    if "/" not in normalized_target:
        return normalized_target in normalized_path.split("/")
    return False


def paths_overlap(path: str, target: str) -> bool:
    cleaned = normalize_target(path)
    normalized_target = normalize_target(target)
    return bool(
        cleaned
        and normalized_target
        and (
            cleaned == normalized_target
            or cleaned.startswith(f"{normalized_target}/")
            or normalized_target.startswith(f"{cleaned}/")
        )
    )
