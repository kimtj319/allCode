"""Grounded fallback summaries for read-only source inspection turns."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from allCode.agent.finalization_helpers import last_tool_results
from allCode.agent.language import ResponseLanguage, normalize_response_language
from allCode.agent.source_answer_synthesis import probe_evidence_lines
from allCode.agent.source_structure import CodeStructureSummary, read_file_code_summaries
from allCode.core.models import Message
from allCode.core.result import CompletionEvidence


def grounded_inspect_summary(
    *,
    messages: Sequence[Message],
    evidence: CompletionEvidence,
    reason: str,
    response_language: ResponseLanguage | None = None,
) -> str:
    language = normalize_response_language(response_language or "ko")
    tool_results = last_tool_results(messages)
    observed_paths = _observed_paths(evidence, tool_results)
    role_lines = _role_lines(evidence, tool_results, observed_paths, language=language)
    overview_lines = _overview_lines(evidence, tool_results)
    code_summaries = read_file_code_summaries(tool_results)
    code_file_lines = _code_file_lines(code_summaries)
    symbol_lines = _symbol_lines(code_summaries)
    wiring_lines = _wiring_lines(code_summaries)
    probe_file_lines, probe_symbol_lines, probe_wiring_lines = probe_evidence_lines(tool_results, language=language)
    code_file_lines = _dedupe_lines([*probe_file_lines, *code_file_lines])
    symbol_lines = _dedupe_lines([*probe_symbol_lines, *symbol_lines])
    wiring_lines = _dedupe_lines([*probe_wiring_lines, *wiring_lines])
    suggested_reads = _suggested_reads(evidence, tool_results)
    truncated = evidence.source_overview_truncated or any(bool(result.metadata.get("truncated")) for result in tool_results)

    if language == "en":
        lines = [
            "Here is a grounded source-structure summary from the evidence collected so far.",
            "",
            "Checked scope:",
        ]
        lines.extend(f"- {path}" for path in observed_paths[:12])
        if overview_lines:
            lines.extend(["", "Structure summary:", *[f"- {line}" for line in overview_lines]])
        if role_lines:
            lines.extend(["", "Inferred roles:", *[f"- {line}" for line in role_lines]])
        if code_file_lines:
            lines.extend(["", "Key file evidence:", *[f"- {line}" for line in code_file_lines]])
        if symbol_lines:
            lines.extend(["", "Main classes/functions:", *[f"- {line}" for line in symbol_lines]])
        if wiring_lines:
            lines.extend(["", "Dependency/wiring clues:", *[f"- {line}" for line in wiring_lines]])
        if suggested_reads:
            lines.extend(["", "Suggested follow-up files:", *[f"- {path}" for path in suggested_reads[:6]]])
        lines.extend(
            [
                "",
                "Evidence scope:",
                "- This summary separates observed paths and inferred roles; unobserved implementation details are not asserted.",
            ]
        )
        if truncated:
            lines.append("- Some inventory output was truncated, so representative files are the next best evidence for deeper analysis.")
        return "\n".join(lines)

    lines = [
        "지금까지 수집한 근거를 기준으로 소스 구조를 요약합니다.",
        "",
        "확인한 범위:",
    ]
    lines.extend(f"- `{path}`" for path in observed_paths[:12])
    if overview_lines:
        lines.extend(["", "구조 요약:", *[f"- {line}" for line in overview_lines]])
    if role_lines:
        lines.extend(["", "주요 역할:", *[f"- {line}" for line in role_lines]])
    if code_file_lines:
        lines.extend(["", "핵심 파일 근거:", *[f"- {line}" for line in code_file_lines]])
    if symbol_lines:
        lines.extend(["", "주요 클래스/함수:", *[f"- {line}" for line in symbol_lines]])
    if wiring_lines:
        lines.extend(["", "의존성/연결 흐름:", *[f"- {line}" for line in wiring_lines]])
    if suggested_reads:
        lines.extend(["", "추가로 확인하면 좋은 파일:", *[f"- `{path}`" for path in suggested_reads[:6]]])
    lines.extend(
        [
            "",
            "근거 범위:",
            "- 확인한 경로와 추론한 역할을 분리해 정리했습니다. 관찰되지 않은 구현 세부사항은 단정하지 않았습니다.",
        ]
    )
    if truncated:
        lines.append("- 일부 inventory 출력이 잘렸으므로, 더 깊은 분석에는 대표 파일 범위 확인이 필요합니다.")
    return "\n".join(lines)


def has_inspect_summary_evidence(evidence: CompletionEvidence) -> bool:
    return bool(
        evidence.source_overview_paths
        or evidence.source_overview_summaries
        or evidence.search_candidate_paths
        or evidence.inspected_paths
        or evidence.inspect_observation_count
    )


def _observed_paths(evidence: CompletionEvidence, tool_results) -> list[str]:
    paths: list[str] = []
    for path in [
        *evidence.source_overview_paths,
        *evidence.inspected_paths,
        *evidence.search_candidate_paths,
        *evidence.representative_read_paths,
        *evidence.source_representative_candidates,
    ]:
        _append_unique(paths, _clean_path(path))
    for result in tool_results:
        observation = result.metadata.get("observation")
        if isinstance(observation, dict) and observation.get("kind") == "source_probe":
            _append_unique(paths, _clean_path(str(observation.get("target") or result.metadata.get("file_path") or "")))
        for path in result.metadata.get("representative_reads", result.metadata.get("suggested_reads", [])):
            if isinstance(path, str):
                _append_unique(paths, _clean_path(path))
        for entry in result.metadata.get("entries", result.metadata.get("results", [])):
            if not isinstance(entry, dict):
                continue
            _append_unique(paths, _clean_path(str(entry.get("path") or "")))
    return [path for path in paths if path][:40]


def _overview_lines(evidence: CompletionEvidence, tool_results) -> list[str]:
    lines: list[str] = []
    for summary in evidence.source_overview_summaries:
        _append_unique(lines, summary[:500])
    for result in tool_results:
        for summary in result.metadata.get("source_overview_summaries", []):
            if isinstance(summary, str):
                _append_unique(lines, summary[:500])
    return lines[:8]


def _suggested_reads(evidence: CompletionEvidence, tool_results) -> list[str]:
    paths: list[str] = []
    for path in [*evidence.source_representative_candidates, *evidence.search_candidate_paths]:
        _append_unique(paths, _clean_path(path))
    for result in tool_results:
        for key in ("representative_reads", "suggested_reads"):
            for path in result.metadata.get(key, []):
                if isinstance(path, str):
                    _append_unique(paths, _clean_path(path))
    read = {_clean_path(path) for path in [*evidence.inspected_paths, *evidence.representative_read_paths]}
    return [path for path in paths if path and path not in read][:8]


def _role_lines(
    evidence: CompletionEvidence,
    tool_results,
    paths: Sequence[str],
    *,
    language: ResponseLanguage,
) -> list[str]:
    roles: list[str] = []
    seen: set[str] = set()
    observed_scopes = _observed_role_scopes(evidence, tool_results)
    for role in _metadata_roles(evidence, tool_results):
        path = _clean_path(str(role.get("path") or ""))
        label = _localized_role(str(role.get("role") or "").strip(), language=language)
        if not path or not label:
            continue
        key = f"{path}:{label}"
        if key in seen:
            continue
        seen.add(key)
        evidence_label = _role_evidence_label(path, observed_scopes, language=language)
        roles.append(f"`{path}`: {label} ({evidence_label})")
    if roles:
        return roles[:12]

    fallback_label = "관찰된 소스 영역" if language == "ko" else "observed source area"
    for path in paths:
        scope = _role_scope(path)
        if not scope or scope in seen:
            continue
        seen.add(scope)
        roles.append(f"`{scope}`: {fallback_label}")
    return roles[:12]


def _metadata_roles(evidence: CompletionEvidence, tool_results) -> list[dict[str, object]]:
    roles: list[dict[str, object]] = []
    for role in evidence.source_package_roles:
        if isinstance(role, dict):
            roles.append(role)
    for result in tool_results:
        for role in result.metadata.get("package_roles", []):
            if isinstance(role, dict):
                roles.append(role)
    return roles


def _code_file_lines(summaries: Sequence[CodeStructureSummary]) -> list[str]:
    lines: list[str] = []
    for summary in summaries[:6]:
        clues: list[str] = []
        if summary.classes:
            clues.append("classes " + ", ".join(f"`{item}`" for item in summary.classes[:3]))
        if summary.functions:
            clues.append("functions " + ", ".join(f"`{item}`" for item in summary.functions[:4]))
        if summary.entrypoints:
            clues.append("entrypoints " + ", ".join(f"`{item}`" for item in summary.entrypoints[:2]))
        if clues:
            lines.append(f"`{summary.path}`: " + "; ".join(clues))
    return lines[:8]


def _symbol_lines(summaries: Sequence[CodeStructureSummary]) -> list[str]:
    lines: list[str] = []
    for summary in summaries[:6]:
        symbols = [*summary.classes[:4], *summary.functions[:6]]
        if symbols:
            lines.append(f"`{summary.path}`: " + ", ".join(f"`{symbol}`" for symbol in symbols[:8]))
    return lines[:8]


def _wiring_lines(summaries: Sequence[CodeStructureSummary]) -> list[str]:
    lines: list[str] = []
    for summary in summaries[:6]:
        clues = [*summary.imports[:5], *summary.entrypoints[:2]]
        if clues:
            lines.append(f"`{summary.path}`: " + ", ".join(f"`{clue}`" for clue in clues[:6]))
    return lines[:8]


def _role_scope(path: str) -> str:
    parts = Path(path).parts
    if not parts:
        return ""
    if "." in parts[-1] and len(parts) > 1:
        return "/".join(parts[:-1])
    return "/".join(parts)


def _observed_role_scopes(evidence: CompletionEvidence, tool_results) -> set[str]:
    scopes: set[str] = set()
    for path in [*evidence.inspected_paths, *evidence.representative_read_paths]:
        scope = _role_scope(_clean_path(path))
        if scope:
            scopes.add(scope)
    for result in tool_results:
        observation = result.metadata.get("observation")
        if isinstance(observation, dict) and observation.get("kind") == "source_probe":
            scope = _role_scope(_clean_path(str(observation.get("target") or "")))
            if scope:
                scopes.add(scope)
        path = _clean_path(str(result.metadata.get("file_path") or ""))
        scope = _role_scope(path)
        if scope:
            scopes.add(scope)
    return scopes


def _role_evidence_label(path: str, observed_scopes: set[str], *, language: ResponseLanguage) -> str:
    observed = any(_same_or_nested_scope(path, scope) for scope in observed_scopes)
    if language == "en":
        return "observed via probe/read" if observed else "overview-based inference"
    return "probe/read 관찰 근거" if observed else "overview 기반 추론"


def _same_or_nested_scope(path: str, scope: str) -> bool:
    return bool(path and scope and (path == scope or path.startswith(f"{scope}/") or scope.startswith(f"{path}/")))


def _append_unique(paths: list[str], path: str) -> None:
    if path and path not in paths:
        paths.append(path)


def _clean_path(path: str) -> str:
    value = path.strip().strip("`")
    if not value:
        return ""
    if value.startswith("/workspace/"):
        return value[len("/workspace/") :]
    parts = Path(value).parts
    for anchor in ("src", "tests", "test"):
        if anchor in parts:
            return "/".join(parts[parts.index(anchor) :])
    if Path(value).is_absolute() and len(parts) > 3:
        return "/".join(parts[-3:])
    return value


def _localized_role(role: str, *, language: ResponseLanguage) -> str:
    if language != "ko":
        return role
    translations = {
        "entrypoint or command/runtime wiring": "명령 실행 진입점 또는 runtime 연결 영역",
        "test or verification support": "테스트와 검증 지원 영역",
        "public code surface coordinating imported dependencies": "공개 클래스/함수와 import 의존성을 조합하는 코드 영역",
        "source module defining public classes or functions": "공개 클래스 또는 함수를 정의하는 source module",
        "integration or dependency wiring module": "외부/내부 의존성을 연결하는 integration module",
        "source package group": "여러 source file로 구성된 package 영역",
        "source file group": "단일 source file 또는 작은 source 영역",
    }
    return translations.get(role, role)


def _dedupe_lines(lines: list[str]) -> list[str]:
    seen: list[str] = []
    for line in lines:
        _append_unique(seen, line)
    return seen
