"""Session and manifest context helpers for ``ContextBuilder``."""

from __future__ import annotations

import re
from pathlib import Path

from allCode.core.path_patterns import is_followup_reference
from allCode.core.result import DocumentManifest, ProjectManifest
from allCode.memory.redaction import redact_text
from allCode.memory.schema import ContextSection, estimate_tokens


def session_note_sections(
    *,
    session_id: str,
    session_notes: dict[str, list[str]],
    assistant_summaries: dict[str, list[str]],
    document_manifests: list[DocumentManifest],
) -> list[ContextSection]:
    notes = session_notes.get(session_id, [])
    assistant = assistant_summaries.get(session_id, [])
    documents = document_context_lines(document_manifests)
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


def followup_manifest_target(
    prompt: str,
    *,
    workspace_root: str,
    project_manifests: list[ProjectManifest],
    document_manifests: list[DocumentManifest],
) -> str | None:
    if not is_followup_reference(prompt):
        return None
    lowered = prompt.lower()
    if document_manifests and document_followup_prompt(lowered):
        for manifest in reversed(document_manifests):
            for target in manifest.candidate_targets():
                if target_exists(workspace_root, target):
                    return target
    if not project_manifests:
        return None
    for manifest in reversed(project_manifests):
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
            if target_exists(workspace_root, target):
                return target
    return None


def extract_session_note(prompt: str) -> str | None:
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


def compact_answer_summary(answer: str) -> str | None:
    compact = " ".join(answer.strip().split())
    if not compact:
        return None
    return redact_text(compact[:1200])


def target_exists(workspace_root: str, target: str) -> bool:
    path = Path(target)
    if not path.is_absolute():
        path = Path(workspace_root) / path
    try:
        return path.expanduser().resolve().exists()
    except OSError:
        return False


def document_followup_prompt(lowered_prompt: str) -> bool:
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


def document_context_lines(document_manifests: list[DocumentManifest]) -> list[str]:
    lines: list[str] = []
    for manifest in document_manifests[-5:]:
        headings = ", ".join(manifest.section_headings[:8])
        suffix = f" sections=[{headings}]" if headings else ""
        lines.append(f"- {manifest.title or Path(manifest.path).name}: {manifest.path}{suffix}")
    return lines

