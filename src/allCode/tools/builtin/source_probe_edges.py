"""Workspace-relative edge enrichment for source_probe observations."""

from __future__ import annotations

from pathlib import Path

from allCode.workspace.source_intelligence import SourceFileAnalysis, SourceImport, SourceReference

COMMON_SOURCE_PREFIXES = ("src", "lib")


def enriched_outgoing_edges(
    analysis: SourceFileAnalysis,
    *,
    current_file: Path,
    workspace_root: Path,
    max_imports: int = 8,
    max_references: int = 12,
) -> list[dict[str, object]]:
    """Return JSON-safe import/reference edges with optional local target paths."""

    edges: list[dict[str, object]] = []
    import_aliases = _import_alias_targets(
        analysis.imports[:max_imports],
        current_file=current_file,
        workspace_root=workspace_root,
    )
    for item in analysis.imports[:max_imports]:
        target = _import_display_target(item)
        resolved = _resolve_import_target(item.module, current_file=current_file, workspace_root=workspace_root)
        if not resolved and item.names:
            resolved = _resolve_named_import(item.module, item.names, current_file=current_file, workspace_root=workspace_root)
        edge = {
            "kind": "import",
            "target": target,
            "raw_target": item.module,
            "line": item.line,
        }
        if resolved:
            edge["resolved_target"] = resolved
        edges.append(edge)
    for item in analysis.references[:max_references]:
        if item.kind not in {"call", "inheritance", "reference"}:
            continue
        symbol_root = item.symbol.split(".", 1)[0]
        resolved = import_aliases.get(symbol_root)
        edge = {
            "kind": item.kind,
            "symbol": item.symbol,
            "target": item.target_hint or item.symbol,
            "line": item.line,
        }
        if resolved:
            edge["resolved_target"] = resolved
        edges.append(edge)
    return _dedupe_edges(edges)[: max_imports + max_references]


def _import_alias_targets(
    imports: list[SourceImport],
    *,
    current_file: Path,
    workspace_root: Path,
) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for item in imports:
        module_target = _resolve_import_target(item.module, current_file=current_file, workspace_root=workspace_root)
        if item.alias and module_target:
            aliases[item.alias] = module_target
        module_root = item.module.strip(".").split(".", 1)[0]
        if module_root and module_target:
            aliases.setdefault(module_root, module_target)
        for name in item.names:
            resolved = _resolve_import_target(
                _join_module_name(item.module, name),
                current_file=current_file,
                workspace_root=workspace_root,
            )
            if not resolved:
                resolved = module_target
            if resolved:
                aliases.setdefault(name, resolved)
    return aliases


def _resolve_named_import(
    module: str,
    names: list[str],
    *,
    current_file: Path,
    workspace_root: Path,
) -> str:
    for name in names[:4]:
        resolved = _resolve_import_target(
            _join_module_name(module, name),
            current_file=current_file,
            workspace_root=workspace_root,
        )
        if resolved:
            return resolved
    return ""


def _resolve_import_target(module: str, *, current_file: Path, workspace_root: Path) -> str:
    module = module.strip()
    if not module:
        return ""
    if module.startswith("."):
        return _resolve_relative_import(module, current_file=current_file, workspace_root=workspace_root)
    return _resolve_absolute_import(module, workspace_root=workspace_root)


def _resolve_relative_import(module: str, *, current_file: Path, workspace_root: Path) -> str:
    dot_count = len(module) - len(module.lstrip("."))
    target_dir = current_file.parent
    for _ in range(max(0, dot_count - 1)):
        target_dir = target_dir.parent
        if not _within_root(target_dir, workspace_root):
            return ""
    suffix = module[dot_count:]
    if not suffix:
        return _existing_module_path(target_dir, workspace_root)
    return _existing_module_path(target_dir.joinpath(*suffix.split(".")), workspace_root)


def _resolve_absolute_import(module: str, *, workspace_root: Path) -> str:
    parts = [part for part in module.split(".") if part]
    if not parts:
        return ""
    roots = [workspace_root, *(workspace_root / prefix for prefix in COMMON_SOURCE_PREFIXES)]
    for root in roots:
        resolved = _existing_module_path(root.joinpath(*parts), workspace_root)
        if resolved:
            return resolved
    return ""


def _existing_module_path(base: Path, workspace_root: Path) -> str:
    candidates = [base.with_suffix(".py"), base / "__init__.py"]
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            continue
        if not _within_root(resolved, workspace_root):
            continue
        if resolved.is_file():
            return resolved.relative_to(workspace_root).as_posix()
    return ""


def _within_root(path: Path, workspace_root: Path) -> bool:
    try:
        path.expanduser().resolve().relative_to(workspace_root.expanduser().resolve())
        return True
    except (OSError, ValueError):
        return False


def _join_module_name(module: str, name: str) -> str:
    if not name:
        return module
    if module in {"", "."}:
        return f".{name}"
    return f"{module}.{name}"


def _import_display_target(item: SourceImport) -> str:
    if item.names:
        names = ",".join(item.names[:4])
        return f"{item.module}:{names}" if item.module else names
    return item.module


def _dedupe_edges(edges: list[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[tuple[object, object, object, object]] = set()
    deduped: list[dict[str, object]] = []
    for edge in edges:
        key = (edge.get("kind"), edge.get("target"), edge.get("resolved_target"), edge.get("line"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(edge)
    return deduped
