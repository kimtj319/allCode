"""Builtin shell and validation tools."""

from __future__ import annotations

import asyncio
import os
import shlex
import subprocess
import sys
from pathlib import Path

from allCode.core.event_bus import EventBus
from allCode.core.models import ToolCall, ToolResult
from allCode.tools.base import ToolContext, ToolDefinition
from allCode.tools.builtin.background_jobs import JOBS
from allCode.tools.builtin.file_ops import resolve_under_root
from allCode.tools.builtin.shell_sandbox import sandbox_command
from allCode.workspace.project_locator import ProjectLocator

MAX_STREAM_CHARS = 20_000


def _truncate(value: str, limit: int = MAX_STREAM_CHARS) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "\n[truncated]"


class RunCommandTool:
    definition = ToolDefinition(
        name="run_command",
        description=(
            "Run a non-interactive shell command in the workspace. Set background=true to "
            "launch a long-running process (dev server, watcher) without blocking; it returns "
            "a job_id to poll with get_command_output and stop with kill_command."
        ),
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "cwd": {"type": "string"},
                "timeout_seconds": {"type": "integer"},
                "background": {"type": "boolean"},
            },
            "required": ["command"],
            "additionalProperties": False,
        },
        read_only=True,
        requires_approval=True,
        group="shell",
    )

    def __init__(self, *, shell_sandbox: str = "off") -> None:
        self._shell_sandbox = shell_sandbox

    async def run(self, call: ToolCall, context: ToolContext, event_bus: EventBus | None = None) -> ToolResult:
        if bool(call.arguments.get("background")):
            return run_background_call(call, context)
        return await run_shell_call(call, context, validation=False, sandbox_mode=self._shell_sandbox)


_SHELL_VERBS = {
    "rm", "rmdir", "unlink", "del", "mv", "cp", "cat", "ls", "touch", "mkdir",
    "python", "python3", "pytest", "pip", "git", "echo", "node", "npm", "make",
}


def _unknown_job_error(call: ToolCall, job_id: str) -> ToolResult:
    """A job_id miss is often the model passing a COMMAND where a job id belongs
    (e.g. get_command_output(job_id='rm foo.py')). Redirect to the right tool so
    the model self-corrects instead of repeating until the loop guard fires."""
    token = job_id.strip()
    first = token.split()[0] if token else ""
    looks_like_command = (" " in token) or (first in _SHELL_VERBS)
    known = [j.job_id for j in JOBS.list_jobs()]
    msg = f"unknown job: {job_id}. job_id must be an id returned by run_command(background=true) (e.g. 'job_1')"
    if known:
        msg += f"; active jobs: {', '.join(known)}"
    if looks_like_command:
        msg += (
            ", not a command string. To DELETE a file or directory use delete_path(path=...); "
            "to run a one-off shell command use run_command(command=...)."
        )
    else:
        msg += "."
    return ToolResult(call_id=call.id, name=call.name, ok=False, error=msg, error_type="unknown_job")


class GetCommandOutputTool:
    definition = ToolDefinition(
        name="get_command_output",
        description="Return new stdout/stderr from a background job (started via run_command background=true) since the last poll.",
        parameters={
            "type": "object",
            "properties": {"job_id": {"type": "string"}},
            "required": ["job_id"],
            "additionalProperties": False,
        },
        read_only=True,
        group="shell",
    )

    async def run(self, call: ToolCall, context: ToolContext, event_bus: EventBus | None = None) -> ToolResult:
        job_id = str(call.arguments.get("job_id", ""))
        job = JOBS.get(job_id)
        if job is None:
            return _unknown_job_error(call, job_id)
        out, err = job.read_new()
        running = job.running()
        status = "running" if running else f"exited (code {job.returncode()})"
        body = _truncate(out)
        if err.strip():
            body = f"{body}\n[stderr]\n{_truncate(err)}" if body.strip() else f"[stderr]\n{_truncate(err)}"
        return ToolResult(
            call_id=call.id,
            name=call.name,
            ok=True,
            content=f"[{status}]\n{body}" if body.strip() else f"[{status}] (no new output)",
            metadata={"job_id": job_id, "running": running, "returncode": job.returncode()},
        )


class KillCommandTool:
    definition = ToolDefinition(
        name="kill_command",
        description="Terminate a background job started via run_command background=true.",
        parameters={
            "type": "object",
            "properties": {"job_id": {"type": "string"}},
            "required": ["job_id"],
            "additionalProperties": False,
        },
        read_only=False,
        group="shell",
    )

    async def run(self, call: ToolCall, context: ToolContext, event_bus: EventBus | None = None) -> ToolResult:
        job_id = str(call.arguments.get("job_id", ""))
        job = JOBS.get(job_id)
        if job is None:
            return _unknown_job_error(call, job_id)
        job.kill()
        return ToolResult(
            call_id=call.id,
            name=call.name,
            ok=True,
            content=f"terminated {job_id} (code {job.returncode()})",
            metadata={"job_id": job_id, "running": job.running(), "returncode": job.returncode()},
        )


def run_background_call(call: ToolCall, context: ToolContext) -> ToolResult:
    try:
        cwd = resolve_under_root(context.workspace.root, str(call.arguments.get("cwd", ".")))
        command = _command_to_string(call.arguments.get("command"))
        if not command:
            return ToolResult(call_id=call.id, name=call.name, ok=False, error="command is required", error_type="missing_command")
        execution_command = _portable_command(command)
        env = _allowed_environment(context.environment)
        popen = subprocess.Popen(
            execution_command,
            shell=True,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            bufsize=1,
        )
        job = JOBS.register(command=command, cwd=str(cwd), popen=popen)
        return ToolResult(
            call_id=call.id,
            name=call.name,
            ok=True,
            content=f"started background job {job.job_id}: {command}\nPoll with get_command_output(job_id='{job.job_id}'), stop with kill_command.",
            metadata={
                "job_id": job.job_id,
                "command": command,
                "cwd": str(cwd),
                "background": True,
                "observation": {"kind": "background_job", "target": command, "summary": f"background {job.job_id}", "risk": "medium"},
            },
        )
    except Exception as exc:
        return ToolResult(call_id=call.id, name=call.name, ok=False, error=str(exc), error_type=exc.__class__.__name__)


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

    def __init__(self, *, shell_sandbox: str = "off") -> None:
        self._shell_sandbox = shell_sandbox

    async def run(self, call: ToolCall, context: ToolContext, event_bus: EventBus | None = None) -> ToolResult:
        return await run_shell_call(call, context, validation=True, sandbox_mode=self._shell_sandbox)


async def run_shell_call(
    call: ToolCall, context: ToolContext, *, validation: bool, sandbox_mode: str = "off"
) -> ToolResult:
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
        sandboxed = sandbox_command(execution_command, workspace_root=Path(context.workspace.root), mode=sandbox_mode)
        if sandboxed is not None:
            execution_command = sandboxed
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
