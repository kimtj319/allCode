"""Deterministic fallback for source-analysis answers that fail grounding."""

from __future__ import annotations

import re
from pathlib import Path

from allCode.agent.language import ResponseLanguage
from allCode.agent.prompt_builder_helpers import tool_results_from_messages
from allCode.agent.source_answer_requirements import important_file_lines, source_answer_requirements
from allCode.agent.source_answer_synthesis import build_source_analysis_brief
from allCode.core.models import Message
from allCode.core.result import CompletionEvidence


def safe_source_analysis_answer(
    *,
    messages: list[Message],
    evidence: CompletionEvidence,
    user_prompt: str,
    language: ResponseLanguage,
) -> str:
    brief = build_source_analysis_brief(
        tool_results_from_messages(messages),
        evidence=evidence,
        user_prompt=user_prompt,
    )
    if language == "en":
        return _render_en(brief, user_prompt=user_prompt)
    return _render_ko(brief, user_prompt=user_prompt)


def _render_ko(brief, *, user_prompt: str) -> str:
    lines = [
        "## 소스 분석 요약",
        "",
        "관찰된 도구 근거만 기준으로 소스 분석을 정리합니다.",
    ]
    if brief.observed_paths:
        lines.extend(["", "### 관찰한 사실", "", "확인한 범위:"])
        lines.extend(f"- `{path}`" for path in brief.observed_paths[:10])
    if brief.representative_files:
        if "### 관찰한 사실" not in lines:
            lines.extend(["", "### 관찰한 사실"])
        lines.extend(["", "대표 파일 근거:"])
        for file in brief.representative_files[:8]:
            parts = []
            if file.symbols:
                parts.append("심볼 " + ", ".join(f"`{symbol}`" for symbol in file.symbols[:5]))
            if file.ranges:
                parts.append("관찰 범위 " + ", ".join(f"`{file.path}:{label}`" for label in file.ranges[:3]))
            if file.wiring:
                parts.append("연결 단서 " + ", ".join(file.wiring[:3]))
            if file.wide_symbols:
                parts.append("넓은 심볼 " + ", ".join(f"`{symbol}`" for symbol in file.wide_symbols[:3]))
            lines.append(f"- `{file.path}`: " + ("; ".join(parts) if parts else file.evidence or "관찰됨"))
    important_files = important_file_lines(brief, prompt=user_prompt, language="ko")
    if important_files:
        lines.extend(["", f"### 요청 기준 중요 파일 {len(important_files)}개", ""])
        lines.extend(f"- {item}" for item in important_files)
    body_items = _body_evidence_items(brief, language="ko")
    if body_items and _body_evidence_requested(user_prompt):
        lines.extend(["", "### 핵심 본문 근거", ""])
        lines.extend(f"- {item}" for item in body_items[:5])
    if brief.inferred_flows:
        lines.extend(["", "### 핵심 실행 흐름", ""])
        flow_steps = _observed_flow_analysis_ko(brief)
        if flow_steps:
            lines.extend(flow_steps)
        lines.extend(f"- {flow}" for flow in brief.inferred_flows[:8])
    if brief.package_roles or brief.entrypoints:
        lines.extend(["", "### 추론한 역할", ""])
        for role in brief.package_roles[:12]:
            lines.append(f"- `{role.path}`: {role.role}")
        if brief.entrypoints:
            lines.append("- 진입점 단서: " + ", ".join(f"`{item}`" for item in brief.entrypoints[:4]))
    bottlenecks = _requested_bottleneck_items(user_prompt, brief, language="ko")
    if bottlenecks:
        lines.extend(["", f"### 관찰 근거 기준 후보 병목 {len(bottlenecks)}개", ""])
        lines.extend(f"- {item}" for item in bottlenecks)
    improvements = _requested_improvement_items(user_prompt, brief, language="ko")
    if improvements:
        lines.extend(["", f"### 관찰 근거 기준 개선점 {len(improvements)}개", ""])
        lines.extend(f"- {item}" for item in improvements)
    gap_notes = _requested_gap_notes(user_prompt, important_files, bottlenecks, improvements, language="ko")
    if brief.unobserved_scopes or brief.confidence_notes or gap_notes:
        lines.extend(["", "### 남은 한계", ""])
        lines.extend(f"- `{scope}`는 직접 관찰하지 못했습니다." for scope in brief.unobserved_scopes[:6])
        lines.extend(f"- {note}" for note in brief.confidence_notes[:4])
        lines.extend(f"- {note}" for note in gap_notes)
    return "\n".join(lines)


