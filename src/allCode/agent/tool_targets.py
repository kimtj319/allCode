"""Remember workspace targets observed through tool execution."""

from __future__ import annotations

from allCode.agent.context import ContextBuilder
from allCode.core.models import ToolResult, TurnState


class ToolTargetRecorder:
    def __init__(self, context_builder: ContextBuilder | None = None) -> None:
        self._context_builder = context_builder

    def record(self, state: TurnState, result: ToolResult) -> None:
        if not result.ok:
            return
        created = [str(path) for path in result.metadata.get("created_files", [])]
        changed = [str(path) for path in result.metadata.get("changed_files", [])]
        file_path = result.metadata.get("file_path")
        if isinstance(file_path, str):
            self._remember(file_path, turn_id=state.turn_id, summary=f"{result.name} target")
        for path in created:
            if path not in state.created_files:
                state.created_files.append(path)
            self._remember(path, turn_id=state.turn_id, summary="created file")
        for path in changed:
            if path not in state.modified_files:
                state.modified_files.append(path)
            self._remember(path, turn_id=state.turn_id, summary="changed file")

    def _remember(self, path: str, *, turn_id: str, summary: str) -> None:
        if self._context_builder is None:
            return
        self._context_builder.remember_target(path, turn_id=turn_id, summary=summary)
