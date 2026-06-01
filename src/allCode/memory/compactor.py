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
            compacted = content[:max_chars]
        else:
            lines = content.splitlines()
            compacted = "\n".join(lines[: max(1, max_tokens // 12)])
            if len(compacted) > max_chars:
                compacted = compacted[:max_chars]
        return section.model_copy(update={"content": compacted, "token_estimate": estimate_tokens(compacted)})
