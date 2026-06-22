"""Parallel multi-agent orchestration with git-worktree isolation and merge.

Runs several independent implementation sub-tasks CONCURRENTLY, each in its own
git worktree branched from a common base commit, so the agents never clobber one
another. Their branches are then integrated sequentially with ``git merge`` —
non-overlapping edits merge automatically (the common case); genuine line-level
conflicts are handed to an optional resolver, and any that remain are isolated
and reported rather than silently mangled.

Safety: the orchestrator never touches the user's current branch or working tree.
All work happens in temporary worktrees/branches off ``base_ref``; the merged
result lands on a dedicated integration branch that the caller adopts explicitly.
Worktrees and per-task branches are always cleaned up.

The LLM is intentionally NOT referenced here. Callers inject a ``runner`` (and an
optional ``conflict_resolver``); the production wiring builds those from sub-agents
that use ONLY the models named in config — this module stays model-agnostic and
deterministically testable with a fake runner.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

_TIMEOUT = 30


@dataclass
class ParallelTaskSpec:
    """One independent sub-task to run in isolation."""

    id: str
    description: str


@dataclass
class RunnerResult:
    """What a task runner reports back after working inside its worktree."""

    ok: bool
    summary: str = ""


# A runner edits files inside the given worktree for the given task and returns
# how it went. It must confine its writes to the worktree path.
Runner = Callable[[ParallelTaskSpec, Path], Awaitable[RunnerResult]]

# A conflict resolver is given the integration worktree and the list of
# conflicted (unmerged) file paths; it should resolve the markers in place and
# return True when the tree is fully resolved. Returning False (or raising)
# leaves the conflict for safe isolation.
ConflictResolver = Callable[[Path, list[str]], Awaitable[bool]]


@dataclass
class ParallelTaskOutcome:
    id: str
    description: str
    status: str  # running|empty|applied|conflict|error|skipped
    summary: str = ""
    files: list[str] = field(default_factory=list)
    detail: str = ""


@dataclass
class ParallelRunReport:
    base_ref: str
    integration_branch: str | None
    outcomes: list[ParallelTaskOutcome]
    merged_files: list[str] = field(default_factory=list)

    @property
    def applied(self) -> list[ParallelTaskOutcome]:
        return [o for o in self.outcomes if o.status == "applied"]

    @property
    def conflicts(self) -> list[ParallelTaskOutcome]:
        return [o for o in self.outcomes if o.status == "conflict"]

    def board(self) -> str:
        """A compact session-board summary of every parallel task."""
        icon = {"applied": "✓", "empty": "·", "conflict": "⚠", "error": "✗", "skipped": "—"}
        lines = ["병렬 작업 보드:"]
        for o in self.outcomes:
            mark = icon.get(o.status, "?")
            head = f"  [{mark}] {o.id}: {o.description.strip()[:60]}  → {o.status}"
            lines.append(head)
            if o.files:
                lines.append(f"        files: {', '.join(o.files[:6])}" + (" …" if len(o.files) > 6 else ""))
            if o.detail:
                lines.append(f"        {o.detail}")
        if self.integration_branch and self.merged_files:
            lines.append(f"통합 브랜치: {self.integration_branch} ({len(self.merged_files)}개 파일)")
            lines.append(f"채택: git merge {self.integration_branch}  ·  검토: git diff {self.base_ref[:8]}..{self.integration_branch}")
        elif self.integration_branch:
            lines.append(f"통합 브랜치: {self.integration_branch} (병합된 변경 없음)")
        if self.conflicts:
            ids = ", ".join(o.id for o in self.conflicts)
            lines.append(f"충돌로 통합 보류된 작업: {ids} (각 작업 브랜치는 보존됨)")
        return "\n".join(lines)


def _git(root: Path, args: list[str], timeout: int = _TIMEOUT) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _ok(proc: subprocess.CompletedProcess | None) -> bool:
    return bool(proc and proc.returncode == 0)


def _head_sha(root: Path) -> str | None:
    proc = _git(root, ["rev-parse", "HEAD"], timeout=5)
    return proc.stdout.strip() if _ok(proc) else None


def _is_git_repo(root: Path) -> bool:
    proc = _git(root, ["rev-parse", "--is-inside-work-tree"], timeout=5)
    return _ok(proc) and proc.stdout.strip() == "true"


def _worktree_dirty(root: Path) -> bool:
    proc = _git(root, ["status", "--porcelain"], timeout=10)
    return _ok(proc) and bool(proc.stdout.strip())


def _changed_files(worktree: Path, base_ref: str) -> list[str]:
    proc = _git(worktree, ["--no-pager", "diff", "--name-only", base_ref, "HEAD"], timeout=15)
    if not _ok(proc):
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _unmerged_files(worktree: Path) -> list[str]:
    proc = _git(worktree, ["--no-pager", "diff", "--name-only", "--diff-filter=U"], timeout=10)
    if not _ok(proc):
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


class _Cleanup:
    """Tracks worktrees/branches to remove, so a partial run never leaks them."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._worktrees: list[Path] = []
        self._branches: list[str] = []

    def track_worktree(self, path: Path) -> None:
        self._worktrees.append(path)

    def track_branch(self, name: str) -> None:
        self._branches.append(name)

    def run(self, *, keep_branches: Sequence[str] = ()) -> None:
        for path in self._worktrees:
            _git(self._root, ["worktree", "remove", "--force", str(path)], timeout=20)
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)
        _git(self._root, ["worktree", "prune"], timeout=10)
        keep = set(keep_branches)
        for name in self._branches:
            if name in keep:
                continue
            _git(self._root, ["branch", "-D", name], timeout=10)


