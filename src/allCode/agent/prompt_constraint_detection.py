"""Pure detection helpers for prompt constraint extraction."""

from __future__ import annotations

import re

from allCode.agent.prompt_constraint_terms import (
    CODE_ARTIFACT_TERMS,
    COMMON_WORKSPACE_DIRS,
    ENGLISH_CHANGE_COMMAND,
    KOREAN_CHANGE_COMMAND,
    KOREAN_CHANGE_CONNECTIVE,
    PROJECT_OUTPUT_TERMS,
)
from allCode.core.path_patterns import PATH_PATTERN, extract_prompt_path


def path_hints(prompt: str) -> list[str]:
    paths: list[str] = []
    for match in PATH_PATTERN.finditer(prompt):
        value = match.group("path").lstrip("@")
        if value not in paths:
            paths.append(value)
    first = extract_prompt_path(prompt)
    if first and first not in paths:
        paths.insert(0, first)
    lowered = prompt.lower()
    for directory in COMMON_WORKSPACE_DIRS:
        if directory in paths:
            continue
        if re.search(rf"(?<![A-Za-z0-9_.-]){re.escape(directory)}(?![A-Za-z0-9_.-])", lowered):
            paths.append(directory)
    return paths


def directory_output_hint(paths: list[str], *, prompt: str, mutation_requested: bool) -> bool:
    if not mutation_requested:
        return False
    lowered = prompt.lower()
    output_context = any(term in lowered for term in ("output", "under", "inside", "directory", "folder")) or any(
        term in prompt for term in ("아래", "하위", "내부", "안에", "디렉터리", "디렉토리", "폴더", "경로")
    )
    for path in paths:
        normalized = path.strip().strip("`").replace("\\", "/")
        while normalized.startswith("./"):
            normalized = normalized[2:]
        if not normalized or normalized.startswith("../"):
            continue
        name = normalized.rsplit("/", 1)[-1]
        if "." in name:
            continue
        if "/" in normalized and output_context:
            return True
        if normalized.split("/", 1)[0] in {"output", "dist", "build", "examples", "apps", "packages"}:
            return True
    return False


def direct_mutation_command(prompt: str) -> bool:
    if ENGLISH_CHANGE_COMMAND.search(prompt):
        return True
    if KOREAN_CHANGE_COMMAND.search(prompt):
        return True
    return bool(KOREAN_CHANGE_CONNECTIVE.search(prompt))


def path_mutation_hint(paths: list[str]) -> bool:
    for path in paths:
        normalized = path.strip().strip("`").replace("\\", "/")
        if not normalized:
            continue
        name = normalized.rsplit("/", 1)[-1]
        if "." in name:
            return True
    return False


def concrete_workspace_paths(paths: list[str]) -> list[str]:
    """Keep only path hints that look like actual workspace locators."""

    concrete: list[str] = []
    for path in paths:
        normalized = path.strip().strip("`").replace("\\", "/")
        while normalized.startswith("@"):
            normalized = normalized[1:]
        if not normalized:
            continue
        first = normalized.split("/", 1)[0]
        name = normalized.rsplit("/", 1)[-1]
        if normalized.startswith(("/", "./", "../")):
            concrete.append(path)
        elif "." in name:
            concrete.append(path)
        elif first in COMMON_WORKSPACE_DIRS:
            concrete.append(path)
    return concrete


def external_knowledge_suppressed(prompt: str) -> bool:
    """Return True when the user explicitly asks for evergreen principles.

    This does not prevent web search for current facts. It only suppresses weak
    unstable-knowledge signals such as "cost" or "benchmark" when the prompt
    says not to use latest/current numbers and asks for general principles.
    """

    lowered = prompt.lower()
    compact = re.sub(r"\s+", "", lowered)
    evergreen_signal = any(
        term in lowered
        for term in (
            "general principle",
            "general principles",
            "general rule",
            "conceptual",
            "evergreen",
            "not latest",
            "not current",
            "no latest",
            "no current",
            "without latest",
            "without current",
        )
    ) or any(term in compact for term in ("일반원칙", "일반적인원칙", "원칙중심", "개념중심", "최신수치가아니라", "최신정보가아니라", "현재정보가아니라"))
    explicit_current_request = any(
        term in lowered for term in ("latest release", "current version", "today's", "as of today")
    ) or any(term in compact for term in ("오늘기준", "현재버전", "최신릴리스"))
    return evergreen_signal and not explicit_current_request


def answer_only_artifact_hint(prompt: str) -> bool:
    """Detect requests for code/project artifacts as answer text, not files."""

    lowered = prompt.lower()
    compact = re.sub(r"\s+", "", lowered)
    artifact_terms = CODE_ARTIFACT_TERMS + PROJECT_OUTPUT_TERMS
    has_artifact = any(term.lower() in lowered or term.lower().replace(" ", "") in compact for term in artifact_terms)
    answer_form = any(
        term in lowered or term in compact
        for term in (
            "draft",
            "outline",
            "design",
            "sketch",
            "snippet",
            "example",
            "candidate",
            "strategy",
            "초안",
            "설계",
            "개요",
            "예시",
            "스니펫",
            "후보",
            "전략",
            "구조",
        )
    )
    no_file_output = any(
        term in lowered or term in compact
        for term in (
            "do not create files",
            "don't create files",
            "without creating files",
            "do not write files",
            "don't write files",
            "answer only",
            "as an answer",
            "answer as text",
            "실제파일은만들지",
            "파일은만들지",
            "파일을만들지",
            "파일생성금지",
            "답변으로만",
            "답변으로작성",
            "답변으로제공",
        )
    )
    return has_artifact and answer_form and no_file_output
