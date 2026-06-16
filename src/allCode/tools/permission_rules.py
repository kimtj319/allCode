"""Per-path / per-command allow & deny rules for tool execution.

Rules are strings in either form:
  - ``Tool``                 — matches every use of that tool/group
  - ``Tool(pattern)``        — matches when the call's target matches the glob

``Tool`` may be an allCode tool name (``run_command``, ``write_file``,
``patch_file``, ``delete_path``, ``run_tests``, ``read_file`` …) or a friendly
group: ``Bash``/``Shell`` (shell commands), ``Edit``/``Write`` (file mutations),
``Read`` (read-only inspection). The pattern is matched (fnmatch) against the
shell command string for shell tools, or the target file path for file tools.

Deny rules win over allow rules; allow rules auto-approve; anything unmatched
falls through to the configured approval mode.
"""

from __future__ import annotations

import fnmatch
import re

_RULE_RE = re.compile(r"^\s*([A-Za-z_][\w]*)\s*(?:\(\s*(.*?)\s*\))?\s*$")

_TOOL_GROUPS: dict[str, set[str]] = {
    "bash": {"run_command", "run_tests", "run_shell"},
    "shell": {"run_command", "run_tests", "run_shell"},
    "edit": {"write_file", "patch_file", "delete_path"},
    "write": {"write_file", "patch_file", "delete_path"},
    "read": {
        "read_file",
        "list_directory",
        "search_files",
        "glob_files",
        "list_tree",
        "source_overview",
        "source_probe",
    },
}


def _tool_matches(group: str, tool_name: str) -> bool:
    group = group.lower()
    members = _TOOL_GROUPS.get(group)
    if members is not None:
        return tool_name in members
    return group == tool_name.lower()


def rule_matches(rule: str, tool_name: str, target: str | None) -> bool:
    match = _RULE_RE.match(rule or "")
    if not match:
        return False
    group, pattern = match.group(1), match.group(2)
    if not _tool_matches(group, tool_name):
        return False
    if pattern is None or pattern == "":
        return True
    if not target:
        return False
    candidate = target.strip()
    return fnmatch.fnmatch(candidate, pattern) or fnmatch.fnmatch(candidate, f"{pattern}*")


class PermissionRules:
    def __init__(self, allow: list[str] | None = None, deny: list[str] | None = None) -> None:
        self.allow = [r for r in (allow or []) if r and r.strip()]
        self.deny = [r for r in (deny or []) if r and r.strip()]

    @property
    def active(self) -> bool:
        return bool(self.allow or self.deny)

    def decision(self, tool_name: str, target: str | None) -> str | None:
        """Return "deny", "allow", or None (no matching rule)."""

        if any(rule_matches(rule, tool_name, target) for rule in self.deny):
            return "deny"
        if any(rule_matches(rule, tool_name, target) for rule in self.allow):
            return "allow"
        return None