def _render_en(brief, *, user_prompt: str) -> str:
    lines = [
        "## Source Analysis Summary",
        "",
        "This summary is based only on observed tool evidence.",
    ]
    if brief.observed_paths:
        lines.extend(["", "### Observed Facts", "", "Checked scope:"])
        lines.extend(f"- `{path}`" for path in brief.observed_paths[:10])
    if brief.representative_files:
        if "### Observed Facts" not in lines:
            lines.extend(["", "### Observed Facts"])
        lines.extend(["", "Representative file evidence:"])
        for file in brief.representative_files[:8]:
            parts = []
            if file.symbols:
                parts.append("symbols " + ", ".join(f"`{symbol}`" for symbol in file.symbols[:5]))
            if file.ranges:
                parts.append("observed ranges " + ", ".join(f"`{file.path}:{label}`" for label in file.ranges[:3]))
            if file.wiring:
                parts.append("wiring " + ", ".join(file.wiring[:3]))
            if file.wide_symbols:
                parts.append("wide symbols " + ", ".join(f"`{symbol}`" for symbol in file.wide_symbols[:3]))
            lines.append(f"- `{file.path}`: " + ("; ".join(parts) if parts else file.evidence or "observed"))
    important_files = important_file_lines(brief, prompt=user_prompt, language="en")
    if important_files:
        lines.extend(["", f"### Requested Important Files ({len(important_files)})", ""])
        lines.extend(f"- {item}" for item in important_files)
    body_items = _body_evidence_items(brief, language="en")
    if body_items and _body_evidence_requested(user_prompt):
        lines.extend(["", "### Key Body Evidence", ""])
        lines.extend(f"- {item}" for item in body_items[:5])
    if brief.inferred_flows:
        lines.extend(["", "### Key Execution Flow", ""])
        flow_steps = _observed_flow_analysis_en(brief)
        if flow_steps:
            lines.extend(flow_steps)
        lines.extend(f"- {flow}" for flow in brief.inferred_flows[:8])
    if brief.package_roles or brief.entrypoints:
        lines.extend(["", "### Inferred Roles", ""])
        for role in brief.package_roles[:12]:
            lines.append(f"- `{role.path}`: {role.role}")
        if brief.entrypoints:
            lines.append("- Entrypoint clues: " + ", ".join(f"`{item}`" for item in brief.entrypoints[:4]))
    bottlenecks = _requested_bottleneck_items(user_prompt, brief, language="en")
    if bottlenecks:
        lines.extend(["", f"### Candidate Bottlenecks From Observed Evidence ({len(bottlenecks)})", ""])
        lines.extend(f"- {item}" for item in bottlenecks)
    improvements = _requested_improvement_items(user_prompt, brief, language="en")
    if improvements:
        lines.extend(["", f"### Improvements From Observed Evidence ({len(improvements)})", ""])
        lines.extend(f"- {item}" for item in improvements)
    gap_notes = _requested_gap_notes(user_prompt, important_files, bottlenecks, improvements, language="en")
    if brief.unobserved_scopes or brief.confidence_notes or gap_notes:
        lines.extend(["", "### Remaining Limitations", ""])
        lines.extend(f"- `{scope}` was not directly observed." for scope in brief.unobserved_scopes[:6])
        lines.extend(f"- {note}" for note in brief.confidence_notes[:4])
        lines.extend(f"- {note}" for note in gap_notes)
    return "\n".join(lines)


def _requested_bottleneck_items(prompt: str, brief, *, language: ResponseLanguage) -> list[str]:
    count = _requested_bottleneck_count(prompt)
    if count <= 0:
        return []
    candidates = _bottleneck_candidates(brief, language=language)
    return candidates[:count]


def _requested_bottleneck_count(prompt: str) -> int:
    return _requested_count_for_markers(
        prompt,
        markers=("병목", "리스크", "위험", "bottleneck", "bottlenecks", "risk", "risks"),
        default_markers=("핵심병목", "주요병목", "keybottleneck", "mainbottleneck"),
    )


def _requested_improvement_count(prompt: str) -> int:
    return _requested_count_for_markers(
        prompt,
        markers=("개선점", "개선", "보강점", "보완점", "improvement", "improvements", "recommendation", "recommendations"),
        default_markers=("주요개선점", "핵심개선점", "keyimprovement", "mainimprovement"),
    )


