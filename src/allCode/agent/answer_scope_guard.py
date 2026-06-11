"""Quality guard for direct answers with explicit evergreen scope."""

from __future__ import annotations

import re
from dataclasses import dataclass

from allCode.agent.language import ResponseLanguage
from allCode.agent.prompt_constraint_detection import external_knowledge_suppressed
from allCode.agent.router import RoutingDecision
from allCode.core.models import Message

_METRIC_NUMBER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(?:[$€£₩]\s*)?"
    r"(?:\d+(?:[.,]\d+)?(?:\s*(?:"
    r"%|ms|msec|s|sec|seconds?|milliseconds?|초|밀리초|원|달러|usd|krw|"
    r"배|x|k|m|b|개|건|쿼리|queries|tokens?|토큰|파라미터|parameters?|"
    r"년|개월|월|주|일|시간|분|회|단계|팀|명|사용자|개발자|"
    r"bytes?|kb|mb|gb|tb|pb|qps|rps|tps|hz|mhz|ghz|cores?|코어|"
    r"million|billion|mn|bn"
    r"))|\d+\s*(?:~|-|–|—|to)\s*\d+|k\s*=\s*\d+|recall@\w+|mrr@\w+)"
    r"(?![A-Za-z0-9_])",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class AnswerScopeViolation:
    reason: str
    excerpt: str


def answer_scope_violation(
    *,
    prompt: str,
    answer: str,
    routing: RoutingDecision,
) -> AnswerScopeViolation | None:
    if routing.kind != "answer":
        return None
    explicit_metric_caution = _explicit_unverified_metric_caution(prompt)
    if routing.requires_external_knowledge and not explicit_metric_caution:
        return None
    if "external_knowledge_suppressed" not in routing.flags and not external_knowledge_suppressed(prompt) and not explicit_metric_caution:
        return None
    for match in _METRIC_NUMBER_PATTERN.finditer(answer):
        value = match.group(0).strip()
        if _inside_square_bracket_citation(answer, match.start(), match.end()):
            continue
        if _number_supplied_by_user(value, prompt):
            continue
        return AnswerScopeViolation(
            reason="concrete_metric_in_evergreen_answer",
            excerpt=_excerpt(answer, match.start(), match.end()),
        )
    return None


def answer_scope_retry_messages(
    *,
    current_messages: list[Message],
    previous_answer: str,
    violation: AnswerScopeViolation,
    language: ResponseLanguage,
) -> list[Message]:
    retry_text = (
        "이전 답변은 사용자가 요청한 '최신 수치가 아닌 일반 원칙 중심' 범위를 벗어나는 구체 수치나 벤치마크를 포함했습니다. "
        "구체적인 숫자, 퍼센트, 비용, 지연 시간, 후보군 크기, 모델 크기 예시는 제거하고, 정성적 기준과 의사결정 흐름만으로 다시 작성하세요. "
        f"문제가 된 발췌: {violation.excerpt}"
        if language == "ko"
        else "The previous answer included concrete metrics or benchmark-like figures even though the user requested stable general principles. "
        "Remove concrete numbers, percentages, costs, latency values, candidate sizes, and model-size examples. "
        f"Rewrite using qualitative criteria and decision flow only. Problem excerpt: {violation.excerpt}"
    )
    return [
        *current_messages,
        Message(role="assistant", content=previous_answer.rstrip()),
        Message(role="user", content=retry_text),
    ]


def answer_scope_retry_used(recovery, *, max_attempts: int = 1) -> bool:
    attempts = sum(1 for state in recovery.states if getattr(state, "reason", None) == "answer_scope_violation")
    return attempts >= max_attempts


def _number_supplied_by_user(value: str, prompt: str) -> bool:
    compact_value = re.sub(r"\s+", "", value).lower()
    if not compact_value:
        return False
    return any(re.sub(r"\s+", "", match.group(0)).lower() == compact_value for match in _METRIC_NUMBER_PATTERN.finditer(prompt))


def _explicit_unverified_metric_caution(prompt: str) -> bool:
    lowered = str(prompt or "").lower()
    compact = re.sub(r"\s+", "", lowered)
    english_markers = (
        "do not assert unverified",
        "don't assert unverified",
        "do not make up numbers",
        "don't make up numbers",
        "do not invent numbers",
        "don't invent numbers",
        "unverified numbers",
        "unverified metrics",
        "needs web search",
        "need web search",
        "requires web search",
    )
    korean_markers = (
        "확인되지않은수치",
        "확인되지않은숫자",
        "검증되지않은수치",
        "검증되지않은숫자",
        "미확인수치",
        "미검증수치",
        "수치를단정하지",
        "숫자를단정하지",
        "웹검색이필요",
        "웹검색필요",
    )
    return any(marker in lowered for marker in english_markers) or any(marker in compact for marker in korean_markers)


def _inside_square_bracket_citation(text: str, start: int, end: int) -> bool:
    left = text.rfind("[", 0, start + 1)
    right = text.find("]", end)
    if left == -1 or right == -1:
        return False
    if "]" in text[left:start] or "[" in text[end:right]:
        return False
    inner = text[left + 1 : right].strip()
    return bool(re.fullmatch(r"\d+(?:\s*(?:,|;|~|-|–|—|to)\s*\d+)*", inner, re.IGNORECASE))


def _excerpt(text: str, start: int, end: int, *, radius: int = 60) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    return text[left:right].replace("\n", " ").strip()
