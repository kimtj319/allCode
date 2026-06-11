"""Grounding guard for source-analysis final answers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from allCode.agent.language import ResponseLanguage
from allCode.agent.prompt_builder_helpers import tool_results_from_messages
from allCode.agent.router import RoutingDecision
from allCode.agent.source_answer_retry_context import safe_source_anchor_candidates
from allCode.agent.source_package_role_guard import (
    missing_priority_package_roles,
    package_role_retry_candidates,
)
from allCode.core.models import Message

ANCHOR_PATTERN = re.compile(
    r"`?(?P<path>(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.[A-Za-z0-9_]+)"
    r":L(?P<start>\d+)(?:-L?(?P<end>\d+))?"
    r"(?:\((?P<label>[^)`]+)\))?`?"
)
PATH_PATTERN = re.compile(r"`?(?P<path>(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.[A-Za-z0-9_]+)`?")
DOTTED_SYMBOL_PATTERN = re.compile(r"(?<![A-Za-z0-9_.])(?P<symbol>[A-Z][A-Za-z0-9_]+(?:\.[A-Za-z_][A-Za-z0-9_]+)+)(?![A-Za-z0-9_.])")
CLAIM_MARKERS = (
    "정의",
    "구현",
    "등록",
    "호출",
    "실행",
    "포함",
    "담당",
    "생성",
    "전달",
    "defined",
    "implements",
    "register",
    "calls",
    "executes",
    "contains",
    "creates",
    "passes",
)
RAW_TOOL_ACTION_MARKERS = (
    '"action"',
    '"parameters"',
    '"tool_call"',
    '"arguments"',
    "```json",
)
LIMITATION_MARKERS = (
    "추론",
    "한계",
    "확인되지",
    "관찰되지",
    "확인하지",
    "관찰하지",
    "inference",
    "limitation",
    "not observed",
    "not verified",
    "unverified",
)


@dataclass(frozen=True)
class SourceAnswerViolation:
    reason: str
    excerpt: str


@dataclass(frozen=True)
class SourceAnchor:
    path: str
    start: int
    end: int
    reason: str = ""
    symbol: str = ""


def source_answer_violation(
    *,
    answer: str,
    routing: RoutingDecision,
    messages: list[Message],
    user_prompt: str = "",
) -> SourceAnswerViolation | None:
    if routing.kind != "inspect":
        return None
    raw_action = _raw_tool_action_answer(answer)
    if raw_action is not None:
        return raw_action
    package_role_violation = missing_priority_package_roles(
        answer=answer,
        messages=messages,
        user_prompt=user_prompt,
    )
    if package_role_violation is not None:
        return package_role_violation
    anchor_map, symbols_by_path, observed_paths, observed_symbols = _source_anchor_map(messages)
    if not anchor_map:
        return None
    body_violation = _missing_required_body_evidence(
        answer=answer,
        anchor_map=anchor_map,
        user_prompt=user_prompt,
    )
    if body_violation is not None:
        return body_violation
    for line in answer.splitlines():
        for missing in _missing_anchors(line, anchor_map):
            return SourceAnswerViolation(
                reason="source_answer_unobserved_anchor",
                excerpt=missing,
            )
        path_violation = _unobserved_path_claim(line, observed_paths)
        if path_violation is not None:
            return path_violation
        symbol_violation = _unobserved_dotted_symbol_claim(line, observed_symbols)
        if symbol_violation is not None:
            return symbol_violation
        anchors = _anchors_in_answer_line(line, anchor_map)
        if not anchors:
            continue
        symbols = _symbols_in_line(line, symbols_by_path)
        if not symbols:
            continue
        for symbol in symbols:
            if not _line_has_supporting_anchor(symbol=symbol, anchors=anchors):
                return SourceAnswerViolation(
                    reason="source_answer_mismatched_anchor",
                    excerpt=_compact(line),
                )
    return None


def source_answer_retry_messages(
    *,
    current_messages: list[Message],
    previous_answer: str,
    violation: SourceAnswerViolation,
    language: ResponseLanguage,
) -> list[Message]:
    anchor_candidates = safe_source_anchor_candidates(current_messages, language=language)
    role_candidates = package_role_retry_candidates(current_messages, language=language)
    if language == "ko":
        if violation.reason == "source_answer_raw_tool_action":
            retry_text = (
                "이전 응답은 최종 답변이 아니라 raw tool/action JSON처럼 보입니다. "
                "도구 호출 계획, action JSON, parameters JSON을 출력하지 말고, 이미 관찰된 소스 근거만으로 한국어 최종 분석 답변을 작성하십시오. "
                "관찰 사실과 추론/한계를 분리하십시오. "
                "추론 과정만 쓰고 끝내지 말고, 사용자에게 보일 최종 마크다운 답변 본문을 지금 바로 작성하십시오. "
                f"문제가 된 발췌: {violation.excerpt}"
            )
        else:
            if violation.reason == "source_answer_missing_priority_package_roles":
                retry_text = (
                    "이전 소스 분석 답변은 관찰된 상위 디렉터리/패키지 역할 일부를 누락했습니다. "
                    "대표 파일 세부 설명보다 디렉터리/패키지별 역할 요약을 먼저 작성하십시오. "
                    "source_overview가 반환한 상위 역할 경로를 빠뜨리지 말고, 직접 관찰하지 않은 상세 동작은 한계로 분리하십시오. "
                    f"{' ' + role_candidates if role_candidates else ''} "
                    "추론 과정만 쓰고 끝내지 말고, 사용자에게 보일 최종 마크다운 답변 본문을 지금 바로 작성하십시오. "
                    f"문제가 된 발췌: {violation.excerpt}"
                )
                return [*current_messages, Message(role="user", content=retry_text)]
            body_guidance = (
                "사용자가 함수/메서드 본문 근거를 요구했고 관찰된 body sample anchor가 있다면, "
                "최소 하나 이상의 `symbol_body_sample` 또는 `child_body_sample` 앵커를 핵심 근거로 직접 인용하십시오. "
                if violation.reason == "source_answer_missing_body_evidence"
                else ""
            )
            retry_text = (
                "이전 소스 분석 답변은 파일/라인 앵커를 관찰 근거와 다르게 사용했습니다. "
                "답변을 다시 작성하되, `path:Lx-Ly(reason:symbol)` 앵커는 괄호 안 reason/symbol과 정확히 맞는 주장에만 붙이십시오. "
                f"{body_guidance}"
                "확신할 수 없는 라인 앵커는 모두 생략하고, 파일명/심볼명 단위 근거로만 설명하십시오. "
                "특히 메서드나 클래스 주장을 import/상수 앵커에 연결하지 마십시오. "
                "확인하지 않은 호출 흐름은 '추론' 또는 '남은 한계'로 분리하고 관찰 사실처럼 쓰지 마십시오. "
                f"{' ' + anchor_candidates if anchor_candidates else ''} "
                "추론 과정만 쓰고 끝내지 말고, 사용자에게 보일 최종 마크다운 답변 본문을 지금 바로 작성하십시오. "
                f"문제가 된 발췌: {violation.excerpt}"
            )
    else:
        if violation.reason == "source_answer_raw_tool_action":
            retry_text = (
                "The previous response looked like raw tool/action JSON, not a final answer. "
                "Do not print tool-call plans, action JSON, or parameters JSON. Write the final source-analysis answer from already observed evidence. "
                "Separate observed facts from inferences and limitations. "
                "Do not stop with reasoning-only text; write the user-visible final Markdown answer now. "
                f"Problem excerpt: {violation.excerpt}"
            )
        else:
            if violation.reason == "source_answer_missing_priority_package_roles":
                retry_text = (
                    "The previous source-analysis answer omitted some observed high-priority package/directory roles. "
                    "Summarize package/directory roles before representative file details. "
                    "Do not omit the top role paths returned by source_overview, and separate unobserved details as limitations. "
                    f"{' ' + role_candidates if role_candidates else ''} "
                    "Do not stop with reasoning-only text; write the user-visible final Markdown answer now. "
                    f"Problem excerpt: {violation.excerpt}"
                )
                return [*current_messages, Message(role="user", content=retry_text)]
            body_guidance = (
                "If the user requested function/method body evidence and observed body-sample anchors exist, "
                "cite at least one `symbol_body_sample` or `child_body_sample` anchor as key evidence. "
                if violation.reason == "source_answer_missing_body_evidence"
                else ""
            )
            retry_text = (
                "The previous source-analysis answer attached file/line anchors to claims that were not supported by those observed anchors. "
                "Rewrite the answer using each `path:Lx-Ly(reason:symbol)` anchor only for the exact reason or symbol in that label. "
                f"{body_guidance}"
                "Omit uncertain line anchors entirely and explain with file-level or symbol-level evidence instead. "
                "Do not attach method or class claims to import or constant anchors. "
                "Separate unverified call flow as inference or limitations, not observed fact. "
                f"{' ' + anchor_candidates if anchor_candidates else ''} "
                "Do not stop with reasoning-only text; write the user-visible final Markdown answer now. "
                f"Problem excerpt: {violation.excerpt}"
            )
    return [
        *current_messages,
        Message(role="user", content=retry_text),
    ]


def source_answer_retry_used(recovery) -> bool:
    return any(str(getattr(state, "last_error", "") or "").startswith("source_answer_") for state in recovery.states)


def _raw_tool_action_answer(answer: str) -> SourceAnswerViolation | None:
    stripped = answer.strip()
    if not stripped:
        return None
    head = stripped[:600].lower()
    starts_like_json = stripped.startswith("{") or stripped.startswith("```json")
    marker_hits = sum(1 for marker in RAW_TOOL_ACTION_MARKERS if marker in head)
    if starts_like_json and marker_hits >= 2:
        return SourceAnswerViolation(
            reason="source_answer_raw_tool_action",
            excerpt=_compact(stripped[:240]),
        )
    return None


def _source_anchor_map(
    messages: list[Message],
) -> tuple[dict[str, list[SourceAnchor]], dict[str, set[str]], set[str], set[str]]:
    anchors: dict[str, list[SourceAnchor]] = {}
    symbols_by_path: dict[str, set[str]] = {}
    observed_paths: set[str] = set()
    observed_symbols: set[str] = set()
    for result in tool_results_from_messages(messages):
        observation = result.metadata.get("observation")
        if not result.ok or not isinstance(observation, dict) or observation.get("kind") != "source_probe":
            continue
        path = _clean_path(str(observation.get("target") or result.metadata.get("file_path") or ""))
        if not path:
            continue
        observed_paths.add(path)
        for item in observation.get("line_ranges", []):
            if not isinstance(item, dict):
                continue
            start = _int_value(item.get("start"))
            end = _int_value(item.get("end")) or start
            if start <= 0 or end <= 0:
                continue
            anchors.setdefault(path, []).append(
                SourceAnchor(
                    path=path,
                    start=start,
                    end=end,
                    reason=str(item.get("reason") or "").strip(),
                    symbol=str(item.get("symbol") or "").strip(),
                )
            )
        symbol_set = symbols_by_path.setdefault(path, set())
        for value in observation.get("observed_symbols", []):
            symbol = str(value or "").strip()
            if symbol:
                symbol_set.add(symbol)
                observed_symbols.add(symbol)
                if "." in symbol:
                    short = symbol.rsplit(".", 1)[-1]
                    symbol_set.add(short)
                    observed_symbols.add(short)
        for value in observation.get("wide_symbols", []):
            if isinstance(value, dict):
                symbol = str(value.get("symbol") or "").strip()
                if symbol:
                    symbol_set.add(symbol)
                    observed_symbols.add(symbol)
                    if "." in symbol:
                        short = symbol.rsplit(".", 1)[-1]
                        symbol_set.add(short)
                        observed_symbols.add(short)
    return anchors, symbols_by_path, observed_paths, observed_symbols


def _missing_required_body_evidence(
    *,
    answer: str,
    anchor_map: dict[str, list[SourceAnchor]],
    user_prompt: str,
) -> SourceAnswerViolation | None:
    if not _body_evidence_requested(user_prompt):
        return None
    body_anchors = [
        anchor
        for anchors in anchor_map.values()
        for anchor in anchors
        if _is_body_sample_anchor(anchor)
    ]
    if not body_anchors:
        return None
    for line in answer.splitlines():
        for anchor in _anchors_in_answer_line(line, anchor_map):
            if _is_body_sample_anchor(anchor):
                return None
    example = body_anchors[0]
    return SourceAnswerViolation(
        reason="source_answer_missing_body_evidence",
        excerpt=f"{example.path}:L{example.start}-L{example.end}({example.reason}:{example.symbol})",
    )


def _body_evidence_requested(prompt: str) -> bool:
    compact = re.sub(r"\s+", "", str(prompt or "").lower())
    return any(
        marker in compact
        for marker in (
            "본문",
            "함수본문",
            "메서드본문",
            "body",
            "functionbody",
            "methodbody",
        )
    )


def _is_body_sample_anchor(anchor: SourceAnchor) -> bool:
    return "body_sample" in str(anchor.reason or "")


def _anchors_in_answer_line(line: str, anchor_map: dict[str, list[SourceAnchor]]) -> list[SourceAnchor]:
    anchors: list[SourceAnchor] = []
    for match in ANCHOR_PATTERN.finditer(line):
        path = _clean_path(match.group("path"))
        start = int(match.group("start"))
        end = int(match.group("end") or start)
        observed = _matching_anchor(anchor_map.get(path, []), start=start, end=end)
        if observed:
            anchors.append(observed)
    return anchors


def _missing_anchors(line: str, anchor_map: dict[str, list[SourceAnchor]]) -> list[str]:
    missing: list[str] = []
    for match in ANCHOR_PATTERN.finditer(line):
        path = _clean_path(match.group("path"))
        start = int(match.group("start"))
        end = int(match.group("end") or start)
        if _matching_anchor(anchor_map.get(path, []), start=start, end=end):
            continue
        missing.append(_compact(match.group(0)))
    return missing


def _matching_anchor(anchors: list[SourceAnchor], *, start: int, end: int) -> SourceAnchor | None:
    for anchor in anchors:
        if anchor.start == start and anchor.end == end:
            return anchor
    for anchor in anchors:
        if start >= anchor.start - 2 and end <= anchor.end + 2:
            return anchor
    return None


def _symbols_in_line(line: str, symbols_by_path: dict[str, set[str]]) -> set[str]:
    symbols: set[str] = set()
    for path, path_symbols in symbols_by_path.items():
        if path not in line and Path(path).name not in line:
            continue
        for symbol in path_symbols:
            if _contains_symbol(line, symbol):
                symbols.add(symbol)
    return symbols


def _unobserved_path_claim(line: str, observed_paths: set[str]) -> SourceAnswerViolation | None:
    if not _looks_like_claim(line) or _looks_like_limitation(line):
        return None
    for match in PATH_PATTERN.finditer(line):
        path = _clean_path(match.group("path"))
        if not path or path in observed_paths:
            continue
        return SourceAnswerViolation(
            reason="source_answer_unobserved_path_claim",
            excerpt=_compact(line),
        )
    return None


def _unobserved_dotted_symbol_claim(line: str, observed_symbols: set[str]) -> SourceAnswerViolation | None:
    if not _looks_like_claim(line) or _looks_like_limitation(line):
        return None
    for match in DOTTED_SYMBOL_PATTERN.finditer(line):
        symbol = match.group("symbol")
        if symbol in observed_symbols or symbol.rsplit(".", 1)[-1] in observed_symbols:
            continue
        return SourceAnswerViolation(
            reason="source_answer_unobserved_symbol_claim",
            excerpt=_compact(line),
        )
    return None


def _line_has_supporting_anchor(*, symbol: str, anchors: list[SourceAnchor]) -> bool:
    for anchor in anchors:
        if _anchor_supports_symbol(anchor, symbol):
            return True
    return False


def _anchor_supports_symbol(anchor: SourceAnchor, symbol: str) -> bool:
    if not symbol:
        return True
    if anchor.symbol and (anchor.symbol == symbol or anchor.symbol.endswith(f".{symbol}") or symbol.endswith(f".{anchor.symbol}")):
        return True
    if symbol in {"__init__", "main"} and anchor.reason in {"imports", "read_file"}:
        return True
    return False


def _contains_symbol(line: str, symbol: str) -> bool:
    if not symbol:
        return False
    escaped = re.escape(symbol)
    return bool(re.search(rf"(?<![A-Za-z0-9_.]){escaped}(?![A-Za-z0-9_.])", line))


def _looks_like_claim(line: str) -> bool:
    lowered = line.lower()
    return any(marker in line or marker in lowered for marker in CLAIM_MARKERS)


def _looks_like_limitation(line: str) -> bool:
    lowered = line.lower()
    return any(marker in line or marker in lowered for marker in LIMITATION_MARKERS)


def _clean_path(path: str) -> str:
    value = str(path or "").strip().strip("`").replace("\\", "/")
    if not value:
        return ""
    parts = Path(value).parts
    for anchor in ("src", "tests", "test"):
        if anchor in parts:
            return "/".join(parts[parts.index(anchor) :])
    return value.strip("/")


def _int_value(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _compact(text: str, *, limit: int = 220) -> str:
    compacted = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(compacted) <= limit:
        return compacted
    return compacted[: limit - 3].rstrip() + "..."
