"""Context memory selection for one turn."""

from __future__ import annotations

from pathlib import Path

from allCode.core.models import TurnInput
from allCode.memory.compactor import ContextCompactor
from allCode.memory.hierarchy import MemoryHierarchy
from allCode.memory.recent_targets import RecentTargetMemory
from allCode.memory.repo_map import RepoMapBuilder
from allCode.memory.schema import ContextSection, estimate_tokens
from allCode.memory.session_summary import SessionSummary
from allCode.memory.store import MemoryStore
from allCode.workspace.indexer import WorkspaceIndex


class ContextMemorySelector:
    def __init__(
        self,
        *,
        store: MemoryStore,
        hierarchy: MemoryHierarchy | None = None,
        recent_targets: RecentTargetMemory | None = None,
        repo_map_builder: RepoMapBuilder | None = None,
        session_summary: SessionSummary | None = None,
        workspace_index: WorkspaceIndex | None = None,
        compactor: ContextCompactor | None = None,
    ) -> None:
        self.store = store
        self.hierarchy = hierarchy or MemoryHierarchy()
        self.recent_targets = recent_targets or RecentTargetMemory()
        self.repo_map_builder = repo_map_builder
        self.session_summary = session_summary
        self.workspace_index = workspace_index
        self.compactor = compactor or ContextCompactor()

    async def select(self, turn_input: TurnInput) -> list[ContextSection]:
        cwd = Path(turn_input.workspace.root)
        active_items = await self.store.load_active_items(cwd=cwd)
        summary = await self.session_summary.load(turn_input.session_id) if self.session_summary is not None else ""
        recent = self.recent_targets.resolve(turn_input.user_prompt, workspace_candidates=self.workspace_index.paths() if self.workspace_index is not None else [])
        merged = self.hierarchy.merge(active_items, session_summary=summary, recent_targets=recent)
        sections = [
            ContextSection(
                name=f"memory:{item.kind}",
                priority=80 if item.kind == "constraint" else 45,
                token_estimate=estimate_tokens(item.text),
                content=item.text,
                source="memory",
                section_type="durable_memory",
            )
            for item in merged
            if item.approved
        ]
        if self.repo_map_builder is not None and self.workspace_index is not None:
            entries = self.repo_map_builder.build_entries(self.workspace_index)
            repo_text = self.repo_map_builder.compact_text(entries, prompt=turn_input.user_prompt, recent_targets=recent)
            if repo_text:
                sections.append(
                    ContextSection(
                        name="repo_map",
                        priority=55,
                        token_estimate=estimate_tokens(repo_text),
                        content=repo_text,
                        source="repo_map",
                        section_type="repo_map",
                    )
                )
        return self.compactor.fit(sections)
