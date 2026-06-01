"""Builtin shell and validation tools."""

from __future__ import annotations

import asyncio
import os
import shlex
import sys
from pathlib import Path

from allCode.core.event_bus import EventBus
from allCode.core.models import ToolCall, ToolResult
from allCode.tools.base import ToolContext, ToolDefinition
from allCode.tools.builtin.file_ops import resolve_under_root

MAX_STREAM_CHARS = 20_000


def _truncate(value: str, limit: int = MAX_STREAM_CHARS) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "\n[truncated]"


class RunCommandTool:
    definition = ToolDefinition(
        name="run_command",
        description="Run a non-interactive shell command in the workspace.",
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "cwd": {"type": "string"},
                "timeout_seconds": {"type": "integer"},
            },
            "required": ["command"],
            "additionalProperties": False,
        },
        read_only=True,
        requires_approval=True,
        group="shell",
    )

    async def run(self, call: ToolCall, context: ToolContext, event_bus: EventBus | None = None) -> ToolResult:
        return await run_shell_call(call, context, validation=False)


class RunTestsTool:
    definition = ToolDefinition(
        name="run_tests",
        description="Run a validation command and return summarized test output.",
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "cwd": {"type": "string"},
                "timeout_seconds": {"type": "integer"},
            },
            "required": ["command"],
            "additionalProperties": False,
        },
        read_only=True,
        group="shell",
    )

    async def run(self, call: ToolCall, context: ToolContext, event_bus: EventBus | None = None) -> ToolResult:
        return await run_shell_call(call, context, validation=True)


async def run_shell_call(call: ToolCall, context: ToolContext, *, validation: bool) -> ToolResult:
    try:
        command = str(call.arguments["command"])
        execution_command = _portable_command(command)
        cwd_arg = str(call.arguments.get("cwd", "."))
        cwd = resolve_under_root(context.workspace.root, cwd_arg)
        timeout = int(call.arguments.get("timeout_seconds", 180 if validation else 60))
        env = _allowed_environment(context.environment)
        process = await asyncio.create_subprocess_shell(
            execution_command,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except TimeoutError:
            process.kill()
            await process.communicate()
            return ToolResult(
                call_id=call.id,
                name=call.name,
                ok=False,
                error=f"command timed out after {timeout}s",
                error_type="TimeoutError",
                metadata={"command": command, "executed_command": execution_command, "validation_command": validation},
            )
        stdout = stdout_bytes.decode(errors="replace")
        stderr = stderr_bytes.decode(errors="replace")
        ok = process.returncode == 0
        return ToolResult(
            call_id=call.id,
            name=call.name,
            ok=ok,
            content=_truncate(stdout),
            error=None if ok else _truncate(stderr or stdout),
            error_type=None if ok else "CommandFailed",
            metadata={
                "command": command,
                "executed_command": execution_command,
                "cwd": str(cwd),
                "returncode": process.returncode,
                "stdout": _truncate(stdout),
                "stderr": _truncate(stderr),
                "full_stdout_chars": len(stdout),
                "full_stderr_chars": len(stderr),
                "validation_command": validation,
                "validation_passed": ok if validation else None,
            },
        )
    except Exception as exc:
        return ToolResult(call_id=call.id, name=call.name, ok=False, error=str(exc), error_type=exc.__class__.__name__)


def _allowed_environment(extra: dict[str, str]) -> dict[str, str]:
    keep = {"PATH", "HOME", "LANG", "LC_ALL", "PYTHONPATH"}
    env = {key: value for key, value in os.environ.items() if key in keep}
    env.update(extra)
    return env


def _portable_command(command: str) -> str:
    try:
        parts = shlex.split(command)
    except ValueError:
        return command
    if not parts or parts[0] != "python":
        return command
    return " ".join([shlex.quote(sys.executable), *[shlex.quote(part) for part in parts[1:]]])
