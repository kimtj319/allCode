"""Related-test discovery signals for validation-required mutations."""

from __future__ import annotations

from pathlib import Path

from allCode.core.result import CompletionEvidence

SOURCE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs"}
DISCOVERY_TOOLS = {"search_files", "glob_files", "list_tree", "source_overview"}


def related_test_discovery_needed(
    routing,
    evidence: CompletionEvidence,
    *,
    workspace_root: str | None = None,
) -> bool:
    if not getattr(routing, "requires_mutation", False) or not getattr(routing, "requires_validation", False):
        return False
    if evidence.validation_commands:
        return False
    source_paths = changed_source_paths(evidence)
    if not source_paths:
        return False
    if workspace_root:
        seed_existing_related_test_candidates(evidence, workspace_root=workspace_root)
    return evidence.related_test_discovery_count <= 0 and not evidence.related_test_candidates


def changed_source_paths(evidence: CompletionEvidence) -> list[str]:
    paths: list[str] = []
    for path in [*evidence.created_files, *evidence.changed_files]:
        normalized = normalize_path(path)
        if _looks_source_path(normalized) and not looks_test_path(normalized) and normalized not in paths:
            paths.append(normalized)
    return paths[:8]


def discovery_symbols(evidence: CompletionEvidence) -> list[str]:
    symbols: list[str] = []
    for value in [*evidence.feature_objectives, *evidence.public_api_expectations, *evidence.validation_failure_symbols]:
        token = _symbol_token(str(value))
        if token and token not in symbols:
            symbols.append(token)
    return symbols[:5]


def seed_existing_related_test_candidates(evidence: CompletionEvidence, *, workspace_root: str) -> list[str]:
    candidates: list[str] = []
    for source_path in changed_source_paths(evidence):
        for candidate in related_test_candidates_for_source(source_path, workspace_root=workspace_root):
            if candidate not in candidates:
                candidates.append(candidate)
            if candidate not in evidence.related_test_candidates:
                evidence.related_test_candidates.append(candidate)
    return candidates


def record_related_test_discovery(result, evidence: CompletionEvidence, *, workspace_root: str) -> None:
    if result.name not in DISCOVERY_TOOLS or not result.ok:
        return
    candidates = related_test_candidates_from_metadata(result.metadata, workspace_root=workspace_root)
    if result.name in DISCOVERY_TOOLS:
        evidence.related_test_discovery_count += 1
    for candidate in candidates:
        if candidate not in evidence.related_test_candidates:
            evidence.related_test_candidates.append(candidate)


def related_test_candidates_from_metadata(metadata: dict, *, workspace_root: str) -> list[str]:
    paths: list[str] = []
    for key in ("matches", "results", "entries", "representative_reads", "suggested_reads", "source_overview_paths"):
        for item in metadata.get(key, []):
            if isinstance(item, str):
                _append_test_candidate(paths, item, workspace_root=workspace_root)
            elif isinstance(item, dict):
                _append_test_candidate(paths, str(item.get("path") or ""), workspace_root=workspace_root)
    for role in metadata.get("package_roles", []):
        if isinstance(role, dict):
            _append_test_candidate(paths, str(role.get("path") or ""), workspace_root=workspace_root)
    return paths[:12]


def related_test_candidates_for_source(path: str, *, workspace_root: str) -> list[str]:
    normalized = normalize_path(path, workspace_root=workspace_root)
    if not normalized or looks_test_path(normalized) or not _looks_source_path(normalized):
        return []
    candidates = _candidate_paths_for_source(normalized)
    existing: list[str] = []
    root = Path(workspace_root).expanduser()
    for candidate in candidates:
        try:
            if (root / candidate).resolve().is_file() and candidate not in existing:
                existing.append(candidate)
        except OSError:
            continue
    return existing[:12]


