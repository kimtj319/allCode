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


def _current_branch(root: Path) -> str:
    result = _run(root, ["rev-parse", "--abbrev-ref", "HEAD"], timeout=5)
    return result.stdout.strip() if result and result.returncode == 0 else ""


def derive_commit_message(root: str | Path) -> str:
    """Heuristic Conventional-Commit message from the staged/working changes.

    Classifies by the paths that changed (tests/docs/build vs source) so the
    auto-commit and PR flows get a meaningful default message without a model
    call. e.g. ``test: update 2 files``, ``docs: update README.md``."""
    workspace = Path(root)
    _run(workspace, ["add", "-N", "."])
    result = _run(workspace, ["--no-pager", "diff", "--name-only", "HEAD"], timeout=10)
    files = [line.strip() for line in (result.stdout.splitlines() if result else []) if line.strip()]
    if not files:
        status = _run(workspace, ["status", "--porcelain"], timeout=5)
        files = [line[3:].strip() for line in (status.stdout.splitlines() if status else []) if line.strip()]
    if not files:
        return "chore: update workspace"
    lowered = [f.lower() for f in files]
    if all("test" in f for f in lowered):
        kind = "test"
    elif all(f.endswith((".md", ".rst", ".txt")) for f in lowered):
        kind = "docs"
    elif any(f.endswith((".toml", ".cfg", ".ini", ".yaml", ".yml", "requirements.txt")) for f in lowered):
        kind = "build"
    else:
        kind = "chore"
    if len(files) == 1:
        return f"{kind}: update {files[0]}"
    return f"{kind}: update {len(files)} files"


def create_pull_request(root: str | Path, *, title: str | None = None, body: str | None = None) -> GitActionResult:
    """Commit pending changes, push the branch, and open a PR via the gh CLI.

    Refuses on the default branch (main/master) so a PR always has a feature
    branch. Requires the GitHub CLI (`gh`) to be installed and authenticated."""
    workspace = Path(root)
    if not is_git_repo(workspace):
        return GitActionResult(ok=False, message="git 저장소가 아닙니다.")
    branch = _current_branch(workspace)
    if branch in {"main", "master", ""}:
        return GitActionResult(ok=False, message=f"기본 브랜치('{branch}')에서는 PR을 만들 수 없습니다. 먼저 새 브랜치를 만드세요.")
    if working_tree_dirty(workspace):
        commit = commit_all(workspace, title or derive_commit_message(workspace))
        if not commit.ok:
            return commit
    push = _run(workspace, ["push", "-u", "origin", branch], timeout=60)
    if push is None or push.returncode != 0:
        detail = (push.stderr.strip() if push else "") or "git push 실패"
        return GitActionResult(ok=False, message=f"브랜치 푸시 실패: {detail}")
    args = ["pr", "create"]
    if title:
        args += ["--title", title, "--body", body or ""]
    else:
        args += ["--fill"]
    try:
        completed = subprocess.run(["gh", "-C", str(workspace), *args], capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return GitActionResult(ok=False, message=f"gh 실행 실패(설치/인증 확인): {exc}")
    if completed.returncode != 0:
        return GitActionResult(ok=False, message=(completed.stderr.strip() or "gh pr create 실패"))
    url = completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else ""
    return GitActionResult(ok=True, message=f"PR을 생성했습니다: {url}", sha=branch)


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
