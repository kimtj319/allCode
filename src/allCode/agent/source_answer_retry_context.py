"""Retry context for grounded source-analysis final answers."""

from __future__ import annotations

from allCode.core.models import Message

MAX_RETRY_ANCHORS = 10


def safe_source_anchor_candidates(messages: list[Message], *, language: str) -> str:
    """Return compact observed anchors that the model may safely cite."""

    candidates: list[str] = []
    for message in messages:
        if message.role != "tool":
            continue
        observation = message.metadata.get("observation")
        if not isinstance(observation, dict) or observation.get("kind") != "source_probe":
            continue
        path = _clean_path(str(observation.get("target") or message.metadata.get("file_path") or ""))
        if not path:
            continue
        for item in observation.get("line_ranges", []):
            if not isinstance(item, dict):
                continue
            start = _positive_int(item.get("start"))
            end = _positive_int(item.get("end")) or start
            if start <= 0 or end <= 0:
                continue
            reason = str(item.get("reason") or "").strip()
            symbol = str(item.get("symbol") or "").strip()
            label = f"{path}:L{start}-L{end}"
            if reason or symbol:
                label = f"{label}(reason:{reason or 'observed'}{':' + symbol if symbol else ''})"
            if label not in candidates:
                candidates.append(label)
            if len(candidates) >= MAX_RETRY_ANCHORS:
                break
        if len(candidates) >= MAX_RETRY_ANCHORS:
            break
    if not candidates:
        return ""
    if language == "ko":
        header = "재작성 시 사용할 수 있는 관찰 앵커 후보:"
    else:
        header = "Observed anchor candidates you may cite in the rewrite:"
    return "\n".join([header, *[f"- `{candidate}`" for candidate in candidates]])


def source_answer_retry_count(recovery) -> int:
    count = 0
    for state in getattr(recovery, "states", []):
        if str(getattr(state, "last_error", "") or "").startswith("source_answer_"):
            count += 1
    return count


def repeated_source_answer_violation(recovery, *, reason: str, excerpt: str) -> bool:
    signature = _violation_signature(reason, excerpt)
    for state in getattr(recovery, "states", []):
        last_error = str(getattr(state, "last_error", "") or "")
        if _normalize(last_error).startswith(signature):
            return True
    return False


def source_answer_violation_error(reason: str, excerpt: str) -> str:
    return f"{reason}: {excerpt}"


def _violation_signature(reason: str, excerpt: str) -> str:
    return _normalize(source_answer_violation_error(reason, excerpt))


def _normalize(value: str) -> str:
    return " ".join(str(value or "").split())


def _clean_path(value: str) -> str:
    cleaned = value.strip().replace("\\", "/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned


def _positive_int(value) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0
