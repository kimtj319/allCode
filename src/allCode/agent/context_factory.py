"""Runtime assembly for workspace and memory context dependencies."""

from __future__ import annotations

from pathlib import Path

from allCode.agent.context import ContextBuilder
from allCode.config.defaults import DEFAULT_CONFIG_DIR
from allCode.config.schema import AppConfig
from allCode.memory.compactor import ContextCompactor
from allCode.memory.recent_targets import RecentTargetMemory
from allCode.memory.repo_map import RepoMapBuilder
from allCode.memory.selector import ContextMemorySelector
from allCode.memory.session_summary import SessionSummary
from allCode.memory.store import MemoryStore
from allCode.workspace.indexer import WorkspaceIndexer
from allCode.workspace.path_resolver import PathResolver
from allCode.workspace.roots import WorkspaceRoots


def build_runtime_context_builder(config: AppConfig) -> ContextBuilder:
    """Build a fresh context builder from current workspace state."""

    root_path = Path(config.workspace.root).expanduser().resolve()
    roots = WorkspaceRoots.from_root(root_path, writable=config.workspace.sandbox_enabled)
    for extra_root in config.workspace.extra_roots:
        roots.add(extra_root, writable=False)

    workspace_index = WorkspaceIndexer().build(roots)
    recent_targets = RecentTargetMemory()
    compactor = ContextCompactor()
    store = MemoryStore(root_path, DEFAULT_CONFIG_DIR)
    selector = ContextMemorySelector(
        store=store,
        recent_targets=recent_targets,
        repo_map_builder=RepoMapBuilder(),
        session_summary=SessionSummary(root_path),
        workspace_index=workspace_index,
        compactor=compactor,
    )
    return ContextBuilder(
        memory_selector=selector,
        path_resolver=PathResolver(roots),
        workspace_index=workspace_index,
        recent_targets=recent_targets,
        compactor=compactor,
    )
