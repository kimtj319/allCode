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
from allCode.workspace.project_locator import ProjectLocator

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
            "additionalProperties": False,
        },
        read_only=True,
        group="shell",
    )

    async def run(self, call: ToolCall, context: ToolContext, event_bus: EventBus | None = None) -> ToolResult:
        return await run_shell_call(call, context, validation=True)


async def run_shell_call(call: ToolCall, context: ToolContext, *, validation: bool) -> ToolResult:
    try:
        cwd_arg = str(call.arguments.get("cwd", "."))
        cwd = resolve_under_root(context.workspace.root, cwd_arg)
        raw_command = call.arguments.get("command")
        command = _command_to_string(raw_command)
        if validation and cwd_arg in {"", "."}:
            cwd = ProjectLocator(context.workspace.root).validation_root(preferred=cwd)
        if validation and not command:
            command = _default_validation_command(cwd)
        if not command:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                ok=False,
                error="command is required",
                error_type="missing_command",
                metadata={"cwd": str(cwd), "validation_command": validation},
            )
        execution_command = _portable_command(command)
        timeout = int(call.arguments.get("timeout_seconds", 180 if validation else 60))
        env = _allowed_environment(context.environment)
        if validation:
            env = _with_validation_pythonpath(env, cwd)
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
        # A validation/test command that finds no tests to run (e.g. pytest exit
        # code 5 in a project without a test suite) is not a real failure: the
        # change is applied and there is nothing to validate. Treat it as
        # satisfied-by-absence so a legitimate edit is not blocked forever, but
        # flag it so the report can note that no tests existed.
        combined = f"{stdout}\n{stderr}".lower()
        # Only pytest's clean "no tests collected" signal (exit code 5 / "no tests
        # ran"), NOT a collection error like ImportError (exit 2, which also prints
        # "collected 0 items / 1 error"). A collection error is a real failure.
        no_tests = (
            bool(validation)
            and not ok
            and process.returncode != 2
            and (process.returncode == 5 or "no tests ran" in combined)
        )
        effective_ok = ok or no_tests
        return ToolResult(
            call_id=call.id,
            name=call.name,
            ok=effective_ok,
            content=_truncate(stdout),
            error=None if effective_ok else _truncate(stderr or stdout),
            error_type=None if effective_ok else "CommandFailed",
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
                "validation_passed": effective_ok if validation else None,
                "no_tests_collected": no_tests,
            },
        )
    except Exception as exc:
        return ToolResult(call_id=call.id, name=call.name, ok=False, error=str(exc), error_type=exc.__class__.__name__)


def _allowed_environment(extra: dict[str, str]) -> dict[str, str]:
    keep = {"PATH", "HOME", "LANG", "LC_ALL", "PYTHONPATH"}
    env = {key: value for key, value in os.environ.items() if key in keep}
    env.update(extra)
    return env


def _with_validation_pythonpath(env: dict[str, str], cwd: Path) -> dict[str, str]:
    updated = dict(env)
    candidates = [str(cwd)]
    src_path = cwd / "src"
    if src_path.is_dir():
        candidates.append(str(src_path))
    existing = updated.get("PYTHONPATH", "")
    for value in existing.split(os.pathsep):
        stripped = value.strip()
        if stripped and stripped not in candidates:
            candidates.append(stripped)
    updated["PYTHONPATH"] = os.pathsep.join(candidates)
    return updated


def _portable_command(command: str) -> str:
    try:
        parts = shlex.split(command)
    except ValueError:
        return command
    if not parts or parts[0] != "python":
        return command
    return " ".join([shlex.quote(sys.executable), *[shlex.quote(part) for part in parts[1:]]])


def _command_to_string(raw_command) -> str:
    if raw_command is None:
        return ""
    if isinstance(raw_command, (list, tuple)):
        return " ".join(shlex.quote(str(part)) for part in raw_command if str(part).strip())
    return str(raw_command).strip()


def _default_validation_command(cwd: Path) -> str:
    if (cwd / "pyproject.toml").exists() or any(cwd.rglob("*.py")):
        return "python -m pytest -q"
    if (cwd / "package.json").exists():
        return "npm test"
    if (cwd / "Cargo.toml").exists():
        return "cargo test"
    if (cwd / "go.mod").exists():
        return "go test ./..."
    if (cwd / "gradlew").exists():
        return "./gradlew test"
    if (cwd / "pom.xml").exists():
        return "mvn test"
    return ""
