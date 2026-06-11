"""Rendering helpers for source-analysis evidence briefs."""

from __future__ import annotations

import re
from collections.abc import Sequence

from allCode.agent.language import ResponseLanguage
from allCode.agent.source_answer_requirements import source_output_obligation_lines
from allCode.agent.source_analysis_types import RepresentativeFile, SourceAnalysisBrief
from allCode.agent.source_responsibility_graph import (
    render_compact_responsibility_matrix,
    render_responsibility_matrix,
)


def source_analysis_final_answer_instruction(language: ResponseLanguage) -> str:
    if language == "en":
        return (
            "Write the final source-analysis answer now. Use only observed tool evidence and supplied context. "
            "Do not mutate files. Do not output raw tool JSON. Structure the answer with: checked scope, "
            "package/directory roles, key execution flow, module interactions, representative file evidence, "
            "and remaining limitations. Separate observed facts from inferred roles. "
            "For broad source-tree role requests, summarize package/directory roles before representative files; "
            "do not reduce the answer to only the probed representative files when package-role evidence is supplied. "
            "Do not claim a package or directory was unobserved when it appears in Package/directory roles. "
            "When representative file evidence includes `path:Lx-Ly(reason:symbol)`, cite those file/line anchors for concrete claims instead of using "
            "generic references, but attach an anchor only to the exact reason or symbol shown inside that anchor label; "
            "do not reuse a class/header/import anchor as evidence for a different method or behavior. "
            "If the user requested function or method body evidence, prioritize observed `symbol_body_sample` and "
            "`child_body_sample` anchors; if none are supplied, state that limitation instead of inventing body-level claims. "
            "If the user requested a specific length, sentence count, bullet count, or output "
            "format, that user format constraint is higher priority than this section template: do not add headings "
            "or extra sections when they would violate the requested count; compress observed facts, inferred roles, "
            "and limitations into exactly the requested form."
        )
    return (
        "이제 최종 소스 분석 답변을 작성하십시오. 관찰된 도구 근거와 제공된 컨텍스트만 사용하고 파일은 수정하지 마십시오. "
        "raw tool JSON을 출력하지 마십시오. 답변에는 확인한 범위, 디렉터리/패키지별 역할, 핵심 실행 흐름, "
        "모듈 간 연결, 대표 파일 근거, 남은 한계를 포함하십시오. 관찰한 사실과 추론한 역할을 분리하십시오. "
        "넓은 소스 트리 역할 요약 요청에서는 대표 파일 설명보다 디렉터리/패키지별 역할 요약을 먼저 작성하십시오. "
        "패키지 역할 근거가 제공되었는데도 답변을 대표 파일 몇 개로만 축소하지 마십시오. "
        "`디렉터리/패키지별 역할`에 등장한 패키지나 디렉터리를 관찰하지 못했다고 말하지 마십시오. "
        "대표 파일 근거에 `path:Lx-Ly(reason:symbol)` 형식의 위치가 있으면 구체 주장에는 그 파일/라인 근거를 우선 인용하되, "
        "해당 앵커의 괄호 안 reason/symbol과 정확히 맞는 주장에만 붙이십시오. 클래스 헤더/가져오기 앵커를 다른 메서드나 동작의 근거로 재사용하지 마십시오. "
        "사용자가 함수나 메서드 본문 근거를 요구했다면 관찰된 `symbol_body_sample` 및 `child_body_sample` 앵커를 우선 사용하고, "
        "그런 앵커가 없으면 본문 수준 주장을 만들지 말고 한계로 명시하십시오. "
        "단, 사용자가 문장 수, 분량, bullet 수, 출력 형식을 지정했다면 그 사용자 형식 제약이 이 섹션 템플릿보다 우선입니다. "
        "요청된 개수를 깨는 제목이나 추가 섹션을 만들지 말고, 관찰 사실/추론 역할/한계를 요청된 형식 안에 정확히 압축하십시오."
    )


