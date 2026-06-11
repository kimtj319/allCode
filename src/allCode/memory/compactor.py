"""Context budget compaction."""

from __future__ import annotations

from allCode.memory.schema import ContextSection, estimate_tokens


class ContextCompactor:
    def __init__(self, *, token_budget: int = 4000, safety_ratio: float = 0.05) -> None:
        self.token_budget = token_budget
        self.safety_ratio = safety_ratio

    def fit(self, sections: list[ContextSection]) -> list[ContextSection]:
        budget = int(self.token_budget * (1.0 - self.safety_ratio))
        ordered = sorted(sections, key=lambda section: (-section.priority, section.token_estimate))
        selected: list[ContextSection] = []
        used = 0
        for section in ordered:
            if used + section.token_estimate <= budget:
                selected.append(section)
                used += section.token_estimate
                continue
            compacted = self._compact_section(section, max_tokens=max(0, budget - used))
            if compacted is not None:
                selected.append(compacted)
                used += compacted.token_estimate
                break
        return sorted(selected, key=lambda section: -section.priority)

    def _compact_section(self, section: ContextSection, *, max_tokens: int) -> ContextSection | None:
        if max_tokens <= 0:
            return None
        max_chars = max_tokens * 4
        content = section.content
        if section.section_type == "active_file":
            compacted = _compact_active_file(content, max_chars=max_chars)
        else:
            lines = content.splitlines()
            compacted = "\n".join(lines[: max(1, max_tokens // 12)])
            if len(compacted) > max_chars:
                compacted = compacted[:max_chars]
        return section.model_copy(update={"content": compacted, "token_estimate": estimate_tokens(compacted)})


def _compact_active_file(content: str, *, max_chars: int) -> str:
    """Compact active-file context without cutting code in the middle of a line."""

    if len(content) <= max_chars:
        return content
    lines = content.splitlines()
    if not lines:
        return ""
    marker = "[active file middle omitted: use source_probe/read_file ranges for exact code]"
    if max_chars <= len(marker) + 20:
        return marker[:max_chars]

    head_lines: list[str] = []
    tail_lines: list[str] = []
    used = len(marker) + 2
    for line in lines:
        addition = len(line) + 1
        if head_lines and used + addition > max_chars // 2:
            break
        if used + addition > max_chars - 1:
            break
        head_lines.append(line)
        used += addition
    for line in reversed(lines):
        addition = len(line) + 1
        if used + addition > max_chars:
            break
        tail_lines.append(line)
        used += addition
    tail_lines.reverse()
    compacted = "\n".join([*head_lines, marker, *tail_lines]).strip()
    if len(compacted) <= max_chars:
        return compacted
    return "\n".join([*head_lines, marker]).strip()
