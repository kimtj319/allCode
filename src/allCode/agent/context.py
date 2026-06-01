"""Context bundle construction from workspace and memory sources."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from allCode.core.models import CoreModel, TurnInput
from allCode.memory.compactor import ContextCompactor
from allCode.memory.recent_targets import RecentTargetMemory
from allCode.memory.schema import ContextSection, RecentTarget, estimate_tokens
from allCode.memory.selector import ContextMemorySelector
from allCode.workspace.indexer import WorkspaceIndex
from allCode.workspace.path_resolver import PathResolver


class ContextBundle(CoreModel):
    sections: list[ContextSection] = Field(default_factory=list)

    def render(self) -> str:
        return "\n\n".join(f"## {section.name}\n{section.content}" for section in self.sections)

    def sources(self) -> list[str]:
        return [section.source for section in self.sections]


class ContextBuilder:
    def __init__(
        self,
        *,
        memory_selector: ContextMemorySelector,
        path_resolver: PathResolver,
        workspace_index: WorkspaceIndex,
        recent_targets: RecentTargetMemory | None = None,
        compactor: ContextCompactor | None = None,
        max_active_file_bytes: int = 64 * 1024,
    ) -> None:
        self.memory_selector = memory_selector
        self.path_resolver = path_resolver
        self.workspace_index = workspace_index
        self.recent_targets = recent_targets or RecentTargetMemory()
        self.compactor = compactor or ContextCompactor()
        self.max_active_file_bytes = max_active_file_bytes

    async def build(self, turn_input: TurnInput) -> ContextBundle:
        memory_sections = await self.memory_selector.select(turn_input)
        workspace_sections = self._workspace_sections(turn_input)
        sections = self.compactor.fit([*workspace_sections, *memory_sections])
        return ContextBundle(sections=sections)

    def remember_target(self, path: str, *, turn_id: str, summary: str = "", symbol: str | None = None) -> None:
        target_type = "function" if symbol else ("directory" if Path(path).is_dir() else "file")
        self.recent_targets.remember(
            RecentTarget(
                path=path,
                symbol=symbol,
                target_type=target_type,
                summary=summary,
                turn_id=turn_id,
            )
        )

    def _workspace_sections(self, turn_input: TurnInput) -> list[ContextSection]:
        resolution = self.path_resolver.resolve_for_read(
            turn_input.user_prompt,
            recent_paths=self.recent_targets.recent_paths(),
            workspace_candidates=self.workspace_index.paths(),
        )
        if resolution.resolved_path is None:
            return []
        path = Path(resolution.resolved_path)
        if not path.exists() or not path.is_file():
            return []
        try:
            file_size = path.stat().st_size
            with path.open("rb") as handle:
                raw = handle.read(self.max_active_file_bytes + 1)
        except OSError:
            return []
        if b"\0" in raw[:1024]:
            return []
        truncated = file_size > self.max_active_file_bytes or len(raw) > self.max_active_file_bytes
        content = raw[: self.max_active_file_bytes].decode("utf-8", errors="replace")
        section_content = content if not truncated else content + "\n[truncated]"
        return [
            ContextSection(
                name=f"active_file:{path.name}",
                priority=100,
                token_estimate=estimate_tokens(section_content),
                content=section_content,
                source=str(path),
                section_type="active_file",
            )
        ]