def render_source_analysis_brief(brief: SourceAnalysisBrief, *, language: ResponseLanguage) -> str:
    if language == "en":
        lines = ["Source analysis evidence brief:"]
        outline = _answer_outline_lines(brief, language=language)
        if outline:
            lines.extend(["", "Answer synthesis outline:", *outline])
        if brief.observed_paths:
            lines.extend(["", "Checked scope:", *[f"- `{path}`" for path in brief.observed_paths[:12]]])
        if brief.package_roles:
            lines.extend(["", "Package/directory roles:"])
            lines.extend(f"- `{role.path}`: {role.role} ({role.evidence or 'observed/inferred evidence'})" for role in brief.package_roles[:10])
        if brief.inferred_flows:
            lines.extend(["", "Key execution flow:", *[f"- {flow}" for flow in brief.inferred_flows[:8]]])
        if brief.cross_module_edges:
            lines.extend(["", "Module interactions:"])
            lines.extend(f"- `{edge.source}` --{edge.kind}--> `{edge.target}`" for edge in brief.cross_module_edges[:10])
        if brief.representative_files:
            lines.extend(["", "Representative file evidence:"])
            lines.extend(_representative_file_lines(brief.representative_files[:8]))
        responsibility_lines = render_responsibility_matrix(brief.responsibility_graph, language=language)
        if responsibility_lines:
            lines.extend(["", *responsibility_lines])
        if brief.unobserved_scopes or brief.confidence_notes:
            lines.append("")
            lines.append("Limitations:")
            lines.extend(f"- `{target}` was not observed." for target in brief.unobserved_scopes[:8])
            lines.extend(f"- {note}" for note in brief.confidence_notes[:6])
        return "\n".join(lines)

    lines = ["소스 분석 근거 brief:"]
    outline = _answer_outline_lines(brief, language=language)
    if outline:
        lines.extend(["", "답변 합성 outline:", *outline])
    if brief.observed_paths:
        lines.extend(["", "확인한 범위:", *[f"- `{path}`" for path in brief.observed_paths[:12]]])
    if brief.package_roles:
        lines.extend(["", "디렉터리/패키지별 역할:"])
        lines.extend(f"- `{role.path}`: {role.role} ({role.evidence or '관찰/추론 근거'})" for role in brief.package_roles[:10])
    if brief.inferred_flows:
        lines.extend(["", "핵심 실행 흐름:", *[f"- {flow}" for flow in brief.inferred_flows[:8]]])
    if brief.cross_module_edges:
        lines.extend(["", "모듈 간 연결:"])
        lines.extend(f"- `{edge.source}` --{edge.kind}--> `{edge.target}`" for edge in brief.cross_module_edges[:10])
    if brief.representative_files:
        lines.extend(["", "대표 파일 근거:"])
        lines.extend(_representative_file_lines(brief.representative_files[:8]))
    responsibility_lines = render_responsibility_matrix(brief.responsibility_graph, language=language)
    if responsibility_lines:
        lines.extend(["", *responsibility_lines])
    if brief.unobserved_scopes or brief.confidence_notes:
        lines.append("")
        lines.append("남은 한계:")
        lines.extend(f"- `{target}`는 직접 관찰하지 못했습니다." for target in brief.unobserved_scopes[:8])
        lines.extend(f"- {note}" for note in brief.confidence_notes[:6])
    return "\n".join(lines)


def render_compact_source_analysis_brief(brief: SourceAnalysisBrief, *, language: ResponseLanguage) -> str:
    """Render evidence without section scaffolding for strict user output formats."""

    observed = ", ".join(f"`{path}`" for path in brief.observed_paths[:6]) or "none"
    roles = "; ".join(f"`{role.path}`={role.role}" for role in brief.package_roles[:5]) or "none"
    representatives = "; ".join(_compact_representative_label(file) for file in brief.representative_files[:5]) or "none"
    responsibilities = render_compact_responsibility_matrix(brief.responsibility_graph, language=language) or "none"
    limitations = ", ".join(f"`{item}`" for item in brief.unobserved_scopes[:5]) or "none"
    if language == "en":
        return (
            "Compact source evidence: "
            f"observed={observed}; roles={roles}; representative_files={representatives}; {responsibilities}; limitations={limitations}. "
            "Answer outline: checked scope -> observed roles -> representative evidence -> limitations. "
            "Use this as evidence, but obey the user's requested sentence/bullet/format limit exactly."
        )
    return (
        "압축 소스 근거: "
        f"관찰범위={observed}; 역할={roles}; 대표파일={representatives}; {responsibilities}; 한계={limitations}. "
        "답변 outline: 확인 범위 -> 관찰 역할 -> 대표 근거 -> 한계. "
        "이 근거를 사용하되 사용자가 요청한 문장 수/bullet/형식 제한을 정확히 지키십시오."
    )


