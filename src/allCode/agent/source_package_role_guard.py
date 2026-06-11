"""Coverage guard for package-role source-analysis answers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from allCode.agent.language import ResponseLanguage
from allCode.agent.prompt_builder_helpers import tool_results_from_messages
from allCode.core.models import Message


@dataclass(frozen=True)
class PackageRoleCoverageViolation:
    reason: str
    excerpt: str


def missing_priority_package_roles(
    *,
    answer: str,
    messages: list[Message],
    user_prompt: str,
) -> PackageRoleCoverageViolation | None:
    if not _broad_source_role_request(user_prompt):
        return None
    role_paths = package_role_paths(messages)
    if len(role_paths) < 4:
        return None
    priority_paths = role_paths[: min(6, len(role_paths))]
    missing = [path for path in priority_paths if not _role_path_mentioned(answer, path)]
    if not missing:
        return None
    return PackageRoleCoverageViolation(
        reason="source_answer_missing_priority_package_roles",
        excerpt="missing observed package roles: " + ", ".join(missing[:4]),
    )


def package_role_retry_candidates(messages: list[Message], *, language: ResponseLanguage) -> str:
    paths = package_role_paths(messages)[:8]
    if not paths:
        return ""
    joined = ", ".join(f"`{path}`" for path in paths)
    if language == "ko":
        return f"관찰된 상위 패키지 역할 후보: {joined}."
    return f"Observed high-priority package role candidates: {joined}."


def package_role_paths(messages: list[Message]) -> list[str]:
    paths: list[str] = []
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
    return paths


def _broad_source_role_request(prompt: str) -> bool:
    lowered = str(prompt or "").lower()
    compact = re.sub(r"\s+", "", lowered)
    source_scope = any(term in lowered for term in ("src", "source tree", "source code", "codebase")) or any(
        term in compact for term in ("현재디렉터리", "현재디렉토리", "소스코드", "코드들")
    )
    role_request = any(term in lowered for term in ("role", "roles", "structure", "architecture")) or any(
        term in compact for term in ("역할", "구조", "아키텍처", "정리")
    )
    return source_scope and role_request


def _role_path_mentioned(answer: str, path: str) -> bool:
    text = str(answer or "")
    if path and path in text:
        return True
    name = Path(path).name
    return bool(name and re.search(rf"(?<![A-Za-z0-9_.-]){re.escape(name)}(?![A-Za-z0-9_.-])", text))


def _clean_path(value: str) -> str:
    return value.strip().strip("`").replace("\\", "/")