def _requested_count_for_markers(prompt: str, *, markers: tuple[str, ...], default_markers: tuple[str, ...]) -> int:
    text = str(prompt or "")
    lowered = text.lower()
    compact = re.sub(r"\s+", "", lowered)
    if not any(marker in compact for marker in markers):
        return 0
    marker_pattern = "|".join(re.escape(marker) for marker in markers)
    patterns = (
        rf"(?:{marker_pattern}).{{0,40}}?(?:각각|each)?\s*(\d+)\s*(?:개|가지|씩|items?|points?)",
        rf"(\d+)\s*(?:개|가지|items?|points?).{{0,40}}?(?:{marker_pattern})",
        rf"(?:{marker_pattern})\D{{0,40}}?(\d+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return min(8, max(1, int(match.group(1))))
    each_match = re.search(r"(?:각각|each)\s*(\d+)\s*(?:개|가지|씩|items?|points?)", text, flags=re.IGNORECASE)
    if each_match:
        return min(8, max(1, int(each_match.group(1))))
    return 3 if any(marker in compact for marker in default_markers) else 0


def _bottleneck_candidates(brief, *, language: ResponseLanguage) -> list[str]:
    items: list[str] = []
    if brief.confidence_notes:
        note = brief.confidence_notes[0]
        items.append(
            f"근거 범위 제한: {note}"
            if language == "ko"
            else f"Evidence coverage limit: {note}"
        )
    if brief.unobserved_scopes:
        scopes = ", ".join(f"`{scope}`" for scope in brief.unobserved_scopes[:3])
        items.append(
            f"미관찰 범위가 남아 흐름 단정이 제한됩니다: {scopes}"
            if language == "ko"
            else f"Unobserved scopes limit flow claims: {scopes}"
        )
    wide_symbols = [
        symbol
        for file in brief.representative_files
        for symbol in file.wide_symbols[:2]
    ]
    if wide_symbols:
        symbols = ", ".join(f"`{symbol}`" for symbol in wide_symbols[:3])
        items.append(
            f"큰 심볼은 헤더/시그니처 위주로만 관찰돼 내부 동작 병목을 더 읽어야 합니다: {symbols}"
            if language == "ko"
            else f"Large symbols were observed by header/signature only, so inner behavior needs deeper inspection: {symbols}"
        )
    if not brief.cross_module_edges and brief.representative_files:
        items.append(
            "대표 파일 근거는 있으나 관찰된 모듈 간 edge가 부족해 실제 실행 흐름 설명 밀도가 낮아질 수 있습니다."
            if language == "ko"
            else "Representative files were observed, but cross-module edges are sparse, which can reduce flow explanation density."
        )
    if len(brief.representative_files) < 3 and brief.observed_paths:
        items.append(
            "대표 파일 관찰 수가 적어 넓은 패키지 분석에서는 일부 역할이 누락될 수 있습니다."
            if language == "ko"
            else "Few representative files were observed, so broad package analysis may miss some roles."
        )
    if not items:
        items.append(
            "관찰된 근거만으로는 명확한 병목을 단정하기 어렵습니다. 추가 대표 파일 읽기가 필요합니다."
            if language == "ko"
            else "Observed evidence does not support a clear bottleneck claim; additional representative reads are needed."
        )
    return _dedupe(items)


def _requested_improvement_items(prompt: str, brief, *, language: ResponseLanguage) -> list[str]:
    count = _requested_improvement_count(prompt)
    if count <= 0:
        return []
    candidates = _improvement_candidates(brief, language=language)
    return candidates[:count]


def _improvement_candidates(brief, *, language: ResponseLanguage) -> list[str]:
    items: list[str] = []
    body_items = _body_evidence_items(brief, language=language)
    if body_items:
        items.append(
            "본문 샘플 anchor가 있는 대표 심볼부터 추가 range를 좁혀 읽어 추론을 관찰 사실로 승격해야 합니다."
            if language == "ko"
            else "Follow body-sample anchors with tighter range reads so inferred behavior can be promoted to observed fact."
        )
    if brief.unobserved_scopes:
        scopes = ", ".join(f"`{scope}`" for scope in brief.unobserved_scopes[:3])
        items.append(
            f"미관찰 대표 후보를 우선 probe/read 대상으로 이어서 분석 범위를 넓혀야 합니다: {scopes}"
            if language == "ko"
            else f"Probe/read the remaining representative candidates first to widen coverage: {scopes}"
        )
    if brief.cross_module_edges:
        items.append(
            "관찰된 import/reference edge를 실행 순서별로 재정렬해 라우팅-도구-최종 답변 흐름을 더 명확히 연결해야 합니다."
            if language == "ko"
            else "Order observed import/reference edges by execution stage to clarify the routing-tool-final answer flow."
        )
    if brief.confidence_notes:
        items.append(
            "coverage/truncation 한계를 최종 답변의 confidence로 드러내고, 부족한 대표 파일 수를 다음 탐색 예산에 반영해야 합니다."
            if language == "ko"
            else "Expose coverage/truncation limits as confidence notes and feed missing representative counts into the next inspection budget."
        )
    if not items:
        items.append(
            "현재 근거로는 구체 개선점을 단정하기 어렵기 때문에 대표 파일 body range를 추가 수집해야 합니다."
            if language == "ko"
            else "Current evidence is too thin for concrete improvements; collect additional representative body ranges."
        )
    return _dedupe(items)


def _requested_gap_notes(
    prompt: str,
    important_files: list[str],
    bottlenecks: list[str],
    improvements: list[str],
    *,
    language: ResponseLanguage,
) -> list[str]:
    requirements = source_answer_requirements(prompt)
    notes: list[str] = []
    if requirements.important_file_count and len(important_files) < requirements.important_file_count:
        notes.append(
            f"요청된 중요 파일 {requirements.important_file_count}개 중 관찰 근거로 설명 가능한 항목은 {len(important_files)}개입니다."
            if language == "ko"
            else f"The prompt requested {requirements.important_file_count} important files; observed evidence supports {len(important_files)}."
        )
    if requirements.risk_count and len(bottlenecks) < requirements.risk_count:
        notes.append(
            f"요청된 리스크/병목 {requirements.risk_count}개 중 관찰 근거로 분리 가능한 항목은 {len(bottlenecks)}개입니다."
            if language == "ko"
            else f"The prompt requested {requirements.risk_count} risks/bottlenecks; observed evidence supports {len(bottlenecks)}."
        )
    if requirements.improvement_count and len(improvements) < requirements.improvement_count:
        notes.append(
            f"요청된 개선점 {requirements.improvement_count}개 중 관찰 근거로 제안 가능한 항목은 {len(improvements)}개입니다."
            if language == "ko"
            else f"The prompt requested {requirements.improvement_count} improvements; observed evidence supports {len(improvements)}."
        )
    return notes


def _body_evidence_requested(prompt: str) -> bool:
    compact = re.sub(r"\s+", "", str(prompt or "").lower())
    return any(marker in compact for marker in ("본문", "함수본문", "메서드본문", "body", "functionbody", "methodbody"))


def _body_evidence_items(brief, *, language: ResponseLanguage) -> list[str]:
    items: list[str] = []
    for file in brief.representative_files:
        body_ranges = [label for label in file.ranges if "body_sample" in label]
        if not body_ranges:
            continue
        symbols = ", ".join(f"`{symbol}`" for symbol in file.symbols[:3]) or "observed symbol"
        anchors = ", ".join(f"`{file.path}:{label}`" for label in body_ranges[:3])
        if language == "ko":
            items.append(f"`{file.path}`의 {symbols}는 본문 샘플 anchor {anchors}로 제한 관찰되었습니다.")
        else:
            items.append(f"`{file.path}` symbols {symbols} were observed through bounded body-sample anchors {anchors}.")
    return _dedupe(items)


def _dedupe(items: list[str]) -> list[str]:
    seen: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.append(item)
    return seen


def _observed_flow_analysis_ko(brief) -> list[str]:
    steps = _observed_flow_steps(brief.representative_files)
    lines = [
        f"- `{path}`: 파일명/심볼 토큰과 관찰된 anchor 기준 `{ko_label}` 단계 후보입니다."
        for path, ko_label, _ in steps[:6]
    ]
    if brief.cross_module_edges:
        edge = brief.cross_module_edges[0]
        lines.append(f"- 관찰된 연결: `{edge.source}` --{edge.kind}--> `{edge.target}`.")
    return lines


def _observed_flow_analysis_en(brief) -> list[str]:
    steps = _observed_flow_steps(brief.representative_files)
    lines = [
        f"- `{path}`: filename/symbol tokens plus observed anchors mark a candidate `{en_label}` stage."
        for path, _, en_label in steps[:6]
    ]
    if brief.cross_module_edges:
        edge = brief.cross_module_edges[0]
        lines.append(f"- Observed edge: `{edge.source}` --{edge.kind}--> `{edge.target}`.")
    return lines


def _observed_flow_steps(files) -> list[tuple[str, str, str]]:
    stages: tuple[tuple[str, str, tuple[str, ...]], ...] = (
        ("실행/반복 제어", "runtime or iteration control", ("loop", "runner", "round")),
        ("소스 탐색 또는 근거 수집", "source exploration or evidence collection", ("source", "probe", "overview")),
        ("검사 또는 처리 핸들러", "inspection or handler processing", ("grounding", "inspect", "tool", "handler")),
        ("출력 또는 응답 구성", "output or response composition", ("answer", "synthesis", "brief", "rendering", "final")),
        ("검증 또는 복구 처리", "validation or recovery handling", ("guard", "fallback", "response", "validation", "repair")),
    )
    seen: set[str] = set()
    selected: list[tuple[str, str, str]] = []
    for file in files:
        path = str(getattr(file, "path", "") or "")
        tokens = _path_tokens(path)
        for ko_label, en_label, markers in stages:
            if en_label in seen or not tokens.intersection(markers):
                continue
            selected.append((path, ko_label, en_label))
            seen.add(en_label)
            break
    return selected


def _path_tokens(path: str) -> set[str]:
    tokens: set[str] = set()
    for part in Path(path).with_suffix("").parts:
        tokens.update(token for token in part.lower().replace("-", "_").split("_") if token)
    return tokens