def source_answer_needs_compact_brief(prompt: str) -> bool:
    text = str(prompt or "")
    compact = re.sub(r"\s+", "", text.lower())
    lowered = text.lower()
    if re.search(r"\d+\s*(sentence|sentences|paragraph|paragraphs|bullet|bullets|line|lines)", lowered):
        return True
    korean_patterns = (
        r"\d+\s*문장",
        r"\d+\s*문단",
        r"\d+\s*줄",
        r"한\s*문장",
        r"짧게",
        r"간단히",
    )
    return any(re.search(pattern, text) for pattern in korean_patterns) or any(
        marker in compact for marker in ("bullet로", "불릿으로", "목록으로")
    )


def _representative_file_lines(files: Sequence[RepresentativeFile]) -> list[str]:
    lines: list[str] = []
    for file in files:
        details: list[str] = [file.evidence] if file.evidence else []
        if file.ranges:
            body_ranges = [label for label in file.ranges if "body_sample" in label]
            if body_ranges:
                details.append(
                    "body anchors "
                    + ", ".join(f"`{file.path}:{label}`" for label in body_ranges[:3])
                )
            details.append(
                "anchors(each supports only its own reason/symbol) "
                + ", ".join(f"`{file.path}:{label}`" for label in file.ranges[:4])
            )
        if file.symbols:
            details.append("symbols " + ", ".join(f"`{symbol}`" for symbol in file.symbols[:5]))
        if file.wiring:
            details.append("wiring " + ", ".join(file.wiring[:4]))
        if file.wide_symbols:
            details.append("wide symbols " + ", ".join(f"`{symbol}`" for symbol in file.wide_symbols[:4]))
        lines.append(f"- `{file.path}`: " + "; ".join(details))
    return lines


def _answer_outline_lines(brief: SourceAnalysisBrief, *, language: ResponseLanguage) -> list[str]:
    if not any((brief.observed_paths, brief.package_roles, brief.representative_files, brief.cross_module_edges, brief.unobserved_scopes)):
        return []
    if language == "en":
        lines = [
            "- Start with the checked scope and state that claims are based on observed tool evidence.",
            "- Explain package or directory roles only from `Package/directory roles` and representative file evidence.",
            "- For broad source-tree role requests, include package/directory roles before representative file details.",
            "- Describe execution or data flow from `Module interactions`, `Key execution flow`, and representative anchors.",
            "- Use `Function responsibility matrix` to connect symbols, body anchors, edges, and limits into model-authored responsibility synthesis.",
            "- End with unobserved scopes or confidence limits instead of filling gaps with guesses.",
        ]
    else:
        lines = [
            "- 확인한 범위와 관찰된 도구 근거 기준임을 먼저 밝히십시오.",
            "- 디렉터리/패키지 역할은 `디렉터리/패키지별 역할`과 대표 파일 근거에서만 설명하십시오.",
            "- 넓은 소스 트리 역할 요청에서는 대표 파일 세부 설명보다 디렉터리/패키지별 역할을 먼저 포함하십시오.",
            "- 실행/데이터 흐름은 `모듈 간 연결`, `핵심 실행 흐름`, 대표 파일 anchor를 기준으로 설명하십시오.",
            "- `함수/모듈 책임 매트릭스`로 symbol, 본문 anchor, edge, 한계를 연결해 직접 책임/흐름을 합성하십시오.",
            "- 직접 관찰하지 못한 범위나 확신 한계를 마지막에 분리하고 추측으로 채우지 마십시오.",
        ]
    if brief.representative_files:
        first_files = ", ".join(f"`{file.path}`" for file in brief.representative_files[:4])
        lines.append(
            f"- Representative evidence priority: {first_files}."
            if language == "en"
            else f"- 대표 근거 우선순위: {first_files}."
        )
    obligation_lines = source_output_obligation_lines(brief.requested_scope, language=language)
    if obligation_lines:
        lines.append("- User-requested output obligations:" if language == "en" else "- 사용자 요청 출력 의무:")
        lines.extend(obligation_lines)
    return lines


def _compact_representative_label(file: RepresentativeFile) -> str:
    details: list[str] = []
    if file.ranges:
        body_ranges = [label for label in file.ranges if "body_sample" in label]
        if body_ranges:
            details.append("body anchors " + ", ".join(f"{file.path}:{label}" for label in body_ranges[:2]))
        details.append("anchors " + ", ".join(f"{file.path}:{label}" for label in file.ranges[:2]))
    if file.symbols:
        details.append("symbols " + ", ".join(file.symbols[:3]))
    if file.wiring:
        details.append("wiring " + ", ".join(file.wiring[:2]))
    if file.wide_symbols:
        details.append("wide " + ", ".join(file.wide_symbols[:2]))
    suffix = f" ({'; '.join(details)})" if details else ""
    return f"`{file.path}`{suffix}"
