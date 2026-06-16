"""Per-turn file checkpoints for /rewind.

Before a turn mutates a file, its current content (or absence) is snapshotted
into a numbered checkpoint under ``.allCode/checkpoints``. ``/rewind`` restores
the most recent checkpoint — reverting that turn's file changes without relying
on git. Repeated rewinds step further back.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


class CheckpointStore:
    def __init__(self, project_root: Path | str) -> None:
        self.root = Path(project_root).expanduser().resolve()
        self.dir = self.root / ".allCode" / "checkpoints"
        self._current: Path | None = None
        self._recorded: set[str] = set()

    def begin_turn(self) -> None:
        """Start a fresh (lazily-created) checkpoint group for this turn."""
        self._current = None
        self._recorded = set()

    def _ensure_current(self) -> Path:
        if self._current is not None:
            return self._current
        self.dir.mkdir(parents=True, exist_ok=True)
        existing = [int(p.name[3:]) for p in self.dir.glob("cp_*") if p.name[3:].isdigit()]
        seq = (max(existing) + 1) if existing else 1
        current = self.dir / f"cp_{seq:06d}"
        (current / "files").mkdir(parents=True, exist_ok=True)
        self._current = current
        self._prune(keep=20)
        return current

    def snapshot(self, abs_path: Path | str) -> None:
        path = Path(abs_path).expanduser().resolve()
        key = str(path)
        if key in self._recorded:
            return
        try:
            rel = str(path.relative_to(self.root))
        except ValueError:
            return  # outside the workspace; do not checkpoint
        self._recorded.add(key)
        current = self._ensure_current()
        existed = path.exists() and path.is_file()
        blob_name = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
        if existed:
            try:
                shutil.copy2(path, current / "files" / blob_name)
            except OSError:
                existed = False
        meta_path = current / "meta.json"
        entries = []
        if meta_path.exists():
            try:
                entries = json.loads(meta_path.read_text(encoding="utf-8"))
            except ValueError:
                entries = []
        entries.append({"rel": rel, "existed": existed, "blob": blob_name})
        meta_path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")

    def has_checkpoints(self) -> bool:
        return bool(self._latest_with_meta())

    def restore_latest(self) -> str:
        latest = self._latest_with_meta()
        if latest is None:
            return "되돌릴 체크포인트가 없습니다."
        try:
            entries = json.loads((latest / "meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return "체크포인트를 읽을 수 없습니다."
        restored = 0
        deleted = 0
        for entry in entries:
            target = self.root / entry["rel"]
            if entry.get("existed"):
                blob = latest / "files" / entry["blob"]
                if blob.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(blob, target)
                    restored += 1
            else:
                if target.exists():
                    target.unlink()
                    deleted += 1
        shutil.rmtree(latest, ignore_errors=True)
        return f"마지막 변경을 되돌렸습니다 (복원 {restored}개 파일, 삭제 {deleted}개)."

    def _latest_with_meta(self) -> Path | None:
        if not self.dir.exists():
            return None
        groups = sorted(
            (p for p in self.dir.glob("cp_*") if (p / "meta.json").exists()),
            key=lambda p: p.name,
        )
        return groups[-1] if groups else None

    def _prune(self, *, keep: int) -> None:
        groups = sorted(p for p in self.dir.glob("cp_*") if p.is_dir())
        for stale in groups[:-keep]:
            shutil.rmtree(stale, ignore_errors=True)
