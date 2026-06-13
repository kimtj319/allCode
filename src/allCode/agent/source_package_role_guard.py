"""Coverage guard for package-role source-analysis answers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from allCode.agent.language import ResponseLanguage
from allCode.agent.prompt_builder_helpers import tool_results_from_messages
from allCode.agent.router import RoutingDecision
from allCode.core.models import Message


@dataclass(frozen=True)
class PackageRoleCoverageViolation:
    reason: str
    excerpt: str


@dataclass(frozen=True)
class PackageRoleEntry:
    path: str
    role: str


def missing_priority_package_roles(
    *,
    answer: str,
    messages: list[Message],
    routing: RoutingDecision | None = None,
    user_prompt: str = "",
) -> PackageRoleCoverageViolation | None:
    role_entries = package_role_entries(messages)
    role_paths = [entry.path for entry in role_entries]
    if not _package_role_guard_applies(routing=routing, messages=messages, role_paths=role_paths):
        return None
    if len(role_entries) < 4:
        return None
    priority_entries = _priority_role_entries(role_entries)
    missing = [entry.path for entry in priority_entries if not _role_entry_supported(answer, entry)]
    if not missing:
        return None
    return PackageRoleCoverageViolation(
        reason="source_answer_missing_priority_package_roles",
        excerpt="missing observed package roles: " + ", ".join(missing[:4]),
    )


def package_role_retry_candidates(messages: list[Message], *, language: ResponseLanguage) -> str:
    entries = package_role_entries(messages)[:8]
    if not entries:
        return ""
    joined = ", ".join(f"`{entry.path}`: {entry.role}" if entry.role else f"`{entry.path}`" for entry in entries)
    if language == "ko":
        return f"관찰된 상위 패키지 역할 후보: {joined}."
    return f"Observed high-priority package role candidates: {joined}."


def package_role_entries(messages: list[Message]) -> list[PackageRoleEntry]:
    paths: list[str] = []
    entries: list[PackageRoleEntry] = []
    for result in tool_results_from_messages(messages):
        roles = result.metadata.get("package_roles")
        if not isinstance(roles, list):
            continue
        for role in roles:
            if not isinstance(role, dict):
                continue
            path = _clean_path(str(role.get("path") or ""))
            if path and path not in paths:
                paths.append(path)
                entries.append(PackageRoleEntry(path=path, role=_compact_role(str(role.get("role") or ""))))
    return entries


def _package_role_guard_applies(
    *,
    routing: RoutingDecision | None,
    messages: list[Message],
    role_paths: list[str],
) -> bool:
    flags = set(getattr(routing, "flags", set()) or set())
    if "broad_source_analysis" in flags:
        return True
    if len(role_paths) < 4:
        return False
    for result in tool_results_from_messages(messages):
        observation = result.metadata.get("observation")
        if not isinstance(observation, dict) or observation.get("kind") != "source_overview":
            continue
        target = _clean_path(str(observation.get("target") or ""))
        if target and "." not in Path(target).name:
            return True
    return False


def _priority_role_entries(entries: list[PackageRoleEntry]) -> list[PackageRoleEntry]:
    concrete = [entry for entry in entries if _package_depth(entry.path) >= 3]
    selected = concrete or entries
    if len(selected) >= 9:
        return selected[:10]
    return selected[: min(8, len(selected))]


def _package_depth(path: str) -> int:
    return len([part for part in _clean_path(path).split("/") if part])


def _role_path_mentioned(answer: str, path: str) -> bool:
    text = str(answer or "")
    if path and path in text:
        return True
    name = Path(path).name
    return bool(name and re.search(rf"(?<![A-Za-z0-9_.-]){re.escape(name)}(?![A-Za-z0-9_.-])", text))


def _role_entry_supported(answer: str, entry: PackageRoleEntry) -> bool:
    if not _role_path_mentioned(answer, entry.path):
        return False
    return not _role_path_in_limitation_context(answer, entry.path)


def _role_path_in_limitation_context(answer: str, path: str) -> bool:
    lines = str(answer or "").splitlines()
    name = Path(path).name
    for index, line in enumerate(lines):
        if path not in line and not (name and re.search(rf"(?<![A-Za-z0-9_.-]){re.escape(name)}(?![A-Za-z0-9_.-])", line)):
            continue
        window = "\n".join(lines[max(0, index - 2) : min(len(lines), index + 3)])
        if _has_limitation_marker(window):
            return True
    return False


def _has_limitation_marker(text: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or "").lower())
    return any(
        marker in compact
        for marker in (
            "관찰근거없",
            "근거없",
            "보류",
            "notobserved",
            "notverified",
            "noevidence",
            "unverified",
        )
    )


def _compact_role(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _clean_path(value: str) -> str:
    return value.strip().strip("`").replace("\\", "/")
