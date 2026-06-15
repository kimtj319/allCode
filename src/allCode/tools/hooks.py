"""Pre/post tool execution hooks (Claude Code-style extensibility).

Hooks are shell commands run around tool execution. A ``pre_tool`` hook whose
command exits non-zero blocks the tool (its stderr becomes the denial reason);
``post_tool`` hooks observe only. The matched tool name, JSON arguments, and (for
post hooks) the ok flag are passed via environment variables so hooks stay
language-agnostic.
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import os
from typing import TYPE_CHECKING

from allCode.core.models import ToolCall, ToolResult

if TYPE_CHECKING:
    from allCode.config.schema import HooksConfig, HookSpec


class HookRunner:
    def __init__(self, hooks: "HooksConfig | None" = None) -> None:
        self._pre = list(hooks.pre_tool) if hooks else []
        self._post = list(hooks.post_tool) if hooks else []

    @property
    def active(self) -> bool:
        return bool(self._pre or self._post)

    async def pre_tool(self, call: ToolCall) -> str | None:
        """Return a denial reason if a matching pre-hook blocks the tool, else None."""
        for spec in self._pre:
            if not _matches(spec.match, call.name):
                continue
            env = _hook_env(call)
            code, _out, err = await _run(spec.command, env, spec.timeout_seconds)
            if code != 0:
                return (err.strip() or f"blocked by pre_tool hook (exit {code})")[:500]
        return None

    async def post_tool(self, call: ToolCall, result: ToolResult) -> None:
        for spec in self._post:
            if not _matches(spec.match, call.name):
                continue
            env = _hook_env(call)
            env["ALLCODE_TOOL_OK"] = "1" if result.ok else "0"
            await _run(spec.command, env, spec.timeout_seconds)


def _matches(pattern: str, name: str) -> bool:
    return fnmatch.fnmatch(name, pattern or "*")


def _hook_env(call: ToolCall) -> dict[str, str]:
    env = dict(os.environ)
    env["ALLCODE_TOOL_NAME"] = call.name
    try:
        env["ALLCODE_TOOL_ARGS"] = json.dumps(call.arguments or {}, ensure_ascii=False)
    except (TypeError, ValueError):
        env["ALLCODE_TOOL_ARGS"] = "{}"
    return env


async def _run(command: str, env: dict[str, str], timeout: int) -> tuple[int, str, str]:
    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        out, err = await asyncio.wait_for(process.communicate(), timeout=timeout)
        return process.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")
    except TimeoutError:
        try:
            process.kill()
        except Exception:
            pass
        return 1, "", f"hook timed out after {timeout}s"
    except Exception as exc:  # noqa: BLE001 - a broken hook must not crash the turn
        return 0, "", str(exc)
