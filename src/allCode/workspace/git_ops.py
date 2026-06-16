"""Git auto-commit and single-step undo for allCode-made changes.

allCode-made commits carry a trailer (``allCode-auto-commit: 1``) so ``/undo``
can verify the tip commit is allCode's before reverting it — a user's own
commits are never touched.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

_MARKER = "allCode-auto-commit: 1"
_TIMEOUT = 10


@dataclass
class GitActionResult:
    ok: bool
    message: str
    sha: str | None = None


def _run(root: Path, args: list[str], timeout: int = _TIMEOUT) -> subprocess.CompletedProcess | None:
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


def is_git_repo(root: str | Path) -> bool:
    result = _run(Path(root), ["rev-parse", "--is-inside-work-tree"], timeout=3)
    return bool(result and result.returncode == 0 and result.stdout.strip() == "true")


def working_tree_diff(root: str | Path, *, max_chars: int = 12000) -> str:
    """Return a unified diff of uncommitted changes (staged + unstaged + new
    files), for a /review-style overview of what the agent changed."""

    base = Path(root)
    if not is_git_repo(base):
        return "git 저장소가 아니어서 변경 사항을 비교할 수 없습니다."
    _run(base, ["add", "-N", "."])  # include new files in the diff
    result = _run(base, ["--no-pager", "diff", "--stat"], timeout=15)
    diff = _run(base, ["--no-pager", "diff"], timeout=15)
    if result is None or diff is None:
        return "git diff를 실행할 수 없습니다."
    stat = result.stdout.strip()
    body = diff.stdout
    if not stat and not body.strip():
        return "커밋되지 않은 변경 사항이 없습니다."
    if len(body) > max_chars:
        body = body[:max_chars].rstrip() + "\n... (diff truncated) ..."
    return f"```\n{stat}\n```\n\n```diff\n{body}\n```"


def working_tree_dirty(root: str | Path) -> bool:
    result = _run(Path(root), ["status", "--porcelain"], timeout=5)
    return bool(result and result.returncode == 0 and result.stdout.strip())


def head_subject(root: str | Path) -> str:
    result = _run(Path(root), ["log", "-1", "--pretty=%s"], timeout=5)
    return result.stdout.strip() if result and result.returncode == 0 else ""


def _head_body(root: Path) -> str:
    result = _run(root, ["log", "-1", "--pretty=%B"], timeout=5)
    return result.stdout if result and result.returncode == 0 else ""


def head_is_allcode_commit(root: str | Path) -> bool:
    return _MARKER in _head_body(Path(root))


def commit_all(root: str | Path, message: str) -> GitActionResult:
    """Stage everything and create an allCode-marked commit. No-op when clean."""
    workspace = Path(root)
    if not is_git_repo(workspace):
        return GitActionResult(ok=False, message="git 저장소가 아닙니다.")
    if not working_tree_dirty(workspace):
        return GitActionResult(ok=False, message="커밋할 변경이 없습니다.")
    add = _run(workspace, ["add", "-A"])
    if add is None or add.returncode != 0:
        return GitActionResult(ok=False, message="git add 실패")
    full_message = f"{message.strip()}\n\n{_MARKER}"
    commit = _run(workspace, ["commit", "-m", full_message, "--no-verify"])
    if commit is None or commit.returncode != 0:
        detail = (commit.stderr.strip() if commit else "") or "git commit 실패"
        return GitActionResult(ok=False, message=detail)
    sha = head_subject(workspace)
    head = _run(workspace, ["rev-parse", "--short", "HEAD"])
    short = head.stdout.strip() if head and head.returncode == 0 else None
    return GitActionResult(ok=True, message=f"커밋 생성: {sha}", sha=short)


def undo_last_allcode_commit(root: str | Path) -> GitActionResult:
    """Reset the tip commit if (and only if) it is an allCode auto-commit.

    Uses ``reset --hard HEAD~1`` to remove the commit and restore the prior file
    state. Refuses when the tip is not an allCode commit so user history is safe.
    """
    workspace = Path(root)
    if not is_git_repo(workspace):
        return GitActionResult(ok=False, message="git 저장소가 아닙니다.")
    if not head_is_allcode_commit(workspace):
        return GitActionResult(ok=False, message="가장 최근 커밋이 allCode 자동 커밋이 아니어서 되돌리지 않았습니다.")
    subject = head_subject(workspace)
    reset = _run(workspace, ["reset", "--hard", "HEAD~1"])
    if reset is None or reset.returncode != 0:
        return GitActionResult(ok=False, message="git reset 실패")
    return GitActionResult(ok=True, message=f"되돌렸습니다: {subject}")
