"""Compact multi-turn project obligations and repair context."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import Field

from allCode.core.models import CoreModel
from allCode.core.result import CompletionEvidence, RepairTarget


class ActiveProjectObligations(CoreModel):
    source_files: list[str] = Field(default_factory=list)
    test_files: list[str] = Field(default_factory=list)
    validation_commands: list[str] = Field(default_factory=list)
    feature_objectives: list[str] = Field(default_factory=list)
    unsatisfied_conditions: list[str] = Field(default_factory=list)

    def render(self) -> str:
        lines: list[str] = []
        if self.feature_objectives:
            lines.append("Feature objectives: " + ", ".join(self.feature_objectives[:8]))
        if self.source_files:
            lines.append("Source files: " + ", ".join(self.source_files[:6]))
        if self.test_files:
            lines.append("Test files: " + ", ".join(self.test_files[:6]))
        if self.validation_commands:
            lines.append("Last validation: " + self.validation_commands[-1])
        if self.unsatisfied_conditions:
            lines.append("Unsatisfied: " + "; ".join(self.unsatisfied_conditions[:6]))
        return "\n".join(lines)


class LatestRepairContext(CoreModel):
    command: str = ""
    targets: list[RepairTarget] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)
    excerpt: str = ""

    def render(self) -> str:
        lines: list[str] = []
        if self.command:
            lines.append(f"Last failing validation command: {self.command}")
        if self.targets:
            rendered_targets = [
                f"{target.file_path}:{target.line_number or ''}".rstrip(":")
                for target in self.targets[:3]
            ]
            lines.append("Repair targets: " + ", ".join(rendered_targets))
        if self.symbols:
            lines.append("Failure symbols: " + ", ".join(self.symbols[:3]))
        if self.excerpt:
            lines.append("Failure excerpt:\n" + self.excerpt[:700])
        return "\n".join(lines)


def active_obligations_from_evidence(evidence: CompletionEvidence, *, workspace_root: str = "") -> ActiveProjectObligations:
    changed = [_relative_to_workspace(path, workspace_root=workspace_root) for path in [*evidence.created_files, *evidence.changed_files]]
    source_files = [path for path in changed if not _looks_test_path(path)]
    test_files = [path for path in changed if _looks_test_path(path)]
    unsatisfied = []
    for artifact in evidence.unsatisfied_artifacts():
        label = artifact.kind
        if artifact.target:
            label = f"{label}:{artifact.target}"
        if artifact.reason:
            label = f"{label} ({artifact.reason})"
        unsatisfied.append(label)
    return ActiveProjectObligations(
        source_files=_dedupe(source_files)[:8],
        test_files=_dedupe(test_files)[:8],
        validation_commands=evidence.validation_commands[-3:],
        feature_objectives=_dedupe(evidence.feature_objectives)[:12],
        unsatisfied_conditions=_dedupe(unsatisfied)[:8],
    )


def feature_objectives_from_prompt(prompt: str) -> list[str]:
    """Extract compact, prompt-derived objectives without scenario-specific terms."""

    objectives: list[str] = []
    compact = " ".join(prompt.split())
    for match in re.finditer(r"`([^`]+)`", compact):
        value = match.group(1).strip()
        if _looks_like_path_or_command(value):
            continue
        _add_objective(objectives, value)
    identifier_text = _remove_path_like_segments(compact)
    for match in re.finditer(r"\b[A-Za-z][A-Za-z0-9_]{3,}\b", identifier_text):
        value = match.group(0)
        if _is_common_word(value) or _looks_like_path_or_command(value):
            continue
        _add_objective(objectives, value)
    for match in re.finditer(
        r"([가-힣A-Za-z0-9_,\s와과및]{2,80})(?:추가|구현|연동|보강|작성|생성|검증|수정)",
        compact,
    ):
        for value in _split_korean_objective_phrase(match.group(1)):
            _add_objective(objectives, value)
    return objectives[:12]


def repair_context_from_evidence(evidence: CompletionEvidence) -> LatestRepairContext:
    return LatestRepairContext(
        command=evidence.validation_failure_command or (evidence.validation_commands[-1] if evidence.validation_commands else ""),
        targets=evidence.validation_failure_targets[:3],
        symbols=evidence.validation_failure_symbols[:3],
        excerpt=evidence.validation_failure_excerpt[:700],
    )


def _looks_test_path(path: str) -> bool:
    lowered = path.lower()
    name = lowered.rsplit("/", 1)[-1]
    return lowered.startswith("tests/") or "/tests/" in lowered or name.startswith("test_") or ".test." in name or ".spec." in name


def _relative_to_workspace(path: str, *, workspace_root: str) -> str:
    value = str(path or "").strip()
    if not value or not workspace_root:
        return value
    candidate = Path(value)
    if not candidate.is_absolute():
        return candidate.as_posix()
    try:
        return candidate.expanduser().resolve().relative_to(Path(workspace_root).expanduser().resolve()).as_posix()
    except (OSError, ValueError):
        return candidate.as_posix()


def _dedupe(values: list[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.append(value)
    return seen


def _add_objective(objectives: list[str], value: str) -> None:
    cleaned = _strip_korean_particle(value.strip(" .,;:()[]{}\"'"))
    if len(cleaned) < 2:
        return
    if cleaned in _KOREAN_STOP_TERMS:
        return
    lowered = cleaned.lower()
    if lowered not in {item.lower() for item in objectives}:
        objectives.append(cleaned)


def _looks_like_path_or_command(value: str) -> bool:
    lowered = value.lower()
    return (
        "/" in value
        or "\\" in value
        or lowered.endswith((".py", ".js", ".ts", ".tsx", ".java", ".go", ".rs", ".md", ".txt"))
        or lowered in {"pytest", "python", "npm", "gradle", "mvn", "cargo"}
    )


def _is_common_word(value: str) -> bool:
    return value.lower() in _ENGLISH_STOP_TERMS


def _split_korean_objective_phrase(value: str) -> list[str]:
    normalized = value.replace(",", " ").replace("및", " ").replace("와", " ").replace("과", " ")
    tokens = []
    for token in normalized.split():
        cleaned = _strip_korean_particle(token)
        if cleaned and cleaned not in _KOREAN_STOP_TERMS:
            tokens.append(cleaned)
    return tokens


def _strip_korean_particle(value: str) -> str:
    if value.endswith("하고") and len(value) > 4:
        return value[:-2]
    for particle in ("으로", "에서", "에게", "와", "과", "을", "를", "에", "의", "도", "은", "는"):
        if value.endswith(particle) and len(value) > len(particle) + 1:
            return value[: -len(particle)]
    return value


def _remove_path_like_segments(value: str) -> str:
    without_backtick_paths = re.sub(
        r"`[^`]*[/\\][^`]*`",
        " ",
        value,
    )
    return re.sub(r"\b\S+[/\\]\S+\b", " ", without_backtick_paths)


_ENGLISH_STOP_TERMS = {
    "about",
    "add",
    "code",
    "create",
    "file",
    "files",
    "implementation",
    "project",
    "python",
    "test",
    "tests",
    "unit",
    "update",
    "validation",
    "with",
}

_KOREAN_STOP_TERMS = {
    "전체",
    "코드",
    "단위",
    "테스트",
    "검증",
    "기존",
    "대한",
    "추가",
    "추가하고",
    "보강",
    "보강하고",
    "파일",
    "프로젝트",
    "기능",
    "로직",
}
