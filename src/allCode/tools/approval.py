"""Approval and risk classification for tool execution."""

from __future__ import annotations

import re
import shlex
from typing import Literal

from allCode.core.models import CoreModel

ApprovalMode = Literal["ask", "auto", "rules"]


class ApprovalDecision(CoreModel):
    allowed: bool
    requires_approval: bool = False
    reason: str = ""
    preview: str = ""
    risk: str = "low"


class ApprovalManager:
    DESTRUCTIVE_PATTERNS = (
        re.compile(r"\brm\s+-[^\n;]*r[^\n;]*f\b"),
        re.compile(r"\bsudo\b"),
        re.compile(r"\bmkfs(?:\.\w+)?\b"),
        re.compile(r"\bdd\s+if="),
        re.compile(r"\bshutdown\b|\breboot\b"),
        re.compile(r">\s*/dev/(?:disk|rdisk|sda|nvme)"),
        re.compile(r"&\s*$"),
    )

    def __init__(self, *, mode: ApprovalMode = "ask", session_allow: list[str] | None = None) -> None:
        self.mode = mode
        self.session_allow = session_allow or []

    def file_mutation(self, *, preview: str, tool_name: str) -> ApprovalDecision:
        if self.mode == "auto":
            return ApprovalDecision(allowed=True, reason="Auto approval mode allowed file mutation.", preview=preview)
        if self._session_allows(tool_name):
            return ApprovalDecision(allowed=True, reason="Session rule allowed file mutation.", preview=preview)
        return ApprovalDecision(
            allowed=False,
            requires_approval=True,
            reason="File mutation requires approval.",
            preview=preview,
            risk="medium",
        )

    def shell_command(self, command: str, *, validation: bool = False) -> ApprovalDecision:
        destructive = self.is_destructive_command(command)
        preview = self.command_preview(command)
        if destructive and not self._session_allows(command):
            return ApprovalDecision(
                allowed=False,
                requires_approval=True,
                reason="Destructive shell command requires explicit approval.",
                preview=preview,
                risk="high",
            )
        if self.mode == "auto" or validation or self._session_allows(command):
            return ApprovalDecision(allowed=True, reason="Shell command allowed.", preview=preview, risk="low")
        return ApprovalDecision(
            allowed=False,
            requires_approval=True,
            reason="Shell command requires approval.",
            preview=preview,
            risk="medium",
        )

    def is_destructive_command(self, command: str) -> bool:
        normalized = " ".join(command.strip().split())
        return any(pattern.search(normalized) for pattern in self.DESTRUCTIVE_PATTERNS)

    def command_preview(self, command: str) -> str:
        try:
            parts = shlex.split(command)
        except ValueError:
            parts = command.split()
        return " ".join(parts[:12])

    def _session_allows(self, value: str) -> bool:
        normalized = value.strip()
        return any(normalized.startswith(rule) for rule in self.session_allow)
