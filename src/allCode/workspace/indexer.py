"""Lightweight workspace file indexer."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import Field

from allCode.core.models import CoreModel
from allCode.workspace.roots import WorkspaceRoots

DEFAULT_IGNORE_DIRS = {
    # version control
    ".git", ".hg", ".svn",
    # python envs / build / packaging
    ".venv", "venv", "__pycache__", "dist", "build", "target", ".eggs", ".tox",
    # tooling caches
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache", "htmlcov", ".coverage",
    # editors / js
    ".idea", ".vscode", "node_modules", ".next", ".nuxt",
    # this agent's own runtime state (config/sessions/memory inbox); not project source
    ".allCode", ".allcode",
}
SOURCE_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".java", ".go", ".rs", ".md", ".toml", ".yaml", ".yml", ".json"}
# Executable code (as opposed to docs/config/data); used to focus architecture
# analysis on actual source rather than markdown/config/generated data files.
CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs",
    ".java", ".kt", ".go", ".rs", ".rb", ".php", ".cs",
    ".c", ".cc", ".cpp", ".h", ".hpp", ".swift", ".scala", ".sh",
}


class FileRecord(CoreModel):
    path: str
    root: str
    relative_path: str
    size: int
    mtime: float
    content_hash: str
    binary: bool = False
    language: str | None = None


class WorkspaceIndex(CoreModel):
    files: list[FileRecord] = Field(default_factory=list)
    skipped: int = 0
    truncated: bool = False

    def source_files(self) -> list[FileRecord]:
        return [record for record in self.files if not record.binary and Path(record.path).suffix in SOURCE_EXTENSIONS]

    def paths(self) -> list[str]:
        return [record.relative_path for record in self.files]


class WorkspaceIndexer:
    def __init__(
        self,
        *,
        ignore_dirs: set[str] | None = None,
        max_files: int = 20_000,
        max_read_size: int = 256 * 1024,
        cache_path: Path | str | None = None,
    ) -> None:
        self.ignore_dirs = ignore_dirs or DEFAULT_IGNORE_DIRS
        self.max_files = max_files
        self.max_read_size = max_read_size
        self.cache_path = Path(cache_path) if cache_path else None
        self._cache: dict[str, FileRecord] = {}

    def build(self, roots: WorkspaceRoots) -> WorkspaceIndex:
        # Persisted hash cache: unchanged files (same path:mtime:size) skip the
        # expensive content read+hash on every launch.
        self._load_cache()
        used: dict[str, FileRecord] = {}
        records: list[FileRecord] = []
        skipped = 0
        for root in roots.roots:
            root_path = root.resolved
            if not root_path.exists():
                skipped += 1
                continue
            iterator = [root_path] if root_path.is_file() else root_path.rglob("*")
            for path in iterator:
                if len(records) >= self.max_files:
                    self._save_cache(used)
                    return WorkspaceIndex(files=records, skipped=skipped, truncated=True)
                if self._ignored(path):
                    continue
                if not path.is_file():
                    continue
                record = self._record(path, root_path)
                records.append(record)
                used[f"{record.path}:{record.mtime}:{record.size}"] = record
        self._save_cache(used)
        return WorkspaceIndex(files=records, skipped=skipped, truncated=False)

    def update_file(self, index: WorkspaceIndex, path: Path, root: Path) -> WorkspaceIndex:
        resolved = path.expanduser().resolve()
        records = [record for record in index.files if Path(record.path) != resolved]
        if resolved.exists() and resolved.is_file() and not self._ignored(resolved):
            records.append(self._record(resolved, root.expanduser().resolve()))
        return WorkspaceIndex(files=records, skipped=index.skipped, truncated=index.truncated)

    def _record(self, path: Path, root: Path) -> FileRecord:
        stat = path.stat()
        cache_key = f"{path}:{stat.st_mtime}:{stat.st_size}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        binary = self._is_binary(path, stat.st_size)
        content_hash = self._hash_metadata(path, stat.st_mtime, stat.st_size)
        if not binary and stat.st_size <= self.max_read_size:
            content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        record = FileRecord(
            path=str(path),
            root=str(root),
            relative_path=str(path.relative_to(root)),
            size=stat.st_size,
            mtime=stat.st_mtime,
            content_hash=content_hash,
            binary=binary,
            language=self._language(path),
        )
        self._cache[cache_key] = record
        return record

    def _ignored(self, path: Path) -> bool:
        return any(part in self.ignore_dirs for part in path.parts)

    def _is_binary(self, path: Path, size: int) -> bool:
        if size > self.max_read_size:
            return False
        try:
            with path.open("rb") as handle:
                chunk = handle.read(1024)
        except OSError:
            return True
        return b"\0" in chunk

    def _hash_metadata(self, path: Path, mtime: float, size: int) -> str:
        return hashlib.sha256(f"{path}:{mtime}:{size}".encode("utf-8")).hexdigest()

    def _load_cache(self) -> None:
        if not self.cache_path or not self.cache_path.exists():
            return
        try:
            raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        cache: dict[str, FileRecord] = {}
        for key, value in raw.items():
            try:
                cache[key] = FileRecord(**value)
            except (TypeError, ValueError):
                continue
        self._cache = cache

    def _save_cache(self, used: dict[str, FileRecord]) -> None:
        if not self.cache_path:
            return
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {key: record.model_dump(mode="json") for key, record in used.items()}
            self.cache_path.write_text(json.dumps(payload), encoding="utf-8")
        except OSError:
            return

    def _language(self, path: Path) -> str | None:
        suffix = path.suffix.lower()
        return {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".java": "java",
            ".go": "go",
            ".rs": "rust",
            ".md": "markdown",
        }.get(suffix)
