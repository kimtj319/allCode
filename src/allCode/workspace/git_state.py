"""Small git dirty-state summaries for final reports."""

from __future__ import annotations

import subprocess
from collections.abc import Iterable
from pathlib import Path

from pydantic import Field

from allCode.core.models import CoreModel
from allCode.core.result import CompletionEvidence


class GitDirtySummary(CoreModel):
    is_repo: bool = False
    root: str
    changed_paths: list[str] = Field(default_factory=list)
    summary: str = ""


def summarize_git_state(root: str | Path, paths: Iterable[str] | None = None) -> GitDirtySummary:
    workspace = Path(root).expanduser().resolve()
    if not _is_git_repo(workspace):
        return GitDirtySummary(root=str(workspace), is_repo=False)
    filtered_paths = [path for path in (paths or []) if path]
    command = ["git", "-C", str(workspace), "status", "--short"]
    if filtered_paths:
        command.extend(["--", *filtered_paths])
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=3, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return GitDirtySummary(root=str(workspace), is_repo=True, summary="git status를 확인하지 못했습니다.")
    if completed.returncode != 0:
        return GitDirtySummary(root=str(workspace), is_repo=True, summary="git status를 확인하지 못했습니다.")
    changed = [_path_from_status(line) for line in completed.stdout.splitlines() if line.strip()]
    changed = [path for path in changed if path]
    if not changed:
        return GitDirtySummary(root=str(workspace), is_repo=True, changed_paths=[])
    return GitDirtySummary(
        root=str(workspace),
        is_repo=True,
        changed_paths=changed,
        summary="Git 변경 요약:\n" + "\n".join(f"- {path}" for path in changed[:20]),
    )


def append_git_summary(final_answer: str, *, workspace_root: str, evidence: CompletionEvidence) -> str:
    paths = [*evidence.changed_files, *evidence.created_files, *evidence.deleted_files]
    if not paths:
        return final_answer
    summary = summarize_git_state(workspace_root, paths)
    if not summary.is_repo or not summary.summary or summary.summary in final_answer:
        return final_answer
    return final_answer.rstrip() + "\n\n" + summary.summary


def _is_git_repo(workspace: Path) -> bool:
    try:
        completed = subprocess.run(
            ["git", "-C", str(workspace), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0 and completed.stdout.strip() == "true"


def _path_from_status(line: str) -> str:
    value = line[3:].strip() if len(line) > 3 else line.strip()
    if " -> " in value:
        value = value.rsplit(" -> ", 1)[-1].strip()
    return value
