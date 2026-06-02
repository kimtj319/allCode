"""Context bundle construction from workspace and memory sources."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import Field

from allCode.core.models import CoreModel, TurnInput
from allCode.core.path_patterns import is_followup_reference
from allCode.core.result import DocumentManifest, ProjectManifest
from allCode.agent.session_state import AgentSessionState
from allCode.memory.compactor import ContextCompactor
from allCode.memory.recent_targets import RecentTargetMemory
from allCode.memory.redaction import redact_text
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
        self._assistant_summaries: dict[str, list[str]] = {}
        self._project_manifests: list[ProjectManifest] = []
        self._document_manifests: list[DocumentManifest] = []

    async def build(self, turn_input: TurnInput) -> ContextBundle:
        memory_sections = await self.memory_selector.select(turn_input)
        session_sections = self._session_note_sections(turn_input)
        workspace_sections = self._workspace_sections(turn_input)
        sections = self.compactor.fit([*workspace_sections, *session_sections, *memory_sections])
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
        if not is_followup_reference(prompt):
            return None
        lowered = prompt.lower()
        if self._document_manifests and self._document_followup_prompt(lowered):
            for manifest in reversed(self._document_manifests):
                for target in manifest.candidate_targets():
                    if self._target_exists(workspace_root, target):
                        return target
        if not self._project_manifests:
            return None
        for manifest in reversed(self._project_manifests):
            candidates = manifest.candidate_targets()
            if any(marker in lowered for marker in ("test", "테스트")):
                for target in candidates:
                    if "test" in Path(target).name.lower() or "/test" in target.lower():
                        return target
            if any(marker in lowered for marker in ("cli", "command", "option", "명령", "옵션", "--")):
                for target in candidates:
                    name = Path(target).name.lower()
                    if name in {"main.py", "cli.py", "__main__.py"} or "cli" in name:
                        return target
            for target in candidates:
                if self._target_exists(workspace_root, target):
                    return target
        return None

    def remember_user_note(self, session_id: str, prompt: str) -> None:
        note = self.extract_user_note(prompt)
        if note is None:
            return
        notes = self._session_notes.setdefault(session_id, [])
        if note not in notes:
            notes.append(note)

    def remember_assistant_summary(self, session_id: str, answer: str) -> None:
        summary = self._compact_answer_summary(answer)
        if summary is None:
            return
        summaries = self._assistant_summaries.setdefault(session_id, [])
        if summary not in summaries:
            summaries.append(summary)

    def extract_user_note(self, prompt: str) -> str | None:
        return self._extract_session_note(prompt)

    def _session_note_sections(self, turn_input: TurnInput) -> list[ContextSection]:
        notes = self._session_notes.get(turn_input.session_id, [])
        assistant = self._assistant_summaries.get(turn_input.session_id, [])
        documents = self._document_context_lines()
        if not notes and not assistant and not documents:
            return []
        lines = [f"- {note}" for note in notes[-10:]]
        if assistant:
            lines.append("Recent assistant answer summaries:")
            lines.extend(f"- {item}" for item in assistant[-5:])
        if documents:
            lines.append("Recent document artifacts:")
            lines.extend(documents)
        content = "\n".join(lines)
        return [
            ContextSection(
                name="session_notes",
                priority=90,
                token_estimate=estimate_tokens(content),
                content=content,
                source="session_notes",
                section_type="session_summary",
            )
        ]

    def _extract_session_note(self, prompt: str) -> str | None:
        compact = " ".join(prompt.strip().split())
        if not compact:
            return None
        korean = re.search(
            r"앞으로\s*[\"'“”‘’]?(?P<alias>[^\"'“”‘’\s]+(?:\s+[^\"'“”‘’\s]+){0,3})[\"'“”‘’]?\s*(?:은|는)\s*(?P<target>[A-Za-z0-9_.:/-]+)",
            compact,
        )
        if korean:
            alias = korean.group("alias").strip()
            target = korean.group("target").strip().rstrip(".,")
            return redact_text(f"User-defined alias: {alias} = {target}")
        english = re.search(
            r"remember\s+(?:that\s+)?[\"']?(?P<alias>[A-Za-z0-9_ .-]{2,40})[\"']?\s+(?:means|is)\s+[\"']?(?P<target>[A-Za-z0-9_.:/-]+)",
            compact,
            re.IGNORECASE,
        )
        if english:
            alias = english.group("alias").strip()
            target = english.group("target").strip().rstrip(".,")
            return redact_text(f"User-defined alias: {alias} = {target}")
        return None

    def _compact_answer_summary(self, answer: str) -> str | None:
        compact = " ".join(answer.strip().split())
        if not compact:
            return None
        return redact_text(compact[:1200])

    @staticmethod
    def _target_exists(workspace_root: str, target: str) -> bool:
        path = Path(target)
        if not path.is_absolute():
            path = Path(workspace_root) / path
        try:
            return path.expanduser().resolve().exists()
        except OSError:
            return False

    @staticmethod
    def _document_followup_prompt(lowered_prompt: str) -> bool:
        compact = lowered_prompt.replace(" ", "")
        markers = (
            "document",
            "report",
            "brief",
            "plan",
            "playbook",
            "문서",
            "보고서",
            "기획서",
            "플레이북",
            "시리즈바이블",
            "앞문서",
            "방금만든문서",
        )
        return any(marker in lowered_prompt or marker in compact for marker in markers)

    def _document_context_lines(self) -> list[str]:
        lines: list[str] = []
        for manifest in self._document_manifests[-5:]:
            headings = ", ".join(manifest.section_headings[:8])
            suffix = f" sections=[{headings}]" if headings else ""
            lines.append(f"- {manifest.title or Path(manifest.path).name}: {manifest.path}{suffix}")
        return lines

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
            if file_size > 20_000:
                token_est = int(file_size / 4)
                line_count = self._count_lines(path)
                workspace_root = Path(turn_input.workspace.root).expanduser().resolve()
                try:
                    relative_path = path.relative_to(workspace_root)
                except ValueError:
                    relative_path = path.name
                section_content = (
                    f"[large file suppressed: {path.name}]\n"
                    f"- path: {relative_path}\n"
                    f"- size_bytes: {file_size}\n"
                    f"- estimated_tokens: {token_est}\n"
                    f"- line_count: {line_count}\n"
                    "- recommended_action: use search_files first, then read_file with start_line/end_line for the relevant range"
                )
                return [
                    ContextSection(
                        name=f"active_file:{path.name}",
                        priority=100,
                        token_estimate=estimate_tokens(section_content),
                        content=section_content,
                        source=str(path),
                        section_type="active_file_metadata",
                    )
                ]
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

    @staticmethod
    def _count_lines(path: Path) -> int:
        try:
            with path.open("rb") as handle:
                return sum(1 for _ in handle)
        except OSError:
            return 0
