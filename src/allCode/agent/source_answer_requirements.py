"""Prompt-derived output obligations for source-analysis answers."""

from __future__ import annotations

import re
from dataclasses import dataclass

from allCode.agent.source_responsibility_graph import responsibility_graph_from_payload


@dataclass(frozen=True)
class SourceAnswerRequirements:
    important_file_count: int = 0
    risk_count: int = 0
    improvement_count: int = 0


def source_answer_requirements(prompt: str) -> SourceAnswerRequirements:
    return SourceAnswerRequirements(
        important_file_count=_requested_count(
            prompt,
            markers=("중요 파일", "핵심 파일", "대표 파일", "important file", "key file", "representative file"),
        ),
        risk_count=_requested_count(prompt, markers=("리스크", "위험", "병목", "risk", "bottleneck")),
        improvement_count=_requested_count(prompt, markers=("개선", "보강", "보완", "improvement", "recommendation")),
    )


def source_output_obligation_lines(prompt: str, *, language: str) -> list[str]:
    requirements = source_answer_requirements(prompt)
    lines: list[str] = []
    if requirements.important_file_count:
        if language == "en":
            lines.append(f"- Cover at least {requirements.important_file_count} important observed files when evidence permits.")
        else:
            lines.append(f"- 관찰 근거가 허용하면 중요한 파일을 최소 {requirements.important_file_count}개 설명하십시오.")
    if requirements.risk_count:
        label = "risks/bottlenecks" if language == "en" else "리스크/병목"
        lines.append(f"- Include {requirements.risk_count} {label}.")
    if requirements.improvement_count:
        label = "improvements" if language == "en" else "개선점"
        lines.append(f"- Include {requirements.improvement_count} {label}.")
    return lines


def important_file_lines(brief, *, prompt: str, language: str) -> list[str]:
    requirements = source_answer_requirements(prompt)
    if requirements.important_file_count <= 0:
        return []
    candidates = _important_file_candidates(brief, language=language)
    return candidates[: requirements.important_file_count]


def _important_file_candidates(brief, *, language: str) -> list[str]:
    candidates: list[str] = []
    graph = responsibility_graph_from_payload(getattr(brief, "responsibility_graph", {}))
    role_by_path = {getattr(role, "path", ""): getattr(role, "role", "") for role in getattr(brief, "package_roles", [])}
    node_roles: dict[str, list[str]] = {}
    for node in graph.nodes:
        if node.role_hint:
            node_roles.setdefault(node.path, []).append(node.role_hint)
    for file in getattr(brief, "representative_files", []):
        path = getattr(file, "path", "")
        if not path:
            continue
        details = _file_details(path, file=file, role_by_path=role_by_path, node_roles=node_roles, language=language)
        _append(candidates, f"`{path}`: {details}")
    for path in getattr(brief, "observed_paths", []):
        if path and _looks_like_file(path):
            _append(
                candidates,
                f"`{path}`: {'source overview evidence' if language == 'en' else 'source overview 근거'}",
            )
    return candidates


def _file_details(path: str, *, file, role_by_path: dict[str, str], node_roles: dict[str, list[str]], language: str) -> str:
    details: list[str] = []
    role = role_by_path.get(path) or _nearest_role(path, role_by_path)
    if role:
        details.append(role)
    if node_roles.get(path):
        details.append("; ".join(_dedupe(node_roles[path])[:2]))
    symbols = list(getattr(file, "symbols", []) or [])
    if symbols:
        label = "symbols" if language == "en" else "관찰 심볼"
        details.append(f"{label} " + ", ".join(f"`{symbol}`" for symbol in symbols[:3]))
    ranges = list(getattr(file, "ranges", []) or [])
    if ranges:
        label = "anchors" if language == "en" else "근거 anchor"
        details.append(f"{label} " + ", ".join(f"`{path}:{item}`" for item in ranges[:2]))
    wiring = list(getattr(file, "wiring", []) or [])
    if wiring:
        label = "wiring" if language == "en" else "연결 단서"
        details.append(f"{label} " + ", ".join(wiring[:2]))
    if not details:
        return "representative file evidence" if language == "en" else "대표 파일 근거"
    return "; ".join(details)


def _nearest_role(path: str, role_by_path: dict[str, str]) -> str:
    for role_path, role in role_by_path.items():
        if role_path and (path.startswith(role_path.rstrip("/") + "/") or role_path.startswith(path.rstrip("/") + "/")):
            return role
    return ""


def _requested_count(prompt: str, *, markers: tuple[str, ...]) -> int:
    text = str(prompt or "")
    lowered = text.lower()
    compact = re.sub(r"\s+", "", lowered)
    marker_compacts = tuple(re.sub(r"\s+", "", marker.lower()) for marker in markers)
    if not any(marker in lowered or marker in compact for marker in (*markers, *marker_compacts)):
        return 0
    marker_pattern = "|".join(re.escape(marker) for marker in (*markers, *marker_compacts))
    patterns = (
        rf"(?:{marker_pattern}).{{0,40}}?(?:최소|at least)?\s*(\d+)\s*(?:개|가지|items?|files?|points?)",
        rf"(\d+)\s*(?:개|가지|items?|files?|points?).{{0,40}}?(?:{marker_pattern})",
        rf"(?:{marker_pattern})\D{{0,40}}?(\d+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return min(12, max(1, int(match.group(1))))
    if any(marker in compact for marker in marker_compacts):
        return 3
    return 0


def _append(values: list[str], value: str) -> None:
    key = _dedupe_key(value)
    if key and all(_dedupe_key(existing) != key for existing in values):
        values.append(value)


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _dedupe_key(value: str) -> str:
    match = re.search(r"`([^`]+)`", value)
    return match.group(1) if match else value.strip()


def _looks_like_file(path: str) -> bool:
    name = str(path or "").rstrip("/").rsplit("/", 1)[-1]
    return "." in name
