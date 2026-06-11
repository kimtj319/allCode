"""Workspace-aware validation repair target ranking."""

from __future__ import annotations

from pathlib import Path

from allCode.core.result import CompletionEvidence, RepairTarget


def rank_repair_targets(
    targets: list[RepairTarget],
    *,
    evidence: CompletionEvidence,
    workspace_root: str,
) -> list[RepairTarget]:
    """Rank validation targets by repair usefulness without scenario-specific paths."""

    changed = {
        _relative_path(path, workspace_root=workspace_root)
        for path in [*evidence.created_files, *evidence.changed_files]
        if path
    }

    def score(target: RepairTarget) -> tuple[int, str]:
        relative = _relative_path(target.file_path, workspace_root=workspace_root)
        lowered = relative.lower()
        value = 0
        if target.reason in {"traceback", "pytest_failed_item", "pytest_failed_file", "path_line"}:
            value += 400
        if target.reason == "missing_module":
            value += 500
        if relative in changed:
            value += 300
        if lowered.startswith("tests/") or "/tests/" in lowered or Path(lowered).name.startswith("test_"):
            value += 200
        if target.line_number is not None:
            value += 50
        if _looks_external_runtime(target.file_path, workspace_root=workspace_root):
            value -= 600
        if any(symbol in {"SyntaxError", "IndentationError"} for symbol in evidence.validation_failure_symbols):
            if target.reason in {"traceback", "path_line"}:
                value += 150
        return (-value, relative)

    ranked: list[RepairTarget] = []
    for target in sorted(targets, key=score):
        normalized = _relative_path(target.file_path, workspace_root=workspace_root)
        copied = target.model_copy(update={"file_path": normalized})
        key = (copied.file_path, copied.line_number, copied.symbol)
        if not any((item.file_path, item.line_number, item.symbol) == key for item in ranked):
            ranked.append(copied)
    return ranked


def _relative_path(path: str, *, workspace_root: str) -> str:
    raw = str(path or "").replace("\\", "/").strip()
    if not raw:
        return ""
    candidate = Path(raw)
    if not candidate.is_absolute():
        return candidate.as_posix()
    try:
        return candidate.expanduser().resolve().relative_to(Path(workspace_root).expanduser().resolve()).as_posix()
    except (OSError, ValueError):
        return candidate.as_posix()


def _looks_external_runtime(path: str, *, workspace_root: str) -> bool:
    raw = str(path or "")
    lowered = raw.lower().replace("\\", "/")
    if not Path(raw).is_absolute():
        return False
    try:
        Path(raw).expanduser().resolve().relative_to(Path(workspace_root).expanduser().resolve())
        return False
    except (OSError, ValueError):
        pass
    markers = ("/site-packages/", "/dist-packages/", "/lib/python", "/python.framework/")
    return any(marker in lowered for marker in markers)
