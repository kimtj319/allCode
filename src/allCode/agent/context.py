"""Context bundle construction from workspace and memory sources."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from allCode.agent.context_file_sections import (
    recent_file_sections as build_recent_file_sections,
)
from allCode.agent.context_file_sections import resolve_recent_file as resolve_context_recent_file
from allCode.agent.context_file_sections import workspace_sections as build_workspace_sections
from allCode.agent.context_session_sections import compact_answer_summary
from allCode.agent.context_session_sections import document_context_lines as build_document_context_lines
from allCode.agent.context_session_sections import document_followup_prompt as matches_document_followup_prompt
from allCode.agent.context_session_sections import extract_session_note
from allCode.agent.context_session_sections import followup_manifest_target as resolve_followup_manifest_target
from allCode.agent.context_session_sections import session_note_sections as build_session_note_sections
from allCode.agent.context_session_sections import target_exists as context_target_exists
from allCode.core.models import CoreModel, TurnInput
from allCode.core.result import DocumentManifest, ProjectManifest
from allCode.agent.session_state import AgentSessionState
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
        session_state: AgentSessionState | None = None,
        max_active_file_bytes: int = 64 * 1024,
    ) -> None:
        self.memory_selector = memory_selector
        self.path_resolver = path_resolver
        self.workspace_index = workspace_index
        self.recent_targets = recent_targets or RecentTargetMemory()
        self.compactor = compactor or ContextCompactor()
        self.session_state = session_state or AgentSessionState()
        self.max_active_file_bytes = max_active_file_bytes
        self._session_notes: dict[str, list[str]] = {}
        self._recent_prompts: dict[str, list[str]] = {}
        self._assistant_summaries: dict[str, list[str]] = {}
        self._project_manifests: list[ProjectManifest] = []
        self._document_manifests: list[DocumentManifest] = []
        # session_start hook output, captured once per process and injected into
        # every turn of that session as session-wide context.
        self._session_start_context: dict[str, str] = {}

    def session_start_done(self, session_id: str) -> bool:
        return session_id in self._session_start_context

    def set_session_start_context(self, session_id: str, text: str) -> None:
        self._session_start_context[session_id] = text or ""

    def session_start_context(self, session_id: str) -> str:
        return self._session_start_context.get(session_id, "")

    async def build(self, turn_input: TurnInput) -> ContextBundle:
        memory_sections = await self.memory_selector.select(turn_input)
        project_sections = self._project_state_sections()
        recent_file_sections = self._recent_file_sections(turn_input)
        session_sections = self._session_note_sections(turn_input)
        workspace_sections = self._workspace_sections(turn_input)
        sections = self.compactor.fit(
            [*project_sections, *recent_file_sections, *workspace_sections, *session_sections, *memory_sections]
        )
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

    def remember_project_manifest(self, manifest: ProjectManifest, *, turn_id: str) -> None:
        if not manifest.project_root:
            return
        self._project_manifests = [
            existing
            for existing in self._project_manifests
            if existing.project_root != manifest.project_root
        ]
        self._project_manifests.append(manifest)
        for target in manifest.candidate_targets()[:12]:
            self.remember_target(target, turn_id=turn_id, summary="project manifest target")

    def remember_document_manifest(self, manifest: DocumentManifest, *, turn_id: str) -> None:
        if not manifest.path:
            return
        updated = manifest.model_copy(update={"updated_at_turn_id": turn_id})
        self._document_manifests = [
            existing
            for existing in self._document_manifests
            if existing.path != updated.path
        ]
        self._document_manifests.append(updated)
        self.remember_target(updated.path, turn_id=turn_id, summary="document manifest target")

    def manifest_recent_paths(self) -> list[str]:
        paths: list[str] = []
        for manifest in reversed(self._project_manifests):
            for target in manifest.candidate_targets():
                if target and target not in paths:
                    paths.append(target)
        for manifest in reversed(self._document_manifests):
            for target in manifest.candidate_targets():
                if target and target not in paths:
                    paths.append(target)
        return paths

    def followup_manifest_target(self, prompt: str, *, workspace_root: str) -> str | None:
        return resolve_followup_manifest_target(
            prompt,
            workspace_root=workspace_root,
            project_manifests=self._project_manifests,
            document_manifests=self._document_manifests,
        )

    def remember_user_note(self, session_id: str, prompt: str) -> None:
        note = self.extract_user_note(prompt)
        if note is None:
            return
        notes = self._session_notes.setdefault(session_id, [])
        if note not in notes:
            notes.append(note)

    def remember_user_prompt(self, session_id: str, prompt: str) -> None:
        # Keep a compact record of recent user turns so the next turn's context
        # carries the actual back-and-forth (not just answer summaries). This is
        # what lets follow-ups like "그 두 번째 방법 더 설명해줘" resolve.
        compact = " ".join(str(prompt or "").split())
        if not compact:
            return
        prompts = self._recent_prompts.setdefault(session_id, [])
        snippet = compact[:240]
        if prompts and prompts[-1] == snippet:
            return
        prompts.append(snippet)
        del prompts[:-8]

    def remember_assistant_summary(self, session_id: str, answer: str) -> None:
        summary = self._compact_answer_summary(answer)
        if summary is None:
            return
        summaries = self._assistant_summaries.setdefault(session_id, [])
        if summary not in summaries:
            summaries.append(summary)

    def extract_user_note(self, prompt: str) -> str | None:
        return self._extract_session_note(prompt)

    def compact_session(self, session_id: str) -> str:
        """Fold the verbose recent conversation (prompts + assistant summaries)
        into a single compact session note and clear the verbose lists, so the
        next turn carries less context. Returns a short human-readable status."""

        prompts = self._recent_prompts.get(session_id, [])
        summaries = self._assistant_summaries.get(session_id, [])
        folded = len(prompts) + len(summaries)
        if folded == 0:
            return "압축할 대화 컨텍스트가 없습니다."
        lines: list[str] = []
        for prompt in prompts[-6:]:
            lines.append(f"사용자: {prompt[:120]}")
        for summary in summaries[-6:]:
            lines.append(f"어시스턴트: {summary[:160]}")
        note = "이전 대화 요약 — " + " / ".join(lines)
        notes = self._session_notes.setdefault(session_id, [])
        notes.append(note[:1200])
        del notes[:-4]
        self._recent_prompts[session_id] = []
        self._assistant_summaries[session_id] = []
        return f"대화 컨텍스트를 압축했습니다 ({folded}건 → 요약 1건)."

    def _session_note_sections(self, turn_input: TurnInput) -> list[ContextSection]:
        return build_session_note_sections(
            session_id=turn_input.session_id,
            session_notes=self._session_notes,
            assistant_summaries=self._assistant_summaries,
            recent_prompts=self._recent_prompts,
            document_manifests=self._document_manifests,
        )

    def _project_state_sections(self) -> list[ContextSection]:
        sections: list[ContextSection] = []
        repair = self.session_state.latest_repair_context
        if repair is not None:
            content = repair.render()
            if content:
                sections.append(
                    ContextSection(
                        name="repair_context",
                        priority=130,
                        token_estimate=estimate_tokens(content),
                        content=content,
                        source="session_repair_context",
                        section_type="repair_context",
                    )
                )
        obligations = self.session_state.active_project_obligations
        if obligations is not None:
            content = obligations.render()
            if content:
                sections.append(
                    ContextSection(
                        name="active_project_obligations",
                        priority=125,
                        token_estimate=estimate_tokens(content),
                        content=content,
                        source="session_project_obligations",
                        section_type="project_obligations",
                    )
                )
        source_ledger = self.session_state.source_exploration_ledger
        if source_ledger is not None:
            content = source_ledger.render()
            if content:
                sections.append(
                    ContextSection(
                        name="source_exploration_ledger",
                        priority=118,
                        token_estimate=estimate_tokens(content),
                        content=content,
                        source="session_source_exploration_ledger",
                        section_type="source_exploration_ledger",
                    )
                )
        return sections

    def _recent_file_sections(self, turn_input: TurnInput) -> list[ContextSection]:
        recent_paths = [
            *self.manifest_recent_paths(),
            *self.recent_targets.recent_paths(),
        ]
        return build_recent_file_sections(turn_input, recent_paths=recent_paths)

    def _extract_session_note(self, prompt: str) -> str | None:
        return extract_session_note(prompt)

    def _compact_answer_summary(self, answer: str) -> str | None:
        return compact_answer_summary(answer)

    @staticmethod
    def _target_exists(workspace_root: str, target: str) -> bool:
        return context_target_exists(workspace_root, target)

    @staticmethod
    def _resolve_recent_file(raw_path: str, *, workspace_root: Path) -> Path | None:
        return resolve_context_recent_file(raw_path, workspace_root=workspace_root)

    @staticmethod
    def _document_followup_prompt(lowered_prompt: str) -> bool:
        return matches_document_followup_prompt(lowered_prompt)

    def _document_context_lines(self) -> list[str]:
        return build_document_context_lines(self._document_manifests)

    def _workspace_sections(self, turn_input: TurnInput) -> list[ContextSection]:
        return build_workspace_sections(
            turn_input,
            path_resolver=self.path_resolver,
            workspace_index=self.workspace_index,
            recent_paths=self.recent_targets.recent_paths(),
            max_active_file_bytes=self.max_active_file_bytes,
        )
