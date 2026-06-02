"""Backend for /memory slash commands."""

from __future__ import annotations

from pathlib import Path

from allCode.memory.inbox import MemoryInbox
from allCode.memory.schema import MemoryItem, estimate_tokens
from allCode.memory.session_store import SessionStore
from allCode.memory.store import MemoryStore


class MemoryCommandService:
    def __init__(self, *, store: MemoryStore, inbox: MemoryInbox, session_store: SessionStore, cwd: Path) -> None:
        self.store = store
        self.inbox = inbox
        self.session_store = session_store
        self.cwd = cwd

    async def handle(self, command: str) -> str:
        parts = command.strip().split(maxsplit=2)
        if len(parts) < 2 or parts[0] != "/memory":
            return "Unknown memory command."
        action = parts[1]
        if action == "show":
            items = await self.store.load_active_items(cwd=self.cwd)
            if not items:
                return "활성 메모리가 없습니다."
            lines = [f"활성 메모리 {len(items)}개:"]
            for item in items:
                evidence = ", ".join(item.evidence[:2]) if item.evidence else "manual"
                token_estimate = estimate_tokens(item.text)
                lines.append(f"- [{item.scope}/{item.kind}] {item.text} ({token_estimate} tokens, source: {evidence})")
            return "\n".join(lines)
        if action == "add" and len(parts) == 3:
            item = MemoryItem(scope="project", kind="instruction", text=parts[2])
            await self.store.add_item(item)
            return f"Added memory {item.id}."
        if action == "refresh":
            items = await self.store.load_active_items(cwd=self.cwd)
            scopes = sorted({item.scope for item in items})
            scope_text = ", ".join(scopes) if scopes else "none"
            return f"Loaded {len(items)} active memory item(s). scopes: {scope_text}."
        if action == "inbox":
            candidates = await self.inbox.list_candidates()
            return "\n".join(f"- {item.id}: {item.text}" for item in candidates)
        if action == "approve" and len(parts) >= 3:
            approved = await self.inbox.approve(parts[2])
            return f"Approved memory {approved.id}."
        if action == "reject" and len(parts) >= 3:
            await self.inbox.reject(parts[2])
            return f"Rejected memory {parts[2]}."
        if action == "clear-session" and len(parts) >= 3:
            await self.session_store.clear_session(parts[2])
            return f"Cleared session {parts[2]}."
        return "Unsupported memory command."