def normalize_path(path: str, *, workspace_root: str | None = None) -> str:
    raw = str(path or "").strip().replace("\\", "/")
    if not raw:
        return ""
    candidate = Path(raw)
    if workspace_root and candidate.is_absolute():
        try:
            return candidate.expanduser().resolve().relative_to(Path(workspace_root).expanduser().resolve()).as_posix()
        except (OSError, ValueError):
            return candidate.as_posix()
    if candidate.is_absolute():
        parts = candidate.parts
        for anchor in ("src", "tests", "test"):
            if anchor in parts:
                return "/".join(parts[parts.index(anchor) :])
    return candidate.as_posix()


def looks_test_path(path: str) -> bool:
    lowered = path.lower().replace("\\", "/")
    name = Path(lowered).name
    return (
        lowered.startswith("tests/")
        or "/tests/" in lowered
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name.endswith(".test.ts")
        or name.endswith(".spec.ts")
        or name.endswith("_test.go")
        or name.endswith("_test.rs")
    )


def _append_test_candidate(paths: list[str], path: str, *, workspace_root: str) -> None:
    normalized = normalize_path(path, workspace_root=workspace_root)
    if normalized and looks_test_path(normalized) and normalized not in paths:
        paths.append(normalized)


def _looks_source_path(path: str) -> bool:
    return Path(path).suffix.lower() in SOURCE_SUFFIXES


def _symbol_token(value: str) -> str:
    cleaned = value.strip().strip("`'\"")
    if not cleaned:
        return ""
    for marker in ("export ", "provide attribute or method ", "accept keyword argument "):
        if cleaned.lower().startswith(marker):
            cleaned = cleaned[len(marker) :]
            break
    token = cleaned.split()[0].strip("`'\".,:;()")[:80]
    if not token or token.startswith("_") or token.startswith("__"):
        return ""
    return token


def _candidate_paths_for_source(path: str) -> list[str]:
    source = Path(path)
    suffix = source.suffix.lower()
    stem = source.stem
    directory = source.parent.as_posix()
    package = _package_path(source)
    candidates: list[str] = []
    if suffix == ".py":
        _append_unique(candidates, f"tests/test_{stem}.py")
        if package:
            _append_unique(candidates, f"tests/{package}/test_{stem}.py")
            _append_unique(candidates, f"tests/{package}/{stem}_test.py")
        _append_unique(candidates, f"{directory}/test_{stem}.py")
        _append_unique(candidates, f"{directory}/{stem}_test.py")
    elif suffix == ".go":
        _append_unique(candidates, f"{directory}/{stem}_test.go")
    elif suffix in {".js", ".jsx", ".ts", ".tsx"}:
        for test_suffix in _js_test_suffixes(suffix):
            _append_unique(candidates, f"{directory}/{stem}{test_suffix}")
            if package:
                _append_unique(candidates, f"tests/{package}/{stem}{test_suffix}")
            _append_unique(candidates, f"tests/{stem}{test_suffix}")
    elif suffix == ".rs":
        _append_unique(candidates, f"{directory}/{stem}_test.rs")
        _append_unique(candidates, f"tests/{stem}_test.rs")
    elif suffix == ".java":
        _append_unique(candidates, f"{directory}/{stem}Test.java")
        if package:
            _append_unique(candidates, f"tests/{package}/{stem}Test.java")
    return candidates


def _package_path(source: Path) -> str:
    parts = list(source.parent.parts)
    if "src" in parts:
        remaining = parts[parts.index("src") + 1 :]
        return "/".join(part for part in remaining if part)
    if parts and parts[0] not in {"", ".", "tests", "test"}:
        return "/".join(parts)
    return ""


def _js_test_suffixes(source_suffix: str) -> tuple[str, ...]:
    base = source_suffix if source_suffix in {".ts", ".tsx"} else ".js"
    return (f".test{base}", f".spec{base}")


def _append_unique(paths: list[str], path: str) -> None:
    normalized = path.replace("\\", "/").strip("/")
    if normalized and normalized not in paths:
        paths.append(normalized)
