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


class SourceExplorationLedger(CoreModel):
    observed_scopes: list[str] = Field(default_factory=list)
    representative_files: list[str] = Field(default_factory=list)
    unobserved_candidates: list[str] = Field(default_factory=list)
    coverage_note: str = ""

    def render(self) -> str:
        lines: list[str] = []
        if self.observed_scopes:
            lines.append("Observed source scopes: " + ", ".join(self.observed_scopes[:6]))
        if self.representative_files:
            lines.append("Representative files read: " + ", ".join(self.representative_files[:8]))
        if self.unobserved_candidates:
            lines.append("Unobserved representative candidates: " + ", ".join(self.unobserved_candidates[:6]))
        if self.coverage_note:
            lines.append("Coverage note: " + self.coverage_note[:240])
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


def source_exploration_ledger_from_evidence(
    evidence: CompletionEvidence,
    *,
    workspace_root: str = "",
) -> SourceExplorationLedger:
    observed = _dedupe(
        [
            _relative_to_workspace(path, workspace_root=workspace_root)
            for path in [*evidence.source_overview_paths, *evidence.inspected_paths]
        ]
    )
    representatives = _dedupe(
        [
            _relative_to_workspace(path, workspace_root=workspace_root)
            for path in [*evidence.representative_read_paths, *evidence.inspected_paths]
        ]
    )
    representative_set = set(representatives)
    unobserved = [
        _relative_to_workspace(path, workspace_root=workspace_root)
        for path in evidence.source_representative_candidates
        if _relative_to_workspace(path, workspace_root=workspace_root) not in representative_set
    ]
    coverage = evidence.source_analysis_coverage or {}
    coverage_note = _coverage_note(coverage, truncated=evidence.source_overview_truncated)
    return SourceExplorationLedger(
        observed_scopes=observed[:10],
        representative_files=representatives[:12],
        unobserved_candidates=_dedupe(unobserved)[:8],
        coverage_note=coverage_note,
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


def _coverage_note(coverage: dict[str, object], *, truncated: bool) -> str:
    parts: list[str] = []
    if truncated or bool(coverage.get("truncated")):
        parts.append("source overview was truncated")
    ratio = coverage.get("coverage_ratio")
    if ratio is not None:
        try:
            parts.append(f"coverage_ratio={float(ratio):.4f}")
        except (TypeError, ValueError):
            pass
    package_count = coverage.get("package_count")
    if package_count is not None:
        parts.append(f"package_count={package_count}")
    return "; ".join(parts)


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


# Verb-conjugation / imperative fragments that are instruction wording, not
# feature nouns. Multi-char suffixes are preferred so genuine nouns ending in an
# ambiguous syllable (메시지, 라우팅, 이미지 …) are not wrongly dropped.
_KO_VERB_SUFFIXES = (
    "해서", "아서", "어서", "여서", "해주고", "주고", "하고", "하라", "해라", "해줘",
    "해줄", "했던", "하던", "하는", "하며", "하면", "합니다", "됩니다", "하기", "하지",
    "해야", "해주", "한다", "된다",
)
_KO_VERB_SINGLE = ("하", "해", "서", "며", "면", "던", "워")


def _is_korean_instruction_fragment(token: str) -> bool:
    if any(token.endswith(suffix) for suffix in _KO_VERB_SUFFIXES):
        return True
    return len(token) >= 2 and token.endswith(_KO_VERB_SINGLE)


def _split_korean_objective_phrase(value: str) -> list[str]:
    normalized = value.replace(",", " ").replace("및", " ").replace("와", " ").replace("과", " ")
    tokens = []
    for token in normalized.split():
        cleaned = _strip_korean_particle(token)
        if not cleaned or cleaned in _KOREAN_STOP_TERMS:
            continue
        # Also drop truncations/inflections of a stop word (e.g. "최종결" from
        # "최종결과", "검증기" from "검증") — generic meta words, not features.
        if any(len(stop) >= 2 and cleaned.startswith(stop) for stop in _KOREAN_STOP_TERMS):
            continue
        if _is_korean_instruction_fragment(cleaned):
            continue
        tokens.append(cleaned)
    return tokens


def _strip_korean_particle(value: str) -> str:
    if value.endswith("하고") and len(value) > 4:
        return value[:-2]
    for particle in ("으로", "에서", "에게", "와", "과", "을", "를", "에", "의", "도", "은", "는", "이", "가", "들"):
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
    # Instruction/meta words that leaked into the "핵심 기능" summary on
    # fix-it style prompts ("검증 실패 원인을 찾아서 정리해서 작성하라").
    "실패",
    "원인",
    "수정",
    "작성",
    "정리",
    "생성",
    "구현",
    "완료",
    "진행",
    "분석",
    "최종",
    "결과",
    "내용",
    "최종결과",
    "유효성",
}
