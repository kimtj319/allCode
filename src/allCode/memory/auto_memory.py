"""Auto-memory candidate extraction."""

from __future__ import annotations

from allCode.core.models import Message
from allCode.memory.redaction import redact_text
from allCode.memory.schema import MemoryItem


class AutoMemoryExtractor:
    def __init__(self, *, min_user_messages: int = 10) -> None:
        self.min_user_messages = min_user_messages

    def extract_candidates(self, messages: list[Message], *, session_id: str) -> list[MemoryItem]:
        user_messages = [message.content for message in messages if message.role == "user" and message.content.strip()]
        if len(user_messages) < self.min_user_messages:
            return []
        candidates: list[MemoryItem] = []
        for text in user_messages:
            lowered = text.lower()
            if any(term in lowered for term in ("always", "never", "prefer", "반드시", "금지", "선호")):
                kind = "constraint" if any(term in lowered for term in ("never", "금지")) else "preference"
                candidates.append(
                    MemoryItem(
                        scope="session",
                        kind=kind,
                        text=redact_text(text),
                        confidence=0.7,
                        source_session_id=session_id,
                        approved=False,
                    )
                )
        return candidates
