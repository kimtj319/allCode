"""Opt-in lint/typecheck validation candidates.

Codex and aider run a project's configured linter/typechecker as part of the
edit→validate loop, not just its tests. We mirror that, but conservatively: a
lint/typecheck command is only added when the project *opts in* by carrying the
tool's config on disk (e.g. ``[tool.ruff]`` in ``pyproject.toml``, an
``eslint`` config, a ``tsconfig.json``). Freshly generated scaffolds without
such config are unaffected, so we never manufacture a spurious failure.
"""

from __future__ import annotations

from pathlib import Path

from allCode.agent.task_plan import ValidationCommand

_PYPROJECT = "pyproject.toml"


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _ruff_configured(root: Path, pyproject: str) -> bool:
    if "[tool.ruff]" in pyproject or "[tool.ruff." in pyproject:
        return True
    return (root / "ruff.toml").exists() or (root / ".ruff.toml").exists()


def _mypy_configured(root: Path, pyproject: str) -> bool:
    if "[tool.mypy]" in pyproject:
        return True
    return (root / "mypy.ini").exists() or (root / ".mypy.ini").exists()


def _eslint_configured(root: Path) -> bool:
    names = (
        ".eslintrc",
        ".eslintrc.js",
        ".eslintrc.cjs",
        ".eslintrc.json",
        ".eslintrc.yml",
        ".eslintrc.yaml",
        "eslint.config.js",
        "eslint.config.mjs",
        "eslint.config.cjs",
    )
    return any((root / name).exists() for name in names)


def syntax_check_candidates(target_root: str, *, environment: dict[str, str] | None = None) -> list[ValidationCommand]:
    """Always-on, dependency-free Python diagnostic.

    Byte-compiles every ``.py`` under the target (without executing it) via
    ``compileall``, so a syntactically broken edit fails validation and triggers
    the repair loop even when the project has no tests, ruff, or mypy. This is
    the lightweight stand-in for editor/LSP diagnostics on the edit→validate loop.
    """

    root = Path(target_root).expanduser()
    if not root.is_dir():
        return []
    has_python = any(
        part not in {".venv", "venv", "__pycache__", "node_modules", ".git"}
        for path in root.rglob("*.py")
        for part in (path.relative_to(root).parts[0],)
    )
    if not has_python:
        return []
    env = dict(environment or {})
    return [ValidationCommand(command="python -m compileall -q .", cwd=target_root, environment=env)]


def lint_candidates(target_root: str, *, environment: dict[str, str] | None = None) -> list[ValidationCommand]:
    """Return lint/typecheck commands the project has opted into, in run order.

    Lint/typecheck runs before tests so style/type regressions surface (and
    trigger repair) before the slower test step.
    """

    root = Path(target_root).expanduser()
    if not root.is_dir():
        return []
    env = dict(environment or {})
    commands: list[ValidationCommand] = []

    pyproject = _read(root / _PYPROJECT)
    if _ruff_configured(root, pyproject):
        commands.append(ValidationCommand(command="python -m ruff check .", cwd=target_root, environment=env))
    if _mypy_configured(root, pyproject):
        commands.append(ValidationCommand(command="python -m mypy .", cwd=target_root, environment=env))

    if (root / "tsconfig.json").exists():
        commands.append(ValidationCommand(command="npx --no-install tsc --noEmit", cwd=target_root, environment=env))
    if _eslint_configured(root):
        commands.append(ValidationCommand(command="npx --no-install eslint .", cwd=target_root, environment=env))

    return commands
