"""Final-answer output format gates."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence

from allCode.core.result import CompletionEvidence

KOREAN_COUNT_WORDS = {
    "한": 1,
    "하나": 1,
    "두": 2,
    "둘": 2,
    "세": 3,
    "셋": 3,
    "네": 4,
    "넷": 4,
    "다섯": 5,
    "여섯": 6,
    "일곱": 7,
    "여덟": 8,
    "아홉": 9,
    "열": 10,
}
KOREAN_COUNT_WORD_PATTERN = "|".join(sorted(KOREAN_COUNT_WORDS, key=len, reverse=True))


def apply_output_format_gate(
    final_answer: str,
    *,
    prompt: str,
    routing,
    evidence: CompletionEvidence,
) -> str:
    """Apply strict user-visible format limits for read-only/direct answers.

    This gate intentionally runs before safety/evidence suffixes are appended in
    finalization. It only reshapes non-mutating answers and skips code blocks so
    generated code, patches, and validation reports are not damaged.
    """

    if _format_gate_blocked(final_answer, routing=routing, evidence=evidence):
        return final_answer
    if _json_requested(prompt):
        return _json_only_answer(final_answer)
    if _table_requested(prompt):
        return _table_only_answer(final_answer, prompt=prompt)
    sentence_count = _requested_count(prompt, unit_patterns=(r"문장", r"sentence(?:s)?"))
    if sentence_count is not None:
        return _limit_sentences(final_answer, sentence_count)
    line_count = _requested_count(prompt, unit_patterns=(r"줄", r"line(?:s)?"))
    if line_count is not None:
        return _limit_lines(final_answer, line_count)
    bullet_count = _requested_bullet_count(prompt)
    if bullet_count is not None:
        return _limit_bullets(final_answer, bullet_count)
    if brevity_requested(prompt):
        return _brief_answer(final_answer)
    return final_answer


def _format_gate_blocked(final_answer: str, *, routing, evidence: CompletionEvidence) -> bool:
    if not final_answer.strip():
        return True
    if "```" in final_answer:
        return True
    if getattr(routing, "requires_mutation", False) or getattr(routing, "requires_validation", False):
        return True
    if evidence.has_file_change() or evidence.validation_commands:
        return True
    return False


def _requested_count(prompt: str, *, unit_patterns: tuple[str, ...]) -> int | None:
    text = str(prompt or "")
    for unit in unit_patterns:
        match = re.search(rf"(?P<count>\d+)\s*{unit}", text, flags=re.IGNORECASE)
        if match:
            try:
                return max(1, min(20, int(match.group("count"))))
            except ValueError:
                return None
        word_match = re.search(rf"(?P<count>{KOREAN_COUNT_WORD_PATTERN})\s*{unit}", text, flags=re.IGNORECASE)
        if word_match:
            return KOREAN_COUNT_WORDS.get(word_match.group("count"))
    if any(re.search(rf"한\s*{unit}", text, flags=re.IGNORECASE) for unit in unit_patterns):
        return 1
    return None


def _limit_sentences(text: str, count: int) -> str:
    units = _sentence_units(text)
    if len(units) < count:
        return text
    return " ".join(units[:count]).strip()


def _limit_lines(text: str, count: int) -> str:
    lines = _content_lines(text)
    if len(lines) < count:
        return text
    return "\n".join(lines[:count]).strip()


def _limit_bullets(text: str, count: int) -> str:
    lines = _content_lines(text)
    if len(lines) < count:
        return text
    return "\n".join(f"- {line}" for line in lines[:count]).strip()


def _brief_answer(text: str) -> str:
    if _extract_markdown_table(text):
        return text
    lines = _brief_content_lines(text)
    if len(lines) > 4:
        return "\n".join(lines[:4]).strip()
    units = _sentence_units(text)
    if len(units) > 3:
        return " ".join(units[:3]).strip()
    return text


def _json_only_answer(text: str) -> str:
    extracted = _extract_json_payload(text)
    if extracted is not None:
        return _stable_json(extracted)
    from_pairs = _json_from_key_value_lines(text)
    if from_pairs is not None:
        return _stable_json(from_pairs)
    return text


def _table_only_answer(text: str, *, prompt: str) -> str:
    table = _extract_markdown_table(text)
    if table:
        return table
    from_pairs = _table_from_key_value_lines(text, korean=_looks_korean(prompt))
    if from_pairs:
        return from_pairs
    return text


def _sentence_units(text: str) -> list[str]:
    content = " ".join(_content_lines(text))
    if not content:
        return []
    rough = re.split(r"(?<=[.!?。？！])\s+", content)
    units = [item.strip() for item in rough if item.strip()]
    if len(units) <= 1:
        units = _korean_sentence_fallback(content)
    return units


def _korean_sentence_fallback(text: str) -> list[str]:
    matches = re.findall(r".+?(?:다\.|요\.|음\.|함\.|됨\.|[.!?。？！])(?:\s+|$)", text)
    return [item.strip() for item in matches if item.strip()]


def _content_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in str(text or "").splitlines():
        line = _strip_markdown_structure(raw_line)
        if line:
            lines.append(line)
    return lines


def _brief_content_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in str(text or "").splitlines():
        stripped = raw_line.strip()
        if not stripped or re.fullmatch(r"#{1,6}\s+.+", stripped):
            continue
        if re.fullmatch(r"\*\*[^*]+\*\*", stripped) or re.fullmatch(r"__[^_]+__", stripped):
            continue
        lines.append(stripped)
    return lines


def _strip_markdown_structure(line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return ""
    if re.fullmatch(r"#{1,6}\s+.+", stripped):
        return ""
    if re.fullmatch(r"\*\*[^*]+\*\*", stripped):
        return ""
    if re.fullmatch(r"__[^_]+__", stripped):
        return ""
    stripped = re.sub(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", "", stripped)
    return stripped.strip()


def _requested_bullet_count(prompt: str) -> int | None:
    text = str(prompt or "")
    compact = re.sub(r"\s+", "", text.lower())
    has_list_signal = any(
        marker in compact
        for marker in (
            "bullet",
            "bullets",
            "bulletpoint",
            "bulletpoints",
            "불릿",
            "목록",
            "항목",
            "리스트",
        )
    )
    if not has_list_signal:
        return None
    patterns = (
        r"(?P<count>\d+)\s*(?:개|가지|항목|줄)?\s*(?:bullet|bullets|bullet points|items|목록|항목|불릿|리스트)",
        r"(?:bullet|bullets|bullet points|items|목록|항목|불릿|리스트)\s*(?P<count>\d+)\s*(?:개|가지|항목|줄)?",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            try:
                return max(1, min(20, int(match.group("count"))))
            except ValueError:
                return None
    korean_word_pattern = (
        rf"(?P<count>{KOREAN_COUNT_WORD_PATTERN})\s*(?:개|가지|항목|줄)?\s*"
        r"(?:bullet|bullets|bullet points|items|목록|항목|불릿|리스트)"
    )
    word_match = re.search(korean_word_pattern, text, flags=re.IGNORECASE)
    if word_match:
        value = KOREAN_COUNT_WORDS.get(word_match.group("count"))
        return max(1, min(20, value)) if value is not None else None
    return 1 if re.search(r"한\s*(?:개\s*)?(?:bullet|목록|항목|불릿)", text, flags=re.IGNORECASE) else None


def brevity_requested(prompt: str) -> bool:
    text = str(prompt or "")
    lowered = text.lower()
    compact = re.sub(r"\s+", "", lowered)
    if _brevity_negated(text):
        return False
    korean_markers = (
        "짧게",
        "간단히",
        "간단하게",
        "간략히",
        "간략하게",
        "간결하게",
        "짧은답변",
    )
    if any(marker in compact for marker in korean_markers):
        return True
    english_patterns = (
        r"\bbriefly\b",
        r"\bconcise(?:ly)?\b",
        r"\bshort answer\b",
        r"\bkeep it short\b",
        r"\bkeep (?:the )?answer short\b",
    )
    return any(re.search(pattern, lowered) for pattern in english_patterns)


def _brevity_negated(text: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or "").lower())
    korean_negations = (
        "짧게하지마",
        "짧게하지말",
        "짧게말고",
        "간단히말고",
        "간단하게말고",
        "간략히말고",
        "간결하게말고",
    )
    if any(marker in compact for marker in korean_negations):
        return True
    english_negations = (
        r"\bdo not (?:be )?(?:brief|concise)\b",
        r"\bdon't (?:be )?(?:brief|concise)\b",
        r"\bnot (?:brief|concise|short)\b",
    )
    return any(re.search(pattern, str(text or "").lower()) for pattern in english_negations)


def _json_requested(prompt: str) -> bool:
    compact = re.sub(r"\s+", "", str(prompt or "").lower())
    return any(marker in compact for marker in ("json", "json객체", "json형식", "json으로"))


def _table_requested(prompt: str) -> bool:
    compact = re.sub(r"\s+", "", str(prompt or "").lower())
    markers = (
        "table",
        "markdown table",
        "표로",
        "표형식",
        "표형태",
        "표로만",
        "표로정리",
        "테이블",
        "테이블로",
    )
    return any(marker.replace(" ", "") in compact for marker in markers)


def _extract_json_payload(text: str) -> object | None:
    value = _parse_json_candidate(str(text or "").strip())
    if value is not None:
        return value
    candidates = _json_candidates(str(text or ""))
    for candidate in reversed(candidates):
        value = _parse_json_candidate(candidate)
        if value is not None:
            return value
    return None


def _json_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    for opener, closer in (("{", "}"), ("[", "]")):
        starts = [index for index, char in enumerate(text) if char == opener]
        ends = [index for index, char in enumerate(text) if char == closer]
        for start in starts:
            for end in reversed(ends):
                if end > start:
                    candidates.append(text[start : end + 1])
                    break
    return candidates[-8:]


def _parse_json_candidate(text: str) -> object | None:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\s*```$", "", candidate)
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, (dict, list)) else None


def _json_from_key_value_lines(text: str) -> dict[str, str] | None:
    pairs: dict[str, str] = {}
    for line in _content_lines(text):
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = _json_key(key)
        value = value.strip()
        if key and value:
            pairs[key] = value
    return pairs or None


def _json_key(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z가-힣_ -]+", "", value).strip().lower()
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned[:80]


def _stable_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _extract_markdown_table(text: str) -> str:
    lines = str(text or "").splitlines()
    for index, line in enumerate(lines[:-1]):
        if not _is_markdown_table_row(line) or not _is_markdown_separator(lines[index + 1]):
            continue
        table_lines = [line.strip(), lines[index + 1].strip()]
        for row in lines[index + 2 :]:
            if not _is_markdown_table_row(row):
                break
            table_lines.append(row.strip())
        return "\n".join(table_lines)
    return ""


def _table_from_key_value_lines(text: str, *, korean: bool) -> str:
    pairs: list[tuple[str, str]] = []
    for line in _content_lines(text):
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key and value:
            pairs.append((key, value))
    if len(pairs) < 2:
        return ""
    headers = ("항목", "내용") if korean else ("Item", "Value")
    rows = [f"| {headers[0]} | {headers[1]} |", "| --- | --- |"]
    rows.extend(f"| {_escape_table_cell(key)} | {_escape_table_cell(value)} |" for key, value in pairs)
    return "\n".join(rows)


def _is_markdown_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2


def _is_markdown_separator(line: str) -> bool:
    if not _is_markdown_table_row(line):
        return False
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return bool(cells) and all(cell and set(cell) <= {"-", ":", " "} and "-" in cell for cell in cells)


def _escape_table_cell(value: str) -> str:
    return value.replace("|", "\\|").strip()


def _looks_korean(text: str) -> bool:
    return bool(re.search(r"[가-힣]", str(text or "")))
