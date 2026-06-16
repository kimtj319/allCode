"""Generate an AGENTS.md draft by inspecting the workspace.

Backs the ``/init`` command (the Codex/Gemini onboarding affordance): detect the
languages, build/test commands and top-level layout so the agent has standing
project context on every future session. Fully deterministic — no model call —
so it is fast and testable.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

_LANG_BY_SUFFIX = {
    ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript",
    ".jsx": "JavaScript", ".go": "Go", ".rs": "Rust", ".java": "Java", ".kt": "Kotlin",
    ".rb": "Ruby", ".php": "PHP", ".cs": "C#", ".c": "C", ".cpp": "C++", ".swift": "Swift",
}
_IGNORE_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "__pycache__", "node_modules", "dist",
    "build", "target", ".idea", ".vscode", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".allCode", ".allcode", "htmlcov",
}


def _detect_commands(root: Path) -> list[tuple[str, str]]:
    """Return (label, command) build/test hints from manifest files present."""
    commands: list[tuple[str, str]] = []
    if (root / "pyproject.toml").exists() or (root / "setup.py").exists() or any(root.glob("*.py")):
        commands.append(("Test", "python -m pytest"))
    if (root / "package.json").exists():
        commands.append(("Test", "npm test"))
        commands.append(("Build", "npm run build"))
    if (root / "Cargo.toml").exists():
        commands.append(("Test", "cargo test"))
        commands.append(("Build", "cargo build"))
    if (root / "go.mod").exists():
        commands.append(("Test", "go test ./..."))
    if (root / "pom.xml").exists():
        commands.append(("Test", "mvn test"))
    if (root / "gradlew").exists():
        commands.append(("Test", "./gradlew test"))
    # De-dup preserving order.
    seen: set[tuple[str, str]] = set()
    unique: list[tuple[str, str]] = []
    for item in commands:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def _detect_languages(root: Path, *, max_files: int = 4000) -> list[str]:
    counts: Counter[str] = Counter()
    scanned = 0
    for path in root.rglob("*"):
        if scanned >= max_files:
            break
        if any(part in _IGNORE_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        lang = _LANG_BY_SUFFIX.get(path.suffix.lower())
        if lang:
            counts[lang] += 1
            scanned += 1
    return [lang for lang, _ in counts.most_common(4)]


def _top_level(root: Path, *, limit: int = 20) -> list[str]:
    entries: list[str] = []
    try:
        for child in sorted(root.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            if child.name in _IGNORE_DIRS or child.name.startswith("."):
                continue
            entries.append(child.name + ("/" if child.is_dir() else ""))
    except OSError:
        return []
    return entries[:limit]


def build_agents_md(project_root: str | Path) -> str:
    """Build an AGENTS.md draft string from on-disk project signals."""
    root = Path(project_root).expanduser()
    name = root.resolve().name or "project"
    languages = _detect_languages(root)
    commands = _detect_commands(root)
    structure = _top_level(root)

    lines = [
        f"# {name}",
        "",
        "> allCode `/init`로 생성된 초안입니다. 프로젝트에 맞게 수정하세요.",
        "",
        "## 개요",
        f"- 주요 언어: {', '.join(languages) if languages else '(감지되지 않음)'}",
        "",
        "## 빌드 / 테스트 명령",
    ]
    if commands:
        lines.extend(f"- {label}: `{command}`" for label, command in commands)
    else:
        lines.append("- (감지된 매니페스트가 없습니다 — 빌드/테스트 명령을 직접 적어주세요.)")
    lines += ["", "## 디렉터리 구조 (최상위)"]
    if structure:
        lines.append("```")
        lines.extend(structure)
        lines.append("```")
    else:
        lines.append("- (비어 있음)")
    lines += [
        "",
        "## 컨벤션 / 에이전트 지침",
        "- (코드 스타일, 금지 사항, 자주 쓰는 워크플로 등을 여기에 추가하세요.)",
        "",
    ]
    return "\n".join(lines)
