"""Recent target memory for follow-up references."""

from __future__ import annotations

from pathlib import Path

from allCode.core.path_patterns import extract_prompt_path, is_followup_reference
from allCode.memory.schema import RecentTarget


class RecentTargetMemory:
    def __init__(self, *, max_targets: int = 20, storage_path: Path | None = None) -> None:
        self.max_targets = max_targets
        self.storage_path = storage_path
        self.targets: list[RecentTarget] = []
        if storage_path is not None and storage_path.exists():
            self.targets = [RecentTarget.model_validate_json(line) for line in storage_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def remember(self, target: RecentTarget) -> None:
        self.targets = [existing for existing in self.targets if not (existing.path == target.path and existing.symbol == target.symbol)]
        self.targets.append(target)
        self.targets = self.targets[-self.max_targets :]
        if self.storage_path is not None:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            self.storage_path.write_text("\n".join(item.model_dump_json() for item in self.targets) + "\n", encoding="utf-8")

    def resolve(self, prompt: str, *, workspace_candidates: list[str]) -> list[RecentTarget]:
        explicit = self._explicit_path(prompt)
        if explicit:
            exact = [target for target in self.targets if target.path == explicit]
            if exact:
                return exact[-1:]
            if _basename_only(explicit):
                basename_matches = [target for target in self.targets if Path(target.path).name == Path(explicit).name]
                if basename_matches:
                    return list(reversed(basename_matches))
            candidates = [path for path in workspace_candidates if path == explicit or Path(path).name == Path(explicit).name]
            return [RecentTarget(path=path, target_type="file", turn_id="workspace", summary="workspace candidate") for path in candidates]
        if self._is_followup(prompt) and self.targets:
            return self.targets[-1:]
        matches = []
        lowered = prompt.lower()
        for target in reversed(self.targets[-5:]):
            if Path(target.path).name.lower() in lowered or (target.symbol and target.symbol.lower() in lowered):
                matches.append(target)
        if matches:
            return matches
        return [
            RecentTarget(path=path, target_type="file", turn_id="workspace", summary="workspace candidate")
            for path in workspace_candidates
            if Path(path).name.lower() in lowered
        ]

    def recent_paths(self) -> list[str]:
        return [target.path for target in reversed(self.targets)]

    def _explicit_path(self, prompt: str) -> str | None:
        return extract_prompt_path(prompt)

    def _is_followup(self, prompt: str) -> bool:
        return is_followup_reference(prompt)


def _basename_only(path: str) -> bool:
    cleaned = path.replace("\\", "/")
    return "/" not in cleaned
