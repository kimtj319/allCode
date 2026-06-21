"""Background shell job registry.

``run_command(background=true)`` launches a long-running process (a dev server,
a watcher, a build) without blocking the turn, and returns a ``job_id``. The
agent then polls ``get_command_output`` and ends it with ``kill_command`` — the
BashOutput/KillBash pattern from Claude Code.

Processes use ``subprocess.Popen`` with daemon reader threads rather than
asyncio, so a job survives across per-turn event loops and stays reachable for
the life of the session.
"""

from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass, field


@dataclass
class BackgroundJob:
    job_id: str
    command: str
    cwd: str
    popen: subprocess.Popen
    _stdout: list[str] = field(default_factory=list)
    _stderr: list[str] = field(default_factory=list)
    _stdout_cursor: int = 0
    _stderr_cursor: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _readers: list[threading.Thread] = field(default_factory=list)

    def start_readers(self) -> None:
        if self.popen.stdout is not None:
            self._spawn_reader(self.popen.stdout, self._stdout)
        if self.popen.stderr is not None:
            self._spawn_reader(self.popen.stderr, self._stderr)

    def _spawn_reader(self, stream, buffer: list[str]) -> None:
        thread = threading.Thread(target=self._pump, args=(stream, buffer), daemon=True)
        self._readers.append(thread)
        thread.start()

    def ensure_drained(self, timeout: float = 2.0) -> None:
        """Once the process has exited, join the reader threads so the final
        output flushed at exit is in the buffers before it is read. Without this,
        poll() can report 'exited' while the pump threads still hold the last
        lines, and a single get_command_output would miss the tail."""
        if self.returncode() is None:
            return
        for thread in self._readers:
            thread.join(timeout=timeout)

    def _pump(self, stream, buffer: list[str]) -> None:
        try:
            for line in iter(stream.readline, ""):
                with self._lock:
                    buffer.append(line)
        except (ValueError, OSError):
            return

    def read_new(self) -> tuple[str, str]:
        """Return stdout/stderr appended since the previous read, advancing cursors."""
        with self._lock:
            out = "".join(self._stdout[self._stdout_cursor :])
            err = "".join(self._stderr[self._stderr_cursor :])
            self._stdout_cursor = len(self._stdout)
            self._stderr_cursor = len(self._stderr)
        return out, err

    def returncode(self) -> int | None:
        return self.popen.poll()

    def running(self) -> bool:
        return self.returncode() is None

    def kill(self) -> None:
        if self.running():
            self.popen.terminate()
            try:
                self.popen.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.popen.kill()


class BackgroundJobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, BackgroundJob] = {}
        self._counter = 0
        self._lock = threading.Lock()

    def register(self, command: str, cwd: str, popen: subprocess.Popen) -> BackgroundJob:
        with self._lock:
            self._counter += 1
            job_id = f"job_{self._counter}"
        job = BackgroundJob(job_id=job_id, command=command, cwd=cwd, popen=popen)
        job.start_readers()
        self._jobs[job_id] = job
        return job

    def get(self, job_id: str) -> BackgroundJob | None:
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[BackgroundJob]:
        return list(self._jobs.values())


# Session-scoped registry shared by the shell tools.
JOBS = BackgroundJobRegistry()