async def run_parallel_tasks(
    tasks: Sequence[ParallelTaskSpec],
    *,
    workspace_root: str | Path,
    runner: Runner,
    max_concurrency: int = 4,
    branch_prefix: str = "allcode/par",
    conflict_resolver: ConflictResolver | None = None,
    base_ref: str | None = None,
) -> ParallelRunReport:
    """Run ``tasks`` concurrently in isolated worktrees, then integrate them.

    Raises ValueError when the workspace is not a usable git repo (no HEAD), so
    the caller can fall back to sequential execution.
    """
    root = Path(workspace_root).expanduser().resolve()
    if not _is_git_repo(root):
        raise ValueError("parallel orchestration requires a git repository")
    resolved_base = base_ref or _head_sha(root)
    if not resolved_base:
        raise ValueError("parallel orchestration requires at least one commit (no HEAD)")

    specs = list(tasks)
    cleanup = _Cleanup(root)
    worktrees_root = root / ".allCode" / "parallel"
    worktrees_root.mkdir(parents=True, exist_ok=True)
    integration_branch = f"{branch_prefix}-integration-{resolved_base[:8]}"

    try:
        # 1) create one isolated worktree+branch per task
        prepared: list[tuple[ParallelTaskSpec, Path, str]] = []
        for index, spec in enumerate(specs):
            branch = f"{branch_prefix}-{index}-{spec.id}"
            wt = worktrees_root / f"{index}-{spec.id}"
            shutil.rmtree(wt, ignore_errors=True)
            _git(root, ["branch", "-D", branch], timeout=10)  # clear any stale branch
            add = _git(root, ["worktree", "add", "-b", branch, str(wt), resolved_base], timeout=30)
            if not _ok(add):
                prepared.append((spec, wt, ""))  # mark unusable
                continue
            cleanup.track_worktree(wt)
            cleanup.track_branch(branch)
            prepared.append((spec, wt, branch))

        # 2) run task runners concurrently (bounded)
        semaphore = asyncio.Semaphore(max(1, max_concurrency))
        outcomes_by_id: dict[str, ParallelTaskOutcome] = {}

        async def _run_one(spec: ParallelTaskSpec, wt: Path, branch: str) -> None:
            if not branch:
                outcomes_by_id[spec.id] = ParallelTaskOutcome(
                    id=spec.id, description=spec.description, status="error", detail="worktree 생성 실패"
                )
                return
            async with semaphore:
                try:
                    result = await runner(spec, wt)
                except Exception as exc:  # noqa: BLE001 - isolate one task's failure
                    outcomes_by_id[spec.id] = ParallelTaskOutcome(
                        id=spec.id, description=spec.description, status="error", detail=str(exc)
                    )
                    return
            # commit whatever the runner changed inside the worktree
            if _worktree_dirty(wt):
                _git(wt, ["add", "-A"], timeout=20)
                _git(wt, ["commit", "-m", f"allcode parallel task {spec.id}", "--no-verify"], timeout=30)
            files = _changed_files(wt, resolved_base)
            status = "applied" if files else "empty"
            if not result.ok and status == "empty":
                status = "error"
            outcomes_by_id[spec.id] = ParallelTaskOutcome(
                id=spec.id, description=spec.description, status=status, summary=result.summary, files=files
            )

        await asyncio.gather(*(_run_one(spec, wt, branch) for spec, wt, branch in prepared))

        # 3) integrate task branches sequentially on a fresh integration worktree
        merged_files: list[str] = []
        integ_wt = worktrees_root / "integration"
        shutil.rmtree(integ_wt, ignore_errors=True)
        _git(root, ["branch", "-D", integration_branch], timeout=10)
        integ_add = _git(root, ["worktree", "add", "-b", integration_branch, str(integ_wt), resolved_base], timeout=30)
        integration_ok = _ok(integ_add)
        if integration_ok:
            cleanup.track_worktree(integ_wt)
            cleanup.track_branch(integration_branch)
            for spec, _wt, branch in prepared:
                outcome = outcomes_by_id.get(spec.id)
                if outcome is None or outcome.status != "applied":
                    continue
                merge = _git(integ_wt, ["merge", "--no-edit", branch], timeout=60)
                if _ok(merge):
                    continue
                # conflict: try the resolver, else abort and isolate this task
                conflicted = _unmerged_files(integ_wt)
                resolved = False
                if conflict_resolver is not None and conflicted:
                    try:
                        resolved = await conflict_resolver(integ_wt, conflicted)
                    except Exception:  # noqa: BLE001
                        resolved = False
                staged = False
                if resolved:
                    # Stage the resolver's edits first; the index only clears its
                    # unmerged (stage>0) entries after `git add`.
                    _git(integ_wt, ["add", "-A"], timeout=20)
                    if not _unmerged_files(integ_wt):
                        commit = _git(integ_wt, ["commit", "--no-edit", "--no-verify"], timeout=30)
                        if _ok(commit):
                            outcome.detail = "충돌 자동 해소됨"
                            staged = True
                if not staged:
                    _git(integ_wt, ["merge", "--abort"], timeout=20)
                    outcome.status = "conflict"
                    outcome.detail = "충돌: " + ", ".join(conflicted[:6])
            merged_files = _changed_files(integ_wt, resolved_base)

        report = ParallelRunReport(
            base_ref=resolved_base,
            integration_branch=integration_branch if integration_ok else None,
            outcomes=[outcomes_by_id[spec.id] for spec in specs if spec.id in outcomes_by_id],
            merged_files=merged_files,
        )
        return report
    finally:
        # Keep the integration branch (the deliverable); remove everything else.
        cleanup.run(keep_branches=[integration_branch])
